"""QA14707 (Q10, DQ7): the US-ZIP anchor is gone, the postcode rule (Q08, DQ8) decides.

The regex US-ZIP anchor of geo_guards read ANY 5-digit number as a US ZIP, so every French
postcode ("75009", "13001") was a US ZIP. A US user's ZIP now stays in the
United States through DQ8 only (the model's guess, then the market), and what
the postcode turns persist in the session is pinned here: a follow-up turn
carries no postcode and must not land in the US either.

Every Mapbox answer is a REAL v6 recording from `fixtures/mapbox_v6/` (H5, H6;
DQ9), served to the real `MapboxClient`. One reuse: « 75009 Paris » was never
recorded and is served the « 75009 » recording (same postcode, real shape; its
list, with Celina TX in it, is the harder tie-break). The « near 11580 » tests themselves
stay where they were (`test_postcode_resolution.py`, `test_geocode_tool.py`).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from b2c_common.geo_intent import CityRef, GeoIntent, Place
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import _postcode_match, geocode_core, geocode_location
from hotel_search_agent.mapbox_client import CANDIDATE_TYPES, GeocodeCandidate, MapboxClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mapbox_v6"

_RECORDED = {
    ("2 boulevard poissonnière 75009", "address,street"): "address_2_bd_poissonniere_75009.json",
    ("75009", "postcode"): "postcode_75009.json",
    ("75009 paris", "postcode"): "postcode_75009.json",
    ("13001 marseille", "postcode"): "postcode_13001_marseille.json",
    ("11580", "postcode"): "postcode_11580.json",
    ("paris", CANDIDATE_TYPES): "place_paris_en.json",
}


def _recorded(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _candidates(name: str) -> list[GeocodeCandidate]:
    return MapboxClient._parse_candidates(_recorded(name))


class _RecordedMapbox:
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
        data = _recorded(name)
        country = params.get("country")
        if country:
            data["features"] = [
                f for f in data["features"]
                if f["properties"]["context"]["country"]["country_code"].lower() == country
            ]
        return httpx.Response(200, json=data)

    @property
    def queries(self) -> list[tuple[str, str]]:
        return [(r["q"], r["types"]) for r in self.requests]


class _SearchBox:
    """Serves the candidates it is given (taken from a real recording)."""

    def __init__(self, *candidates: GeocodeCandidate):
        self.candidates = list(candidates)
        self.calls: list[tuple] = []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        return list(self.candidates)


class _FrenchInventory:
    """Only the French Paris has hotels, as in the real inventory."""

    def count_near(self, lat, lon, *, radius_km=25.0):
        return 500 if abs(lat - 48.85) < 1 else 0


@pytest.fixture
def mapbox(monkeypatch):
    recorded = _RecordedMapbox()
    recorded.searchbox = _SearchBox()
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: recorded.client)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: recorded.searchbox)
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _FrenchInventory())
    return recorded


def _ctx(*texts, profile_in=None):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=text) for text in texts]
    parts.append(convert_a2a_part_to_genai_part(datapart))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _postcode(code: str, **kwargs) -> Place:
    return Place(mention=code, kind="admin_district", canonical=code, postal_code=code, **kwargs)


def _address() -> Place:
    return Place(mention="2 boulevard Poissonnière", kind="address",
                 canonical="2 Boulevard Poissonnière", postal_code="75009")


class TestTheAnchorIsGone:
    def test_the_names_are_deleted(self):
        from hotel_search_agent import geo_guards

        # No name of the old anchor (its selector, its dataclass) is left in
        # either module, matched without the underscores and the case.
        for module in (geo_guards, geocode_tool):
            assert not [n for n in dir(module) if "postalanchor" in n.replace("_", "").lower()]

    def test_a_five_digit_number_no_longer_forces_a_country(self, mapbox):
        geocode_core(city="75009", raw_user_message="un hôtel près de 75009")

        assert mapbox.requests and all("country" not in r for r in mapbox.requests)


class TestNoCountryNamedStaysInFrance:
    def test_a_postcode_with_its_city_on_a_us_locale_is_paris(self, mapbox):
        # The city the user wrote breaks the FR / Celina (TX) tie before the market.
        result = geocode_location(
            intent=GeoIntent(places=[_postcode("75009")],
                             city=CityRef(mention="Paris", canonical="Paris")),
            locale="en-US",
            tool_context=_ctx("a hotel in the 75009 Paris"),
        )

        assert result["ok"] is True
        assert result["country_code"] == "FR"
        assert result["profile_delta"]["last_city"] == "Paris"
        assert mapbox.queries == [("75009 Paris", "postcode")]
        assert all("country" not in r for r in mapbox.requests)

    @pytest.mark.parametrize("text", [
        "2 boulevard Poissonnière 75009 Paris",
        "hotel 13001 marseille",
    ])
    def test_the_two_french_inputs_never_see_a_us_candidate(self, mapbox, text):
        if "13001" in text:
            places = [Place(mention="marseille", kind="city", canonical="Marseille",
                            postal_code="13001")]
            intent = GeoIntent(places=places)
        else:
            intent = GeoIntent(places=[_address()],
                               city=CityRef(mention="Paris", canonical="Paris"))

        result = geocode_location(intent=intent, locale="en-US", tool_context=_ctx(text))

        assert result["ok"] is True
        assert result["country_code"] == "FR"
        assert all("country" not in r for r in mapbox.requests)


class TestPostcodeMatchOrderWhenTheCityMatchesNothing:
    """The city step only narrows: when no candidate with the postcode is in
    the turn's city, the order is the guess, then the market, then Mapbox's."""

    def test_the_guess_then_the_market_then_mapbox_rank(self):
        candidates = _candidates("postcode_75009.json")  # Paris FR, Celina US, UA, EE

        def place(guess, market):
            match = _postcode_match(candidates, "75009", city="Lyon", guess=guess, market=market)
            assert match is not None
            return match.place

        assert place("US", "FR") == "Celina"  # the guess before the market
        assert place(None, "US") == "Celina"  # then the market
        assert place(None, "FR") == "Paris"
        assert place(None, None) == "Paris"  # then Mapbox's own order (the 1st)


class TestFollowUpTurnsAfterAPostcode:
    def test_after_a_bare_postcode_the_follow_up_is_not_geocoded_in_the_us(self, mapbox):
        first = geocode_location(
            intent=GeoIntent(places=[_postcode("75009")],
                             city=CityRef(mention="Paris", canonical="Paris")),
            locale="en",
            tool_context=_ctx("hotel dans le 75009 Paris"),
        )
        assert first["profile_delta"]["last_city"] == "Paris"
        assert "zone" not in first["profile_delta"]
        mapbox.requests.clear()

        # The session now holds city Paris and no zone; the user changes only
        # the filters, with no new place and an English locale.
        second = geocode_location(
            intent=GeoIntent(),
            tool_context=_ctx("cheaper please", profile_in={"city": "Paris", "locale": "en"}),
        )

        assert second["ok"] is True
        assert second["country_code"] == "FR"
        assert mapbox.requests and all(r.get("country") != "us" for r in mapbox.requests)

    def test_after_an_address_the_zone_is_the_name_without_the_postcode(self, mapbox):
        first = geocode_location(
            intent=GeoIntent(places=[_address()]),
            locale="en",
            tool_context=_ctx("2 boulevard Poissonnière 75009"),
        )

        zone = first["profile_delta"]["zone"]
        assert zone == "2 Boulevard Poissonnière"
        assert "75009" not in zone
        assert first["distance_origin_type"] == "poi"

        # Follow-up with that persisted zone and city, no new place: the
        # address is searched again (the Search Box answers with the real
        # recorded candidate of the address), still a "poi" origin, in France.
        address = _candidates("address_2_bd_poissonniere_75009.json")[0]
        mapbox.searchbox.candidates = [address]
        mapbox.requests.clear()

        second = geocode_location(
            intent=GeoIntent(),
            tool_context=_ctx("cheaper please", profile_in={
                "city": "Paris", "zone": zone, "locale": "en",
            }),
        )

        assert second["ok"] is True
        assert second["country_code"] == "FR"
        assert second["distance_origin_type"] == "poi"
        # The follow-up looked up the persisted address itself, not a postcode.
        assert mapbox.searchbox.calls == [(zone, None)]
        assert mapbox.queries[0][0] == f"{zone}, Paris"
        assert all(r.get("country") != "us" for r in mapbox.requests)
        assert all(country != "US" for _, country in mapbox.searchbox.calls)
