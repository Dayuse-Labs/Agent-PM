"""Shared calendar resolution of semantic labels, never customer text parsing."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

def resolve_relative_day(value: Any, today: date) -> date | None:
    v = str(value or "").strip().lower()
    if v == "today":
        return today
    if v == "tomorrow":
        return today + timedelta(days=1)
    if v == "day_after_tomorrow":
        return today + timedelta(days=2)
    if v in WEEKDAYS:
        delta = (WEEKDAYS[v] - today.weekday()) % 7
        return today + timedelta(days=delta or 7)  # "next X" excludes today itself
    return None

