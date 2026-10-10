"""Question ownership survives Redis, without overriding a later conversation topic."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from b2c_concierge import templates
from b2c_concierge.budget import TurnBudget
from b2c_concierge.clarification_state import location_reply_context, remember_location_question
from b2c_concierge.profile import SessionProfile, apply_profile_delta, leaf_profile_view
from b2c_concierge.triage import classify

from .test_spine import _answer, _drive_in, _new_session, scripted  # noqa: F401


def first_location_question(runner, session, install_script):
    install_script(json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'missing', 'evidence': 'for two'},
        'requested_occupancy': {'total': 2, 'evidence': 'two'}}))
    question = _answer(_drive_in(runner, session.id, 'for two'))
    assert question == templates.missing_destination_question('en')
    return question


def test_question_is_private_owned_and_bound_to_the_actual_previous_answer():
    p = SessionProfile()
    remember_location_question(p, 'Which place?', '12')
    p = SessionProfile.from_dict(p.to_dict())
    assert location_reply_context(p, 'Which place?') == {'kind': 'location', 'value': '12'}
    assert location_reply_context(p, 'What is your budget?') is None
    assert location_reply_context(p, None) is None
    assert 'pending_clarification' not in leaf_profile_view(p)
    apply_profile_delta(p, {'pending_clarification': None}, 'same')
    assert p.pending_clarification


@pytest.mark.parametrize('number', ['77', '78240', '2'])
def test_unknown_number_after_location_question_stays_geographic_and_keeps_constraints(scripted, fake_profile_store, number):  # noqa: F811
    runner, session = _new_session()
    p = SessionProfile(requested_budget={'amount': 150, 'currency': 'USD', 'unit': 'total'},
        requested_window={'end': '18:00'}, timeslot_end='18:00', amenities=['pool'])
    asyncio.run(fake_profile_store.set(session.id, p))
    first_location_question(runner, session, scripted)
    llm, leaves = scripted(json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'unknown', 'evidence': number}, 'requested_budget': None}))
    answer = _answer(_drive_in(runner, session.id, number))
    assert answer == templates.numeric_role_clarification('en')
    assert not leaves and len(llm.calls) == 1
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.pending_clarification['value'] == number and saved.pending_party_total == 2
    assert saved.requested_budget == p.requested_budget and saved.timeslot_end == '18:00'
    assert saved.amenities == ['pool'] and saved.requested_destination is None
    assert 'pending_clarification' in llm.calls[0]['messages'][-1]['content']


def test_a_model_budget_cannot_quote_the_location_question_to_gain_provenance(monkeypatch):
    question = 'Which city?'
    async def completion(**kwargs):
        d = {'family': 'search', 'requested_budget': {'amount': 77, 'unit': 'total',
             'currency': 'EUR', 'evidence': '77', 'answer_to': question}, 'bare_budget_value': 77}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(d)))])
    monkeypatch.setattr('b2c_concierge.triage.litellm.acompletion', completion)
    got = asyncio.run(classify('77', TurnBudget(), previous_reply=question,
        location_context={'pending_clarification': {'kind': 'location'}}))
    assert got.requested_budget is None and got.bare_budget_value is None
    assert got.unclassified_numeric_input and got.budget_checked


def test_explicit_budget_can_still_change_the_topic(monkeypatch):
    async def completion(**kwargs):
        d = {'family': 'search', 'requested_budget': {'amount': 90, 'unit': 'total',
             'currency': 'USD', 'evidence': '90 USD'}}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(d)))])
    monkeypatch.setattr('b2c_concierge.triage.litellm.acompletion', completion)
    got = asyncio.run(classify('90 USD', TurnBudget(), previous_reply='Which city?',
        location_context={'pending_clarification': {'kind': 'location'}}))
    assert got.requested_budget['amount'] == 90 and got.requested_budget['currency'] == 'USD'


def test_an_intervening_answer_expires_question_ownership(scripted, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    first_location_question(runner, session, scripted)
    scripted(json.dumps({'family': 'faq', 'language': 'en'}), 'Here is the general policy.')
    _drive_in(runner, session.id, 'What is the general cancellation policy?')
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.pending_clarification is None
    scripted(json.dumps({'family': 'search', 'language': 'en', 'requested_budget': None}))
    assert _answer(_drive_in(runner, session.id, '200')) == templates.numeric_role_clarification('en')


def test_explicit_region_after_numeric_clarification_is_kept_while_party_is_pending(scripted, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    first_location_question(runner, session, scripted)
    scripted(json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'unknown', 'evidence': '12'}}))
    _drive_in(runner, session.id, '12')
    message = 'Example Province'
    scripted(json.dumps({'family': 'search', 'language': 'en', 'location_update': {
        'action': 'change', 'evidence': message, 'targets': [{'kind': 'region', 'query': message, 'country': 'GB'}]}}), response={'results': []})
    answer = _answer(_drive_in(runner, session.id, message))
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.requested_destination['areas'][0]['query'] == message
    assert saved.pending_clarification is None and saved.pending_party_total == 2
    assert 'adults' in answer and 'children' in answer


def test_geographic_number_cannot_select_an_old_hotel(scripted, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    p = SessionProfile(last_results=[{'hotel_id': 42, 'name': 'Old hotel'}],
        pending_booking={'hotel_id': 42, 'offer_id': 'old-offer'})
    asyncio.run(fake_profile_store.set(session.id, p))
    first_location_question(runner, session, scripted)
    llm, leaves = scripted(json.dumps({'family': 'booking', 'language': 'en',
        'pick': 'position', 'pick_position': 1, 'booking_confirmation': 'confirmed',
        'location_update': {'action': 'unknown', 'evidence': '1'}}))
    answer = _answer(_drive_in(runner, session.id, '1'))
    assert answer == templates.numeric_role_clarification('en')
    assert not leaves and len(llm.calls) == 1


def test_spoken_ordinal_after_location_question_cannot_choose_an_old_hotel(scripted, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    p = SessionProfile(last_results=[{'hotel_id': 42, 'name': 'Old hotel'}],
        pending_booking={'hotel_id': 42, 'offer_id': 'old-offer'})
    asyncio.run(fake_profile_store.set(session.id, p))
    first_location_question(runner, session, scripted)
    llm, leaves = scripted(json.dumps({'family': 'details', 'language': 'en',
        'pick': 'position', 'pick_position': 1, 'location_update': {'action': 'preserve'}}))
    answer = _answer(_drive_in(runner, session.id, 'Tell me about the first option'))
    assert answer == templates.ambiguous_place_or_hotel_question('en')
    assert not leaves and len(llm.calls) == 1
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.pending_booking is None and saved.pending_clarification['kind'] == 'location'
