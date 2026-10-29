"""Point 3 (prod 2026-10-27/28): what the search relaxed is said in code.

Prod: « Geen aanbiedingen in Den Bosch … met jacuzzi » then « gebied
vergroten » ×2 → « Ik kan de zoekzone niet zelf vergroten »; « quitar un
filtro » → the same search, « si me dices qué filtro quieres quitar… ». The
leaf now relaxes an empty search (and applies the recovery chips) and its
DataPart says what it did, under `relaxation`; the concierge writes it before
the synthesis, the way the « aucune offre » sentence is written.
"""
from __future__ import annotations

import asyncio

from b2c_concierge.profile import _RECOVERY_SUGGESTIONS, SessionProfile
from b2c_concierge.relaxation_notice import clicked_relax_chip, relaxation_line, relaxation_note

from .test_spine import _answer, _drive_in, _new_session, scripted  # noqa: F401, F811  (fixture)

_DUBLIN_CONTEXT = {"city": "Dublin", "zone": None, "date": "2026-10-29", "amenities": ["jacuzzi"]}


def test_every_recovery_chip_but_the_zone_maps_to_a_relax_action_in_seven_languages():
    for language, labels in _RECOVERY_SUGGESTIONS.items():
        assert clicked_relax_chip(labels[0]) == "budget", language
        assert clicked_relax_chip(labels[2]) == "filters", language
        assert clicked_relax_chip(labels[1]) is None, language  # the zone chip: `widen_area`


def test_free_text_is_never_read_as_a_chip():
    for message in ("quitar el filtro de spa", "can you increase the budget to 200", "élargis un peu", ""):
        assert clicked_relax_chip(message) is None


def test_the_empty_search_is_cited_then_what_was_relaxed():
    line = relaxation_line(
        {"steps": ["amenities"], "amenities": ["jacuzzi"], "searched_date": "2026-10-29"},
        _DUBLIN_CONTEXT, "fr",
    )
    assert line.startswith("Aucune offre à Dublin le jeudi 29 octobre 2026, avec jacuzzi.")
    assert line.endswith("Voici les offres les plus proches, en assouplissant le critère jacuzzi.")


def test_a_next_day_rescue_names_the_empty_day_and_the_day_shown():
    line = relaxation_line(
        {"steps": ["timeslot", "next_day"], "searched_date": "2026-10-28", "offered_date": "2026-10-29"},
        {"city": "Hong Kong", "zone": "Wan Chai", "date": "2026-10-29", "timeslot_start": "21:00"},
        "en",
    )
    assert "Wednesday, October 28, 2026" in line and "from 21:00" in line
    assert line.endswith("relaxing the time slot and the date (Thursday, October 29, 2026).")


def test_a_wider_ring_says_how_far():
    line = relaxation_line({"steps": ["timeslot", "radius"], "radius_km": 100.0, "searched_date": "2026-12-12"},
                           {"city": "Cape Canaveral", "date": "2026-12-12"}, "en")
    assert "the area (up to 100 km)" in line


def test_the_request_lines_say_what_changed_or_that_nothing_could():
    assert relaxation_line({"request": {"requested": ["filters"], "removed": ["amenities"],
                                        "amenities": ["jacuzzi"]}}, None, "es") == "He quitado el filtro jacuzzi."
    assert relaxation_line({"request": {"requested": ["filters"], "nothing_to_remove": True, "chip": "filters"}},
                           None, "es") == "No había ningún filtro aplicado a esta búsqueda."
    assert relaxation_line({"request": {"requested": ["budget"], "no_budget": True, "chip": "budget"}}, None, "en") == (
        "No price cap was applied to this search."
    )
    assert relaxation_line({"request": {"requested": ["budget"], "budget": {"from": 80.0, "to": 100.0,
                                                                            "currency": "EUR"}}}, None, "fr") == (
        "J'ai relevé le budget de 80 à 100 EUR pour cette recherche."
    )
    assert relaxation_line({"request": {"requested": ["area"]}}, None, "nl") == ""
    assert relaxation_line(None, None, "fr") == ""


def test_the_synthesis_is_told_the_cards_match_less_than_asked():
    note = relaxation_note({"steps": ["amenities"]})
    assert "NO offer matched everything asked" in note
    assert relaxation_note(None) == ""


def test_the_chip_reaches_the_leaf_and_the_line_leads_the_answer(scripted, fake_profile_store):  # noqa: F811
    """« quitar un filtro » (Barcelona): the chip is data for the leaf, and the
    leaf's « nothing to remove » is written before the synthesis."""
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city="Barcelona", language="es", last_suggestions=list(_RECOVERY_SUGGESTIONS["es"]),
        consecutive_empty_searches=1, date_checked=True,
    )))
    response = {
        "results": [{"hotel_id": 1, "name": "Hotel Uno", "city": "Barcelona"}],
        "relaxation": {"request": {"requested": ["filters"], "nothing_to_remove": True, "chip": "filters"}},
        "search_context": {"city": "Barcelona", "date": "2026-10-28"},
    }
    _, leaf_calls = scripted(
        '{"family": "search", "language": "es"}', "Hotel Uno está disponible mañana.",
        leaf_text="results: Hotel Uno", response=response,
    )
    events = _drive_in(runner, session.id, "quitar un filtro")
    assert leaf_calls.kwargs[0]["query_params"]["relax"] == "filters"
    assert _answer(events).startswith("No había ningún filtro aplicado a esta búsqueda.")


def test_a_rescued_turn_is_visible_in_turn_facts():
    """Review of #173: a rescued turn was only a `dayuse_metric=search_rescue`
    log line. The leaf now raises `search_rescue` (`fallbacks_fired`): it
    becomes the `fallback_search_rescue` score and a `turn_facts.fallbacks`
    entry (append-only contract)."""
    from b2c_concierge.turn_facts import spine_turn_facts

    facts = spine_turn_facts(
        family="search", route="leaf:hotel_search", status="ok", hotels_returned=3, fallbacks={"search_rescue"},
    )
    assert facts["fallbacks"] == ["search_rescue"]
