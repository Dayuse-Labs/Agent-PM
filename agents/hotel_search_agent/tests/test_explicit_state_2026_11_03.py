"""Prod 2026-11-02 (`ba44795`): a US state the user wrote was lost, and an
island was taken for a county that shares one of its words.

A. Session 2eb025cb, « What is the closest day use option I have near Auburn,
   AL? ». The leaf's model put « AL » in the place's `region` (and the city's),
   not in `region_named`, the only field `_place_args` read; the free-text tier
   skips « al » (a word in Spanish and Italian). Without a state, the resolver
   asked between Washington and California, the two Auburns with hotels:
   Alabama was not even an option. The user typed « Auburn Alabama » and left
   a negative feedback.
B. Session 580064bf, « Amelia Island » (kind `region`): `_area_match` took
   « Amelia County, Virginia », whose name echoes the request by its longest
   word (« amelia » ties with « island »). The Virginia anchor was kept for
   three empty searches and the conversation was lost.

Each `GeoIntent` below is the one the model really sent (Langfuse, tool
input). The candidate lists are what Mapbox returned when probed live on
2026-11-03. Offline: Mapbox, Search Box and the inventory are fakes.
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
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.mapbox_client import GeocodeCandidate

#: `mapbox_client.AREA_TYPES`, spelled out so this file imports on any tree.
AREA_TYPES = "region,district"


def _c(name, place_name, region, *, ftype="place", lat, lon, cc="US", rank=0):
    return GeocodeCandidate(
        latitude=lat, longitude=lon, name=name, place_name=place_name,
        place_formatted=place_name.split(", ", 1)[-1], feature_type=ftype,
        country_code=cc, region=region, bbox=None, rank=rank,
    )


AUBURN_WA = _c("Auburn", "Auburn, Washington, United States", "Washington", lat=47.307, lon=-122.229)
AUBURN_CA = _c("Auburn", "Auburn, California, United States", "California", lat=38.897, lon=-121.076,
               rank=1)
AUBURN_AL = _c("Auburn", "Auburn, Alabama, United States", "Alabama", lat=32.607, lon=-85.482, rank=2)
AMELIA_COUNTY = _c("Amelia County", "Amelia County, Virginia, United States", "Virginia",
                   ftype="district", lat=37.343, lon=-77.981)
ISLAND_COUNTY = _c("Island County", "Island County, Washington, United States", "Washington",
                   ftype="district", lat=48.218, lon=-122.686, rank=1)
AMELIA_ISLAND = _c("Amelia Island", "Amelia Island, Fernandina Beach, Florida 32034, United States",
                   "Florida", ftype="poi", lat=30.627, lon=-81.461)
CHILTON_COUNTY = _c("Chilton County", "Chilton County, Alabama, United States", "Alabama",
                    ftype="district", lat=32.839, lon=-86.631)
KREIS_KAISERSLAUTERN = _c("Kreis Kaiserslautern", "Kreis Kaiserslautern, Rheinland-Pfalz, Deutschland",
                          "Rheinland-Pfalz", ftype="district", lat=49.4, lon=7.7, cc="DE")

#: Hotels within 25 km (inventory snapshot): the Auburns of Washington and
#: California have some, the one of Alabama none — which is why it fell out of
#: the question.
INVENTORY = {47.307: 20, 38.897: 8, 32.607: 0}

V6 = {
    # A bare « Auburn »: Mapbox's own order.
    ("Auburn", "US"): [AUBURN_WA, AUBURN_CA, AUBURN_AL],
    # With the state in the query, that state's Auburn comes first.
    ("Auburn, Alabama", "US"): [AUBURN_AL, AUBURN_WA, AUBURN_CA],
    ("Auburn, Washington", "US"): [AUBURN_WA, AUBURN_CA, AUBURN_AL],
    ("Auburn, California", "US"): [AUBURN_CA, AUBURN_WA, AUBURN_AL],
    ("Amelia Island", "US", "area"): [AMELIA_COUNTY, ISLAND_COUNTY],
    ("Amelia Island", None, "area"): [AMELIA_COUNTY, ISLAND_COUNTY],
    ("Amelia County", "US", "area"): [AMELIA_COUNTY],
    ("Hilton Head Island", "US", "area"): [CHILTON_COUNTY],
    ("Hilton Head Island", None, "area"): [CHILTON_COUNTY],
    ("Landkreis Kaiserslautern und Landkreis Kusel", "DE", "area"): [KREIS_KAISERSLAUTERN],
}
SEARCH_BOX = {("Amelia Island", "US"): [AMELIA_ISLAND]}


class _V6:
    def __init__(self):
        self.calls: list[tuple] = []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None,
                           types=None, **kwargs):
        key = (query, (country or "").upper() or None)
        self.calls.append((query, key[1], types))
        if types == AREA_TYPES:
            return list(V6.get((*key, "area"), []))
        return list(V6.get(key, []))


class _SearchBox:
    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        return list(SEARCH_BOX.get((query, (country or "").upper() or None), []))


class _Inventory:
    def count_near(self, lat, lon, *, radius_km=25.0):
        return INVENTORY.get(round(lat, 3), 0)


@pytest.fixture
def v6(monkeypatch):
    fake = _V6()
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: fake)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _SearchBox())
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory())
    return fake


def _ctx(*texts, profile_in=None):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=t) for t in texts]
    parts.append(convert_a2a_part_to_genai_part(datapart))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _city(mention, canonical="Auburn", *, region=None, region_named=None) -> GeoIntent:
    """The shape the leaf's model sends for a city, its state in `region`."""
    return GeoIntent(
        places=[Place(mention=mention, kind="city", canonical=canonical, city=canonical,
                      country="US", region=region)],
        city=CityRef(mention=mention, canonical=canonical, region=region, country="US"),
        region_named=region_named, relation="near", carryover="new",
    )


def _at(result, candidate) -> bool:
    return (result.get("latitude"), result.get("longitude")) == (candidate.latitude, candidate.longitude)


def _options(result) -> list[str]:
    return [o["region"] for o in (result.get("clarification") or {}).get("options", [])]


# --- A: a state written with the place is the user's ---------------------------

PROD_MESSAGE = "What is the closest day use option I have near Auburn, AL?"
#: The tool input of trace f3cbdf51, verbatim.
PROD_INTENT = {
    "schema_version": "1.1",
    "places": [{"mention": "Auburn, AL", "kind": "city", "canonical": "Auburn", "city": "Auburn",
                "country": "US", "region": "AL", "city_inferred": False}],
    "city": {"mention": "Auburn, AL", "canonical": "Auburn", "region": "AL", "country": "US"},
    "relation": "near", "carryover": "new",
}


class TestAStateWrittenWithThePlace:
    def test_the_prod_intent_resolves_auburn_alabama(self, v6):
        result = geocode_location(intent=GeoIntent.model_validate(PROD_INTENT), locale="en",
                                  tool_context=_ctx(PROD_MESSAGE))

        assert result["ok"] is True
        assert "clarification" not in result
        assert _at(result, AUBURN_AL)
        # The state rides with the city to the next turn (« Friday? »).
        assert result["profile_delta"]["last_state_context"] == "AL"
        # The state is a query term, as for `region_named`.
        assert ("Auburn, Alabama", "US", None) in v6.calls

    def test_the_real_tool_converts_the_models_dict(self, v6):
        # The shape ADK hands the tool: a dict, converted by the declaration.
        tool = FunctionTool(geocode_location)

        result = asyncio.run(tool.run_async(
            args={"intent": PROD_INTENT, "locale": "en"}, tool_context=_ctx(PROD_MESSAGE),
        ))

        assert result["ok"] is True
        assert _at(result, AUBURN_AL)

    def test_the_answer_the_user_had_to_type_still_resolves(self, v6):
        # Witness, trace 1a3da8eb: « Auburn Alabama », with `region_named`.
        intent = _city("Auburn Alabama", region="AL", region_named="AL")

        result = geocode_location(intent=intent, locale="en", tool_context=_ctx("Auburn Alabama"))

        assert _at(result, AUBURN_AL)

    def test_the_states_name_written_in_full(self, v6):
        intent = _city("Auburn Alabama", region="AL")

        result = geocode_location(intent=intent, locale="en", tool_context=_ctx("near Auburn Alabama"))

        assert _at(result, AUBURN_AL)

    @pytest.mark.parametrize(
        ("message", "mention", "region", "expected"),
        [
            # Another explicit state, whose code the free-text tier also skips.
            ("Day use hotel near Auburn, WA tomorrow", "Auburn, WA", "WA", AUBURN_WA),
            ("day room in Auburn, CA please", "Auburn, CA", "CA", AUBURN_CA),
            # The model wrote the state's name, the user its code.
            ("near Auburn, AL", "Auburn, AL", "Alabama", AUBURN_AL),
        ],
    )
    def test_another_explicit_state(self, v6, message, mention, region, expected):
        result = geocode_location(intent=_city(mention, region=region), locale="en",
                                  tool_context=_ctx(message))

        assert result["ok"] is True
        assert _at(result, expected)

    def test_a_later_correction_wins_over_the_anchored_state(self, v6):
        # Alabama anchored on the turn before; the user now writes California.
        intent = _city("Auburn, California", region="CA")

        result = geocode_location(
            intent=intent, locale="en", profile_state_context="AL", profile_location_hint="Auburn",
            tool_context=_ctx("Sorry, I meant Auburn, California"),
        )

        assert _at(result, AUBURN_CA)
        assert result["profile_delta"]["last_state_context"] == "CA"


class TestNoStateTheUserDidNotWrite:
    """The homonym question stays when the user gave no state."""

    def test_auburn_alone_is_still_asked(self, v6):
        result = geocode_location(intent=_city("Auburn"), locale="en",
                                  tool_context=_ctx("day use near Auburn"))

        assert result["error"] == "geocode_ambiguous"
        assert _options(result) == ["Washington", "California"]

    def test_a_state_only_the_model_knows_decides_nothing(self, v6):
        # The model may fill `region` from its own knowledge: not the user's word.
        result = geocode_location(intent=_city("Auburn", region="AL"), locale="en",
                                  tool_context=_ctx("day use near Auburn"))

        assert result["error"] == "geocode_ambiguous"
        assert _options(result) == ["Washington", "California"]

    def test_a_mention_the_user_did_not_write(self, v6):
        # « Auburn, AL » as the model's mention, but the user wrote « Auburn ».
        result = geocode_location(intent=_city("Auburn, AL", region="AL"), locale="en",
                                  tool_context=_ctx("a hotel near Auburn tonight"))

        assert result["error"] == "geocode_ambiguous"

    @pytest.mark.parametrize(
        ("message", "mention", "canonical", "region", "expected"),
        [
            # A state's name inside the city's own name is not a state written.
            ("a day room in Kansas City", "Kansas City", "Kansas City", "KS", None),
            ("a day room in Kansas City, Kansas", "Kansas City, Kansas", "Kansas City", "KS", "KS"),
            ("a hotel in Virginia Beach", "Virginia Beach", "Virginia Beach", "VA", None),
            ("Auburn, AL", "Auburn, AL", "Auburn", "AL", "AL"),
        ],
    )
    def test_the_places_own_name_is_not_its_state(self, message, mention, canonical, region, expected):
        claims = geocode_tool._Claims(message, message)

        place = Place(mention=mention, kind="city", canonical=canonical, region=region)

        assert claims.region(place) == expected

    def test_the_code_elsewhere_in_the_message_is_not_the_places(self, v6):
        # « al » is a word of the message, not of the place's mention.
        result = geocode_location(intent=_city("Auburn", region="AL"), locale="es",
                                  tool_context=_ctx("un hotel cerca al centro de Auburn"))

        assert result["error"] == "geocode_ambiguous"


# --- B: an area is the one asked for, not one sharing a word -------------------


def _area(mention, canonical, kind="region", country="US") -> GeoIntent:
    return GeoIntent(places=[Place(mention=mention, kind=kind, canonical=canonical, country=country)],
                     relation="whole_city", carryover="new")


class TestAnAreaIsTheOneAskedFor:
    def test_amelia_island_is_the_island_in_florida(self, v6):
        # The tool input of trace fd3877c1, verbatim.
        intent = GeoIntent.model_validate({
            "schema_version": "1.1",
            "places": [{"mention": "Amelia Island", "kind": "region", "canonical": "Amelia Island",
                        "city": None, "country": "US", "postal_code": None, "city_inferred": False}],
            "city": {"mention": "Amelia Island", "canonical": "Amelia Island", "country": "US"},
            "country_named": None, "relation": "whole_city", "carryover": "new",
        })

        result = geocode_location(intent=intent, locale="en",
                                  tool_context=_ctx("Anniversary spa day", "Amelia Island"))

        assert result["ok"] is True
        assert _at(result, AMELIA_ISLAND)
        assert "Virginia" not in result["resolved_place"]
        # Carried as the destination, an area, in its own state.
        assert result["profile_delta"]["last_city"] == "Amelia Island"
        assert result["profile_delta"]["city_is_area"] is True
        assert result["profile_delta"]["last_state_context"] == "FL"

    def test_the_next_turn_searches_the_island_again(self, v6):
        # Replay of 580064bf, turn 3 « Friday November 6th »: no place named,
        # the carried island is searched again — never « in which city? ».
        profile = {"city": "Amelia Island", "city_is_area": True, "zone": "Amelia Island",
                   "state_anchor": "FL", "entry_market_country": "US"}

        result = geocode_location(intent=GeoIntent(), locale="en", profile_state_context="FL",
                                  profile_location_hint="Amelia Island",
                                  tool_context=_ctx("Friday November 6th", profile_in=profile))

        assert result["ok"] is True
        assert "clarification" not in result
        assert _at(result, AMELIA_ISLAND)

    def test_a_county_that_only_shares_a_word_is_never_taken(self, v6):
        # Replay 2026-11-03: « Hilton Head Island » -> Chilton County, Alabama.
        result = geocode_location(intent=_area("Hilton Head Island", "Hilton Head Island"),
                                  locale="en", tool_context=_ctx("Hilton Head Island"))

        assert "Chilton" not in (result.get("resolved_place") or "")
        assert result["error"] == "geocode_ambiguous"  # the honest « where is that? »

    def test_the_county_asked_for_is_still_found(self, v6):
        result = geocode_location(intent=_area("Amelia County", "Amelia County", "admin_district"),
                                  locale="en", tool_context=_ctx("Amelia County"))

        assert _at(result, AMELIA_COUNTY)

    def test_an_area_named_inside_a_longer_request(self, v6):
        # Witness, real conversation 8900fe08: two districts in one name; the
        # first is searched, as before.
        intent = _area("Landkreisen Kaiserslautern und Kusel",
                       "Landkreis Kaiserslautern und Landkreis Kusel", "admin_district", "DE")

        result = geocode_location(
            intent=intent, locale="de",
            tool_context=_ctx("ob es ein Tageshotel in den beiden Landkreisen Kaiserslautern und Kusel gibt"),
        )

        assert _at(result, KREIS_KAISERSLAUTERN)
