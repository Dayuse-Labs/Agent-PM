"""2026-10-29 — the leaf answers before the turn's deadline with what it found.

The concierge stamps ONE deadline per turn and sends the leaf its budget for
the call (A2A request metadata `dayuse_turn_budget_ms`). An extra search that
cannot end before it does not start; one still running at it (an MCP that
hangs past its own timeout) is cut; the local page's wait is cut to it. The
first page, already found, goes back to the concierge: never a « search
unavailable » because an extra call outlived the concierge's wait.

Driven through the REAL after-tool chain of `root_agent` against a fake MCP.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from google.adk.a2a.converters.part_converter import convert_genai_part_to_a2a_part

from hotel_search_agent import extra_calls, geo_rank
from hotel_search_agent.response_bridge import (
    STATE_APPLIED_AMENITIES_KEY,
    STATE_PREFERRED_AMENITIES_KEY,
    STATE_SEARCH_DATE_KEY,
    STATE_TURN_T0_KEY,
    emit_search_datapart,
)

DAY = "2026-11-19"
_ARGS = {"lat": 48.91177, "lon": 2.333646, "date": DAY, "radiusKm": 20, "from": 0}


def _hotel(i: int) -> dict:
    return {
        "hotelId": i, "name": f"Hotel {i}", "cityName": "Paris", "countryName": "France",
        "starRating": 4, "globalAverageRating": 4.5,
        "offers": [{"priceEuro": 9000 + i, "startHour": 10, "startMinute": 0, "endHour": 17,
                    "endMinute": 0, "availabilityDate": DAY, "ratePlanId": 1}],
    }


def _page(*ids: int) -> dict:
    return {"structuredContent": {"resolvedDate": DAY, "total": len(ids), "results": [_hotel(i) for i in ids]}}


class _SlowMcp:
    """An MCP whose every call hangs (past its own 5 s timeout)."""

    name = "search_offers"
    raw_mcp_tool = None

    def __init__(self, seconds: float = 30.0):
        self.seconds = seconds
        self.requests: list[dict] = []

    async def run_async(self, *, args, tool_context):
        self.requests.append(dict(args))
        await asyncio.sleep(self.seconds)
        return _page(9)


def _ctx(budget_ms: int | None) -> SimpleNamespace:
    """A turn that started now, with the budget the concierge sent."""
    meta = {"dayuse_trace_id": "s"}
    if budget_ms is not None:
        meta["dayuse_turn_budget_ms"] = budget_ms
    ctx = SimpleNamespace(
        state={STATE_SEARCH_DATE_KEY: {"date": DAY, "same_day": False},
               STATE_APPLIED_AMENITIES_KEY: [], STATE_PREFERRED_AMENITIES_KEY: [],
               STATE_TURN_T0_KEY: time.monotonic()},
        user_content=None, agent_name="b2c_hotel_search", invocation_id="t",
        run_config=SimpleNamespace(custom_metadata={"a2a_metadata": meta}),
    )
    # Looked up at call time: the counter-proof runs this file on origin/main.
    getattr(extra_calls, "stamp_turn_deadline", lambda context: None)(ctx)
    return ctx


async def _after_chain(tool, args, ctx, first):
    from hotel_search_agent.agent import root_agent

    for callback in root_agent.after_tool_callback:
        result = callback(tool=tool, args=args, tool_context=ctx, tool_response=first)
        if asyncio.iscoroutine(result):
            result = await result
        if result is not None:
            return result
    return None


def _emitted_ids(ctx) -> list[int]:
    content = emit_search_datapart(ctx)
    data = next(convert_genai_part_to_a2a_part(p).root.data for p in content.parts if p.inline_data is not None)
    return [card["hotel_id"] for card in data["results"]]


def test_a_hung_extra_call_is_cut_at_the_deadline_and_the_first_page_goes_back(monkeypatch):
    """A thin first page (2 hotels) calls the completion; the MCP hangs. The
    turn's budget (0.6 s here) cuts it: the 2 hotels found are the answer."""
    monkeypatch.setenv("HOTEL_SEARCH_MCP_TIMEOUT_SECONDS", "0.2")
    mcp = _SlowMcp()
    ctx = _ctx(budget_ms=600)

    async def go():
        started = time.monotonic()
        await asyncio.wait_for(_after_chain(mcp, dict(_ARGS), ctx, _page(1, 2)), timeout=3.0)
        return time.monotonic() - started

    elapsed = asyncio.run(go())

    assert len(mcp.requests) == 1  # the completion started (it could end in time)…
    assert elapsed < 1.5  # …and was cut at the deadline, not at the MCP's pace
    assert ctx.state[extra_calls.STATE_EXTRA_CALLS_STOPPED_KEY] == "deadline"
    assert _emitted_ids(ctx) == [1, 2]


def test_no_extra_call_starts_when_it_cannot_end_before_the_deadline():
    """3 s left, an MCP call bounded at 5 s: the completion does not start —
    inside R2's 20 s window, it would have."""
    mcp = _SlowMcp(seconds=0.0)
    ctx = _ctx(budget_ms=3000)
    asyncio.run(_after_chain(mcp, dict(_ARGS), ctx, _page(1, 2)))
    assert mcp.requests == []
    assert ctx.state[extra_calls.STATE_EXTRA_CALLS_STOPPED_KEY] == "deadline"
    assert _emitted_ids(ctx) == [1, 2]


def test_the_local_page_wait_is_cut_to_the_deadline():
    """`geo_rank` waits for its local page at most `remaining_seconds`, which
    now ends at the turn's deadline (0.3 s left here), not 20 s after the
    leaf turn's start. Read through the shared helper, so the page layout of
    `geo_rank` (one task or several) does not matter."""
    import inspect

    ctx = _ctx(budget_ms=300)
    assert extra_calls.remaining_seconds(ctx) <= 0.3
    assert "remaining_seconds(tool_context)" in inspect.getsource(geo_rank.await_local_pool)


def test_the_budget_is_read_from_the_request_metadata():
    ctx = _ctx(budget_ms=12_000)
    left = extra_calls.time_left(ctx)
    assert 11.5 < left <= 12.0
    for unusable in (None, True, -5, "12000"):
        bare = SimpleNamespace(state={}, run_config=SimpleNamespace(
            custom_metadata={"a2a_metadata": {extra_calls.TURN_BUDGET_METADATA_KEY: unusable}}))
        extra_calls.stamp_turn_deadline(bare)
        assert extra_calls.STATE_TURN_DEADLINE_KEY not in bare.state
    # Without one (another caller): the default budget from the turn's start.
    assert 43.0 < extra_calls.time_left(_ctx(budget_ms=None)) <= extra_calls.DEFAULT_TURN_BUDGET_SECONDS


def test_the_leaf_stamps_the_deadline_before_its_turn():
    from hotel_search_agent.agent import root_agent

    assert extra_calls.stamp_turn_deadline in root_agent.before_agent_callback
