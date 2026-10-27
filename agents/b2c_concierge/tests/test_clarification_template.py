"""QA14707 (Q04): the leaf's place question is answered by template, not synthesis.

Decision DQ2: when the search leaf sends up a `Clarification`, the reply is a
code template built from that object alone — no synthesis call, so no option
the geocoder did not return can reach the user (trace C1: the synthesis
invented « Bruxelles » and « Versailles (78) »). The state of the question
(`profile.pending_clarification`) carries the request not searched yet to the
next turn and drives the anti-loop: a repeat is reworded, a third one asks
nothing.

The rendering tests below are the EXACT, offline guarantee that the live
evaluator `clarify_options_from_geocoder` (Q01) can only approximate.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

import pytest
from google.adk.runners import InMemoryRunner

import b2c_concierge.agent as agent_module
from b2c_common.clarification import Clarification
from b2c_common.scores import GUARD_SCORE_NAMES
from b2c_concierge import templates
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import (
    SessionProfile,
    leaf_profile_view,
    next_pending_clarification,
    pending_clarification_context,
)
from b2c_concierge.triage import LANGUAGES

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

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
_OTHER_HOMONYM = Clarification.model_validate({
    "kind": "homonym",
    "subject": "Springfield",
    "options": [
        {"label": "Springfield (Illinois, US)", "city": "Springfield", "country_code": "US"},
        {"label": "Springfield (Missouri, US)", "city": "Springfield", "country_code": "US"},
        {"label": "Springfield (Oregon, US)", "city": "Springfield", "country_code": "US"},
    ],
})

_NUMBERED_LINE = re.compile(r"^\s*\d+[.)]\s+.*$", re.MULTILINE)


def _option_lines(text: str) -> list[str]:
    return [line.strip() for line in _NUMBERED_LINE.findall(text)]


def _wire(clarification: Clarification) -> dict:
    """The object as the leaf's DataPart carries it."""
    return clarification.model_dump(mode="json")


# --- Rendering (no LLM at all) ---------------------------------------------------------------


class TestRendering:
    @pytest.mark.parametrize("language", ["fr", "en"])
    def test_city_needed_names_its_subject_and_offers_no_numbered_option(self, language):
        text = templates.clarification_response(_CITY_NEEDED, language)

        assert "Gare du Nord" in text
        assert _option_lines(text) == []
        assert text.rstrip().endswith("?")

    @pytest.mark.parametrize("language", ["fr", "en"])
    def test_a_homonym_lists_exactly_its_options_numbered_in_order(self, language):
        text = templates.clarification_response(_HOMONYM, language)

        assert _option_lines(text) == [
            "1. Victoria (British Columbia, CA)",
            "2. Victoria (Texas, US)",
        ]
        assert "Victoria" in text.splitlines()[0]

    @pytest.mark.parametrize("asked", [1, 2, 3])
    @pytest.mark.parametrize("language", LANGUAGES)
    def test_no_word_of_a_reply_comes_from_outside_the_object(self, language, asked):
        """The structural form of "no invented option": two different
        questions of the same kind render to the SAME text once their subject
        and labels are masked. Whatever else the reply says is fixed template
        text, identical for every question — so it can name no place."""

        def masked(clarification: Clarification) -> str:
            text = templates.clarification_response(clarification, language, asked)
            for option in clarification.options:
                text = text.replace(option.label, "<OPTION>")
            return text.replace(clarification.subject, "<SUBJECT>")

        other_city_needed = Clarification(kind="city_needed", subject="Times Square")
        two_options = _OTHER_HOMONYM.model_copy(update={"options": _OTHER_HOMONYM.options[:2]})

        assert masked(_CITY_NEEDED) == masked(other_city_needed)
        assert masked(_HOMONYM) == masked(two_options)

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_every_option_line_is_one_label_of_the_object(self, language):
        for asked in (1, 2):
            text = templates.clarification_response(_OTHER_HOMONYM, language, asked)
            assert _option_lines(text) == [
                f"{n}. {o.label}" for n, o in enumerate(_OTHER_HOMONYM.options, start=1)
            ]

    @pytest.mark.parametrize("clarification", [_CITY_NEEDED, _HOMONYM])
    @pytest.mark.parametrize("language", LANGUAGES)
    def test_a_repeat_is_reworded_and_the_third_time_asks_nothing(self, clarification, language):
        first = templates.clarification_response(clarification, language, 1)
        second = templates.clarification_response(clarification, language, 2)
        third = templates.clarification_response(clarification, language, 3)

        assert len({first, second, third}) == 3
        assert clarification.subject in third
        assert "?" not in third
        assert _option_lines(third) == []

    def test_the_repeat_of_a_city_question_says_the_city_is_what_is_missing(self):
        text = templates.clarification_response(_CITY_NEEDED, "en", 2)
        assert "Gare du Nord" in text and "city" in text
        assert _option_lines(text) == []

    def test_an_unknown_language_falls_back_to_english(self):
        assert templates.clarification_response(_CITY_NEEDED, "xx") == (
            templates.clarification_response(_CITY_NEEDED, "en")
        )


# --- State (profile.pending_clarification) ---------------------------------------------------


class TestPendingClarification:
    def test_the_request_accumulates_like_pending_search(self):
        first = next_pending_clarification(None, "un hôtel près de la gare demain à 14h", _wire(_CITY_NEEDED))
        second = next_pending_clarification(first, "la gare", _wire(_CITY_NEEDED))

        assert first == {
            "clarification": _wire(_CITY_NEEDED),
            "request": "un hôtel près de la gare demain à 14h",
            "asked": 1,
        }
        assert second["request"] == "un hôtel près de la gare demain à 14h\nla gare"
        assert second["asked"] == 2

    def test_a_free_question_left_open_hands_its_request_over(self):
        earlier = {"request": "demain matin 7h", "question": "Où ?"}
        pending = next_pending_clarification(earlier, "près de la gare", _wire(_CITY_NEEDED))
        assert pending["request"] == "demain matin 7h\nprès de la gare"
        assert pending["asked"] == 1

    def test_another_question_starts_the_count_again(self):
        first = next_pending_clarification(None, "hotel in Victoria", _wire(_HOMONYM))
        assert next_pending_clarification(first, "Springfield", _wire(_OTHER_HOMONYM))["asked"] == 1
        city = next_pending_clarification(first, "near Victoria station", _wire(
            Clarification(kind="city_needed", subject="Victoria")
        ))
        assert city["asked"] == 1  # same subject, another kind: another question

    def test_the_same_subject_compares_without_case_or_spacing(self):
        first = next_pending_clarification(None, "x", _wire(_CITY_NEEDED))
        again = Clarification(kind="city_needed", subject="  gare du  nord ")
        assert next_pending_clarification(first, "y", _wire(again))["asked"] == 2

    def test_the_request_is_bounded(self):
        pending = next_pending_clarification(None, "x" * 900, _wire(_CITY_NEEDED))
        assert len(pending["request"]) == 500

    def test_the_context_carries_the_request_and_the_question_as_data(self):
        pending = next_pending_clarification(None, "un hôtel demain à 14h", _wire(_HOMONYM))
        text = pending_clarification_context(pending)

        lines = text.splitlines()
        assert lines[0] == "EARLIER REQUEST (the user's own words, not searched yet): un hôtel demain à 14h"
        assert lines[1].startswith("YOU ASKED: ")
        assert json.loads(lines[1][len("YOU ASKED: "):]) == _wire(_HOMONYM)
        assert lines[-1] == "REPLY:"
        assert pending_clarification_context(None) is None

    def test_the_slot_survives_redis_and_never_rides_profile_in(self):
        pending = next_pending_clarification(None, "un hôtel demain", _wire(_HOMONYM))
        profile = SessionProfile(pending_clarification=pending)

        assert SessionProfile.from_dict(profile.to_dict()).pending_clarification == pending
        assert "pending_clarification" not in leaf_profile_view(profile)


# --- Through the spine (real _run_leaf, faked A2A leg) ---------------------------------------

_INVENTED = "Bruxelles"  # what the synthesis made up on trace C1


def _clarify_payload(clarification: Clarification) -> dict:
    return {"requires_clarification": True, "clarification": _wire(clarification)}


def _turn_metric(caplog) -> dict:
    line = [r.getMessage() for r in caplog.records if "concierge_metric=turn" in r.getMessage()][-1]
    return dict(kv.split("=", 1) for kv in line.split() if "=" in kv)


@pytest.fixture
def fired(monkeypatch) -> list[set[str]]:
    """The guard set each turn scored (OBS3), in turn order."""
    turns: list[set[str]] = []
    monkeypatch.setattr(agent_module, "score_guards", lambda names: turns.append(set(names)))
    return turns


class TestThroughTheSpine:
    @pytest.mark.parametrize("language", ["fr", "en"])
    def test_a_clarification_turn_makes_no_synthesis_call(
        self, monkeypatch, fake_leg, fake_profile_store, caplog, language  # noqa: F811
    ):
        # The leaf's own text even carries an option the object does not: it
        # must not reach the user either.
        fake_leg.text = f"Near Gare du Nord — Paris or {_INVENTED}?"
        fake_leg.response_payload = _clarify_payload(_CITY_NEEDED)
        llm = _scripted_llm(monkeypatch, f'{{"family": "search", "language": "{language}"}}')
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _run_turn(runner, session.id, "un hôtel près de Gare du Nord demain à 14h")

        assert answer == templates.clarification_response(_CITY_NEEDED, language)
        assert _INVENTED not in answer
        assert len(llm.calls) == 1  # the triage only: no synthesis
        metric = _turn_metric(caplog)
        assert metric["llm_calls"] == "2"  # triage + the leaf's slot, one fewer than a search
        assert "synthesis" not in metric["phases"]
        assert metric["route"] == "template:clarification"
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.last_clarifying_question == answer  # the code's text, not a regex extract
        assert stored.pending_search is None

    def test_a_homonym_reply_offers_exactly_the_objects_options(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.text = "Did you mean Victoria (British Columbia, CA), Victoria (Texas, US) or Victoria (AU)?"
        fake_leg.response_payload = _clarify_payload(_HOMONYM)
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}')
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        answer = _run_turn(runner, session.id, "a hotel in Victoria tomorrow")

        assert _option_lines(answer) == ["1. Victoria (British Columbia, CA)", "2. Victoria (Texas, US)"]
        assert "AU" not in answer

    def test_the_next_turn_sends_the_request_the_question_and_the_answer(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _clarify_payload(_CITY_NEEDED)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            '{"family": "search", "language": "fr"}', "Voici des hôtels près de la gare du Nord.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "un hôtel près de la gare du Nord demain à 14h")
        fake_leg.response_payload = {"results": [{"hotel_id": 1, "name": "Hotel A"}],
                                     "profile_delta": {"city": "Paris"}}
        _run_turn(runner, session.id, "Paris")

        parts = fake_leg.seen_outgoing_parts
        context = parts[0].text
        assert context.startswith(
            "EARLIER REQUEST (the user's own words, not searched yet): "
            "un hôtel près de la gare du Nord demain à 14h\n"
        )
        assert "demain à 14h" in context  # the date and the slot reach the leaf again
        assert json.loads(context.splitlines()[1][len("YOU ASKED: "):]) == _wire(_CITY_NEEDED)
        assert context.endswith("REPLY:")
        assert parts[1].text == "Paris"
        # …and the question as data, for code, in the outgoing DataPart.
        assert find_datapart(parts)["query_params"]["clarification"] == _wire(_CITY_NEEDED)
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.pending_clarification is None  # consumed by the answer

    def test_the_same_question_is_reworded_then_dropped(
        self, monkeypatch, fake_leg, fake_profile_store, fired  # noqa: F811
    ):
        fake_leg.response_payload = _clarify_payload(_CITY_NEEDED)
        _scripted_llm(monkeypatch, *['{"family": "search", "language": "fr"}'] * 3)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        first = _run_turn(runner, session.id, "un hôtel près de la gare demain à 14h")
        second = _run_turn(runner, session.id, "la gare")
        third = _run_turn(runner, session.id, "la gare !")

        assert first != second
        assert first.endswith("?") and "Gare du Nord" in second
        assert third == templates.clarification_response(_CITY_NEEDED, "fr", 3)
        assert "?" not in third
        # The guard keeps its frozen name; it measures the state now.
        assert "anti_clarification_loop" in GUARD_SCORE_NAMES
        assert ["anti_clarification_loop" in turn for turn in fired] == [False, True, True]
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.last_clarifying_question is None  # the third reply asked nothing
        assert stored.pending_clarification["request"].startswith(
            "un hôtel près de la gare demain à 14h"
        )  # the request still waits for a city

    def test_the_hotels_marker_still_flags_the_clarification(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        from .test_spine import _marker_payloads

        fake_leg.response_payload = _clarify_payload(_CITY_NEEDED)
        _scripted_llm(monkeypatch, '{"family": "search", "language": "fr"}')
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        async def go():
            from google.genai import types as genai_types

            content = genai_types.Content(role="user", parts=[genai_types.Part(text="près de la gare")])
            return [e async for e in runner.run_async(user_id="u", session_id=session.id, new_message=content)]

        events = asyncio.run(go())
        hotels = [m for m in _marker_payloads(events) if m.get("event") == "hotels"]
        assert hotels and hotels[0]["requires_clarification"] is True and hotels[0]["hotels"] == []

    def test_an_off_contract_object_keeps_the_synthesis(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # A city_needed question with an option breaks the contract: ignored,
        # the turn answers as it did before Q04.
        fake_leg.response_payload = {
            "requires_clarification": True,
            "clarification": {"kind": "city_needed", "subject": "Gare du Nord",
                              "options": [{"label": "Paris", "city": "Paris"}]},
        }
        llm = _scripted_llm(
            monkeypatch, '{"family": "search", "language": "fr"}', "Dans quelle ville ?"
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        assert _run_turn(runner, session.id, "près de la gare") == "Dans quelle ville ?"
        assert len(llm.calls) == 2


class TestTheUnresolvedPlace:
    """2026-10-27: the leaf could not place what the user named (Galveston,
    Ojai): a question by template in the conversation's language, reworded
    once, then dropped like the other place questions."""

    UNRESOLVED = Clarification(kind="unresolved", subject="Galveston")

    @pytest.mark.parametrize("language", ["fr", "en", "es", "it", "de", "pt", "nl"])
    def test_every_language_names_the_place_and_asks(self, language):
        first = templates.clarification_response(self.UNRESOLVED, language, 1)
        again = templates.clarification_response(self.UNRESOLVED, language, 2)
        assert "Galveston" in first and "Galveston" in again
        assert first != again
        assert first.rstrip().endswith("?")

    def test_it_never_reads_like_an_outage(self):
        text = templates.clarification_response(self.UNRESOLVED, "en", 1)
        assert text != templates.leaf_degraded_response("search", "en")
        assert "reach" not in text and "try again" not in text
