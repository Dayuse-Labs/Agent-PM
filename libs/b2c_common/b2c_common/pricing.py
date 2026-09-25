"""Which MCP price an offer displays (Booking Fees, QA n°6 — product rule 2026-09-23).

MCP_B2C sends two EUR-cents prices per offer: `priceEuro` (without booking
fees) and `priceEuroWithBookingFees`. Which one the customer sees is a
per-hotel back-office setting, `showPricesWithoutBookingFees` (boolean, root of
the hotel document): `true` → `priceEuro`, otherwise
`priceEuroWithBookingFees`. The agent used to display `priceEuro` everywhere,
while MCP filters the budget and sorts on the fee-included price — a card could
show less than the customer would pay.

Shared lib on purpose: the search leaf and the concierge must pick the SAME
price, or the card, the booking card and the reply disagree on one hotel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def display_price_euro(offer: Mapping[str, Any], hotel: Mapping[str, Any] | None) -> Any:
    """The raw EUR-cents price to display for `offer` of `hotel` (same unit and
    shape as MCP's fields — callers format it as before). Falls back to
    `priceEuro` when the fee-included price is missing, so a card never loses
    its price over an absent field."""
    if hotel is not None and hotel.get("showPricesWithoutBookingFees") is True:
        return offer.get("priceEuro")
    with_fees = offer.get("priceEuroWithBookingFees")
    return with_fees if with_fees is not None else offer.get("priceEuro")
