"""Real concierge turns: a provider place choice survives budget/time refinements."""
import asyncio
import json
from datetime import date, timedelta

import pytest
from b2c_common.confirmed_location import context_for_triage, location_intent, pending_location, verified_place

import b2c_concierge.agent as agent_module
from b2c_concierge.profile import SessionProfile, apply_profile_delta, leaf_profile_view

from .test_spine import _answer, _drive_in, _new_session, scripted  # noqa: F401

VALENCE = {"provider_id": "mapbox:valence-26", "name": "Valence", "label": "Valence, Drôme, France",
           "country_code": "FR", "region": "26", "feature_type": "place", "latitude": 44.93, "longitude": 4.89}
SPAIN = {**VALENCE, "provider_id": "mapbox:valencia-es", "label": "Valence, Espagne", "country_code": "ES", "region": "V", "latitude": 39.47, "longitude": -0.38}
PENDING = {"question": "Valence dans la Drôme ou en Espagne ?", "options": [VALENCE, SPAIN]}


def test_failed_resolution_cannot_overwrite_accepted_location(scripted, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    profile = SessionProfile(city='Valence', country_anchor='FR', confirmed_location=VALENCE,
                             date='2026-11-01', amenities=['pool'])
    asyncio.run(fake_profile_store.set(session.id, profile))
    scripted(json.dumps({'family': 'search', 'language': 'en',
        'location_update': {'action': 'preserve'}}), 'Please clarify the area.', response={
            'requires_clarification': True, 'location_resolution_failed': True,
            'resolved_location': SPAIN,
            'profile_delta': {'city': 'Valencia', 'country_anchor': 'ES',
                              'zone': 'Unverified district', 'state_anchor': 'V'}})
    _drive_in(runner, session.id, 'With a pool')
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.city == 'Valence' and saved.country_anchor == 'FR'
    assert saved.confirmed_location == VALENCE and saved.zone is None
    assert saved.date == '2026-11-01' and saved.amenities == ['pool']


def test_location_rejection_keeps_independent_non_geo_updates():
    from b2c_concierge.location_state import accepted_location_delta
    update = {'city': 'Wrong city', 'search_anchor': {'lat': 1, 'lon': 2},
              'date': '2026-11-01', 'amenities': ['pool']}
    for response in ({'location_resolution_failed': True}, {'requires_clarification': True},
                     {'location_clarification': PENDING, 'requires_clarification': True}):
        assert accepted_location_delta(response, update) == {'date': '2026-11-01', 'amenities': ['pool']}
    assert accepted_location_delta({'resolved_location': VALENCE}, update) == update

AIRPORT = {"provider_id": "provider:airport-vienna", "name": "Vienna International Airport",
           "label": "Vienna International Airport, Schwechat, Austria", "feature_type": "poi",
           "country_code": "AT", "region": "Lower Austria", "latitude": 48.1103, "longitude": 16.5697,
           "search_context": {"city": "Schwechat", "zone": "Vienna International Airport", "metro": None}}


def test_resolved_airport_survives_hour_followup_then_changes_destination(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    from b2c_concierge.location_state import receive_location
    profile = SessionProfile(date="2026-11-01")
    receive_location(profile, {"resolved_location": AIRPORT})
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, profile))
    seen = []

    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs))
        return "No offers", {"results": []}

    scripted(json.dumps({"family": "search", "language": "en",
        "requested_window": {"start": "13:00", "end": "18:00", "evidence": "1300 to 1800"},
        "location_intent": {"action": "preserve", "evidence": "1300 to 1800"}}), "No offers.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "1300 to 1800")
    stored = asyncio.run(fake_profile_store.get(session.id))
    assert stored.confirmed_location == AIRPORT and stored.city == "Schwechat"
    assert stored.zone == AIRPORT["name"]
    assert (stored.timeslot_start, stored.timeslot_end) == ("13:00", "18:00")
    assert seen[0][1]["query_params"]["reuse_confirmed_location"] is True
    scripted(json.dumps({"family": "search", "language": "en",
        "location_intent": {"action": "change", "evidence": "Paris"},
        "requested_areas": [{"query": "Paris", "kind": "municipality", "country": "FR", "evidence": "Paris"}]}), "No offers.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "Paris instead")
    assert seen[-1][0]["confirmed_location"] is None
    assert not seen[-1][1].get("query_params", {}).get("reuse_confirmed_location")


@pytest.mark.parametrize("patch", [{"latitude": True}, {"longitude": float('nan')}, {"provider_id": ""}, {"feature_type": "poi"}])
def test_place_requires_provider_identity_and_valid_coordinates(patch):
    assert verified_place({**VALENCE, **patch}) is None


def test_pending_options_cannot_be_dropped_or_renumbered():
    assert pending_location({**PENDING, "options": [VALENCE, {**SPAIN, "provider_id": ""}]}) is None
    assert pending_location({**PENDING, "options": [VALENCE, VALENCE]}) is None


def test_selection_is_bounded_and_grounded_in_this_reply():
    ctx = context_for_triage(PENDING, None)
    for position in [0, 3, True, "1"]:
        assert location_intent({"action": "select", "position": position, "evidence": "26"}, "26", ctx) is None
    assert location_intent({"action": "select", "position": 1, "evidence": "Drôme"}, "26", ctx) is None
    assert location_intent({"action": "select", "position": 1, "evidence": "26"}, "26", ctx) == {"action": "select", "position": 1}


def test_leaf_delta_cannot_invent_or_clear_confirmation():
    p = SessionProfile(confirmed_location=VALENCE, pending_location=PENDING)
    apply_profile_delta(p, {"confirmed_location": SPAIN, "pending_location": {"op": "clear"}}, "hello")
    assert p.confirmed_location == VALENCE and p.pending_location == PENDING
    assert "pending_location" not in leaf_profile_view(p)
    assert leaf_profile_view(p)["confirmed_location"] == VALENCE


def test_place_choice_and_refinements_preserve_identity(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        pending_location=PENDING, budget_max=90, budget_request_source="explicit",
        date="2026-11-01", amenities=["pool"], timeslot_start="11:00", timeslot_end="16:00",
    )))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs))
        return "Offers checked", {"results": [], "resolved_location": VALENCE,
            "search_date": {"date": "2026-11-01"}, "profile_delta": {"city": "Valence"}}
    scripted(json.dumps({"family": "booking", "language": "fr", "pick": "position", "pick_position": 1,
        "bare_budget_value": 26, "location_intent": {"action": "select", "position": 1, "evidence": "26"}}), "Pas d'offres.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "26")
    p = asyncio.run(fake_profile_store.get(session.id))
    assert p.confirmed_location == VALENCE and p.pending_location is None
    assert p.budget_max == 90 and p.date == "2026-11-01" and p.amenities == ["pool"]
    assert seen[0][1]["query_params"]["reuse_confirmed_location"] is True
    assert seen[0][0]["confirmed_location"]["provider_id"] == VALENCE["provider_id"]
    scripted(json.dumps({"family": "search", "language": "en", "location_intent": {"action": "preserve", "evidence": "With a pool"}}), "No offers.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "With a pool")
    assert len(seen) == 2 and seen[1][1]["query_params"]["reuse_confirmed_location"] is True
    assert seen[1][0]["timeslot_end"] == "16:00"


_FR_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def test_yes_cannot_choose_homonym_and_date_answer_is_preserved(scripted, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(pending_location=PENDING)))
    llm, leaves = scripted('{"family":"ack","language":"fr","location_intent":{"action":"preserve","evidence":"Yes"}}')
    assert _answer(_drive_in(runner, session.id, "Yes")) == PENDING["question"]
    assert len(llm.calls) == 1 and leaves == []
    # Clock-relative (PR134-FIX B4): a literal "12 novembre 2026" stopped
    # being a future date — and stopped testing this — on 2026-11-13.
    day = date.today() + timedelta(days=30)
    said = f"Le {day.day} {_FR_MONTHS[day.month - 1]} {day.year}"
    scripted('{"family":"search","language":"fr","location_intent":{"action":"preserve","evidence":"%s"}}' % said)
    assert _answer(_drive_in(runner, session.id, said)) == PENDING["question"]
    p = asyncio.run(fake_profile_store.get(session.id))
    assert p.date == day.isoformat() and p.pending_location == PENDING


def test_first_clarification_is_terminal_and_clears_stale_cards(scripted, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        last_results=[{"hotel_id": 99, "name": "Old hotel"}], date="2026-11-01")))
    llm, leaves = scripted('{"family":"search","language":"fr"}', response={
        "requires_clarification": True, "location_clarification": PENDING})
    assert _answer(_drive_in(runner, session.id, "Valence")) == PENDING["question"]
    assert len(llm.calls) == 1 and len(leaves) == 1
    p = asyncio.run(fake_profile_store.get(session.id))
    assert p.pending_location == PENDING and p.last_results is None and p.date == "2026-11-01"


def test_new_destination_invalidates_committed_place(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Valence", confirmed_location=VALENCE)))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs))
        return "No offers", {"results": []}
    scripted('{"family":"search","language":"fr","location_intent":{"action":"change","evidence":"Lyon"},"requested_areas":[{"query":"Lyon","kind":"municipality","country":"FR","evidence":"Lyon"}]}', "Pas d'offres.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "Lyon")
    assert seen[0][0]["confirmed_location"] is None
    assert not seen[0][1].get("query_params", {}).get("reuse_confirmed_location")


def test_unverified_changed_city_cannot_keep_old_confirmation():
    from b2c_concierge.location_state import receive_location
    p = SessionProfile(city="Valence", country_anchor="FR", confirmed_location=VALENCE)
    apply_profile_delta(p, {"city": "Lyon"}, "Lyon")
    receive_location(p, {"results": []})
    assert p.confirmed_location is None


def test_existing_grounded_area_answer_selects_without_redundant_flag():
    from b2c_concierge.location_state import selected_place
    p = SessionProfile(pending_location={**PENDING, "options": [
        {**VALENCE, "administrative_code": "26"},
        {**VALENCE, "provider_id": "mapbox:valence82", "administrative_code": "82"},
    ]})
    assert selected_place(p, None, [{"query": "Valence", "country": "FR", "code": "26"}])["provider_id"] == VALENCE["provider_id"]
    assert selected_place(p, None, [{"query": "Valence", "country": "FR"}]) is None
    assert selected_place(p, None, [{"query": "Valence", "country": "FR", "code": "99"}]) is None


def test_compact_hours_reach_leaf_with_confirmed_place(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    from types import SimpleNamespace

    from google.genai import types
    from b2c_concierge.a2a_datapart import encode_datapart
    from hotel_search_agent.datetime_resolver import resolve_search_timeslot
    from hotel_search_agent.geocode_tool import inject_profile_geo_context
    from hotel_search_agent.response_bridge import STATE_EXACT_WINDOW_KEY

    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Valence", confirmed_location=VALENCE)))
    seen = []

    async def leaf(leaf, ctx, profile_in, **kwargs):
        wire = {"profile_in": profile_in, "query_params": kwargs["query_params"]}
        tool_ctx = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
            types.Part(text="1300 - 1800"), encode_datapart(wire),
        ]))
        # A leaf's erroneous device mode cannot override the validated preserving
        # turn. No GPS was supplied and no provider request is needed.
        result = inject_profile_geo_context(SimpleNamespace(name="geocode_location"),
                                            {"city": "", "origin": "device"}, tool_ctx)
        assert result["resolved_location"] == VALENCE
        args = {}
        resolve_search_timeslot(SimpleNamespace(name="search_offers"), args, tool_ctx)
        assert tool_ctx.state[STATE_EXACT_WINDOW_KEY] == {"start_total": 780, "end_total": 1080}
        seen.append(profile_in)
        return "No offers", {"results": [], "resolved_location": VALENCE}

    scripted(json.dumps({"location_intent": {"action": "preserve", "evidence": "1300 - 1800"},
        "family": "search", "language": "de", "requested_window": {
            "start": "13:00", "end": "18:00", "evidence": "1300 - 1800"}}), "Keine Angebote.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "1300 - 1800")
    assert len(seen) == 1 and seen[0]["requested_window"] == {"start": "13:00", "end": "18:00"}


@pytest.mark.parametrize("parent", ["Paris", "", None, 42, "Auckland from history"])
def test_refined_parent_must_be_quoted_in_current_reply(parent):
    ctx = {"unresolved_request": {"zone": "convention centre"}}
    value = {"action": "refine", "parent_city": parent, "evidence": "Auckland"}
    assert location_intent(value, "Auckland", ctx) == {"action": "refine"}


@pytest.mark.parametrize("zone,city", [("convention centre", "Auckland"), ("airport", "Rome")])
def test_parent_reply_resolves_original_target_through_leaf_contract(
    zone, city, scripted, monkeypatch, fake_profile_store  # noqa: F811
):
    from types import SimpleNamespace
    from google.genai import types
    from b2c_concierge.a2a_datapart import encode_datapart
    from hotel_search_agent.geocode_tool import inject_profile_geo_context

    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(zone=zone, date="2026-11-01")))
    seen = []

    async def leaf(leaf, ctx, profile_in, **kwargs):
        wire = {"profile_in": profile_in, "query_params": kwargs["query_params"]}
        tool_ctx = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
            types.Part(text=city), encode_datapart(wire),
        ]))
        # The leaf tries a city-only query: the concierge's combined request
        # must restore the original specific target before provider resolution.
        args = {"city": city, "origin": "destination"}
        result = inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, tool_ctx)
        assert result is None
        assert args["city"] == city and args["zone"] == zone
        assert profile_in["confirmed_location"] is None
        seen.append(args)
        return "Which date?", {"results": []}

    scripted(json.dumps({"family": "search", "language": "en", "location_intent": {
        "action": "refine", "parent_city": city, "evidence": city}}), "Which date?")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, city)
    assert len(seen) == 1
    stored = asyncio.run(fake_profile_store.get(session.id))
    assert stored.city == city and stored.zone == zone
    assert stored.date == "2026-11-01"
