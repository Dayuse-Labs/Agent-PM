"""templates.py — direct unit coverage for the booking-summary time display,
and (UX2, 2026-08-27) the 7-language coverage/fallback/non-regression DoD.

S-G6: `_format_time_slot`/`booking_offer_summary_response` used to force
":00" on every offer regardless of its real minutes (`start_hour`/`end_hour`
ints) — now takes already-formatted "HH:MM" strings.
"""
from __future__ import annotations

from collections.abc import Callable

import pytest
from b2c_common.clarification import Clarification

from b2c_concierge import templates
from b2c_concierge.triage import LANGUAGES


class TestFormatTimeSlot:
    def test_formats_hh_mm_strings_with_real_minutes(self):
        assert templates._format_time_slot("07:30", "13:30") == "07:30–13:30"

    def test_none_on_either_side_yields_none(self):
        assert templates._format_time_slot(None, "13:30") is None
        assert templates._format_time_slot("07:30", None) is None
        assert templates._format_time_slot(None, None) is None


class TestBookingOfferSummaryResponse:
    def test_includes_the_real_minute_precise_slot(self):
        text = templates.booking_offer_summary_response(
            hotel_name="Villa Paris Orly", date="2026-07-20",
            start_time="07:30", end_time="13:30", price="€54.00", language="en",
        )
        assert "07:30" in text and "13:30" in text
        assert "07:30–13:30" in text

    def test_omits_slot_entirely_when_offer_has_no_time(self):
        text = templates.booking_offer_summary_response(
            hotel_name="Villa Paris Orly", date="2026-07-20",
            start_time=None, end_time=None, price="€54.00", language="fr",
        )
        assert "créneau" not in text


# --- UX2 (2026-08-27): DoD — every templates.py function has a real table
# entry for all 7 languages, none silently falling back to English, plus the
# fallback itself stays reachable and fr/en stay byte-identical to before. ---

_SHORTLIST = [{"name": "Villa Paris Orly"}, {"name": "Ibis Lyon Gare"}]
_CITY_NEEDED = Clarification(kind="city_needed", subject="Gare du Nord")
_HOMONYM = Clarification.model_validate({
    "kind": "homonym",
    "subject": "Victoria",
    "options": [{"label": "Victoria (Texas, US)", "city": "Victoria", "country_code": "US"}],
})

# One representative call per templates.py function/branch — the fixed
# (non-language) arguments are irrelevant to the assertion, only `language`
# varies. label -> callable(language) -> str.
_CASES: dict[str, Callable[[str | None], str]] = {
    "ack_response": lambda lang: templates.ack_response(lang),
    "inline_unresolved:get_hotel_details": lambda lang: templates.inline_unresolved_response(
        "get_hotel_details", lang
    ),
    "inline_unresolved:compare_hotels": lambda lang: templates.inline_unresolved_response(
        "compare_hotels", lang
    ),
    "inline_unresolved:generate_booking_link": lambda lang: templates.inline_unresolved_response(
        "generate_booking_link", lang
    ),
    "booking_offer_summary": lambda lang: templates.booking_offer_summary_response(
        hotel_name="Villa Paris Orly", date="2026-07-20",
        start_time="07:30", end_time="13:30", price="€54.00", language=lang,
    ),
    "booking_link": lambda lang: templates.booking_link_response(
        hotel_name="Villa Paris Orly", url="https://dayuse.com/x", language=lang,
    ),
    "booking_needs_selection:list": lambda lang: templates.booking_needs_selection_response(
        _SHORTLIST, None, lang
    ),
    "booking_needs_selection:no_offer": lambda lang: templates.booking_needs_selection_response(
        None, "no bookable offer", lang
    ),
    "booking_needs_selection:no_list": lambda lang: templates.booking_needs_selection_response(
        None, None, lang
    ),
    "search_exhausted:budget": lambda lang: templates.search_exhausted_response(
        lang, "Paris", reason="budget"
    ),
    "search_exhausted:pagination": lambda lang: templates.search_exhausted_response(
        lang, "Paris", reason="pagination"
    ),
    "service_degraded": lambda lang: templates.service_degraded_response(lang),
    "leaf_degraded:search": lambda lang: templates.leaf_degraded_response("search", lang, "Paris"),
    "leaf_degraded:faq": lambda lang: templates.leaf_degraded_response("faq", lang, "Paris"),
    "named_hotel_ambiguous_response": lambda lang: templates.named_hotel_ambiguous_response(
        "Leonardo Royal", [{"name": "Leonardo Royal Hotel London City", "city": "london"}], lang
    ),
    "named_hotel_not_offered_notice": lambda lang: templates.named_hotel_not_offered_notice(
        "St Paul's Hotel", "7", lang
    ),
    "clarification:city_needed": lambda lang: templates.clarification_response(
        _CITY_NEEDED, lang, 1
    ),
    "clarification:city_needed_again": lambda lang: templates.clarification_response(
        _CITY_NEEDED, lang, 2
    ),
    "clarification:homonym": lambda lang: templates.clarification_response(_HOMONYM, lang, 1),
    "clarification:homonym_again": lambda lang: templates.clarification_response(
        _HOMONYM, lang, 2
    ),
    "clarification:give_up": lambda lang: templates.clarification_response(_HOMONYM, lang, 3),
}

_NON_ENGLISH_LANGUAGES = [lang for lang in LANGUAGES if lang != "en"]


class TestSevenLanguageCoverage:
    """DoD #1: every language differs from the English string — a language
    that quietly reused the EN table entry would pass every other check here
    (valid string, no crash) while shipping franglais."""

    @pytest.mark.parametrize("case", _CASES)
    @pytest.mark.parametrize("language", _NON_ENGLISH_LANGUAGES)
    def test_language_differs_from_english(self, case, language):
        en_text = _CASES[case]("en")
        text = _CASES[case](language)
        assert text != en_text, f"{case}[{language}] matches the English string"

    @pytest.mark.parametrize("case", _CASES)
    def test_all_seven_languages_produce_non_empty_text(self, case):
        for language in LANGUAGES:
            assert _CASES[case](language)


class TestFallbackToEnglish:
    """DoD #2: a language triage could never actually emit (recognized set is
    closed) still degrades cleanly to English rather than raising, via the
    same `.get(language, table["en"])` every table uses."""

    @pytest.mark.parametrize("case", _CASES)
    @pytest.mark.parametrize("language", ["ja", "xx", "", None])
    def test_unrecognized_language_falls_back_to_english(self, case, language):
        assert _CASES[case](language) == _CASES[case]("en")


class TestFrenchAndEnglishUnchanged:
    """DoD #3: fr/en are the iso-contract with agent-usa on its two biggest
    markets — the widened tables must not have altered a single existing
    string. Exact string locks, not substring checks."""

    def test_ack_response(self):
        assert templates.ack_response("fr") == (
            "Bonjour ! Je suis le concierge Dayuse : dites-moi la ville (et la date si vous "
            "l'avez) et je vous trouve un hôtel en journée. Vous pouvez aussi me poser une "
            "question sur le fonctionnement de Dayuse."
        )
        assert templates.ack_response("en") == (
            "Hello! I'm the Dayuse concierge: tell me the city (and the date if you have one) "
            "and I'll find you a day-use hotel. You can also ask me how Dayuse works."
        )

    def test_booking_link_response(self):
        assert templates.booking_link_response(
            hotel_name="Villa Paris Orly", url="https://dayuse.com/x", language="fr"
        ) == (
            "Voici votre lien de réservation pour Villa Paris Orly — il reste à finaliser "
            "sur la page Dayuse : https://dayuse.com/x"
        )
        assert templates.booking_link_response(
            hotel_name="Villa Paris Orly", url="https://dayuse.com/x", language="en"
        ) == (
            "Here's your booking link for Villa Paris Orly — you'll finalize on the Dayuse "
            "page: https://dayuse.com/x"
        )

    def test_search_exhausted_response(self):
        assert templates.search_exhausted_response("fr", "Paris", reason="budget") == (
            "Même après avoir élargi le budget, je ne trouve toujours rien à Paris. "
            "Essayez une autre ville, ou dites-moi ce que je peux ajuster (date, quartier)."
        )
        assert templates.search_exhausted_response("en", "Paris", reason="pagination") == (
            "You've now seen every hotel matching your criteria in Paris. Want me to "
            "widen the budget, the area, or drop a filter?"
        )

    def test_leaf_degraded_response(self):
        assert templates.leaf_degraded_response("search", "fr", "Paris") == (
            "Je n'arrive pas à joindre la recherche d'hôtels à Paris pour le moment, et je "
            "préfère ne rien inventer. Pouvez-vous réessayer dans un instant ?"
        )
        assert templates.leaf_degraded_response("faq", "en") == (
            "I can't look up the Dayuse conditions right now, and I'd rather not make "
            "anything up. Could you try again in a moment?"
        )


class TestNamedHotel:
    """mcp-dayuse#7."""

    def test_the_ambiguity_lists_each_candidate_with_its_city(self):
        text = templates.named_hotel_ambiguous_response(
            "Leonardo Royal",
            [
                {"name": "Leonardo Royal Hotel London City", "city": "london"},
                {"name": "Hôtel X", "city": "paris-10"},
            ],
            "fr",
        )
        assert text == (
            "Plusieurs hôtels correspondent à « Leonardo Royal » : Leonardo Royal Hotel "
            "London City (London), Hôtel X (Paris 10). Lequel souhaitez-vous ?"
        )

    def test_not_offered_names_the_hotel_and_the_day(self):
        assert templates.named_hotel_not_offered_notice(
            "St Paul's Hotel", "mercredi 7 octobre 2026", "fr"
        ) == (
            "St Paul's Hotel n'a pas d'offre disponible le mercredi 7 octobre 2026 : "
            "voici les hôtels les plus proches."
        )
