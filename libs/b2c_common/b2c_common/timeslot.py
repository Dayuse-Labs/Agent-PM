"""The ONE definition of "this offer matches the requested time slot".

mcp-dayuse#4 / #8: the site, MCP and the leaf each had their own rule (the
leaf required the offer to fit INSIDE the window, the opposite of the site),
so "Lyon 12h–13h" answered "no offer covers it exactly" with five 08–14 /
10–16 offers on screen, and "22h01–23h01" showed offers closing at 22:00.

Site rule (`DurationQuery.php`, decision 2026-10-06): the offer CONTAINS the
window — it starts at or before the arrival hour and ends at or after the
departure hour, in whole hours. Requested minutes round to the NEAREST hour
(12h59 → 13h, 22h01 → 22h); equal bounds after rounding become a 1-hour
window; hours are capped at 24 (end of day).

Shared by the leaf (filter) and the concierge (`guard_window_match`), so the
two can never disagree.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def nearest_hour(minutes_of_day: int) -> int:
    return min((minutes_of_day + 30) // 60, 24)


def requested_hours(
    start_minutes: int | None, end_minutes: int | None
) -> tuple[int | None, int | None]:
    """(arrival_hour, departure_hour) for a window in minutes-of-day; either
    side may be None (one-sided request)."""
    arrival = min(nearest_hour(start_minutes), 23) if start_minutes is not None else None
    departure = nearest_hour(end_minutes) if end_minutes is not None else None
    if arrival is not None and departure is not None and departure <= arrival:
        departure = min(arrival + 1, 24)
    return arrival, departure


def slot_covers_window(
    slot_start_hour: Any, slot_end_hour: Any, start_minutes: int | None, end_minutes: int | None
) -> bool:
    """Whether a slot [start_hour, end_hour] contains the requested window.
    One-sided: the user can at least be there during the hour after the
    arrival (or before the departure). A slot whose hours cannot be read
    never matches — never assume a fit that cannot be verified."""
    try:
        slot_start, slot_end = int(slot_start_hour), int(slot_end_hour)
    except (TypeError, ValueError):
        return False
    if slot_end == 0 and slot_start > 0:
        slot_end = 24  # an offer ending at midnight
    arrival, departure = requested_hours(start_minutes, end_minutes)
    if arrival is None and departure is not None:
        arrival = departure - 1
    elif departure is None and arrival is not None:
        departure = arrival + 1
    if arrival is None or departure is None:
        return True
    return slot_start <= arrival and slot_end >= departure


def parse_hhmm(value: Any) -> int | None:
    """"HH:MM" → minutes of day, else None."""
    if not isinstance(value, str) or ":" not in value:
        return None
    hours, _, minutes = value.partition(":")
    try:
        h, m = int(hours), int(minutes)
    except ValueError:
        return None
    if not (0 <= h <= 24 and 0 <= m <= 59):
        return None
    return h * 60 + m


# mcp-dayuse#4/#8: names the window and never says "exactly" — the cards
# below it are the closest offers, labelled as such.
_WINDOW_FALLBACK: dict[str, str] = {
    "fr": "Aucune offre ne couvre tout le créneau {window} ; voici les offres les plus proches.",
    "en": "No offer covers the whole {window} time slot; here are the closest offers.",
    "es": "Ninguna oferta cubre toda la franja {window}; aquí tienes las más cercanas.",
    "it": "Nessuna offerta copre tutta la fascia {window}; ecco le offerte più vicine.",
    "de": "Kein Angebot deckt das ganze Zeitfenster {window} ab; hier sind die nächstgelegenen Angebote.",
    "pt": "Nenhuma oferta cobre todo o horário {window}; aqui estão as ofertas mais próximas.",
    "nl": "Geen enkel aanbod dekt het hele tijdslot {window}; hier zijn de dichtstbijzijnde aanbiedingen.",
}


def window_fallback_line(window: str, language: str) -> str:
    """The sentence that labels the cards as the closest offers when none
    covers the window — the leaf's outcome line and the concierge's backstop
    say it with the same words."""
    template = _WINDOW_FALLBACK.get(language, _WINDOW_FALLBACK["en"])
    return template.format(window=window).replace("  ", " ")


# --- Dayparts (decision Mathias 2026-10-06, option B; tightened 2026-10-29) ---
# "l'après-midi", "por la tarde": no clock time, so the site's covering rule
# cannot apply as is (it would demand an offer spanning the whole afternoon).
# Option B made a daypart a pure OVERLAP filter (MCP's own `timeSlot` rule):
# an 08:30-14:00 offer then passed for « domani pomeriggio » (side by side of
# 2026-10-29: 4 of 5 Rome cards were morning offers; time slot covered on 12
# of 25 checked cards, against 20 for agent-usa). Now an offer matches a
# daypart when it COVERS at least half of it (`DAYPART_MIN_HOURS`, whole hours
# rounded up): 10-16 or 14-20 is an afternoon, 08:30-14:00 is not. Still a
# fact of the offer's own hours, read the same way by the leaf (filter) and
# anything that checks a card. The search itself still asks MCP for the
# overlap (wider pool); the leaf keeps, per hotel, an offer that covers.
# Morning starts at 08:00 (was 06:00): day-use offers before 8 are rare, and a
# 6-hour morning would refuse the common 10:00 arrival (2 h of it).
DAYPART_HOURS: dict[str, tuple[int, int]] = {
    "morning": (8, 12),
    "afternoon": (12, 18),
    "evening": (18, 23),
}

#: Hours of the daypart an offer must cover: half of it, rounded up
#: (morning 2 h, afternoon 3 h, evening 3 h).
DAYPART_MIN_HOURS: dict[str, int] = {
    name: -(-(last - first) // 2) for name, (first, last) in DAYPART_HOURS.items()
}

# Accent-folded, lower-cased text. Spanish/Portuguese "mañana"/"tarde" alone
# also mean "tomorrow"/"late": only their daypart constructions count.
_DAYPART_RES: dict[str, re.Pattern[str]] = {
    "morning": re.compile(
        r"\b(?:matin|matinee|morning|(?:por|de|en) la manana|mattin[ao]|vormittags?"
        r"|morgens|am morgen|(?:de|pela|a) manha|ochtend|s ochtends)\b"
    ),
    "afternoon": re.compile(
        r"\b(?:apres[ -]midi|aprem|afternoon|(?:por|de|en|a) la tarde|(?:a|de|pela) tarde"
        r"|pomeriggio|nachmittags?|middag|s middags)\b"
    ),
    "evening": re.compile(
        r"\b(?:soir|soiree|evening|tonight|(?:por|de|en) la noche|(?:a|de|pela) noite"
        # Italian "sera" only in its daypart constructions: bare, it is
        # also French "(ce) sera".
        r"|(?:la|di|in) sera|serata|stasera|abends?|am abend|avond|s avonds)\b"
    ),
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().replace("'", " ")


def daypart_in(text: str) -> str | None:
    """The ONE daypart the text names, else None (none, or several)."""
    folded = _fold(text or "")
    found = [name for name, pattern in _DAYPART_RES.items() if pattern.search(folded)]
    return found[0] if len(found) == 1 else None


def slot_overlaps_daypart(slot_start_hour: Any, slot_end_hour: Any, daypart: str) -> bool:
    """Part of the slot falls inside the daypart (touching bounds do not
    count: an 08-12 offer is not an afternoon offer)."""
    hours = DAYPART_HOURS.get(daypart)
    if hours is None:
        return False
    try:
        slot_start, slot_end = int(slot_start_hour), int(slot_end_hour)
    except (TypeError, ValueError):
        return False
    if slot_end == 0 and slot_start > 0:
        slot_end = 24
    return slot_start < hours[1] and slot_end > hours[0]


def slot_covers_daypart(slot_start_hour: Any, slot_end_hour: Any, daypart: str) -> bool:
    """The slot covers at least `DAYPART_MIN_HOURS[daypart]` hours of the
    daypart (2026-10-29). An offer ending at or before its start runs past
    midnight: it covers until the end of the day. A slot whose hours cannot be
    read never matches."""
    hours = DAYPART_HOURS.get(daypart)
    if hours is None:
        return False
    try:
        slot_start, slot_end = int(slot_start_hour), int(slot_end_hour)
    except (TypeError, ValueError):
        return False
    if slot_end <= slot_start:
        slot_end = 24
    covered = min(slot_end, hours[1]) - max(slot_start, hours[0])
    return covered >= DAYPART_MIN_HOURS[daypart]
