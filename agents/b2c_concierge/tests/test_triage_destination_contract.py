"""Recorded failure shapes at the semantic decision / session-state boundary."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from b2c_common.confirmed_location import context_for_triage, location_intent
from b2c_concierge.budget import TurnBudget
from b2c_concierge.triage import classify
from b2c_concierge.triage_schema import TRIAGE_RESPONSE_FORMAT
import b2c_concierge.agent as agent_module
from b2c_concierge.profile import SessionProfile

from .test_spine import _answer, _drive_in, _new_session, scripted  # noqa: F401


@pytest.mark.parametrize('message,target', [
    ('Budapest', {'kind': 'city', 'query': 'Budapest', 'scope': 'nearby'}),
    ('Near San Bruno', {'kind': 'city', 'query': 'San Bruno', 'country': 'US',
                       'evidence': 'San Bruno', 'scope': 'nearby', 'region': 'California'}),
    ('Red deer', {'kind': 'city', 'query': 'Red Deer', 'country': 'CA',
                  'evidence': 'Red deer', 'scope': 'nearby', 'region': 'Alberta'}),
])
def test_recorded_city_extraction_reaches_leaf_and_persists_without_inferred_region(
    scripted, monkeypatch, fake_profile_store, message, target,  # noqa: F811
):
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(date='2030-11-01')))
    seen = []

    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return 'No offers', {'results': []}

    scripted(json.dumps({'family': 'search', 'language': 'en', 'location_update': {
        'action': 'change', 'evidence': message, 'targets': [target]}}), 'No offers')
    monkeypatch.setattr(agent_module, '_run_leaf', leaf)
    _drive_in(runner, session.id, message)
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert len(seen) == 1
    assert seen[0]['city'] == target['query']
    assert seen[0]['search_areas'] is None  # Nearby cities do not create strict boundaries.
    assert seen[0]['state_anchor'] is None
    assert profile.requested_destination['areas'][0]['query'] == target['query']
    assert 'region' not in profile.requested_destination['areas'][0]
    assert profile.confirmed_location is None  # A quoted name is not provider geometry.


def _decision(action, kind, evidence, parent_city=None):
    return {"action": action, "kind": kind, "evidence": evidence,
            "parent_city": parent_city, "position": None}


def test_sparse_contract_uses_the_existing_single_call(monkeypatch):
    seen = []
    async def llm(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            "family": "search", "language": "fr",
            "location_intent": _decision("device", "device", "près de moi"),
        })))])
    monkeypatch.setattr("b2c_concierge.triage.litellm.acompletion", llm)
    budget = TurnBudget()
    result = asyncio.run(classify("près de moi", budget))
    assert budget.llm_calls == len(seen) == 1
    fmt = seen[0]["response_format"]
    assert fmt == TRIAGE_RESPONSE_FORMAT == {"type": "json_object"}
    assert result.location_intent == {"action": "device", "kind": "device"}


def test_parent_quote_may_be_separate_from_operation_quote_but_not_from_current_message():
    value = _decision("refine", "landmark", "near airport", "Philadelphia")
    assert location_intent(value, "Philadelphia near airport", {})["parent_city"] == "Philadelphia"
    assert "parent_city" not in location_intent(value, "near airport", {"confirmed_city": "Philadelphia"})


@pytest.mark.parametrize("action,kind", [("device", "landmark"), ("preserve", "city"), ("missing", "hotel")])
def test_descriptive_kind_cannot_override_the_primary_operation(action, kind):
    intent = location_intent(_decision(action, kind, "x"), "x", {})
    assert intent == {"action": action, "kind": "device" if action == "device" else "none"}


def test_unresolved_correction_and_parent_are_persisted_across_real_concierge_turns(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(date="2026-11-01")))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return "Please clarify", {"results": [], "profile_delta": {"city": "Paris"}}
    turns = [
        ("près de la defndebpour", _decision("change", "landmark", "la defndebpour"),
         {"query": "la defndebpour", "evidence": "la defndebpour"}, None),
        ("Il s’agit de courbevoie", _decision("refine", "city", "Il s’agit", "courbevoie"), None,
         [{"query": "Courbevoie", "country": "FR", "kind": "municipality", "evidence": "courbevoie"}]),
        ("la defense pas aux usa", _decision("correct", "landmark", "la defense"),
         {"query": "la defense", "evidence": "la defense"}, None),
    ]
    for text, decision, landmark, areas in turns:
        scripted(json.dumps({"family": "search", "language": "fr", "location_intent": decision,
                             "requested_landmark": landmark, "requested_areas": areas}), "Please clarify")
        monkeypatch.setattr(agent_module, "_run_leaf", leaf)
        _drive_in(runner, session.id, text)
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.requested_destination == {"kind": "landmark", "query": "la defense", "city": "courbevoie"}
    assert seen[1]["zone"] == "la defndebpour" and seen[2]["city"] == "courbevoie"
    assert profile.confirmed_location is None


def test_device_decision_cannot_be_overridden_by_a_spurious_landmark(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city="Paris", date="2026-11-01", requested_destination={"kind": "landmark", "query": "Gare de Lyon", "city": "Paris"},
        search_anchor={"type": "gps", "lat": 48.8, "lon": 2.3})))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs["query_params"]))
        return "Searching", {"results": [], "profile_delta": {"zone": "Brasserie Des Prés"}}
    scripted(json.dumps({"family": "search", "language": "fr",
                         "location_intent": _decision("device", "device", "près de moi"),
                         "requested_landmark": {"query": "près de moi", "evidence": "près de moi"}}), "Searching")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "Chambre en journée près de moi")
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.requested_destination == {"kind": "device"}
    assert profile.zone is None and profile.city is None
    assert seen[0][1]["device_authoritative"] is True
    assert not seen[0][1].get("landmark_authoritative")


@pytest.mark.parametrize("repeat_parent_in_areas", [True, False])
def test_parent_of_a_group_does_not_replace_members_after_partial_results(scripted, monkeypatch, fake_profile_store, repeat_parent_in_areas):  # noqa: F811
    runner, session = _new_session()
    areas = [{"query": name, "kind": "municipality", "country": "BR", "evidence": name}
             for name in ("Barra da Tijuca", "Recreio dos Bandeirantes")]
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city="Barra da Tijuca", date="2026-11-01", search_areas=areas,
        requested_destination={"kind": "areas", "areas": areas},
        last_results=[{"hotel_id": 1, "name": "Previously shown"}])))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return "Searching", {"results": []}
    scripted(json.dumps({"family": "search", "language": "pt",
                         "location_intent": _decision("refine", "city", "Rio de Janeiro", "Rio de Janeiro"),
                         "requested_areas": [{"query": "Rio de Janeiro", "kind": "municipality", "country": "BR", "evidence": "Rio de Janeiro"}] if repeat_parent_in_areas else None}), "Searching")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "Rio de Janeiro")
    assert [a["subarea"] for a in seen[0]["search_areas"]] == [a["query"] for a in areas]
    assert all(a["query"] == "Rio de Janeiro" for a in seen[0]["search_areas"])


def test_device_availability_is_kept_alongside_pending_candidates():
    # An invalid pending payload is not promoted, but native-context existence
    # remains available even when a request has already been persisted.
    c = context_for_triage(None, None, requested={"kind": "device"}, device_available=True)
    assert c["device_available"] is True


def test_named_hotel_survives_parent_reply_and_new_city_releases_it(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(date="2026-11-01")))
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs["query_params"]))
        return "Checked", {"results": []}
    turns = [
        ("Rambler oasis hotel", {"location_intent": _decision("change", "hotel", "Rambler oasis hotel"),
                                 "hotel_name": "Rambler oasis hotel"}),
        ("Hongkong", {"location_intent": _decision("refine", "city", "Hongkong", "Hongkong"),
                     "requested_areas": [{"query": "Hongkong", "kind": "municipality", "country": "HK", "evidence": "Hongkong"}]}),
        ("Singapore instead", {"location_intent": _decision("change", "city", "Singapore instead"),
                               "requested_areas": [{"query": "Singapore", "kind": "municipality", "country": "SG", "evidence": "Singapore"}]}),
    ]
    for message, data in turns:
        scripted(json.dumps({"family": "search", "language": "en", **data}), "Checked")
        monkeypatch.setattr(agent_module, "_run_leaf", leaf)
        _drive_in(runner, session.id, message)
    assert seen[0][0]["requested_destination"] == {"kind": "hotel", "query": "Rambler oasis hotel"}
    assert seen[1][0]["requested_destination"] == {"kind": "hotel", "query": "Rambler oasis hotel", "city": "Hongkong"}
    assert seen[1][0]["search_areas"] is None and seen[1][1]["destination_authoritative"]
    assert seen[2][0]["requested_destination"]["kind"] == "areas"
    assert seen[2][0]["city"] == "Singapore"


def test_invalid_geographic_proof_asks_without_searching_but_keeps_other_constraints(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city="Paris", date="2026-11-01", requested_destination={"kind": "landmark", "query": "Gare de Lyon", "city": "Paris"})))
    async def forbidden(*args, **kwargs):
        raise AssertionError("An ungrounded geographic update cannot authorize a new search")
    scripted(json.dumps({"family": "search", "language": "en",
                         "location_intent": _decision("change", "city", "Paris"),
                         "requested_areas": [{"query": "London", "kind": "municipality", "country": "GB", "evidence": "London"}],
                         "requested_budget": {"amount": 80, "currency": "EUR", "unit": "total", "evidence": "80 EUR"}}))
    monkeypatch.setattr(agent_module, "_run_leaf", forbidden)
    _drive_in(runner, session.id, "London, under 80 EUR")
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.city == "Paris" and profile.requested_destination["query"] == "Gare de Lyon"
    assert profile.requested_budget["amount"] == 80
    assert "Which place" in profile.last_clarifying_question


@pytest.mark.parametrize("copied_evidence", ["Paris", "", None])
@pytest.mark.parametrize("with_kind", [True, False])
def test_geographic_noop_does_not_block_budget_or_rewrite_destination(
    scripted, monkeypatch, fake_profile_store, copied_evidence, with_kind,  # noqa: F811
):
    runner, session = _new_session()
    destination = {"kind": "landmark", "query": "Gare de Lyon", "city": "Paris"}
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city="Paris", zone="Gare de Lyon", date="2030-11-01",
        timeslot_start="10:00", timeslot_end="16:00",
        requested_destination=destination,
    )))
    seen = []

    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return "No offers", {"results": []}

    scripted(json.dumps({
        "family": "search", "language": "en",
        "location_intent": (_decision("preserve", "city", copied_evidence) if with_kind
                            else {"action": "preserve", "evidence": copied_evidence}),
        "requested_areas": [{"query": "London", "kind": "municipality", "country": "GB", "evidence": "London"}],
        "requested_budget": {"amount": 80, "currency": "EUR", "unit": "total", "evidence": "80 EUR"},
    }), "No offers")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, "under 80 EUR")
    assert len(seen) == 1
    assert seen[0]["requested_destination"] == destination
    assert seen[0]["requested_budget"] == {"amount": 80.0, "currency": "EUR", "unit": "total"}
    assert (seen[0]["timeslot_start"], seen[0]["timeslot_end"]) == ("10:00", "16:00")
    assert seen[0]["search_areas"] is None


@pytest.mark.parametrize("action", ["change", "correct", "refine", "device", "select"])
def test_mutating_geographic_operations_still_require_current_evidence(action):
    value = _decision(action, "city", "old place", "London")
    assert location_intent(value, "under 80 EUR", {}) is None


def test_current_airport_extraction_is_not_discarded_by_redundant_kind(monkeypatch):
    async def llm(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            "family": "search", "language": "en",
            "location_intent": _decision("refine", "area", "near airport", "Philadelphia"),
            "requested_landmark": {"query": "airport", "city": "Philadelphia", "evidence": "near airport"},
        })))])
    monkeypatch.setattr("b2c_concierge.triage.litellm.acompletion", llm)
    result = asyncio.run(classify("Philadelphia near airport", TurnBudget()))
    assert result.requested_landmark["query"] == "airport"
    assert result.location_intent["parent_city"] == "Philadelphia"


def test_actual_minutes_are_disclosed_even_when_hour_rule_accepts_the_card():
    from b2c_concierge.window_guard import enforce_window_match, literal_window_notice
    cards = [
        {"name": "Partial hotel", "timeslots": [{"start": "10:30", "end": "17:00"}]},
        {"name": "Covering hotel", "timeslots": [{"start": "09:00", "end": "18:00"}]},
    ]
    assert enforce_window_match(cards, "10:00", "17:00") == (cards, 0)
    notice = literal_window_notice(cards, "10:00", "17:00", "fr")
    assert "Partial hotel" in notice and "10:30–17:00" in notice
    assert "Covering hotel" not in notice
    assert literal_window_notice(cards[1:], "10:00", "17:00", "en") is None
    assert literal_window_notice(cards, None, None, "en") is None


def test_midnight_ending_offer_is_not_reported_as_a_partial_window():
    from b2c_concierge.window_guard import literal_window_notice
    cards = [{"name": "Late hotel", "timeslots": [{"start": "18:00", "end": "00:00"}]}]
    assert literal_window_notice(cards, "19:00", "24:00", "en") is None


def test_minute_disclosure_reaches_synthesis_and_final_answer(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city="Paris", date="2030-11-01", timeslot_start="10:00", timeslot_end="17:00",
        requested_window={"start": "10:00", "end": "17:00"})))
    async def leaf(*args, **kwargs):
        return "Found", {"results": [{"hotel_id": 10, "name": "Partial hotel", "price": 90,
                                      "timeslots": [{"start": "10:30", "end": "17:00"}]}]}
    llm, _ = scripted(json.dumps({"family": "search", "language": "en",
                                 "location_intent": _decision("preserve", "none", "Show options")}),
                      "Here is an option.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    answer = _answer(_drive_in(runner, session.id, "Show options"))
    assert "10:30–17:00" in answer and "Partial hotel" in answer
    assert "EXACT DISPLAYED HOURS:" in json.dumps(llm.calls[-1])
    assert len(llm.calls) == 2  # triage and synthesis; no extra LLM for disclosure
