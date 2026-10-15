"""QA14707 (Q21, H3 RC6): a homonym option picked by the user is looked up by its own name.

H3 `geo7-manhattan-answer` plan-r1 (trace 0fbae06a9ce3f6d01179f2954134307a):
the leaf asked which « Manhattan », the user answered « New York ». The
concierge sent the option's city, country and region (Q05, Q14), but the
reply « New York » also gave a state, which went into the v6 query
(« Manhattan, New York ») and switched off Q14's narrowing. Mapbox answered
New York City, the echo of « Manhattan » refused it, and with no zone there is
no tier 2: `geocode_echo_mismatch`.

The H3 answer turn is served from the REAL v6 responses recorded on 2026-10-15
(H6, DQ9) for « Manhattan » and « Manhattan, New York » (country=us,
language=fr, default types), through the real `MapboxClient`.

The street branch (Q20) holds the same state rules (mocked candidates): a
named, anchored or chosen state never lets it resolve a street in another
state.
"""
from __future__ import annotations

import asyncio
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
from hotel_search_agent.geocode_tool import (
    geocode_core,
    geocode_location,
    inject_profile_geo_context,
)
from hotel_search_agent.mapbox_client import ADDRESS_TYPES, CANDIDATE_TYPES, GeocodeCandidate, MapboxClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mapbox_v6"

#: (q, types) as recorded by H6 -> the recorded response.
_RECORDED = {
    ("manhattan", CANDIDATE_TYPES): "place_manhattan_us_fr.json",
    ("manhattan, new york", CANDIDATE_TYPES): "place_manhattan_new_york_us_fr.json",
}

MANHATTAN_NY = "Manhattan, État de New York, États-Unis"
NEW_YORK_CITY = "New York, État de New York, États-Unis"

#: The concierge's prefix on the answer turn (`pending_clarification_context`),
#: the shape the H3 leaf input showed: the earlier request and the question
#: asked, as their own text part before the user's words.
PREFIX = (
    "EARLIER REQUEST (the user's own words, not searched yet): un hôtel à Manhattan demain\n"
    'YOU ASKED: {"kind": "homonym", "subject": "Manhattan", "options": ['
    '{"label": "Manhattan (État de New York, États-Unis)", "city": "Manhattan", '
    '"region": "État de New York", "country_code": "US"}, '
    '{"label": "Manhattan (Kansas, États-Unis)", "city": "Manhattan", '
    '"region": "Kansas", "country_code": "US"}]}\n'
    "REPLY:"
)
REPLY = "New York"
#: What the concierge sends once option 1 is chosen (Q05 + Q14).
PICKED = {
    "city": "Manhattan",
    "country_anchor": "US",
    "region_anchor": "État de New York",
    "language": "fr",
}
INTENT = {"places": [{"mention": "Manhattan", "kind": "city", "canonical": "Manhattan"}]}


class _RecordedMapbox:
    """The real `MapboxClient`, its HTTP answered from the H6 recordings."""

    def __init__(self):
        self.requests: list[dict] = []
        self.client = MapboxClient(
            "test-token", client=httpx.Client(transport=httpx.MockTransport(self._handle))
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(params)
        name = _RECORDED.get((params["q"].casefold(), params.get("types")))
        if name is None:
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        country = params.get("country")
        if country:
            data["features"] = [
                f for f in data["features"]
                if f["properties"]["context"]["country"]["country_code"].lower() == country
            ]
        return httpx.Response(200, json=data)


class _NycInventory:
    """Hotels around New York City only: Manhattan NY and NYC are both in the
    inventory tier, the other Manhattans are not."""

    def count_near(self, lat, lon, *, radius_km=25.0):
        return 200 if abs(lat - 40.75) < 0.3 and abs(lon + 73.98) < 0.3 else 0


class _NoSearchBox:
    def forward_candidates(self, *args, **kwargs):
        raise AssertionError("a picked city never reaches Search Box")


@pytest.fixture
def recorded(monkeypatch):
    fake = _RecordedMapbox()
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: fake.client)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _NoSearchBox())
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _NycInventory())
    return fake


def _ctx(*texts, profile_in=None):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=text) for text in texts]
    parts.append(convert_a2a_part_to_genai_part(datapart))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _answer_turn(profile_in: dict) -> dict:
    """The leaf's tool call as the runner makes it: the before-tool callback,
    then the real FunctionTool."""
    tool = FunctionTool(geocode_location)
    ctx = _ctx(PREFIX, REPLY, profile_in=profile_in)
    args: dict = {"intent": INTENT}
    inject_profile_geo_context(tool, args, ctx)
    return asyncio.run(tool.run_async(args=args, tool_context=ctx))


class TestTheManhattanAnswer:
    def test_the_picked_option_is_resolved(self, recorded):
        result = _answer_turn(PICKED)

        assert result["ok"] is True
        assert result["resolved_place"] == MANHATTAN_NY
        assert result["resolved_feature_type"] == "locality"
        assert "clarification" not in result
        # The picked option by its own name, with no state term from the reply.
        assert [r["q"] for r in recorded.requests] == ["Manhattan"]
        assert recorded.requests[0]["country"] == "us"
        assert recorded.requests[0]["language"] == "fr"

    def test_without_the_pick_the_reply_still_names_the_state(self, recorded):
        # Negative control: no `region_anchor`, so nothing was picked. The
        # state written in the message feeds the query exactly as before Q21,
        # and the turn ends where H3 measured it.
        profile = {key: value for key, value in PICKED.items() if key != "region_anchor"}

        result = _answer_turn(profile)

        assert [r["q"] for r in recorded.requests] == ["Manhattan, New York"]
        assert result["error"] == "geocode_echo_mismatch"
        assert result["diagnostics"]["resolved_place"] == NEW_YORK_CITY


# --- the street branch holds the state ------------------------------------------


def _street(region: str, lat: float, lon: float, rank: int) -> GeocodeCandidate:
    return GeocodeCandidate(
        latitude=lat,
        longitude=lon,
        name="Main Street",
        place_name=f"Main Street, Springfield, {region}, United States",
        place_formatted=f"Springfield, {region}, United States",
        feature_type="street",
        country_code="US",
        region=region,
        bbox=None,
        rank=rank,
        place="Springfield",
    )


def _city(region: str, lat: float, lon: float, rank: int) -> GeocodeCandidate:
    return GeocodeCandidate(
        latitude=lat,
        longitude=lon,
        name="Springfield",
        place_name=f"Springfield, {region}, United States",
        place_formatted=f"{region}, United States",
        feature_type="place",
        country_code="US",
        region=region,
        bbox=None,
        rank=rank,
    )


MO_STREET = _street("Missouri", 37.2100, -93.2900, 0)
IL_STREET = _street("Illinois", 39.8000, -89.6500, 1)
IL_CITY = _city("Illinois", 39.7990, -89.6440, 0)
MO_CITY = _city("Missouri", 37.2090, -93.2923, 1)


class _V6:
    """Mapbox mocked: the address lookup returns the Missouri street first."""

    def __init__(self, streets):
        self.streets = list(streets)
        self.calls: list[tuple] = []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None, types=None):
        self.calls.append((query, country, types))
        return list(self.streets) if types == ADDRESS_TYPES else [IL_CITY, MO_CITY]


class _SpringfieldInventory:
    def count_near(self, lat, lon, *, radius_km=25.0):
        return 12 if round(lat, 3) in (39.799, 37.209) else 0


def _install(monkeypatch, streets=(MO_STREET, IL_STREET)) -> _V6:
    fake = _V6(streets)
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: fake)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _NoSearchBox())
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _SpringfieldInventory())
    return fake


STREET_ARGS = {"city": "Springfield", "zone": "Main Street", "zone_kind": "street"}
STREET_TEXT = "a hotel on Main Street, Springfield tomorrow"
STREET_INTENT = GeoIntent(
    places=[Place(mention="Main Street", kind="street", canonical="Main Street", city="Springfield")]
)


def _coords(result: dict) -> tuple[float, float] | None:
    return (result["latitude"], result["longitude"]) if result.get("ok") else None


def _at(candidate: GeocodeCandidate) -> tuple[float, float]:
    return (candidate.latitude, candidate.longitude)


class TestTheStreetBranchHoldsTheState:
    def test_a_named_state(self, monkeypatch):
        v6 = _install(monkeypatch)

        result = geocode_core(**STREET_ARGS, region_named="IL", raw_user_message=STREET_TEXT)

        assert result["ok"] is True
        assert _coords(result) == _at(IL_STREET)
        assert v6.calls[0] == ("Main Street, Springfield", None, ADDRESS_TYPES)

    def test_an_anchored_state(self, monkeypatch):
        _install(monkeypatch)

        result = geocode_core(**STREET_ARGS, profile_state_context="IL", raw_user_message=STREET_TEXT)

        assert result["ok"] is True
        assert _coords(result) == _at(IL_STREET)

    def test_a_chosen_region_from_the_profile(self, monkeypatch):
        _install(monkeypatch)
        profile_in = {"city": "Springfield", "country_anchor": "US", "region_anchor": "Illinois"}

        result = geocode_location(
            intent=STREET_INTENT, tool_context=_ctx(STREET_TEXT, profile_in=profile_in)
        )

        assert result["ok"] is True
        assert _coords(result) == _at(IL_STREET)

    @pytest.mark.parametrize(
        "state",
        [
            {"region_named": "IL"},
            {"profile_state_context": "IL"},
            {"region_chosen": "Illinois"},
        ],
    )
    def test_with_only_the_other_states_street_it_falls_through_with_the_state(
        self, monkeypatch, state
    ):
        # The Missouri street alone: none is kept, and the pre-Q20 path
        # resolves the city with the state, never the Missouri street.
        v6 = _install(monkeypatch, streets=(MO_STREET,))

        result = geocode_core(**STREET_ARGS, **state, raw_user_message=STREET_TEXT)

        assert _coords(result) == _at(IL_CITY)
        assert "Missouri" not in str(result)
        assert v6.calls[0][2] == ADDRESS_TYPES
        assert v6.calls[1][2] is None

    def test_with_no_state_the_first_street_in_the_city_is_kept(self, monkeypatch):
        # Negative control: nothing designated, Q20's rule as it was.
        v6 = _install(monkeypatch)

        result = geocode_core(**STREET_ARGS, raw_user_message=STREET_TEXT)

        assert _coords(result) == _at(MO_STREET)
        assert v6.calls == [("Main Street, Springfield", None, ADDRESS_TYPES)]
