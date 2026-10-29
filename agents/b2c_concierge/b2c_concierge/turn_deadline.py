"""One absolute deadline per turn, set when the turn starts (2026-10-29).

Before, each stage owned a duration of its own (triage 2 x 4 s, leaf 45 s,
synthesis 2 x 15 s, the leaf's extra searches « within 20 s of the leaf
turn's start »): nothing tied them to one end, so a stage could start work
the next one would never wait for — a leaf still searching after the
concierge had answered « search unavailable », a synthesis started with no
time left to finish — and a leaf that failed was counted `leaf_call
status=ok` (CHANTIERS O7).

Now the concierge stamps `deadline = start + TURN_DEADLINE_SECONDS` and every
stage derives its budget from what is left:

- the leaf gets `min(its own budget, time left - SYNTHESIS_RESERVE_SECONDS)`,
  and is TOLD it (A2A request metadata `dayuse_turn_budget_ms`, never in the
  model's prompt) minus `LEAF_RETURN_GRACE_SECONDS`: it starts no extra
  search that cannot end before it, cuts one still running at it, and
  answers with what it already found (`hotel_search_agent.extra_calls`);
- the synthesis is bounded by the time left, and does not start under
  `SYNTHESIS_FLOOR_SECONDS`: the cards are already on screen, the answer is
  the leaf's own outcome line in code (`synthesis_fallback_text`).

60 s by default: the widget proxy cuts a stream silent for 60 s, and the
budgets inside fit as before — triage <= 8 s, leaf <= 45 s, then the
synthesis gets what is left. A normal turn (p90 ~12 s) never sees it; a turn
that would have gone past it now ends with what was found.
"""
from __future__ import annotations

import os
import time
from contextvars import ContextVar

#: The leaf's budget for the call in flight, in ms, read by the A2A request
#: metadata provider (`agent._leaf_request_meta`) — set and reset by
#: `_run_leaf` around the one call.
LEAF_BUDGET_MS: ContextVar[int | None] = ContextVar("b2c_leaf_budget_ms", default=None)

#: Below this, no synthesis call starts: an answer in code instead.
SYNTHESIS_FLOOR_SECONDS = 2.0
#: What the leaf hands back after its own deadline: the DataPart's way home.
LEAF_RETURN_GRACE_SECONDS = 1.0


def turn_deadline_seconds() -> float:
    """Read at call time (tests set it with monkeypatch.setenv)."""
    return float(os.environ.get("CONCIERGE_TURN_DEADLINE_SECONDS", "60.0"))


def synthesis_reserve_seconds() -> float:
    """Kept for the synthesis when the leaf's budget is cut by the deadline."""
    return float(os.environ.get("CONCIERGE_SYNTHESIS_RESERVE_SECONDS", "8.0"))


def turn_deadline(t_start: float) -> float:
    return t_start + turn_deadline_seconds()


def time_left(deadline: float | None) -> float | None:
    """Seconds before the deadline (negative past it), None without one."""
    if deadline is None:
        return None
    return deadline - time.monotonic()


def leaf_budget(own_budget: float, deadline: float | None) -> float:
    """The leaf's wait: its own budget, cut so the synthesis keeps its reserve."""
    left = time_left(deadline)
    if left is None:
        return own_budget
    return min(own_budget, left - synthesis_reserve_seconds())
