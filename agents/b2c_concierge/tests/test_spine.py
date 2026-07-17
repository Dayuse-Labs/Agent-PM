"""Spine tests over a real ADK runner — offline, LLM and leaves mocked.

Locks the S2 structural invariants:
- a simple search turn stays within the <= 3 LLM calls/turn budget (THE test
  required by the phase — it fails if a 4th call ever slips in);
- an ack turn costs ZERO LLM calls;
- honest degradation on leaf failure (no synthesis, no invention);
- inline stub turns answer via template (triage only);
- logs and metrics never carry message content (GDPR).
"""
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

import b2c_concierge.agent as agent_module
from b2c_concierge import templates
from b2c_concierge.agent import root_agent
from b2c_concierge.budget import MAX_LLM_CALLS_PER_TURN

USER_MESSAGE_SEARCH = "je cherche un hôtel à Paris demain"


def _llm_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class ScriptedLlm:
    """Queue of canned litellm outcomes (str → response, Exception → raise).
    Any call beyond the plan fails the test: that IS the budget leash."""

    def __init__(self, *plan):
        self.plan = list(plan)
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if not self.plan:
            raise AssertionError("unexpected extra LLM call (budget breach)")
        item = self.plan.pop(0)
        if isinstance(item, Exception):
            raise item
        return _llm_response(item)


@pytest.fixture
def scripted(monkeypatch):
    """Installs a scripted LLM + a fake leaf leg; returns (llm, leaf_calls)."""

    def _install(*plan, leaf_text="LEAF OUTCOME"):
        llm = ScriptedLlm(*plan)
        # Both triage and synthesis resolve litellm.acompletion at call time on
        # the shared module object — one patch covers both call sites.
        monkeypatch.setattr(agent_module.litellm, "acompletion", llm)
        leaf_calls: list[str] = []

        async def fake_run_leaf(leaf, ctx, profile_in):
            leaf_calls.append(leaf)
            return leaf_text, {}

        monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
        return llm, leaf_calls

    return _install


def _drive(message: str) -> str:
    """One turn through a real InMemoryRunner; returns the final answer text."""
    runner = InMemoryRunner(root_agent)

    async def go():
        session = await runner.session_service.create_session(
            app_name=runner.app_name, user_id="u"
        )
        content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
        return [
            event
            async for event in runner.run_async(
                user_id="u", session_id=session.id, new_message=content
            )
        ]

    events = asyncio.run(go())
    texts = [
        part.text
        for event in events
        if event.content and event.content.parts
        for part in event.content.parts
        if part.text
    ]
    return "\n".join(texts).strip()


def _turn_metric(caplog) -> dict:
    line = next(
        record.getMessage()
        for record in caplog.records
        if "concierge_metric=turn" in record.getMessage()
    )
    return dict(kv.split("=", 1) for kv in line.split() if "=" in kv)


class TestBudget:
    def test_simple_search_turn_stays_within_llm_budget(self, scripted, caplog):
        llm, leaf_calls = scripted(
            '{"family": "search", "language": "fr"}',
            "Voici 2 hôtels à Paris pour demain.",
            leaf_text="results: hotel A, hotel B",
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive(USER_MESSAGE_SEARCH)
        assert answer == "Voici 2 hôtels à Paris pour demain."
        assert leaf_calls == ["hotel_search"]
        metric = _turn_metric(caplog)
        # THE phase invariant: a simple turn must never exceed 3 LLM calls.
        assert int(metric["llm_calls"]) <= MAX_LLM_CALLS_PER_TURN
        assert metric["llm_calls"] == "3"  # triage + leaf slot + synthesis
        assert metric["phases"] == "triage,leaf_llm,synthesis"

    def test_ack_turn_costs_zero_llm(self, scripted, caplog):
        llm, leaf_calls = scripted()  # empty plan: ANY llm call fails the test
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive("Bonjour !")
        assert answer == templates.ack_response("fr")
        assert llm.calls == []
        assert leaf_calls == []
        assert _turn_metric(caplog)["llm_calls"] == "0"

    def test_inline_stub_turn_is_triage_only(self, scripted, caplog):
        llm, leaf_calls = scripted('{"family": "details", "language": "fr"}')
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive("quels équipements a cet hôtel ?")
        assert answer == templates.stub_response("get_hotel_details", "fr")
        assert len(llm.calls) == 1
        assert leaf_calls == []
        metric = _turn_metric(caplog)
        assert metric["llm_calls"] == "1"
        assert metric["route"] == "inline:get_hotel_details"


class TestRoutingThroughTheSpine:
    def test_faq_turn_routes_to_the_faq_leaf(self, scripted):
        llm, leaf_calls = scripted(
            '{"family": "faq", "language": "fr"}',
            "Vous pouvez annuler gratuitement jusqu'à l'heure d'arrivée.",
            leaf_text="conditions: free cancellation until check-in",
        )
        answer = _drive("quelles sont les conditions d'annulation ?")
        assert leaf_calls == ["faq"]
        assert answer == "Vous pouvez annuler gratuitement jusqu'à l'heure d'arrivée."

    def test_triage_llm_failure_still_routes_via_regex(self, scripted):
        llm, leaf_calls = scripted(
            TimeoutError("triage down"),
            "Voici ce que j'ai trouvé.",
            leaf_text="results: hotel C",
        )
        answer = _drive("je cherche un hôtel à Lyon")
        assert leaf_calls == ["hotel_search"]  # regex fallback family
        assert answer == "Voici ce que j'ai trouvé."


class TestHonestDegradation:
    def test_leaf_failure_degrades_honestly_without_synthesis(self, scripted, caplog, monkeypatch):
        llm, _ = scripted('{"family": "search", "language": "fr"}')

        async def dead_leaf(leaf, ctx, profile_in):
            return None, {}

        monkeypatch.setattr(agent_module, "_run_leaf", dead_leaf)
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive(USER_MESSAGE_SEARCH)
        assert answer == templates.leaf_degraded_response("search", "fr")
        assert len(llm.calls) == 1  # triage only: no synthesis over nothing
        assert _turn_metric(caplog)["status"] == "degraded"

    def test_synthesis_failure_serves_leaf_text_verbatim(self, scripted, caplog):
        llm, leaf_calls = scripted(
            '{"family": "search", "language": "fr"}',
            TimeoutError("synthesis down"),
            leaf_text="GROUNDED LEAF TEXT",
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive(USER_MESSAGE_SEARCH)
        assert answer == "GROUNDED LEAF TEXT"
        assert _turn_metric(caplog)["status"] == "synthesis_fallback"


class TestGdprMetricEvents:
    def test_metric_events_never_contain_message_content(self, scripted, monkeypatch):
        """S3 lock: every llm_metric_events row the spine emits carries counters
        and labels only — never the user message (GDPR invariant)."""
        import b2c_concierge.triage as triage_module

        events: list[dict] = []

        def capture(event_type, service, invocation_id, **fields):
            events.append({"event_type": event_type, "service": service, **fields})

        monkeypatch.setattr(agent_module, "enqueue_metric_event", capture)
        monkeypatch.setattr(triage_module, "enqueue_metric_event", capture)
        scripted(
            '{"family": "search", "language": "fr"}',
            "Réponse synthétisée.",
            leaf_text="results: hotel A",
        )
        _drive(USER_MESSAGE_SEARCH)
        assert {e["event_type"] for e in events} >= {"llm_call", "turn"}
        assert all(e["service"] == "b2c_concierge" for e in events)
        blob = json.dumps(events, ensure_ascii=False)
        assert "Paris" not in blob
        assert USER_MESSAGE_SEARCH not in blob


class TestGdprLogs:
    def test_logs_never_contain_message_content(self, scripted, caplog):
        llm, _ = scripted(
            '{"family": "search", "language": "fr"}',
            "Réponse synthétisée.",
            leaf_text="results: hotel A",
        )
        with caplog.at_level(logging.DEBUG):
            _drive(USER_MESSAGE_SEARCH)
        own_records = [
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("b2c_concierge")
        ]
        assert own_records, "the turn metric line must exist"
        for message in own_records:
            assert "Paris" not in message
            assert USER_MESSAGE_SEARCH not in message
