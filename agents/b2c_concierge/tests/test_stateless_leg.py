"""StatelessLeafLeg (latency audit 2026-07-28) — the outgoing A2A message is
the CURRENT turn's user event only, never the conversation replay. Stock
RemoteA2aAgent walked the whole session (its stop condition needs a persisted
leg-authored event, which `_run_leaf` never persists), so turn N re-sent N
profile snapshots plus all prose — the leaf prompt grew linearly within a
conversation."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.events import Event
from google.genai import types as genai_types

from b2c_concierge.a2a_datapart import encode_datapart
from b2c_concierge.leg import StatelessLeafLeg


def _leg() -> StatelessLeafLeg:
    return StatelessLeafLeg(name="hotel_search_leg", agent_card="http://leaf.invalid/card")


def _user_event(text: str, with_datapart: dict | None = None) -> Event:
    parts = [genai_types.Part(text=text)]
    if with_datapart is not None:
        parts.append(encode_datapart(with_datapart))
    return Event(
        author="user",
        invocation_id="inv",
        content=genai_types.Content(role="user", parts=parts),
    )


def _model_event(text: str) -> Event:
    return Event(
        author="b2c_concierge",
        invocation_id="inv",
        content=genai_types.Content(role="model", parts=[genai_types.Part(text=text)]),
    )


def _ctx(events: list[Event]) -> SimpleNamespace:
    return SimpleNamespace(session=SimpleNamespace(events=events))


class TestCurrentTurnOnly:
    def test_three_turn_session_sends_only_the_last_user_event(self):
        events = [
            _user_event("turn 1", {"profile_in": {"city": None}}),
            _model_event("answer 1"),
            _user_event("turn 2", {"profile_in": {"city": "Paris"}}),
            _model_event("answer 2"),
            _user_event("turn 3", {"profile_in": {"city": "Paris", "date": "2026-07-29"}}),
        ]
        parts, context_id = _leg()._construct_message_parts_from_session(_ctx(events))

        assert context_id is None
        # Exactly the last user event's parts: its text + its ONE DataPart.
        assert len(parts) == 2
        texts = [p.root.text for p in parts if getattr(p.root, "text", None)]
        assert texts == ["turn 3"]
        # Nothing from earlier turns leaks through.
        flat = str([p.root for p in parts])
        assert "turn 1" not in flat and "answer" not in flat

    def test_parts_keep_the_user_input_stamp(self):
        parts, _ = _leg()._construct_message_parts_from_session(
            _ctx([_user_event("hello", {"profile_in": {}})])
        )
        assert parts, "expected converted parts"
        for part in parts:
            assert part.root.metadata["is_user_input"] is True

    def test_a_trailing_model_event_does_not_hide_the_user_turn(self):
        # ADK appends non-partial events as the turn progresses — the leg must
        # find the user event even when it is not the very last one.
        events = [_user_event("find me a hotel", {"profile_in": {}}), _model_event("progress")]
        parts, _ = _leg()._construct_message_parts_from_session(_ctx(events))
        texts = [p.root.text for p in parts if getattr(p.root, "text", None)]
        assert texts == ["find me a hotel"]

    def test_empty_session_sends_nothing(self):
        parts, context_id = _leg()._construct_message_parts_from_session(_ctx([]))
        assert parts == [] and context_id is None


class TestAdkPinGuard:
    """The override couples to a PRIVATE google-adk seam (2.4.0). An ADK bump
    that renames or reshapes it must fail HERE, loudly — not silently regrow
    the leaf payload by falling back to the parent's full-history walk."""

    def test_base_method_still_exists_with_the_expected_shape(self):
        base = RemoteA2aAgent._construct_message_parts_from_session
        params = list(inspect.signature(base).parameters)
        assert params == ["self", "ctx"]

    def test_the_converter_seam_still_exists(self):
        leg = _leg()
        assert callable(leg._genai_part_converter)

    def test_the_override_is_actually_wired(self):
        assert (
            StatelessLeafLeg._construct_message_parts_from_session
            is not RemoteA2aAgent._construct_message_parts_from_session
        )
