"""Grounded edits persist explicit constraints before a remote search can fail."""
from __future__ import annotations

import math
from typing import Any

from .profile import BUDGET_SOURCE_EXPLICIT, SessionProfile


def _clock(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    h, m = value.split(":")
    return h.isascii() and m.isascii() and h.isdecimal() and m.isdecimal() and int(h) < 24 and int(m) < 60


def parse_search_update(value: Any, message: str) -> dict:
    if not isinstance(value, dict):
        return {}
    out = {}
    for field in ("budget_max", "timeslot_start", "timeslot_end"):
        item = value.get(field)
        if not isinstance(item, dict) or "value" not in item:
            continue
        evidence = item.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip() or evidence.strip().casefold() not in message.casefold():
            continue
        val = item["value"]
        if field == "budget_max":
            if item.get("currency") not in (None, "EUR"):
                continue  # The MCP cap is EUR; no invented currency conversion.
            if val is not None and (isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0):
                continue
        elif not _clock(val):
            continue
        out[field] = val
    return out


def apply_search_update(profile: SessionProfile, update: dict | None, budget_action: str | None = None) -> None:
    if not update:
        return
    budget_edit_allowed = budget_action not in {"retain", "cheaper"}
    if budget_action == "set" and update.get("budget_max") is None:
        budget_edit_allowed = False
    if budget_action == "clear" and update.get("budget_max") is not None:
        budget_edit_allowed = False
    if budget_edit_allowed and "budget_max" in update and profile.display_currency in (None, "EUR"):
        profile.budget_max = update["budget_max"]
        profile.budget_request_source = BUDGET_SOURCE_EXPLICIT
    if "timeslot_start" in update or "timeslot_end" in update:
        start = update.get("timeslot_start", profile.timeslot_start)
        end = update.get("timeslot_end", profile.timeslot_end)
        if start and end and start >= end:
            return  # An overnight stay must not become an inverted day window.
        profile.timeslot_start, profile.timeslot_end = start, end
        profile.timeslot = f"{start}-{end}" if start and end else None
        profile.timeslot_mode = "range" if start and end else "start_only" if start else "end_only" if end else None
        profile.timeslot_request_source = BUDGET_SOURCE_EXPLICIT


def protect_explicit_constraints(profile: SessionProfile, delta: dict) -> dict:
    """A leaf's fresh extraction cannot erase an already committed user edit.

    Managed turns extract edits in triage. The leaf still owns retrieval and
    resolved dates, but has no authority to reinterpret the user's cap/window.
    """
    protected: set[str] = set()
    if profile.budget_request_source == BUDGET_SOURCE_EXPLICIT:
        protected.update(("budget_max", "budget_request_source"))
    if profile.timeslot_request_source == BUDGET_SOURCE_EXPLICIT:
        protected.update(("timeslot", "timeslot_start", "timeslot_end", "timeslot_request_source"))
    return {k: v for k, v in delta.items() if k not in protected}
