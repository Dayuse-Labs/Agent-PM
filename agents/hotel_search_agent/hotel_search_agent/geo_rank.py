"""Proximity first, at comparable quality, for a search around a city or a device fix.

Prod 2026-10-27/28 (262 searches with hotels since the switch): for the SAME
cities AgentB2C showed hotels much further from the centre than agent-usa
(median of the 5 cards, city searches: Paris 1.1 → 7.5 km, London 1.4 → 9.4,
Rome 2.7 → 11.4, Los Angeles 3.8 → 18.2). Not the supply: « Paris » alone sends
`search_offers` without `radiusKm` nor `sortBy`, so MCP ranks ~500 hotels of
the whole 20 km disc by `score` (relevance, which ignores distance) and the
leaf keeps its first page: Gennevilliers 10.7 km, Antony 11.3 km; « London »
gives Brentford 13 km, Croydon 15 km and no central card; Los Angeles with a
pool puts The Delphi Hotel (0.4 km) 4th behind Marina del Rey (19 km).

What agent-usa did (`search_tool.py::_apply_final_geo_order`): a pool of
candidates around the anchor, then ONE order invariant — tiers local / nearby /
alternative, and inside a tier a quality score with a gradual distance penalty:
« no later stable sort may put a distant comparable card ahead of a local one ».

Here, from facts only (no word of the message is read):
- the pool: the page the model's call returns (MCP's relevance order over
  the whole disc, 20 km for a city), plus the page of the SAME search (same
  filters, date, offset) on the local disc only, fetched IN PARALLEL with it
  (`start_local_pool`, a before-tool callback, launches it; `await_local_pool`,
  an after-tool callback, collects it within `POOL_WAIT_SECONDS`). One MCP
  call more; the turn only waits for whatever the local page takes beyond the
  search's own (measured live on 6 cities: 0 to 0.9 s). MCP's `score` is the same
  for a hotel whatever the radius or the sort (probed live 2026-10-28), so the
  two pages compare. The local page is in relevance order, not nearest first:
  the 5 nearest hotels of Paris, London or München cost 0.1 to 0.3 of average
  rating (probed), the 5 most relevant within 5 km keep it.
- the local radius, from the place: the smallest ring of the site's that holds
  10 inventory hotels (`site_radius_km`, the same density signal as the POI
  ring), never under `LOCAL_FLOOR_KM` — 5 km in Paris, London, Rome, Lille,
  München, Los Angeles; 50 km around Galveston, where nothing changes.
- the order (`rank_pool`): local (≤ local radius) before nearby (≤ 35 km, or
  twice the local radius) before alternative; inside a tier, MCP's `score`
  divided by `1 + distance / local radius`.

Only for an anchor whose centre means something: a city centroid of a city
(`place`/`locality`, not a region or a département carried as an area) or a
device fix. A landmark/district/address is already searched nearest first in
its own ring (`inject_landmark_radius`), a « nearby area » asks for further, a
nearest-first rescue already is nearest first: none of them is touched. A
sparse place whose local radius covers the whole search disc needs no second
call: the relevance page is reordered on its own.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from typing import Any

from hotel_search_agent.extra_calls import may_call, record_outcome, remaining_seconds
from hotel_search_agent.inventory import haversine_km
from hotel_search_agent.response_bridge import (
    STATE_NEARBY_KEY,
    anchor_feature,
    anchor_origin,
    read_structured_payload,
    site_radius_km,
)

_metrics_logger = logging.getLogger("dayuse.metrics")

#: Never call a ring tighter than this « local » for a city: a dense centre
#: (Paris: 123 inventory hotels within 2 km) still has a local area wider than
#: its densest ring.
LOCAL_FLOOR_KM = 5.0
#: agent-usa's `GEO_FAR_FALLBACK_DISTANCE_KM`: beyond it a card is an
#: alternative, whatever the place.
NEARBY_FLOOR_KM = 35.0
#: MCP's own radius when `radiusKm` is absent (a city search).
MCP_DEFAULT_RADIUS_KM = 20.0
#: How long the local page may still take once the search's own page is back.
POOL_WAIT_SECONDS = float(os.environ.get("HOTEL_SEARCH_GEO_POOL_WAIT_SECONDS", "2.0"))

#: Geocoder feature types whose centroid is a city centre. A region, a
#: département or a country carried as an area has an arbitrary centroid
#: (its main city's): its relevance order stays.
_CITY_FEATURE_TYPES = frozenset({"place", "locality"})

#: Local pages in flight, by tool context (the same object reaches the
#: before- and the after-tool callbacks of one call). Bounded: a call that
#: raised past every callback leaves its entry, the oldest go first.
_PENDING: dict[int, asyncio.Task] = {}
_MAX_PENDING = 64

#: The local page's raw results, from `await_local_pool` to
#: `ranked_payload`, for ONE call: cleared when a call starts and once read.
STATE_GEO_POOL_KEY = "temp:hotel_search_geo_pool"


def local_radius_km(lat: float, lon: float) -> float:
    """The radius a card counts as local within, from the inventory around
    the anchor (dense centre → `LOCAL_FLOOR_KM`, sparse place → wider)."""
    return max(LOCAL_FLOOR_KM, site_radius_km(lat, lon))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _distance(item: dict[str, Any], lat: float, lon: float) -> float | None:
    """From the anchor: measured on the hotel's coordinates, else MCP's
    `distanceKm` (measured from the search point, which is the anchor)."""
    h_lat, h_lon = _number(item.get("lat")), _number(item.get("lon"))
    if h_lat is not None and h_lon is not None:
        return haversine_km(lat, lon, h_lat, h_lon)
    return _number(item.get("distanceKm"))


def tier(distance: float | None, local_km: float) -> int:
    """0 local, 1 nearby, 2 alternative (or no distance at all)."""
    if distance is None:
        return 2
    if distance <= local_km:
        return 0
    if distance <= max(NEARBY_FLOOR_KM, 2 * local_km):
        return 1
    return 2


def rank_pool(
    items: list[dict[str, Any]], lat: float, lon: float, local_km: float
) -> list[dict[str, Any]]:
    """The pool, each hotel once (first occurrence kept), in the order the
    cards are cut from: tier first, then MCP's score with a gradual distance
    penalty; ties keep MCP's own order (a stable sort). A hotel with no score
    ranks last of its tier."""
    seen: set[Any] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("hotelId", id(item))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    def order(item: dict[str, Any]) -> tuple[int, float]:
        distance = _distance(item, lat, lon)
        score = _number(item.get("score")) or 0.0
        weighted = score / (1.0 + (distance if distance is not None else local_km) / local_km)
        return tier(distance, local_km), -weighted

    return sorted(unique, key=order)


def _qualifies(args: dict[str, Any], tool_context: Any) -> tuple[float, float, float] | None:
    """(lat, lon, local radius) when this search's cards are ranked here."""
    if args.get("sortBy") or tool_context.state.get(STATE_NEARBY_KEY):
        return None  # already nearest first, or the user asked for further
    origin = anchor_origin(tool_context)
    if origin is None:
        return None
    anchor_type, lat, lon = origin
    if anchor_type == "city_centroid":
        if anchor_feature(tool_context) not in _CITY_FEATURE_TYPES:
            return None
    elif anchor_type != "gps":
        return None
    return lat, lon, local_radius_km(lat, lon)


def start_local_pool(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback`, LAST (the args are final): launch the same
    search on the local disc, next to it. Always returns None."""
    if getattr(tool, "name", "") != "search_offers" or not hasattr(tool, "run_async"):
        return None
    tool_context.state[STATE_GEO_POOL_KEY] = None  # never a previous call's page
    qualified = _qualifies(args, tool_context)
    if qualified is None:
        return None
    _lat, _lon, local_km = qualified
    radius = _number(args.get("radiusKm")) or MCP_DEFAULT_RADIUS_KM
    if local_km >= radius:
        _log("skip_sparse", None, local_km)
        return None  # the whole disc is local: its own page says it all
    if not may_call(tool_context):
        return None  # R2: after an extra call failed, or past the deadline
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    while len(_PENDING) >= _MAX_PENDING:
        _PENDING.pop(next(iter(_PENDING))).cancel()
    _PENDING[id(tool_context)] = loop.create_task(
        tool.run_async(args={**args, "radiusKm": local_km}, tool_context=tool_context)
    )
    return None


async def await_local_pool(
    tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any
) -> None:
    """`after_tool_callback`, before `capture_after_tool`: collect the local
    page (bounded wait) and stash its results for `ranked_payload`. Any
    failure keeps the search's own page alone. Always returns None."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    task = _PENDING.pop(id(tool_context), None)
    if task is None:
        return None
    started = time.monotonic()
    failed = not isinstance(tool_response, dict) or bool(
        tool_response.get("isError") or tool_response.get("error") or tool_response.get("ok") is False
    )
    if failed:
        task.cancel()
        return None
    # R2 (review of #173): the wait never runs past the extra calls' deadline.
    wait = min(POOL_WAIT_SECONDS, max(0.0, remaining_seconds(tool_context)))
    try:
        local = await asyncio.wait_for(task, timeout=wait)
    except asyncio.TimeoutError:
        _log("timeout", started, None)
        return None
    except Exception as exc:  # noqa: BLE001 — a second page never breaks the turn
        record_outcome(tool_context, None, exc)
        _log("error", started, None)
        return None
    if record_outcome(tool_context, local):
        _log("error", started, None)
        return None
    payload = read_structured_payload(local)
    found = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(found, list) or not found:
        _log("empty", started, None)
        return None
    tool_context.state[STATE_GEO_POOL_KEY] = found
    _log("ok", started, None)
    return None


def ranked_payload(tool_context: Any, args: dict[str, Any], structured: dict[str, Any]) -> dict[str, Any]:
    """`structured` with its `results` replaced by the ranked pool (its own
    page plus the local page, when one came back), for a qualifying search;
    `structured` itself otherwise."""
    qualified = _qualifies(args, tool_context)
    if qualified is None:
        return structured
    lat, lon, local_km = qualified
    page = structured.get("results")
    if not isinstance(page, list):
        return structured
    extra = tool_context.state.get(STATE_GEO_POOL_KEY)
    tool_context.state[STATE_GEO_POOL_KEY] = None
    pool = list(page) + (list(extra) if isinstance(extra, list) else [])
    ranked = rank_pool(pool, lat, lon, local_km)
    _metrics_logger.info(
        "dayuse_metric=geo_rank agent=b2c_hotel_search local_km=%s pool=%d page=%d local=%d",
        local_km, len(ranked), len(page),
        sum(1 for item in ranked[: len(page)] if tier(_distance(item, lat, lon), local_km) == 0),
    )
    return {**structured, "results": ranked}


def _log(status: str, started: float | None, local_km: float | None) -> None:
    # Counts only, never a place (GDPR, same as the D+1 probe and the completion).
    # `ms` is the wait AFTER the search's own page came back: the added latency.
    _metrics_logger.info(
        "dayuse_metric=geo_pool agent=b2c_hotel_search status=%s ms=%d local_km=%s",
        status, int((time.monotonic() - started) * 1000) if started is not None else 0,
        local_km if local_km is not None else "-",
    )
