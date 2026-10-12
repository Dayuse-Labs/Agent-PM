"""MCP circuit breaker wiring — fake clock, no sleeping, no real MCP call.

DoD (phase S04, item 5): MCP down -> clean diagnostics dict in the tool
response, never an exception, and repeated failures open the breaker so
further calls are short-circuited instantly (a guard never re-runs a loop).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from hotel_search_agent import mcp_guard
from hotel_search_agent.mcp_guard import (
    mcp_circuit_after_tool,
    mcp_circuit_before_tool,
    mcp_circuit_on_error,
)
from hotel_search_agent.resilience import CircuitBreaker


@dataclass
class _Tool:
    name: str


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture(autouse=True)
def fresh_breaker(monkeypatch, clock):
    """Every test gets its own breaker (fake clock, no sleeping) instead of
    the shared module-level singleton — tests must not leak failure counts
    into each other."""
    fresh = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0, clock=clock)
    monkeypatch.setattr(mcp_guard, "breaker", fresh)
    return fresh


SEARCH_TOOL = _Tool("search_offers")
NAMED_LOOKUP_TOOL = _Tool("find_hotel_by_name")
OTHER_TOOL = _Tool("get_faq_conditions")


class TestIgnoresNonMcpTools:
    def test_before_tool_never_touches_other_tools(self):
        assert mcp_circuit_before_tool(OTHER_TOOL, {}, None) is None

    def test_after_tool_never_touches_other_tools(self, fresh_breaker):
        mcp_circuit_after_tool(OTHER_TOOL, {}, None, {"error": "boom"})
        assert fresh_breaker.allow()  # no failure recorded

    def test_on_error_never_touches_other_tools(self):
        assert mcp_circuit_on_error(OTHER_TOOL, {}, None, RuntimeError("boom")) is None


class TestBeforeTool:
    def test_allows_call_while_closed(self):
        assert mcp_circuit_before_tool(SEARCH_TOOL, {}, None) is None

    def test_short_circuits_with_clean_diagnostic_while_open(self, fresh_breaker):
        for _ in range(3):
            fresh_breaker.record_failure()

        result = mcp_circuit_before_tool(SEARCH_TOOL, {}, None)

        assert result is not None
        assert result["ok"] is False
        assert result["error"] == "mcp_circuit_open"
        assert result["diagnostics"]["tool"] == "search_offers"
        # S-CX2 (audit F3): the reason enters the model context and can be
        # echoed to the customer — it must stay customer-neutral, jargon-free.
        reason = result["diagnostics"]["reason"]
        assert "unavailable" in reason
        for jargon in ("MCP", "circuit"):
            assert jargon.lower() not in reason.lower()


class TestAfterToolClassification:
    @pytest.mark.parametrize(
        "tool_response",
        [
            {"isError": True},
            {"error": "MCP tool execution failed: connection refused"},
            {"structuredContent": {"ok": False, "error": "no ES connection"}},
            {"ok": False, "error": "no ES connection"},
        ],
    )
    def test_error_shapes_record_a_failure(self, fresh_breaker, tool_response):
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, tool_response)
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, tool_response)
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, tool_response)
        assert not fresh_breaker.allow()

    def test_successful_response_does_not_record_a_failure(self, fresh_breaker):
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, {"ok": True, "results": []})
        assert fresh_breaker.allow()

    def test_tool_budget_stop_is_not_a_failure(self, fresh_breaker):
        # The tool_budget callback's own short-circuit dict must not trip the
        # MCP breaker — it's control flow, not an MCP failure.
        for _ in range(5):
            mcp_circuit_after_tool(
                SEARCH_TOOL, {}, None, {"ok": False, "error": "TOOL BUDGET EXHAUSTED — ..."}
            )
        assert fresh_breaker.allow()

    def test_success_resets_a_partial_failure_streak(self, fresh_breaker):
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, {"ok": False, "error": "down"})
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, {"ok": False, "error": "down"})
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, {"ok": True})
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, {"ok": False, "error": "down"})
        assert fresh_breaker.allow()


class TestOnErrorSwallowsExceptions:
    def test_returns_clean_diagnostic_instead_of_reraising(self):
        result = mcp_circuit_on_error(NAMED_LOOKUP_TOOL, {}, None, ConnectionError("MCP down"))
        assert result is not None
        assert result["ok"] is False
        assert result["error"] == "mcp_circuit_open"
        assert result["diagnostics"]["tool"] == "find_hotel_by_name"
        # S-CX2 (audit F3): customer-neutral reason, jargon-free (see above).
        reason = result["diagnostics"]["reason"]
        assert "unavailable" in reason
        for jargon in ("MCP", "circuit"):
            assert jargon.lower() not in reason.lower()

    def test_repeated_raised_errors_open_the_breaker(self, fresh_breaker):
        for _ in range(3):
            mcp_circuit_on_error(SEARCH_TOOL, {}, None, ConnectionError("MCP down"))

        assert not fresh_breaker.allow()
        assert mcp_circuit_before_tool(SEARCH_TOOL, {}, None) is not None


class TestRecovery:
    def test_breaker_recovers_after_cooldown(self, fresh_breaker, clock):
        for _ in range(3):
            fresh_breaker.record_failure()
        assert mcp_circuit_before_tool(SEARCH_TOOL, {}, None) is not None

        clock.advance(30.0)

        assert mcp_circuit_before_tool(SEARCH_TOOL, {}, None) is None


# --- mcp-dayuse#8: which MCP errors are the request's fault ---------------------------------

_NOT_FOUND = {
    "content": [{"type": "text", "text": 'No hotel found for "Novotel Lyon Zorbalix"'}],
    "structuredContent": {"error": {
        "kind": "HotelNotFoundError", "message": "No hotel found", "retryable": False,
        "query": "Novotel Lyon Zorbalix",
    }},
    "isError": True,
}
# Verbatim from the local MCP, 2026-10-06 (QA trace 9bc5feb6's shape).
_INVALID_ARGS = {
    "content": [{"type": "text", "text": (
        "MCP error -32602: Input validation error: Invalid arguments for tool search_offers: "
        "Unrecognized key(s) in object: 'currency'"
    )}],
    "isError": True,
}


@pytest.mark.parametrize(
    "response,kind",
    [
        (_NOT_FOUND, "not_found"),
        (_INVALID_ARGS, "rejected"),
        ({"structuredContent": {"error": {"kind": "AmbiguousHotelError", "retryable": False}},
          "isError": True}, "rejected"),
        ({"isError": True, "content": [{"type": "text", "text": "ES timeout"}]}, "failed"),
        ({"ok": False, "error": "mcp_circuit_open"}, "failed"),
        ({"ok": True, "structuredContent": {"items": []}}, None),
    ],
)
def test_classify_mcp_error(response, kind):
    assert mcp_guard.classify_mcp_error(response) == kind


def test_invalid_arguments_do_not_open_the_breaker(clock, monkeypatch):
    # Three rejected calls used to open the circuit for 30 s, for everyone.
    monkeypatch.setattr(mcp_guard, "breaker", CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0, clock=clock))
    for _ in range(3):
        mcp_circuit_after_tool(_Tool("search_offers"), {}, None, _INVALID_ARGS)
    assert mcp_circuit_before_tool(_Tool("search_offers"), {}, None) is None


# --- PR134-FIX B1: only calls really sent to MCP feed the breaker -----------------------------


class _ChainContext:
    """A per-call ToolContext stand-in, driven through the leaf's REAL chain."""

    invocation_id = "b1-chain"
    agent_name = "b2c_hotel_search"

    def __init__(self, state: dict):
        self.state = state
        self.user_content = None


def _adk_tool_call(tool_name: str, state: dict, mcp_answer: dict) -> dict:
    """ADK 2.4's order (flows/llm_flows/functions.py, steps 1-6): the canonical
    before chain stops at the first non-None result, the tool runs only if none
    short-circuited, and the after chain runs EITHER WAY."""
    from hotel_search_agent.agent import root_agent

    tool, args, ctx = _Tool(tool_name), {"name": "Hotel X"}, _ChainContext(state)
    response = None
    for callback in root_agent.canonical_before_tool_callbacks:
        response = callback(tool, args, ctx)
        if response is not None:
            break
    if response is None:
        response = mcp_answer
    for callback in root_agent.canonical_after_tool_callbacks:
        callback(tool, args, ctx, response)
    return response


def test_local_refusals_never_open_the_breaker(fresh_breaker):
    from b2c_common.confirmed_location import CLARIFICATION_KEY

    # `location_requires_clarification`: the leaf refuses BEFORE any MCP hit.
    # Three such refusals, from anyone, used to give 30 s of "the search is
    # unavailable" to every user of the process.
    for _ in range(3):
        refused = _adk_tool_call(
            "search_offers", {CLARIFICATION_KEY: {"question": "Which Paris?"}}, {"ok": True}
        )
        assert refused["error"] == "location_requires_clarification"
    assert fresh_breaker.allow()


def test_real_mcp_failures_through_the_chain_still_open_the_breaker(fresh_breaker):
    for _ in range(3):
        _adk_tool_call("find_hotel_by_name", {}, {"isError": True, "content": [{"type": "text", "text": "ES timeout"}]})
    assert not fresh_breaker.allow()


def test_a_local_refusal_is_not_metered_as_a_tool_error(fresh_breaker):
    import logging

    from b2c_common.confirmed_location import CLARIFICATION_KEY

    rows: list[str] = []

    class _Collect(logging.Handler):
        def emit(self, record):
            rows.append(record.getMessage())

    logger = logging.getLogger("dayuse.metrics")  # propagate=False: caplog never sees it
    handler = _Collect()
    logger.addHandler(handler)
    try:
        _adk_tool_call("search_offers", {CLARIFICATION_KEY: {"question": "?"}}, {"ok": True})
    finally:
        logger.removeHandler(handler)
    rows = [r for r in rows if "dayuse_metric=tool_call" in r]
    assert len(rows) == 1 and "status=ok" in rows[0] and "error_type=-" in rows[0]


def test_a_callback_that_dispatches_mcp_itself_is_still_observed(fresh_breaker, monkeypatch):
    # The area batch calls `tool.run_async` from a before_tool_callback: its
    # short-circuit IS the real MCP outcome and must keep feeding the breaker.
    import asyncio
    from types import SimpleNamespace

    from hotel_search_agent.area_scope import STATE_AREAS, search_areas_before_tool
    from hotel_search_agent.mcp_guard import mcp_call_pending

    monkeypatch.setattr("hotel_search_agent.geocode_tool.get_mapbox_client", lambda: SimpleNamespace())

    async def run_async(*, args, tool_context):
        return {"isError": True, "content": [{"type": "text", "text": "ES timeout"}]}

    tool = SimpleNamespace(name="search_offers", run_async=run_async)
    for _ in range(3):
        ctx = _ChainContext({STATE_AREAS: [{"id": "a", "label": "Yvelines", "country": "FR",
                                            "latitude": 48.8, "longitude": 1.8, "radius_km": 70}]})
        mcp_call_pending(tool, {}, ctx)
        response = asyncio.run(search_areas_before_tool(tool, {}, ctx))
        assert response == {"ok": False, "error": "area_search_unavailable"}
        mcp_circuit_after_tool(tool, {}, ctx, response)
    assert not fresh_breaker.allow()
