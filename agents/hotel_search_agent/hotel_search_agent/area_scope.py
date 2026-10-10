"""Typed destinations and provider-verified membership for bounded area searches.

The LLM identifies up to five alternative administrative areas/municipalities.
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

from b2c_common.search_areas import MAX_AREAS, area_name_in_text, validate_areas as validate_areas

from hotel_search_agent.geo_guards import resolve_state_hint
from hotel_search_agent.inventory import haversine_km
from hotel_search_agent.mapbox_client import MapboxClient
from hotel_search_agent.identity_confidence import dominant_identity

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


def _same_child_name(query: str, candidate: Any) -> bool:
    """Provider child labels may include their own verified parent's name.

    No name aliases or fuzzy similarity. Parent membership is required by the
    caller; an unrelated parent's prefix cannot establish this relationship.
    """
    wanted = _identity_words(query, False)
    actual = _identity_words(candidate.name, False)
    parent = _identity_words(candidate.parent_city_name, False)
    return bool(wanted and (wanted == actual or (
        candidate.parent_city_id and parent and actual in (parent + wanted, wanted + parent))))


def _area_question(query: str, candidates: list, language: str | None) -> str:
    labels = list(dict.fromkeys(c.place_name for c in candidates if c.place_name))[:3]
    templates = {
        "en": "Which city do you mean for {query}? Please give its containing city or an exact address.",
        "fr": "Dans quelle ville cherchez-vous {query} ? Précisez la ville ou une adresse exacte.",
        "de": "In welcher Stadt meinen Sie {query}? Bitte nennen Sie die Stadt oder eine genaue Adresse.",
        "it": "In quale città cerchi {query}? Indica la città o un indirizzo preciso.",
        "es": "¿En qué ciudad buscas {query}? Indica la ciudad o una dirección exacta.",
        "pt": "Em que cidade procura {query}? Indique a cidade ou uma morada exata.",
        "nl": "In welke stad bedoelt u {query}? Geef de stad of een exact adres aan.",
    }
    question = templates.get(language or "en", templates["en"]).format(query=query)
    return question + (" (" + "; ".join(labels) + ")" if labels else "")


def _resolve_area(item: dict[str, str], client: MapboxClient, language: str | None,
                  parent: dict | None = None, *, identity_only: bool = False) -> dict:
    if item.get("required_region") and parent is None:
        return _resolve_region_scoped_area(item, client, language)
    if parent is None and item.get("subarea"):
        return _resolve_subarea(item, client, language)
    if not item["country"] and item.get("code") and parent is None:
        # A numeric administrative code has no global identity. Named areas
        # use provider evidence below; homonyms still require clarification.
        return {"ok": False, "error": "area_parent_needed", "diagnostics": {
            "area": item["query"], "reason": "Which containing city and country does this requested area belong to?"}}
    types = {"administrative": "region,district", "municipality": "place,locality",
             "neighborhood": "locality,neighborhood"}[item["kind"]]
    if parent is not None:
        types = "locality,neighborhood"
    query = f'{item["subarea"]}, {item["query"]}' if parent is not None else item["query"]
    region = item.get("region")
    region_hint = (resolve_state_hint(keywords=[region], country_code=item["country"] or None)
                   or region) if region else None
    if region:
        query += ", " + region
    candidates = ([parent["candidate"]] if parent and parent.get("candidate") else
                  client.geocode_candidates(query, country=item["country"] or None, types=types, language=language))
    matches = [c for c in candidates if c.feature_type in types.split(",")
               and c.country_code and (not item["country"] or c.country_code == item["country"]) and c.mapbox_id
               and (parent is None or parent["id"] in c.parent_ids)
               and (not region_hint or area_name_in_text(region_hint, c.place_name))
               and ((item.get("code") and parent is None and c.administrative_code.casefold() == item["code"].casefold())
                    or (parent is not None and _same_child_name(item["subarea"], c))
                    or (parent is None and not item.get("code") and _same_area_name(item["query"], c.name, item["kind"] == "administrative")))]
    # Inspect actual provider identities before asking for information the
    # provider can establish. Explicit country/parent/region constraints above
    # remain hard filters; the selected area's membership is still verified.
    candidate = dominant_identity(matches)
    if candidate is None:
        return {"ok": False, "error": "area_unresolved", "diagnostics": {
            "reason": "The requested area could not be resolved uniquely; do not substitute its parent city.",
            "area": item["query"],
            "question": _area_question(item["query"], matches, language),
        }}
    if identity_only:
        return {"ok": True, "area": {"id": candidate.mapbox_id,
                "identities": _provider_identities(candidate), "label": candidate.name,
                "country": candidate.country_code}}
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
    identities = _provider_identities(candidate)
    return {"ok": True, "area": {"id": candidate.mapbox_id, "identities": identities, "label": candidate.name,
            "country": candidate.country_code, "latitude": lat, "longitude": lon, "radius_km": radius,
            "bbox": list(bbox)}}


def _same_parent_name(query: str, provider_name: str) -> bool:
    wanted, actual = _identity_words(query, False), _identity_words(provider_name, False)
    # Provider municipality labels may append the generic feature type.
    # This is not a list of geographic aliases and never strips proper names.
    return bool(wanted) and (wanted == actual or actual == wanted + ["city"])


def _resolve_subarea(item: dict[str, str], client: MapboxClient, language: str | None) -> dict:
    """Resolve child + parent as one provider relationship, not two guesses.

    A parent homonym must not block an otherwise unique neighborhood identity.
    The provider's explicit parent ID establishes both; hotel membership below
    still requires that ID AND the child's identity.
    """
    query = item["subarea"] + ", " + item["query"]
    if item.get("region"):
        query += ", " + item["region"]
    candidates = client.geocode_candidates(query, country=item["country"] or None,
                                           types="locality,neighborhood", language=language)
    matches = [c for c in candidates if c.mapbox_id and c.country_code
               and c.feature_type in {"locality", "neighborhood"}
               and (not item["country"] or c.country_code == item["country"])
               and _same_child_name(item["subarea"], c)
               and c.parent_city_id and c.parent_city_id in c.parent_ids
               and _same_parent_name(item["query"], c.parent_city_name)]
    candidate = dominant_identity(matches)
    parent_id = candidate.parent_city_id if candidate else None
    if candidate is None and candidates:
        # Provider labels may be absent or canonicalized (e.g. an abbreviation
        # in the request). Resolve the parent once and join on its ID; never
        # add an alias dictionary or infer that identity from proximity.
        parent = _resolve_area({k: v for k, v in item.items() if k != "subarea"},
                               client, language, identity_only=True)
        if parent["ok"]:
            parent_id = parent["area"]["id"]
            candidate = dominant_identity([c for c in candidates
                if parent_id in c.parent_ids and _same_child_name(item["subarea"], c)
                and c.feature_type in {"locality", "neighborhood"}
                and c.mapbox_id and c.country_code
                and (not item["country"] or c.country_code == item["country"])
                and (not c.parent_city_id or c.parent_city_id == parent_id)])
    child: dict = (_resolve_area(item, client, language, parent={"id": parent_id, "candidate": candidate})
             if candidate else {"ok": False, "error": "area_parent_identity_unverified"})
    if not child["ok"]:
        return {"ok": False, "error": "area_subarea_unresolved", "diagnostics": {
            "area": item["query"], "subarea": item["subarea"],
            "reason": "The required subset and its containing city are not verified together. Ask for a precise address inside that subset; do not substitute parent-city hotels.",
            "provider_error": child["error"],
        }}
    assert candidate is not None
    child["area"]["required_parent_id"] = parent_id
    child["area"]["label"] = item["query"] + " — " + item["subarea"]
    return child


def _provider_identities(candidate: Any) -> list[str]:
    identities = [candidate.mapbox_id]
    # Forward and reverse Mapbox IDs can differ for the same administrative
    # entity. Only an explicit provider semantic ID can establish equivalence;
    # labels, bounding boxes and postal prefixes are never membership evidence.
    wikidata = candidate.wikidata_id
    if wikidata.startswith("Q") and wikidata[1:].isascii() and wikidata[1:].isdigit():
        identities.append("wikidata:" + wikidata)
    return identities


def _resolve_region_scoped_area(item: dict[str, str], client: MapboxClient, language: str | None) -> dict:
    """Retrieve near the city but verify the customer's mandatory region.

    A containing region is an intersection, never another accepted destination.
    Its whole bounding disc need not fit MCP when searching a particular city.
    """
    point = _resolve_area({k: v for k, v in item.items() if k != "required_region"}, client, language)
    if not point["ok"]:
        return point
    region = _resolve_area({"query": item["required_region"], "kind": "administrative",
                            "country": point["area"]["country"], "evidence": item["required_region"]},
                           client, language, identity_only=True)
    if not region["ok"]:
        return region
    area = point["area"]
    mandatory = region["area"]["identities"]
    if item["kind"] == "municipality" and not item.get("boundary_evidence") and not item.get("subarea"):
        # The city locates retrieval; its boundary was not requested. Per-hotel
        # reverse membership below proves the region, including nearby suburbs.
        area.update(id=region["area"]["id"], identities=mandatory,
                    radius_km=20, sort_by="distance")
    else:
        area["required_region_identities"] = mandatory
    area["label"] = item["query"] + " — " + item["required_region"]
    return {"ok": True, "area": area}


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
    unanchored_alternatives = len(requests) > 1 and any(
        item["kind"] == "neighborhood" and not item["country"] and not item.get("subarea")
        for item in requests
    )
    outcomes: list[dict[str, Any]] = ([{"ok": False, "error": "area_parent_needed", "diagnostics": {
        "area": item["query"], "reason": "Which containing city do these alternative neighborhoods belong to?"}}
        for item in requests] if unanchored_alternatives else
        [_resolve_area(item, client, language) for item in requests])
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

    At most five read-only MCP requests (five raw candidates each) and twenty-five
    membership lookups; no model retry/extra reasoning phase. A second batch in
    the same turn is blocked. Raw per-area calls remain visible to the MCP client.
    """
    if getattr(tool, "name", "") != "search_offers":
        return None
    areas = tool_context.state.get(STATE_AREAS)
    if not isinstance(areas, list) or not areas:
        return None
    if len(areas) > MAX_AREAS:
        return {"ok": False, "error": "Too many search areas for one bounded batch."}
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
        points = [a for a in areas if a.get("scope") == "nearby_point"]
        if points:
            matches = [a for a in points if haversine_km(lat, lon, a["latitude"], a["longitude"]) <= a["radius_km"]]
            if not matches:
                return None, False
            origins = [{"label": a["label"], "latitude": a["latitude"], "longitude": a["longitude"],
                        "distance_km": round(haversine_km(lat, lon, a["latitude"], a["longitude"]), 1)}
                       for a in matches]
            return {**hotel, "verifiedSearchOrigins": origins, "countryCode": matches[0]["country"]}, False
        identifiers = await asyncio.to_thread(client.containing_area_ids, lat, lon)
        if identifiers is None:
            return None, True
        matching = [a for a in areas if identifiers.intersection(a.get("identities") or [a["id"]])
                    and (not a.get("required_parent_id") or a["required_parent_id"] in identifiers)
                    and (not a.get("required_region_identities") or identifiers.intersection(a["required_region_identities"]))]
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
                "failed_area_names": [a["label"] for a, p in zip(areas, payloads, strict=True) if p is None],
                "notice": ("Bounded sample around each verified alternative landmark; distances checked against each provider point. "
                           "Some alternatives may be unresolved or failed. Never claim exhaustive availability or absence."
                           if any(a.get("scope") == "nearby_point" for a in areas) else
                           "Bounded sample from each requested area, filtered by provider membership. No claim of exhaustive availability or absence. Some candidates can be outside the requested boundaries; they were removed.")}
    tool_context.state[STATE_COVERAGE] = coverage
    if all(p is None for p in payloads):
        return {"ok": False, "error": "area_search_unavailable"}
    return {"structuredContent": {"results": valid, "total": len(valid),
                                   "resolvedDate": args.get("date"), "areaCoverage": coverage}}
