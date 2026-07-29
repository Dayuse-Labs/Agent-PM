"""Profile guard tests — behavior ported from the agent-usa production audit
(2026-06-09, tests/unit/application/test_audit_fixes_2026_06.py) onto the
b2c-concierge session-profile schema. The BEHAVIOR is the spec; the old
implementation lived in a workflow-based architecture and is not reused.

- P1 (budget integrity): a bare-number reply is always the user's explicit
  budget and is never silently auto-widened.
- P6 (timeslot sanitization): a one-sided clock label is salvaged into a
  bound, never persisted corrupted; an anchored bound is never inverted by a
  later timeless turn's re-extraction.

S-G1 (2026-07-23 geo/multi-turn remediation) adds the profile v2 schema +
typed-ops reducer tests: new slots, `{"op": "set"|"clear"}` semantics,
absent-is-carryover, flat-delta retro-compat, city-vs-zone invalidation
rules, and the pagination accumulator (`shown_hotel_ids`/`search_cursor`).
"""
from __future__ import annotations

import logging

from b2c_concierge.profile import (
    AUTO_WIDEN_MAX_ATTEMPTS,
    BUDGET_SOURCE_EXPLICIT,
    BUDGET_SOURCE_FLEXIBLE_DEFAULT,
    MAX_SHOWN_HOTEL_IDS,
    PROFILE_SCHEMA_VERSION,
    SessionProfile,
    _looks_like_time_derived_budget,
    _normalize_timeslot,
    _split_one_sided_clock,
    advance_search_cursor,
    apply_profile_delta,
    extract_final_question,
    is_bare_affirmative,
    is_booking_confirmation_signal,
    is_more_options_signal,
    is_search_refinement_signal,
    leaf_profile_view,
    maybe_auto_widen,
    questions_equivalent,
    record_search_outcome,
    record_search_shortlist,
    reset_search_cursor,
    resolve_hotel_reference,
    resolve_hotel_reference_strict,
    resolve_hotel_references,
    resolve_shortlist_ordinal,
    search_context_line,
    select_cheapest_hotel,
)


class TestResolveShortlistOrdinal:
    SHORTLIST = [
        {"hotel_id": 111, "name": "Cadillac Hotel & Beach Club"},
        {"hotel_id": 222, "name": "Wyndham Garden Miami"},
        {"hotel_id": 333, "name": "Regency Miami Airport"},
    ]

    def _pick(self, text):
        hit = resolve_shortlist_ordinal(text, self.SHORTLIST)
        return hit["hotel_id"] if hit else None

    def test_bare_digit_picks_by_position(self):
        assert self._pick("1") == 111
        assert self._pick("2") == 222
        assert self._pick("3") == 333

    def test_common_prefixes_and_whitespace(self):
        assert self._pick(" #2 ") == 222
        assert self._pick("n°3") == 333
        assert self._pick("option 1") == 111

    def test_ordinal_words_both_languages(self):
        assert self._pick("the first") == 111
        assert self._pick("premier") == 111
        assert self._pick("deuxième") == 222
        assert self._pick("third") == 333

    def test_out_of_range_is_none(self):
        assert self._pick("0") is None
        assert self._pick("4") is None
        assert self._pick("9") is None

    def test_date_like_le_number_is_not_a_pick(self):
        # "le 2"/"le 28" is a French date refinement, never a position pick.
        assert self._pick("le 2") is None
        assert self._pick("le 28") is None

    def test_non_ordinal_messages_are_none(self):
        assert self._pick("cheaper") is None
        assert self._pick("1 star hotel please") is None
        assert self._pick("book the Cadillac") is None

    def test_no_shortlist_is_none(self):
        assert resolve_shortlist_ordinal("1", None) is None
        assert resolve_shortlist_ordinal("1", []) is None


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


# ── "Other options" pagination signal (S-G5) ────────────────────────────────


class TestMoreOptionsSignal:
    def test_matches_common_phrasings(self):
        for text in (
            "other options?", "any other options", "show me more",
            "more options please", "anything else?", "what else do you have",
            "any other ones", "autres options", "autre chose",
            "d'autres hôtels", "encore des hôtels",
        ):
            assert is_more_options_signal(text), text

    def test_does_not_match_an_unrelated_message(self):
        assert not is_more_options_signal("hotel in Paris tomorrow")
        assert not is_more_options_signal("cheaper please")

    def test_empty_message_never_matches(self):
        assert not is_more_options_signal("")
        assert not is_more_options_signal(None)

    def test_routes_to_search_via_refinement_signal_with_prior_context(self):
        profile = SessionProfile(city="Paris")
        assert is_search_refinement_signal("other options", profile)
        assert is_search_refinement_signal("autres options", profile)

    def test_no_prior_context_is_not_a_refinement_signal(self):
        assert not is_search_refinement_signal("other options", SessionProfile())

    def test_naming_a_shortlist_hotel_is_unaffected(self):
        # "other options" itself never names a hotel — sanity check it doesn't
        # accidentally disable the booking/details exclusion for a real pick.
        profile = SessionProfile(
            city="Paris", last_results=[{"hotel_id": 1, "name": "Villa Paris Orly"}]
        )
        assert not is_search_refinement_signal("book Villa Paris Orly", profile)


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

    def test_keeps_the_offer_identity_the_card_was_priced_on(self):
        """S-CX5: without this, a booking turn can only re-derive an offer from
        a fresh lookup — which is how a €87/11:00-19:00/tomorrow card produced
        a €90/17:00-23:00/today link (prod session 2026-07-27)."""
        profile = SessionProfile()
        record_search_shortlist(
            profile,
            [
                {
                    "hotel_id": 22293,
                    "name": "Hôtel Mercure Paris La Défense",
                    "offer_id": "1836debf-aaee-11ee-99ec-0272db9e0c27",
                    "offer_date": "2026-07-28",
                    "price": "€87.00",
                    "price_eur_cents": 8700,
                    "timeslots": [{"start": "11:00", "end": "19:00"}],
                }
            ],
        )
        assert profile.last_results == [
            {
                "hotel_id": 22293,
                "name": "Hôtel Mercure Paris La Défense",
                "offer_id": "1836debf-aaee-11ee-99ec-0272db9e0c27",
                "offer_date": "2026-07-28",
                "price": "€87.00",
                "price_eur_cents": 8700,
                "start_time": "11:00",
                "end_time": "19:00",
            }
        ]

    def test_a_card_without_an_offer_stores_no_null_offer_keys(self):
        """Absent means absent: a None `offer_id` would read as data downstream
        and send the booking step to an offer that doesn't exist."""
        profile = SessionProfile()
        record_search_shortlist(profile, [{"hotel_id": 1, "name": "Hotel A", "offer_id": None}])
        assert profile.last_results == [{"hotel_id": 1, "name": "Hotel A"}]


class TestSelectCheapestHotel:
    """S-CX5, the DECISION half: triage's `pick` field says the user asked for
    the cheapest (comprehension, LLM); this picks WHICH one, from the prices on
    screen. MCP has no price ordering to delegate to."""

    SHOWN = [
        {"hotel_id": 1, "name": "Mercure La Défense", "price_eur_cents": 8700},
        {"hotel_id": 2, "name": "Drawing House", "price_eur_cents": 8100},
        {"hotel_id": 3, "name": "Pullman Bercy", "price_eur_cents": 11200},
    ]

    def test_picks_the_cheapest_of_the_shortlist(self):
        hit = select_cheapest_hotel(self.SHOWN)
        assert hit is not None and hit["hotel_id"] == 2  # €81, not the first shown

    def test_nothing_on_screen_resolves_nothing(self):
        assert select_cheapest_hotel(None) is None
        assert select_cheapest_hotel([]) is None

    def test_a_shortlist_without_prices_resolves_nothing(self):
        """Cards predating the numeric price (or a source that carries none)
        must not be ranked on a guess — the turn falls through to its normal
        routing instead."""
        assert select_cheapest_hotel([{"hotel_id": 1, "name": "Mercure"}]) is None

    def test_entries_without_a_price_are_skipped_not_guessed(self):
        mixed = [{"hotel_id": 9, "name": "Unknown price"}, *self.SHOWN]
        hit = select_cheapest_hotel(mixed)
        assert hit is not None and hit["hotel_id"] == 2

    def test_it_never_reads_the_message(self):
        """The signature is the guarantee: understanding lives in triage, this
        only decides. A regression that re-adds text parsing breaks here."""
        import inspect

        assert list(inspect.signature(select_cheapest_hotel).parameters) == ["last_results"]


class TestSearchCursorLifecycle:
    def test_a_refined_search_restarts_at_page_one(self):
        """S-CX5: the cursor only ever reset on a city change, so one "other
        options" turn kept the already-shown hotels hidden from every later
        search in that city — including the one meant to rank them by price."""
        profile = SessionProfile(city="Paris")
        advance_search_cursor(profile)
        advance_search_cursor(profile)
        assert profile.search_cursor == 2
        reset_search_cursor(profile)
        assert profile.search_cursor == 0

    def test_resetting_keeps_the_shown_ids_for_later_pagination(self):
        """The exclusion set stays accumulated — it is simply not consulted at
        page 1. Clearing it would break the next real "other options" turn."""
        profile = SessionProfile(city="Paris", shown_hotel_ids=[1, 2, 3], search_cursor=1)
        reset_search_cursor(profile)
        assert profile.shown_hotel_ids == [1, 2, 3]


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

    def test_explicit_confirmation_phrases_are_signals(self):
        """Prod 2026-07-28: R9 asks « Confirmez-vous cette réservation ? » and
        the natural echoes fell through to triage → the greeting template —
        the confirmation could never be typed, only clicked."""
        profile = SessionProfile(pending_booking={"hotel_id": 1})
        for message in (
            "oui je confirme",
            "je confirme",
            "Je confirme la réservation",
            "c'est confirmé",
            "je valide",
            "yes I confirm",
            "confirmed",
            "oui je veux réserver",
            "vas-y",
        ):
            assert is_booking_confirmation_signal(message, profile), message

    def test_refusals_and_questions_never_signal_even_with_confirm_verbs(self):
        """A false positive here would GENERATE THE LINK (user_confirmed feeds
        the R9 gate) — negations and questions must always lose."""
        profile = SessionProfile(pending_booking={"hotel_id": 1})
        for message in (
            "non je ne confirme pas",
            "je ne confirme pas",
            "non",
            "annule la réservation",
            "cancel the booking",
            "attends, pas encore",
            "plutôt un autre hôtel",
            "et si je confirme ?",
            "je confirme quoi ?",
        ):
            assert not is_booking_confirmation_signal(message, profile), message

    def test_explicit_confirmation_without_pending_booking_is_not_a_signal(self):
        assert not is_booking_confirmation_signal("je confirme", SessionProfile())


# ── S-G1 (2026-07-23): profile v2 schema + typed-ops reducer ────────────────


class TestProfileV2Schema:
    def test_new_fields_default_to_none_or_empty(self):
        profile = SessionProfile()
        assert profile.named_hotel is None
        assert profile.zone is None
        assert profile.metro is None
        assert profile.date is None
        assert profile.date_reference is None
        assert profile.currency is None
        assert profile.locale is None
        assert profile.domain is None
        assert profile.search_anchor is None
        assert profile.distance_origin is None
        assert profile.shown_hotel_ids == []
        assert profile.search_cursor == 0
        assert profile.client_timezone is None

    def test_round_trips_with_all_v2_fields_populated(self):
        profile = SessionProfile(
            city="Paris",
            named_hotel={"hotel_id": 1, "name": "A", "source": "shortlist"},
            zone="Le Marais",
            metro="Chatelet",
            date="2026-07-24",
            date_reference={
                "expression": "demain", "resolved_from": "2026-07-23", "client_tz": "Europe/Paris",
            },
            currency="EUR",
            locale="fr-FR",
            domain="dayuse.com",
            search_anchor={"type": "gps", "lat": 48.8, "lon": 2.3, "label": "here", "set_at_turn": 1},
            distance_origin={"latitude": 48.8, "longitude": 2.3, "label": "here", "type": "gps"},
            shown_hotel_ids=[1, 2, 3],
            search_cursor=2,
            client_timezone="Europe/Paris",
        )
        restored = SessionProfile.from_dict(profile.to_dict())
        assert restored == profile

    def test_to_dict_stamps_schema_version(self):
        assert SessionProfile().to_dict()["schema_version"] == PROFILE_SCHEMA_VERSION

    def test_from_dict_tolerates_an_unknown_schema_version(self):
        restored = SessionProfile.from_dict({"city": "Lyon", "schema_version": "0.9-unknown"})
        assert restored.city == "Lyon"

    def test_apply_profile_delta_tolerates_a_schema_version_key(self):
        profile = SessionProfile(city="Lyon")
        apply_profile_delta(profile, {"schema_version": "2.0", "budget_max": 50}, "50")
        assert profile.budget_max == 50.0


class TestFlatDeltaRetroCompat:
    def test_flat_legacy_delta_still_works_unchanged(self):
        """The leaf doesn't emit typed ops yet (migrates in S-G5/S-G6) — a
        plain 'key: value' delta must behave exactly as before."""
        profile = SessionProfile()
        apply_profile_delta(
            profile,
            {"city": "New York", "budget_max": 180, "amenities": ["pool"], "language": "en"},
            "180",
        )
        assert profile.city == "New York"
        assert profile.budget_max == 180.0
        assert profile.budget_request_source == BUDGET_SOURCE_EXPLICIT
        assert profile.amenities == ["pool"]
        assert profile.language == "en"

    def test_mixed_flat_and_typed_ops_in_the_same_delta(self):
        profile = SessionProfile(city="Miami", zone="Miami")
        apply_profile_delta(
            profile, {"budget_max": 90, "zone": {"op": "clear"}}, "90, forget the zone",
        )
        assert profile.budget_max == 90.0
        assert profile.zone is None

    def test_client_timezone_applies_and_carries_over(self):
        # S-G6: facade native-context intake sends it fresh every request, but
        # apply_profile_delta must still carry it over when a turn's delta
        # simply doesn't mention it (e.g. a leaf-only delta).
        profile = SessionProfile()
        apply_profile_delta(profile, {"client_timezone": "Europe/Paris"}, "")
        assert profile.client_timezone == "Europe/Paris"
        apply_profile_delta(profile, {"city": "Lyon"}, "Lyon")
        assert profile.client_timezone == "Europe/Paris"  # untouched, absent = carryover


class TestTypedPatchOpsGeneric:
    def test_absent_slot_is_always_carryover(self):
        origin = {"latitude": 48.8, "longitude": 2.3, "label": "Paris", "type": "city_centroid"}
        profile = SessionProfile(
            currency="EUR", locale="fr-FR", domain="dayuse.com", distance_origin=origin,
        )
        apply_profile_delta(profile, {"budget_max": 50}, "50")
        assert profile.currency == "EUR"
        assert profile.locale == "fr-FR"
        assert profile.domain == "dayuse.com"
        assert profile.distance_origin == origin

    def test_typed_set_op_applies_the_value(self):
        profile = SessionProfile()
        apply_profile_delta(profile, {"currency": {"op": "set", "value": "USD"}}, "in dollars please")
        assert profile.currency == "USD"

    def test_typed_clear_op_resets_to_the_slot_default(self):
        profile = SessionProfile(currency="USD", search_cursor=3, shown_hotel_ids=[1, 2])
        apply_profile_delta(
            profile,
            {
                "currency": {"op": "clear"},
                "search_cursor": {"op": "clear"},
                "shown_hotel_ids": {"op": "clear"},
            },
            "reset",
        )
        assert profile.currency is None
        assert profile.search_cursor == 0
        assert profile.shown_hotel_ids == []

    def test_date_and_date_reference_set_then_carryover(self):
        profile = SessionProfile()
        apply_profile_delta(
            profile,
            {
                "date": "2026-07-24",
                "date_reference": {
                    "expression": "demain", "resolved_from": "2026-07-23", "client_tz": "Europe/Paris",
                },
            },
            "demain",
        )
        assert profile.date == "2026-07-24"
        assert profile.date_reference["expression"] == "demain"
        apply_profile_delta(profile, {"budget_max": 100}, "100")
        assert profile.date == "2026-07-24"
        assert profile.date_reference["expression"] == "demain"

    def test_search_anchor_set_and_clear(self):
        profile = SessionProfile()
        apply_profile_delta(
            profile,
            {
                "search_anchor": {
                    "op": "set",
                    "value": {"type": "gps", "lat": 48.8, "lon": 2.3, "label": "here", "set_at_turn": 1},
                },
            },
            "near me",
        )
        assert profile.search_anchor["type"] == "gps"
        apply_profile_delta(profile, {"search_anchor": {"op": "clear"}}, "forget my location")
        assert profile.search_anchor is None


class TestNamedHotelSetClear:
    def test_named_hotel_flat_set(self):
        profile = SessionProfile()
        apply_profile_delta(
            profile,
            {"named_hotel": {"hotel_id": 42, "name": "Villa Paris Orly", "source": "shortlist"}},
            "book Villa Paris Orly",
        )
        assert profile.named_hotel == {"hotel_id": 42, "name": "Villa Paris Orly", "source": "shortlist"}

    def test_named_hotel_typed_set_op(self):
        profile = SessionProfile()
        apply_profile_delta(
            profile,
            {"named_hotel": {"op": "set", "value": {"hotel_id": 7, "name": "Ibis", "source": "mcp"}}},
            "book the Ibis",
        )
        assert profile.named_hotel == {"hotel_id": 7, "name": "Ibis", "source": "mcp"}

    def test_named_hotel_typed_clear_op(self):
        profile = SessionProfile(named_hotel={"hotel_id": 7, "name": "Ibis", "source": "mcp"})
        apply_profile_delta(profile, {"named_hotel": {"op": "clear"}}, "never mind, show me options again")
        assert profile.named_hotel is None

    def test_named_hotel_absent_is_carryover(self):
        profile = SessionProfile(named_hotel={"hotel_id": 7, "name": "Ibis", "source": "mcp"})
        apply_profile_delta(profile, {"budget_max": 90}, "90")
        assert profile.named_hotel == {"hotel_id": 7, "name": "Ibis", "source": "mcp"}


class TestCityChangeInvalidationV2:
    def test_city_change_clears_zone_metro_and_search_anchor(self):
        profile = SessionProfile(
            city="Miami", zone="Miami", metro="Miami-Dade",
            search_anchor={"type": "gps", "lat": 1.0, "lon": 2.0, "label": "here", "set_at_turn": 1},
        )
        apply_profile_delta(profile, {"city": "Paris"}, "actually Paris")
        assert profile.zone is None
        assert profile.metro is None
        assert profile.search_anchor is None

    def test_city_change_resets_shown_hotel_ids_and_search_cursor(self):
        profile = SessionProfile(city="Miami", shown_hotel_ids=[1, 2, 3], search_cursor=2)
        apply_profile_delta(profile, {"city": "Paris"}, "actually Paris")
        assert profile.shown_hotel_ids == []
        assert profile.search_cursor == 0

    def test_zone_change_alone_does_not_reset_shown_hotel_ids_or_cursor(self):
        profile = SessionProfile(city="Miami", zone="Miami", shown_hotel_ids=[1, 2], search_cursor=1)
        apply_profile_delta(profile, {"zone": "Fort Lauderdale"}, "Fort Lauderdale instead")
        assert profile.shown_hotel_ids == [1, 2]
        assert profile.search_cursor == 1

    def test_fresh_zone_in_the_same_delta_survives_the_city_change(self):
        profile = SessionProfile(city="Miami", zone="Miami")
        apply_profile_delta(profile, {"city": "Paris", "zone": "Le Marais"}, "paris le marais")
        assert profile.zone == "Le Marais"


# ── the 3 eval-pack zone-change variants (multiturn-zone_change_0/1/2,
# multiturn-carry_same_time_0/1/2): a suburb/zone change must never drop the
# date/timeslot/budget/amenities already collected (audit case 0/3) ────────


class TestZoneChangeConservation:
    def test_zone_change_preserves_budget_timeslot_amenities_and_date(self):
        profile = SessionProfile(
            city="Miami", budget_max=200.0, budget_request_source=BUDGET_SOURCE_EXPLICIT,
            timeslot_start="14:00", timeslot_end="18:00", timeslot_mode="range",
            amenities=["pool"], date="2026-07-24", zone="Miami",
        )
        apply_profile_delta(profile, {"zone": "Fort Lauderdale"}, "Same budget in Fort Lauderdale")
        assert profile.zone == "Fort Lauderdale"
        assert profile.city == "Miami"
        assert profile.budget_max == 200.0
        assert profile.timeslot_start == "14:00" and profile.timeslot_end == "18:00"
        assert profile.amenities == ["pool"]
        assert profile.date == "2026-07-24"

    def test_repeated_zone_changes_keep_conserving_context(self):
        profile = SessionProfile(city="Miami", budget_max=200.0, zone="Miami")
        apply_profile_delta(profile, {"zone": "Fort Lauderdale"}, "Same budget in Fort Lauderdale")
        apply_profile_delta(profile, {"zone": "Boca Raton"}, "Actually Boca Raton instead")
        assert profile.zone == "Boca Raton"
        assert profile.budget_max == 200.0

    def test_zone_change_preserves_date_reference_and_timeslot_start(self):
        profile = SessionProfile(
            city="Boca Raton", timeslot_start="11:00",
            date_reference={
                "expression": "tomorrow", "resolved_from": "2026-07-10", "client_tz": "America/New_York",
            },
        )
        apply_profile_delta(
            profile, {"zone": "Fort Lauderdale"}, "Use the same time for tomorrow in Fort Lauderdale",
        )
        assert profile.zone == "Fort Lauderdale"
        assert profile.timeslot_start == "11:00"
        assert profile.date_reference["expression"] == "tomorrow"


class TestShownHotelIdsAccumulation:
    def test_accumulates_ids_across_searches(self):
        profile = SessionProfile()
        record_search_shortlist(profile, [{"hotel_id": 1, "name": "A"}, {"hotel_id": 2, "name": "B"}])
        record_search_shortlist(profile, [{"hotel_id": 3, "name": "C"}])
        assert profile.shown_hotel_ids == [1, 2, 3]

    def test_re_shown_hotel_moves_to_the_end_without_duplicating(self):
        profile = SessionProfile()
        record_search_shortlist(profile, [{"hotel_id": 1, "name": "A"}, {"hotel_id": 2, "name": "B"}])
        record_search_shortlist(profile, [{"hotel_id": 1, "name": "A"}])
        assert profile.shown_hotel_ids == [2, 1]

    def test_capped_at_25_dropping_the_oldest(self):
        profile = SessionProfile()
        for i in range(30):
            record_search_shortlist(profile, [{"hotel_id": i, "name": f"Hotel {i}"}])
        assert len(profile.shown_hotel_ids) == MAX_SHOWN_HOTEL_IDS == 25
        assert profile.shown_hotel_ids == list(range(5, 30))

    def test_empty_results_do_not_touch_shown_hotel_ids(self):
        profile = SessionProfile(shown_hotel_ids=[1, 2])
        record_search_shortlist(profile, [])
        record_search_shortlist(profile, None)
        assert profile.shown_hotel_ids == [1, 2]


class TestSearchCursorAdvance:
    def test_advance_increments_the_cursor(self):
        profile = SessionProfile(search_cursor=0)
        advance_search_cursor(profile)
        assert profile.search_cursor == 1
        advance_search_cursor(profile)
        assert profile.search_cursor == 2

    def test_advance_touches_no_other_field(self):
        profile = SessionProfile(
            city="Paris", budget_max=100.0, zone="Le Marais", amenities=["pool"],
            shown_hotel_ids=[1, 2], search_cursor=3,
        )
        advance_search_cursor(profile)
        assert profile.city == "Paris"
        assert profile.budget_max == 100.0
        assert profile.zone == "Le Marais"
        assert profile.amenities == ["pool"]
        assert profile.shown_hotel_ids == [1, 2]
        assert profile.search_cursor == 4


class TestProfileOpsRgpdMetric:
    def test_logs_set_and_clear_counts_with_slot_names_never_values(self, caplog):
        profile = SessionProfile(city="Miami", zone="Miami", currency="USD")
        with caplog.at_level(logging.INFO):
            apply_profile_delta(
                profile,
                {"budget_max": 150, "zone": {"op": "clear"}, "currency": {"op": "clear"}},
                "150, forget the zone and currency",
            )
        lines = [r.getMessage() for r in caplog.records if "profile_ops" in r.getMessage()]
        assert lines, "expected a profile_ops metric line"
        line = lines[0]
        assert "set=1" in line and "clear=2" in line
        assert "budget_max" in line and "zone" in line and "currency" in line
        assert "150" not in line
        assert "Miami" not in line
        assert "USD" not in line

    def test_no_op_delta_logs_nothing(self, caplog):
        profile = SessionProfile()
        with caplog.at_level(logging.INFO):
            apply_profile_delta(profile, {}, "hello")
        lines = [r.getMessage() for r in caplog.records if "profile_ops" in r.getMessage()]
        assert lines == []


class TestLeafProfileView:
    """Latency audit 2026-07-28 — the A2A copy of the profile is slimmed: the
    whole profile_in lands verbatim in the leaf's LLM prompt, so display-only
    shortlist fields and concierge-internal turn state are pure prompt-token
    cost (measured ~+535 tokens per leaf call for a 5-hotel S-CX5 shortlist).
    The full profile (Redis, booking card, picks) is NOT touched."""

    def _fat_profile(self) -> SessionProfile:
        profile = SessionProfile()
        record_search_shortlist(
            profile,
            [
                {
                    "hotel_id": 42,
                    "name": "Villa Paris Orly",
                    "price": "€54.00",
                    "price_eur_cents": 5400,
                    "offer_id": "uuid-1",
                    "offer_date": "2026-07-29",
                    "image_urls": ["https://cdn.example/photo-42.jpg"],
                    "url": "https://www.dayuse.fr/hotels/france/villa-paris-orly",
                    "city": "Paris",
                    "rating": 4.7,
                    "rating_count": 12,
                    "stars": 4,
                    "timeslots": [{"start": "10:00", "end": "17:00"}],
                }
            ],
        )
        profile.pending_booking = {"hotel_id": 42, "offer_id": "uuid-1"}
        profile.last_clarifying_question = "Quelle ville ?"
        profile.last_suggestions = ["Paris", "Lyon"]
        profile.city = "Paris"
        profile.budget_max = 150.0
        profile.search_cursor = 5
        profile.shown_hotel_ids = [42, 43]
        return profile

    def test_shortlist_shrinks_to_identity_only(self):
        view = leaf_profile_view(self._fat_profile())
        assert view["last_results"] == [{"hotel_id": 42, "name": "Villa Paris Orly"}]

    def test_concierge_only_keys_never_travel(self):
        view = leaf_profile_view(self._fat_profile())
        for key in (
            "pending_booking",
            "last_suggestions",
            "last_clarifying_question",
            "amenity_claim_corrections",
            "auto_widen_disclosure",
            "named_hotel",
            "distance_origin",
            "picked_hotel_id",
        ):
            assert key not in view

    def test_every_leaf_consumed_slot_is_kept(self):
        # The definitive read set of the leaf packages (geocode_tool,
        # datetime_resolver, equipment_ids, response_bridge), 2026-07-28.
        view = leaf_profile_view(self._fat_profile())
        for key in (
            "city", "zone", "metro", "state_anchor", "country_anchor",
            "search_anchor", "locale", "language", "client_timezone", "date",
            "timeslot_start", "amenities", "search_cursor", "shown_hotel_ids",
            "budget_max", "timeslot_end", "timeslot", "schema_version",
        ):
            assert key in view, f"leaf-consumed or model-visible slot {key!r} missing"
        assert view["search_cursor"] == 5
        assert view["shown_hotel_ids"] == [42, 43]

    def test_the_profile_itself_keeps_the_full_shortlist(self):
        profile = self._fat_profile()
        leaf_profile_view(profile)
        # The view is a copy: the booking card's offer identity must survive.
        assert profile.last_results[0]["offer_id"] == "uuid-1"
        assert profile.last_results[0]["image_urls"] == ["https://cdn.example/photo-42.jpg"]
        assert profile.pending_booking == {"hotel_id": 42, "offer_id": "uuid-1"}
