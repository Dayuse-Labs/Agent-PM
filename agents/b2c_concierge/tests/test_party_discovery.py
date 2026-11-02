"""Unknown composition permits discovery, never invented counts — nor a question.

2026-11-02: an unsplit total is never asked about and blocks neither the
cards nor the link (prod: dates and hours read as parties ended on « Of these
9 guests, how many are adults… » with no card).

Ported from #134 (`test_party_discovery.py`), slice 5 of PORT1. Left out:
`location_update` (Géographie) and the private-access warning (equipment).
"""
import asyncio
import json

import pytest
from google.adk.runners import InMemoryRunner

from b2c_common.party_discovery import possible_party
from b2c_concierge import inline_tools
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.ground_truth import shortlist_ground_truth_block
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


def test_a_pending_total_no_longer_refuses_the_link(monkeypatch):
    p = SessionProfile(pending_party_total=3, pending_booking=None, last_results=[])
    result = asyncio.run(inline_tools.generate_booking_link("Hotel", p, False, None))
    assert result.get("error") != "party_composition_required"


def test_discovery_filters_offers_before_selecting_cheapest():
    offers = [
        {"ratePlanUuid": "too-small", "price": 5000, "capacity": 1, "childrenCapacity": 0},
        {"ratePlanUuid": "possible", "price": 7000, "capacity": 2, "childrenCapacity": 1},
    ]
    cards = normalize_search_results({"results": [{"hotelId": 42, "name": "Example", "offers": offers}]}, party_total=3)
    assert len(cards) == 1 and cards[0]["offer_id"] == "possible"


def test_search_progresses_with_total_and_rejects_leaf_invented_counts(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City")))
    fake_leg.response_payload = {"results": [{"hotel_id": 42, "name": "Example", "capacity": 2}],
                                 "profile_delta": {"adults": 2, "children": 0}}
    llm = _scripted_llm(monkeypatch, json.dumps({"family": "search", "language": "en",
        "requested_occupancy": {"names_people": True, "total": 2, "evidence": "two"}}), "Here is Example.")
    text = _run_turn(runner, session.id, "for two")
    outgoing = find_datapart(fake_leg.seen_outgoing_parts)
    assert outgoing["query_params"]["party_total"] == 2
    assert "adults" not in outgoing["profile_in"] and "children" not in outgoing["profile_in"]
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.pending_party_total == 2 and saved.adults is None and saved.children is None
    assert fake_leg.call_count == 1 and len(llm.calls) == 2  # triage + the usual synthesis
    assert text == "Here is Example." and "adults and children" not in text
    assert saved.last_clarifying_question is None


def test_an_empty_page_for_an_unknown_composition_is_answered_like_any_empty_page(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City")))
    fake_leg.response_payload = {"results": []}
    _scripted_llm(monkeypatch, json.dumps({"family": "search", "language": "en",
        "requested_occupancy": {"names_people": True, "total": 4, "evidence": "four of us"}}), "Nothing here today.")
    text = _run_turn(runner, session.id, "four of us")
    assert "adults" not in text and "guests" not in text
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.pending_party_total == 4


def test_the_composition_answer_resolves_the_pending_total(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City", pending_party_total=3)))
    fake_leg.response_payload = {"results": [{"hotel_id": 42, "name": "Example"}]}
    _scripted_llm(monkeypatch, json.dumps({"family": "search", "language": "en",
        "requested_occupancy": {"names_people": True, "children": 1, "evidence": "one child"}}), "Here is Example.")
    _run_turn(runner, session.id, "one child")
    outgoing = find_datapart(fake_leg.seen_outgoing_parts)
    assert outgoing["query_params"]["occupancy_update"] == {"children": 1, "adults": 2}
    assert "party_total" not in outgoing["query_params"]
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert (saved.adults, saved.children, saved.pending_party_total) == (2, 1, None)


def test_a_total_on_a_booking_turn_goes_on_to_the_booking(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    seen = {}

    async def booking(self, ctx, profile, *args, **kwargs):
        seen["party_total"] = profile.pending_party_total
        yield self._final(ctx, "Please confirm this offer.")

    monkeypatch.setattr(type(root_agent), "_run_booking", booking)
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City", last_results=[
        {"hotel_id": 42, "name": "Example", "offer_id": "o", "offer_date": "2026-11-01"}])))
    _scripted_llm(monkeypatch, json.dumps({"family": "booking", "language": "en",
        "requested_occupancy": {"names_people": True, "total": 3, "evidence": "for three"}, "hotel_name": "Example"}))
    text = _run_turn(runner, session.id, "Book Example for three")
    assert text == "Please confirm this offer."
    assert seen["party_total"] == 3


def test_room_preference_survives_followup(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city='Example City')))
    fake_leg.response_payload = {'results': [{'hotel_id': 42, 'name': 'Example'}],
                                 'profile_delta': {'room_requirements': {'op': 'clear'}}}
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en',
                  'requested_room': {'bedding': 'double', 'evidence': 'double bed'}}), 'Here is Example.')
    _run_turn(runner, session.id, 'a double bed please')
    assert find_datapart(fake_leg.seen_outgoing_parts)['profile_in']['room_requirements'] == {'bedding': 'double'}
    _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en'}), 'More.')
    _run_turn(runner, session.id, 'other options')
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.room_requirements == {'bedding': 'double'}


def test_room_requirements_reach_synthesis_as_intent_not_fact():
    block = shortlist_ground_truth_block({'results': [{'name': 'Example'}]},
                                         SessionProfile(room_requirements={'bedding': 'double'}))
    assert "ROOM REQUIREMENTS (customer intent, not verified facts): {'bedding': 'double'}" in block


def test_a_composition_given_on_a_booking_turn_is_kept_and_unblocks_the_link(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    # Review fix: the answer to the composition question may come with "book it".
    seen = {}

    async def booking(self, ctx, profile, *args, **kwargs):
        seen["party"] = (profile.adults, profile.children, profile.pending_party_total)
        yield self._final(ctx, "Please confirm this offer.")

    monkeypatch.setattr(type(root_agent), "_run_booking", booking)
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City", pending_party_total=3)))
    _scripted_llm(monkeypatch, json.dumps({"family": "booking", "language": "en", "hotel_name": "Example",
        "requested_occupancy": {"names_people": True, "adults": 2, "children": 1, "evidence": "2 adults and 1 child"}}))
    _run_turn(runner, session.id, "2 adults and 1 child, book Example")
    assert seen["party"] == (2, 1, None)  # _run_booking (faked here) saves the profile


def test_shown_offers_are_revalidated_without_re_filtering_bed_or_party(monkeypatch):
    from .test_dated_details import _dated_profile, receipt
    from .test_inline_tools import FakeResult, _install, _run
    _install(monkeypatch, {"get_hotel_details": lambda a: FakeResult(receipt(a))})
    profile = _dated_profile(2)
    profile.room_requirements, profile.pending_party_total = {"bedding": "double"}, 3
    result = _run(inline_tools.compare_hotels("Compare these hotels", profile))
    assert [h["offer_id"] for h in result["hotels"]] == ["offer-1", "offer-2"]


def test_a_total_that_empties_the_page_does_not_hide_it():
    # 2026-11-02 replay (« a family of 4 » at Sabiha): the total is never asked,
    # so it may not empty a page — the page is served without it.
    offers = [{"ratePlanUuid": "double", "price": 5000, "capacity": 2, "childrenCapacity": 0}]
    payload = {"results": [{"hotelId": 42, "name": "Example", "offers": offers}]}
    assert normalize_search_results(payload, party_total=4)[0]["offer_id"] == "double"
    roomy = [*offers, {"ratePlanUuid": "family", "price": 9000, "capacity": 2, "childrenCapacity": 2}]
    payload = {"results": [{"hotelId": 42, "name": "Example", "offers": roomy}]}
    assert normalize_search_results(payload, party_total=4)[0]["offer_id"] == "family"
