"""The day after, ranked by distance like the day asked (2026-10-30).

Prod after #175 (100 real conversations, 29/10 16:28Z to 30/10 08:04Z): 18 lists
served on the day after because today's bookings were closed opened on a card
7.5 km out (median), against 1.2 km for the lists of the day asked. « Romantic,
London » showed Brentford, Wembley, Sutton (12-17 km); « Madrid » Alcobendas
and Getafe before the centre. The next-day probe made ONE call, the city's 20
km disc in relevance order, and `capture_after_tool` swapped it in after the
ranking (`geo_rank.ranked_payload`) and the far-card trim had already run.

Now the probe runs the local and core pages of the day after next to its own
call, and the swapped-in payload goes through `ranked_payload` then
`trim_far_cards`. Hotel facts below: the prod cards of conversation C044
(London, distances from Mapbox's point of London).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from hotel_search_agent.datetime_resolver import probe_next_day_after_tool
from hotel_search_agent.response_bridge import (
    STATE_DATE_FALLBACK_KEY,
    STATE_SEARCH_DATE_KEY,
    _STATE_ANCHOR_FEATURE_KEY,
    _STATE_ANCHOR_KEY,
    _STATE_RESULTS_KEY,
    capture_after_tool,
)

LONDON = (51.507322, -0.127647)


def _hotel(hotel_id: int, name: str, lat: float, lon: float, score: float, price: int = 9000) -> dict:
    return {
        "hotelId": hotel_id, "name": name, "lat": lat, "lon": lon, "score": score,
        "cityName": "london", "offers": [{
            "priceEuro": price, "priceEuroWithBookingFees": price, "availabilityDate": "2026-10-30",
            "startHour": 10, "endHour": 17,
        }],
    }


# The 20 km disc in relevance order: what prod showed (C044 T2).
FAR = [
    _hotel(1, "Holiday Inn London Brentford Lock", 51.4837, -0.3113, 1.20),
    _hotel(2, "Novotel London Wembley", 51.5560, -0.2797, 1.18),
    _hotel(3, "MSM Arena Hotel", 51.5545, -0.2620, 1.15),
    _hotel(4, "Holiday Inn LONDON - SUTTON", 51.3628, -0.1925, 1.10),
    _hotel(5, "Warren House Hotel", 51.4182, -0.2696, 1.05),
]
# The same search on the 5 km disc and the 2 km ring (C044 T3, the day asked).
CENTRAL = [
    _hotel(11, "Thistle Holborn the Kingsley", 51.5181, -0.1236, 0.85),
    _hotel(12, "Marlin Waterloo", 51.4990, -0.1110, 0.83),
    _hotel(13, "Treehouse Hotel London", 51.5173, -0.1436, 0.84),
    _hotel(14, "Leonardo Royal Hotel London St Pauls", 51.5126, -0.0989, 0.82),
    _hotel(15, "The Dover Hotel", 51.4930, -0.1460, 0.80),
]


class _Search:
    name = "search_offers"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        results = FAR if "radiusKm" not in args else CENTRAL
        return {"structuredContent": {"resolvedDate": args["date"], "total": 233, "results": results}}


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(state={
        _STATE_ANCHOR_KEY: {"latitude": LONDON[0], "longitude": LONDON[1], "label": "London",
                            "type": "city_centroid"},
        _STATE_ANCHOR_FEATURE_KEY: "place",
        STATE_SEARCH_DATE_KEY: {"date": "2026-10-29", "same_day": True},
    }, user_content=None)


def _closed_today() -> dict:
    return {"structuredContent": {"resolvedDate": "2026-10-29", "total": 0, "totalBeforeCutoff": 233,
                                  "results": []}}


def _serve(tool: _Search, ctx: SimpleNamespace) -> list[dict]:
    args = {"lat": LONDON[0], "lon": LONDON[1], "date": "2026-10-29", "from": 0}
    response = _closed_today()
    asyncio.run(probe_next_day_after_tool(tool, args, ctx, response))
    capture_after_tool(tool, args, ctx, response)
    return ctx.state[_STATE_RESULTS_KEY]


def test_the_next_day_probe_also_fetches_the_local_and_core_pages():
    tool = _Search()
    ctx = _ctx()
    _serve(tool, ctx)
    assert all(call["date"] == "2026-10-30" for call in tool.calls)
    assert sorted(call.get("radiusKm", 20.0) for call in tool.calls) == [2.0, 5.0, 20.0]
    assert ctx.state[STATE_DATE_FALLBACK_KEY]["pool"]


def test_the_day_after_opens_on_the_centre_not_on_brentford():
    cards = _serve(_Search(), _ctx())
    assert cards[0]["distance_km"] <= 2.0
    assert all(card["distance_km"] <= 3.0 for card in cards)
    assert "Holiday Inn London Brentford Lock" not in {card["name"] for card in cards}


def test_without_the_pages_the_day_after_is_still_ranked_and_trimmed():
    """The local pages may not come back (deadline, error): the relevance page
    alone is still ordered nearest tier first — here all far, kept as the offer."""

    class _OnlyDisc(_Search):
        async def run_async(self, *, args, tool_context):
            self.calls.append(dict(args))
            results = [*FAR[:3], CENTRAL[0], CENTRAL[1]] if "radiusKm" not in args else []
            return {"structuredContent": {"resolvedDate": args["date"], "total": 233, "results": results}}

    cards = _serve(_OnlyDisc(), _ctx())
    assert [card["name"] for card in cards[:2]] == ["Thistle Holborn the Kingsley", "Marlin Waterloo"]
