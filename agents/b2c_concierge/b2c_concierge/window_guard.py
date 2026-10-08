"""guard_window_match (mcp-dayuse#8): every card shown as a match covers the
requested time slot, by the site rule (`b2c_common.timeslot`).

QA 2026-09-30, reproduced locally 2026-10-06: "Lyon demain de 22h01 à
23h01" showed three cards closing at 22:00, and the reply said "vous pouvez
réserver ce créneau". The leaf now filters with the same predicate; this is
the backstop on what actually reaches the screen, plus the closest-offers
disclosure the synthesis is known to drop.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from b2c_common.timeslot import parse_hhmm, requested_hours, slot_covers_window, window_fallback_line

# What must be said is that the cards are the CLOSEST offers (mcp-dayuse#4):
# "aucune ne couvre entièrement le créneau" alone leaves the cards unlabelled
# (seen live 2026-10-06). Coarse on purpose, like currency_guard: a missed
# paraphrase costs one extra honest sentence, never a silent claim.
_ALREADY_SAID_RE = re.compile(
    r"plus proches|closest|más cercan|più vicin|nächstgelegen|mais próxim|dichtstbij", re.IGNORECASE
)


def _card_covers(card: dict[str, Any], start: int | None, end: int | None) -> bool | None:
    """True/False when the card's slots say so, None when it carries none."""
    slots = [s for s in card.get("timeslots") or [] if isinstance(s, dict)]
    if not slots:
        return None
    for slot in slots:
        slot_start, slot_end = parse_hhmm(slot.get("start")), parse_hhmm(slot.get("end"))
        if slot_start is None or slot_end is None:
            continue
        if slot_covers_window(slot_start // 60, slot_end // 60, start, end):
            return True
    return False


def window_label(timeslot_start: str | None, timeslot_end: str | None) -> str:
    arrival, departure = requested_hours(parse_hhmm(timeslot_start), parse_hhmm(timeslot_end))
    if arrival is not None and departure is not None:
        return f"{arrival:02d}:00–{departure:02d}:00"
    hour = arrival if arrival is not None else departure
    return f"{hour:02d}:00" if hour is not None else ""


def enforce_window_match(
    results: list[dict[str, Any]], timeslot_start: str | None, timeslot_end: str | None
) -> tuple[list[dict[str, Any]], int]:
    """`(cards_to_show, dropped)`. Cards that do not cover the window are
    dropped; when that would leave nothing, all are kept (the caller then
    labels them as the closest offers). A card without slots is kept: it
    cannot be judged, and is not a claim about the time either."""
    start, end = parse_hhmm(timeslot_start), parse_hhmm(timeslot_end)
    if start is None and end is None:
        return results, 0
    kept = [c for c in results if not isinstance(c, dict) or _card_covers(c, start, end) is not False]
    dropped = len(results) - len(kept)
    if dropped and not kept:
        return results, dropped
    return kept, dropped


def enforce_window_disclosure(text: str, window: str, language: str) -> tuple[str, bool]:
    """Append the closest-offers sentence unless the answer already says no
    offer covers the slot."""
    if not text or _ALREADY_SAID_RE.search(text):
        return text, False
    return f"{text.rstrip()}\n\n{window_fallback_line(window, language)}", True


def requested_window_has_ended(
    cards: list[dict[str, Any]], served_date: Any, requested_end: str | None,
    *, requested_start: str | None = None, now: datetime | None = None,
) -> bool:
    """Prove the requested departure is past at every returned destination.

    An 08–20 offer can still be bookable at 16:10, but cannot satisfy a user's
    10–14 request today. Use the provider's hotel timezone, never the device's
    timezone or a country guess. Missing evidence does not establish expiry.
    This does not reject a still-usable slot just because its start is past.
    """
    end = parse_hhmm(requested_end)
    if not cards or end is None or end > 1440 or not isinstance(served_date, str):
        return False
    try:
        day = date.fromisoformat(served_date)
    except ValueError:
        return False
    start = parse_hhmm(requested_start)
    # A departure before arrival belongs to the following local calendar day.
    # Keep the requested arrival date intact; this only evaluates expiration.
    if start is not None and start <= 1440 and end < start:
        day += timedelta(days=1)
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        return False
    for card in cards:
        zone = card.get("timezone") if isinstance(card, dict) else None
        if not isinstance(zone, str) or not zone:
            return False
        try:
            local = instant.astimezone(ZoneInfo(zone))
        except (ValueError, ZoneInfoNotFoundError):
            return False
        if day > local.date() or (day == local.date() and end > local.hour * 60 + local.minute):
            return False
    return True


_PAST_WINDOW: dict[str, str] = {
    "en": "The requested time slot {window} on {day} has already ended at the destination. Which date would you like?",
    "fr": "Le créneau demandé {window} du {day} est déjà passé à destination. Pour quelle date souhaitez-vous chercher ?",
    "es": "La franja solicitada {window} del {day} ya ha terminado en el destino. ¿Para qué fecha quieres buscar?",
    "it": "La fascia richiesta {window} del {day} è già terminata a destinazione. Per quale data vuoi cercare?",
    "de": "Das gewünschte Zeitfenster {window} am {day} ist am Zielort bereits vorbei. Für welches Datum möchten Sie suchen?",
    "pt": "O horário solicitado {window} de {day} já terminou no destino. Para que data pretende pesquisar?",
    "nl": "Het gevraagde tijdslot {window} op {day} is op de bestemming al voorbij. Voor welke datum wil je zoeken?",
}


def past_window_question(start: str | None, end: str, day: str, language: str) -> str:
    from .date_format import format_date_human

    window = f"{start}–{end}" if start else end
    return _PAST_WINDOW.get(language, _PAST_WINDOW["en"]).format(
        window=window, day=format_date_human(day, language),
    )
