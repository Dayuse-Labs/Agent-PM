"""Spine tests over a real ADK runner — offline, LLM and leaves mocked.

Locks the S2 structural invariants:
- a simple search turn stays within the <= 3 LLM calls/turn budget (THE test
  required by the phase — it fails if a 4th call ever slips in);
- an ack turn costs ZERO LLM calls;
- honest degradation on leaf failure (no synthesis, no invention);
- inline stub turns answer via template (triage only);
- logs and metrics never carry message content (GDPR).
"""
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

import b2c_concierge.agent as agent_module
from b2c_concierge import templates
from b2c_concierge.agent import root_agent
from b2c_concierge.budget import MAX_LLM_CALLS_PER_TURN
from b2c_concierge.profile import SessionProfile

USER_MESSAGE_SEARCH = "je cherche un hôtel à Paris demain"


def _llm_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _async_result(value):
    """An async callable (any signature) that always returns `value` — used
    to fake inline_tools.get_hotel_details/compare_hotels/generate_booking_link
    without ever attempting a real MCP connection in tests."""

    async def _fake(*args, **kwargs):
        return value

    return _fake


def _recording_async_result(value):
    """Like `_async_result`, but records every call's args/kwargs on
    `.calls` — used to assert on the exact `user_confirmed` the spine passed
    down (R9's bypass guarantee)."""
    calls: list[tuple[tuple, dict]] = []

    async def _fake(*args, **kwargs):
        calls.append((args, kwargs))
        return value

    _fake.calls = calls
    return _fake


class ScriptedLlm:
    """Queue of canned litellm outcomes (str → response, Exception → raise).
    Any call beyond the plan fails the test: that IS the budget leash."""

    def __init__(self, *plan):
        self.plan = list(plan)
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if not self.plan:
            raise AssertionError("unexpected extra LLM call (budget breach)")
        item = self.plan.pop(0)
        if isinstance(item, Exception):
            raise item
        if not isinstance(item, str):
            return item  # a pre-built response (e.g. finish_reason=length)
        return _llm_response(item)


class _LeafCalls(list):
    """The leaves called, in order; `.kwargs` holds what each call was given."""

    def __init__(self):
        super().__init__()
        self.kwargs: list[dict] = []


@pytest.fixture
def scripted(monkeypatch):
    """Installs a scripted LLM + a fake leaf leg; returns (llm, leaf_calls)."""

    def _install(*plan, leaf_text="LEAF OUTCOME", response=None):
        llm = ScriptedLlm(*plan)
        # Both triage and synthesis resolve litellm.acompletion at call time on
        # the shared module object — one patch covers both call sites.
        monkeypatch.setattr(agent_module.litellm, "acompletion", llm)
        leaf_calls = _LeafCalls()

        async def fake_run_leaf(leaf, ctx, profile_in, **kwargs):
            leaf_calls.append(leaf)
            leaf_calls.kwargs.append(kwargs)
            return leaf_text, dict(response or {})

        monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
        return llm, leaf_calls

    return _install


def _marker_payloads(events) -> list[dict]:
    """The decoded `{"event": ...}` payload of every partial marker event, in
    order — progress/hotels use the \\x1f (Unit Separator) prefix; plain
    streamed answer chunks (also partial) do not and are excluded."""
    payloads = []
    for event in events:
        if not event.partial or not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.text and part.text.startswith(agent_module._US):
                payloads.append(json.loads(part.text[len(agent_module._US):]))
    return payloads


def _stream_chunks(events) -> list[str]:
    """Plain streamed-answer partial chunks (progress/hotels markers excluded)."""
    chunks = []
    for event in events:
        if not event.partial or not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.text and not part.text.startswith(agent_module._US):
                chunks.append(part.text)
    return chunks


def _marker_index(events, kind: str) -> int:
    for i, event in enumerate(events):
        if not event.partial or not event.content or not event.content.parts:
            continue
        text = event.content.parts[0].text or ""
        if text.startswith(agent_module._US) and json.loads(text[len(agent_module._US):]).get("event") == kind:
            return i
    raise AssertionError(f"no {kind!r} marker event found")


def _final_index(events) -> int:
    for i, event in enumerate(events):
        if not event.partial:
            return i
    raise AssertionError("no final (non-partial) event found")


def _new_session():
    runner = InMemoryRunner(root_agent)

    async def go():
        return await runner.session_service.create_session(app_name=runner.app_name, user_id="u")

    return runner, asyncio.run(go())


def _drive_in(runner, session_id, message: str) -> list:
    async def go():
        content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
        return [
            event
            async for event in runner.run_async(user_id="u", session_id=session_id, new_message=content)
        ]

    return asyncio.run(go())


def _answer(events) -> str:
    texts = [
        part.text
        for event in events
        if not event.partial and event.content and event.content.parts
        for part in event.content.parts
        if part.text
    ]
    return "\n".join(texts).strip()


def _drive(message: str) -> str:
    """One turn through a real InMemoryRunner; returns the final answer text."""
    runner = InMemoryRunner(root_agent)

    async def go():
        session = await runner.session_service.create_session(
            app_name=runner.app_name, user_id="u"
        )
        content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
        return [
            event
            async for event in runner.run_async(
                user_id="u", session_id=session.id, new_message=content
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


def _drive_events(message: str) -> list:
    """Like `_drive` but returns the RAW event list — for tests that inspect
    the progress/hotels markers or the streamed chunk sequence."""
    runner = InMemoryRunner(root_agent)

    async def go():
        session = await runner.session_service.create_session(
            app_name=runner.app_name, user_id="u"
        )
        content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
        return [
            event
            async for event in runner.run_async(
                user_id="u", session_id=session.id, new_message=content
            )
        ]

    return asyncio.run(go())


def _turn_metric(caplog) -> dict:
    line = next(
        record.getMessage()
        for record in caplog.records
        if "concierge_metric=turn" in record.getMessage()
    )
    return dict(kv.split("=", 1) for kv in line.split() if "=" in kv)


class TestBudget:
    def test_simple_search_turn_stays_within_llm_budget(self, scripted, caplog):
        llm, leaf_calls = scripted(
            '{"family": "search", "language": "fr"}',
            "Voici 2 hôtels à Paris pour demain.",
            leaf_text="results: hotel A, hotel B",
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive(USER_MESSAGE_SEARCH)
        assert answer == "Voici 2 hôtels à Paris pour demain."
        assert leaf_calls == ["hotel_search"]
        metric = _turn_metric(caplog)
        # THE phase invariant: a simple turn must never exceed 3 LLM calls.
        assert int(metric["llm_calls"]) <= MAX_LLM_CALLS_PER_TURN
        assert metric["llm_calls"] == "3"  # triage + leaf slot + synthesis
        assert metric["phases"] == "triage,leaf_llm,synthesis"

    def test_ack_turn_costs_zero_llm(self, scripted, caplog):
        llm, leaf_calls = scripted()  # empty plan: ANY llm call fails the test
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive("Bonjour !")
        assert answer == templates.ack_response("fr")
        assert llm.calls == []
        assert leaf_calls == []
        assert _turn_metric(caplog)["llm_calls"] == "0"

    def test_first_turn_bare_ok_with_fr_locale_gets_the_french_ack(
        self, scripted, fake_profile_store
    ):
        # S-CX2 (audit F5): a bare "ok" has no language signal for
        # guess_language — the client locale (applied to the profile by the
        # facade before the spine runs, S-G2) must beat the English default.
        scripted()  # zero-LLM path: any call fails the test
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(locale="fr-FR")))
        events = _drive_in(runner, session.id, "ok")
        assert _answer(events) == templates.affirmative_relaunch_response("fr", searched=False)

    def test_inline_lookup_turn_degrades_on_triage_only_when_unresolved(self, scripted, caplog, monkeypatch):
        # The details lookup fails for another reason than "no such hotel"
        # (MCP unreachable): degrades honestly BEFORE any synthesis call
        # (mirrors the leaf-degradation budget shape).
        llm, leaf_calls = scripted('{"family": "details", "language": "fr"}')
        monkeypatch.setattr(
            agent_module.inline_tools, "get_hotel_details",
            _async_result({"ok": False, "error": "get_hotel_details failed: ConnectError"}),
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive("quels équipements a le Sonesta Carmel ?")
        assert answer == templates.inline_unresolved_response("get_hotel_details", "fr")
        assert len(llm.calls) == 1
        assert leaf_calls == []
        metric = _turn_metric(caplog)
        assert metric["llm_calls"] == "1"
        assert metric["route"] == "inline:get_hotel_details"
        assert metric["status"] == "degraded"

    def test_a_details_turn_naming_no_hotel_found_goes_to_the_search(self, scripted, caplog, monkeypatch):
        # 2026-10-27 (prod « Vasca idromassaggio », « 有浴缸 »): no hotel on
        # screen or in the catalogue answers to the message — it was never a
        # question about one. The search leaf gets the turn, never the
        # "I couldn't find that hotel" template. Still 3 LLM slots at most.
        llm, leaf_calls = scripted(
            '{"family": "details", "language": "it"}', "Ecco gli hotel con vasca idromassaggio.",
            response={"results": [{"hotel_id": 1, "name": "Hotel A"}]},
        )
        monkeypatch.setattr(
            agent_module.inline_tools, "get_hotel_details",
            _async_result({"ok": False, "error": "no hotel reference in the message"}),
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive("Vasca idromassaggio")
        assert answer != templates.inline_unresolved_response("get_hotel_details", "it")
        assert leaf_calls == [agent_module.LEAF_HOTEL_SEARCH]
        metric = _turn_metric(caplog)
        assert metric["route"] == "leaf:hotel_search"
        assert int(metric["llm_calls"]) <= 3

    def test_inline_lookup_turn_synthesizes_when_resolved(self, scripted, caplog, monkeypatch):
        llm, leaf_calls = scripted(
            '{"family": "details", "language": "fr"}',
            "Le Sonesta Carmel a une piscine et un spa.",
        )
        monkeypatch.setattr(
            agent_module.inline_tools, "get_hotel_details",
            _async_result(
                {"ok": True, "hotel": {"id": 1, "name": "Sonesta Carmel", "amenities": ["Pool", "Spa"]}}
            ),
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive("quels équipements a le Sonesta Carmel ?")
        assert answer == "Le Sonesta Carmel a une piscine et un spa."
        assert leaf_calls == []
        metric = _turn_metric(caplog)
        assert metric["llm_calls"] == "2"  # triage + synthesis, no leaf/MCP-LLM slot
        assert metric["route"] == "inline:get_hotel_details"
        assert metric["status"] == "ok"


class TestRoutingThroughTheSpine:
    def test_faq_turn_routes_to_the_faq_leaf(self, scripted):
        llm, leaf_calls = scripted(
            '{"family": "faq", "language": "fr"}',
            "Vous pouvez annuler gratuitement jusqu'à l'heure d'arrivée.",
            leaf_text="conditions: free cancellation until check-in",
        )
        answer = _drive("quelles sont les conditions d'annulation ?")
        assert leaf_calls == ["faq"]
        assert answer == "Vous pouvez annuler gratuitement jusqu'à l'heure d'arrivée."

    def test_triage_llm_failure_still_routes_via_regex(self, scripted):
        llm, leaf_calls = scripted(
            TimeoutError("triage down"),
            "Voici ce que j'ai trouvé.",
            leaf_text="results: hotel C",
        )
        answer = _drive("je cherche un hôtel à Lyon")
        assert leaf_calls == ["hotel_search"]  # regex fallback family
        assert answer == "Voici ce que j'ai trouvé."


class TestLanguageWhenTheTriageFails:
    """Demo 2026-10-27 (session synthetic-deploy-widen-4641f0a9): the triage
    timed out on « élargir la zone » and its regex guess answered a French
    session in English."""

    @staticmethod
    def _stuck():
        return agent_module.litellm.Timeout(message="stuck", model="openai/gpt-6-luna", llm_provider="openai")

    def _synthesis_lang(self, llm) -> str:
        user = llm.calls[-1]["messages"][-1]["content"]
        return next(line for line in user.splitlines() if line.startswith("LANG:"))

    def test_the_session_language_stands(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(language="fr", city="Paris")))
        llm, leaf_calls = scripted(self._stuck(), self._stuck(), "Voici d'autres hôtels.",
                                   leaf_text="results: hotel A")
        _drive_in(runner, session.id, "élargir la zone")
        assert leaf_calls == ["hotel_search"]
        assert self._synthesis_lang(llm) == "LANG: fr"

    def test_on_a_first_turn_the_locale_stands(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(locale="fr-FR", city="Paris")))
        llm, _ = scripted(self._stuck(), self._stuck(), "Voici d'autres hôtels.", leaf_text="results: hotel A")
        _drive_in(runner, session.id, "élargir la zone")
        assert self._synthesis_lang(llm) == "LANG: fr"


class TestHonestDegradation:
    def test_leaf_failure_degrades_honestly_without_synthesis(self, scripted, caplog, monkeypatch):
        llm, _ = scripted('{"family": "search", "language": "fr"}')

        async def dead_leaf(leaf, ctx, profile_in, **kwargs):
            return None, {}

        monkeypatch.setattr(agent_module, "_run_leaf", dead_leaf)
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive(USER_MESSAGE_SEARCH)
        assert answer == templates.leaf_degraded_response("search", "fr")
        assert len(llm.calls) == 1  # triage only: no synthesis over nothing
        assert _turn_metric(caplog)["status"] == "degraded"

    def test_synthesis_failure_serves_leaf_text_verbatim(self, scripted, caplog):
        llm, leaf_calls = scripted(
            '{"family": "search", "language": "fr"}',
            TimeoutError("synthesis down"),
            leaf_text="GROUNDED LEAF TEXT",
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive(USER_MESSAGE_SEARCH)
        assert answer == "GROUNDED LEAF TEXT"
        assert _turn_metric(caplog)["status"] == "synthesis_fallback"

    @pytest.mark.parametrize(
        "synthesis",
        [
            # QA trace 62207822: gpt-5.2 spent max_tokens on reasoning.
            SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=None), finish_reason="length",
            )]),
            # Cut off mid-sentence: still never served.
            SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="Vous avez de belles"), finish_reason="length",
            )]),
            _llm_response("   "),
        ],
        ids=["length-empty", "length-partial", "blank"],
    )
    def test_unusable_synthesis_serves_a_clean_scored_fallback(
        self, scripted, caplog, monkeypatch, synthesis
    ):
        scored: list[set[str]] = []
        monkeypatch.setattr(agent_module, "score_fallbacks", lambda f: scored.append(set(f)))
        scripted(
            '{"family": "search", "language": "fr"}',
            synthesis,
            leaf_text=(
                "5 offre(s) de jour trouvée(s) : Hotel A, Hotel B. "
                "Recherche effectuée pour le 2026-09-30."
            ),
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive("un hôtel à San Francisco avec parking et piscine")
        assert "2026-09-30" not in answer
        assert "mercredi 30 septembre 2026" in answer
        assert "Vous avez de belles" not in answer
        assert "filtrer les résultats sur le parking" in answer
        assert _turn_metric(caplog)["status"] == "synthesis_fallback"
        assert scored == [{"synthesis"}]

    def test_a_good_synthesis_still_carries_the_parking_reserve(self, scripted):
        # mcp-dayuse#4 (trace 62207822, live repro 2026-10-07): parking is not
        # filterable, and a normal synthesis answered "tous avec piscine".
        scripted(
            '{"family": "search", "language": "fr"}',
            "Voici une sélection d'hôtels à Lyon, tous avec piscine.",
            response={"results": [{"hotel_id": 1, "name": "Hotel A"}]},
        )
        answer = _drive("un hôtel à Lyon demain avec parking et piscine")
        assert answer.startswith("Voici une sélection d'hôtels à Lyon, tous avec piscine.")
        assert answer.count("filtrer les résultats sur le parking") == 1

    def test_parking_reserve_needs_cards_on_screen(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            "Aucune offre ce jour-là.",
            response={"results": []},
        )
        assert "parking" not in _drive("un hôtel à Lyon demain avec parking")

    def test_a_good_synthesis_scores_no_fallback(self, scripted, monkeypatch):
        scored: list[set[str]] = []
        monkeypatch.setattr(agent_module, "score_fallbacks", lambda f: scored.append(set(f)))
        scripted('{"family": "search", "language": "fr"}', "Voici deux hôtels.")
        assert _drive(USER_MESSAGE_SEARCH) == "Voici deux hôtels."
        assert scored == [set()]

    def test_a_rejected_search_asks_to_rephrase_not_to_retry(self, scripted, monkeypatch):
        # QA trace 9bc5feb6: an argument the MCP schema refuses got "retry in a
        # moment", which can only fail the same way.
        scored: list[set[str]] = []
        monkeypatch.setattr(agent_module, "score_fallbacks", lambda f: scored.append(set(f)))
        scripted(
            '{"family": "search", "language": "fr"}',
            leaf_text="La recherche d'hôtels est momentanément indisponible.",
            response={
                "status": "search_unavailable", "unavailable_reason": "rejected",
                "fallbacks_fired": ["mcp_error"],
            },
        )
        assert _drive(USER_MESSAGE_SEARCH) == templates.search_rejected_response("fr")
        assert scored == [{"mcp_error"}]

    def test_named_hotel_missing_from_city_results_is_said_first(self, scripted, monkeypatch):
        # QA trace 6ef04c80: the named hotel was not found and a city-wide
        # search answered without a word about it.
        scored: list[set[str]] = []
        monkeypatch.setattr(agent_module, "score_fallbacks", lambda f: scored.append(set(f)))
        scripted(
            '{"family": "search", "language": "fr"}',
            "Plusieurs options à Lyon.",
            response={
                "results": [{"hotel_id": 1, "name": "Hotel Dau Ly"}],
                "named_hotel_not_found": "Novotel Lyon Zorbalix",
                "fallbacks_fired": ["named_hotel_not_found"],
                "profile_delta": {"city": "Lyon"},
            },
        )
        answer = _drive("des dispos au Novotel Lyon Zorbalix ?")
        assert answer == (
            templates.named_hotel_not_found_notice("Novotel Lyon Zorbalix", "fr", "Lyon")
            + "\n\nPlusieurs options à Lyon."
        )
        assert scored == [{"named_hotel_not_found"}]

    def test_no_notice_when_the_named_hotel_is_on_screen_anyway(self, scripted):
        # The name lookup is stricter than the search (mcp-dayuse#3).
        scripted(
            '{"family": "search", "language": "fr"}',
            "Le Pullman Lyon est disponible.",
            response={
                "results": [{"hotel_id": 1, "name": "Pullman Lyon"}],
                "named_hotel_not_found": "Pullman Lyon",
                "profile_delta": {"city": "Lyon"},
            },
        )
        assert _drive("le Pullman Lyon a des dispos ?") == "Le Pullman Lyon est disponible."

    def test_a_named_hotel_is_handed_to_the_leaf_by_name(self, scripted):
        # mcp-dayuse#7: « St Paul's Hotel » was geocoded as a landmark.
        _, leaf_calls = scripted(
            '{"family": "search", "language": "fr", "hotel_name": "St Paul\'s Hotel"}',
            "Le St Paul's Hotel est disponible.",
            response={"results": [{"hotel_id": 7, "name": "St Paul's Hotel"}]},
        )
        _drive("un hôtel au St Paul's Hotel à Londres demain")
        assert [k["query_params"] for k in leaf_calls.kwargs] == [{"hotel_name": "St Paul's Hotel"}]

    def test_a_named_hotel_without_offers_that_day_is_said_first(self, scripted):
        from datetime import timedelta

        from b2c_concierge.date_format import format_date_human
        from b2c_concierge.requested_date import reference_today

        # Clock-relative: a literal "demain" date rots the next day (the
        # date_served guard then fires on top of the notice under test).
        tomorrow = (reference_today(None) + timedelta(days=1)).isoformat()
        scripted(
            '{"family": "search", "language": "fr", "hotel_name": "St Paul\'s Hotel"}',
            "Voici des hôtels proches.",
            response={
                "results": [{"hotel_id": 3, "name": "The W14"}],
                "search_date": {"date": tomorrow},
                "named_hotel": {"name": "St Paul's Hotel", "offered": False},
            },
        )
        answer = _drive("un hôtel au St Paul's Hotel à Londres demain")
        assert answer == (
            templates.named_hotel_not_offered_notice(
                "St Paul's Hotel", format_date_human(tomorrow, "fr"), "fr"
            )
            + "\n\nVoici des hôtels proches."
        )

    def test_several_matching_hotels_are_a_question_then_the_reply_picks_one(
        self, monkeypatch, fake_profile_store
    ):
        candidates = [
            {"name": "Leonardo Royal Hotel London City", "city": "london"},
            {"name": "Leonardo Royal Hotel London St Pauls", "city": "london"},
        ]
        plan = [
            '{"family": "search", "language": "fr", "hotel_name": "Leonardo Royal"}',
            # triage reads « celui de … » as a position: the words must win.
            '{"family": "search", "language": "fr", "pick": "position", "pick_position": 1}',
            "Le Leonardo Royal Hotel London St Pauls est disponible.",
        ]
        monkeypatch.setattr(agent_module.litellm, "acompletion", ScriptedLlm(*plan))
        sent: list[dict] = []
        responses = [
            {"named_hotel_ambiguous": {"query": "Leonardo Royal", "candidates": candidates},
             "requires_clarification": True},
            {"results": [{"hotel_id": 2, "name": "Leonardo Royal Hotel London St Pauls"}]},
        ]

        async def fake_run_leaf(leaf, ctx, profile_in, **kwargs):
            sent.append(kwargs)
            return None, responses.pop(0)

        monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
        runner, session = _new_session()
        first = _answer(_drive_in(runner, session.id, "je veux le Leonardo Royal à Londres demain"))
        assert first == templates.named_hotel_ambiguous_response("Leonardo Royal", candidates, "fr")
        _drive_in(runner, session.id, "celui de St Pauls")
        assert sent[1]["query_params"]["hotel_name"] == "Leonardo Royal Hotel London St Pauls"
        assert asyncio.run(fake_profile_store.get(session.id)).named_candidates is None

    def test_a_homonym_question_is_answered_in_the_conversation_language(
        self, monkeypatch, fake_profile_store
    ):
        # mcp-dayuse#7: « New York » answering « which Manhattan? » came back in
        # English. (Q11: the place asked about no longer travels as a profile
        # slot any more; the language assertions stand.)
        plan = [
            '{"family": "search", "language": "fr"}',
            "Quel Manhattan ?",
            '{"family": "search", "language": "en"}',
            "Voici des hôtels à Manhattan.",
        ]
        llm = ScriptedLlm(*plan)
        monkeypatch.setattr(agent_module.litellm, "acompletion", llm)
        seen: list[dict] = []
        responses = [
            {"requires_clarification": True},
            {"results": [{"hotel_id": 1, "name": "Moxy NYC Downtown"}],
             "profile_delta": {"city": "Manhattan"}},
        ]

        async def fake_run_leaf(leaf, ctx, profile_in, **kwargs):
            seen.append(dict(profile_in))
            return "leaf", responses.pop(0)

        monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
        runner, session = _new_session()
        _drive_in(runner, session.id, "un hôtel à Manhattan demain")
        _drive_in(runner, session.id, "New York")
        assert "LANG: fr" in str(llm.calls[3]["messages"])
        profile = asyncio.run(fake_profile_store.get(session.id))
        assert profile.language == "fr"

    def test_named_hotel_not_found_without_any_text_is_answered_in_code(self, scripted, caplog):
        scripted(
            '{"family": "search", "language": "fr"}',
            leaf_text=None,
            response={"named_hotel_not_found": "Novotel Lyon Zorbalyx",
                      "fallbacks_fired": ["named_hotel_not_found"]},
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive("des dispos au Novotel Lyon Zorbalyx ?")
        assert answer == templates.named_hotel_not_found_response("Novotel Lyon Zorbalyx", "fr")
        assert _turn_metric(caplog)["status"] == "ok"

    def test_search_unavailable_status_degrades_honestly_without_synthesis(
        self, scripted, caplog
    ):
        # S-CX2 (audit CX F2 — false scarcity): the leaf reports the search
        # TOOLS never ran (MCP unreachable / circuit open). The spine must
        # serve the honest degraded template — synthesizing here produced a
        # false "no offers in Marseille" while the backend was simply down.
        llm, _ = scripted(
            '{"family": "search", "language": "fr"}',
            leaf_text="La recherche d'hôtels est momentanément indisponible.",
            response={
                "status": "search_unavailable",
                "profile_delta": {"city": "Marseille"},
            },
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive(USER_MESSAGE_SEARCH)
        # The geocode delta is kept (the destination WAS understood) and names
        # the city in the degraded template.
        assert answer == templates.leaf_degraded_response("search", "fr", "Marseille")
        assert len(llm.calls) == 1  # triage only: never synthesize a fake zero
        assert _turn_metric(caplog)["status"] == "degraded"

    def test_search_unavailable_is_not_recorded_as_an_empty_search(
        self, scripted, fake_profile_store
    ):
        # The inventory was never consulted: no empty-streak, no auto-widen,
        # no recovery chips — a retry must start from a clean slate.
        runner, session = _new_session()
        scripted(
            '{"family": "search", "language": "fr"}',
            leaf_text="indisponible",
            response={"status": "search_unavailable", "profile_delta": {"city": "Marseille"}},
        )
        _drive_in(runner, session.id, USER_MESSAGE_SEARCH)
        profile = asyncio.run(fake_profile_store.get(session.id))
        assert profile.city == "Marseille"  # the delta still landed
        assert profile.consecutive_empty_searches == 0
        assert not profile.last_suggestions

    def test_same_day_dead_end_swaps_in_the_date_chips(self, scripted, fake_profile_store):
        # S-CX6 wiring: the leaf says the empty search was for TODAY, so the
        # recovery chips must offer other days — budget/zone/filter cannot
        # reopen a closed booking window (Fabien's 17h20 session, 2026-07-27).
        runner, session = _new_session()
        scripted(
            '{"family": "search", "language": "fr"}',
            "Aucune offre pour aujourd'hui.",
            leaf_text="Aucune offre.",
            response={
                "results": [],
                "search_date": {
                    "date": "2026-07-27", "same_day": True, "cutoff_closed": True,
                },
            },
        )
        _drive_in(runner, session.id, USER_MESSAGE_SEARCH)
        profile = asyncio.run(fake_profile_store.get(session.id))
        assert profile.last_suggestions == ["voir demain", "après-demain", "élargir la zone"]

    def test_a_future_date_dead_end_keeps_the_budget_zone_filter_chips(
        self, scripted, fake_profile_store
    ):
        runner, session = _new_session()
        scripted(
            '{"family": "search", "language": "fr"}',
            "Aucune offre le 9 septembre.",
            leaf_text="Aucune offre.",
            response={"results": [], "search_date": {"date": "2026-09-09", "same_day": False}},
        )
        _drive_in(runner, session.id, USER_MESSAGE_SEARCH)
        profile = asyncio.run(fake_profile_store.get(session.id))
        assert profile.last_suggestions == [
            "augmenter le budget", "élargir la zone", "retirer un filtre",
        ]

    def test_textless_leaf_with_datapart_synthesizes_instead_of_degrading(
        self, scripted, caplog, monkeypatch
    ):
        # S-G9 finding 2 / S-G10 fix: a leaf turn that ends with ZERO text parts
        # but a real DataPart (the search itself succeeded — observed under
        # gpt-5.2 on follow-up turns) must NOT read as a dead leaf. The
        # synthesis re-writes from the structured results anyway; discarding
        # the response here threw away a successful search AND its profile_delta.
        llm, _ = scripted(
            '{"family": "search", "language": "fr"}',
            "Voici 1 hôtel trouvé à Paris.",
        )

        async def textless_leaf(leaf, ctx, profile_in, **kwargs):
            return None, {
                "results": [{"id": 1, "name": "Villa", "price": "€50.00"}],
                "profile_delta": {"city": {"op": "set", "value": "Paris"}},
            }

        monkeypatch.setattr(agent_module, "_run_leaf", textless_leaf)
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive(USER_MESSAGE_SEARCH)
        assert answer == "Voici 1 hôtel trouvé à Paris."
        assert _turn_metric(caplog)["status"] == "ok"

    def test_leaf_clarify_flag_rides_the_hotels_marker(self, scripted):
        # S-G10 (D3): the leaf's deterministic geocode-clarify DataPart flag
        # must reach the facade via the hotels marker payload.
        llm, _ = scripted(
            '{"family": "search", "language": "en"}',
            "Did you mean Budapest (Hungary) or Budapest (Georgia)?",
            leaf_text="Did you mean Budapest (Hungary), or Budapest (Georgia, United States)?",
            response={"requires_clarification": True},
        )
        runner, session = _new_session()
        events = _drive_in(runner, session.id, USER_MESSAGE_SEARCH)
        hotels_markers = [m for m in _marker_payloads(events) if m.get("event") == "hotels"]
        assert hotels_markers
        assert hotels_markers[0]["requires_clarification"] is True
        assert hotels_markers[0]["hotels"] == []

    def test_search_turn_marker_reports_no_clarification(self, scripted):
        llm, _ = scripted(
            '{"family": "search", "language": "fr"}',
            "Voici ce que j'ai trouvé.",
            leaf_text="results: hotel A",
            response={"results": [{"id": 1, "name": "Villa"}]},
        )
        runner, session = _new_session()
        events = _drive_in(runner, session.id, USER_MESSAGE_SEARCH)
        hotels_markers = [m for m in _marker_payloads(events) if m.get("event") == "hotels"]
        assert hotels_markers
        assert hotels_markers[0]["requires_clarification"] is False

    def test_textless_leaf_with_failed_synthesis_degrades_honestly(
        self, scripted, monkeypatch
    ):
        # Double failure only: no leaf text AND the synthesis call dies —
        # honest degraded template, never an empty final message.
        llm, _ = scripted(
            '{"family": "search", "language": "fr"}',
            TimeoutError("synthesis down"),
        )

        async def textless_leaf(leaf, ctx, profile_in, **kwargs):
            return None, {"results": [{"id": 1, "name": "Villa", "price": "€50.00"}]}

        monkeypatch.setattr(agent_module, "_run_leaf", textless_leaf)
        answer = _drive(USER_MESSAGE_SEARCH)
        assert answer == templates.leaf_degraded_response("search", "fr")


class TestGdprMetricEvents:
    def test_metric_events_never_contain_message_content(self, scripted, monkeypatch):
        """S3 lock: every llm_metric_events row the spine emits carries counters
        and labels only — never the user message (GDPR invariant)."""
        import b2c_concierge.triage as triage_module

        events: list[dict] = []

        def capture(event_type, service, invocation_id, **fields):
            events.append({"event_type": event_type, "service": service, **fields})

        monkeypatch.setattr(agent_module, "enqueue_metric_event", capture)
        monkeypatch.setattr(triage_module, "enqueue_metric_event", capture)
        scripted(
            '{"family": "search", "language": "fr"}',
            "Réponse synthétisée.",
            leaf_text="results: hotel A",
        )
        _drive(USER_MESSAGE_SEARCH)
        assert {e["event_type"] for e in events} >= {"llm_call", "turn"}
        assert all(e["service"] == "b2c_concierge" for e in events)
        blob = json.dumps(events, ensure_ascii=False)
        assert "Paris" not in blob
        assert USER_MESSAGE_SEARCH not in blob

    def test_turn_facts_never_contain_message_content(self, scripted):
        """The widget forwards `turn_facts` to a third party (Amplitude): the
        geocoded city may ride it, the user's words never."""
        message = "je cherche une chambre calme avec terrasse"
        scripted(
            '{"family": "search", "language": "fr"}',
            "Réponse synthétisée.",
            response={"results": [{"name": "Hotel A"}], "profile_delta": {"city": "Lyon"}},
        )
        facts = _turn_facts(_drive_events(message))
        assert facts["resolved_city"] == "Lyon"
        blob = json.dumps(facts, ensure_ascii=False).lower()
        for word in message.split():
            if len(word) > 3:
                assert word not in blob


class TestGdprLogs:
    def test_logs_never_contain_message_content(self, scripted, caplog):
        llm, _ = scripted(
            '{"family": "search", "language": "fr"}',
            "Réponse synthétisée.",
            leaf_text="results: hotel A",
        )
        with caplog.at_level(logging.DEBUG):
            _drive(USER_MESSAGE_SEARCH)
        own_records = [
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("b2c_concierge")
        ]
        assert own_records, "the turn metric line must exist"
        for message in own_records:
            assert "Paris" not in message
            assert USER_MESSAGE_SEARCH not in message


class TestInternalEvents:
    """S06: progress -> hotels -> streamed tokens, the internal event
    contract the S9 SSE facade will expose over the wire."""

    def test_progress_event_is_first_and_partial(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            "Voici votre hôtel.",
            leaf_text="results: hotel A",
        )
        events = _drive_events(USER_MESSAGE_SEARCH)
        assert events[0].partial is True
        assert _marker_payloads(events)[0] == {"event": "progress"}

    def test_progress_event_fires_even_on_pure_ack_turn(self, scripted):
        scripted()  # empty plan: an ack turn must cost zero LLM calls
        events = _drive_events("Bonjour !")
        assert [p["event"] for p in _marker_payloads(events)] == ["progress", "turn_facts"]

    def test_hotels_event_fires_after_leaf_and_before_the_final_answer(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            "Voici votre hôtel.",
            leaf_text="results: hotel A",
            response={"results": [{"name": "Hotel Alameda"}]},
        )
        events = _drive_events(USER_MESSAGE_SEARCH)
        hotels_payloads = [p for p in _marker_payloads(events) if p["event"] == "hotels"]
        assert hotels_payloads == [
            {
                "event": "hotels",
                "hotels": [{"name": "Hotel Alameda"}],
                "requires_clarification": False,
                # S-PERF4: a hotels-first client localizes the cards from this.
                "response_language": "fr",
                # S-PERF4 + S-CX9: no pick for this result — it carries no
                # hotel_id, so it never was bookable and its card gets no CTA.
                "hotel_picks": [],
                "search_page": None,
            }
        ]
        assert _marker_index(events, "hotels") < _final_index(events)

    def test_degraded_inline_turn_has_no_hotels_event(self, scripted, monkeypatch):
        scripted('{"family": "details", "language": "fr"}')
        monkeypatch.setattr(
            agent_module.inline_tools, "get_hotel_details",
            _async_result({"ok": False, "error": "get_hotel_details failed: ConnectError"}),
        )
        events = _drive_events("quels équipements a cet hôtel ?")
        assert [p["event"] for p in _marker_payloads(events)] == ["progress", "turn_facts"]

    def test_resolved_inline_lookup_turn_fires_a_hotels_event(self, scripted, monkeypatch):
        scripted('{"family": "details", "language": "fr"}', "Le voici.")
        monkeypatch.setattr(
            agent_module.inline_tools, "get_hotel_details",
            _async_result({"ok": True, "hotel": {"id": 1, "name": "Hotel A"}}),
        )
        events = _drive_events("quels équipements a le Hotel A ?")
        hotels_payloads = [p for p in _marker_payloads(events) if p["event"] == "hotels"]
        assert hotels_payloads == [
            {
                "event": "hotels",
                "hotels": [{"id": 1, "name": "Hotel A"}],
                "requires_clarification": False,
                "response_language": "fr",
                # details/compare never touch `last_results`, and no search ran
                # in this session — same empty list `build_chat_payload` returns.
                "hotel_picks": [],
                "search_page": None,
            }
        ]

    def test_synthesis_streams_multiple_chunks_that_join_into_the_final_text(self, scripted):
        final_text = "Voici deux hôtels très sympas à Paris pour demain."
        scripted(
            '{"family": "search", "language": "fr"}',
            final_text,
            leaf_text="results: hotel A, hotel B",
        )
        events = _drive_events(USER_MESSAGE_SEARCH)
        chunks = _stream_chunks(events)
        assert len(chunks) > 1, "a single lump chunk is not a stream"
        assert "".join(chunks) == final_text
        assert _answer(events) == final_text
        # every chunk event must be partial (never persisted to the session).
        assert all(e.partial for e in events if e is not events[_final_index(events)])


def _turn_facts(events) -> dict:
    (facts,) = [p for p in _marker_payloads(events) if p["event"] == "turn_facts"]
    return facts


class TestTurnFactsMarker:
    """The one `turn_facts` marker every turn ends on: what the widget's
    analytics event needs and only the spine knows."""

    def test_ack_turn_reports_a_template_answer(self, scripted):
        scripted()
        events = _drive_events("Bonjour !")
        assert _turn_facts(events) == {
            "event": "turn_facts",
            "trace_id": None,
            "family": "ack",
            "route": "template:ack",
            "status": "ok",
            "response_type": "answer",
            "results_count": 0,
            "empty_reason": "none",
            "clarification_reason": "none",
            "guards_fired": [],
            "fallbacks": [],
            "resolved_city": None,
        }

    def test_marker_comes_right_before_the_final_answer(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            "Voici votre hôtel.",
            response={"results": [{"name": "Hotel Alameda"}]},
        )
        events = _drive_events(USER_MESSAGE_SEARCH)
        assert _marker_index(events, "turn_facts") == _final_index(events) - 1
        assert _final_index(events) == len(events) - 1

    def test_search_with_hotels_reports_results_and_the_searched_city(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            "Voici vos hôtels.",
            response={
                "results": [{"name": "Hotel A"}, {"name": "Hotel B"}],
                "profile_delta": {"city": "Lyon"},
                "guards_fired": ["state_anchoring"],
            },
        )
        facts = _turn_facts(_drive_events("un hôtel pour demain"))
        assert facts["family"] == "search"
        assert facts["route"] == "leaf:hotel_search"
        assert facts["response_type"] == "results"
        assert facts["results_count"] == 2
        assert facts["empty_reason"] == "none"
        assert facts["resolved_city"] == "Lyon"
        assert "state_anchoring" in facts["guards_fired"]

    def test_empty_search_reports_no_offers(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            "Aucune offre.",
            response={"results": [], "profile_delta": {"city": "Lyon"}},
        )
        facts = _turn_facts(_drive_events("un hôtel pour ce soir"))
        assert facts["response_type"] == "answer"
        assert facts["results_count"] == 0
        assert facts["empty_reason"] == "no_offers"
        assert facts["resolved_city"] == "Lyon"

    def test_empty_search_on_a_closed_day_reports_date_unavailable(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            "Aucune offre pour aujourd'hui.",
            response={
                "results": [],
                "search_date": {"date": "2026-07-27", "same_day": True, "cutoff_closed": True},
            },
        )
        facts = _turn_facts(_drive_events("un hôtel pour ce soir"))
        assert facts["empty_reason"] == "date_unavailable"

    def test_search_tools_down_reports_an_error(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            response={"status": "search_unavailable", "profile_delta": {"city": "Marseille"}},
        )
        facts = _turn_facts(_drive_events(USER_MESSAGE_SEARCH))
        assert facts["status"] == "degraded"
        assert facts["empty_reason"] == "error"
        assert facts["resolved_city"] is None

    def test_unreachable_search_leaf_reports_an_error(self, scripted, monkeypatch):
        scripted('{"family": "search", "language": "fr"}')

        async def failing_leaf(leaf, ctx, profile_in, **kwargs):
            return None, {}

        monkeypatch.setattr(agent_module, "_run_leaf", failing_leaf)
        facts = _turn_facts(_drive_events(USER_MESSAGE_SEARCH))
        assert facts["status"] == "degraded"
        assert facts["empty_reason"] == "error"

    def test_unreachable_faq_leaf_ran_no_search(self, scripted, monkeypatch):
        scripted('{"family": "faq", "language": "fr"}')

        async def failing_leaf(leaf, ctx, profile_in, **kwargs):
            return None, {}

        monkeypatch.setattr(agent_module, "_run_leaf", failing_leaf)
        facts = _turn_facts(_drive_events("comment annuler ?"))
        assert facts["status"] == "degraded"
        assert facts["empty_reason"] == "none"

    @pytest.mark.parametrize(("kind", "reason"), [("city_needed", "location"), ("homonym", "homonym")])
    def test_place_question_reports_its_kind(self, scripted, kind, reason):
        from b2c_common.clarification import Clarification, ClarificationOption

        options = (
            [
                ClarificationOption(label="Valence (Drôme)", city="Valence", country_code="FR"),
                ClarificationOption(label="Valencia (Spain)", city="Valencia", country_code="ES"),
            ]
            if kind == "homonym"
            else []
        )
        question = Clarification(kind=kind, subject="Valence", options=options)
        scripted(
            '{"family": "search", "language": "fr"}',
            response={"requires_clarification": True, "clarification": question.model_dump(mode="json")},
        )
        facts = _turn_facts(_drive_events("un hôtel à Valence"))
        assert facts["route"] == "template:clarification"
        assert facts["response_type"] == "clarification"
        assert facts["clarification_reason"] == reason
        assert facts["resolved_city"] is None

    def test_free_question_without_a_search_is_a_clarification(self, scripted):
        scripted(
            '{"family": "search", "language": "fr"}',
            "Pour quelle date souhaitez-vous réserver ?",
            leaf_text="For which date?",
            response={"profile_delta": {"city": "Lyon"}},
        )
        facts = _turn_facts(_drive_events("un hôtel à Lyon"))
        assert facts["response_type"] == "clarification"
        assert facts["clarification_reason"] == "other"
        assert facts["empty_reason"] == "none"

    def test_ambiguous_hotel_name_is_a_homonym_question(self, scripted):
        scripted(
            '{"family": "search", "language": "fr", "hotel_name": "Ibis"}',
            response={
                "named_hotel_ambiguous": {
                    "query": "Ibis",
                    "candidates": [{"name": "Ibis Gare"}, {"name": "Ibis Centre"}],
                },
            },
        )
        facts = _turn_facts(_drive_events("l'hôtel Ibis"))
        assert facts["response_type"] == "clarification"
        assert facts["clarification_reason"] == "homonym"

    def test_resolved_details_lookup_reports_the_hotel_shown(self, scripted, monkeypatch):
        scripted('{"family": "details", "language": "fr"}', "Le voici.")
        monkeypatch.setattr(
            agent_module.inline_tools, "get_hotel_details",
            _async_result({"ok": True, "hotel": {"id": 1, "name": "Hotel A"}}),
        )
        facts = _turn_facts(_drive_events("quels équipements a le Hotel A ?"))
        assert facts["route"] == "inline:get_hotel_details"
        assert facts["response_type"] == "results"
        assert facts["results_count"] == 1


_SEARCH = '{"family": "search", "language": "en"}'
_SHOWN_OFFER = {
    "hotel_id": 12, "name": "Example", "offer_id": "shown", "offer_date": "2026-10-10",
    "offer_totals": {"EUR": 11700},
}
_PRICE_LOWER = (
    '{"family": "search", "language": "en",'
    ' "price_comparison": {"value": "lower", "evidence": "cheaper"}}'
)
_CITY_NEEDED_PAYLOAD = {
    "requires_clarification": True,
    "clarification": {"kind": "city_needed", "subject": "Gare du Nord", "options": []},
}


def _route_case(case_id, *, triage, seed=None, response=None, message="a hotel", turns=1,
                expected, booking=None):
    return pytest.param(
        dict(triage=triage, seed=seed, response=response, message=message, turns=turns, booking=booking),
        expected,
        id=case_id,
    )


ROUTE_FACTS_CASES = [
    _route_case(
        "party_question_on_a_booking_turn",
        triage=json.dumps({
            "family": "booking", "language": "en", "hotel_name": "Example",
            "requested_occupancy": {"total": 3, "evidence": "for three"},
        }),
        seed=SessionProfile(city="Paris", last_results=[_SHOWN_OFFER]),
        message="Book Example for three",
        expected=("clarification", "party", "none"),
    ),
    _route_case(
        "party_question_over_an_empty_page",
        triage=_SEARCH,
        seed=SessionProfile(city="Paris", pending_party_total=3),
        response={"results": []},
        expected=("clarification", "party", "none"),
    ),
    _route_case(
        "budget_unit_question_before_the_search",
        triage=json.dumps({
            "family": "search", "language": "en",
            "requested_budget": {"amount": 10, "currency": "EUR", "unit": "hour", "evidence": "10 euros per hour"},
        }),
        seed=SessionProfile(city="Lyon"),
        message="Lyon at 10 euros per hour",
        expected=("clarification", "budget", "none"),
    ),
    _route_case(
        "cheaper_without_a_priced_reference",
        triage=_PRICE_LOWER,
        seed=SessionProfile(city="Paris", last_results=[{"hotel_id": 12, "name": "Unpriced"}]),
        message="Anything cheaper?",
        expected=("clarification", "budget", "none"),
    ),
    _route_case(
        "booking_degraded_with_a_shortlist_on_screen",
        triage='{"family": "booking", "language": "en"}',
        seed=SessionProfile(city="Paris", last_results=[_SHOWN_OFFER]),
        booking={"ok": False, "error": "no hotel reference in the message"},
        expected=("clarification", "other", "none"),
    ),
    _route_case(
        "booking_degraded_without_a_shortlist",
        triage='{"family": "booking", "language": "en"}',
        booking={"ok": False, "error": "no hotel reference in the message"},
        expected=("answer", "none", "none"),
    ),
    _route_case(
        "cheaper_page_with_nothing_strictly_cheaper",
        triage=_PRICE_LOWER,
        seed=SessionProfile(city="Paris", requested_budget={}, last_results=[_SHOWN_OFFER]),
        response={"results": []},
        message="Anything cheaper?",
        expected=("answer", "none", "filters_too_strict"),
    ),
    _route_case(
        "other_options_over_an_exhausted_pool",
        triage=_SEARCH,
        seed=SessionProfile(city="Paris", last_results=[_SHOWN_OFFER]),
        response={"results": []},
        message="other options",
        expected=("answer", "none", "no_offers"),
    ),
    _route_case(
        "third_place_question_gives_up_and_asks_nothing",
        triage=_SEARCH,
        response=_CITY_NEEDED_PAYLOAD,
        turns=3,
        expected=("answer", "none", "none"),
    ),
    _route_case(
        "second_place_question_is_still_a_clarification",
        triage=_SEARCH,
        response=_CITY_NEEDED_PAYLOAD,
        turns=2,
        expected=("clarification", "location", "none"),
    ),
]


class TestRouteTurnFacts:
    @pytest.mark.parametrize(("case", "expected"), ROUTE_FACTS_CASES)
    def test_route_reports_its_response_type_and_reasons(
        self, scripted, monkeypatch, fake_profile_store, case, expected
    ):
        scripted(*[case["triage"]] * case["turns"], response=case["response"])
        if case["booking"] is not None:
            monkeypatch.setattr(
                agent_module.inline_tools, "generate_booking_link", _async_result(case["booking"])
            )
        runner, session = _new_session()
        if case["seed"] is not None:
            asyncio.run(fake_profile_store.set(session.id, case["seed"]))
        for _ in range(case["turns"]):
            events = _drive_in(runner, session.id, case["message"])
        facts = _turn_facts(events)
        assert (facts["response_type"], facts["clarification_reason"], facts["empty_reason"]) == expected


class TestTurnWithTwoFinalEvents:
    def test_the_earlier_final_is_yielded_not_overwritten_and_the_marker_precedes_the_last(
        self, scripted, monkeypatch, caplog
    ):
        scripted()

        async def two_finals(self, ctx, budget):
            self._emit_turn_metric("search", "leaf:hotel_search", budget, 0.0, "ok")
            yield self._final(ctx, "first answer")
            yield self._final(ctx, "last answer")

        monkeypatch.setattr(type(root_agent), "_run_turn", two_finals)
        with caplog.at_level(logging.ERROR, logger="b2c_concierge.agent"):
            events = _drive_events("un hôtel secret")
        finals = [e.content.parts[0].text for e in events if not e.partial]
        assert finals == ["first answer", "last answer"]
        assert _marker_index(events, "turn_facts") == len(events) - 2
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert errors and not any("un hôtel secret" in m or "answer" in m for m in errors)


class TestSynthesisQuestionIsNotPolicedByText:
    """QA14707 (Q11): the P10 text guard (extract the synthesis's last sentence,
    compare it to the previous question, retry once, then strip) is gone. The
    anti-loop works on the stored place question (`pending_clarification.asked`,
    see test_clarification_template.py); a synthesized reply is shown as written
    and costs ONE synthesis call, whatever it ends on."""

    QUESTION = "Which airport area exactly should I prioritize?"

    def test_a_synthesis_repeating_the_previous_question_is_not_retried(
        self, scripted, fake_profile_store, caplog
    ):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(last_clarifying_question=self.QUESTION))
        )
        llm, _ = scripted(
            '{"family": "search", "language": "en"}',
            f"Happy to help! {self.QUESTION}",
            leaf_text="results: hotel A",
        )
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            events = _drive_in(runner, session.id, "let's do nova")
        assert _answer(events) == f"Happy to help! {self.QUESTION}"
        assert len(llm.calls) == 2  # triage + ONE synthesis, no retry
        assert _turn_metric(caplog)["llm_calls"] == "3"  # + the leaf's own slot

    def test_a_new_synthesized_question_is_left_alone(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(last_clarifying_question=self.QUESTION))
        )
        scripted(
            '{"family": "search", "language": "en"}',
            "Got it. What budget should I plan for?",
            leaf_text="results: hotel A",
        )
        events = _drive_in(runner, session.id, "let's do nova")
        assert _answer(events) == "Got it. What budget should I plan for?"

    def test_what_the_next_turn_answers_is_the_leafs_question_not_the_synthesis(
        self, scripted, fake_profile_store
    ):
        runner, session = _new_session()
        scripted(
            '{"family": "search", "language": "en"}',
            "A completely different paraphrase, shall we continue?",
            leaf_text="Here are some options.\nWould you like hotels closer to the centre?",
        )
        _drive_in(runner, session.id, "a hotel in Nice")
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.last_clarifying_question == "Would you like hotels closer to the centre?"

    def test_a_leaf_that_asked_nothing_keeps_the_synthesis_question(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(last_clarifying_question=self.QUESTION))
        )
        scripted(
            '{"family": "search", "language": "en"}',
            "Here you go. Anything else?",
            leaf_text="results: hotel A",
        )
        _drive_in(runner, session.id, "let's do nova")
        stored = asyncio.run(fake_profile_store.get(session.id))
        # Q27: the stale question is gone; the synthesis's own last line
        # (the leaf asked nothing) is what the next turn answers.
        assert stored.last_clarifying_question == "Here you go. Anything else?"


class TestRecoveryAck:
    """P2 (2026-06-11 audit): a bare "ok"/"sure" — or a verbatim recovery-chip
    click — after an empty search must re-run the search, never celebrate a
    stale/empty shortlist via the zero-LLM ack template."""

    def test_bare_ok_after_empty_streak_routes_to_search(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(consecutive_empty_searches=1))
        )
        llm, leaf_calls = scripted(
            '{"family": "ack", "language": "en"}',
            "Sure, widening the search now.",
            leaf_text="results: hotel A",
        )
        events = _drive_in(runner, session.id, "ok")
        assert leaf_calls == ["hotel_search"]
        assert _answer(events) == "Sure, widening the search now."

    def test_recovery_chip_matches_last_suggestions_verbatim(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(
                session.id,
                SessionProfile(
                    last_suggestions=["increase the budget", "try a nearby area", "remove a filter"]
                ),
            )
        )
        llm, leaf_calls = scripted(
            '{"family": "ack", "language": "en"}',
            "Widening the area now.",
            leaf_text="results: hotel A",
        )
        events = _drive_in(runner, session.id, "try a nearby area")
        assert leaf_calls == ["hotel_search"]
        assert _answer(events) == "Widening the area now."
        # The click is a fact the code knows: the leaf widens the ring on it.
        assert leaf_calls.kwargs[0]["query_params"] == {"widen_area": True}

    def test_another_chip_sends_no_widening(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(
                session.id,
                SessionProfile(
                    last_suggestions=["increase the budget", "try a nearby area", "remove a filter"]
                ),
            )
        )
        llm, leaf_calls = scripted(
            '{"family": "ack", "language": "en"}', "Done.", leaf_text="results: hotel A",
        )
        _drive_in(runner, session.id, "remove a filter")
        assert leaf_calls == ["hotel_search"]
        assert "widen_area" not in (leaf_calls.kwargs[0].get("query_params") or {})

    def test_greeting_after_empty_streak_still_goes_to_the_ack_template(
        self, scripted, fake_profile_store
    ):
        """A pure greeting is NOT a recovery signal even with an empty streak
        — only a bare affirmative or a verbatim suggestion match is."""
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(consecutive_empty_searches=2))
        )
        llm, leaf_calls = scripted()  # empty plan: must cost zero LLM calls
        events = _drive_in(runner, session.id, "Bonjour !")
        assert leaf_calls == []
        assert _answer(events) == templates.ack_response("fr")

    def test_bare_ok_without_empty_streak_stays_a_template(self, scripted, fake_profile_store):
        runner, session = _new_session()
        llm, leaf_calls = scripted()  # empty plan: a fresh session has no signal
        events = _drive_in(runner, session.id, "ok")
        assert leaf_calls == []
        assert _answer(events) == templates.affirmative_relaunch_response("en", searched=False)


class TestBareAffirmativeIsNoGreeting:
    """mcp-dayuse#6 (Mathias 2026-10-06): "oui"/"ok" with no question pending
    gets a short relaunch — never "Bonjour, je suis le concierge" mid-way."""

    def test_ok_after_a_search_offers_to_refine(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Nice", language="fr")))
        scripted()  # zero-LLM fast path
        events = _drive_in(runner, session.id, "ok")
        assert _answer(events) == templates.affirmative_relaunch_response("fr", searched=True)

    def test_oui_classified_ack_by_the_llm_relaunches(self, scripted, fake_profile_store):
        # "oui" is not in the fast-path word list: triage says ack.
        runner, session = _new_session()
        llm, leaf_calls = scripted('{"family": "ack", "language": "fr", "affirmative": true}')
        events = _drive_in(runner, session.id, "oui")
        assert leaf_calls == []
        assert _answer(events) == templates.affirmative_relaunch_response("fr", searched=False)

    def test_a_greeting_still_gets_the_greeting(self, scripted, fake_profile_store):
        runner, session = _new_session()
        scripted()
        events = _drive_in(runner, session.id, "bonjour")
        assert _answer(events) == templates.ack_response("fr")


class TestRefinementRouting:
    """Multi-turn (S9+): a follow-up adjusting a PRIOR search (new date, cheaper,
    other zone) must re-search, even when triage mis-labels it booking/details —
    the flat booking dead-end ("Je n'arrive pas à préparer cette réservation")
    was the bug. FAQ is never overridden."""

    def test_date_change_triaged_booking_reroutes_to_search(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Paris")))
        llm, leaf_calls = scripted(
            '{"family": "booking", "language": "fr"}',  # triage MIS-labels it booking
            "Voici des hôtels à Paris pour le 28.",  # synthesis (search path)
            leaf_text="results",
            response={"results": [{"name": "H", "hotel_id": 1}]},
        )
        _drive_in(runner, session.id, "ok je le veux pour le 28")
        assert leaf_calls == ["hotel_search"]  # re-routed to a fresh search, not booking

    def test_budget_change_triaged_details_reroutes_to_search(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Paris")))
        llm, leaf_calls = scripted(
            '{"family": "details", "language": "fr"}',
            "Voici des options moins chères à Paris.",
            leaf_text="results",
            response={"results": [{"name": "H", "hotel_id": 1}]},
        )
        _drive_in(runner, session.id, "moins cher")
        assert leaf_calls == ["hotel_search"]

    def test_faq_is_not_overridden_by_a_refinement_modifier(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Paris")))
        llm, leaf_calls = scripted(
            '{"family": "faq", "language": "fr"}',
            "Les conditions d'annulation sont…",
            leaf_text="policy text",
        )
        _drive_in(runner, session.id, "peut-on annuler pour le 28 juillet ?")
        assert leaf_calls == ["faq"]  # a policy question with a date stays FAQ


class TestBookingNeedsSelection:
    """Transparency: a booking that can't resolve a hotel never dead-ends — it
    lists the on-screen shortlist to pick from, or says what's missing."""

    def test_lists_the_shortlist_when_present(self):
        msg = templates.booking_needs_selection_response(
            [{"hotel_id": 1, "name": "Villa Paris Orly"}, {"hotel_id": 2, "name": "OKKO"}],
            "hotel not found",
            "fr",
        )
        assert "1. Villa Paris Orly" in msg and "2. OKKO" in msg

    def test_no_bookable_offer_reason_is_worded(self):
        msg = templates.booking_needs_selection_response([], "no bookable offer for this hotel", "en")
        assert "no bookable day-use offer" in msg

    def test_no_shortlist_asks_to_search_first(self):
        msg = templates.booking_needs_selection_response(None, "no hotel reference in the message", "fr")
        assert "ville" in msg.lower()


class TestBookingGuardR9:
    """Guard #12 (R9): generate_booking_link is only ever callable through
    the code-owned confirmed=false -> confirmed=true gate. Both legitimate
    paths, plus the bypass attempt that must never produce a link, driven
    through the REAL spine (triage + routing), not just inline_tools.py."""

    def test_fresh_booking_request_quotes_confirmed_false_with_no_synthesis_call(
        self, scripted, caplog, monkeypatch
    ):
        llm, leaf_calls = scripted('{"family": "booking", "language": "en"}')
        fake = _recording_async_result(
            {
                "ok": True,
                "confirmed": False,
                "hotel_name": "Sonesta Carmel",
                "date": "2026-07-20",
                "start_time": "17:00",
                "end_time": "23:00",
                "price": "€54.00",
            }
        )
        monkeypatch.setattr(agent_module.inline_tools, "generate_booking_link", fake)
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive("book the Sonesta Carmel for me")
        assert leaf_calls == []
        assert "Sonesta Carmel" in answer and "€54.00" in answer
        assert "http" not in answer  # no link on the quote turn
        # Zero-LLM booking flow: only the triage slot is charged, never synthesis.
        metric = _turn_metric(caplog)
        assert metric["llm_calls"] == "1"
        assert metric["route"] == "inline:generate_booking_link"
        assert len(llm.calls) == 1
        # The spine passed user_confirmed=False (no pending offer existed yet).
        assert fake.calls[0][0][2] is False

    def test_confirmation_turn_with_pending_offer_returns_the_link(
        self, scripted, fake_profile_store, monkeypatch
    ):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(
                session.id,
                SessionProfile(
                    pending_booking={
                        "hotel_id": 22293,
                        "hotel_name": "Sonesta Carmel",
                        "date": "2026-07-20",
                        "rate_plan_uuid": "abc",
                        "rate_plan_id": None,
                    }
                ),
            )
        )
        # A bare "yes" is a social ack by regex, but the pending booking
        # overrides the fast-path — triage still runs once (classifies the
        # ack), then the booking-confirmation signal re-routes it.
        scripted('{"family": "ack", "language": "en"}')
        fake = _recording_async_result(
            {
                "ok": True,
                "confirmed": True,
                "hotel_name": "Sonesta Carmel",
                "url": "https://www.dayuse.fr/tunnel/booking?offerId=abc",
            }
        )
        monkeypatch.setattr(agent_module.inline_tools, "generate_booking_link", fake)

        events = _drive_in(runner, session.id, "yes")
        answer = _answer(events)
        assert fake.calls[0][0][2] is True
        # S-CX5: the link now rides a `booking_card` marker, and the prose no
        # longer pastes 250 characters of tracked URL next to it.
        card = next(
            m["booking_card"] for m in _marker_payloads(events) if m.get("event") == "booking"
        )
        assert card["url"] == "https://www.dayuse.fr/tunnel/booking?offerId=abc"
        assert card["hotel_name"] == "Sonesta Carmel"
        # The text KEEPS the URL: an A2A consumer never sees the card marker,
        # and the widget strips raw URLs itself when a card is present.
        assert "https://www.dayuse.fr/tunnel/booking?offerId=abc" in answer

    def test_the_rate_plans_reach_the_widget_marker(self, scripted, monkeypatch):
        """S-CX8: the formula selector is only real if the plans survive the
        whole way out — inline tool -> `_booking_card` -> the `booking` marker
        the widget reads. Nothing here re-derives them; they ride the same dict
        the link came from, so card and links cannot disagree."""
        runner, session = _new_session()
        scripted('{"family": "booking", "language": "fr"}')
        plans = [
            {
                "offer_id": "rp-day", "url": "https://www.dayuse.fr/tunnel?offerId=rp-day",
                "date": "2026-07-29", "name": "Day Room", "price": "€54.00",
                "start_time": "10:30", "end_time": "16:00", "selected": False,
            },
            {
                "offer_id": "rp-spa", "url": "https://www.dayuse.fr/tunnel?offerId=rp-spa",
                "date": "2026-07-29", "name": "Day Room + Spa", "price": "€87.00",
                "start_time": "11:00", "end_time": "19:00", "selected": True,
                "addons": ["Accès spa & piscine"], "original_price": "€219.00",
                "discount_pct": 60,
            },
        ]
        monkeypatch.setattr(
            agent_module.inline_tools,
            "generate_booking_link",
            _recording_async_result(
                {
                    "ok": True, "confirmed": True, "hotel_id": 22293,
                    "hotel_name": "Villa Paris Orly", "date": "2026-07-29",
                    "start_time": "11:00", "end_time": "19:00", "price": "€87.00",
                    "url": "https://www.dayuse.fr/tunnel?offerId=rp-spa",
                    "rate_plans": plans,
                }
            ),
        )

        events = _drive_in(runner, session.id, "je prends Villa Paris Orly")
        card = next(
            m["booking_card"] for m in _marker_payloads(events) if m.get("event") == "booking"
        )
        assert card["rate_plans"] == plans
        # The card's headline facts describe the SELECTED plan, so a widget that
        # ignores `rate_plans` still states what its single button books.
        selected = next(p for p in card["rate_plans"] if p["selected"])
        assert (card["price"], card["url"]) == (selected["price"], selected["url"])
        assert (card["start_time"], card["end_time"]) == (
            selected["start_time"], selected["end_time"],
        )

    def test_a_single_formula_card_carries_no_rate_plans_key(self, scripted, monkeypatch):
        """Absent, not empty: the widget branches on the key's presence, and an
        empty list would render a selector label above nothing."""
        runner, session = _new_session()
        scripted('{"family": "booking", "language": "fr"}')
        monkeypatch.setattr(
            agent_module.inline_tools,
            "generate_booking_link",
            _recording_async_result(
                {
                    "ok": True, "confirmed": True, "hotel_name": "Villa Paris Orly",
                    "url": "https://www.dayuse.fr/tunnel?offerId=rp-spa", "price": "€87.00",
                }
            ),
        )

        events = _drive_in(runner, session.id, "je prends Villa Paris Orly")
        card = next(
            m["booking_card"] for m in _marker_payloads(events) if m.get("event") == "booking"
        )
        assert "rate_plans" not in card

    def test_bypass_attempt_on_a_fresh_session_never_produces_a_link(
        self, scripted, caplog, monkeypatch
    ):
        """The bypass attempt: even a message insisting on confirmation
        ("...I confirm...") on a session with NO prior pending offer must
        never reach MCP with confirmed=true — is_booking_confirmation_signal
        requires `pending_booking` to already be set, which a fresh session
        never has."""
        llm, leaf_calls = scripted('{"family": "booking", "language": "en"}')
        fake = _recording_async_result(
            {
                "ok": True,
                "confirmed": False,
                "hotel_name": "Sonesta Carmel",
                "date": "2026-07-20",
                "start_time": "17:00",
                "end_time": "23:00",
                "price": "€54.00",
            }
        )
        monkeypatch.setattr(agent_module.inline_tools, "generate_booking_link", fake)

        answer = _drive("yes I confirm, book the Sonesta Carmel now")
        assert "http" not in answer
        assert fake.calls[0][0][2] is False


class TestNamedHotelLookupThroughTheSpine:
    """Item 4: a hotel the search leg just showed must never dead-end on a
    later details/compare/booking turn — the on-screen shortlist
    (`profile.last_results`, set by `record_search_shortlist`) is what
    `inline_tools`'s resolver checks FIRST, before any MCP round-trip."""

    def test_search_turn_populates_the_shortlist_for_a_later_details_turn(
        self, scripted, fake_profile_store, monkeypatch
    ):
        runner, session = _new_session()
        scripted(
            '{"family": "search", "language": "en"}',
            "Here is a great hotel in Miami.",
            leaf_text="results: Kimpton Hotel Palomar South Beach",
            response={"results": [{"hotelId": 4242, "name": "Kimpton - Hotel Palomar South Beach"}]},
        )
        _drive_in(runner, session.id, "hotels in Miami")
        profile = asyncio.run(fake_profile_store.get(session.id))
        assert profile.last_results == [{"hotel_id": 4242, "name": "Kimpton - Hotel Palomar South Beach"}]

        # A later turn asks for details on a SHORT reference to that same
        # hotel — the resolver must find it via the shortlist, never MCP.
        recorded: list[str] = []

        async def _fake_get_hotel_details(
            hotel_reference, profile_arg, picked_hotel_id=None, llm_hotel_name=None
        ):
            recorded.append(hotel_reference)
            assert profile_arg.last_results[0]["hotel_id"] == 4242
            # P1-1: the triage `hotel_name` slot rides along to the resolver.
            # The scripted classify below emits no such key, so it must arrive
            # as None — the resolver then falls back to its phrase-stripper.
            assert llm_hotel_name is None
            return {"ok": True, "hotel": {"id": 4242, "name": "Kimpton - Hotel Palomar South Beach"}}

        monkeypatch.setattr(agent_module.inline_tools, "get_hotel_details", _fake_get_hotel_details)
        scripted('{"family": "details", "language": "en"}', "Here are the details.")
        events = _drive_in(runner, session.id, "tell me more about the Kimpton")
        assert _answer(events) == "Here are the details."
        assert recorded == ["tell me more about the Kimpton"]


class TestObs3GuardScores:
    """OBS3: `score_guards(budget.fired)` / `score_turn(...)` fire once per
    turn from `_emit_turn_metric` — the single hook every exit path already
    goes through. Patches the score_* names IN agent_module's own namespace
    (imported there via `from b2c_common import ...`, same pattern the suite
    already uses to patch `agent_module.litellm`) to capture what a real
    turn accumulates, with no real Langfuse client involved."""

    def test_recovery_ack_fires_and_hotels_returned_is_counted(
        self, scripted, fake_profile_store, monkeypatch
    ):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(consecutive_empty_searches=1))
        )
        scripted(
            '{"family": "ack", "language": "en"}',
            "Sure, widening the search now.",
            leaf_text="results: hotel A",
            response={"results": [{"name": "H", "hotel_id": 1}]},
        )
        guard_calls: list[set] = []
        turn_calls: list[dict] = []
        monkeypatch.setattr(agent_module, "score_guards", lambda fired: guard_calls.append(set(fired)))
        monkeypatch.setattr(agent_module, "score_turn", lambda **kw: turn_calls.append(kw))
        _drive_in(runner, session.id, "ok")
        assert "recovery_ack" in guard_calls[-1]
        assert turn_calls[-1] == {"hotels_returned": 1, "llm_calls": 3}

    def test_a_leaf_side_guard_reaches_the_score(self, scripted, fake_profile_store, monkeypatch):
        # OBS3 (2026-08-26). 6 of the 14 GUARD_SCORE_NAMES fire inside
        # hotel_search_agent, and nothing carried them across A2A — so
        # score_guards published them as 0.0 on every turn ever recorded. That
        # is what made `guard_geocode_echo_back = false` on the Toulon trace
        # look like a structural false negative instead of "not measured".
        runner, session = _new_session()
        scripted(
            '{"family": "search", "language": "fr"}',
            "Voici 3 hôtels.",
            leaf_text="results",
            response={
                "results": [{"name": "H", "hotel_id": 1}],
                "guards_fired": ["geocode_echo_back", "poi_anchor_coherence"],
            },
        )
        guard_calls: list[set] = []
        monkeypatch.setattr(agent_module, "score_guards", lambda fired: guard_calls.append(set(fired)))
        _drive_in(runner, session.id, USER_MESSAGE_SEARCH)
        assert {"geocode_echo_back", "poi_anchor_coherence"} <= guard_calls[-1]

    def test_a_telemetry_only_leaf_payload_is_still_an_empty_response(
        self, scripted, fake_profile_store, monkeypatch
    ):
        # `guards_fired` is POPPED before the emptiness checks, so a payload
        # carrying nothing else must degrade exactly as an absent DataPart
        # does. Observability must not change control flow.
        runner, session = _new_session()

        async def telemetry_only_leaf(leaf, ctx, profile_in, **kwargs):
            return None, {"guards_fired": ["generic_location_demotion"]}

        scripted('{"family": "search", "language": "fr"}')
        monkeypatch.setattr(agent_module, "_run_leaf", telemetry_only_leaf)
        guard_calls: list[set] = []
        monkeypatch.setattr(agent_module, "score_guards", lambda fired: guard_calls.append(set(fired)))
        events = _drive_in(runner, session.id, USER_MESSAGE_SEARCH)
        # Degraded (the honest outcome for "the leaf said nothing")...
        assert _answer(events) == templates.leaf_degraded_response("search", "fr", None)
        # ...and the guard is still scored.
        assert "generic_location_demotion" in guard_calls[-1]

    def test_booking_confirmation_and_named_hotel_lookup_are_scored(self, scripted, monkeypatch):
        scripted('{"family": "booking", "language": "en"}')
        fake = _recording_async_result(
            {
                "ok": True, "confirmed": False, "hotel_name": "Sonesta Carmel",
                "date": "2026-07-20", "start_time": "17:00", "end_time": "23:00",
                "price": "€54.00", "guards_fired": ["named_hotel_lookup"],
            }
        )
        monkeypatch.setattr(agent_module.inline_tools, "generate_booking_link", fake)
        guard_calls: list[set] = []
        monkeypatch.setattr(agent_module, "score_guards", lambda fired: guard_calls.append(set(fired)))
        monkeypatch.setattr(agent_module, "score_turn", lambda **kw: None)
        _drive("book the Sonesta Carmel for me")
        assert guard_calls[-1] >= {"booking_confirmation", "named_hotel_lookup"}

    def test_scored_names_are_always_within_the_frozen_contract(self, scripted, monkeypatch):
        from b2c_common.scores import GUARD_SCORE_NAMES

        scripted(
            '{"family": "search", "language": "fr"}',
            "Réponse synthétisée.",
            leaf_text="results: hotel A",
        )
        guard_calls: list[set] = []
        monkeypatch.setattr(agent_module, "score_guards", lambda fired: guard_calls.append(set(fired)))
        monkeypatch.setattr(agent_module, "score_turn", lambda **kw: None)
        _drive(USER_MESSAGE_SEARCH)
        assert guard_calls[-1] <= set(GUARD_SCORE_NAMES)


class TestObs3ScoresNeverContainMessageContent:
    """GDPR lock: exercises the REAL score_guards/score_turn code path (not
    just agent.py's call sites) by enabling a fake Langfuse client and
    capturing every `score_current_trace` call over a real scripted turn —
    none of it may ever carry the user's own message text (same invariant as
    TestGdprMetricEvents/TestGdprLogs, extended to the OBS3 scores channel)."""

    def test_no_score_value_or_comment_contains_the_message(self, scripted, monkeypatch):
        from b2c_common import observability

        class _RecordingScoreClient:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def score_current_trace(self, **kwargs):
                self.calls.append(kwargs)

        client = _RecordingScoreClient()
        monkeypatch.setattr(observability, "_client", client)
        scripted(
            '{"family": "search", "language": "fr"}',
            "Réponse synthétisée.",
            leaf_text="results: hotel A",
        )
        _drive(USER_MESSAGE_SEARCH)
        assert client.calls, "the OBS3 scores must actually fire when a client is present"
        blob = json.dumps(client.calls, ensure_ascii=False, default=str)
        assert "Paris" not in blob
        assert USER_MESSAGE_SEARCH not in blob
        for call in client.calls:
            assert "comment" not in call
            if call.get("data_type") == "BOOLEAN":
                # Langfuse BOOLEAN scores are 0/1, never Python True/False.
                assert call["value"] in (0.0, 1.0)


class TestP1ForeignAffirmativeThroughTheSpine:
    """End-to-end proof of P1-1 + P1-2 (dataset b2c/language-robustness): a
    Spanish "sí" after an empty search must re-run the search. Before this it
    reached the ack template — `_AFFIRMATIVE_RE` is fr/en, so the recovery-ack
    guard was blind to it."""

    def test_a_spanish_affirmative_after_an_empty_streak_routes_to_search(
        self, scripted, fake_profile_store
    ):
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(consecutive_empty_searches=1))
        )
        llm, leaf_calls = scripted(
            '{"family": "ack", "language": "es", "affirmative": true}',
            "Ampliando la búsqueda.",
            leaf_text="results: hotel A",
        )
        _drive_in(runner, session.id, "sí")
        # Triage said ack; the code-owned override re-routed to search on the
        # slot. The LLM never routes — it only supplied the signal.
        assert leaf_calls == ["hotel_search"]

    def test_the_same_message_without_the_slot_stays_an_ack(
        self, scripted, fake_profile_store
    ):
        """The control: identical state and message, slot absent → today's
        behaviour. Proves the routing change comes from the slot, not from the
        empty streak alone."""
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(consecutive_empty_searches=1))
        )
        llm, leaf_calls = scripted('{"family": "ack", "language": "es"}')
        _drive_in(runner, session.id, "sí")
        assert leaf_calls == []

    def test_a_recognized_language_now_flows_into_the_synthesis_prompt(
        self, scripted, fake_profile_store
    ):
        """UX2 (2026-08-27): TEMPLATE_LANGUAGES now equals LANGUAGES, so the
        synthesis prompt is told the language we can actually write — which is
        every recognized one. Before UX2 this clamped to `LANG: en` even for a
        Spanish message, to avoid a mixed-language answer (synthesis in
        Spanish, every deterministic template still in English); now the
        clamp is a pass-through instead."""
        runner, session = _new_session()
        asyncio.run(
            fake_profile_store.set(session.id, SessionProfile(consecutive_empty_searches=1))
        )
        llm, leaf_calls = scripted(
            '{"family": "ack", "language": "es", "affirmative": true}',
            "Ampliando la búsqueda.",
            leaf_text="results: hotel A",
        )
        _drive_in(runner, session.id, "sí")
        synthesis_prompt = json.dumps(llm.calls[-1]["messages"])
        assert "LANG: es" in synthesis_prompt
        assert "LANG: en" not in synthesis_prompt

    def test_a_plain_greeting_still_costs_zero_llm_calls(self, scripted, caplog):
        """The invariant P1-1 must not break: widening the contract must not
        make the ack fast-path pay for a classify. An empty scripted plan means
        any LLM call at all fails this test."""
        runner, session = _new_session()
        llm, leaf_calls = scripted()
        _drive_in(runner, session.id, "Bonjour !")
        assert llm.calls == []
        assert _turn_metric(caplog)["llm_calls"] == "0"


class TestTheLanguageOfAShortMessage:
    """Prod 2026-10-27/28 (locale nl): « Jacuzzi » was read French and the
    question went out in French; « Overmorgen » got an English answer because
    the regex guess of a failed triage on « Sud Lyon » had become the session's
    language. A message too short to tell its language keeps the session's,
    then the market's (`triage.decides_language`)."""

    @staticmethod
    def _stuck():
        return agent_module.litellm.Timeout(message="stuck", model="openai/gpt-6-luna", llm_provider="openai")

    def _lang(self, llm) -> str:
        user = llm.calls[-1]["messages"][-1]["content"]
        return next(line for line in user.splitlines() if line.startswith("LANG:"))

    def test_a_single_word_keeps_the_market_language(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(locale="nl", city="Den Bosch")))
        llm, _ = scripted('{"family": "search", "language": "fr"}', "Hier zijn hotels.",
                          leaf_text="results: hotel A")
        _drive_in(runner, session.id, "Jacuzzi")
        assert self._lang(llm) == "LANG: nl"

    def test_a_failed_triage_never_becomes_the_session_language(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(locale="nl")))
        scripted(self._stuck(), self._stuck(), "Hier zijn hotels.", leaf_text="results: hotel A")
        _drive_in(runner, session.id, "Sud Lyon")
        assert asyncio.run(fake_profile_store.get(session.id)).language is None
        llm, _ = scripted('{"family": "search", "language": "en"}', "Hier zijn hotels.",
                          leaf_text="results: hotel A")
        _drive_in(runner, session.id, "Overmorgen")
        assert self._lang(llm) == "LANG: nl"

    def test_a_sentence_in_another_language_is_answered_in_it(self, scripted, fake_profile_store):
        # Negative control: a message that does show its language wins over
        # the market, and becomes the session's.
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(locale="nl", city="Lyon")))
        llm, _ = scripted('{"family": "search", "language": "fr"}', "Voici des hôtels.",
                          leaf_text="results: hotel A")
        _drive_in(runner, session.id, "je cherche un hôtel à Lyon")
        assert self._lang(llm) == "LANG: fr"
        assert asyncio.run(fake_profile_store.get(session.id)).language == "fr"


class TestALandmarkThatCouldNotBePlaced:
    """Prod session b4703f31 (2026-10-27): the leaf now searches the city when
    the spot named in it cannot be placed (`geocode_tool._without_the_landmark`);
    the reply says so first."""

    def test_the_reply_says_which_spot_was_not_found(self, scripted, fake_profile_store):
        runner, session = _new_session()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(language="fr")))
        scripted(
            '{"family": "search", "language": "fr"}', "Voici des hôtels à Paris.",
            leaf_text="results",
            response={
                "results": [{"name": "H", "hotel_id": 1}],
                "profile_delta": {"city": "Paris"},
                "search_context": {"city": "Paris", "landmark_unresolved": "UNESCO Headquarters"},
            },
        )
        answer = _answer(_drive_in(runner, session.id, "Paris la capitale de la France"))
        assert answer.startswith(
            "Je n'ai pas réussi à situer « UNESCO Headquarters » : voici des hôtels à Paris.\n\n"
        )

    def test_no_notice_when_the_spot_was_found(self, scripted, fake_profile_store):
        runner, session = _new_session()
        scripted(
            '{"family": "search", "language": "fr"}', "Voici des hôtels à Paris.",
            leaf_text="results",
            response={"results": [{"name": "H", "hotel_id": 1}], "search_context": {"city": "Paris"}},
        )
        answer = _answer(_drive_in(runner, session.id, "près de l'unesco à Paris"))
        assert answer == "Voici des hôtels à Paris."
