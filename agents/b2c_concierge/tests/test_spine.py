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
from b2c_concierge.profile import SessionProfile

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

    def _install(*plan, leaf_text="LEAF OUTCOME", response=None):
        llm = ScriptedLlm(*plan)
        # Both triage and synthesis resolve litellm.acompletion at call time on
        # the shared module object — one patch covers both call sites.
        monkeypatch.setattr(agent_module.litellm, "acompletion", llm)
        leaf_calls: list[str] = []

        async def fake_run_leaf(leaf, ctx, profile_in):
            leaf_calls.append(leaf)
            return leaf_text, dict(response or {})

        monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
        return llm, leaf_calls

    return _install


def _marker_payloads(events) -> list[dict]:
    """The decoded `{"event": ...}` payload of every partial marker event, in
    order — progress/hotels use the \\x1f (Unit Separator) prefix; plain
    streamed answer chunks (also partial) do not and are excluded."""
    payloads = []
    for event in events:
        if not event.partial or not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.text and part.text.startswith(agent_module._US):
                payloads.append(json.loads(part.text[len(agent_module._US):]))
    return payloads


def _stream_chunks(events) -> list[str]:
    """Plain streamed-answer partial chunks (progress/hotels markers excluded)."""
    chunks = []
    for event in events:
        if not event.partial or not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.text and not part.text.startswith(agent_module._US):
                chunks.append(part.text)
    return chunks


def _marker_index(events, kind: str) -> int:
    for i, event in enumerate(events):
        if not event.partial or not event.content or not event.content.parts:
            continue
        text = event.content.parts[0].text or ""
        if text.startswith(agent_module._US) and json.loads(text[len(agent_module._US):]).get("event") == kind:
            return i
    raise AssertionError(f"no {kind!r} marker event found")


def _final_index(events) -> int:
    for i, event in enumerate(events):
        if not event.partial:
            return i
    raise AssertionError("no final (non-partial) event found")


def _new_session():
    runner = InMemoryRunner(root_agent)

    async def go():
        return await runner.session_service.create_session(app_name=runner.app_name, user_id="u")

    return runner, asyncio.run(go())


def _drive_in(runner, session_id, message: str) -> list:
    async def go():
        content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
        return [
            event
            async for event in runner.run_async(user_id="u", session_id=session_id, new_message=content)
        ]

    return asyncio.run(go())


def _answer(events) -> str:
    texts = [
        part.text
        for event in events
        if not event.partial and event.content and event.content.parts
        for part in event.content.parts
        if part.text
    ]
    return "\n".join(texts).strip()


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
    # S06: progress/hotels markers and streamed synthesis chunks are all
    # `partial=True` (never appended to the session — see agent.py's
    # `_marker_event`); the answer is the ONE terminal non-partial event.
    texts = [
        part.text
        for event in events
        if not event.partial and event.content and event.content.parts
        for part in event.content.parts
        if part.text
    ]
    return "\n".join(texts).strip()


def _drive_events(message: str) -> list:
    """Like `_drive` but returns the RAW event list — for tests that inspect
    the progress/hotels markers or the streamed chunk sequence."""
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

    return asyncio.run(go())


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


class TestInternalEvents:
    """S06: progress -> hotels -> streamed tokens, the internal event
    contract the S9 SSE facade will expose over the wire."""

    def test_progress_event_is_first_and_partial(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            "Voici votre hôtel.",
            leaf_text="results: hotel A",
        )
        events = _drive_events(USER_MESSAGE_SEARCH)
        assert events[0].partial is True
        assert _marker_payloads(events)[0] == {"event": "progress"}

    def test_progress_event_fires_even_on_pure_ack_turn(self, scripted):
        scripted()  # empty plan: an ack turn must cost zero LLM calls
        events = _drive_events("Bonjour !")
        assert _marker_payloads(events) == [{"event": "progress"}]

    def test_hotels_event_fires_after_leaf_and_before_the_final_answer(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            "Voici votre hôtel.",
            leaf_text="results: hotel A",
            response={"results": [{"name": "Hotel Alameda"}]},
        )
        events = _drive_events(USER_MESSAGE_SEARCH)
        hotels_payloads = [p for p in _marker_payloads(events) if p["event"] == "hotels"]
        assert hotels_payloads == [{"event": "hotels", "hotels": [{"name": "Hotel Alameda"}]}]
        assert _marker_index(events, "hotels") < _final_index(events)

    def test_inline_and_degraded_turns_have_no_hotels_event(self, scripted, monkeypatch):
        scripted('{"family": "details", "language": "fr"}')
        events = _drive_events("quels équipements a cet hôtel ?")
        assert [p["event"] for p in _marker_payloads(events)] == ["progress"]

    def test_synthesis_streams_multiple_chunks_that_join_into_the_final_text(self, scripted):
        final_text = "Voici deux hôtels très sympas à Paris pour demain."
        scripted(
            '{"family": "search", "language": "fr"}',
            final_text,
            leaf_text="results: hotel A, hotel B",
        )
        events = _drive_events(USER_MESSAGE_SEARCH)
        chunks = _stream_chunks(events)
        assert len(chunks) > 1, "a single lump chunk is not a stream"
        assert "".join(chunks) == final_text
        assert _answer(events) == final_text
        # every chunk event must be partial (never persisted to the session).
        assert all(e.partial for e in events if e is not events[_final_index(events)])


class TestAntiClarificationLoopGuard:
    """P10 (2026-06-11 audit): a synthesized reply repeating the PREVIOUS
    turn's trailing question gets exactly ONE bounded retry with a do-not-ask
    directive, then a deterministic strip — never a full loop restart."""

    QUESTION = "Which airport area exactly should I prioritize?"

    def test_repeated_question_triggers_one_bounded_retry(self, scripted, fake_profile_store, caplog):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(last_clarifying_question=self.QUESTION))
        )
        scripted(
            '{"family": "search", "language": "en"}',
            f"Happy to help! {self.QUESTION}",
            "Here are the Queens options.",
            leaf_text="results: hotel A",
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            events = _drive_in(runner, session.id, "let's do nova")
        assert _answer(events) == "Here are the Queens options."
        # The retry is an internal detail of ONE "synthesis" budget slot.
        assert _turn_metric(caplog)["llm_calls"] == "3"

    def test_still_looping_after_retry_strips_the_question_deterministically(
        self, scripted, fake_profile_store
    ):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(last_clarifying_question=self.QUESTION))
        )
        scripted(
            '{"family": "search", "language": "en"}',
            f"Happy to help! {self.QUESTION}",
            f"Of course. {self.QUESTION}",
            leaf_text="results: hotel A",
        )
        events = _drive_in(runner, session.id, "let's do nova")
        answer = _answer(events)
        assert self.QUESTION not in answer
        assert answer == "Of course."

    def test_new_question_is_not_treated_as_a_repeat(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(last_clarifying_question=self.QUESTION))
        )
        scripted(
            '{"family": "search", "language": "en"}',
            "Got it. What budget should I plan for?",
            leaf_text="results: hotel A",
        )
        events = _drive_in(runner, session.id, "let's do nova")
        assert _answer(events) == "Got it. What budget should I plan for?"


class TestRecoveryAck:
    """P2 (2026-06-11 audit): a bare "ok"/"sure" — or a verbatim recovery-chip
    click — after an empty search must re-run the search, never celebrate a
    stale/empty shortlist via the zero-LLM ack template."""

    def test_bare_ok_after_empty_streak_routes_to_search(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(consecutive_empty_searches=1))
        )
        llm, leaf_calls = scripted(
            '{"family": "ack", "language": "en"}',
            "Sure, widening the search now.",
            leaf_text="results: hotel A",
        )
        events = _drive_in(runner, session.id, "ok")
        assert leaf_calls == ["hotel_search"]
        assert _answer(events) == "Sure, widening the search now."

    def test_recovery_chip_matches_last_suggestions_verbatim(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(
                session.id,
                SessionProfile(
                    last_suggestions=["increase the budget", "try a nearby area", "remove a filter"]
                ),
            )
        )
        llm, leaf_calls = scripted(
            '{"family": "ack", "language": "en"}',
            "Widening the area now.",
            leaf_text="results: hotel A",
        )
        events = _drive_in(runner, session.id, "try a nearby area")
        assert leaf_calls == ["hotel_search"]
        assert _answer(events) == "Widening the area now."

    def test_greeting_after_empty_streak_still_goes_to_the_ack_template(
        self, scripted, fake_profile_store
    ):
        """A pure greeting is NOT a recovery signal even with an empty streak
        — only a bare affirmative or a verbatim suggestion match is."""
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(consecutive_empty_searches=2))
        )
        llm, leaf_calls = scripted()  # empty plan: must cost zero LLM calls
        events = _drive_in(runner, session.id, "Bonjour !")
        assert leaf_calls == []
        assert _answer(events) == templates.ack_response("fr")

    def test_bare_ok_without_empty_streak_stays_a_plain_ack(self, scripted, fake_profile_store):
        runner, session = _new_session()
        llm, leaf_calls = scripted()  # empty plan: a fresh session has no signal
        events = _drive_in(runner, session.id, "ok")
        assert leaf_calls == []
        assert _answer(events) == templates.ack_response("en")
