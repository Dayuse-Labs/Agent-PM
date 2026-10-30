"""Numbers read as filters, and the default city of a reply that named one (2026-10-30).

Prod after #175 (100 real conversations): « 18+ » (a check-in age) read as
18 adults, then 8 empty turns in a row; « Paris », « Wien », « Dubai », « New
York », « Istanbul » — the city chips of the place question — answered with
« Sans ville indiquée, voici des hôtels à … » five times.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from b2c_common.geo_intent import GeoIntent
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.relaxation import rescue_empty_search_after_tool
from hotel_search_agent.response_bridge import (
    STATE_SEARCH_DATE_KEY,
    _STATE_BUDGET_TIMESLOT_KEY,
    _STATE_RELAXATION_ADDED_KEY,
    _STATE_RESULTS_KEY,
    capture_after_tool,
)


def _hotel(hotel_id: int, capacity: int) -> dict:
    return {"hotelId": hotel_id, "name": f"Houston {hotel_id}", "offers": [{
        "priceEuro": 9000, "priceEuroWithBookingFees": 9000, "capacity": capacity,
        "availabilityDate": "2026-11-01", "startHour": 10, "endHour": 18,
    }]}


class _Search:
    name = "search_offers"

    def __init__(self):
        self.calls: list[dict] = []

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        party = args.get("adults") or 0
        results = [h for h in (_hotel(1, 2), _hotel(2, 4), _hotel(3, 2)) if party <= h["offers"][0]["capacity"]]
        return {"structuredContent": {"total": len(results), "results": results}}


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(state={STATE_SEARCH_DATE_KEY: {"date": "2026-11-01", "same_day": False}},
                           user_content=None)


def test_a_party_no_offer_sleeps_shows_the_cards_without_it_and_is_not_carried():
    tool, ctx = _Search(), _ctx()
    args = {"lat": 29.76, "lon": -95.36, "date": "2026-11-01", "adults": 18}
    response = {"structuredContent": {"total": 0, "results": []}}

    asyncio.run(rescue_empty_search_after_tool(tool, args, ctx, response))
    capture_after_tool(tool, args, ctx, response)

    assert "adults" not in tool.calls[0]
    assert len(ctx.state[_STATE_RESULTS_KEY]) == 3
    relaxed = ctx.state[_STATE_RELAXATION_ADDED_KEY]
    assert relaxed["steps"] == ["party"]
    assert relaxed["party"] == {"adults": 18, "children": None, "max_capacity": 4}
    assert "adults" not in (ctx.state.get(_STATE_BUDGET_TIMESLOT_KEY) or {})


# --- the default city -----------------------------------------------------------------------


def _geo_ctx(text: str, query_params: dict) -> SimpleNamespace:
    datapart = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": query_params, "profile_in": {}}))
    parts = [genai_types.Part(text=text), convert_a2a_part_to_genai_part(datapart)]
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _spy(monkeypatch):
    calls: list[dict] = []

    def core(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "latitude": 1.0, "longitude": 2.0, "resolved_place": kwargs["city"],
                "profile_delta": {"last_city": kwargs["city"]}}

    monkeypatch.setattr(geocode_tool, "geocode_core", core)
    return calls


OFFER = {"default_place": {"city": "Paris", "country_code": "FR"}, "place_chips": ["Paris", "Lyon", "Bordeaux"]}


def test_a_reply_that_is_the_offered_city_is_that_city_named_without_the_default_note(monkeypatch):
    calls = _spy(monkeypatch)

    result = geocode_location(intent=GeoIntent(), tool_context=_geo_ctx("Paris", OFFER))

    assert [c["city"] for c in calls] == ["Paris"]
    assert "default_place" not in result
    assert "default_place" not in result["profile_delta"]


def test_a_reply_that_is_another_city_chip_searches_that_city(monkeypatch):
    calls = _spy(monkeypatch)

    result = geocode_location(intent=GeoIntent(), tool_context=_geo_ctx("lyon", OFFER))

    assert [c["city"] for c in calls] == ["Lyon"]
    assert "default_place" not in result


def test_a_reply_with_no_place_still_falls_back_on_the_market_city_and_says_so(monkeypatch):
    calls = _spy(monkeypatch)

    result = geocode_location(intent=GeoIntent(), tool_context=_geo_ctx("Demain", OFFER))

    assert [c["city"] for c in calls] == ["Paris"]
    assert result["default_place"] == "Paris"
