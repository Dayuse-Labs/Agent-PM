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
