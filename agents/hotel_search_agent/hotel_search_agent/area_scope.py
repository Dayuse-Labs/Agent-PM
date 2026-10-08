"""Typed destinations and provider-verified membership for bounded area searches.

The LLM identifies up to three alternative administrative areas/municipalities.
It never provides coordinates or boundaries. The existing geocoder resolves
identities; the MCP's discs retrieve candidates; reverse geocoding verifies each
hotel belongs to at least one requested area before any price/card is exposed.
A returned page is explicitly a sample, never proof that an area is exhausted.
"""
from __future__ import annotations

import asyncio
import math
import unicodedata
from typing import Any, Awaitable

from b2c_common.search_areas import validate_areas as validate_areas

from hotel_search_agent.inventory import haversine_km
from hotel_search_agent.mapbox_client import MapboxClient

STATE_AREAS = "temp:search_areas"
STATE_COVERAGE = "temp:area_coverage"
STATE_RAN = "temp:area_search_ran"
STATE_FAILED = "temp:area_resolution_failed"
STATE_RESOLUTION = "temp:area_resolution"
PAGE_SIZE = 5


# Administrative labels are localized by the provider ("provincia di Brescia")
# and may include the type before/after the proper name. This is identity
# normalization AFTER typed intent, not a natural-language area classifier.
_ADMIN_LABEL_WORDS = frozenset({
    "province", "provincia", "provincie", "provinz", "county", "comte",
    "departement", "department", "departamento", "state", "estado", "stato",
    "region", "regione", "district", "distretto", "canton",
    "de", "di", "du", "des", "of", "the", "e", "et", "and", "la", "le", "les",
})


def _identity_words(label: str, administrative: bool) -> list[str]:
    folded = "".join(c for c in unicodedata.normalize("NFKD", label.casefold()) if not unicodedata.combining(c))
    words = "".join(c if c.isalnum() else " " for c in folded).split()
    return [w for w in words if w not in _ADMIN_LABEL_WORDS] if administrative else words


def _same_area_name(query: str, label: str, administrative: bool) -> bool:
    words = _identity_words(query, administrative)
    return bool(words) and words == _identity_words(label, administrative)


def resolve_areas(requests: list[dict[str, str]], client: MapboxClient, language: str | None = None) -> dict:
    resolved: list[dict[str, Any]] = []
    for item in requests:
        types = "region,district" if item["kind"] == "administrative" else "place,locality"
        candidates = client.geocode_candidates(item["query"], country=item["country"], types=types, language=language)
        # Typed identity, country and name/code all agree. Never select an
        # attractive city merely because its inventory is denser than a region.
        matches = [c for c in candidates if c.feature_type in types.split(",")
                   and c.country_code == item["country"] and c.mapbox_id
                   and ((item.get("code") and c.administrative_code.casefold() == item["code"].casefold())
                        or (not item.get("code") and _same_area_name(item["query"], c.name, item["kind"] == "administrative")))]
        unique = {c.mapbox_id: c for c in matches}
        if len(unique) != 1:
            return {"ok": False, "error": "area_unresolved", "diagnostics": {
                "reason": "The requested area could not be resolved uniquely; do not substitute its parent city.",
                "area": item["query"],
            }}
        candidate = next(iter(unique.values()))
        bbox = candidate.bbox
        if (bbox is None or not all(math.isfinite(x) for x in bbox)
                or not -180 <= bbox[0] < bbox[2] <= 180
                or not -90 <= bbox[1] < bbox[3] <= 90):
            return {"ok": False, "error": "area_boundary_unavailable", "diagnostics": {"area": candidate.name}}
        lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        radius = math.ceil(max(haversine_km(lat, lon, y, x) for x in (bbox[0], bbox[2]) for y in (bbox[1], bbox[3]))) + 1
        if radius > 200:
            return {"ok": False, "error": "area_exceeds_search_radius", "diagnostics": {
                "area": candidate.name, "reason": "This whole area exceeds the MCP's 200 km radius. Ask for a narrower part without discarding the requested region.",
            }, "profile_delta": {"search_areas": requests, "last_city": candidate.name}}
        resolved.append({"id": candidate.mapbox_id, "label": candidate.name,
                         "country": candidate.country_code, "latitude": lat, "longitude": lon,
                         "radius_km": radius})
    first = resolved[0]
    label = " / ".join(a["label"] for a in resolved)
    countries = {a["country"] for a in resolved}
    return {"ok": True, "latitude": first["latitude"], "longitude": first["longitude"],
            "resolved_place": label, "distance_origin_type": "area", "search_areas": resolved,
            "country_code": first["country"] if len(countries) == 1 else None,
            "profile_delta": {"last_city": label, "search_areas": requests,
                              "zone": {"op": "clear"}, "metro": {"op": "clear"},
                              "distance_origin": {"op": "clear"},
                              "country_anchor": first["country"] if len(countries) == 1 else {"op": "clear"}}}


def search_areas_before_tool(tool: Any, args: dict[str, Any], tool_context: Any) -> Awaitable[dict] | dict | None:
    """One bounded batch, after all existing date/budget/equipment guards.

    At most three read-only MCP requests (five raw candidates each) and fifteen
    membership lookups; no model retry/extra reasoning phase. A second batch in
    the same turn is blocked. Raw per-area calls remain visible to the MCP client.
    """
    if getattr(tool, "name", "") != "search_offers":
        return None
    areas = tool_context.state.get(STATE_AREAS)
    if not isinstance(areas, list) or not areas:
        return None
    if tool_context.state.get(STATE_RAN):
        return {"ok": False, "error": "Area search already completed; answer from this turn's retrieved sample."}
    tool_context.state[STATE_RAN] = True
    return _search_areas(tool, args, tool_context, areas)


async def _search_areas(tool: Any, args: dict[str, Any], tool_context: Any, areas: list[dict]) -> dict:
    from hotel_search_agent.geocode_tool import get_mapbox_client
    from hotel_search_agent.response_bridge import read_structured_payload

    # The same guarded filters are used for EVERY area. No model-provided
    # coordinates/radius can alter the provider-derived retrieval geometry.
    async def retrieve(area: dict) -> dict | None:
        query = {**args, "lat": area["latitude"], "lon": area["longitude"],
                 "radiusKm": area["radius_km"], "size": PAGE_SIZE, "sortBy": "relevance"}
        try:
            raw = await tool.run_async(args=query, tool_context=tool_context)
        except Exception:
            return None
        if not isinstance(raw, dict) or raw.get("isError") or raw.get("ok") is False:
            return None
        payload = read_structured_payload(raw)
        return payload if isinstance(payload, dict) and isinstance(payload.get("results"), list) else None

    payloads = await asyncio.gather(*(retrieve(a) for a in areas))
    # Round-robin before the existing top-five cut preserves representation of
    # alternative areas. Deduplicate by server hotel identity, never hotel name.
    hotels: list[dict] = []
    seen: set[Any] = set()
    for i in range(PAGE_SIZE):
        for payload in payloads:
            rows = payload.get("results", []) if payload else []
            if i >= len(rows) or not isinstance(rows[i], dict):
                continue
            hotel = rows[i]
            identifier = hotel.get("hotelId") or hotel.get("id")
            if identifier is not None and identifier not in seen:
                seen.add(identifier)
                hotels.append(hotel)
    client = get_mapbox_client()

    async def verify(hotel: dict) -> tuple[dict | None, bool]:
        lat, lon = hotel.get("lat"), hotel.get("lon")
        if (isinstance(lat, bool) or isinstance(lon, bool) or not isinstance(lat, (float, int))
                or not isinstance(lon, (float, int)) or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            return None, True
        identifiers = await asyncio.to_thread(client.containing_area_ids, lat, lon)
        if identifiers is None:
            return None, True
        matching = [a for a in areas if a["id"] in identifiers]
        if not matching:
            return None, False
        return {**hotel, "verifiedSearchAreas": [a["label"] for a in matching],
                "countryCode": matching[0]["country"]}, False

    checked = await asyncio.gather(*(verify(h) for h in hotels))
    valid = [hotel for hotel, _ in checked if hotel is not None]
    coverage = {"areas": [a["label"] for a in areas], "exhaustive": False,
                "retrieved": len(hotels), "verified": len(valid),
                "unverified": sum(unknown for _, unknown in checked),
                "failed_areas": sum(p is None for p in payloads),
                "notice": "Bounded sample from each requested area, filtered by provider membership. No claim of exhaustive availability or absence. Some candidates can be outside the requested boundaries; they were removed."}
    tool_context.state[STATE_COVERAGE] = coverage
    if all(p is None for p in payloads):
        return {"ok": False, "error": "area_search_unavailable"}
    return {"structuredContent": {"results": valid, "total": len(valid),
                                   "resolvedDate": args.get("date"), "areaCoverage": coverage}}
