"""Written-out dates (QA 2026-09-08 n°2): prod replies leaked the leaf's ISO
search date ("Pour demain (2026-09-24) à Paris…"). The prompt now gets the
date in words; `humanize_iso_dates` backstops whatever the model still emits."""
from __future__ import annotations

from datetime import date

import pytest

from b2c_concierge.date_format import format_date_human, humanize_iso_dates


class TestFormatDateHuman:
    @pytest.mark.parametrize(
        ("language", "expected"),
        [
            ("fr", "jeudi 24 septembre 2026"),
            ("en", "Thursday, September 24, 2026"),
            ("es", "jueves 24 de septiembre de 2026"),
            ("it", "giovedì 24 settembre 2026"),
            ("de", "Donnerstag, 24. September 2026"),
            ("pt", "quinta-feira, 24 de setembro de 2026"),
            ("nl", "donderdag 24 september 2026"),
        ],
    )
    def test_all_seven_languages(self, language, expected):
        assert format_date_human("2026-09-24", language) == expected

    def test_french_first_of_the_month_is_1er(self):
        assert format_date_human("2026-09-01", "fr") == "mardi 1er septembre 2026"

    def test_accepts_a_date_object(self):
        assert format_date_human(date(2026, 9, 8), "en") == "Tuesday, September 8, 2026"

    def test_unknown_language_falls_back_to_english(self):
        assert format_date_human("2026-09-24", "ja") == "Thursday, September 24, 2026"

    def test_unparseable_value_is_returned_unchanged(self):
        assert format_date_human("demain", "fr") == "demain"
        assert format_date_human("2026-13-40", "fr") == "2026-13-40"


class TestHumanizeIsoDates:
    def test_the_prod_reply_is_rewritten(self):
        text = "Pour demain (2026-09-24) à Paris avec piscine, tu as 5 offres."
        corrected, replaced = humanize_iso_dates(text, "fr")
        assert corrected == (
            "Pour demain (jeudi 24 septembre 2026) à Paris avec piscine, tu as 5 offres."
        )
        assert replaced == 1

    def test_dates_inside_urls_are_left_untouched(self):
        url = "https://www.dayuse.com/hotels/france/drawing-house?date=2026-09-24"
        text = f"Réserve ici : {url} pour le 2026-09-24."
        corrected, replaced = humanize_iso_dates(text, "fr")
        assert url in corrected
        assert corrected.endswith("pour le jeudi 24 septembre 2026.")
        assert replaced == 1

    def test_text_without_iso_date_is_unchanged(self):
        text = "Here are 5 hotels in Paris for tomorrow."
        assert humanize_iso_dates(text, "en") == (text, 0)

    def test_invalid_calendar_date_is_not_rewritten(self):
        assert humanize_iso_dates("ref 2026-13-40", "en") == ("ref 2026-13-40", 0)

    def test_longer_digit_runs_are_not_mistaken_for_dates(self):
        text = "booking 12026-09-24-7"
        assert humanize_iso_dates(text, "en") == (text, 0)

    def test_empty_text(self):
        assert humanize_iso_dates("", "fr") == ("", 0)
