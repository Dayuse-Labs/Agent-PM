"""End-to-end facade tests for native-context intake (S-G2, 2026-07-23) — GPS
anchor round-trip through the REAL composed ASGI app + Redis (fakeredis)
profile store, exactly like test_facade_http.py's search turn. Confirms the
DoD's own scenario: a turn with `client_geo_context` (the verified widget GPS
shape — see facade.py's probe notes) persists a `search_anchor`; a later turn
with no location carries it over; an explicit new city clears it.
"""
from __future__ import annotations

import asyncio
import json
import logging

import b2c_concierge.agent as agent_module
from b2c_concierge.triage import Triage

_GPS_GRANTED = {
    "client_geo_context": {
        "device": {"latitude": 48.8566, "longitude": 2.3522, "accuracy_m": 25.0, "permission": "granted"}
    }
}


def _fake_search_leaf(city: str):
    async def fake_run_leaf(leaf, ctx, profile_in):
        return (f"Voici des hôtels à {city}.", {"results": [], "profile_delta": {"city": city}})

    return fake_run_leaf


def _install_search_turn(monkeypatch, city: str):
    async def fake_classify(message, budget, invocation_id="", *, recent_messages=None, previous_question=None):
        budget.charge("triage")
        return Triage("search", "fr", used_llm=False)

    async def fake_generate_once(self, **kwargs):
        return "Réponse."

    monkeypatch.setattr(agent_module, "classify", fake_classify)
    monkeypatch.setattr(agent_module, "_run_leaf", _fake_search_leaf(city))
    monkeypatch.setattr(agent_module._B2cConcierge, "_generate_once", fake_generate_once)


# --- GPS anchor persistence + no-silent-downgrade -------------------------------------------
def test_gps_anchor_persists_to_redis_profile(client, store):
    r = client.post("/v3/chat", json={"message": "Bonjour !", **_GPS_GRANTED})
    assert r.status_code == 200
    session_id = r.json()["session_id"]
    profile = asyncio.run(store.get(session_id))
    assert profile.search_anchor == {
        "type": "gps", "lat": 48.8566, "lon": 2.3522, "label": None, "set_at_turn": 0,
    }


def test_gps_anchor_surfaces_in_active_filters(client):
    r = client.post("/v3/chat", json={"message": "Bonjour !", **_GPS_GRANTED})
    af = r.json()["active_filters"]
    assert af["search_anchor"]["type"] == "gps"
    assert af["search_anchor"]["lat"] == 48.8566
    assert af["search_anchor"]["lon"] == 2.3522


def test_anchor_carries_over_on_a_turn_with_no_location_signal(client):
    first = client.post("/v3/chat", json={"message": "Bonjour !", **_GPS_GRANTED})
    sid = first.json()["session_id"]
    second = client.post(
        "/v3/chat", json={"message": "Merci !"}, headers={"X-Client-Session-Id": sid}
    )
    assert second.json()["active_filters"]["search_anchor"]["type"] == "gps"


def test_anchor_replaced_by_an_explicit_new_city(client, monkeypatch):
    first = client.post("/v3/chat", json={"message": "Bonjour !", **_GPS_GRANTED})
    sid = first.json()["session_id"]
    assert first.json()["active_filters"]["search_anchor"] is not None

    _install_search_turn(monkeypatch, "Berlin")
    second = client.post(
        "/v3/chat", json={"message": "un hôtel à Paris"}, headers={"X-Client-Session-Id": sid}
    )
    af = second.json()["active_filters"]
    # First city-bearing delta (None -> "Berlin") never triggers the anchor
    # clear (S-G1's rule only fires on an ACTUAL change from a prior city) —
    # the anchor still coexists with the freshly-resolved city here.
    assert af["city"] == "Berlin"
    assert af["search_anchor"] is not None

    _install_search_turn(monkeypatch, "Chicago")
    third = client.post(
        "/v3/chat", json={"message": "et à Chicago ?"}, headers={"X-Client-Session-Id": sid}
    )
    af3 = third.json()["active_filters"]
    assert af3["city"] == "Chicago"
    assert af3["search_anchor"] is None  # explicit city CHANGE clears the stale GPS anchor


def test_denied_permission_never_sets_an_anchor(client):
    r = client.post(
        "/v3/chat",
        json={"message": "Bonjour !", "client_geo_context": {"device": {"permission": "denied"}}},
    )
    assert r.json()["active_filters"]["search_anchor"] is None


def test_unavailable_permission_never_sets_an_anchor(client):
    r = client.post(
        "/v3/chat",
        json={
            "message": "Bonjour !",
            "client_geo_context": {"device": {"permission": "unavailable"}},
        },
    )
    assert r.json()["active_filters"]["search_anchor"] is None


# --- locale/currency/domain intake -----------------------------------------------------------
def test_locale_currency_domain_persist_and_surface(client):
    r = client.post(
        "/v3/chat",
        json={"message": "Bonjour !", "locale": "fr-FR", "currency": "eur", "domain": "Dayuse.com"},
    )
    af = r.json()["active_filters"]
    assert af["locale"] == "fr-FR"
    assert af["currency"] == "EUR"
    assert af["domain"] == "dayuse.com"
    assert r.json()["response_language"] == "fr"


def test_declared_locale_beats_the_message_guess(client):
    r = client.post("/v3/chat", json={"message": "Bonjour !", "locale": "es-ES"})
    # UX2 (2026-08-27): "es" is now answerable, and the DECLARED locale wins
    # over guess_language's French-hint false positive on this message.
    assert r.json()["response_language"] == "es"
    assert r.json()["active_filters"]["locale"] == "es-ES"


def test_unsupported_locale_falls_back_to_guess_language(client):
    r = client.post("/v3/chat", json={"message": "Bonjour !", "locale": "ja-JP"})
    # A primary tag outside the 7 recognized languages never becomes
    # response_language; guess_language("Bonjour !") still resolves "fr".
    assert r.json()["response_language"] == "fr"
    assert r.json()["active_filters"]["locale"] == "ja-JP"  # still stored, just not used for language


def test_empty_message_ack_prefers_locale_over_default_english(client):
    r = client.post("/v3/chat", json={"message": "", "locale": "fr"})
    assert r.json()["response_language"] == "fr"


# --- market currency by default (rule of 2026-10-26) -------------------------------------------
_NY_CARD = {
    "id": 2, "name": "Hotel Midtown", "price": "€165.10", "price_eur_cents": 16510,
    "hotel_price": "USD 187.00", "hotel_price_minor": 18700, "hotel_currency_code": "USD",
    "currency_code": "USD", "offer_totals": {"EUR": 16510, "USD": 18700},
}


def _install_ny_search(monkeypatch):
    _install_search_turn(monkeypatch, "New York")

    async def fake_run_leaf(leaf, ctx, profile_in):
        return ("Voici un hôtel.", {"results": [dict(_NY_CARD)], "profile_delta": {"city": "New York"}})

    monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)


def test_a_us_visitor_gets_the_card_in_dollars(client, monkeypatch):
    """Prod 2026-10-26: the widget sent currency=USD and the card said €165.10
    although it carried hotel_price USD 187.00."""
    _install_ny_search(monkeypatch)
    r = client.post(
        "/v3/chat",
        json={"message": "a day room in New York tomorrow", "currency": "USD", "entry_market_country": "US"},
    )
    card = r.json()["hotels"][0]
    assert card["price"] == "USD 187.00"
    assert (card["display_currency"], card["display_price_minor"]) == ("USD", 18700)


def test_a_euro_market_keeps_the_same_card_in_euros(client, monkeypatch):
    _install_ny_search(monkeypatch)
    r = client.post(
        "/v3/chat",
        json={"message": "un hôtel à New York demain", "currency": "EUR", "entry_market_country": "FR"},
    )
    card = r.json()["hotels"][0]
    assert card["price"] == "€165.10"
    assert card.get("display_currency") is None


# --- never a 500 on garbage/opaque optional fields --------------------------------------------
def test_garbage_native_context_never_500s(client):
    r = client.post(
        "/v3/chat",
        json={
            "message": "Bonjour !",
            "locale": 12345,
            "currency": ["EUR"],
            "domain": {"nested": True},
            "native_context": {"deeply": {"nested": ["opaque", "blob"]}},
            "client_geo_context": {"device": {"latitude": "not-a-number", "permission": "granted"}},
            "selected_place": "unspecified-shape",
        },
    )
    assert r.status_code == 200
    assert r.json()["active_filters"]["search_anchor"] is None


# --- RGPD: GPS coordinates must never reach logs or llm_metric_events -------------------------
def test_gps_coordinates_never_appear_in_logs_or_metrics(client, monkeypatch, caplog):
    """S3/S-G2 lock: a turn that DOES carry a real GPS fix must still never
    leak the coordinates into either channel — same invariant as
    test_spine.py's TestGdprMetrics/TestGdprLogs, exercised here through the
    facade's native-context intake specifically (profile.py's `_log_profile_ops`
    already logs slot NAMES only; this proves that discipline holds end-to-end
    through the new GPS path too)."""
    events: list[dict] = []

    def capture(event_type, service, invocation_id, **fields):
        events.append({"event_type": event_type, "service": service, **fields})

    monkeypatch.setattr(agent_module, "enqueue_metric_event", capture)
    _install_search_turn(monkeypatch, "Paris")

    with caplog.at_level(logging.DEBUG):
        r = client.post("/v3/chat", json={"message": "un hôtel à Paris", **_GPS_GRANTED})

    assert r.status_code == 200
    assert r.json()["active_filters"]["search_anchor"]["lat"] == 48.8566  # sanity: anchor DID get set

    log_blob = "\n".join(record.getMessage() for record in caplog.records)
    assert "48.8566" not in log_blob
    assert "2.3522" not in log_blob

    metrics_blob = json.dumps(events, ensure_ascii=False)
    assert "48.8566" not in metrics_blob
    assert "2.3522" not in metrics_blob
