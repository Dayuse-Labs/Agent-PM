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
    "date lost on a later turn" bug in reverse).
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
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hotel_search_agent.response_bridge import (
    STATE_EXACT_WINDOW_KEY,
    STATE_RESOLVED_DATE_KEY,
    read_profile_in,
)

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


def _resolve_absolute(value: Any, today: date) -> date | None:
    v = str(value or "").strip()
    match = _ISO_DATE_RE.match(v)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = _MONTH_DAY_RE.match(v)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        try:
            candidate = date(today.year, month, day)
        except ValueError:
            return None
        if candidate < today:
            try:
                candidate = date(today.year + 1, month, day)
            except ValueError:
                return None
        return candidate
    return None


def resolve_date_label(label: Any, today: date) -> tuple[date, str, str | None]:
    """(resolved_date, resolved_from, expression) from the model's `date` label.
    `resolved_from` in {"relative", "absolute", "default"} — "default" covers a
    missing/malformed label (the caller decides whether that's a fresh-turn
    bootstrap or a carryover; this function only ever resolves what it's given)."""
    if isinstance(label, dict):
        expression = label.get("expression") if isinstance(label.get("expression"), str) else None
        label_type, value = label.get("type"), label.get("value")
        if label_type == "relative":
            resolved = _resolve_relative(value, today)
            if resolved is not None:
                return resolved, "relative", expression
        elif label_type == "absolute":
            resolved = _resolve_absolute(value, today)
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
    avoided by construction rather than patched after the fact)."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    profile_in = read_profile_in(tool_context)
    today = reference_today(profile_in)
    label = args.pop("date", None)
    if isinstance(label, dict) and label.get("type") in ("relative", "absolute"):
        resolved_date, resolved_from, expression = resolve_date_label(label, today)
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
            return None
    # No fresh, resolvable label this turn — carry over rather than re-derive.
    carried = profile_in.get("date")
    args["date"] = carried if isinstance(carried, str) and carried else today.isoformat()
    return None


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
