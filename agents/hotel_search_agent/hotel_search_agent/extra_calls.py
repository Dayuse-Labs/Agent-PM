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

Counts only in the logs (GDPR): kind, status, ms — never a place or a date.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from hotel_search_agent import mcp_guard
from hotel_search_agent.response_bridge import STATE_TURN_T0_KEY, read_structured_payload

_metrics_logger = logging.getLogger("dayuse.metrics")

EXTRA_CALLS_DEADLINE_SECONDS = float(os.environ.get("HOTEL_SEARCH_EXTRA_CALLS_DEADLINE_SECONDS", "20.0"))
#: Set once an extra call failed or the deadline passed: no more extra call
#: this turn ("error" | "deadline").
STATE_EXTRA_CALLS_STOPPED_KEY = "temp:hotel_search_extra_calls_stopped"


def _now() -> float:
    return time.monotonic()


def remaining_seconds(tool_context: Any) -> float:
    """Seconds left before the deadline; the full budget when the turn's start
    was not stamped (a callback driven alone, in a test)."""
    t0 = tool_context.state.get(STATE_TURN_T0_KEY)
    if not isinstance(t0, float):
        return EXTRA_CALLS_DEADLINE_SECONDS
    return EXTRA_CALLS_DEADLINE_SECONDS - (_now() - t0)


def may_call(tool_context: Any) -> bool:
    """Whether one more extra call may START now."""
    state = tool_context.state
    if state.get(STATE_EXTRA_CALLS_STOPPED_KEY):
        return False
    if remaining_seconds(tool_context) <= 0:
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
    ("skipped", None) when it may not start (stopped, deadline, breaker open)."""
    if not may_call(tool_context):
        _log(kind, "skipped", None)
        return "skipped", None
    started = _now()
    try:
        response = await tool.run_async(args=args, tool_context=tool_context)
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
