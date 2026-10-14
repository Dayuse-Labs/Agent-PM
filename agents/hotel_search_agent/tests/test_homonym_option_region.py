"""QA14707 (Q14): a homonym option chosen by its number reaches the leaf with its region.

Two options of a homonym question can share `city` and `country_code`
(« Springfield (Illinois, United States) » / « Springfield (Missouri, United
States) »). The concierge resolves the option the user picked from the stored
`Clarification` and sends its region as data, `profile_in.region_anchor`. The
tool applies it itself (`_fill_place_from_profile`, never a before-tool
callback: ADK drops an argument the tool does not declare), and the core
narrows the candidates Mapbox returned to that region — the geocoder still
decides, the region is never a query term or a coordinate.

Mapbox, Search Box and the inventory are fakes.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.tools.function_tool import FunctionTool
from google.genai import types as genai_types

from b2c_common.geo_intent import CityRef, GeoIntent, Place
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_core, geocode_location
from hotel_search_agent.mapbox_client import GeocodeCandidate


def _city(name, region, cc, lat, lon, rank):
    return GeocodeCandidate(
        latitude=lat,
        longitude=lon,
        name=name,
        place_name=f"{name}, {region}, United States",
        place_formatted=f"{region}, United States",
        feature_type="place",
        country_code=cc,
        region=region,
        bbox=None,
        rank=rank,
    )


ILLINOIS = _city("Springfield", "Illinois", "US", 39.7990, -89.6440, 0)
MISSOURI = _city("Springfield", "Missouri", "US", 37.2090, -93.2923, 1)
#: Both in the inventory tier with the same footprint: a genuine homonym.
INVENTORY = {39.799: 12, 37.209: 12}


class _V6:
    def __init__(self, *candidates):
        self.candidates = list(candidates)
        self.calls: list[tuple] = []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        return list(self.candidates)


class _Inventory:
    def count_near(self, lat, lon, *, radius_km=25.0):
        return INVENTORY.get(round(lat, 3), 0)


class _NoSearchBox:
    def forward_candidates(self, *args, **kwargs):
        raise AssertionError("a city homonym never reaches Search Box")


@pytest.fixture
def v6(monkeypatch):
    fake = _V6(ILLINOIS, MISSOURI)
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: fake)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _NoSearchBox())
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory())
    return fake


#: The concierge's prefix on the answer turn (`pending_clarification_context`).
PREFIX = (
    "EARLIER REQUEST (the user's own words, not searched yet): a hotel in Springfield tomorrow\n"
    'YOU ASKED: {"kind": "homonym", "subject": "Springfield", "options": ['
    '{"label": "Springfield (Illinois, United States)", "city": "Springfield", '
    '"region": "Illinois", "country_code": "US"}, '
    '{"label": "Springfield (Missouri, United States)", "city": "Springfield", '
    '"region": "Missouri", "country_code": "US"}]}\n'
    "REPLY:"
)
#: What the concierge sends once option 2 is chosen (Q05 + Q14).
CHOSEN = {"city": "Springfield", "country_anchor": "US", "region_anchor": "Missouri",
          "zone": None, "state_anchor": None}


def _ctx(*texts, profile_in=None):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=text) for text in texts]
    parts.append(convert_a2a_part_to_genai_part(datapart))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


class TestTheChosenRegion:
    def test_without_the_region_the_same_question_comes_back(self, v6):
        # The control: city and country alone are still the homonym (Q05).
        profile = {key: value for key, value in CHOSEN.items() if key != "region_anchor"}

        result = geocode_location(intent=GeoIntent(), tool_context=_ctx(PREFIX, "2", profile_in=profile))

        assert result["error"] == "geocode_ambiguous"
        assert [o["region"] for o in result["clarification"]["options"]] == ["Illinois", "Missouri"]

    @pytest.mark.parametrize(
        "intent",
        [
            GeoIntent(),
            # The model may also read the city off the prefix: same city, same rule.
            GeoIntent(city=CityRef(mention="Springfield", canonical="Springfield")),
        ],
    )
    def test_the_chosen_option_is_resolved_and_nothing_is_asked(self, v6, intent):
        result = geocode_location(intent=intent, tool_context=_ctx(PREFIX, "2", profile_in=CHOSEN))

        assert "clarification" not in result
        assert result["ok"] is True
        assert (result["latitude"], result["longitude"]) == (MISSOURI.latitude, MISSOURI.longitude)
        # One lookup, the city alone: the region narrowed what Mapbox returned,
        # it was never added to the query or turned into a filter.
        assert v6.calls == [("Springfield", "US")]

    def test_the_real_tool_reads_the_region_from_the_inbound_datapart(self, v6):
        tool = FunctionTool(geocode_location)

        result = asyncio.run(
            tool.run_async(args={"intent": {}}, tool_context=_ctx(PREFIX, "2", profile_in=CHOSEN))
        )

        assert result["ok"] is True
        assert (result["latitude"], result["longitude"]) == (MISSOURI.latitude, MISSOURI.longitude)

    def test_the_region_is_never_a_model_argument(self):
        properties = FunctionTool(geocode_location)._get_declaration().parameters_json_schema["properties"]

        assert "region_chosen" not in properties
        assert "region_anchor" not in properties


class TestTheRegionGoesWithItsCity:
    @pytest.fixture
    def core(self, monkeypatch):
        seen: list[dict] = []
        monkeypatch.setattr(geocode_tool, "geocode_core", lambda **kw: seen.append(kw) or {"ok": False})
        return seen

    def test_another_city_this_turn_leaves_it_out(self, core):
        intent = GeoIntent(places=[Place(mention="Chicago", kind="city", canonical="Chicago")])

        geocode_location(intent=intent, tool_context=_ctx("what about Chicago", profile_in=CHOSEN))

        assert core[0]["city"] == "Chicago"
        assert "region_chosen" not in core[0]

    def test_the_carried_city_takes_it(self, core):
        geocode_location(intent=GeoIntent(), tool_context=_ctx("later in the evening", profile_in=CHOSEN))

        assert (core[0]["city"], core[0]["region_chosen"]) == ("Springfield", "Missouri")

    def test_a_postcode_turn_carries_nothing_over(self, core):
        # Q08: a postcode names a new place by itself.
        intent = GeoIntent(places=[Place(mention="65806", kind="admin_district", postal_code="65806")])

        geocode_location(intent=intent, tool_context=_ctx("near 65806", profile_in=CHOSEN))

        assert "region_chosen" not in core[0]


class TestTheCoreNarrowsOnly:
    def test_a_region_no_candidate_has_narrows_nothing(self, v6):
        result = geocode_core(city="Springfield", country_code="US", region_chosen="Texas")

        assert result["error"] == "geocode_ambiguous"

    def test_a_state_named_this_turn_speaks_for_itself(self, v6):
        # « Springfield IL »: the user's own state wins over the earlier pick.
        result = geocode_core(city="Springfield", country_code="US", region_named="IL",
                              region_chosen="Missouri", raw_user_message="Springfield IL")

        assert result["ok"] is True
        assert (result["latitude"], result["longitude"]) == (ILLINOIS.latitude, ILLINOIS.longitude)

    def test_case_and_accents_do_not_matter(self, v6):
        result = geocode_core(city="Springfield", country_code="US", region_chosen="missouri")

        assert (result["latitude"], result["longitude"]) == (MISSOURI.latitude, MISSOURI.longitude)
