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
    assert payload["requires_clarification"] is False
    assert payload["state"] == "responding"


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


# --- price formatting (consistent with S07) -------------------------------------------------
def test_normalize_hotels_formats_price_euro_cents():
    out = normalize_hotels([{"name": "H", "priceEuro": 8000}])
    assert out[0]["price"] == "€80.00"


def test_normalize_hotels_keeps_existing_display_price():
    out = normalize_hotels([{"name": "H", "price": "€54.00", "priceEuro": 5400}])
    assert out[0]["price"] == "€54.00"  # not overwritten


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
