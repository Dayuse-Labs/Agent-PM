"""Contract regressions and contrasts; no production messages or provider calls."""
import asyncio
import json
from datetime import date

import pytest

from b2c_common.date_period import period_decision
from b2c_common.destination_request import address_context_question
from b2c_common.location_update import adapt_location_update
from b2c_concierge.date_state import decide_date
from b2c_concierge.profile import (SessionProfile, apply_profile_delta, leaf_profile_view,
    extract_final_question, is_booking_confirmation_signal, is_more_options_signal)
from b2c_concierge.search_clarification import grounded_need, reduce_need, need_question
from .test_spine_profile import _scripted_llm, _new_session, _run_turn, fake_leg  # noqa: F401
from google.adk.runners import InMemoryRunner
from b2c_concierge.agent import root_agent


@pytest.mark.parametrize('message,quote', [
    ('Avec piscine et dispo demain', 'dispo demain'),
    ('A room available tomorrow please', 'available tomorrow'),
    ('disponible pasado mañana', 'disponible pasado mañana'),
])
def test_flexible_label_does_not_erase_single_relative_day(message, quote):
    update = period_decision({'kind': 'flexible', 'evidence': quote}, message, require_scope=True)
    result = decide_date(message, None, None, update, date(2030, 5, 6))
    assert result.expected and result.from_message and result.pending_period is None


@pytest.mark.parametrize('message', ['tomorrow or Sunday', 'tomorrow or October 22',
                                     'tomorrow and today', 'from tomorrow to Friday', 'tomorrow or next week'])
def test_true_alternatives_and_ranges_still_require_day_choice(message):
    result = decide_date(message, None, None, {'kind': 'flexible', 'evidence': message}, date(2030, 5, 6))
    assert result.expected is None and result.pending_period


def test_non_temporal_reply_cannot_create_unscoped_flexibility():
    assert period_decision({'kind': 'flexible', 'evidence': 'none'}, 'none', require_scope=True) is None
    assert period_decision({'kind': 'flexible', 'scope': 'dates', 'evidence': 'dates are flexible'},
                           'dates are flexible', require_scope=True) == {'kind': 'flexible', 'evidence': 'dates are flexible'}


def test_multiple_postcodes_retain_names_without_becoming_an_unverified_union():
    message = 'near AB1 2CD and EF3 4GH'
    data = adapt_location_update({'location_update': {'action': 'change', 'evidence': message,
        'relation': 'near_all', 'targets': [
            {'kind': 'postcode', 'query': q, 'evidence': q, 'country': 'GB'} for q in ['AB1 2CD', 'EF3 4GH']]}}, message, None)
    need = grounded_need(data['clarification_need'], message)
    assert need['queries'] == ['AB1 2CD', 'EF3 4GH']
    assert data['location_intent']['action'] == 'unknown' and data['requested_areas'] is None
    assert 'both' in need_question(need, 'en')


@pytest.mark.parametrize('bad', [
    {'kind': 'multiple_origins', 'queries': ['invented', 'B'], 'relation': 'between', 'evidence': 'A and B'},
    {'kind': 'multiple_origins', 'queries': ['A', 'B'], 'relation': 'drive_time', 'evidence': 'A and B'},
    {'kind': 'airport', 'queries': ['A'], 'evidence': 'A', 'lat': 1},
])
def test_question_contract_never_accepts_invented_places_or_coordinates(bad):
    assert grounded_need(bad, 'A and B') is None


def test_airport_question_owns_type_across_city_then_date_then_specific_airport():
    need = {'kind': 'airport', 'queries': ['airport'], 'relation': 'choose'}
    need = reduce_need(None, need, 'Example City', {'action': 'change'},
                       [{'kind': 'municipality', 'query': 'Example City'}], None)
    assert need['parent'] == 'Example City'
    assert reduce_need(None, need, 'tomorrow', {'action': 'preserve'}, None, None) == need
    assert reduce_need(None, need, 'ABC airport', {'action': 'change'}, None,
                       {'query': 'ABC airport'}) is None
    assert reduce_need(None, need, 'instead Example City centre', {'action': 'change'},
                       [{'kind': 'municipality', 'query': 'Example City'}], None) is None


def test_previous_place_is_internal_context_not_a_leaf_coordinate_override():
    prior = {'name': 'Earlier City', 'latitude': 10, 'longitude': 20}
    profile = SessionProfile(previous_location_context=prior)
    assert SessionProfile.from_dict(profile.to_dict()).previous_location_context == prior
    assert 'previous_location_context' not in leaf_profile_view(profile)
    apply_profile_delta(profile, {'previous_location_context': {'name': 'Invented'}}, 'same')
    assert profile.previous_location_context == prior


def test_address_question_asks_for_parent_not_already_supplied_street():
    answer = address_context_question('12 Example Street', 'en', missing_city=True)
    assert '12 Example Street' in answer and 'city and country' in answer
    assert 'postcode' not in answer


@pytest.mark.parametrize('message', ['I do not confirm', 'I cannot confirm', 'confirm what', 'read the booking conditions'])
def test_lexical_confirmation_cannot_override_nonconfirmation(message):
    assert not is_booking_confirmation_signal(message, SessionProfile(pending_booking={'hotel_id': 1}),
                                              llm_booking_confirmation='none')


@pytest.mark.parametrize('message', ['confirm?', 'cancel the booking', 'non je confirme pas'])
def test_question_and_existing_refusal_guard_precede_model_confirmation(message):
    assert not is_booking_confirmation_signal(message, SessionProfile(pending_booking={'hotel_id': 1}),
                                              llm_booking_confirmation='confirm')


def test_negated_pagination_uses_semantic_decision_not_keyword():
    assert not is_more_options_signal('Do not show other options', False)
    assert is_more_options_signal('otras opciones', True)
    assert is_more_options_signal('other options', None)


def test_final_question_scanner_handles_long_nonquestion_and_sentence_boundaries():
    assert extract_final_question('a' * 100000) is None
    assert extract_final_question('First. Second! Keep this?  ') == 'Keep this?'
    assert extract_final_question('First? Next?') == 'Next?'


def test_airport_city_answer_does_not_dispatch_city_centre_search(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'missing', 'evidence': 'near airport'},
        'clarification_need': {'kind': 'airport', 'queries': ['airport'], 'evidence': 'near airport'}}))
    first = _run_turn(runner, session.id, 'near airport')
    assert 'airport or terminal' in first and fake_leg.call_count == 0
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'change', 'evidence': 'Example City', 'targets': [
            {'kind': 'city', 'query': 'Example City', 'country': 'US'}]}}))
    second = _run_turn(runner, session.id, 'Example City')
    assert 'Example City' in second and 'airport or terminal' in second
    assert fake_leg.call_count == 0
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.pending_clarification['need']['parent'] == 'Example City'


def test_hotel_city_is_a_separate_grounded_mcp_parameter():
    from b2c_common.confirmed_location import location_intent
    from b2c_common.destination_request import refine_hotel
    message = 'Example Hotel in Example City'
    data = adapt_location_update({'location_update': {'action': 'change', 'evidence': message,
        'parent_city': 'Example City', 'targets': [{'kind': 'hotel', 'query': 'Example Hotel',
        'evidence': 'Example Hotel'}]}}, message, None)
    intent = location_intent(data['location_intent'], message, None)
    assert refine_hotel(data['hotel_name'], None, intent['action'], intent['parent_city'], message) == {
        'kind': 'hotel', 'query': 'Example Hotel', 'city': 'Example City'}


def test_previous_parent_hint_survives_real_triage_validation(monkeypatch):
    from types import SimpleNamespace
    from b2c_concierge.triage import classify
    from b2c_concierge.budget import TurnBudget
    async def completion(**kwargs):
        data = {'family': 'search', 'language': 'en', 'location_update': {
            'action': 'change', 'evidence': 'Example Quarter', 'parent_city': 'Prior City',
            'targets': [{'kind': 'neighborhood', 'query': 'Example Quarter', 'country': 'US'}]}}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))])
    monkeypatch.setattr('b2c_concierge.triage.litellm.acompletion', completion)
    context = {'previous_verified_context': {'provider_city': {'name': 'Prior City'}, 'country_code': 'US'}}
    result = asyncio.run(classify('Example Quarter', TurnBudget(), location_context=context))
    assert result.requested_areas[0]['query'] == 'Prior City'
    assert result.requested_areas[0]['subarea'] == 'Example Quarter'
    # This is an unverified query with an old parent hint, not a provider identity.
    assert 'latitude' not in result.requested_areas[0]


def test_previous_parent_cannot_bind_a_target_in_an_explicitly_different_country():
    raw = {'location_update': {'action': 'change', 'evidence': 'Example Quarter',
        'parent_city': 'Prior City', 'targets': [{'kind': 'neighborhood', 'query': 'Example Quarter', 'country': 'FR'}]}}
    context = {'previous_verified_context': {'provider_city': {'name': 'Prior City'}, 'country_code': 'US'}}
    result = adapt_location_update(raw, 'Example Quarter', context)
    assert result['requested_areas'][0]['query'] == 'Example Quarter'
    assert 'subarea' not in result['requested_areas'][0]


def test_single_native_terminal_proposal_needs_explicit_place_selection():
    from dataclasses import replace
    from hotel_search_agent.mapbox_client import GeocodeCandidate
    from hotel_search_agent.geocode_tool import _terminal_confirmation
    from b2c_common.confirmed_location import pending_location
    from b2c_concierge.location_state import selected_place
    terminal = GeocodeCandidate(51.4, -.4, 'Terminal 4 Departures Example Airport',
        'Terminal 4 Departures Example Airport, Example City, GB', 'Example City, GB',
        'poi', 'GB', 'England', None, 0, 'terminal-id',
        parent_city_name='Example City', parent_city_id='city-id', poi_categories=('airport_terminal',))
    shop = replace(terminal, mapbox_id='shop-id', poi_categories=('shop',))
    proposal = _terminal_confirmation([shop, terminal], 'Example Airport Terminal 4', 'en')
    assert proposal['confirmation_required'] is True
    assert len(proposal['options']) == 1 and proposal['options'][0]['provider_id'] == 'terminal-id'
    assert pending_location(proposal)
    profile = SessionProfile(pending_location=proposal)
    assert selected_place(profile, {'action': 'preserve'}) is None
    assert selected_place(profile, {'action': 'select', 'position': 1})['provider_id'] == 'terminal-id'
    assert _terminal_confirmation([terminal], 'Example Airport Terminal 5', 'en') is None
    assert _terminal_confirmation([shop], 'Example Airport Terminal 4', 'en') is None
    assert pending_location({'question': proposal['question'], 'options': proposal['options']}) is None


def test_terminal_categories_are_read_only_from_provider_metadata():
    from hotel_search_agent.searchbox_client import SearchBoxClient
    payload = {'features': [{'geometry': {'coordinates': [0.1, 51]}, 'properties': {
        'name': 'Example Terminal 2', 'feature_type': 'poi', 'mapbox_id': 'provider-id',
        'poi_category_ids': ['airport_terminal'], 'context': {'country': {'country_code': 'GB'}}}}]}
    c = SearchBoxClient._parse(payload, fallback='arbitrary')[0]
    assert c.poi_categories == ('airport_terminal',) and not c.airport_iata
