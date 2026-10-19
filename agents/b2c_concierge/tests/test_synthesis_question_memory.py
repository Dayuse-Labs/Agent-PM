"""QA14707 (Q27): a follow-up question only the synthesis asks is remembered.

Q11 made the next turn's `previous_question` the leaf's own last line. When the
leaf asked nothing and only the synthesis ends on a question, a following
« oui » reached the triage with no question. The same `leaf_question` rule (a
trailing '?', 300 chars, no wording read) now also reads the final synthesis,
the leaf's line winning. Offline: fake leaf, scripted synthesis.
"""
from __future__ import annotations

import asyncio

from google.adk.runners import InMemoryRunner

from b2c_concierge.agent import root_agent
from b2c_concierge.profile import leaf_question, turn_question

from .test_clarification_routing import _C2_TRIAGE, mcp_calls  # noqa: F401
from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

_SYNTH_QUESTION = "Would you like hotels closer to the centre?"
_SEARCH = '{"family": "search", "language": "en"}'
_PAYLOAD = {"results": ["hotel A"], "profile_delta": {"city": "Nice"}}


def _stored(store, session_id):
    return asyncio.run(store.get(session_id))


def _ctx_text(parts) -> str:
    return parts[0].text if parts and parts[0].text else ""


class TestRule:
    def test_leaf_line_wins_then_synthesis_line(self):
        assert turn_question("Which city?", f"x\n{_SYNTH_QUESTION}") == "Which city?"
        assert turn_question("results: A", f"x\n{_SYNTH_QUESTION}") == _SYNTH_QUESTION
        assert turn_question("results: A", "No question here.") is None
        assert turn_question(None, None) is None

    def test_same_cap_as_the_leaf_rule(self):
        long = "a" * 400 + "?"
        assert turn_question(None, long) == leaf_question(long)
        assert len(turn_question(None, long)) == 300


class TestThroughTheSpine:
    def test_a_question_only_the_synthesis_asks_is_stored_and_answered_by_oui(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _PAYLOAD
        llm = _scripted_llm(
            monkeypatch,
            _SEARCH, f"Hotels in Nice.\n{_SYNTH_QUESTION}",
            '{"family": "search", "language": "en", "affirmative": true}', "Closer ones.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "a hotel in Nice")
        stored = _stored(fake_profile_store, session.id)
        assert stored.last_clarifying_question == _SYNTH_QUESTION
        assert stored.pending_search["question"] == _SYNTH_QUESTION

        _run_turn(runner, session.id, "oui")
        triage_input = llm.calls[2]["messages"][1]["content"]
        assert "LAST ASSISTANT QUESTION" in triage_input
        assert _SYNTH_QUESTION in triage_input
        assert f"YOU ASKED: {_SYNTH_QUESTION}" in _ctx_text(fake_leg.seen_outgoing_parts)

    def test_the_leafs_line_wins_over_the_synthesis(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.text = "Voulez-vous des hôtels plus proches du centre ?"
        fake_leg.response_payload = _PAYLOAD
        _scripted_llm(monkeypatch, _SEARCH, f"Hotels in Nice.\n{_SYNTH_QUESTION}")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "a hotel in Nice")

        stored = _stored(fake_profile_store, session.id)
        assert stored.last_clarifying_question == fake_leg.text

    def test_a_synthesis_without_a_question_mark_stores_none(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = _PAYLOAD
        _scripted_llm(monkeypatch, _SEARCH, "Hotels in Nice. Enjoy.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "a hotel in Nice")

        assert _stored(fake_profile_store, session.id).last_clarifying_question is None

    def test_oui_after_a_synthesis_question_books_nothing_without_an_offer(
        self, monkeypatch, fake_leg, fake_profile_store, mcp_calls  # noqa: F811
    ):
        """R9: the remembered question never makes « oui » a booking."""
        fake_leg.response_payload = _PAYLOAD
        _scripted_llm(
            monkeypatch,
            _SEARCH, f"Hotels in Nice.\n{_SYNTH_QUESTION}",
            '{"family": "booking", "language": "en", "booking_confirmation": "confirm"}',
            "Here are hotels.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "a hotel in Nice")
        _run_turn(runner, session.id, "oui")

        called = {name for name, _ in mcp_calls}
        assert "generate_booking_link" not in called
        assert "find_hotel_by_name" not in called
