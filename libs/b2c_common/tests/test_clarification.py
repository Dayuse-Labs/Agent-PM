"""`Clarification` — the closed shape of a place question (QA14707, Q03).

What the contract must refuse matters as much as what it accepts: an unknown
field, a coordinate, an option on a `city_needed` question. Each of those is a
way for something other than the geocoder to put a place in front of the user.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from b2c_common.clarification import MAX_OPTIONS, Clarification, ClarificationOption

_VICTORIA_BC = {
    "label": "Victoria (British Columbia, Canada)",
    "city": "Victoria",
    "region": "British Columbia",
    "country_code": "CA",
}


def _option(**overrides):
    return {**_VICTORIA_BC, **overrides}


class TestAccepts:
    def test_a_city_needed_question_has_no_option(self):
        clarification = Clarification(kind="city_needed", subject="Gare du Nord")

        assert clarification.model_dump() == {
            "schema_version": "1",
            "kind": "city_needed",
            "subject": "Gare du Nord",
            "options": [],
        }

    def test_a_homonym_question_round_trips_through_json(self):
        clarification = Clarification(
            kind="homonym",
            subject="Victoria",
            options=[_option(), _option(label="Victoria (Texas, US)", region="Texas", country_code="US")],
        )

        again = Clarification.model_validate_json(clarification.model_dump_json())

        assert again == clarification
        assert [o.country_code for o in again.options] == ["CA", "US"]

    def test_an_option_may_have_no_country(self):
        # Mapbox can leave `context.country` out: absent, never guessed.
        option = ClarificationOption(label="Victoria", city="Victoria")
        assert option.country_code is None
        assert option.region == ""


class TestRefuses:
    @pytest.mark.parametrize("field", ["latitude", "longitude", "lat", "lon", "coordinates", "bbox"])
    def test_no_coordinate_can_ride_on_the_question(self, field):
        with pytest.raises(ValidationError):
            Clarification.model_validate({"kind": "city_needed", "subject": "Gare du Nord", field: 48.88})

    @pytest.mark.parametrize("field", ["latitude", "longitude", "lat", "lon", "coordinates", "bbox"])
    def test_no_coordinate_can_ride_on_an_option(self, field):
        with pytest.raises(ValidationError):
            ClarificationOption.model_validate(_option(**{field: 48.43}))

    def test_the_model_declares_no_coordinate_field(self):
        declared = set(Clarification.model_fields) | set(ClarificationOption.model_fields)
        assert declared == {
            "schema_version", "kind", "subject", "options",
            "label", "city", "region", "country_code",
        }

    def test_an_unknown_field_is_refused(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            Clarification.model_validate(
                {"kind": "homonym", "subject": "Victoria", "options": [_option()], "question": "?"}
            )

    def test_an_unknown_kind_is_refused(self):
        # `too_vague` is a GeoIntent reason (DQ5), not a question the leaf asks.
        with pytest.raises(ValidationError):
            Clarification(kind="too_vague", subject="downtown")  # type: ignore[arg-type]

    def test_another_schema_version_is_refused(self):
        with pytest.raises(ValidationError):
            Clarification.model_validate({"schema_version": "2", "kind": "city_needed", "subject": "x"})

    def test_a_city_needed_question_refuses_any_option(self):
        # The question is asked before any lookup: an option there could only
        # come from somewhere other than the geocoder.
        with pytest.raises(ValidationError, match="city_needed question carries no option"):
            Clarification(kind="city_needed", subject="Gare du Nord", options=[_option()])

    def test_an_unresolved_place_carries_no_option(self):
        # 2026-10-27: every candidate left is one the echo guard refused.
        Clarification(kind="unresolved", subject="Galveston")
        with pytest.raises(ValidationError, match="unresolved question carries no option"):
            Clarification(kind="unresolved", subject="Galveston", options=[_option()])

    def test_a_homonym_question_needs_an_option(self):
        with pytest.raises(ValidationError, match="homonym question needs at least one option"):
            Clarification(kind="homonym", subject="Victoria")

    def test_at_most_five_options(self):
        assert MAX_OPTIONS == 5
        Clarification(kind="homonym", subject="Victoria", options=[_option()] * MAX_OPTIONS)
        with pytest.raises(ValidationError):
            Clarification(kind="homonym", subject="Victoria", options=[_option()] * (MAX_OPTIONS + 1))

    @pytest.mark.parametrize("code", ["ca", "CAN", "Canada", ""])
    def test_a_country_code_is_iso2_uppercase(self, code):
        with pytest.raises(ValidationError):
            ClarificationOption.model_validate(_option(country_code=code))

    def test_an_empty_subject_or_label_is_refused(self):
        with pytest.raises(ValidationError):
            Clarification(kind="city_needed", subject="")
        with pytest.raises(ValidationError):
            ClarificationOption.model_validate(_option(label=""))

    def test_the_question_is_immutable(self):
        clarification = Clarification(kind="city_needed", subject="Gare du Nord")
        with pytest.raises(ValidationError):
            clarification.subject = "Paris"  # type: ignore[misc]
