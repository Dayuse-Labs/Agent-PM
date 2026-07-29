"""Offline unit tests for S-G6's date/duration/minute resolution.

No network, no LLM, no MCP. The injection tests use the REAL ADK `LlmRequest`
and genai `FunctionDeclaration` types (same pattern as test_equipment_ids.py);
the before_tool_callback tests build `user_content` through the REAL ADK
a2a->genai part converter (same pattern as test_response_bridge.py).
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, timedelta

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.models.llm_request import LlmRequest
from google.genai import types as genai_types

from hotel_search_agent.datetime_resolver import (
    inject_datetime_declaration,
    parse_duration_minutes,
    probe_next_day_after_tool,
    reference_today,
    resolve_date_label,
    resolve_search_date,
    resolve_search_timeslot,
)
from hotel_search_agent.response_bridge import (
    STATE_DATE_FALLBACK_KEY,
    STATE_EXACT_WINDOW_KEY,
    STATE_RESOLVED_DATE_KEY,
    STATE_SEARCH_DATE_KEY,
)


class _Ctx:
    def __init__(self, state=None, user_content=None):
        self.state = state if state is not None else {}
        self.user_content = user_content


class _Tool:
    def __init__(self, name):
        self.name = name


def _user_content_with_profile(profile_in: dict) -> genai_types.Content:
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in})
    )
    return genai_types.Content(
        role="user",
        parts=[genai_types.Part(text="hotel"), convert_a2a_part_to_genai_part(datapart)],
    )


def _ctx_with_profile(profile_in: dict) -> _Ctx:
    return _Ctx(user_content=_user_content_with_profile(profile_in))


# --- inject_datetime_declaration (before_model) -------------------------------------------------

_MCP_SCHEMA = {
    "type": "object",
    "properties": {
        "lat": {"type": "number"},
        "lon": {"type": "number"},
        "date": {"type": "string", "format": "date"},
        "timeSlot": {
            "type": "object",
            "properties": {
                "startHour": {"type": "integer", "minimum": 0, "maximum": 23},
                "endHour": {"type": "integer", "minimum": 0, "maximum": 23},
            },
            "additionalProperties": False,
        },
    },
    "required": ["lat", "lon", "date"],
    "additionalProperties": False,
}


def _llm_request(schema: dict | None) -> LlmRequest:
    decl = genai_types.FunctionDeclaration(name="search_offers")
    if schema is not None:
        decl.parameters_json_schema = schema
    other = genai_types.FunctionDeclaration(
        name="find_hotel_by_name", parameters_json_schema={"type": "object", "properties": {}}
    )
    return LlmRequest(
        config=genai_types.GenerateContentConfig(
            tools=[genai_types.Tool(function_declarations=[other, decl])]
        )
    )


def test_inject_replaces_date_with_a_label_object():
    request = _llm_request(copy.deepcopy(_MCP_SCHEMA))
    assert inject_datetime_declaration(None, request) is None
    decl = request.config.tools[0].function_declarations[1]
    date_prop = decl.parameters_json_schema["properties"]["date"]
    assert date_prop["type"] == "object"
    assert date_prop["properties"]["type"]["enum"] == ["absolute", "relative"]


def test_inject_adds_duration_and_timeslot_minutes():
    request = _llm_request(copy.deepcopy(_MCP_SCHEMA))
    inject_datetime_declaration(None, request)
    decl = request.config.tools[0].function_declarations[1]
    schema = decl.parameters_json_schema
    assert schema["properties"]["duration"]["type"] == "string"
    slot_props = schema["properties"]["timeSlot"]["properties"]
    assert slot_props["startMinute"]["enum"] == [0, 15, 30, 45]
    assert slot_props["endMinute"]["enum"] == [0, 15, 30, 45]


def test_inject_removes_date_from_required_but_keeps_lat_lon():
    request = _llm_request(copy.deepcopy(_MCP_SCHEMA))
    inject_datetime_declaration(None, request)
    decl = request.config.tools[0].function_declarations[1]
    assert decl.parameters_json_schema["required"] == ["lat", "lon"]


def test_inject_never_mutates_the_source_schema_dict():
    source = copy.deepcopy(_MCP_SCHEMA)
    request = _llm_request(source)
    inject_datetime_declaration(None, request)
    assert source == _MCP_SCHEMA


def test_inject_leaves_other_declarations_untouched():
    request = _llm_request(copy.deepcopy(_MCP_SCHEMA))
    inject_datetime_declaration(None, request)
    other = request.config.tools[0].function_declarations[0]
    assert "date" not in (other.parameters_json_schema or {}).get("properties", {})


def test_inject_noop_without_parameters_json_schema():
    request = _llm_request(None)
    assert inject_datetime_declaration(None, request) is None
    assert request.config.tools[0].function_declarations[1].parameters_json_schema is None


def test_inject_is_idempotent_per_request():
    request = _llm_request(copy.deepcopy(_MCP_SCHEMA))
    inject_datetime_declaration(None, request)
    inject_datetime_declaration(None, request)
    decl = request.config.tools[0].function_declarations[1]
    assert decl.parameters_json_schema["properties"]["duration"]["type"] == "string"


# --- reference_today ------------------------------------------------------------------------


def test_reference_today_uses_client_timezone_when_valid():
    # Fixed comparison: a timezone far ahead of UTC vs far behind can legally
    # disagree with the OS local date at the instant of the test run, so we
    # only assert it does NOT raise and returns a real date object.
    result = reference_today({"client_timezone": "Asia/Tokyo"})
    assert isinstance(result, date)


def test_reference_today_falls_back_to_server_clock_on_invalid_timezone():
    assert reference_today({"client_timezone": "Not/AZone"}) == date.today()


def test_reference_today_falls_back_to_server_clock_when_absent():
    assert reference_today({}) == date.today()


# --- resolve_date_label ----------------------------------------------------------------------

_TODAY = date(2026, 7, 23)  # a Thursday


def test_resolve_relative_today_tomorrow_day_after_tomorrow():
    assert resolve_date_label({"type": "relative", "value": "today"}, _TODAY) == (
        _TODAY, "relative", None,
    )
    assert resolve_date_label({"type": "relative", "value": "tomorrow"}, _TODAY)[0] == date(
        2026, 7, 24
    )
    assert resolve_date_label(
        {"type": "relative", "value": "day_after_tomorrow"}, _TODAY
    )[0] == date(2026, 7, 25)


def test_resolve_relative_weekday_means_next_occurrence_never_today():
    # _TODAY is a Thursday: "thursday" must resolve to NEXT week, not today.
    resolved, resolved_from, _ = resolve_date_label(
        {"type": "relative", "value": "thursday"}, _TODAY
    )
    assert resolved == date(2026, 7, 30)
    assert resolved_from == "relative"


def test_resolve_relative_weekday_ahead_this_week():
    resolved, _, _ = resolve_date_label({"type": "relative", "value": "monday"}, _TODAY)
    assert resolved == date(2026, 7, 27)  # next Monday, 4 days ahead


def test_resolve_absolute_iso_date():
    resolved, resolved_from, _ = resolve_date_label(
        {"type": "absolute", "value": "2026-08-05", "expression": "August 5th"}, _TODAY
    )
    assert resolved == date(2026, 8, 5)
    assert resolved_from == "absolute"


def test_resolve_absolute_month_day_without_year_stays_this_year_when_future():
    resolved, _, _ = resolve_date_label({"type": "absolute", "value": "12-25"}, _TODAY)
    assert resolved == date(2026, 12, 25)


def test_resolve_absolute_month_day_without_year_rolls_to_next_year_when_past():
    resolved, _, _ = resolve_date_label({"type": "absolute", "value": "01-01"}, _TODAY)
    assert resolved == date(2027, 1, 1)


def test_resolve_missing_or_malformed_label_defaults_to_today():
    assert resolve_date_label(None, _TODAY) == (_TODAY, "default", None)
    assert resolve_date_label({}, _TODAY) == (_TODAY, "default", None)
    assert resolve_date_label({"type": "relative", "value": "gibberish"}, _TODAY)[1] == "default"
    assert resolve_date_label({"type": "absolute", "value": "not-a-date"}, _TODAY)[1] == "default"


def test_resolve_absolute_invalid_calendar_date_defaults():
    assert resolve_date_label({"type": "absolute", "value": "02-30"}, _TODAY)[1] == "default"


def test_resolve_absolute_iso_with_hallucinated_past_year_rolls_forward():
    """Prod 2026-07-29: gpt-4o-mini labelled "6 aout" as "2023-08-06" (it was
    told never to add a year), the leaf searched three years back and the empty
    result was served as "no offers in Melun". The month/day it extracted is
    still good — keep it, drop its year."""
    resolved, resolved_from, expression = resolve_date_label(
        {"type": "absolute", "value": "2023-08-06", "expression": "6 aout"}, _TODAY
    )
    assert resolved == date(2026, 8, 6)  # _TODAY is 2026-07-23
    assert resolved_from == "absolute"
    assert expression == "6 aout"


def test_resolve_absolute_iso_past_year_whose_month_day_already_passed_rolls_a_year():
    # Same rule as the year-less branch: 01-01 is next year's, never last year's.
    resolved, _, _ = resolve_date_label({"type": "absolute", "value": "2023-01-01"}, _TODAY)
    assert resolved == date(2027, 1, 1)


def test_resolve_absolute_iso_past_year_with_impossible_month_day_defaults():
    assert resolve_date_label({"type": "absolute", "value": "2023-02-30"}, _TODAY)[1] == "default"


def test_resolve_absolute_iso_today_itself_is_kept():
    resolved, _, _ = resolve_date_label(
        {"type": "absolute", "value": _TODAY.isoformat()}, _TODAY
    )
    assert resolved == _TODAY  # >= today, so never rolled forward


# --- resolve_search_date (before_tool_callback) -----------------------------------------------


def test_resolve_date_ignores_other_tools():
    ctx = _ctx_with_profile({})
    args = {"date": {"type": "relative", "value": "tomorrow"}}
    assert resolve_search_date(_Tool("find_hotel_by_name"), args, ctx) is None
    assert args["date"] == {"type": "relative", "value": "tomorrow"}  # untouched


def test_resolve_date_fresh_relative_label_writes_iso_and_stashes_delta():
    ctx = _ctx_with_profile({})
    args = {"date": {"type": "relative", "value": "tomorrow", "expression": "demain"}}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert args["date"] != "tomorrow"
    assert len(args["date"]) == 10 and args["date"].count("-") == 2  # ISO YYYY-MM-DD
    stashed = ctx.state[STATE_RESOLVED_DATE_KEY]
    assert stashed["date"] == args["date"]
    assert stashed["date_reference"]["resolved_from"] == "relative"
    assert stashed["date_reference"]["expression"] == "demain"


def test_resolve_date_fresh_absolute_label_writes_iso_and_stashes_delta():
    ctx = _ctx_with_profile({})
    args = {"date": {"type": "absolute", "value": "2026-08-05", "expression": "August 5th"}}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert args["date"] == "2026-08-05"
    stashed = ctx.state[STATE_RESOLVED_DATE_KEY]
    assert stashed["date"] == "2026-08-05"
    assert stashed["date_reference"]["resolved_from"] == "absolute"


def test_resolve_date_includes_client_tz_in_date_reference_when_present():
    ctx = _ctx_with_profile({"client_timezone": "Europe/Paris"})
    args = {"date": {"type": "relative", "value": "today"}}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert ctx.state[STATE_RESOLVED_DATE_KEY]["date_reference"]["client_tz"] == "Europe/Paris"


def test_resolve_date_no_label_carries_over_profile_date_and_stashes_nothing():
    # Computed from the real clock, not hardcoded: `reference_today` reads it
    # when no client_timezone is given, so a literal date would silently turn
    # this carry-over test into a past-date test the day it went by.
    future = (date.today() + timedelta(days=7)).isoformat()
    ctx = _ctx_with_profile({"date": future})
    args = {}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert args["date"] == future
    assert STATE_RESOLVED_DATE_KEY not in ctx.state  # nothing new to persist


def test_resolve_date_hallucinated_past_year_never_reaches_mcp_nor_the_profile():
    """The verbatim payload from prod trace 1ee2b59c (2026-07-29 12:57 UTC),
    driven through the real callback: MCP must never receive the past date, and
    the profile must never persist it (that persistence is what made turn 2 fail
    too — the model read it back out of profile_in and re-sent it)."""
    ctx = _ctx_with_profile({})
    args = {"date": {"type": "absolute", "value": "2023-08-06", "expression": "6 aout"}}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert args["date"] >= date.today().isoformat()
    assert args["date"].endswith("-08-06")  # the month/day the user really gave
    assert ctx.state[STATE_RESOLVED_DATE_KEY]["date"] == args["date"]


def test_resolve_date_carried_over_past_date_falls_back_to_today():
    """A session straddling midnight carries yesterday's resolved date (30-min
    sliding TTL). Searching it is a guaranteed empty result, and empty reads as
    "no offers here" — so the floor applies to the carry-over path too."""
    ctx = _ctx_with_profile({"date": (date.today() - timedelta(days=1)).isoformat()})
    args = {}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert args["date"] == date.today().isoformat()
    assert STATE_RESOLVED_DATE_KEY not in ctx.state  # a floor is not a new fact


def test_a_floored_stale_carried_date_is_stashed_as_the_same_day_it_became():
    """Merge seam between the past-date floor (PR #57) and S-CX6's stash: the
    floor runs FIRST, so `same_day` describes the search that actually ran. Get
    the order wrong and a session carrying yesterday's date lands on today with
    `same_day=False` — the closed-day probe then never fires on the one turn
    that needs it, and the user gets "no offers" for a day that is simply over."""
    ctx = _ctx_with_profile({"date": (date.today() - timedelta(days=1)).isoformat()})
    args = {}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert ctx.state[STATE_SEARCH_DATE_KEY] == {
        "date": date.today().isoformat(),
        "same_day": True,
    }


def test_resolve_date_carried_over_today_is_kept():
    ctx = _ctx_with_profile({"date": date.today().isoformat()})
    args = {}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert args["date"] == date.today().isoformat()


def test_resolve_date_carried_over_non_iso_value_falls_back_to_today():
    ctx = _ctx_with_profile({"date": "next tuesday"})
    args = {}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert args["date"] == date.today().isoformat()


def test_resolve_date_no_label_no_profile_date_falls_back_to_today():
    ctx = _ctx_with_profile({})
    args = {}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert args["date"] == date.today().isoformat()
    assert STATE_RESOLVED_DATE_KEY not in ctx.state


def test_resolve_date_malformed_label_behaves_like_no_label():
    future = (date.today() + timedelta(days=7)).isoformat()  # clock-relative, see above
    ctx = _ctx_with_profile({"date": future})
    args = {"date": {"type": "relative", "value": "gibberish"}}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert args["date"] == future  # carryover wins, "gibberish" never persisted
    assert STATE_RESOLVED_DATE_KEY not in ctx.state


# --- parse_duration_minutes --------------------------------------------------------------------


def test_parse_duration_hours_minutes_and_combined():
    assert parse_duration_minutes("PT1H") == 60
    assert parse_duration_minutes("PT30M") == 30
    assert parse_duration_minutes("PT1H30M") == 90
    assert parse_duration_minutes("pt2h") == 120  # case-insensitive


def test_parse_duration_rejects_garbage():
    assert parse_duration_minutes("PT") is None
    assert parse_duration_minutes("1 hour") is None
    assert parse_duration_minutes(None) is None
    assert parse_duration_minutes(60) is None


# --- resolve_search_timeslot (before_tool_callback, A4-c) ---------------------------------------


def test_timeslot_ignores_other_tools():
    ctx = _ctx_with_profile({})
    args = {"timeSlot": {"startHour": 7, "startMinute": 30}}
    assert resolve_search_timeslot(_Tool("find_hotel_by_name"), args, ctx) is None
    assert args["timeSlot"] == {"startHour": 7, "startMinute": 30}


def test_timeslot_sub_hour_window_floors_and_ceils_for_mcp():
    ctx = _ctx_with_profile({})
    args = {"timeSlot": {"startHour": 7, "startMinute": 30, "endHour": 13, "endMinute": 30}}
    resolve_search_timeslot(_Tool("search_offers"), args, ctx)
    assert args["timeSlot"] == {"startHour": 7, "endHour": 14}
    exact = ctx.state[STATE_EXACT_WINDOW_KEY]
    assert exact == {"start_total": 7 * 60 + 30, "end_total": 13 * 60 + 30}


def test_timeslot_whole_hour_window_unchanged_from_before():
    ctx = _ctx_with_profile({})
    args = {"timeSlot": {"startHour": 14, "endHour": 20}}
    resolve_search_timeslot(_Tool("search_offers"), args, ctx)
    assert args["timeSlot"] == {"startHour": 14, "endHour": 20}
    assert ctx.state[STATE_EXACT_WINDOW_KEY] == {"start_total": 14 * 60, "end_total": 20 * 60}


def test_timeslot_duration_with_fresh_start_computes_end():
    ctx = _ctx_with_profile({})
    args = {"timeSlot": {"startHour": 9}, "duration": "PT1H30M"}
    resolve_search_timeslot(_Tool("search_offers"), args, ctx)
    assert "duration" not in args
    assert args["timeSlot"] == {"startHour": 9, "endHour": 11}  # 9:00 + 1h30 = 10:30 -> ceil 11
    assert ctx.state[STATE_EXACT_WINDOW_KEY] == {"start_total": 9 * 60, "end_total": 10 * 60 + 30}


def test_timeslot_duration_alone_invents_no_window():
    # core-e2e-201: "for 1 hour" with NO start anywhere must never become an
    # absolute window.
    ctx = _ctx_with_profile({})
    args = {"duration": "PT1H"}
    resolve_search_timeslot(_Tool("search_offers"), args, ctx)
    assert "timeSlot" not in args
    assert "duration" not in args
    assert STATE_EXACT_WINDOW_KEY not in ctx.state


def test_timeslot_duration_combines_with_carried_over_start():
    ctx = _ctx_with_profile({"timeslot_start": "09:00"})
    args = {"duration": "PT1H"}
    resolve_search_timeslot(_Tool("search_offers"), args, ctx)
    assert args["timeSlot"] == {"startHour": 9, "endHour": 10}
    assert ctx.state[STATE_EXACT_WINDOW_KEY] == {"start_total": 9 * 60, "end_total": 10 * 60}


def test_timeslot_one_sided_start_only_kept_as_is():
    ctx = _ctx_with_profile({})
    args = {"timeSlot": {"startHour": 15, "startMinute": 15}}
    resolve_search_timeslot(_Tool("search_offers"), args, ctx)
    assert args["timeSlot"] == {"startHour": 15}
    assert ctx.state[STATE_EXACT_WINDOW_KEY] == {"start_total": 15 * 60 + 15, "end_total": None}


def test_timeslot_absent_entirely_stashes_nothing():
    ctx = _ctx_with_profile({})
    args = {}
    resolve_search_timeslot(_Tool("search_offers"), args, ctx)
    assert "timeSlot" not in args
    assert STATE_EXACT_WINDOW_KEY not in ctx.state


def test_timeslot_end_never_overflows_past_23():
    ctx = _ctx_with_profile({})
    args = {"timeSlot": {"startHour": 22, "endHour": 23, "endMinute": 45}}
    resolve_search_timeslot(_Tool("search_offers"), args, ctx)
    assert args["timeSlot"]["endHour"] == 23  # never 24


# --- S-CX6: same-day cutoff → next-day probe ----------------------------------------------------
# Live-measured premise (2026-07-27, MCP staging): every day-use offer's
# `cutoffDeadlineUtc` falls on the stay date itself (Paris 05h→16h, latest 16h),
# so an afternoon search dated today returns `total=518, results=[]` — a closed
# day, not an empty market. These tests pin WHEN the extra MCP call is spent.


class _ProbeTool:
    """A search_offers stand-in that records the args of the probe's re-call."""

    name = "search_offers"

    def __init__(self, payload=None, raises=False):
        self._payload = payload
        self._raises = raises
        self.calls: list[dict] = []

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        if self._raises:
            raise RuntimeError("MCP down")
        return {"structuredContent": self._payload, "isError": False}


def _closed_day_response(total: int = 518) -> dict:
    """What MCP really returns for a same-day search after the last cutoff."""
    return {
        "structuredContent": {
            "resolvedDate": "2026-07-27",
            "total": total,
            "results": [],
            "has_more": True,
            "next_offset": 5,
        },
        "isError": False,
    }


def _bookable_payload(iso_date: str = "2026-07-28") -> dict:
    return {
        "resolvedDate": iso_date,
        "total": 518,
        "results": [
            {
                "hotelId": 1,
                "name": "Villa Paris Orly",
                "cityName": "Paris",
                "offers": [{"priceEuro": 5400, "availabilityDate": iso_date, "ratePlanId": 1}],
            }
        ],
    }


def _same_day_ctx(today: str = "2026-07-27") -> _Ctx:
    ctx = _ctx_with_profile({})
    ctx.state[STATE_SEARCH_DATE_KEY] = {"date": today, "same_day": True}
    return ctx


async def _run_probe(tool, ctx, response, args=None) -> None:
    await probe_next_day_after_tool(
        tool, args if args is not None else {"lat": 48.84, "lon": 2.37, "date": "2026-07-27"},
        ctx, response,
    )


def test_probe_stashes_the_next_day_when_today_is_closed():
    tool = _ProbeTool(_bookable_payload())
    ctx = _same_day_ctx()
    asyncio.run(_run_probe(tool, ctx, _closed_day_response()))
    stashed = ctx.state[STATE_DATE_FALLBACK_KEY]
    assert stashed["searched_date"] == "2026-07-27"
    assert stashed["offered_date"] == "2026-07-28"  # D+1, computed in code
    assert stashed["payload"]["results"][0]["name"] == "Villa Paris Orly"
    assert tool.calls[0]["date"] == "2026-07-28"


def test_probe_returns_none_so_it_never_breaks_the_after_tool_chain():
    # ADK stops at the first truthy after_tool_callback result: a probe that
    # returned its payload would cost capture_after_tool's compact rewrite.
    tool = _ProbeTool(_bookable_payload())
    out = asyncio.run(
        probe_next_day_after_tool(
            tool, {"lat": 48.84, "lon": 2.37, "date": "2026-07-27"},
            _same_day_ctx(), _closed_day_response(),
        )
    )
    assert out is None


def test_probe_keeps_the_filters_but_restarts_at_page_one():
    tool = _ProbeTool(_bookable_payload())
    args = {
        "lat": 48.84, "lon": 2.37, "date": "2026-07-27", "from": 50,
        "priceRangeMax": 80.0, "timeSlot": {"startHour": 14, "endHour": 20},
        "hotelEquipmentIds": [33],
    }
    asyncio.run(_run_probe(tool, _same_day_ctx(), _closed_day_response(), args))
    sent = tool.calls[0]
    assert "from" not in sent  # another day is page 1, not page 11
    assert sent["priceRangeMax"] == 80.0
    assert sent["timeSlot"] == {"startHour": 14, "endHour": 20}
    assert sent["hotelEquipmentIds"] == [33]


def test_probe_flags_the_closed_window_as_the_established_cause():
    # This flag is what licenses the concierge to SAY "today is closed": hotels
    # matched (total > 0) and none was bookable. It is stamped even when the
    # next day turns out empty too — that turn still needs date-first chips.
    tool = _ProbeTool({"resolvedDate": "2026-07-28", "total": 518, "results": []})
    ctx = _same_day_ctx()
    asyncio.run(_run_probe(tool, ctx, _closed_day_response()))
    assert ctx.state[STATE_SEARCH_DATE_KEY]["cutoff_closed"] is True


def test_probe_never_flags_a_closed_window_on_an_empty_pool():
    # total == 0 (probed: Tokyo) is "no day-use inventory here", NOT a closed
    # booking window — flagging it would fabricate the cause downstream.
    tool = _ProbeTool(_bookable_payload())
    ctx = _same_day_ctx()
    asyncio.run(_run_probe(tool, ctx, _closed_day_response(total=0)))
    assert "cutoff_closed" not in ctx.state[STATE_SEARCH_DATE_KEY]


def test_probe_does_not_fire_on_an_empty_pool():
    # total == 0 is a market with no inventory at all (probed: Tokyo) — another
    # day cannot help, so the second MCP call would be pure waste.
    tool = _ProbeTool(_bookable_payload())
    ctx = _same_day_ctx()
    asyncio.run(_run_probe(tool, ctx, _closed_day_response(total=0)))
    assert tool.calls == [] and STATE_DATE_FALLBACK_KEY not in ctx.state


def test_probe_does_not_fire_on_a_future_date_search():
    tool = _ProbeTool(_bookable_payload())
    ctx = _ctx_with_profile({})
    ctx.state[STATE_SEARCH_DATE_KEY] = {"date": "2026-08-05", "same_day": False}
    asyncio.run(_run_probe(tool, ctx, _closed_day_response()))
    assert tool.calls == [] and STATE_DATE_FALLBACK_KEY not in ctx.state


def test_probe_does_not_fire_when_the_search_already_returned_hotels():
    tool = _ProbeTool(_bookable_payload())
    ctx = _same_day_ctx()
    asyncio.run(
        _run_probe(tool, ctx, {"structuredContent": _bookable_payload("2026-07-27"), "isError": False})
    )
    assert tool.calls == [] and STATE_DATE_FALLBACK_KEY not in ctx.state


def test_probe_ignores_a_failed_search():
    for response in (
        {"isError": True},
        {"error": "mcp_circuit_open"},
        {"ok": False},
    ):
        tool = _ProbeTool(_bookable_payload())
        ctx = _same_day_ctx()
        asyncio.run(_run_probe(tool, ctx, response))
        assert tool.calls == [], response
        assert STATE_DATE_FALLBACK_KEY not in ctx.state, response


def test_probe_swallows_an_mcp_failure_of_its_own():
    # A rescue probe must never turn an honest empty answer into a broken turn.
    tool = _ProbeTool(raises=True)
    ctx = _same_day_ctx()
    asyncio.run(_run_probe(tool, ctx, _closed_day_response()))
    assert STATE_DATE_FALLBACK_KEY not in ctx.state


def test_probe_stashes_nothing_when_the_next_day_is_empty_too():
    tool = _ProbeTool({"resolvedDate": "2026-07-28", "total": 518, "results": []})
    ctx = _same_day_ctx()
    asyncio.run(_run_probe(tool, ctx, _closed_day_response()))
    assert tool.calls and STATE_DATE_FALLBACK_KEY not in ctx.state


def test_resolve_search_date_always_stamps_the_searched_date():
    # The carry-over/default path persists NOTHING to the profile — this key is
    # the only way anything downstream can name the date it searched.
    ctx = _ctx_with_profile({})
    args = {}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    today = date.today().isoformat()
    assert args["date"] == today
    assert ctx.state[STATE_SEARCH_DATE_KEY] == {"date": today, "same_day": True}


def test_resolve_search_date_marks_a_carried_over_future_date_as_not_today():
    ctx = _ctx_with_profile({"date": "2026-09-09"})
    args = {}
    resolve_search_date(_Tool("search_offers"), args, ctx)
    assert ctx.state[STATE_SEARCH_DATE_KEY] == {"date": "2026-09-09", "same_day": False}
