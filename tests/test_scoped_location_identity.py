"""Provider identity must survive a scoped search and the next budget turn."""
import asyncio
from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part, convert_genai_part_to_a2a_part
from google.genai import types

from b2c_common.confirmed_location import verified_place
from b2c_concierge.location_state import receive_location
from b2c_concierge.profile import SessionProfile, leaf_profile_view
from hotel_search_agent import geocode_tool
from hotel_search_agent.mapbox_client import GeocodeCandidate
from hotel_search_agent.owned_origin_plan import prepare_owned_origin, reuse_owned_origin
from hotel_search_agent.response_bridge import capture_after_tool, emit_search_datapart, enforce_resolved_search_origin, find_datapart


def context(profile=None, params=None):
    part = a2a_types.Part(root=a2a_types.DataPart(data={
        'profile_in': profile or {}, 'query_params': params or {},
    }))
    return SimpleNamespace(state={}, invocation_id='scoped-location', user_content=types.Content(
        role='user', parts=[types.Part(text='Daytime. Up to $125'), convert_a2a_part_to_genai_part(part)],
    ))


@pytest.mark.parametrize('feature_type', ['place', 'locality'])
def test_scoped_provider_identity_crosses_a2a_and_prepares_followup_without_geocoding(monkeypatch, feature_type):
    candidate = GeocodeCandidate(latitude=37.624871, longitude=-122.414612,
        name='San Bruno', place_name='San Bruno, California, United States', place_formatted='California, United States',
        feature_type=feature_type, country_code='US', region='California', bbox=None, rank=0,
        mapbox_id='provider:san-bruno', administrative_code='CA')
    client = SimpleNamespace(geocode_candidates=lambda *a, **kw: [candidate])
    monkeypatch.setattr(geocode_tool, 'get_mapbox_client', lambda: client)
    result = geocode_tool.geocode_location(city='San Bruno', zone='San Bruno', country_code='US')
    assert result['ok'] and result['resolved_location']['feature_type'] == feature_type
    assert result['resolved_location']['search_context']['zone'] == 'San Bruno'
    ctx = context()
    capture_after_tool(SimpleNamespace(name='geocode_location'), {}, ctx, result)
    wire = emit_search_datapart(ctx)
    parts = [convert_a2a_part_to_genai_part(convert_genai_part_to_a2a_part(p)) for p in wire.parts]
    payload = find_datapart(parts)
    profile = SessionProfile()
    receive_location(profile, payload)
    assert profile.city == profile.zone == 'San Bruno'
    assert profile.confirmed_location['provider_id'] == candidate.mapbox_id
    def forbid():
        raise AssertionError('An unchanged verified scope must not be geocoded again')
    monkeypatch.setattr(geocode_tool, 'get_mapbox_client', forbid)
    following = context(leaf_profile_view(profile), {'reuse_confirmed_location': True})
    asyncio.run(prepare_owned_origin(following))
    # The actual leaf attempted device mode on the budget-only follow-up.
    cached = reuse_owned_origin(SimpleNamespace(name='geocode_location'), {'origin': 'device', 'city': 'San Bruno'}, following)
    assert cached['resolved_location'] == profile.confirmed_location
    args = {'lat': 0, 'lon': 0}
    assert enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), args, following) is None
    assert args == {'lat': candidate.latitude, 'lon': candidate.longitude}


@pytest.mark.parametrize('bad_scope', [None, {}, {'zone': 12}, {'zone': 'San Bruno', 'city': []}])
def test_malformed_scoped_provider_identity_is_not_authority(bad_scope):
    place = {'provider_id': 'provider:one', 'name': 'San Bruno', 'label': 'San Bruno, US',
        'feature_type': 'poi', 'country_code': 'US', 'latitude': 37.6, 'longitude': -122.4,
        'search_context': bad_scope}
    assert verified_place(place) is None


def test_changed_scope_cannot_reuse_previous_provider_identity():
    place = {'provider_id': 'provider:one', 'name': 'San Bruno', 'label': 'San Bruno, US',
        'feature_type': 'place', 'country_code': 'US', 'region': 'California',
        'latitude': 37.6, 'longitude': -122.4,
        'search_context': {'city': 'San Bruno', 'zone': 'San Bruno', 'metro': None}}
    ctx = context({'confirmed_location': place, 'city': 'San Bruno', 'zone': 'Station X'},
                  {'reuse_confirmed_location': True})
    args = {'city': 'San Bruno', 'zone': 'Station X'}
    assert geocode_tool.inject_profile_geo_context(SimpleNamespace(name='geocode_location'), args, ctx) is None
    assert args['zone'] == 'Station X'
