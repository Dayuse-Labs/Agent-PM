"""Concierge-owned date decision before any search clarification.

Literal single-day evidence, a multi-day request and a carried date have
different authority. Reduce them once; a model's period label is not a date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from b2c_common.date_period import freeze_period, weekday_in_period

from .requested_date import expected_search_date, mentions_a_date, parse_requested_date

# Exact date labels only, not a natural-language classifier. The established
# date parser still resolves the full message, including conflicting dates.
_SINGLE_DAYS = frozenset({
    "today", "tomorrow", "day after tomorrow", "tonight",
    "aujourd'hui", "aujourd’hui", "demain", "après-demain", "après demain", "ce soir",
    "hoy", "mañana", "pasado mañana", "oggi", "domani", "dopodomani",
    "heute", "morgen", "übermorgen", "hoje", "amanhã", "depois de amanhã",
    "vandaag", "morgen", "overmorgen",
})


@dataclass(frozen=True)
class DateDecision:
    expected: str | None
    from_message: bool
    pending_period: dict | None


def _single_day_mislabeled(period: dict, message: str, today: date) -> bool:
    quote = period.get("evidence", "")
    if not isinstance(quote, str) or not quote or quote not in message:
        return False
    if quote.strip().casefold() not in _SINGLE_DAYS:
        return False
    requested = parse_requested_date(message, today)
    # Another date/weekday outside the quote means a genuine ambiguity. A
    # range's first endpoint must never silently become the chosen stay.
    remainder = message.replace(quote, " ")
    return (requested is not None and requested == parse_requested_date(quote, today)
            and not mentions_a_date(remainder, today))


def decide_date(message: str, carried: str | None, pending_period: dict | None,
                update: dict | None, today: date, *, weekday: str | None = None,
                calendar: dict | None = None) -> DateDecision:
    if update and _single_day_mislabeled(update, message, today):
        update = None
    pending = freeze_period(update, today) if update else pending_period
    expected, explicit = expected_search_date(message, None if pending else carried, today,
                                               weekday=weekday, calendar=calendar)
    if pending:
        if update:
            expected, explicit = None, False
        if weekday:
            expected = weekday_in_period(pending, weekday, today)
            explicit = expected is not None
        if expected and explicit:
            pending = None
        else:
            expected = None
    return DateDecision(expected, explicit, pending)
