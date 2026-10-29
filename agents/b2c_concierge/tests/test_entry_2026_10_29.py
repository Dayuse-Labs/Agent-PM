"""2026-10-29 — the entry without a place, and the answers that led nowhere.

Prod after #173 (97 real conversations, 28/10 17:19Z → 29/10 07:38Z):
- 45 opened on « Où et pour quel jour ? » with day chips only; a day clicked
  brought a bare « Dans quelle ville ? » (29 of the 34 next turns), and 16 of
  them never saw a hotel;
- the chip « Enjoy a romantic moment together » was triaged `ack` and answered
  by the greeting (2 conversations stopped there); « Sera » at turn 6 and
  « Sai leggere !!!! » at turn 5 got the same greeting;
- « How discreet is the booking? » (a dayuse.com chip) was answered and left
  there: 3 rebounds, where agent-usa asked « Sure — a discreet hotel. Which city
  are you looking in? » in 46 of 53 conversations.

Over the REAL spine (only the A2A leg and the LLM scripted, same seams as
test_spine_profile.py). The triage replies are the shape the prod triage
returned on those messages, with this branch's `wish` slot.
"""
from __future__ import annotations

import asyncio

from google.adk.runners import InMemoryRunner

from b2c_concierge import templates
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.market_cities import default_place, market_cities
from b2c_concierge.profile import SessionProfile

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

_NO_PLACE = {"destination_missing": True}
# Prod trace S074 (« Enjoy a romantic moment together », en/USD): the triage's
# own reply, family ack — plus the wish this branch asks for.
_ROMANTIC_ACK = (
    '{"family": "ack", "language": "en", "pick": "none", "pick_position": null, '
    '"affirmative": false, "day_stated": false, "answers_pending": "no", '
    '"wish": "a romantic moment for two"}'
)
# Prod trace S036/S071 (« How discreet is the booking? »): faq.
_DISCREET_FAQ = (
    '{"family": "faq", "language": "en", "pick": "none", "affirmative": false, '
    '"answers_pending": "no", "wish": "a discreet hotel"}'
)
_FAQ_ANSWER = (
    "Your booking is discreet: only your first and last name are shared with the hotel. "
    "Anything else you'd like to know?"
)


def _stored(store, session_id) -> SessionProfile:
    return asyncio.run(store.get(session_id))


def _seed(store, session_id, **fields) -> None:
    asyncio.run(store.set(session_id, SessionProfile(**fields)))


class TestMarketCities:
    def test_the_chips_are_the_markets_largest_cities_and_unknown_markets_have_none(self):
        assert market_cities("FR") == ["Paris", "Lyon", "Bordeaux"]
        assert market_cities("us") == ["New York", "Los Angeles", "Houston"]
        assert market_cities("ZZ") == [] and market_cities(None) == []
        assert default_place("IT") == {"city": "Roma", "country_code": "IT"}
        assert default_place("ZZ") is None

    def test_near_me_comes_first_and_is_left_out_after_a_refusal(self):
        assert templates.place_chips("de", ["Frankfurt"]) == ["In meiner Nähe", "Frankfurt"]
        assert templates.place_chips("de", ["Frankfurt"], near_me=False) == ["Frankfurt"]

    def test_the_wish_is_quoted_in_every_language(self):
        for language in ("fr", "en", "es", "it", "de", "pt", "nl"):
            question = templates.place_question(language, wish="WISH")
            assert "WISH" in question and question.endswith("?")
            assert templates.place_question(language) != question


class TestAWishWithoutAPlace:
    def test_a_wish_triaged_ack_on_the_first_turn_is_searched_and_its_place_asked(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _NO_PLACE
        _scripted_llm(monkeypatch, _ROMANTIC_ACK)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(fake_profile_store, session.id, entry_market_country="US")

        answer = _run_turn(runner, session.id, "Enjoy a romantic moment together")

        assert answer == "Sure — a romantic moment for two. Which city are you looking in?"
        assert fake_leg.call_count == 1  # the search leaf ran, never the greeting
        stored = _stored(fake_profile_store, session.id)
        assert stored.last_suggestions == ["Near me", "New York", "Los Angeles", "Houston"]
        assert stored.pending_search["place_question"] is True

    def test_the_answer_to_it_searches_with_the_wish_and_says_the_day(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _NO_PLACE
        _scripted_llm(
            monkeypatch, _ROMANTIC_ACK, '{"family": "search", "language": "en"}', "Here are hotels."
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _run_turn(runner, session.id, "Enjoy a romantic moment together")

        fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": {"city": "Chicago"}}
        _run_turn(runner, session.id, "Chicago")

        parts = fake_leg.seen_outgoing_parts
        # The wish travels with the reply, as the user's own words.
        assert parts[0].text == "Enjoy a romantic moment together"
        assert parts[1].text == "Chicago"


class TestNoGreetingPastTheFirstTurn:
    def test_a_social_message_after_a_search_is_not_the_opening_greeting(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": {"city": "Milano"}}
        _scripted_llm(monkeypatch, '{"family": "search", "language": "it"}', "Ecco gli hotel.",
                      '{"family": "ack", "language": "it"}')
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _run_turn(runner, session.id, "un hotel a Milano domani")

        # Prod S039 T6 / S041 T5 got « Ciao! Sono il concierge Dayuse… ».
        answer = _run_turn(runner, session.id, "Sai leggere !!!!")

        assert answer == templates.ack_followup_response("it")
        assert answer != templates.ack_response("it")

    def test_a_thank_you_on_the_regex_fast_path_after_the_first_turn_too(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": {"city": "Paris"}}
        _scripted_llm(monkeypatch, '{"family": "search", "language": "fr"}', "Voici des hôtels.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(fake_profile_store, session.id, locale="fr")
        _run_turn(runner, session.id, "un hôtel à Paris demain")

        assert _run_turn(runner, session.id, "merci") == templates.ack_followup_response("fr")

    def test_the_first_turn_greeting_is_unchanged(self, monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
        _scripted_llm(monkeypatch)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(fake_profile_store, session.id, locale="fr")

        assert _run_turn(runner, session.id, "Bonjour") == templates.ack_response("fr")
        assert fake_leg.call_count == 0


class TestAChipFaqLeadsToTheSearch:
    def test_a_dayuse_box_faq_is_answered_then_the_place_is_asked_with_its_chips(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.text = "Only your first and last name are shared with the hotel."
        fake_leg.response_payload = {}
        llm = _scripted_llm(monkeypatch, _DISCREET_FAQ, _FAQ_ANSWER)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(fake_profile_store, session.id, locale="en", entry_market_country="GB", entry_source="dayuse_box")

        answer = _run_turn(runner, session.id, "How discreet is the booking?")

        question = "Sure — a discreet hotel. Which city are you looking in?"
        # The FAQ answer, without its own question, then the place question.
        assert answer.endswith(f"\n\n{question}")
        assert "Anything else" not in answer
        assert "appends its own question about the city" in llm.calls[1]["messages"][1]["content"]
        stored = _stored(fake_profile_store, session.id)
        assert stored.last_suggestions == ["Near me", "London", "Manchester", "Birmingham"]
        assert stored.last_clarifying_question == question
        assert stored.pending_search["place_question"] is True
        assert stored.pending_search["request"] == "How discreet is the booking?"

    def test_the_city_then_searches_with_the_request(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.text = "Only your first and last name are shared with the hotel."
        fake_leg.response_payload = {}
        _scripted_llm(monkeypatch, _DISCREET_FAQ, _FAQ_ANSWER,
                      '{"family": "search", "language": "en", "answers_pending": "yes"}', "Here are hotels.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(fake_profile_store, session.id, locale="en", entry_source="dayuse_box")
        _run_turn(runner, session.id, "How discreet is the booking?")

        fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": {"city": "London"}}
        _run_turn(runner, session.id, "London")

        assert fake_leg.call_count == 2
        assert fake_leg.seen_outgoing_parts[0].text == "How discreet is the booking?"
        assert fake_leg.seen_outgoing_parts[1].text == "London"

    def test_a_support_question_on_the_site_is_answered_alone(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # No chip (no `source`), no wish read: an existing booking's question.
        fake_leg.text = "You can cancel from your confirmation email."
        fake_leg.response_payload = {}
        _scripted_llm(monkeypatch, '{"family": "faq", "language": "en", "wish": null}',
                      "You can cancel it from your confirmation email.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(fake_profile_store, session.id, locale="en", entry_market_country="US")

        answer = _run_turn(runner, session.id, "How do I cancel my booking?")

        assert answer == "You can cancel it from your confirmation email."
        stored = _stored(fake_profile_store, session.id)
        assert stored.last_suggestions is None and stored.pending_search is None


class TestTheDayOnlyAnswer:
    def test_a_refused_position_never_falls_back_on_the_market_city(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # The visitor clicked « près de moi » and refused the position: they
        # asked for around them, not for Paris.
        fake_leg.response_payload = _NO_PLACE
        _scripted_llm(monkeypatch, '{"family": "search", "language": "fr"}',
                      '{"family": "search", "language": "fr"}')
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(fake_profile_store, session.id, locale="fr", entry_market_country="FR")
        _run_turn(runner, session.id, "un hôtel avec jacuzzi")
        profile = _stored(fake_profile_store, session.id)
        profile.device_location_refused = True
        asyncio.run(fake_profile_store.set(session.id, profile))

        answer = _run_turn(runner, session.id, "Près de moi")

        assert "default_place" not in (find_datapart(fake_leg.seen_outgoing_parts).get("query_params") or {})
        assert answer == templates.place_question("fr", location_refused=True)
        assert _stored(fake_profile_store, session.id).last_suggestions == ["Paris", "Lyon", "Bordeaux"]
