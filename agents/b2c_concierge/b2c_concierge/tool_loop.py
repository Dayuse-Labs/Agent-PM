"""Bounded tool-calling loop for the b2c-concierge synthesis step (S06).

A generic, reusable mechanism: at most `max_rounds` tool-call round-trips
before the loop is FORCED to finalize with plain text (`tool_choice="none"`)
— a guard never relaunches a full loop (architecture invariant: "un guard ne
relance jamais une boucle : 1 retry borné, puis correction déterministe"),
it hard-stops instead.

Not wired into routing.py/agent.py this session (Fabien's call, S06): the
mechanism is built and unit-tested standalone here, against the current
`inline_tools` stubs, ready for S07 to plug in the real MCP-backed
get_hotel_details/compare_hotels tools and decide WHEN synthesis should
offer them. `generate_booking_link` must NEVER be offered to this loop — R9
(guard #12, S07) requires the turn-state confirmation flag gate to sit in
front of it, which this generic loop does not provide.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import litellm

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROUNDS = 2


def _execute_tool_call(call: Any, tool_impls: dict[str, Callable[..., dict[str, Any]]]) -> dict[str, Any]:
    """A tool-result message for `call` — never raises: an unknown tool name
    or a tool exception both become an honest error string fed back to the
    model (same "never invent, degrade honestly" posture as the rest of the
    spine), not a crash of the loop."""
    name = call.function.name
    try:
        kwargs = json.loads(call.function.arguments or "{}")
    except (ValueError, TypeError):
        kwargs = {}
    impl = tool_impls.get(name)
    if impl is None:
        result: dict[str, Any] = {"ok": False, "error": f"unknown tool '{name}'"}
    else:
        try:
            result = impl(**kwargs)
        except Exception as exc:  # noqa: BLE001 — a tool failure must not crash the loop
            logger.warning("tool_loop: %s raised %s", name, type(exc).__name__)
            result = {"ok": False, "error": f"{name} failed: {type(exc).__name__}"}
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "content": json.dumps(result, ensure_ascii=False),
    }


def _assistant_tool_call_message(message: Any) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }
            for call in message.tool_calls
        ],
    }


async def run_bounded_tool_loop(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_impls: dict[str, Callable[..., dict[str, Any]]],
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    **litellm_kwargs: Any,
) -> str:
    """Runs `messages` through `model`, executing at most `max_rounds` tool
    round-trips (each round: one model call that requests tool calls, all
    executed and fed back as tool-result messages). On the round AFTER the
    bound is reached, if the model still wants a tool, the loop force-
    finalizes with one extra `tool_choice="none"` call instead of executing
    a 3rd round — it never keeps looping, and always returns real text.
    """
    conversation = list(messages)
    rounds = 0
    while True:
        resp = await litellm.acompletion(
            model=model, messages=conversation, tools=tools, tool_choice="auto", **litellm_kwargs
        )
        message = resp.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return (message.content or "").strip()
        if rounds >= max_rounds:
            forced = await litellm.acompletion(
                model=model, messages=conversation, tool_choice="none", **litellm_kwargs
            )
            return (forced.choices[0].message.content or "").strip()
        rounds += 1
        conversation.append(_assistant_tool_call_message(message))
        for call in tool_calls:
            conversation.append(_execute_tool_call(call, tool_impls))
