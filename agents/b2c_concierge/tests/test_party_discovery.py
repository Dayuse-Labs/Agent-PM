"""Unknown composition permits discovery, never invented counts or booking.

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
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City")))
    fake_leg.response_payload = {"results": [{"hotel_id": 42, "name": "Example", "capacity": 3}],
                                 "profile_delta": {"adults": 2, "children": 0}}
    llm = _scripted_llm(monkeypatch, json.dumps({"family": "search", "language": "en",
        "requested_occupancy": {"total": 3, "counts": "people", "evidence": "for three"}}))
    text = _run_turn(runner, session.id, "for three")
    outgoing = find_datapart(fake_leg.seen_outgoing_parts)
    assert outgoing["query_params"]["party_total"] == 3
    assert "adults" not in outgoing["profile_in"] and "children" not in outgoing["profile_in"]
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.pending_party_total == 3 and saved.adults is None and saved.children is None
    assert fake_leg.call_count == 1 and len(llm.calls) == 1
    assert "options" in text and "confirmation" in text and "adults and children" in text


def test_two_people_get_the_normal_answer_with_their_capacity_filter(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    # Prod audit 2026-11-02: « Suitability for your group of 2 still needs
    # confirmation: how many adults and children? » in 12 replies. Two people
    # fit any offer the capacity filter keeps, whatever their split.
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City")))
    fake_leg.response_payload = {"results": [{"hotel_id": 42, "name": "Example", "capacity": 2}]}
    llm = _scripted_llm(monkeypatch, json.dumps({"family": "search", "language": "en",
        "requested_occupancy": {"total": 2, "counts": "people", "evidence": "for two"}}), "Here is Example.")
    text = _run_turn(runner, session.id, "for two")
    assert find_datapart(fake_leg.seen_outgoing_parts)["query_params"]["party_total"] == 2
    assert asyncio.run(fake_profile_store.get(session.id)).pending_party_total == 2
    assert len(llm.calls) == 2 and "Here is Example." in text
    assert "adults and children" not in text and "confirmation" not in text


def test_an_empty_page_is_not_answered_by_the_composition_question(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    # Prod audit 2026-11-02: 10 of 10 such questions, over 0 cards, came from
    # misread numbers (« 30km », « From 4pm »…). The leaf now serves the page
    # without the capacity filter when that filter alone emptied it; an empty
    # page left means MCP itself found nothing.
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City")))
    fake_leg.response_payload = {"results": []}
    _scripted_llm(monkeypatch, json.dumps({"family": "search", "language": "en",
        "requested_occupancy": {"total": 4, "counts": "people", "evidence": "four of us"}}), "No offers there.")
    text = _run_turn(runner, session.id, "four of us")
    assert "how many are adults" not in text and "adults and children" not in text


def test_the_search_a_total_emptied_is_cited_with_that_total():
    from b2c_concierge.relaxation_notice import relaxation_line

    relaxation = {"steps": ["party"], "searched_date": "2026-11-03", "party": {"total": 3, "max_capacity": 2}}
    line = relaxation_line(relaxation, {"city": "Paris", "date": "2026-11-03"}, "fr")
    assert line.startswith("Aucune offre à Paris le mardi 3 novembre 2026, pour 3 personnes.")
    assert "adultes" not in line and "le nombre de personnes" in line


def test_a_total_no_room_sleeps_ends_on_the_closed_question_and_is_dropped(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City", pending_party_total=4)))
    fake_leg.response_payload = {"results": [{"hotel_id": 42, "name": "Example", "capacity": 2}],
                                 "relaxation": {"steps": ["party"], "searched_date": "2026-11-03",
                                                "party": {"total": 4, "max_capacity": 2}}}
    _scripted_llm(monkeypatch, json.dumps({"family": "search", "language": "en"}), "Here is Example.")
    text = _run_turn(runner, session.id, "a hotel tomorrow")
    assert text.endswith("Just to check: are you really 4 people?")
    assert "adults and children" not in text
    assert asyncio.run(fake_profile_store.get(session.id)).pending_party_total is None


def test_the_composition_answer_resolves_the_pending_total(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City", pending_party_total=3)))
    fake_leg.response_payload = {"results": [{"hotel_id": 42, "name": "Example"}]}
    _scripted_llm(monkeypatch, json.dumps({"family": "search", "language": "en",
        "requested_occupancy": {"children": 1, "counts": "people", "evidence": "one child"}}), "Here is Example.")
    _run_turn(runner, session.id, "one child")
    outgoing = find_datapart(fake_leg.seen_outgoing_parts)
    assert outgoing["query_params"]["occupancy_update"] == {"children": 1, "adults": 2}
    assert "party_total" not in outgoing["query_params"]
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert (saved.adults, saved.children, saved.pending_party_total) == (2, 1, None)


@pytest.mark.parametrize("total,words", [(3, "three"), (2, "two")])
def test_a_total_on_a_booking_turn_asks_the_composition_before_any_link(
    monkeypatch, fake_leg, fake_profile_store, total, words  # noqa: F811
):
    # Two people get no question at search time, but a booking link still
    # needs their split (R9).
    def forbidden():
        raise AssertionError("Booking must not reach MCP before composition")
    monkeypatch.setattr(inline_tools, "_mcp_session", forbidden)
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Example City", last_results=[
        {"hotel_id": 42, "name": "Example", "offer_id": "o", "offer_date": "2026-11-01"}])))
    _scripted_llm(monkeypatch, json.dumps({"family": "booking", "language": "en", "hotel_name": "Example",
        "requested_occupancy": {"total": total, "counts": "people", "evidence": f"for {words}"}}))
    text = _run_turn(runner, session.id, f"Book Example for {words}")
    assert text == f"Of these {total} guests, how many are adults and how many are children?"
    assert asyncio.run(fake_profile_store.get(session.id)).pending_party_total == total


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
        "requested_occupancy": {"adults": 2, "children": 1, "counts": "people", "evidence": "2 adults and 1 child"}}))
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
