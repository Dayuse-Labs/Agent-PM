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


@pytest.mark.parametrize("value", [True, -1, 31, "0", 0.5])
def test_invalid_semantic_party_count_is_not_an_update(value):
    from b2c_concierge.triage import _grounded_occupancy
    assert _grounded_occupancy({"children": value, "evidence": "sans enfant"}, "sans enfant") is None


def test_party_update_requires_current_quote_and_preserves_absent_counts():
    from b2c_concierge.triage import _grounded_occupancy
    assert _grounded_occupancy({"children": 0, "evidence": "sans enfant"}, "Paris") is None
    assert _grounded_occupancy({"adults": 0, "evidence": "personne"}, "personne") is None
    assert _grounded_occupancy({"children": 0, "evidence": "sans enfant"}, "Finalement sans enfant") == {"children": 0}
    assert _grounded_occupancy({"adults": 2, "evidence": "deux adultes"}, "deux adultes") == {"adults": 2}


def test_party_retraction_reaches_mcp_and_survives_next_turn(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    from hotel_search_agent.occupancy import inject_profile_occupancy
    from hotel_search_agent.response_bridge import STATE_ZERO_CHILDREN_KEY
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Paris", adults=2, children=1,
        date="2030-10-09", timeslot_start="10:00", timeslot_end="17:00",
        requested_window={"start": "10:00", "end": "17:00"})))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        params = kwargs.get("query_params", {})
        content = types.Content(role="user", parts=[types.Part(text="party update"),
            encode_datapart({"profile_in": profile_in, "query_params": params})])
        context = SimpleNamespace(state={}, user_content=content)
        # Reproduce a copied old count on the update, then a silent follow-up.
        args = {"adults": 2, "children": 1} if not seen else {}
        inject_profile_occupancy(SimpleNamespace(name="search_offers"), args, context)
        seen.append((profile_in.copy(), args.copy(), context.state[STATE_ZERO_CHILDREN_KEY]))
        return "No offers", {"results": [], "profile_delta": {"children": 1} if len(seen) == 1 else {}}
    llm, _ = scripted(json.dumps({"family": "search", "language": "fr", "requested_occupancy": {
        "adults": 2, "children": 0, "evidence": "sans enfant, nous serons seulement deux adultes"}}), "No offers.",
        json.dumps({"family": "search", "language": "fr"}), "No offers.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "Finalement sans enfant, nous serons seulement deux adultes.")
    _drive_in(runner, session.id, "Autres options")
    assert len(seen) == 2
    for profile, args, zero in seen:
        assert profile["adults"] == 2 and profile["children"] == 0
        assert args == {"adults": 2} and zero is True
        assert profile["date"] == "2030-10-09" and profile["timeslot_end"] == "17:00"
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.children == 0
    assert len(llm.calls) == 4


def test_party_counts_survive_city_clarification(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in.copy())
        return "Which city?", {"requires_clarification": True}
    scripted(json.dumps({"family": "search", "language": "en", "requested_occupancy": {
        "adults": 1, "children": 2, "evidence": "one adult and two children"}}), "Which city?",
        json.dumps({"family": "search", "language": "en"}), "Searching Paris.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "A pool for one adult and two children")
    _drive_in(runner, session.id, "Paris")
    assert len(seen) == 2
    assert all(p["adults"] == 1 and p["children"] == 2 for p in seen)


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


@pytest.mark.parametrize("action,expected_zone", [("refine", "23rd st"), ("change", None), (None, None)])
def test_parent_refinement_without_area_extraction_reaches_geocoder(scripted, monkeypatch, fake_profile_store, action, expected_zone):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Manhattan", zone="23rd st",
        date="2026-11-01", requested_window={"start": "18:30", "end": "21:00"})))
    payload = {"family": "search", "language": "en", "requested_budget": None}
    if action:
        payload["location_intent"] = {"action": action, "evidence": "New York, ny, usa"}
    llm, _ = scripted(json.dumps(payload), "Current location result.")
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        params = kwargs.get("query_params", {})
        content = types.Content(role="user", parts=[types.Part(text="New York, ny, usa"),
            encode_datapart({"profile_in": profile_in, "query_params": params})])
        args = {"city": "new york", "zone": "23rd st", "country_code": "US"}
        inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args,
                                   SimpleNamespace(state={}, user_content=content))
        seen.append((args, params, profile_in))
        return "Location unresolved", {"requires_clarification": True}
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "New York, ny, usa")
    args, params, profile = seen[0]
    assert args.get("zone") == expected_zone
    assert bool(params.get("pending_request_refinement")) is (action == "refine")
    assert profile["requested_window"] == {"start": "18:30", "end": "21:00"}
    assert profile["date"] == "2026-11-01"
    assert len(llm.calls) == 2


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


def test_room_requirement_remains_owned_after_location_reply_and_retraction(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    from hotel_search_agent.equipment_ids import enforce_equipment_filters
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city='Paris')))
    observed = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        envelope = {'profile_in': profile_in, 'query_params': kwargs.get('query_params', {})}
        tool_ctx = SimpleNamespace(state={}, user_content=types.Content(role='user', parts=[encode_datapart(envelope)]))
        args = {'amenities': ['jacuzzi'], 'roomEquipmentIds': [41]}
        enforce_equipment_filters(SimpleNamespace(name='search_offers'), args, tool_ctx)
        observed.append((args, envelope['query_params'].get('amenities_authoritative')))
        return 'No offers', {'results': [], 'profile_delta': {'set': {'amenities': ['jacuzzi']}}}
    turns = [
        ('Avec baignoire', {'add': ['bathtub'], 'evidence': 'baignoire'}),
        ('Paris', None),
        ('Enlève la baignoire', {'remove': ['bathtub'], 'evidence': 'Enlève la baignoire'}),
        ('Paris', None),
    ]
    for message, update in turns:
        scripted(json.dumps({'family': 'search', 'language': 'fr', 'requested_amenities': update}), 'No matching offers.')
        monkeypatch.setattr(agent_module, '_run_leaf', leaf)
        _drive_in(runner, session.id, message)
    assert observed == [({'roomEquipmentIds': [11]}, True), ({'roomEquipmentIds': [11]}, True), ({}, True), ({}, True)]


@pytest.mark.parametrize('action,expected_subareas', [
    ('refine', ['Barra da Tijuca', 'Recreio dos Bandeirantes']), ('change', []),
])
def test_city_parent_answer_preserves_unresolved_neighborhood_union(scripted, monkeypatch, fake_profile_store, action, expected_subareas):  # noqa: F811
    from b2c_common.search_areas import validate_areas
    runner, session = _new_session()
    prior = [{'query': name, 'kind': 'municipality', 'country': 'BR', 'evidence': name}
             for name in ['Barra da Tijuca', 'Recreio dos Bandeirantes']]
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city='Barra da Tijuca / Recreio dos Bandeirantes', search_areas=prior,
        date='2026-11-01', amenities=['pool'], amenities_owned=True)))
    scripted(json.dumps({'family': 'search', 'language': 'pt',
        'location_intent': {'action': action, 'evidence': 'Rio de Janeiro'},
        'requested_areas': [{'query': 'Rio de Janeiro', 'kind': 'municipality', 'country': 'BR', 'evidence': 'Rio de Janeiro'}]}),
        'Current search outcome.')
    observed = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        observed.append((profile_in, kwargs['query_params']))
        return 'Areas unresolved', {'requires_clarification': True}
    monkeypatch.setattr(agent_module, '_run_leaf', leaf)
    _drive_in(runner, session.id, 'Rio de Janeiro')
    profile, params = observed[0]
    assert profile['city'] == 'Rio de Janeiro'
    assert profile['date'] == '2026-11-01' and profile['amenities'] == ['pool']
    areas = profile['search_areas']
    assert [a.get('subarea') for a in areas or []] == expected_subareas
    if expected_subareas:
        assert validate_areas(areas) == areas
        assert all(a['query'] == 'Rio de Janeiro' for a in areas)
    assert params['areas_authoritative'] is True


def test_pagination_delivery_is_owned_by_concierge_not_leaf(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city='Paris', last_results=[{'hotel_id': 1, 'name': 'Previous'}], shown_hotel_ids=[1])))
    llm, _ = scripted('{"family":"search","language":"en","wants_more_options":true}',
                      'Additional choices are available.')
    async def leaf(leaf, ctx, profile_in, **kwargs):
        return 'Ask to widen for more options', {'results': [{'id': 2, 'name': 'New option'}],
            'result_delivery': {'kind': 'additional_page', 'new_hotel_count': 0}}
    monkeypatch.setattr(agent_module, '_run_leaf', leaf)
    _drive_in(runner, session.id, 'Other options please')
    prompt = llm.calls[-1]['messages'][-1]['content']
    assert 'additional hotels have ALREADY been returned' in prompt
    assert 'a fresh search is still required' not in prompt
    stored = asyncio.run(fake_profile_store.get(session.id))
    assert stored.last_results[0]['hotel_id'] == 2
    assert len(llm.calls) == 2  # Triage and synthesis, no corrective model phase.
