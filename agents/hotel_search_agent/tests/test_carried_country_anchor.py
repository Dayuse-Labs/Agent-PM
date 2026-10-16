"""QA14707 (Q19): a carried country is a hard filter only for the city it was carried with.

H3 `geo-poi-multiturn-country-switch` (trace 170d28eb...): in London, « actually
make it paris » sent Mapbox `country=gb` (the carried anchor), v6 returned
nothing there, Search Box answered « Paris Baguette, London ». The anchor is the
country of the CARRIED city; it goes with that city only.

Mapbox v6 is served from the H6 recordings (`place_paris_gb_en.json`: country gb,
0 features; `place_paris_en.json`: no country), Search Box is a fake.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.tools.function_tool import FunctionTool
from google.genai import types as genai_types

from b2c_common.geo_intent import GeoIntent, Place
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.mapbox_client import GeocodeCandidate, MapboxClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mapbox_v6"

BAGUETTE = GeocodeCandidate(
    latitude=51.5136, longitude=-0.1365, name="Paris Baguette",
    place_name="Paris Baguette, London, United Kingdom",
    place_formatted="London, United Kingdom", feature_type="poi",
    country_code="GB", region="England", bbox=None, rank=0,
)


class _RecordedMapbox:
    def __init__(self):
        self.requests: list[dict] = []
        self.client = MapboxClient(
            "test-token", client=httpx.Client(transport=httpx.MockTransport(self._handle))
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(params)
        name = "place_paris_gb_en.json" if params.get("country") == "gb" else "place_paris_en.json"
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        country = params.get("country")
        if country:
            data["features"] = [
                f for f in data["features"]
                if f["properties"]["context"]["country"]["country_code"].lower() == country
            ]
        return httpx.Response(200, json=data)


class _SearchBox:
    def __init__(self):
        self.calls: list[tuple] = []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        return [BAGUETTE] if country == "GB" else []


class _Inventory:
    """Only the French Paris has hotels, as in the real inventory."""

    def count_near(self, lat, lon, *, radius_km=25.0):
        return 500 if abs(lat - 48.85) < 1 else 0


@pytest.fixture
def mapbox(monkeypatch):
    recorded = _RecordedMapbox()
    recorded.searchbox = _SearchBox()
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: recorded.client)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: recorded.searchbox)
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory())
    return recorded


def _ctx(*texts, profile_in=None):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=text) for text in texts]
    parts.append(convert_a2a_part_to_genai_part(datapart))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


LONDON = {"city": "London", "country_anchor": "GB", "locale": "en-GB"}


def test_a_new_city_leaves_the_carried_country_behind(mapbox):
    intent = GeoIntent(places=[Place(mention="paris", kind="city", canonical="Paris")])

    result = geocode_location(intent=intent, tool_context=_ctx("actually make it paris", profile_in=LONDON))

    assert all("country" not in r for r in mapbox.requests)
    assert all(country is None for _, country in mapbox.searchbox.calls)
    assert result["ok"] is True
    assert "Paris" in result["resolved_place"] and "Baguette" not in result["resolved_place"]
    assert result["country_code"] == "FR"


def test_the_real_tool_does_the_same(mapbox):
    import asyncio

    tool = FunctionTool(geocode_location)
    result = asyncio.run(tool.run_async(
        args={"intent": {"places": [{"mention": "paris", "kind": "city", "canonical": "Paris"}]}},
        tool_context=_ctx("actually make it paris", profile_in=LONDON),
    ))

    assert all("country" not in r for r in mapbox.requests)
    assert all(country is None for _, country in mapbox.searchbox.calls)
    assert result["country_code"] == "FR"


def test_a_follow_up_keeps_the_anchor_with_the_carried_city(mapbox):
    # Negative control: no new place, the carried city is searched again.
    geocode_location(intent=GeoIntent(), tool_context=_ctx("moins cher", profile_in=LONDON))

    assert mapbox.requests and all(r.get("country") == "gb" for r in mapbox.requests)


def test_a_new_zone_in_the_carried_city_keeps_the_filter(mapbox):
    intent = GeoIntent(places=[Place(
        mention="les champs élysées", kind="landmark", canonical="Champs-Élysées", city="Paris")])

    geocode_location(
        intent=intent,
        tool_context=_ctx("près des champs élysées",
                          profile_in={"city": "Paris", "country_anchor": "FR"}),
    )

    assert mapbox.requests and all(r.get("country") == "fr" for r in mapbox.requests)
