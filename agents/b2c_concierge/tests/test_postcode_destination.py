"""Postal identity uses provider postcode features, not names of unrelated places."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

import b2c_concierge.agent as concierge
from b2c_common.destination_request import postcode_context_question
from hotel_search_agent import geocode_tool as geo
from hotel_search_agent.mapbox_client import MapboxClient
from hotel_search_agent.response_bridge import capture_after_tool, emit_search_datapart, find_datapart

from .test_address_destination import context
from .test_spine import _drive_in, _new_session, scripted  # noqa: F401

CODE = 'AB12'


def candidate():
    return MapboxClient._parse_candidates({'features': [{'geometry': {'coordinates': [-1.2, 51.5]},
        'properties': {'feature_type': 'postcode', 'mapbox_id': 'provider:postcode:ab12',
            'name': CODE, 'full_address': CODE + ', Example City, United Kingdom',
            'context': {'country': {'country_code': 'GB'},
                'place': {'name': 'Example City', 'mapbox_id': 'provider:city:example'}}}}]})[0]


def test_postcode_provider_scope_is_owned_and_preserves_point_on_followup(monkeypatch):
    calls = []
    def provider(query, **kwargs):
        calls.append((query, kwargs))
        return [candidate()]
    monkeypatch.setattr(geo, 'get_mapbox_client', lambda: SimpleNamespace(geocode_candidates=provider))
    request = {'kind': 'postcode', 'query': CODE, 'city': 'Example City'}
    ctx = context(request=request)
    tool = SimpleNamespace(name='geocode_location')
    args = {'city': 'Wrong City', 'place_kind': 'municipality'}
    assert geo.inject_profile_geo_context(tool, args, ctx) is None
    assert args['place_kind'] == 'postcode' and args['zone'] == CODE
    result = geo.geocode_location(**args)
    assert result['ok'] and result['resolved_feature_type'] == 'postcode'
    assert calls[0][0] == CODE + ', Example City' and calls[0][1]['types'] == 'postcode'
    again = geo.inject_profile_geo_context(tool, {}, context(request=request, confirmed=result['resolved_location']))
    assert again['ok'] and again['longitude'] == -1.2 and len(calls) == 1


@pytest.mark.parametrize('changes', [
    {'feature_type': 'place'}, {'feature_type': 'poi'}, {'name': 'AB123'},
    {'parent_city_name': 'Other City'}, {'country_code': 'CA'}, {'mapbox_id': ''},
])
def test_wrong_postal_identity_is_not_accepted_despite_plausible_coordinates(monkeypatch, changes):
    monkeypatch.setattr(geo, 'get_mapbox_client', lambda: SimpleNamespace(
        geocode_candidates=lambda *a, **kw: [replace(candidate(), **changes)]))
    result = geo.geocode_location(zone=CODE, city='Example City', country_code='GB', place_kind='postcode')
    assert not result['ok'] and result['diagnostics']['reason'] == 'postcode_not_uniquely_verified'


def test_ambiguous_postcode_does_not_choose_provider_first_and_transports_clarification(monkeypatch):
    monkeypatch.setattr(geo, 'get_mapbox_client', lambda: SimpleNamespace(
        geocode_candidates=lambda *a, **kw: [candidate(), replace(candidate(), mapbox_id='other:postcode')]))
    ctx = context(request={'kind': 'postcode', 'query': CODE})
    result = geo.geocode_location(zone=CODE, place_kind='postcode')
    assert not result['ok']
    capture_after_tool(SimpleNamespace(name='geocode_location'), {}, ctx, result)
    payload = find_datapart(emit_search_datapart(ctx).parts)
    assert payload['destination_clarification'] == {'kind': 'postcode_context', 'query': CODE}


def test_city_clarification_does_not_replace_the_postcode(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return 'Invented competing city', {'results': [], 'requires_clarification': True,
            'destination_clarification': {'kind': 'postcode_context', 'query': CODE}}
    monkeypatch.setattr(concierge, '_run_leaf', leaf)
    for text, update in [(CODE, {'action': 'change', 'evidence': CODE,
        'targets': [{'kind': 'postcode', 'query': CODE}]}),
        ('Example City', {'action': 'refine', 'evidence': 'Example City', 'parent_city': 'Example City'})]:
        scripted(json.dumps({'family': 'search', 'language': 'en', 'location_update': update}))
        monkeypatch.setattr(concierge, '_run_leaf', leaf)
        events = _drive_in(runner, session.id, text)
        answer = ' '.join(p.text for e in events if e.content for p in e.content.parts if p.text)
        assert postcode_context_question(CODE, 'en') in answer and 'Invented competing city' not in answer
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.requested_destination == {'kind': 'postcode', 'query': CODE, 'city': 'Example City'}
    assert all(p['requested_destination']['kind'] == 'postcode' for p in seen)


def test_numeric_postcode_reaches_leaf_without_becoming_budget(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    scripted(json.dumps({'family': 'search', 'language': 'en', 'requested_budget': None,
        'location_update': {'action': 'change', 'evidence': '78240', 'targets': [
            {'kind': 'postcode', 'query': '78240'}]}}))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return 'Unresolved', {'results': [], 'requires_clarification': True,
            'destination_clarification': {'kind': 'postcode_context', 'query': '78240'}}
    monkeypatch.setattr(concierge, '_run_leaf', leaf)
    events = _drive_in(runner, session.id, '78240')
    assert len(seen) == 1 and seen[0]['requested_destination']['query'] == '78240'
    assert seen[0].get('budget_max') is None and not seen[0].get('requested_budget')
    answer = ' '.join(p.text for e in events if e.content for p in e.content.parts if p.text)
    assert postcode_context_question('78240', 'en') in answer
