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
    STATE_DATE_FALLBACK_KEY,
    STATE_EXACT_WINDOW_KEY,
    STATE_RESOLVED_DATE_KEY,
    STATE_SEARCH_DATE_KEY,
    _outcome_text,
    _photo_url,
    _price_eur_cents,
    capture_after_tool,
    decode_datapart,
    emit_search_datapart,
    encode_datapart,
    find_datapart,
    inject_pagination_offset,
    inject_landmark_radius,
    normalize_hotel,
    normalize_search_results,
    read_profile_in,
    skip_final_generation,
    stamp_turn_start,
)


class TestLandmarkRadius:
    """P0-2 fix 4. A landmark anchor and a city anchor used to search the same
    20 km disc (MCP's `radiusKm` default), so a geocode precise to 250 m still
    returned hotels 7-13 km away. That is why fixing the geocode alone left
    `hotels_within_km` at 24%."""

    def _ctx(self, origin):
        # The GEOCODE-branch anchor, not the search-branch distance origin:
        # the latter is only written after search_offers has run.
        state = {} if origin is None else {"temp:hotel_search_anchor": origin}
        return _Ctx(state=state)

    def test_a_poi_anchor_tightens_the_disc(self):
        args = {"lat": 48.8698, "lon": 2.3078}
        inject_landmark_radius(_Tool("search_offers"), args, self._ctx({"type": "poi"}))
        assert args["radiusKm"] == 3.0

    def test_a_city_anchor_leaves_mcp_its_own_default(self):
        # Absent key, NOT an explicit 20 — MCP owns the city default.
        args = {"lat": 48.85, "lon": 2.35}
        inject_landmark_radius(_Tool("search_offers"), args, self._ctx({"type": "city"}))
        assert "radiusKm" not in args

    def test_a_gps_anchor_is_deliberately_not_tightened(self):
        args = {"lat": 48.85, "lon": 2.35}
        inject_landmark_radius(_Tool("search_offers"), args, self._ctx({"type": "gps"}))
        assert "radiusKm" not in args

    def test_no_anchor_stashed_is_a_no_op(self):
        args = {"lat": 48.85, "lon": 2.35}
        inject_landmark_radius(_Tool("search_offers"), args, self._ctx(None))
        assert "radiusKm" not in args

    def test_a_radius_the_model_invented_is_dropped(self):
        # Doctrine: a radius is a filter, and the LLM never owns a filter value.
        args = {"lat": 48.85, "lon": 2.35, "radiusKm": 200}
        inject_landmark_radius(_Tool("search_offers"), args, self._ctx({"type": "city"}))
        assert "radiusKm" not in args

    def test_a_model_radius_is_replaced_on_a_poi_anchor(self):
        args = {"lat": 48.8698, "lon": 2.3078, "radiusKm": 200}
        inject_landmark_radius(_Tool("search_offers"), args, self._ctx({"type": "poi"}))
        assert args["radiusKm"] == 3.0

    def test_other_tools_are_untouched(self):
        args = {"name": "Hilton", "radiusKm": 9}
        inject_landmark_radius(_Tool("find_hotel_by_name"), args, self._ctx({"type": "poi"}))
        assert args == {"name": "Hilton", "radiusKm": 9}


class TestCardOccupancyDisclosure:
    """P0-1: how many people the priced offer sleeps. From the SAME `best` dict
    as the price and the time slot, so the numbers on one card always describe
    ONE offer. Snake_case on the card; MCP sends `capacity`/`childrenCapacity`."""

    def _hotel(self, **offer_extra):
        offer = {
            "priceEuro": 9000,
            "startHour": 10,
            "endHour": 18,
            "ratePlanUuid": "rp-1",
            "availabilityDate": "2026-08-26",
        }
        offer.update(offer_extra)
        return {"hotelId": 1, "name": "H", "offers": [offer]}

    def test_capacity_and_children_capacity_reach_the_card(self):
        card = normalize_hotel(self._hotel(capacity=2, childrenCapacity=1))
        assert card["capacity"] == 2
        assert card["children_capacity"] == 1

    def test_zero_children_capacity_is_reported_not_dropped(self):
        # An adults-only offer is a fact a family needs to see.
        card = normalize_hotel(self._hotel(capacity=2, childrenCapacity=0))
        assert card["children_capacity"] == 0

    def test_absent_capacity_yields_no_key_never_a_guess(self):
        card = normalize_hotel(self._hotel())
        assert "capacity" not in card
        assert "children_capacity" not in card

    def test_garbage_capacity_is_ignored(self):
        card = normalize_hotel(self._hotel(capacity="deux", childrenCapacity=True))
        assert "capacity" not in card
        assert "children_capacity" not in card


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


# --- numeric price + review count on the card (S-CX3a) ---------------------------------------
def test_normalize_hotel_keeps_the_numeric_price_next_to_the_display_string():
    """The display string alone made every price-vs-budget decision impossible
    (audit CX gap G-b2) — both now travel, and they describe the SAME offer."""
    card = normalize_hotel(_hotel(1, 5432))
    assert card["price"] == "€54.32"
    assert card["price_eur_cents"] == 5432
    assert isinstance(card["price_eur_cents"], int)


def test_normalize_hotel_carries_rating_count_from_total_review():
    hotel = _hotel(1, 5000) | {"totalReview": 412}
    assert normalize_hotel(hotel)["rating_count"] == 412


def test_normalize_hotel_rating_count_is_none_when_mcp_omits_total_review():
    """`totalReview` is optional in the MCP payload — absent means unknown,
    never 0 (a 0 would read as "no reviews" and shrink a real rating away)."""
    assert normalize_hotel(_hotel(1, 5000))["rating_count"] is None


def test_normalize_hotel_omits_both_price_forms_when_no_offer_fits():
    """price and price_eur_cents must never disagree: same offer, same filter."""
    hotel = _hotel_with_offers(1, [_offer(7, 0, 13, 0)])  # 07:00-13:00
    card = normalize_hotel(hotel, exact_window=(7 * 60 + 30, 13 * 60 + 30))  # 07:30-13:30 asked
    assert "price" not in card and "price_eur_cents" not in card


def test_normalize_hotel_keeps_the_servers_own_relevance_score():
    """Probed live 2026-07-27: search_offers sends `score` per hotel (the order
    `results` already arrives in). Kept as `relevance_score` so a re-rank can
    modify the server's baseline instead of inventing a rival ranking."""
    card = normalize_hotel(_hotel(1, 5000) | {"score": 0.8123})
    assert card["relevance_score"] == 0.8123


def test_normalize_hotel_omits_relevance_score_when_absent_or_garbage():
    """get_hotel_details carries no `score` (search-only) — absent, not faked;
    and a score is not a coordinate: 200.0 is kept, "high" is not."""
    assert "relevance_score" not in normalize_hotel(_hotel(1, 5000))
    for bad in ("high", None, [0.5]):
        assert "relevance_score" not in normalize_hotel(_hotel(1, 5000) | {"score": bad})
    assert normalize_hotel(_hotel(1, 5000) | {"score": 200.0})["relevance_score"] == 200.0


# --- offer identity on the card (S-CX5) -------------------------------------------------------
def test_normalize_hotel_carries_the_identity_of_the_offer_it_priced():
    """The card's offer_id/offer_date must describe the SAME offer as its
    price — that pair is what lets the booking step reuse this exact offer."""
    hotel = _hotel(1, 5432)
    hotel["offers"][0]["ratePlanUuid"] = "019d2b0c-4f34-7110-882d-d5709ca05b6f"
    card = normalize_hotel(hotel)
    assert card["offer_id"] == "019d2b0c-4f34-7110-882d-d5709ca05b6f"
    assert card["offer_date"] == "2026-07-21"
    assert card["price_eur_cents"] == 5432


def test_normalize_hotel_takes_the_identity_of_the_CHEAPEST_offer_not_the_first():
    """`_best_offer` prices the cheapest; the identity must follow it, or the
    card would quote one offer and book another."""
    cheap = _offer(11, 0, 19, 0, price=8700) | {"ratePlanUuid": "cheap-uuid"}
    pricey = _offer(17, 0, 23, 0, price=9000) | {"ratePlanUuid": "pricey-uuid"}
    card = normalize_hotel(_hotel_with_offers(1, [pricey, cheap]))  # pricey listed FIRST
    assert card["price"] == "€87.00"
    assert card["offer_id"] == "cheap-uuid"
    assert card["timeslots"] == [{"start": "11:00", "end": "19:00"}]


def test_normalize_hotel_omits_offer_identity_when_mcp_sends_no_uuid():
    """No uuid = no reusable offer. The card says so by omission; the booking
    path then falls back to a fresh, date-scoped lookup."""
    card = normalize_hotel(_hotel(1, 5000))  # fixture carries ratePlanId only
    assert "offer_id" not in card
    assert card["offer_date"] == "2026-07-21"


def test_normalize_hotel_drops_offer_identity_with_the_offer_it_belonged_to():
    """The exact-window filter removed every offer — identity must go with it,
    never survive as a stale pointer to an offer the card no longer shows."""
    offer = _offer(7, 0, 13, 0) | {"ratePlanUuid": "filtered-out"}
    card = normalize_hotel(_hotel_with_offers(1, [offer]), exact_window=(7 * 60 + 30, 13 * 60 + 30))
    assert "offer_id" not in card and "offer_date" not in card


def test_price_eur_cents_rounds_and_rejects_garbage():
    assert _price_eur_cents(5000) == 5000
    assert _price_eur_cents(4999.6) == 5000
    for bad in (None, "", "abc", [5000], {}):
        assert _price_eur_cents(bad) is None


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


# --- hotel-page url from the ES slug (S-G12 — never slugified from the name) -----------------
def test_normalize_hotel_builds_url_from_es_slug_and_market():
    hotel = _hotel(1, 5000)  # countryName "France" in the fixture
    hotel["slug"] = "ibis-rungis-aeroport-paris-orly"
    card = normalize_hotel(hotel)
    assert card["url"] == "https://www.dayuse.fr/hotels/france/ibis-rungis-aeroport-paris-orly"


def test_normalize_hotel_omits_url_without_slug_even_with_a_name():
    hotel = _hotel(1, 5000)
    hotel["name"] = "Ibis Rungis Aéroport Paris Orly"  # tempting, but NOT a slug source
    assert "url" not in normalize_hotel(hotel)


def test_normalize_hotel_omits_url_on_unmapped_market():
    hotel = _hotel(1, 5000)
    hotel["slug"] = "some-hotel"
    hotel["countryName"] = "Atlantis"
    assert "url" not in normalize_hotel(hotel)


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
    # Nested in profile_delta — the concierge only reads that key off the wire
    # (S-G9 finding 1: a top-level sibling never reaches the profile).
    assert data["profile_delta"]["distance_origin"]["type"] == "city_centroid"
    assert "distance_origin" not in data  # no stale top-level duplicate
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


def test_capture_geocode_ambiguous_stashes_the_clarify_question():
    # S-G10 (D3): the homonym clarify question becomes a deterministic
    # requires_clarification signal downstream.
    ctx = _Ctx()
    resp = {
        "ok": False,
        "error": "geocode_ambiguous",
        "diagnostics": {"question": "Did you mean Budapest (Hungary), or Budapest (Georgia, United States)?"},
    }
    assert capture_after_tool(_Tool("geocode_location"), {}, ctx, resp) is None
    assert "Budapest (Hungary)" in ctx.state["temp:hotel_search_clarify_question"]


def test_capture_geocode_ambiguous_also_stashes_the_zone_it_asked_about():
    # 2026-08-26, measured in prod: asked "gare de lyon — which city?", answered
    # "paris", and the search ran on the bare Paris centroid (Saint-Denis 7,4 km,
    # Orly 12,6 km) because the clarify persisted nothing. A question whose
    # subject dies with the turn cannot be answered.
    ctx = _Ctx()
    resp = {
        "ok": False,
        "error": "geocode_ambiguous",
        "diagnostics": {"question": "Près de « gare de lyon » — dans quelle ville cherchez-vous ?"},
        "profile_delta": {"zone": "gare de lyon"},
    }
    assert capture_after_tool(_Tool("geocode_location"), {}, ctx, resp) is None
    assert ctx.state["temp:hotel_search_profile_delta"] == {"zone": "gare de lyon"}


def test_a_clarify_delta_never_erases_what_the_turn_already_resolved():
    # Merge, don't replace: an earlier tool call in the same turn may already
    # have stashed a delta, and the clarify must not blank it.
    ctx = _Ctx({"temp:hotel_search_profile_delta": {"last_city": "Paris"}})
    resp = {
        "ok": False,
        "error": "geocode_ambiguous",
        "diagnostics": {"question": "q"},
        "profile_delta": {"zone": "gare de lyon"},
    }
    capture_after_tool(_Tool("geocode_location"), {}, ctx, resp)
    assert ctx.state["temp:hotel_search_profile_delta"] == {
        "last_city": "Paris", "zone": "gare de lyon"
    }


def test_capture_geocode_other_errors_stash_no_clarify_question():
    ctx = _Ctx()
    resp = {"ok": False, "error": "geocode_echo_mismatch", "diagnostics": {"query": "x"}}
    capture_after_tool(_Tool("geocode_location"), {}, ctx, resp)
    assert "temp:hotel_search_clarify_question" not in ctx.state


def test_emit_flags_requires_clarification_when_no_search_ran():
    question = "Did you mean Budapest (Hungary), or Budapest (Georgia, United States)?"
    ctx = _Ctx({"temp:hotel_search_clarify_question": question})
    content = emit_search_datapart(ctx)
    from hotel_search_agent.response_bridge import decode_datapart as _dec
    data = next(d for d in (_dec(p) for p in content.parts) if d is not None)
    assert data["requires_clarification"] is True
    assert "results" not in data
    # The question rides as this event's text (the emitted content replaces the
    # model's final text — losing it would leave the orchestrator nothing to say).
    texts = [p.text for p in content.parts if p.text]
    assert question in texts


def test_emit_does_not_flag_clarification_when_a_search_ran():
    # A clarify followed by a successful search the same turn is a search turn.
    ctx = _Ctx({
        "temp:hotel_search_clarify_question": "Did you mean X or Y?",
        _RESULTS_KEY: [{"id": 1, "name": "Villa"}],
    })
    content = emit_search_datapart(ctx)
    from hotel_search_agent.response_bridge import decode_datapart as _dec
    data = next(d for d in (_dec(p) for p in content.parts) if d is not None)
    assert "requires_clarification" not in data
    assert data["results"]


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
def test_capture_search_offers_excludes_shown_hotel_ids_while_paginating():
    ctx = _Ctx(
        user_content=_user_content_with_profile_in({"shown_hotel_ids": [0, 1], "search_cursor": 1})
    )
    resp = {"structuredContent": _search_offers_structured(3), "isError": False}  # ids 0,1,2
    returned = capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert [h["hotel_id"] for h in ctx.state["temp:hotel_search_results"]] == [2]
    assert [h["hotel_id"] for h in returned["hotels"]] == [2]


def test_capture_search_offers_shows_everything_again_on_page_one():
    """S-CX5 REGRESSION (prod 2026-07-27): this filter exists so page 2 doesn't
    repeat page 1. Applied to EVERY search — as it was — it made a refined
    search hide the hotels just displayed, so "book the cheapest" answered with
    ranks 6-10 while the five cheapest were still on screen. At cursor 0 the
    full pool must come back, already-shown hotels included."""
    ctx = _Ctx(
        user_content=_user_content_with_profile_in({"shown_hotel_ids": [0, 1], "search_cursor": 0})
    )
    resp = {"structuredContent": _search_offers_structured(3), "isError": False}
    returned = capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert [h["hotel_id"] for h in returned["hotels"]] == [0, 1, 2]


def test_capture_search_offers_treats_a_missing_cursor_as_page_one():
    """An older profile (or a leaf called without the key) must not silently
    fall back to hiding results."""
    ctx = _Ctx(user_content=_user_content_with_profile_in({"shown_hotel_ids": [0, 1]}))
    resp = {"structuredContent": _search_offers_structured(3), "isError": False}
    returned = capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert [h["hotel_id"] for h in returned["hotels"]] == [0, 1, 2]


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


# --- S-CX2: search-unavailable truthfulness (audit CX 2026-07-24, F2/F3) ----------------------
# When the MCP search tools could not run this turn, the leaf must say so
# deterministically — never let the model's prose read as a legitimate
# "no offers in <city>" (false scarcity) when the backend was simply down.
_SEARCH_UNAVAILABLE_KEY = "temp:hotel_search_search_unavailable"
_CLARIFY_KEY = "temp:hotel_search_clarify_question"


def test_circuit_open_search_response_sets_the_unavailable_flag():
    ctx = _Ctx()
    out = capture_after_tool(
        _Tool("search_offers"), {}, ctx,
        {"ok": False, "error": "mcp_circuit_open", "diagnostics": {"tool": "search_offers"}},
    )
    assert out is None  # the model still sees the neutral diagnostic untouched
    assert ctx.state[_SEARCH_UNAVAILABLE_KEY] is True


def test_generic_tool_failure_does_not_set_the_flag():
    # A non-breaker failure keeps the pre-S-CX2 behavior: the model relays it;
    # the anchor-without-results signal in emit still catches a broken search.
    ctx = _Ctx()
    capture_after_tool(_Tool("search_offers"), {}, ctx, {"isError": True})
    assert _SEARCH_UNAVAILABLE_KEY not in ctx.state


def test_emit_reports_search_unavailable_when_breaker_tripped():
    ctx = _Ctx({_SEARCH_UNAVAILABLE_KEY: True})
    content = emit_search_datapart(ctx)
    data = _decode(content)
    assert data["status"] == "search_unavailable"
    assert "results" not in data
    assert "temporarily unavailable" in content.parts[0].text


def test_emit_reports_search_unavailable_on_anchor_without_results():
    # The Marseille repro (audit F2): geocode succeeded (anchor stashed — the
    # instruction then mandates a search) but no search response ever came
    # back (MCP toolset unreachable / call failed / tool budget spent first).
    ctx = _Ctx(
        {_ANCHOR_KEY: {"latitude": 43.29, "longitude": 5.37, "label": "Marseille", "type": "city_centroid"}}
    )
    data = _decode(emit_search_datapart(ctx))
    assert data["status"] == "search_unavailable"


def test_search_unavailable_text_is_localized_fr():
    ctx = _Ctx(
        {_SEARCH_UNAVAILABLE_KEY: True},
        user_content=_user_content_with_profile_in({"language": "fr"}),
    )
    content = emit_search_datapart(ctx)
    assert "momentanément indisponible" in content.parts[0].text


def test_clarify_turn_is_not_flagged_search_unavailable():
    ctx = _Ctx({_CLARIFY_KEY: "Did you mean Victoria (British Columbia, Canada)?"})
    data = _decode(emit_search_datapart(ctx))
    assert data["requires_clarification"] is True
    assert "status" not in data


def test_geocode_fail_turn_keeps_the_model_text():
    # No anchor, no breaker flag, no results: a geocode ok=False turn — the
    # model's honest diagnostic stands, emit stays silent (pre-S-CX2 behavior).
    assert emit_search_datapart(_Ctx()) is None


def test_successful_search_carries_no_status():
    ctx = _Ctx({_RESULTS_KEY: [{"id": 1, "name": "Hotel A"}]})
    data = _decode(emit_search_datapart(ctx))
    assert "status" not in data


def test_skip_final_generation_short_circuits_when_search_unavailable():
    ctx = _Ctx(
        {_SEARCH_UNAVAILABLE_KEY: True},
        user_content=_user_content_with_profile_in({"language": "fr"}),
    )
    resp = skip_final_generation(ctx, None)
    assert resp is not None  # no wasted final prose call that could echo jargon
    assert "momentanément indisponible" in resp.content.parts[0].text


def test_outcome_text_is_localized_fr():
    ctx = _Ctx(
        {_RESULTS_KEY: []},
        user_content=_user_content_with_profile_in({"language": "fr"}),
    )
    content = emit_search_datapart(ctx)
    assert "Aucune offre de jour" in content.parts[0].text


class TestNightRateReachesTheCarousel:
    """S-CX8: `computeNightDiscount` in the widget reads `slot.original_price`
    (EUROS) and nothing had ever filled it, so the carousel's discount badge was
    dead code in prod. MCP exposed `originalPriceEuro` (EUR cents) on
    2026-07-28."""

    @staticmethod
    def _hotel(**offer_extra):
        return {
            "results": [
                {
                    "hotelId": 7720,
                    "name": "Ibis La Ciotat",
                    "offers": [
                        {
                            "ratePlanUuid": "rp-1",
                            "availabilityDate": "2026-07-29",
                            "startHour": 10,
                            "endHour": 15,
                            "priceEuro": 6900,
                            **offer_extra,
                        }
                    ],
                }
            ]
        }

    def test_the_night_rate_lands_on_the_slot_in_euros(self):
        cards = normalize_search_results(self._hotel(originalPriceEuro=7670))
        # Euros with cents, not the raw 7670: the widget compares it against a
        # price it parsed as 69, so cents here would read as a €7 670 night.
        assert cards[0]["timeslots"] == [
            {"start": "10:00", "end": "15:00", "original_price": 76.70}
        ]

    def test_no_night_rate_leaves_the_slot_untouched(self):
        cards = normalize_search_results(self._hotel())
        assert cards[0]["timeslots"] == [{"start": "10:00", "end": "15:00"}]

    def test_a_night_rate_not_above_the_day_rate_makes_no_claim(self):
        for value in (6900, 6000):
            cards = normalize_search_results(self._hotel(originalPriceEuro=value))
            assert "original_price" not in cards[0]["timeslots"][0]

# --- S-CX6: the same-day cutoff swap (capture side) ---------------------------------------------
def _closed_day(total: int = 518) -> dict:
    return {"structuredContent": {"resolvedDate": "2026-07-27", "total": total, "results": []},
            "isError": False}


def _stashed_next_day(n: int = 3) -> dict:
    payload = _search_offers_structured(n)
    payload["resolvedDate"] = "2026-07-28"
    return {"searched_date": "2026-07-27", "offered_date": "2026-07-28", "payload": payload}


def test_capture_serves_the_probed_next_day_instead_of_a_dead_end():
    ctx = _Ctx({STATE_DATE_FALLBACK_KEY: _stashed_next_day()})
    returned = capture_after_tool(_Tool("search_offers"), {}, ctx, _closed_day())
    assert len(ctx.state["temp:hotel_search_results"]) == 3
    # The model's compact view must describe the day it is actually looking at.
    assert returned["resolvedDate"] == "2026-07-28"
    assert [h["name"] for h in returned["hotels"]] == ["Hotel 0", "Hotel 1", "Hotel 2"]


def test_capture_marks_the_swapped_day_so_the_answer_must_disclose_it():
    ctx = _Ctx({STATE_DATE_FALLBACK_KEY: _stashed_next_day()})
    capture_after_tool(_Tool("search_offers"), {}, ctx, _closed_day())
    assert ctx.state[STATE_SEARCH_DATE_KEY] == {
        "date": "2026-07-28", "same_day": False, "cutoff_fallback_from": "2026-07-27",
    }


def test_capture_carries_the_fallback_date_forward_to_the_profile():
    # Without this the NEXT turn ("cheaper", "with a pool") re-searches today
    # and dies on the very same cutoff.
    ctx = _Ctx({STATE_DATE_FALLBACK_KEY: _stashed_next_day()})
    capture_after_tool(_Tool("search_offers"), {}, ctx, _closed_day())
    assert ctx.state[STATE_RESOLVED_DATE_KEY] == {
        "date": "2026-07-28", "date_reference": {"resolved_from": "cutoff_fallback"},
    }


def test_capture_stamps_the_swapped_cards_like_any_other_card():
    # Why the swap sits BEFORE the stamping block: cards served from the probe
    # still need their country / applied-amenity truth.
    stashed = _stashed_next_day(2)
    for hotel in stashed["payload"]["results"]:
        hotel["lat"], hotel["lon"] = 48.86, 2.35
    ctx = _Ctx({
        STATE_DATE_FALLBACK_KEY: stashed,
        "temp:hotel_search_country_code": "FR",
        STATE_APPLIED_AMENITIES_KEY: ["pool"],
    })
    capture_after_tool(_Tool("search_offers"), {"lat": 48.84, "lon": 2.37}, ctx, _closed_day())
    cards = ctx.state["temp:hotel_search_results"]
    assert cards and all(c["country_code"] == "FR" for c in cards)
    assert all("pool" in c["amenities"] for c in cards)
    assert all(isinstance(c.get("distance_km"), float) for c in cards)


def test_capture_without_a_probe_payload_still_reports_the_honest_zero():
    ctx = _Ctx()
    returned = capture_after_tool(_Tool("search_offers"), {}, ctx, _closed_day())
    assert ctx.state["temp:hotel_search_results"] == []
    assert returned["hotels"] == [] and returned["total"] == 518
    assert STATE_SEARCH_DATE_KEY not in ctx.state


def test_capture_never_swaps_over_real_same_day_results():
    ctx = _Ctx({STATE_DATE_FALLBACK_KEY: _stashed_next_day()})
    resp = {"structuredContent": _search_offers_structured(2), "isError": False}
    capture_after_tool(_Tool("search_offers"), {}, ctx, resp)
    assert len(ctx.state["temp:hotel_search_results"]) == 2
    assert STATE_SEARCH_DATE_KEY not in ctx.state  # nothing was swapped


def test_datapart_carries_the_search_date():
    ctx = _Ctx({
        "temp:hotel_search_results": normalize_search_results(_search_offers_structured(2)),
        STATE_SEARCH_DATE_KEY: {
            "date": "2026-07-28", "same_day": False, "cutoff_fallback_from": "2026-07-27",
        },
    })
    payload = find_datapart(emit_search_datapart(ctx).parts)
    assert payload["search_date"]["cutoff_fallback_from"] == "2026-07-27"


def test_outcome_text_discloses_the_swapped_day_in_both_languages():
    results = normalize_search_results(_search_offers_structured(2))
    search_date = {"date": "2026-07-28", "same_day": False, "cutoff_fallback_from": "2026-07-27"}
    fr = _outcome_text(results, False, "fr", search_date)
    assert "closes" in fr and "2026-07-28" in fr and "2026-07-27" in fr
    en = _outcome_text(results, False, "en", search_date)
    assert "closed" in en and "2026-07-28" in en


def test_outcome_text_names_the_closed_day_on_a_dead_end():
    # The defect Fabien hit: a 0-result answer that never said WHICH day it
    # searched reads as a display bug.
    text = _outcome_text([], False, "fr", {"date": "2026-07-27", "same_day": True})
    assert "2026-07-27" in text and "closes" in text


def test_skip_final_generation_carries_the_same_disclosure():
    ctx = _Ctx({
        "temp:hotel_search_results": normalize_search_results(_search_offers_structured(1)),
        STATE_SEARCH_DATE_KEY: {
            "date": "2026-07-28", "same_day": False, "cutoff_fallback_from": "2026-07-27",
        },
    })
    text = skip_final_generation(ctx, None).content.parts[0].text
    assert "2026-07-28" in text


class TestGuardsFiredCrossesA2A:
    """OBS3 (2026-08-26). 6 of the 14 `GUARD_SCORE_NAMES` fire in THIS leaf and
    had no way to reach the concierge, so `score_guards` published them as 0.0 on
    every turn ever recorded — which is why `guard_geocode_echo_back = false` on
    the Toulon trace read as a structural false negative rather than "not
    measured". The tool reports what fired, `capture_after_tool` accumulates it,
    and `emit_search_datapart` puts it on the wire."""

    def test_capture_after_tool_accumulates_across_calls(self):
        ctx = _Ctx()
        capture_after_tool(_Tool("geocode_location"), {}, ctx,
                           {"ok": False, "guards_fired": ["generic_location_demotion"]})
        capture_after_tool(_Tool("geocode_location"), {}, ctx,
                           {"ok": True, "latitude": 1.0, "longitude": 2.0,
                            "guards_fired": ["state_anchoring"]})
        assert ctx.state["temp:hotel_search_guards_fired"] == [
            "generic_location_demotion", "state_anchoring",
        ]

    def test_a_failed_geocode_still_records_its_guards(self):
        # A guard that fired and then made the turn fail honestly is exactly
        # what OBS3 needs to see — scoring only successes reports the opposite.
        ctx = _Ctx()
        capture_after_tool(_Tool("geocode_location"), {}, ctx,
                           {"ok": False, "error": "geocode_echo_mismatch",
                            "guards_fired": ["geocode_echo_back"]})
        assert ctx.state["temp:hotel_search_guards_fired"] == ["geocode_echo_back"]

    def test_emit_puts_guards_on_the_datapart(self):
        ctx = _Ctx(state={
            "temp:hotel_search_guards_fired": ["state_anchoring"],
            "temp:hotel_search_profile_delta": {"last_city": "Milford"},
        })
        content = emit_search_datapart(ctx)
        assert content is not None
        payload = _decode(content)
        assert payload["guards_fired"] == ["state_anchoring"]
        # Top-level, NOT inside profile_delta: apply_profile_delta would reject
        # an unknown slot, and this is telemetry rather than profile state.
        assert "guards_fired" not in payload["profile_delta"]

    def test_guards_alone_are_enough_to_emit(self):
        # The turn that matters most for the demotion guard has no results and
        # no profile delta at all ("un hôtel près de la gare"). If telemetry
        # could not create a payload, that guard would stay unmeasurable.
        ctx = _Ctx(state={"temp:hotel_search_guards_fired": ["generic_location_demotion"]})
        content = emit_search_datapart(ctx)
        assert content is not None
        assert _decode(content)["guards_fired"] == ["generic_location_demotion"]
