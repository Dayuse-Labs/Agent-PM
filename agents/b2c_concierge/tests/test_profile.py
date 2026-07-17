"""Profile guard tests — behavior ported from the agent-usa production audit
(2026-06-09, tests/unit/application/test_audit_fixes_2026_06.py) onto the
b2c-concierge session-profile schema. The BEHAVIOR is the spec; the old
implementation lived in a workflow-based architecture and is not reused.

- P1 (budget integrity): a bare-number reply is always the user's explicit
  budget and is never silently auto-widened.
- P6 (timeslot sanitization): a one-sided clock label is salvaged into a
  bound, never persisted corrupted; an anchored bound is never inverted by a
  later timeless turn's re-extraction.
"""
from __future__ import annotations

from b2c_concierge.profile import (
    BUDGET_SOURCE_EXPLICIT,
    BUDGET_SOURCE_FLEXIBLE_DEFAULT,
    SessionProfile,
    _normalize_timeslot,
    _split_one_sided_clock,
    apply_profile_delta,
    maybe_auto_widen,
    record_search_outcome,
)


class TestBudgetIntegrity:
    def test_bare_number_answer_marks_budget_explicit(self):
        profile = SessionProfile()
        apply_profile_delta(profile, {"city": "New York", "budget_max": 180}, "180")
        assert profile.budget_max == 180.0
        assert profile.budget_request_source == BUDGET_SOURCE_EXPLICIT

    def test_bare_number_with_dollar_sign_marks_budget_explicit(self):
        profile = SessionProfile()
        apply_profile_delta(profile, {"city": "New York", "budget_max": 40}, "$40")
        assert profile.budget_request_source == BUDGET_SOURCE_EXPLICIT

    def test_leaf_supplied_source_is_not_overridden_by_a_non_bare_message(self):
        """A non-bare-number message keeps whatever source the delta claims —
        the guard only OVERRIDES toward explicit, it never invents a source."""
        profile = SessionProfile()
        apply_profile_delta(
            profile,
            {"city": "New York", "budget_max": 150, "budget_request_source": BUDGET_SOURCE_FLEXIBLE_DEFAULT},
            "find me something under 150 please",
        )
        assert profile.budget_max == 150.0
        assert profile.budget_request_source == BUDGET_SOURCE_FLEXIBLE_DEFAULT

    def test_auto_widen_skips_bare_number_budget_marked_explicit(self):
        profile = SessionProfile()
        apply_profile_delta(profile, {"city": "New York", "budget_max": 110}, "110")
        profile.consecutive_empty_searches = 2

        widened = maybe_auto_widen(profile)

        assert widened is False
        assert profile.budget_max == 110.0

    def test_auto_widen_sets_disclosure_payload(self):
        profile = SessionProfile(
            consecutive_empty_searches=2,
            budget_max=100.0,
            budget_request_source=BUDGET_SOURCE_FLEXIBLE_DEFAULT,
        )

        widened = maybe_auto_widen(profile)

        assert widened is True
        assert profile.budget_max == 150.0
        assert profile.auto_widen_disclosure == {"from": 100.0, "to": 150.0}

    def test_auto_widen_skips_below_streak_threshold(self):
        profile = SessionProfile(
            consecutive_empty_searches=1,
            budget_max=100.0,
            budget_request_source=BUDGET_SOURCE_FLEXIBLE_DEFAULT,
        )
        assert maybe_auto_widen(profile) is False
        assert profile.budget_max == 100.0

    def test_record_search_outcome_resets_streak_on_results(self):
        profile = SessionProfile(consecutive_empty_searches=3)
        record_search_outcome(profile, results_count=2)
        assert profile.consecutive_empty_searches == 0

    def test_record_search_outcome_increments_streak_on_empty(self):
        profile = SessionProfile(consecutive_empty_searches=1)
        record_search_outcome(profile, results_count=0)
        assert profile.consecutive_empty_searches == 2


class TestTimeslotSanitization:
    def test_one_sided_clock_label_is_salvaged_as_start_bound(self):
        profile = SessionProfile()
        apply_profile_delta(
            profile,
            {"city": "New York", "timeslot": "15:00-", "budget_max": 150},
            "3p check in queens bk",
        )
        assert profile.timeslot in (None, "")
        assert profile.timeslot_start == "15:00"
        assert "15:00_" not in str(profile.timeslot)

    def test_normalize_timeslot_rejects_one_sided_clock_strings(self):
        assert _normalize_timeslot("15:00-") is None
        assert _normalize_timeslot("-09:00") is None
        assert _normalize_timeslot("15:00_") is None
        assert _normalize_timeslot("morning") == "morning"

    def test_split_one_sided_clock_bounds(self):
        assert _split_one_sided_clock("15:00-") == ("15:00", None)
        assert _split_one_sided_clock("-09:00") == (None, "09:00")
        assert _split_one_sided_clock("9am-") == ("09:00", None)
        assert _split_one_sided_clock("morning") == (None, None)

    def test_end_bound_not_inverted_to_start_on_timeless_turn(self):
        profile = SessionProfile(
            city="Cincinnati",
            timeslot_end="09:00",
            timeslot_request_source=BUDGET_SOURCE_EXPLICIT,
            timeslot_mode="end_only",
        )
        # Turn 2: no time in the message, but re-extraction flips the same
        # clock value into a start-bound candidate (prod session aa092825).
        apply_profile_delta(
            profile,
            {"city": "Cincinnati", "timeslot_start": "09:00", "budget_max": 200},
            "Just find me a hotel that allows that early of check in",
        )
        assert profile.timeslot_end == "09:00"
        assert profile.timeslot_start in (None, "")
        assert profile.timeslot_mode == "end_only"

    def test_start_bound_accepted_when_message_has_explicit_time(self):
        """The inversion guard only blocks a TIMELESS re-extraction — a turn
        that genuinely mentions a new time must still be able to update the
        bound."""
        profile = SessionProfile(
            city="Cincinnati", timeslot_end="09:00", timeslot_mode="end_only"
        )
        apply_profile_delta(
            profile,
            {"timeslot_start": "07:00"},
            "actually can we check in at 7am instead",
        )
        assert profile.timeslot_start == "07:00"
        assert profile.timeslot_mode == "range"

    def test_fresh_timeslot_bounds_set_range_mode(self):
        profile = SessionProfile()
        apply_profile_delta(
            profile, {"timeslot_start": "10:00", "timeslot_end": "14:00"}, "10am to 2pm"
        )
        assert profile.timeslot_start == "10:00"
        assert profile.timeslot_end == "14:00"
        assert profile.timeslot_mode == "range"


class TestGeoAnchors:
    def test_state_anchor_persists_across_turns_without_city_change(self):
        profile = SessionProfile(city="Florence", state_anchor="KY")
        apply_profile_delta(profile, {"budget_max": 120}, "120")
        assert profile.state_anchor == "KY"

    def test_state_anchor_cleared_on_explicit_city_switch(self):
        profile = SessionProfile(city="Florence", state_anchor="KY", country_anchor="US")
        apply_profile_delta(profile, {"city": "Paris"}, "actually let's do Paris")
        assert profile.city == "Paris"
        assert profile.state_anchor is None
        assert profile.country_anchor is None

    def test_country_anchor_cleared_on_explicit_city_switch(self):
        profile = SessionProfile(city="Florence", country_anchor="IT")
        apply_profile_delta(profile, {"city": "Milford"}, "let's try Milford instead")
        assert profile.country_anchor is None

    def test_fresh_anchor_in_the_same_delta_survives_the_city_change(self):
        """A city switch that ALSO resolves a new anchor (same delta, e.g. the
        leaf disambiguated "Florence Kentucky") keeps the fresh anchor — the
        clear only wipes STALE anchors from a previous city."""
        profile = SessionProfile(city="Florence", state_anchor="IT")
        apply_profile_delta(
            profile,
            {"city": "Florence", "state_anchor": "KY", "country_anchor": "US"},
            "florence kentucky please",
        )
        assert profile.state_anchor == "KY"
        assert profile.country_anchor == "US"

    def test_no_city_change_no_anchor_wipe(self):
        profile = SessionProfile(city="Florence", state_anchor="KY")
        apply_profile_delta(profile, {"city": "Florence", "budget_max": 90}, "90")
        assert profile.state_anchor == "KY"


class TestProfileSerialization:
    def test_round_trips_through_dict(self):
        profile = SessionProfile(
            city="Paris",
            budget_max=150.0,
            budget_request_source=BUDGET_SOURCE_EXPLICIT,
            amenities=["pool", "spa"],
        )
        restored = SessionProfile.from_dict(profile.to_dict())
        assert restored == profile

    def test_from_dict_ignores_unknown_keys(self):
        restored = SessionProfile.from_dict({"city": "Lyon", "not_a_field": "x"})
        assert restored.city == "Lyon"


class TestAmenitiesAndLanguage:
    def test_amenities_merge_without_duplicates(self):
        profile = SessionProfile(amenities=["pool"])
        apply_profile_delta(profile, {"amenities": ["pool", "spa"]}, "with spa please")
        assert profile.amenities == ["pool", "spa"]

    def test_language_is_overwritten(self):
        profile = SessionProfile(language="en")
        apply_profile_delta(profile, {"language": "fr"}, "en français")
        assert profile.language == "fr"
