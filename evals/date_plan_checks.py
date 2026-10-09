"""Date-range and multi-stay evidence checks, independent of agent date logic.

Oracles are manually reviewed user requirements. No prose classification, date
inference from old active_filters, or inventory completeness claim is made here.
An undated legacy card cannot prove availability on either requested date.
"""
from datetime import date
from typing import Any

from evals.priced_stay_checks import check_priced_stays


def _day(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 10 or value[4] != '-' or value[7] != '-':
        return None
    digits = value[:4] + value[5:7] + value[8:]
    if not digits.isascii() or not digits.isdigit():
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _minute(value: Any) -> int | None:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ':':
        return None
    digits = value[:2] + value[3:]
    if not digits.isascii() or not digits.isdigit():
        return None
    hour, minute = int(value[:2]), int(value[3:])
    return hour * 60 + minute if (hour < 24 and minute < 60) or (hour == 24 and minute == 0) else None


def _cards(response: dict | None) -> list:
    raw = response.get('hotels') if isinstance(response, dict) else None
    return raw if isinstance(raw, list) else []


def check_date_range(response: dict | None, *, start: str, end: str) -> dict:
    if _day(start) is None or _day(end) is None or start > end:
        raise ValueError('A date range needs valid ordered ISO dates')
    rows = _cards(response)
    dates = [_day(c.get('offer_date')) if isinstance(c, dict) else None for c in rows]
    bad = [i for i, value in enumerate(dates) if value is not None and not start <= value <= end]
    unknown = [i for i, value in enumerate(dates) if value is None]
    return {'check': 'displayed_date_range', 'status': 'fail' if bad else 'skipped' if not rows or unknown else 'pass',
            'start': start, 'end': end, 'cards': len(rows), 'outside_range_indices': bad,
            'unknown_date_indices': unknown,
            'scope': 'Displayed dates only. No cards or undated cards cannot prove fulfillment; clarification quality is reviewed separately.'}


def check_stay_sequence(response: dict | None, stays: list[dict], *, schema: str, budget: dict | None = None) -> dict:
    """Require a separate dated, covering offer witness for every requested stay.

    Multiple stays on the same date (room quantity/overlap) need another oracle;
    rejecting them is safer than reusing one offer as two reservations. Missing
    witnesses are skipped, never proof of no inventory or automatic bad dialogue.
    """
    if schema not in {'b2c', 'legacy'} or not stays:
        raise ValueError('Nonempty stays and a known card schema are required')
    ids, days = set(), set()
    for stay in stays:
        if not isinstance(stay, dict) or set(stay) != {'id', 'date', 'start', 'end'}:
            raise ValueError('A stay requires exactly id,date,start,end')
        identifier, day = stay['id'], _day(stay['date'])
        start, end = _minute(stay['start']), _minute(stay['end'])
        if (not isinstance(identifier, str) or not identifier or identifier in ids
                or day is None or day in days or start is None or end is None or start >= end):
            raise ValueError('Unique stay IDs/dates and increasing same-day windows are required')
        ids.add(identifier)
        days.add(day)
    rows = _cards(response)
    dated = [(i, c, _day(c.get('offer_date'))) for i, c in enumerate(rows) if isinstance(c, dict)]
    checks = []
    for stay in stays:
        selected = [c for _, c, day in dated if day == stay['date']]
        window = {'start': stay['start'], 'end': stay['end']}
        if budget is not None:
            evidence = check_priced_stays({'hotels': selected}, {'budget': budget, 'stay_window': window}, schema=schema)
            status = evidence['status']
        else:
            wanted_start, wanted_end = _minute(stay['start']), _minute(stay['end'])
            assert wanted_start is not None and wanted_end is not None  # Validated above.
            witnesses, uncertain = 0, False
            for card in selected:
                slots = card.get('timeslots')
                if not isinstance(slots, list) or not slots:
                    uncertain = True
                    continue
                for slot in slots:
                    a = _minute(slot.get('start')) if isinstance(slot, dict) else None
                    z = _minute(slot.get('end')) if isinstance(slot, dict) else None
                    if a is None or z is None or a >= z:
                        uncertain = True
                    elif a <= wanted_start and z >= wanted_end:
                        witnesses += 1
            status = 'pass' if witnesses else 'skipped' if not selected or uncertain else 'fail'
            evidence = {'covering_slot_witnesses': witnesses, 'unknown_slot_data': uncertain}
        checks.append({'stay_id': stay['id'], 'date': stay['date'], 'window': window,
                       'dated_cards': len(selected), 'status': status, 'evidence': evidence})
    unexpected = [i for i, _, day in dated if day is not None and day not in days]
    return {'check': 'dated_stay_sequence',
            'status': 'fail' if unexpected or any(c['status'] == 'fail' for c in checks)
                      else 'pass' if all(c['status'] == 'pass' for c in checks) else 'skipped',
            'stays': checks, 'unrequested_date_indices': unexpected,
            'unknown_date_cards': len(rows) - sum(day is not None for _, _, day in dated),
            'scope': 'One correctly dated offer witness per distinct stay; prices and hours must belong to the same quote when budget is supplied. Does not grade prose, exhaustive inventory or booking actions.'}
