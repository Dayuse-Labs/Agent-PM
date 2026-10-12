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


# ISO 4217 exceptions to the 2-decimal rule — the unit of MCP's `hotelPrice*`
# fields (minor units of `hotelCurrency`, as indexed by dayuse-com / moneyphp).
_ZERO_DECIMAL = frozenset({
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF",
    "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF",
})
_THREE_DECIMAL = frozenset({"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"})


def minor_units(currency: str) -> int:
    if currency in _ZERO_DECIMAL:
        return 0
    if currency in _THREE_DECIMAL:
        return 3
    return 2


def display_price_hotel(offer: Mapping[str, Any], hotel: Mapping[str, Any] | None) -> Any:
    """Same Booking Fees rule as `display_price_euro`, on the hotel-currency
    fields MCP exposes per offer (`hotelPrice` / `hotelPriceWithBookingFees`,
    minor units of `hotelCurrency`)."""
    if hotel is not None and hotel.get("showPricesWithoutBookingFees") is True:
        return offer.get("hotelPrice")
    with_fees = offer.get("hotelPriceWithBookingFees")
    return with_fees if with_fees is not None else offer.get("hotelPrice")


def format_minor_amount(amount: Any, currency: Any) -> str | None:
    """`"HKD 780.00"` from `(78000, "HKD")`, `"JPY 1600"` from `(1600, "JPY")`.
    The ISO code (not a glyph) is what the widget's price parser keys on."""
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        return None
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        return None
    code = currency.upper()
    decimals = minor_units(code)
    return f"{code} {amount / 10 ** decimals:.{decimals}f}"


def hotel_currency_price(
    offer: Mapping[str, Any], hotel: Mapping[str, Any] | None
) -> dict[str, Any]:
    """The offer's price in the hotel's own currency, ready to stamp on a card:
    `hotel_price` (formatted), `hotel_price_minor`, `hotel_currency_code`, and
    `hotel_original_price` (major units, only when a real discount). Empty when
    MCP sent no usable hotel-currency price."""
    currency = offer.get("hotelCurrency")
    amount = display_price_hotel(offer, hotel)
    formatted = format_minor_amount(amount, currency)
    if formatted is None:
        return {}
    code = str(currency).upper()
    fields: dict[str, Any] = {
        "hotel_price": formatted,
        "hotel_price_minor": amount,
        "hotel_currency_code": code,
    }
    original = offer.get("originalHotelPrice")
    if isinstance(original, int) and not isinstance(original, bool) and original > amount > 0:
        fields["hotel_original_price"] = round(original / 10 ** minor_units(code), 3)
    return fields


def has_unverified_zero_price(offer: Mapping[str, Any], hotel: Mapping[str, Any] | None) -> bool:
    """A zero indexed rate has no commercial proof of a free stay.

    The MCP contract currently exposes no explicit complimentary-rate authority.
    Keep positive alternatives; do not turn this sentinel into a cheapest quote
    or a booking choice. Missing prices retain their existing unknown behavior.
    """
    return display_price_euro(offer, hotel) == 0 or display_price_hotel(offer, hotel) == 0


def offer_totals(offer: Mapping[str, Any]) -> dict[str, int]:
    """The offer's fee-inclusive totals in minor units, keyed by currency: EUR
    always, plus the hotel's own currency when MCP indexes it. Whatever the
    hotel chooses to SHOW on its card, this is what the customer pays (before
    optional extras). A missing or non-positive quote is simply absent: never
    a total of zero, never derived from the fee-less price."""
    quotes = {"EUR": offer.get("priceEuroWithBookingFees")}
    code = offer.get("hotelCurrency")
    if isinstance(code, str) and code != "EUR" and len(code) == 3 and code.isascii() and code.isupper() and code.isalpha():
        quotes[code] = offer.get("hotelPriceWithBookingFees")
    return {code: value for code, value in quotes.items()
            if isinstance(value, int) and not isinstance(value, bool) and value > 0}
