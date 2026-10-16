"""QA14707 (Q05): the answer to a place question goes before the booking.

Trace C2 (session 8a79b460…): after « dans quelle ville ? », the user wrote
« Je confirme ». The triage read `{"family": "booking", "booking_confirmation":
"confirm"}`, the spine took the booking route, `generate_booking_link` found no
offer and asked `find_hotel_by_name("Je confirme")`, and the turn ended on the
"no list" template — the request (date, slot) was lost.

The fix is a routing priority read from the STATE, not from the words: with a
place question pending (`profile.pending_clarification`, Q04), the triage's
closed slot `answers_pending` sends the turn back to the search, ahead of every
pick, ordinal and booking reading. Only a real booking signal — an offer
pending, R9 — goes first. An option chosen by its number resolves its city in
code, from the options the geocoder returned.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import pytest
from google.adk.runners import InMemoryRunner

import b2c_concierge.agent as agent_module
import b2c_concierge.triage as triage_module
from b2c_common.clarification import Clarification
from b2c_concierge import templates
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.budget import MAX_LLM_CALLS_PER_TURN, TurnBudget
from b2c_concierge.profile import SessionProfile, apply_profile_delta, chosen_clarification_option
from b2c_concierge.triage import ANSWERS_PENDING, classify

from .test_spine_profile import _llm_response, _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

_CITY_NEEDED = Clarification(kind="city_needed", subject="Gare du Nord")
_HOMONYM = Clarification.model_validate({
    "kind": "homonym",
    "subject": "Victoria",
    "options": [
        {"label": "Victoria (British Columbia, CA)", "city": "Victoria",
         "region": "British Columbia", "country_code": "CA"},
        {"label": "Victoria (Texas, US)", "city": "Victoria", "region": "Texas", "country_code": "US"},
    ],
})

# Trace C2's triage of « Je confirme », plus the new slot.
_C2_TRIAGE = (
    '{"family": "booking", "language": "fr", "booking_confirmation": "confirm",'
    ' "answers_pending": "yes"}'
)
_SEARCH_RESULTS = {"results": [{"hotel_id": 1, "name": "Hotel A"}], "profile_delta": {"city": "Paris"}}
_SHORTLIST = [
    {"hotel_id": 101, "name": "Villa Paris Orly"},
    {"hotel_id": 102, "name": "OKKO Hotels Paris Rueil"},
    {"hotel_id": 103, "name": "Eurohotel Créteil"},
]
_PENDING_OFFER = {
    "hotel_id": 101, "hotel_name": "Villa Paris Orly", "date": "2026-07-28",
    "rate_plan_uuid": "offer-villa", "start_time": "10:00", "end_time": "17:00", "price": "€54.00",
}


@pytest.fixture
def mcp_calls(monkeypatch) -> list[tuple[str, dict]]:
    """Every inline MCP call the concierge makes (no network)."""
    calls: list[tuple[str, dict]] = []

    class _Res:
        isError = False
        structuredContent = {"link": {"url": "https://www.dayuse.com/booking/offer-villa"}}
        content: list = []

    class _Session:
        async def call_tool(self, name, arguments, *, meta=None):
            calls.append((name, dict(arguments)))
            return _Res()

    @asynccontextmanager
    async def _session():
        yield _Session()

    monkeypatch.setattr(agent_module.inline_tools, "_mcp_session", _session)
    return calls


@pytest.fixture
def fired(monkeypatch) -> list[set[str]]:
    turns: list[set[str]] = []
    monkeypatch.setattr(agent_module, "score_guards", lambda names: turns.append(set(names)))
    return turns


def _turn_routes(caplog) -> list[str]:
    routes = []
    for record in caplog.records:
        message = record.getMessage()
        if "concierge_metric=turn" in message:
            routes.append(dict(kv.split("=", 1) for kv in message.split() if "=" in kv)["route"])
    return routes


def _seed(store, session_id: str, **fields) -> None:
    asyncio.run(store.set(session_id, SessionProfile(**fields)))


def _ask(runner, session, fake_leg, clarification: Clarification, message: str) -> str:  # noqa: F811
    """Turn 1: the leaf asks a place question instead of searching."""
    fake_leg.response_payload = {"requires_clarification": True,
                                 "clarification": clarification.model_dump(mode="json")}
    answer = _run_turn(runner, session.id, message)
    fake_leg.response_payload = _SEARCH_RESULTS
    return answer


class TestAnswerBeforeBooking:
    def test_je_confirme_answering_a_city_question_searches_and_books_nothing(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls, caplog  # noqa: F811
    ):
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            _C2_TRIAGE, "Voici des hôtels près de la gare du Nord.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            _ask(runner, session, fake_leg, _CITY_NEEDED, "un hôtel près de la gare du Nord demain à 14h")
            answer = _run_turn(runner, session.id, "Je confirme")

        assert fake_leg.call_count == 2  # the answer went back to the search leaf
        assert _turn_routes(caplog)[-1] == "leaf:hotel_search"
        called = {name for name, _ in mcp_calls}
        assert "generate_booking_link" not in called
        assert "find_hotel_by_name" not in called
        assert answer != templates.booking_needs_selection_response(None, "hotel not found", "fr")
        # The request the question interrupted reaches the leaf with the answer.
        context = fake_leg.seen_outgoing_parts[0].text
        assert "demain à 14h" in context and context.endswith("REPLY:")
        assert fake_leg.seen_outgoing_parts[1].text == "Je confirme"

    def test_a_booking_triage_with_nothing_to_book_answers_the_question(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls  # noqa: F811
    ):
        """R9, strengthened: even when the triage misses `answers_pending`, a
        booking needs an offer or a list on screen — with neither, the
        message answers the pending question."""
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            '{"family": "booking", "language": "fr", "booking_confirmation": "confirm"}',
            "Voici des hôtels.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _ask(runner, session, fake_leg, _CITY_NEEDED, "un hôtel près de la gare du Nord demain")
        _run_turn(runner, session.id, "Je confirme")

        assert fake_leg.call_count == 2
        assert mcp_calls == []

    def test_without_a_pending_question_the_no_list_template_is_unchanged(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls, caplog  # noqa: F811
    ):
        _scripted_llm(monkeypatch, _C2_TRIAGE)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _run_turn(runner, session.id, "Je confirme")

        assert answer == templates.booking_needs_selection_response(None, "hotel not found", "fr")
        assert _turn_routes(caplog) == ["inline:generate_booking_link"]
        assert fake_leg.call_count == 0
        # …and MCP is never asked for the raw message as a hotel name.
        assert "find_hotel_by_name" not in {name for name, _ in mcp_calls}

    @pytest.mark.parametrize("question_pending", [False, True])
    def test_a_pending_offer_keeps_je_confirme_a_booking_confirmation(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls, fired, question_pending  # noqa: F811
    ):
        """R9 (guard #12) unchanged: the one signal that goes before a pending
        question is an offer awaiting its confirmation."""
        _scripted_llm(monkeypatch, _C2_TRIAGE)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        pending = (
            {"clarification": _CITY_NEEDED.model_dump(mode="json"), "request": "demain", "asked": 1}
            if question_pending else None
        )
        _seed(fake_profile_store, session.id, last_results=_SHORTLIST,
              pending_booking=dict(_PENDING_OFFER), pending_clarification=pending)

        _run_turn(runner, session.id, "je confirme")

        assert fake_leg.call_count == 0
        link_calls = [args for name, args in mcp_calls if name == "generate_booking_link"]
        assert link_calls == [{
            "hotelId": 101, "date": "2026-07-28", "confirmed": True, "ratePlanUuid": "offer-villa",
        }]
        assert "booking_confirmation" in fired[-1]
        assert asyncio.run(fake_profile_store.get(session.id)).pending_booking is None


class TestChosenOption:
    @pytest.mark.parametrize(("index", "country"), [(2, "US"), (1, "CA")])
    def test_an_option_index_searches_the_city_of_that_option(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls, index, country  # noqa: F811
    ):
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}',
            '{"family": "search", "language": "en", "answers_pending": "yes",'
            f' "answer_option": {index}, "pick": "position", "pick_position": {index}}}',
            "Here are hotels in Victoria.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        # A shortlist from an earlier search is still on screen: a bare "2"
        # used to take the ordinal → booking branch.
        _seed(fake_profile_store, session.id, last_results=_SHORTLIST, city="Paris", zone="Opéra")

        _ask(runner, session, fake_leg, _HOMONYM, "a hotel in Victoria tomorrow")
        _run_turn(runner, session.id, str(index))

        assert fake_leg.call_count == 2
        assert mcp_calls == []  # no booking, no name lookup
        profile_in = find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]
        assert profile_in["city"] == "Victoria"
        assert profile_in["country_anchor"] == country
        assert profile_in["zone"] is None  # the old zone does not carry over

    def test_an_index_outside_the_options_resolves_nothing(self):
        pending = {"clarification": _HOMONYM.model_dump(mode="json")}
        assert chosen_clarification_option(pending, 3) is None
        assert chosen_clarification_option(pending, None) is None
        assert chosen_clarification_option(
            {"clarification": _CITY_NEEDED.model_dump(mode="json")}, 1
        ) is None
        assert chosen_clarification_option(pending, 2)["country_code"] == "US"


_SPRINGFIELD = Clarification.model_validate({
    "kind": "homonym",
    "subject": "Springfield",
    "options": [
        {"label": "Springfield (Illinois, United States)", "city": "Springfield",
         "region": "Illinois", "country_code": "US"},
        {"label": "Springfield (Missouri, United States)", "city": "Springfield",
         "region": "Missouri", "country_code": "US"},
    ],
})


class TestOptionsSharingCityAndCountry:
    """QA14707 (Q14): two options with the same `city` and `country_code`
    differ only by their region. The chosen option's region travels to the
    leaf as data (`profile_in.region_anchor`), taken from the stored
    `Clarification` — city and country alone re-geocode the same homonym."""

    def _answer(self, monkeypatch, fake_leg, store, index: int, message: str, *extra_llm):  # noqa: F811
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}',
            '{"family": "search", "language": "en", "answers_pending": "yes",'
            f' "answer_option": {index}}}',
            "Here are hotels in Springfield.",
            *extra_llm,
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _ask(runner, session, fake_leg, _SPRINGFIELD, "a hotel in Springfield tomorrow afternoon")
        fake_leg.response_payload = {"results": [{"hotel_id": 7, "name": "Hotel S"}],
                                     "profile_delta": {"city": "Springfield"}}
        _run_turn(runner, session.id, message)
        return runner, session

    @pytest.mark.parametrize(
        ("index", "message", "region"),
        [(2, "the second one", "Missouri"), (1, "1", "Illinois")],
    )
    def test_the_chosen_options_region_reaches_the_leaf_as_data(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls, index, message, region  # noqa: F811
    ):
        self._answer(monkeypatch, fake_leg, fake_profile_store, index, message)

        assert fake_leg.call_count == 2  # the leaf call is the turn's only search
        assert mcp_calls == []
        profile_in = find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]
        assert (profile_in["city"], profile_in["country_anchor"], profile_in["region_anchor"]) == (
            "Springfield", "US", region
        )
        # The user's words name no region: it comes from the stored question.
        assert fake_leg.seen_outgoing_parts[-2].text == message

    def test_the_region_stays_with_its_city_on_the_next_turn(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls  # noqa: F811
    ):
        runner, session = self._answer(
            monkeypatch, fake_leg, fake_profile_store, 2, "2",
            '{"family": "search", "language": "en"}', "Later ones in Springfield.",
        )

        _run_turn(runner, session.id, "something later in the evening")

        assert fake_leg.call_count == 3
        profile_in = find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]
        assert (profile_in["city"], profile_in["region_anchor"]) == ("Springfield", "Missouri")

    def test_a_city_change_clears_it_and_a_leaf_delta_never_sets_it(self):
        profile = SessionProfile(city="Springfield", country_anchor="US", region_anchor="Missouri")

        apply_profile_delta(profile, {"region_anchor": "Texas"}, "")
        assert profile.region_anchor == "Missouri"
        apply_profile_delta(profile, {"region_anchor": {"op": "clear"}}, "")
        assert profile.region_anchor == "Missouri"

        apply_profile_delta(profile, {"city": "Paris"}, "Paris")
        assert profile.region_anchor is None

    def test_a_city_typed_as_the_answer_sets_no_region(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls  # noqa: F811
    ):
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}',
            '{"family": "search", "language": "en", "answers_pending": "yes"}',
            "Here are hotels.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _ask(runner, session, fake_leg, _SPRINGFIELD, "a hotel in Springfield tomorrow")
        _run_turn(runner, session.id, "Missouri")

        assert find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]["region_anchor"] is None


class TestFastPath:
    @pytest.mark.parametrize("message", ["ok", "merci", "super"])
    def test_with_a_question_pending_the_ack_fast_path_never_applies(
        self, monkeypatch, fake_leg, fake_profile_store, caplog, message  # noqa: F811
    ):
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            '{"family": "ack", "language": "fr", "answers_pending": "no"}',
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _ask(runner, session, fake_leg, _CITY_NEEDED, "un hôtel près de la gare du Nord")
        _run_turn(runner, session.id, message)

        assert len(llm.calls) == 2  # turn 2 went through the triage
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.pending_clarification is None  # consumed by the turn


class TestTriageSlot:
    def _classify(self, monkeypatch, payload: str):
        async def fake_acompletion(**kwargs):
            return _llm_response(payload)

        monkeypatch.setattr(triage_module.litellm, "acompletion", fake_acompletion)
        return asyncio.run(classify("Je confirme", TurnBudget(), previous_question="Dans quelle ville ?"))

    def test_the_slot_is_a_closed_enum(self):
        assert ANSWERS_PENDING == ("yes", "no")

    def test_yes_and_the_option_are_carried_through(self, monkeypatch):
        t = self._classify(
            monkeypatch, '{"family": "search", "language": "fr", "answers_pending": "yes", "answer_option": 2}'
        )
        assert (t.answers_pending, t.answer_option) == ("yes", 2)

    @pytest.mark.parametrize("raw", ['"maybe"', '"YES"', "true", "1", "null", '["yes"]'])
    def test_a_value_outside_the_enum_falls_back_to_no(self, monkeypatch, raw):
        t = self._classify(
            monkeypatch,
            f'{{"family": "search", "language": "fr", "answers_pending": {raw}, "answer_option": 2}}',
        )
        assert t.answers_pending == "no"
        assert t.answer_option is None  # no option without an answer

    def test_an_absent_slot_is_no(self, monkeypatch):
        t = self._classify(monkeypatch, '{"family": "search", "language": "fr"}')
        assert (t.answers_pending, t.answer_option) == ("no", None)

    @pytest.mark.parametrize("raw", ["0", "-1", "true", '"deux"'])
    def test_an_unusable_option_is_none(self, monkeypatch, raw):
        t = self._classify(
            monkeypatch, f'{{"family": "search", "language": "fr", "answers_pending": "yes", "answer_option": {raw}}}'
        )
        assert t.answers_pending == "yes" and t.answer_option is None

    def test_the_llm_being_down_is_no(self, monkeypatch):
        async def _boom(**kwargs):
            raise TimeoutError("down")

        monkeypatch.setattr(triage_module.litellm, "acompletion", _boom)
        t = asyncio.run(classify("Paris", TurnBudget()))
        assert t.used_llm is False and t.answers_pending == "no"


def test_the_llm_budget_per_turn_is_unchanged():
    assert MAX_LLM_CALLS_PER_TURN == 3
