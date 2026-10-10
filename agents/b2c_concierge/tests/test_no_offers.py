"""mcp-dayuse#5: the "no offers" sentence cites the search that actually ran."""
from __future__ import annotations

import pytest

from b2c_concierge.no_offers import drop_restated, no_offers_line

_LYON = {
    "city": "Lyon", "zone": None, "date": "2026-10-07", "daypart": None,
    "timeslot_start": "06:00", "timeslot_end": "16:00", "budget_max": 20.0,
    "amenities": ["spa", "pool"], "adults": None, "children": None, "radius_km": 20,
}


def test_every_applied_criterion_is_cited():
    assert no_offers_line(_LYON, "fr") == (
        "Je n’ai trouvé aucune offre vérifiable dans cette recherche à Lyon le mercredi 7 octobre 2026, de 6h à 16h, à moins de 20 €, avec spa et piscine."
    )


def test_a_zone_is_cited_with_its_city():
    """Live 2026-10-06: "Gare du Nord" and 7h–9h vanished from the LLM's version."""
    context = {
        **_LYON, "city": "Paris", "zone": "Gare du Nord", "timeslot_start": "07:00",
        "timeslot_end": "09:00", "budget_max": 30.0, "amenities": ["sauna"],
    }
    assert no_offers_line(context, "en") == (
        "I found no verifiable offer in this search around Gare du Nord, Paris on Wednesday, October 7, 2026, "
        "from 7:00 to 9:00, under €30, with a sauna."
    )


def test_a_daypart_replaces_the_window():
    context = {**_LYON, "daypart": "afternoon", "timeslot_start": None, "timeslot_end": None,
               "budget_max": None, "amenities": []}
    assert no_offers_line(context, "fr") == "Je n’ai trouvé aucune offre vérifiable dans cette recherche à Lyon le mercredi 7 octobre 2026, l'après-midi."


def test_minutes_are_not_rounded_in_the_displayed_request():
    context = {**_LYON, "timeslot_start": "22:01", "timeslot_end": "23:01", "budget_max": None, "amenities": []}
    assert "de 22h01 à 23h01" in no_offers_line(context, "fr")


@pytest.mark.parametrize(("language", "expected"), [
    ("fr", "de 10h30 à 19h"), ("en", "from 10:30 to 19:00"),
    ("es", "de 10:30 a 19:00"), ("it", "dalle 10:30 alle 19"),
    ("de", "von 10:30 bis 19 Uhr"), ("pt", "das 10h30 às 19h"),
    ("nl", "van 10.30 tot 19.00 uur"),
])
def test_jfk_half_hour_request_is_preserved_in_every_language(language, expected):
    context = {**_LYON, "timeslot_start": "10:30", "timeslot_end": "19:00"}
    assert expected in no_offers_line(context, language)


@pytest.mark.parametrize(("start", "end", "expected"), [
    ("10:30", None, "from 10:30"),
    (None, "19:45", "until 19:45"),
    ("23:30", "24:00", "from 23:30 to 24:00"),
    ("10:15", "10:45", "from 10:15 to 10:45"),
])
def test_one_sided_and_short_windows_do_not_invent_or_shift_bounds(start, end, expected):
    context = {**_LYON, "timeslot_start": start, "timeslot_end": end}
    assert expected in no_offers_line(context, "en")


@pytest.mark.parametrize("language", ["fr", "en", "es", "it", "de", "pt", "nl"])
def test_every_language_cites_the_same_facts(language):
    line = no_offers_line({**_LYON, "adults": 3}, language)
    assert "Lyon" in line and "2026" in line and "20" in line and "3" in line
    assert "{" not in line and line.endswith(".")


def test_a_restated_sentence_is_dropped_and_the_next_step_kept():
    """Live 2026-10-06: shown the sentence, the synthesis copied it anyway."""
    line = no_offers_line(_LYON, "fr")
    text = (
        "Je n’ai trouvé aucune offre vérifiable dans cette recherche à Lyon le mercredi 7 octobre 2026, à moins de 20 €, avec spa et piscine. "
        "Je vous recommande d'augmenter votre budget ou de changer de date."
    )
    assert drop_restated(text, line) == "Je vous recommande d'augmenter votre budget ou de changer de date."


def test_a_german_date_does_not_split_the_restated_sentence():
    line = no_offers_line(_LYON, "de")
    text = f"{line} Versuchen Sie ein anderes Datum."
    assert drop_restated(text, line) == "Versuchen Sie ein anderes Datum."


def test_an_unrelated_answer_is_left_alone():
    line = no_offers_line(_LYON, "fr")
    text = "Essayez une autre date.\n\nOu une zone plus large."
    assert drop_restated(text, line) == text


def test_nothing_to_cite_gives_no_sentence():
    assert no_offers_line(None, "fr") == ""
    assert no_offers_line({}, "fr") == ""


@pytest.mark.parametrize("language", ["fr", "en", "es", "it", "de", "pt", "nl"])
def test_empty_budget_search_keeps_all_criteria_and_native_currency(language):
    line = no_offers_line({**_LYON, "timeslot_start": "10:30", "timeslot_end": "19:00"}, language,
                          requested_budget={"amount": 150, "currency": "USD", "unit": "total"})
    assert "Lyon" in line and "2026" in line and "150 USD" in line
    assert "10" in line and "30" in line and "19" in line
    assert "€" not in line  # a sent EUR retrieval cap is not the user's USD cap
    assert "{" not in line
