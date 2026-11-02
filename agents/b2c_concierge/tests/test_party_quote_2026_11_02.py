"""Prod 2026-10-30 → 11-02 (after #179): the triage quoted a fragment of a date
or an hour as a party — « 08 » of « 08.11.26 », « 11.11. », « 9 /13 », the « 2 »
of « 2 di notte » — and the composition question went out with no card. A quote
made of digits and punctuation alone names no one; the prompt says an hour, a
time range or a length of stay is no party either.
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
def test_a_quote_without_a_word_is_no_party(message, total, evidence):
    raw = {"adults": None, "children": None, "total": total, "evidence": evidence}
    assert _grounded_occupancy(raw, message) is None
    assert _occupancy_out_of_range({**raw, "total": 99}, message) is None


@pytest.mark.parametrize("message,evidence,total", [
    ("trier zentrum am 08.11.26 für 2 personen", "für 2 personen", 2),
    ("una stanza per due fra 10 minuti", "per due", 2),
    ("ich suche ein zimmer zu zweit", "zu zweit", 2),
    ("Day room for a family of 3", "family of 3", 3),
    ("Mong kok 二人", "二人", 2),
])
def test_a_quote_that_names_the_people_is_kept(message, evidence, total):
    assert _grounded_occupancy({"total": total, "evidence": evidence}, message) == {"total": total}


def test_a_count_beyond_any_room_with_its_word_is_still_reported():
    raw = {"total": 250, "evidence": "250 rooms"}
    assert _occupancy_out_of_range(raw, "Ok show me 250 rooms for Nov 3") == 250


def test_the_prompt_says_hours_and_stay_lengths_are_no_party():
    prompt = triage_module._TRIAGE_INSTRUCTION
    assert "3 horas" in prompt and "9 /13" in prompt and "2 di notte" in prompt
    assert "never a bare number" in prompt
