"""Resolve each owned alternative through the existing provider guards.

No extra model phase: the ordinary bounded area batch retrieves the verified
point discs with the same guarded date, slot, party and equipment filters.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from google.genai import types

from b2c_common.confirmed_location import verified_place
from b2c_common.destination_request import DestinationRequest, destination_request
from hotel_search_agent.area_scope import STATE_FAILED, STATE_RESOLUTION
from hotel_search_agent.geocode_tool import geocode_location, inject_profile_geo_context
from hotel_search_agent.response_bridge import (
    _POI_RADIUS_KM, capture_after_tool, encode_datapart, find_datapart, read_profile_in,
)

_GEO = SimpleNamespace(name="geocode_location")


async def prepare_landmark_alternatives(callback_context: Any) -> None:
    content = getattr(callback_context, "user_content", None)
    envelope = find_datapart(getattr(content, "parts", None)) or {}
    profile = read_profile_in(callback_context)
    request = destination_request(profile.get("requested_destination"))
    if ((envelope.get("query_params") or {}).get("destination_authoritative") is not True
            or not request or request.kind != "landmarks"):
        return None

    async def resolve(item: Any) -> tuple[dict | None, dict | None]:
        # Independent invocation contexts prevent one alternative's provider
        # anchor from being inherited as another alternative's parent.
        child = {**profile, "city": item.city, "zone": item.query, "metro": None,
                 "search_areas": None, "confirmed_location": None, "pending_location": None,
                 "country_anchor": None, "state_anchor": None, "distance_origin": None,
                 "requested_destination": DestinationRequest(kind="landmark", **item.model_dump()).model_dump(exclude_none=True)}
        parts = [p for p in (getattr(content, "parts", None) or []) if getattr(p, "text", None)]
        parts.append(encode_datapart({"profile_in": child, "query_params": {"destination_authoritative": True}}))
        context = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=parts))
        args: dict[str, Any] = {}
        response = await asyncio.to_thread(inject_profile_geo_context, _GEO, args, context)
        if response is None:
            response = await asyncio.to_thread(geocode_location, **args)
        place = verified_place(response.get("resolved_location")) if response.get("ok") else None
        if not place or place["feature_type"] != "poi":
            return None, {"query": item.query, "error": response.get("error") or "landmark_identity_unverified",
                          "diagnostics": response.get("diagnostics") or {}}
        return {"id": place["provider_id"], "label": item.query, "country": place["country_code"],
                "latitude": place["latitude"], "longitude": place["longitude"],
                "radius_km": _POI_RADIUS_KM, "scope": "nearby_point", "sort_by": "distance"}, None

    outcomes = await asyncio.gather(*(resolve(item) for item in request.landmarks or []))
    points = [point for point, _ in outcomes if point is not None]
    unresolved = [failure for _, failure in outcomes if failure is not None]
    if not points:
        labels = " / ".join(item.query for item in request.landmarks or [])
        questions = {
            "fr": "Dans quelle ville ou près de quelle adresse dois-je situer ces lieux : {places} ?",
            "en": "Which city or address should I use for these alternatives: {places}?",
            "de": "In welcher Stadt oder bei welcher Adresse liegen diese Alternativen: {places}?",
            "es": "¿En qué ciudad o cerca de qué dirección están estas alternativas: {places}?",
            "it": "In quale città o vicino a quale indirizzo si trovano queste alternative: {places}?",
            "pt": "Em que cidade ou perto de que endereço ficam estas alternativas: {places}?",
            "nl": "In welke stad of bij welk adres liggen deze alternatieven: {places}?",
        }
        question = questions.get(str(profile.get("language") or "en"), questions["en"]).format(places=labels)
        result = {"ok": False, "error": "geocode_ambiguous", "diagnostics": {
            "question": question,
            "alternatives": unresolved, "options": [],
        }}
        callback_context.state[STATE_FAILED] = result
        # The existing origin instruction exposes the failed plan to the leaf.
        callback_context.state[STATE_RESOLUTION] = result
        capture_after_tool(_GEO, {}, callback_context, result)
        return None
    first = points[0]
    result = {"ok": True, "latitude": first["latitude"], "longitude": first["longitude"],
              "resolved_place": " / ".join(p["label"] for p in points),
              "distance_origin_type": "area", "search_areas": points,
              "unresolved_areas": unresolved, "profile_delta": {}}
    countries = {p["country"] for p in points}
    if len(countries) == 1:
        result["country_code"] = first["country"]
    capture_after_tool(_GEO, {}, callback_context, result)
    return None


def reuse_landmark_alternatives(tool: Any, args: dict, tool_context: Any) -> dict | None:
    """A model cannot collapse the prepared alternatives to a new single point."""
    if getattr(tool, "name", "") != "geocode_location":
        return None
    request = destination_request(read_profile_in(tool_context).get("requested_destination"))
    if request and request.kind == "landmarks":
        return tool_context.state.get(STATE_RESOLUTION) or tool_context.state.get(STATE_FAILED)
    return None
