"""Prod audit 2026-11-02: a party total whose split is unknown never empties
the page.

The concierge sends such a total as `query_params.party_total`; the leaf
keeps the offers that could host it (`possible_party`). Since #173, 10 of 10
« how many adults and children? » were asked over 0 cards, for numbers that
were no party at all (« 30km », « From 4pm », « 3 horas »…). When that filter
alone empties the page, the page is served without it and the relaxation says
so (`party`, with the most a room here sleeps): the concierge ends on one
closed question and drops the total.
"""
from __future__ import annotations

from types import SimpleNamespace

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import (
    convert_a2a_part_to_genai_part,
    convert_genai_part_to_a2a_part,
)
from google.genai import types as genai_types

from hotel_search_agent.response_bridge import (
    STATE_APPLIED_AMENITIES_KEY,
    STATE_PREFERRED_AMENITIES_KEY,
    STATE_SEARCH_DATE_KEY,
    capture_after_tool,
    emit_search_datapart,
)

_ARGS = {"lat": 46.519, "lon": 6.632, "from": 0, "radiusKm": 30, "date": "2026-11-03"}


def _hotel(i: int, capacity: int) -> dict:
    return {
        "hotelId": i, "name": f"Hotel {i}", "cityName": "lausanne", "countryName": "Switzerland",
        "starRating": 4, "globalAverageRating": 4.4, "distanceKm": 1.0 + i,
        "offers": [{"priceEuro": 10400, "priceEuroWithBookingFees": 11100, "startHour": 10, "startMinute": 0,
                    "endHour": 17, "endMinute": 0, "availabilityDate": "2026-11-03", "ratePlanId": i,
                    "capacity": capacity}],
    }


def _turn(party_total: int, *hotels: dict) -> dict:
    part = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {"party_total": party_total},
                                                        "profile_in": {}}))
    content = genai_types.Content(role="user", parts=[genai_types.Part(text="x"), convert_a2a_part_to_genai_part(part)])
    state = {STATE_APPLIED_AMENITIES_KEY: [], STATE_PREFERRED_AMENITIES_KEY: [],
             STATE_SEARCH_DATE_KEY: {"date": "2026-11-03", "same_day": False}}
    ctx = SimpleNamespace(state=state, user_content=content)
    payload = {"resolvedDate": "2026-11-03", "total": len(hotels), "results": list(hotels)}
    capture_after_tool(SimpleNamespace(name="search_offers"), dict(_ARGS), ctx, {"structuredContent": payload})
    out = emit_search_datapart(ctx)
    return next(convert_genai_part_to_a2a_part(p).root.data for p in out.parts if p.inline_data is not None)


def test_a_total_no_room_here_sleeps_serves_the_page_and_says_so():
    data = _turn(30, _hotel(1, 2), _hotel(2, 4))
    assert [card["name"] for card in data["results"]] == ["Hotel 1", "Hotel 2"]
    assert data["relaxation"] == {"steps": ["party"], "searched_date": "2026-11-03",
                                  "party": {"total": 30, "max_capacity": 4}}


def test_a_total_some_room_sleeps_keeps_its_filter_and_no_relaxation():
    data = _turn(3, _hotel(1, 2), _hotel(2, 4))
    assert [card["name"] for card in data["results"]] == ["Hotel 2"]
    assert "relaxation" not in data
