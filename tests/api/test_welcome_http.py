"""E — `POST /v3/chat/welcome`, the mobile app's opening view (2026-10-27).

Widget logs after the switch of ai.dayuse.com: `POST /v3/chat/welcome HTTP/1.1"
404` on every opening of the assistant in the app. agent-usa served it
(contract: agent-usa `docs/SPEC_WIDGET_NATIVE_CONTEXT.md`), the widget still
calls it (`index.js::startFromAppContext`). Through the REAL composed ASGI app,
offline. The payloads are the app's shape (`aiAssistantBridge.ts`), with made-up
values.
"""
from __future__ import annotations

import logging

import b2c_concierge.agent as agent_module

_NATIVE = {
    "amp_device_id": "device-x",
    "amp_session_id": 1793035505424,
    "favoriteHotelIds": [12, 34],
    "geolocation": {"lat": 45.76, "lon": 4.83},
    "lastBookings": [
        {"hotelName": "Hôtel A", "hotelCity": "Lyon",
         "price": {"amount": 8900, "subunitDivisor": 100, "currency": "EUR"}, "timeslot": "10:00-17:00"},
        {"hotelName": "Hôtel B", "hotelCity": "Paris",
         "price": {"amount": 12000, "subunitDivisor": 100, "currency": "EUR"}, "timeslot": "14:00-20:00"},
        {"hotelName": "Hôtel C", "hotelCity": "lyon",
         "price": {"amount": 7900, "subunitDivisor": 100, "currency": "EUR"}, "timeslot": "10:00-17:00"},
    ],
}


def test_the_route_exists_and_personalizes_from_the_bookings(client):
    response = client.post("/v3/chat/welcome",
                           json={"native_context": _NATIVE, "locale": "fr", "currency": "EUR"})

    assert response.status_code == 200
    body = response.json()
    assert body["is_personalized"] is True
    # Lyon twice (any case), Paris once: most booked first, each once.
    assert body["suggestions"] == ["Chambre en journée à Lyon", "Chambre en journée à Paris"]
    assert "Lyon" in body["message"]
    assert body["market"] == {"language": "fr", "currency": "EUR"}


def test_a_visitor_without_bookings_keeps_the_widget_defaults(client):
    # Logged out in the app: no `lastBookings`. The widget only acts on
    # `is_personalized: true`.
    response = client.post("/v3/chat/welcome",
                           json={"native_context": {"amp_device_id": "d"}, "locale": "en"})

    assert response.status_code == 200
    assert response.json() == {"is_personalized": False, "message": "", "suggestions": [],
                               "market": {"language": "en", "currency": None}}


def test_malformed_context_never_fails(client):
    for native in (None, "x", [], {"lastBookings": "x"}, {"lastBookings": [None, {"hotelCity": 3}]}):
        response = client.post("/v3/chat/welcome", json={"native_context": native})
        assert response.status_code == 200
        assert response.json()["is_personalized"] is False


def test_no_llm_no_session_and_no_booking_detail_in_the_logs(client, monkeypatch, caplog):
    async def no_llm(**kwargs):
        raise AssertionError("the welcome view never calls an LLM")

    monkeypatch.setattr(agent_module.litellm, "acompletion", no_llm)
    with caplog.at_level(logging.DEBUG):
        response = client.post("/v3/chat/welcome", json={"native_context": _NATIVE, "locale": "en"})

    assert response.status_code == 200
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("Lyon", "Paris", "Hôtel A", "8900", "device-x"):
        assert secret not in logged
    assert "concierge_metric=welcome personalized=1 suggestions=2" in logged


def test_the_internal_key_is_required_like_the_other_routes(client, monkeypatch):
    monkeypatch.setenv("CHAT_API_KEY", "k")
    assert client.post("/v3/chat/welcome", json={"native_context": _NATIVE}).status_code == 401
    ok = client.post("/v3/chat/welcome", json={"native_context": _NATIVE},
                     headers={"X-Internal-Api-Key": "k"})
    assert ok.status_code == 200
