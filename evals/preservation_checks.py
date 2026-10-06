"""Independent checks on displayed offers against explicitly annotated needs.

These checks do not infer intent from an old model's filters or parse natural
language. A mismatch measures the displayed offer, not whether a disclosed
alternative is an acceptable answer. No results or missing fields are not passes.
No production ranking/date/filter implementation is imported.
"""
from __future__ import annotations

import re
import math
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


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _cards(response: dict | None) -> list[Any]:
    value = response.get("hotels") if isinstance(response, dict) else None
    return value if isinstance(value, list) else []


def _price(card: Any, currency: str) -> float | None:
    if not isinstance(card, dict):
        return None
    if currency == "EUR":
        return _number(card.get("price_eur_cents"))
    if card.get("hotel_currency_code") == currency:
        return _number(card.get("hotel_price_minor"))
    return None  # Market currency does not describe the EUR numeric price.


def check_search_cards(response: dict | None, expected: dict) -> list[dict]:
    """Check explicitly annotated constraints on the actual displayed cards.

    Carryover is expressed by annotating each follow-up turn independently.
    This function never treats generated active_filters as proof of relevance.
    Budget is in currency-specific minor units; no implicit conversion occurs.
    Amenity inclusion, geography and acceptable alternatives need source review.
    """
    allowed = {"offer_date", "stay_window", "capacity_min", "stars_min", "budget"}
    if set(expected) - allowed:
        raise ValueError("unsupported search-card expectation")
    checks = check_displayed_offers(response, {
        k: v for k, v in expected.items() if k in {"offer_date", "stay_window"}
    })
    cards = _cards(response)
    for oracle, field in (("capacity_min", "capacity"), ("stars_min", "stars")):
        if oracle not in expected:
            continue
        required = _number(expected[oracle])
        if required is None or required <= 0 or required != int(required):
            raise ValueError(f"{oracle} must be a positive integer")
        if oracle == "stars_min" and required > 5:
            raise ValueError("stars_min cannot exceed five")
        values = []
        for card in cards:
            actual = _number(card.get(field)) if isinstance(card, dict) else None
            values.append(None if actual is None else actual >= required)
        checks.append(_result(f"displayed_{oracle}", values))
    if "budget" in expected:
        budget = expected["budget"]
        if not isinstance(budget, dict) or set(budget) != {"currency", "max_minor"}:
            raise ValueError("budget requires currency and max_minor")
        currency, limit = budget["currency"], _number(budget["max_minor"])
        if not isinstance(currency, str) or not re.fullmatch("[A-Z]{3}", currency):
            raise ValueError("budget currency must be an explicit three-letter code")
        if limit is None or limit <= 0 or limit != int(limit):
            raise ValueError("budget max_minor must be a positive integer")
        prices = [_price(card, currency) for card in cards]
        checks.append(_result("displayed_budget", [None if v is None else v <= limit for v in prices]))
    return checks


def check_search_transition(previous: dict | None, current: dict | None, requirement: str) -> dict:
    """Compare two displayed shortlists for an explicitly annotated follow-up.

    A failed comparison means no observed cheaper/new hotel, not an incorrect
    answer: honestly explaining no alternative may satisfy the conversation.
    The caller must select the relevant prior turn; no dialogue intent is guessed.
    """
    old, new = _cards(previous), _cards(current)
    if requirement not in {"cheaper_option", "new_hotel"}:
        raise ValueError("unsupported search transition")
    status = "skipped"
    reason = "missing comparable cards"
    if old and new and requirement == "cheaper_option":
        before, after = [_price(c, "EUR") for c in old], [_price(c, "EUR") for c in new]
        if all(v is not None for v in before):
            floor = min(v for v in before if v is not None)
            if any(v is not None and v < floor for v in after):
                status, reason = "pass", "at least one displayed option is strictly cheaper in EUR"
            elif all(v is not None for v in after):
                status, reason = "fail", "no displayed option is cheaper than the previous minimum"
    if old and new and requirement == "new_hotel":
        def identity(card: Any) -> str | None:
            value = card.get("hotel_id", card.get("id")) if isinstance(card, dict) else None
            return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value) else None

        before_ids, after_ids = [identity(c) for c in old], [identity(c) for c in new]
        if all(v is not None for v in before_ids):
            if any(v is not None and v not in before_ids for v in after_ids):
                status, reason = "pass", "at least one new displayed hotel identity"
            elif all(v is not None for v in after_ids):
                status, reason = "fail", "all displayed hotel identities were already shown"
    return {"check": requirement, "status": status, "reason": reason,
            "previous_cards": len(old), "current_cards": len(new),
            "scope": "displayed shortlist change only; full answer and alternative disclosure require review"}
