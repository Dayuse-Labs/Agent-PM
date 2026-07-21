"""Offline unit tests for the leaf's structured-results DataPart + truncation bridge.

No network, no LLM, no MCP: the callbacks are pure functions over fake
tool/agent contexts. The DataPart is verified through the REAL ADK A2A converter
(`convert_genai_part_to_a2a_part`), the exact hop the orchestrator relies on.
"""
from __future__ import annotations

import json

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_genai_part_to_a2a_part

from hotel_search_agent.response_bridge import (
    STATE_APPLIED_AMENITIES_KEY,
    _photo_url,
    capture_after_tool,
    decode_datapart,
    emit_search_datapart,
    encode_datapart,
    find_datapart,
    normalize_hotel,
    normalize_search_results,
    skip_final_generation,
)


class _Ctx:
    """Minimal stand-in for ADK ToolContext/CallbackContext (a dict-backed .state)."""

    def __init__(self, state=None):
        self.state = state if state is not None else {}


class _Tool:
    def __init__(self, name):
        self.name = name


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
    # leaf keys mapped to the orchestrator's profile schema (S5 naming gap)
    assert data["profile_delta"] == {"city": "Paris", "state_anchor": "NY"}
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
    assert data["profile_delta"] == {"city": "Lyon"}


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
    assert data["profile_delta"] == {"city": "Paris", "country_anchor": "FR"}


def test_emit_country_anchor_flows_even_on_a_geocode_only_turn():
    # geocode ran but no search (e.g. the model asked a clarification): the anchor
    # still reaches the orchestrator so active_filters/market survive the turn.
    ctx = _Ctx({"temp:hotel_search_country_code": "FR"})
    data = _decode(emit_search_datapart(ctx))
    assert data == {"profile_delta": {"country_anchor": "FR"}}


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
