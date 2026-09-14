"""Shifts the wall clock forward by `$TIMESHIFT_DAYS` for the source AND the
tests alike, so that a test computing its dates from the clock stays green and
only a test pinned to a date LITERAL fails.

Loaded with `-p timeshift_plugin` (see `test_calendar_rot.py`), i.e. before any
collection, so the `from datetime import date` of every module imported
afterwards — source and test — binds the shifted class.

`today()`/`now()`/`.date()` must return `cls(...)`, never the stdlib instance:
`reference_today` is asserted with `isinstance(result, date)`, and a real
`date` is not an instance of the subclass.
"""

import datetime as _dt
import os

SHIFT = _dt.timedelta(days=int(os.environ.get("TIMESHIFT_DAYS", "400")))
_real_date, _real_datetime = _dt.date, _dt.datetime


class ShiftedDate(_real_date):
    @classmethod
    def today(cls) -> "ShiftedDate":
        d = _real_date.today() + SHIFT
        return cls(d.year, d.month, d.day)


class ShiftedDateTime(_real_datetime):
    @classmethod
    def now(cls, tz: object = None) -> "ShiftedDateTime":
        d = _real_datetime.now(tz) + SHIFT  # type: ignore[arg-type]
        return cls(d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond, d.tzinfo)

    @classmethod
    def utcnow(cls) -> "ShiftedDateTime":
        d = _real_datetime.utcnow() + SHIFT
        return cls(d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond)

    def date(self) -> ShiftedDate:
        return ShiftedDate(self.year, self.month, self.day)


_dt.date = ShiftedDate  # type: ignore[misc]
_dt.datetime = ShiftedDateTime  # type: ignore[misc]
