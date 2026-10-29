"""Point 5 of 2026-10-29 — the time slot (prod after #173, side by side with agent-usa).

- « domani pomeriggio »: a daypart filtered by OVERLAP only, so an 09-13 offer
  passed for the afternoon (Rome, 4 of 5 cards). Now an offer covers half of
  the daypart (`b2c_common.timeslot.slot_covers_daypart`); the model names the
  daypart in its own field (« sera notte » was missed by the regex).
- « check in is 3-4 pm » became `timeSlot {endHour: 16}`; « 9-18 »,
  « Sabah 09.00 akşam 17.00 » were dropped as invented. The model quotes its
  hours (`timeSlot.expression`) and says an arrival is one (`arrivalOnly`).
- « le 1er novembre » after 12h-18h: the slot dropped / the mode switched from
  `contain` to `overlap`. A turn that states no time keeps the window, and
  `timeSlotMode` is code-owned.

The MCP payload below is a trimmed copy of a real `search_offers` answer
(Rome, Piazza Venezia, 2026-10-30, timeSlot 12-18), hotel data only.
"""
from __future__ import annotations

import copy

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.models.llm_request import LlmRequest
from google.genai import types as genai_types

from hotel_search_agent.datetime_resolver import inject_datetime_declaration, resolve_search_timeslot
from hotel_search_agent.response_bridge import STATE_EXACT_WINDOW_KEY, normalize_search_results

_DAYPART_KEY = "temp:hotel_search_daypart"
_GUARDS_KEY = "temp:hotel_search_guards_fired"


class _Ctx:
    def __init__(self, user_content=None):
        self.state: dict = {}
        self.user_content = user_content


class _Tool:
    name = "search_offers"


def _ctx(text: str, profile_in: dict | None = None) -> _Ctx:
    datapart = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}}))
    return _Ctx(genai_types.Content(
        role="user", parts=[genai_types.Part(text=text), convert_a2a_part_to_genai_part(datapart)],
    ))


def _resolve(text: str, args: dict, profile_in: dict | None = None) -> _Ctx:
    ctx = _ctx(text, profile_in)
    resolve_search_timeslot(_Tool(), args, ctx)
    return ctx


def _offer(uuid: str, start: int, end: int, price: int) -> dict:
    return {
        "ratePlanUuid": uuid, "availabilityDate": "2026-10-30", "startHour": start, "startMinute": 0,
        "endHour": end, "endMinute": 0, "priceEuro": price, "priceEuroWithBookingFees": price + 400,
        "originalPriceEuro": 18000, "hotelCurrency": "EUR", "hotelPrice": price,
        "hotelPriceWithBookingFees": price + 400, "capacity": 2, "childrenCapacity": 0,
        "bedding": "double", "ratePlanName": "Standard Double Room",
    }


_ROME = {"results": [
    {"hotelId": 7793, "name": "UNA Hotels Decò Roma", "cityName": "roma", "countryName": "Italy",
     "starRating": 4, "globalAverageRating": 4.65, "totalReview": 46, "slug": "unahotels-deco-roma",
     "countryCode": "IT", "lat": 41.8999178, "lon": 12.499742, "distanceKm": 1.5, "currencyCode": "EUR",
     "score": 0.89,
     "offers": [_offer("a-9-13", 9, 13, 8000), _offer("a-10-17", 10, 17, 8500), _offer("a-15-20", 15, 20, 10000)]},
    {"hotelId": 9443, "name": "Warmthotel", "cityName": "roma", "countryName": "Italy",
     "starRating": 4, "globalAverageRating": 4.53, "totalReview": 89, "slug": "warmthotel",
     "countryCode": "IT", "lat": 41.8125818, "lon": 12.4753328, "distanceKm": 9.3, "currencyCode": "EUR",
     "score": 0.91,
     # Morning offers only (the 10-17 and 16-21 of the real answer removed).
     "offers": [_offer("b-9-12", 9, 12, 5900), _offer("b-11-14", 11, 14, 6900)]},
]}


# --- the afternoon is covered, not touched ---------------------------------------------------


def test_an_afternoon_card_carries_an_offer_covering_the_afternoon_not_the_cheapest_overlap():
    cards = normalize_search_results(copy.deepcopy(_ROME), None, "afternoon")
    assert [c["name"] for c in cards] == ["UNA Hotels Decò Roma"]
    assert cards[0]["timeslots"][0] == {"start": "10:00", "end": "17:00", "original_price": 180.0}


def test_a_hotel_with_only_morning_offers_is_not_an_afternoon_card():
    cards = normalize_search_results(copy.deepcopy(_ROME), None, "afternoon")
    assert "Warmthotel" not in [c["name"] for c in cards]


# --- the daypart is the model's field ---------------------------------------------------------


def test_the_models_daypart_applies_where_the_regex_reads_none():
    # S039 (prod, it): « sera notte » — no daypart the regex knows.
    args = {"daypart": "evening"}
    ctx = _resolve("Milano il 13, sera notte", args)
    assert args == {"timeSlot": {"startHour": 18, "endHour": 23}, "timeSlotMode": "overlap"}
    assert ctx.state[_DAYPART_KEY] == "evening"
    assert STATE_EXACT_WINDOW_KEY not in ctx.state


def test_a_daypart_outside_the_enum_is_ignored():
    args = {"daypart": "night"}
    ctx = _resolve("un hôtel à Lyon", args)
    assert "timeSlot" not in args and _DAYPART_KEY not in ctx.state


# --- quoted hours are kept, whatever the notation ---------------------------------------------


def test_hours_quoted_in_a_notation_the_regex_ignores_are_kept():
    # S015 (prod, de): « 9-18 » was dropped as an invented slot.
    args = {"timeSlot": {"startHour": 9, "endHour": 18, "expression": "9-18"}}
    ctx = _resolve("Morgen 9-18", args)
    assert args["timeSlot"] == {"startHour": 9, "endHour": 18}
    assert args["timeSlotMode"] == "contain"
    assert ctx.state[STATE_EXACT_WINDOW_KEY] == {"start_total": 540, "end_total": 1080}
    assert _GUARDS_KEY not in ctx.state


def test_hours_with_dots_and_words_around_them_are_kept():
    # S042 (prod, tr): « Sabah 09.00 akşam 17.00 » lost its slot.
    args = {"timeSlot": {"startHour": 9, "endHour": 17, "expression": "Sabah 09.00 akşam 17.00"}}
    _resolve("Sabah 09.00 akşam 17.00", args)
    assert args["timeSlot"] == {"startHour": 9, "endHour": 17}


def test_a_quote_that_is_not_in_the_message_proves_nothing():
    args = {"timeSlot": {"startHour": 12, "endHour": 23, "expression": "12-23"}}
    ctx = _resolve("un hôtel à Lyon demain", args)
    assert "timeSlot" not in args
    assert ctx.state[_GUARDS_KEY] == ["timeslot_sanitization"]


def test_an_hour_the_quote_does_not_hold_is_dropped():
    args = {"timeSlot": {"startHour": 9, "endHour": 15, "expression": "à 9h"}}
    _resolve("plutôt à 9h", args, {"timeslot_start": "13:00", "timeslot_end": "15:00"})
    assert args["timeSlot"] == {"startHour": 9}


# --- an arrival is not a departure --------------------------------------------------------------


def test_an_arrival_range_is_an_arrival_never_an_end_hour():
    # S063 (prod, en): « check in is 3-4 pm » searched as « until 16:00 ».
    args = {"timeSlot": {"startHour": 15, "endHour": 16, "expression": "3-4 pm", "arrivalOnly": True}}
    ctx = _resolve("San Carlos check in is 3-4 pm", args)
    assert args["timeSlot"] == {"startHour": 15}
    assert args["timeSlotMode"] == "overlap"
    assert ctx.state[STATE_EXACT_WINDOW_KEY] == {"start_total": 900, "end_total": None}


def test_pm_hours_quoted_on_a_12_hour_clock_are_written():
    args = {"timeSlot": {"startHour": 15, "endHour": 16, "expression": "3-4 pm"}}
    _resolve("check in is 3-4 pm", args)
    assert args["timeSlot"] == {"startHour": 15, "endHour": 16}


# --- the slot stays between turns, the mode is code-owned ---------------------------------------


def test_a_turn_that_states_no_time_keeps_the_window_in_play():
    # S056 (prod, fr): « le 1er novembre » after 12h-18h.
    args: dict = {}
    ctx = _resolve("le 1er novembre", args, {"timeslot_start": "12:00", "timeslot_end": "18:00"})
    assert args == {"timeSlot": {"startHour": 12, "endHour": 18}, "timeSlotMode": "contain"}
    assert ctx.state[STATE_EXACT_WINDOW_KEY] == {"start_total": 720, "end_total": 1080}


def test_the_models_own_mode_is_never_sent():
    args = {"timeSlot": {"startHour": 12, "endHour": 18, "expression": "12h-18h"}, "timeSlotMode": "overlap"}
    _resolve("le 1er novembre de 12h-18h", args)
    assert args["timeSlotMode"] == "contain"


def test_no_time_anywhere_sends_no_slot_and_no_mode():
    args = {"timeSlotMode": "contain"}
    ctx = _resolve("un hôtel à Lyon", args)
    assert args == {}
    assert STATE_EXACT_WINDOW_KEY not in ctx.state


def test_a_new_daypart_replaces_the_carried_clock_window():
    args = {"daypart": "morning"}
    ctx = _resolve("plutôt le matin", args, {"timeslot_start": "12:00", "timeslot_end": "18:00"})
    assert args["timeSlot"] == {"startHour": 8, "endHour": 12}
    assert ctx.state[_DAYPART_KEY] == "morning"


# --- what the model is shown --------------------------------------------------------------------


def test_the_declaration_offers_the_daypart_the_quote_and_the_arrival_and_hides_the_mode():
    schema = {
        "type": "object",
        "properties": {
            "lat": {"type": "number"}, "lon": {"type": "number"}, "date": {"type": "string"},
            "timeSlotMode": {"type": "string", "enum": ["overlap", "contain"]},
            "timeSlot": {"type": "object", "properties": {"startHour": {"type": "integer"},
                                                         "endHour": {"type": "integer"}}},
        },
        "required": ["lat", "lon", "date"],
    }
    decl = genai_types.FunctionDeclaration(name="search_offers")
    decl.parameters_json_schema = schema
    request = LlmRequest(config=genai_types.GenerateContentConfig(
        tools=[genai_types.Tool(function_declarations=[decl])]
    ))
    inject_datetime_declaration(None, request)
    widened = request.config.tools[0].function_declarations[0].parameters_json_schema
    assert widened["properties"]["daypart"]["enum"] == ["morning", "afternoon", "evening"]
    assert "timeSlotMode" not in widened["properties"]
    slot = widened["properties"]["timeSlot"]["properties"]
    assert slot["expression"]["type"] == "string" and slot["arrivalOnly"]["type"] == "boolean"
