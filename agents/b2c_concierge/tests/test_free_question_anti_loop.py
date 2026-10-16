"""QA14707 (Q28): the anti-loop on FREE questions, read from the state.

Q11 removed the text-based retry-clarification-loop guard: a leaf that asked a
non-place question turn after turn was never corrected (old production
sessions repeated one question up to 7 times). The loop is now a count in the
persisted `pending_search` slot (`asked`: turns in a row that ended on a free
question without a search), never a comparison of wordings. Past
`templates.CLARIFICATION_MAX_ASKS`, the one synthesis call is told not to ask;
a question line it still ends on is dropped, or a fixed template answers. No
retry, no added LLM call. Offline: one session, fake leaf, scripted LLM.
"""
from __future__ import annotations

import asyncio
import logging

import pytest
from google.adk.runners import InMemoryRunner

import b2c_concierge.agent as agent_module
from b2c_common.scores import GUARD_SCORE_NAMES
from b2c_concierge import templates
from b2c_concierge.agent import root_agent
from b2c_concierge.budget import MAX_LLM_CALLS_PER_TURN
from b2c_concierge.profile import SessionProfile
from b2c_concierge.triage import TEMPLATE_LANGUAGES

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

_SEARCH = '{"family": "search", "language": "en"}'
_REQUEST = "a hotel tomorrow from 2pm to 6pm"
# Four different wordings: the loop is the count of turns, not one sentence.
_LEAF_QUESTIONS = (
    "Which city are you looking in?",
    "Which neighbourhood would you like?",
    "Could you tell me the area?",
    "Any district in mind?",
)
_MESSAGES = (_REQUEST, "somewhere nice", "anywhere really", "I don't know")
_RESULTS = {"results": [{"hotel_id": 1, "name": "Hotel A"}], "profile_delta": {"city": "Nice"}}


def _stored(store, session_id) -> SessionProfile:
    return asyncio.run(store.get(session_id))


def _last_line(text: str) -> str:
    return [line for line in text.splitlines() if line.strip()][-1].strip()


def _context_text(parts) -> str:
    return parts[0].text if len(parts) > 1 and parts[0].text else ""


def _synthesis_inputs(llm) -> list[str]:
    return [
        call["messages"][1]["content"]
        for call in llm.calls
        if call["messages"][0]["content"].startswith("You are the synthesis step")
    ]


@pytest.fixture
def fired(monkeypatch) -> list[set[str]]:
    """The guard set each turn scored (OBS3), in turn order."""
    turns: list[set[str]] = []
    monkeypatch.setattr(agent_module, "score_guards", lambda names: turns.append(set(names)))
    return turns


def _ask_turn(runner, session_id, fake_leg, n: int) -> str:  # noqa: F811
    """Turn n (0-based): the leaf asks a free question instead of searching."""
    fake_leg.text = _LEAF_QUESTIONS[n]
    fake_leg.response_payload = None
    return _run_turn(runner, session_id, _MESSAGES[n])


class TestFourAsksInARow:
    def test_from_the_third_ask_the_reply_asks_nothing(
        self, monkeypatch, fake_leg, fake_profile_store, fired  # noqa: F811
    ):
        # The synthesis keeps ending on the leaf's question (it ignores the
        # instruction): only code stands between the user and a fourth ask.
        plan: list[str] = []
        for question in _LEAF_QUESTIONS:
            plan += [_SEARCH, f"I need one more detail.\n{question}"]
        _scripted_llm(monkeypatch, *plan)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        replies, stored, contexts = [], [], []
        for n in range(4):
            replies.append(_ask_turn(runner, session.id, fake_leg, n))
            contexts.append(_context_text(fake_leg.seen_outgoing_parts))
            stored.append(_stored(fake_profile_store, session.id))

        # What the user reads first: turns 1 and 2 keep the question, turns 3
        # and 4 ask nothing.
        assert [_last_line(reply) for reply in replies[:2]] == list(_LEAF_QUESTIONS[:2])
        for n in (2, 3):
            assert not _last_line(replies[n]).endswith("?"), replies[n]
            assert replies[n] == "I need one more detail."
        # The state behind it.
        for n in (0, 1):
            assert stored[n].last_clarifying_question == _LEAF_QUESTIONS[n]
            assert stored[n].pending_search["asked"] == n + 1
        # From turn 3 (asked > CLARIFICATION_MAX_ASKS) the question is gone.
        for n in (2, 3):
            assert stored[n].pending_search["asked"] > templates.CLARIFICATION_MAX_ASKS
            assert stored[n].last_clarifying_question is None
            assert stored[n].pending_search["question"] is None
            assert stored[n].pending_search["request"].startswith(_REQUEST)  # date and slot kept
        assert [s.pending_search["asked"] for s in stored] == [1, 2, 3, 4]
        assert ["anti_clarification_loop" in turn for turn in fired] == [False, False, True, True]
        # Turn 3's leaf still read the question of turn 2; turn 4's leaf gets
        # the request still open, and no YOU ASKED.
        assert f"YOU ASKED: {_LEAF_QUESTIONS[1]}" in contexts[2]
        assert contexts[3].startswith(f"EARLIER REQUEST (the user's own words, not searched yet): {_REQUEST}")
        assert "YOU ASKED" not in contexts[3]

    def test_the_correction_rides_on_the_one_synthesis_call(
        self, monkeypatch, fake_leg, fake_profile_store, caplog  # noqa: F811
    ):
        plan: list[str] = []
        for question in _LEAF_QUESTIONS[:3]:
            plan += [_SEARCH, f"I need one more detail.\n{question}"]
        llm = _scripted_llm(monkeypatch, *plan)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        for n in range(2):
            _ask_turn(runner, session.id, fake_leg, n)
        calls_before = len(llm.calls)
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            _ask_turn(runner, session.id, fake_leg, 2)

        assert len(llm.calls) - calls_before == 2  # the triage + the one synthesis
        synthesis_inputs = _synthesis_inputs(llm)
        assert len(synthesis_inputs) == 3
        assert ["NO QUESTION:" in text for text in synthesis_inputs] == [False, False, True]
        line = [r.getMessage() for r in caplog.records if "concierge_metric=turn" in r.getMessage()][-1]
        metric = dict(kv.split("=", 1) for kv in line.split() if "=" in kv)
        assert metric["phases"].split(",").count("synthesis") == 1
        assert int(metric["llm_calls"]) <= MAX_LLM_CALLS_PER_TURN == 3
        assert "anti_clarification_loop" in GUARD_SCORE_NAMES


class TestCorrectionBranches:
    """The three ways a corrected turn ends: the synthesis obeyed, its
    question line is dropped, or nothing remains and the template answers."""

    def _third_turn(self, monkeypatch, fake_leg, fake_profile_store, synthesis: str):  # noqa: F811
        _scripted_llm(
            monkeypatch,
            _SEARCH, _LEAF_QUESTIONS[0], _SEARCH, _LEAF_QUESTIONS[1], _SEARCH, synthesis,
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        for n in range(2):
            _ask_turn(runner, session.id, fake_leg, n)
        reply = _ask_turn(runner, session.id, fake_leg, 2)
        return reply, _stored(fake_profile_store, session.id)

    def test_a_synthesis_that_obeys_is_served_as_is(
        self, monkeypatch, fake_leg, fake_profile_store, fired  # noqa: F811
    ):
        reply, stored = self._third_turn(
            monkeypatch, fake_leg, fake_profile_store, "I'll search as soon as I have the area."
        )
        assert reply == "I'll search as soon as I have the area."
        assert stored.last_clarifying_question is None
        assert "anti_clarification_loop" in fired[-1]  # the leaf still asked

    def test_the_question_line_it_still_ends_on_is_dropped(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        reply, stored = self._third_turn(
            monkeypatch, fake_leg, fake_profile_store,
            "Nothing to search yet.\n\nWhich area would you like?",
        )
        assert reply == "Nothing to search yet."
        assert stored.last_clarifying_question is None

    def test_a_synthesis_that_is_only_a_question_gets_the_template(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        reply, stored = self._third_turn(
            monkeypatch, fake_leg, fake_profile_store, "Which area would you like?"
        )
        assert reply == templates.no_question_response("en")
        assert stored.last_clarifying_question is None
        assert stored.pending_search["request"].startswith(_REQUEST)

    @pytest.mark.parametrize("language", TEMPLATE_LANGUAGES)
    def test_the_template_asks_nothing_in_every_language(self, language):
        text = templates.no_question_response(language)
        assert text and "?" not in text
        if language != "en":
            assert text != templates.no_question_response("en")  # a real translation

    def test_the_drop_rule_is_punctuation_only(self):
        from b2c_concierge.profile import without_final_question

        assert without_final_question("A.\nB?") == "A."
        assert without_final_question("A.\nB?\n\n  ") == "A."
        assert without_final_question("A?\nB.") == "A?\nB."  # not its last line
        assert without_final_question("A.\nB?\nC?") == "A."
        assert without_final_question("Only a question?") == ""
        assert without_final_question(None) == ""


class TestStoredCount:
    @pytest.mark.parametrize(
        "stored_asked", ["missing", True, False, "2", 0, -3], ids=repr
    )
    def test_an_unusable_count_loads_and_counts_from_one(
        self, monkeypatch, fake_leg, fake_profile_store, fired, stored_asked  # noqa: F811
    ):
        slot: dict = {"request": _REQUEST, "question": _LEAF_QUESTIONS[0]}
        if stored_asked != "missing":
            slot["asked"] = stored_asked
        profile = SessionProfile.from_dict({"pending_search": slot})  # written by another writer
        assert profile.pending_search == slot
        _scripted_llm(monkeypatch, _SEARCH, f"One more detail.\n{_LEAF_QUESTIONS[1]}")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, profile))

        reply = _ask_turn(runner, session.id, fake_leg, 1)

        assert _last_line(reply) == _LEAF_QUESTIONS[1]
        assert _stored(fake_profile_store, session.id).pending_search["asked"] == 1
        assert "anti_clarification_loop" not in fired[-1]

    def test_a_search_with_results_between_asks_resets_the_count(
        self, monkeypatch, fake_leg, fake_profile_store, fired  # noqa: F811
    ):
        _scripted_llm(
            monkeypatch,
            _SEARCH, _LEAF_QUESTIONS[0], _SEARCH, _LEAF_QUESTIONS[1],
            _SEARCH, "Here are hotels in Nice.",
            _SEARCH, _LEAF_QUESTIONS[2], _SEARCH, _LEAF_QUESTIONS[3],
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        counts = []

        for n in range(2):
            _ask_turn(runner, session.id, fake_leg, n)
            counts.append(_stored(fake_profile_store, session.id).pending_search["asked"])
        fake_leg.text = "results: hotel A"
        fake_leg.response_payload = _RESULTS
        _run_turn(runner, session.id, "Nice")
        assert _stored(fake_profile_store, session.id).pending_search is None  # cleared, as before
        for n in (2, 3):
            replies = _ask_turn(runner, session.id, fake_leg, n)
            counts.append(_stored(fake_profile_store, session.id).pending_search["asked"])

        assert counts == [1, 2, 1, 2]
        assert _last_line(replies) == _LEAF_QUESTIONS[3]
        assert not any("anti_clarification_loop" in turn for turn in fired)

    def test_the_count_holds_no_message_text(self):
        from b2c_concierge.profile import next_pending_search

        slot = next_pending_search(None, _REQUEST, False, _LEAF_QUESTIONS[0], ended_on_question=True)
        assert slot == {"request": _REQUEST, "question": _LEAF_QUESTIONS[0], "asked": 1}
        assert type(slot["asked"]) is int

    def test_a_place_question_keeps_its_own_count(self):
        from b2c_concierge.profile import free_question_streak, next_pending_search

        place_slot = {"clarification": {"kind": "city_needed", "subject": "Gare"}, "request": _REQUEST, "asked": 2}
        assert free_question_streak(place_slot) == 0
        after = next_pending_search(place_slot, "x", False, "Which city?", ended_on_question=True)
        assert after["asked"] == 1

    def test_a_turn_that_asked_nothing_ends_the_streak(self):
        from b2c_concierge.profile import next_pending_search

        earlier = {"request": _REQUEST, "question": "Which city?", "asked": 2}
        after = next_pending_search(earlier, "hmm", False, None, ended_on_question=False)
        assert after == {"request": f"{_REQUEST}\nhmm", "question": None, "asked": 0}
        assert next_pending_search(earlier, "Nice", True, None, ended_on_question=False) is None
