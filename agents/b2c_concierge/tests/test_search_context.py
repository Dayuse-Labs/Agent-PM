import pytest
from b2c_common.search_location import parse_location_update

from b2c_concierge.profile import SessionProfile
from b2c_concierge.search_context import prepare_search_context


@pytest.mark.parametrize('value', [None, [], {'action':'invent'},
    {'action':'replace','city':3}, {'action':'replace','city':'a','latitude':48},
    {'action':'replace','city':'a','country_code':'USA'},
    {'action':'retain','city':'Paris'}, {'action':'replace','zone':''}])
def test_bad_edits_do_not_become_location_state(value):
    assert parse_location_update(value) is None


def test_budget_followup_retains_landmark_and_filters_after_profile_roundtrip():
    profile = SessionProfile(budget_max=100, amenities=['pool'], timeslot_start='10:00', timeslot_end='17:00')
    prepare_search_context(profile, {'action':'replace','city':'London','zone':'Heathrow Airport Terminal 3','country_code':'GB'})
    # No geocode result came back (timeout). The request, not coordinates, persists.
    profile = SessionProfile.from_dict(profile.to_dict())
    view = prepare_search_context(profile, {'action':'retain'})
    assert profile.city is None  # no false promotion to verified state
    assert view['city'] == 'London'
    assert view['zone'] == 'Heathrow Airport Terminal 3'
    assert view['budget_max'] == 100 and view['amenities'] == ['pool']
    assert (view['timeslot_start'],view['timeslot_end']) == ('10:00','17:00')


def test_destination_replacement_does_not_inherit_country_zone_or_coordinates():
    profile = SessionProfile(city='Paris',zone='Bercy',country_anchor='FR',state_anchor='Île-de-France',
        search_anchor={'lat':48.8,'lon':2.3,'type':'gps'},budget_max=100)
    view = prepare_search_context(profile, {'action':'replace','city':'Cambridge'})
    assert view['city'] == 'Cambridge'
    assert all(view[k] is None for k in ['zone','country_anchor','state_anchor','search_anchor'])
    assert view['budget_max'] == 100
    view = prepare_search_context(profile, {'action':'retain'})
    assert view['search_anchor'] is None and view['country_anchor'] is None


def test_clarification_adds_city_without_dropping_landmark_then_can_clear_zone():
    profile = SessionProfile()
    prepare_search_context(profile, {'action':'replace','zone':'Central Station'})
    view = prepare_search_context(profile, {'action':'refine','city':'Rotterdam','country_code':'NL'})
    assert view['zone'] == 'Central Station' and view['city'] == 'Rotterdam'
    view = prepare_search_context(profile, {'action':'refine','zone':None})
    assert view['zone'] is None and view['city'] == 'Rotterdam'


def test_malformed_triage_does_not_override_legacy_leaf_contract():
    profile = SessionProfile(city='Paris')
    view = prepare_search_context(profile, None)
    assert 'search_location_request' not in view
    assert profile.search_location_request is None


def test_city_kind_cannot_search_a_hotel_named_after_city_and_state():
    profile = SessionProfile()
    view = prepare_search_context(profile, {'action':'replace','kind':'city','city':'Milford',
        'zone':'Milford, CT','region':'Connecticut','country_code':'US'})
    assert view['zone'] is None
    assert view['city'] == 'Milford' and view['state_anchor'] == 'Connecticut'


def test_city_clarification_keeps_original_landmark_kind_and_name():
    profile = SessionProfile()
    prepare_search_context(profile, {'action':'replace','kind':'landmark','zone':'Central Station'})
    view = prepare_search_context(profile, {'action':'refine','kind':'city','city':'Rotterdam','zone':'Rotterdam'})
    assert view['zone'] == 'Central Station'
    assert view['search_location_request']['kind'] == 'landmark'
