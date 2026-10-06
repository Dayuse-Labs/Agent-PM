"""b2c_common.timeslot — the one "offer matches the slot" rule (site parity,
mcp-dayuse#4/#8). The table is the shared oracle: offers × windows → expected."""
from __future__ import annotations

import pytest

from b2c_common.timeslot import requested_hours, slot_covers_window, window_fallback_line


def _m(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


@pytest.mark.parametrize(
    "slot,window,expected",
    [
        # QA Lyon 12h–13h: offers that contain the window match.
        ((8, 14), ("12:00", "13:00"), True),
        ((10, 16), ("12:00", "13:00"), True),
        ((11, 17), ("12:00", "13:00"), True),
        ((13, 18), ("12:00", "13:00"), False),  # starts after arrival
        # Window equal to the offer.
        ((12, 13), ("12:00", "13:00"), True),
        # QA Lyon 6h–16h: the site finds nothing (capture prod 05/10).
        ((8, 14), ("06:00", "16:00"), False),
        ((10, 16), ("06:00", "16:00"), False),
        # QA 22h01–23h01 → 22h–23h.
        ((17, 22), ("22:01", "23:01"), False),
        ((17, 23), ("22:01", "23:01"), True),
        # 12h59 → 13h; equal bounds after rounding → a 1-hour window.
        ((13, 14), ("12:59", "13:10"), True),
        ((12, 13), ("12:59", "13:10"), False),
        # One-sided.
        ((10, 17), ("14:00", None), True),
        ((8, 14), ("14:00", None), False),
        ((8, 14), (None, "14:00"), True),
        # Offer ending at midnight; unreadable slot never matches.
        ((18, 0), ("22:00", "23:30"), True),
        ((None, 14), ("12:00", "13:00"), False),
        # No window at all: everything matches.
        ((8, 14), (None, None), True),
    ],
)
def test_oracle(slot, window, expected):
    start = _m(window[0]) if window[0] else None
    end = _m(window[1]) if window[1] else None
    assert slot_covers_window(slot[0], slot[1], start, end) is expected


def test_requested_hours_caps_late_windows():
    assert requested_hours(_m("23:30"), None) == (23, None)
    assert requested_hours(_m("23:30"), _m("23:40")) == (23, 24)


def test_fallback_line_has_no_exactly():
    assert window_fallback_line("06:00–16:00", "fr") == (
        "Aucune offre ne couvre tout le créneau 06:00–16:00 ; voici les offres les plus proches."
    )


# --- dayparts: the soft filter (option B, 2026-10-06) ------------------------
from b2c_common.timeslot import daypart_in, slot_overlaps_daypart  # noqa: E402


@pytest.mark.parametrize(
    "text,expected",
    [
        ("un hôtel à Lyon l'après-midi", "afternoon"),
        ("busco un hotel en madrid mañana por la tarde", "afternoon"),
        ("am Nachmittag in Berlin", "afternoon"),
        ("à tarde em Lisboa", "afternoon"),
        ("demain matin à Lyon", "morning"),
        ("por la mañana en Madrid", "morning"),
        ("ce soir à Paris", "evening"),
        ("stasera a Roma", "evening"),
        # Not dayparts.
        ("mañana en Madrid", None),  # tomorrow
        ("llego tarde", None),  # late
        ("ce sera pour 2 personnes", None),  # French "sera"
        ("matin ou soir", None),  # two of them: nothing certain
        ("de 12h à 13h", None),
    ],
)
def test_daypart_in(text, expected):
    assert daypart_in(text) == expected


@pytest.mark.parametrize(
    "slot,daypart,expected",
    [
        ((10, 16), "afternoon", True),
        ((8, 12), "afternoon", False),  # touching is not overlapping
        ((8, 14), "afternoon", True),
        ((17, 23), "evening", True),
        ((8, 14), "evening", False),
        ((18, 0), "evening", True),  # ends at midnight
        ((7, 10), "morning", True),
        ((None, 10), "morning", False),
    ],
)
def test_slot_overlaps_daypart(slot, daypart, expected):
    assert slot_overlaps_daypart(slot[0], slot[1], daypart) is expected
