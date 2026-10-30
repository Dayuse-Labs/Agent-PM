"""« Demain, plus près » (2026-10-30).

Prod after #175: 6 conversations of a same-day evening search around a precise
place, 0 click. Arabellapark (München) at 18h: the offers still open were
3.9-4.6 km away (Rilano, Ramada Messe, Moxy Messe); the next day, the Westin
Grand and the Four Points are 0.2-0.3 km away (seen in the same session's
third turn). Coordinates: the spot as geocoded in prod, hotels placed at the
distances prod showed.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from hotel_search_agent.datetime_resolver import probe_next_day_after_tool
from hotel_search_agent.response_bridge import (
    STATE_RESOLVED_DATE_KEY,
    STATE_SEARCH_DATE_KEY,
    _STATE_ANCHOR_KEY,
    _STATE_RESULTS_KEY,
    capture_after_tool,
)

SPOT = (48.15269343, 11.62100352)


def _hotel(hotel_id: int, name: str, km_east: float, day: str) -> dict:
    return {"hotelId": hotel_id, "name": name, "lat": SPOT[0], "lon": SPOT[1] + km_east / 74.1,
            "offers": [{"priceEuro": 10500, "priceEuroWithBookingFees": 10500, "availabilityDate": day,
                        "startHour": 14, "endHour": 21}]}


TONIGHT = [_hotel(1, "The Rilano Hotel München", -3.9, "2026-10-29"),
           _hotel(2, "Rilano 24/7 Hotel München", -3.9, "2026-10-29"),
           _hotel(3, "Ramada Encore Munich Messe", 4.1, "2026-10-29"),
           _hotel(4, "Moxy Munich Messe", 4.6, "2026-10-29")]
TOMORROW = [_hotel(5, "The Westin Grand Munich", 0.2, "2026-10-30"),
            _hotel(6, "Four Points by Sheraton Munich Arabellapark", 0.3, "2026-10-30"),
            _hotel(7, "Leonardo Hotel Munich Arabellapark", 0.7, "2026-10-30"),
            _hotel(8, "Courtyard by Marriott Munich City East", 2.6, "2026-10-30")]


class _Search:
    name = "search_offers"

    def __init__(self):
        self.calls: list[dict] = []

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        return {"structuredContent": {"total": 19, "results": TOMORROW}}


def _ctx(profile_in=None) -> SimpleNamespace:
    datapart = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}}))
    parts = [genai_types.Part(text="Tageszimmer in arabellapark"), convert_a2a_part_to_genai_part(datapart)]
    return SimpleNamespace(state={
        _STATE_ANCHOR_KEY: {"latitude": SPOT[0], "longitude": SPOT[1], "label": "Arabellapark", "type": "poi"},
        STATE_SEARCH_DATE_KEY: {"date": "2026-10-29", "same_day": True},
    }, user_content=genai_types.Content(role="user", parts=parts))


def _tonight() -> dict:
    return {"structuredContent": {"total": 4, "totalBeforeCutoff": 19, "results": TONIGHT}}


def _serve(ctx) -> tuple[_Search, list[dict]]:
    tool = _Search()
    args = {"lat": SPOT[0], "lon": SPOT[1], "date": "2026-10-29", "radiusKm": 5, "sortBy": "distance", "from": 0}
    asyncio.run(probe_next_day_after_tool(tool, args, ctx, _tonight()))
    capture_after_tool(tool, args, ctx, _tonight())
    return tool, ctx.state[_STATE_RESULTS_KEY]


def test_tonight_far_and_tomorrow_close_shows_tomorrow_said_as_such():
    ctx = _ctx()
    tool, cards = _serve(ctx)

    assert tool.calls[0]["date"] == "2026-10-30"
    assert cards[0]["name"] == "The Westin Grand Munich"
    assert ctx.state[STATE_SEARCH_DATE_KEY] == {
        "date": "2026-10-30", "same_day": False, "closer_from": "2026-10-29", "tonight_nearest_km": 3.9,
    }
    assert ctx.state[STATE_RESOLVED_DATE_KEY]["date"] == "2026-10-30"


def test_a_day_the_user_stated_is_never_swapped():
    ctx = _ctx({"date": "2026-10-29"})
    tool, cards = _serve(ctx)

    assert tool.calls == []
    assert cards[0]["name"] == "The Rilano Hotel München"


def test_close_offers_tonight_need_no_other_day():
    ctx = _ctx()
    tool = _Search()
    near = [_hotel(i, f"Near {i}", 0.3 * i, "2026-10-29") for i in range(1, 5)]
    response = {"structuredContent": {"total": 4, "totalBeforeCutoff": 19, "results": near}}
    asyncio.run(probe_next_day_after_tool(tool, {"lat": SPOT[0], "lon": SPOT[1], "date": "2026-10-29"}, ctx, response))
    assert tool.calls == []
