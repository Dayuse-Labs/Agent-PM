"""A daypart is covered, not touched (2026-10-29): an offer matches when it
covers half of the daypart, whole hours rounded up."""
from b2c_common.timeslot import DAYPART_HOURS, DAYPART_MIN_HOURS, slot_covers_daypart


def test_half_of_each_daypart_rounded_up():
    assert DAYPART_HOURS["morning"] == (8, 12)
    assert DAYPART_MIN_HOURS == {"morning": 2, "afternoon": 3, "evening": 3}


def test_a_morning_offer_is_not_an_afternoon_offer():
    # Rome, side by side 2026-10-29: 08:30-14:00, 09:00-13:00, 11:30-15:00 for « pomeriggio ».
    assert not slot_covers_daypart(8, 14, "afternoon")
    assert not slot_covers_daypart(9, 13, "afternoon")
    assert slot_covers_daypart(11, 15, "afternoon")


def test_offers_that_cover_the_afternoon():
    assert slot_covers_daypart(10, 16, "afternoon")
    assert slot_covers_daypart(14, 20, "afternoon")


def test_the_usual_10_oclock_arrival_is_a_morning():
    assert slot_covers_daypart(10, 17, "morning")
    assert not slot_covers_daypart(11, 17, "morning")


def test_an_offer_running_past_midnight_covers_the_evening():
    assert slot_covers_daypart(20, 8, "evening")
    assert slot_covers_daypart(19, 0, "evening")
    assert not slot_covers_daypart(16, 20, "evening")


def test_unreadable_hours_or_an_unknown_daypart_never_match():
    assert not slot_covers_daypart(None, 17, "afternoon")
    assert not slot_covers_daypart(10, 17, "night")
