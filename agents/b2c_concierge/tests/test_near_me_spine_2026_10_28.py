"""2026-10-28: « près de moi » through the spine — the device position the
facade stored (`search_anchor`, type gps) is what the leaf searches around,
and it stays the origin of the follow-ups (agent-usa: « keep the near-me GPS
origin across refinement turns »)."""
from __future__ import annotations

import asyncio

from google.adk.runners import InMemoryRunner

from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import SessionProfile, has_search_destination

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

_GPS = {"type": "gps", "lat": 41.3917, "lon": 2.1649, "label": None, "set_at_turn": 0}
_CLEARS = {slot: {"op": "clear"} for slot in ("city", "zone", "metro", "state_anchor", "city_is_area")}


def test_a_near_me_search_drops_the_earlier_city_and_keeps_the_position(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    _scripted_llm(
        monkeypatch,
        '{"family": "search", "language": "es"}', "Cerca de ti.",
        '{"family": "search", "language": "es"}', "Con piscina, cerca de ti.",
    )
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Madrid", search_anchor=_GPS)))

    fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": dict(_CLEARS)}
    _run_turn(runner, session.id, "Habitación de día cerca de mí")
    stored = asyncio.run(fake_profile_store.get(session.id))
    assert stored.city is None
    assert stored.search_anchor == _GPS
    assert has_search_destination(stored)

    fake_leg.response_payload = {"results": ["hotel B"], "profile_delta": {}}
    _run_turn(runner, session.id, "con piscina")
    profile_in = find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]
    assert profile_in["search_anchor"]["lat"] == _GPS["lat"]
    assert not profile_in.get("city")


def test_a_device_position_is_a_destination_a_bare_profile_is_not():
    assert has_search_destination(SessionProfile(search_anchor=_GPS))
    assert has_search_destination(SessionProfile(city="Lyon"))
    assert not has_search_destination(SessionProfile())
    assert not has_search_destination(SessionProfile(search_anchor={"type": "gps"}))


def test_the_synthesis_is_told_the_cards_are_around_the_user():
    from b2c_concierge.ground_truth import shortlist_ground_truth_block

    response = {"results": [{"hotel_id": 1, "name": "Hôtel A", "distance_km": 0.6}]}
    near = SessionProfile(distance_origin={"latitude": 48.86, "longitude": 2.36, "type": "gps"})
    city = SessionProfile(distance_origin={"latitude": 48.86, "longitude": 2.36, "type": "city_centroid"})
    assert "never ask for their position" in shortlist_ground_truth_block(response, near)
    assert "never ask for their position" not in shortlist_ground_truth_block(response, city)
