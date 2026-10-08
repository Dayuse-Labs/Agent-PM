"""Real concierge turns: a provider place choice survives budget/time refinements."""
import asyncio
import json

import pytest
from b2c_common.confirmed_location import context_for_triage, location_intent, pending_location, verified_place

import b2c_concierge.agent as agent_module
from b2c_concierge.profile import SessionProfile, apply_profile_delta, leaf_profile_view

from .test_spine import _answer, _drive_in, _new_session, scripted  # noqa: F401

VALENCE = {"provider_id": "mapbox:valence-26", "name": "Valence", "label": "Valence, Drôme, France",
           "country_code": "FR", "region": "26", "feature_type": "place", "latitude": 44.93, "longitude": 4.89}
SPAIN = {**VALENCE, "provider_id": "mapbox:valencia-es", "label": "Valence, Espagne", "country_code": "ES", "region": "V", "latitude": 39.47, "longitude": -0.38}
PENDING = {"question": "Valence dans la Drôme ou en Espagne ?", "options": [VALENCE, SPAIN]}


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


def test_yes_cannot_choose_homonym_and_date_answer_is_preserved(scripted, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(pending_location=PENDING)))
    llm, leaves = scripted('{"family":"ack","language":"fr","location_intent":{"action":"preserve","evidence":"Yes"}}')
    assert _answer(_drive_in(runner, session.id, "Yes")) == PENDING["question"]
    assert len(llm.calls) == 1 and leaves == []
    scripted('{"family":"search","language":"fr","location_intent":{"action":"preserve","evidence":"Le 12 novembre 2026"}}')
    assert _answer(_drive_in(runner, session.id, "Le 12 novembre 2026")) == PENDING["question"]
    p = asyncio.run(fake_profile_store.get(session.id))
    assert p.date == "2026-11-12" and p.pending_location == PENDING


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
