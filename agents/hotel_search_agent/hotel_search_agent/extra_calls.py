"""The MCP calls a search turn makes beyond the model's own (R2, review of #173).

The next-day probe (`datetime_resolver`), the zero-result rescue
(`relaxation`), the completion of a thin page (`completion`) and the local page
of the proximity ranking (`geo_rank`) call `search_offers` from inside callbacks
(`tool.run_async`). Those calls go through neither the per-tool budget nor the
MCP circuit breaker's callbacks, and they used to read an error or a 429 as
« empty » and go on to the next one. They now all go through here:

- **On error, stop.** A raised exception, or a response the breaker counts as
  a failure (`isError`, 429 included), is recorded on the breaker
  (`mcp_guard.breaker`), logged `status=error`, and ends every extra call of
  the turn — the rescue's next rung AND the completion: never a second call on
  a server that just refused one.
- **A time bound.** No extra call STARTS more than
  `EXTRA_CALLS_DEADLINE_SECONDS` after the leaf turn began
  (`stamp_turn_start`). The concierge waits 45 s for the search leaf (#168);
  its two model calls take ~2-5 s each (p95 5.1 s, prod) and are capped at
  2 × 15 s; an MCP call is capped at 5 s (`HOTEL_SEARCH_MCP_TIMEOUT_SECONDS`).
  With 20 s, the last extra call ends by ~25 s and the local page's wait
  (`geo_rank`, ≤ 2 s) is cut to what remains, so the leaf answers well within
  the 45 s on a normal turn — 4 searches in a row at 5 s each no longer can
  push an « aucune offre » into a timeout. A turn whose model calls already
  ate 20 s gets its first page only: honest, never a degraded turn.
- **The turn's deadline (2026-10-29).** The concierge stamps ONE deadline per
  turn and tells the leaf its budget for this call (A2A request metadata
  `dayuse_turn_budget_ms`, read by `stamp_turn_deadline`). An extra call
  starts only when it can end before it (its MCP timeout, 5 s, still fits),
  one still running at it is cut (`asyncio.wait_for`: an MCP that hangs past
  its own timeout, a stream that never closes), and no further one starts:
  the turn answers with the page it already has, before the concierge stops
  waiting — never a « search unavailable » over hotels found. The local
  page's wait (`geo_rank`) is cut to the same time left (`remaining_seconds`).
  Without the metadata (another caller), the deadline is
  `DEFAULT_TURN_BUDGET_SECONDS` after the turn's start.

Counts only in the logs (GDPR): kind, status, ms — never a place or a date.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from hotel_search_agent import mcp_guard
from hotel_search_agent.response_bridge import STATE_TURN_T0_KEY, read_structured_payload

_metrics_logger = logging.getLogger("dayuse.metrics")

EXTRA_CALLS_DEADLINE_SECONDS = float(os.environ.get("HOTEL_SEARCH_EXTRA_CALLS_DEADLINE_SECONDS", "20.0"))
#: The leaf's own deadline when the caller sent none: the concierge's default
#: wait (45 s) minus the second it keeps for the answer's way back.
DEFAULT_TURN_BUDGET_SECONDS = 44.0
#: The turn's deadline on this leaf's clock (`time.monotonic()`).
STATE_TURN_DEADLINE_KEY = "temp:hotel_search_turn_deadline"
#: The A2A request metadata key the concierge sends the budget in (ms).
TURN_BUDGET_METADATA_KEY = "dayuse_turn_budget_ms"
#: Set once an extra call failed or the deadline passed: no more extra call
#: this turn ("error" | "deadline").
STATE_EXTRA_CALLS_STOPPED_KEY = "temp:hotel_search_extra_calls_stopped"


def _now() -> float:
    return time.monotonic()


def _mcp_timeout_seconds() -> float:
    """The MCP call's own bound (`agent.build_connection_params`)."""
    return float(os.environ.get("HOTEL_SEARCH_MCP_TIMEOUT_SECONDS", "5.0"))


def stamp_turn_deadline(callback_context: Any) -> None:
    """`before_agent_callback`, after `stamp_turn_start`: the turn's deadline on
    this leaf's clock, from the budget the concierge sent with the request
    (relative, so two hosts' clocks never need to agree). Nothing when it sent
    none or an unusable one. Always returns None."""
    run_config = getattr(callback_context, "run_config", None)
    meta = (getattr(run_config, "custom_metadata", None) or {}).get("a2a_metadata") or {}
    budget_ms = meta.get(TURN_BUDGET_METADATA_KEY) if isinstance(meta, dict) else None
    if isinstance(budget_ms, bool) or not isinstance(budget_ms, (int, float)) or budget_ms < 0:
        return None
    callback_context.state[STATE_TURN_DEADLINE_KEY] = _now() + float(budget_ms) / 1000.0
    return None


def time_left(tool_context: Any) -> float:
    """Seconds before the turn's deadline (negative past it): the one the
    concierge sent, else `DEFAULT_TURN_BUDGET_SECONDS` after the turn's start,
    else that whole budget (a callback driven alone, in a test)."""
    state = tool_context.state
    deadline = state.get(STATE_TURN_DEADLINE_KEY)
    if isinstance(deadline, float):
        return deadline - _now()
    t0 = state.get(STATE_TURN_T0_KEY)
    if isinstance(t0, float):
        return DEFAULT_TURN_BUDGET_SECONDS - (_now() - t0)
    return DEFAULT_TURN_BUDGET_SECONDS


def remaining_seconds(tool_context: Any) -> float:
    """Seconds left to START an extra call (R2's window, from the turn's start)
    and to wait for one (the turn's deadline): the smaller; the full window
    when the turn's start was not stamped (a callback driven alone, in a test)."""
    t0 = tool_context.state.get(STATE_TURN_T0_KEY)
    window = EXTRA_CALLS_DEADLINE_SECONDS - (_now() - t0) if isinstance(t0, float) else EXTRA_CALLS_DEADLINE_SECONDS
    return min(window, time_left(tool_context))


def may_call(tool_context: Any) -> bool:
    """Whether one more extra call may START now: inside R2's window, and with
    time to end (its MCP timeout) before the turn's deadline."""
    state = tool_context.state
    if state.get(STATE_EXTRA_CALLS_STOPPED_KEY):
        return False
    if remaining_seconds(tool_context) <= 0 or time_left(tool_context) < _mcp_timeout_seconds():
        state[STATE_EXTRA_CALLS_STOPPED_KEY] = "deadline"
        return False
    if not mcp_guard.breaker.allow():
        state[STATE_EXTRA_CALLS_STOPPED_KEY] = "error"
        return False
    return True


def record_outcome(tool_context: Any, response: Any, error: Exception | None = None) -> bool:
    """Feeds the breaker with one extra call's outcome; True when it failed
    (then no more extra call this turn)."""
    failed = error is not None or mcp_guard.is_tool_failure(response)
    if failed:
        mcp_guard.breaker.record_failure()
        tool_context.state[STATE_EXTRA_CALLS_STOPPED_KEY] = "error"
    else:
        mcp_guard.breaker.record_success()
    return failed


async def extra_call(
    tool: Any, args: dict[str, Any], tool_context: Any, *, kind: str
) -> tuple[str, dict[str, Any] | None]:
    """One extra `search_offers` call: ("ok", payload), ("error", None) or
    ("skipped", None) when it may not start (stopped, deadline, breaker open).
    Cut at the turn's deadline: ("deadline", None), and no extra call after it
    — a cut is not the server's failure, the breaker is not fed."""
    if not may_call(tool_context):
        _log(kind, "skipped", None)
        return "skipped", None
    started = _now()
    try:
        response = await asyncio.wait_for(
            tool.run_async(args=args, tool_context=tool_context), timeout=max(0.0, time_left(tool_context))
        )
    except asyncio.TimeoutError:
        tool_context.state[STATE_EXTRA_CALLS_STOPPED_KEY] = "deadline"
        _log(kind, "deadline", started)
        return "deadline", None
    except Exception as exc:  # noqa: BLE001 — an extra call never breaks the turn
        record_outcome(tool_context, None, exc)
        _log(kind, "error", started)
        return "error", None
    if record_outcome(tool_context, response):
        _log(kind, "error", started)
        return "error", None
    payload = read_structured_payload(response)
    _log(kind, "ok", started)
    return "ok", payload if isinstance(payload, dict) else None


def _log(kind: str, status: str, started: float | None) -> None:
    _metrics_logger.info(
        "dayuse_metric=extra_search_call agent=b2c_hotel_search kind=%s status=%s ms=%d",
        kind, status, int((_now() - started) * 1000) if started is not None else -1,
    )
