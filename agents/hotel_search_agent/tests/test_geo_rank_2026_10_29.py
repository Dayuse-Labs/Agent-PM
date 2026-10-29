"""The centre in the pool, a distance penalty on its scale, no far filler (2026-10-29).

Side-by-side with agent-usa on 22 identical requests (prod, 2026-10-29): « un
hôtel à Paris demain » showed Ivry, Malakoff, Porte d'Italie (3.2-5.1 km)
where agent-usa showed five hotels at 1.3-1.8 km; Madrid with a pool ended on
Getafe (12 km). MCP's pages hold 5 hotels and its `score` favours the inner
suburbs (Paris: 1.0-1.2 at 3-5 km, 0.8-0.85 inside 2 km, same ratings), so
the two pages of #173 (the city's, the 5 km disc's) never held the centre.

Fixtures: the real `search_offers` pages (MCP_B2C prod, read-only probe of
2026-10-29, hotel facts only) of the search as the leaf sends it, of the same
search on the 5 km local disc, and on the 2 km core ring.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import statistics
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotel_search_agent import extra_calls, geo_rank
from hotel_search_agent.geo_rank import (
    STATE_GEO_POOL_KEY,
    STATE_GEO_RANK_KEY,
    _distance,
    await_local_pool,
    rank_pool,
    start_local_pool,
    tier,
    trim_far_cards,
)
from hotel_search_agent.response_bridge import (
    _STATE_ANCHOR_FEATURE_KEY,
    _STATE_ANCHOR_KEY,
    _STATE_RESULTS_KEY,
    capture_after_tool,
)

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "geo_rank_city_pages_2026_10_29.json").read_text()
)["cities"]


def _state(city: dict, **extra) -> dict:
    args = city["args"]
    return {
        _STATE_ANCHOR_KEY: {"latitude": args["lat"], "longitude": args["lon"], "label": None,
                            "type": "city_centroid"},
        _STATE_ANCHOR_FEATURE_KEY: "place",
        **extra,
    }


def _ctx(state: dict) -> SimpleNamespace:
    return SimpleNamespace(state=state, user_content=None)


def _pool(city: dict, *kinds: str) -> list[dict]:
    return [hotel for kind in kinds for hotel in city[kind]["results"]]


def _cards(city: dict, *kinds: str) -> list[dict]:
    """The cards of the leaf's call, its own page ranked with the given pages."""
    ctx = _ctx(_state(city, **{STATE_GEO_POOL_KEY: _pool(city, *kinds)}))
    capture_after_tool(SimpleNamespace(name="search_offers"), dict(city["args"]), ctx,
                       {"structuredContent": city["page"]})
    return ctx.state[_STATE_RESULTS_KEY]


def _median_km(cards: list[dict]) -> float:
    return statistics.median(card["distance_km"] for card in cards)


def _rating(city: dict, cards: list[dict]) -> float:
    by_id = {h["hotelId"]: h for kind in ("page", "local_page", "core_page") for h in city[kind]["results"]}
    return statistics.mean(by_id[card["hotel_id"]]["globalAverageRating"] for card in cards)


# --- the centre reaches the pool ---------------------------------------------------------------


def test_paris_shows_the_centre_not_the_inner_suburbs():
    """#173's two pages: Leveque 3.1, Drawing House 2.7, Porte d'Italie 4.3,
    Malakoff 4.7, Ivry 4.6 (median 4.3 km). With the core ring's page: the
    boosted hotel stays first, then Notre-Dame, the Marais, Canal Saint-Martin."""
    city = _FIXTURE["paris"]
    before = _cards(city, "local_page")
    after = _cards(city, "local_page", "core_page")
    assert _median_km(before) > 4.0
    assert after[0]["name"] == "Grand Hôtel Leveque"
    assert _median_km(after) <= 1.5
    assert max(card["distance_km"] for card in after) <= 3.5
    assert _rating(city, after) >= _rating(city, before) - 0.15


@pytest.mark.parametrize("name, max_km", [("london", 2.0), ("rome", 2.0), ("milano_spa", 2.0)])
def test_dense_centres_keep_their_cards_inside_the_core_ring(name, max_km):
    """London was 2.0-3.7 km (Paddington, Aldgate), Rome up to 2 km, Milano with
    a spa 1.5-3.5 km (no card under 1.4 km, while STRAF is at 0.2)."""
    city = _FIXTURE[name]
    before = _cards(city, "local_page")
    after = _cards(city, "local_page", "core_page")
    assert max(card["distance_km"] for card in after) <= max_km
    assert _median_km(after) <= _median_km(before)
    assert _rating(city, after) >= _rating(city, before) - 0.1


def test_midtown_anchor_keeps_brooklyn_and_jersey_city_off_the_cards():
    """New York searched from Midtown (the anchor itself is the geocoder's
    business): The Tillary (Brooklyn, 6.5 km) and Jersey City never come first."""
    city = _FIXTURE["ny_midtown"]
    cards = _cards(city, "local_page", "core_page")
    assert all(card["distance_km"] <= 2.0 for card in cards)
    assert "The Tillary Hotel Brooklyn" not in {card["name"] for card in cards}


# --- the distance penalty and its invariant ----------------------------------------------------


@pytest.mark.parametrize("name", sorted(_FIXTURE))
def test_no_card_comes_before_a_nearer_one_scoring_at_least_as_high(name):
    city = _FIXTURE[name]
    args = city["args"]
    ranked = rank_pool(_pool(city, "page", "local_page", "core_page"), args["lat"], args["lon"], 5.0, 2.0)
    for first, second in itertools.combinations(ranked, 2):
        d1, d2 = _distance(first, args["lat"], args["lon"]), _distance(second, args["lat"], args["lon"])
        assert not (
            tier(d2, 5.0) <= tier(d1, 5.0) and d2 < d1 and (second.get("score") or 0) >= (first.get("score") or 0)
        ), (first["name"], second["name"])


def test_the_penalty_scale_is_the_core_ring():
    """Paris, 2 km scale: Holiday Inn Gare de Lyon (1.9 km, 0.83) before Drawing
    House (2.7 km, 0.96) — on the local disc's 5 km scale the order flips."""
    city = _FIXTURE["paris"]
    args = city["args"]
    by_name = {h["name"]: h for h in _pool(city, "local_page", "core_page")}
    pair = [by_name["Drawing House"], by_name["Holiday Inn Paris - Gare de Lyon Bastille, an IHG Hotel"]]
    names = [h["name"] for h in rank_pool(pair, args["lat"], args["lon"], 5.0, 2.0)]
    assert names == ["Holiday Inn Paris - Gare de Lyon Bastille, an IHG Hotel", "Drawing House"]
    assert [h["name"] for h in rank_pool(pair, args["lat"], args["lon"], 5.0)][0] == "Drawing House"


# --- no far filler -----------------------------------------------------------------------------


def test_madrid_with_a_pool_ends_without_getafe():
    """Four hotels with a pool within 5 km of Sol, then Hotel Los Olivos
    (Getafe, 12 km) as the fifth card: dropped."""
    city = _FIXTURE["madrid_pool"]
    cards = _cards(city, "local_page", "core_page")
    assert "Hotel Los Olivos" not in {card["name"] for card in cards}
    assert len(cards) == 4
    assert all(card["distance_km"] <= 5.0 for card in cards)


def test_a_place_with_few_local_hotels_keeps_its_further_cards():
    """Two local cards only: the further ones are the offer, they stay."""
    city = _FIXTURE["madrid_pool"]
    args = city["args"]
    ctx = _ctx({STATE_GEO_RANK_KEY: {"lat": args["lat"], "lon": args["lon"], "local_km": 5.0}})
    cards = [{"name": h["name"], "latitude": h["lat"], "longitude": h["lon"]} for h in city["page"]["results"]]
    assert len([c for c in cards if _distance({"lat": c["latitude"], "lon": c["longitude"]}, args["lat"], args["lon"]) <= 5]) == 2
    assert trim_far_cards(ctx, cards) == cards


def test_a_search_not_ranked_here_is_never_trimmed():
    city = _FIXTURE["madrid_pool"]
    cards = [{"name": h["name"], "latitude": h["lat"], "longitude": h["lon"]} for h in city["page"]["results"]]
    assert trim_far_cards(_ctx({}), cards) == cards


# --- the pages: launched with the search, collected within the extra calls' budget -----------


class _Search:
    name = "search_offers"

    def __init__(self, responses: dict[float, dict | Exception], delays: dict[float, float] | None = None):
        self.responses = responses
        self.delays = delays or {}
        self.calls: list[dict] = []

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        radius = args["radiusKm"]
        await asyncio.sleep(self.delays.get(radius, 0.0))
        response = self.responses[radius]
        if isinstance(response, Exception):
            raise response
        return {"structuredContent": response}


def _run(tool: _Search, city: dict, ctx: SimpleNamespace) -> None:
    async def flow():
        start_local_pool(tool, city["args"], ctx)
        await await_local_pool(tool, city["args"], ctx, {"structuredContent": city["page"]})

    asyncio.run(flow())


def test_both_pages_are_asked_and_pooled():
    city = _FIXTURE["paris"]
    tool = _Search({5.0: city["local_page"], 2.0: city["core_page"]})
    ctx = _ctx(_state(city))
    _run(tool, city, ctx)
    assert [call["radiusKm"] for call in tool.calls] == [5.0, 2.0]
    assert ctx.state[STATE_GEO_POOL_KEY] == _pool(city, "local_page", "core_page")


def test_a_page_slower_than_2_s_is_still_waited_for():
    """#173 cut the wait at 2 s: Beverly Hills (prod 2026-10-28) then showed the
    relevance page alone — one card at 3 km, then LAX and Burbank. The wait is
    now the extra calls' budget, capped at MCP's own 5 s call timeout."""
    assert geo_rank.POOL_WAIT_SECONDS == 5.0
    city = _FIXTURE["paris"]
    tool = _Search({5.0: city["local_page"], 2.0: city["core_page"]}, {2.0: 2.1})
    ctx = _ctx(_state(city))
    _run(tool, city, ctx)
    assert ctx.state[STATE_GEO_POOL_KEY] == _pool(city, "local_page", "core_page")


def test_the_wait_never_runs_past_the_extra_calls_deadline(monkeypatch):
    monkeypatch.setattr(geo_rank, "remaining_seconds", lambda _ctx: 0.05)
    city = _FIXTURE["paris"]
    tool = _Search({5.0: city["local_page"], 2.0: city["core_page"]}, {2.0: 0.5})
    ctx = _ctx(_state(city))
    _run(tool, city, ctx)
    assert ctx.state[STATE_GEO_POOL_KEY] == city["local_page"]["results"]  # the late one is dropped
    assert not geo_rank._PENDING


def test_a_failed_page_keeps_the_other_and_stops_the_extra_calls():
    city = _FIXTURE["paris"]
    tool = _Search({5.0: city["local_page"], 2.0: RuntimeError("MCP down")})
    ctx = _ctx(_state(city))
    _run(tool, city, ctx)
    assert ctx.state[STATE_GEO_POOL_KEY] == city["local_page"]["results"]
    assert ctx.state[extra_calls.STATE_EXTRA_CALLS_STOPPED_KEY] == "error"


def test_a_place_whose_core_is_its_local_disc_asks_one_page(monkeypatch):
    """Beverly Hills, Los Angeles, Miami: the inventory's ring is 5 km, the
    local disc already."""
    monkeypatch.setattr(geo_rank, "site_radius_km", lambda lat, lon: 5.0)
    city = _FIXTURE["paris"]
    tool = _Search({5.0: city["local_page"]})
    _run(tool, city, _ctx(_state(city)))
    assert [call["radiusKm"] for call in tool.calls] == [5.0]
