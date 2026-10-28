"""R2 (review of #173): the extra `search_offers` calls (next-day probe,
zero-result rescue, completion, local page) stop on the first error and never
start past the deadline — driven through the REAL after-tool chain of
`root_agent` against a fake MCP that counts the requests it receives."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from hotel_search_agent import extra_calls, mcp_guard
from hotel_search_agent.response_bridge import (
    STATE_APPLIED_AMENITIES_KEY,
    STATE_PREFERRED_AMENITIES_KEY,
    STATE_SEARCH_DATE_KEY,
    STATE_TURN_T0_KEY,
)

TODAY, TOMORROW = "2026-10-28", "2026-10-29"
_429 = {"isError": True, "content": [{"type": "text", "text": "Error: HTTP 429 Too Many Requests"}]}


def _payload(*, total=0, before=None, day=TODAY):
    data = {"resolvedDate": day, "total": total, "results": []}
    if before is not None:
        data["totalBeforeCutoff"] = before
    return {"structuredContent": data}


class _Mcp:
    """A fake MCP server: answers every request with `answer(args)` (or raises
    it) and counts what it receives."""

    name = "search_offers"
    raw_mcp_tool = None

    def __init__(self, answer, clock=None, seconds_per_call=0.0):
        self.answer = answer
        self.requests: list[dict] = []
        self.clock = clock
        self.seconds = seconds_per_call

    async def run_async(self, *, args, tool_context):
        self.requests.append(dict(args))
        if self.clock is not None:
            self.clock[0] += self.seconds
        result = self.answer(args)
        if isinstance(result, Exception):
            raise result
        return result


def _ctx(*, same_day=True, t0=None):
    state = {STATE_SEARCH_DATE_KEY: {"date": TODAY, "same_day": same_day},
             STATE_APPLIED_AMENITIES_KEY: ["jacuzzi"], STATE_PREFERRED_AMENITIES_KEY: []}
    if t0 is not None:
        state[STATE_TURN_T0_KEY] = t0
    return SimpleNamespace(state=state, user_content=None, agent_name="b2c_hotel_search", invocation_id="t")


async def _after_chain(tool, args, ctx, first):
    from hotel_search_agent.agent import root_agent

    for callback in root_agent.after_tool_callback:
        result = callback(tool=tool, args=args, tool_context=ctx, tool_response=first)
        if asyncio.iscoroutine(result):
            result = await result
        if result is not None:
            return result
    return None


_ARGS = {"lat": 53.34938, "lon": -6.260559, "hotelEquipmentIds": [41], "radiusKm": 20, "date": TODAY}


@pytest.mark.parametrize("failure", [_429, RuntimeError("429 Too Many Requests")], ids=["isError-429", "raised"])
def test_a_429_on_the_probe_stops_the_rescue_and_the_completion(failure, monkeypatch):
    # Today, closing (6 hotels before cutoff): the probe goes first and gets a 429.
    lines: list[str] = []
    monkeypatch.setattr(extra_calls._metrics_logger, "info", lambda fmt, *a: lines.append(fmt % a))
    mcp = _Mcp(lambda args: failure)
    ctx = _ctx()
    asyncio.run(_after_chain(mcp, dict(_ARGS), ctx, _payload(before=6)))

    assert len(mcp.requests) == 1  # the probe only: no rescue, no completion
    assert ctx.state[extra_calls.STATE_EXTRA_CALLS_STOPPED_KEY] == "error"
    assert mcp_guard.breaker._failures == 1
    assert any("kind=next_day_probe status=error" in line for line in lines)


def test_a_429_on_the_rescue_is_not_read_as_empty():
    # Not today: no probe; the rescue's first rung gets a 429 — before, the
    # ladder went on to its second rung and the completion made a 4th call.
    mcp = _Mcp(lambda args: _429)
    ctx = _ctx(same_day=False)
    asyncio.run(_after_chain(mcp, {**_ARGS, "date": TOMORROW}, ctx, _payload(day=TOMORROW)))

    assert len(mcp.requests) == 1
    assert mcp_guard.breaker._failures == 1


def test_the_breaker_counts_the_extra_calls_with_the_model_calls():
    # The breaker the model's own MCP calls go through (`mcp_circuit_*`, 3
    # failures in a row): two failed model calls, then an extra call's 429.
    mcp_guard.breaker.record_failure()
    mcp_guard.breaker.record_failure()
    status, _ = asyncio.run(extra_calls.extra_call(_Mcp(lambda args: _429), dict(_ARGS), _ctx(), kind="rescue"))
    assert status == "error" and mcp_guard.breaker.allow() is False
    # And an open breaker starts no extra call at all.
    mcp = _Mcp(lambda args: _payload())
    status, _ = asyncio.run(extra_calls.extra_call(mcp, dict(_ARGS), _ctx(), kind="completion"))
    assert status == "skipped" and mcp.requests == []


def test_no_extra_call_starts_past_the_deadline(monkeypatch):
    """Worst case on the PR before R2: 4 searches in a row (first page,
    rescue ×2, completion after an empty rescue). A slow MCP (5 s per call),
    the first page back at 12 s: two rescue rungs start (12→17 s, 17→22 s),
    the completion would start at 22 s, past the 20 s deadline: it does not."""
    clock = [12.0]
    monkeypatch.setattr(extra_calls, "_now", lambda: clock[0])
    mcp = _Mcp(lambda args: _payload(day=args["date"]), clock=clock, seconds_per_call=5.0)
    ctx = _ctx(same_day=False, t0=0.0)

    asyncio.run(_after_chain(mcp, {**_ARGS, "date": TOMORROW}, ctx, _payload(day=TOMORROW)))

    assert len(mcp.requests) == 2
    assert clock[0] <= extra_calls.EXTRA_CALLS_DEADLINE_SECONDS + 5.0
    assert ctx.state[extra_calls.STATE_EXTRA_CALLS_STOPPED_KEY] == "deadline"


def test_late_first_page_gets_no_extra_call(monkeypatch):
    clock = [21.0]
    monkeypatch.setattr(extra_calls, "_now", lambda: clock[0])
    mcp = _Mcp(lambda args: _payload(day=args["date"]), clock=clock, seconds_per_call=5.0)
    asyncio.run(_after_chain(mcp, {**_ARGS, "date": TOMORROW}, _ctx(same_day=False, t0=0.0), _payload(day=TOMORROW)))
    assert mcp.requests == []


def test_without_a_deadline_hit_the_ladder_runs_as_designed(monkeypatch):
    clock = [3.0]
    monkeypatch.setattr(extra_calls, "_now", lambda: clock[0])
    mcp = _Mcp(lambda args: _payload(day=args["date"]), clock=clock, seconds_per_call=0.5)
    asyncio.run(_after_chain(mcp, {**_ARGS, "date": TOMORROW}, _ctx(same_day=False, t0=0.0), _payload(day=TOMORROW)))
    # Rescue ×2 (amenity, then ring) and the completion's wider ring.
    assert len(mcp.requests) == 3
