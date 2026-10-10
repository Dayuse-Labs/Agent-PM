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
    {'evidence': 'previous message'}, {'country': 'USA'},
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


@pytest.mark.parametrize('explicit', [True, False])
def test_city_refinement_retains_mandatory_department(explicit):
    message = 'Melun, toujours en Seine-et-Marne'
    raw = transaction(message, query='Melun', region='Seine-et-Marne')
    raw['location_update']['targets'][0]['country'] = 'FR'
    previous = {'kind': 'areas', 'areas': [{'query': 'Seine-et-Marne', 'kind': 'administrative',
                                          'country': 'FR', 'evidence': 'Seine-et-Marne'}]}
    if explicit:
        raw['location_update']['targets'][0]['region_scope'] = 'inside'
    got = adapt_location_update(raw, message, {'requested_destination': previous} if not explicit else None)
    areas = validate_areas(got['requested_areas'], message)
    assert areas[0]['required_region'] == 'Seine-et-Marne'
    assert requires_area_membership(areas)
    repeated = preserve_area_boundary(areas, [{'query': 'Melun', 'kind': 'municipality',
                                              'country': 'FR', 'evidence': 'Melun'}])
    assert repeated[0]['required_region'] == 'Seine-et-Marne'


@pytest.mark.parametrize('message,expected', [('London', 'refine'), ('Switch to London', 'change')])
def test_postcode_question_owns_bare_city_reply(message, expected):
    raw = transaction(message, query='London')
    context = {'requested_destination': {'kind': 'postcode', 'query': 'W4'},
               'pending_clarification': {'kind': 'location'}}
    got = adapt_location_update(raw, message, context)
    assert got['location_intent']['action'] == expected
    if expected == 'refine':
        assert got['location_intent']['parent_city'] == 'London'
        assert got['requested_areas'] is None


@pytest.mark.parametrize('message,query,expected', [('London', 'London', 'refine'),
    ('Oxford', 'Oxford', 'change'), ('Switch to London', 'London', 'change')])
def test_verified_postcode_parent_does_not_broaden_existing_results(message, query, expected):
    context = {'requested_destination': {'kind': 'postcode', 'query': 'W4'}, 'confirmed_city': 'London'}
    got = adapt_location_update(transaction(message, query=query), message, context)
    assert got['location_intent']['action'] == expected


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


def test_recorded_budapest_transaction_needs_only_one_literal_quote():
    message = 'Budapest'
    raw = {'location_update': {'action': 'change', 'evidence': message, 'targets': [
        {'kind': 'city', 'query': 'Budapest', 'scope': 'nearby'}]}}
    got = adapt_location_update(raw, message, None)
    assert validate_areas(got['requested_areas'], message) == [
        {'query': 'Budapest', 'kind': 'municipality', 'country': '', 'evidence': message}]
    assert got['location_intent']['action'] == 'change'


@pytest.mark.parametrize('message,query,country,inferred_region', [
    ('Near San Bruno', 'San Bruno', 'US', 'California'),
    ('Red deer', 'Red Deer', 'CA', 'Alberta'),
])
def test_recorded_city_is_retained_without_inferred_region(message, query, country, inferred_region):
    raw = transaction(message, query=query, region=inferred_region)
    raw['location_update']['targets'][0].update(country=country, evidence=message)
    got = adapt_location_update(raw, message, None)
    areas = validate_areas(got['requested_areas'], message)
    assert areas == [{'query': query, 'kind': 'municipality', 'country': country, 'evidence': message}]
    assert not requires_area_membership(areas)


@pytest.mark.parametrize('target', [
    {'kind': 'city', 'query': 'Rome'},
    {'kind': 'city', 'query': 'Budapest', 'evidence': 'earlier Budapest'},
    {'kind': 'city', 'query': 'Budapest', 'evidence': None},
    {'kind': 'city', 'query': 'Budapest', 'evidence': ''},
])
def test_transaction_quote_cannot_rescue_ungrounded_target_or_invalid_explicit_quote(target):
    raw = {'location_update': {'action': 'change', 'evidence': 'Budapest', 'targets': [target]}}
    got = adapt_location_update(raw, 'Budapest', None)
    assert got['location_intent']['action'] == 'unknown'
    assert got['requested_areas'] is None


@pytest.mark.parametrize('kind,scope', [('landmark', 'nearby'), ('neighborhood', 'inside')])
@pytest.mark.parametrize('parent_on_targets', [True, False])
def test_redundant_parent_target_preserves_the_same_destination_contract(kind, scope, parent_on_targets):
    message = 'Example City near River Gate or Market Square'
    targets = [{'kind': kind, 'query': name, 'evidence': name, 'scope': scope,
                **({'parent_city': 'Example City'} if parent_on_targets else {})}
               for name in ('River Gate', 'Market Square')]
    raw = {'location_update': {'action': 'change', 'evidence': message,
            'parent_city': 'Example City', 'targets': targets}}
    expected = adapt_location_update(raw, message, None)
    raw['location_update']['targets'] = [
        {'kind': 'city', 'query': 'Example City', 'evidence': 'Example City'}, *targets]
    assert adapt_location_update(raw, message, None) == expected
    if kind == 'landmark':
        assert [p['query'] for p in expected['requested_landmarks']] == ['River Gate', 'Market Square']
        assert all(p['city'] == 'Example City' for p in expected['requested_landmarks'])
    else:
        assert [p['subarea'] for p in expected['requested_areas']] == ['River Gate', 'Market Square']


def test_each_landmark_keeps_its_explicit_parent_without_becoming_an_alternative_city():
    message = 'River Gate in Example City or Market Square in Other City'
    raw = {'location_update': {'action': 'change', 'evidence': message, 'targets': [
        {'kind': 'landmark', 'query': 'River Gate', 'parent_city': 'Example City'},
        {'kind': 'landmark', 'query': 'Market Square', 'parent_city': 'Other City'},
    ]}}
    got = adapt_location_update(raw, message, None)
    assert [(p['query'], p['city']) for p in got['requested_landmarks']] == [
        ('River Gate', 'Example City'), ('Market Square', 'Other City')]


@pytest.mark.parametrize('parent', [None, 'Other City', 'Invented City'])
def test_independent_city_alternative_is_not_dropped_without_a_grounded_parent_relation(parent):
    message = 'Example City or River Gate in Other City'
    raw = {'location_update': {'action': 'change', 'evidence': message, 'targets': [
        {'kind': 'city', 'query': 'Example City'},
        {'kind': 'landmark', 'query': 'River Gate', 'parent_city': parent},
    ]}}
    got = adapt_location_update(raw, message, None)
    assert got['location_intent']['action'] == 'unknown'
    assert got['requested_landmark'] is None


def test_single_landmark_parent_is_grounded_even_when_emitted_on_its_target():
    message = 'River Gate in Example City'
    raw = {'location_update': {'action': 'change', 'evidence': message, 'targets': [
        {'kind': 'landmark', 'query': 'River Gate', 'parent_city': 'Example City'}]}}
    assert adapt_location_update(raw, message, None)['requested_landmark']['city'] == 'Example City'
    raw['location_update']['targets'][0]['parent_city'] = 'Invented City'
    assert adapt_location_update(raw, message, None)['requested_landmark']['city'] is None


def test_named_area_survives_an_optional_code_not_in_current_message():
    from b2c_common.search_areas import validate_areas
    message = 'I mean Example Province'
    got = adapt_location_update({'location_update': {'action': 'correct', 'evidence': message,
        'targets': [{'kind': 'region', 'query': 'Example Province', 'country': 'GB', 'code': '12'}]}}, message, None)
    areas = validate_areas(got['requested_areas'], message)
    assert areas and areas[0]['query'] == 'Example Province' and 'code' not in areas[0]


def test_explicit_numeric_area_code_is_not_discarded_or_replaced_by_a_hint():
    from b2c_common.search_areas import validate_areas
    for code, accepted in [('12', True), ('13', False)]:
        got = adapt_location_update({'location_update': {'action': 'change', 'evidence': '12',
            'targets': [{'kind': 'region', 'query': '12', 'country': 'GB', 'code': code}]}}, '12', None)
        assert got['requested_areas'][0]['code'] == code
        assert bool(validate_areas(got['requested_areas'], '12')) is accepted


@pytest.mark.parametrize('family,action,name,message,expected', [
    ('details', 'preserve', 'Hilton Atlanta', 'Tell me about Hilton Atlanta', 'Hilton Atlanta'),
    ('details', 'preserve', 'Ritz Paris', 'Tell me about Ritz Paris', 'Ritz Paris'),
    ('details', 'preserve', 'Invented Hotel', 'Tell me about the second', None),
    ('search', 'preserve', 'Hilton Atlanta', 'Show Hilton Atlanta', None),
    ('booking', 'preserve', 'Hilton Atlanta', 'Book Hilton Atlanta', None),
    ('details', 'unknown', 'Hilton Atlanta', 'Tell me about Hilton Atlanta', None),
])
def test_named_facts_and_preserved_search_area_are_independent(family, action, name, message, expected):
    data = {'family': family, 'hotel_name': name,
            'location_update': {'action': action, 'evidence': message, 'targets': []}}
    got = adapt_location_update(data, message, None)
    assert got['hotel_name'] == expected
    assert got['requested_areas'] is None


@pytest.mark.parametrize('literal,normalized', [
    ('Sampletwn', 'Sampletown'), ('Lower Sampletown', 'Lower Sampletown'),
    ('Sampletownn', 'Sampletown'),
])
def test_model_spelling_normalization_keeps_the_literal_provider_query(literal, normalized):
    message = 'Hotels in ' + literal
    raw = transaction(message, query=normalized, evidence=literal)
    got = adapt_location_update(raw, message, None)
    areas = validate_areas(got['requested_areas'], message)
    assert areas[0]['query'] == literal and areas[0]['evidence'] == literal
    assert got['location_intent']['action'] == 'change'


def test_spelling_recovery_requires_an_explicit_literal_target_quote():
    raw = {'location_update': {'action': 'change', 'evidence': 'Sampletwn',
           'targets': [{'kind': 'city', 'query': 'Sampletown'}]}}
    assert adapt_location_update(raw, 'Sampletwn', None)['location_intent']['action'] == 'unknown'


@pytest.mark.parametrize('literal,canonical', [('Nyc', 'New York City'), ('Sampletwn', 'Sampletown'), ('Milano', 'Rome')])
def test_explicit_mention_wins_over_untrusted_canonical_label(literal, canonical):
    message = 'Hotels in ' + literal
    raw = transaction(message, query=canonical, evidence=literal)
    got = adapt_location_update(raw, message, None)
    areas = validate_areas(got['requested_areas'], message)
    assert areas[0]['query'] == literal and areas[0]['evidence'] == literal
    assert areas[0]['query'] != canonical
    assert 'latitude' not in areas[0] and 'longitude' not in areas[0]


@pytest.mark.parametrize('nested', [False, True])
def test_inside_neighborhood_parent_placement_is_equivalent(nested):
    message = 'Berlin Mitte'
    raw = {'location_update': {'action': 'change', 'evidence': message, 'targets': [
        {'kind': 'neighborhood', 'query': 'Mitte', 'country': 'DE', 'evidence': message, 'scope': 'inside'}]}}
    owner = raw['location_update']['targets'][0] if nested else raw['location_update']
    owner['parent_city'] = 'Berlin'
    got = adapt_location_update(raw, message, None)
    assert validate_areas(got['requested_areas'], message) == [
        {'query': 'Berlin', 'kind': 'municipality', 'country': 'DE', 'evidence': 'Berlin', 'subarea': 'Mitte'}]
    owner['parent_city'] = 'Invented City'
    got = adapt_location_update(raw, message, None)
    assert got['requested_areas'][0]['query'] == 'Mitte'
    assert 'subarea' not in got['requested_areas'][0]


def test_each_alternative_neighborhood_keeps_its_own_grounded_parent():
    message = 'Berlin Mitte or Paris Marais'
    raw = {'location_update': {'action': 'change', 'evidence': message, 'targets': [
        {'kind': 'neighborhood', 'query': 'Mitte', 'country': 'DE', 'parent_city': 'Berlin'},
        {'kind': 'neighborhood', 'query': 'Marais', 'country': 'FR', 'parent_city': 'Paris'}]}}
    got = adapt_location_update(raw, message, None)
    areas = validate_areas(got['requested_areas'], message)
    assert [(a['query'], a['subarea'], a['country']) for a in areas] == [('Berlin', 'Mitte', 'DE'), ('Paris', 'Marais', 'FR')]


@pytest.mark.parametrize('confirmed,expected', [('Berlin', 'Berlin'), ('Paris', 'Mitte')])
def test_neighborhood_followup_only_reuses_the_provider_confirmed_parent(confirmed, expected):
    raw = {'location_update': {'action': 'change', 'evidence': 'Mitte', 'targets': [
        {'kind': 'neighborhood', 'query': 'Mitte', 'country': 'DE', 'parent_city': 'Berlin'}]}}
    got = adapt_location_update(raw, 'Mitte', {'confirmed_city': confirmed})
    areas = validate_areas(got['requested_areas'], 'Mitte', confirmed_city=confirmed)
    assert areas and areas[0]['query'] == expected
    if expected == 'Berlin':
        assert validate_areas(got['requested_areas'], 'Mitte') is None
        assert validate_areas(got['requested_areas'], 'Other', confirmed_city='Berlin') is None
        assert got['requested_areas'][0]['subarea'] == 'Mitte'
