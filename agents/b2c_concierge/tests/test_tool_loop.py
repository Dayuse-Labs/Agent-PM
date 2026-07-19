"""Standalone unit tests for the bounded tool-calling loop (S06).

NOT wired into agent.py/routing.py this session (Fabien's call) — these tests
exercise `run_bounded_tool_loop` directly against a scripted litellm mock and
the CURRENT `inline_tools` stubs, as a concrete usage example ready for S07.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from b2c_concierge import inline_tools
from b2c_concierge.tool_loop import run_bounded_tool_loop

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "compare_hotels",
            "description": "Compare hotels",
            "parameters": {"type": "object", "properties": {"hotel_ids": {"type": "array"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hotel_details",
            "description": "Get hotel details",
            "parameters": {"type": "object", "properties": {"hotel_id": {"type": "string"}}},
        },
    },
]

TOOL_IMPLS = {
    "compare_hotels": inline_tools.compare_hotels,
    "get_hotel_details": inline_tools.get_hotel_details,
}


def _call(call_id: str, name: str, arguments: str = "{}"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def _resp(content: str | None = None, tool_calls: list | None = None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class ScriptedLitellm:
    """Queue of canned responses; any call beyond the plan fails the test."""

    def __init__(self, *plan):
        self.plan = list(plan)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if not self.plan:
            raise AssertionError("unexpected extra litellm call")
        return self.plan.pop(0)


def _run(max_rounds=2, tool_impls=None):
    return asyncio.run(
        run_bounded_tool_loop(
            model="fake-model",
            messages=[{"role": "user", "content": "hi"}],
            tools=TOOLS,
            tool_impls=tool_impls if tool_impls is not None else TOOL_IMPLS,
            max_rounds=max_rounds,
        )
    )


@pytest.fixture
def patch_litellm(monkeypatch):
    """`run_bounded_tool_loop` calls the shared `litellm.acompletion` — patch
    the module attribute directly (same pattern as the spine's own tests)."""
    import b2c_concierge.tool_loop as tool_loop_module

    def _install(llm):
        monkeypatch.setattr(tool_loop_module.litellm, "acompletion", llm)

    return _install


class TestNoToolCallsNeeded:
    def test_plain_text_returns_immediately(self, patch_litellm):
        llm = ScriptedLitellm(_resp(content="No comparison needed."))
        patch_litellm(llm)
        result = _run()
        assert result == "No comparison needed."
        assert len(llm.calls) == 1
        assert llm.calls[0]["tool_choice"] == "auto"


class TestBoundedRounds:
    def test_one_round_then_clean_finish(self, patch_litellm):
        llm = ScriptedLitellm(
            _resp(tool_calls=[_call("c1", "compare_hotels", '{"hotel_ids": ["a", "b"]}')]),
            _resp(content="Hotel A is closer to the beach."),
        )
        patch_litellm(llm)
        result = _run()
        assert result == "Hotel A is closer to the beach."
        assert len(llm.calls) == 2
        # the tool result was fed back as a `role: tool` message.
        tool_messages = [m for m in llm.calls[1]["messages"] if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0]["tool_call_id"] == "c1"

    def test_two_rounds_within_the_bound_then_clean_finish(self, patch_litellm):
        llm = ScriptedLitellm(
            _resp(tool_calls=[_call("c1", "compare_hotels")]),
            _resp(tool_calls=[_call("c2", "get_hotel_details", '{"hotel_id": "a"}')]),
            _resp(content="Here is the detail you asked for."),
        )
        patch_litellm(llm)
        result = _run()
        assert result == "Here is the detail you asked for."
        assert len(llm.calls) == 3

    def test_a_third_round_never_executes_a_tool_and_forces_a_clean_finalize(self, patch_litellm):
        """The architecture invariant: a guard never relaunches a full loop —
        beyond max_rounds it force-finalizes with tool_choice=none instead of
        executing yet another tool round."""
        llm = ScriptedLitellm(
            _resp(tool_calls=[_call("c1", "compare_hotels")]),
            _resp(tool_calls=[_call("c2", "get_hotel_details")]),
            _resp(tool_calls=[_call("c3", "compare_hotels")]),  # still wants a tool -> bound hit
            _resp(content="Best effort answer without a 3rd tool call."),
        )
        patch_litellm(llm)
        result = _run(max_rounds=2)
        assert result == "Best effort answer without a 3rd tool call."
        assert len(llm.calls) == 4
        assert llm.calls[-1]["tool_choice"] == "none"
        # no 3rd tool-result message was ever appended (c3 never executed).
        tool_call_ids = {
            m["tool_call_id"]
            for call in llm.calls
            for m in call["messages"]
            if m.get("role") == "tool"
        }
        assert tool_call_ids == {"c1", "c2"}


class TestHonestDegradation:
    def test_unknown_tool_name_feeds_back_an_error_never_raises(self, patch_litellm):
        llm = ScriptedLitellm(
            _resp(tool_calls=[_call("c1", "generate_booking_link")]),  # not in TOOL_IMPLS
            _resp(content="I can't do that yet."),
        )
        patch_litellm(llm)
        result = _run()
        assert result == "I can't do that yet."
        tool_message = next(m for m in llm.calls[1]["messages"] if m.get("role") == "tool")
        assert "unknown tool" in tool_message["content"]

    def test_tool_exception_feeds_back_an_error_never_raises(self, patch_litellm):
        def _raiser(**kwargs):
            raise RuntimeError("boom")

        llm = ScriptedLitellm(
            _resp(tool_calls=[_call("c1", "compare_hotels")]),
            _resp(content="Handled gracefully."),
        )
        patch_litellm(llm)
        result = _run(tool_impls={"compare_hotels": _raiser})
        assert result == "Handled gracefully."
        tool_message = next(m for m in llm.calls[1]["messages"] if m.get("role") == "tool")
        assert "failed" in tool_message["content"]
