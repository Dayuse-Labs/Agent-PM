"""QA 2026-10-20 (Fabien): a hotel search that names no day asks for one,
once per session, before the first search — over the REAL spine, with only
the A2A leg and the LLM scripted (same seams as test_spine_profile.py).

Trace d327c03d: « Rooftop pool in Los Angeles » searched today, unasked.

Prod session 7e296e4b (2026-10-27): a request that names no place either
(`place_check`, the turn's second LLM call) is asked the day and the place at
once. Every script below that reaches the question answers that call too.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import litellm
import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

import b2c_concierge.agent as agent_module
import b2c_concierge.place_check as place_check_module
from b2c_concierge import templates
from b2c_concierge.budget import MAX_LLM_CALLS_PER_TURN
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import SessionProfile
from b2c_concierge.profile_store import ProfileStore
from b2c_concierge.requested_date import parse_requested_date, reference_today
from b2c_concierge.triage import LANGUAGES

from .test_spine import _marker_payloads, _turn_metric
from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

pytestmark = pytest.mark.date_unsettled

_REQUEST = "Rooftop pool in Los Angeles"
_QUESTION = templates.date_question("en")
_SEARCH_EN = '{"family": "search", "language": "en"}'
_NAMES_A_PLACE = '{"names_a_place": true}'
_NO_PLACE = '{"names_a_place": false}'
_PLACE_QUESTION = templates.date_place_question("en")
_RESULTS = {"results": ["hotel A"], "profile_delta": {"city": "Los Angeles"}}


def _context_text(parts) -> str:
    return parts[0].text if parts and parts[0].text else ""


def _stored(store, session_id) -> SessionProfile:
    return asyncio.run(store.get(session_id))


class TestTheQuestion:
    def test_a_dateless_first_search_asks_the_day_and_searches_nothing(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        llm = _scripted_llm(monkeypatch, _SEARCH_EN, _NAMES_A_PLACE)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        answer = _run_turn(runner, session.id, _REQUEST)

        assert answer == _QUESTION
        assert fake_leg.call_count == 0
        assert len(llm.calls) == 2  # the triage and the place check: no leaf, no synthesis
        stored = _stored(fake_profile_store, session.id)
        assert stored.date_checked is True
        assert stored.date is None
        assert stored.last_clarifying_question == _QUESTION
        assert stored.last_suggestions == templates.date_chips("en")
        assert stored.pending_search == {
            "request": _REQUEST, "question": _QUESTION, "asked": 1, "date_question": True,
        }

    def test_the_analytics_facts_count_it_as_a_question(self, monkeypatch, fake_leg):  # noqa: F811
        _scripted_llm(monkeypatch, _SEARCH_EN, _NAMES_A_PLACE)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        async def go():
            content = genai_types.Content(role="user", parts=[genai_types.Part(text=_REQUEST)])
            return [e async for e in runner.run_async(user_id="u", session_id=session.id, new_message=content)]

        (facts,) = [p for p in _marker_payloads(asyncio.run(go())) if p["event"] == "turn_facts"]
        assert facts["route"] == "template:date_question"
        assert facts["response_type"] == "clarification"
        assert facts["clarification_reason"] == "other"
        assert facts["results_count"] == 0

    def test_the_reply_searches_that_day_with_the_request_it_completes(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        _scripted_llm(monkeypatch, _SEARCH_EN, _NAMES_A_PLACE, _SEARCH_EN, "Here are hotels for tomorrow.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, _REQUEST)
        fake_leg.response_payload = _RESULTS
        _run_turn(runner, session.id, "Tomorrow")

        assert fake_leg.call_count == 1
        parts = fake_leg.seen_outgoing_parts
        # The request alone, unlabelled: the day is already read (profile_in).
        assert _context_text(parts) == _REQUEST
        assert parts[1].text == "Tomorrow"
        stored = _stored(fake_profile_store, session.id)
        assert stored.date == (reference_today(None) + timedelta(days=1)).isoformat()
        assert stored.pending_search is None or "date_question" not in stored.pending_search

    def test_a_reply_naming_no_day_searches_and_the_question_never_comes_back(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}', _NAMES_A_PLACE,
            '{"family": "search", "language": "fr"}', "Voici des hôtels.",
            '{"family": "search", "language": "fr"}', "Voici des hôtels à Lyon.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        assert _run_turn(runner, session.id, "un hôtel avec piscine à Nice") == templates.date_question("fr")
        fake_leg.response_payload = _RESULTS
        _run_turn(runner, session.id, "peu importe")
        _run_turn(runner, session.id, "et à Lyon ?")

        assert fake_leg.call_count == 2

    def test_the_day_chips_do_not_outlive_the_turn_that_answers(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.text = "Free cancellation up to the start of the slot."
        fake_leg.response_payload = {}
        _scripted_llm(
            monkeypatch, _SEARCH_EN, _NAMES_A_PLACE,
            '{"family": "faq", "language": "en"}', "You can cancel for free.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, _REQUEST)
        _run_turn(runner, session.id, "Can I cancel for free?")

        assert _stored(fake_profile_store, session.id).last_suggestions is None


class TestNoQuestion:
    @pytest.mark.parametrize(
        "message",
        ["a hotel in Nice tomorrow", "un hôtel à Nice ce soir", "un hôtel à Nice le 3", "a hotel in Nice on Friday"],
    )
    def test_a_day_in_the_message_searches_at_once(self, monkeypatch, fake_leg, message):  # noqa: F811
        fake_leg.response_payload = _RESULTS
        _scripted_llm(monkeypatch, _SEARCH_EN, "Here are hotels.")
        runner = InMemoryRunner(root_agent)

        _run_turn(runner, _new_session(runner).id, message)

        assert fake_leg.call_count == 1

    @pytest.mark.parametrize("day_stated, searched", [("true", 1), ("false", 0)])
    def test_the_triage_reads_a_day_the_regex_cannot(self, monkeypatch, fake_leg, day_stated, searched):  # noqa: F811
        # "maintenant" names today in no form `mentions_a_date` reads: only the
        # triage slot spares the question, and it never adds one.
        fake_leg.response_payload = _RESULTS
        _scripted_llm(
            monkeypatch, '{"family": "search", "language": "fr", "day_stated": %s}' % day_stated,
            "Voici." if searched else _NAMES_A_PLACE,
        )
        runner = InMemoryRunner(root_agent)

        _run_turn(runner, _new_session(runner).id, "un hôtel à Nice maintenant")

        assert fake_leg.call_count == searched

    def test_a_day_already_in_the_session_is_not_asked_again(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _RESULTS
        _scripted_llm(monkeypatch, _SEARCH_EN, "Here are hotels.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        carried = (reference_today(None) + timedelta(days=2)).isoformat()
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(date=carried)))

        _run_turn(runner, session.id, "a hotel in Nice")

        assert fake_leg.call_count == 1

    def test_a_named_hotel_is_looked_up_without_asking(self, monkeypatch, fake_leg):  # noqa: F811
        fake_leg.response_payload = _RESULTS
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "hotel_name": "Pullman Paris Montparnasse"}',
            "Voici le Pullman.",
        )
        runner = InMemoryRunner(root_agent)

        _run_turn(runner, _new_session(runner).id, "je veux le Pullman Paris Montparnasse")

        assert fake_leg.call_count == 1

    def test_with_redis_down_the_search_runs_instead_of_asking(self, monkeypatch, fake_leg):  # noqa: F811
        # Every turn would start from an empty profile: the reply could never
        # find the request again, and the question would come back each turn.
        class _DeadClient:
            async def get(self, *a, **k):
                raise ConnectionError("redis unreachable")

            async def set(self, *a, **k):
                raise ConnectionError("redis unreachable")

            async def exists(self, *a, **k):
                raise ConnectionError("redis unreachable")

        monkeypatch.setattr(agent_module, "get_profile_store", lambda: ProfileStore(_DeadClient()))
        fake_leg.response_payload = _RESULTS
        _scripted_llm(monkeypatch, _SEARCH_EN, "Here are hotels.")
        runner = InMemoryRunner(root_agent)

        answer = _run_turn(runner, _new_session(runner).id, _REQUEST)

        assert fake_leg.call_count == 1
        assert answer == "Here are hotels."


class TestTheDayAndThePlace:
    """Prod session 7e296e4b: « i nedd room with hot tub in it » was asked the
    day, then the city, before anything was searched."""

    _NO_PLACE_REQUEST = "room with hot tub"

    def test_a_request_naming_no_place_asks_the_day_and_the_place(
        self, monkeypatch, fake_leg, fake_profile_store, caplog  # noqa: F811
    ):
        llm = _scripted_llm(monkeypatch, _SEARCH_EN, _NO_PLACE)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        with caplog.at_level("INFO", logger="b2c_concierge.metrics"):
            answer = _run_turn(runner, session.id, self._NO_PLACE_REQUEST)

        assert answer == _PLACE_QUESTION
        assert fake_leg.call_count == 0
        # The place check reads the request the reply will hand the leaf.
        assert self._NO_PLACE_REQUEST in llm.calls[1]["messages"][-1]["content"]
        metric = _turn_metric(caplog)
        assert metric["phases"] == "triage,place_check"
        assert int(metric["llm_calls"]) < MAX_LLM_CALLS_PER_TURN
        stored = _stored(fake_profile_store, session.id)
        assert stored.last_clarifying_question == _PLACE_QUESTION
        assert stored.last_suggestions is None  # a day chip would answer half of it
        assert stored.pending_search == {
            "request": self._NO_PLACE_REQUEST, "question": _PLACE_QUESTION, "asked": 1, "date_question": True,
        }

    def test_its_analytics_facts_call_it_a_location_question(self, monkeypatch, fake_leg):  # noqa: F811
        _scripted_llm(monkeypatch, _SEARCH_EN, _NO_PLACE)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        async def go():
            content = genai_types.Content(
                role="user", parts=[genai_types.Part(text=self._NO_PLACE_REQUEST)]
            )
            return [e async for e in runner.run_async(user_id="u", session_id=session.id, new_message=content)]

        (facts,) = [p for p in _marker_payloads(asyncio.run(go())) if p["event"] == "turn_facts"]
        assert facts["route"] == "template:date_place_question"
        assert facts["response_type"] == "clarification"
        assert facts["clarification_reason"] == "location"

    def test_a_request_naming_a_place_keeps_the_day_question(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        _scripted_llm(monkeypatch, _SEARCH_EN, _NAMES_A_PLACE)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        assert _run_turn(runner, session.id, "hot tub room in Paris") == _QUESTION
        assert _stored(fake_profile_store, session.id).last_suggestions == templates.date_chips("en")

    def test_a_place_the_session_knows_costs_no_check(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        llm = _scripted_llm(monkeypatch, _SEARCH_EN)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        gps = {"type": "device", "lat": 48.86, "lon": 2.35, "label": "device", "set_at_turn": 0}
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(search_anchor=gps)))

        assert _run_turn(runner, session.id, self._NO_PLACE_REQUEST) == _QUESTION
        assert len(llm.calls) == 1

    @pytest.mark.parametrize(
        "check_answer",
        ["timeout", '{"names_a_place": "no"}', "I think there is none"],
    )
    def test_a_check_that_cannot_say_keeps_the_day_question(
        self, monkeypatch, fake_leg, fake_profile_store, check_answer  # noqa: F811
    ):
        if check_answer == "timeout":
            check_answer = litellm.Timeout("timed out", model="openai/gpt-6-luna", llm_provider="openai")
        llm = _scripted_llm(monkeypatch, _SEARCH_EN, check_answer)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        assert _run_turn(runner, session.id, self._NO_PLACE_REQUEST) == _QUESTION
        assert len(llm.calls) == 2  # one attempt, never a retry
        assert _stored(fake_profile_store, session.id).last_suggestions == templates.date_chips("en")

    def test_the_reply_with_both_searches_the_request_there_that_day(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        _scripted_llm(monkeypatch, _SEARCH_EN, _NO_PLACE, _SEARCH_EN, "Here are hotels in Paris.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, self._NO_PLACE_REQUEST)
        fake_leg.response_payload = _RESULTS
        _run_turn(runner, session.id, "tomorrow in Paris")

        assert fake_leg.call_count == 1
        parts = fake_leg.seen_outgoing_parts
        assert _context_text(parts) == self._NO_PLACE_REQUEST
        assert parts[1].text == "tomorrow in Paris"
        stored = _stored(fake_profile_store, session.id)
        assert stored.date == (reference_today(None) + timedelta(days=1)).isoformat()

    def test_the_check_never_reports_the_request(self, monkeypatch, fake_leg, caplog):  # noqa: F811
        # GDPR: counters only in the metric rows, nothing of the request in the logs.
        events: list[dict] = []

        def capture(event_type, service, invocation_id, **fields):
            events.append({"event_type": event_type, **fields})

        monkeypatch.setattr(place_check_module, "enqueue_metric_event", capture)
        _scripted_llm(monkeypatch, _SEARCH_EN, RuntimeError("provider down"))
        runner = InMemoryRunner(root_agent)

        with caplog.at_level("DEBUG"):
            _run_turn(runner, _new_session(runner).id, self._NO_PLACE_REQUEST)

        assert [e["phase"] for e in events] == ["place_check"]
        blob = " ".join(
            [str(events)] + [r.getMessage() for r in caplog.records if r.name.startswith("b2c_concierge")]
        )
        assert "hot tub" not in blob


class TestTemplates:
    def test_the_day_and_place_question_is_translated_and_falls_back_to_english(self):
        questions = {templates.date_place_question(language) for language in LANGUAGES}
        assert len(questions) == len(LANGUAGES)
        assert not questions & {templates.date_question(language) for language in LANGUAGES}
        assert templates.date_place_question("xx") == _PLACE_QUESTION

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_each_chip_is_a_day_the_reply_parser_reads(self, language):
        today = reference_today(None)
        days = [parse_requested_date(chip, today) for chip in templates.date_chips(language)]
        assert days == [today + timedelta(days=n) for n in range(3)]

    def test_the_question_is_translated_and_falls_back_to_english(self):
        questions = {templates.date_question(language) for language in LANGUAGES}
        assert len(questions) == len(LANGUAGES)
        assert templates.date_question("xx") == _QUESTION
        assert templates.date_chips("xx") == templates.date_chips("en")
