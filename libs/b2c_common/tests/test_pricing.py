"""Booking Fees (QA n°6, product rule 2026-09-23): the displayed price follows
the hotel's `showPricesWithoutBookingFees` — `true` → `priceEuro`, otherwise
`priceEuroWithBookingFees` (falling back to `priceEuro` when it is missing)."""
from __future__ import annotations

from b2c_common import display_price_euro

_OFFER = {"priceEuro": 9500, "priceEuroWithBookingFees": 10400}


class TestDisplayPriceEuro:
    def test_flag_true_shows_the_price_without_fees(self):
        assert display_price_euro(_OFFER, {"showPricesWithoutBookingFees": True}) == 9500

    def test_flag_false_shows_the_price_with_fees(self):
        assert display_price_euro(_OFFER, {"showPricesWithoutBookingFees": False}) == 10400

    def test_flag_absent_shows_the_price_with_fees(self):
        assert display_price_euro(_OFFER, {}) == 10400
        assert display_price_euro(_OFFER, None) == 10400

    def test_missing_fee_price_falls_back_to_price_euro(self):
        # A card must never lose its price over an absent field.
        assert display_price_euro({"priceEuro": 9500}, {}) == 9500

    def test_only_a_real_true_counts(self):
        assert display_price_euro(_OFFER, {"showPricesWithoutBookingFees": "true"}) == 10400
