"""QA14707 Q23 (DQ11): the `Place` of the `GeoIntent` asks for the place's city
and country right after its name, as the production leaf model reads it.

H3 (`scratchpad/h3-diagnosis.md`, RC1): in the declaration the leaf's model
read, `city` was `Place`'s 5th property and `country` its 7th, after
`postal_code`, and none was required. gpt-4o-mini filled `places[].city` on 9
of 222 places and `country` on 0, so every landmark without a typed city got
the city question. An LLM-only probe of the leaf's real instruction showed
gpt-6-luna (the leaves' model since 2026-10-15, #139) filling them 15/15 once
they come right after `canonical` and are listed as required.

1. The declaration the model reads: the leaf's REAL `geocode_location`, through
   the conversion LiteLLM sends to OpenAI.
2. The mapping of the shapes gpt-6-luna wrote under that declaration: each
   intent below is copied verbatim from the recorded probe
   (`scratchpad/h3/probe_out_luna-v1.json`, the `args.intent` of a call) and
   goes through the real `FunctionTool`, Mapbox mocked. This proves what the
   code does with those shapes, not what the model writes: that is H3'.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.models.lite_llm import _function_declaration_to_tool_param
from google.adk.tools.function_tool import FunctionTool
from google.genai import types as genai_types

from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.mapbox_client import POSTCODE_TYPES, GeocodeCandidate

PLACE_ORDER = [
    "mention", "kind", "canonical", "city", "country", "postal_code", "region", "city_inferred",
]
PLACE_REQUIRED = ["mention", "kind", "canonical", "city", "country", "postal_code"]


def _defs() -> dict[str, Any]:
    declaration = FunctionTool(geocode_location)._get_declaration()
    assert declaration is not None
    param = _function_declaration_to_tool_param(declaration)
    json.dumps(param)  # plain JSON: what LiteLLM sends
    parameters = param["function"]["parameters"]
    return parameters.get("$defs", {})


class TestTheDeclarationTheModelReads:
    def test_place_asks_city_and_country_right_after_the_name(self):
        place = _defs()["Place"]

        assert list(place["properties"]) == PLACE_ORDER

    def test_place_lists_the_keys_the_model_must_write(self):
        place = _defs()["Place"]

        assert place["required"] == PLACE_REQUIRED


# --- the shapes gpt-6-luna wrote under this declaration ---------------------------
#
# Verbatim from `scratchpad/h3/probe_out_luna-v1.json` (variant V1 = this
# task's schema, the leaf's real instruction), one `args.intent` per call.

BUCKINGHAM = {"places": [{"mention": "buckingham palace", "kind": "landmark", "canonical": "Buckingham Palace", "city": "London", "country": "GB", "city_inferred": True}], "relation": "near", "carryover": "new"}  # noqa: E501
POSTCODE_ONLY = [
    {"places": [{"mention": "75009", "kind": "address", "canonical": "75009", "city": "Paris", "country": "FR", "postal_code": "75009", "city_inferred": True}], "city": {"mention": "", "canonical": "Paris", "country": "FR"}, "relation": "in", "carryover": "new"},  # noqa: E501
    {"schema_version": "1.1", "places": [{"mention": "75009", "kind": "admin_district", "canonical": "9th arrondissement of Paris", "city": "Paris", "country": "FR", "postal_code": "75009", "city_inferred": True}], "city": {"mention": "", "canonical": "Paris", "country": "FR"}, "relation": "in", "carryover": "new"},  # noqa: E501
    {"places": [{"mention": "75009", "kind": "address", "canonical": "75009", "city": "Paris", "country": "FR", "postal_code": "75009", "city_inferred": True}], "city": None, "relation": "in", "carryover": "new"},  # noqa: E501
]
GARE_DU_NORD_BARE = [
    {"schema_version": "1.1", "places": [{"mention": "Gare du Nord", "kind": "station", "canonical": "Gare du Nord", "city": None, "country": "FR", "postal_code": None, "city_inferred": False}], "city": None, "relation": "near", "carryover": "new", "ambiguity": {"reason": "homonym"}},  # noqa: E501
    {"schema_version": "1.1", "places": [{"mention": "Gare du Nord", "kind": "station", "canonical": "Gare du Nord", "city": None, "country": None, "postal_code": None, "city_inferred": False}], "city": None, "relation": "near", "carryover": "new", "ambiguity": None},  # noqa: E501
]
GARE_DE_LYON = [
    {"places": [{"mention": "gare de Lyon", "kind": "station", "canonical": "Gare de Lyon", "city": None, "country": "FR", "city_inferred": False}], "ambiguity": {"reason": "city_needed"}, "relation": "near", "carryover": "new"},  # noqa: E501
    {"schema_version": "1.1", "places": [{"mention": "gare de Lyon", "kind": "station", "canonical": "Gare de Lyon", "city": None, "country": "FR", "city_inferred": False}], "city": None, "country_named": None, "relation": "near", "carryover": "new", "ambiguity": {"reason": "city_needed"}},  # noqa: E501
]
ANSWER_PARI = [
    {"schema_version": "1.1", "places": [{"mention": "Gare du Nord", "kind": "station", "canonical": "Gare du Nord", "city": None, "country": None, "postal_code": None, "city_inferred": False}], "city": {"mention": "Pari", "canonical": "Paris", "country": "FR"}, "relation": "near", "carryover": "new"},  # noqa: E501
    {"places": [{"mention": "Gare du Nord", "kind": "station", "canonical": "Gare du Nord", "city": "Paris", "country": "FR", "city_inferred": True}], "city": {"mention": "Pari", "canonical": "Paris", "country": "FR"}, "relation": "near", "carryover": "new"},  # noqa: E501
]
#: The concierge's prefix on the answer turn, as the probe sent it.
ANSWER_PREFIX = (
    "EARLIER REQUEST (the user's own words, not searched yet): "
    "un hôtel près de la Gare du Nord demain à 14h\n"
    'YOU ASKED: {"schema_version": "1", "kind": "city_needed", "subject": "Gare du Nord", '
    '"options": []}\nREPLY:'
)


def _c(name, cc, region, *, ftype="place", lat=0.0, lon=0.0, place_name=None):
    return GeocodeCandidate(
        latitude=lat, longitude=lon, name=name,
        place_name=place_name or f"{name}, {region}, {cc}",
        place_formatted=f"{region}, {cc}",
        feature_type=ftype, country_code=cc, region=region, bbox=None, rank=0,
    )


class _V6:
    """Mapbox v6, answering per query; records `(query, types)` per call."""

    def __init__(self, by_query=None):
        self.by_query = by_query or {}
        self.calls: list[tuple] = []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, kwargs.get("types")))
        return list(self.by_query.get(query, []))


class _SearchBox:
    def __init__(self, *candidates):
        self.candidates = list(candidates)
        self.calls: list[tuple] = []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, proximity))
        return list(self.candidates)


class _Inventory:
    def __init__(self, by_lat):
        self.by_lat = by_lat

    def count_near(self, lat, lon, *, radius_km=25.0):
        return self.by_lat.get(round(lat, 4), 0)


def _patch(monkeypatch, v6=None, box=None, inventory=None):
    v6 = v6 or _V6()
    box = box or _SearchBox()
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: v6)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory(inventory or {}))
    return v6, box


def _ctx(*texts):
    """The leaf's `tool_context`: the text part(s), then the A2A DataPart, as
    the real a2a→genai converter hands them to the leaf (the probe's profile
    was empty)."""
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": {}})
    )
    parts = [genai_types.Part(text=text) for text in texts]
    parts.append(convert_a2a_part_to_genai_part(datapart))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _call(intent: dict, ctx, **args) -> dict:
    """The model's call through the real `FunctionTool`: the dict converts to
    a `GeoIntent` (a failed conversion would reach the tool as a raw dict)."""
    return asyncio.run(
        FunctionTool(geocode_location).run_async(args={"intent": intent, **args}, tool_context=ctx)
    )


@pytest.fixture
def statuses(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        geocode_tool, "mark_level", lambda level, status_message="": seen.append(status_message)
    )
    return seen


@pytest.fixture
def core(monkeypatch):
    """Spy: the flat arguments `geocode_location` hands the pipeline."""
    seen: list[dict] = []
    monkeypatch.setattr(
        geocode_tool, "geocode_core", lambda **kwargs: seen.append(kwargs) or {"ok": False}
    )
    return seen


LONDON = _c("London", "GB", "England", lat=51.5072, lon=-0.1276)
PALACE = _c(
    "Buckingham Palace", "GB", "London", ftype="poi", lat=51.5014, lon=-0.1419,
    place_name="Buckingham Palace, London SW1A 1AA, United Kingdom",
)
PARIS = _c("Paris", "FR", "Île-de-France", lat=48.8566, lon=2.3522)
GARE_DU_NORD = _c(
    "Gare du Nord", "FR", "Paris", ftype="poi", lat=48.8809, lon=2.3553,
    place_name="Gare du Nord, 75010 Paris, France",
)
#: A v6 answer that echoes neither the station nor the city: tier 1 falls
#: through, the city is geocoded on its own and aims the Search-Box lookup.
V6_MISS = _c("Nordhausen", "DE", "Thuringia", lat=51.5, lon=10.8)


class TestTheLunaShapesMap:
    def test_buckingham_palace_with_london_is_geocoded_in_london(self, monkeypatch, statuses):
        v6, box = _patch(
            monkeypatch,
            _V6({"Buckingham Palace, London": [V6_MISS], "London": [LONDON]}),
            _SearchBox(PALACE),
            {51.5072: 900, 51.5014: 300},
        )

        result = _call(
            BUCKINGHAM, _ctx("a day use hotel near buckingham palace on friday"), locale="en-GB"
        )

        assert "geocode_city_needed" not in statuses
        assert "clarification" not in result
        assert result["ok"] is True
        assert result["resolved_place"] == "Buckingham Palace, London SW1A 1AA, United Kingdom"
        assert result["country_code"] == "GB"
        assert v6.calls[0] == ("Buckingham Palace, London", None)
        # The palace lookup is aimed at London, the city the model knew.
        assert box.calls == [("Buckingham Palace", "-0.1276,51.5072")]

    @pytest.mark.parametrize("intent", POSTCODE_ONLY, ids=["address", "admin_district", "no_city"])
    def test_dans_le_75009_takes_the_postcode_path(self, core, intent):
        _call(intent, _ctx("un hôtel dans le 75009 demain après-midi"))

        # Q08: the postcode reaches the pipeline, and a place that is nothing
        # but the code is no zone (« dans le 75009 »: the postcode is the place).
        assert core[0]["postal_code"] == "75009"
        assert core[0]["zone"] is None
        assert core[0]["city"] == "Paris"
        assert core[0]["country_code"] is None  # FR is a guess, never the filter (DQ8)

    def test_dans_le_75009_is_looked_up_as_a_postcode_first(self, monkeypatch):
        v6, box = _patch(monkeypatch)

        _call(POSTCODE_ONLY[0], _ctx("un hôtel dans le 75009 demain après-midi"))

        assert v6.calls[0] == ("75009 Paris", POSTCODE_TYPES)

    @pytest.mark.parametrize("intent", GARE_DU_NORD_BARE, ids=["homonym", "no_ambiguity"])
    def test_gare_du_nord_with_no_city_gives_the_city_question(self, monkeypatch, statuses, intent):
        _v6, box = _patch(monkeypatch)

        result = _call(intent, _ctx("un hôtel près de la Gare du Nord demain"))

        assert result["error"] == "geocode_ambiguous"
        assert "geocode_city_needed" in statuses
        assert result["clarification"]["kind"] == "city_needed"
        assert result["clarification"]["subject"] == "Gare du Nord"
        assert result["clarification"]["options"] == []
        assert box.calls == []

    @pytest.mark.parametrize("intent", GARE_DE_LYON, ids=["short", "full"])
    def test_gare_de_lyon_flagged_city_needed_gives_the_city_question(
        self, monkeypatch, statuses, intent
    ):
        v6, box = _patch(monkeypatch)

        result = _call(intent, _ctx("un hôtel à la gare de Lyon demain"))

        assert result["error"] == "geocode_ambiguous"
        assert "geocode_city_needed" in statuses
        assert result["clarification"]["kind"] == "city_needed"
        assert result["clarification"]["subject"] == "Gare de Lyon"
        assert v6.calls == [] and box.calls == []

    @pytest.mark.parametrize("intent", ANSWER_PARI, ids=["station_city_null", "station_city_paris"])
    def test_the_pari_answer_geocodes_gare_du_nord_in_paris(self, monkeypatch, statuses, intent):
        _v6, box = _patch(
            monkeypatch,
            _V6({"Paris": [PARIS], "Gare du Nord, Paris": [V6_MISS]}),
            _SearchBox(GARE_DU_NORD),
            {48.8566: 780, 48.8809: 300},
        )

        result = _call(intent, _ctx(ANSWER_PREFIX, "Pari"))

        assert "geocode_city_needed" not in statuses
        assert result["ok"] is True
        assert result["resolved_place"] == "Gare du Nord, 75010 Paris, France"
        assert box.calls == [("Gare du Nord", "2.3522,48.8566")]
