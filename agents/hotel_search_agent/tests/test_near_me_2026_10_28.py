"""2026-10-28: « près de moi » — the user's own position, read by the model
(`GeoIntent.near_user`), never looked up as a place.

agent-usa served the chip 489 times from September to the switch (9 in 10
with results: « Based on your location, here are day rooms around Eixample
(Barcelona), all within about 1–2 km »); AgentB2C had no chip and no such
field, so « moi » could only be a place or nothing. Offline: the geocoder is a
spy that must not be reached when the position decides.
"""
from __future__ import annotations

from types import SimpleNamespace

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import (
    convert_a2a_part_to_genai_part,
    convert_genai_part_to_a2a_part,
)
from google.genai import types as genai_types

from b2c_common.geo_intent import CityRef, GeoIntent, Place
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.response_bridge import (
    capture_after_tool,
    emit_search_datapart,
    inject_landmark_radius,
)


def _ctx(text, profile_in=None):
    """The leaf's `tool_context`: the inbound text, then the A2A DataPart, as
    the real a2a→genai converter hands them to the leaf."""
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=text), convert_a2a_part_to_genai_part(datapart)]
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _decode(content) -> dict:
    for part in content.parts:
        if part.inline_data is not None:
            return convert_genai_part_to_a2a_part(part).root.data
    raise AssertionError("no datapart in content")


class _Tool:
    def __init__(self, name):
        self.name = name


class _RingInventory:
    def __init__(self, per_km: float):
        self.per_km = per_km

    def count_near(self, lat, lon, *, radius_km):
        return int(radius_km * self.per_km)

_BARCELONA = (41.3917, 2.1649)  # a device fix, Eixample


def _no_lookup(monkeypatch):
    calls: list[dict] = []

    def spy(**kwargs):
        calls.append(kwargs)
        return {"ok": False, "error": "spy"}

    monkeypatch.setattr(geocode_tool, "geocode_core", spy)
    return calls


def test_near_me_with_a_device_fix_searches_around_it_without_a_lookup(monkeypatch):
    calls = _no_lookup(monkeypatch)
    ctx = _ctx("Habitación de día cerca de mí", profile_in={"city": "Madrid"})

    result = geocode_location(
        intent=GeoIntent(near_user=True), proximity_lat=_BARCELONA[0], proximity_lon=_BARCELONA[1],
        tool_context=ctx,
    )

    assert calls == []
    assert result["ok"] is True
    assert (result["latitude"], result["longitude"]) == _BARCELONA
    assert result["distance_origin_type"] == "gps"
    # The earlier destination (Madrid) is dropped for the follow-ups.
    assert result["profile_delta"] == {"near_user": True}


def test_near_me_without_a_position_names_no_place_and_never_the_earlier_city(monkeypatch):
    calls = _no_lookup(monkeypatch)
    ctx = _ctx("Chambre en journée près de moi", profile_in={"city": "Paris"})

    result = geocode_location(intent=GeoIntent(near_user=True), tool_context=ctx)

    assert calls == []
    assert result == {
        "ok": False, "error": "no_geocodable_location",
        "diagnostics": {"reason": "missing_city", "zone_hint": None},
    }


def test_a_place_named_with_near_me_is_searched_as_the_place(monkeypatch):
    # « near me in Boston »: Boston, as agent-usa did.
    calls = _no_lookup(monkeypatch)
    ctx = _ctx("day room near me in Boston")

    geocode_location(
        intent=GeoIntent(near_user=True, city=CityRef(mention="Boston", canonical="Boston", country="US")),
        proximity_lat=_BARCELONA[0], proximity_lon=_BARCELONA[1], tool_context=ctx,
    )

    assert len(calls) == 1
    assert calls[0]["city"] == "Boston"


def test_without_the_flag_nothing_changes(monkeypatch):
    calls = _no_lookup(monkeypatch)
    ctx = _ctx("un hôtel à Lyon")

    geocode_location(
        intent=GeoIntent(places=[Place(mention="Lyon", kind="city", canonical="Lyon", country="FR")]),
        proximity_lat=_BARCELONA[0], proximity_lon=_BARCELONA[1], tool_context=ctx,
    )

    assert len(calls) == 1


def test_the_turn_drops_the_earlier_destination_and_takes_a_close_ring(monkeypatch):
    from hotel_search_agent import response_bridge

    monkeypatch.setattr(response_bridge, "get_inventory", lambda: _RingInventory(per_km=10))
    ok = geocode_tool._near_user(*_BARCELONA)
    ctx = _ctx("Day room near me")
    capture_after_tool(_Tool("geocode_location"), {}, ctx, ok)
    args = {"lat": _BARCELONA[0], "lon": _BARCELONA[1], "date": "2026-10-28"}

    inject_landmark_radius(_Tool("search_offers"), args, ctx)
    ctx.state["temp:hotel_search_results"] = [{"id": 1, "name": "Hotel A"}]
    delta = _decode(emit_search_datapart(ctx))["profile_delta"]

    # The POI ring, nearest first (MCP's 20 km disc in relevance order before).
    assert args["sortBy"] == "distance"
    assert args["radiusKm"] <= 5
    for slot in ("city", "zone", "metro", "state_anchor", "city_is_area"):
        assert delta[slot] == {"op": "clear"}
