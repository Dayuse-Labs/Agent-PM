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


def test_rejected_traffic_does_not_extend_recovery_deadline(clock):
    for _ in range(3):
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, {"error": "transport timeout"})
    for elapsed in (1, 9, 19):
        clock.advance(elapsed)
        response = mcp_circuit_before_tool(SEARCH_TOOL, {}, None)
        assert response is not None
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, response)
    clock.advance(1)
    assert mcp_circuit_before_tool(SEARCH_TOOL, {}, None) is None
    mcp_circuit_after_tool(SEARCH_TOOL, {}, None, {"ok": True})
    assert mcp_circuit_before_tool(NAMED_LOOKUP_TOOL, {}, None) is None


def test_budget_rejection_does_not_clear_real_failure_streak(fresh_breaker):
    for _ in range(2):
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, {"error": "transport timeout"})
    mcp_circuit_after_tool(SEARCH_TOOL, {}, None, {"error": "TOOL BUDGET EXHAUSTED"})
    assert fresh_breaker.allow()
    mcp_circuit_after_tool(SEARCH_TOOL, {}, None, {"error": "transport timeout"})
    assert not fresh_breaker.allow()


def test_raised_error_observed_afterwards_counts_only_once(fresh_breaker):
    for _ in range(2):
        response = mcp_circuit_on_error(SEARCH_TOOL, {}, None, ConnectionError("down"))
        mcp_circuit_after_tool(SEARCH_TOOL, {}, None, response)
        assert fresh_breaker.allow()
    mcp_circuit_on_error(SEARCH_TOOL, {}, None, ConnectionError("down"))
    assert not fresh_breaker.allow()
