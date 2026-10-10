"""Persistent offer preferences without inferred property/price inclusions."""
import json

import pytest
from b2c_common.room_requirements import apply_room_update, bedding_matches, grounded_room_update, unverified_access
from b2c_concierge.profile import SessionProfile, apply_profile_delta, leaf_profile_view
from hotel_search_agent.response_bridge import normalize_search_results


def test_grounded_current_update_carries_unrelated_scopes():
    p = {'bedding': 'double', 'private_amenities': ['jacuzzi']}
    u = grounded_room_update({'included_amenities': ['breakfast'], 'evidence': 'breakfast included'}, 'with breakfast included')
    assert apply_room_update(p, u) == {**p, 'included_amenities': ['breakfast']}
    assert apply_room_update(p, {'bedding': 'any'}) == {'private_amenities': ['jacuzzi']}
    assert apply_room_update(p, {'private_amenities': []}) == {'bedding': 'double'}


@pytest.mark.parametrize('update', [
    {'bedding': 'double', 'evidence': 'old quote'},
    {'bedding': 'invented', 'evidence': 'double'},
    {'bedding': ['double'], 'evidence': 'double'},
    {'private_amenities': ['made up'], 'evidence': 'double'},
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


def test_private_or_included_access_is_not_proven_by_an_amenity_label():
    assert unverified_access({'private_amenities': ['jacuzzi']})
    assert unverified_access({'included_amenities': ['pool']})
    assert not unverified_access({'bedding': 'double'})
