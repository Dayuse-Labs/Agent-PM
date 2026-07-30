"""tool_budget_guard — per-TOOL call budget for this leaf (prod 2026-07-29).

The fleet's `make_tool_budget_callback` counts every tool call in ONE flat
counter. This leaf's nominal turn already spends exactly two calls
(`geocode_location` then `search_offers`), so with the historical flat cap of 2 a
single failed geocode consumed the whole budget and the MCP search was
short-circuited before it ever ran:

    tool=geocode_location ms=78 status=error error_type=tool_returned_error
    tool=geocode_location ms=57 status=ok
    tool=search_offers    ms=0  status=ok  budget_stopped=true   <-- never ran

The leaf then returned no results and the concierge answered with its honest
degradation ("je n'arrive pas à joindre la recherche d'hôtels à Singapore") — an
outage that never happened, for a search that MCP_B2C answers in ~0,7 s. It hit
destinations whose first geocode attempt fails ("SG", "Singapour") far more often
than a one-shot city like "Paris", which is why it read as Singapore-specific.

Counting per tool keeps the anti-loop guarantee the flat budget was built for —
each tool stays hard-capped, "1 retry borné" — while making it impossible for a
geocode retry to starve the search. The stop directive keeps the fleet's
`TOOL BUDGET` prefix: that string is what `dayuse_agent_common.metrics` matches to
flag `budget_stopped=true`, so the metric keeps working unchanged.

Wired as an ADK `before_tool_callback`: returning a dict skips the tool and the
dict becomes the tool result; returning None lets the call proceed.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from b2c_common.observability import mark_level

# Same "TOOL BUDGET" prefix as the fleet's directive — `metrics.tool_metric_after`
# flags `budget_stopped` on exactly that prefix. Wording names the ONE tool that
# is capped, so the model retries a DIFFERENT step instead of giving up entirely.
STOP_MESSAGE = (
    "TOOL BUDGET EXHAUSTED for this tool — you have already called it enough times "
    "for this question. Do NOT call it again. Use the other tools you still need, or "
    "answer from what you have already retrieved."
)

_INV_KEY = "_per_tool_budget_inv"
_COUNTS_KEY = "_per_tool_budget_counts"


def make_per_tool_budget_callback(
    limits: Mapping[str, int], default_limit: int, stop_message: str = STOP_MESSAGE
) -> Callable[[Any, dict[str, Any], Any], Optional[dict]]:
    """A `before_tool_callback` capping each tool NAME at its own budget.

    `limits` holds the per-tool caps; any tool not listed falls back to
    `default_limit`. Counters live in session state namespaced by
    `invocation_id` and reset when it changes, so one question never inherits
    another's count (same contract as the fleet callback it replaces).
    """

    def before_tool(tool: Any, args: dict[str, Any], tool_context: Any) -> Optional[dict]:
        state = tool_context.state
        if state.get(_INV_KEY) != tool_context.invocation_id:
            state[_INV_KEY] = tool_context.invocation_id
            state[_COUNTS_KEY] = {}
        name = str(getattr(tool, "name", "") or "")
        # Reassigned (not mutated in place): ADK state tracks writes by key.
        counts = dict(state.get(_COUNTS_KEY) or {})
        counts[name] = counts.get(name, 0) + 1
        state[_COUNTS_KEY] = counts
        if counts[name] > limits.get(name, default_limit):
            mark_level("WARNING", status_message="tool_budget_exhausted")
            return {"ok": False, "error": stop_message}
        return None

    return before_tool
