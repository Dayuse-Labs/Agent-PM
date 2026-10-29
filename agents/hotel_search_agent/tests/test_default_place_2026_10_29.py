"""2026-10-29: the answer to the place question gave no place (« Demain »).

Prod after #173: a day chip clicked under « Où et pour quel jour ? » brought a
second, bare « Dans quelle ville ? »; 16 of 45 such conversations never saw a
hotel. The concierge now offers the visitor market's main city
(`query_params.default_place`) on that answer turn only, and the leaf searches
it when — and only when — nothing else locates the request: no place named,
none carried, no device position. Offline: `geocode_core` is a spy.
"""
from __future__ import annotations

from types import SimpleNamespace

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from b2c_common.geo_intent import CityRef, GeoIntent
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.response_bridge import _search_context

_PARIS_OK = {
    "ok": True, "latitude": 48.8566, "longitude": 2.3522, "resolved_place": "Paris, France",
    "resolved_feature_type": "place", "distance_origin_type": "city_centroid", "country_code": "FR",
    "profile_delta": {"last_city": "Paris"},
}
_OFFER = {"default_place": {"city": "Paris", "country_code": "FR"}}


def _ctx(text, *, query_params=None, profile_in=None):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": query_params or {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=text), convert_a2a_part_to_genai_part(datapart)]
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _spy(monkeypatch, answer=None):
    calls: list[dict] = []

    def core(**kwargs):
        calls.append(kwargs)
        return dict(answer or _PARIS_OK)

    monkeypatch.setattr(geocode_tool, "geocode_core", core)
    return calls


def test_a_day_only_answer_searches_the_offered_market_city_and_says_so(monkeypatch):
    calls = _spy(monkeypatch)
    ctx = _ctx("Trouvez une chambre avec jacuzzi\nDemain", query_params=_OFFER)

    result = geocode_location(intent=GeoIntent(), tool_context=ctx)

    assert [(c["city"], c["country_code"]) for c in calls] == [("Paris", "FR")]
    assert result["ok"] is True and result["default_place"] == "Paris"
    assert result["profile_delta"]["default_place"] == "Paris"
    # What the concierge reads to say it (`search_context.default_place`).
    context = _search_context({}, result["profile_delta"], {}, {"date": "2026-10-30"})
    assert context["default_place"] == "Paris"


def test_a_place_named_in_the_answer_wins_over_the_offer(monkeypatch):
    calls = _spy(monkeypatch)
    ctx = _ctx("Trouvez une chambre avec jacuzzi\nLyon", query_params=_OFFER)

    result = geocode_location(
        intent=GeoIntent(city=CityRef(mention="Lyon", canonical="Lyon", country="FR")), tool_context=ctx,
    )

    assert [c["city"] for c in calls] == ["Lyon"]
    assert "default_place" not in result


def test_a_device_position_wins_over_the_offer(monkeypatch):
    calls = _spy(monkeypatch, {"ok": True, "latitude": 1.0, "longitude": 2.0, "profile_delta": {}})
    ctx = _ctx("Demain", query_params=_OFFER)

    result = geocode_location(intent=GeoIntent(), proximity_lat=48.87, proximity_lon=2.33, tool_context=ctx)

    assert all(c.get("city") != "Paris" for c in calls)
    assert "default_place" not in result


def test_without_the_offer_nothing_changes(monkeypatch):
    calls = _spy(monkeypatch, {
        "ok": False, "error": "no_geocodable_location", "diagnostics": {"reason": "missing_city", "zone_hint": None},
    })
    ctx = _ctx("Demain")

    result = geocode_location(intent=GeoIntent(), tool_context=ctx)

    assert all(c.get("city") in ("", None) for c in calls)
    assert result["error"] == "no_geocodable_location"


def test_the_offered_city_anchors_no_state_for_the_next_turn(monkeypatch):
    # Replay 2026-10-29 (S092): New York by default, then « Atlanta ga » was
    # looked up in New York state (Atlanta, NY) — the anchor came from a city
    # the user never named.
    _spy(monkeypatch, {**_PARIS_OK, "profile_delta": {"last_city": "New York", "last_state_context": "NY"}})
    ctx = _ctx("I have a long layover between flights\nThe day after tomorrow",
               query_params={"default_place": {"city": "New York", "country_code": "US"}})

    result = geocode_location(intent=GeoIntent(), tool_context=ctx)

    assert result["profile_delta"] == {"last_city": "New York", "default_place": "New York"}
