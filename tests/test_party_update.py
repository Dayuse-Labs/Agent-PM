"""A total guest count never silently becomes an adult count."""
import pytest

from b2c_common.party_update import resolve_party_update
from b2c_concierge.profile import SessionProfile
from b2c_concierge.triage import _grounded_occupancy


@pytest.mark.parametrize("update,expected", [
    ({"total": 3}, ({"adults": 2, "children": 1}, None)),
    ({"adults": 3}, ({"adults": 3}, None)),
    ({"total": 4}, (None, 4)),
    ({"total": 1}, ({"adults": 1, "children": 0}, None)),
    ({"total": 4, "children": 1}, ({"adults": 3, "children": 1}, None)),
    ({"children": 0}, ({"children": 0}, None)),
])
def test_total_confirmation_differs_from_an_explicit_component_change(update, expected):
    assert resolve_party_update(2, 1, None, update) == expected


@pytest.mark.parametrize("adults,children", [(None, None), (2, None), (None, 1)])
def test_unknown_composition_is_not_invented_from_total(adults, children):
    assert resolve_party_update(adults, children, None, {"total": 3}) == (None, 3)


def test_pending_total_survives_storage_and_partial_answer_resolves_it():
    profile = SessionProfile(pending_party_total=3)
    loaded = SessionProfile.from_dict(profile.to_dict())
    assert loaded.pending_party_total == 3
    assert resolve_party_update(None, None, loaded.pending_party_total, {"children": 1}) == ({"children": 1, "adults": 2}, None)
    assert resolve_party_update(None, None, 3, None) == (None, 3)
    assert resolve_party_update(None, None, 3, {"adults": 4}) == ({"adults": 4}, 3)
    assert resolve_party_update(None, None, 3, {"adults": 2, "children": 2}) == ({"adults": 2, "children": 2}, None)


@pytest.mark.parametrize("raw", [
    {"total": True}, {"total": 0}, {"total": 31}, {"total": 3.0},
    {"total": 3, "adults": 3, "children": 1}, {"total": 2, "adults": 3},
    {"total": 3, "children": 3},
])
def test_invalid_or_contradictory_current_total_is_not_accepted(raw):
    assert _grounded_occupancy({**raw, "counts": "people", "evidence": "party"}, "party") is None


def test_current_literal_total_is_accepted_and_stale_quote_is_rejected():
    party = {"total": 3, "counts": "people", "evidence": "we are three"}
    assert _grounded_occupancy(party, "Yes, we are three") == {"total": 3}
    assert _grounded_occupancy(party, "cheaper please") is None


@pytest.mark.parametrize("adults,children,pending", [(None, None, None), (2, 1, None), (None, None, 3)])
def test_one_person_is_one_adult_with_nothing_to_ask(adults, children, pending):
    # Prod audit 2026-11-02: « votre groupe de 1 personnes… combien d'adultes
    # et d'enfants ? » in 8 replies.
    assert resolve_party_update(adults, children, pending, {"total": 1}) == ({"adults": 1, "children": 0}, None)
