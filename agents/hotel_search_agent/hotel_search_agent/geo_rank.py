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
  divided by `1 + distance / decay radius`.

2026-10-29 (side-by-side with agent-usa on 22 identical requests, prod
2026-10-29: « un hôtel à Paris demain » gave 3.2-5.1 km — Ivry, Malakoff, Porte
d'Italie — where agent-usa showed five hotels at 1.3-1.8 km):
- MCP's pages hold 5 hotels (`size` defaults to 5, probed), so the local page
  was the 5 most relevant hotels of the whole 5 km disc: MCP's `score` favours
  the inner suburbs (Paris: 1.0-1.2 at 3-5 km, 0.8-0.85 inside 2 km, ratings
  alike, 4.5-4.8 — probed 2026-10-29), and the centre never reached the pool.
  A THIRD page now runs with the two others: the same search on the CORE ring
  (`core_radius_km`: the site's smallest ring holding 10 inventory hotels,
  2 km in every dense centre measured), in relevance order — the best of the
  centre, not merely the nearest (the 5 nearest of Paris cost 0.1-0.3 of
  average rating). Skipped when that ring is the local disc already (Los
  Angeles, Beverly Hills, Miami: 5 km).
- the distance penalty starts at 0 km and its scale is the core ring
  (`decay radius`): 2 km in a dense centre, so a card 2 km further must score
  twice as high to come first. agent-usa's − 1.25 point/km sits on its own
  0-100 compatibility score; on MCP's score, whose suburb/centre gap is 25-40 %
  for the same ratings, an additive 1.25 %/km lets every suburb of the probe
  win again (computed on the Paris, London, Rome, Milano pages).
- the invariant, stated: a card never comes before a NEARER card of the same
  or a nearer tier whose score is at least as high (`rank_pool`).
- a far card is not the filler of a central page: once the cards hold
  `MIN_LOCAL_CARDS` local hotels, none beyond twice the local radius is shown
  (`trim_far_cards`; Madrid with a pool: four hotels within 5 km, then Getafe
  at 12 km as the fifth card).
- the wait for those pages is the extra calls' own budget (`extra_calls`, R2
  of #173), capped at `POOL_WAIT_SECONDS` (MCP's own 5 s call timeout), no
  longer 2 s: a 2 s cut dropped the local page on a slow MCP answer, and the
  relevance page alone went on screen (Beverly Hills, prod 2026-10-28: one
  card at 3 km, then Downtown, LAX, Burbank at 13-17 km).
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from typing import Any

from hotel_search_agent.extra_calls import extra_call, may_call, record_outcome, remaining_seconds
from hotel_search_agent.inventory import haversine_km
from b2c_common.pricing import display_price_euro

from hotel_search_agent.response_bridge import (
    STATE_NEARBY_KEY,
    STATE_PRIORITY_KEY,
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
#: The most the local pages may still take once the search's own page is back:
#: MCP's own call timeout (`HOTEL_SEARCH_MCP_TIMEOUT_SECONDS`, 5 s), never past
#: the extra calls' deadline (`extra_calls.remaining_seconds`).
POOL_WAIT_SECONDS = float(os.environ.get("HOTEL_SEARCH_GEO_POOL_WAIT_SECONDS", "5.0"))
#: Local cards from which no far card (beyond twice the local radius) is shown.
MIN_LOCAL_CARDS = 3

#: Geocoder feature types whose centroid is a city centre. A region, a
#: département or a country carried as an area has an arbitrary centroid
#: (its main city's): its relevance order stays.
_CITY_FEATURE_TYPES = frozenset({"place", "locality"})

#: Local pages in flight, by tool context (the same object reaches the
#: before- and the after-tool callbacks of one call). Bounded: a call that
#: raised past every callback leaves its entry, the oldest go first.
_PENDING: dict[int, list[asyncio.Task]] = {}
_MAX_PENDING = 64

#: The local page's raw results, from `await_local_pool` to
#: `ranked_payload`, for ONE call: cleared when a call starts and once read.
STATE_GEO_POOL_KEY = "temp:hotel_search_geo_pool"
#: The anchor and local radius the cards of THIS call were ranked around
#: ({lat, lon, local_km}), for `trim_far_cards`; None when not ranked here.
STATE_GEO_RANK_KEY = "temp:hotel_search_geo_rank"


def core_radius_km(lat: float, lon: float) -> float:
    """The centre of the place, from the inventory around the anchor: the
    site's smallest ring holding 10 hotels (2 km in a dense centre). The
    distance penalty's scale, and the ring of the core page."""
    return site_radius_km(lat, lon)


def local_radius_km(lat: float, lon: float) -> float:
    """The radius a card counts as local within, from the inventory around
    the anchor (dense centre → `LOCAL_FLOOR_KM`, sparse place → wider)."""
    return max(LOCAL_FLOOR_KM, core_radius_km(lat, lon))


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


def cheapest_price(item: dict[str, Any]) -> float:
    """The lowest price the customer is shown among a hotel's offers (EUR
    cents, `display_price_euro`), +inf when none."""
    prices = [
        display_price_euro(offer, item) for offer in item.get("offers") or [] if isinstance(offer, dict)
    ]
    numbers = [float(p) for p in prices if isinstance(p, (int, float)) and not isinstance(p, bool) and p > 0]
    return min(numbers) if numbers else math.inf


def rank_pool(
    items: list[dict[str, Any]], lat: float, lon: float, local_km: float,
    decay_km: float | None = None, priority: str | None = None,
) -> list[dict[str, Any]]:
    """The pool, each hotel once (first occurrence kept), in the order the
    cards are cut from: tier first, then MCP's score with a gradual distance
    penalty, `score / (1 + distance / decay_km)` (`decay_km`: the core ring,
    else the local radius); ties keep MCP's own order (a stable sort). A hotel
    with no score ranks last of its tier.

    The invariant this order holds: a card never comes before a nearer card of
    the same or a nearer tier whose score is at least as high."""
    decay = decay_km if decay_km and decay_km > 0 else local_km
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

    def order(item: dict[str, Any]) -> tuple[int, float, float]:
        distance = _distance(item, lat, lon)
        score = _number(item.get("score")) or 0.0
        weighted = score / (1.0 + (distance if distance is not None else local_km) / decay)
        # 2026-10-30: what the user put first (« le moins cher ») orders each
        # ring of distance; the ring itself stays first.
        first = cheapest_price(item) if priority == "price" else 0.0
        return tier(distance, local_km), first, -weighted

    return sorted(unique, key=order)


def prioritize_cards(tool_context: Any, cards: list[dict[str, Any]], ring_km: float | None) -> list[dict[str, Any]]:
    """The cards of a search not ranked here (a spot, a district, an area),
    reordered by what the user put first inside each ring of distance
    (`tier`, the search's own ring as the local one): « le moins cher » near a
    station puts the cheapest of the nearest first. Cards as they are
    otherwise. Stable: equal prices keep their order."""
    if tool_context.state.get(STATE_PRIORITY_KEY) != "price" or len(cards) < 2:
        return cards
    # The search's own ring is the local one when it is a spot's (2-10 km);
    # a wide ring the user gave (« 50 km max ») keeps the local disc of a city.
    local = ring_km if ring_km and 0 < ring_km <= 2 * LOCAL_FLOOR_KM else LOCAL_FLOOR_KM

    def price(card: dict[str, Any]) -> float:
        cents = card.get("price_eur_cents")
        return float(cents) if isinstance(cents, int) and not isinstance(cents, bool) and cents > 0 else math.inf

    return sorted(cards, key=lambda card: (tier(_number(card.get("distance_km")), local), price(card)))


def _qualifies(args: dict[str, Any], tool_context: Any) -> tuple[float, float, float, float] | None:
    """(lat, lon, local radius, core ring) when this search's cards are ranked here."""
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
    core_km = core_radius_km(lat, lon)
    return lat, lon, max(LOCAL_FLOOR_KM, core_km), core_km


def _pages(args: dict[str, Any], local_km: float, core_km: float) -> list[tuple[str, float]]:
    """The extra pages worth asking: the local disc unless it is the whole
    search disc, the core ring unless it is the local disc already."""
    radius = _number(args.get("radiusKm")) or MCP_DEFAULT_RADIUS_KM
    pages: list[tuple[str, float]] = []
    if local_km < radius:
        pages.append(("local", local_km))
    if core_km < min(local_km, radius):
        pages.append(("core", core_km))
    return pages


def start_local_pool(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback`, LAST (the args are final): launch the same
    search on the local disc, next to it. Always returns None."""
    if getattr(tool, "name", "") != "search_offers" or not hasattr(tool, "run_async"):
        return None
    tool_context.state[STATE_GEO_POOL_KEY] = None  # never a previous call's page
    qualified = _qualifies(args, tool_context)
    if qualified is None:
        return None
    _lat, _lon, local_km, core_km = qualified
    pages = _pages(args, local_km, core_km)
    if not pages:
        _log("skip_sparse", None, local_km)
        return None  # the whole disc is local: its own page says it all
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    tasks: list[asyncio.Task] = []
    for _kind, ring in pages:
        if not may_call(tool_context):
            break  # R2: after an extra call failed, or past the deadline
        tasks.append(loop.create_task(
            tool.run_async(args={**args, "radiusKm": ring}, tool_context=tool_context)
        ))
    if not tasks:
        return None
    while len(_PENDING) >= _MAX_PENDING:
        for stale in _PENDING.pop(next(iter(_PENDING))):
            stale.cancel()
    _PENDING[id(tool_context)] = tasks
    return None


async def await_local_pool(
    tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any
) -> None:
    """`after_tool_callback`, before `capture_after_tool`: collect the local
    page (bounded wait) and stash its results for `ranked_payload`. Any
    failure keeps the search's own page alone. Always returns None."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    tasks = _PENDING.pop(id(tool_context), None)
    if not tasks:
        return None
    started = time.monotonic()
    failed = not isinstance(tool_response, dict) or bool(
        tool_response.get("isError") or tool_response.get("error") or tool_response.get("ok") is False
    )
    if failed:
        for task in tasks:
            task.cancel()
        return None
    # R2 (review of #173): the wait never runs past the extra calls' deadline.
    wait = min(POOL_WAIT_SECONDS, max(0.0, remaining_seconds(tool_context)))
    done, late = await asyncio.wait(tasks, timeout=wait) if wait > 0 else (set(), set(tasks))
    for task in late:
        task.cancel()
    if late:
        _log("timeout", started, None)
    found: list[Any] = []
    for task in tasks:  # launch order: the local page, then the core ring's
        if task not in done:
            continue
        error = task.exception()
        if error is not None:
            record_outcome(tool_context, None, error if isinstance(error, Exception) else None)
            _log("error", started, None)
            continue
        local = task.result()
        if record_outcome(tool_context, local):
            _log("error", started, None)
            continue
        payload = read_structured_payload(local)
        results = payload.get("results") if isinstance(payload, dict) else None
        if isinstance(results, list):
            found.extend(results)
    if not found:
        _log("empty", started, None)
        return None
    tool_context.state[STATE_GEO_POOL_KEY] = found
    _log("ok", started, None)
    return None


async def fetch_ring_pages(
    tool: Any, args: dict[str, Any], tool_context: Any, *, kind: str, skip_km: Any = None
) -> list[Any]:
    """The local and core pages of `args` (the same search on the local disc
    and on the core ring), through `extra_calls`, in parallel: their raw
    results, launch order, [] when the search is not ranked here or none came
    back. For a search the leaf runs itself from a callback (the next-day
    probe, 2026-10-30), next to its own call. `skip_km`: a ring already asked
    (the first-open-day scan asks the local disc itself)."""
    qualified = _qualifies(args, tool_context)
    if qualified is None:
        return []
    _lat, _lon, local_km, core_km = qualified
    pages = [(name, ring) for name, ring in _pages(args, local_km, core_km) if ring != skip_km]
    if not pages:
        return []
    answers = await asyncio.gather(*(
        extra_call(tool, {**args, "radiusKm": ring}, tool_context, kind=kind) for _kind, ring in pages
    ))
    found: list[Any] = []
    for status, payload in answers:
        results = payload.get("results") if status == "ok" and isinstance(payload, dict) else None
        if isinstance(results, list):
            found.extend(results)
    return found


def ranked_payload(
    tool_context: Any, args: dict[str, Any], structured: dict[str, Any], extra: list[Any] | None = None
) -> dict[str, Any]:
    """`structured` with its `results` replaced by the ranked pool (its own
    page plus the local and core pages that came back), for a qualifying
    search; `structured` itself otherwise. `extra`: the pages of another call
    than the model's own (the next-day probe's, `fetch_ring_pages`); without
    it, the pages `await_local_pool` collected."""
    tool_context.state[STATE_GEO_RANK_KEY] = None
    qualified = _qualifies(args, tool_context)
    if qualified is None:
        return structured
    lat, lon, local_km, core_km = qualified
    page = structured.get("results")
    if not isinstance(page, list):
        return structured
    if extra is None:
        extra = tool_context.state.get(STATE_GEO_POOL_KEY)
        tool_context.state[STATE_GEO_POOL_KEY] = None
    pool = list(page) + (list(extra) if isinstance(extra, list) else [])
    ranked = rank_pool(pool, lat, lon, local_km, core_km, tool_context.state.get(STATE_PRIORITY_KEY))
    tool_context.state[STATE_GEO_RANK_KEY] = {"lat": lat, "lon": lon, "local_km": local_km}
    _metrics_logger.info(
        "dayuse_metric=geo_rank agent=b2c_hotel_search local_km=%s core_km=%s pool=%d page=%d local=%d",
        local_km, core_km, len(ranked), len(page),
        sum(1 for item in ranked[: len(page)] if tier(_distance(item, lat, lon), local_km) == 0),
    )
    return {**structured, "results": ranked}


def trim_far_cards(tool_context: Any, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cards cut from the ranked pool, without the far ones once enough
    are local: with `MIN_LOCAL_CARDS` cards within the local radius, a card
    beyond twice that radius is dropped (Madrid with a pool: Getafe at 12 km
    after four hotels within 5 km). Measured on each card's coordinates; a
    card without them stays. A search not ranked here is returned as is."""
    ranked = tool_context.state.get(STATE_GEO_RANK_KEY)
    if not isinstance(ranked, dict):
        return cards
    lat, lon, local_km = (_number(ranked.get(key)) for key in ("lat", "lon", "local_km"))
    if lat is None or lon is None or local_km is None:
        return cards

    def distance(card: dict[str, Any]) -> float | None:
        c_lat, c_lon = _number(card.get("latitude")), _number(card.get("longitude"))
        if c_lat is None or c_lon is None:
            return None
        return haversine_km(lat, lon, c_lat, c_lon)

    distances = [distance(card) for card in cards]
    local = sum(1 for d in distances if d is not None and d <= local_km)
    if local < MIN_LOCAL_CARDS:
        return cards
    kept = [card for card, d in zip(cards, distances) if d is None or d <= 2 * local_km]
    if len(kept) < len(cards):
        _metrics_logger.info(
            "dayuse_metric=geo_trim agent=b2c_hotel_search local=%d dropped=%d", local, len(cards) - len(kept)
        )
    return kept


def _log(status: str, started: float | None, local_km: float | None) -> None:
    # Counts only, never a place (GDPR, same as the D+1 probe and the completion).
    # `ms` is the wait AFTER the search's own page came back: the added latency.
    _metrics_logger.info(
        "dayuse_metric=geo_pool agent=b2c_hotel_search status=%s ms=%d local_km=%s",
        status, int((time.monotonic() - started) * 1000) if started is not None else 0,
        local_km if local_km is not None else "-",
    )
