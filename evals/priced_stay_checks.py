"""Compare explicit budget/stay requirements across legacy and B2C cards.

Only amounts attached to the same offer may satisfy a combined requirement.
No exchange rates, generated match scores, or production filters are used.
"""
from __future__ import annotations

from decimal import Decimal

from evals.preservation_checks import _cards, _number, _price, _result, _window


# Explicitly supported by this audit's annotated budgets. Other currencies
# remain unknown instead of assuming that every ISO currency has two decimals.
_MINOR_SCALE = {"EUR": 100, "USD": 100, "GBP": 100, "CAD": 100, "AUD": 100}


def _legacy_price(slot: dict, currency: str) -> float | None:
    value = _number(slot.get("price"))
    if value is None or slot.get("currency") != currency or currency not in _MINOR_SCALE:
        return None
    minor = Decimal(str(value)) * _MINOR_SCALE[currency]
    return float(minor) if minor == minor.to_integral_value() else None


def check_priced_stays(response: dict | None, expected: dict, *, schema: str) -> dict:
    """Check each card has an offer satisfying budget and optional stay jointly.

Legacy slot prices are major units with their own explicit currency. B2C's
canonical card amount describes its single selected slot; it cannot be joined
to multiple slots. Prices are displayed amounts, not a total-inclusive quote.
Unknown currency/price/slot fields cannot prove failure or success. A disclosed
alternative may still be useful: this is not an overall response-quality grade.
"""
    if schema not in {"legacy", "b2c"}:
        raise ValueError("explicit legacy or b2c schema required")
    if set(expected) - {"budget", "stay_window"} or "budget" not in expected:
        raise ValueError("budget and optional stay_window required")
    budget = expected["budget"]
    if not isinstance(budget, dict) or set(budget) != {"currency", "max_minor"}:
        raise ValueError("budget requires currency and max_minor")
    currency, limit = budget["currency"], _number(budget["max_minor"])
    if not isinstance(currency, str) or currency not in _MINOR_SCALE or limit is None or limit <= 0 or limit != int(limit):
        raise ValueError("supported explicit currency and positive integer minor limit required")
    required = _window(expected.get("stay_window"))
    if "stay_window" in expected and required is None:
        raise ValueError("stay_window requires increasing same-day HH:MM interval")
    values = []
    for card in _cards(response):
        if not isinstance(card, dict):
            values.append(None)
            continue
        slots = card.get("timeslots")
        if not isinstance(slots, list) or not slots:
            values.append(None)
            continue
        offers = []
        for slot in slots:
            if not isinstance(slot, dict):
                offers.append(None)
                continue
            price = (_legacy_price(slot, currency) if schema == "legacy"
                     else _price(card, currency) if len(slots) == 1 else None)
            window = _window(slot)
            priced = None if price is None else price <= limit
            covered = (True if required is None else None if window is None
                       else window[0] <= required[0] and window[1] >= required[1])
            offers.append(False if priced is False or covered is False
                          else None if priced is None or covered is None else True)
        values.append(True if True in offers else None if None in offers else False)
    result = _result("displayed_priced_stay" if required else "displayed_offer_budget", values)
    result["price_basis"] = "same-offer displayed amount; no FX or inferred fees"
    return result
