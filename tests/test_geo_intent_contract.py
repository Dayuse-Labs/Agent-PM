"""`GeoIntent` v1.1 contract (plan qa14707, Q06).

1. Snapshot: `contracts/geo_intent.schema.json` is exactly the schema generated
   from the model, so any field change is a visible diff. Regenerate with
   `python libs/b2c_common/b2c_common/geo_intent.py > contracts/geo_intent.schema.json`.
2. Offline ADK 2.4 proof that the search leaf can take a `GeoIntent` as a
   structured tool argument (DQ1), the 4 properties Q07 relies on:
   - the declaration builds, with the nested object and the enumerations;
   - the LiteLLM conversion produces a valid tool schema;
   - `dict` arguments arrive in the function as a `GeoIntent`;
   - an absent or partial argument is not rejected before the function.

This module keeps `from __future__ import annotations`, like `geocode_tool.py`,
so the tool below is declared under the same conditions Q07's will be. The
signature form is not free: `GeoIntent | None`, and `Optional[GeoIntent]` under
stringified annotations, reach the function as a plain dict (ADK's
`_preprocess_args` only converts a class or a non-string `typing.Union`).
`geo_intent: GeoIntent = GeoIntent()` converts in every case.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import jsonschema
from google.adk.features import FeatureName, is_feature_enabled
from google.adk.models.lite_llm import _function_declaration_to_tool_param
from google.adk.tools.function_tool import FunctionTool

from b2c_common.geo_intent import Ambiguity, GeoIntent, Place

CONTRACT = Path(__file__).resolve().parent.parent / "contracts" / "geo_intent.schema.json"


def locate(city: str = "", geo_intent: GeoIntent = GeoIntent()) -> dict:
    """Stand-in for Q07's `geocode_location` wrapper: reports what it received."""
    return {"received": geo_intent}


def _tool() -> FunctionTool:
    return FunctionTool(locate)


def _run(args: dict[str, Any]) -> Any:
    # `locate` takes no tool_context, so ADK never touches it.
    return asyncio.run(_tool().run_async(args=args, tool_context=None))  # type: ignore[arg-type]


def _parameters() -> dict[str, Any]:
    declaration = _tool()._get_declaration()
    assert declaration is not None
    assert declaration.parameters_json_schema is not None
    return declaration.parameters_json_schema


def _tool_param() -> dict[str, Any]:
    declaration = _tool()._get_declaration()
    assert declaration is not None
    return _function_declaration_to_tool_param(declaration)


_FULL_ARGS = {
    "geo_intent": {
        "schema_version": "1.1",
        "places": [{
            "mention": "2 boulevard Poissonnière 75009",
            "kind": "address",
            "canonical": "2 Boulevard Poissonnière",
            "postal_code": "75009",
            "city": "Paris",
            "region": None,
            "country": "FR",
            "city_inferred": True,
        }],
        "city": {"mention": "", "canonical": "Paris", "region": None, "country": "FR"},
        "country_named": None,
        "region_named": None,
        "relation": "in",
        "carryover": "new",
        "exclusions": [],
        "ambiguity": None,
    },
}


class TestSnapshot:
    def test_snapshot_matches_the_model(self):
        assert CONTRACT.exists(), "contracts/geo_intent.schema.json is missing"
        assert json.loads(CONTRACT.read_text(encoding="utf-8")) == GeoIntent.model_json_schema(), (
            "GeoIntent changed: regenerate contracts/geo_intent.schema.json "
            "(python libs/b2c_common/b2c_common/geo_intent.py > contracts/geo_intent.schema.json) "
            "and review the diff"
        )

    def test_snapshot_is_a_valid_json_schema(self):
        jsonschema.Draft202012Validator.check_schema(json.loads(CONTRACT.read_text(encoding="utf-8")))


class TestDeclarationBuilds:
    def test_adk_uses_the_json_schema_path(self):
        # The legacy declaration path drops every field description (the prompt
        # rules) and `maxItems`, and emits OpenAPI `nullable`: GeoIntent relies
        # on ADK's default JSON-schema path.
        assert is_feature_enabled(FeatureName.JSON_SCHEMA_FOR_FUNC_DECL)

    def test_nested_object_and_enumerations(self):
        params = _parameters()
        assert params["properties"]["geo_intent"]["$ref"] == "#/$defs/GeoIntent"
        assert "geo_intent" not in params.get("required", [])
        defs = params["$defs"]
        assert set(defs) == {"GeoIntent", "Place", "CityRef", "Exclusion", "Ambiguity"}
        intent = defs["GeoIntent"]
        assert intent["additionalProperties"] is False
        assert intent["properties"]["places"]["items"] == {"$ref": "#/$defs/Place"}
        assert intent["properties"]["places"]["maxItems"] == 2
        assert intent["properties"]["relation"]["enum"] == ["in", "near", "whole_city"]
        assert intent["properties"]["carryover"]["enum"] == ["new", "keep", "replace_place_keep_city", "refine"]
        kind = defs["Place"]["properties"]["kind"]["anyOf"][0]
        assert kind["enum"][0] == "city" and "station" in kind["enum"]
        reason = defs["Ambiguity"]["properties"]["reason"]["anyOf"][0]
        assert reason["enum"] == ["homonym", "city_needed", "too_vague"]
        assert set(defs["Ambiguity"]["properties"]) == {"reason"}

    def test_declared_object_is_the_contract(self):
        # The tool declaration carries exactly the snapshotted model.
        params = _parameters()
        snapshot = json.loads(CONTRACT.read_text(encoding="utf-8"))
        assert params["$defs"]["GeoIntent"] == {k: v for k, v in snapshot.items() if k != "$defs"}
        for name, schema in snapshot["$defs"].items():
            assert params["$defs"][name] == schema


class TestLiteLlmToolSchema:
    def test_openai_function_shape(self):
        param = _tool_param()
        assert param["type"] == "function"
        assert param["function"]["name"] == "locate"
        parameters = param["function"]["parameters"]
        assert parameters["type"] == "object"
        assert set(parameters["properties"]) == {"city", "geo_intent"}
        json.dumps(param)  # plain JSON, no genai enum object left in it

    def test_parameters_are_a_valid_json_schema_with_resolvable_refs(self):
        parameters = _tool_param()["function"]["parameters"]
        jsonschema.Draft202012Validator.check_schema(parameters)
        validator = jsonschema.Draft202012Validator(parameters)
        validator.validate(_FULL_ARGS)
        validator.validate({})
        validator.validate({"geo_intent": {"places": [{
            "mention": "gare de lyon", "kind": "station", "canonical": "Gare de Lyon",
            "city": None, "country": "FR", "postal_code": None,
        }]}})

    def test_the_place_keys_are_required_of_the_model_only(self):
        # Q23: the JSON schema the model reads asks it to write a place's six
        # keys (null when unknown). It binds the model's output, never the
        # tool's input: the same partial place still reaches the function as a
        # `GeoIntent` (`TestArgumentConversion`).
        validator = jsonschema.Draft202012Validator(_tool_param()["function"]["parameters"])
        partial = {"geo_intent": {"places": [{"mention": "gare de lyon"}]}}
        assert not validator.is_valid(partial)
        received = _run(partial)["received"]
        assert isinstance(received, GeoIntent)
        assert received.places[0] == Place(mention="gare de lyon")

    def test_the_schema_refuses_what_the_model_refuses(self):
        validator = jsonschema.Draft202012Validator(_tool_param()["function"]["parameters"])
        for bad in (
            {"geo_intent": {"latitude": 48.85}},
            {"geo_intent": {"places": [{"kind": "planet"}]}},
            {"geo_intent": {"ambiguity": {"reason": "homonym", "options": ["Paris"]}}},
            {"geo_intent": {"places": [{}, {}, {}]}},
        ):
            assert not validator.is_valid(bad), bad

    def test_field_descriptions_reach_the_llm(self):
        # They are prompt: the S5 rule (DQ6) and the place-city rule must be in
        # what the LLM reads.
        defs = _tool_param()["function"]["parameters"]["$defs"]
        reason = defs["Ambiguity"]["properties"]["reason"]["description"]
        assert reason == Ambiguity.model_fields["reason"].description
        assert "gare de Lyon" in reason
        city = defs["Place"]["properties"]["city"]["description"]
        assert city == Place.model_fields["city"].description
        assert "Gare du Nord" in city
        assert defs["GeoIntent"]["description"] == GeoIntent.__doc__


class TestArgumentConversion:
    def test_dict_arrives_as_a_geo_intent(self):
        received = _run(_FULL_ARGS)["received"]
        assert isinstance(received, GeoIntent)
        assert received == GeoIntent.model_validate(_FULL_ARGS["geo_intent"])
        assert received.places[0].postal_code == "75009"

    def test_missing_argument_is_not_rejected(self):
        result = _run({})
        assert "error" not in result
        assert result["received"] == GeoIntent()

    def test_partial_argument_is_not_rejected_and_converts(self):
        result = _run({"geo_intent": {"places": [{"mention": "gare de lyon"}],
                                      "ambiguity": {"reason": "city_needed"}}})
        assert "error" not in result
        received = result["received"]
        assert isinstance(received, GeoIntent)
        assert received.places[0].mention == "gare de lyon"
        assert received.places[0].city is None
        assert received.ambiguity == Ambiguity(reason="city_needed")
        assert received.carryover == "keep"

    def test_invalid_argument_reaches_the_function_as_the_raw_dict(self):
        # ADK logs the validation error and passes the original value through:
        # the tool, not ADK, decides what to do with a malformed intent (Q07).
        raw = {"places": [{"mention": "mars", "kind": "planet"}]}
        result = _run({"geo_intent": raw})
        assert "error" not in result
        assert result["received"] == raw
