"""2026-10-28 (Victor) — the day is never asked in a message of its own.

Replaces the contract of 2026-10-20 (Fabien, PR #148: a dateless first search
asked « Which day would you like to book for? » alone, then the city on the
next turn). Prod 2026-10-27/28: 12 of the 13 conversations that ended on that
question had one turn; the entry chips (« With a jacuzzi », « Je veux un
après-midi spa ») fell from 82 % to 33 % of conversations with results.

New contract, over the REAL spine (only the A2A leg and the LLM scripted, same
seams as test_spine_profile.py):
- place missing → ONE question: the place and, while it is open, the day,
  with the day chips; a reply that gives only the place searches at once;
- place known, day missing → the search runs (today, or tomorrow past the
  same-day cutoff: the leaf's D+1 probe) and the SAME answer says which day,
  with the chips for the days after it;
- the day is asked once per session, and announced once.

2026-10-29 (prod after #173: 45 of 97 conversations opened on « Où et pour quel
jour ? », a day chip brought a bare « Dans quelle ville ? », 16 never saw a
hotel): the place question asks the PLACE only, restates the wish the triage
read, and offers « près de moi » and the market's cities as chips; the day is
never asked (it falls back on today, said with the hotels); an answer that
gives no place searches the market's main city (`default_place`), and asks
again once only where no market is known.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from b2c_concierge import templates
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.date_format import format_date_human
from b2c_concierge.profile import SessionProfile
from b2c_concierge.requested_date import parse_requested_date, reference_today
from b2c_concierge.triage import LANGUAGES

from .test_spine import _marker_payloads
from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

pytestmark = pytest.mark.date_unsettled

_TODAY = reference_today(None)
_TOMORROW = _TODAY + timedelta(days=1)
_REQUEST = "Find a room with a jacuzzi"
_SEARCH_EN = '{"family": "search", "language": "en"}'
_SEARCH_FR = '{"family": "search", "language": "fr"}'
_SEARCH_EN_WISH = '{"family": "search", "language": "en", "wish": "a room with a jacuzzi"}'
# The leaf's flag when the request names no place (`destination_missing`,
# response_bridge.emit_search_datapart).
_NO_PLACE = {"destination_missing": True}


def _results(day=_TODAY, city="Los Angeles", **search_date):
    return {
        "results": ["hotel A"],
        "profile_delta": {"city": city},
        "search_date": {"date": day.isoformat(), "same_day": day == _TODAY, **search_date},
    }


def _stored(store, session_id) -> SessionProfile:
    return asyncio.run(store.get(session_id))


def _context_text(parts) -> str:
    return parts[0].text if parts and parts[0].text else ""


class TestPlaceMissing:
    def test_one_question_asks_the_place_only_restating_the_wish_with_place_chips(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.text = "Which city?"
        fake_leg.response_payload = _NO_PLACE
        llm = _scripted_llm(monkeypatch, _SEARCH_EN_WISH)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(entry_market_country="US")))

        answer = _run_turn(runner, session.id, _REQUEST)

        question = "Sure — a room with a jacuzzi. Which city are you looking in?"
        assert answer == question
        assert "day" not in answer
        assert fake_leg.call_count == 1  # the leaf ran: no question before it
        assert len(llm.calls) == 1  # the triage only: the question is code-owned
        stored = _stored(fake_profile_store, session.id)
        assert stored.date_checked is False  # the day is not asked
        assert stored.last_suggestions == ["Near me", "New York", "Los Angeles", "Houston"]
        assert stored.last_clarifying_question == question
        assert stored.pending_search["request"] == _REQUEST
        assert stored.pending_search["place_question"] is True

    def test_without_a_wish_nor_a_market_the_question_is_the_bare_place_with_near_me(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _NO_PLACE
        _scripted_llm(monkeypatch, _SEARCH_EN)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        answer = _run_turn(runner, session.id, _REQUEST)

        assert answer == "Which city (or neighbourhood) are you looking in?"
        assert _stored(fake_profile_store, session.id).last_suggestions == ["Near me"]

    def test_a_wish_in_another_language_than_the_reply_is_not_quoted(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # A French session: an English wish would mix two languages.
        fake_leg.response_payload = _NO_PLACE
        _scripted_llm(monkeypatch, _SEARCH_EN_WISH)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(language="fr", locale="fr")))

        answer = _run_turn(runner, session.id, "Jacuzzi")

        assert answer == "Dans quelle ville (ou quel quartier) cherchez-vous ?"

    def test_the_analytics_facts_count_it_as_a_location_question(self, monkeypatch, fake_leg):  # noqa: F811
        fake_leg.response_payload = _NO_PLACE
        _scripted_llm(monkeypatch, _SEARCH_EN)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        async def go():
            content = genai_types.Content(role="user", parts=[genai_types.Part(text=_REQUEST)])
            return [e async for e in runner.run_async(user_id="u", session_id=session.id, new_message=content)]

        (facts,) = [p for p in _marker_payloads(asyncio.run(go())) if p["event"] == "turn_facts"]
        assert facts["route"] == "template:place_question"
        assert facts["response_type"] == "clarification"
        assert facts["clarification_reason"] == "location"

    def test_a_reply_with_only_the_place_searches_at_once_and_says_the_day(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        _scripted_llm(monkeypatch, _SEARCH_EN, _SEARCH_EN, "Here are hotels in Los Angeles.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        fake_leg.response_payload = _NO_PLACE
        _run_turn(runner, session.id, _REQUEST)

        fake_leg.response_payload = _results()
        answer = _run_turn(runner, session.id, "Los Angeles")

        assert fake_leg.call_count == 2
        # The request travels as the user's own words, with the reply.
        parts = fake_leg.seen_outgoing_parts
        assert _context_text(parts) == _REQUEST
        assert parts[1].text == "Los Angeles"
        notice = templates.date_retained_notice(
            format_date_human(_TODAY.isoformat(), "en"), "en", with_chips=True
        )
        assert answer == f"Here are hotels in Los Angeles.\n\n{notice}"
        assert _stored(fake_profile_store, session.id).last_suggestions == templates.later_date_chips("en", 0)

    def test_a_reply_with_the_place_and_the_day_searches_that_day_without_a_notice(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        _scripted_llm(monkeypatch, _SEARCH_EN, _SEARCH_EN, "Here are hotels for tomorrow.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        fake_leg.response_payload = _NO_PLACE
        _run_turn(runner, session.id, _REQUEST)

        fake_leg.response_payload = _results(_TOMORROW)
        answer = _run_turn(runner, session.id, "Los Angeles, tomorrow")

        assert answer == "Here are hotels for tomorrow."
        stored = _stored(fake_profile_store, session.id)
        assert stored.date == _TOMORROW.isoformat()
        assert stored.last_suggestions is None

    def test_a_reply_with_only_the_day_searches_the_market_city_never_a_second_question(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _NO_PLACE
        _scripted_llm(monkeypatch, _SEARCH_EN, _SEARCH_EN, "Here are hotels in New York.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(entry_market_country="US")))

        _run_turn(runner, session.id, _REQUEST)
        fake_leg.response_payload = {
            **_results(_TOMORROW, city="New York"),
            "search_context": {"city": "New York", "default_place": "New York"},
        }
        answer = _run_turn(runner, session.id, "Tomorrow")

        # The leaf was offered the market's main city, to search when — and
        # only when — the answer names no place.
        envelope = find_datapart(fake_leg.seen_outgoing_parts)
        assert envelope["query_params"]["default_place"] == {"city": "New York", "country_code": "US"}
        assert answer.startswith(templates.default_place_notice("New York", "en"))
        stored = _stored(fake_profile_store, session.id)
        assert stored.date == _TOMORROW.isoformat()

    def test_without_a_market_a_reply_with_only_the_day_asks_the_place_once_more(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _NO_PLACE
        _scripted_llm(monkeypatch, _SEARCH_EN, _SEARCH_EN)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, _REQUEST)
        answer = _run_turn(runner, session.id, "Tomorrow")

        assert answer == templates.place_question("en")
        envelope = find_datapart(fake_leg.seen_outgoing_parts)
        assert "default_place" not in (envelope.get("query_params") or {})
        stored = _stored(fake_profile_store, session.id)
        assert stored.date == _TOMORROW.isoformat()
        assert stored.last_suggestions == ["Near me"]

    def test_any_day_is_an_answer_the_day_question_never_comes_back(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # Prod session a1bb0e7f (Bilbao): « Da igual » twice, a question each time.
        fake_leg.response_payload = _NO_PLACE
        _scripted_llm(monkeypatch, _SEARCH_FR, _SEARCH_FR, _SEARCH_FR, "Voici des hôtels.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        assert _run_turn(runner, session.id, "un hôtel avec piscine") == templates.place_question("fr")
        assert _run_turn(runner, session.id, "peu importe") == templates.place_question("fr")
        fake_leg.response_payload = _results(city="Nice")
        answer = _run_turn(runner, session.id, "Nice")

        assert "pour quel jour" not in answer
        assert fake_leg.call_count == 3

    def test_the_leafs_own_place_question_asks_the_place_only_with_the_city_chips(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # A zone without its city (« gare de Lyon »): the leaf's template
        # question, about the place only (2026-10-29), its chips the market's.
        fake_leg.response_payload = {
            "requires_clarification": True,
            "clarification": {"kind": "city_needed", "subject": "gare de Lyon", "options": []},
        }
        _scripted_llm(monkeypatch, _SEARCH_FR)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(entry_market_country="FR")))

        answer = _run_turn(runner, session.id, "un hôtel près de la gare de Lyon")

        assert answer == "Près de « gare de Lyon », dans quelle ville cherchez-vous ?"
        stored = _stored(fake_profile_store, session.id)
        assert stored.last_suggestions == ["Près de moi", "Paris", "Lyon", "Bordeaux"]
        assert stored.date_checked is False

    def test_a_refused_device_location_is_said_before_the_question(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _NO_PLACE
        _scripted_llm(monkeypatch, _SEARCH_FR)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(device_location_refused=True)))

        answer = _run_turn(runner, session.id, "Chambre en journée près de moi")

        assert answer == (
            "Je n'ai pas accès à votre position. Dans quelle ville (ou quel quartier) cherchez-vous ?"
        )
        stored = _stored(fake_profile_store, session.id)
        assert stored.device_location_refused is False  # one-shot
        assert stored.last_suggestions is None  # no « près de moi » chip right after a refusal

    def test_without_the_leafs_flag_the_turn_is_served_as_before(
        self, monkeypatch, fake_leg  # noqa: F811
    ):
        # Contre-épreuve of the trigger: a leaf that searched nothing for
        # another reason (its honest diagnostic) keeps the synthesis.
        fake_leg.text = "The search could not run."
        fake_leg.response_payload = {}
        _scripted_llm(monkeypatch, _SEARCH_EN, "The search could not run this time.")
        runner = InMemoryRunner(root_agent)

        answer = _run_turn(runner, _new_session(runner).id, _REQUEST)

        assert answer == "The search could not run this time."


class TestPlaceKnown:
    def test_the_search_runs_at_once_and_the_answer_says_the_day_with_the_chips(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _results()
        llm = _scripted_llm(monkeypatch, _SEARCH_EN, "Here are rooftop pools in Los Angeles.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        answer = _run_turn(runner, session.id, "Rooftop pool in Los Angeles")

        assert fake_leg.call_count == 1
        assert len(llm.calls) == 2  # triage + synthesis: nothing more
        human = format_date_human(_TODAY.isoformat(), "en")
        assert answer == (
            "Here are rooftop pools in Los Angeles.\n\n"
            + templates.date_retained_notice(human, "en", with_chips=True)
        )
        stored = _stored(fake_profile_store, session.id)
        assert stored.last_suggestions == ["Tomorrow", "The day after tomorrow"]
        assert stored.date_announced is True
        assert stored.date_checked is False  # announced, never asked

    def test_past_the_same_day_cutoff_the_day_said_is_tomorrow(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _results(_TOMORROW, cutoff_fallback_from=_TODAY.isoformat())
        _scripted_llm(monkeypatch, _SEARCH_FR, "Les réservations du jour sont closes : voici demain.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        answer = _run_turn(runner, session.id, "un hôtel à Nice")

        assert format_date_human(_TOMORROW.isoformat(), "fr") in answer
        assert _stored(fake_profile_store, session.id).last_suggestions == ["Après-demain"]

    def test_the_day_is_announced_once_per_session(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _results(city="Nice")
        _scripted_llm(monkeypatch, _SEARCH_FR, "Voici Nice.", _SEARCH_FR, "Voici Cannes.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "un hôtel à Nice")
        fake_leg.response_payload = _results(city="Cannes")
        answer = _run_turn(runner, session.id, "et à Cannes ?")

        assert answer == "Voici Cannes."

    @pytest.mark.parametrize(
        "message",
        ["a hotel in Nice tomorrow", "un hôtel à Nice ce soir", "un hôtel à Nice le 3", "a hotel in Nice on Friday"],
    )
    def test_a_day_in_the_message_gets_no_notice(self, monkeypatch, fake_leg, message):  # noqa: F811
        fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": {"city": "Nice"}}
        _scripted_llm(monkeypatch, _SEARCH_EN, "Here are hotels.")
        runner = InMemoryRunner(root_agent)

        assert _run_turn(runner, _new_session(runner).id, message) == "Here are hotels."

    @pytest.mark.parametrize("day_stated, notice", [("true", False), ("false", True)])
    def test_the_triage_reads_a_day_the_regex_cannot(self, monkeypatch, fake_leg, day_stated, notice):  # noqa: F811
        # "maintenant" names today in no form `mentions_a_date` reads.
        fake_leg.response_payload = _results(city="Nice")
        _scripted_llm(
            monkeypatch, '{"family": "search", "language": "fr", "day_stated": %s}' % day_stated, "Voici.",
        )
        runner = InMemoryRunner(root_agent)

        answer = _run_turn(runner, _new_session(runner).id, "un hôtel à Nice maintenant")

        assert (answer != "Voici.") is notice

    def test_a_day_already_in_the_session_gets_no_notice(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        carried = _TODAY + timedelta(days=2)
        fake_leg.response_payload = _results(carried, city="Nice")
        _scripted_llm(monkeypatch, _SEARCH_EN, "Here are hotels.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(date=carried.isoformat())))

        assert _run_turn(runner, session.id, "a hotel in Nice") == "Here are hotels."

    def test_a_month_without_its_day_says_the_day_taken_without_chips(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # Prod: « Cualquier tarde a partir de las 16 mes de noviembre » stayed
        # on today. The leaf labels a month (`type: month`) and searches its
        # first day; the answer says so — the day chips (today, +1, +2) would
        # not be days of that month.
        first = _TODAY + timedelta(days=5)
        fake_leg.response_payload = {
            **_results(first, city="Barcelona"),
            "profile_delta": {
                "city": "Barcelona",
                "date": {"op": "set", "value": first.isoformat()},
                "date_reference": {"op": "set", "value": {"resolved_from": "month"}},
            },
        }
        _scripted_llm(monkeypatch, '{"family": "search", "language": "es"}', "Estas son las opciones.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        answer = _run_turn(runner, session.id, "cualquier tarde del mes que viene en Barcelona")

        human = format_date_human(first.isoformat(), "es")
        assert answer.endswith(templates.date_retained_notice(human, "es", with_chips=False))
        assert _stored(fake_profile_store, session.id).last_suggestions is None


class TestDayCorrections:
    def test_a_new_day_the_leaf_read_wins_over_the_carried_one(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # Prod session eaf1fad8 (Dublin): « Pick a date in 2 weeks » was
        # searched on Nov 10, then the date guard put Oct 29 back and said
        # « these offers are for Nov 10, not Oct 29 ».
        carried = _TODAY + timedelta(days=2)
        later = _TODAY + timedelta(days=14)
        fake_leg.response_payload = {
            "results": ["hotel A"],
            "profile_delta": {"date": {"op": "set", "value": later.isoformat()}},
            "search_date": {"date": later.isoformat(), "same_day": False},
        }
        _scripted_llm(monkeypatch, _SEARCH_EN, "Here are hotels in two weeks.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(
            session.id, SessionProfile(city="Dublin", date=carried.isoformat(), date_announced=True),
        ))

        answer = _run_turn(runner, session.id, "Pick a date in 2 weeks")

        assert answer == "Here are hotels in two weeks."
        assert _stored(fake_profile_store, session.id).date == later.isoformat()

    def test_a_cheaper_request_with_nothing_on_screen_searches_instead_of_asking(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # Prod session a1bb0e7f (Bilbao): « Pasado mañana » triaged `lower`
        # with nothing on screen asked « no verified total to compare » twice.
        fake_leg.response_payload = _results(_TODAY + timedelta(days=2), city="Bilbao")
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "es", "price_comparison": '
            '{"value": "lower", "evidence": "Pasado mañana"}}',
            "Estas son las opciones en Bilbao.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Bilbao")))

        answer = _run_turn(runner, session.id, "Pasado mañana")

        assert fake_leg.call_count == 1
        assert answer == "Estas son las opciones en Bilbao."


class TestTemplates:
    @pytest.mark.parametrize("language", LANGUAGES)
    def test_each_chip_is_a_day_the_reply_parser_reads(self, language):
        days = [parse_requested_date(chip, _TODAY) for chip in templates.date_chips(language)]
        assert days == [_TODAY + timedelta(days=n) for n in range(3)]

    def test_the_questions_are_translated_and_fall_back_to_english(self):
        for ask_day in (True, False):
            questions = {templates.place_question(lang, ask_day=ask_day) for lang in LANGUAGES}
            assert len(questions) == len(LANGUAGES)
            assert templates.place_question("xx", ask_day=ask_day) == templates.place_question(
                "en", ask_day=ask_day
            )
        assert templates.date_chips("xx") == templates.date_chips("en")

    def test_the_chips_after_the_day_searched(self):
        assert templates.later_date_chips("en", 0) == ["Tomorrow", "The day after tomorrow"]
        assert templates.later_date_chips("en", 1) == ["The day after tomorrow"]
        assert templates.later_date_chips("en", 5) == []
