"""Grounded distance changes preserve filters and never invent a point origin."""
from types import SimpleNamespace

import pytest
from google.genai import types

from b2c_common.destination_request import destination_request, refine_landmark
from b2c_common.proximity_request import apply_proximity, grounded_proximity, proximity_notice
from b2c_concierge.profile import SessionProfile, apply_profile_delta, pagination_search_key
from hotel_search_agent.response_bridge import encode_datapart, inject_landmark_radius


def area(subarea=None):
    return {'kind': 'areas', 'areas': [{'kind': 'municipality', 'query': 'Example City',
            'country': 'GB', 'evidence': 'Example City', **({'subarea': subarea} if subarea else {})}]}


@pytest.mark.parametrize('quote,amount,unit,expected', [('within 30 km', 30, 'km', 30.),
    ('within 10 miles', 10, 'mi', 16.09344), ('entro 2,5 chilometri', 2.5, 'km', 2.5)])
def test_explicit_unit_is_converted_in_code(quote, amount, unit, expected):
    assert grounded_proximity({'distance': amount, 'unit': unit, 'anchor': 'current',
        'evidence': quote}, quote) == {'radius_km': expected, 'anchor': 'current'}


@pytest.mark.parametrize('value,message', [
    ({'distance': 3, 'unit': 'km', 'anchor': 'current', 'evidence': '30 km'}, '30 km'),
    ({'distance': 30, 'unit': 'km', 'anchor': 'current', 'evidence': '30 dollars'}, '30 dollars'),
    ({'distance': 30, 'unit': 'km', 'anchor': 'current', 'evidence': '30 minutes'}, '30 minutes'),
    ({'distance': True, 'unit': 'km', 'anchor': 'current', 'evidence': '1 km'}, '1 km'),
    ({'distance': 300, 'unit': 'km', 'anchor': 'current', 'evidence': '300 km'}, '300 km'),
    ({'distance': 30, 'unit': ['km'], 'anchor': 'current', 'evidence': '30 km'}, '30 km'),
    ({'distance': 30, 'unit': 'km', 'anchor': ['current'], 'evidence': '30 km'}, '30 km'),
    ({'distance': 30, 'unit': 'km', 'anchor': 'current', 'evidence': '30 km'}, 'same place'),
])
def test_ungrounded_or_non_distance_values_do_not_authorize_geometry(value, message):
    assert grounded_proximity(value, message) is None


def test_parent_relaxation_requires_a_known_parent_and_does_not_infer_one_from_language():
    update = {'radius_km': 30., 'anchor': 'parent_city'}
    got = apply_proximity(area('east district'), update)
    assert got and got.areas == area()['areas'] and got.radius_km == 30.
    assert apply_proximity({'kind': 'landmark', 'query': 'River Gate'}, update) is None
    assert apply_proximity(None, update) is None
    # Merely specifying a distance around the current boundary cannot discard it.
    assert apply_proximity(area('east district'), {'radius_km': 30., 'anchor': 'current'}) is None


def test_a_radius_cannot_be_attached_to_multiple_or_strict_area_origins():
    for value in ({'kind': 'hotel', 'query': 'Example Hotel'}, area('east district')):
        assert destination_request({**value, 'radius_km': 30}) is None


@pytest.mark.parametrize('kind', ['landmark', 'postcode', 'address'])
def test_current_point_keeps_identity_and_mcp_cannot_override_owned_radius(kind):
    request = {'kind': kind, 'query': 'Example Place'}
    got = apply_proximity(request, {'radius_km': 30., 'anchor': 'current'})
    assert got and got.kind == kind and got.query == request['query']
    ctx = SimpleNamespace(state={'temp:hotel_search_anchor': {'type': 'poi'}},
        user_content=types.Content(role='user', parts=[encode_datapart({'profile_in': {
            'requested_destination': got.model_dump(exclude_none=True)}})]))
    # Use the actual bridge-owned key; a stale distance-origin result is not enough.
    from hotel_search_agent.response_bridge import _STATE_ANCHOR_KEY
    ctx.state = {_STATE_ANCHOR_KEY: {'type': 'poi'}}
    args = {'radiusKm': 199}
    inject_landmark_radius(SimpleNamespace(name='search_offers'), args, ctx)
    assert args['radiusKm'] == 30
    ctx.state = {}
    inject_landmark_radius(SimpleNamespace(name='search_offers'), args, ctx)
    assert 'radiusKm' not in args


def test_radius_changes_pagination_and_pending_intent_is_concierge_owned():
    p = SessionProfile(requested_destination=area(), pending_proximity={'radius_km': 30., 'anchor': 'current'})
    before = pagination_search_key(p)
    p.requested_destination = {**area(), 'radius_km': 30.}
    assert pagination_search_key(p) != before
    apply_profile_delta(p, {'pending_proximity': None, 'requested_destination': area()}, 'same')
    assert p.pending_proximity and p.requested_destination['radius_km'] == 30.
    assert SessionProfile.from_dict(p.to_dict()).pending_proximity == p.pending_proximity


def test_radius_notice_requires_an_executed_origin_not_only_an_unapplied_request():
    assert proximity_notice({'radius_km': 30}, 'en') == ''
    assert 'mapped point' in proximity_notice({'radius_km': 30, 'radius_origin': 'Example City'}, 'en')


def test_search_context_discloses_radius_only_when_actual_tool_radius_matches():
    from hotel_search_agent.response_bridge import _search_context, _STATE_ANCHOR_KEY, _STATE_RADIUS_KEY
    profile = {'requested_destination': {**area(), 'radius_km': 30.}}
    state = {_STATE_ANCHOR_KEY: {'type': 'city_centroid', 'label': 'Provider City'}, _STATE_RADIUS_KEY: 30.}
    actual = _search_context(state, {}, profile, None)
    assert actual['radius_origin'] == 'Provider City' and actual['radius_km'] == 30.
    state[_STATE_RADIUS_KEY] = 20.
    assert 'radius_origin' not in _search_context(state, {}, profile, None)


def test_parent_clarification_preserves_distance_but_new_destination_does_not_inherit_it():
    prior = {'kind': 'postcode', 'query': 'AB12', 'radius_km': 30.}
    clarified = refine_landmark(None, prior, 'refine', 'Example City')
    assert clarified and clarified['radius_km'] == 30. and clarified['kind'] == 'postcode'
    repeated = refine_landmark({'kind': 'postcode', 'query': 'AB12'}, prior, 'refine', 'Example City')
    assert repeated and repeated['radius_km'] == 30.
    changed = refine_landmark({'query': 'Another Landmark'}, prior, 'change', None)
    assert changed and 'radius_km' not in changed


@pytest.mark.parametrize('origin,expected', [('gps', 30), ('poi', 3), ('city_centroid', None), (None, None)])
def test_explicit_device_radius_requires_a_verified_device_origin(origin, expected):
    from hotel_search_agent.response_bridge import _STATE_ANCHOR_KEY, _POI_RADIUS_KM
    request = apply_proximity({'kind': 'device'}, {'radius_km': 30., 'anchor': 'current'})
    assert request is not None and request.radius_km == 30
    ctx = SimpleNamespace(state={_STATE_ANCHOR_KEY: {'type': origin}},
        user_content=types.Content(role='user', parts=[encode_datapart({'profile_in': {
            'requested_destination': request.model_dump(exclude_none=True)}})]))
    args = {'radiusKm': 199}
    inject_landmark_radius(SimpleNamespace(name='search_offers'), args, ctx)
    assert args.get('radiusKm') == (_POI_RADIUS_KM if origin == 'poi' else expected)


def test_default_device_search_does_not_acquire_a_radius_or_model_location():
    assert destination_request({'kind': 'device'}).radius_km is None
    assert destination_request({'kind': 'device', 'query': 'invented', 'radius_km': 30}) is None
