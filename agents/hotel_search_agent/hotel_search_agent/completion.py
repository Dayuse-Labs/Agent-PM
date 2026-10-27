"""A thin first page is completed from one wider search.

Prod session 1eb2430a (2026-10-27): the landmark ring is sized on the raw
inventory (`site_radius_km`: the smallest ring holding 10 hotels), not on the
hotels matching the search. With a pool, a spa and a €300 cap, the 2 and 5 km
rings returned 1 and 0 hotels while 18 and 19 matched within 20 km. The site
counts the hotels matching the query, then completes page 1 up to 50 km
(`HotelElasticSearchService::processSearchQueryToCompleteSearchPage`).

Same here, from code: when the first page holds fewer than `MAX_RESULTS`
hotels, ONE more `search_offers` call runs on `COMPLETION_RADIUS_KM` (the
nearby ring when the user asked to widen), nearest first, and without the
optional wishes (`amenities_preferred`: « idéalement un massage »).
`capture_after_tool` appends its hotels after the first page's. No LLM call:
the turn's 3-slot budget is unchanged.

Same pattern as `datetime_resolver.probe_next_day_after_tool`: the args were
already rewritten by the before-tool callbacks, `tool.run_async` re-enters no
callback, any failure is swallowed, and it always returns None. The two never
both fire: a same-day dead end (hotels exist, every offer past its cutoff) is
the D+1 probe's, and a wider ring would not reopen it.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from hotel_search_agent.equipment_ids import equipment_ids_for
from hotel_search_agent.response_bridge import (
    MAX_RESULTS,
    NEARBY_RADIUS_KM,
    SITE_RADII_KM,
    STATE_APPLIED_AMENITIES_KEY,
    STATE_COMPLETION_KEY,
    STATE_NEARBY_KEY,
    STATE_PREFERRED_AMENITIES_KEY,
    STATE_SEARCH_DATE_KEY,
    read_structured_payload,
)
from hotel_search_agent.schema_guard import drop_args_outside_schema

#: The site's widest ring, also where it completes a thin page.
COMPLETION_RADIUS_KM = SITE_RADII_KM[-1]
#: MCP's own radius when `radiusKm` is absent (a city search).
_MCP_DEFAULT_RADIUS_KM = 20.0

_metrics_logger = logging.getLogger("dayuse.metrics")


def _same_day_dead_end(state: Any, structured: dict[str, Any], results: list) -> bool:
    search_date = state.get(STATE_SEARCH_DATE_KEY)
    if results or not isinstance(search_date, dict) or not search_date.get("same_day"):
        return False
    try:
        return int(structured.get("total") or 0) > 0
    except (TypeError, ValueError):
        return False


async def complete_thin_search_after_tool(
    tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any
) -> None:
    """`after_tool_callback`, placed before `capture_after_tool`, which
    consumes what it stashes. Always returns None (a truthy return would break
    the after-tool chain)."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    if not isinstance(tool_response, dict) or tool_response.get("isError"):
        return None
    if tool_response.get("ok") is False or tool_response.get("error"):
        return None
    if args.get("from"):
        return None  # a later page: the first one was already completed
    structured = read_structured_payload(tool_response)
    if not isinstance(structured, dict):
        return None
    results = structured.get("results") or []
    if len(results) >= MAX_RESULTS or _same_day_dead_end(tool_context.state, structured, results):
        return None
    state = tool_context.state
    preferred = list(state.get(STATE_PREFERRED_AMENITIES_KEY) or [])
    sent_radius = args.get("radiusKm") or _MCP_DEFAULT_RADIUS_KM
    radius = max(NEARBY_RADIUS_KM if state.get(STATE_NEARBY_KEY) else COMPLETION_RADIUS_KM, sent_radius)
    if not preferred and radius <= sent_radius:
        return None  # nothing to relax
    completion_args = {key: value for key, value in args.items() if key != "from"}
    completion_args["radiusKm"] = radius
    completion_args["sortBy"] = "distance"
    ids = equipment_ids_for(list(state.get(STATE_APPLIED_AMENITIES_KEY) or []))
    if ids:
        completion_args["hotelEquipmentIds"] = ids
    else:
        completion_args.pop("hotelEquipmentIds", None)
    drop_args_outside_schema(tool, completion_args, tool_context)
    started = time.monotonic()
    try:
        response = await tool.run_async(args=completion_args, tool_context=tool_context)
    except Exception:  # noqa: BLE001 — a completion never breaks the turn
        _log("error", started, len(results), 0)
        return None
    payload = read_structured_payload(response)
    found = payload.get("results") if isinstance(payload, dict) else None
    if not found:
        _log("empty", started, len(results), 0)
        return None
    state[STATE_COMPLETION_KEY] = {"payload": payload, "radius_km": radius, "relaxed": preferred}
    _log("ok", started, len(results), len(found))
    return None


def _log(status: str, started: float, first: int, found: int) -> None:
    # Counts only, never a place or an amenity (GDPR, same as the D+1 probe).
    _metrics_logger.info(
        "dayuse_metric=search_completion agent=b2c_hotel_search status=%s first=%d found=%d ms=%d",
        status, first, found, int((time.monotonic() - started) * 1000),
    )
