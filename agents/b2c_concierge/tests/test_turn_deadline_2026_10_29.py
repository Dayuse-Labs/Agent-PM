"""2026-10-29 — one deadline per turn, and a failed leaf is a failure (O7).

- `_run_leaf` waits the family's budget cut so the synthesis keeps its
  reserve, and tells the leaf that budget in the A2A request metadata.
- A turn whose synthesis would run past the deadline answers with what the
  leaf found (the cards, the leaf's outcome line) — not « search unavailable »,
  and not after the deadline.
- A leaf that sent back nothing, a transport error the leg turned into an
  event, a failed A2A task: `leaf_call status=error`, never `status=ok` with
  the exception's text as the leaf's outcome (CHANTIERS O7).
"""
from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace

import pytest
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

import b2c_concierge.agent as agent_module
from b2c_concierge import templates
from b2c_concierge.a2a_datapart import encode_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.routing import LEAF_HOTEL_SEARCH

from .test_spine_profile import _llm_response, _new_session

_RESULTS = {"results": [{"hotel_id": 1, "name": "Hotel A"}], "profile_delta": {"city": "Paris"}}
_LEAF_TEXT = "Offres de jour affichées : Hotel A."


class _Leg:
    """The A2A leg: yields `events` after `delay` s, and records the request
    metadata the leg would send (`_leaf_request_meta`) while it runs."""

    def __init__(self, events: list[Event], delay: float = 0.0):
        self.events, self.delay = events, delay
        self.meta: dict | None = None

    async def run_async(self, ctx):
        # Looked up at call time: the counter-proof runs this file on origin/main.
        provider = getattr(agent_module, "_leaf_request_meta", lambda c, m: {"dayuse_trace_id": c.session.id})
        self.meta = provider(ctx, None)
        if self.delay:
            await asyncio.sleep(self.delay)
        for event in self.events:
            yield event


def _event(*parts: genai_types.Part, **extra) -> Event:
    return Event(author="hotel_search_leg", invocation_id="i",
                 content=genai_types.Content(role="model", parts=list(parts)) if parts else None, **extra)


def _ctx() -> SimpleNamespace:
    user = Event(author="user", content=genai_types.Content(role="user", parts=[genai_types.Part(text="Paris")]))
    return SimpleNamespace(session=SimpleNamespace(id="s", events=[user]), invocation_id="i")


def _call(monkeypatch, leg: _Leg, deadline: float | None = None):
    monkeypatch.setattr(agent_module, "_get_leg", lambda leaf: leg)
    kwargs = {} if deadline is None else {"deadline": deadline}
    return asyncio.run(agent_module._run_leaf(LEAF_HOTEL_SEARCH, _ctx(), {}, **kwargs))


def _leaf_call_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "concierge_metric=leaf_call" in r.getMessage()]


class TestFailedLeafIsAnError:
    @pytest.mark.parametrize(
        ("events", "error_type"),
        [
            ([], "EmptyLeafResponse"),
            ([_event(error_message="A2A request failed: ReadTimeout")], "A2AError"),
            # The leaf's exception, as its failed task's status message (ADK executor).
            ([_event(genai_types.Part(text="litellm.Timeout: APITimeoutError"),
                     custom_metadata={"a2a:response": {"status": {"state": "failed"}}})], "LeafTaskFailed"),
        ],
        ids=["nothing", "transport-error", "failed-task"],
    )
    def test_status_error_and_no_outcome(self, monkeypatch, caplog, events, error_type):
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            text, response = _call(monkeypatch, _Leg(events))
        assert (text, response) == (None, {})
        [line] = _leaf_call_lines(caplog)
        assert "status=error" in line and f"error_type={error_type}" in line

    def test_an_answer_is_still_ok(self, monkeypatch, caplog):
        leg = _Leg([_event(genai_types.Part(text=_LEAF_TEXT), encode_datapart(_RESULTS))])
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            text, response = _call(monkeypatch, leg)
        assert text == _LEAF_TEXT and response["results"] == _RESULTS["results"]
        assert "status=ok" in _leaf_call_lines(caplog)[0]


class TestTheLeafIsToldItsBudget:
    def test_the_budget_rides_the_request_metadata(self, monkeypatch):
        leg = _Leg([_event(genai_types.Part(text=_LEAF_TEXT))])
        _call(monkeypatch, leg, deadline=time.monotonic() + 30.0)
        # 30 s left, 8 s kept for the synthesis, 1 s for the answer's way back.
        assert 20_500 <= leg.meta["dayuse_turn_budget_ms"] <= 21_000
        assert leg.meta["dayuse_trace_id"] == "s"
        # Outside a call: the session id only, as before.
        assert agent_module._leaf_request_meta(_ctx(), None) == {"dayuse_trace_id": "s"}

    def test_its_own_ceiling_holds_when_the_turn_has_time(self, monkeypatch):
        leg = _Leg([_event(genai_types.Part(text=_LEAF_TEXT))])
        _call(monkeypatch, leg, deadline=time.monotonic() + 120.0)
        assert leg.meta["dayuse_turn_budget_ms"] == 44_000  # 45 s, less the 1 s grace

    def test_the_wait_is_cut_so_the_synthesis_keeps_its_reserve(self, monkeypatch, caplog):
        leg = _Leg([_event(genai_types.Part(text=_LEAF_TEXT))], delay=5.0)
        started = time.monotonic()
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            text, _ = _call(monkeypatch, leg, deadline=time.monotonic() + 9.5)
        assert text is None and time.monotonic() - started < 2.5
        assert "status=error" in _leaf_call_lines(caplog)[0]


class _SlowSynthesis:
    """Triage answers at once; the synthesis hangs (a stuck provider)."""

    def __init__(self, triage: str, seconds: float):
        self.triage, self.seconds, self.calls = triage, seconds, []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return _llm_response(self.triage)
        await asyncio.sleep(self.seconds)
        return _llm_response("trop tard")


class TestTheTurnEndsWithWhatWasFound:
    def _turn(self, monkeypatch, leaf_delay: float) -> tuple[list[Event], float, _SlowSynthesis]:
        monkeypatch.setenv("CONCIERGE_TURN_DEADLINE_SECONDS", "3.0")
        monkeypatch.setenv("CONCIERGE_SYNTHESIS_RESERVE_SECONDS", "1.0")
        llm = _SlowSynthesis('{"family": "search", "language": "fr"}', seconds=30.0)
        monkeypatch.setattr(agent_module.litellm, "acompletion", llm)
        agent_module._reset_synthesis_routers()
        leg = _Leg([_event(genai_types.Part(text=_LEAF_TEXT), encode_datapart(_RESULTS))], delay=leaf_delay)
        monkeypatch.setattr(agent_module, "_get_leg", lambda leaf: leg)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        async def go():
            content = genai_types.Content(role="user", parts=[genai_types.Part(text="un hôtel à Paris demain")])
            started = time.monotonic()
            events = [e async for e in runner.run_async(user_id="u", session_id=session.id, new_message=content)]
            return events, time.monotonic() - started

        events, elapsed = asyncio.run(asyncio.wait_for(go(), timeout=8.0))
        return events, elapsed, llm

    @staticmethod
    def _final(events) -> str:
        return "".join(p.text for e in events if not e.partial and e.content for p in e.content.parts if p.text)

    def test_a_stuck_synthesis_is_cut_and_the_hotels_found_are_the_answer(self, monkeypatch):
        events, elapsed, llm = self._turn(monkeypatch, leaf_delay=0.2)
        final = self._final(events)
        assert elapsed < 4.0  # by the 3 s deadline, not after the stuck call
        assert "Hotel A" in final
        assert final != templates.leaf_degraded_response("search", "fr", "Paris")
        hotels = [p for e in events if e.partial and e.content for p in e.content.parts
                  if p.text and '"event": "hotels"' in p.text]
        assert hotels and "Hotel A" in hotels[0].text

    def test_no_synthesis_starts_without_the_time_to_finish(self, monkeypatch, caplog):
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            events, _, llm = self._turn(monkeypatch, leaf_delay=1.2)
        assert len(llm.calls) == 1  # the triage only
        assert "Hotel A" in self._final(events)
        assert any("stage=synthesis action=skipped" in r.getMessage() for r in caplog.records)
