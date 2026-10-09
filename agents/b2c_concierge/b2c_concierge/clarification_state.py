"""Concierge-owned question scope, bound to the actual previous answer."""
from __future__ import annotations

from .profile import SessionProfile


def location_reply_context(profile: SessionProfile, previous_reply: str | None) -> dict[str, str] | None:
    pending = profile.pending_clarification
    if (not isinstance(pending, dict) or pending.get("kind") != "location"
            or not isinstance(pending.get("question"), str) or not previous_reply
            or pending["question"].strip() != previous_reply.strip()):
        return None
    return {k: v for k, v in pending.items() if k in {"kind", "value"} and isinstance(v, str)}


def remember_location_question(profile: SessionProfile, question: str, value: str | None = None) -> None:
    profile.last_clarifying_question = question
    profile.pending_clarification = {"kind": "location", "question": question}
    if value is not None:
        profile.pending_clarification["value"] = value
