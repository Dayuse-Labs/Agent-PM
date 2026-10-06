"""guard_window_match (mcp-dayuse#8): every card shown as a match covers the
requested time slot, by the site rule (`b2c_common.timeslot`).

QA 2026-09-30, reproduced locally 2026-10-06: "Lyon demain de 22h01 à
23h01" showed three cards closing at 22:00, and the reply said "vous pouvez
réserver ce créneau". The leaf now filters with the same predicate; this is
the backstop on what actually reaches the screen, plus the closest-offers
disclosure the synthesis is known to drop.
"""
from __future__ import annotations

import re
from typing import Any

from b2c_common.timeslot import parse_hhmm, requested_hours, slot_covers_window, window_fallback_line

# Coarse on purpose, like currency_guard: a missed paraphrase costs one
# extra honest sentence, never a silent claim.
_ALREADY_SAID_RE = re.compile(r"couvr|\bcover|cubr|copr|\bdeckt?\b|\bdekt\b|\bcobr", re.IGNORECASE)


def _card_covers(card: dict[str, Any], start: int | None, end: int | None) -> bool | None:
    """True/False when the card's slots say so, None when it carries none."""
    slots = [s for s in card.get("timeslots") or [] if isinstance(s, dict)]
    if not slots:
        return None
    for slot in slots:
        slot_start, slot_end = parse_hhmm(slot.get("start")), parse_hhmm(slot.get("end"))
        if slot_start is None or slot_end is None:
            continue
        if slot_covers_window(slot_start // 60, slot_end // 60, start, end):
            return True
    return False


def window_label(timeslot_start: str | None, timeslot_end: str | None) -> str:
    arrival, departure = requested_hours(parse_hhmm(timeslot_start), parse_hhmm(timeslot_end))
    if arrival is not None and departure is not None:
        return f"{arrival:02d}:00–{departure:02d}:00"
    hour = arrival if arrival is not None else departure
    return f"{hour:02d}:00" if hour is not None else ""


def enforce_window_match(
    results: list[dict[str, Any]], timeslot_start: str | None, timeslot_end: str | None
) -> tuple[list[dict[str, Any]], int]:
    """`(cards_to_show, dropped)`. Cards that do not cover the window are
    dropped; when that would leave nothing, all are kept (the caller then
    labels them as the closest offers). A card without slots is kept: it
    cannot be judged, and is not a claim about the time either."""
    start, end = parse_hhmm(timeslot_start), parse_hhmm(timeslot_end)
    if start is None and end is None:
        return results, 0
    kept = [c for c in results if not isinstance(c, dict) or _card_covers(c, start, end) is not False]
    dropped = len(results) - len(kept)
    if dropped and not kept:
        return results, dropped
    return kept, dropped


def enforce_window_disclosure(text: str, window: str, language: str) -> tuple[str, bool]:
    """Append the closest-offers sentence unless the answer already says no
    offer covers the slot."""
    if not text or _ALREADY_SAID_RE.search(text):
        return text, False
    return f"{text.rstrip()}\n\n{window_fallback_line(window, language)}", True
