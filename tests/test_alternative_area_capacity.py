"""Four accepted destinations must not become an unknown-location transaction."""
import asyncio
import math
from types import SimpleNamespace

import pytest

from b2c_common.destination_request import DestinationRequest
from b2c_common.location_update import adapt_location_update
from b2c_common.search_areas import MAX_AREAS, validate_areas
from hotel_search_agent.area_scope import STATE_AREAS, STATE_COVERAGE, resolve_areas, search_areas_before_tool
from hotel_search_agent.response_bridge import capture_after_tool, encode_datapart
from hotel_search_agent.mapbox_client import GeocodeCandidate
from google.genai import types


def context():
    ctx = SimpleNamespace(state={}, invocation_id="turn", user_content=types.Content(role="user", parts=[
        types.Part(text="alternative cities"), encode_datapart({"profile_in": {}})]))
    # The leaf's real per-tool budget guard runs first on every tool call.
    from hotel_search_agent.agent import MAX_TOOL_CALLS, PER_TOOL_CALL_LIMITS
    from hotel_search_agent.tool_budget_guard import make_per_tool_budget_callback
    make_per_tool_budget_callback(PER_TOOL_CALL_LIMITS, MAX_TOOL_CALLS)(SimpleNamespace(name="search_offers"), {}, ctx)
    return ctx

NAMES = ['Alpha City', 'Beta City', 'Gamma City', 'Delta City', 'Epsilon City', 'Zeta City']


def transaction(count, kind='city'):
    message = ' or '.join(NAMES[:count])
    raw = {'location_update': {'action': 'change', 'evidence': message, 'targets': [
        {'kind': kind, 'query': name, 'country': 'FR', 'evidence': name} for name in NAMES[:count]]}}
    return adapt_location_update(raw, message, None), message


@pytest.mark.parametrize('count', [4, 5])
def test_four_or_five_grounded_alternatives_cross_the_destination_contract(count):
    got, message = transaction(count)
    assert got['location_intent']['action'] == 'change'
    areas = validate_areas(got['requested_areas'], message)
    assert [a['query'] for a in areas] == NAMES[:count]
    assert DestinationRequest(kind='areas', areas=areas).areas == areas


def test_bound_is_explicit_and_does_not_expand_landmark_budget():
    got, _ = transaction(6)
    assert got['location_intent']['action'] == 'unknown'
    got, _ = transaction(4, 'landmark')
    assert got['location_intent']['action'] == 'unknown' and got['requested_landmarks'] is None
    assert MAX_AREAS == 5


@pytest.mark.parametrize('count', [4, 5])
def test_provider_verified_batch_searches_accepted_areas_within_the_read_cap(monkeypatch, count):
    # PR134-FIX R6 (Fabien, 2026-10-12): every area is one MCP read under the
    # per-tool cap. Past it, an area is "not searched" — disclosed through
    # failed_area_names, never presented as an absence of hotels.
    from hotel_search_agent.agent import PER_TOOL_CALL_LIMITS
    cap = PER_TOOL_CALL_LIMITS['search_offers']
    got, message = transaction(count)
    areas = validate_areas(got['requested_areas'], message)
    features = {name: GeocodeCandidate(48.15, i + .05, name, name, 'France', 'place', 'FR', name,
        (float(i), 48.1, i + .1, 48.2), 0, f'area{i}', '')
        for i, name in enumerate(NAMES[:count])}
    provider = SimpleNamespace(geocode_candidates=lambda query, **kw: [features[query]],
        containing_area_ids=lambda lat, lon: {f'area{math.floor(lon)}'})
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', lambda: provider)
    resolved = resolve_areas(areas, provider)
    assert resolved['ok']
    ctx = context()
    capture_after_tool(SimpleNamespace(name='geocode_location'), {}, ctx, resolved)
    calls = []
    async def run_async(*, args, tool_context):
        calls.append(dict(args))
        i = math.floor(args['lon'])
        return {'structuredContent': {'results': [{'hotelId': i + 1, 'lat': 48.15, 'lon': i + .05}]}}
    tool = SimpleNamespace(name='search_offers', run_async=run_async)
    args = {'date': '2026-10-14', 'priceRangeMax': 80, 'hotelEquipmentIds': [41],
            'timeSlot': {'startHour': 10, 'endHour': 17}, 'adults': 2}
    result = asyncio.run(search_areas_before_tool(tool, args, ctx))
    assert len(calls) == cap
    assert all(all(call[k] == v for k, v in args.items()) and call['size'] == 5 for call in calls)
    assert len(result['structuredContent']['results']) == cap
    assert ctx.state[STATE_COVERAGE]['areas'] == NAMES[:count]
    assert ctx.state[STATE_COVERAGE]['failed_area_names'] == NAMES[cap:count]
    assert ctx.state[STATE_COVERAGE]['exhaustive'] is False
    assert search_areas_before_tool(tool, args, ctx)['ok'] is False
    assert len(calls) == cap


def test_excessive_internal_batch_is_rejected_before_any_dispatch():
    ctx = context()
    ctx.state[STATE_AREAS] = [{}] * 6
    tool = SimpleNamespace(name='search_offers')  # No runnable tool is needed.
    assert search_areas_before_tool(tool, {}, ctx)['ok'] is False
