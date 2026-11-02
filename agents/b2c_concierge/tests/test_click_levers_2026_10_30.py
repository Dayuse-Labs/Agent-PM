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


# --- point 4: numbers read as filters -----------------------------------------------------------

import asyncio  # noqa: E402

from google.adk.runners import InMemoryRunner  # noqa: E402

from b2c_concierge.agent import cards_from_shortlist, root_agent, same_place_and_day  # noqa: E402
from b2c_concierge.relaxation_notice import party_check  # noqa: E402
from b2c_concierge.triage import _occupancy_out_of_range  # noqa: E402

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: E402,F401

_CONTEXT = {"city": "Houston", "zone": None, "date": "2026-11-01"}
_CARD = {"hotel_id": 1, "name": "C. Baldwin", "price": "€138", "offer_id": "o1", "offer_date": "2026-11-01",
         "timeslots": [{"start": "10:00", "end": "18:00"}]}


def test_the_closed_question_states_the_most_a_room_sleeps():
    text = party_check({"party": {"adults": 18, "children": None, "max_capacity": 4}}, "en")
    assert text == "The offers found here sleep at most 4 people per room. Just to check: are you really 18 people?"
    assert party_check({"steps": ["radius"]}, "en") == ""


def test_a_party_count_beyond_any_room_is_reported_not_applied():
    raw = {"adults": None, "children": None, "total": 250, "counts": "people", "evidence": "250 rooms"}
    assert _occupancy_out_of_range(raw, "Ok show me 250 rooms for Nov 3") == 250
    assert _occupancy_out_of_range({**raw, "total": 4, "evidence": "4"}, "we are 4") is None
    assert _occupancy_out_of_range({**raw, "evidence": "999 rooms"}, "Ok show me 250 rooms") is None


def test_only_a_criterion_changed_on_the_same_place_and_day():
    import json

    before = json.dumps({**_CONTEXT, "adults": None})
    assert same_place_and_day(before, json.dumps({**_CONTEXT, "adults": 18}))
    assert not same_place_and_day(before, json.dumps({**_CONTEXT, "date": "2026-11-02"}))
    assert not same_place_and_day(before, json.dumps({**_CONTEXT, "city": "Humble"}))
    assert not same_place_and_day(None, before)


def test_the_shortlist_comes_back_in_the_card_shape():
    cards = cards_from_shortlist([{"hotel_id": 1, "name": "A", "start_time": "10:00", "end_time": "18:00"}])
    assert cards == [{"hotel_id": 1, "name": "A", "id": 1, "timeslots": [{"start": "10:00", "end": "18:00"}]}]


def _turns(monkeypatch, fake_leg, second_payload, second_triage):  # noqa: F811
    fake_leg.response_payload = {"results": [_CARD], "profile_delta": {"city": "Houston"},
                                 "search_context": _CONTEXT}
    _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Here is C. Baldwin.",
                  second_triage, "Here you go.")
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    _run_turn(runner, session.id, "Houston")
    fake_leg.response_payload = second_payload
    return runner, session, _run_turn(runner, session.id, "18+")


_EIGHTEEN = ('{"family": "search", "language": "en", "requested_occupancy": '
             '{"adults": 18, "children": null, "total": null, "evidence": "18+"}}')


def test_18_adults_no_room_sleeps_ends_on_one_closed_question_and_is_dropped(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    payload = {"results": [_CARD], "search_context": {**_CONTEXT, "adults": None},
               "relaxation": {"steps": ["party"], "searched_date": "2026-11-01",
                              "party": {"adults": 18, "children": None, "max_capacity": 4}}}
    runner, session, answer = _turns(monkeypatch, fake_leg, payload, _EIGHTEEN)

    assert answer.endswith("Just to check: are you really 18 people?")
    stored = asyncio.run(fake_profile_store.get(session.id))
    assert stored.adults is None
    assert stored.last_clarifying_question.endswith("are you really 18 people?")


def test_a_criterion_that_empties_the_list_keeps_the_previous_cards(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    payload = {"results": [], "search_context": {**_CONTEXT, "adults": 18}}
    _runner, _session, answer = _turns(monkeypatch, fake_leg, payload, _EIGHTEEN)

    assert templates.previous_cards_notice("en") in answer


# --- point 5: « demain, plus près » ---------------------------------------------------------

from b2c_concierge.ground_truth import date_context_block  # noqa: E402


@pytest.mark.parametrize("language", ["fr", "en", "es", "it", "de", "pt", "nl"])
def test_the_closer_tomorrow_notice_gives_tonights_distance_and_the_day(language):
    text = templates.closer_tomorrow_notice(3.9, "DAY", language)
    assert "DAY" in text and ("3,9" in text or "3.9" in text)
    assert "DAY" in templates.closer_tomorrow_notice(None, "DAY", language)


def test_the_synthesis_is_told_the_cards_are_for_the_next_day():
    block = date_context_block({"search_date": {"date": "2026-10-30", "closer_from": "2026-10-29"}}, "en")
    assert block.startswith("MANDATORY") and "NOT for" in block
