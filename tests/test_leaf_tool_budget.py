"""Leaf tool budget + circuit-breaker classification (prod 2026-07-29).

Two independent defects turned a healthy MCP_B2C into a user-visible outage
("je n'arrive pas à joindre la recherche d'hôtels à Singapore", while
`search_offers` answers Singapore in ~0,7 s):

1. The tool budget was a FLAT cap of 2 over all tools, and a nominal turn already
   spends `geocode_location` + `search_offers`. One failed geocode (frequent on
   "SG"/"Singapour", rare on "Paris") consumed the budget and the search was
   short-circuited before it ever ran — leaf logs showed
   `search_offers ms=0 budget_stopped=true`.
2. The MCP circuit breaker counted a typed BUSINESS error (`HotelNotFoundError`,
   `AmbiguousHotelError`) as a dependency failure: three legitimate "no hotel by
   that name" answers opened it and every search degraded for the next 30 s.
"""
from __future__ import annotations

from types import SimpleNamespace

from hotel_search_agent.agent import MAX_TOOL_CALLS, PER_TOOL_CALL_LIMITS
from hotel_search_agent.mcp_guard import _is_tool_failure
from hotel_search_agent.tool_budget_guard import make_per_tool_budget_callback


class _Ctx:
    """Minimal stand-in for ADK's ToolContext: a state dict + invocation id."""

    def __init__(self, invocation_id: str = "inv-1") -> None:
        self.state: dict[str, object] = {}
        self.invocation_id = invocation_id


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _call(cb, ctx: _Ctx, name: str):
    return cb(_tool(name), {}, ctx)


def test_geocode_retry_never_starves_the_search() -> None:
    """The regression: geocode twice (one failure + its retry), search still runs."""
    cb = make_per_tool_budget_callback({"geocode_location": 2, "search_offers": 2}, 2)
    ctx = _Ctx()

    assert _call(cb, ctx, "geocode_location") is None  # 1st attempt (failed upstream)
    assert _call(cb, ctx, "geocode_location") is None  # bounded retry
    assert _call(cb, ctx, "search_offers") is None  # used to be budget_stopped


def test_each_tool_stays_hard_capped() -> None:
    """Per-tool counting must not weaken the anti-loop guarantee."""
    cb = make_per_tool_budget_callback({"geocode_location": 2}, 2)
    ctx = _Ctx()

    _call(cb, ctx, "geocode_location")
    _call(cb, ctx, "geocode_location")
    stopped = _call(cb, ctx, "geocode_location")

    assert isinstance(stopped, dict)
    assert stopped["ok"] is False
    # `dayuse_agent_common.metrics` flags budget_stopped on this exact prefix.
    assert str(stopped["error"]).startswith("TOOL BUDGET")


def test_unlisted_tool_falls_back_to_the_default_cap() -> None:
    cb = make_per_tool_budget_callback({"geocode_location": 5}, 1)
    ctx = _Ctx()

    assert _call(cb, ctx, "some_other_tool") is None
    assert isinstance(_call(cb, ctx, "some_other_tool"), dict)


def test_counters_reset_on_a_new_invocation() -> None:
    cb = make_per_tool_budget_callback({"search_offers": 1}, 1)
    ctx = _Ctx("inv-1")

    assert _call(cb, ctx, "search_offers") is None
    assert isinstance(_call(cb, ctx, "search_offers"), dict)

    ctx.invocation_id = "inv-2"  # next question, same session
    assert _call(cb, ctx, "search_offers") is None


def test_wired_limits_leave_room_for_a_geocode_retry_and_the_search() -> None:
    """The wiring itself is the guarantee — a flat cap would fail this."""
    cb = make_per_tool_budget_callback(PER_TOOL_CALL_LIMITS, MAX_TOOL_CALLS)
    ctx = _Ctx()

    assert _call(cb, ctx, "geocode_location") is None
    assert _call(cb, ctx, "geocode_location") is None
    assert _call(cb, ctx, "search_offers") is None
    assert _call(cb, ctx, "find_hotel_by_name") is None


def test_business_error_does_not_trip_the_breaker() -> None:
    """`retryable: False` = the backend answered; only the request needs refining."""
    ambiguous = {
        "isError": True,
        "structuredContent": {
            "error": {
                "kind": "AmbiguousHotelError",
                "message": 'Multiple hotels match "Singapour": ...',
                "retryable": False,
                "candidates": [{"hotelId": 1, "name": "QT Singapore"}],
            }
        },
    }
    assert _is_tool_failure(ambiguous) is False


def test_backend_failure_still_trips_the_breaker() -> None:
    unavailable = {
        "isError": True,
        "structuredContent": {
            "error": {
                "kind": "RepositoryUnavailableError",
                "message": "Search backend unavailable, please retry later",
                "retryable": True,
            }
        },
    }
    assert _is_tool_failure(unavailable) is True
    # No envelope at all (older MCP_B2C) → unchanged conservative behaviour.
    assert _is_tool_failure({"isError": True}) is True
    assert _is_tool_failure({"error": "boom"}) is True
