"""Prod 2026-10-30 → 11-02 (after #179): the triage read parties where nobody was
named — a fragment of a date or an hour (« 08 » of « 08.11.26 », « 11.11. »,
« 9 /13 »), a distance (« à 25 minutes » → 25), a place (« Singapore »,
« près de moi » → 1) — and the composition question went out with no card.

The model says first, as a typed yes/no (`names_people`), whether the message
names people; the code only checks facts about its output (the quote is in the
message, and is not itself a date) — it never judges the words.
"""
import pytest

from b2c_concierge import triage as triage_module
from b2c_concierge.triage import _grounded_occupancy, _occupancy_out_of_range


@pytest.mark.parametrize("message,total,evidence", [
    ("trier zentrum am 08.11.26", 8, "08"),
    ("Datum ist der 11.11.", 11, "11.11."),
    ("9 /13 domani mattina  c'è?", 9, "9 /13"),
    ("adesso, 2 di notte del 2 novembre", 2, "2"),
    ("18+", 18, "18+"),
])
def test_the_models_no_on_a_date_or_an_hour_is_final(message, total, evidence):
    # The code never judges the words: the model's typed answer decides
    # (measured on real annotated messages, HANDOFF 2026-11-02).
    raw = {"names_people": False, "adults": None, "children": None, "total": total, "evidence": evidence}
    assert _grounded_occupancy(raw, message) is None
    assert _occupancy_out_of_range({**raw, "total": 99}, message) is None


def test_a_quote_that_is_a_date_is_still_no_party():
    raw = {"names_people": True, "total": 7, "evidence": "7 novembre"}
    assert _grounded_occupancy(raw, "Samedi 7 novembre") is None


@pytest.mark.parametrize("message,total,evidence", [
    ("Entre 8H à 15H, à 25 minutes", 25, "À 25 minutes"),
    ("Lausanne et 30km", 30, "30km"),
    ("From 4pm", 4, "From 4pm"),
    ("Près de moi", 1, "moi"),
    ("Singapore", 1, "Singapore"),
    ("Ok show me 250 rooms for Nov 3", 250, "250 rooms"),
])
def test_without_an_explicit_yes_the_slot_is_no_party(message, total, evidence):
    raw = {"adults": None, "children": None, "total": total, "evidence": evidence}
    for flag in ({}, {"names_people": False}, {"names_people": "true"}, {"names_people": 1}):
        assert _grounded_occupancy({**raw, **flag}, message) is None
        assert _occupancy_out_of_range({**raw, **flag}, message) is None


@pytest.mark.parametrize("message,evidence,total", [
    ("trier zentrum am 08.11.26 für 2 personen", "für 2 personen", 2),
    ("una stanza per due fra 10 minuti", "per due", 2),
    ("ich suche ein zimmer zu zweit", "zu zweit", 2),
    ("Day room for a family of 3", "family of 3", 3),
    ("享受二人浪漫時光", "二人", 2),
])
def test_a_quote_that_names_the_people_is_kept(message, evidence, total):
    raw = {"names_people": True, "total": total, "evidence": evidence}
    assert _grounded_occupancy(raw, message) == {"total": total}


def test_a_count_beyond_any_room_with_its_people_is_still_reported():
    raw = {"names_people": True, "total": 250, "evidence": "250 people"}
    assert _occupancy_out_of_range(raw, "we are 250 people on Nov 3") == 250


def test_the_prompt_asks_first_whether_the_message_names_people():
    prompt = triage_module._TRIAGE_INSTRUCTION
    assert '"names_people": true or false' in prompt and 'Decide "names_people" FIRST' in prompt
    assert "3 horas" in prompt and "9 /13" in prompt and "à 25 minutes" in prompt
    assert "never a bare number" in prompt
