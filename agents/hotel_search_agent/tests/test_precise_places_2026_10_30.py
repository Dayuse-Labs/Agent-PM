"""Precise places that came back as a city centre (prod after #175, 2026-10-30).

7 conversations of the 100 real ones since #175, and not one click: the
airport of Incheon → the centre of Seoul (the only card 50 km from the
airport); « st pete clearwater airport » → Clearwater, Kansas (Wichita, 1 750
km); « Colborne » (Ontario) → a neighbourhood of Hamilton (cards 173-212 km
out); « Tsim Sha Tsui », « Mong Kok » → « Hong Kong », the centre of the island
across the harbour, labelled `poi`; « quartier Rogier » → « Bruxelles », `poi`.

Each `GeoIntent` is the one the leaf's model sent (tool input of the trace).
Candidates: what Mapbox v6 and Search Box returned, probed live on 2026-10-30
(names, types, countries, coordinates as returned); inventory counts are
fakes that reproduce prod's choice of homonym.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from b2c_common.clarification import Clarification
from b2c_common.geo_intent import GeoIntent
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.mapbox_client import GeocodeCandidate


def _c(name, place_name, cc, region, *, ftype="place", lat=0.0, lon=0.0, rank=0):
    return GeocodeCandidate(
        latitude=lat, longitude=lon, name=name, place_name=place_name, place_formatted="",
        feature_type=ftype, country_code=cc, region=region, bbox=None, rank=rank,
    )


SEOUL = _c("Seoul", "Seoul, South Korea", "KR", "Seoul", lat=37.566679, lon=126.978291)
INCHEON_AIRPORT = _c(
    "Incheon International Airport",
    "Incheon International Airport, 272 Gonghang-ro, Incheon, 22382, South Korea", "KR", "",
    ftype="poi", lat=37.4495, lon=126.4507,
)
CLEARWATER_FL = _c("Clearwater", "Clearwater, Florida, United States", "US", "Florida",
                   lat=27.9623, lon=-82.8017)
CLEARWATER_KS = _c("Clearwater", "Clearwater, Kansas, United States", "US", "Kansas",
                   lat=37.5046, lon=-97.5060, rank=5)
CLEARWATER_MN = _c("Clearwater", "Clearwater, Minnesota, United States", "US", "Minnesota",
                   lat=45.4193, lon=-94.0489, rank=3)
PIE_AIRPORT = _c(
    "St. Petersburg–Clearwater International Airport",
    "St. Petersburg–Clearwater International Airport, Spadco Drive, Clearwater, Florida 33762, United States",
    "US", "Florida", ftype="poi", lat=27.9068, lon=-82.6908,
)
MSP_AIRPORT = _c(
    "Minneapolis–Saint Paul International Airport",
    "Minneapolis–Saint Paul International Airport, 4300 Glumack Drive, Minneapolis, Minnesota 55111, United States",
    "US", "Minnesota", ftype="poi", lat=44.8836, lon=-93.2115, rank=1,
)
COLBORNE = _c("Colborne", "Colborne, Ontario, Canada", "CA", "Ontario", lat=44.0050, lon=-77.8880)
COLBORNE_SIMCOE = _c("Colborne", "Colborne, Simcoe, Ontario, Canada", "CA", "Ontario",
                     ftype="locality", lat=42.8582, lon=-80.3114, rank=1)
COLBORNE_DUNDAS = _c("Colborne", "Colborne, Dundas, Ontario, Canada", "CA", "Ontario",
                     ftype="neighborhood", lat=43.2681, lon=-79.9644, rank=2)
HONG_KONG = _c("Hong Kong", "Hong Kong", "HK", "Hong Kong", lat=22.279356, lon=114.16255)
BRUSSELS = _c("Brussels", "Bruxelles, Région de Bruxelles-Capitale, Belgique", "BE",
              "Région de Bruxelles-Capitale", lat=50.8551, lon=4.35121)

#: Hotels within 25 km. Clearwater, Kansas has Wichita's around it, the
#: Florida town too few for the tier (prod chose Kansas); Hamilton's hotels sit
#: around the Dundas neighbourhood.
INVENTORY = {37.567: 300, 37.45: 40, 37.505: 30, 27.962: 2, 27.907: 2, 45.419: 0,
             44.005: 0, 42.858: 1, 43.268: 40, 22.279: 138, 50.855: 58}


class _V6:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None, types=None, **kw):
        self.calls.append((query, country, types))
        return list(self.answers.get((query, (country or "").upper() or None), []))


class _SearchBox:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kw):
        self.calls.append((query, country, proximity))
        return list(self.answers.get(query, []))


class _Inventory:
    def count_near(self, lat, lon, *, radius_km=25.0):
        return INVENTORY.get(round(lat, 3), 0)

    def dense_centre(self, lat, lon):
        return None


@pytest.fixture
def geo(monkeypatch):
    def patch(v6, box=None):
        fake_v6, fake_box = _V6(v6), _SearchBox(box or {})
        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: fake_v6)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: fake_box)
        monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory())
        return fake_v6, fake_box
    return patch


def _run(intent: dict, text: str, profile_in=None, locale="en"):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=text), convert_a2a_part_to_genai_part(datapart)]
    ctx = SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))
    return geocode_location(
        intent=GeoIntent.model_validate(intent), locale=locale, language_hint=locale[:2], tool_context=ctx,
    )


# --- the spot under its own name ---------------------------------------------------------------

INCHEON = {  # C001
    "places": [{"mention": "Inchon airport", "kind": "airport", "canonical": "Incheon International Airport",
                "city": "Incheon", "country": "KR", "city_inferred": True}],
    "city": {"mention": "Seoul", "canonical": "Seoul", "country": "KR"},
    "country_named": "KR", "relation": "near", "carryover": "new",
}


def test_incheon_airport_is_the_airport_not_the_centre_of_seoul(geo):
    v6, box = geo(
        {("Incheon International Airport, Seoul", "KR"): [SEOUL], ("Seoul", "KR"): [SEOUL]},
        {"Incheon International Airport": [INCHEON_AIRPORT]},
    )

    result = _run(INCHEON, "A hotel close to the Inchon airport in Seoul Korea")

    assert result["ok"] is True
    assert result["resolved_place"].startswith("Incheon International Airport")
    assert result["distance_origin_type"] == "poi"
    assert "landmark_unresolved" not in result
    # Looked up alone, scoped to the country the model announced.
    assert ("Incheon International Airport", "KR", None) in box.calls


ST_PETE = {  # C081
    "places": [{"mention": "st pete clearwater airport", "kind": "airport",
                "canonical": "St. Pete–Clearwater International Airport", "city": "Clearwater",
                "country": "US", "city_inferred": True}],
    "relation": "near", "carryover": "new",
}
CLEARWATERS = [CLEARWATER_FL, CLEARWATER_MN, CLEARWATER_KS]


def test_st_pete_clearwater_airport_is_in_florida_not_kansas(geo):
    geo(
        {("St. Pete–Clearwater International Airport, Clearwater", "US"): CLEARWATERS,
         ("Clearwater", "US"): CLEARWATERS},
        {"St. Pete–Clearwater International Airport": [PIE_AIRPORT, MSP_AIRPORT]},
    )

    result = _run(ST_PETE, "are there any day use hotels near st pete clearwater airport")

    assert result["ok"] is True
    assert "Kansas" not in result["resolved_place"]
    assert result["resolved_place"].startswith("St. Petersburg–Clearwater International Airport")
    assert result["distance_origin_type"] == "poi"


def test_a_spot_found_in_another_country_than_announced_is_not_taken(geo):
    # The same airport name, announced in Korea: a US answer is not it.
    intent = {**INCHEON, "places": [{**INCHEON["places"][0], "canonical": "St. Pete–Clearwater International Airport",
                                     "mention": "Inchon airport"}]}
    geo(
        {("St. Pete–Clearwater International Airport, Seoul", "KR"): [SEOUL], ("Seoul", "KR"): [SEOUL]},
        {"St. Pete–Clearwater International Airport": [PIE_AIRPORT]},
    )

    result = _run(intent, "A hotel close to the Inchon airport in Seoul Korea")

    assert "Clearwater" not in str(result.get("resolved_place"))


# --- a town is a town --------------------------------------------------------------------------

COLBORNE_INTENT = {  # C016
    "places": [{"mention": "Colborne", "kind": "city", "canonical": "Colborne", "country": "CA", "region": "ON"}],
    "city": {"mention": "Colborne", "canonical": "Colborne", "region": "ON", "country": "CA"},
    "relation": "whole_city", "carryover": "new",
}


def test_colborne_is_the_town_not_a_neighbourhood_of_hamilton(geo):
    geo({("Colborne", "CA"): [COLBORNE, COLBORNE_SIMCOE, COLBORNE_DUNDAS]})

    result = _run(COLBORNE_INTENT, "Colborne")

    assert result.get("resolved_place") != "Colborne, Dundas, Ontario, Canada"
    assert result.get("distance_origin_type") != "poi"


# --- never the city's centre labelled as the spot ------------------------------------------------

TSIM_SHA_TSUI = {  # C071: the city is the model's, not the user's
    "places": [{"mention": "尖沙咀", "kind": "neighborhood", "canonical": "尖沙咀", "city": "Hong Kong",
                "country": "HK", "city_inferred": True}],
    "city": {"mention": "", "canonical": "Hong Kong", "country": "HK"},
    "relation": "in", "carryover": "new",
}


def test_tsim_sha_tsui_is_asked_about_never_searched_on_the_island(geo):
    geo({("尖沙咀, Hong Kong", "HK"): [HONG_KONG], ("Hong Kong", "HK"): [HONG_KONG]})

    result = _run(TSIM_SHA_TSUI, "尖沙咀")

    assert result["ok"] is False and result["error"] == "geocode_ambiguous"
    clarification = Clarification.model_validate(result["clarification"])
    assert clarification.kind == "unresolved" and clarification.city == "Hong Kong"


ROGIER = {  # C041 T2: the city typed by the user
    "places": [{"mention": "Rogier", "kind": "neighborhood", "canonical": "Quartier Rogier", "city": "Brussels",
                "country": "BE", "city_inferred": True}],
    "city": {"mention": "Bruxelles", "canonical": "Brussels", "country": "BE"},
    "relation": "in", "carryover": "refine",
}


def test_a_district_nobody_places_in_a_city_the_user_named_is_the_city_said_as_such(geo):
    geo({("Quartier Rogier, Brussels", "BE"): [BRUSSELS], ("Brussels", "BE"): [BRUSSELS],
         ("Bruxelles", "BE"): [BRUSSELS]})

    result = _run(ROGIER, "Dans le quartier Rogier, Bruxelles", locale="fr")

    assert result["ok"] is True
    assert result["distance_origin_type"] == "city_centroid"
    assert result["landmark_unresolved"] == "Quartier Rogier"


def test_without_a_city_the_wire_shape_of_a_question_is_unchanged():
    question = Clarification(kind="unresolved", subject="Ojai")
    assert "city" not in question.model_dump(mode="json")
