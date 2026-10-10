"""Customer request survives failed resolution, corrections and leaf drift."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from google.genai import types

from b2c_common.confirmed_location import context_for_triage
from b2c_common.destination_request import destination_request, refine_landmark
import b2c_concierge.agent as agent_module
from b2c_concierge.a2a_datapart import encode_datapart
from b2c_concierge.location_state import receive_location
from b2c_concierge.profile import SessionProfile, apply_profile_delta
from b2c_concierge.templates import contextual_ack_response
from hotel_search_agent.geocode_tool import inject_profile_geo_context

from .test_location_confirmation import AIRPORT
from .test_spine import _drive_in, _new_session, scripted  # noqa: F401


def _landmark(query="La Defanse", city="Courbevoie"):
    return {"kind": "landmark", "query": query, "city": city}


@pytest.mark.parametrize("patch", [
    {"latitude": 48.0}, {"kind": "verified"}, {"query": ""},
    {"kind": "device"}, {"country_guess": "France"}, {"city": 42},
])
def test_request_cannot_supply_provider_evidence_or_invalid_state(patch):
    assert destination_request({**_landmark(), **patch}) is None


def test_request_remains_distinct_from_provider_answer_and_survives_storage():
    requested = _landmark("Vienna International Airport", "Vienna")
    profile = SessionProfile(requested_destination=requested)
    receive_location(profile, {"resolved_location": AIRPORT})
    profile = SessionProfile.from_dict(json.loads(json.dumps(profile.to_dict())))
    assert profile.city == "Schwechat" and profile.requested_destination == requested
    context = context_for_triage(None, profile.confirmed_location, requested=profile.requested_destination)
    assert context["requested_destination"]["city"] == "Vienna"
    assert context["confirmed_place"] == AIRPORT["label"]
    assert context["confirmed_city"] is None  # No provider parent in this fixture.


@pytest.mark.parametrize("action,expected", [("correct", "Courbevoie"), ("change", None), (None, None)])
def test_only_same_target_correction_can_inherit_unresolved_parent(action, expected):
    update = {"query": "La Défense", "city": None, "country_guess": None}
    assert refine_landmark(update, _landmark(), action, None)["city"] == expected
    assert refine_landmark({**update, "city": "Paris"}, _landmark(), action, None)["city"] == "Paris"


def test_leaf_cannot_replace_request_or_clear_its_aliases():
    profile = SessionProfile(city="Courbevoie", zone="La Défense", requested_destination=_landmark("La Défense"))
    apply_profile_delta(profile, {
        "requested_destination": {"op": "clear"}, "city": {"op": "set", "value": "Paris"},
        "zone": {"op": "clear"}, "metro": "somewhere", "budget_max": 80,
    }, "under 80 EUR")
    assert profile.city == "Courbevoie" and profile.zone == "La Défense"
    assert profile.metro is None and profile.budget_max == 80
    assert profile.requested_destination == _landmark("La Défense")


def test_active_destination_precedes_a_fragment_of_a_stale_clarifying_question():
    response = contextual_ack_response("nl", "Den Bosch", "Eindhoven/Tilburg/Utrecht) om meer opties te vinden?")
    assert "Den Bosch" in response and "Eindhoven" not in response


def test_leaf_cannot_reduce_requested_union_or_replace_it_with_device(monkeypatch):
    areas = [{"query": name, "kind": "municipality", "country": "PT", "evidence": name}
             for name in ("Lisbon", "Porto")]
    request = {"kind": "areas", "areas": areas}
    seen = []
    def resolve(scoped, client, language):
        seen.append(scoped)
        return {"ok": True, "areas": scoped}
    monkeypatch.setattr("hotel_search_agent.geocode_tool.resolve_areas", resolve)
    monkeypatch.setattr("hotel_search_agent.geocode_tool.get_mapbox_client", lambda: object())
    ctx = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
        types.Part(text="cheaper"), encode_datapart({"profile_in": {
            "requested_destination": request, "city": "Porto", "search_areas": areas,
        }, "query_params": {"destination_authoritative": True}}),
    ]))
    args = {"city": "Porto", "origin": "device"}
    assert inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, ctx)["ok"]
    assert seen == [areas] and args["origin"] == "destination"


def test_multiturn_correction_retains_customer_parent_without_fabricating_confirmation(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(date="2026-11-01")))
    seen = []

    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs["query_params"]))
        return "Please clarify", {"results": [], "profile_delta": {"city": "Paris", "zone": "city centre"}}

    turns = [
        ("La Defanse à Courbevoie", {"requested_landmark": {
            "query": "La Defanse", "city": "Courbevoie", "evidence": "La Defanse à Courbevoie"}}),
        ("Pardon, La Défense", {"location_intent": {"action": "correct", "evidence": "Pardon, La Défense"},
            "requested_landmark": {"query": "La Défense", "evidence": "La Défense"}}),
        ("moins de 80 EUR", {"location_intent": {"action": "preserve", "evidence": "moins de 80 EUR"}}),
    ]
    for text, extraction in turns:
        scripted(json.dumps({"family": "search", "language": "fr", **extraction}), "Please clarify")
        monkeypatch.setattr(agent_module, "_run_leaf", leaf)
        _drive_in(runner, session.id, text)
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.requested_destination == _landmark("La Défense")
    assert profile.city == "Courbevoie" and profile.zone == "La Défense"
    assert profile.confirmed_location is None and profile.distance_origin is None
    assert all(q["destination_authoritative"] for _, q in seen)
    # Exercise the actual A2A enforcement on the non-geographic third turn.
    p, q = seen[-1]
    ctx = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
        types.Part(text="moins de 80 EUR"), encode_datapart({"profile_in": p, "query_params": q}),
    ]))
    args = {"city": "Paris", "zone": "centre", "origin": "device"}
    assert inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, ctx) is None
    assert args["city"] == "Courbevoie" and args["zone"] == "La Défense"
    assert args["origin"] == "destination"


def test_new_city_clears_device_intent_and_leaf_cannot_revive_near_me(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        requested_destination={"kind": "device"}, date="2026-11-01")))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs["query_params"]))
        return "Checked", {"results": [], "profile_delta": {"zone": "mij in de buurt"}}
    scripted(json.dumps({"family": "search", "language": "nl", "location_intent": {
        "action": "change", "evidence": "Heemskerk"}, "requested_areas": [
            {"query": "Heemskerk", "kind": "municipality", "country": "NL", "evidence": "Heemskerk"}]}), "Checked")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "Heemskerk")
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.city == "Heemskerk" and profile.zone is None
    assert profile.requested_destination["kind"] == "areas"
    p, q = seen[0]
    ctx = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
        types.Part(text="Heemskerk"), encode_datapart({"profile_in": p, "query_params": q}),
    ]))
    args = {"city": "Amsterdam", "zone": "mij in de buurt", "origin": "device"}
    assert inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, ctx) is None
    assert args["city"] == "Heemskerk" and not args.get("zone") and args["origin"] == "destination"


def test_multiturn_alternative_landmarks_keep_all_targets_and_shared_filters(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(date="2026-11-01", adults=2, children=1)))
    seen = []

    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs["query_params"]))
        return "Please clarify", {"results": [], "profile_delta": {"city": "Unrelated City", "zone": "centre"}}

    turns = [
        ("North airport or South station", {"action": "change", "evidence": "North airport or South station",
          "targets": [{"kind": "landmark", "query": name} for name in ["North airport", "South station"]]}),
        ("Example City", {"action": "refine", "parent_city": "Example City", "evidence": "Example City"}),
        ("under 80 EUR", {"action": "preserve"}),
    ]
    for text, update in turns:
        scripted(json.dumps({"family": "search", "language": "en", "location_update": update}), "Please clarify")
        monkeypatch.setattr(agent_module, "_run_leaf", leaf)
        _drive_in(runner, session.id, text)
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert len(seen) == 3
    assert saved.requested_destination == {"kind": "landmarks", "landmarks": [
        {"query": "North airport", "city": "Example City"},
        {"query": "South station", "city": "Example City"},
    ]}
    assert saved.city is None and saved.zone is None and saved.confirmed_location is None
    assert saved.date == "2026-11-01" and saved.adults == 2 and saved.children == 1
    assert all(q["destination_authoritative"] for _, q in seen)
    assert all(p["requested_destination"]["kind"] == "landmarks" for p, _ in seen)
    assert all(len(p["requested_destination"]["landmarks"]) == 2 for p, _ in seen)


def test_landmark_context_question_is_transported_without_choice_synthesis(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    seen = []

    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        request = profile_in["requested_destination"]
        if request["kind"] == "landmarks":
            return "Which city?", {"requires_clarification": True, "destination_clarification": {
                "kind": "landmark_context", "queries": [p["query"] for p in request["landmarks"]]}}
        return "Searched", {"results": []}

    turns = [
        ("North airport or South station", {"action": "change", "evidence": "North airport or South station",
          "targets": [{"kind": "landmark", "query": name} for name in ["North airport", "South station"]]}),
        ("Example City", {"action": "refine", "parent_city": "Example City", "evidence": "Example City"}),
        ("Switch to Coastal City instead", {"action": "change", "evidence": "Switch to Coastal City instead",
          "targets": [{"kind": "city", "query": "Coastal City"}]}),
    ]
    for i, (text, update) in enumerate(turns):
        scripted(json.dumps({"family": "search", "language": "en", "location_update": update}), "BAD: Choose just one place")
        monkeypatch.setattr(agent_module, "_run_leaf", leaf)
        events = _drive_in(runner, session.id, text)
        profile = asyncio.run(fake_profile_store.get(session.id))
        if i < 2:
            answer = " ".join(p.text for e in events if e.content for p in e.content.parts or [] if p.text)
            assert "BAD:" not in answer
            assert "North airport" in answer and "South station" in answer
            assert profile.last_clarifying_question in answer
            if i == 0:
                assert "which city" in answer.lower()
            else:
                assert "Example City" in answer and "address or terminal" in answer
    assert [p['requested_destination']['kind'] for p in seen] == ['landmarks', 'landmarks', 'areas']
    assert profile.requested_destination['areas'][0]['query'] == 'Coastal City'


def test_party_total_confirmation_keeps_children_and_unknown_total_is_clarified(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Paris", adults=2, children=1)))
    seen = []

    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return "Checked", {"results": []}

    for text, occupancy in [
        ("we are three", {"total": 3}),
        ("now four people", {"total": 4}),
        ("one child", {"children": 1}),
    ]:
        scripted(json.dumps({"family": "search", "language": "en", "location_update": {"action": "preserve"},
                             "requested_occupancy": {**occupancy, "evidence": text}}), "Checked")
        monkeypatch.setattr(agent_module, "_run_leaf", leaf)
        _drive_in(runner, session.id, text)
        saved = asyncio.run(fake_profile_store.get(session.id))
        if text == 'now four people':
            assert saved.pending_party_total == 4
            assert len(seen) == 2  # Conditional discovery does not invent a composition.
            assert 'adults' not in seen[-1] and 'children' not in seen[-1]
            assert '4 guests' in saved.last_clarifying_question
    assert [(p.get('adults'), p.get('children')) for p in seen] == [(2, 1), (None, None), (3, 1)]
    assert saved.pending_party_total is None
