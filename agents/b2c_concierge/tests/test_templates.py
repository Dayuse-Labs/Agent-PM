"""templates.py — direct unit coverage for the booking-summary time display.

S-G6: `_format_time_slot`/`booking_offer_summary_response` used to force
":00" on every offer regardless of its real minutes (`start_hour`/`end_hour`
ints) — now takes already-formatted "HH:MM" strings.
"""
from __future__ import annotations

from b2c_concierge import templates


class TestFormatTimeSlot:
    def test_formats_hh_mm_strings_with_real_minutes(self):
        assert templates._format_time_slot("07:30", "13:30") == "07:30–13:30"

    def test_none_on_either_side_yields_none(self):
        assert templates._format_time_slot(None, "13:30") is None
        assert templates._format_time_slot("07:30", None) is None
        assert templates._format_time_slot(None, None) is None


class TestBookingOfferSummaryResponse:
    def test_includes_the_real_minute_precise_slot(self):
        text = templates.booking_offer_summary_response(
            hotel_name="Villa Paris Orly", date="2026-07-20",
            start_time="07:30", end_time="13:30", price="€54.00", language="en",
        )
        assert "07:30" in text and "13:30" in text
        assert "07:30–13:30" in text

    def test_omits_slot_entirely_when_offer_has_no_time(self):
        text = templates.booking_offer_summary_response(
            hotel_name="Villa Paris Orly", date="2026-07-20",
            start_time=None, end_time=None, price="€54.00", language="fr",
        )
        assert "créneau" not in text
