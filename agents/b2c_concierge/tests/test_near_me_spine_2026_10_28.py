"""2026-10-28: « près de moi » through the spine — the device position the
facade stored (`search_anchor`, type gps) is what the leaf searches around,
and it stays the origin of the follow-ups (agent-usa: « keep the near-me GPS
origin across refinement turns »)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from google.adk.runners import InMemoryRunner

from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import SessionProfile, has_search_destination

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

from b2c_concierge.facade import _parse_gps_anchor

# The browser's fix at full precision, through the facade's intake: R3 (review
# of #173) rounds it once, there, to 3 decimals (~110 m).
_GPS = _parse_gps_anchor(
    {"client_geo_context": {"device": {"latitude": 41.391734, "longitude": 2.164912, "permission": "granted"}}}, 0
)
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
    assert (profile_in["search_anchor"]["lat"], profile_in["search_anchor"]["lon"]) == (41.392, 2.165)
    assert not profile_in.get("city")


def test_naming_a_place_after_near_me_forgets_the_position(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    """R3 (review of #173, GDPR): « près de moi » clears the city, so « à Lyon »
    set the first city and the position stayed for the whole session (profile,
    the leaf's profile_in, Mapbox `proximity`)."""
    from hotel_search_agent.geocode_tool import inject_profile_geo_context

    _scripted_llm(
        monkeypatch,
        '{"family": "search", "language": "fr"}', "Près de vous.",
        '{"family": "search", "language": "fr"}', "À Lyon.",
        '{"family": "search", "language": "fr"}', "Avec piscine, à Lyon.",
    )
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(search_anchor=_GPS)))

    fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": dict(_CLEARS)}
    _run_turn(runner, session.id, "Chambre en journée près de moi")
    fake_leg.response_payload = {"results": ["hotel B"], "profile_delta": {"city": "Lyon"}}
    _run_turn(runner, session.id, "à Lyon")

    assert asyncio.run(fake_profile_store.get(session.id)).search_anchor is None
    fake_leg.response_payload = {"results": ["hotel C"], "profile_delta": {}}
    _run_turn(runner, session.id, "avec piscine")
    profile_in = find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]
    assert profile_in.get("search_anchor") is None
    args: dict = {}
    inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, _ctx_with(profile_in))
    assert "proximity_lat" not in args and "proximity_lon" not in args


def _ctx_with(profile_in: dict) -> SimpleNamespace:
    from a2a import types as a2a_types
    from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
    from google.genai import types as genai_types

    part = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in}))
    content = genai_types.Content(role="user", parts=[genai_types.Part(text="x"), convert_a2a_part_to_genai_part(part)])
    return SimpleNamespace(state={}, user_content=content)


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
