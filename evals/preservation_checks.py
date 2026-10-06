"""Independent checks on displayed offers against explicitly annotated needs.

These checks do not infer intent from an old model's filters or parse natural
language. A mismatch measures the displayed offer, not whether a disclosed
alternative is an acceptable answer. No results or missing fields are not passes.
No production ranking/date/filter implementation is imported.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any


def _minutes(value: Any) -> int | None:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d|24:00", value):
        return None
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _window(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        return None
    start, end = _minutes(value.get("start")), _minutes(value.get("end"))
    if start is None or end is None or start >= end:
        return None  # Cross-midnight stays need explicit dated intervals.
    return start, end


def _date(value: Any) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _slot_covers(hotel: dict, required: tuple[int, int]) -> bool | None:
    slots = hotel.get("timeslots")
    if not isinstance(slots, list) or not slots:
        return None
    parsed = [_window(slot) for slot in slots]
    if any(slot is not None and slot[0] <= required[0] and slot[1] >= required[1] for slot in parsed):
        return True
    # A known covering slot is sufficient; missing slots cannot prove absence.
    return None if any(slot is None for slot in parsed) else False


def _result(name: str, values: list[bool | None]) -> dict:
    return {
        "check": name,
        "status": "fail" if False in values else "skipped" if not values or None in values else "pass",
        "displayed_cards": len(values),
        "verified_matching_cards": sum(v is True for v in values),
        "verified_mismatching_cards": sum(v is False for v in values),
        "unverifiable_cards": sum(v is None for v in values),
        "scope": "displayed offer agreement only; alternatives and overall answer quality need separate review",
    }


def check_displayed_offers(response: dict | None, expected: dict) -> list[dict]:
    """Score only declared requirements; reject unsupported/invalid oracles.

    Schema: ``offer_date: YYYY-MM-DD`` and/or
    ``stay_window: {start: HH:MM, end: HH:MM}`` (same day, 24:00 allowed as end).
    Expectations must come from reviewed user intent, not generated filters.
    Dates are display consistency, not proof of historical inventory/eligibility.
    """
    unsupported = set(expected) - {"offer_date", "stay_window"}
    if unsupported:
        raise ValueError(f"unsupported offer expectations: {sorted(unsupported)}")
    wanted_date = _date(expected.get("offer_date"))
    wanted_window = _window(expected.get("stay_window"))
    if "offer_date" in expected and wanted_date is None:
        raise ValueError("offer_date must be a valid explicit ISO date")
    if "stay_window" in expected and wanted_window is None:
        raise ValueError("stay_window requires an increasing same-day HH:MM interval")
    raw = response.get("hotels") if isinstance(response, dict) else None
    hotels = raw if isinstance(raw, list) else []
    checks = []
    if wanted_date is not None:
        values = []
        for hotel in hotels:
            actual = _date(hotel.get("offer_date")) if isinstance(hotel, dict) else None
            values.append(actual == wanted_date if actual is not None else None)
        checks.append(_result("displayed_offer_date", values))
    if wanted_window is not None:
        checks.append(_result("displayed_offer_covers_stay", [
            _slot_covers(h, wanted_window) if isinstance(h, dict) else None for h in hotels
        ]))
    return checks
