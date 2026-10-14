"""geo_intent.py (plan qa14707, Q06) — the `GeoIntent` v1.1 model the search
leaf's LLM fills. Locks the invariants the code relies on: no coordinate field
anywhere, `ambiguity` without `options` (DQ5), closed enumerations,
`extra="forbid"` at every level, a default on every field (an absent or partial
argument still validates), at most 2 places, and a description on every field
(the descriptions are prompt: they end up in the tool declaration).
"""
from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import BaseModel, ValidationError

from b2c_common.geo_intent import (
    MAX_PLACES,
    SCHEMA_VERSION,
    Ambiguity,
    CityRef,
    Exclusion,
    GeoIntent,
    Place,
)

_MODELS: tuple[type[BaseModel], ...] = (GeoIntent, Place, CityRef, Exclusion, Ambiguity)

_COORDINATE_NAMES = {
    "lat", "lon", "lng", "latitude", "longitude", "coordinates", "coords",
    "bbox", "center", "geometry", "point", "location",
}


def _nested_models(model: type[BaseModel]) -> set[type[BaseModel]]:
    """Every model reachable from `model` through its field annotations."""
    found: set[type[BaseModel]] = set()
    stack: list[Any] = [model]
    while stack:
        current = stack.pop()
        if isinstance(current, type) and issubclass(current, BaseModel):
            if current in found:
                continue
            found.add(current)
            stack.extend(f.annotation for f in current.model_fields.values())
        else:
            stack.extend(get_args(current))
    return found


def _schema_nodes(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _schema_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _schema_nodes(value)


class TestNoCoordinate:
    def test_every_model_is_covered(self):
        assert _nested_models(GeoIntent) == set(_MODELS)

    def test_no_coordinate_field_name_in_any_model(self):
        for model in _MODELS:
            assert not set(model.model_fields) & _COORDINATE_NAMES, model.__name__

    def test_no_numeric_type_anywhere_in_the_schema(self):
        # A coordinate is a number; the contract has none at all, whatever its name.
        types_seen = {n.get("type") for n in _schema_nodes(GeoIntent.model_json_schema())}
        assert not types_seen & {"number", "integer"}

    @pytest.mark.parametrize("key", ["latitude", "longitude", "lat", "lon"])
    def test_a_coordinate_sent_by_the_llm_is_refused(self, key):
        with pytest.raises(ValidationError):
            GeoIntent.model_validate({key: 48.85})
        with pytest.raises(ValidationError):
            GeoIntent.model_validate({"places": [{"mention": "Paris", key: 2.35}]})


class TestAmbiguityHasNoOptions:
    def test_only_reason(self):
        assert set(Ambiguity.model_fields) == {"reason"}

    def test_options_are_refused(self):
        with pytest.raises(ValidationError):
            Ambiguity.model_validate({"reason": "homonym", "options": ["Paris", "Paris, TX"]})
        with pytest.raises(ValidationError):
            GeoIntent.model_validate({"ambiguity": {"reason": "homonym", "options": ["Paris"]}})

    def test_reasons_are_closed(self):
        reason = Ambiguity.model_json_schema()["properties"]["reason"]
        enums = [n["enum"] for n in _schema_nodes(reason) if "enum" in n]
        assert enums == [["homonym", "city_needed", "too_vague"]]
        with pytest.raises(ValidationError):
            Ambiguity.model_validate({"reason": "unsure"})


class TestDefaults:
    @pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__name__)
    def test_every_field_has_a_default(self, model):
        assert [n for n, f in model.model_fields.items() if f.is_required()] == []
        model()  # builds from nothing

    def test_empty_intent(self):
        intent = GeoIntent()
        assert intent.schema_version == SCHEMA_VERSION == "1.1"
        assert intent.places == []
        assert intent.city is None
        assert intent.country_named is None
        assert intent.region_named is None
        assert intent.relation == "in"
        # `keep` = fill the empty slots from the earlier search, today's behaviour.
        assert intent.carryover == "keep"
        assert intent.exclusions == []
        assert intent.ambiguity is None

    def test_partial_argument_validates(self):
        intent = GeoIntent.model_validate({"places": [{"mention": "gare de lyon"}]})
        place = intent.places[0]
        assert place.mention == "gare de lyon"
        assert place.kind is None
        assert place.canonical == ""
        assert place.postal_code is None
        assert place.city is None
        assert place.city_inferred is False


class TestClosedSchema:
    @pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__name__)
    def test_extra_keys_are_refused_at_every_level(self, model):
        assert model.model_config.get("extra") == "forbid"
        with pytest.raises(ValidationError):
            model.model_validate({"unexpected": "x"})

    def test_place_kinds_are_closed(self):
        assert set(get_args(get_args(Place.model_fields["kind"].annotation)[0])) == {
            "city", "admin_district", "neighborhood", "landmark", "street",
            "station", "airport", "address", "hotel", "region",
        }
        with pytest.raises(ValidationError):
            Place.model_validate({"kind": "planet"})

    def test_relation_and_carryover_are_closed(self):
        with pytest.raises(ValidationError):
            GeoIntent.model_validate({"relation": "inside"})
        with pytest.raises(ValidationError):
            GeoIntent.model_validate({"carryover": "replace"})

    def test_schema_version_is_fixed(self):
        with pytest.raises(ValidationError):
            GeoIntent.model_validate({"schema_version": "1"})

    def test_at_most_two_places(self):
        assert MAX_PLACES == 2
        GeoIntent.model_validate({"places": [{"mention": "a"}, {"mention": "b"}]})
        with pytest.raises(ValidationError):
            GeoIntent.model_validate({"places": [{"mention": "a"}, {"mention": "b"}, {"mention": "c"}]})

    def test_frozen(self):
        # A frozen `GeoIntent()` is safe as a shared tool-parameter default.
        intent = GeoIntent()
        with pytest.raises(ValidationError):
            intent.relation = "near"  # type: ignore[misc]


class TestFields:
    def test_place_fields(self):
        assert list(Place.model_fields) == [
            "mention", "kind", "canonical", "postal_code", "city", "region", "country", "city_inferred",
        ]

    def test_city_fields(self):
        assert list(CityRef.model_fields) == ["mention", "canonical", "region", "country"]

    def test_intent_fields(self):
        assert list(GeoIntent.model_fields) == [
            "schema_version", "places", "city", "country_named", "region_named",
            "relation", "carryover", "exclusions", "ambiguity",
        ]

    @pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__name__)
    def test_every_field_and_model_is_described(self, model):
        # The descriptions are what the LLM reads in the tool declaration.
        assert model.__doc__ and model.__doc__.strip()
        assert [n for n, f in model.model_fields.items() if not (f.description or "").strip()] == []


class TestExamples:
    """The shapes Q07 will map — one per rule moved from the prompt."""

    def test_address_with_postcode_keeps_the_postcode(self):
        # QA trace C: « 2 boulevard Poissonnière 75009 » — the postcode used to be thrown away.
        intent = GeoIntent.model_validate({
            "places": [{
                "mention": "2 boulevard Poissonnière 75009",
                "kind": "address",
                "canonical": "2 Boulevard Poissonnière",
                "postal_code": "75009",
                "city": "Paris",
                "city_inferred": True,
                "country": "FR",
            }],
        })
        assert intent.places[0].postal_code == "75009"
        assert intent.country_named is None  # FR is a guess, never the hard filter (DQ8)

    def test_city_needed_carries_the_s5_rule(self):
        # DQ6: a place named after a city it is not in — no city, reason city_needed.
        intent = GeoIntent.model_validate({
            "places": [{"mention": "gare de lyon", "kind": "station", "canonical": "Gare de Lyon"}],
            "ambiguity": {"reason": "city_needed"},
        })
        assert intent.places[0].city is None
        assert intent.city is None
        assert intent.ambiguity == Ambiguity(reason="city_needed")

    def test_misspelt_city_keeps_mention_and_canonical(self):
        intent = GeoIntent.model_validate({
            "places": [{"mention": "Pari", "kind": "city", "canonical": "Paris"}],
            "city": {"mention": "Pari", "canonical": "Paris", "country": "FR"},
            "carryover": "new",
        })
        assert intent.city == CityRef(mention="Pari", canonical="Paris", country="FR")
        assert intent.places[0].mention == "Pari"

    def test_round_trip(self):
        intent = GeoIntent.model_validate({
            "places": [{"mention": "times square", "kind": "landmark", "canonical": "Times Square",
                        "city": "New York", "city_inferred": True, "country": "US"}],
            "relation": "near",
            "exclusions": [{"mention": "NYC", "canonical": "New York", "kind": "city"}],
        })
        assert GeoIntent.model_validate(intent.model_dump()) == intent
        assert GeoIntent.model_validate_json(intent.model_dump_json()) == intent
