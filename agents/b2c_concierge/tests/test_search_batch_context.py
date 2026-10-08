"""Regression seams from the frozen search campaign; no network or model calls."""
import asyncio
import json
from datetime import date
from types import SimpleNamespace

import pytest
from google.genai import types

import b2c_concierge.agent as agent_module
from b2c_concierge.profile import SessionProfile
from b2c_concierge.requested_date import expected_search_date
from b2c_concierge.triage import _grounded_weekday
from b2c_common.date_labels import grounded_calendar
from b2c_common.confirmed_location import context_for_triage
from b2c_common.search_areas import validate_areas
from hotel_search_agent.geocode_tool import inject_profile_geo_context
from hotel_search_agent.response_bridge import encode_datapart, inject_origin_sort

from .test_spine import _drive_in, _new_session, scripted  # noqa: F401


def test_numeric_dates_never_authorize_weekday_rollover():
    for message in ("Philadelphia on the 24th", "12am 09/10 check in"):
        evidence = "24th" if "24th" in message else "09/10"
        assert _grounded_weekday({"value": "friday", "evidence": evidence}, message) is None
    assert _grounded_weekday({"value": "friday", "evidence": "vendredi"}, "Pour vendredi") == "friday"


@pytest.mark.parametrize("message,parts,today,expected", [
    ("on the 24th", {"day": 24}, date(2026, 10, 8), "2026-10-24"),
    ("09/10", {"day": 9, "month": 10}, date(2026, 10, 9), "2026-10-09"),
    ("on the 2nd", {"day": 2}, date(2026, 12, 30), "2027-01-02"),
    ("31", {"day": 31}, date(2026, 4, 15), "2026-05-31"),
])
def test_calendar_components_override_carried_date_and_wrong_weekday(message, parts, today, expected):
    typed = grounded_calendar({**parts, "evidence": message}, message)
    assert typed is not None
    assert expected_search_date(message, "2026-10-10", today, weekday="friday", calendar=typed) == (expected, True)


@pytest.mark.parametrize("patch", [{"day": 13}, {"day": True}, {"day": 32}, {"year": 2027}, {"evidence": "old"}])
def test_calendar_provenance_rejects_unquoted_numbers(patch):
    assert grounded_calendar({"day": 24, "evidence": "24th", **patch}, "24th") is None


def test_normalized_spelling_preserves_two_requested_areas_not_arbitrary_identity():
    areas = [dict(query="Tuen Mun", kind="municipality", country="HK", evidence="Tuenmun"),
             dict(query="Tung Chung", kind="municipality", country="HK", evidence="tungchung")]
    assert len(validate_areas(areas, "Tuenmun, tungchung")) == 2
    assert validate_areas([{**areas[0], "query": "Paris"}], "Tuenmun") is None
    assert validate_areas([{**areas[0], "code": "CA"}], "Tuenmun") is None


def test_region_and_native_origin_are_visible_without_exposing_coordinates():
    context = context_for_triage(None, None, areas=[{"query": "Yvelines"}], device_available=True)
    assert context == {"requested_areas": [{"query": "Yvelines"}], "device_available": True}


@pytest.mark.parametrize("action,expected_zone", [("refine", "al mankool"), ("change", None)])
def test_city_clarification_preserves_unresolved_zone_but_new_destination_clears_it(scripted, monkeypatch, fake_profile_store, action, expected_zone):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(zone="al mankool", date="2026-11-01", timeslot_start="13:00")))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        envelope = {"profile_in": profile_in, "query_params": kwargs["query_params"]}
        tool_ctx = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[types.Part(text="at Dubai"), encode_datapart(envelope)]))
        args = {"city": "Dubai", "zone": "old copied district"}
        inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, tool_ctx)
        seen.append((profile_in, args))
        return "No offers", {"results": []}
    scripted(json.dumps({"family": "search", "language": "en", "location_intent": {"action": action, "evidence": "Dubai"},
        "requested_areas": [{"query": "Dubai", "kind": "municipality", "country": "AE", "evidence": "Dubai"}]}), "No offers.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "at Dubai")
    p, args = seen[0]
    assert p["zone"] == expected_zone and args.get("zone") == expected_zone
    assert p["date"] == "2026-11-01" and p["timeslot_start"] == "13:00"


def test_owned_device_intent_wins_over_leaf_copied_city():
    ctx = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
        types.Part(text="Near me"), encode_datapart({"profile_in": {"city": "Paris", "search_anchor": {"type": "gps", "lat": 48.6, "lon": 1.6}},
                                                  "query_params": {"device_authoritative": True}})]))
    result = inject_profile_geo_context(SimpleNamespace(name="geocode_location"), {"city": "Paris", "origin": "destination"}, ctx)
    assert result["ok"] and result["distance_origin_type"] == "gps"
    assert result["latitude"] == 48.6 and result["longitude"] == 1.6


@pytest.mark.parametrize("origin,expected", [(None, None), ({"type": "city_centroid"}, "distance"), ({"type": "poi"}, "distance")])
def test_backend_sorts_verified_city_and_landmark_before_pagination(origin, expected):
    args = {"from": 5, "size": 5, "date": "2026-11-01", "priceMax": 20000}
    inject_origin_sort(SimpleNamespace(name="search_offers"), args, SimpleNamespace(state={"temp:hotel_search_anchor": origin}))
    assert args.get("sortBy") == expected
    assert args["from"] == 5 and args["date"] == "2026-11-01" and args["priceMax"] == 20000
