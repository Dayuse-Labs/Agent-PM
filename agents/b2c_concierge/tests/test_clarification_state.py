"""QA14707 (Q11): the question state is the code's, never a regex's.

Q11 removed the text readers of the clarification route:

* "YOU ASKED" no longer comes from `extract_final_question` (a regex over the
  synthesis's paraphrase): it is the leaf's own text, or the stored
  `Clarification`;
* the yes/no that answers a pending question is the triage's call
  (`affirmative`, `answers_pending`), not `is_bare_affirmative`;
* `pending_place` and `_extract_hotel_name_candidate` are gone.

These tests lock the state side of that change: the `asked` count, the turn
after a third ask, the details route, and a stored profile written by another
writer.
"""
from __future__ import annotations

import asyncio

import pytest
from google.adk.runners import InMemoryRunner

import b2c_concierge.agent as agent_module
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import SessionProfile

from .test_clarification_routing import (  # noqa: F401
    _CITY_NEEDED,
    _SEARCH_RESULTS,
    _seed,
    mcp_calls,
)
from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

_SEARCH = '{"family": "search", "language": "fr"}'
_REQUEST = "un hôtel près de la gare du Nord demain de 14h à 18h"


def _stored(store, session_id) -> SessionProfile:
    return asyncio.run(store.get(session_id))


def _leaf_asks(fake_leg) -> None:  # noqa: F811
    fake_leg.response_payload = {
        "requires_clarification": True,
        "clarification": _CITY_NEEDED.model_dump(mode="json"),
    }


class TestAskedCountEndsWithTheAnswer:
    def test_a_search_answer_clears_the_state_so_the_same_question_restarts_at_1(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        _scripted_llm(
            monkeypatch,
            _SEARCH,
            '{"family": "search", "language": "fr", "answers_pending": "yes"}', "Voici des hôtels.",
            _SEARCH,
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _leaf_asks(fake_leg)
        _run_turn(runner, session.id, _REQUEST)
        assert _stored(fake_profile_store, session.id).pending_clarification["asked"] == 1

        fake_leg.response_payload = _SEARCH_RESULTS
        _run_turn(runner, session.id, "Paris")
        assert _stored(fake_profile_store, session.id).pending_clarification is None

        _leaf_asks(fake_leg)  # the same question, later
        _run_turn(runner, session.id, "un hôtel près de la gare du Nord")
        assert _stored(fake_profile_store, session.id).pending_clarification["asked"] == 1

    def test_the_same_question_in_a_row_keeps_counting(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        _scripted_llm(monkeypatch, _SEARCH, _SEARCH)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _leaf_asks(fake_leg)
        _run_turn(runner, session.id, _REQUEST)
        _run_turn(runner, session.id, "euh")
        assert _stored(fake_profile_store, session.id).pending_clarification["asked"] == 2


class TestTurnAfterTheThirdAsk:
    @staticmethod
    def _three_asks(monkeypatch, fake_leg, fake_profile_store, *tail):  # noqa: F811
        _scripted_llm(monkeypatch, _SEARCH, _SEARCH, _SEARCH, *tail)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _leaf_asks(fake_leg)
        for message in (_REQUEST, "euh", "je ne sais pas"):
            _run_turn(runner, session.id, message)
        stored = _stored(fake_profile_store, session.id)
        assert stored.pending_clarification["asked"] == 3
        assert stored.last_clarifying_question is None  # the third reply asked nothing
        return runner, session

    def test_a_city_reply_searches_with_the_pending_request(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        runner, session = self._three_asks(
            monkeypatch, fake_leg, fake_profile_store, _SEARCH, "Voici des hôtels à Paris."
        )
        fake_leg.response_payload = _SEARCH_RESULTS
        calls_before = fake_leg.call_count
        _run_turn(runner, session.id, "Paris")

        assert fake_leg.call_count == calls_before + 1
        context = fake_leg.seen_outgoing_parts[0].text
        assert context.startswith("EARLIER REQUEST")
        assert _REQUEST in context  # the date and the slot are not lost
        assert fake_leg.seen_outgoing_parts[1].text == "Paris"
        assert _stored(fake_profile_store, session.id).pending_clarification is None

    def test_a_booking_shaped_triage_with_no_pending_offer_books_and_looks_up_nothing(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls  # noqa: F811
    ):
        runner, session = self._three_asks(
            monkeypatch, fake_leg, fake_profile_store,
            '{"family": "booking", "language": "fr", "booking_confirmation": "confirm"}',
            "Voici des hôtels.",
        )
        fake_leg.response_payload = _SEARCH_RESULTS
        calls_before = fake_leg.call_count
        _run_turn(runner, session.id, "Je confirme")

        called = {name for name, _ in mcp_calls}
        assert "generate_booking_link" not in called
        assert "find_hotel_by_name" not in called
        assert fake_leg.call_count == calls_before + 1  # it went back to the search
        assert _REQUEST in fake_leg.seen_outgoing_parts[0].text


class TestNoWordListDecidesTheAnswer:
    """`is_bare_affirmative` no longer decides whether a message answers the
    pending question: the triage's closed slots do."""

    def test_an_affirmative_the_triage_reads_answers_the_pending_question(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        def refuse(*_args, **_kwargs):
            raise AssertionError("is_bare_affirmative read on the pending-question path")

        monkeypatch.setattr(agent_module, "is_bare_affirmative", refuse)
        _scripted_llm(
            monkeypatch,
            '{"family": "ack", "language": "fr", "affirmative": true}', "Voici plus près.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(
            fake_profile_store, session.id,
            pending_search={"request": None, "question": "Voulez-vous plus près du centre ?"},
            last_clarifying_question="Voulez-vous plus près du centre ?",
        )
        fake_leg.response_payload = _SEARCH_RESULTS
        answer = _run_turn(runner, session.id, "oui")

        assert answer == "Voici plus près."
        assert fake_leg.call_count == 1
        assert fake_leg.seen_outgoing_parts[0].text == (
            "YOU ASKED: Voulez-vous plus près du centre ?\nREPLY:"
        )

    def test_a_word_the_triage_does_not_read_as_an_answer_is_not_one(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        _scripted_llm(monkeypatch, '{"family": "ack", "language": "fr"}')
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(
            fake_profile_store, session.id,
            pending_search={"request": None, "question": "Voulez-vous plus près du centre ?"},
            last_clarifying_question="Voulez-vous plus près du centre ?",
        )
        _run_turn(runner, session.id, "oui")
        assert fake_leg.call_count == 0  # an ack, whatever the word
        assert _stored(fake_profile_store, session.id).pending_search is None


class TestDetailsRouteNeverSendsTheRawMessage:
    def test_no_hotel_name_from_the_triage_means_no_find_hotel_by_name(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls  # noqa: F811
    ):
        _scripted_llm(
            monkeypatch,
            '{"family": "details", "language": "fr"}', "Je ne trouve pas cet hôtel.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(fake_profile_store, session.id, city="Paris")
        message = "montre-moi la fiche du Moxy Chelsea"
        _run_turn(runner, session.id, message)

        sent = [arguments for name, arguments in mcp_calls if name == "find_hotel_by_name"]
        assert sent == []
        assert all(message not in str(arguments.values()) for _, arguments in mcp_calls)

    def test_the_triage_name_is_what_find_hotel_by_name_receives(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls  # noqa: F811
    ):
        _scripted_llm(
            monkeypatch,
            '{"family": "details", "language": "fr", "hotel_name": "Moxy Chelsea"}',
            "Voici la fiche.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _seed(fake_profile_store, session.id, city="Paris")
        _run_turn(runner, session.id, "montre-moi la fiche du Moxy Chelsea")

        sent = [arguments for name, arguments in mcp_calls if name == "find_hotel_by_name"]
        assert [arguments["name"] for arguments in sent] == ["Moxy Chelsea"]


class TestMalformedStoredRegionAnchor:
    """A profile written by another writer: `region_anchor` is a str | None,
    but Redis holds whatever was written."""

    @pytest.mark.parametrize("region", [12, {"op": "clear"}, ["Texas"], True])
    def test_it_loads_the_leaf_call_goes_out_and_no_region_is_chosen(
        self, monkeypatch, fake_leg, fake_profile_store, region  # noqa: F811
    ):
        from hotel_search_agent.geocode_tool import _fill_place_from_profile

        data = SessionProfile(city="Springfield", country_anchor="US").to_dict()
        data["region_anchor"] = region
        loaded = SessionProfile.from_dict(data)  # does not raise
        assert loaded.region_anchor == region

        _scripted_llm(monkeypatch, _SEARCH, "Voici des hôtels.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, loaded))
        fake_leg.response_payload = _SEARCH_RESULTS
        _run_turn(runner, session.id, "des hôtels à Springfield")

        assert fake_leg.call_count == 1  # the leaf call went out
        profile_in = find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]
        args = {"city": "Springfield"}
        _fill_place_from_profile(args, profile_in)  # does not raise
        assert "region_chosen" not in args
