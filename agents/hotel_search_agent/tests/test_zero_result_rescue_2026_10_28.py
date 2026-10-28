"""Point 3 (prod 2026-10-27/28): « Aucune offre » no longer ends the turn.

36 empty searches after #160, from their real `search_offers` arguments (traces
Langfuse): a hard amenity filter (Dublin, jacuzzi 41), a strict slot (Wan Chai
« check in at around 9pm », 21h, 2 km, the same day; La Rochelle « à 14h » + spa
35), the same-day evening (Barcelona at 19:53, no filter left: MCP now counts
`total` AFTER the cutoff check and `totalBeforeCutoff` before it, so the
next-day probe keyed on `total` never fired), a 2 km ring around « la
métropole lilloise » (the building of the Métropole européenne de Lille). And
the recovery chips « quitar un filtro », « aumentar el presupuesto » re-ran the
same search.

The MCP payload shapes are the live ones (probed read-only 2026-10-28: Hong
Kong 2 km at 17h local `total=0, totalBeforeCutoff=4`; Dublin jacuzzi 0, Dublin
without it 19 hotels 0.4-2.1 km; La Rochelle spa 0, without the slot nor the spa
Novotel La Rochelle Centre 0.6 km). Offline: a fake tool records every call.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import (
    convert_a2a_part_to_genai_part,
    convert_genai_part_to_a2a_part,
)
from google.genai import types as genai_types

from hotel_search_agent import response_bridge
from hotel_search_agent.completion import complete_thin_search_after_tool
from hotel_search_agent.datetime_resolver import probe_next_day_after_tool
from hotel_search_agent.relaxation import (
    MAX_RESCUE_CALLS,
    apply_relax_request,
    inject_relaxation_declaration,
    read_relax_request,
    rescue_empty_search_after_tool,
)
from hotel_search_agent.response_bridge import (
    STATE_AMENITIES_MUST_HAVE_KEY,
    STATE_APPLIED_AMENITIES_KEY,
    STATE_COMPLETION_KEY,
    STATE_DATE_FALLBACK_KEY,
    STATE_EXACT_WINDOW_KEY,
    STATE_NEARBY_KEY,
    STATE_NEXT_DAY_PROBED_KEY,
    STATE_PREFERRED_AMENITIES_KEY,
    STATE_RELAX_APPLIED_KEY,
    STATE_RESCUE_KEY,
    STATE_RESCUE_RAN_KEY,
    STATE_SEARCH_DATE_KEY,
    capture_after_tool,
    emit_search_datapart,
    inject_landmark_radius,
    pool_before_cutoff,
    radius_floor_km,
)

# --- live-shaped payloads ---------------------------------------------------------------------


def _hotel(i: int, name: str, km: float, *, start: int = 7, end: int = 15, day: str = "2026-10-29") -> dict:
    return {
        "hotelId": i, "name": name, "cityName": "X", "countryName": "Y", "starRating": 4,
        "globalAverageRating": 4.4, "distanceKm": km,
        "offers": [{"priceEuro": 10400, "priceEuroWithBookingFees": 11100, "startHour": start, "startMinute": 0,
                    "endHour": end, "endMinute": 0, "availabilityDate": day, "ratePlanId": i}],
    }


def _payload(*hotels: dict, total: int | None = None, before: int | None = None, day: str = "2026-10-29") -> dict:
    data: dict = {"resolvedDate": day, "total": len(hotels) if total is None else total,
                  "results": list(hotels)}
    if before is not None:
        data["totalBeforeCutoff"] = before
    return data


def _response(payload: dict) -> dict:
    return {"structuredContent": payload}


_DUBLIN = [_hotel(1, "Marlin Hotel Stephens Green", 1.1), _hotel(2, "NYX Hotel Dublin Christchurch", 0.8),
           _hotel(3, "Maldron Hotel Parnell Square", 0.4)]
_WANCHAI = [_hotel(11, "Kew Green Hotel Wanchai Hong Kong", 0.8, start=10, end=18),
            _hotel(12, "Shama Central Hong Kong", 1.0, start=10, end=18)]
_ROCHELLE = [_hotel(21, "Novotel La Rochelle Centre", 0.6, day="2026-11-04")]


class _Search:
    """`search_offers` as the after-tool callbacks see it: answers in order."""

    name = "search_offers"

    def __init__(self, *answers: dict | Exception, schema: dict | None = None):
        self.answers = list(answers)
        self.calls: list[dict] = []
        self.raw_mcp_tool = SimpleNamespace(inputSchema=schema) if schema else None

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        answer = self.answers.pop(0) if self.answers else _response(_payload())
        if isinstance(answer, Exception):
            raise answer
        return answer


def _state(day: str, *, same_day: bool, applied: list[str] | None = None, **extra) -> dict:
    return {STATE_APPLIED_AMENITIES_KEY: applied or [], STATE_PREFERRED_AMENITIES_KEY: [],
            STATE_SEARCH_DATE_KEY: {"date": day, "same_day": same_day}, **extra}


def _rescue(tool: _Search, args: dict, state: dict, first: dict) -> SimpleNamespace:
    ctx = SimpleNamespace(state=state, user_content=None)
    assert asyncio.run(rescue_empty_search_after_tool(tool, dict(args), ctx, first)) is None
    return ctx


#: Dublin, « Find a room with a jacuzzi » → « Dublin » (session eaf1fad8).
_DUBLIN_ARGS = {"lat": 53.34938, "lon": -6.260559, "hotelEquipmentIds": [41], "from": 0, "date": "2026-10-29"}
#: « Check in at around 9pm wan chai side » (session ee50581d), same day.
_WANCHAI_ARGS = {"lat": 22.279356, "lon": 114.16255, "timeSlot": {"startHour": 21}, "timeSlotMode": "contain",
                 "from": 0, "radiusKm": 2, "sortBy": "distance", "date": "2026-10-28"}
#: « Le 4 novembre à 14h à la Rochelle » + spa (session 8ded983e).
_ROCHELLE_ARGS = {"lat": 46.15778, "lon": -1.153455, "timeSlot": {"startHour": 14}, "timeSlotMode": "contain",
                  "hotelEquipmentIds": [35], "from": 0, "radiusKm": 50, "date": "2026-11-04"}


# --- the count MCP sends now ------------------------------------------------------------------


def test_the_pool_before_cutoff_is_read_from_its_own_count():
    assert pool_before_cutoff({"total": 0, "totalBeforeCutoff": 4}) == 4
    assert pool_before_cutoff({"total": 12}) == 12  # an older server: total, before cutoff


def test_the_next_day_probe_fires_on_a_closed_day_counted_after_cutoff():
    """Hong Kong 2 km, 17h local: total 0, 4 before cutoff — the probe used to
    read `total` alone and never fired (none of the 13 same-day evenings)."""
    tool = _Search(_response(_payload(*_WANCHAI)))
    state = _state("2026-10-28", same_day=True)
    ctx = SimpleNamespace(state=state, user_content=None)
    first = _response(_payload(total=0, before=4, day="2026-10-28"))
    asyncio.run(probe_next_day_after_tool(tool, {"lat": 1, "lon": 2, "date": "2026-10-28"}, ctx, first))
    assert [call["date"] for call in tool.calls] == ["2026-10-29"]
    assert ctx.state[STATE_DATE_FALLBACK_KEY]["offered_date"] == "2026-10-29"
    assert ctx.state[STATE_NEXT_DAY_PROBED_KEY] is True


def test_the_next_day_probe_stays_off_over_an_empty_pool():
    tool = _Search(_response(_payload(*_WANCHAI)))
    ctx = SimpleNamespace(state=_state("2026-10-28", same_day=True), user_content=None)
    asyncio.run(probe_next_day_after_tool(tool, {"date": "2026-10-28"}, ctx,
                                          _response(_payload(total=0, before=0))))
    assert tool.calls == [] and STATE_NEXT_DAY_PROBED_KEY not in ctx.state


# --- the rescue -------------------------------------------------------------------------------


def test_an_amenity_that_is_not_a_must_have_is_relaxed_first_when_no_slot():
    tool = _Search(_response(_payload(*_DUBLIN)))
    ctx = _rescue(tool, _DUBLIN_ARGS, _state("2026-10-29", same_day=False, applied=["jacuzzi"]),
                  _response(_payload(total=0, before=0)))
    [sent] = tool.calls
    assert "hotelEquipmentIds" not in sent and "from" not in sent
    assert sent["date"] == "2026-10-29"
    rescue = ctx.state[STATE_RESCUE_KEY]
    assert rescue["steps"] == ["amenities"] and rescue["amenities"] == ["jacuzzi"]


def test_a_relaxed_search_that_finds_today_closed_moves_to_the_next_day():
    """Wan Chai, 21h: once relaxed, hotels matched today but all past their
    cutoff (total 0 < 4 before cutoff): the same relaxation the day after."""
    tool = _Search(_response(_payload(total=0, before=4, day="2026-10-28")),
                   _response(_payload(*_WANCHAI)))
    ctx = _rescue(tool, _WANCHAI_ARGS, _state("2026-10-28", same_day=True),
                  _response(_payload(total=0, before=0, day="2026-10-28")))
    assert len(tool.calls) == MAX_RESCUE_CALLS
    first, second = tool.calls
    assert first["radiusKm"] == 50 and first["date"] == "2026-10-28"
    assert second["radiusKm"] == 50 and second["date"] == "2026-10-29"
    rescue = ctx.state[STATE_RESCUE_KEY]
    assert rescue["steps"] == ["radius", "next_day"] and rescue["offered_date"] == "2026-10-29"


def test_the_steps_are_taken_in_the_order_that_saves_most():
    """R1 (review of #173): amenity, then ring, then slot — Fabien's replay
    on MCP prod: amenity 14/16, ring ×2 11/26, slot 1/10. La Rochelle 14h +
    spa: the spa goes first, then the ring; the slot is never reached."""
    tool = _Search(_response(_payload(day="2026-11-04")), _response(_payload(*_ROCHELLE, day="2026-11-04")))
    ctx = _rescue(tool, _ROCHELLE_ARGS, _state("2026-11-04", same_day=False, applied=["spa"]),
                  _response(_payload(day="2026-11-04")))
    first, second = tool.calls
    assert "hotelEquipmentIds" not in first and first["timeSlot"] == {"startHour": 14} and first["radiusKm"] == 50
    assert "hotelEquipmentIds" not in second and second["timeSlot"] == {"startHour": 14}
    assert second["radiusKm"] == 100
    assert ctx.state[STATE_RESCUE_KEY]["steps"] == ["amenities", "radius"]


def test_a_must_have_amenity_is_kept_and_the_ring_widens_instead():
    tool = _Search(_response(_payload(*_DUBLIN)))
    state = _state("2026-10-29", same_day=False, applied=["jacuzzi"], **{STATE_AMENITIES_MUST_HAVE_KEY: True})
    ctx = _rescue(tool, _DUBLIN_ARGS, state, _response(_payload()))
    [sent] = tool.calls
    assert sent["hotelEquipmentIds"] == [41]
    assert sent["radiusKm"] == 50.0 and sent["sortBy"] == "distance"
    assert ctx.state[STATE_RESCUE_KEY]["steps"] == ["radius"]


def test_a_must_have_still_lets_the_optional_wishes_go():
    tool = _Search(_response(_payload(*_DUBLIN)))
    state = _state("2026-10-29", same_day=False, applied=["jacuzzi"],
                   **{STATE_AMENITIES_MUST_HAVE_KEY: True, STATE_PREFERRED_AMENITIES_KEY: ["spa"]})
    ctx = _rescue(tool, {**_DUBLIN_ARGS, "hotelEquipmentIds": [41, 35]}, state, _response(_payload()))
    assert tool.calls[0]["hotelEquipmentIds"] == [41]
    assert ctx.state[STATE_RESCUE_KEY]["amenities"] == ["spa"]


def test_the_rescue_runs_once_per_turn_and_never_on_a_later_page_or_a_full_one():
    cases = [
        ({**_DUBLIN_ARGS, "from": 5}, _state("2026-10-29", same_day=False, applied=["jacuzzi"]),
         _response(_payload())),
        (_DUBLIN_ARGS, _state("2026-10-29", same_day=False, applied=["jacuzzi"],
                              **{STATE_RESCUE_RAN_KEY: True}), _response(_payload())),
        (_DUBLIN_ARGS, _state("2026-10-29", same_day=False, applied=["jacuzzi"]),
         _response(_payload(*_DUBLIN))),
        (_DUBLIN_ARGS, _state("2026-10-29", same_day=False, applied=["jacuzzi"],
                              **{STATE_DATE_FALLBACK_KEY: {"offered_date": "2026-10-30"}}),
         _response(_payload())),
        (_DUBLIN_ARGS, _state("2026-10-29", same_day=False), {"isError": True, "content": []}),
    ]
    for args, state, first in cases:
        tool = _Search(_response(_payload(*_DUBLIN)))
        ctx = _rescue(tool, args, state, first)
        assert tool.calls == [] and STATE_RESCUE_KEY not in ctx.state, args


def test_the_next_day_probe_counts_against_the_rescue_budget():
    tool = _Search(_response(_payload(total=0, before=4, day="2026-10-28")), _response(_payload(*_WANCHAI)))
    state = _state("2026-10-28", same_day=True, **{STATE_NEXT_DAY_PROBED_KEY: True})
    ctx = _rescue(tool, _WANCHAI_ARGS, state, _response(_payload(total=0, before=0)))
    assert len(tool.calls) == 1 and STATE_RESCUE_KEY not in ctx.state


def test_nothing_to_relax_costs_no_call_and_a_failure_is_swallowed():
    tool = _Search(_response(_payload(*_DUBLIN)))
    _rescue(tool, {"lat": 35.67, "lon": 139.65, "radiusKm": 100, "date": "2026-10-28", "from": 0},
            _state("2026-10-28", same_day=True), _response(_payload(total=0, before=0)))
    assert tool.calls == []
    ctx = _rescue(_Search(RuntimeError("429"), RuntimeError("429")), _DUBLIN_ARGS,
                  _state("2026-10-29", same_day=False, applied=["jacuzzi"]), _response(_payload()))
    assert STATE_RESCUE_KEY not in ctx.state


def test_the_completion_stands_down_after_a_rescue_that_found_cards():
    tool = _Search(_response(_payload(*_DUBLIN)))
    state = _state("2026-10-29", same_day=False, applied=["jacuzzi"], **{
        STATE_RESCUE_RAN_KEY: True,
        STATE_RESCUE_KEY: {"payload": _payload(*_DUBLIN), "steps": ["amenities"]},
    })
    ctx = SimpleNamespace(state=state, user_content=None)
    asyncio.run(complete_thin_search_after_tool(tool, dict(_DUBLIN_ARGS), ctx, _response(_payload())))
    assert tool.calls == [] and STATE_COMPLETION_KEY not in ctx.state


def test_after_an_empty_rescue_the_completion_still_widens_with_the_filters():
    # Replay 2026-10-28 (« dans la métropole lilloise entre 14 et 18 » +
    # jacuzzi): the rescue's two calls found nothing, the completion's 50 km
    # ring with the jacuzzi did (4 hotels on main).
    tool = _Search(_response(_payload(*_DUBLIN)))
    state = _state("2026-10-29", same_day=False, applied=["jacuzzi"], **{STATE_RESCUE_RAN_KEY: True})
    ctx = SimpleNamespace(state=state, user_content=None)
    asyncio.run(complete_thin_search_after_tool(tool, dict(_DUBLIN_ARGS), ctx, _response(_payload())))
    assert len(tool.calls) == 1 and tool.calls[0]["hotelEquipmentIds"] == [41]
    assert STATE_COMPLETION_KEY in ctx.state


# --- the capture serves the rescue and says what was relaxed ----------------------------------


def _decode(content: genai_types.Content) -> dict:
    return next(convert_genai_part_to_a2a_part(p).root.data for p in content.parts if p.inline_data is not None)


def test_rescued_cards_are_served_without_claiming_the_relaxed_amenity():
    state = _state("2026-10-29", same_day=False, applied=["jacuzzi"])
    state[STATE_RESCUE_KEY] = {"payload": _payload(*_DUBLIN), "steps": ["amenities"],
                               "searched_date": "2026-10-29", "amenities": ["jacuzzi"]}
    ctx = SimpleNamespace(state=state, user_content=None)
    capture_after_tool(SimpleNamespace(name="search_offers"), dict(_DUBLIN_ARGS), ctx, _response(_payload()))
    data = _decode(emit_search_datapart(ctx))
    assert [card["name"] for card in data["results"]][:1] == ["Marlin Hotel Stephens Green"]
    assert all("jacuzzi" not in (card.get("amenities") or []) for card in data["results"])
    assert data["relaxation"] == {"steps": ["amenities"], "searched_date": "2026-10-29", "amenities": ["jacuzzi"]}
    # The filter itself stays the user's: it is not dropped from the profile.
    assert data["profile_delta"]["amenities"] == {"op": "set", "value": ["jacuzzi"]}


def test_a_next_day_rescue_serves_that_day_and_flags_the_closest_slot():
    state = _state("2026-10-28", same_day=True, **{STATE_EXACT_WINDOW_KEY: {"start_total": 21 * 60, "end_total": None}})
    state[STATE_RESCUE_KEY] = {"payload": _payload(*_WANCHAI), "steps": ["timeslot", "next_day"],
                               "searched_date": "2026-10-28", "offered_date": "2026-10-29"}
    ctx = SimpleNamespace(state=state, user_content=None)
    capture_after_tool(SimpleNamespace(name="search_offers"), dict(_WANCHAI_ARGS), ctx,
                       _response(_payload(total=0, before=0, day="2026-10-28")))
    data = _decode(emit_search_datapart(ctx))
    assert len(data["results"]) == 2
    assert data["search_date"]["date"] == "2026-10-29"
    assert data["search_date"]["cutoff_fallback_from"] == "2026-10-28"
    assert data["profile_delta"]["date"] == {"op": "set", "value": "2026-10-29"}
    assert data["timeslot_fallback"]
    assert data["relaxation"]["steps"] == ["timeslot", "next_day"]


# --- the user's request to loosen the search --------------------------------------------------


def _ctx_with_query(query_params: dict, state: dict | None = None) -> SimpleNamespace:
    part = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": query_params, "profile_in": {}}))
    content = genai_types.Content(role="user", parts=[genai_types.Part(text="x"), convert_a2a_part_to_genai_part(part)])
    return SimpleNamespace(state=state if state is not None else {}, user_content=content)


def _request(args: dict, *, relax: str | None = None, chip: str | None = None, state: dict | None = None) -> tuple:
    args = dict(args)
    if relax:
        args["relax"] = relax
    ctx = _ctx_with_query({"relax": chip} if chip else {}, state)
    tool = SimpleNamespace(name="search_offers")
    read_relax_request(tool, args, ctx)
    apply_relax_request(tool, args, ctx)
    return args, ctx


def test_the_model_label_area_widens_the_ring():
    args, ctx = _request({"lat": 1.0, "lon": 2.0, "date": "2026-10-28"}, relax="area")
    assert ctx.state[STATE_NEARBY_KEY] is True
    assert "relax" not in args


def test_remove_a_filter_drops_the_amenities_for_good():
    """« quitar un filtro » after « jacuzzi »: the filter leaves the search and the profile."""
    state = {STATE_APPLIED_AMENITIES_KEY: ["jacuzzi"], STATE_PREFERRED_AMENITIES_KEY: []}
    args, ctx = _request({**_DUBLIN_ARGS}, chip="filters", state=state)
    assert "hotelEquipmentIds" not in args
    assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == []
    assert ctx.state[STATE_RELAX_APPLIED_KEY] == {"requested": ["filters"], "removed": ["amenities"],
                                                  "amenities": ["jacuzzi"]}


def test_remove_a_filter_without_amenity_drops_the_slot_and_the_profile_forgets_it():
    state = {STATE_APPLIED_AMENITIES_KEY: [], STATE_PREFERRED_AMENITIES_KEY: []}
    args, ctx = _request({**_WANCHAI_ARGS}, chip="filters", state=state)
    assert "timeSlot" not in args and "timeSlotMode" not in args
    ctx.state["temp:hotel_search_results"] = []
    data = _decode(emit_search_datapart(ctx))
    assert data["profile_delta"]["timeslot_start"] == {"op": "clear"}
    assert data["relaxation"]["request"]["removed"] == ["timeslot"]


def test_nothing_to_remove_is_said_not_pretended():
    """Barcelona: « quitar un filtro » over a search with no filter left."""
    args, ctx = _request({"lat": 41.38, "lon": 2.16, "date": "2026-10-27"}, chip="filters",
                         state={STATE_APPLIED_AMENITIES_KEY: [], STATE_PREFERRED_AMENITIES_KEY: []})
    assert ctx.state[STATE_RELAX_APPLIED_KEY]["nothing_to_remove"] is True


def test_raise_the_budget_raises_the_cap_of_this_search_only():
    args, ctx = _request({"lat": 1.0, "lon": 2.0, "date": "2026-10-28", "priceRangeMax": 80}, relax="budget")
    assert args["priceRangeMax"] == 100.0
    assert ctx.state[STATE_RELAX_APPLIED_KEY]["budget"] == {"from": 80.0, "to": 100.0}
    ctx.state["temp:hotel_search_results"] = []
    capture_after_tool(SimpleNamespace(name="search_offers"), args, ctx, _response(_payload(*_DUBLIN)))
    data = _decode(emit_search_datapart(ctx))
    assert "budget_max" not in data.get("profile_delta", {})


def test_raise_the_budget_without_a_cap_is_said():
    """« increase the budget » (Wan Chai): there was no cap to raise."""
    args, ctx = _request({"lat": 1.0, "lon": 2.0, "date": "2026-10-28"}, chip="budget")
    capture_after_tool(SimpleNamespace(name="search_offers"), args, ctx, _response(_payload()))
    data = _decode(emit_search_datapart(ctx))
    assert data["relaxation"]["request"]["no_budget"] is True


def test_the_virtual_params_never_reach_mcp_nor_a_name_lookup():
    args = {"name": "Ibis", "relax": "area", "amenities_must_have": True}
    read_relax_request(SimpleNamespace(name="find_hotel_by_name"), args, SimpleNamespace(state={}, user_content=None))
    assert args == {"name": "Ibis"}


def test_the_declaration_offers_relax_and_must_have():
    decl = SimpleNamespace(name="search_offers", parameters_json_schema={"type": "object", "properties": {}})
    request = SimpleNamespace(config=SimpleNamespace(tools=[SimpleNamespace(function_declarations=[decl])]))
    inject_relaxation_declaration(None, request)
    props = decl.parameters_json_schema["properties"]
    assert props["relax"]["enum"] == ["area", "filters", "time", "budget"]
    assert props["amenities_must_have"]["type"] == "boolean"


# --- the ring floor ---------------------------------------------------------------------------


class _DenseInventory:
    def count_near(self, lat, lon, radius_km):
        return 50  # dense: the site's ring is the smallest, 2 km


@pytest.fixture
def dense(monkeypatch):
    monkeypatch.setattr(response_bridge, "get_inventory", lambda: _DenseInventory())


def _ring(anchor: dict, profile_in: dict | None = None) -> float:
    part = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}}))
    content = genai_types.Content(role="user", parts=[convert_a2a_part_to_genai_part(part)])
    ctx = SimpleNamespace(state={"temp:hotel_search_anchor": anchor}, user_content=content)
    args = {"lat": anchor["latitude"], "lon": anchor["longitude"], "date": "2026-11-05"}
    inject_landmark_radius(SimpleNamespace(name="search_offers"), args, ctx)
    return args["radiusKm"]


def test_an_area_is_never_searched_on_a_building_ring(dense):
    """« Dans la métropole lilloise »: the GeoIntent said `region`, Mapbox
    returned the MEL building (poi). 2 km → the city ring."""
    anchor = {"latitude": 50.63119107, "longitude": 3.07808304, "type": "poi",
              "place_kind": "region", "feature_type": "poi"}
    assert _ring(anchor) == 20.0


def test_a_neighbourhood_gets_at_least_five_km(dense):
    """« wan chai side »: `neighborhood`, resolved to the Hong Kong place."""
    anchor = {"latitude": 22.279356, "longitude": 114.16255, "type": "poi",
              "place_kind": "neighborhood", "feature_type": "place"}
    assert _ring(anchor) == 5.0


def test_a_station_keeps_the_site_ring(dense):
    anchor = {"latitude": 41.90128243, "longitude": 12.50157624, "type": "poi",
              "place_kind": "station", "feature_type": "poi"}
    assert _ring(anchor) == 2.0
    assert radius_floor_km({"place_kind": "landmark", "feature_type": "poi"}) is None


def test_a_follow_up_keeps_the_zone_kind_through_the_profile():
    """« Sans jaccuzzi »: an empty intent re-resolves the carried zone; its
    kind comes back from the profile, so the ring stays an area's."""
    part = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {}, "profile_in": {"zone_kind": "region"}}))
    content = genai_types.Content(role="user", parts=[convert_a2a_part_to_genai_part(part)])
    ctx = SimpleNamespace(state={}, user_content=content)
    geocode = {"ok": True, "latitude": 50.63, "longitude": 3.07, "resolved_place": "MEL",
               "resolved_feature_type": "poi", "distance_origin_type": "poi",
               "profile_delta": {"zone": "Métropole européenne de Lille"}}
    capture_after_tool(SimpleNamespace(name="geocode_location"), {"intent": {}}, ctx, geocode)
    assert ctx.state["temp:hotel_search_anchor"]["place_kind"] == "region"
    ctx.state["temp:hotel_search_results"] = []
    data = _decode(emit_search_datapart(ctx))
    assert data["profile_delta"]["zone_kind"] == {"op": "set", "value": "region"}


def test_rescued_cards_link_to_the_users_site_like_every_other_card():
    # #172 (links in the user's language) × point 3: the cards the rescue
    # serves are built on the user's host too (a French user, Irish hotels).
    irish = [{**hotel, "slug": f"hotel-{i}", "countryCode": "IE", "countryName": "Ireland"}
             for i, hotel in enumerate(_DUBLIN)]
    state = _state("2026-10-29", same_day=False, applied=["jacuzzi"])
    state[STATE_RESCUE_KEY] = {"payload": _payload(*irish), "steps": ["amenities"],
                               "searched_date": "2026-10-29", "amenities": ["jacuzzi"]}
    datapart = a2a_types.Part(root=a2a_types.DataPart(data={
        "query_params": {}, "profile_in": {"language": "fr", "entry_market_country": "FR"},
    }))
    ctx = SimpleNamespace(state=state, user_content=genai_types.Content(
        role="user", parts=[genai_types.Part(text="jacuzzi"), convert_a2a_part_to_genai_part(datapart)],
    ))
    capture_after_tool(SimpleNamespace(name="search_offers"), dict(_DUBLIN_ARGS), ctx, _response(_payload()))
    urls = [card.get("url") for card in _decode(emit_search_datapart(ctx))["results"]]
    assert urls and all(url.startswith("https://www.dayuse.fr/hotels/") for url in urls)


# --- R1 (review of #173): the real after-tool chain, nothing stashed by hand --------------------


class _FakeMcp:
    """`search_offers` answering on the arguments it receives (date, slot,
    amenity), like MCP: what the chain sends decides what comes back."""

    name = "search_offers"
    raw_mcp_tool = None

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        return _response(self.answer(args))


def _chain_ctx(state: dict) -> SimpleNamespace:
    """A tool context with what the fleet's timing/metrics callbacks read."""
    return SimpleNamespace(state=state, user_content=None, agent_name="b2c_hotel_search", invocation_id="t")


async def _after_chain(tool, args: dict, ctx, first: dict):
    """`root_agent.after_tool_callback` in order, ADK's rule: the first
    non-None return ends the chain (`capture_after_tool` rewrites)."""
    from hotel_search_agent.agent import root_agent

    for callback in root_agent.after_tool_callback:
        result = callback(tool=tool, args=args, tool_context=ctx, tool_response=first)
        if asyncio.iscoroutine(result):
            result = await result
        if result is not None:
            return result
    return None


def test_the_same_evening_with_a_strict_slot_ends_on_the_next_day_without_it():
    """Fabien's reproduction: today 18h+ with a strict slot, today closing.
    Before: probe (J+1, slot) empty, then the rescue relaxed the slot on
    TODAY (closed) — nothing, while J+1 without the slot had 2 hotels."""
    today, tomorrow = "2026-10-28", "2026-10-29"

    def answer(args):
        if args["date"] == today:
            return _payload(total=0, before=6, day=today)
        if "timeSlot" in args:
            return _payload(day=tomorrow)
        return _payload(*_WANCHAI, day=tomorrow)

    tool = _FakeMcp(answer)
    args = {"lat": 22.279356, "lon": 114.16255, "timeSlot": {"startHour": 21}, "timeSlotMode": "contain",
            "radiusKm": 100, "sortBy": "distance", "date": today}
    ctx = _chain_ctx(_state(today, same_day=True))
    first = _response(answer(args))

    asyncio.run(_after_chain(tool, dict(args), ctx, first))

    assert [(c["date"], "timeSlot" in c) for c in tool.calls] == [(tomorrow, True), (tomorrow, False)]
    data = _decode(emit_search_datapart(ctx))
    assert [card["name"] for card in data["results"]] == [h["name"] for h in _WANCHAI]
    assert data["relaxation"]["steps"] == ["timeslot", "next_day"]
    assert data["search_date"]["date"] == tomorrow
    # Visible in Langfuse (`fallback_search_rescue`) and in `turn_facts.fallbacks`.
    assert data["fallbacks_fired"] == ["search_rescue"]
