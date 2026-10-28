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
    # Lyon twice (any case), Paris once: most booked first, each once — then
    # « près de moi » (2026-10-28), named so the widget asks for the position.
    assert body["suggestions"] == [
        "Chambre en journée à Lyon", "Chambre en journée à Paris", "Chambre en journée près de moi",
    ]
    assert body["near_me"] == "Chambre en journée près de moi"
    assert "Lyon" in body["message"]
    assert body["market"] == {"language": "fr", "currency": "EUR"}


def test_an_app_visitor_without_bookings_gets_the_near_me_chip(client):
    # 2026-10-28: logged out in the app (no `lastBookings`): the « near me »
    # chip alone — agent-usa's first entry, absent since the switch. The
    # widget keeps its own greeting (empty message).
    response = client.post("/v3/chat/welcome",
                           json={"native_context": {"amp_device_id": "d"}, "locale": "en"})

    assert response.status_code == 200
    assert response.json() == {"is_personalized": True, "message": "", "suggestions": ["Day room near me"],
                               "near_me": "Day room near me",
                               "market": {"language": "en", "currency": None}}


def test_the_near_me_chip_speaks_the_seven_languages(client):
    labels = {
        client.post("/v3/chat/welcome", json={"native_context": {"a": 1}, "locale": lang}).json()["near_me"]
        for lang in ("fr", "en", "es", "it", "de", "pt", "nl")
    }
    assert len(labels) == 7
    assert "Camera a uso diurno vicino a me" in labels  # agent-usa's label, 84 conversations


def test_outside_the_app_nothing_is_offered(client):
    # The web page (no `native_context`) has its own hero chips.
    for native in (None, "x", [], {}):
        response = client.post("/v3/chat/welcome", json={"native_context": native})
        assert response.status_code == 200
        assert response.json()["is_personalized"] is False
        assert response.json()["suggestions"] == []


def test_malformed_bookings_never_fail(client):
    for native in ({"lastBookings": "x"}, {"lastBookings": [None, {"hotelCity": 3}]}):
        response = client.post("/v3/chat/welcome", json={"native_context": native, "locale": "en"})
        assert response.status_code == 200
        assert response.json()["suggestions"] == ["Day room near me"]


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
    assert "concierge_metric=welcome personalized=1 suggestions=3" in logged


def test_the_internal_key_is_required_like_the_other_routes(client, monkeypatch):
    monkeypatch.setenv("CHAT_API_KEY", "k")
    assert client.post("/v3/chat/welcome", json={"native_context": _NATIVE}).status_code == 401
    ok = client.post("/v3/chat/welcome", json={"native_context": _NATIVE},
                     headers={"X-Internal-Api-Key": "k"})
    assert ok.status_code == 200
