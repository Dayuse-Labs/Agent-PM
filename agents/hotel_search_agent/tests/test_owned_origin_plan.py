"""A search emitted first must use the current concierge-owned location.

Regression: two parallel search calls were rejected locally before geocoding,
spent the attempt quota, and left no useful search for a cheaper follow-up.
"""
import asyncio
from inspect import isawaitable
from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types

from hotel_search_agent.agent import PER_TOOL_CALL_LIMITS, MAX_TOOL_CALLS, root_agent
from hotel_search_agent.response_bridge import enforce_resolved_search_origin
from hotel_search_agent.tool_budget_guard import make_per_tool_budget_callback, reserve_mcp_read

PLACE = {'provider_id': 'provider:sample-city', 'name': 'Paris', 'label': 'Paris, France',
         'country_code': 'FR', 'region': '', 'feature_type': 'place',
         'latitude': 48.85, 'longitude': 2.35}


def context(profile, params):
    part = a2a_types.Part(root=a2a_types.DataPart(data={'profile_in': profile, 'query_params': params}))
    return SimpleNamespace(state={}, invocation_id='search-followup',
                           user_content=types.Content(role='user', parts=[types.Part(text='Less expensive, please'),
                               convert_a2a_part_to_genai_part(part)]))


def prepare(ctx):
    async def run():
        for cb in root_agent.before_agent_callback:
            result = cb(ctx)
            if isawaitable(result):
                result = await result
            assert result is None
    asyncio.run(run())


def forbid_provider(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError('A confirmed preserving turn needs no geocoding request')
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', fail)


def test_search_first_uses_confirmed_origin_and_preserves_the_two_read_limit(monkeypatch):
    forbid_provider(monkeypatch)
    ctx = context({'city': 'Paris', 'confirmed_location': PLACE}, {'reuse_confirmed_location': True})
    prepare(ctx)
    tool = SimpleNamespace(name='search_offers')
    guard = make_per_tool_budget_callback(PER_TOOL_CALL_LIMITS, MAX_TOOL_CALLS)
    for _ in range(2):
        args = {'lat': 0, 'lon': 0}
        assert guard(tool, args, ctx) is None
        assert enforce_resolved_search_origin(tool, args, ctx) is None
        assert args == {'lat': 48.85, 'lon': 2.35}
        assert reserve_mcp_read(ctx, 'search_offers')
    assert guard(tool, {}, ctx)['ok'] is False
    assert not reserve_mcp_read(ctx, 'search_offers')


def test_prose_only_owned_search_gets_one_guarded_read_without_model_retry(monkeypatch):
    from google.adk.models.llm_response import LlmResponse
    from hotel_search_agent.owned_origin_plan import ensure_grounded_search
    from hotel_search_agent.response_bridge import skip_final_generation
    forbid_provider(monkeypatch)
    ctx = context({'city': 'Paris', 'confirmed_location': PLACE}, {'reuse_confirmed_location': True})
    prepare(ctx)
    prose = LlmResponse(content=types.Content(role='model', parts=[types.Part(text='Fully booked until next year')]))
    response = ensure_grounded_search(ctx, prose)
    call = response.content.parts[0].function_call
    assert call.name == 'search_offers' and call.args == {}
    assert ensure_grounded_search(ctx, prose) is None
    ctx.state['temp:hotel_search_results'] = []  # A real empty page also ends the turn.
    assert skip_final_generation(ctx, None) is not None


@pytest.mark.parametrize('mode', ['unowned', 'failed', 'attempted', 'tool_call', 'empty_result'])
def test_owned_read_fallback_never_retries_or_overrides_clarification(monkeypatch, mode):
    from google.adk.models.llm_response import LlmResponse
    from hotel_search_agent.owned_origin_plan import ensure_grounded_search
    forbid_provider(monkeypatch)
    ctx = context({'city': 'Paris', 'confirmed_location': PLACE},
                  {} if mode == 'unowned' else {'reuse_confirmed_location': True})
    prepare(ctx)
    if mode == 'failed':
        ctx.state['temp:area_resolution_failed'] = {'ok': False}
    if mode == 'attempted':
        ctx.state.update(_per_tool_budget_inv=ctx.invocation_id, _per_tool_budget_counts={'search_offers': 1})
    if mode == 'empty_result':
        ctx.state['temp:hotel_search_results'] = []
    parts = [types.Part(function_call=types.FunctionCall(name='search_offers', args={}))] if mode == 'tool_call' else [types.Part(text='No offers')]
    assert ensure_grounded_search(ctx, LlmResponse(content=types.Content(role='model', parts=parts))) is None


@pytest.mark.parametrize('params,profile', [
    ({}, {'city': 'Paris', 'confirmed_location': PLACE}),
    ({'reuse_confirmed_location': True}, {'city': 'Paris', 'confirmed_location': {**PLACE, 'latitude': 999}}),
])
def test_unowned_or_invalid_carried_place_does_not_authorize_search(monkeypatch, params, profile):
    forbid_provider(monkeypatch)
    ctx = context(profile, params)
    prepare(ctx)
    assert enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), {}, ctx)['status'] == 'geocode_required'


def test_preparation_is_reset_when_next_turn_has_no_location_authority(monkeypatch):
    forbid_provider(monkeypatch)
    ctx = context({'city': 'Paris', 'confirmed_location': PLACE}, {'reuse_confirmed_location': True})
    prepare(ctx)
    assert enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), {}, ctx) is None
    ctx.user_content = context({}, {}).user_content
    ctx.invocation_id = 'changed-turn'
    prepare(ctx)
    assert enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), {}, ctx)['status'] == 'geocode_required'


def test_owned_city_is_resolved_once_before_model_even_with_stale_prior_identity(monkeypatch):
    calls = []
    def resolve(**args):
        calls.append(args)
        assert args['city'] == 'Lyon' and args['origin'] == 'destination'
        return {'ok': True, 'latitude': 45.76, 'longitude': 4.84,
                'resolved_place': 'Lyon, France', 'country_code': 'FR'}
    monkeypatch.setattr('hotel_search_agent.owned_origin_plan.geocode_location', resolve)
    ctx = context({'city': 'Lyon', 'country_anchor': 'FR', 'confirmed_location': PLACE},
                  {'areas_authoritative': True})
    prepare(ctx)
    args = {'lat': 0, 'lon': 0}
    assert enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), args, ctx) is None
    assert args == {'lat': 45.76, 'lon': 4.84} and len(calls) == 1
    guard = make_per_tool_budget_callback(PER_TOOL_CALL_LIMITS, MAX_TOOL_CALLS)
    from hotel_search_agent.owned_origin_plan import reuse_owned_origin
    tool = SimpleNamespace(name='geocode_location')
    # Even if the model ignores the prepared-plan instruction, neither its
    # contradictory city nor repeated calls can cause another provider lookup.
    for _ in range(2):
        bad_args = {'city': 'Orlando', 'origin': 'device'}
        assert guard(tool, bad_args, ctx) is None
        assert reuse_owned_origin(tool, bad_args, ctx)['resolved_place'] == 'Lyon, France'
    assert guard(tool, {}, ctx)['ok'] is False
    assert len(calls) == 1


def test_owned_device_uses_actual_anchor_before_model_not_prior_city(monkeypatch):
    forbid_provider(monkeypatch)
    ctx = context({'city': 'Paris', 'confirmed_location': PLACE,
                   'search_anchor': {'type': 'gps', 'lat': 43.3, 'lon': 5.4}},
                  {'device_authoritative': True})
    prepare(ctx)
    args = {'lat': 0, 'lon': 0}
    assert enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), args, ctx) is None
    assert args == {'lat': 43.3, 'lon': 5.4}


def test_missing_device_blocks_search_instead_of_reusing_old_city(monkeypatch):
    forbid_provider(monkeypatch)
    ctx = context({'city': 'Paris', 'confirmed_location': PLACE}, {'device_authoritative': True})
    prepare(ctx)
    result = enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), {}, ctx)
    assert result['error'] == 'device_location_unavailable'


def test_landmark_failure_does_not_allow_model_to_supply_replacement_coordinates(monkeypatch):
    calls = []
    def resolve(**args):
        calls.append(args)
        assert args['city'] == 'London' and args['zone'] == 'Station X'
        return {'ok': False, 'error': 'geocode_echo_mismatch', 'diagnostics': {'query': 'Station X'}}
    monkeypatch.setattr('hotel_search_agent.owned_origin_plan.geocode_location', resolve)
    ctx = context({'city': 'London', 'zone': 'Station X', 'country_anchor': 'GB'},
                  {'landmark_authoritative': True})
    prepare(ctx)
    result = enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), {'lat': 0, 'lon': 0}, ctx)
    assert result['error'] == 'geocode_echo_mismatch'
    assert len(calls) == 1


def test_real_callback_order_preserves_attempt_limits_before_reuse():
    from hotel_search_agent.owned_origin_plan import reuse_owned_origin, prepare_owned_origin
    from hotel_search_agent.response_bridge import stamp_turn_start
    callbacks = root_agent.before_tool_callback
    guard = next(cb for cb in callbacks if cb.__module__.endswith('tool_budget_guard'))
    assert callbacks.index(guard) < callbacks.index(reuse_owned_origin) < callbacks.index(enforce_resolved_search_origin)
    assert root_agent.before_agent_callback.index(stamp_turn_start) < root_agent.before_agent_callback.index(prepare_owned_origin)


def test_owned_region_with_gps_but_no_origin_decision_stays_with_existing_flow(monkeypatch):
    forbid_provider(monkeypatch)
    ctx = context({'city': 'Île-de-France',
                   'search_areas': [{'query': 'Île-de-France', 'kind': 'administrative', 'country': 'FR',
                                     'evidence': 'Île-de-France', 'boundary_evidence': '', 'code': '', 'subarea': ''}],
                   'search_anchor': {'type': 'gps', 'lat': 48.8, 'lon': 2.3}},
                  {'areas_authoritative': True})
    prepare(ctx)
    assert enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), {}, ctx)['status'] == 'geocode_required'
