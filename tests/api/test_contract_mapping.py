"""Pure, offline tests of the v3 contract mapping + conversation-log row.

These are the golden non-regression fixtures for the response SHAPE: the exact
key set agent-usa's /v3/chat returns (message, hotels, suggestions, session_id,
active_filters, the legacy aliases, the staged-workflow booleans), asserted
against build_chat_payload's output. No HTTP, no LLM, no Redis.
"""
from __future__ import annotations

import json

from b2c_concierge import conversation_log
from b2c_concierge.facade import (
    CONTRACT_KEYS,
    build_active_filters,
    build_chat_payload,
    normalize_hotels,
)
from b2c_concierge.profile import SessionProfile


# --- golden contract SHAPE ------------------------------------------------------------------
def test_payload_has_exactly_the_contract_keys():
    payload = build_chat_payload(
        session_id="sid1",
        final_text="Bonjour !",
        hotels=None,
        profile=SessionProfile(),
        language="fr",
        turn_id="t1",
    )
    assert set(payload.keys()) == set(CONTRACT_KEYS)


def test_legacy_aliases_mirror_message():
    payload = build_chat_payload(
        session_id="sid1", final_text="hello there", hotels=None,
        profile=SessionProfile(), language="en", turn_id="t1",
    )
    assert payload["message"] == "hello there"
    assert payload["response"] == "hello there"  # legacy frontend alias
    assert payload["context"] == "hello there"  # legacy frontend alias
    assert payload["conversation_id"] == payload["session_id"] == "sid1"


def test_no_lookup_turn_maps_hotels_none_and_not_ready():
    payload = build_chat_payload(
        session_id="s", final_text="ack", hotels=None,
        profile=SessionProfile(), language="en", turn_id="t",
    )
    assert payload["hotels"] is None
    assert payload["ready_to_search"] is False
    assert payload["requires_clarification"] is False  # default stays False
    assert payload["state"] == "responding"


def test_geocode_clarify_turn_reports_requires_clarification():
    # S-G10 (D3): the leaf's deterministic geocode-clarify flag reaches the
    # contract field (was hardcoded False — safe clarifying questions scored
    # as hard failures). Reporting only: nothing blocks.
    payload = build_chat_payload(
        session_id="s", final_text="Did you mean Budapest (Hungary), or Budapest (Georgia)?",
        hotels=None, profile=SessionProfile(), language="en", turn_id="t",
        requires_clarification=True,
    )
    assert payload["requires_clarification"] is True
    assert payload["ready_to_search"] is False
    assert set(payload.keys()) == set(CONTRACT_KEYS)  # shape untouched


def test_search_turn_maps_hotel_list_and_ready():
    hotels = [{"id": 101, "name": "Pool Hotel Miami", "country_code": "US"}]
    payload = build_chat_payload(
        session_id="s", final_text="Here are options.", hotels=hotels,
        profile=SessionProfile(city="Miami"), language="en", turn_id="t",
    )
    assert payload["hotels"] == hotels
    assert payload["ready_to_search"] is True
    assert payload["market_country"] == "US"
    assert payload["entry_market_country"] == "US"
    assert payload["search_country"] == "US"
    assert payload["market"] == {"country_code": "US"}


# --- market country (the widget's ISO-keyed market table drives button + card URLs) ----------
def test_market_falls_back_to_profile_country_anchor():
    payload = build_chat_payload(
        session_id="s", final_text="Voici.", hotels=[{"id": 1, "name": "Villa Paris Orly"}],
        profile=SessionProfile(city="Paris", country_anchor="FR"), language="fr", turn_id="t",
    )
    assert payload["market_country"] == "FR"
    assert payload["entry_market_country"] == "FR"
    assert payload["search_country"] == "FR"
    assert payload["market"] == {"country_code": "FR"}
    assert payload["active_filters"]["country_code"] == "FR"


def test_market_absent_without_any_country_signal():
    payload = build_chat_payload(
        session_id="s", final_text="Voici.", hotels=[{"id": 1, "name": "Villa"}],
        profile=SessionProfile(city="Paris"), language="fr", turn_id="t",
    )
    assert payload["market"] == {}
    assert payload["market_country"] is None
    assert payload["search_country"] is None


def test_full_country_name_never_becomes_a_pseudo_market_code():
    # MCP sends `country: "France"` (full name, probed live 2026-07-20). The
    # widget's COUNTRY_META is ISO-keyed: "FRANCE" would silently fail there —
    # None is strictly better (widget falls back to its entry market).
    payload = build_chat_payload(
        session_id="s", final_text="Voici.",
        hotels=[{"id": 1, "name": "Villa", "country": "France"}],
        profile=SessionProfile(city="Paris", country_anchor="Île-de-France"),
        language="fr", turn_id="t",
    )
    assert payload["market_country"] is None
    assert payload["market"] == {}


def test_first_hotel_with_iso_code_wins():
    hotels = [{"id": 1, "name": "A", "country": "France"}, {"id": 2, "name": "B", "country_code": "FR"}]
    payload = build_chat_payload(
        session_id="s", final_text="Voici.", hotels=hotels,
        profile=SessionProfile(), language="fr", turn_id="t",
    )
    assert payload["market_country"] == "FR"


# --- price formatting (consistent with S07) -------------------------------------------------
def test_normalize_hotels_formats_price_euro_cents():
    out = normalize_hotels([{"name": "H", "priceEuro": 8000}])
    assert out[0]["price"] == "€80.00"


def test_normalize_hotels_keeps_existing_display_price():
    out = normalize_hotels([{"name": "H", "price": "€54.00", "priceEuro": 5400}])
    assert out[0]["price"] == "€54.00"  # not overwritten


def test_normalize_hotels_passes_image_urls_through_untouched():
    # image_urls is set upstream (response_bridge.py / inline_tools.py) from
    # mainPhotoNormal -> static.dayuse.com — the facade must not drop or
    # reshape it (widget reads hotel.image_urls to render the photo carousel).
    out = normalize_hotels([{"name": "H", "image_urls": ["https://static.dayuse.com/hotels/1/a.png"]}])
    assert out[0]["image_urls"] == ["https://static.dayuse.com/hotels/1/a.png"]


def test_normalize_hotels_empty_and_non_dict_passthrough():
    assert normalize_hotels(None) == []
    assert normalize_hotels([]) == []
    assert normalize_hotels(["weird"]) == ["weird"]


# --- active_filters mapping -----------------------------------------------------------------
def test_active_filters_maps_profile_fields():
    profile = SessionProfile(
        city="Paris", budget_max=150.0, amenities=["pool", "spa"], country_anchor="FR"
    )
    af = build_active_filters(profile)
    assert af["city"] == "Paris"
    assert af["resolved_city"] == "Paris"
    assert af["budget_max"] == 150.0
    assert af["amenities"] == ["pool", "spa"]
    assert af["country_code"] == "FR"


def test_active_filters_synthesizes_one_sided_timeslot():
    assert build_active_filters(SessionProfile(timeslot_start="15:00"))["timeslot"] == "15:00-"
    assert build_active_filters(SessionProfile(timeslot_end="09:00"))["timeslot"] == "-09:00"
    assert (
        build_active_filters(SessionProfile(timeslot_start="10:00", timeslot_end="17:00"))["timeslot"]
        == "10:00-17:00"
    )
    assert build_active_filters(SessionProfile(timeslot="morning"))["timeslot"] == "morning"


def test_profile_status_derivation():
    assert build_chat_payload(
        session_id="s", final_text="x", hotels=None, profile=SessionProfile(),
        language="en", turn_id="t",
    )["profile_status"] == "empty"
    assert build_chat_payload(
        session_id="s", final_text="x", hotels=None, profile=SessionProfile(budget_max=100.0),
        language="en", turn_id="t",
    )["profile_status"] == "collecting"
    assert build_chat_payload(
        session_id="s", final_text="x", hotels=None, profile=SessionProfile(city="Paris"),
        language="en", turn_id="t",
    )["profile_status"] == "ready"


def test_suggestions_map_recovery_chips():
    profile = SessionProfile(last_suggestions=["increase the budget", "remove a filter"])
    payload = build_chat_payload(
        session_id="s", final_text="no results", hotels=None, profile=profile,
        language="en", turn_id="t",
    )
    assert payload["suggestions"] == ["increase the budget", "remove a filter"]


def test_payload_is_json_serializable():
    payload = build_chat_payload(
        session_id="s", final_text="x", hotels=[{"name": "H", "priceEuro": 5400}],
        profile=SessionProfile(city="Paris"), language="fr", turn_id="t",
    )
    json.dumps(payload)  # must not raise


# --- conversation_logs row + is_synthetic ---------------------------------------------------
def test_conversation_log_row_shape_and_synthetic_flag():
    row = conversation_log.build_conversation_log_row(
        session_id="s1",
        turn_index=2,
        user_message="je cherche un hôtel",
        assistant_message="voici des options",
        hotels=[{"name": "H"}],
        active_filters={"city": "Paris"},
        response_language="fr",
        is_synthetic=True,
    )
    assert row["session_id"] == "s1"
    assert row["turn_index"] == 2
    assert row["user_message"] == "je cherche un hôtel"
    assert row["assistant_message"] == "voici des options"
    assert row["response_language"] == "fr"
    assert row["is_synthetic"] is True
    # jsonb columns are pre-encoded strings the CAST turns back into jsonb
    assert json.loads(row["hotels"]) == [{"name": "H"}]
    assert json.loads(row["active_filters"]) == {"city": "Paris"}


def test_conversation_log_row_defaults_non_synthetic():
    row = conversation_log.build_conversation_log_row(
        session_id="s", turn_index=0, user_message="", assistant_message="",
        hotels=None, active_filters={}, response_language="", is_synthetic=False,
    )
    assert row["is_synthetic"] is False
    assert row["hotels"] == "[]"
    assert row["response_language"] is None  # empty → NULL


def test_detect_is_synthetic():
    assert conversation_log.detect_is_synthetic({"x-dayuse-synthetic": "true"}) is True
    assert conversation_log.detect_is_synthetic({"x-dayuse-synthetic": "1"}) is True
    assert conversation_log.detect_is_synthetic({"x-dayuse-synthetic": "yes"}) is True
    assert conversation_log.detect_is_synthetic({"x-dayuse-synthetic": "0"}) is False
    assert conversation_log.detect_is_synthetic({"x-dayuse-synthetic": "false"}) is False
    assert conversation_log.detect_is_synthetic({}) is False
