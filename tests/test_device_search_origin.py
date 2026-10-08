"""A device follow-up changes origin, without erasing verified region bounds."""
import asyncio
from types import SimpleNamespace

import pytest
from google.genai import types
from hotel_search_agent import geocode_tool as geo
from hotel_search_agent.area_scope import STATE_AREAS, use_device_origin, resolve_areas
from hotel_search_agent.mapbox_client import GeocodeCandidate
from hotel_search_agent.response_bridge import (
    capture_after_tool, find_datapart, emit_search_datapart, encode_datapart,
    enforce_resolved_search_origin, prepare_owned_area_plan,
)
from b2c_concierge.profile import SessionProfile, apply_profile_delta

AREA = {"query": "Yvelines", "kind": "administrative", "country": "FR", "evidence": "Yvelines"}
GPS = {"type": "gps", "lat": 48.6, "lon": 1.6}


def provider(ids=None):
    return SimpleNamespace(
        geocode_candidates=lambda *a, **k: [GeocodeCandidate(
            48.8, 1.8, "Yvelines", "Yvelines", "France", "region", "FR", "Yvelines",
            (1.44, 48.43, 2.23, 49.09), 0, "area78", "78")],
        containing_area_ids=lambda *a: {"area78"} if ids is None else ids,
    )


def context(profile=None, authoritative=False):
    return SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
        types.Part(text="Près de moi"), encode_datapart({"profile_in": profile or {},
                                                       "query_params": {"areas_authoritative": authoritative}}),
    ]))


def profile():
    return {"city": "Yvelines", "search_areas": [AREA], "search_anchor": GPS,
            "date": "2026-10-10", "budget_max": 150, "timeslot_end": "20:00", "amenities": ["spa"]}


@pytest.mark.parametrize("copied", [{}, {"city": "Yvelines"}, {"zone": "Yvelines"}])
def test_region_to_device_budget_followup_and_explicit_destination(monkeypatch, copied):
    monkeypatch.setattr(geo, "get_mapbox_client", provider)
    ctx = context(profile())
    tool = SimpleNamespace(name="geocode_location")
    result = geo.inject_profile_geo_context(tool, {"origin": "device", **copied}, ctx)
    assert result["ok"] and (result["latitude"], result["longitude"]) == (48.6, 1.6)
    assert result["search_areas"][0]["radius_km"] > 50
    capture_after_tool(tool, {}, ctx, result)
    args = {"lat": 0, "lon": 0}
    assert enforce_resolved_search_origin(SimpleNamespace(name="search_offers"), args, ctx) is None
    assert args == {"lat": 48.6, "lon": 1.6}
    # A successful resolution persists even with no results: a follow-up must
    # not silently switch back to the centroid when price changes.
    payload = find_datapart(emit_search_datapart(ctx).parts)
    updated = SessionProfile.from_dict(profile())
    apply_profile_delta(updated, payload["profile_delta"], "Près de moi")
    assert updated.search_anchor == GPS
    assert updated.distance_origin["type"] == "gps"
    assert updated.search_areas == [AREA]
    assert (updated.date, updated.budget_max, updated.timeslot_end, updated.amenities) == ("2026-10-10", 150, "20:00", ["spa"])
    following = geo.inject_profile_geo_context(tool, {}, context(updated.to_dict()))
    assert following["latitude"] == 48.6 and following["distance_origin_type"] == "gps"
    named = {"city": "Lyon", "country_code": "FR"}
    assert geo.inject_profile_geo_context(tool, named, context(updated.to_dict())) is None
    assert named["city"] == "Lyon"


@pytest.mark.parametrize("anchor", [None, {"type": "poi", "lat": 48.6, "lon": 1.6},
                                     {"type": "gps", "lat": True, "lon": 1.6},
                                     {"type": "gps", "lat": 48.6},
                                     {"type": "gps", "lat": float('nan'), "lon": 1.6}])
def test_model_coordinates_cannot_replace_missing_trusted_device(monkeypatch, anchor):
    monkeypatch.setattr(geo, "get_mapbox_client", provider)
    ctx = context({**profile(), "search_anchor": anchor})
    args = {"origin": "device", "proximity_lat": 48.6, "proximity_lon": 1.6}
    result = geo.inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, ctx)
    assert result["error"] == "device_location_unavailable"
    assert not ctx.state.get(STATE_AREAS)


def test_region_membership_and_named_place_cannot_be_overridden(monkeypatch):
    monkeypatch.setattr(geo, "get_mapbox_client", lambda: provider({"other-region"}))
    result = geo.inject_profile_geo_context(SimpleNamespace(name="geocode_location"), {"origin": "device"}, context(profile()))
    assert result["error"] == "device_area_conflict"
    named = geo.inject_profile_geo_context(SimpleNamespace(name="geocode_location"), {"origin": "device", "city": "Lyon"}, context(profile()))
    assert named["error"] == "conflicting_location_origin"


def test_device_mode_without_region_clears_old_named_destination():
    ctx = context({"city": "Paris", "zone": "Bercy", "search_anchor": GPS})
    result = geo.inject_profile_geo_context(SimpleNamespace(name="geocode_location"), {"origin": "device"}, ctx)
    capture_after_tool(SimpleNamespace(name="geocode_location"), {}, ctx, result)
    delta = find_datapart(emit_search_datapart(ctx).parts)["profile_delta"]
    assert delta["city"] == {"op": "clear"} and delta["zone"] == {"op": "clear"}
    assert delta["search_anchor"] == GPS
    assert delta["distance_origin"]["latitude"] == 48.6


def test_area_plan_does_not_preempt_device_interpretation():
    ctx = context(profile(), authoritative=True)
    asyncio.run(prepare_owned_area_plan(ctx))
    assert not ctx.state


def test_device_origin_is_exposed_as_a_closed_tool_choice():
    from google.adk.tools import FunctionTool
    schema = FunctionTool(geo.geocode_location)._get_declaration().parameters_json_schema
    assert schema["properties"]["origin"]["enum"] == ["destination", "device"]


def test_device_outside_required_child_and_oversize_disc_remain_blocked():
    p = provider()
    resolved = resolve_areas([AREA], p)
    resolved["search_areas"][0]["required_parent_id"] = "required-parent"
    assert use_device_origin(resolved, GPS, p)["error"] == "device_area_conflict"
    resolved["search_areas"][0].pop("required_parent_id")
    resolved["search_areas"][0]["bbox"] = [-10, 40, 10, 50]
    assert use_device_origin(resolved, GPS, p)["error"] == "area_exceeds_search_radius"


def test_device_disc_keeps_membership_filter_and_nearest_sort(monkeypatch):
    from hotel_search_agent.area_scope import search_areas_before_tool
    p = provider()
    plan = use_device_origin(resolve_areas([AREA], p), GPS, p)
    ctx = context()
    ctx.state[STATE_AREAS] = plan["search_areas"]
    p.containing_area_ids = lambda lat, lon: {"area78"} if lat == 48.6 else {"outside"}
    monkeypatch.setattr(geo, "get_mapbox_client", lambda: p)
    calls = []
    async def run_async(*, args, tool_context):
        calls.append(args)
        return {"structuredContent": {"results": [
            {"hotelId": 1, "lat": 48.6, "lon": 1.61}, {"hotelId": 2, "lat": 48.4, "lon": 1.61}]}}
    result = asyncio.run(search_areas_before_tool(SimpleNamespace(name="search_offers", run_async=run_async),
                                                 {"lat": 0, "lon": 0, "date": "2026-10-10", "endHour": 20}, ctx))
    assert calls[0]["lat"] == 48.6 and calls[0]["sortBy"] == "distance"
    assert calls[0]["date"] == "2026-10-10" and calls[0]["endHour"] == 20
    assert [h["hotelId"] for h in result["structuredContent"]["results"]] == [1]
