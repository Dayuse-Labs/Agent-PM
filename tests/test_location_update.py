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
