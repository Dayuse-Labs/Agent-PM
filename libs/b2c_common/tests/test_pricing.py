"""Booking Fees (QA n°6, product rule 2026-09-23): the displayed price follows
the hotel's `showPricesWithoutBookingFees` — `true` → `priceEuro`, otherwise
`priceEuroWithBookingFees` (falling back to `priceEuro` when it is missing)."""
from __future__ import annotations

from b2c_common import (
    display_price_euro,
    display_price_hotel,
    format_minor_amount,
    hotel_currency_price,
    minor_units,
)

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


class TestHotelCurrencyPrice:
    OFFER = {
        "hotelCurrency": "HKD",
        "hotelPrice": 78000,
        "hotelPriceWithBookingFees": 80500,
        "originalHotelPrice": 160000,
    }

    def test_same_booking_fees_rule_as_the_eur_price(self):
        assert display_price_hotel(self.OFFER, {}) == 80500
        assert display_price_hotel(self.OFFER, {"showPricesWithoutBookingFees": True}) == 78000

    def test_formatting_follows_iso_minor_units(self):
        assert minor_units("JPY") == 0 and minor_units("BHD") == 3 and minor_units("HKD") == 2
        assert format_minor_amount(78000, "HKD") == "HKD 780.00"
        assert format_minor_amount(1600, "JPY") == "JPY 1600"
        assert format_minor_amount(4300, "BHD") == "BHD 4.300"
        assert format_minor_amount(None, "HKD") is None
        assert format_minor_amount(100, "EURO") is None

    def test_card_fields(self):
        assert hotel_currency_price(self.OFFER, {}) == {
            "hotel_price": "HKD 805.00",
            "hotel_price_minor": 80500,
            "hotel_currency_code": "HKD",
            "hotel_original_price": 1600.0,
        }

    def test_nothing_without_a_usable_hotel_currency_price(self):
        assert hotel_currency_price({"priceEuro": 9500}, {}) == {}
