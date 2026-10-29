"""Bounded dialogue context for interpreting follow-ups, never a policy source.

2026-10-29 (review of the 97 real conversations after #173, defects B8-B10,
B15, B17, A9, C5): the synthesis saw the history on the FAQ route only, and
the search leaf saw the current message alone (`leg.py`, its model runs
`include_contents="none"`). A « 2 » answering a numbered question, a date
given before a clarification, a wish from the first message, the party size
given the turn before: lost between two turns.

`dialogue_context` is what both now receive, on every route, built in CODE
from the session profile (Redis, same TTL as the rest of it) — the language
model reads it; no word of the message is interpreted here:

- `turns`: the last `MAX_TURNS` exchanges, oldest first — the user's own
  words (`MAX_USER_CHARS`) and a short cut of the answer they got
  (`MAX_REPLY_CHARS`, its head and its tail, where the question sits), plus
  how many hotels it showed. Never the cards themselves. A policy answer
  (FAQ) is never memory (decision of 2026-10-07: its text could carry a
  policy the model made up): its reply is the fixed `POLICY_REPLY`.
- `asked`: the question the previous answer ended on, which THIS message may
  answer (`last_clarifying_question`), when the last reply's cut lacks it.
- `state`: what the previous turn left — the place resolved, the day, the
  time slot, the filters, the party, the hotels on screen (ids and names).
  Never the device position (only that the search runs around it), never an
  e-mail address (masked in the user's words).

Size, worst case (3 full turns, a long question, a full state): ~2 100
characters, ~520 tokens for the synthesis; ~1 400 characters, ~330 tokens for
the search leaf, which reads the state in its `profile_in` already
(`leaf_dialogue`). Typical: a few dozen tokens. Measured per turn by
`context_size` (a count, no content, in the `dialogue_context` metric).
"""
from __future__ import annotations

import json
import re
from typing import Any

#: Exchanges kept, user words and reply cuts (characters).
MAX_TURNS = 3
MAX_USER_CHARS = 200
MAX_REPLY_CHARS = 160
MAX_ASKED_CHARS = 200
MAX_ON_SCREEN = 5
MAX_NAME_CHARS = 60

#: What a FAQ answer is remembered as — never its text.
POLICY_REPLY = "(answered a question about Dayuse's policies)"

# Data minimisation, not comprehension: an address is masked before the words
# are stored, whatever the message says.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


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


def _clip(text: str, limit: int) -> str:
    """One line, at most `limit` characters: the head and the tail of a longer
    text (a reply's question is its last sentence)."""
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    tail = limit // 2 - 2
    return f"{flat[: limit - tail - 3].rstrip()} … {flat[-tail:].lstrip()}"


def _user_words(message: str) -> str:
    return _clip(_EMAIL_RE.sub("[email]", message or ""), MAX_USER_CHARS)


def record_exchange(
    profile: Any, message: str, reply: str, hotels: int = 0, *, policy_answer: bool = False
) -> None:
    """Appends this turn's exchange to `profile.recent_turns` (bounded); the
    caller persists the profile. An empty message or reply is not an exchange."""
    user, answer = _user_words(message), _clip(reply, MAX_REPLY_CHARS)
    if policy_answer and answer:
        answer = POLICY_REPLY
    if not user or not answer:
        return
    turn: dict[str, Any] = {"user": user, "reply": answer}
    if hotels:
        turn["hotels"] = int(hotels)
    kept = [t for t in (profile.recent_turns or []) if isinstance(t, dict)]
    profile.recent_turns = [*kept, turn][-MAX_TURNS:]


def _place(profile: Any) -> dict[str, Any]:
    place: dict[str, Any] = {}
    for key in ("city", "zone", "metro", "region_anchor", "state_anchor", "country_anchor"):
        value = getattr(profile, key, None)
        if isinstance(value, str) and value:
            place[key.removesuffix("_anchor")] = value
    named = getattr(profile, "named_hotel", None)
    if isinstance(named, dict) and named.get("name"):
        place["hotel"] = named["name"]
    if isinstance(getattr(profile, "search_anchor", None), dict):
        place["near_device_position"] = True  # never the coordinates
    return place


def _time(profile: Any) -> str | None:
    if profile.timeslot:
        return str(profile.timeslot)
    start, end = profile.timeslot_start, profile.timeslot_end
    if start or end:
        return f"{start or ''}-{end or ''}"
    return profile.daypart or None


def _filters(profile: Any) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if profile.amenities:
        filters["amenities"] = list(profile.amenities)
    if profile.preferred_amenities:
        filters["ideally"] = list(profile.preferred_amenities)
    if profile.standing:
        filters["standing"] = profile.standing
    budget = profile.requested_budget
    if isinstance(budget, dict) and budget.get("amount"):
        filters["budget_max"] = " ".join(
            str(part) for part in (budget["amount"], budget.get("currency"), budget.get("unit")) if part
        )
    elif profile.budget_max:
        filters["budget_max"] = f"{profile.budget_max:g} EUR"
    if profile.price_comparison:
        filters["cheaper_than_shown"] = True
    party = {key: getattr(profile, key) for key in ("adults", "children") if getattr(profile, key) is not None}
    if profile.pending_party_total is not None:
        party = {"total_unsplit": profile.pending_party_total}
    if party:
        filters["party"] = party
    return filters


def previous_state(profile: Any) -> dict[str, Any]:
    """What the previous turn left, as facts of the profile (empty keys out)."""
    state: dict[str, Any] = {}
    place = _place(profile)
    if place:
        state["place"] = place
    if profile.date:
        state["date"] = profile.date
    time_of_day = _time(profile)
    if time_of_day:
        state["time"] = time_of_day
    filters = _filters(profile)
    if filters:
        state["filters"] = filters
    on_screen = [
        {"id": entry.get("hotel_id"), "name": _clip(str(entry["name"]), MAX_NAME_CHARS)}
        for entry in (profile.last_results or [])[:MAX_ON_SCREEN]
        if isinstance(entry, dict) and entry.get("name")
    ]
    if on_screen:
        state["on_screen"] = on_screen
    return state


def dialogue_context(profile: Any) -> dict[str, Any] | None:
    """The context of this turn, read from the profile BEFORE the turn
    changes it; None on a conversation's first turn."""
    turns = [dict(t) for t in (profile.recent_turns or []) if isinstance(t, dict)][-MAX_TURNS:]
    context: dict[str, Any] = {}
    if turns:
        context["turns"] = turns
    asked = " ".join(str(profile.last_clarifying_question or "").split())
    if asked:
        last_reply = turns[-1].get("reply", "") if turns else ""
        if asked[-60:] not in last_reply:
            context["asked"] = _clip(asked, MAX_ASKED_CHARS)
    state = previous_state(profile)
    if state and (turns or asked):
        context["state"] = state
    return context or None


def leaf_dialogue(context: dict[str, Any] | None) -> dict[str, Any] | None:
    """The search leaf's share: the exchanges and the question; the state is
    already its `profile_in`."""
    if not context:
        return None
    kept: dict[str, Any] = {key: context[key] for key in ("turns", "asked") if key in context}
    return kept or None


def dialogue_json(context: dict[str, Any] | None) -> str:
    return json.dumps(context, ensure_ascii=False, separators=(",", ":")) if context else ""


def context_size(context: dict[str, Any] | None) -> int:
    """Characters of the serialized context (≈ 4 per token) — for the metric."""
    return len(dialogue_json(context))
