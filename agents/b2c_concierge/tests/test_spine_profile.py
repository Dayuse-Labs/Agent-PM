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
from b2c_concierge.profile import BUDGET_SOURCE_EXPLICIT, BUDGET_SOURCE_FLEXIBLE_DEFAULT


def _llm_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class ScriptedLlm:
    def __init__(self, *plan):
        self.plan = list(plan)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self.plan.pop(0)
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
            event
            async for event in runner.run_async(
                user_id="u", session_id=session_id, new_message=content
            )
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


class TestOutgoingProfileEnvelope:
    def test_profile_in_travels_to_the_leaf_as_a_datapart(self, monkeypatch, fake_leg):
        fake_leg.response_payload = {"results": [], "profile_delta": {}}
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "synthesized reply")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "looking for a hotel")

        outgoing_parts = fake_leg.seen_outgoing_parts
        decoded = find_datapart(outgoing_parts)
        assert decoded is not None
        assert set(decoded) == {"query_params", "profile_in"}
        assert decoded["profile_in"]["budget_max"] is None
        assert decoded["profile_in"]["city"] is None


class TestProfileDeltaAppliedAndPersisted:
    def test_budget_delta_is_persisted_after_the_turn(self, monkeypatch, fake_leg, fake_profile_store):
        fake_leg.response_payload = {
            "results": ["hotel A"],
            "profile_delta": {"city": "Paris", "budget_max": 150, "budget_request_source": BUDGET_SOURCE_FLEXIBLE_DEFAULT},
        }
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Here is a hotel in Paris.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "a hotel in Paris please")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.city == "Paris"
        assert stored.budget_max == 150.0
        assert stored.budget_request_source == BUDGET_SOURCE_FLEXIBLE_DEFAULT

    def test_amenities_delta_is_persisted_and_surfaces_in_search_context(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        """S10: the leaf emits the amenity filters it hard-applied
        (equipment_ids/response_bridge) as `profile_delta.amenities`; the
        orchestrator must merge them (accumulating filter for next turns) AND
        show them in the SAME turn's SEARCH CONTEXT (transparency)."""
        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A", "amenities": ["pool"]}],
            "profile_delta": {"amenities": ["pool"]},
        }
        llm = _scripted_llm(
            monkeypatch, '{"family": "search", "language": "fr"}', "Voici un hôtel avec piscine."
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "un hotel à miami avec une piscine")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.amenities == ["pool"]
        # The delta is applied BEFORE synthesis (agent.py), so the search-context
        # line the model saw this turn already restates the amenity.
        assert "amenities: pool" in llm.calls[-1]["messages"][1]["content"]

    def test_bare_number_reply_overrides_the_leafs_own_source_claim(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        """The P1 safety net: even if the leaf's own extraction mislabels a
        plain-number reply as a system default, the orchestrator's guard
        forces `explicit` — the exact bug the 2026-06 audit found in prod."""
        fake_leg.response_payload = {
            "results": ["hotel A"],
            "profile_delta": {"budget_max": 180, "budget_request_source": BUDGET_SOURCE_FLEXIBLE_DEFAULT},
        }
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Got it.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "180")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.budget_request_source == BUDGET_SOURCE_EXPLICIT


class TestAutoWidenThroughTheSpine:
    def test_two_empty_searches_widen_a_non_explicit_budget(self, monkeypatch, fake_leg, fake_profile_store):
        fake_leg.response_payload = {
            "results": [],
            "profile_delta": {"budget_max": 100, "budget_request_source": BUDGET_SOURCE_FLEXIBLE_DEFAULT},
        }
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "No luck yet.",
            '{"family": "search", "language": "en"}', "Still nothing.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "a hotel under 100")
        fake_leg.response_payload = {"results": []}  # keep budget_max as already stored
        _run_turn(runner, session.id, "still looking")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.consecutive_empty_searches == 2
        assert stored.budget_max == 150.0
        # S06: the disclosure is surfaced by THIS SAME turn's synthesis (see
        # agent.py's _synthesize_with_guards) and cleared right after — it
        # must never persist to be silently re-surfaced (or re-suppressed)
        # on a later turn.
        assert stored.auto_widen_disclosure is None
        # The widening turn's own synthesis call must have SEEN the note —
        # otherwise the guard stays silent (the exact S05 handoff gap).
        synthesis_calls = [c for c in llm.calls if "AUTO_WIDEN" in c["messages"][1]["content"]]
        assert len(synthesis_calls) == 1
        assert "100.0 to 150.0" in synthesis_calls[0]["messages"][1]["content"]

    def test_explicit_budget_is_never_auto_widened(self, monkeypatch, fake_leg, fake_profile_store):
        fake_leg.response_payload = {"results": [], "profile_delta": {"budget_max": 100}}
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "No luck yet.",
            '{"family": "search", "language": "en"}', "Still nothing.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "100")  # bare number -> explicit
        fake_leg.response_payload = {"results": []}
        _run_turn(runner, session.id, "still looking")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.consecutive_empty_searches == 2
        assert stored.budget_max == 100.0
        assert stored.auto_widen_disclosure is None


class TestSearchExhaustionThroughTheSpine:
    """S12 audit 2026-07-20 (prod session 034c97c4, Rimini): 2 widens, then a
    3rd empty search that can't widen further sets `search_exhausted` — a
    later bare affirmative must be gated BEFORE the leaf, a substantive
    message must clear the flags and search again."""

    def test_repeated_empty_searches_reach_terminal_exhaustion_on_a_bare_ok(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "No luck yet.",       # turn 1: streak 1, no widen
            '{"family": "search", "language": "en"}', "Still nothing.",    # turn 2: streak 2, widen #1
            '{"family": "search", "language": "en"}', "Nothing here.",     # turn 3: streak 3, widen #2 (cap)
            '{"family": "search", "language": "en"}', "Still no offers.",  # turn 4: streak 4, can't widen -> exhausted
            '{"family": "ack", "language": "en"}',                          # turn 5: bare "ok" -> gated, NO synthesis
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        fake_leg.response_payload = {
            "results": [],
            "profile_delta": {"budget_max": 100, "budget_request_source": BUDGET_SOURCE_FLEXIBLE_DEFAULT},
        }
        _run_turn(runner, session.id, "a hotel under 100")
        fake_leg.response_payload = {"results": []}
        _run_turn(runner, session.id, "still looking")
        _run_turn(runner, session.id, "no luck")
        _run_turn(runner, session.id, "anything else")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.search_exhausted is True
        assert stored.widen_attempt_count == 2
        assert stored.budget_max == 225.0  # 100 -> 150 -> 225 (2 widens, then capped)

        calls_before = fake_leg.call_count
        llm_calls_before = len(llm.calls)
        reply = _run_turn(runner, session.id, "ok")

        assert fake_leg.call_count == calls_before  # the leaf was NEVER called this turn
        assert len(llm.calls) == llm_calls_before + 1  # triage only, zero synthesis call
        assert "widening the budget" in reply.lower() or "élargi" in reply.lower()

    def test_new_constraint_after_exhaustion_clears_flags_and_searches_again(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "No luck yet.",
            '{"family": "search", "language": "en"}', "Still nothing.",
            '{"family": "search", "language": "en"}', "Nothing here.",
            '{"family": "search", "language": "en"}', "Still no offers.",
            '{"family": "search", "language": "en"}', "A hotel in Lyon.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        fake_leg.response_payload = {
            "results": [],
            "profile_delta": {"budget_max": 100, "budget_request_source": BUDGET_SOURCE_FLEXIBLE_DEFAULT},
        }
        _run_turn(runner, session.id, "a hotel under 100")
        fake_leg.response_payload = {"results": []}
        _run_turn(runner, session.id, "still looking")
        _run_turn(runner, session.id, "no luck")
        _run_turn(runner, session.id, "anything else")

        calls_before = fake_leg.call_count
        fake_leg.response_payload = {"results": ["hotel B"], "profile_delta": {"city": "Lyon"}}
        _run_turn(runner, session.id, "Lyon instead")

        assert fake_leg.call_count == calls_before + 1  # the leaf WAS called this time
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.search_exhausted is False
        assert stored.widen_attempt_count == 0


class TestPaginationThroughTheSpine:
    """S-G5: "other options" advances `profile.search_cursor` (sent to the leaf
    as `profile_in.search_cursor`, read by the leaf's own `inject_pagination_offset`
    before_tool_callback to compute search_offers' `from`) — and a page that
    comes back with ZERO new hotels immediately extends the S12 exhaustion
    flag/template (never a parallel mechanism): zero extra LLM call, same
    turn, no streak to wait for."""

    def test_other_options_advances_the_cursor_sent_to_the_leaf(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "A hotel in Paris.",
            # Mis-triaged as ack on purpose — the code-owned routing override
            # (is_search_refinement_signal, now covering "other options") must
            # force this to search regardless of what triage guessed.
            '{"family": "ack", "language": "en"}', "More hotels in Paris.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A"}],
            "profile_delta": {"city": "Paris"},
        }
        _run_turn(runner, session.id, "a hotel in Paris")

        fake_leg.response_payload = {"results": [{"id": 2, "name": "Hotel B"}]}
        _run_turn(runner, session.id, "any other options?")

        outgoing = find_datapart(fake_leg.seen_outgoing_parts)
        assert outgoing["profile_in"]["search_cursor"] == 1

    def test_more_options_with_zero_new_results_is_immediately_exhausted(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "A hotel in Paris.",
            '{"family": "search", "language": "en"}', "unused — must not be consumed",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A"}],
            "profile_delta": {"city": "Paris"},
        }
        _run_turn(runner, session.id, "a hotel in Paris")

        # The leaf already excluded shown_hotel_ids before returning — nothing
        # new survived this page.
        fake_leg.response_payload = {"results": []}
        calls_before = len(llm.calls)
        reply = _run_turn(runner, session.id, "other options")

        assert len(llm.calls) == calls_before + 1  # triage only — zero synthesis call
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.search_exhausted is True
        assert "criteria" in reply.lower() or "crit" in reply.lower()

    def test_plain_refinement_does_not_advance_the_cursor(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        # "cheaper" is a real new constraint, not a pagination continuation —
        # only is_more_options_signal advances the cursor.
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "A hotel in Paris.",
            '{"family": "search", "language": "en"}', "A cheaper one.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A"}],
            "profile_delta": {"city": "Paris"},
        }
        _run_turn(runner, session.id, "a hotel in Paris")

        fake_leg.response_payload = {"results": [{"id": 1, "name": "Hotel A"}]}
        _run_turn(runner, session.id, "cheaper please")

        outgoing = find_datapart(fake_leg.seen_outgoing_parts)
        assert outgoing["profile_in"]["search_cursor"] == 0


class TestProvenanceHonestyThroughTheSpine:
    """S12 audit 2026-07-20: a non-explicit budget/timeslot must never be
    claimed as user-requested by the synthesis LLM (rule 8) — the PROVENANCE
    marker mirrors the existing AUTO_WIDEN precedent."""

    def test_default_budget_source_is_exposed_as_provenance(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A"}],
            "profile_delta": {"budget_max": 150, "budget_request_source": BUDGET_SOURCE_FLEXIBLE_DEFAULT},
        }
        llm = _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Here is a hotel.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "hotels in Paris")

        user_msg = llm.calls[-1]["messages"][1]["content"]
        system_msg = llm.calls[-1]["messages"][0]["content"]
        assert "PROVENANCE" in user_msg
        assert "flexible_default" in user_msg
        assert "never claim the user requested" in system_msg.lower()

    def test_explicit_budget_never_gets_a_provenance_note(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A"}],
            "profile_delta": {"budget_max": 150, "budget_request_source": BUDGET_SOURCE_EXPLICIT},
        }
        llm = _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Here is a hotel.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "hotels in Paris under 150")

        assert "PROVENANCE" not in llm.calls[-1]["messages"][1]["content"]


class TestCurrencyDisclosureThroughTheSpine:
    """S-G7 (A6-a): display stays EUR, never an invented conversion — the
    CURRENCY marker mirrors the existing PROVENANCE/AUTO_WIDEN precedent.
    Two independent triggers: the user's own native-context currency
    (profile.currency), and a shown hotel's own `currency_code` (live-probed
    2026-07-23 — MCP sends it, but the numeric price stays EUR regardless)."""

    def test_non_eur_user_currency_triggers_a_disclosure(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A"}],
            "profile_delta": {"city": "Miami", "currency": "USD"},
        }
        llm = _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Here is a hotel.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "hotels in Miami")

        user_msg = llm.calls[-1]["messages"][1]["content"]
        system_msg = llm.calls[-1]["messages"][0]["content"]
        assert "CURRENCY" in user_msg
        assert "USD" in user_msg
        assert "no conversion" in system_msg.lower()

    def test_non_eur_hotel_currency_triggers_a_disclosure_even_without_user_currency(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A", "currency_code": "USD"}],
            "profile_delta": {"city": "Miami"},
        }
        llm = _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Here is a hotel.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "hotels in Miami")

        user_msg = llm.calls[-1]["messages"][1]["content"]
        assert "CURRENCY" in user_msg
        assert "USD" in user_msg

    def test_eur_currency_never_gets_a_disclosure(self, monkeypatch, fake_leg, fake_profile_store):
        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A", "currency_code": "EUR"}],
            "profile_delta": {"city": "Paris", "currency": "EUR"},
        }
        llm = _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Here is a hotel.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "hotels in Paris")

        assert "CURRENCY" not in llm.calls[-1]["messages"][1]["content"]

    def test_unknown_currency_never_gets_a_disclosure(self, monkeypatch, fake_leg, fake_profile_store):
        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A"}],
            "profile_delta": {"city": "Paris"},
        }
        llm = _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Here is a hotel.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "hotels in Paris")

        assert "CURRENCY" not in llm.calls[-1]["messages"][1]["content"]


class TestProfileContinuityAcrossTurns:
    def test_city_from_turn_one_is_sent_as_profile_in_on_turn_two(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": {"city": "Lyon"}}
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', "A hotel in Lyon.",
            '{"family": "search", "language": "en"}', "Another one in Lyon.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "a hotel in Lyon")
        fake_leg.response_payload = {"results": ["hotel B"], "profile_delta": {}}
        _run_turn(runner, session.id, "another one please")

        outgoing_parts = fake_leg.seen_outgoing_parts
        decoded = find_datapart(outgoing_parts)
        assert decoded["profile_in"]["city"] == "Lyon"


class TestProfileStoreOutageDegradesHonestly:
    def test_turn_still_answers_when_redis_is_unreachable(self, monkeypatch, fake_leg):
        """The profile store is a NEW dependency (S5) — it must not become a
        new single point of failure: a Redis outage degrades the turn like a
        leaf outage would (answer served, profile simply not persisted)."""
        from b2c_concierge.profile_store import ProfileStore

        class _DeadClient:
            async def get(self, *a, **k):
                raise ConnectionError("redis unreachable")

            async def set(self, *a, **k):
                raise ConnectionError("redis unreachable")

        monkeypatch.setattr(agent_module, "get_profile_store", lambda: ProfileStore(_DeadClient()))
        fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": {"city": "Nice"}}
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "A hotel in Nice.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        answer = _run_turn(runner, session.id, "a hotel in Nice")

        assert answer == "A hotel in Nice."


class TestCheapestPickThroughTheSpine:
    """S-CX5, prod session 2026-07-27 replayed over the real spine.

    Fabien searched Paris (5 hotels, cheapest €54), then typed "ok je veux
    booké le moins cher". The turn re-ran a SEARCH — the message matched the
    refinement keywords — and that search excluded every hotel already shown,
    so it answered with ranks 6-10 (€81/€87/€112) under the sentence "La moins
    chère est". Two defects in one turn: the pick became a search, and the
    search hid the very hotels it was meant to rank."""

    SEARCH_RESULTS = [
        {
            "hotel_id": 101, "name": "Villa Paris Orly", "price": "€54.00",
            "price_eur_cents": 5400, "offer_id": "offer-villa", "offer_date": "2026-07-28",
            "timeslots": [{"start": "10:00", "end": "17:00"}],
        },
        {
            "hotel_id": 102, "name": "OKKO Hotels Paris Rueil", "price": "€70.00",
            "price_eur_cents": 7000, "offer_id": "offer-okko", "offer_date": "2026-07-28",
        },
        {
            "hotel_id": 103, "name": "Eurohotel Créteil", "price": "€58.00",
            "price_eur_cents": 5800, "offer_id": "offer-euro", "offer_date": "2026-07-28",
        },
    ]

    def _fake_mcp(self, monkeypatch):
        from contextlib import asynccontextmanager

        calls: list[tuple[str, dict]] = []

        class _Res:
            isError = False
            structuredContent = {"confirmationRequired": True, "hotel": {}, "offer": {}}
            content: list = []

        class _Session:
            async def call_tool(self, name, arguments):
                calls.append((name, dict(arguments)))
                return _Res()

        @asynccontextmanager
        async def _session():
            yield _Session()

        monkeypatch.setattr(agent_module.inline_tools, "_mcp_session", _session)
        return calls

    def test_the_cheapest_is_picked_from_the_screen_never_re_searched(
        self, monkeypatch, fake_leg
    ):
        mcp_calls = self._fake_mcp(monkeypatch)
        fake_leg.response_payload = {
            "results": self.SEARCH_RESULTS,
            "profile_delta": {"city": "Paris", "date": "2026-07-28"},
        }
        # Turn 2: triage read both a booking intent AND the superlative.
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "pick": "none"}',
            "Pour demain à Paris, voici 3 offres.",
            '{"family": "booking", "language": "fr", "pick": "cheapest"}',
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "je veux un hôtel à Paris pour demain")
        assert fake_leg.call_count == 1

        _run_turn(runner, session.id, "ok je veux booké le moins cher")

        # No second search at all: the answer was already on screen.
        assert fake_leg.call_count == 1
        link_call = next(c for c in mcp_calls if c[0] == "generate_booking_link")
        # €54.00 — the cheapest — not the first, not a relevance-ranked pick.
        assert link_call[1]["hotelId"] == 101
        assert link_call[1]["ratePlanUuid"] == "offer-villa"
        assert link_call[1]["date"] == "2026-07-28"
        # S-CX5: an explicit pick on a booking turn IS the confirmation — the
        # link comes back on this turn, no "vous confirmez ?" round-trip.
        assert link_call[1]["confirmed"] is True
        # And resolving it took no MCP lookup either — the shortlist knew.
        assert "find_hotel_by_name" not in {c[0] for c in mcp_calls}
        assert "get_hotel_details" not in {c[0] for c in mcp_calls}

    def test_a_bare_comparative_still_runs_a_fresh_search(self, monkeypatch, fake_leg):
        """The mirror case: "quelque chose de moins cher" is a real refinement
        and must still reach the leaf, or this fix would break re-searching."""
        self._fake_mcp(monkeypatch)
        fake_leg.response_payload = {
            "results": self.SEARCH_RESULTS,
            "profile_delta": {"city": "Paris", "date": "2026-07-28"},
        }
        # Triage reads the comparative correctly: pick=none -> a real search.
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "pick": "none"}',
            "Pour demain à Paris, voici 3 offres.",
            '{"family": "search", "language": "fr", "pick": "none"}',
            "Voici des options moins chères.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "je veux un hôtel à Paris pour demain")
        _run_turn(runner, session.id, "tu as quelque chose de moins cher ?")

        assert fake_leg.call_count == 2

    def test_a_refined_search_stops_hiding_the_hotels_already_shown(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        """The pagination cursor used to survive every later turn, so the leaf
        kept excluding already-shown hotels from searches that were not
        pagination at all. A refined search must go back to page 1."""
        fake_leg.response_payload = {
            "results": self.SEARCH_RESULTS,
            "profile_delta": {"city": "Paris"},
        }
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}', "3 offres.",
            '{"family": "search", "language": "fr"}', "3 autres offres.",
            '{"family": "search", "language": "fr"}', "avec piscine.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "un hôtel à Paris")
        _run_turn(runner, session.id, "montre-moi d'autres options")
        assert asyncio.run(fake_profile_store.get(session.id)).search_cursor == 1

        _run_turn(runner, session.id, "avec une piscine")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.search_cursor == 0
        # The exclusion set survives for the NEXT real pagination turn.
        assert stored.shown_hotel_ids == [101, 102, 103]


class TestPickWithoutBookingIntent:
    """S-CX5 safety line: understanding that a message POINTS AT a hotel is not
    the same as being asked to book it. "montre-moi le moins cher" must answer
    ABOUT that hotel — never mint a tunnel link nobody asked for, and never
    fall back to a search that would re-rank the named hotel away."""

    def test_a_display_pick_goes_to_details_not_to_a_link(self, monkeypatch, fake_leg):
        from contextlib import asynccontextmanager

        calls: list[tuple[str, dict]] = []

        class _Session:
            async def call_tool(self, name, arguments):
                calls.append((name, dict(arguments)))
                return SimpleNamespace(
                    isError=False,
                    content=[],
                    structuredContent={
                        "hotel": {"hotelId": 101, "name": "Villa Paris Orly"},
                        "offers": [{"priceEuro": 5400, "availabilityDate": "2026-07-28"}],
                    },
                )

        @asynccontextmanager
        async def _session():
            yield _Session()

        monkeypatch.setattr(agent_module.inline_tools, "_mcp_session", _session)
        fake_leg.response_payload = {
            "results": TestCheapestPickThroughTheSpine.SEARCH_RESULTS,
            "profile_delta": {"city": "Paris", "date": "2026-07-28"},
        }
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "pick": "none"}',
            "Pour demain à Paris, voici 3 offres.",
            '{"family": "search", "language": "fr", "pick": "cheapest"}',
            "La moins chère est la Villa Paris Orly à 54 €.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "je veux un hôtel à Paris pour demain")
        _run_turn(runner, session.id, "montre-moi le moins cher")

        tools = {c[0] for c in calls}
        assert "generate_booking_link" not in tools  # no unrequested link
        assert "get_hotel_details" in tools
        assert calls[0][1]["hotelId"] == 101  # and it IS the cheapest one
        assert fake_leg.call_count == 1  # no re-search either
