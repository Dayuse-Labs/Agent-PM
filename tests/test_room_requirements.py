"""Persistent bedding preference; provider bedding is offer-level evidence.

Ported from #134 (`tests/test_room_requirements.py`), slice 5 of PORT1 —
bedding only. Left out: private/included/access amenity scopes and the
displayed-slot fact (equipment and Dates families).
"""
import json

import pytest
from b2c_common.room_requirements import apply_room_update, bedding_matches, grounded_room_update
from b2c_concierge.profile import SessionProfile, apply_profile_delta, leaf_profile_view
from hotel_search_agent.response_bridge import normalize_search_results


def test_grounded_current_update_and_explicit_removal():
    assert grounded_room_update({'bedding': 'double', 'evidence': 'lit double'}, 'avec un lit double') == {'bedding': 'double'}
    assert apply_room_update({'bedding': 'double'}, {'bedding': 'any'}) == {}
    assert apply_room_update({'bedding': 'double'}, None) == {'bedding': 'double'}
    assert apply_room_update(None, {'bedding': 'twin'}) == {'bedding': 'twin'}


@pytest.mark.parametrize('update', [
    {'bedding': 'double', 'evidence': 'old quote'},
    {'bedding': 'invented', 'evidence': 'double'},
    {'bedding': ['double'], 'evidence': 'double'},
    {'private_amenities': ['jacuzzi'], 'evidence': 'double'},
    {'bedding': 'double', 'evidence': 'double', 'provider_verified': True},
])
def test_invalid_updates_cannot_change_room_intent(update):
    assert grounded_room_update(update, 'double') is None


def test_room_requirements_survive_storage_and_leaf_cannot_overwrite_them():
    p = SessionProfile(room_requirements={'bedding': 'double'})
    p = SessionProfile.from_dict(json.loads(json.dumps(p.to_dict())))
    assert leaf_profile_view(p)['room_requirements'] == {'bedding': 'double'}
    apply_profile_delta(p, {'room_requirements': {'op': 'clear'}}, '')
    assert p.room_requirements == {'bedding': 'double'}


@pytest.mark.parametrize('bed,expected', [('double', True), ('double_king', True), ('double_queen', True), ('single', False), ('twin_single', False), (None, False)])
def test_double_bed_is_proved_by_formula_not_occupancy(bed, expected):
    assert bedding_matches({'bedding': bed, 'capacity': 2}, {'bedding': 'double'}) is expected


def test_bedding_filter_precedes_offer_selection_and_unknown_is_not_a_match():
    offers = [{'ratePlanUuid': 'twin', 'bedding': 'twin_single', 'price': 1000},
              {'ratePlanUuid': 'king', 'bedding': 'double_king', 'price': 3000}]
    cards = normalize_search_results({'results': [{'hotelId': 42, 'name': 'Test', 'offers': offers}]}, room_requirements={'bedding': 'double'})
    assert cards[0]['offer_id'] == 'king'
    assert normalize_search_results({'results': [{'hotelId': 42, 'offers': offers[:1]}]}, room_requirements={'bedding': 'double'}) == []
