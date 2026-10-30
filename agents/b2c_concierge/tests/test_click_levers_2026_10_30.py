"""Concierge side of the click levers (prod after #175, 2026-10-30)."""
from __future__ import annotations

import pytest

from b2c_common.clarification import Clarification
from b2c_concierge import templates


@pytest.mark.parametrize("language", ["fr", "en", "es", "it", "de", "pt", "nl"])
def test_a_spot_in_a_known_city_is_asked_about_as_a_spot(language):
    """« Tsim Sha Tsui », Hong Kong: not « which city or country? » but a
    nearby place in that city."""
    text = templates.clarification_response(
        Clarification(kind="unresolved", subject="Tsim Sha Tsui", city="Hong Kong"), language
    )
    assert "Tsim Sha Tsui" in text and "Hong Kong" in text


def test_without_a_city_the_question_is_unchanged():
    text = templates.clarification_response(Clarification(kind="unresolved", subject="Ojai"), "fr")
    assert text == "Je n'ai pas réussi à situer « Ojai ». Vous pouvez préciser la ville ou le pays ?"
