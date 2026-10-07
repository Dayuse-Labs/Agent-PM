"""End-to-end profile plumbing tests over the REAL `_run_leaf` — only the A2A
leg itself is faked (no network, no httpx). Unlike test_spine.py's `scripted`
fixture (which replaces `_run_leaf` wholesale), this exercises the actual S5
wiring: the outgoing `{query_params, profile_in}` DataPart, the incoming
`profile_delta` decode, the budget-integrity / auto-widen guards, and Redis
(fakeredis) persistence across turns of the SAME session.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

import b2c_concierge.agent as agent_module
from b2c_concierge.a2a_datapart import encode_datapart, find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import (
    BUDGET_SOURCE_EXPLICIT,
    SessionProfile,
)


def _llm_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class ScriptedLlm:
    def __init__(self, *plan):
        self.plan = list(plan)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self.plan.pop(0) if self.plan else "Unverified answer from scripted control."
        if isinstance(item, Exception):
            raise item
        return _llm_response(item)


class FakeLeg:
    """Stands in for the A2A leg: records the ctx it received (so the test
    can inspect the outgoing DataPart) and yields a scripted response that
    may itself carry a DataPart (the leaf's SearchResponse)."""

    def __init__(self):
        self.text = "results: hotel A"
        self.response_payload: dict | None = None
        # A snapshot of the outgoing parts, taken HERE: the ADK runner keeps
        # appending events to the session as the turn finishes, so reading
        # ctx.session.events[-1] after the turn would see the FINAL answer
        # event instead of the user turn we were sent.
        self.seen_outgoing_parts: list[genai_types.Part] = []
        self.call_count = 0  # S12: proves the search-exhaustion gate skips the leaf entirely

    async def run_async(self, ctx):
        self.call_count += 1
        self.seen_outgoing_parts = list(ctx.session.events[-1].content.parts or [])
        parts = [genai_types.Part(text=self.text)]
        if self.response_payload is not None:
            parts.append(encode_datapart(self.response_payload))
        yield Event(
            author="hotel_search_leg",
            invocation_id=ctx.invocation_id,
            content=genai_types.Content(role="model", parts=parts),
        )


@pytest.fixture
def fake_leg(monkeypatch):
    leg = FakeLeg()
    monkeypatch.setattr(agent_module, "_get_leg", lambda leaf: leg)
    return leg


def _scripted_llm(monkeypatch, *plan) -> ScriptedLlm:
    llm = ScriptedLlm(*plan)
    monkeypatch.setattr(agent_module.litellm, "acompletion", llm)
    return llm


def _new_session(runner):
    async def go():
        return await runner.session_service.create_session(app_name=runner.app_name, user_id="u")

    return asyncio.run(go())


def _run_turn(runner, session_id, message):
    async def go():
        content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
        return [
            event async for event in runner.run_async(user_id="u", session_id=session_id, new_message=content)
        ]

    events = asyncio.run(go())
    # S06: progress/hotels markers and streamed synthesis chunks are all
    # `partial=True` (never appended to the session — see agent.py's
    # `_marker_event`); the answer is the ONE terminal non-partial event.
    texts = [
        part.text
        for event in events
        if not event.partial and event.content and event.content.parts
        for part in event.content.parts
        if part.text
    ]
    return "\n".join(texts).strip()


def test_recognized_bare_budget_reaches_actual_search_arguments(monkeypatch, fake_leg, fake_profile_store):
    """Observed prod comparison: triage knew 60 but MCP received no cap."""
    from hotel_search_agent.budget_injection import inject_profile_budget

    fake_leg.response_payload = {"results": [], "profile_delta": {}}
    llm = _scripted_llm(
        monkeypatch,
        '{"family":"search","language":"en","bare_budget_value":60}',
        "No matching offers under your budget.",
    )
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Orange County", budget_max=150)))
    _run_turn(runner, session.id, "60")

    payload = find_datapart(fake_leg.seen_outgoing_parts)
    assert payload["profile_in"]["budget_max"] == 60
    assert payload["profile_in"]["budget_request_source"] == BUDGET_SOURCE_EXPLICIT
    # Exercise the real leaf callback, not just a profile or UI assertion.
    context = SimpleNamespace(user_content=genai_types.Content(parts=fake_leg.seen_outgoing_parts))
    args = {"lat": 33.78, "lon": -117.85}
    inject_profile_budget(SimpleNamespace(name="search_offers"), args, context)
    assert args["priceRangeMax"] == 60
    assert asyncio.run(fake_profile_store.get(session.id)).budget_max == 60
    assert len(llm.calls) == 2


def test_bare_shortlist_position_does_not_become_a_budget(monkeypatch, fake_leg, fake_profile_store):
    observed = {}

    async def booking(self, ctx, profile, *args, **kwargs):
        observed["budget"] = profile.budget_max
        yield self._final(ctx, "Please confirm this offer.")

    monkeypatch.setattr(type(root_agent), "_run_booking", booking)
    _scripted_llm(monkeypatch, '{"family":"search","language":"en","bare_budget_value":2}')
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    seeded = SessionProfile(
        city="Paris",
        budget_max=150,
        last_results=[
            {"hotel_id": 1, "name": "First Hotel"},
            {"hotel_id": 2, "name": "Second Hotel"},
        ],
    )
    asyncio.run(fake_profile_store.set(session.id, seeded))
    _run_turn(runner, session.id, "2")
    assert observed["budget"] == 150
    assert fake_leg.call_count == 0


def test_search_request_survives_leaf_timeout_and_reaches_next_turn(monkeypatch, fake_profile_store):
    import json

    seen = []

    async def unavailable(leaf, ctx, profile_in, **kwargs):
        seen.append((profile_in, kwargs))
        return None, {}

    monkeypatch.setattr(agent_module, "_run_leaf", unavailable)
    llm = _scripted_llm(
        monkeypatch,
        json.dumps(
            {
                "family": "search",
                "language": "en",
                "location_evidence": "Milford ct",
                "location_update": {
                    "action": "replace",
                    "city": "Milford",
                    "region": "Connecticut",
                    "country_code": "US",
                },
            }
        ),
        json.dumps(
            {
                "family": "search",
                "language": "en",
                "bare_budget_value": 110,
                "location_update": {"action": "retain"},
            }
        ),
    )
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    _run_turn(runner, session.id, "Milford ct")
    _run_turn(runner, session.id, "110")
    assert len(llm.calls) == 2  # triage only; no retry or synthesis on timeout
    assert seen[1][0]["city"] == "Milford"
    assert seen[1][0]["state_anchor"] == "Connecticut"
    assert seen[1][0]["budget_max"] == 110
    assert seen[1][1]["query_params"]["recent_user_messages"] == ["Milford ct"]
    stored = asyncio.run(fake_profile_store.get(session.id))
    assert stored.city is None and stored.search_location_request["city"] == "Milford"


def test_contextual_decline_keeps_filters_without_search_or_welcome(
    monkeypatch, fake_leg, fake_profile_store
):
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(
        fake_profile_store.set(
            session.id,
            SessionProfile(
                city="Paris",
                language="en",
                budget_max=60,
                last_clarifying_question="Would you like to increase your budget?",
            ),
        )
    )
    llm = _scripted_llm(
        monkeypatch,
        '{"family":"ack","language":"en","affirmative":false}',
        "Understood, I’ll keep your current criteria.",
    )
    answer = _run_turn(runner, session.id, "No")
    assert fake_leg.call_count == 0
    assert len(llm.calls) == 2
    assert "Previous assistant question" in llm.calls[-1]["messages"][1]["content"]
    assert "current criteria" in answer
    assert asyncio.run(fake_profile_store.get(session.id)).budget_max == 60


def test_geo_rejection_cannot_be_synthesized_into_no_inventory(monkeypatch, fake_leg, fake_profile_store):
    fake_leg.response_payload = {"requires_clarification": True}
    fake_leg.text = "Could you provide the exact address?"
    llm = _scripted_llm(monkeypatch, '{"family":"search","language":"en"}')
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    answer = _run_turn(runner, session.id, "An ambiguous district")
    assert answer == fake_leg.text
    assert len(llm.calls) == 1
    assert asyncio.run(fake_profile_store.get(session.id)).last_clarifying_question


def test_hotel_identity_cannot_claim_a_verified_offer(monkeypatch, fake_leg, fake_profile_store):
    fake_leg.response_payload = {"identity_only": True, "results": [{"hotel_id": 7, "name": "Known Hotel"}]}
    fake_leg.text = "I found an available offer!"
    llm = _scripted_llm(monkeypatch, '{"family":"search","language":"en"}')
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    answer = _run_turn(runner, session.id, "Known Hotel")
    assert "not been verified" in answer
    assert len(llm.calls) == 1


def test_contextual_decline_without_extracted_question_does_not_restart(
    monkeypatch, fake_leg, fake_profile_store
):
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(
        fake_profile_store.set(
            session.id,
            SessionProfile(
                city="Paris",
                language="en",
                budget_max=60,
            ),
        )
    )
    _scripted_llm(
        monkeypatch,
        '{"family":"ack","language":"en","affirmative":false}',
        "Understood, I’ll keep your current criteria.",
    )
    answer = _run_turn(runner, session.id, "No")
    assert fake_leg.call_count == 0
    assert "current criteria" in answer


def test_first_cheapest_search_without_shortlist_still_reaches_search(
    monkeypatch, fake_leg, fake_profile_store
):
    fake_leg.response_payload = {"requires_clarification": True}
    fake_leg.text = "Which city should I search?"
    _scripted_llm(monkeypatch, '{"family":"search","language":"en","pick":"cheapest"}')
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    answer = _run_turn(runner, session.id, "Cheapest hotels near me")
    assert fake_leg.call_count == 1
    assert answer


def test_travel_time_never_comes_from_an_unverified_faq_or_distance(
    monkeypatch, fake_leg, fake_profile_store
):
    llm = _scripted_llm(monkeypatch, '{"family":"faq","language":"en","travel_measure":"duration"}')
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    answer = _run_turn(runner, session.id, "How long does it take to get from the station to the hotel?")
    assert fake_leg.call_count == 0
    assert len(llm.calls) == 1
    assert "can’t verify travel time" in answer


def test_walking_distance_request_is_not_a_travel_duration_block(monkeypatch, fake_leg, fake_profile_store):
    fake_leg.response_payload = {"requires_clarification": True}
    fake_leg.text = "Which park do you mean?"
    _scripted_llm(monkeypatch, '{"family":"search","language":"en","travel_measure":"distance"}')
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    answer = _run_turn(runner, session.id, "A hotel within walking distance of the park")
    assert fake_leg.call_count == 1
    assert answer


def test_support_followup_context_reaches_triage_faq_and_final_answer_but_not_another_session(
    monkeypatch, fake_leg, fake_profile_store
):
    fake_leg.text = "Check the confirmation email for your booking."
    fake_leg.response_payload = {}
    llm = _scripted_llm(
        monkeypatch,
        '{"family":"faq","language":"en"}',
        "Check your confirmation email.",
        '{"family":"faq","language":"en"}',
        "Guest bookings are in the confirmation email.",
        '{"family":"faq","language":"en"}',
        "Check your confirmation email.",
    )
    runner = InMemoryRunner(root_agent)
    first = _new_session(runner)
    _run_turn(runner, first.id, "Where can I find my reservation?")
    _run_turn(runner, first.id, "I booked as a guest")
    assert "Where can I find my reservation?" in llm.calls[2]["messages"][1]["content"]
    envelope = find_datapart(fake_leg.seen_outgoing_parts)
    assert envelope["query_params"]["recent_user_messages"] == ["Where can I find my reservation?"]
    synthesis = llm.calls[3]["messages"][1]["content"]
    assert "RECENT USER MESSAGES" in synthesis
    assert "Where can I find my reservation?" in synthesis
    assert "I booked as a guest" in synthesis
    assert "Check your confirmation email." not in synthesis
    second = _new_session(runner)
    _run_turn(runner, second.id, "Where is my reservation?")
    assert "RECENT USER MESSAGES" not in llm.calls[4]["messages"][1]["content"]
    assert "RECENT USER MESSAGES" not in llm.calls[5]["messages"][1]["content"]


def test_overnight_never_fetches_day_offers(monkeypatch, fake_leg, fake_profile_store):
    _scripted_llm(monkeypatch, '{"family":"search","language":"en","stay_kind":"overnight"}')
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    answer = _run_turn(runner, session.id, "Overnight use")
    assert fake_leg.call_count == 0
    assert "overnight" in str(answer)
    stored = asyncio.run(fake_profile_store.get(session.id))
    assert stored.stay_kind == "overnight"
    assert stored.last_clarifying_question


def test_unresolved_position_never_calls_any_tool(monkeypatch, fake_leg, fake_profile_store):
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    _scripted_llm(
        monkeypatch,
        '{"family":"booking","language":"en","pick":"position","pick_position":1,"hotel_name":"Invented Hotel"}',
    )

    async def forbidden(*args, **kwargs):
        pytest.fail("An unresolved ordinal must never call a catalogue or booking tool")

    monkeypatch.setattr(agent_module.inline_tools, "generate_booking_link", forbidden)
    _run_turn(runner, session.id, "the first one")
    assert fake_leg.call_count == 0


def test_bare_budget_preserves_established_language(monkeypatch, fake_leg, fake_profile_store):
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    asyncio.run(
        fake_profile_store.set(session.id, SessionProfile(city="London", language="en", locale="fr-FR"))
    )
    llm = _scripted_llm(
        monkeypatch,
        '{"family":"search","language":"fr","bare_budget_value":60}',
        "No offers within that budget.",
    )
    _run_turn(runner, session.id, "60")
    assert "LANG: en" in llm.calls[-1]["messages"][1]["content"]
    assert asyncio.run(fake_profile_store.get(session.id)).language == "en"
