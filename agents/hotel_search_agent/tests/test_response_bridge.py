"""Offline unit tests for the leaf's structured-results DataPart + truncation bridge.

No network, no LLM, no MCP: the callbacks are pure functions over fake
tool/agent contexts. The DataPart is verified through the REAL ADK A2A converter
(`convert_genai_part_to_a2a_part`), the exact hop the orchestrator relies on.
"""
from __future__ import annotations

import json

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import (
    convert_a2a_part_to_genai_part,
    convert_genai_part_to_a2a_part,
)
from google.genai import types as genai_types

from hotel_search_agent.response_bridge import (
    MAX_RESULTS,
    STATE_APPLIED_AMENITIES_KEY,
    STATE_EXACT_WINDOW_KEY,
    STATE_RESOLVED_DATE_KEY,
    _photo_url,
    capture_after_tool,
    decode_datapart,
    emit_search_datapart,
    encode_datapart,
    find_datapart,
    inject_pagination_offset,
    normalize_hotel,
    normalize_search_results,
    read_profile_in,
    skip_final_generation,
    stamp_turn_start,
)


class _Ctx:
    """Minimal stand-in for ADK ToolContext/CallbackContext (dict-backed .state
    + optional user_content, mirroring test_equipment_ids.py's fixture)."""

    def __init__(self, state=None, user_content=None):
        self.state = state if state is not None else {}
        self.user_content = user_content


class _Tool:
    def __init__(self, name):
        self.name = name


def _user_content_with_profile_in(profile_in: dict) -> genai_types.Content:
    """The inbound message as the leaf actually sees it: the orchestrator's
    `{query_params, profile_in}` a2a DataPart converted by the REAL ADK
    converter into the tag-envelope genai Part riding user_content (same
    pattern as test_equipment_ids.py's `_user_content_with_profile`)."""
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in})
    )
    return genai_types.Content(
        role="user",
        parts=[genai_types.Part(text="autres options"), convert_a2a_part_to_genai_part(datapart)],
    )


def _hotel(i: int, price: int) -> dict:
    return {
        "hotelId": i,
        "name": f"Hotel {i}",
        "cityName": "Paris",
        "countryName": "France",
        "starRating": 4,
        "globalAverageRating": 4.5,
        "offers": [
            {
                "priceEuro": price,
                "startHour": 10,
                "startMinute": 0,
                "endHour": 17,
                "endMinute": 0,
                "availabilityDate": "2026-07-21",
                "ratePlanId": 1,
            }
        ],
    }


def _search_offers_structured(n: int = 7) -> dict:
    return {
        "resolvedDate": "2026-07-21",
        "total": n,
        "results": [_hotel(i, 5000 + i * 100) for i in range(n)],
    }


# --- normalize_search_results ---------------------------------------------------------------
def test_normalize_maps_camelcase_and_caps_at_five():
    out = normalize_search_results(_search_offers_structured(7))
    assert len(out) == 5  # capped
    first = out[0]
    assert first["id"] == 0 and first["hotel_id"] == 0
    assert first["name"] == "Hotel 0"
    assert first["city"] == "Paris"
    assert first["country"] == "France"
    assert first["stars"] == 4
    assert first["rating"] == 4.5
    assert first["price"] == "€50.00"  # priceEuro 5000 cents → €50.00 (S07-consistent)
    assert first["timeslots"] == [{"start": "10:00", "end": "17:00"}]


# --- hotel photo URL (mainPhotoNormal -> static.dayuse.com) ----------------------------------
def test_photo_url_prefixes_a_relative_main_photo_normal():
    assert _photo_url("/hotels/22293/abc-villa-paris-orly.png") == (
        "https://static.dayuse.com/hotels/22293/abc-villa-paris-orly.png"
    )


def test_photo_url_rejects_missing_or_malformed_values():
    for bad in (None, "", "not-a-path", 42, ["/hotels/1/a.png"]):
        assert _photo_url(bad) is None


# --- card coordinates + distance instrumentation (A8-a, S-G3) -------------------------------
_ANCHOR_KEY = "temp:hotel_search_anchor"
_DISTANCE_ORIGIN_KEY = "temp:hotel_search_distance_origin"
_RESULTS_KEY = "temp:hotel_search_results"


def _geo_hotel(i, lat, lon):
    return {"hotelId": i, "name": f"Hotel {i}", "lat": lat, "lon": lon,
            "offers": [{"priceEuro": 5000, "startHour": 10, "startMinute": 0, "endHour": 17, "endMinute": 0}]}


def test_normalize_hotel_carries_lat_lon_when_present():
    card = normalize_hotel(_geo_hotel(1, 48.8588, 2.3469))
    assert card["latitude"] == 48.8588
    assert card["longitude"] == 2.3469


def test_normalize_hotel_omits_lat_lon_when_absent():
    card = normalize_hotel(_hotel(1, 5000))  # helper carries no coordinates
    assert "latitude" not in card and "longitude" not in card


# --- per-hotel currency_code (S-G7, display-only — live-probed 2026-07-23) -------------------
def test_normalize_hotel_stamps_currency_code_from_currencycode():
    hotel = _hotel(1, 11933)
    hotel["currencyCode"] = "usd"
    card = normalize_hotel(hotel)
    assert card["currency_code"] == "USD"
    assert card["price"] == "€119.33"  # priceEuro is unaffected — no conversion


def test_normalize_hotel_omits_currency_code_when_absent_or_garbage():
    for bad in (None, "", "EURO", 42):
        hotel = _hotel(1, 5000)
        hotel["currencyCode"] = bad
        assert "currency_code" not in normalize_hotel(hotel)
    assert "currency_code" not in normalize_hotel(_hotel(1, 5000))  # key absent entirely


def test_normalize_hotel_omits_lat_lon_on_garbage():
    card = normalize_hotel({"hotelId": 1, "name": "X", "lat": "nope", "lon": None})
    assert "latitude" not in card and "longitude" not in card


def test_capture_geocode_stashes_the_resolved_anchor():
    ctx = _Ctx()
    resp = {"ok": True, "latitude": 48.8566, "longitude": 2.3522,
            "resolved_place": "Paris, Île-de-France, France", "distance_origin_type": "city_centroid",
            "profile_delta": {"last_city": "Paris"}}
    capture_after_tool(_Tool("geocode_location"), {}, ctx, resp)
    anchor = ctx.state[_ANCHOR_KEY]
    assert anchor["latitude"] == 48.8566 and anchor["longitude"] == 2.3522
    assert anchor["type"] == "city_centroid"
    assert anchor["label"] == "Paris, Île-de-France, France"


def test_capture_search_offers_stamps_distance_km_from_stashed_anchor():
    ctx = _Ctx({_ANCHOR_KEY: {"latitude": 48.8566, "longitude": 2.3522, "label": "Paris", "type": "city_centroid"}})
    structured = {"total": 1, "results": [_geo_hotel(1, 48.8588, 2.3469)]}
    capture_after_tool(_Tool("search_offers"), {"lat": 48.8566, "lon": 2.3522}, ctx, {"structuredContent": structured, "isError": False})
    card = ctx.state[_RESULTS_KEY][0]
    assert "distance_km" in card and card["distance_km"] < 1.0  # ~0.6 km from Notre-Dame
    origin = ctx.state[_DISTANCE_ORIGIN_KEY]
    assert origin["type"] == "city_centroid"


def test_capture_search_offers_distance_from_args_when_no_anchor():
    ctx = _Ctx()  # no stashed anchor (e.g. the model geocoded in a prior turn)
    structured = {"total": 1, "results": [_geo_hotel(1, 40.71, -74.0)]}
    capture_after_tool(_Tool("search_offers"), {"lat": 40.71, "lon": -74.0}, ctx, {"structuredContent": structured, "isError": False})
    assert ctx.state[_RESULTS_KEY][0]["distance_km"] == 0.0
    assert ctx.state[_DISTANCE_ORIGIN_KEY]["type"] == "search_coordinate"


def test_capture_search_offers_no_distance_without_any_origin():
    ctx = _Ctx()
    structured = {"total": 1, "results": [_geo_hotel(1, 40.71, -74.0)]}
    capture_after_tool(_Tool("search_offers"), {}, ctx, {"structuredContent": structured, "isError": False})
    assert "distance_km" not in ctx.state[_RESULTS_KEY][0]
    assert _DISTANCE_ORIGIN_KEY not in ctx.state


def test_emit_includes_distance_origin_when_results_present():
    ctx = _Ctx({
        _RESULTS_KEY: [{"id": 1, "name": "Villa", "latitude": 48.8, "longitude": 2.3, "distance_km": 0.5}],
        _DISTANCE_ORIGIN_KEY: {"latitude": 48.8566, "longitude": 2.3522, "label": "Paris", "type": "city_centroid"},
    })
    from hotel_search_agent.response_bridge import decode_datapart as _dec  # local, avoids top churn
    content = emit_search_datapart(ctx)
    data = None
    for part in content.parts:
        d = _dec(part)
        if d is not None:
            data = d
    assert data["distance_origin"]["type"] == "city_centroid"
    assert data["results"][0]["distance_km"] == 0.5


def test_normalize_hotel_sets_image_urls_when_main_photo_normal_present():
    hotel = _hotel(1, 5000)
    hotel["mainPhotoNormal"] = "/hotels/1/photo.png"
    card = normalize_hotel(hotel)
    assert card["image_urls"] == ["https://static.dayuse.com/hotels/1/photo.png"]


def test_normalize_hotel_omits_image_urls_without_a_photo():
    card = normalize_hotel(_hotel(1, 5000))  # no mainPhotoNormal in the fixture
    assert "image_urls" not in card


def test_normalize_picks_cheapest_offer():
    hotel = {
        "hotelId": 9,
        "name": "Multi",
        "offers": [
            {"priceEuro": 9000, "startHour": 9, "startMinute": 0, "endHour": 12, "endMinute": 0},
            {"priceEuro": 4000, "startHour": 14, "startMinute": 0, "endHour": 20, "endMinute": 30},
        ],
    }
    card = normalize_search_results({"results": [hotel]})[0]
    assert card["price"] == "€40.00"
    assert card["timeslots"] == [{"start": "14:00", "end": "20:30"}]


def test_normalize_handles_find_hotel_by_name_single_shape():
    out = normalize_search_results({"hotel": {"hotelId": 42, "name": "Solo", "cityName": "Lyon"}})
    assert len(out) == 1
    assert out[0]["id"] == 42 and out[0]["name"] == "Solo" and out[0]["city"] == "Lyon"
    assert out[0]["amenities"] == []  # search_offers/identity carry no amenities


def test_normalize_empty_and_garbage():
    assert normalize_search_results({}) == []
    assert normalize_search_results({"results": []}) == []
    assert normalize_search_results(None) == []
    assert normalize_search_results("nope") == []


# --- exclude_ids (S-G5 pagination safety net) --------------------------------------------------
def test_normalize_excludes_already_shown_ids_before_the_top_five_cut():
    structured = _search_offers_structured(7)  # hotelId 0..6
    out = normalize_search_results(structured, exclude_ids={0, 1, 2})
    ids = [h["hotel_id"] for h in out]
    assert 0 not in ids and 1 not in ids and 2 not in ids
    assert ids == [3, 4, 5, 6]  # 4 survivors, still capped at MAX_RESULTS (not hit here)


def test_normalize_exclude_ids_can_shrink_below_max_results():
    structured = _search_offers_structured(3)  # hotelId 0,1,2
    out = normalize_search_results(structured, exclude_ids={0, 1})
    assert len(out) == 1 and out[0]["hotel_id"] == 2


def test_normalize_no_exclude_ids_behaves_exactly_as_before():
    out = normalize_search_results(_search_offers_structured(7), exclude_ids=None)
    assert len(out) == MAX_RESULTS
    out2 = normalize_search_results(_search_offers_structured(7), exclude_ids=set())
    assert len(out2) == MAX_RESULTS


# --- capture_after_tool ---------------------------------------------------------------------
def test_capture_search_offers_truncates_and_stashes():
    ctx = _Ctx()
    big_text = json.dumps(_search_offers_structured(7))  # the ~24k-token mirror
    resp = {"structuredContent": _search_offers_structured(7), "content": [{"type": "text", "text": big_text}], "isError": False}
    returned = capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    # payload the model now ingests is the compact top-5, WITHOUT the text mirror
    assert returned is not None
    assert "content" not in returned
    assert len(returned["hotels"]) == 5
    assert returned["total"] == 7
    # full normalized results stashed for emit_search_datapart
    assert len(ctx.state["temp:hotel_search_results"]) == 5


def test_capture_search_offers_failure_is_untouched():
    ctx = _Ctx()
    assert capture_after_tool(_Tool("search_offers"), {}, ctx, {"isError": True}) is None
    assert capture_after_tool(_Tool("search_offers"), {}, ctx, {"ok": False, "error": "x"}) is None
    assert ctx.state == {}  # nothing stashed on failure


def test_capture_falls_back_to_content_text_when_no_structured_content():
    ctx = _Ctx()
    resp = {"content": [{"type": "text", "text": json.dumps(_search_offers_structured(2))}], "isError": False}
    returned = capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert returned is not None and len(returned["hotels"]) == 2
    assert len(ctx.state["temp:hotel_search_results"]) == 2


def test_capture_geocode_stashes_profile_delta_no_truncation():
    ctx = _Ctx()
    resp = {"ok": True, "latitude": 48.8, "longitude": 2.3, "profile_delta": {"last_city": "Paris"}}
    assert capture_after_tool(_Tool("geocode_location"), {}, ctx, resp) is None  # not truncated
    assert ctx.state["temp:hotel_search_profile_delta"] == {"last_city": "Paris"}


def test_capture_find_hotel_by_name_stashes_but_does_not_truncate():
    ctx = _Ctx()
    resp = {"structuredContent": {"hotel": {"hotelId": 7, "name": "Villa"}}, "isError": False}
    assert capture_after_tool(_Tool("find_hotel_by_name"), {}, ctx, resp) is None
    assert len(ctx.state["temp:hotel_search_results"]) == 1


# --- geocoded country → per-card country_code (widget market resolution) ---------------------
def test_capture_geocode_stashes_iso_country_code():
    ctx = _Ctx()
    resp = {"ok": True, "country_code": "fr", "profile_delta": {"last_city": "Paris"}}
    capture_after_tool(_Tool("geocode_location"), {}, ctx, resp)
    assert ctx.state["temp:hotel_search_country_code"] == "FR"  # normalized upper


def test_capture_geocode_rejects_non_iso_country_values():
    for bad in ("France", "", "F", None, 33):
        ctx = _Ctx()
        capture_after_tool(_Tool("geocode_location"), {}, ctx, {"ok": True, "country_code": bad})
        assert "temp:hotel_search_country_code" not in ctx.state


def test_capture_search_offers_stamps_geocoded_country_on_cards():
    ctx = _Ctx({"temp:hotel_search_country_code": "FR"})
    resp = {"structuredContent": _search_offers_structured(3), "isError": False}
    returned = capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert all(c["country_code"] == "FR" for c in ctx.state["temp:hotel_search_results"])
    assert all(c["country_code"] == "FR" for c in returned["hotels"])


def test_capture_search_offers_server_sent_country_code_wins_over_stamp():
    hotel = _hotel(1, 5000)
    hotel["countryCode"] = "ch"  # the day MCP ships a per-hotel code, it wins
    ctx = _Ctx({"temp:hotel_search_country_code": "FR"})
    resp = {"structuredContent": {"results": [hotel]}, "isError": False}
    capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert ctx.state["temp:hotel_search_results"][0]["country_code"] == "CH"


def test_capture_search_offers_without_geocode_leaves_cards_uncoded():
    ctx = _Ctx()
    resp = {"structuredContent": _search_offers_structured(2), "isError": False}
    capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert all("country_code" not in c for c in ctx.state["temp:hotel_search_results"])


def test_capture_find_hotel_by_name_is_never_stamped():
    # A name lookup is not bound to the geocoded location — no stamp.
    ctx = _Ctx({"temp:hotel_search_country_code": "FR"})
    resp = {"structuredContent": {"hotel": {"hotelId": 7, "name": "Villa"}}, "isError": False}
    capture_after_tool(_Tool("find_hotel_by_name"), {}, ctx, resp)
    assert "country_code" not in ctx.state["temp:hotel_search_results"][0]


def test_capture_ignores_non_target_tools():
    ctx = _Ctx()
    assert capture_after_tool(_Tool("some_other_tool"), {}, ctx, {"structuredContent": {}}) is None
    assert ctx.state == {}


# --- read_profile_in (S-G5 shared reader) ------------------------------------------------------
def test_read_profile_in_decodes_the_inbound_datapart():
    ctx = _Ctx(user_content=_user_content_with_profile_in({"city": "Miami", "search_cursor": 2}))
    assert read_profile_in(ctx) == {"city": "Miami", "search_cursor": 2}


def test_read_profile_in_defaults_to_empty_dict():
    for content in (None, genai_types.Content(role="user", parts=[genai_types.Part(text="hi")])):
        assert read_profile_in(_Ctx(user_content=content)) == {}
    assert read_profile_in(_Ctx()) == {}


# --- shown_hotel_ids exclusion wired end-to-end through capture_after_tool (S-G5) --------------
def test_capture_search_offers_excludes_shown_hotel_ids_from_profile_in():
    ctx = _Ctx(user_content=_user_content_with_profile_in({"shown_hotel_ids": [0, 1]}))
    resp = {"structuredContent": _search_offers_structured(3), "isError": False}  # ids 0,1,2
    returned = capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert [h["hotel_id"] for h in ctx.state["temp:hotel_search_results"]] == [2]
    assert [h["hotel_id"] for h in returned["hotels"]] == [2]


def test_capture_find_hotel_by_name_is_never_excluded():
    # A named lookup must never be hidden as "already shown".
    ctx = _Ctx(user_content=_user_content_with_profile_in({"shown_hotel_ids": [7]}))
    resp = {"structuredContent": {"hotel": {"hotelId": 7, "name": "Villa"}}, "isError": False}
    capture_after_tool(_Tool("find_hotel_by_name"), {}, ctx, resp)
    assert len(ctx.state["temp:hotel_search_results"]) == 1


# --- inject_pagination_offset (before_tool_callback, S-G5/A7) ----------------------------------
def test_inject_pagination_offset_computes_from_the_cursor():
    ctx = _Ctx(user_content=_user_content_with_profile_in({"search_cursor": 2}))
    args = {"lat": 1.0, "lon": 2.0, "date": "2026-07-21"}
    assert inject_pagination_offset(_Tool("search_offers"), args, ctx) is None
    assert args["from"] == 2 * MAX_RESULTS


def test_inject_pagination_offset_defaults_to_zero_without_a_cursor():
    ctx = _Ctx()
    args = {}
    inject_pagination_offset(_Tool("search_offers"), args, ctx)
    assert args["from"] == 0


def test_inject_pagination_offset_overwrites_any_model_supplied_from():
    # The model is never taught pagination — any `from` it invents is not trusted.
    ctx = _Ctx(user_content=_user_content_with_profile_in({"search_cursor": 1}))
    args = {"from": 999}
    inject_pagination_offset(_Tool("search_offers"), args, ctx)
    assert args["from"] == MAX_RESULTS


def test_inject_pagination_offset_ignores_other_tools():
    ctx = _Ctx(user_content=_user_content_with_profile_in({"search_cursor": 5}))
    args = {"name": "Villa"}
    inject_pagination_offset(_Tool("find_hotel_by_name"), args, ctx)
    assert "from" not in args


def test_inject_pagination_offset_tolerates_garbage_cursor():
    ctx = _Ctx(user_content=_user_content_with_profile_in({"search_cursor": "nope"}))
    args = {}
    inject_pagination_offset(_Tool("search_offers"), args, ctx)
    assert args["from"] == 0


# --- applied amenity filters → per-card amenities (server-guaranteed truths) ------------------
def test_capture_stamps_hard_filtered_amenities_on_search_cards():
    # hotelEquipmentIds is a HARD filter: every returned hotel has the amenity,
    # even though search_offers sends no amenity list. "pet_friendly" is stamped
    # as "pet friendly" — the claim guard's synonym table only knows the spaced form.
    ctx = _Ctx({STATE_APPLIED_AMENITIES_KEY: ["pool", "pet_friendly"]})
    resp = {"structuredContent": _search_offers_structured(3), "isError": False}
    returned = capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    for card in ctx.state["temp:hotel_search_results"]:
        assert "pool" in card["amenities"]
        assert "pet friendly" in card["amenities"]
    for card in returned["hotels"]:
        assert "pool" in card["amenities"]


def test_capture_without_applied_filter_leaves_amenities_empty():
    ctx = _Ctx({STATE_APPLIED_AMENITIES_KEY: []})
    resp = {"structuredContent": _search_offers_structured(2), "isError": False}
    capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert all(c["amenities"] == [] for c in ctx.state["temp:hotel_search_results"])


def test_capture_stamp_never_duplicates_a_server_sent_amenity():
    hotel = _hotel(1, 5000)
    hotel["amenities"] = [{"id": 33, "name": "pool"}]  # hypothetical server list
    ctx = _Ctx({STATE_APPLIED_AMENITIES_KEY: ["pool"]})
    resp = {"structuredContent": {"results": [hotel]}, "isError": False}
    capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert ctx.state["temp:hotel_search_results"][0]["amenities"] == ["pool"]


def test_capture_never_stamps_find_hotel_by_name():
    # A name lookup is not bound to this search's filters.
    ctx = _Ctx({STATE_APPLIED_AMENITIES_KEY: ["pool"]})
    resp = {"structuredContent": {"hotel": {"hotelId": 7, "name": "Villa"}}, "isError": False}
    capture_after_tool(_Tool("find_hotel_by_name"), {}, ctx, resp)
    assert ctx.state["temp:hotel_search_results"][0]["amenities"] == []


# --- budget / time-slot capture (the real search_offers args) --------------------------------
_BUDGET_TIMESLOT_KEY = "temp:hotel_search_budget_timeslot"


def test_capture_search_offers_stashes_budget_and_timeslot_from_args():
    ctx = _Ctx()
    args = {"priceRangeMax": 80, "timeSlot": {"startHour": 14, "endHour": 20}}
    resp = {"structuredContent": _search_offers_structured(2), "isError": False}
    capture_after_tool(_Tool("search_offers"), args, ctx, resp)
    stashed = ctx.state[_BUDGET_TIMESLOT_KEY]
    assert stashed["budget_max"] == 80.0
    assert stashed["timeslot_start"] == "14:00"
    assert stashed["timeslot_end"] == "20:00"


def test_capture_search_offers_without_budget_or_timeslot_stashes_nothing():
    ctx = _Ctx()
    resp = {"structuredContent": _search_offers_structured(2), "isError": False}
    capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert _BUDGET_TIMESLOT_KEY not in ctx.state  # never a wrong/empty entry


def test_capture_search_offers_captures_budget_even_on_zero_results():
    # A 0-result search is exactly when auto-widen (S12) needs the budget.
    ctx = _Ctx()
    resp = {"structuredContent": {"results": [], "total": 0}, "isError": False}
    capture_after_tool(_Tool("search_offers"), {"priceRangeMax": 60}, ctx, resp)
    assert ctx.state[_BUDGET_TIMESLOT_KEY] == {"budget_max": 60.0}


def test_capture_ignores_garbage_budget_and_keeps_one_sided_timeslot():
    ctx = _Ctx()
    args = {"priceRangeMax": "not-a-number", "timeSlot": {"startHour": 9}}
    resp = {"structuredContent": _search_offers_structured(1), "isError": False}
    capture_after_tool(_Tool("search_offers"), args, ctx, resp)
    stashed = ctx.state[_BUDGET_TIMESLOT_KEY]
    assert "budget_max" not in stashed
    assert stashed["timeslot_start"] == "09:00"
    assert "timeslot_end" not in stashed


def test_capture_rejects_non_positive_budget():
    ctx = _Ctx()
    resp = {"structuredContent": _search_offers_structured(1), "isError": False}
    for bad in (0, -20, None):
        ctx.state.clear()
        capture_after_tool(_Tool("search_offers"), {"priceRangeMax": bad}, ctx, resp)
        assert _BUDGET_TIMESLOT_KEY not in ctx.state


def test_capture_midnight_start_hour_is_not_dropped_as_falsy():
    ctx = _Ctx()
    args = {"timeSlot": {"startHour": 0, "endHour": 6}}
    resp = {"structuredContent": _search_offers_structured(1), "isError": False}
    capture_after_tool(_Tool("search_offers"), args, ctx, resp)
    assert ctx.state[_BUDGET_TIMESLOT_KEY] == {"timeslot_start": "00:00", "timeslot_end": "06:00"}


def test_capture_budget_not_stashed_on_failed_search():
    ctx = _Ctx()
    capture_after_tool(_Tool("search_offers"), {"priceRangeMax": 80}, ctx, {"isError": True})
    assert _BUDGET_TIMESLOT_KEY not in ctx.state


def test_capture_find_hotel_by_name_ignores_budget_args():
    # find_hotel_by_name has no budget/timeslot params — never capture from it.
    ctx = _Ctx()
    resp = {"structuredContent": {"hotel": {"hotelId": 7, "name": "Villa"}}, "isError": False}
    capture_after_tool(_Tool("find_hotel_by_name"), {"priceRangeMax": 80}, ctx, resp)
    assert _BUDGET_TIMESLOT_KEY not in ctx.state


def _capture_metric_lines(args: dict) -> list[str]:
    """The dayuse.metrics lines a search_offers capture emits. Uses a manual
    handler (the metrics logger is self-configured, may not propagate to caplog)."""
    import logging as _logging

    records: list[str] = []

    class _Grab(_logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = _logging.getLogger("dayuse.metrics")
    handler = _Grab()
    logger.addHandler(handler)
    try:
        resp = {"structuredContent": _search_offers_structured(1), "isError": False}
        capture_after_tool(_Tool("search_offers"), args, _Ctx(), resp)
    finally:
        logger.removeHandler(handler)
    return [m for m in records if "budget_timeslot" in m]


def test_capture_budget_metric_logs_flags_only_never_the_values():
    # GDPR: the counter emits presence flags (0/1), NEVER the budget amount (80)
    # or the hours (14/20) — a budget/time preference is user content.
    line = _capture_metric_lines({"priceRangeMax": 80, "timeSlot": {"startHour": 14, "endHour": 20}})[0]
    assert "has_budget=1" in line and "has_timeslot=1" in line
    assert "80" not in line and "14" not in line and "20" not in line


def test_capture_budget_metric_reports_zero_when_nothing_extracted():
    # The negation/hallucination check: a search with no budget in the message
    # logs has_budget=0 (not a fabricated filter).
    line = _capture_metric_lines({})[0]
    assert "has_budget=0" in line and "has_timeslot=0" in line


# --- emit_search_datapart (verified through the REAL ADK A2A converter) ----------------------
def _decode(content) -> dict:
    """Find the datapart among the Content's parts (a text summary may precede
    it) and decode it through the real ADK converter."""
    for part in content.parts:
        if part.inline_data is not None:
            a2a_part = convert_genai_part_to_a2a_part(part)
            assert isinstance(a2a_part.root, a2a_types.DataPart)
            return a2a_part.root.data
    raise AssertionError("no datapart in content")


def _text(content) -> str:
    return "".join(p.text for p in content.parts if p.text)


def test_emit_builds_decodable_datapart_with_results_and_mapped_delta():
    ctx = _Ctx(
        {
            "temp:hotel_search_results": [{"id": 1, "name": "Villa Test"}],
            "temp:hotel_search_profile_delta": {"last_city": "Paris", "last_state_context": "NY"},
        }
    )
    content = emit_search_datapart(ctx)
    assert content is not None
    data = _decode(content)
    assert data["results"] == [{"id": 1, "name": "Villa Test"}]
    # leaf keys mapped to the orchestrator's profile schema (S5 naming gap),
    # typed-ops shape (S-G5 migration — the concierge's reducer accepts both,
    # this locks the leaf's OWN emission format).
    assert data["profile_delta"] == {
        "city": {"op": "set", "value": "Paris"},
        "state_anchor": {"op": "set", "value": "NY"},
    }
    # a grounded text outcome rides in the SAME Content (becomes leaf_text), so
    # the orchestrator never sees a datapart-only response and degrades
    assert "Villa Test" in _text(content)


def test_emit_zero_results_carries_a_no_offers_outcome_text():
    content = emit_search_datapart(_Ctx({"temp:hotel_search_results": []}))
    assert _decode(content) == {"results": []}
    assert _text(content)  # non-empty outcome line ("No day-use offers found…")


def test_emit_results_only_when_no_delta():
    ctx = _Ctx({"temp:hotel_search_results": []})
    data = _decode(emit_search_datapart(ctx))
    assert data == {"results": []}  # a real 0-result search, no profile_delta


def test_emit_delta_only_when_no_search_ran():
    ctx = _Ctx({"temp:hotel_search_profile_delta": {"last_city": "Lyon"}})
    data = _decode(emit_search_datapart(ctx))
    assert "results" not in data  # no search this turn → orchestrator won't record a 0-outcome
    assert data["profile_delta"] == {"city": {"op": "set", "value": "Lyon"}}


def test_emit_delta_carries_country_anchor_from_geocode():
    ctx = _Ctx(
        {
            "temp:hotel_search_results": [{"id": 1, "name": "Villa Test"}],
            "temp:hotel_search_profile_delta": {"last_city": "Paris"},
            "temp:hotel_search_country_code": "FR",
        }
    )
    data = _decode(emit_search_datapart(ctx))
    # the orchestrator's apply_profile_delta reads `country_anchor` (its schema)
    assert data["profile_delta"] == {
        "city": {"op": "set", "value": "Paris"},
        "country_anchor": {"op": "set", "value": "FR"},
    }


def test_emit_country_anchor_flows_even_on_a_geocode_only_turn():
    # geocode ran but no search (e.g. the model asked a clarification): the anchor
    # still reaches the orchestrator so active_filters/market survive the turn.
    ctx = _Ctx({"temp:hotel_search_country_code": "FR"})
    data = _decode(emit_search_datapart(ctx))
    assert data == {"profile_delta": {"country_anchor": {"op": "set", "value": "FR"}}}


# --- zone/metro → profile_delta (S-G5: previously never persisted at all) --------------------
def test_emit_delta_carries_zone_and_metro_as_typed_ops():
    ctx = _Ctx(
        {
            "temp:hotel_search_results": [{"id": 1, "name": "Villa Test"}],
            "temp:hotel_search_profile_delta": {
                "last_city": "Paris",
                "zone": "La Défense",
                "metro": "Île-de-France",
            },
        }
    )
    data = _decode(emit_search_datapart(ctx))
    assert data["profile_delta"] == {
        "city": {"op": "set", "value": "Paris"},
        "zone": {"op": "set", "value": "La Défense"},
        "metro": {"op": "set", "value": "Île-de-France"},
    }


def test_emit_omits_zone_metro_when_absent():
    ctx = _Ctx(
        {
            "temp:hotel_search_results": [{"id": 1, "name": "Villa Test"}],
            "temp:hotel_search_profile_delta": {"last_city": "Paris"},
        }
    )
    data = _decode(emit_search_datapart(ctx))
    assert "zone" not in data["profile_delta"]
    assert "metro" not in data["profile_delta"]


def test_emit_returns_none_when_nothing_captured():
    assert emit_search_datapart(_Ctx()) is None


def test_emit_includes_applied_amenities_in_profile_delta():
    # The concierge re-learns the filter (apply_profile_delta merges amenities),
    # so next turn's profile_in accumulates it and active_filters light up.
    ctx = _Ctx(
        {
            "temp:hotel_search_results": [{"id": 1, "name": "Villa Test"}],
            STATE_APPLIED_AMENITIES_KEY: ["pool"],
        }
    )
    data = _decode(emit_search_datapart(ctx))
    assert data["profile_delta"] == {"amenities": ["pool"]}


def test_emit_omits_amenities_when_none_applied():
    # An empty list must never reach the delta — it could read as a wipe.
    ctx = _Ctx({"temp:hotel_search_results": [], STATE_APPLIED_AMENITIES_KEY: []})
    data = _decode(emit_search_datapart(ctx))
    assert "profile_delta" not in data


# --- budget / time-slot → profile_delta (the S9/S12 gap this session closes) -----------------
def test_emit_maps_budget_and_timeslot_to_the_concierge_schema_keys():
    ctx = _Ctx(
        {
            "temp:hotel_search_results": [{"id": 1, "name": "Villa Test"}],
            _BUDGET_TIMESLOT_KEY: {
                "budget_max": 80.0,
                "timeslot_start": "14:00",
                "timeslot_end": "20:00",
            },
        }
    )
    data = _decode(emit_search_datapart(ctx))
    # EXACT keys apply_profile_delta reads (verified 2026-07-21). The leaf always
    # reports flexible_default — the concierge's P1 guard owns the explicit upgrade.
    assert data["profile_delta"] == {
        "budget_max": 80.0,
        "budget_request_source": "flexible_default",
        "timeslot_start": "14:00",
        "timeslot_end": "20:00",
        "timeslot_request_source": "flexible_default",
    }


def test_emit_budget_only_carries_no_timeslot_keys():
    ctx = _Ctx({"temp:hotel_search_results": [], _BUDGET_TIMESLOT_KEY: {"budget_max": 120.0}})
    data = _decode(emit_search_datapart(ctx))
    assert data["profile_delta"] == {
        "budget_max": 120.0,
        "budget_request_source": "flexible_default",
    }


def test_emit_timeslot_only_carries_no_budget_keys():
    ctx = _Ctx({"temp:hotel_search_results": [], _BUDGET_TIMESLOT_KEY: {"timeslot_start": "09:00"}})
    data = _decode(emit_search_datapart(ctx))
    assert data["profile_delta"] == {
        "timeslot_start": "09:00",
        "timeslot_request_source": "flexible_default",
    }


def test_emit_never_reports_an_explicit_budget_source():
    ctx = _Ctx({"temp:hotel_search_results": [], _BUDGET_TIMESLOT_KEY: {"budget_max": 50.0}})
    data = _decode(emit_search_datapart(ctx))
    assert data["profile_delta"]["budget_request_source"] == "flexible_default"


def test_emit_omits_budget_timeslot_when_none_captured():
    ctx = _Ctx({"temp:hotel_search_results": []})
    data = _decode(emit_search_datapart(ctx))
    assert "profile_delta" not in data


def test_emit_budget_timeslot_coexists_with_city_and_amenities():
    # The new keys must not clobber the delta the earlier steps already built.
    ctx = _Ctx(
        {
            "temp:hotel_search_results": [{"id": 1, "name": "Villa Test"}],
            "temp:hotel_search_profile_delta": {"last_city": "Paris"},
            STATE_APPLIED_AMENITIES_KEY: ["pool"],
            _BUDGET_TIMESLOT_KEY: {"budget_max": 90.0},
        }
    )
    data = _decode(emit_search_datapart(ctx))
    assert data["profile_delta"] == {
        "city": {"op": "set", "value": "Paris"},
        "amenities": ["pool"],
        "budget_max": 90.0,
        "budget_request_source": "flexible_default",
    }


# --- inbound DataPart codec (the leaf reading profile_in from user_content) -------------------
def test_decode_datapart_roundtrips_encode():
    payload = {"query_params": {}, "profile_in": {"amenities": ["pool"], "city": "Miami"}}
    assert decode_datapart(encode_datapart(payload)) == payload


def test_find_datapart_skips_text_parts_and_survives_garbage():
    from google.genai import types as genai_types

    text_part = genai_types.Part(text="hello")
    assert find_datapart([text_part]) is None
    assert find_datapart(None) is None
    payload = {"profile_in": {"amenities": []}}
    assert find_datapart([text_part, encode_datapart(payload)]) == payload


def test_find_datapart_prefers_the_last_match_over_the_first():
    # S-G5 root-cause fix, live-verified 2026-07-23: on THIS side,
    # tool_context.user_content.parts accumulates every turn's inbound
    # DataPart across the whole A2A session (n_parts grows turn over turn) —
    # the FIRST match is turn 1's stale snapshot forever; only the LAST one
    # is the current turn's real profile_in. This is what silently pinned
    # every profile-driven bridge (amenities, geo context, pagination) to
    # turn 1 until search_cursor made it visible (the one field that can
    # never coincidentally equal turn 1's value).
    turn1 = {"profile_in": {"search_cursor": 0, "city": "Paris"}}
    turn2 = {"profile_in": {"search_cursor": 1, "city": "Paris"}}
    turn3 = {"profile_in": {"search_cursor": 2, "city": "Paris"}}
    parts = [encode_datapart(turn1), encode_datapart(turn2), encode_datapart(turn3)]
    assert find_datapart(parts) == turn3


# --- skip_final_generation (short-circuits the wasted 3rd LLM call) --------------------------
def _skip_text(resp) -> str:
    """Outcome text carried by the canned LlmResponse (or '' if none)."""
    if resp is None or resp.content is None:
        return ""
    return "".join(p.text for p in resp.content.parts if p.text)


def test_skip_short_circuits_once_results_are_stashed():
    ctx = _Ctx({"temp:hotel_search_results": [{"id": 1, "name": "Villa Test"}]})
    resp = skip_final_generation(ctx, llm_request=None)
    assert resp is not None  # the real final-prose LLM call is skipped
    assert "Villa Test" in _skip_text(resp)  # same code-built outcome the emit step uses


def test_skip_short_circuits_on_zero_results():
    # A 0-result search is a real outcome (stashes []): still short-circuit — the
    # honest "no offers" line, not a wasted LLM call, and the orchestrator re-synthesizes it.
    ctx = _Ctx({"temp:hotel_search_results": []})
    resp = skip_final_generation(ctx, llm_request=None)
    assert resp is not None
    assert _skip_text(resp)  # non-empty ("No day-use offers found…")


def test_skip_lets_model_speak_when_no_search_ran():
    # geocode-fail / clarification / MCP-degraded: no results stashed → the model must
    # still generate the honest diagnostic that becomes the orchestrator's leaf_text.
    assert skip_final_generation(_Ctx(), llm_request=None) is None


def test_skip_lets_model_speak_after_geocode_only():
    # geocode ran and stashed a profile_delta, but no search yet → do NOT short-circuit
    # (the model still needs to decide/emit search_offers, i.e. LLM call #2).
    ctx = _Ctx({"temp:hotel_search_profile_delta": {"last_city": "Paris"}})
    assert skip_final_generation(ctx, llm_request=None) is None


# --- stamp_turn_start / leaf_turn_total (S-G4 per-phase instrumentation) ----------------------
def _total_metric_lines(ctx) -> list[str]:
    """The dayuse.metrics lines an emit_search_datapart call emits, filtered to
    leaf_turn_total (same manual-handler pattern as _capture_metric_lines)."""
    import logging as _logging

    records: list[str] = []

    class _Grab(_logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = _logging.getLogger("dayuse.metrics")
    handler = _Grab()
    logger.addHandler(handler)
    try:
        emit_search_datapart(ctx)
    finally:
        logger.removeHandler(handler)
    return [m for m in records if "leaf_turn_total" in m]


def test_stamp_turn_start_sets_a_monotonic_float():
    ctx = _Ctx()
    assert stamp_turn_start(ctx) is None
    assert isinstance(ctx.state["temp:hotel_search_turn_t0"], float)


def test_emit_logs_total_ms_minus_one_when_stamp_never_ran():
    # The unit tests above call emit_search_datapart directly on a bare fake
    # context — same "-1 means the before-callback didn't fire" convention as
    # dayuse_agent_common.metrics._elapsed_ms.
    line = _total_metric_lines(_Ctx())[0]
    assert "ms=-1" in line


def test_emit_logs_a_real_total_ms_after_stamp_turn_start():
    ctx = _Ctx()
    stamp_turn_start(ctx)
    line = _total_metric_lines(ctx)[0]
    assert "ms=-1" not in line
    ms = int(line.split("ms=")[1].split()[0])
    assert ms >= 0


def test_emit_logs_total_even_when_nothing_was_captured():
    # A geocode-fail / clarification-only turn (emit_search_datapart returns
    # None) must still get a total-ms row — that path is exactly what a
    # bimodal-latency bug (Chester GB) needs instrumented.
    ctx = _Ctx()
    stamp_turn_start(ctx)
    assert emit_search_datapart(ctx) is None
    assert _total_metric_lines(ctx)  # the row still fired despite no payload


def test_emit_total_metric_never_carries_message_content():
    # GDPR: flags/durations only — the line is a fixed format with no room for
    # free text, but assert it explicitly (same posture as the budget/timeslot
    # counter test above).
    ctx = _Ctx({"temp:hotel_search_results": [{"id": 1, "name": "Secret Villa Name"}]})
    stamp_turn_start(ctx)
    line = _total_metric_lines(ctx)[0]
    assert "Secret Villa Name" not in line
    assert line.startswith("dayuse_metric=leaf_turn_total agent=b2c_hotel_search ms=")


# --- S-G6: exact-minute window (A4-c) -----------------------------------------------------------


def _offer(start_hour, start_minute, end_hour, end_minute, price=5000):
    return {
        "priceEuro": price,
        "startHour": start_hour,
        "startMinute": start_minute,
        "endHour": end_hour,
        "endMinute": end_minute,
        "availabilityDate": "2026-07-21",
        "ratePlanId": 1,
    }


def _hotel_with_offers(i, offers):
    return {
        "hotelId": i,
        "name": f"Hotel {i}",
        "cityName": "Paris",
        "countryName": "France",
        "offers": offers,
    }


def test_normalize_hotel_drops_offers_outside_exact_window():
    hotel = _hotel_with_offers(1, [_offer(7, 0, 13, 0)])  # 07:00-13:00
    card = normalize_hotel(hotel, exact_window=(7 * 60 + 30, 13 * 60 + 30))  # 07:30-13:30 asked
    assert "price" not in card  # the only offer starts too early — doesn't fit


def test_normalize_hotel_keeps_offers_fitting_inside_exact_window():
    hotel = _hotel_with_offers(1, [_offer(7, 30, 13, 30)])
    card = normalize_hotel(hotel, exact_window=(7 * 60, 14 * 60))  # wider ask, offer fits inside
    assert card["price"] == "€50.00"


def test_normalize_search_results_drops_hotels_with_no_fitting_offer():
    structured = {
        "results": [
            _hotel_with_offers(1, [_offer(7, 0, 13, 0)]),  # too early, excluded
            _hotel_with_offers(2, [_offer(7, 30, 13, 30)]),  # fits exactly
        ]
    }
    results = normalize_search_results(structured, exact_window=(7 * 60 + 30, 13 * 60 + 30))
    assert [h["id"] for h in results] == [2]


def test_normalize_search_results_without_exact_window_behaves_exactly_as_before():
    structured = {"results": [_hotel_with_offers(1, [_offer(7, 0, 13, 0)])]}
    results = normalize_search_results(structured, exact_window=None)
    assert len(results) == 1  # no strict filter applied


def test_capture_overrides_timeslot_minutes_from_the_exact_window_state():
    # core-e2e-084: args["timeSlot"] only holds the FLOORED/CEILED hours by
    # now (the before_tool_callback already rewrote them) — the exact minutes
    # must come from the stashed state, not args.
    ctx = _Ctx({STATE_EXACT_WINDOW_KEY: {"start_total": 7 * 60 + 30, "end_total": 13 * 60 + 30}})
    args = {"priceRangeMax": 200, "timeSlot": {"startHour": 7, "endHour": 14}}
    resp = {
        "structuredContent": {"results": [_hotel_with_offers(1, [_offer(7, 30, 13, 30)])]},
        "isError": False,
    }
    capture_after_tool(_Tool("search_offers"), args, ctx, resp)
    stashed = ctx.state[_BUDGET_TIMESLOT_KEY]
    assert stashed["timeslot_start"] == "07:30"
    assert stashed["timeslot_end"] == "13:30"
    assert stashed["budget_max"] == 200.0  # unrelated capture untouched


def test_capture_applies_exact_window_post_filter():
    ctx = _Ctx({STATE_EXACT_WINDOW_KEY: {"start_total": 7 * 60 + 30, "end_total": 13 * 60 + 30}})
    resp = {
        "structuredContent": {
            "results": [
                _hotel_with_offers(1, [_offer(7, 0, 13, 0)]),  # excluded
                _hotel_with_offers(2, [_offer(7, 30, 13, 30)]),  # kept
            ]
        },
        "isError": False,
    }
    capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    results = ctx.state["temp:hotel_search_results"]
    assert [h["id"] for h in results] == [2]
    assert "temp:hotel_search_timeslot_fallback" not in ctx.state


def test_capture_falls_back_when_exact_window_would_empty_everything():
    ctx = _Ctx({STATE_EXACT_WINDOW_KEY: {"start_total": 7 * 60 + 30, "end_total": 13 * 60 + 30}})
    resp = {
        "structuredContent": {
            "results": [_hotel_with_offers(1, [_offer(7, 0, 13, 0)])],  # only non-fitting offer
        },
        "isError": False,
    }
    capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    results = ctx.state["temp:hotel_search_results"]
    assert [h["id"] for h in results] == [1]  # fallback: coarser results, never a silent 0
    assert ctx.state["temp:hotel_search_timeslot_fallback"] is True


def test_capture_no_exact_window_state_never_filters():
    ctx = _Ctx()  # resolve_search_timeslot never ran (e.g. an older-style test/caller)
    resp = {
        "structuredContent": {"results": [_hotel_with_offers(1, [_offer(7, 0, 13, 0)])]},
        "isError": False,
    }
    capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert len(ctx.state["temp:hotel_search_results"]) == 1


def test_outcome_text_appends_fallback_disclosure():
    from hotel_search_agent.response_bridge import _outcome_text

    text = _outcome_text([{"name": "Hotel 1"}], timeslot_fallback=True)
    assert "closest matches" in text
    assert _outcome_text([{"name": "Hotel 1"}], timeslot_fallback=False) == (
        "1 day-use offer(s) found: Hotel 1."
    )


def test_skip_final_generation_includes_fallback_note():
    ctx = _Ctx(
        {
            "temp:hotel_search_results": [{"id": 1, "name": "Villa"}],
            "temp:hotel_search_timeslot_fallback": True,
        }
    )
    response = skip_final_generation(ctx, None)
    assert "closest matches" in response.content.parts[0].text


# --- S-G6: resolved date -> profile_delta --------------------------------------------------------


def test_emit_delta_carries_resolved_date_and_date_reference():
    ctx = _Ctx(
        {
            "temp:hotel_search_results": [{"id": 1, "name": "Villa"}],
            STATE_RESOLVED_DATE_KEY: {
                "date": "2026-07-24",
                "date_reference": {"resolved_from": "relative", "expression": "demain"},
            },
        }
    )
    data = _decode(emit_search_datapart(ctx))
    assert data["profile_delta"]["date"] == {"op": "set", "value": "2026-07-24"}
    assert data["profile_delta"]["date_reference"] == {
        "op": "set",
        "value": {"resolved_from": "relative", "expression": "demain"},
    }


def test_emit_omits_date_when_no_fresh_label_was_resolved():
    # A carryover-only turn (resolve_search_date never stashed anything): the
    # profile's own carried-over date/date_reference must NOT be touched.
    ctx = _Ctx({"temp:hotel_search_results": [{"id": 1, "name": "Villa"}]})
    data = _decode(emit_search_datapart(ctx))
    assert "date" not in data.get("profile_delta", {})
    assert "date_reference" not in data.get("profile_delta", {})
