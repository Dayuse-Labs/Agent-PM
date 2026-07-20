"""End-to-end profile plumbing tests over the REAL `_run_leaf` — only the A2A
leg itself is faked (no network, no httpx). Unlike test_spine.py's `scripted`
fixture (which replaces `_run_leaf` wholesale), this exercises the actual S5
wiring: the outgoing `{query_params, profile_in}` DataPart, the incoming
`profile_delta` decode, the budget-integrity / auto-widen guards, and Redis
(fakeredis) persistence across turns of the SAME session.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

import b2c_concierge.agent as agent_module
from b2c_concierge.a2a_datapart import encode_datapart, find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import BUDGET_SOURCE_EXPLICIT, BUDGET_SOURCE_FLEXIBLE_DEFAULT


def _llm_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class ScriptedLlm:
    def __init__(self, *plan):
        self.plan = list(plan)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self.plan.pop(0)
        if isinstance(item, Exception):
            raise item
        return _llm_response(item)


class FakeLeg:
    """Stands in for the A2A leg: records the ctx it received (so the test
    can inspect the outgoing DataPart) and yields a scripted response that
    may itself carry a DataPart (the leaf's SearchResponse)."""

    def __init__(self):
        self.text = "results: hotel A"
        self.response_payload: dict | None = None
        # A snapshot of the outgoing parts, taken HERE: the ADK runner keeps
        # appending events to the session as the turn finishes, so reading
        # ctx.session.events[-1] after the turn would see the FINAL answer
        # event instead of the user turn we were sent.
        self.seen_outgoing_parts: list[genai_types.Part] = []

    async def run_async(self, ctx):
        self.seen_outgoing_parts = list(ctx.session.events[-1].content.parts or [])
        parts = [genai_types.Part(text=self.text)]
        if self.response_payload is not None:
            parts.append(encode_datapart(self.response_payload))
        yield Event(
            author="hotel_search_leg",
            invocation_id=ctx.invocation_id,
            content=genai_types.Content(role="model", parts=parts),
        )


@pytest.fixture
def fake_leg(monkeypatch):
    leg = FakeLeg()
    monkeypatch.setattr(agent_module, "_get_leg", lambda leaf: leg)
    return leg


def _scripted_llm(monkeypatch, *plan) -> ScriptedLlm:
    llm = ScriptedLlm(*plan)
    monkeypatch.setattr(agent_module.litellm, "acompletion", llm)
    return llm


def _new_session(runner):
    async def go():
        return await runner.session_service.create_session(app_name=runner.app_name, user_id="u")

    return asyncio.run(go())


def _run_turn(runner, session_id, message):
    async def go():
        content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
        return [
            event
            async for event in runner.run_async(
                user_id="u", session_id=session_id, new_message=content
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


class TestOutgoingProfileEnvelope:
    def test_profile_in_travels_to_the_leaf_as_a_datapart(self, monkeypatch, fake_leg):
        fake_leg.response_payload = {"results": [], "profile_delta": {}}
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "synthesized reply")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "looking for a hotel")

        outgoing_parts = fake_leg.seen_outgoing_parts
        decoded = find_datapart(outgoing_parts)
        assert decoded is not None
        assert set(decoded) == {"query_params", "profile_in"}
        assert decoded["profile_in"]["budget_max"] is None
        assert decoded["profile_in"]["city"] is None


class TestProfileDeltaAppliedAndPersisted:
    def test_budget_delta_is_persisted_after_the_turn(self, monkeypatch, fake_leg, fake_profile_store):
        fake_leg.response_payload = {
            "results": ["hotel A"],
            "profile_delta": {"city": "Paris", "budget_max": 150, "budget_request_source": BUDGET_SOURCE_FLEXIBLE_DEFAULT},
        }
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Here is a hotel in Paris.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "a hotel in Paris please")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.city == "Paris"
        assert stored.budget_max == 150.0
        assert stored.budget_request_source == BUDGET_SOURCE_FLEXIBLE_DEFAULT

    def test_amenities_delta_is_persisted_and_surfaces_in_search_context(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        """S10: the leaf emits the amenity filters it hard-applied
        (equipment_ids/response_bridge) as `profile_delta.amenities`; the
        orchestrator must merge them (accumulating filter for next turns) AND
        show them in the SAME turn's SEARCH CONTEXT (transparency)."""
        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A", "amenities": ["pool"]}],
            "profile_delta": {"amenities": ["pool"]},
        }
        llm = _scripted_llm(
            monkeypatch, '{"family": "search", "language": "fr"}', "Voici un hôtel avec piscine."
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "un hotel à miami avec une piscine")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.amenities == ["pool"]
        # The delta is applied BEFORE synthesis (agent.py), so the search-context
        # line the model saw this turn already restates the amenity.
        assert "amenities: pool" in llm.calls[-1]["messages"][1]["content"]

    def test_bare_number_reply_overrides_the_leafs_own_source_claim(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        """The P1 safety net: even if the leaf's own extraction mislabels a
        plain-number reply as a system default, the orchestrator's guard
        forces `explicit` — the exact bug the 2026-06 audit found in prod."""
        fake_leg.response_payload = {
            "results": ["hotel A"],
            "profile_delta": {"budget_max": 180, "budget_request_source": BUDGET_SOURCE_FLEXIBLE_DEFAULT},
        }
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Got it.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "180")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.budget_request_source == BUDGET_SOURCE_EXPLICIT


class TestAutoWidenThroughTheSpine:
    def test_two_empty_searches_widen_a_non_explicit_budget(self, monkeypatch, fake_leg, fake_profile_store):
        fake_leg.response_payload = {
            "results": [],
            "profile_delta": {"budget_max": 100, "budget_request_source": BUDGET_SOURCE_FLEXIBLE_DEFAULT},
        }
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "No luck yet.",
            '{"family": "search", "language": "en"}', "Still nothing.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "a hotel under 100")
        fake_leg.response_payload = {"results": []}  # keep budget_max as already stored
        _run_turn(runner, session.id, "still looking")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.consecutive_empty_searches == 2
        assert stored.budget_max == 150.0
        # S06: the disclosure is surfaced by THIS SAME turn's synthesis (see
        # agent.py's _synthesize_with_guards) and cleared right after — it
        # must never persist to be silently re-surfaced (or re-suppressed)
        # on a later turn.
        assert stored.auto_widen_disclosure is None
        # The widening turn's own synthesis call must have SEEN the note —
        # otherwise the guard stays silent (the exact S05 handoff gap).
        synthesis_calls = [c for c in llm.calls if "AUTO_WIDEN" in c["messages"][1]["content"]]
        assert len(synthesis_calls) == 1
        assert "100.0 to 150.0" in synthesis_calls[0]["messages"][1]["content"]

    def test_explicit_budget_is_never_auto_widened(self, monkeypatch, fake_leg, fake_profile_store):
        fake_leg.response_payload = {"results": [], "profile_delta": {"budget_max": 100}}
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "No luck yet.",
            '{"family": "search", "language": "en"}', "Still nothing.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "100")  # bare number -> explicit
        fake_leg.response_payload = {"results": []}
        _run_turn(runner, session.id, "still looking")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.consecutive_empty_searches == 2
        assert stored.budget_max == 100.0
        assert stored.auto_widen_disclosure is None


class TestProfileContinuityAcrossTurns:
    def test_city_from_turn_one_is_sent_as_profile_in_on_turn_two(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": {"city": "Lyon"}}
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "A hotel in Lyon.",
            '{"family": "search", "language": "en"}', "Another one in Lyon.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "a hotel in Lyon")
        fake_leg.response_payload = {"results": ["hotel B"], "profile_delta": {}}
        _run_turn(runner, session.id, "another one please")

        outgoing_parts = fake_leg.seen_outgoing_parts
        decoded = find_datapart(outgoing_parts)
        assert decoded["profile_in"]["city"] == "Lyon"


class TestProfileStoreOutageDegradesHonestly:
    def test_turn_still_answers_when_redis_is_unreachable(self, monkeypatch, fake_leg):
        """The profile store is a NEW dependency (S5) — it must not become a
        new single point of failure: a Redis outage degrades the turn like a
        leaf outage would (answer served, profile simply not persisted)."""
        from b2c_concierge.profile_store import ProfileStore

        class _DeadClient:
            async def get(self, *a, **k):
                raise ConnectionError("redis unreachable")

            async def set(self, *a, **k):
                raise ConnectionError("redis unreachable")

        monkeypatch.setattr(agent_module, "get_profile_store", lambda: ProfileStore(_DeadClient()))
        fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": {"city": "Nice"}}
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "A hotel in Nice.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        answer = _run_turn(runner, session.id, "a hotel in Nice")

        assert answer == "A hotel in Nice."
