"""Historic failures exercised through actual concierge turns and A2A callbacks."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from google.genai import types

import b2c_concierge.agent as agent_module
from b2c_concierge.a2a_datapart import encode_datapart
from b2c_concierge.profile import SessionProfile, select_best_rated_hotel
from hotel_search_agent.geocode_tool import inject_profile_geo_context

from .test_location_confirmation import AIRPORT
from .test_spine import _answer, _drive_in, _new_session, scripted  # noqa: F401


@pytest.mark.parametrize("prior", [None, AIRPORT])
def test_new_address_wins_over_conflicting_parent_extraction(prior, scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city="New York", zone="542 West 47th Street", confirmed_location=prior, date="2026-11-01")))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs["query_params"]))
        return "Checked", {"results": []}
    scripted(json.dumps({"family": "search", "language": "en", "location_intent": {
        "action": "refine", "parent_city": "547 West 47th Street", "evidence": "547 West 47th Street"},
        "requested_landmark": {"query": "547 West 47th Street", "city": "New York",
                               "evidence": "547 West 47th Street, New York"}}), "Checked")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "Correction: 547 West 47th Street, New York")
    assert seen[0][0]["zone"] == "547 West 47th Street"
    assert seen[0][0]["city"] == "New York"
    assert seen[0][0]["confirmed_location"] is None
    assert seen[0][1]["landmark_authoritative"] is True


def test_parent_correction_reresolves_even_a_previously_confirmed_scope(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city="Schwechat", zone="Vienna International Airport", confirmed_location=AIRPORT,
        date="2026-11-01", budget_max=100)))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs["query_params"]))
        return "Checked", {"results": []}
    scripted(json.dumps({"family": "search", "language": "en", "location_intent": {
        "action": "refine", "parent_city": "Vienna", "evidence": "Vienna"}}), "Checked")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "In Vienna")
    p, q = seen[0]
    assert p["city"] == "Vienna" and p["zone"] == "Vienna International Airport"
    assert p["confirmed_location"] is None and p["budget_max"] == 100
    assert q["landmark_authoritative"] and not q.get("reuse_confirmed_location")


def test_no_destination_cannot_be_inferred_from_timezone_or_amenity(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(client_timezone="Europe/Rome")))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        tool_ctx = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
            types.Part(text="Vorrei una camera con doccia"),
            encode_datapart({"profile_in": profile_in, "query_params": kwargs["query_params"]}),
        ]))
        answer = inject_profile_geo_context(SimpleNamespace(name="geocode_location"),
            {"city": "Rome", "zone": "camera con doccia"}, tool_ctx)
        assert answer["error"] == "geocode_ambiguous"
        seen.append(answer)
        return answer["diagnostics"]["question"], {"results": [], "requires_clarification": True,
            "profile_delta": {"city": "Rome", "zone": "camera con doccia"}}
    scripted('{"family":"search","language":"it","location_intent":{"action":"missing","evidence":"Vorrei una camera con doccia"}}', "In quale città?")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "Vorrei una camera con doccia")
    p = asyncio.run(fake_profile_store.get(session.id))
    assert len(seen) == 1 and p.city is None and p.zone is None


@pytest.mark.parametrize("message", ["???", "aucune"])
def test_misclassified_active_reply_keeps_search_context(message, scripted, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Paris", language="fr",
        last_results=[{"hotel_id": 42, "name": "Hotel"}])))
    llm, leaves = scripted('{"family":"ack","language":"fr"}')
    answer = _answer(_drive_in(runner, session.id, message))
    assert "Paris" in answer and "modifier" in answer and "Bonjour" not in answer
    assert not leaves and len(llm.calls) == 1
    assert asyncio.run(fake_profile_store.get(session.id)).last_results[0]["hotel_id"] == 42


def test_best_rating_uses_scores_not_rank_or_price():
    rows = [{"hotel_id": 1, "rating": 4.526}, {"hotel_id": 2, "rating": 4.666},
            {"hotel_id": 3, "rating": None}, {"hotel_id": 4, "rating": float("nan")},
            {"hotel_id": 5, "rating": True}, {"hotel_id": 6, "rating": 9}]
    assert select_best_rated_hotel(rows)["hotel_id"] == 2
    assert select_best_rated_hotel(rows[2:]) is None


def test_best_rating_pick_routes_to_verified_hotel_details(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Paris", last_results=[
        {"hotel_id": 1, "rating": 4.526}, {"hotel_id": 2, "rating": 4.666}])))
    seen = []
    async def inline(self, *args, **kwargs):
        seen.append(kwargs["picked_hotel_id"])
        if False:
            yield None
    monkeypatch.setattr(agent_module._B2cConcierge, "_run_inline_lookup", inline)
    scripted('{"family":"details","language":"fr","pick":"best_rated"}')
    _drive_in(runner, session.id, "Le mieux noté parmi ceux-là ?")
    assert seen == [2]
