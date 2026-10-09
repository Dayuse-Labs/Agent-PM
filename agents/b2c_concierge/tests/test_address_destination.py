"""Typed address intent reaches the provider and survives real profile/A2A code."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from google.genai import types

import b2c_concierge.agent as concierge
from b2c_common.confirmed_location import grounded_landmark, verified_place
from b2c_common.destination_request import address_context_question, refine_landmark
from b2c_common.location_update import adapt_location_update
from b2c_concierge.profile import SessionProfile
from hotel_search_agent import geocode_tool as geo
from hotel_search_agent.mapbox_client import MapboxClient
from hotel_search_agent.response_bridge import (
    capture_after_tool, emit_search_datapart, encode_datapart, find_datapart,
)

from .test_spine import _drive_in, _new_session, scripted  # noqa: F401

QUERY = "144 Example Street, Sampletown, NJ 08043"


def provider_feature():
    return {"geometry": {"coordinates": [-74.9, 39.8]}, "properties": {
        "feature_type": "address", "mapbox_id": "provider:address:144", "name": "144 Example Street",
        "full_address": QUERY, "match_code": {
            "confidence": "exact", "address_number": "matched", "street": "matched"},
        "context": {"country": {"country_code": "US"}, "region": {"name": "New Jersey"},
                    "place": {"name": "Sampletown", "mapbox_id": "provider:city"}},
    }}


def candidate():
    return MapboxClient._parse_candidates({"features": [provider_feature()]})[0]


def context(request=None, confirmed=None):
    return SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
        types.Part(text="under 100"), encode_datapart({"profile_in": {
            "requested_destination": request or {"kind": "address", "query": QUERY},
            "zone": QUERY, "city": None, "confirmed_location": confirmed,
        }, "query_params": {"destination_authoritative": True}}),
    ]))


def test_address_transaction_and_parent_refinement_retain_type():
    raw = {"location_update": {"action": "change", "evidence": QUERY,
                               "targets": [{"kind": "address", "query": QUERY}]}}
    adapted = adapt_location_update(raw, QUERY, None)
    got = grounded_landmark(adapted["requested_landmark"], QUERY)
    assert got["kind"] == "address" and got["query"] == QUERY
    assert got["city"] is None
    refined = refine_landmark(None, {"kind": "address", "query": QUERY}, "refine", "Sampletown")
    assert refined["kind"] == "address" and refined["query"] == QUERY
    assert grounded_landmark({**adapted["requested_landmark"], "query": "invented"}, QUERY) is None


def test_provider_match_components_are_parsed():
    got = candidate()
    assert (got.address_confidence, got.address_number_match, got.street_match) == ("exact", "matched", "matched")


@pytest.mark.parametrize("patch", [
    {"street_match": "unmatched", "address_confidence": "high"},
    {"address_number_match": "plausible"}, {"address_confidence": "low"},
    {"address_confidence": ""}, {"feature_type": "place"}, {"mapbox_id": ""},
])
def test_wrong_street_plausible_number_weak_match_and_city_never_become_address(monkeypatch, patch):
    monkeypatch.setattr(geo, "get_mapbox_client", lambda: SimpleNamespace(
        geocode_candidates=lambda *a, **kw: [replace(candidate(), **patch)]))
    result = geo.geocode_location(zone=QUERY, place_kind="address")
    assert result["ok"] is False and result["error"] == "geocode_ambiguous"
    assert "latitude" not in result
    assert result["diagnostics"]["question"] == address_context_question(QUERY, "en")


def test_multiple_verified_addresses_remain_ambiguous(monkeypatch):
    monkeypatch.setattr(geo, "get_mapbox_client", lambda: SimpleNamespace(geocode_candidates=lambda *a, **kw: [
        candidate(), replace(candidate(), mapbox_id="different:address", latitude=40.),
    ]))
    assert geo.geocode_location(zone=QUERY, place_kind="address")["ok"] is False


def test_address_scope_is_owned_and_verified_point_reused_on_followup(monkeypatch):
    calls = []
    def provider(query, **kwargs):
        calls.append((query, kwargs))
        return [candidate()]
    monkeypatch.setattr(geo, "get_mapbox_client", lambda: SimpleNamespace(geocode_candidates=provider))
    tool = SimpleNamespace(name="geocode_location")
    args = {"city": "Paris", "zone": "downtown", "place_kind": "municipality", "origin": "device"}
    assert geo.inject_profile_geo_context(tool, args, context()) is None
    assert args["place_kind"] == "address" and args["zone"] == QUERY and not args.get("city")
    result = geo.geocode_location(**args)
    assert result["ok"] and result["distance_origin_type"] == "poi"
    point = verified_place(result["resolved_location"])
    assert point["feature_type"] == "address" and point["search_context"]["zone"] == QUERY
    again = geo.inject_profile_geo_context(tool, {"city": "Paris"}, context(confirmed=point))
    assert again["ok"] and again["latitude"] == 39.8 and len(calls) == 1
    assert calls[0][0] == QUERY and calls[0][1]["types"] == "address"


def test_unowned_leaf_address_flag_cannot_change_provider_scope():
    ctx = context(request={"kind": "landmark", "query": QUERY})
    args = {"place_kind": "address"}
    geo.inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, ctx)
    assert "place_kind" not in args


def test_failed_address_emits_typed_clarification(monkeypatch):
    monkeypatch.setattr(geo, "get_mapbox_client", lambda: SimpleNamespace(geocode_candidates=lambda *a, **kw: []))
    ctx = context()
    result = geo.geocode_location(zone=QUERY, place_kind="address")
    capture_after_tool(SimpleNamespace(name="geocode_location"), {}, ctx, result)
    payload = find_datapart(emit_search_datapart(ctx).parts)
    assert payload["requires_clarification"]
    assert payload["destination_clarification"] == {"kind": "address_context", "query": QUERY}


def test_address_clarification_and_city_answer_preserve_address_multiturn(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(date="2027-01-12", budget_max=120)))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return "Which city?", {"results": [], "requires_clarification": True,
                              "destination_clarification": {"kind": "address_context", "query": QUERY}}
    turns = [(QUERY, {"action": "change", "evidence": QUERY, "targets": [{"kind": "address", "query": QUERY}]}),
             ("Sampletown", {"action": "refine", "evidence": "Sampletown", "parent_city": "Sampletown"})]
    for text, transaction in turns:
        scripted(json.dumps({"family": "search", "language": "en", "location_update": transaction}))
        monkeypatch.setattr(concierge, "_run_leaf", leaf)
        events = _drive_in(runner, session.id, text)
        answer = " ".join(p.text for e in events if e.content for p in e.content.parts if p.text)
        assert address_context_question(QUERY, "en") in answer
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.requested_destination["kind"] == "address"
    assert profile.requested_destination["query"] == QUERY and profile.requested_destination["city"] == "Sampletown"
    assert profile.budget_max == 120 and profile.date == "2027-01-12"
    assert all(p["requested_destination"]["kind"] == "address" for p in seen)
