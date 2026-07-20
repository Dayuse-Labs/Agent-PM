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
    AUTO_WIDEN_MAX_ATTEMPTS,
    BUDGET_SOURCE_EXPLICIT,
    BUDGET_SOURCE_FLEXIBLE_DEFAULT,
    SessionProfile,
    _looks_like_time_derived_budget,
    _normalize_timeslot,
    _split_one_sided_clock,
    apply_profile_delta,
    extract_final_question,
    is_bare_affirmative,
    is_booking_confirmation_signal,
    is_search_refinement_signal,
    maybe_auto_widen,
    questions_equivalent,
    record_search_outcome,
    record_search_shortlist,
    resolve_hotel_reference,
    resolve_hotel_reference_strict,
    resolve_hotel_references,
    search_context_line,
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


# ── S12 audit 2026-07-20: search-exhaustion terminal guard (prod 034c97c4) ──


class TestSearchExhaustion:
    def test_first_widen_increments_attempt_count(self):
        profile = SessionProfile(
            consecutive_empty_searches=2, budget_max=100.0,
            budget_request_source=BUDGET_SOURCE_FLEXIBLE_DEFAULT,
        )
        assert maybe_auto_widen(profile) is True
        assert profile.widen_attempt_count == 1
        assert profile.search_exhausted is False

    def test_second_widen_increments_to_the_cap(self):
        profile = SessionProfile(
            consecutive_empty_searches=2, budget_max=150.0,
            budget_request_source=BUDGET_SOURCE_FLEXIBLE_DEFAULT, widen_attempt_count=1,
        )
        assert maybe_auto_widen(profile) is True
        assert profile.widen_attempt_count == 2
        assert profile.search_exhausted is False

    def test_failed_widen_below_the_cap_does_not_exhaust(self):
        """Only 1 prior real widen and nothing left to widen (explicit budget)
        — must NOT exhaust yet (agent-usa: exhaustion needs >= 2 prior widens)."""
        profile = SessionProfile(
            consecutive_empty_searches=2, budget_max=499.0,
            budget_request_source=BUDGET_SOURCE_EXPLICIT, widen_attempt_count=1,
        )
        assert maybe_auto_widen(profile) is False
        assert profile.search_exhausted is False

    def test_failed_widen_at_the_cap_sets_exhausted(self):
        profile = SessionProfile(
            consecutive_empty_searches=2, budget_max=499.0,
            budget_request_source=BUDGET_SOURCE_EXPLICIT,
            widen_attempt_count=AUTO_WIDEN_MAX_ATTEMPTS,
        )
        assert maybe_auto_widen(profile) is False
        assert profile.search_exhausted is True

    def test_missing_budget_at_the_cap_also_sets_exhausted(self):
        profile = SessionProfile(
            consecutive_empty_searches=2, budget_max=None,
            widen_attempt_count=AUTO_WIDEN_MAX_ATTEMPTS,
        )
        assert maybe_auto_widen(profile) is False
        assert profile.search_exhausted is True

    def test_successful_search_clears_exhaustion_and_attempt_count(self):
        profile = SessionProfile(
            search_exhausted=True, widen_attempt_count=2, consecutive_empty_searches=4,
        )
        record_search_outcome(profile, results_count=3)
        assert profile.search_exhausted is False
        assert profile.widen_attempt_count == 0

    def test_empty_outcome_never_clears_exhaustion(self):
        profile = SessionProfile(search_exhausted=True, widen_attempt_count=2)
        record_search_outcome(profile, results_count=0)
        assert profile.search_exhausted is True
        assert profile.widen_attempt_count == 2


class TestIsBareAffirmative:
    def test_matches_bare_affirmatives(self):
        for message in ["ok", "Ok!", "oui", "sure", "d'accord", "parfait 👍"]:
            assert is_bare_affirmative(message) is True

    def test_rejects_substantive_messages(self):
        for message in ["Lyon", "20", "try Lyon instead", "ok let's go to Lyon", ""]:
            assert is_bare_affirmative(message) is False


# ── S12 audit 2026-07-20: budget-vs-duration false positive (prod audit 2026-07-19) ──


class TestBudgetVsDurationGuard:
    def test_flags_a_duration_mention(self):
        assert _looks_like_time_derived_budget("Less than 20 minutes away", 20) is True

    def test_flags_a_distance_mention(self):
        assert _looks_like_time_derived_budget("within 35 km", 35) is True

    def test_currency_marker_is_never_dropped(self):
        for message in ["less than $20", "budget less than 20 dollars", "20€ max"]:
            assert _looks_like_time_derived_budget(message, 20) is False

    def test_apply_profile_delta_drops_a_time_derived_budget(self):
        profile = SessionProfile()
        apply_profile_delta(
            profile,
            {"city": "Hillsborough", "budget_max": 20, "budget_request_source": "llm_extraction"},
            "Less than 20 minutes away",
        )
        assert profile.budget_max is None
        assert profile.budget_request_source is None

    def test_apply_profile_delta_keeps_a_currency_marked_budget(self):
        profile = SessionProfile()
        apply_profile_delta(profile, {"city": "Hillsborough", "budget_max": 20}, "less than $20")
        assert profile.budget_max == 20.0


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


# ── P2 (S06): recovery suggestions + the recovery-ack signal ────────────────


class TestRecoverySuggestionsLifecycle:
    def test_zero_results_sets_localized_suggestions(self):
        profile = SessionProfile()
        record_search_outcome(profile, results_count=0, language="fr")
        assert profile.last_suggestions == [
            "augmenter le budget", "élargir la zone", "retirer un filtre",
        ]

    def test_zero_results_defaults_to_english(self):
        profile = SessionProfile()
        record_search_outcome(profile, results_count=0, language="en")
        assert profile.last_suggestions == [
            "increase the budget", "try a nearby area", "remove a filter",
        ]

    def test_fresh_results_clear_a_stale_offer(self):
        profile = SessionProfile(last_suggestions=["increase the budget"])
        record_search_outcome(profile, results_count=3, language="en")
        assert profile.last_suggestions is None


class TestRecoveryAckSignal:
    def test_bare_ok_after_empty_streak_is_a_refinement_signal(self):
        profile = SessionProfile(consecutive_empty_searches=1)
        assert is_search_refinement_signal("Ok", profile)
        assert is_search_refinement_signal("sure", profile)

    def test_bare_ok_without_empty_streak_is_not_a_signal(self):
        profile = SessionProfile(consecutive_empty_searches=0)
        assert not is_search_refinement_signal("Ok", profile)

    def test_unrelated_message_after_empty_streak_is_not_a_signal(self):
        profile = SessionProfile(consecutive_empty_searches=2)
        assert not is_search_refinement_signal("what about parking", profile)

    def test_greeting_after_empty_streak_is_not_a_signal(self):
        # Only a bare AFFIRMATIVE counts — a greeting/thanks is not "yes, do that".
        profile = SessionProfile(consecutive_empty_searches=2)
        assert not is_search_refinement_signal("Bonjour", profile)

    def test_recovery_chip_matches_last_suggestions_verbatim(self):
        profile = SessionProfile(
            last_suggestions=["increase the budget", "try a nearby area", "remove a filter"]
        )
        assert is_search_refinement_signal("Try a nearby area", profile)
        assert not is_search_refinement_signal("Adjust your price range", profile)

    def test_chip_match_is_case_insensitive_and_never_a_prose_regex(self):
        """The match is against the PERSISTED list verbatim, not a regex over
        the assistant's own synthesized prose (which is LLM-authored/streamed
        and not a stable target)."""
        profile = SessionProfile(last_suggestions=["remove a filter"])
        assert is_search_refinement_signal("REMOVE A FILTER", profile)
        assert not is_search_refinement_signal("please remove a filter for me", profile)


# ── Multi-turn refinement (S9+): a follow-up adjusting a prior search ────────


class TestRefinementModifierSignal:
    def test_date_change_after_a_search_is_a_refinement(self):
        profile = SessionProfile(city="Paris")
        assert is_search_refinement_signal("je le veux pour le 28", profile)
        assert is_search_refinement_signal("plutôt demain", profile)
        assert is_search_refinement_signal("actually the 28th of July", profile)

    def test_budget_change_after_a_search_is_a_refinement(self):
        profile = SessionProfile(city="Paris")
        assert is_search_refinement_signal("moins cher", profile)
        assert is_search_refinement_signal("cheaper please", profile)
        assert is_search_refinement_signal("150", profile)  # bare number = a budget

    def test_timeslot_change_after_a_search_is_a_refinement(self):
        assert is_search_refinement_signal("plutôt le matin", SessionProfile(city="Paris"))

    def test_no_prior_search_context_no_refinement(self):
        # A date/budget with NO prior search is a fresh search via triage, not a
        # refinement override.
        assert not is_search_refinement_signal("je le veux pour le 28", SessionProfile())

    def test_naming_a_shortlist_hotel_stays_booking_not_refinement(self):
        profile = SessionProfile(
            city="Paris", last_results=[{"hotel_id": 1, "name": "Villa Paris Orly"}]
        )
        assert not is_search_refinement_signal("book Villa Paris Orly for the 28th", profile)

    def test_prior_context_via_shortlist_only(self):
        profile = SessionProfile(last_results=[{"hotel_id": 1, "name": "Foo Palace"}])
        assert is_search_refinement_signal("le 28 juillet", profile)


class TestSearchContextLine:
    def test_summarizes_known_params(self):
        line = search_context_line(
            SessionProfile(city="Paris", budget_max=150.0, amenities=["pool"])
        )
        assert "Paris" in line and "150" in line and "pool" in line

    def test_empty_when_nothing_known(self):
        assert search_context_line(SessionProfile()) == ""


# ── P10 (S06): anti-clarification-loop pure detectors ───────────────────────


class TestExtractFinalQuestion:
    def test_returns_last_question(self):
        message = (
            "Thanks — 5pm works.\n"
            "Quick note: I can't re-run the same list from here, but I can refine "
            "if you tell me one thing: do you want Queens or Brooklyn?"
        )
        question = extract_final_question(message)
        assert question is not None
        assert "Queens or Brooklyn" in question

    def test_none_without_a_trailing_question(self):
        assert extract_final_question("Here are your hotels.") is None
        assert extract_final_question("") is None

    def test_none_when_the_question_is_not_the_last_sentence(self):
        assert extract_final_question("Which area? Anyway, here are your hotels.") is None


class TestQuestionsEquivalent:
    QUESTION = "Which airport area exactly should I prioritize?"

    def test_exact_and_fuzzy_match(self):
        assert questions_equivalent(self.QUESTION, self.QUESTION)
        assert questions_equivalent(self.QUESTION, "Which airport area, exactly, should I prioritize?")

    def test_different_question_does_not_match(self):
        assert not questions_equivalent(self.QUESTION, "What budget should I use for the search?")

    def test_none_or_empty_never_matches(self):
        assert not questions_equivalent(self.QUESTION, None)
        assert not questions_equivalent(self.QUESTION, "")
        assert not questions_equivalent(None, None)


# ── S07: named-hotel lookup (the `_last_results` equivalent) ───────────────

SHORTLIST = [
    {"hotel_id": 4242, "name": "Kimpton - Hotel Palomar South Beach"},
    {"hotel_id": 4243, "name": "Hampton Inn Miami Midtown"},
]


class TestRecordSearchShortlist:
    def test_non_empty_results_populate_the_shortlist(self):
        profile = SessionProfile()
        record_search_shortlist(
            profile, [{"hotelId": 1, "name": "Hotel A"}, {"hotel_id": 2, "name": "Hotel B"}]
        )
        assert profile.last_results == [
            {"hotel_id": 1, "name": "Hotel A"},
            {"hotel_id": 2, "name": "Hotel B"},
        ]

    def test_empty_results_leave_a_previous_shortlist_untouched(self):
        profile = SessionProfile(last_results=list(SHORTLIST))
        record_search_shortlist(profile, [])
        record_search_shortlist(profile, None)
        assert profile.last_results == SHORTLIST

    def test_bounded_to_max_shortlist(self):
        profile = SessionProfile()
        results = [{"hotel_id": i, "name": f"Hotel {i}"} for i in range(10)]
        record_search_shortlist(profile, results)
        assert len(profile.last_results) == 5

    def test_entries_without_a_name_are_dropped(self):
        profile = SessionProfile()
        record_search_shortlist(profile, [{"hotel_id": 1}, {"hotel_id": 2, "name": "Hotel B"}])
        assert profile.last_results == [{"hotel_id": 2, "name": "Hotel B"}]


class TestResolveHotelReference:
    def test_short_reference_matches_the_full_shortlist_name(self):
        # prod session 34d216e3: find_hotel_by_name failed on "Kimpton" even
        # though the agent had just shown that hotel.
        hotel = resolve_hotel_reference("Kimpton", SHORTLIST)
        assert hotel is not None and hotel["hotel_id"] == 4242

    def test_full_name_matches_exactly(self):
        hotel = resolve_hotel_reference("Kimpton - Hotel Palomar South Beach", SHORTLIST)
        assert hotel is not None and hotel["hotel_id"] == 4242

    def test_message_wrapping_the_name_still_matches(self):
        hotel = resolve_hotel_reference("book the Hampton Inn Miami Midtown please", SHORTLIST)
        assert hotel is not None and hotel["hotel_id"] == 4243

    def test_no_match_returns_none(self):
        assert resolve_hotel_reference("Moxy NYC Chelsea", SHORTLIST) is None

    def test_empty_shortlist_returns_none(self):
        assert resolve_hotel_reference("Kimpton", None) is None
        assert resolve_hotel_reference("Kimpton", []) is None

    def test_too_short_names_are_never_matched(self):
        assert resolve_hotel_reference("W", [{"hotel_id": 1, "name": "W"}]) is None


# ── S12 audit 2026-07-20: the strict (substring-only) tier of the same lookup ──

_STALE_TOKEN_ONLY_SHORTLIST = [{"hotel_id": 99, "name": "Wren Valley Inn"}]


class TestResolveHotelReferenceStrict:
    def test_substring_match_still_resolves(self):
        hotel = resolve_hotel_reference_strict("Kimpton", SHORTLIST)
        assert hotel is not None and hotel["hotel_id"] == 4242

    def test_token_only_overlap_is_never_trusted(self):
        # "Sir Christopher Wren Hotel" shares only the word "wren" with the
        # stale shortlist's "Wren Valley Inn" — the WEAK tier (unchanged,
        # resolve_hotel_reference) still matches it, but the STRICT tier must
        # not (audit 2026-07-20: a stale shortlist must never mask a
        # different, explicitly-named hotel via a one-word coincidence).
        assert resolve_hotel_reference_strict(
            "Sir Christopher Wren Hotel", _STALE_TOKEN_ONLY_SHORTLIST
        ) is None
        assert resolve_hotel_reference(
            "Sir Christopher Wren Hotel", _STALE_TOKEN_ONLY_SHORTLIST
        ) is not None

    def test_empty_shortlist_returns_none(self):
        assert resolve_hotel_reference_strict("Kimpton", None) is None
        assert resolve_hotel_reference_strict("Kimpton", []) is None


class TestResolveHotelReferences:
    def test_two_named_hotels_both_resolve(self):
        hits = resolve_hotel_references("compare Kimpton and Hampton Inn Miami Midtown", SHORTLIST)
        ids = {h["hotel_id"] for h in hits}
        assert ids == {4242, 4243}

    def test_no_names_mentioned_returns_empty(self):
        assert resolve_hotel_references("compare them", SHORTLIST) == []


# ── S07: booking confirmation signal (R9, guard #12) ────────────────────────


class TestIsBookingConfirmationSignal:
    def test_bare_affirmative_with_pending_booking_is_a_signal(self):
        profile = SessionProfile(pending_booking={"hotel_id": 1})
        assert is_booking_confirmation_signal("yes", profile)
        assert is_booking_confirmation_signal("d'accord", profile)

    def test_bare_affirmative_without_pending_booking_is_not_a_signal(self):
        profile = SessionProfile()
        assert not is_booking_confirmation_signal("yes", profile)

    def test_non_affirmative_message_is_not_a_signal_even_with_pending_booking(self):
        profile = SessionProfile(pending_booking={"hotel_id": 1})
        assert not is_booking_confirmation_signal("what about a different hotel?", profile)
