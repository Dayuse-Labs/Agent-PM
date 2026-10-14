"""QA14707 (Q08): an address or a postcode the user wrote is resolved by the geocoder.

Trace C (`phases/QA14707/DIAGNOSTIC.md`): « Un hôtel près du 2 boulevard
Poissonnière 75009 demain » gave `zone="2 boulevard Poissonnière"`, the
postcode was thrown away and the user was asked which city. The `GeoIntent`
now carries `places[].postal_code`, and the country of a postcode follows DQ8:

- only a country the user NAMED is a hard Mapbox filter;
- otherwise only the candidates whose `context.postcode` equals the written
  code are kept, and among those the named city, then the model's guess, then
  the market's country break the tie.

Every Mapbox answer here is a REAL v6 response recorded by Fabien (H5, DQ9) in
`fixtures/mapbox_v6/`, served to the real `MapboxClient` over an
`httpx.MockTransport` for the exact query and types it was recorded with. A
`country` parameter is applied the way Mapbox applies it (the other countries'
features are dropped). Any other request gets no feature: nothing here is a
made-up v6 shape.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import jsonschema
import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.models.lite_llm import _function_declaration_to_tool_param
from google.adk.tools.function_tool import FunctionTool
from google.genai import types as genai_types

from b2c_common.geo_intent import CityRef, GeoIntent, Place
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_core, geocode_location
from hotel_search_agent.mapbox_client import CANDIDATE_TYPES, GeocodeCandidate, MapboxClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mapbox_v6"

#: (q, types) as recorded by H5 -> the recorded response.
_RECORDED = {
    ("2 boulevard poissonnière 75009", "address,street"): "address_2_bd_poissonniere_75009.json",
    ("75009", "postcode"): "postcode_75009.json",
    ("13001 marseille", "postcode"): "postcode_13001_marseille.json",
    ("11580", "postcode"): "postcode_11580.json",
}


def _recorded(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _RecordedMapbox:
    """The real `MapboxClient`, its HTTP answered from the H5 recordings."""

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
    def __init__(self, *candidates: GeocodeCandidate):
        self.candidates = list(candidates)
        self.calls: list[tuple] = []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country, proximity))
        return list(self.candidates)


class _NoInventory:
    def count_near(self, lat, lon, *, radius_km=25.0):
        return 0


@pytest.fixture
def mapbox(monkeypatch):
    recorded = _RecordedMapbox()
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: recorded.client)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _SearchBox())
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _NoInventory())
    return recorded


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


TRACE_C = "Un hôtel près du 2 boulevard Poissonnière 75009 demain"


def _address(**kwargs) -> Place:
    return Place(mention="2 boulevard Poissonnière", kind="address",
                 canonical="2 Boulevard Poissonnière", postal_code="75009", **kwargs)


def _postcode(code: str, **kwargs) -> Place:
    return Place(mention=code, kind="admin_district", canonical=code, postal_code=code, **kwargs)


def _candidates(name: str) -> list[GeocodeCandidate]:
    return MapboxClient._parse_candidates(_recorded(name))


# --- what the client reads --------------------------------------------------------


class TestTheClientReadsTheContext:
    def test_postcode_place_and_match_code_of_a_real_address_answer(self):
        first, second = _candidates("address_2_bd_poissonniere_75009.json")[:2]

        assert (first.postcode, first.place, first.country_code) == ("75009", "Paris", "FR")
        assert first.match_confidence == "high"
        assert first.feature_type == "address"
        assert (second.postcode, second.match_confidence) == ("75002", "low")

    def test_a_postcode_feature_carries_no_match_code(self):
        paris, celina = _candidates("postcode_75009.json")[:2]

        assert (paris.postcode, paris.place, paris.country_code) == ("75009", "Paris", "FR")
        assert (celina.postcode, celina.place, celina.country_code) == ("75009", "Celina", "US")
        assert paris.match_confidence == celina.match_confidence == ""


# --- trace C ----------------------------------------------------------------------


class TestTraceC:
    def test_the_address_and_its_postcode_give_paris_and_no_question(self, mapbox, statuses):
        result = geocode_location(intent=GeoIntent(places=[_address()]), tool_context=_ctx(TRACE_C))

        assert "geocode_city_needed" not in statuses
        assert "clarification" not in result
        assert result["ok"] is True
        assert result["resolved_place"] == "2 Boulevard Poissonnière, 75009 Paris, France"
        assert (result["latitude"], result["longitude"]) == (48.870905, 2.347691)
        assert result["country_code"] == "FR"
        assert result["distance_origin_type"] == "poi"
        # The city is the candidate's `context.place`; the zone is the address,
        # without its postcode.
        assert result["profile_delta"]["last_city"] == "Paris"
        assert result["profile_delta"]["zone"] == "2 Boulevard Poissonnière"
        # One lookup: the full mention with its postcode, address and street types.
        assert mapbox.queries == [("2 Boulevard Poissonnière 75009", "address,street")]

    def test_a_postcode_the_model_also_left_in_the_mention_is_not_sent_twice(self, mapbox):
        place = Place(mention="2 boulevard Poissonnière 75009", kind="address",
                      postal_code="75009")

        result = geocode_location(intent=GeoIntent(places=[place]), tool_context=_ctx(TRACE_C))

        assert result["ok"] is True
        assert mapbox.queries[0] == ("2 boulevard Poissonnière 75009", "address,street")
        assert result["profile_delta"]["zone"] == "2 Boulevard Poissonnière"

    def test_a_postcode_the_user_never_wrote_is_discarded(self, monkeypatch):
        seen: list[dict] = []
        monkeypatch.setattr(geocode_tool, "geocode_core", lambda **kw: seen.append(kw) or {})

        geocode_location(
            intent=GeoIntent(places=[_address()]),
            tool_context=_ctx("Un hôtel près du 2 boulevard Poissonnière demain"),
        )

        assert seen[0]["postal_code"] is None
        assert seen[0]["zone"] == "2 Boulevard Poissonnière"


class TestThePostcodeMustBeEqual:
    def test_a_candidate_with_another_postcode_is_refused(self):
        # Mapbox's other answers to the same query: 75002, 92230, Belgian and
        # Canadian codes. None is ever taken for 75009.
        others = _candidates("address_2_bd_poissonniere_75009.json")[1:]
        assert others and all(c.postcode != "75009" for c in others)

        assert geocode_tool._postcode_match(others, "75009", city=None, guess="FR", market="FR") is None
        right = geocode_tool._postcode_match(
            _candidates("address_2_bd_poissonniere_75009.json"), "75009",
            city=None, guess=None, market=None,
        )
        assert right is not None and right.name == "2 Boulevard Poissonnière"

    def test_in_the_pipeline_the_wrong_street_never_wins(self, monkeypatch, statuses):
        # The same recording without its right answer: Mapbox's top is now
        # « 2 Rue Poissonnière, 75002 Paris ». It is refused; the postcode
        # alone gives Paris, and the address is searched there.
        recorded = _RecordedMapbox(drop_first=frozenset({"address_2_bd_poissonniere_75009.json"}))
        box = _SearchBox()
        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: recorded.client)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)
        monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _NoInventory())

        result = geocode_location(intent=GeoIntent(places=[_address()]), tool_context=_ctx(TRACE_C))

        assert "75002" not in str(result)
        assert "geocode_city_needed" not in statuses
        assert recorded.queries[:2] == [
            ("2 Boulevard Poissonnière 75009", "address,street"),
            ("75009", "postcode"),
        ]
        # Paris from `context.place`, then the usual path for a zone in a city.
        assert recorded.queries[2] == ("2 Boulevard Poissonnière, Paris", CANDIDATE_TYPES)
        assert box.calls[0][0] == "2 Boulevard Poissonnière, Paris"


# --- DQ8: the country of a postcode -----------------------------------------------


class TestOnlyANamedCountryFilters:
    @pytest.mark.parametrize("locale", [None, "en", "en-US", "fr-FR"])
    def test_no_country_named_no_country_filter(self, mapbox, locale):
        geocode_location(intent=GeoIntent(places=[_address()]), locale=locale,
                         tool_context=_ctx(TRACE_C))
        geocode_location(intent=GeoIntent(places=[_postcode("75009", country="US")]),
                         locale=locale, tool_context=_ctx("un hôtel dans le 75009"))

        assert len(mapbox.requests) == 2
        assert all("country" not in r for r in mapbox.requests)

    def test_a_named_country_is_the_filter(self, mapbox):
        result = geocode_location(
            intent=GeoIntent(places=[_postcode("75009", country="FR")], country_named="US"),
            tool_context=_ctx("a hotel in 75009 in the US"),
        )

        assert [r.get("country") for r in mapbox.requests] == ["us"]
        assert result["ok"] is True
        assert result["resolved_place"] == "Celina, Texas 75009, États-Unis"

    def test_the_named_country_also_filters_the_address(self, mapbox):
        geocode_location(
            intent=GeoIntent(places=[_address()], country_named="FR"),
            tool_context=_ctx(TRACE_C + " en France"),
        )

        assert [r.get("country") for r in mapbox.requests] == ["fr"]

    def test_the_carried_country_anchor_is_not_a_filter_on_a_new_postcode(self, mapbox):
        # A US search earlier in the session: its anchor would make 75009
        # Celina. DQ8 keeps only a country the user named as a hard filter.
        result = geocode_location(
            intent=GeoIntent(places=[_address()]),
            tool_context=_ctx(TRACE_C, profile_in={
                "country_anchor": "US", "city": "New York", "zone": "Times Square",
            }),
        )

        assert all("country" not in r for r in mapbox.requests)
        assert result["resolved_place"] == "2 Boulevard Poissonnière, 75009 Paris, France"
        assert result["profile_delta"]["last_city"] == "Paris"


class TestTiesBetweenCountries:
    """75009 is Paris, FR and Celina, TX (the recording's 1st and 2nd answers)."""

    @pytest.mark.parametrize(
        ("guess", "locale", "expected"),
        [
            ("FR", "en-US", "Paris"),   # the guess wins over the market
            ("US", "fr-FR", "Celina"),  # whichever way round
            (None, "en-US", "Celina"),  # no guess: the market decides
            (None, "fr-FR", "Paris"),
            (None, "en", "Paris"),      # « en » names no country: Mapbox's order
            (None, None, "Paris"),
        ],
    )
    def test_the_guess_then_the_market(self, mapbox, guess, locale, expected):
        result = geocode_location(
            intent=GeoIntent(places=[_postcode("75009", country=guess)]),
            locale=locale,
            tool_context=_ctx("un hôtel dans le 75009"),
        )

        assert result["ok"] is True
        assert result["profile_delta"]["last_city"] == expected
        assert mapbox.queries == [("75009", "postcode")]

    def test_a_bare_postcode_is_searched_around_its_centroid_with_no_zone(self, mapbox):
        result = geocode_location(
            intent=GeoIntent(places=[_postcode("75009", country="FR")]),
            tool_context=_ctx("un hôtel dans le 75009"),
        )

        assert (result["latitude"], result["longitude"]) == (48.875676, 2.343131)
        assert result["resolved_feature_type"] == "postcode"
        assert result["distance_origin_type"] == "city_centroid"
        # A carried bare code would come back without the postcode rule.
        assert "zone" not in result["profile_delta"]

    def test_poissonniere_on_an_en_usd_market_is_never_searched_in_the_us(self, mapbox):
        # Raphael's sessions: en/USD market, no country named, and the city
        # written. The market says US; the postcode equality says Paris.
        result = geocode_location(
            intent=GeoIntent(places=[_address()], city=CityRef(mention="Paris", canonical="Paris")),
            locale="en-US",
            tool_context=_ctx("A hotel near 2 boulevard Poissonnière 75009 Paris tomorrow",
                              profile_in={"currency": "USD", "locale": "en-US"}),
        )

        assert result["ok"] is True
        assert result["country_code"] == "FR"
        assert result["profile_delta"]["last_city"] == "Paris"
        assert all("country" not in r for r in mapbox.requests)

    @pytest.mark.parametrize(
        "places",
        [
            [Place(mention="marseille", kind="city", canonical="Marseille", postal_code="13001")],
            [_postcode("13001"), Place(mention="marseille", kind="city", canonical="Marseille")],
        ],
    )
    def test_13001_marseille_stays_in_marseille_on_a_us_market(self, mapbox, places):
        # Mapbox also answers Trujillo (PE), Ciudad Real (ES), Hanam (KR)...:
        # the city the user wrote decides before the market.
        result = geocode_location(
            intent=GeoIntent(places=places), locale="en-US",
            tool_context=_ctx("hotel 13001 marseille"),
        )

        assert mapbox.queries == [("13001 Marseille", "postcode")]
        assert result["ok"] is True
        assert result["country_code"] == "FR"
        assert result["profile_delta"]["last_city"] == "Marseille"


class TestNear11580:
    """The prod bug « near 11580 » (geocoded outside the United States). Its
    tests in `test_geocode_tool.py::TestUsZipCountryScoping` are unchanged and
    still pass: without a `postal_code` the US-ZIP anchor still applies. With
    one, Mapbox's own first answer is Mexico City; the DQ8 tie-break keeps the
    US case."""

    @pytest.mark.parametrize(("guess", "locale"), [("US", None), ("US", "fr-FR"), (None, "en-US")])
    def test_a_us_guess_or_a_us_market_stays_in_the_us(self, mapbox, guess, locale):
        result = geocode_location(
            intent=GeoIntent(places=[_postcode("11580", country=guess)]),
            locale=locale,
            tool_context=_ctx("Allows cats. Near 11580"),
        )

        assert result["ok"] is True
        assert result["country_code"] == "US"
        assert result["resolved_place"] == "Valley Stream, New York 11580, United States"
        assert all("country" not in r for r in mapbox.requests)

    def test_without_a_postal_code_the_us_anchor_still_scopes_the_lookup(self, mapbox):
        geocode_core(city="11580", raw_user_message="Allows cats. Near 11580")

        assert mapbox.requests[0]["country"] == "us"

    def test_with_a_postal_code_the_us_anchor_stays_out_of_the_way(self, mapbox):
        # A landmark with its postcode goes on to the usual path, in the
        # postcode's city. The anchor would read 75009 there as a US ZIP and
        # scope every later lookup to the US; the postcode rule decided instead.
        message = "un hôtel près de l'Opéra Garnier 75009"
        assert geocode_tool.select_us_postal_anchor(message) is not None

        geocode_core(zone="Palais Garnier", zone_kind="landmark", postal_code="75009",
                     raw_user_message=message)

        assert mapbox.queries[:2] == [("75009", "postcode"), ("Palais Garnier, Paris", CANDIDATE_TYPES)]
        assert all("country" not in r for r in mapbox.requests)


# --- the city question ------------------------------------------------------------


class TestTheCityQuestion:
    def test_gare_du_nord_with_neither_city_nor_postcode_still_asks(self, mapbox, statuses):
        result = geocode_location(
            intent=GeoIntent(places=[Place(mention="Gare du Nord", kind="station",
                                           canonical="Gare du Nord")]),
            tool_context=_ctx("un hôtel près de Gare du Nord demain"),
        )

        assert result["error"] == "geocode_ambiguous"
        assert "geocode_city_needed" in statuses
        assert result["clarification"]["kind"] == "city_needed"
        assert mapbox.requests == []

    def test_a_postcode_is_enough_for_the_city(self, monkeypatch, mapbox, statuses):
        # The Palais Garnier is in the 75009: its city comes from the postcode,
        # so no question, and the landmark is looked up in Paris.
        box = _SearchBox()
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)
        garnier = Place(mention="Opéra Garnier", kind="landmark", canonical="Palais Garnier",
                        postal_code="75009")

        result = geocode_location(
            intent=GeoIntent(places=[garnier]),
            tool_context=_ctx("un hôtel près de l'Opéra Garnier 75009"),
        )

        assert "geocode_city_needed" not in statuses
        assert "clarification" not in result
        assert mapbox.queries[0] == ("75009", "postcode")
        assert box.calls[0][0] == "Palais Garnier, Paris"

    def test_an_unknown_postcode_alone_is_an_honest_miss_never_the_gps(self, mapbox):
        result = geocode_location(
            intent=GeoIntent(places=[_postcode("99999")]),
            proximity_lat=48.85, proximity_lon=2.35,
            tool_context=_ctx("un hôtel dans le 99999"),
        )

        assert result == {"ok": False, "error": "geocode_no_match",
                          "diagnostics": {"query": "99999"}}


# --- the model-facing interface (Q07 narrowed it, Q08 pins it) --------------------


class TestTheModelFacingTool:
    def test_the_declaration_has_no_free_place_or_country_argument(self):
        declaration = FunctionTool(geocode_location)._get_declaration()
        assert declaration is not None
        properties = declaration.parameters_json_schema["properties"]

        for gone in ("country_code", "country_guess", "city", "zone", "raw_user_message"):
            assert gone not in properties
        assert "intent" in properties

    def test_an_undeclared_country_code_never_reaches_mapbox(self, mapbox):
        # A model that still sends `country_code` (the pre-Q07 interface): ADK
        # drops the undeclared key, and the GeoIntent names no country.
        args = {"intent": {"places": [{"mention": "2 boulevard Poissonnière", "kind": "address",
                                       "canonical": "2 Boulevard Poissonnière",
                                       "postal_code": "75009"}]},
                "country_code": "US"}

        result = asyncio.run(
            FunctionTool(geocode_location).run_async(args=args, tool_context=_ctx(TRACE_C))
        )

        assert result["ok"] is True
        assert result["country_code"] == "FR"
        assert mapbox.requests and all("country" not in r for r in mapbox.requests)

    @pytest.mark.parametrize(("anchor", "sent"), [("us", "us"), ("US", "us"), ("USA", None)])
    def test_the_carried_anchor_is_the_other_filter_after_iso2(self, monkeypatch, anchor, sent):
        requests: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(dict(request.url.params))
            return httpx.Response(200, json={"features": []})

        client = MapboxClient("test-token", client=httpx.Client(transport=httpx.MockTransport(handler)))
        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: client)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _SearchBox())
        monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _NoInventory())

        asyncio.run(FunctionTool(geocode_location).run_async(
            args={"intent": {}, "country_code": "FR"},
            tool_context=_ctx("moins cher ?", profile_in={"city": "Portland", "country_anchor": anchor}),
        ))

        assert requests
        assert [r.get("country") for r in requests] == [sent] * len(requests)


class TestTheLiteLlmConversion:
    """The leaf's REAL `geocode_location`, through the conversion LiteLLM sends
    to OpenAI (`tests/test_geo_intent_contract.py` proved it on a stand-in)."""

    @staticmethod
    def _function() -> dict:
        declaration = FunctionTool(geocode_location)._get_declaration()
        assert declaration is not None
        param = _function_declaration_to_tool_param(declaration)
        json.dumps(param)  # plain JSON, nothing left of the genai types
        assert param["type"] == "function"
        return param["function"]

    def _intent(self) -> tuple[dict, dict]:
        parameters = self._function()["parameters"]
        intent = parameters["properties"]["intent"]
        defs = parameters.get("$defs", {})
        if "$ref" in intent:
            intent = defs[intent["$ref"].rsplit("/", 1)[-1]]
        return intent, defs

    def test_the_function_keeps_its_name_and_description(self):
        function = self._function()

        assert function["name"] == "geocode_location"
        assert "intent" in function["description"]
        assert "coordinates" in function["description"]

    def test_intent_keeps_the_geo_intent_object(self):
        intent, defs = self._intent()

        assert intent["description"] == GeoIntent.__doc__
        assert intent["additionalProperties"] is False
        places = intent["properties"]["places"]
        assert places["maxItems"] == 2
        assert places["description"] == GeoIntent.model_fields["places"].description
        place = places["items"]
        if "$ref" in place:
            place = defs[place["$ref"].rsplit("/", 1)[-1]]
        for field in ("postal_code", "country", "city", "mention"):
            assert place["properties"][field]["description"] == Place.model_fields[field].description
        assert intent["properties"]["country_named"]["description"] == (
            GeoIntent.model_fields["country_named"].description
        )

    def test_the_parameters_are_a_valid_schema_that_takes_trace_c(self):
        parameters = self._function()["parameters"]
        jsonschema.Draft202012Validator.check_schema(parameters)
        validator = jsonschema.Draft202012Validator(parameters)

        validator.validate({"intent": GeoIntent(places=[_address()]).model_dump(mode="json")})
        validator.validate({})
        assert not validator.is_valid({"intent": {"places": [{}, {}, {}]}})
        assert not validator.is_valid({"intent": {"latitude": 48.87}})
        for gone in ("country_code", "country_guess", "city", "zone", "raw_user_message"):
            assert gone not in parameters["properties"]
