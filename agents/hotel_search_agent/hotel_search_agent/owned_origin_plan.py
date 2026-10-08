"""Prepare current code-owned geography before model tool scheduling.

The concierge still interprets the message. This module only executes its typed
location decision through the same geocode injection and provider guards used
by the ordinary FunctionTool. Nothing is inferred from text here.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from b2c_common.confirmed_location import verified_place
from b2c_common.search_areas import requires_area_membership, validate_areas
from hotel_search_agent.area_scope import STATE_FAILED, STATE_RESOLUTION, trusted_device_coordinates
from hotel_search_agent.geocode_tool import geocode_location, inject_profile_geo_context
from hotel_search_agent.response_bridge import capture_after_tool, find_datapart, read_profile_in

_STATE_PLAN = 'temp:hotel_search_owned_origin_plan'
_GEO_TOOL = SimpleNamespace(name='geocode_location')


async def prepare_owned_origin(callback_context: Any) -> None:
    """At most one guarded resolution; confirmed identities need no network.

    No current authority means the existing model/tool flow remains responsible
    for extraction. A profile alone does not authorize an automatic search.
    Area preparation may already have resolved the current request.
    """
    callback_context.state[_STATE_PLAN] = None
    content = getattr(callback_context, 'user_content', None)
    envelope = find_datapart(getattr(content, 'parts', None)) or {}
    params = envelope.get('query_params') or {}
    owned = any(params.get(k) is True for k in (
        'areas_authoritative', 'landmark_authoritative', 'device_authoritative', 'reuse_confirmed_location',
    ))
    if not owned or callback_context.state.get(STATE_RESOLUTION) or callback_context.state.get(STATE_FAILED):
        return None
    profile = read_profile_in(callback_context)
    # A regional boundary alone does not choose between its centroid and the
    # supplied device position. Preserve the existing area-plan contract until
    # the concierge explicitly owns device mode; do not guess that decision.
    if (requires_area_membership(validate_areas(profile.get('search_areas')))
            and trusted_device_coordinates(profile.get('search_anchor')) is not None
            and params.get('device_authoritative') is not True):
        return None
    if params.get('reuse_confirmed_location') is True and not verified_place(profile.get('confirmed_location')):
        return None
    # Supplying the owned city prevents an old identity from being reused when
    # the current typed decision is a different ordinary city.
    args: dict[str, Any] = {}
    if params.get('areas_authoritative') is True and profile.get('city'):
        args['city'] = profile['city']
    if not (params.get('device_authoritative') is True or params.get('reuse_confirmed_location') is True
            or profile.get('city') or profile.get('zone') or profile.get('search_areas')):
        return None
    result = await asyncio.to_thread(inject_profile_geo_context, _GEO_TOOL, args, callback_context)
    if result is None:
        result = await asyncio.to_thread(geocode_location, **args)
    callback_context.state[_STATE_PLAN] = result
    if not result.get('ok'):
        callback_context.state[STATE_FAILED] = result
    capture_after_tool(_GEO_TOOL, args, callback_context, result)
    return None


def reuse_owned_origin(tool: Any, args: dict[str, Any], tool_context: Any) -> dict | None:
    """After the normal quota guard, reuse this turn's prepared geocode.

    Repeated model calls still consume their normal attempt budget, but cannot
    issue a second provider request or replace the current owned destination.
    """
    if getattr(tool, 'name', '') == 'geocode_location':
        return tool_context.state.get(_STATE_PLAN)
    return None


def inject_owned_origin(callback_context: Any, llm_request: Any) -> None:
    plan = callback_context.state.get(_STATE_PLAN)
    if not isinstance(plan, dict) or callback_context.state.get(STATE_RESOLUTION):
        return None  # Regional plans have their own existing instruction.
    if plan.get('ok'):
        instruction = (
            'The current destination has ALREADY been verified in code. Skip geocode_location. '
            'Call search_offers once; code binds its coordinates to the verified origin '
            f"lat={plan['latitude']}, lon={plan['longitude']}. "
            'Label only the requested filters; established profile constraints carry forward. '
            'Do not emit parallel overlap/contain searches or invent a numerical budget for cheaper.'
        )
    else:
        diagnostic = {k: plan[k] for k in ('error', 'diagnostics') if k in plan}
        instruction = (
            'The current destination could not be verified. Do not search or call another geocode. '
            'Explain this diagnostic or ask its clarification, without inventing an alternative location: '
            + json.dumps(diagnostic, ensure_ascii=False)
        )
    llm_request.append_instructions([instruction])
    return None
