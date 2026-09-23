"""Human-readable dates in the turn's language (QA report n°2, 2026-09-08).

Why it exists. The leaf hands the concierge its search date as ISO
(`search_date.date = "2026-09-24"`) and the ground-truth block used to paste
it verbatim into the synthesis prompt ("these results are for 2026-09-24.
State that date."). The model obeyed literally: prod replies read
"Pour demain (2026-09-24) à Paris…" — a machine format leaking to users.

Two layers, same posture as `currency_guard` / `link_guard`:
  1. `format_date_human` — the prompt receives the date already written the
     way a person would say it, in the turn's language;
  2. `humanize_iso_dates` — a deterministic post-LLM backstop rewriting any
     ISO date the model still emitted. URLs are left untouched: a booking or
     hotel-page link may legitimately carry an ISO date parameter.

No locale/Babel dependency on purpose: 7 languages, fixed tables, pure code —
the output never depends on the container's installed locales.
"""
from __future__ import annotations

import re
from datetime import date

_WEEKDAYS = {
    "fr": ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "es": ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"),
    "it": ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"),
    "de": ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"),
    "pt": (
        "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo",
    ),
    "nl": ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"),
}

_MONTHS = {
    "fr": (
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ),
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
    "es": (
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ),
    "it": (
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ),
    "de": (
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ),
    "pt": (
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    ),
    "nl": (
        "januari", "februari", "maart", "april", "mei", "juni",
        "juli", "augustus", "september", "oktober", "november", "december",
    ),
}

_ISO_DATE_RE = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])")
_URL_RE = re.compile(r"https?://\S+")


def format_date_human(value: str | date, language: str) -> str:
    """`"2026-09-24"` → `"jeudi 24 septembre 2026"` (fr), `"Thursday,
    September 24, 2026"` (en)… Unknown language falls back to English; an
    unparseable string is returned unchanged (never raise on a prompt path)."""
    if isinstance(value, date):
        d = value
    else:
        try:
            d = date.fromisoformat(value)
        except ValueError:
            return value
    lang = language if language in _MONTHS else "en"
    weekday = _WEEKDAYS[lang][d.weekday()]
    month = _MONTHS[lang][d.month - 1]
    if lang == "en":
        return f"{weekday}, {month} {d.day}, {d.year}"
    if lang == "fr":
        day = "1er" if d.day == 1 else str(d.day)
        return f"{weekday} {day} {month} {d.year}"
    if lang == "es":
        return f"{weekday} {d.day} de {month} de {d.year}"
    if lang == "pt":
        return f"{weekday}, {d.day} de {month} de {d.year}"
    if lang == "de":
        return f"{weekday}, {d.day}. {month} {d.year}"
    return f"{weekday} {d.day} {month} {d.year}"  # it, nl


def humanize_iso_dates(text: str, language: str) -> tuple[str, int]:
    """`(corrected_text, replaced)`: every valid ISO date outside a URL is
    rewritten with `format_date_human`. Invalid calendar dates (`2026-13-40`)
    are left as-is — they are not dates, rewriting them would invent one."""
    if not text:
        return text, 0
    url_spans = [m.span() for m in _URL_RE.finditer(text)]
    replaced = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal replaced
        start = match.start()
        if any(lo <= start < hi for lo, hi in url_spans):
            return match.group(0)
        human = format_date_human(match.group(0), language)
        if human == match.group(0):
            return human
        replaced += 1
        return human

    return _ISO_DATE_RE.sub(_sub, text), replaced
