"""One extra small page when a grounded cap rejects the first retrieved page.

MCP's price filter is EUR, while a customer's cap may be another currency.
Keep native fee-inclusive filtering, but do not equate five expensive nearby
hotels with no affordable inventory. Raw pages stay at five (transport limit),
the existing per-tool quota owns the extra read, and the model still sees five
compact cards. This is a bounded sample, never exhaustive availability.
"""
from __future__ import annotations

import math
from typing import Any, Awaitable

from hotel_search_agent.area_scope import STATE_AREAS
from hotel_search_agent.response_bridge import (
    normalize_search_results,
    read_profile_in,
    read_structured_payload,
)
from hotel_search_agent.tool_budget_guard import STOP_MESSAGE, reserve_mcp_read


def search_budget_pages_before_tool(tool: Any, args: dict[str, Any], tool_context: Any) -> Awaitable[dict] | dict | None:
    if getattr(tool, "name", "") != "search_offers" or tool_context.state.get(STATE_AREAS):
        return None  # Area searches already own their bounded retrieval batch.
    # This callback is after all local argument/origin guards. Reserve every
    # real search dispatch, even without a cap, so a second model call cannot
    # bypass pages already consumed by a deterministic budget search.
    if not reserve_mcp_read(tool_context, "search_offers"):
        return {"ok": False, "error": STOP_MESSAGE}
    profile = read_profile_in(tool_context)
    cap = profile.get("requested_budget")
    if not isinstance(cap, dict) or cap.get("unit") != "total":
        return None
    amount, currency = cap.get("amount"), cap.get("currency")
    if (isinstance(amount, bool) or not isinstance(amount, (int, float))
            or not math.isfinite(amount) or amount <= 0
            or not isinstance(currency, str) or len(currency) != 3):
        return None
    return _search(tool, args, tool_context, cap, profile)


async def _search(tool: Any, args: dict[str, Any], ctx: Any, cap: dict, profile: dict) -> dict:
    # All location/date/window/occupancy/equipment guards have already run.
    query = {**args, "size": 5}
    first = await tool.run_async(args=query, tool_context=ctx)
    payload = read_structured_payload(first)
    if not isinstance(first, dict) or first.get("isError") or first.get("ok") is False:
        return first
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return first
    excluded = set(profile.get("shown_hotel_ids") or []) if profile.get("search_cursor") else None
    if normalize_search_results(payload, excluded, requested_budget=cap):
        return first
    offset = payload.get("next_offset")
    current = query.get("from", 0)
    if (payload.get("has_more") is not True or not payload["results"]
            or isinstance(offset, bool) or not isinstance(offset, int)
            or not isinstance(current, int) or offset != current + 5
            or not reserve_mcp_read(ctx, "search_offers")):
        return first
    second = await tool.run_async(args={**query, "from": offset}, tool_context=ctx)
    next_payload = read_structured_payload(second)
    if not isinstance(second, dict) or second.get("isError") or second.get("ok") is False:
        return second
    if (not isinstance(next_payload, dict) or not isinstance(next_payload.get("results"), list)
            or next_payload.get("resolvedDate") != payload.get("resolvedDate")):
        return {"ok": False, "error": "Budget search page could not be verified."}
    # Existing normalization excludes shown identities and filters every offer
    # against the same cap BEFORE its five-card cut. Keep server totals as raw
    # retrieval metadata; they are not affordable/bookable counts.
    return {"structuredContent": {**next_payload,
                                  "results": payload["results"] + next_payload["results"]}}
