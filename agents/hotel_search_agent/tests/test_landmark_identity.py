"""A resolved provider POI must survive a follow-up without becoming a city."""
from types import SimpleNamespace

import httpx
import pytest
from google.genai import types

from b2c_common.confirmed_location import verified_place
from b2c_concierge.location_state import receive_location
from b2c_concierge.profile import SessionProfile, leaf_profile_view
from hotel_search_agent import geocode_tool
from hotel_search_agent.response_bridge import capture_after_tool, emit_search_datapart, find_datapart, inject_landmark_radius
from hotel_search_agent.searchbox_client import SearchBoxClient

PAYLOAD = {"features": [{"geometry": {"coordinates": [16.5697, 48.1103]},
    "properties": {"mapbox_id": "provider:airport-vienna", "name": "Vienna International Airport",
        "feature_type": "poi", "full_address": "Schwechat, Austria",
        "context": {"country": {"country_code": "at"}, "region": {"name": "Lower Austria"}}}}]}


def _resolved(monkeypatch):
    box = SearchBoxClient("offline", client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=PAYLOAD))))
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: SimpleNamespace(geocode_candidates=lambda *a, **kw: []))
    return geocode_tool.geocode_location(city="Schwechat", zone="Vienna International Airport", country_code="AT")


def test_provider_poi_to_concierge_and_back_preserves_identity_and_radius(monkeypatch):
    from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part, convert_genai_part_to_a2a_part
    result = _resolved(monkeypatch)
    assert result["ok"]
    place = result.get("resolved_location")
    assert place and place["provider_id"] == "provider:airport-vienna"
    ctx = SimpleNamespace(state={}, user_content=None)
    tool = SimpleNamespace(name="geocode_location")
    capture_after_tool(tool, {}, ctx, result)
    parts = [convert_a2a_part_to_genai_part(convert_genai_part_to_a2a_part(p)) for p in emit_search_datapart(ctx).parts]
    profile = SessionProfile(date="2026-11-01", timeslot_start="13:00", timeslot_end="18:00")
    receive_location(profile, find_datapart(parts))
    assert profile.city == "Schwechat" and profile.zone == "Vienna International Airport"
    assert profile.confirmed_location == place
    content = types.Content(role="user", parts=[types.Part(text="Under 90 euros")])
    # Use the same DataPart conversion as production, including the owned profile.
    from a2a import types as a2a_types
    content.parts.append(convert_a2a_part_to_genai_part(a2a_types.Part(root=a2a_types.DataPart(data={
        "profile_in": leaf_profile_view(profile), "query_params": {}}))))
    follow = SimpleNamespace(state={}, user_content=content)
    reused = geocode_tool.inject_profile_geo_context(tool, {"city": "Schwechat", "zone": profile.zone}, follow)
    assert reused and reused["resolved_location"] == place
    assert reused["distance_origin_type"] == "poi"
    capture_after_tool(tool, {}, follow, reused)
    args = {"radiusKm": 20}
    inject_landmark_radius(SimpleNamespace(name="search_offers"), args, follow)
    assert reused["latitude"] == 48.1103 and reused["longitude"] == 16.5697
    assert args["radiusKm"] == 3
    assert profile.timeslot_start == "13:00" and profile.timeslot_end == "18:00"


@pytest.mark.parametrize("change", [{"city": "Paris"}, {"zone": "Other airport"}, {"origin": "device"}, {"country_code": "FR"}])
def test_a_changed_destination_does_not_reuse_old_poi(monkeypatch, change):
    result = _resolved(monkeypatch)
    assert result.get("resolved_location")
    from a2a import types as a2a_types
    from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
    profile = SessionProfile()
    receive_location(profile, result)
    ctx = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[types.Part(text="New destination"),
        convert_a2a_part_to_genai_part(a2a_types.Part(root=a2a_types.DataPart(data={"profile_in": leaf_profile_view(profile)})))]))
    args = {"city": profile.city, "zone": profile.zone, **change}
    reused = geocode_tool.inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, ctx)
    assert not reused or reused.get("resolved_location") != result["resolved_location"]


def test_poi_without_provider_id_or_search_context_cannot_be_committed(monkeypatch):
    place = _resolved(monkeypatch).get("resolved_location")
    assert place
    assert verified_place({**place, "provider_id": ""}) is None
    assert verified_place({**place, "search_context": None}) is None


@pytest.mark.parametrize('parser', ['geocoding', 'searchbox'])
def test_provider_parent_survives_poi_storage_and_authorizes_street_refinement(parser):
    import copy
    from b2c_common.confirmed_location import context_for_triage, grounded_landmark
    from hotel_search_agent.mapbox_client import MapboxClient
    payload = copy.deepcopy(PAYLOAD)
    payload['features'][0]['properties']['context']['place'] = {'id': 'provider:schwechat', 'name': 'Schwechat'}
    if parser == 'geocoding':
        candidate = MapboxClient._parse_candidates(payload)[0]
    else:
        candidate = SearchBoxClient._parse(payload, fallback='ignored')[0]
    place = geocode_tool._provider_place(candidate, city='Vienna', zone=candidate.name)
    assert place['provider_city'] == {'name': 'Schwechat', 'provider_id': 'provider:schwechat'}
    profile = SessionProfile()
    receive_location(profile, {'resolved_location': place})
    stored = SessionProfile.from_dict(profile.to_dict())
    context = context_for_triage(None, stored.confirmed_location)
    assert context['confirmed_city'] == 'Schwechat'  # Provider parent, not request city Vienna.
    update = grounded_landmark({'query': 'Main Street', 'city': 'Schwechat',
        'country_guess': 'AT', 'evidence': 'Main Street'}, 'Main Street',
        confirmed_city=context['confirmed_city'], confirmed_country=context['country'])
    assert update['city'] == 'Schwechat'
    assert grounded_landmark({'query': 'Main Street', 'city': 'Vienna',
        'country_guess': 'AT', 'evidence': 'Main Street'}, 'Main Street',
        confirmed_city=context['confirmed_city'], confirmed_country=context['country'])['city'] is None


@pytest.mark.parametrize('parent', [None, {}, {'name': 'Schwechat'}, {'name': 'Schwechat', 'provider_id': ''}])
def test_unproven_poi_parent_does_not_authorize_city_inheritance(parent):
    from b2c_common.confirmed_location import context_for_triage
    place = {'provider_id': 'provider:airport', 'name': 'Airport', 'label': 'Airport, Vienna, Austria',
        'country_code': 'AT', 'feature_type': 'poi', 'latitude': 48.1, 'longitude': 16.5,
        'search_context': {'city': 'Vienna', 'zone': 'Airport'}, 'provider_city': parent}
    assert context_for_triage(None, place)['confirmed_city'] is None


def test_owned_municipality_fallback_retains_geographic_type(monkeypatch):
    from hotel_search_agent.mapbox_client import GeocodeCandidate
    common = dict(latitude=48.1, longitude=16.5, place_formatted='Austria', country_code='AT', region='', bbox=None)
    business = GeocodeCandidate(**common, name='Schwechat', place_name='Schwechat Business, Austria',
                                feature_type='poi', rank=0, mapbox_id='provider:business')
    city = GeocodeCandidate(**common, name='Schwechat', place_name='Schwechat, Austria',
                            feature_type='place', rank=1, mapbox_id='provider:city')
    monkeypatch.setattr(geocode_tool, 'get_mapbox_client', lambda: SimpleNamespace(geocode_candidates=lambda *a, **kw: []))
    monkeypatch.setattr(geocode_tool, 'get_searchbox_client', lambda: SimpleNamespace(forward_candidates=lambda *a, **kw: [business, city]))
    result = geocode_tool.geocode_location(city='Schwechat', country_code='AT', place_kind='municipality')
    assert result['ok'] and result['resolved_location']['provider_id'] == 'provider:city'
    assert result['distance_origin_type'] == 'city_centroid'
    monkeypatch.setattr(geocode_tool, 'get_searchbox_client', lambda: SimpleNamespace(forward_candidates=lambda *a, **kw: [business]))
    assert geocode_tool.geocode_location(city='Schwechat', country_code='AT', place_kind='municipality')['ok'] is False
    # A real landmark request still uses the same provider business taxonomy.
    from dataclasses import replace
    airport = replace(business, name='Vienna International Airport', place_name='Vienna International Airport, Schwechat, Austria')
    monkeypatch.setattr(geocode_tool, 'get_searchbox_client', lambda: SimpleNamespace(forward_candidates=lambda *a, **kw: [airport]))
    assert geocode_tool.geocode_location(city='Schwechat', zone=airport.name, country_code='AT')['ok'] is True
