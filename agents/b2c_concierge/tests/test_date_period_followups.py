"""Real-journey failure shape: multi-day intent cannot become a next-day offer."""
import asyncio
import json
from datetime import date

import pytest
from google.adk.runners import InMemoryRunner

from b2c_common.date_period import grounded_period, freeze_period, weekday_in_period
from b2c_concierge.agent import root_agent
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.profile import SessionProfile, apply_profile_delta, leaf_profile_view
from .test_spine_profile import _scripted_llm, _new_session, _run_turn, fake_leg  # noqa: F401


@pytest.fixture
def friday(monkeypatch):
    monkeypatch.setattr('b2c_concierge.agent.reference_today', lambda _: date(2026, 10, 9))


def setup_period(monkeypatch, store, *, message='next week', kind='next_week', extra=None):
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    profile = SessionProfile(city='Example City', date='2026-10-09',
        requested_budget={'amount': 150, 'currency': 'CAD', 'unit': 'total'},
        requested_window={'start': '10:30', 'end': '16:00'}, timeslot_start='10:30', timeslot_end='16:00',
        adults=2, children=0, amenities=['pool'])
    asyncio.run(store.set(session.id, profile))
    script = {'family': 'search', 'language': 'en',
        'requested_date_period': {'kind': kind, 'evidence': message, **({'scope': 'dates'} if kind == 'flexible' else {})}, **(extra or {})}
    llm = _scripted_llm(monkeypatch, json.dumps(script))
    answer = _run_turn(runner, session.id, message)
    return runner, session, profile, answer, llm


def test_period_is_grounded_private_and_cannot_be_changed_by_leaf():
    assert grounded_period({'kind': 'next_week', 'evidence': 'next week'}, 'next week')
    assert grounded_period({'kind': 'tomorrow', 'evidence': 'next week'}, 'next week') is None
    assert grounded_period({'kind': 'next_week', 'evidence': 'not quoted'}, 'next week') is None
    p = SessionProfile(pending_date_period=freeze_period({'kind': 'next_week', 'evidence': 'next week'}, date(2026, 10, 9)))
    p = SessionProfile.from_dict(p.to_dict())
    assert 'pending_date_period' not in leaf_profile_view(p)
    apply_profile_delta(p, {'pending_date_period': {'op': 'clear'}}, 'same')
    assert p.pending_date_period['start'] == '2026-10-12'
    assert weekday_in_period(p.pending_date_period, 'sunday', date(2026, 10, 10)) == '2026-10-18'
    assert weekday_in_period(p.pending_date_period, 'monday', date(2026, 10, 20)) is None


@pytest.mark.parametrize('message,kind', [('next week', 'next_week'), ('this week', 'this_week'),
    ('dates are flexible', 'flexible'), ('October 12 through 18', 'range')])
def test_multiday_question_cannot_dispatch_today_or_tomorrow(monkeypatch, fake_leg, fake_profile_store, friday, message, kind):  # noqa: F811
    runner, session, original, answer, llm = setup_period(monkeypatch, fake_profile_store, message=message, kind=kind)
    assert fake_leg.call_count == 0 and len(llm.calls) == 1
    assert 'Which specific date' in answer and message in answer
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.date is None and saved.pending_date_period['kind'] == kind
    assert saved.city == original.city and saved.requested_budget == original.requested_budget
    assert saved.requested_window == original.requested_window and saved.amenities == ['pool']
    assert saved.adults == 2 and saved.children == 0


def test_endpoint_extraction_does_not_reduce_a_range_to_one_date(monkeypatch, fake_leg, fake_profile_store, friday):  # noqa: F811
    _, session, _, answer, _ = setup_period(monkeypatch, fake_profile_store,
        message='October 12 through 18', kind='range',
        extra={'requested_calendar': {'day': 12, 'month': 10, 'evidence': 'October 12'}})
    assert fake_leg.call_count == 0 and 'Which specific date' in answer
    assert asyncio.run(fake_profile_store.get(session.id)).date is None


def test_filters_and_location_followups_keep_period_then_weekday_selects_inside_it(monkeypatch, fake_leg, fake_profile_store, friday):  # noqa: F811
    runner, session, original, _, _ = setup_period(monkeypatch, fake_profile_store)
    llm = _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'requested_budget': {'amount': 100, 'currency': 'CAD', 'unit': 'total', 'evidence': '100 CAD'}}))
    assert 'Which specific date' in _run_turn(runner, session.id, 'under 100 CAD')
    assert 'DATE CONTEXT' in llm.calls[0]['messages'][-1]['content']
    assert fake_leg.call_count == 0
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'change', 'evidence': 'Another City',
                            'targets': [{'kind': 'city', 'query': 'Another City', 'country': 'CA'}]}}))
    _run_turn(runner, session.id, 'Another City')
    assert fake_leg.call_count == 0
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'requested_weekday': {'value': 'sunday', 'evidence': 'Sunday'}}), 'Matching offers.')
    fake_leg.response_payload = {'results': [], 'profile_delta': {}}
    _run_turn(runner, session.id, 'Sunday')
    assert fake_leg.call_count == 1
    outgoing = find_datapart(fake_leg.seen_outgoing_parts)['profile_in']
    assert outgoing['date'] == '2026-10-18'  # Not nearest Sunday, 2026-10-11.
    assert outgoing['city'] == 'Another City' and outgoing['requested_budget']['amount'] == 100
    assert outgoing['requested_window'] == original.requested_window
    assert 'pending_date_period' not in outgoing
    assert asyncio.run(fake_profile_store.get(session.id)).pending_date_period is None


def test_explicit_new_calendar_date_replaces_unresolved_period(monkeypatch, fake_leg, fake_profile_store, friday):  # noqa: F811
    runner, session, _, _, _ = setup_period(monkeypatch, fake_profile_store)
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'requested_calendar': {'day': 22, 'month': 10, 'evidence': 'October 22'}}), 'Matching offers.')
    fake_leg.response_payload = {'results': [], 'profile_delta': {}}
    _run_turn(runner, session.id, 'Actually October 22 instead')
    assert find_datapart(fake_leg.seen_outgoing_parts)['profile_in']['date'] == '2026-10-22'
    assert asyncio.run(fake_profile_store.get(session.id)).pending_date_period is None


def test_pending_period_prevents_ordinal_from_reusing_old_date(monkeypatch, fake_leg, fake_profile_store, friday):  # noqa: F811
    runner, session, _, _, _ = setup_period(monkeypatch, fake_profile_store)
    saved = asyncio.run(fake_profile_store.get(session.id))
    saved.last_results = [{'hotel_id': 123, 'name': 'Old result'}]
    asyncio.run(fake_profile_store.set(session.id, saved))
    _scripted_llm(monkeypatch, json.dumps({'family': 'details', 'language': 'en',
        'pick': 'position', 'pick_position': 1}))
    answer = _run_turn(runner, session.id, 'Tell me about the first one')
    assert 'Which specific date' in answer and fake_leg.call_count == 0


@pytest.mark.parametrize('period_evidence', [
    'on October 31 and then do another one from like 8 AM to 2 PM on the November 1',
    'on October 31 and then do another one ... on the November 1',
])
@pytest.mark.parametrize('budget_text', ['under $150', 'under 150'])
def test_two_dates_survive_earlier_budget_clarification(monkeypatch, fake_leg, fake_profile_store, friday, period_evidence, budget_text):  # noqa: F811
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    message = f'Looking for a room {budget_text} want to arrive 9 AM to 3 PM on October 31 and then do another one from like 8 AM to 2 PM on the November 1'
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'requested_budget': {'amount': 150, 'currency': None, 'unit': 'total', 'evidence': budget_text},
        'requested_date_period': {'kind': 'range', 'evidence': period_evidence}}))
    first = _run_turn(runner, session.id, message)
    assert fake_leg.call_count == 0
    # PR134-FIX B3: an unwritten unit is the display currency (EUR), never a
    # question — the pending period is what still needs asking, either way.
    assert 'Which specific date' in first
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.pending_date_period is not None and profile.date is None
    assert profile.pending_date_period['kind'] == ('range' if period_evidence in message else 'unresolved')
    assert '...' not in profile.pending_date_period['evidence']
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'change', 'evidence': 'New York', 'targets': [
            {'kind': 'city', 'query': 'New York', 'country': 'US', 'scope': 'nearby'}]}}))
    _run_turn(runner, session.id, 'New York')
    assert fake_leg.call_count == 0
    assert asyncio.run(fake_profile_store.get(session.id)).date is None


def test_calendar_date_survives_budget_currency_question(monkeypatch, fake_leg, fake_profile_store, friday):  # noqa: F811
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    # PR134-FIX B3: a bare "under 150" no longer asks (display currency); an
    # hourly amount still does — the unit cannot be assumed.
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'requested_budget': {'amount': 10, 'currency': None, 'unit': 'hour', 'evidence': '10 per hour'},
        'requested_calendar': {'month': 10, 'day': 31, 'evidence': 'October 31'}}))
    first = _run_turn(runner, session.id, 'A day room on October 31 at 10 per hour')
    assert 'currency' in first and fake_leg.call_count == 0
    assert asyncio.run(fake_profile_store.get(session.id)).date == '2026-10-31'


def test_invalid_period_does_not_gain_calendar_authority():
    from b2c_common.date_period import period_decision, period_question
    period = period_decision({'kind': 'next_week', 'evidence': 'not literal'}, 'dates unclear')
    frozen = freeze_period(period, date(2026, 10, 9))
    assert frozen['kind'] == 'unresolved' and 'start' not in frozen and 'end' not in frozen
    assert weekday_in_period(frozen, 'tuesday', date(2026, 10, 9)) is None
    assert 'couldn’t verify' in period_question(frozen, 'en')


def test_currency_only_answer_cannot_relabel_the_pending_period(monkeypatch, fake_leg, fake_profile_store, friday):  # noqa: F811
    runner, session, _, _, _ = setup_period(monkeypatch, fake_profile_store)
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'requested_date_period': {'kind': 'next_week', 'evidence': 'USD'}}))
    answer = _run_turn(runner, session.id, 'USD')
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.pending_date_period['evidence'] == 'next week'
    assert saved.pending_date_period['start'] == '2026-10-12'
    assert 'USD (2026' not in answer
    assert fake_leg.call_count == 0


@pytest.mark.parametrize('kind', ['range', 'flexible', 'next_week'])
@pytest.mark.parametrize('message,quote', [('demain', 'demain'), ('pour demain de 12h à 18h', 'demain'),
                                          ('tomorrow with a pool', 'tomorrow')])
def test_single_day_cannot_be_replaced_by_a_model_period_label(
        monkeypatch, fake_leg, fake_profile_store, friday, kind, message, quote):  # noqa: F811
    runner, session, original, _, _ = setup_period(monkeypatch, fake_profile_store)
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'requested_date_period': {'kind': kind, 'evidence': quote}}), 'Matching offers.')
    fake_leg.response_payload = {'results': [], 'profile_delta': {}}
    _run_turn(runner, session.id, message)
    assert fake_leg.call_count == 1
    outgoing = find_datapart(fake_leg.seen_outgoing_parts)['profile_in']
    assert outgoing['date'] == '2026-10-10'
    assert outgoing['city'] == original.city and outgoing['adults'] == 2
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.pending_date_period is None and saved.date == '2026-10-10'


@pytest.mark.parametrize('message', ['tomorrow or Sunday', 'tomorrow or October 22', 'tomorrow and today'])
def test_single_day_endpoint_quote_does_not_silence_other_dates(message):
    from b2c_concierge.date_state import decide_date
    result = decide_date(message, None, None, {'kind': 'range', 'evidence': 'tomorrow'}, date(2026, 10, 9))
    assert result.expected is None and result.pending_period
