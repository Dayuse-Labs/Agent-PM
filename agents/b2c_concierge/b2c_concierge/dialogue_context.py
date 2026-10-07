"""Bounded user context for interpreting follow-ups, never a policy source."""
from __future__ import annotations

from typing import Any


def recent_user_messages(events: list[Any], current_message: str) -> list[str]:
    messages = []
    for event in events:
        content = getattr(event, "content", None)
        if content is None or content.role != "user" or getattr(event, "author", "") != "user":
            continue
        text = "\n".join(p.text for p in content.parts or [] if p.text)
        if text.strip():
            messages.append(text)
    # ADK has already appended the current user event before running the spine.
    if messages and messages[-1] == current_message:
        messages.pop()
    return [message[:400] for message in messages[-3:]]


def last_assistant_message(events: list[Any], *, author: str) -> str | None:
    """Last customer-facing concierge reply, never tool output or reasoning.

    Bound the tail so the final clarification survives a long hotel shortlist.
    This is interpretation context, not evidence for policies or booking consent.
    """
    for event in reversed(events):
        content = getattr(event, "content", None)
        if (getattr(event, "author", None) != author
                or getattr(event, "partial", False)
                or content is None or content.role != "model"):
            continue
        text = "\n".join(
            p.text for p in content.parts or []
            if p.text and not getattr(p, "thought", False)
        )
        if text.strip():
            return text[-1200:]
    return None
