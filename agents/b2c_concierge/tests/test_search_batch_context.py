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


@pytest.mark.parametrize("action,expected_zone", [("refine", "al mankool"), (None, "al mankool"), ("change", None)])
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


def test_pending_empty_location_is_explicit_in_triage_context():
    assert context_for_triage(None, None, unresolved={}) == {"unresolved_request": {}}


@pytest.mark.parametrize("city,zone,expected_city,expected_zone", [
    ("New York City", "Manhattan", "Manhattan", None),
    ("Chicago", "copied district", "Manhattan", None),
])
def test_leaf_cannot_promote_owned_municipality_into_unverified_poi(city, zone, expected_city, expected_zone):
    context = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
        types.Part(text="Manhattan, New York, USA"), encode_datapart({
            "profile_in": {"city": "Manhattan", "country_anchor": "US"},
            "query_params": {"areas_authoritative": True}})]))
    args = {"city": city, "zone": zone, "country_code": "CA"}
    inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, context)
    assert args["city"] == expected_city and args.get("zone") == expected_zone
    assert args["country_code"] == "US"


def test_daypart_survives_city_clarification_and_replaces_old_clock(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(timeslot_start="09:00", timeslot_end="12:00",
        requested_window={"start": "09:00", "end": "12:00"}, requested_duration_minutes=180)))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in.copy())
        return "Which town?", {"requires_clarification": True}
    llm = scripted(json.dumps({"family": "search", "language": "en", "requested_daypart": {"value": "evening", "evidence": "evening"}}),
                   "Which town?", json.dumps({"family": "search", "language": "en", "requested_areas": [
                       {"query": "Farnborough", "kind": "municipality", "country": "GB", "evidence": "Farnborough"}]}), "Checking Farnborough.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "I need an evening room instead")
    _drive_in(runner, session.id, "Farnborough")
    assert len(seen) == 2
    for profile in seen:
        assert profile["daypart"] == "evening"
        assert profile["timeslot_start"] is None and profile["timeslot_end"] is None
        assert profile["requested_duration_minutes"] is None
    assert llm[0].calls[0]["response_format"] == {"type": "json_object"}


def test_daypart_requires_current_quote_and_supported_value():
    from b2c_concierge.triage import _grounded_daypart
    assert _grounded_daypart({"value": "evening", "evidence": "soirée"}, "En soirée svp") == "evening"
    assert _grounded_daypart({"value": "evening", "evidence": "evening"}, "Farnborough") is None
    assert _grounded_daypart({"value": "midnight", "evidence": "midnight"}, "midnight") is None


def test_currency_waits_for_actual_inventory_and_survives_city_answer(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    from .test_spine import _answer
    runner, session = _new_session()
    scripted('{"family":"search","language":"en","display_currency":"USD"}', 'Which city?',
             '{"family":"search","language":"en"}', 'Here is an offer in dollars.')
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        if len(seen) == 1:
            return 'Which city?', {'results': [], 'requires_clarification': True}
        return 'Found an offer', {'results': [{'id': 77, 'name': 'Example Hotel', 'price': '€90.00',
             'hotel_price': 'USD 100.00', 'hotel_price_minor': 10000, 'hotel_currency_code': 'USD'}]}
    monkeypatch.setattr(agent_module, '_run_leaf', leaf)
    first = _answer(_drive_in(runner, session.id, 'A room tomorrow with prices in USD'))
    assert "can't show prices in USD" not in first
    _drive_in(runner, session.id, 'New York')
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.requested_currency == 'USD' and saved.display_currency == 'HOTEL'
    assert saved.last_results[0]['price'] == 'USD 100.00'


@pytest.mark.parametrize('city,zone', [('Milano', 'dintorni'), ('Strasbourg', None)])
def test_owned_city_controls_origin_and_does_not_create_an_unowned_poi(city, zone):
    context = SimpleNamespace(state={}, user_content=types.Content(role='user', parts=[
        types.Part(text=f'{city} {zone or ""}'), encode_datapart({
            'profile_in': {'city': city, 'country_anchor': 'IT' if city == 'Milano' else 'FR'},
            'query_params': {'areas_authoritative': True}})]))
    args = {'city': city, 'zone': zone, 'origin': 'device'}
    result = inject_profile_geo_context(SimpleNamespace(name='geocode_location'), args, context)
    assert result is None  # Continue to ordinary provider resolution, no fabricated result.
    assert args['origin'] == 'destination' and args['city'] == city
    assert 'zone' not in args


def test_landmark_parent_can_only_reuse_identical_provider_confirmed_city():
    from b2c_common.confirmed_location import grounded_landmark
    raw = {'query': 'LAX airport', 'city': 'Los Angeles', 'country_guess': 'US', 'evidence': 'LAX airport'}
    assert grounded_landmark(raw, 'Near LAX airport')['city'] is None
    assert grounded_landmark(raw, 'Near LAX airport', confirmed_city='Los Angeles', confirmed_country='US')['city'] == 'Los Angeles'
    assert grounded_landmark(raw, 'Near LAX airport', confirmed_city='Paris', confirmed_country='FR')['city'] is None
    assert grounded_landmark({**raw, 'country_guess': 'CA'}, 'Near LAX airport',
                             confirmed_city='Los Angeles', confirmed_country='US')['city'] is None


def test_facility_followup_cannot_override_confirmed_city_with_device_origin(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    place = {'provider_id': 'verified-dublin', 'name': 'Dublin', 'label': 'Dublin, Ireland', 'country_code': 'IE',
             'feature_type': 'place', 'latitude': 53.34938, 'longitude': -6.260559, 'region': 'Dublin'}
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city='Dublin', confirmed_location=place)))
    scripted('{"family":"search","language":"en","requested_amenities":{"add":["pool"],"remove":[],"evidence":"pool"}}',
             'No matching offers.')
    observed = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        envelope = {'profile_in': profile_in, 'query_params': kwargs['query_params']}
        tool_ctx = SimpleNamespace(state={}, user_content=types.Content(role='user', parts=[
            types.Part(text='With a pool'), encode_datapart(envelope)]))
        result = inject_profile_geo_context(SimpleNamespace(name='geocode_location'), {'city': 'Dublin', 'origin': 'device'}, tool_ctx)
        observed.append(result)
        return 'No offers', {'results': []}
    monkeypatch.setattr(agent_module, '_run_leaf', leaf)
    _drive_in(runner, session.id, 'With a pool')
    assert observed[0]['ok'] is True
    assert observed[0]['resolved_location']['provider_id'] == 'verified-dublin'
    assert observed[0]['distance_origin_type'] == 'city_centroid'
