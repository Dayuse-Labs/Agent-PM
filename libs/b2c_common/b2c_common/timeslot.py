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
