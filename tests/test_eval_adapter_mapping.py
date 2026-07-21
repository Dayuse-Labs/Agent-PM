"""Pure, offline tests of the eval-pack adapter's mapping rules (S15).

The adapter (scripts/run_eval_adapter.py) may only FILL ABSENT hotel-card keys
from facts already in the card (country full name, the facade's €X.XX price
string) and must disclose every addition under eval_debug.adapter_mapped.
These tests lock that contract: no overwrite, no invention, full disclosure.
The HTTP plumbing itself reuses the proven run_widget_proxy.py pattern and is
exercised by the smoke run — only the pure functions are unit-tested here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_eval_adapter.py"
_spec = importlib.util.spec_from_file_location("run_eval_adapter", _SCRIPT)
assert _spec is not None and _spec.loader is not None
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)


# --- map_hotel_card: country_code -----------------------------------------------------------
def test_country_code_added_from_full_name():
    card, added = adapter.map_hotel_card({"id": 1, "country": "France"})
    assert card["country_code"] == "FR"
    assert "country_code" in added


def test_country_name_matching_is_case_insensitive():
    for name in ("FRANCE", "france", "  France "):
        card, _ = adapter.map_hotel_card({"country": name})
        assert card["country_code"] == "FR"


def test_existing_country_code_never_overwritten():
    card, added = adapter.map_hotel_card({"country": "France", "country_code": "BE"})
    assert card["country_code"] == "BE"
    assert added == []


def test_unknown_country_name_left_unmapped():
    card, added = adapter.map_hotel_card({"country": "Atlantis"})
    assert "country_code" not in card
    assert added == []


def test_non_string_country_ignored():
    card, added = adapter.map_hotel_card({"country": 33})
    assert "country_code" not in card
    assert added == []


# --- map_hotel_card: currency / display_price ------------------------------------------------
def test_currency_and_display_price_derived_from_facade_price_format():
    card, added = adapter.map_hotel_card({"price": "€123.45"})
    assert card["currency"] == "EUR"
    assert card["display_price"] == 123.45
    assert set(added) == {"currency", "display_price"}


def test_price_without_cents_also_matches():
    card, _ = adapter.map_hotel_card({"price": "€89"})
    assert card["display_price"] == 89.0


def test_non_facade_price_formats_do_not_map():
    for price in ("US$120", "123.45", "€12.3", "€ 120.00", None, 120):
        card, added = adapter.map_hotel_card({"price": price})
        assert "currency" not in card, price
        assert "display_price" not in card, price
        assert added == []


def test_existing_currency_never_overwritten():
    card, added = adapter.map_hotel_card({"price": "€10.00", "currency": "GBP"})
    assert card["currency"] == "GBP"
    assert added == ["display_price"]


# --- map_chat_payload: disclosure + identity --------------------------------------------------
def test_payload_maps_hotels_and_discloses_per_hotel():
    payload = {
        "message": "voici",
        "hotels": [
            {"id": "h1", "country": "Italy", "price": "€99.00"},
            {"id": "h2", "country_code": "US", "currency": "EUR", "price": "€50.00"},
        ],
    }
    out = adapter.map_chat_payload(payload)
    assert out["hotels"][0]["country_code"] == "IT"
    assert out["eval_debug"]["adapter_mapped"] == {
        "h1": ["country_code", "currency", "display_price"],
        "h2": ["display_price"],
    }
    # original payload untouched (mapping returns a copy)
    assert "eval_debug" not in payload
    assert "country_code" not in payload["hotels"][0]


def test_payload_without_mappable_hotels_returned_identical():
    payload = {"message": "ok", "hotels": [{"id": "h1", "country_code": "FR"}]}
    assert adapter.map_chat_payload(payload) is payload


def test_payload_with_null_hotels_returned_identical():
    payload = {"message": "ok", "hotels": None}
    assert adapter.map_chat_payload(payload) is payload


def test_non_dict_hotel_entries_pass_through():
    payload = {"hotels": ["oddball", {"id": "h1", "country": "Spain"}]}
    out = adapter.map_chat_payload(payload)
    assert out["hotels"][0] == "oddball"
    assert out["hotels"][1]["country_code"] == "ES"
    assert out["eval_debug"]["adapter_mapped"] == {"h1": ["country_code"]}


def test_disclosure_key_falls_back_to_index_when_no_id():
    payload = {"hotels": [{"country": "Qatar"}]}
    out = adapter.map_chat_payload(payload)
    assert out["eval_debug"]["adapter_mapped"] == {"index_0": ["country_code"]}


def test_existing_eval_debug_preserved():
    payload = {
        "hotels": [{"id": "h1", "country": "Sweden"}],
        "eval_debug": {"tool_calls": [{"name": "search_offers"}]},
    }
    out = adapter.map_chat_payload(payload)
    assert out["eval_debug"]["tool_calls"] == [{"name": "search_offers"}]
    assert out["eval_debug"]["adapter_mapped"] == {"h1": ["country_code"]}
