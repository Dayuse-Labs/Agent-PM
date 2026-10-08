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



def grounded_calendar(value: Any, message: str) -> dict | None:
    """Validate typed date components and their quote, without parsing intent."""
    if not isinstance(value, dict) or set(value) - {"day", "month", "year", "evidence"}:
        return None
    evidence = value.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip() or evidence not in message or len(evidence) > 160:
        return None
    # Numeric provenance only: the LLM decides whether these numbers are a date.
    # This is also compatible with ordinal suffixes and leading zeroes.
    numeric_parts = "".join(c if c.isascii() and c.isdigit() else " " for c in evidence).split()
    numbers = {int(part) for part in numeric_parts}
    day, month, year = (value.get(k) for k in ("day", "month", "year"))
    for component, low, high in ((day, 1, 31), (month, 1, 12), (year, 1900, 9999)):
        if component is None:
            continue
        if isinstance(component, bool) or not isinstance(component, int) or not low <= component <= high:
            return None
    if day is None or day not in numbers or (year is not None and year not in numbers):
        return None
    # A named month is interpreted semantically; numeric months must be quoted.
    # Day/month-only values with a written month are supported by the existing
    # calendar parser as well. Never accept a year without its month.
    if year is not None and month is None:
        return None
    return {"day": day, "month": month, "year": year, "evidence": evidence}


def resolve_calendar(value: dict, today: date) -> date | None:
    """Resolve missing calendar components in code; never calculate a weekday."""
    day, month, year = value["day"], value.get("month"), value.get("year")
    if year is not None:
        if month is None:
            return None
        try:
            return date(year, month, day)
        except (ValueError, TypeError):
            return None
    if month is not None:
        for candidate_year in range(today.year, min(today.year + 5, 10000)):
            try:
                candidate = date(candidate_year, month, day)
            except ValueError:
                continue
            if candidate >= today:
                return candidate
        return None
    for offset in range(13):
        month_index = today.year * 12 + today.month - 1 + offset
        try:
            candidate = date(month_index // 12, month_index % 12 + 1, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None
