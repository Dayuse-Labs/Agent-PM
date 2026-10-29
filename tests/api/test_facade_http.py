"""End-to-end facade tests over the real composed ASGI app (offline).

The ack path is fully deterministic and zero-LLM (template), so most HTTP
mechanics (session/cookie/reset/auth/is_synthetic, and the SSE progress→done
ordering) are tested with no mocking at all. One search turn is driven with the
spine's LLM/leaf boundaries stubbed, to prove the full SSE ordering
progress → hotels → tokens → done and the hotel/ready_to_search mapping.
"""
from __future__ import annotations

import json
import logging
import re

import pytest

import b2c_concierge.agent as agent_module
from b2c_common.clarification import Clarification
import b2c_concierge.facade as facade_module
from b2c_concierge import templates
from b2c_concierge.facade import CONTRACT_KEYS
from b2c_concierge.triage import Triage


# --- non-streamed /v3/chat ------------------------------------------------------------------
def test_ack_turn_returns_full_contract_and_sets_cookie(client):
    r = client.post("/v3/chat", json={"message": "Bonjour !"})
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == set(CONTRACT_KEYS)
    assert data["message"]
    assert data["hotels"] is None
    assert data["ready_to_search"] is False
    assert data["session_id"]
    set_cookie = r.headers.get("set-cookie", "")
    assert "du_chat_sid=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()


def test_cookie_reuses_server_session_across_turns(client):
    first = client.post("/v3/chat", json={"message": "Bonjour !"})
    first_sid = first.json()["session_id"]
    second = client.post("/v3/chat", json={"message": "Merci !"})
    assert second.json()["session_id"] == first_sid  # cookie carried the session


def test_x_client_session_id_header_pins_the_session(client):
    r = client.post(
        "/v3/chat", json={"message": "hello"}, headers={"X-Client-Session-Id": "pinned-123"}
    )
    assert r.json()["session_id"] == "pinned-123"


def test_client_header_outranks_an_existing_cookie(client):
    """THE RELOAD BUG. The `du_chat_sid` cookie is httponly, so the widget cannot
    drop it from JS: while it outranked `X-Client-Session-Id`, a reloaded page —
    which wipes the visible conversation and mints a new client session id — was
    silently pinned back onto the previous server session, and answered a fresh
    "je cherche un hotel" with the city/date/amenities of the search before the
    reload. The explicit client id must win; the cookie only backs it up."""
    first = client.post(
        "/v3/chat", json={"message": "Bonjour !"}, headers={"X-Client-Session-Id": "before-reload"}
    )
    assert first.json()["session_id"] == "before-reload"
    assert "du_chat_sid=before-reload" in first.headers.get("set-cookie", "")

    # Same cookie jar (the browser kept the cookie across the reload), new id.
    second = client.post(
        "/v3/chat", json={"message": "Bonjour !"}, headers={"X-Client-Session-Id": "after-reload"}
    )
    assert second.json()["session_id"] == "after-reload"
    assert "du_chat_sid=after-reload" in second.headers.get("set-cookie", "")


def test_m1_accepts_legacy_body_session_when_no_cookie(fresh_client):
    c = fresh_client()
    r = c.post("/v3/chat", json={"message": "hello", "session_id": "legacy_session_123"})
    assert r.status_code == 200
    assert r.json()["session_id"] == "legacy_session_123"
    assert "du_chat_sid=legacy_session_123" in r.headers.get("set-cookie", "")


def test_m1_rejects_invalid_legacy_body_session(fresh_client):
    c = fresh_client()
    r = c.post("/v3/chat", json={"message": "hello", "session_id": "bad session with spaces"})
    assert r.status_code == 400
    assert r.json()["error"] == "Invalid session_id"


# --- session reset --------------------------------------------------------------------------
def test_session_reset_clears_cookie_and_starts_fresh(client):
    first = client.post("/v3/chat", json={"message": "Bonjour !"})
    first_sid = first.json()["session_id"]

    reset = client.post("/v3/chat/session/reset")
    assert reset.status_code == 204
    assert "Max-Age=0" in reset.headers.get("set-cookie", "")

    # A greeting the ack regex answers without the LLM ("hello again" is not):
    # this test is about the session cookie and must stay offline.
    second = client.post("/v3/chat", json={"message": "Hello!"})
    assert second.json()["session_id"] != first_sid


# --- auth (phase minimum: internal API key) -------------------------------------------------
def test_missing_api_key_returns_401(monkeypatch, client):
    monkeypatch.setenv("CHAT_API_KEY", "secret")
    r = client.post("/v3/chat", json={"message": "hello"})
    assert r.status_code == 401
    assert r.json() == {"error": "Unauthorized"}


def test_invalid_api_key_returns_401(monkeypatch, client):
    monkeypatch.setenv("CHAT_API_KEY", "secret")
    r = client.post("/v3/chat", json={"message": "hello"}, headers={"X-Internal-Api-Key": "wrong"})
    assert r.status_code == 401


def test_valid_api_key_returns_200(monkeypatch, client):
    monkeypatch.setenv("CHAT_API_KEY", "secret")
    r = client.post("/v3/chat", json={"message": "hello"}, headers={"X-Internal-Api-Key": "secret"})
    assert r.status_code == 200
    assert r.json()["session_id"]


def test_auth_bypass_overrides_api_key(monkeypatch, client):
    monkeypatch.setenv("CHAT_API_KEY", "secret")
    monkeypatch.setenv("AUTH_BYPASS", "true")
    r = client.post("/v3/chat", json={"message": "hello"})
    assert r.status_code == 200


def test_v3_is_not_behind_the_d7_a2a_bearer(client):
    """The whole point of the split: /v3 must NOT require the D7 A2A bearer."""
    r = client.post("/v3/chat", json={"message": "hello"})  # no Authorization header at all
    assert r.status_code == 200


# --- is_synthetic detection -----------------------------------------------------------------
def test_synthetic_header_marks_the_log_row(client, captured_logs):
    client.post("/v3/chat", json={"message": "Bonjour !"}, headers={"X-Dayuse-Synthetic": "true"})
    assert captured_logs and captured_logs[-1]["is_synthetic"] is True


def test_no_synthetic_header_is_real_traffic(client, captured_logs):
    client.post("/v3/chat", json={"message": "Bonjour !"})
    assert captured_logs and captured_logs[-1]["is_synthetic"] is False


def test_log_row_carries_turn_content_and_index(client, captured_logs):
    client.post("/v3/chat", json={"message": "Bonjour !"}, headers={"X-Client-Session-Id": "sess-x"})
    client.post("/v3/chat", json={"message": "Merci !"}, headers={"X-Client-Session-Id": "sess-x"})
    assert captured_logs[0]["turn_index"] == 0
    assert captured_logs[1]["turn_index"] == 1
    assert captured_logs[1]["user_message"] == "Merci !"
    assert captured_logs[1]["assistant_message"]


# --- SSE --------------------------------------------------------------------------------------
def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event = ""
        data = "{}"
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        events.append((event, json.loads(data)))
    return events


def test_sse_ack_streams_progress_first_then_done(client):
    r = client.post("/v3/chat/stream", json={"message": "Bonjour !"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    assert events[0][0] == "progress"  # TTFT marker is first
    assert events[-1][0] == "done"
    done_payload = events[-1][1]
    assert set(done_payload.keys()) == set(CONTRACT_KEYS)
    # ack path: no hotels, no token events
    assert [e for e, _ in events if e == "hotels"] == []


def test_sse_search_streams_progress_hotels_tokens_done(monkeypatch, client):
    async def fake_classify(message, budget, invocation_id="", *, recent_messages=None, previous_question=None):
        budget.charge("triage")
        return Triage("search", "fr", used_llm=False)

    async def fake_run_leaf(leaf, ctx, profile_in, **kwargs):
        return (
            "Voici des hôtels à Paris.",
            {
                "results": [
                    {"id": 101, "name": "Pool Hotel Paris", "country_code": "FR", "priceEuro": 8000}
                ],
                "profile_delta": {"city": "Paris"},
            },
        )

    async def fake_generate_once(self, **kwargs):
        return "Voici deux hôtels en journée à Paris pour vous."

    monkeypatch.setattr(agent_module, "classify", fake_classify)
    monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
    monkeypatch.setattr(agent_module._B2cConcierge, "_generate_once", fake_generate_once)

    r = client.post("/v3/chat/stream", json={"message": "un hôtel à Paris"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]

    assert kinds[0] == "progress"
    assert "hotels" in kinds
    assert "token" in kinds
    assert kinds[-1] == "done"
    # order: progress before hotels before first token before done
    assert kinds.index("progress") < kinds.index("hotels") < kinds.index("token") < kinds.index("done")

    hotels_event = next(d for e, d in events if e == "hotels")
    assert hotels_event["hotels"][0]["name"] == "Pool Hotel Paris"
    assert hotels_event["hotels"][0]["price"] == "€80.00"  # priceEuro cents → €X.XX (S07)
    # S-PERF4: the flag AND the language ride the frame, so a hotels-first client
    # decides whether to paint the shortlist — and in which language — from the
    # SAME inputs the `done` payload will carry.
    assert hotels_event["requires_clarification"] is False
    assert hotels_event["response_language"] == "fr"

    done_payload = events[-1][1]
    # The early frame and the final payload must never disagree on the language.
    assert done_payload["response_language"] == hotels_event["response_language"]
    # …nor on WHICH cards are bookable. S-CX9 gates the card's booking CTA on
    # `hotel_picks`; a client painting the shortlist on this frame renders every
    # card with no CTA unless the picks ride it too. Non-empty is the point of the
    # assertion — an equality between two empty lists would prove nothing.
    assert hotels_event["hotel_picks"] == [
        {"hotel_id": 101, "name": "Pool Hotel Paris", "price": None, "price_eur_cents": None}
    ]
    assert hotels_event["hotel_picks"] == done_payload["hotel_picks"]
    assert done_payload["hotels"][0]["name"] == "Pool Hotel Paris"
    assert done_payload["ready_to_search"] is True
    assert done_payload["active_filters"]["city"] == "Paris"
    # reassembled token stream == the final message
    streamed = "".join(d["text"] for e, d in events if e == "token")
    assert streamed.strip() == done_payload["message"].strip()


def test_sse_hotels_frame_carries_the_clarify_flag(monkeypatch, client):
    """A clarifying turn must be recognisable ON THE FRAME, not only in `done`:
    the widget renders the shortlist as soon as the frame lands, and the
    blocking-POST path answers a clarifying turn WITHOUT a carousel. Without
    this flag the two transports would disagree on that turn."""
    async def fake_classify(message, budget, invocation_id="", *, recent_messages=None, previous_question=None):
        budget.charge("triage")
        return Triage("search", "fr", used_llm=False)

    async def fake_run_leaf(leaf, ctx, profile_in, **kwargs):
        return (
            "De quelle ville parlez-vous ?",
            {
                "results": [{"id": 7, "name": "Ambiguous Hotel", "country_code": "FR"}],
                "requires_clarification": True,
            },
        )

    async def fake_generate_once(self, **kwargs):
        return "De quelle ville parlez-vous ?"

    monkeypatch.setattr(agent_module, "classify", fake_classify)
    monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
    monkeypatch.setattr(agent_module._B2cConcierge, "_generate_once", fake_generate_once)

    r = client.post("/v3/chat/stream", json={"message": "un hôtel dans le centre"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    hotels_event = next(d for e, d in events if e == "hotels")
    assert hotels_event["requires_clarification"] is True
    assert events[-1][1]["requires_clarification"] is True


def test_sse_clarification_turn_streams_progress_then_the_template(monkeypatch, client):
    """QA14707 (Q04, DQ2): a place question from the leaf skips the synthesis.
    The stream must not lose its shape for it: `progress` first, the template's
    text as tokens, `done` carrying the same text and the clarify flag."""
    clarification = Clarification(kind="city_needed", subject="Gare du Nord")

    async def fake_classify(message, budget, invocation_id="", *, recent_messages=None, previous_question=None):
        budget.charge("triage")
        return Triage("search", "fr", used_llm=False)

    async def fake_run_leaf(leaf, ctx, profile_in, **kwargs):
        return (
            "Near Gare du Nord — which city?",
            {"requires_clarification": True, "clarification": clarification.model_dump(mode="json")},
        )

    async def no_synthesis(self, **kwargs):
        raise AssertionError("a clarification turn makes no synthesis call")

    monkeypatch.setattr(agent_module, "classify", fake_classify)
    monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
    monkeypatch.setattr(agent_module._B2cConcierge, "_generate_once", no_synthesis)

    r = client.post("/v3/chat/stream", json={"message": "un hôtel près de Gare du Nord demain"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    expected = templates.clarification_response(clarification, "fr")

    assert kinds[0] == "progress"
    assert kinds[-1] == "done"
    assert "token" in kinds and kinds.index("progress") < kinds.index("token")
    streamed = "".join(d["text"] for e, d in events if e == "token")
    assert streamed.strip() == expected
    done_payload = events[-1][1]
    assert done_payload["message"].strip() == expected
    assert done_payload["requires_clarification"] is True


def test_sse_hotels_frame_picks_are_this_turns_not_the_previous_turns(monkeypatch, client):
    """The picks on the frame are built from the session profile, so WHEN the
    frame is emitted decides which turn's shortlist they describe. Emitted before
    the turn's `profile_delta` and `record_search_shortlist` are applied, they
    would carry the PREVIOUS turn's hotels — i.e. this turn's cards would get
    booking CTAs pointing at the hotels of the search before it. Two turns, two
    cities: the second frame must know nothing about the first."""
    turns = iter([
        ("Paris", {"id": 101, "name": "Hotel Paris", "country_code": "FR"}),
        ("Lyon", {"id": 202, "name": "Hotel Lyon", "country_code": "FR"}),
    ])
    seen: list[dict] = []

    async def fake_classify(message, budget, invocation_id="", *, recent_messages=None, previous_question=None):
        budget.charge("triage")
        return Triage("search", "fr", used_llm=False)

    async def fake_run_leaf(leaf, ctx, profile_in, **kwargs):
        city, hotel = next(turns)
        return (f"Des hôtels à {city}.", {"results": [hotel], "profile_delta": {"city": city}})

    async def fake_generate_once(self, **kwargs):
        return "Voici."

    monkeypatch.setattr(agent_module, "classify", fake_classify)
    monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
    monkeypatch.setattr(agent_module._B2cConcierge, "_generate_once", fake_generate_once)

    for message in ("un hôtel à Paris", "et à Lyon ?"):
        r = client.post("/v3/chat/stream", json={"message": message})
        assert r.status_code == 200
        events = _parse_sse(r.text)
        seen.append({
            "frame": next(d for e, d in events if e == "hotels")["hotel_picks"],
            "done": events[-1][1]["hotel_picks"],
        })

    assert [p["hotel_id"] for p in seen[0]["frame"]] == [101]
    assert [p["hotel_id"] for p in seen[1]["frame"]] == [202]  # NOT 101
    # And each frame still agrees with its own turn's payload.
    assert seen[0]["frame"] == seen[0]["done"]
    assert seen[1]["frame"] == seen[1]["done"]


# --- last-resort shield (S-CX1) ---------------------------------------------------------------
# An unexpected exception escaping the spine's inner nets must NEVER surface as
# a bare Starlette 500 (JSON) or a dead stream with no terminal frame (SSE) —
# the widget always gets the iso-contract shape with an honest degraded message.
def test_unexpected_crash_returns_contract_payload_not_500(monkeypatch, client):
    async def crash(session_id, user_id, message):
        raise RuntimeError("boom")
        yield  # pragma: no cover — async-generator shape

    monkeypatch.setattr(facade_module, "_drive", crash)
    r = client.post("/v3/chat", json={"message": "hotel in Paris please"})
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == set(CONTRACT_KEYS)
    assert data["message"] == templates.service_degraded_response("en")
    assert data["hotels"] is None
    assert data["ready_to_search"] is False
    assert "du_chat_sid=" in r.headers.get("set-cookie", "")


def test_shield_message_is_localized_from_locale(monkeypatch, client):
    async def crash(session_id, user_id, message):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(facade_module, "_drive", crash)
    r = client.post("/v3/chat", json={"message": "hotel", "locale": "fr-FR"})
    assert r.json()["message"] == templates.service_degraded_response("fr")
    assert r.json()["response_language"] == "fr"


def test_shield_now_supported_locale_answers_in_that_language(monkeypatch, client):
    """UX2 (2026-08-27): templates.py now has all 7 recognized languages, so a
    DECLARED "es" locale is served in Spanish — even when the message text
    would trip guess_language's French hints (es/it/pt share them)."""
    async def crash(session_id, user_id, message):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(facade_module, "_drive", crash)
    r = client.post("/v3/chat", json={"message": "hôtel à Paris", "locale": "es-ES"})
    assert r.json()["message"] == templates.service_degraded_response("es")
    assert r.json()["response_language"] == "es"


def test_shield_unsupported_locale_answers_english(monkeypatch, client):
    """Customers span many languages but templates exist for the 7 triage
    recognizes: a DECLARED locale outside that set still answers in English."""
    async def crash(session_id, user_id, message):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(facade_module, "_drive", crash)
    r = client.post("/v3/chat", json={"message": "hôtel à Paris", "locale": "ja-JP"})
    assert r.json()["message"] == templates.service_degraded_response("en")
    assert r.json()["response_language"] == "en"


def test_sse_midstream_crash_still_ends_with_done(monkeypatch, client):
    """Once the 200 + event-stream headers are committed, a degraded `done` is
    the only terminal signal the widget can act on — the stream must never just
    die (pre-S-CX1 behavior: truncated stream, no `done`, no `error` frame)."""
    async def crash_mid(session_id, user_id, message):
        yield "progress", {}
        yield "token", "Je regarde ce qui est dispo"
        raise RuntimeError("boom mid-stream")

    monkeypatch.setattr(facade_module, "_drive", crash_mid)
    r = client.post("/v3/chat/stream", json={"message": "un hôtel à Paris", "locale": "fr-FR"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "progress"
    assert kinds[-1] == "done"
    done = events[-1][1]
    assert set(done.keys()) == set(CONTRACT_KEYS)
    assert done["message"] == templates.service_degraded_response("fr")
    assert done["hotels"] is None


def test_sse_setup_crash_still_streams_progress_and_done(monkeypatch, client):
    """A failure BEFORE the stream opens (session backend down) must still
    serve an event-stream ending in `done`, not a 500 body an EventSource
    can't parse."""
    async def broken_session(session_id, user_id):
        raise RuntimeError("session backend down")

    monkeypatch.setattr(facade_module, "_get_or_create_session", broken_session)
    r = client.post("/v3/chat/stream", json={"message": "hello"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    assert [e for e, _ in events] == ["progress", "done"]
    assert set(events[-1][1].keys()) == set(CONTRACT_KEYS)


def test_shield_survives_profile_store_failure(monkeypatch, client):
    """The shield payload is built from PURE inputs — it must hold even when
    Redis itself is what crashed the turn (here: _finalize's profile read)."""
    async def ok_drive(session_id, user_id, message):
        yield "final", "tout va bien"

    class _BrokenStore:
        async def get(self, session_id):
            raise ConnectionError("redis down hard")

    monkeypatch.setattr(facade_module, "_drive", ok_drive)
    monkeypatch.setattr(facade_module, "get_profile_store", lambda: _BrokenStore())
    r = client.post("/v3/chat", json={"message": "hello"})
    assert r.status_code == 200
    assert r.json()["message"] == templates.service_degraded_response("en")


def test_json_and_stream_agree_on_the_same_turn(monkeypatch, client):
    """The non-streamed payload must equal the SSE `done` payload (bar the
    per-turn turn_id) for the same input — one turn logic, two encodings."""
    async def fake_classify(message, budget, invocation_id="", *, recent_messages=None, previous_question=None):
        budget.charge("triage")
        return Triage("search", "fr", used_llm=False)

    async def fake_run_leaf(leaf, ctx, profile_in, **kwargs):
        return ("ok", {"results": [{"id": 1, "name": "Hotel A", "country_code": "FR"}]})

    async def fake_generate_once(self, **kwargs):
        return "Une réponse."

    monkeypatch.setattr(agent_module, "classify", fake_classify)
    monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
    monkeypatch.setattr(agent_module._B2cConcierge, "_generate_once", fake_generate_once)

    json_resp = client.post(
        "/v3/chat", json={"message": "hôtel"}, headers={"X-Client-Session-Id": "cmp-json"}
    ).json()
    stream_events = _parse_sse(
        client.post(
            "/v3/chat/stream", json={"message": "hôtel"}, headers={"X-Client-Session-Id": "cmp-sse"}
        ).text
    )
    done = stream_events[-1][1]
    for key in CONTRACT_KEYS:
        if key in ("turn_id", "session_id", "conversation_id"):
            continue
        assert json_resp[key] == done[key], key


# --- mcp-dayuse#6: an expired profile is said, not silently reset ----------------------------
def _expire(store, session_id):
    import asyncio

    asyncio.run(store.delete(session_id))


def test_a_greeting_turn_keeps_the_profile_alive(client, store):
    import asyncio

    client.post("/v3/chat", json={"message": "Bonjour !"}, headers={"X-Client-Session-Id": "alive-1"})
    assert asyncio.run(store.exists("alive-1")) is True


def test_an_expired_profile_mid_conversation_is_announced(client, store):
    headers = {"X-Client-Session-Id": "expired-1"}
    first = client.post("/v3/chat", json={"message": "Bonjour !"}, headers=headers).json()
    assert first["session_expired"] is False
    _expire(store, "expired-1")  # the 30 min Redis TTL ran out

    second = client.post("/v3/chat", json={"message": "Merci !"}, headers=headers).json()

    assert second["session_expired"] is True
    notice = templates.session_expired_notice("fr", 30)
    assert second["message"] == f"{notice}\n\n{templates.ack_response('fr')}"
    third = client.post("/v3/chat", json={"message": "Merci !"}, headers=headers).json()
    assert third["session_expired"] is False


def test_the_stream_done_frame_carries_the_expiry(client, store):
    headers = {"X-Client-Session-Id": "expired-2"}
    client.post("/v3/chat", json={"message": "Bonjour !"}, headers=headers)
    _expire(store, "expired-2")

    r = client.post("/v3/chat/stream", json={"message": "Bonjour !"}, headers=headers)
    done = [json.loads(b.split("data: ", 1)[1]) for b in r.text.split("\n\n") if b.startswith("event: done")]

    assert done[-1]["session_expired"] is True
    assert done[-1]["message"].startswith(templates.session_expired_notice("fr", 30))


def test_a_redis_outage_is_not_an_expiry(monkeypatch, client, store):
    headers = {"X-Client-Session-Id": "outage-1"}
    client.post("/v3/chat", json={"message": "Bonjour !"}, headers=headers)

    async def _down(session_id):
        return None

    monkeypatch.setattr(store, "exists", _down)
    second = client.post("/v3/chat", json={"message": "Merci !"}, headers=headers).json()
    assert second["session_expired"] is False


# --- turn_facts: what the widget's analytics event copies -------------------------------------
def test_json_turn_carries_the_spines_turn_facts(client):
    facts = client.post("/v3/chat", json={"message": "Bonjour !"}).json()["turn_facts"]
    assert facts == {
        "trace_id": None,
        "family": "ack",
        "route": "template:ack",
        "status": "ok",
        "response_type": "answer",
        "results_count": 0,
        "empty_reason": "none",
        "clarification_reason": "none",
        "guards_fired": [],
        "fallbacks": [],
        "resolved_city": None,
    }


def test_stream_turn_facts_ride_done_and_no_frame_of_their_own(monkeypatch, client):
    async def fake_classify(message, budget, invocation_id="", *, recent_messages=None, previous_question=None):
        budget.charge("triage")
        return Triage("search", "fr", used_llm=False)

    async def fake_run_leaf(leaf, ctx, profile_in, **kwargs):
        return ("ok", {"results": [{"id": 1, "name": "Hotel A"}], "profile_delta": {"city": "Nantes"}})

    async def fake_generate_once(self, **kwargs):
        return "Une réponse."

    monkeypatch.setattr(agent_module, "classify", fake_classify)
    monkeypatch.setattr(agent_module, "_run_leaf", fake_run_leaf)
    monkeypatch.setattr(agent_module._B2cConcierge, "_generate_once", fake_generate_once)

    events = _parse_sse(client.post("/v3/chat/stream", json={"message": "un hôtel"}).text)
    names = [e for e, _ in events]
    assert set(names) == {"progress", "hotels", "token", "done"}
    # One `progress` opens the stream (TTFT), one follows the leaf (the widget
    # proxy's 60 s silence window); turn_facts add no frame of their own.
    assert names[:3] == ["progress", "progress", "hotels"]
    assert names.count("progress") == 2
    facts = events[-1][1]["turn_facts"]
    assert facts["route"] == "leaf:hotel_search"
    assert facts["response_type"] == "results"
    assert facts["results_count"] == 1
    assert facts["resolved_city"] == "Nantes"


def test_empty_message_turn_facts_name_the_empty_ack(client):
    facts = client.post("/v3/chat", json={"message": "  "}).json()["turn_facts"]
    assert (facts["family"], facts["route"], facts["status"]) == ("ack", "template:empty_ack", "ok")


def test_shield_turn_facts_report_an_error(monkeypatch, client):
    async def crash(session_id, user_id, message):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(facade_module, "_drive", crash)
    facts = client.post("/v3/chat", json={"message": "hôtel"}).json()["turn_facts"]
    assert facts["family"] == "unknown"
    assert facts["route"] == "facade_shield"
    assert facts["status"] == "degraded"
    assert facts["empty_reason"] == "error"
    assert facts["trace_id"] is None


def test_sse_setup_crash_turn_facts_report_an_error(monkeypatch, client):
    async def broken_session(session_id, user_id):
        raise RuntimeError("session backend down")

    monkeypatch.setattr(facade_module, "_get_or_create_session", broken_session)
    events = _parse_sse(client.post("/v3/chat/stream", json={"message": "hello"}).text)
    facts = events[-1][1]["turn_facts"]
    assert (facts["route"], facts["status"], facts["trace_id"]) == ("facade_shield", "degraded", None)


def test_a_spine_turn_without_a_marker_is_reported_unknown_and_warned(monkeypatch, client, caplog):
    async def markerless_drive(session_id, user_id, message):
        yield "final", "Une réponse."

    monkeypatch.setattr(facade_module, "_drive", markerless_drive)
    message = "un hôtel secret"
    with caplog.at_level(logging.WARNING, logger="b2c_concierge.facade"):
        facts = client.post("/v3/chat", json={"message": message}).json()["turn_facts"]
    assert facts["status"] == "unknown"
    warnings = [r.getMessage() for r in caplog.records if r.name == "b2c_concierge.facade"]
    assert any("turn_facts" in w for w in warnings)
    assert not any(message in w for w in warnings)


def test_a_markerless_stream_turn_is_reported_unknown(monkeypatch, client):
    async def markerless_drive(session_id, user_id, message):
        yield "final", "Une réponse."

    monkeypatch.setattr(facade_module, "_drive", markerless_drive)
    events = _parse_sse(client.post("/v3/chat/stream", json={"message": "un hôtel"}).text)
    assert events[-1][1]["turn_facts"]["status"] == "unknown"


def test_the_empty_message_turn_is_not_unknown(client, caplog):
    with caplog.at_level(logging.WARNING, logger="b2c_concierge.facade"):
        facts = client.post("/v3/chat", json={"message": "  "}).json()["turn_facts"]
    assert facts["status"] == "ok"
    assert not [r for r in caplog.records if r.name == "b2c_concierge.facade"]


def test_a_valid_client_turn_id_is_echoed(client):
    turn_id = "8f14e45f-ceea-467a-9575-0f1a2b3c4d5e_t3"
    body = {"message": "Bonjour !", "turn_id": turn_id}
    assert client.post("/v3/chat", json=body).json()["turn_id"] == turn_id
    events = _parse_sse(client.post("/v3/chat/stream", json=body).text)
    assert events[-1][1]["turn_id"] == turn_id


def test_the_shield_echoes_the_client_turn_id(monkeypatch, client):
    async def crash(session_id, user_id, message):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(facade_module, "_drive", crash)
    r = client.post("/v3/chat", json={"message": "hôtel", "turn_id": "abc_t1"})
    assert r.json()["turn_id"] == "abc_t1"


@pytest.mark.parametrize("turn_id", ["", "has space", "x" * 129, 42, None, "<script>"])
def test_an_invalid_client_turn_id_is_replaced(client, turn_id):
    sent = client.post("/v3/chat", json={"message": "Bonjour !", "turn_id": turn_id}).json()["turn_id"]
    assert sent != turn_id
    assert re.fullmatch(r"[0-9a-f]{32}", sent)
