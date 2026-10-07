"""Assertions on the controlled inventory, independent of LLM wording."""
import copy

import pytest

from evals.common_inventory import CommonInventory, LegacyAvailability, UnsupportedDimension


def fixture():
    offer = {'ratePlanId': 11, 'availabilityDate': '2026-10-07', 'priceEuroWithBookingFees': 6050,
             'startHour': 10, 'startMinute': 0, 'endHour': 18, 'endMinute': 0, 'capacity': 2}
    h = {'hotelId': 1, 'name': 'Synthetic Hotel', 'lat': 48.85, 'lon': 2.35, 'starRating': 4, 'offers': [offer]}
    other = copy.deepcopy(h)
    other.update(hotelId=2, lat=40.71, lon=-74.0)
    return {'date': '2026-10-07', 'hotels': [{'provider': h, 'country_code': 'FR'}, {'provider': other, 'country_code': 'US'}]}


def query(**kwargs):
    return {'date': '2026-10-07', 'lat': 48.85, 'lon': 2.35, **kwargs}


def test_common_price_and_geo_constraints():
    inv = CommonInventory(fixture())
    assert inv.search(query(priceRangeMax=60))['results'] == []
    result = inv.search(query(priceRangeMax=60.5))['results']
    assert [h['hotelId'] for h in result] == [1]
    assert result[0]['offers'][0]['priceEuroWithBookingFees'] == 6050
    assert LegacyAvailability(inv).get_rate_plan(1, 11)['price_minor'] == 6050
    assert LegacyAvailability(inv).get_rate_plan(1, 11)['booking_fee_minor'] == 0


def test_overlap_is_not_full_coverage_and_result_does_not_mutate_snapshot():
    inv = CommonInventory(fixture())
    assert inv.search(query(timeSlot={'startHour': 17, 'endHour': 20}))['total'] == 1
    assert inv.search(query(timeSlot={'startHour': 18, 'endHour': 20}))['total'] == 0
    result = inv.search(query())
    result['results'][0]['offers'][0]['priceEuroWithBookingFees'] = 0
    assert inv.search(query())['results'][0]['offers'][0]['priceEuroWithBookingFees'] == 6050


def test_out_of_scope_evidence_is_never_invented():
    inv = CommonInventory(fixture())
    with pytest.raises(UnsupportedDimension):
        inv.search(query(date='2026-10-08'))
    with pytest.raises(UnsupportedDimension):
        inv.search(query(hotelEquipmentIds=[123]))


def test_controlled_pagination_has_a_real_end():
    inv = CommonInventory(fixture())
    assert inv.search(query(size=1))['has_more'] is False
    assert inv.search(query(**{'from': 1}))['results'] == []


def test_cutoff_excludes_the_same_offer_in_both_adapters():
    data = fixture()
    data['hotels'][0]['provider']['offers'][0]['cutoffDeadlineUtc'] = '2000-01-01T00:00:00Z'
    inventory = CommonInventory(data)
    assert inventory.search(query())['results'] == []
    assert LegacyAvailability(inventory).get_rate_plan(1, 11)['available'] is False
