"""The date the user asked for, read in code (mcp-dayuse#8, `guard_date_served`).

QA 2026-09-30 (Côte d'Azur): "le 3 octobre" was asked, the leaf asked which
Côte d'Azur first, and the search on the next turn ran on today. The leaf is
stateless and only ever labels a date inside a `search_offers` call, so a turn
that ends on a clarification never stored the date. Reproduced locally on
2026-10-06 ("le 10 octobre" → offers for the 6th, announced as such).

`parse_requested_date` reads an UNAMBIGUOUS date from the message — relative
day, "10 octobre" / "October 10", ISO — in the 7 reply languages. Anything it
is not sure about (weekdays, a bare "le 3", two different dates) is None: it
is the FACT the guard checks against, so it must never guess. Grounded semantic
weekday labels from triage supplement it in `expected_search_date`.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from b2c_common.date_labels import resolve_relative_day

from .date_format import _MONTHS, _WEEKDAYS, format_date_human

# Month name (accent-free, lower case) → month number, incl. common
# abbreviations. Built from date_format's 7-language tables.
_MONTH_NUMBERS: dict[str, int] = {}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


for _names in _MONTHS.values():
    for _index, _name in enumerate(_names, start=1):
        _MONTH_NUMBERS[_fold(_name)] = _index
for _abbr, _index in {
    "jan": 1, "janv": 1, "feb": 2, "fev": 2, "fevr": 2, "mar": 3, "apr": 4, "avr": 4,
    "jun": 6, "jul": 7, "juil": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "okt": 10,
    "nov": 11, "dec": 12, "dez": 12,
}.items():
    _MONTH_NUMBERS.setdefault(_abbr, _index)

_MONTH_ALT = "|".join(sorted(_MONTH_NUMBERS, key=len, reverse=True))

# "10 octobre", "10. Oktober", "10 de octubre", "1er mai", "3rd of October"
_DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})(?:er|st|nd|rd|th|º|°|\.)?\s+(?:de\s+|of\s+)?(" + _MONTH_ALT + r")\.?\b"
    r"(?:\s+(?:de\s+)?(\d{4}))?"
)
# "October 10", "Oct 10th, 2026". Not for words that are also common verbs or
# nouns in that position ("I may 2…", "mar" = sea in Spanish).
_MONTH_FIRST_EXCLUDED = {"may", "mai", "mar", "mars"}
_MONTH_DAY_RE = re.compile(
    r"\b("
    + "|".join(m for m in sorted(_MONTH_NUMBERS, key=len, reverse=True) if m not in _MONTH_FIRST_EXCLUDED)
    + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?"
)
# "du 10 au 12 octobre", "10-12 Oct": a range is not one day.
_RANGE_RE = re.compile(
    r"\b\d{1,2}(?:er|st|nd|rd|th)?\s*(?:-|au|a|al|to|bis|tot|et|and|y|e|und|en|ou|or)\s*\d{1,2}"
    r"(?:er|st|nd|rd|th|\.)?\s+(?:de\s+)?(?:" + _MONTH_ALT + r")\b"
)
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

# Relative days. "mañana" / "Morgen" also mean "morning": only taken when not
# preceded by an article that makes them the noun.
_RELATIVE: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\b(?:apres[- ]demain|day after tomorrow|pasado manana|dopodomani"
                r"|ubermorgen|depois de amanha|overmorgen)\b"), 2),
    (re.compile(r"\b(?:demain|tomorrow|domani|amanha|morgen)\b"), 1),
    (re.compile(r"(?<!la )(?<!esta )(?<!por la )\bmanana\b"), 1),
    (re.compile(r"\b(?:aujourd.hui|today|tonight|ce soir|hoy|oggi|heute|hoje|vandaag)\b"), 0),
)
_MORNING_NOUN_RE = re.compile(r"\b(?:am|guten|goede|heute)\s+morgen\b|\bgoedemorgen\b|\bmorgens\b")


def reference_today(client_timezone: Any) -> date:
    """Same anchor as the leaf's `datetime_resolver.reference_today`: the
    client's timezone when known and valid, else the server's date."""
    if isinstance(client_timezone, str) and client_timezone:
        try:
            return datetime.now(ZoneInfo(client_timezone)).date()
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return date.today()


def _next_occurrence(month: int, day: int, today: date) -> date | None:
    """Mirrors the leaf: a past month/day rolls to next year."""
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    if candidate < today:
        try:
            return date(today.year + 1, month, day)
        except ValueError:
            return None
    return candidate


def _dated(day: str, month: int, year: str | None, today: date) -> date | None:
    if year:
        try:
            return date(int(year), month, int(day))
        except ValueError:
            return None
    return _next_occurrence(month, int(day), today)


def parse_requested_date(message: str, today: date) -> date | None:
    """The one date the message asks for, or None when there is none or it
    is not certain. A past explicit date is returned as-is: the leaf floors
    it, and the caller decides what a past request means."""
    text = _fold(message or "")
    if _RANGE_RE.search(text):
        return None
    found: set[date] = set()
    for match in _ISO_RE.finditer(text):
        try:
            found.add(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            return None
    for match in _DAY_MONTH_RE.finditer(text):
        resolved = _dated(match.group(1), _MONTH_NUMBERS[match.group(2)], match.group(3), today)
        if resolved is None:
            return None
        found.add(resolved)
    for match in _MONTH_DAY_RE.finditer(text):
        resolved = _dated(match.group(2), _MONTH_NUMBERS[match.group(1)], match.group(3), today)
        if resolved is None:
            return None
        found.add(resolved)
    # "heute Morgen" is this morning: keep the "heute", drop the noun.
    relative_text = _MORNING_NOUN_RE.sub(
        lambda m: " heute " if m.group(0).startswith("heute") else " ", text
    )
    for pattern, offset in _RELATIVE:
        if pattern.search(relative_text):
            found.add(today + timedelta(days=offset))
            relative_text = pattern.sub(" ", relative_text)
    if len(found) != 1:
        return None
    return found.pop()


_WEEKDAY_ALT = "|".join(
    sorted({_fold(name).split("-")[0] for names in _WEEKDAYS.values() for name in names}, key=len, reverse=True)
)
_ANY_DATE_HINT_RE = re.compile(
    r"\b(?:" + _WEEKDAY_ALT + "|" + _MONTH_ALT + r")\b"
    r"|\b(?:le|the|el|il|der|den|o|de)\s+\d{1,2}(?:er|st|nd|rd|th|\.)?\b(?!\s*h)"
    r"|\b\d{1,2}[/.]\d{1,2}\b|\b\d{4}-\d{2}-\d{2}\b"
)


def mentions_a_date(message: str, today: date) -> bool:
    """Whether the message says ANYTHING about a day — even one
    `parse_requested_date` will not resolve (a weekday, "le 3"). When it does,
    the leaf may legitimately search another day than the carried one."""
    text = _fold(message or "")
    if parse_requested_date(message, today) is not None or _ANY_DATE_HINT_RE.search(text):
        return True
    return any(pattern.search(text) for pattern, _ in _RELATIVE)


_SERVED_NOTICE: dict[str, str] = {
    "fr": "Attention : ces offres sont pour le {served}, pas pour le {requested} que vous avez demandé. "
    "Dites-moi si je relance la recherche pour le {requested}.",
    "en": "Please note: these offers are for {served}, not {requested} as you asked. "
    "Let me know if I should search again for {requested}.",
    "es": "Atención: estas ofertas son para el {served}, no para el {requested} que pediste. "
    "Dime si vuelvo a buscar para el {requested}.",
    "it": "Attenzione: queste offerte sono per {served}, non per {requested} come richiesto. "
    "Dimmi se devo rifare la ricerca per {requested}.",
    "de": "Hinweis: Diese Angebote gelten für {served}, nicht für {requested} wie gewünscht. "
    "Soll ich erneut für {requested} suchen?",
    "pt": "Atenção: estas ofertas são para {served}, não para {requested} como pediu. "
    "Diga-me se devo pesquisar novamente para {requested}.",
    "nl": "Let op: deze aanbiedingen gelden voor {served}, niet voor {requested} zoals gevraagd. "
    "Zal ik opnieuw zoeken voor {requested}?",
}


def date_served_notice(requested: str, served: str, language: str) -> str:
    """The deterministic correction of `guard_date_served`: say which day the
    offers on screen are for, and offer the day that was asked."""
    template = _SERVED_NOTICE.get(language, _SERVED_NOTICE["en"])
    return template.format(
        served=format_date_human(served, language), requested=format_date_human(requested, language)
    )


def expected_search_date(
    message: str, carried: str | None, today: date, *, weekday: str | None = None
) -> tuple[str | None, bool]:
    """`(expected_iso, from_this_message)`: the day this turn's search must run
    on, or None when code cannot know it. From this message when it names one
    day; else the carried profile date, but only when the message says nothing
    about a day at all (a weekday the parser skips may legitimately move it)."""
    requested = parse_requested_date(message, today)
    if requested is not None:
        return (requested.isoformat(), True) if requested >= today else (None, True)
    # Semantic triage supplies an evidence-grounded weekday before the leaf can
    # ask for a place clarification. Share its calendar rule with the leaf.
    if weekday is not None:
        resolved = resolve_relative_day(weekday, today)
        if resolved is not None:
            return resolved.isoformat(), True
    if carried and not mentions_a_date(message, today):
        try:
            if date.fromisoformat(carried) >= today:
                return carried, False
        except ValueError:
            return None, False
    return None, False
