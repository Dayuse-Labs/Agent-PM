"""Missing location precedes party composition without discarding either."""
import asyncio
import json

import b2c_concierge.agent as module
from b2c_concierge.profile import SessionProfile

from .test_spine import _drive_in, _new_session, scripted  # noqa: F401


def answer(events):
    return ' '.join(p.text for e in events if e.content for p in e.content.parts if p.text)


def test_total_survives_location_then_composition_clarification(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    async def no_inventory(*args, **kwargs):
        raise AssertionError('No inventory search until the composition is known')
    monkeypatch.setattr(module, '_run_leaf', no_inventory)
    scripted(json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'missing', 'evidence': 'for two'},
        'requested_occupancy': {'total': 2, 'evidence': 'two'}}))
    first = answer(_drive_in(runner, session.id, 'for two'))
    assert 'Which city' in first and 'children' not in first
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.pending_party_total == 2 and profile.adults is None and profile.children is None
    scripted(json.dumps({'family': 'search', 'language': 'en', 'location_update': {
        'action': 'change', 'evidence': 'Example City', 'targets': [
            {'kind': 'city', 'query': 'Example City'}]}}))
    second = answer(_drive_in(runner, session.id, 'Example City'))
    assert 'adults' in second and 'children' in second and 'Which city' not in second
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.city == 'Example City' and profile.pending_party_total == 2


def test_existing_place_keeps_party_question_first(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city='Example City')))
    scripted(json.dumps({'family': 'search', 'language': 'en',
        'requested_occupancy': {'total': 3, 'evidence': 'three'},
        'location_update': {'action': 'preserve'}}))
    text = answer(_drive_in(runner, session.id, 'we are three'))
    assert 'adults' in text and 'children' in text and 'Which city' not in text
