"""Unknown composition permits discovery, never invented counts or booking."""
import asyncio
import json

import pytest
from google.adk.runners import InMemoryRunner

from b2c_common.party_discovery import possible_party
from b2c_concierge import inline_tools
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import SessionProfile, leaf_profile_view
from hotel_search_agent.response_bridge import normalize_search_results

from .test_spine_profile import (  # noqa: F401
    _new_session, _run_turn, _scripted_llm, fake_leg,
)


@pytest.mark.parametrize("offer,total,expected", [
    ({"capacity": 2, "childrenCapacity": 1}, 3, True),
    ({"capacity": 2, "childrenCapacity": 0}, 3, False),
    ({"capacity": 2}, 2, True),
    ({"capacity": 2}, 3, False),
    ({"capacity": True, "childrenCapacity": 5}, 2, False),
    ({"childrenCapacity": 5}, 2, False),
])
def test_capacity_is_a_possible_composition_only(offer, total, expected):
    assert possible_party(offer, total) is expected


def test_changed_total_hides_stale_composition_from_leaf():
    p = SessionProfile(adults=2, children=1, pending_party_total=4)
    view = leaf_profile_view(p)
    assert "adults" not in view and "children" not in view
    assert p.adults == 2 and p.children == 1  # Concierge retains correction context.


@pytest.mark.parametrize("confirmed,picked", [(True, None), (False, 42)])
def test_pending_composition_blocks_all_booking_paths(monkeypatch, confirmed, picked):
    def forbidden():
        raise AssertionError("Booking must not reach MCP before composition")
    monkeypatch.setattr(inline_tools, "_mcp_session", forbidden)
    p = SessionProfile(pending_party_total=3, pending_booking={"hotel_id": 42})
    result = asyncio.run(inline_tools.generate_booking_link("Hotel", p, confirmed, picked))
    assert result == {"ok": False, "error": "party_composition_required"}
    assert p.pending_booking is None


def test_discovery_filters_offers_before_selecting_cheapest():
    offers = [
        {"ratePlanUuid": "too-small", "price": 5000, "capacity": 1, "childrenCapacity": 0},
        {"ratePlanUuid": "possible", "price": 7000, "capacity": 2, "childrenCapacity": 1},
    ]
    cards = normalize_search_results({"results": [{"hotelId": 42, "name": "Example", "offers": offers}]}, party_total=3)
    assert len(cards) == 1 and cards[0]["offer_id"] == "possible"


def test_search_progresses_with_total_and_rejects_leaf_invented_counts(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    from b2c_concierge.a2a_datapart import find_datapart
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City")))
    fake_leg.response_payload = {"results": [{"hotel_id": 42, "name": "Example", "capacity": 2}],
                                 "profile_delta": {"adults": 2, "children": 0}}
    llm = _scripted_llm(monkeypatch, json.dumps({"family": "search", "language": "en",
        "location_update": {"action": "preserve"}, "requested_occupancy": {"total": 2, "evidence": "two"}}))
    text = _run_turn(runner, session.id, "for two")
    outgoing = find_datapart(fake_leg.seen_outgoing_parts)
    assert outgoing["query_params"]["party_total"] == 2
    assert "adults" not in outgoing["profile_in"] and "children" not in outgoing["profile_in"]
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.pending_party_total == 2 and saved.adults is None and saved.children is None
    assert fake_leg.call_count == 1 and len(llm.calls) == 1
    assert "options" in text and "confirmation" in text and "adults and children" in text


def test_room_preference_survives_followup_and_private_access_is_conditional(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    from b2c_concierge.a2a_datapart import find_datapart
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city='Example City')))
    fake_leg.response_payload = {'results': [{'hotel_id': 42, 'name': 'Example'}], 'profile_delta': {}}
    plan = json.dumps({'family': 'search', 'language': 'en', 'location_update': {'action': 'preserve'},
                       'requested_room': {'bedding': 'double', 'private_amenities': ['jacuzzi'],
                                          'evidence': 'double bed and private jacuzzi'}})
    _scripted_llm(monkeypatch, plan)
    first = _run_turn(runner, session.id, 'double bed and private jacuzzi')
    assert 'not confirmed' in first
    assert find_datapart(fake_leg.seen_outgoing_parts)['profile_in']['room_requirements'] == {
        'bedding': 'double', 'private_amenities': ['jacuzzi']}
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
                                        'location_update': {'action': 'preserve'}}))
    second = _run_turn(runner, session.id, 'other options')
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.room_requirements == {'bedding': 'double', 'private_amenities': ['jacuzzi']}
    # PR134-FIX B2: the access warning is said once per requested set, not on
    # every turn that still carries it.
    assert 'not confirmed' not in second
