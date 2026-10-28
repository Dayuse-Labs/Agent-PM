"""Proximity first, at comparable quality, around a city's centre (prod 2026-10-28).

Prod traces since the switch: « Paris » alone showed Gennevilliers (10.7 km),
Antony (11.3 km); « London » Brentford (13 km), Croydon (15 km) and no central
card; Los Angeles with a pool put The Delphi Hotel (0.4 km) 4th behind Marina
del Rey (19 km). MCP ranks the whole 20 km disc by `score`, which ignores
distance, and the leaf kept its first page.

Fixtures: the real `search_offers` pages (MCP_B2C prod, read-only probe of
2026-10-28, hotel facts only) of the city search as the leaf sends it, and of
the same search on the 5 km local disc (`geo_rank.start_local_pool`).
"""
from __future__ import annotations

import asyncio
import json
import statistics
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotel_search_agent import geo_rank
from hotel_search_agent.geo_rank import (
    STATE_GEO_POOL_KEY,
    await_local_pool,
    local_radius_km,
    rank_pool,
    ranked_payload,
    start_local_pool,
    tier,
)
from hotel_search_agent.response_bridge import (
    _STATE_ANCHOR_FEATURE_KEY,
    _STATE_ANCHOR_KEY,
    _STATE_RESULTS_KEY,
    STATE_NEARBY_KEY,
    capture_after_tool,
)

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "geo_rank_city_pages_2026_10_28.json").read_text()
)["cities"]


def _city(name: str) -> dict:
    return _FIXTURE[name]


def _state(city: dict, *, anchor_type: str = "city_centroid", feature: str | None = "place", **extra) -> dict:
    args = city["args"]
    return {
        _STATE_ANCHOR_KEY: {"latitude": args["lat"], "longitude": args["lon"], "label": None, "type": anchor_type},
        _STATE_ANCHOR_FEATURE_KEY: feature,
        **extra,
    }


def _ctx(state: dict) -> SimpleNamespace:
    return SimpleNamespace(state=state, user_content=None)


class _Search:
    name = "search_offers"

    def __init__(self, response: dict | None = None, delay: float = 0.0, error: Exception | None = None):
        self.response = response
        self.delay = delay
        self.error = error
        self.calls: list[dict] = []

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return {"structuredContent": self.response}


def _cards(city: dict, state: dict, args: dict | None = None) -> list[dict]:
    ctx = _ctx(state)
    capture_after_tool(_Search(), dict(args or city["args"]), ctx, {"structuredContent": city["page"]})
    return ctx.state[_STATE_RESULTS_KEY]


# --- the order invariant -----------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_FIXTURE))
def test_no_card_from_a_further_tier_comes_before_a_nearer_one(name):
    city = _city(name)
    args = city["args"]
    pool = city["page"]["results"] + city["local_page"]["results"]
    ranked = rank_pool(pool, args["lat"], args["lon"], 5.0)
    tiers = [tier(item["distanceKm"], 5.0) for item in ranked]
    assert tiers == sorted(tiers)
    assert len({item["hotelId"] for item in ranked}) == len(ranked)  # each hotel once


def test_paris_cards_come_from_the_city_not_its_suburbs():
    """Before: 3.1, 7.5, 10.7, 11.3, 6.2 km (median 7.5). The boosted hotel of
    MCP's page stays first: it is local too."""
    city = _city("paris")
    cards = _cards(city, _state(city, **{STATE_GEO_POOL_KEY: city["local_page"]["results"]}))
    assert cards[0]["name"] == "Grand Hôtel Leveque"
    assert all(card["distance_km"] <= 5.0 for card in cards)
    assert statistics.median(card["distance_km"] for card in cards) < 5.0


def test_london_gets_central_cards_at_the_same_rating():
    """Before: Brentford 13.1, Croydon 14.7, Wembley 12.1… (median 13.1 km)."""
    city = _city("london")
    before = city["page"]["results"]
    cards = _cards(city, _state(city, **{STATE_GEO_POOL_KEY: city["local_page"]["results"]}))
    assert statistics.median(card["distance_km"] for card in cards) <= 3.0
    by_id = {h["hotelId"]: h for h in city["page"]["results"] + city["local_page"]["results"]}
    rating = statistics.mean(by_id[card["hotel_id"]]["globalAverageRating"] for card in cards)
    assert rating >= statistics.mean(h["globalAverageRating"] for h in before) - 0.1


def test_los_angeles_pool_puts_the_downtown_hotel_first():
    """The Delphi Hotel (0.4 km) was 4th behind Marina del Rey (19.2 km)."""
    city = _city("la_pool")
    cards = _cards(city, _state(city, **{STATE_GEO_POOL_KEY: city["local_page"]["results"]}))
    assert cards[0]["name"] == "The Delphi Hotel"
    assert max(card["distance_km"] for card in cards) <= 5.0


def test_without_the_local_page_the_own_page_is_still_ordered_by_tier():
    """The local page timed out: Munich's own page, local cards first."""
    city = _city("munich")
    cards = _cards(city, _state(city))
    assert [card["distance_km"] for card in cards][:2] == [1.2, 3.1]
    assert {card["hotel_id"] for card in cards} == {h["hotelId"] for h in city["page"]["results"]}


def test_a_device_fix_is_ranked_the_same_way():
    city = _city("la_pool")
    cards = _cards(city, _state(city, anchor_type="gps", feature="gps",
                                **{STATE_GEO_POOL_KEY: city["local_page"]["results"]}))
    assert cards[0]["name"] == "The Delphi Hotel"


@pytest.mark.parametrize(
    "state_kwargs, args_extra",
    [
        ({"anchor_type": "poi", "feature": "poi"}, {}),  # a landmark: its own ring, nearest first
        ({"feature": "area"}, {}),  # a département carried as an area: arbitrary centroid
        ({"feature": "region"}, {}),
        ({STATE_NEARBY_KEY: True}, {}),  # the user asked for further
        ({}, {"sortBy": "distance"}),  # a nearest-first rescue
    ],
)
def test_other_searches_keep_mcp_order(state_kwargs, args_extra):
    city = _city("london")
    state = _state(city, **{k: v for k, v in state_kwargs.items() if k in ("anchor_type", "feature")})
    state.update({k: v for k, v in state_kwargs.items() if k not in ("anchor_type", "feature")})
    state[STATE_GEO_POOL_KEY] = city["local_page"]["results"]
    cards = _cards(city, state, {**city["args"], **args_extra})
    expected = city["page"]["results"]
    if state_kwargs.get("anchor_type") == "poi":
        # Unchanged too: a landmark's page is put nearest first, as before.
        expected = sorted(expected, key=lambda h: h["distanceKm"])
    assert [card["hotel_id"] for card in cards] == [h["hotelId"] for h in expected]


def test_the_pool_serves_one_search_only():
    city = _city("paris")
    ctx = _ctx(_state(city, **{STATE_GEO_POOL_KEY: city["local_page"]["results"]}))
    ranked_payload(ctx, city["args"], city["page"])
    assert ctx.state[STATE_GEO_POOL_KEY] is None


# --- the local page: launched with the search, collected after it ------------------------------


def _run_call(tool: _Search, args: dict, state: dict, primary: dict, primary_delay: float = 0.0) -> SimpleNamespace:
    """The leaf's call: last before-tool callback, the MCP call, then the
    after-tool collection — inside one event loop, as ADK runs them."""
    ctx = _ctx(state)

    async def flow():
        start_local_pool(tool, args, ctx)
        await asyncio.sleep(primary_delay)  # the search's own call
        await await_local_pool(tool, args, ctx, primary)

    asyncio.run(flow())
    return ctx


def test_the_local_page_is_the_same_search_on_the_local_disc():
    city = _city("paris")
    tool = _Search(city["local_page"])
    sent = {**city["args"], "hotelEquipmentIds": [35], "timeSlot": {"startHour": 14, "endHour": 18}}
    ctx = _run_call(tool, sent, _state(city), {"structuredContent": city["page"]})
    [local] = tool.calls
    assert local == {**sent, "radiusKm": local_radius_km(sent["lat"], sent["lon"])}
    assert local["radiusKm"] == 5.0
    assert ctx.state[STATE_GEO_POOL_KEY] == city["local_page"]["results"]


def test_the_next_page_asks_the_next_local_page():
    city = _city("paris")
    tool = _Search(city["local_page"])
    _run_call(tool, {**city["args"], "from": 5}, _state(city), {"structuredContent": city["page"]})
    assert tool.calls[0]["from"] == 5


def test_it_runs_in_parallel_with_the_search():
    """Launched before the search's own call returns: no added latency."""
    city = _city("paris")
    tool = _Search(city["local_page"], delay=0.2)
    ctx = _ctx(_state(city))

    async def flow():
        start_local_pool(tool, city["args"], ctx)
        await asyncio.sleep(0)
        assert tool.calls, "the local page must already be on its way"
        await asyncio.sleep(0.25)
        t0 = asyncio.get_running_loop().time()
        await await_local_pool(tool, city["args"], ctx, {"structuredContent": city["page"]})
        return asyncio.get_running_loop().time() - t0

    assert asyncio.run(flow()) < 0.1


def test_a_local_page_too_slow_is_dropped(monkeypatch):
    monkeypatch.setattr(geo_rank, "POOL_WAIT_SECONDS", 0.05)
    city = _city("paris")
    ctx = _run_call(_Search(city["local_page"], delay=1.0), city["args"], _state(city),
                    {"structuredContent": city["page"]})
    assert ctx.state[STATE_GEO_POOL_KEY] is None
    assert not geo_rank._PENDING


def test_a_failed_local_page_keeps_the_own_page():
    city = _city("paris")
    ctx = _run_call(_Search(error=RuntimeError("MCP down")), city["args"], _state(city),
                    {"structuredContent": city["page"]})
    assert ctx.state[STATE_GEO_POOL_KEY] is None


def test_a_failed_search_cancels_the_local_page():
    city = _city("paris")
    tool = _Search(city["local_page"], delay=1.0)
    ctx = _run_call(tool, city["args"], _state(city), {"isError": True, "content": []})
    assert ctx.state[STATE_GEO_POOL_KEY] is None
    assert not geo_rank._PENDING


@pytest.mark.parametrize(
    "state_kwargs, args_extra",
    [
        ({"anchor_type": "poi", "feature": "poi"}, {}),
        ({"feature": "area"}, {}),
        ({}, {"sortBy": "distance"}),
        ({}, {"radiusKm": 5.0}),  # the whole disc is local already (a sparse place widened to it)
    ],
)
def test_no_second_call_when_it_cannot_change_the_cards(state_kwargs, args_extra):
    city = _city("paris")
    tool = _Search(city["local_page"])
    _run_call(tool, {**city["args"], **args_extra}, _state(city, **state_kwargs),
              {"structuredContent": city["page"]})
    assert tool.calls == []


def test_a_sparse_place_makes_no_second_call(monkeypatch):
    """Galveston: no inventory hotel within 20 km, local radius 50 km ≥ the disc."""
    monkeypatch.setattr(geo_rank, "site_radius_km", lambda lat, lon: 50.0)
    city = _city("paris")
    tool = _Search(city["local_page"])
    _run_call(tool, city["args"], _state(city), {"structuredContent": city["page"]})
    assert tool.calls == []


def test_the_local_radius_follows_the_inventory(monkeypatch):
    monkeypatch.setattr(geo_rank, "site_radius_km", lambda lat, lon: 2.0)
    assert local_radius_km(0.0, 0.0) == 5.0  # a dense centre: never under the floor
    monkeypatch.setattr(geo_rank, "site_radius_km", lambda lat, lon: 30.0)
    assert local_radius_km(0.0, 0.0) == 30.0
