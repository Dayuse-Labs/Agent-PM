"""A semantic distance relaxation reaches A2A while unrelated constraints survive."""
import asyncio
import json

import b2c_concierge.agent as module
from b2c_concierge.profile import SessionProfile

from .test_spine import _drive_in, _new_session, scripted  # noqa: F401


def test_parent_radius_relaxation_clears_failed_subarea_and_keeps_hours_budget(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    original = {'kind': 'areas', 'areas': [{'kind': 'municipality', 'query': 'Example City',
        'country': 'GB', 'evidence': 'Example City', 'subarea': 'east side'}]}
    p = SessionProfile(city='Example City', requested_destination=original, search_areas=original['areas'],
        requested_window={'end': '24:00'}, timeslot_end='24:00', date='2027-01-12',
        requested_budget={'amount': 150, 'currency': 'GBP', 'unit': 'total'}, amenities=['pool'], adults=2)
    asyncio.run(fake_profile_store.set(session.id, p))
    scripted(json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'preserve'}, 'requested_proximity': {
            'distance': 30, 'unit': 'km', 'anchor': 'parent_city', 'evidence': 'also within 30 km'}}))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return '', {'results': [], 'search_context': {'city': 'Example City', 'date': '2027-01-12',
            'timeslot_end': '24:00', 'radius_km': 30., 'radius_origin': 'Example City', 'adults': 2}}
    monkeypatch.setattr(module, '_run_leaf', leaf)
    events = _drive_in(runner, session.id, 'also within 30 km')
    assert len(seen) == 1
    sent = seen[0]
    request = sent['requested_destination']
    assert request['radius_km'] == 30 and 'subarea' not in request['areas'][0]
    assert sent['timeslot_end'] == '24:00' and sent['date'] == '2027-01-12'
    assert sent['requested_budget'] == p.requested_budget and sent['amenities'] == ['pool']
    assert sent['search_areas'] is None and sent['zone'] is None
    text = ' '.join(part.text for event in events if event.content for part in event.content.parts if part.text)
    assert '30 km' in text and 'mapped point' in text


def test_distance_without_origin_survives_until_city_answer(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    scripted(json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'missing', 'evidence': 'within 30 km'},
        'requested_proximity': {'distance': 30, 'unit': 'km', 'anchor': 'current', 'evidence': '30 km'}}))
    first = _drive_in(runner, session.id, 'within 30 km')
    assert any('From which city' in (p.text or '') for e in first if e.content for p in e.content.parts)
    assert asyncio.run(fake_profile_store.get(session.id)).pending_proximity['radius_km'] == 30.
    scripted(json.dumps({'family': 'search', 'language': 'en', 'location_update': {
        'action': 'change', 'evidence': 'Example City', 'targets': [{'kind': 'city', 'query': 'Example City'}]}}))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return 'No inventory', {'results': [], 'search_context': {'city': 'Example City'}}
    monkeypatch.setattr(module, '_run_leaf', leaf)
    _drive_in(runner, session.id, 'Example City')
    assert seen[0]['requested_destination']['radius_km'] == 30.
    assert asyncio.run(fake_profile_store.get(session.id)).pending_proximity is None
