"""Typed session profile of the b2c-concierge spine + its deterministic guards.

The profile is orchestrator-owned state (the leaves are stateless — decision B3):
it travels OUT to a leaf as `profile_in` and comes back as `profile_delta` (the
A2A DataPart envelope, see a2a_datapart.py), never the reverse. Storage is
Redis (profile_store.py); this module is pure and Redis-free on purpose so the
guards stay unit-testable without a broker.

Two guards port the P1/P6 production-audit fixes from agent-usa onto this
schema (behavior ported, not code — the old implementation lived in a very
different, workflow-based architecture):
  - budget integrity: a bare-number reply ("180", "$40") is ALWAYS the user's
    explicit budget, regardless of what a leaf's own extraction claims, and an
    explicit budget is never silently auto-widened;
  - timeslot sanitization: a one-sided clock label ("15:00-") is salvaged into
    a start/end bound, never persisted as a corrupted free-text string; an
    anchored bound (e.g. an end-only "before 9am") is never inverted by a
    later turn's re-extraction that carries no new time-of-day text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

BUDGET_SOURCE_EXPLICIT = "explicit"
BUDGET_SOURCE_FLEXIBLE_DEFAULT = "flexible_default"

AUTO_WIDEN_STREAK_THRESHOLD = 2
AUTO_WIDEN_FACTOR = 1.5


@dataclass
class SessionProfile:
    """One session's accumulated search context — the orchestrator's only
    state; the leaves never store this (stateless contract, decision B3)."""

    city: str | None = None
    state_anchor: str | None = None
    country_anchor: str | None = None
    budget_max: float | None = None
    budget_request_source: str | None = None
    timeslot: str | None = None
    timeslot_start: str | None = None
    timeslot_end: str | None = None
    timeslot_request_source: str | None = None
    timeslot_mode: str | None = None  # "start_only" | "end_only" | "range"
    amenities: list[str] = field(default_factory=list)
    language: str | None = None
    consecutive_empty_searches: int = 0
    auto_widen_disclosure: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "city": self.city,
            "state_anchor": self.state_anchor,
            "country_anchor": self.country_anchor,
            "budget_max": self.budget_max,
            "budget_request_source": self.budget_request_source,
            "timeslot": self.timeslot,
            "timeslot_start": self.timeslot_start,
            "timeslot_end": self.timeslot_end,
            "timeslot_request_source": self.timeslot_request_source,
            "timeslot_mode": self.timeslot_mode,
            "amenities": list(self.amenities),
            "language": self.language,
            "consecutive_empty_searches": self.consecutive_empty_searches,
            "auto_widen_disclosure": self.auto_widen_disclosure,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionProfile":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)


# --- Budget integrity (P1) --------------------------------------------------

_BARE_NUMBER_RE = re.compile(r"^\s*[$€£]?\s*(\d+(?:[.,]\d+)?)\s*[$€£]?\s*$")


def _bare_number_value(message: str) -> float | None:
    """The message IS a plain number (currency symbol tolerated) — nothing
    else. "180" and "$40" match; "under 180" or "180 max" do not."""
    match = _BARE_NUMBER_RE.match(message or "")
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def maybe_auto_widen(profile: SessionProfile) -> bool:
    """Auto-widen the budget after a streak of empty searches — SKIPPED when
    the current budget is the user's own explicit figure (never silently
    override what they typed). Sets the mandatory disclosure payload when it
    does widen; a later synthesis step (S06) must surface it to the user."""
    if profile.consecutive_empty_searches < AUTO_WIDEN_STREAK_THRESHOLD:
        return False
    if profile.budget_request_source == BUDGET_SOURCE_EXPLICIT:
        return False
    if profile.budget_max is None:
        return False
    old_budget = profile.budget_max
    new_budget = round(old_budget * AUTO_WIDEN_FACTOR, 2)
    profile.budget_max = new_budget
    profile.auto_widen_disclosure = {"from": old_budget, "to": new_budget}
    return True


# --- Timeslot sanitization (P6) ---------------------------------------------

_CLOCK_TOKEN_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$", re.IGNORECASE)

_TIME_MENTION_RE = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|h)\b|\b\d{1,2}:\d{2}\b|"
    r"\b(?:morning|afternoon|evening|night|matin|midi|apr[eè]s-midi|soir(?:ée)?)\b",
    re.IGNORECASE,
)


def _parse_clock_token(token: str) -> str | None:
    match = _CLOCK_TOKEN_RE.match(token)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _split_one_sided_clock(value: str | None) -> tuple[str | None, str | None]:
    """A one-sided bound ("15:00-", "-09:00", "9am-") salvaged into
    (start, None) or (None, end). A non-clock free-text label ("morning")
    is left alone — (None, None), the caller keeps it as-is."""
    if not value:
        return (None, None)
    stripped = value.strip()
    if len(stripped) < 2:
        return (None, None)
    if stripped[-1] in "-_" and stripped[0] not in "-_":
        start = _parse_clock_token(stripped[:-1])
        return (start, None) if start else (None, None)
    if stripped[0] in "-_" and stripped[-1] not in "-_":
        end = _parse_clock_token(stripped[1:])
        return (None, end) if end else (None, None)
    return (None, None)


def _normalize_timeslot(value: str | None) -> str | None:
    """None if `value` is a malformed one-sided clock label (the caller
    salvages the bound separately via `_split_one_sided_clock`) — such a
    string must NEVER be persisted as the free-text timeslot. Any other
    value (including a clean clock string or a day-part word) passes through."""
    if not value:
        return None
    start, end = _split_one_sided_clock(value)
    if start or end:
        return None
    return value


def _mentions_explicit_time(message: str) -> bool:
    return bool(_TIME_MENTION_RE.search(message or ""))


# --- Combined delta application ---------------------------------------------


def apply_profile_delta(
    profile: SessionProfile, delta: dict[str, Any], user_message: str
) -> SessionProfile:
    """Merge a leaf-returned `profile_delta` into the stored profile, with the
    budget-integrity and timeslot-sanitization guards applied in-place.
    Mutates and returns `profile`. `delta` is untrusted wire data — read-only,
    never mutated."""
    delta = dict(delta)

    # City change clears the geo anchors (S04 complement) — unless the SAME
    # delta also carries a fresh anchor, applied right after.
    if delta.get("city"):
        new_city = delta["city"]
        if profile.city and new_city != profile.city:
            profile.state_anchor = None
            profile.country_anchor = None
        profile.city = new_city
    if "state_anchor" in delta:
        profile.state_anchor = delta["state_anchor"]
    if "country_anchor" in delta:
        profile.country_anchor = delta["country_anchor"]

    # Budget integrity (P1): a bare-number reply is ALWAYS explicit, whatever
    # the delta's own source claim says.
    if delta.get("budget_max") is not None:
        new_budget = float(delta["budget_max"])
        profile.budget_max = new_budget
        source = delta.get("budget_request_source")
        if _bare_number_value(user_message) == new_budget:
            source = BUDGET_SOURCE_EXPLICIT
        if source is not None:
            profile.budget_request_source = source

    # Timeslot sanitization (P6): salvage a raw one-sided clock label into a
    # bound instead of persisting the corrupted string.
    if "timeslot" in delta:
        raw = delta.get("timeslot")
        normalized = _normalize_timeslot(raw) if raw else None
        if raw and normalized is None:
            start, end = _split_one_sided_clock(raw)
            if start:
                delta.setdefault("timeslot_start", start)
            if end:
                delta.setdefault("timeslot_end", end)
        else:
            profile.timeslot = normalized

    start_candidate = delta.get("timeslot_start")
    end_candidate = delta.get("timeslot_end")
    reject_start = bool(
        start_candidate
        and profile.timeslot_mode == "end_only"
        and profile.timeslot_end == start_candidate
        and not _mentions_explicit_time(user_message)
    )
    reject_end = bool(
        end_candidate
        and profile.timeslot_mode == "start_only"
        and profile.timeslot_start == end_candidate
        and not _mentions_explicit_time(user_message)
    )
    if start_candidate and not reject_start:
        profile.timeslot_start = start_candidate
    if end_candidate and not reject_end:
        profile.timeslot_end = end_candidate
    if (start_candidate and not reject_start) or (end_candidate and not reject_end):
        if profile.timeslot_start and profile.timeslot_end:
            profile.timeslot_mode = "range"
        elif profile.timeslot_start:
            profile.timeslot_mode = "start_only"
        elif profile.timeslot_end:
            profile.timeslot_mode = "end_only"
    if "timeslot_request_source" in delta:
        profile.timeslot_request_source = delta["timeslot_request_source"]

    if delta.get("amenities"):
        merged = list(profile.amenities)
        for amenity in delta["amenities"]:
            if amenity not in merged:
                merged.append(amenity)
        profile.amenities = merged

    if delta.get("language"):
        profile.language = delta["language"]

    return profile


def record_search_outcome(profile: SessionProfile, results_count: int) -> None:
    """Tracks the empty-search streak that feeds `maybe_auto_widen` — called
    once per search turn with the leaf's returned result count."""
    profile.consecutive_empty_searches = (
        0 if results_count > 0 else profile.consecutive_empty_searches + 1
    )
