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


def _resolve_area(item: dict[str, str], client: MapboxClient, language: str | None,
                  parent: dict | None = None) -> dict:
    types = "region,district" if item["kind"] == "administrative" else "place,locality"
    if parent is not None:
        types = "locality,neighborhood"
    query = f'{item["subarea"]}, {item["query"]}' if parent is not None else item["query"]
    candidates = client.geocode_candidates(query, country=item["country"], types=types, language=language)
    matches = [c for c in candidates if c.feature_type in types.split(",")
               and c.country_code == item["country"] and c.mapbox_id
               and (parent is None or parent["id"] in c.parent_ids)
               and ((item.get("code") and parent is None and c.administrative_code.casefold() == item["code"].casefold())
                    or ((parent is not None or not item.get("code")) and _same_area_name(item["subarea"] if parent is not None else item["query"], c.name, parent is None and item["kind"] == "administrative")))]
    unique = {c.mapbox_id: c for c in matches}
    if len(unique) != 1:
        return {"ok": False, "error": "area_unresolved", "diagnostics": {
            "reason": "The requested area could not be resolved uniquely; do not substitute its parent city.",
            "area": item["query"],
        }}
    candidate = next(iter(unique.values()))
    if parent is None and item.get("subarea"):
        # Identity of the parent is required, but its bounding disc need not
        # fit MCP when the actual requested subset is smaller.
        child = _resolve_area(item, client, language, parent={"id": candidate.mapbox_id})
        if not child["ok"]:
            return {"ok": False, "error": "area_subarea_unresolved", "diagnostics": {
                "area": item["query"], "subarea": item["subarea"],
                "reason": "The parent is resolved but the required subset is not verified. Ask for a named neighborhood or precise address inside that subset. Do not ask yes/no confirmation of the same unresolved words or show parent-city hotels as compliant.",
                "provider_error": child["error"],
            }}
        child["area"]["required_parent_id"] = candidate.mapbox_id
        child["area"]["label"] = item["query"] + " — " + item["subarea"]
        return child
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
        }}
    identities = [candidate.mapbox_id]
    # Forward and reverse Mapbox IDs can differ for the same administrative
    # entity. Only an explicit provider semantic ID can establish equivalence;
    # labels, bounding boxes and postal prefixes are never membership evidence.
    wikidata = candidate.wikidata_id
    if wikidata.startswith("Q") and wikidata[1:].isascii() and wikidata[1:].isdigit():
        identities.append("wikidata:" + wikidata)
    return {"ok": True, "area": {"id": candidate.mapbox_id, "identities": identities, "label": candidate.name,
            "country": candidate.country_code, "latitude": lat, "longitude": lon, "radius_km": radius,
            "bbox": list(bbox)}}


def trusted_device_coordinates(anchor: Any) -> tuple[float, float] | None:
    if not isinstance(anchor, dict) or anchor.get("type") != "gps":
        return None
    lat, lon = anchor.get("lat"), anchor.get("lon")
    if (isinstance(lat, bool) or isinstance(lon, bool)
            or not isinstance(lat, (float, int)) or not isinstance(lon, (float, int))
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return None
    return float(lat), float(lon)


def use_device_origin(resolution: dict, anchor: Any, client: MapboxClient) -> dict:
    """Retain verified area membership, retrieving nearest to trusted GPS.

    One reverse lookup verifies the device belongs to a requested area. The
    discs still cover every area's full provider bbox; no silent narrowing or
    acceptance of model coordinates. Each hotel's membership remains checked.
    """
    coords = trusted_device_coordinates(anchor)
    if coords is None:
        return {"ok": False, "error": "device_location_unavailable", "diagnostics": {
            "question": "Which city or address inside the requested area should I search near?"}}
    lat, lon = coords
    areas = resolution["search_areas"]
    identities = client.containing_area_ids(lat, lon)
    if identities is None or not any(
        identities.intersection(a.get("identities") or [a["id"]])
        and (not a.get("required_parent_id") or a["required_parent_id"] in identities)
        for a in areas
    ):
        return {"ok": False, "error": "device_area_conflict", "diagnostics": {
            "question": "Your position is not verified inside the requested area. Should I keep that area or search around your position?"}}
    shifted = []
    for area in areas:
        bbox = area["bbox"]
        radius = math.ceil(max(haversine_km(lat, lon, y, x)
                              for x in (bbox[0], bbox[2]) for y in (bbox[1], bbox[3]))) + 1
        if radius > 200:
            return {"ok": False, "error": "area_exceeds_search_radius", "diagnostics": {
                "question": "Which part of the requested area should I keep? Its full extent exceeds the search radius from your position."}}
        shifted.append({**area, "latitude": lat, "longitude": lon, "radius_km": radius,
                        "sort_by": "distance"})
    return {**resolution, "latitude": lat, "longitude": lon, "resolved_place": "your current location",
            "distance_origin_type": "gps", "search_areas": shifted,
            "profile_delta": {**resolution["profile_delta"], "device_origin": True}}


def resolve_areas(requests: list[dict[str, str]], client: MapboxClient, language: str | None = None) -> dict:
    # These are alternative areas, never an intersection. A failed alternative
    # must stay visible, but cannot erase valid membership in another requested
    # area. No substitution, radius expansion or extra provider call is needed.
    outcomes = [_resolve_area(item, client, language) for item in requests]
    resolved = [outcome["area"] for outcome in outcomes if outcome["ok"]]
    unresolved = [{"query": item["query"] + (" — " + item["subarea"] if item.get("subarea") else ""), "error": outcome["error"]}
                  for item, outcome in zip(requests, outcomes, strict=True) if not outcome["ok"]]
    if not resolved:
        failure = dict(outcomes[0])
        if failure["error"] in {"area_exceeds_search_radius", "area_subarea_unresolved"}:
            failure["profile_delta"] = {"search_areas": requests, "last_city": failure["diagnostics"]["area"]}
        return {**failure, "unresolved_areas": unresolved}
    first = resolved[0]
    label = " / ".join(a["label"] for a in resolved)
    countries = {item["country"] for item in requests}
    return {"ok": True, "latitude": first["latitude"], "longitude": first["longitude"],
            "resolved_place": label, "distance_origin_type": "area", "search_areas": resolved,
            "unresolved_areas": unresolved,
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
                 "radiusKm": area["radius_km"], "size": PAGE_SIZE,
                 "sortBy": area.get("sort_by") or ("distance" if area.get("required_parent_id") else "relevance")}
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
        matching = [a for a in areas if identifiers.intersection(a.get("identities") or [a["id"]])
                    and (not a.get("required_parent_id") or a["required_parent_id"] in identifiers)]
        if not matching:
            return None, False
        return {**hotel, "verifiedSearchAreas": [a["label"] for a in matching],
                "countryCode": matching[0]["country"]}, False

    checked = await asyncio.gather(*(verify(h) for h in hotels))
    valid = [hotel for hotel, _ in checked if hotel is not None]
    unresolved = (tool_context.state.get(STATE_RESOLUTION) or {}).get("unresolved_areas", [])
    coverage = {"areas": [a["label"] for a in areas], "exhaustive": False,
                "unresolved_areas": [item["query"] for item in unresolved],
                "retrieved": len(hotels), "verified": len(valid),
                "unverified": sum(unknown for _, unknown in checked),
                "failed_areas": sum(p is None for p in payloads),
                "notice": "Bounded sample from each requested area, filtered by provider membership. No claim of exhaustive availability or absence. Some candidates can be outside the requested boundaries; they were removed."}
    tool_context.state[STATE_COVERAGE] = coverage
    if all(p is None for p in payloads):
        return {"ok": False, "error": "area_search_unavailable"}
    return {"structuredContent": {"results": valid, "total": len(valid),
                                   "resolvedDate": args.get("date"), "areaCoverage": coverage}}
