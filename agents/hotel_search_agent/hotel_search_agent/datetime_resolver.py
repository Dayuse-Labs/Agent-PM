"""datetime_resolver.py — code-owned date/duration/minute resolution for search_offers.

S-G6 (2026-07-23): `search_offers` REQUIRES a `date` (live-probed against MCP_B2C
staging: `"required": ["lat", "lon", "date"]`, `date` is a plain ISO
`yyyy-MM-dd` string — "already resolved", i.e. MCP does zero date math itself,
exactly like geocoding). Its `timeSlot` sub-object is integer-hour only
(`startHour`/`endHour`, no minute fields, `additionalProperties: false`) — the
probe also confirmed there is no duration/availability parameter at all.

Same split of responsibility as `equipment_ids.py` (the proven template):
  - `inject_datetime_declaration` (before_model) widens the model-facing
    `search_offers` declaration: `date` becomes a LABEL object
    `{type: relative|absolute, value, expression}` (never a resolved string —
    the model must never compute a calendar date itself), a new virtual
    `duration` string param (ISO-8601, e.g. "PT1H") is added, and `timeSlot`
    gains virtual `startMinute`/`endMinute` sub-properties. The model only
    ever LABELS what the user said; it never converts a duration into an
    absolute window and never resolves "tomorrow" into a date itself (the
    historic bug this closes: "for 1 hour" extracted as "00:00-01:00",
    core-e2e-201 — and the S10 negation-inversion lesson generalizes to any
    LLM arithmetic on a filter value: never trust it, always recompute in code).
  - `resolve_search_date` (before_tool, LAST group) pops the model's `date`
    label, resolves it in code against a reference "today" (the client's own
    timezone when known — `profile_in.client_timezone`, S-G2/S-G6 — else the
    server clock, documented fallback), and writes the real ISO string MCP
    requires. A turn with NO fresh label reuses the profile's own carried-over
    `date` (never re-derives "today" over a real prior date — the audit's
    "date lost on a later turn" bug in reverse). One invariant across every
    path: **a date strictly before the reference "today" is never sent to
    MCP** — whether the model invented a past year or the session carried a
    pre-midnight date, the search would come back empty and that empty reads
    to the customer as "no offers in <city>" (prod 2026-07-29).
  - `resolve_search_timeslot` (before_tool, LAST group) pops the virtual
    `duration`/`startMinute`/`endMinute`, computes the EXACT requested window
    in minutes-of-day, floors/ceils it to the whole hours MCP actually accepts
    (A4-c interim — the real minute-level filter is a cross-repo ask, see
    reports/MCP-B2C-REQUESTS.md), and stashes the exact window for
    response_bridge.capture_after_tool to recover (accurate profile capture +
    the offer-level exact-minute post-filter). A duration with NO start hour
    anywhere (fresh or carried over) invents NO window at all — `timeSlot` is
    simply omitted, per the spine's "LLM labels, code computes, never guesses"
    rule.
"""
from __future__ import annotations

import copy
import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from b2c_common.observability import mark_level
from b2c_common.timeslot import DAYPART_HOURS, daypart_in
from hotel_search_agent.response_bridge import (
    STATE_DATE_FALLBACK_KEY,
    STATE_DAYPART_KEY,
    STATE_EXACT_WINDOW_KEY,
    STATE_RESOLVED_DATE_KEY,
    STATE_SEARCH_DATE_KEY,
    read_profile_in,
    read_structured_payload,
    record_guards_fired,
)

# Same stdout metrics logger as equipment_ids.py / response_bridge.py.
_metrics_logger = logging.getLogger("dayuse.metrics")

# --- model-facing schema widening -------------------------------------------------------------

_DATE_LABEL_PROPERTY: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["absolute", "relative"]},
        "value": {
            "type": "string",
            "description": (
                "For type=relative: one of today, tomorrow, day_after_tomorrow, "
                "monday, tuesday, wednesday, thursday, friday, saturday, sunday "
                "(a bare weekday ALWAYS means its NEXT occurrence, never today "
                "even if today IS that weekday). For type=absolute: the date the "
                "user stated, as YYYY-MM-DD if they gave a year, otherwise MM-DD "
                "— NEVER add or guess a year yourself, the system picks the "
                "soonest matching calendar date."
            ),
        },
        "expression": {
            "type": "string",
            "description": "The user's original wording for the date, verbatim.",
        },
    },
    "required": ["type", "value"],
    "additionalProperties": False,
    "description": (
        "LABEL the date/day the user means — you never compute or resolve it "
        "yourself, the system does. Omit this entirely when no day/date is "
        "mentioned at all (the system keeps searching the ongoing date)."
    ),
}

_DURATION_PROPERTY: dict[str, Any] = {
    "type": "string",
    "description": (
        "ONLY for an explicit LENGTH OF STAY the user stated as a duration "
        "('for 1 hour', 'for 30 minutes', 'pour 2 heures') — as an ISO-8601 "
        "duration, e.g. PT1H, PT30M, PT1H30M. NEVER for a specific start/end "
        "clock time (use timeSlot for that) and NEVER invent one when the user "
        "did not state a length of stay — a duration is not a start/end window, "
        "the system computes any actual window from it, you never do."
    ),
}

_MINUTE_ENUM = [0, 15, 30, 45]
_START_MINUTE_PROPERTY: dict[str, Any] = {
    "type": "integer",
    "enum": _MINUTE_ENUM,
    "description": "Minutes past startHour, ONLY when the user stated them (e.g. '7:30am').",
}
_END_MINUTE_PROPERTY: dict[str, Any] = {
    "type": "integer",
    "enum": _MINUTE_ENUM,
    "description": "Minutes past endHour, ONLY when the user stated them (e.g. '1:30pm').",
}


def inject_datetime_declaration(callback_context: Any, llm_request: Any) -> None:
    """`before_model_callback`: widen the search_offers declaration exactly the
    way `equipment_ids.inject_amenities_declaration` widens it for amenities —
    same deepcopy safety (never mutate the McpTool's cached schema in place),
    same idempotent per-request rebuild. `date` is REMOVED from the widened
    `required` list: the model never has to supply it (code always fills
    `args["date"]` in `resolve_search_date`, fresh label or not), so leaving it
    required would pressure the model into inventing one when nothing was said."""
    config = getattr(llm_request, "config", None)
    for tool_entry in getattr(config, "tools", None) or []:
        for decl in getattr(tool_entry, "function_declarations", None) or []:
            if getattr(decl, "name", None) != "search_offers":
                continue
            schema = getattr(decl, "parameters_json_schema", None)
            if not isinstance(schema, dict):
                return None
            widened = copy.deepcopy(schema)
            properties = widened.setdefault("properties", {})
            properties["date"] = copy.deepcopy(_DATE_LABEL_PROPERTY)
            properties["duration"] = copy.deepcopy(_DURATION_PROPERTY)
            time_slot_schema = properties.get("timeSlot")
            if isinstance(time_slot_schema, dict):
                time_slot_props = time_slot_schema.setdefault("properties", {})
                time_slot_props["startMinute"] = copy.deepcopy(_START_MINUTE_PROPERTY)
                time_slot_props["endMinute"] = copy.deepcopy(_END_MINUTE_PROPERTY)
            required = widened.get("required")
            if isinstance(required, list):
                widened["required"] = [r for r in required if r != "date"]
            decl.parameters_json_schema = widened
            return None
    return None


# --- reference "today" -------------------------------------------------------------------------


def reference_today(profile_in: dict[str, Any]) -> date:
    """"Today" for date-label resolution: the CLIENT's own timezone
    (`profile_in.client_timezone`, S-G2 intake + S-G6 profile field) computed
    against the real wall clock, else the server's own local date (documented
    fallback — deliberately NOT the client's raw `client_local_time` reading,
    which S-G2 chose not to persist: a device clock can be wrong, the server's
    own clock plus a validated IANA timezone is the safer, simpler anchor)."""
    tz_name = profile_in.get("client_timezone")
    if isinstance(tz_name, str) and tz_name:
        try:
            return datetime.now(ZoneInfo(tz_name)).date()
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return date.today()


# --- date label resolution ----------------------------------------------------------------------

_RELATIVE_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_DAY_RE = re.compile(r"^(\d{2})-(\d{2})$")


def _resolve_relative(value: Any, today: date) -> date | None:
    v = str(value or "").strip().lower()
    if v == "today":
        return today
    if v == "tomorrow":
        return today + timedelta(days=1)
    if v == "day_after_tomorrow":
        return today + timedelta(days=2)
    if v in _RELATIVE_WEEKDAYS:
        delta = (_RELATIVE_WEEKDAYS[v] - today.weekday()) % 7
        return today + timedelta(days=delta or 7)  # "next X" excludes today itself
    return None


def _next_occurrence(month: int, day: int, today: date) -> date | None:
    """`month`/`day` as its next occurrence at or after `today`, rolling the
    year when it has already passed. None when the pair is not a real calendar
    date in either year (e.g. 02-30)."""
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


def _resolve_absolute(value: Any, today: date, guards_fired: list[str]) -> date | None:
    v = str(value or "").strip()
    match = _ISO_DATE_RE.match(v)
    if match:
        year, month, day = (int(match.group(i)) for i in (1, 2, 3))
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate >= today:
            return candidate
        mark_level("WARNING", status_message="date_hallucinated_year_rolled_forward")
        guards_fired.append("date_hallucinated_year_rolled_forward")
        # A year in the PAST is proof the model invented one. Its instruction is
        # explicit — "YYYY-MM-DD if they gave a year, else MM-DD; NEVER add or
        # guess a year yourself" — and prod 2026-07-29 caught gpt-4o-mini
        # labelling "6 aout" as "2023-08-06": a search three years back, 0
        # results served as "no offers in Melun", then persisted to
        # profile.date and replayed on every later turn (it reads exactly like
        # broken multi-turn state). Nobody books a day-use in the past, so the
        # month/day it DID extract is the only trustworthy part: roll it forward
        # under the same rule the year-less branch below has always used.
        return _next_occurrence(month, day, today)
    match = _MONTH_DAY_RE.match(v)
    if match:
        return _next_occurrence(int(match.group(1)), int(match.group(2)), today)
    return None


def _usable_carried_date(value: Any, today: date, guards_fired: list[str]) -> str | None:
    """The carried `profile_in.date` when it is still searchable — else None,
    so the caller falls back to today.

    Rejects a date strictly BEFORE today for the same reason as the guard
    above: it can only ever come back empty, and that empty reads to the
    customer as "no offers here". Reachable without any model mistake — the
    profile TTL is a 30-min sliding window, so a session that straddles
    midnight carries yesterday's resolved date into today. Also rejects a
    non-ISO value, which MCP would only reject at schema level anyway."""
    if not isinstance(value, str) or not value:
        return None
    try:
        carried = date.fromisoformat(value)
    except ValueError:
        return None
    if carried < today:
        mark_level("WARNING", status_message="date_carryover_stale_floored")
        guards_fired.append("date_carryover_stale_floored")
        return None
    return value


def resolve_date_label(
    label: Any, today: date, guards_fired: list[str] | None = None
) -> tuple[date, str, str | None]:
    """(resolved_date, resolved_from, expression) from the model's `date` label.
    `resolved_from` in {"relative", "absolute", "default"} — "default" covers a
    missing/malformed label (the caller decides whether that's a fresh-turn
    bootstrap or a carryover; this function only ever resolves what it's given).

    OBS3: `guards_fired` is the accumulator the caller reads back to learn that
    `date_hallucinated_year_rolled_forward` fired (same pattern as
    `geocode_tool`, which threads one through its own guards). Optional because
    resolution itself does not need it — the date math is identical either
    way — and because this signature is public."""
    fired = guards_fired if guards_fired is not None else []
    if isinstance(label, dict):
        expression = label.get("expression") if isinstance(label.get("expression"), str) else None
        label_type, value = label.get("type"), label.get("value")
        if label_type == "relative":
            resolved = _resolve_relative(value, today)
            if resolved is not None:
                return resolved, "relative", expression
        elif label_type == "absolute":
            resolved = _resolve_absolute(value, today, fired)
            if resolved is not None:
                return resolved, "absolute", expression
        return today, "default", expression
    return today, "default", None


def resolve_search_date(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback`: the ONLY writer of search_offers' `date` — the
    model never owns a resolved calendar date, only the label.

    A FRESH, resolvable label this turn is resolved AND persisted
    (`STATE_RESOLVED_DATE_KEY`, mapped to `profile_delta.date`/
    `date_reference` by `response_bridge.emit_search_datapart`). Anything else
    (no label, or a label that fails to resolve) reuses `profile_in.date`
    (carried over from an earlier turn) as the value actually sent to MCP,
    falling back to `reference_today` only on a true first mention — and
    persists NOTHING, so a silent turn never overwrites a real prior date with
    today's bootstrap default (the audit's "date lost on a later turn" bug,
    avoided by construction rather than patched after the fact).

    OBS3 (2026-08-26): this is where the two date guards finally become
    OBSERVABLE. They fire in pure helpers with no `tool_context`, so they report
    through a local accumulator that is handed to `record_guards_fired` on both
    exits — from there `emit_search_datapart` puts it on the A2A DataPart and
    the concierge folds it into `score_guards`. Before this, both names were
    published as 0.0 on every turn forever, which reads as "the guard did not
    fire" instead of "the guard is not measured"."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    profile_in = read_profile_in(tool_context)
    today = reference_today(profile_in)
    guards_fired: list[str] = []
    label = args.pop("date", None)
    if isinstance(label, dict) and label.get("type") in ("relative", "absolute"):
        resolved_date, resolved_from, expression = resolve_date_label(label, today, guards_fired)
        if resolved_from != "default":
            args["date"] = resolved_date.isoformat()
            date_reference: dict[str, Any] = {"resolved_from": resolved_from}
            if expression:
                date_reference["expression"] = expression
            client_tz = profile_in.get("client_timezone")
            if isinstance(client_tz, str) and client_tz:
                date_reference["client_tz"] = client_tz
            tool_context.state[STATE_RESOLVED_DATE_KEY] = {
                "date": resolved_date.isoformat(),
                "date_reference": date_reference,
            }
            _stash_search_date(tool_context, args["date"], today)
            record_guards_fired(tool_context, guards_fired)
            return None
    # No fresh, resolvable label this turn — carry over rather than re-derive,
    # unless the carried date is no longer searchable (`_usable_carried_date`).
    args["date"] = (
        _usable_carried_date(profile_in.get("date"), today, guards_fired) or today.isoformat()
    )
    # Stash AFTER the guard, never before: `same_day` is what licenses the
    # next-day probe, and a stale carried date floored back to today must be
    # reported as the same-day search it has just become.
    _stash_search_date(tool_context, args["date"], today)
    # A label that fired the year-roll guard and STILL failed to resolve lands
    # here rather than on the exit above (a past leap day: "2020-02-29" is a
    # real date, so the guard fires, but 02-29 has no next occurrence in either
    # candidate year) — same accumulator, so the guard is reported either way.
    record_guards_fired(tool_context, guards_fired)
    return None


def _stash_search_date(tool_context: Any, iso_date: str, today: date) -> None:
    """S-CX6: record the date the search is ACTUALLY running on, on every
    search — including the carry-over/default path that persists nothing to the
    profile. `same_day` is the flag the next-day probe fires on and the flag
    the concierge needs to offer dates instead of a wider zone: a closed day
    cannot be fixed by budget, area or filters."""
    tool_context.state[STATE_SEARCH_DATE_KEY] = {
        "date": iso_date,
        "same_day": iso_date == today.isoformat(),
    }


async def probe_next_day_after_tool(
    tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any
) -> None:
    """`after_tool_callback` — the same-day cutoff rescue (S-CX6).

    Every day-use offer's `cutoffDeadlineUtc` falls on the STAY date itself:
    measured live 2026-07-27 over 63 Paris offers, cutoffs run 05h→16h local,
    the latest at 16h. So from mid-afternoon on, a search dated today returns
    ZERO for the whole market — 11 pages of a 518-hotel pool walked at 17h50,
    empty on every one — while the same coordinates one day later return
    offers from 54 €. That dead end is what a user reads as "no results alors
    que je devrais en avoir" (Fabien's session, 2026-07-27).

    Fires ONLY on the exact signature of a closed day, so a normal empty search
    is never charged a second call:
      - the search ran on the session's OWN today (`same_day`), and
      - the pool is NOT empty (`total` > 0 — MCP counts matches BEFORE the
        bookability check, so `total` > 0 with `results` == [] means "hotels
        exist, every offer is past cutoff", whereas `total` == 0 is a market
        with no inventory at all and a D+1 probe would be pure waste).

    Placed BEFORE `capture_after_tool` in the chain and ALWAYS returns None:
    a truthy return breaks the after-tool chain (ADK `functions.py`, first
    non-None wins), which would cost the compact-payload rewrite and the
    profile hand-off. ADK awaits an awaitable callback mixed among sync ones
    (`inspect.isawaitable` there), so this being the only async callback in the
    list is fine. `tool.run_async` re-enters neither the before- nor the
    after-tool callbacks, so there is no recursion to guard against — and no
    `from` offset either: a fallback day always starts at page 1.

    Budget: one extra MCP call (leaf-owned 5 s timeout) on a dead-end turn
    only, measured ~600 ms, inside the orchestrator's 10 s leaf budget. Any
    failure is swallowed — a rescue probe must never turn an honest empty
    answer into a broken turn."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    if not isinstance(tool_response, dict) or tool_response.get("isError"):
        return None
    if tool_response.get("ok") is False or tool_response.get("error"):
        return None
    search_date = tool_context.state.get(STATE_SEARCH_DATE_KEY)
    if not isinstance(search_date, dict) or not search_date.get("same_day"):
        return None
    structured = read_structured_payload(tool_response)
    if not isinstance(structured, dict) or structured.get("results"):
        return None
    try:
        pool_total = int(structured.get("total") or 0)
    except (TypeError, ValueError):
        pool_total = 0
    if pool_total <= 0:
        return None  # genuinely no inventory here — another day will not help

    # The cause is now established, and it is the ONLY thing that licenses
    # saying "today's bookings are closed": hotels match the search, none is
    # bookable. A same-day zero over an EMPTY pool (probed: Tokyo, total=0) is a
    # market with no day-use inventory — claiming a closed window there would be
    # a fabricated cause, so the flag stays off and the generic recovery holds.
    tool_context.state[STATE_SEARCH_DATE_KEY] = {**search_date, "cutoff_closed": True}

    searched = str(search_date.get("date") or "")
    try:
        offered = (date.fromisoformat(searched) + timedelta(days=1)).isoformat()
    except ValueError:
        return None

    probe_args = {k: v for k, v in args.items() if k != "from"}
    probe_args["date"] = offered
    started = time.monotonic()
    try:
        probe_response = await tool.run_async(args=probe_args, tool_context=tool_context)
    except Exception:  # noqa: BLE001 — a rescue probe never breaks the turn
        _log_probe("error", started, found=0)
        return None
    payload = read_structured_payload(probe_response)
    found = payload.get("results") if isinstance(payload, dict) else None
    if not found:
        _log_probe("empty", started, found=0)
        return None
    tool_context.state[STATE_DATE_FALLBACK_KEY] = {
        "searched_date": searched,
        "offered_date": offered,
        "payload": payload,
    }
    _log_probe("ok", started, found=1)
    return None


def _log_probe(status: str, started: float, found: int) -> None:
    """Content-free metric (RGPD): status/ms/found flag only — never the date or
    the place, same rule as the budget/time-slot presence flags."""
    _metrics_logger.info(
        "dayuse_metric=cutoff_fallback_probe agent=b2c_hotel_search status=%s ms=%d found=%d",
        status,
        int((time.monotonic() - started) * 1000),
        found,
    )


# --- duration + sub-hour timeSlot ---------------------------------------------------------------

_DURATION_RE = re.compile(r"^P(?:T(?:(\d+)H)?(?:(\d+)M)?)$")


def parse_duration_minutes(value: Any) -> int | None:
    """Minutes from an ISO-8601-style duration ("PT1H", "PT30M", "PT1H30M"), or
    None for anything else (absent, malformed, a bare number the model
    shouldn't have sent here). At least one component must be present —
    "PT" alone is not a duration."""
    if not isinstance(value, str):
        return None
    match = _DURATION_RE.match(value.strip().upper())
    if not match or not (match.group(1) or match.group(2)):
        return None
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)


def _minutes_of_day(hour: Any, minute: Any = 0) -> int | None:
    try:
        h, m = int(hour), int(minute or 0)
    except (TypeError, ValueError):
        return None
    return h * 60 + m if (0 <= h <= 23 and 0 <= m <= 59) else None


def _parse_hhmm_to_minutes(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{1,2}):(\d{2})$", value.strip())
    return _minutes_of_day(match.group(1), match.group(2)) if match else None


_MAX_MINUTE_OF_DAY = 23 * 60 + 59

# A clock time the user actually stated: "14h", "14h30", "13:30", "2pm",
# "15 heures/Uhr/horas/ore/uur", "a las 3", "midi"/"noon"... in the 7 reply
# languages. A daypart ("l'après-midi", "por la tarde") is not one.
_CLOCK_TIME_RE = re.compile(
    r"\b\d{1,2}\s*h(?:\s*\d{2})?\b|\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*(?:am|pm|a\.m\.|p\.m\.)"
    r"|\b\d{1,2}\s*(?:heures?|uhr|horas?|ore|uur)\b"
    r"|\b(?:a las|alle|às|as|om|um|at|à)\s+\d{1,2}\b"
    r"|(?<!après-)(?<!apres-)(?<!après )(?<!apres )\b(?:midi|minuit|noon|midnight|mediod[ií]a|medianoche|mezzogiorno|mezzanotte"
    r"|mittags?|mitternacht|meio-dia|meia-noite|middag|middernacht)\b",
    re.IGNORECASE,
)


def _user_text(tool_context: Any) -> str:
    content = getattr(tool_context, "user_content", None)
    parts = getattr(content, "parts", None) or []
    return " ".join(p.text for p in parts if getattr(p, "text", None))


def _is_carried_slot(time_slot: dict[str, Any], profile_in: dict[str, Any]) -> bool:
    """The model repeated the clock window already in the profile (a
    follow-up turn: "et à Villeurbanne ?")."""
    carried = (
        _parse_hhmm_to_minutes(profile_in.get("timeslot_start")),
        _parse_hhmm_to_minutes(profile_in.get("timeslot_end")),
    )
    if carried == (None, None):
        return False
    sent = (time_slot.get("startHour"), time_slot.get("endHour"))
    return sent == tuple(m // 60 if m is not None else None for m in carried)


_NAMED_HOURS = {
    "midi": {12}, "noon": {12}, "mediodia": {12}, "mezzogiorno": {12}, "mittag": {12},
    "mittags": {12}, "meio-dia": {12}, "middag": {12},
    "minuit": {0, 23}, "midnight": {0, 23}, "medianoche": {0, 23}, "mezzanotte": {0, 23},
    "mitternacht": {0, 23}, "meia-noite": {0, 23}, "middernacht": {0, 23},
}


def _stated_hours(text: str) -> set[int]:
    """The hours of every clock time the message states ("à 9h" → {9},
    "2pm" → {14}, "midi" → {12})."""
    hours: set[int] = set()
    for match in _CLOCK_TIME_RE.finditer(text):
        token = match.group(0).lower()
        number = re.search(r"\d{1,2}", token)
        if number is None:
            hours |= _NAMED_HOURS.get(token.replace("í", "i"), set())
            continue
        hour = int(number.group(0))
        if re.search(r"p\.?m", token) and hour < 12:
            hour += 12
        hours.add(hour)
    return hours


def _drop_unstated_carried_bounds(
    time_slot: dict[str, Any], tool_context: Any, profile_in: dict[str, Any]
) -> dict[str, Any]:
    """mcp-dayuse#6 (Mathias 2026-10-06): a stated time replaces the whole
    window. "à 9h" after 13h-15h came back from the model as 9h-15h — the end
    is the previous turn's, never restated. A bound equal to the carried one
    and absent from a message that does state a time is dropped."""
    text = _user_text(tool_context)
    if not _CLOCK_TIME_RE.search(text):
        return time_slot
    stated = _stated_hours(text)
    kept = dict(time_slot)
    for hour_key, minute_key, profile_key in (
        ("startHour", "startMinute", "timeslot_start"),
        ("endHour", "endMinute", "timeslot_end"),
    ):
        carried = _parse_hhmm_to_minutes(profile_in.get(profile_key))
        if carried is None or kept.get(hour_key) != carried // 60 or carried // 60 in stated:
            continue
        kept.pop(hour_key)
        kept.pop(minute_key, None)
    return kept


def _daypart_for_turn(
    time_slot: dict[str, Any], tool_context: Any, profile_in: dict[str, Any]
) -> str | None:
    """mcp-dayuse#8, option B (Mathias 2026-10-06): a daypart is read IN CODE
    ("l'après-midi", "por la tarde") and filters softly — the model used to
    turn it into an invented clock window (12h-23h) that the site's covering
    rule then emptied. A stated clock time wins; a daypart carried from the
    profile applies when the turn says nothing about time."""
    text = _user_text(tool_context)
    if _CLOCK_TIME_RE.search(text):
        return None
    fresh = daypart_in(text)
    if fresh is not None:
        return fresh
    carried = profile_in.get("daypart")
    if carried in DAYPART_HOURS and not _is_carried_slot(time_slot, profile_in):
        return str(carried)
    return None


def _invented_time_slot(time_slot: dict[str, Any], tool_context: Any, profile_in: dict[str, Any]) -> bool:
    """mcp-dayuse#8: a `timeSlot` the user never stated. The instruction
    already forbids it, but "por la tarde" came back as 12h-23h — harmless
    while the leaf kept offers INSIDE the window, it empties a search under
    the site's covering rule (b2c_common.timeslot). A slot repeated from the
    profile (a follow-up turn) is not invented."""
    if not time_slot or _CLOCK_TIME_RE.search(_user_text(tool_context)):
        return False
    return not _is_carried_slot(time_slot, profile_in)


def resolve_search_timeslot(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback` (A4-c interim): combine the model's `timeSlot`
    (now possibly minute-precise) with an explicit `duration` label into the
    EXACT requested window (minutes-of-day), then floor/ceil it to the whole
    hours the real `search_offers` schema accepts (live-probed: no minute
    fields exist server-side — a cross-repo ask, reports/MCP-B2C-REQUESTS.md).
    The exact window is stashed (`STATE_EXACT_WINDOW_KEY`) for
    `response_bridge.capture_after_tool` to recover: accurate
    `timeslot_start`/`timeslot_end` capture (core-e2e-084) and the
    offer-level exact-minute post-filter.

    A duration with NO start anywhere (fresh this turn OR carried over from
    `profile_in.timeslot_start`) invents NO window at all: `timeSlot` is
    popped/omitted entirely — the historic core-e2e-201 bug ("for 1 hour"
    becoming an absolute "00:00-01:00" window) is closed by construction, not
    by a special case, because there is simply nothing to compute a window
    from."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    profile_in = read_profile_in(tool_context)
    time_slot = args.get("timeSlot")
    time_slot = time_slot if isinstance(time_slot, dict) else {}
    daypart = _daypart_for_turn(time_slot, tool_context, profile_in)
    if daypart is not None:
        # MCP's own timeSlot is an OVERLAP filter: exactly the soft rule.
        # No exact window is stashed — the covering rule must not apply.
        args.pop("duration", None)
        start_hour, end_hour = DAYPART_HOURS[daypart]
        args["timeSlot"] = {"startHour": start_hour, "endHour": end_hour}
        tool_context.state[STATE_DAYPART_KEY] = daypart
        return None
    if _invented_time_slot(time_slot, tool_context, profile_in):
        mark_level("WARNING", status_message="timeslot_sanitization")
        record_guards_fired(tool_context, ["timeslot_sanitization"])
        time_slot = {}
    time_slot = _drop_unstated_carried_bounds(time_slot, tool_context, profile_in)
    start_total = _minutes_of_day(time_slot.get("startHour"), time_slot.get("startMinute"))
    end_total = _minutes_of_day(time_slot.get("endHour"), time_slot.get("endMinute"))
    duration_minutes = parse_duration_minutes(args.pop("duration", None))

    if start_total is None and duration_minutes is not None:
        start_total = _parse_hhmm_to_minutes(profile_in.get("timeslot_start"))
    if end_total is None and start_total is not None and duration_minutes is not None:
        end_total = min(start_total + duration_minutes, _MAX_MINUTE_OF_DAY)

    new_time_slot: dict[str, int] = {}
    if start_total is not None:
        new_time_slot["startHour"] = start_total // 60
    if end_total is not None:
        hour, minute = divmod(end_total, 60)
        new_time_slot["endHour"] = min(hour + 1, 23) if minute else hour
    if new_time_slot:
        args["timeSlot"] = new_time_slot
    else:
        args.pop("timeSlot", None)

    if start_total is not None or end_total is not None:
        tool_context.state[STATE_EXACT_WINDOW_KEY] = {
            "start_total": start_total,
            "end_total": end_total,
        }
    return None
