"""QA14707 (Q26): a bare postcode is searched around its centroid, not across its city.

H3' on gpt-6-luna (`qa14707-postcode-only-fr`, « un hôtel dans le 75009 demain
après-midi », run `h3-2026-10-15-luna-plan-r3`): the geocoding was right
(« 75009, Paris, France », 48.875676, 2.343131) but its origin type was
`city_centroid`, so `inject_landmark_radius` left MCP its 20 km city default and
the inventory ranking returned hotels 3.3 km and 6.4 km away and in Gennevilliers.

The user named a small area: the origin is a `poi`, and the S4 rule gives
`search_offers` the site's tight ring, nearest first. The Mapbox answers are the
REAL v6 recordings of H5 (DQ9), served to the real client by the harness of
`test_postcode_resolution.py`; the chain run here is the leaf's own callbacks:
`geocode_location` -> `capture_after_tool` -> `inject_landmark_radius`.
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
from hotel_search_agent import geocode_tool, response_bridge
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.mapbox_client import MapboxClient
from hotel_search_agent.response_bridge import (
    capture_after_tool,
    emit_search_datapart,
    find_datapart,
    inject_landmark_radius,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mapbox_v6"

#: (q, types) as recorded by H5 -> the recorded response.
_RECORDED = {
    ("2 boulevard poissonnière 75009", "address,street"): "address_2_bd_poissonniere_75009.json",
    ("75009", "postcode"): "postcode_75009.json",
    ("13001 marseille", "postcode"): "postcode_13001_marseille.json",
    ("11580", "postcode"): "postcode_11580.json",
}


def _handle(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    name = _RECORDED.get((params["q"].casefold(), params.get("types")))
    if name is None:
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    country = params.get("country")
    if country:  # applied the way Mapbox applies it
        data["features"] = [
            f for f in data["features"]
            if f["properties"]["context"]["country"]["country_code"].lower() == country
        ]
    return httpx.Response(200, json=data)


class _SearchBox:
    def forward_candidates(self, query, **kwargs):
        return []


class _NoInventory:
    def count_near(self, lat, lon, *, radius_km=25.0):
        return 0


@pytest.fixture
def mapbox(monkeypatch):
    """The H5 recordings behind the real `MapboxClient` (as test_postcode_resolution)."""
    client = MapboxClient("test-token", client=httpx.Client(transport=httpx.MockTransport(_handle)))
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: client)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _SearchBox())
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _NoInventory())


def _postcode(code, **kwargs):
    return Place(mention=code, kind="admin_district", canonical=code, postal_code=code, **kwargs)


def _address():
    return Place(mention="2 boulevard Poissonnière", kind="address",
                 canonical="2 Boulevard Poissonnière", postal_code="75009")


def _ctx(text):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": {}})
    )
    parts = [genai_types.Part(text=text), convert_a2a_part_to_genai_part(datapart)]
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


class _Tool:
    def __init__(self, name):
        self.name = name


class _Ring:
    """`per_km` hotels per km of radius: enough to pick a ring."""

    def __init__(self, per_km):
        self.per_km = per_km

    def count_near(self, lat, lon, *, radius_km):
        return int(radius_km * self.per_km)


def _geocode(intent, ctx, **kwargs):
    # Through the real FunctionTool declaration path of the leaf: the tool the
    # model calls is this function, wrapped.
    assert FunctionTool(geocode_location).name == "geocode_location"
    return geocode_location(intent=intent, tool_context=ctx, **kwargs)


def _search_args(monkeypatch, result, ctx, per_km=10):
    """What `search_offers` is sent after this geocode, via the leaf's callbacks."""
    monkeypatch.setattr(response_bridge, "get_inventory", lambda: _Ring(per_km))
    capture_after_tool(_Tool("geocode_location"), {}, ctx, result)
    args = {"lat": result["latitude"], "lon": result["longitude"]}
    inject_landmark_radius(_Tool("search_offers"), args, ctx)
    return args


class TestABarePostcodeGetsTheTightDisc:
    def test_75009_is_a_poi_origin_and_search_offers_gets_the_site_ring(self, mapbox, monkeypatch):
        ctx = _ctx("un hôtel dans le 75009 demain après-midi")
        result = _geocode(GeoIntent(places=[_postcode("75009", country="FR")]), ctx)

        assert (result["latitude"], result["longitude"]) == (48.875676, 2.343131)
        assert result["distance_origin_type"] == "poi"
        args = _search_args(monkeypatch, result, ctx)
        # Dense Paris: the smallest ring holding 10 hotels is the 2 km one,
        # inside the 3 km the QA item checks; never the 20 km city default.
        assert args["radiusKm"] == 2.0
        assert args["sort"] == "distance"
        assert (args["lat"], args["lon"]) == (48.875676, 2.343131)

    def test_a_sparse_area_widens_the_ring_by_inventory_not_by_the_origin_type(
        self, mapbox, monkeypatch
    ):
        ctx = _ctx("un hôtel dans le 75009")
        result = _geocode(GeoIntent(places=[_postcode("75009", country="FR")]), ctx)

        args = _search_args(monkeypatch, result, ctx, per_km=0)

        assert args["radiusKm"] == 50.0

    @pytest.mark.parametrize(
        ("places", "country", "locale"),
        [
            ([_postcode("13001"), Place(mention="marseille", kind="city", canonical="Marseille")],
             "FR", "en-US"),
            ([_postcode("11580", country="US")], "US", None),
        ],
    )
    def test_the_tie_break_fixtures_take_the_same_branch(
        self, mapbox, monkeypatch, places, country, locale
    ):
        ctx = _ctx(" ".join(["hotel", *(p.mention for p in places)]))
        result = _geocode(GeoIntent(places=places), ctx, locale=locale)

        assert result["ok"] is True
        assert result["country_code"] == country
        assert result["distance_origin_type"] == "poi"
        assert _search_args(monkeypatch, result, ctx)["sort"] == "distance"


class TestNothingElseMoves:
    def test_an_address_with_its_postcode_keeps_its_own_poi_origin(self, mapbox):
        result = _geocode(
            GeoIntent(places=[_address()]),
            _ctx("Un hôtel près du 2 boulevard Poissonnière 75009 demain"),
        )

        assert result["distance_origin_type"] == "poi"
        assert (result["latitude"], result["longitude"]) == (48.870905, 2.347691)

    def test_the_follow_up_turn_persists_the_city_only_no_zone(self, mapbox):
        result = _geocode(GeoIntent(places=[_postcode("75009", country="FR")]),
                          _ctx("un hôtel dans le 75009"))

        delta = result["profile_delta"]
        assert delta["last_city"] == "Paris"
        assert "zone" not in delta
        assert "distance_origin" not in delta

    # A city alone keeps `city_centroid`: pinned by
    # test_geocode_tool.py::TestRadiusFollowsTheRequestNotTheGeocoder.


class TestAnEmptyTightDiscIsNeverASilentAnswer:
    def test_zero_offers_around_the_postcode_is_an_honest_empty_outcome(self, mapbox, monkeypatch):
        """Same path as a POI with no offer: `search_offers` ran and came back
        empty, the leaf emits `results: []` plus the code-built « no offers »
        line (`_outcome_text`, response_bridge.py), which the synthesis must
        report. There is no automatic widening of the ring on an empty answer:
        the ring is chosen BEFORE the call, from the inventory, and widens to
        50 km where the area is sparse (previous test)."""
        ctx = _ctx("un hôtel dans le 75009")
        result = _geocode(GeoIntent(places=[_postcode("75009", country="FR")]), ctx)
        args = _search_args(monkeypatch, result, ctx)
        capture_after_tool(
            _Tool("search_offers"), args, ctx,
            {"structuredContent": {"results": [], "total": 0}, "isError": False},
        )

        content = emit_search_datapart(ctx)

        assert content is not None
        payload = find_datapart(content.parts)
        assert payload["results"] == []
        assert any("No day-use offers found" in (p.text or "") for p in content.parts)
