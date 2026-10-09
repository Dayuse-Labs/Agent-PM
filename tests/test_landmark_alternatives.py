"""Alternative POIs survive typed intent, provider resolution and retrieval."""
import asyncio
from types import SimpleNamespace

import pytest
from google.genai import types

from b2c_common.destination_request import DestinationRequest, destination_request
from b2c_common.location_update import adapt_location_update
from b2c_concierge.profile import SessionProfile
from hotel_search_agent import landmark_alternatives as module
from hotel_search_agent.area_scope import STATE_AREAS, STATE_COVERAGE, STATE_FAILED, search_areas_before_tool
from hotel_search_agent.response_bridge import encode_datapart, read_profile_in


def request():
    return DestinationRequest(kind="landmarks", landmarks=[
        {"query": "North airport", "city": "Example City", "country_guess": "US"},
        {"query": "South station", "city": "Example City", "country_guess": "US"},
    ]).model_dump(exclude_none=True)


def context():
    return SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
        types.Part(text="North airport or South station in Example City"),
        encode_datapart({"profile_in": {"requested_destination": request(), "date": "2027-01-12", "adults": 2},
                        "query_params": {"destination_authoritative": True}}),
    ]))


def place(name, lat):
    return {"provider_id": "provider:" + name, "name": name, "label": name,
            "country_code": "US", "feature_type": "poi", "region": "Example State",
            "latitude": lat, "longitude": 10.0, "search_context": {"city": "Example City", "zone": name, "metro": None}}


def test_grounded_alternatives_roundtrip_session_without_losing_parent_or_kind():
    message = "North airport or South station in Example City"
    raw = {"location_update": {"action": "change", "evidence": message, "parent_city": "Example City",
                              "targets": [{"kind": "landmark", "query": name, "country": "US"}
                                          for name in ["North airport", "South station"]]}}
    got = adapt_location_update(raw, message, None)
    assert got["requested_landmark"] is None
    owned = DestinationRequest(kind="landmarks", landmarks=got["requested_landmarks"])
    profile = SessionProfile(requested_destination=owned.model_dump(exclude_none=True))
    reloaded = SessionProfile.from_dict(profile.to_dict())
    assert destination_request(reloaded.requested_destination) == owned
    assert [p.query for p in owned.landmarks] == ["North airport", "South station"]
    assert all(p.city == "Example City" for p in owned.landmarks)


@pytest.mark.parametrize("mutate", [
    lambda raw: raw["location_update"]["targets"][1].update(query="Invented airport"),
    lambda raw: raw["location_update"]["targets"][1].update(evidence="previous message"),
])
def test_ungrounded_alternative_rejects_whole_transaction(mutate):
    raw = {"location_update": {"action": "change", "evidence": "North or South", "targets": [
        {"kind": "landmark", "query": "North"}, {"kind": "landmark", "query": "South"}]}}
    mutate(raw)
    got = adapt_location_update(raw, "North or South", None)
    assert got["location_intent"]["action"] == "unknown"
    assert got["requested_landmarks"] is None


def test_unsupported_mixed_target_does_not_authorize_empty_change():
    raw = {"location_update": {"action": "change", "evidence": "Alpha Hotel or Beta", "targets": [
        {"kind": "hotel", "query": "Alpha Hotel"}, {"kind": "city", "query": "Beta"}]}}
    got = adapt_location_update(raw, "Alpha Hotel or Beta", None)
    assert got["location_intent"]["action"] == "unknown"
    assert not got["hotel_name"] and not got["requested_areas"]


@pytest.mark.parametrize("count", [0, 1, 4])
def test_plan_bound_and_device_separation(count):
    points = [{"query": str(i)} for i in range(count)]
    assert destination_request({"kind": "landmarks", "landmarks": points}) is None
    assert destination_request({"kind": "device", "landmarks": request()["landmarks"]}) is None


def mock_resolver(monkeypatch, fail_second=False, invalid_second=False):
    seen = []
    def inject(tool, args, ctx):
        p = read_profile_in(ctx)
        seen.append(p)
        assert p["date"] == "2027-01-12" and p["adults"] == 2
        args.update(city=p["city"], zone=p["zone"])
    def resolve(city, zone):
        if fail_second and zone == "South station":
            return {"ok": False, "error": "geocode_ambiguous", "diagnostics": {"question": "Which city?"}}
        p = place(zone, 10.0 if zone == "North airport" else 11.0)
        if invalid_second and zone == "South station":
            p.pop("provider_id")
        return {"ok": True, "latitude": p["latitude"], "longitude": 10., "resolved_location": p}
    monkeypatch.setattr(module, "inject_profile_geo_context", inject)
    monkeypatch.setattr(module, "geocode_location", resolve)
    return seen


def test_each_landmark_has_independent_resolution_and_model_cannot_replace_union(monkeypatch):
    seen = mock_resolver(monkeypatch)
    ctx = context()
    asyncio.run(module.prepare_landmark_alternatives(ctx))
    assert len(seen) == 2
    assert all(p["confirmed_location"] is None and p["requested_destination"]["kind"] == "landmark" for p in seen)
    points = ctx.state[STATE_AREAS]
    assert len(points) == 2 and all(p["scope"] == "nearby_point" and p["radius_km"] == 3 for p in points)
    result = module.reuse_landmark_alternatives(SimpleNamespace(name="geocode_location"), {"city": "unrelated"}, ctx)
    assert result["search_areas"] == points


@pytest.mark.parametrize("invalid", [False, True])
def test_one_unresolved_or_invalid_provider_identity_does_not_erase_other(monkeypatch, invalid):
    mock_resolver(monkeypatch, fail_second=not invalid, invalid_second=invalid)
    ctx = context()
    asyncio.run(module.prepare_landmark_alternatives(ctx))
    result = module.reuse_landmark_alternatives(SimpleNamespace(name="geocode_location"), {}, ctx)
    assert result["ok"] and len(result["search_areas"]) == 1
    assert result["unresolved_areas"][0]["query"] == "South station"


def test_no_resolved_point_blocks_inventory(monkeypatch):
    monkeypatch.setattr(module, "inject_profile_geo_context", lambda *args: {"ok": False, "error": "geocode_ambiguous"})
    ctx = context()
    asyncio.run(module.prepare_landmark_alternatives(ctx))
    assert STATE_FAILED in ctx.state and not ctx.state.get(STATE_AREAS)
    assert len(ctx.state[STATE_FAILED]["diagnostics"]["alternatives"]) == 2


def test_bounded_batch_keeps_filters_roundrobins_results_and_checks_each_distance(monkeypatch):
    mock_resolver(monkeypatch)
    ctx = context()
    asyncio.run(module.prepare_landmark_alternatives(ctx))
    calls = []
    class Tool:
        name = "search_offers"
        async def run_async(self, args, tool_context):
            calls.append(args)
            lat = args["lat"]
            rows = [{"hotelId": int(lat * 10), "lat": lat + .005, "lon": 10.0},
                    {"hotelId": 999, "lat": 40., "lon": 10.}]
            return {"structuredContent": {"results": rows}}
    args = {"date": "2027-01-12", "adults": 2, "children": 1, "timeSlot": {"startHour": 10, "endHour": 17},
            "maxPrice": 120, "hotelEquipmentIds": [4]}
    result = asyncio.run(search_areas_before_tool(Tool(), args, ctx))
    assert len(calls) == 2
    assert all(all(call[k] == v for k, v in args.items()) for call in calls)
    hotels = result["structuredContent"]["results"]
    assert [h["hotelId"] for h in hotels] == [100, 110]
    assert [h["verifiedSearchOrigins"][0]["label"] for h in hotels] == ["North airport", "South station"]
    assert all(h["verifiedSearchOrigins"][0]["distance_km"] == .6 for h in hotels)
    assert ctx.state[STATE_COVERAGE]["exhaustive"] is False
    assert search_areas_before_tool(Tool(), args, ctx)["ok"] is False


def test_unresolved_alternatives_emit_typed_clarification_for_concierge(monkeypatch):
    from hotel_search_agent.response_bridge import emit_search_datapart, find_datapart
    monkeypatch.setattr(module, "inject_profile_geo_context", lambda *args: {"ok": False, "error": "geocode_ambiguous"})
    ctx = context()
    asyncio.run(module.prepare_landmark_alternatives(ctx))
    emitted = emit_search_datapart(ctx)
    payload = find_datapart(emitted.parts)
    assert payload['requires_clarification'] is True
    assert payload['destination_clarification'] == {
        'kind': 'landmark_context', 'queries': ['North airport', 'South station'],
    }
