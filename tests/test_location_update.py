"""Destination transactions retain intent without inferring provider geometry."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from b2c_common.location_update import adapt_location_update
from b2c_common.search_areas import preserve_area_boundary, requires_area_membership, validate_areas
from hotel_search_agent.area_scope import resolve_areas
from hotel_search_agent.mapbox_client import GeocodeCandidate


def transaction(message, kind='city', query='Milano', **kw):
    return {'location_update': {'action': 'change', 'evidence': message,
            'targets': [{'kind': kind, 'query': query, 'country': 'IT',
                         'evidence': query, **kw}]}}


def test_vicinity_is_not_part_of_provider_identity_or_strict_boundary():
    message = 'Milano e dintorni'
    got = adapt_location_update(transaction(message), message, None)
    areas = validate_areas(got['requested_areas'], message)
    assert areas == [{'query': 'Milano', 'kind': 'municipality', 'country': 'IT', 'evidence': 'Milano'}]
    assert not requires_area_membership(areas)


def test_city_limit_and_neighborhood_require_membership():
    message = 'only inside Milano'
    got = adapt_location_update(transaction(message, scope='inside'), message, None)
    assert requires_area_membership(validate_areas(got['requested_areas'], message))
    message = 'in Porta Romana'
    got = adapt_location_update(transaction(message, kind='neighborhood', query='Porta Romana'), message, None)
    assert got['requested_areas'][0]['kind'] == 'neighborhood'
    assert requires_area_membership(validate_areas(got['requested_areas'], message))


def test_parent_clarification_retains_both_neighborhoods():
    previous = [{'query': name, 'country': 'BR', 'kind': 'neighborhood', 'evidence': name}
                for name in ['Barra', 'Recreio']]
    got = adapt_location_update({'location_update': {'action': 'refine', 'evidence': 'Rio de Janeiro',
                                'parent_city': 'Rio de Janeiro'}}, 'Rio de Janeiro', None)
    refined = preserve_area_boundary(previous, got['requested_areas'], parent_refinement=True,
                                     parent_city=got['location_intent']['parent_city'])
    assert [a['subarea'] for a in refined] == ['Barra', 'Recreio']
    assert all(a['query'] == 'Rio de Janeiro' for a in refined)


def test_new_airport_in_confirmed_city_owns_landmark_not_city_center():
    message = 'near the airport'
    raw = transaction(message, kind='landmark', query='airport')
    raw['location_update']['parent_city'] = 'Philadelphia'
    got = adapt_location_update(raw, message, {'confirmed_city': 'Philadelphia'})
    assert got['location_intent']['action'] == 'change'
    assert got['requested_landmark']['city'] == 'Philadelphia'
    assert got['requested_landmark']['query'] == 'airport'


@pytest.mark.parametrize('mutation', [
    {'query': 'Rome'}, {'evidence': 'previous message'}, {'country': 'USA'},
    {'kind': 'coordinates'}, {'scope': '200km'},
])
def test_invalid_target_cannot_mutate_geography(mutation):
    raw = transaction('Milano')
    raw['location_update']['targets'][0].update(mutation)
    got = adapt_location_update(raw, 'Milano', None)
    assert got['location_intent']['action'] == 'unknown'
    assert got['requested_areas'] is None
    assert got['requested_landmark'] is None


def test_conflicting_noop_cannot_leave_legacy_target_or_hotel_name():
    raw = transaction('Milano')
    raw.update(hotel_name='invented', requested_landmark={'query': 'invented'})
    raw['location_update']['action'] = 'preserve'
    got = adapt_location_update(raw, 'Milano', None)
    assert got['location_intent']['action'] == 'unknown'
    assert got['hotel_name'] is None
    assert got['requested_landmark'] is None


def test_neighborhood_resolution_requires_provider_type_identity_and_bbox():
    area = {'query': 'Porta Romana', 'country': 'IT', 'kind': 'neighborhood', 'evidence': 'Porta Romana'}
    c = GeocodeCandidate(45.45, 9.2, 'Porta Romana', 'Porta Romana', 'Italy', 'neighborhood', 'IT',
                         'Lombardy', (9.19, 45.44, 9.21, 45.46), 0, 'district-1', '')
    calls = []
    def provider(query, **kwargs):
        calls.append(kwargs)
        return [c]
    assert resolve_areas([area], SimpleNamespace(geocode_candidates=provider))['ok']
    assert calls[0]['types'] == 'locality,neighborhood'
    for changed in [{'feature_type': 'place'}, {'country_code': 'FR'}, {'name': 'Milano'}, {'bbox': None}]:
        fake = SimpleNamespace(geocode_candidates=lambda *args, **kw: [replace(c, **changed)])
        assert not resolve_areas([area], fake)['ok']


def test_unknown_country_preserves_owned_city_instead_of_letting_leaf_reinterpret_vicinity():
    message = 'Milano e dintorni'
    raw = transaction(message)
    raw['location_update']['targets'][0].pop('country')
    got = adapt_location_update(raw, message, None)
    areas = validate_areas(got['requested_areas'], message)
    assert areas == [{'query': 'Milano', 'kind': 'municipality', 'country': '', 'evidence': 'Milano'}]
    assert not requires_area_membership(areas)


def test_unresolved_alternative_neighborhoods_are_kept_before_parent_clarification():
    message = 'Barra ou Recreio'
    raw = {'location_update': {'action': 'change', 'evidence': message, 'targets': [
        {'kind': 'neighborhood', 'query': name, 'evidence': name} for name in ['Barra', 'Recreio']]}}
    got = adapt_location_update(raw, message, None)
    areas = validate_areas(got['requested_areas'], message)
    assert len(areas) == 2
    def no_global_district_lookup(*args, **kwargs):
        pytest.fail('Unknown neighborhood must ask its parent, not use an IP-biased provider result')
    unresolved = resolve_areas(areas, SimpleNamespace(geocode_candidates=no_global_district_lookup))
    assert not unresolved['ok'] and len(unresolved['unresolved_areas']) == 2
    refined = preserve_area_boundary(areas, None, parent_refinement=True, parent_city='Rio de Janeiro')
    assert [a['subarea'] for a in refined] == ['Barra', 'Recreio']
    assert all(a['query'] == 'Rio de Janeiro' and a['country'] == '' for a in refined)


def test_current_mention_of_confirmed_parent_can_ground_airport_parent_without_invention():
    message = 'In Philadelphia near airport'
    got = adapt_location_update(transaction(message, kind='landmark', query='airport'), message,
                                {'confirmed_city': 'Philadelphia'})
    assert got['requested_landmark']['city'] == 'Philadelphia'
    got = adapt_location_update(transaction('near airport', kind='landmark', query='airport'), 'near airport',
                                {'confirmed_city': 'Philadelphia'})
    assert got['requested_landmark']['city'] is None


@pytest.mark.parametrize('city,region', [('Glendora', 'CA'), ('San Antonio', 'Texas'), ('Fayetteville', 'nc')])
def test_city_and_parent_region_are_one_destination(city, region):
    message = f'{city}, {region}'
    raw = transaction(message, query=city, region=region)
    raw['location_update']['targets'][0]['country'] = 'US'
    got = adapt_location_update(raw, message, None)
    areas = validate_areas(got['requested_areas'], message)
    assert len(areas) == 1 and areas[0]['region'] == region
    assert not requires_area_membership(areas)


def test_explicit_containing_city_is_not_lost_when_country_unknown():
    message = 'New York City queens'
    raw = transaction(message, kind='neighborhood', query='queens')
    raw['location_update']['targets'][0].pop('country')
    raw['location_update']['parent_city'] = 'New York City'
    got = adapt_location_update(raw, message, None)
    areas = validate_areas(got['requested_areas'], message)
    assert areas == [{'query': 'New York City', 'kind': 'municipality', 'country': '',
                      'evidence': 'New York City', 'subarea': 'queens'}]


def test_bounded_city_provider_must_match_its_parent_region():
    area = {'query': 'Glendora', 'kind': 'municipality', 'country': 'US',
            'region': 'CA', 'evidence': 'Glendora', 'boundary_evidence': 'only inside'}
    c = GeocodeCandidate(34.13, -117.87, 'Glendora', 'Glendora, California, United States',
                         'United States', 'place', 'US', 'California',
                         (-117.9, 34.1, -117.8, 34.2), 0, 'glendora-ca', '')
    queries = []
    def provider(query, **kwargs):
        queries.append(query)
        return [c]
    assert resolve_areas([area], SimpleNamespace(geocode_candidates=provider))['ok']
    assert queries == ['Glendora, CA']
    wrong = replace(c, place_name='Glendora, Mississippi, United States', region='Mississippi')
    assert not resolve_areas([area], SimpleNamespace(geocode_candidates=lambda *a, **kw: [wrong]))['ok']
