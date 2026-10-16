"""QA14707 (Q20, H3 RC5): a street or an address with no postcode is resolved by the address lookup.

H3 `qa14707-versailles-address-fr` (trace 1dc8ced4...): « Boulevard de la
République, Versailles » went to the generic lookup, whose types
(`CANDIDATE_TYPES`) never return a street. Mapbox answered Leipzig, the echo
guard refused it, and the turn asked « Leipzig or Versailles (Louisiana) ».
`qa14707-poissonniere-75009-no-country-en` failed the same way. The address
lookup (`ADDRESS_TYPES`) ran only when a postcode had been extracted.

Every Mapbox answer here is a REAL v6 response recorded on 2026-10-15 (H6, DQ9)
in `fixtures/mapbox_v6/`, served to the real `MapboxClient` for the exact query
and types it was recorded with. Any other request gets no feature.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.tools.function_tool import FunctionTool
from google.genai import types as genai_types

from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import _street_match, geocode_core, geocode_location
from hotel_search_agent.mapbox_client import ADDRESS_TYPES, CANDIDATE_TYPES, GeocodeCandidate, MapboxClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mapbox_v6"

STREET = "street_bd_republique_versailles.json"
STREET_NO_CITY = "street_bd_republique_no_city.json"
PLACE_CAND = "place_bd_republique_versailles_cand.json"
POISSONNIERE_PARIS = "address_2_bd_poissonniere_paris_no_postcode.json"
POISSONNIERE_IN_ZONE = "address_2_bd_poissonniere_75009_paris_in_zone.json"

#: (q, types) as recorded by H6 -> the recorded response.
_RECORDED = {
    ("boulevard de la république, versailles", ADDRESS_TYPES): STREET,
    ("boulevard de la république", ADDRESS_TYPES): STREET_NO_CITY,
    ("boulevard de la république, versailles", CANDIDATE_TYPES): PLACE_CAND,
    ("2 boulevard poissonnière, paris", ADDRESS_TYPES): POISSONNIERE_PARIS,
    ("2 boulevard poissonnière, 75009 paris", ADDRESS_TYPES): POISSONNIERE_IN_ZONE,
}

#: plan-r2 trace 1dc8ced4548bd034a88c8f591e076436, as recorded in H3 (the same
#: constants as test_geo_intent_mapping.py: a sibling test module cannot be
#: imported in the full-suite run).
VERSAILLES_TEXT = "Trouve moi une chambre à Boulevard de la République Versailles pour 13h demain"
VERSAILLES_INTENT = {
    "places": [
        {
            "mention": "Boulevard de la République",
            "kind": "street",
            "canonical": "Boulevard de la République",
            "city": "Versailles",
        }
    ],
    "city": "Versailles",
}

BD_REPUBLIQUE_VERSAILLES = "Boulevard de la République, 78000 Versailles, France"
POISSONNIERE_75009 = "2 Boulevard Poissonnière, 75009 Paris, France"


def _recorded(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _candidates(name: str) -> list[GeocodeCandidate]:
    return MapboxClient._parse_candidates(_recorded(name))


class _RecordedMapbox:
    """The real `MapboxClient`, its HTTP answered from the H6 recordings."""

    def __init__(self, drop_first: frozenset[str] = frozenset()):
        self.requests: list[dict] = []
        self._drop_first = drop_first
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
        if name in self._drop_first:
            data["features"] = data["features"][1:]
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
    def __init__(self):
        self.calls: list[tuple] = []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        return []


class _NoInventory:
    def count_near(self, lat, lon, *, radius_km=25.0):
        return 0


class _LeipzigInventory:
    """Hotels around Leipzig, none around the other generic candidates
    (Landshut, Lübben, Versailles in Louisiana): the shape under which the H3
    live probe saw the echo mismatch on Leipzig. With no inventory at all, the
    resolver asks between the German candidates instead."""

    def count_near(self, lat, lon, *, radius_km=25.0):
        return 50 if abs(lat - 51.34) < 0.5 and abs(lon - 12.38) < 0.5 else 0


def _install(
    monkeypatch, drop_first: frozenset[str] = frozenset(), inventory=None
) -> _RecordedMapbox:
    recorded = _RecordedMapbox(drop_first)
    recorded.searchbox = _SearchBox()
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: recorded.client)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: recorded.searchbox)
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: inventory or _NoInventory())
    return recorded


@pytest.fixture
def mapbox(monkeypatch):
    return _install(monkeypatch)


@pytest.fixture
def versailles(monkeypatch):
    return _install(monkeypatch, inventory=_LeipzigInventory())


@pytest.fixture
def statuses(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        geocode_tool, "mark_level", lambda level, status_message="": seen.append(status_message)
    )
    return seen


def _ctx(*texts, profile_in=None):
    """The leaf's `tool_context`: the text part(s), then the A2A DataPart, as
    the real a2a→genai converter hands them to the leaf."""
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=text) for text in texts]
    parts.append(convert_a2a_part_to_genai_part(datapart))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _no_country(recorded: _RecordedMapbox) -> bool:
    return all("country" not in r for r in recorded.requests) and all(
        country is None for _, country in recorded.searchbox.calls
    )


# --- what the client reads --------------------------------------------------------


class TestTheClientReadsTheMatchCode:
    def test_an_address_with_its_city_and_postcode_in_the_query(self):
        first = _candidates(POISSONNIERE_IN_ZONE)[0]

        assert (first.match_place, first.match_postcode, first.match_confidence) == (
            "matched", "matched", "exact",
        )

    def test_an_address_with_its_city_only(self):
        first = _candidates(POISSONNIERE_PARIS)[0]

        assert (first.match_place, first.match_postcode, first.match_confidence) == (
            "matched", "unmatched", "medium",
        )

    def test_a_street_carries_no_match_code(self):
        street = _candidates(STREET)[0]

        assert street.feature_type == "street"
        assert (street.place, street.postcode) == ("Versailles", "78000")
        assert street.match_place == street.match_postcode == street.match_confidence == ""


# --- the Versailles trace ---------------------------------------------------------


class TestVersailles:
    def test_the_street_in_its_city_is_the_answer(self, versailles, statuses):
        result = geocode_core(
            city="Versailles", zone="Boulevard de la République", zone_kind="street"
        )

        assert result["ok"] is True
        assert result["resolved_place"] == BD_REPUBLIQUE_VERSAILLES
        assert result["resolved_feature_type"] == "street"
        assert result["country_code"] == "FR"
        assert result["distance_origin_type"] == "poi"
        assert result["profile_delta"]["zone"] == "Boulevard de la République"
        assert result["profile_delta"]["last_city"] == "Versailles"
        # One lookup, the street in its city with the address types, and no
        # country filter anywhere.
        assert versailles.queries == [("Boulevard de la République, Versailles", ADDRESS_TYPES)]
        assert _no_country(versailles)
        assert "geocode_city_needed" not in statuses

    def test_the_real_tool_with_the_recorded_intent(self, versailles, statuses):
        result = asyncio.run(
            FunctionTool(geocode_location).run_async(
                args={"intent": VERSAILLES_INTENT}, tool_context=_ctx(VERSAILLES_TEXT)
            )
        )

        assert result["ok"] is True
        assert result["resolved_place"] == BD_REPUBLIQUE_VERSAILLES
        assert result["distance_origin_type"] == "poi"
        assert result["profile_delta"]["zone"] == "Boulevard de la République"
        assert result["profile_delta"]["last_city"] == "Versailles"
        assert "clarification" not in result
        assert "geocode_city_needed" not in statuses
        assert "geocode_ambiguous" not in statuses
        assert versailles.queries == [("Boulevard de la République, Versailles", ADDRESS_TYPES)]
        assert _no_country(versailles)


# --- an address with no postcode --------------------------------------------------


class TestPoissonniereWithoutPostcode:
    def test_the_address_in_the_named_city(self, mapbox, statuses):
        result = geocode_core(city="Paris", zone="2 Boulevard Poissonnière", zone_kind="address")

        assert result["ok"] is True
        assert result["resolved_place"] == POISSONNIERE_75009
        assert result["distance_origin_type"] == "poi"
        assert result["profile_delta"]["zone"] == "2 Boulevard Poissonnière"
        assert result["profile_delta"]["last_city"] == "Paris"
        assert mapbox.queries == [("2 Boulevard Poissonnière, Paris", ADDRESS_TYPES)]
        assert _no_country(mapbox)
        assert "geocode_ambiguous" not in statuses

    def test_the_whole_address_in_the_zone_and_no_city(self, mapbox, statuses):
        # The user's own string carried the place: Mapbox says so itself
        # (`match_code.place == "matched"`).
        result = geocode_core(zone="2 Boulevard Poissonnière, 75009 Paris", zone_kind="address")

        assert result["ok"] is True
        assert result["resolved_place"] == POISSONNIERE_75009
        assert result["distance_origin_type"] == "poi"
        assert result["profile_delta"]["zone"] == "2 Boulevard Poissonnière"
        assert result["profile_delta"]["last_city"] == "Paris"
        assert mapbox.queries == [("2 Boulevard Poissonnière, 75009 Paris", ADDRESS_TYPES)]
        assert _no_country(mapbox)
        assert "geocode_city_needed" not in statuses


# --- negative controls ------------------------------------------------------------


def _today(
    monkeypatch, drop_first: frozenset[str] = frozenset(), inventory=None, **args
) -> tuple[dict, list]:
    """The same call on the path a zone of another kind takes: the turn as it
    ran before Q20."""
    recorded = _install(monkeypatch, drop_first, inventory)
    return geocode_core(**{**args, "zone_kind": None}), recorded.queries


class TestNothingDesignatedChangesNothing:
    def test_a_street_with_no_city_still_asks_the_city(self, monkeypatch, statuses):
        args = {"zone": "Boulevard de la République"}
        recorded = _install(monkeypatch)

        result = geocode_core(**args, zone_kind="street")

        # Mapbox's answers are Algerian and French streets with no match_code:
        # none is taken, and the city question is exactly today's.
        assert recorded.queries == [("Boulevard de la République", ADDRESS_TYPES)]
        assert "Algérie" not in str(result)
        assert result["error"] == "geocode_ambiguous"
        assert result["clarification"]["kind"] == "city_needed"
        assert "geocode_city_needed" in statuses
        before, before_queries = _today(monkeypatch, **args)
        assert result == before
        assert before_queries == []

    def test_a_street_in_another_city_is_refused(self, monkeypatch):
        # The Versailles recording without its Versailles street: the others
        # are in Chaville, Marnes-la-Coquette, Garches...
        args = {"city": "Versailles", "zone": "Boulevard de la République"}
        recorded = _install(monkeypatch, frozenset({STREET}), _LeipzigInventory())

        result = geocode_core(**args, zone_kind="street")

        assert "Chaville" not in str(result)
        # Today's outcome, the one H3 measured: Leipzig, refused by the echo.
        assert result["error"] == "geocode_echo_mismatch"
        assert "Leipzig, Saxony, Germany" in str(result)
        before, before_queries = _today(
            monkeypatch, frozenset({STREET}), _LeipzigInventory(), **args
        )
        assert result == before
        assert recorded.queries == [
            ("Boulevard de la République, Versailles", ADDRESS_TYPES), *before_queries,
        ]

    def test_a_low_match_is_refused(self, monkeypatch):
        # The Paris recording without its 75009 address: Mapbox's top is now
        # « 2 Rue Poissonnière, 75002 Paris », in Paris but graded "low".
        args = {"city": "Paris", "zone": "2 Boulevard Poissonnière"}
        recorded = _install(monkeypatch, frozenset({POISSONNIERE_PARIS}))

        result = geocode_core(**args, zone_kind="address")

        assert "75002" not in str(result)
        before, before_queries = _today(monkeypatch, frozenset({POISSONNIERE_PARIS}), **args)
        assert result == before
        assert recorded.queries == [
            ("2 Boulevard Poissonnière, Paris", ADDRESS_TYPES), *before_queries,
        ]


class TestTheRuleItself:
    def test_another_place_than_the_city_is_refused(self):
        # The right address, high in Mapbox's grading, but in Paris, not Lyon.
        assert _street_match(_candidates(POISSONNIERE_PARIS), "2 Boulevard Poissonnière", city="Lyon") is None

    def test_a_low_confidence_is_refused_even_in_the_city(self):
        low = _candidates(POISSONNIERE_PARIS)[1]
        assert (low.place, low.match_confidence) == ("Paris", "low")

        assert _street_match([low], "2 Poissonnière", city="Paris") is None

    def test_with_no_city_a_street_is_never_taken(self):
        streets = _candidates(STREET_NO_CITY)
        assert all(c.feature_type == "street" for c in streets)

        assert _street_match(streets, "Boulevard de la République", city=None) is None

    def test_with_no_city_the_query_must_have_carried_the_place_or_the_postcode(self):
        # The recorded exact match, with only its match_code.place/postcode
        # flipped: the same confidence, the same name, now refused.
        right = _candidates(POISSONNIERE_IN_ZONE)[0]
        zone = "2 Boulevard Poissonnière, 75009 Paris"
        assert _street_match([right], zone, city=None) is right

        unmatched = replace(right, match_place="unmatched", match_postcode="unmatched")
        assert _street_match([unmatched], zone, city=None) is None
        assert _street_match([replace(unmatched, match_postcode="matched")], zone, city=None)


class TestNoLookupAdded:
    def test_a_station_makes_no_address_lookup(self, mapbox):
        geocode_core(city="Paris", zone="Gare du Nord", zone_kind="station")

        assert mapbox.queries and all(types != ADDRESS_TYPES for _, types in mapbox.queries)

    def test_an_address_with_its_postcode_keeps_the_postcode_lookup(self, mapbox):
        geocode_core(
            zone="2 Boulevard Poissonnière", zone_kind="address", postal_code="75009",
        )

        assert mapbox.queries[0] == ("2 Boulevard Poissonnière 75009", ADDRESS_TYPES)
        assert ("2 Boulevard Poissonnière", ADDRESS_TYPES) not in mapbox.queries
