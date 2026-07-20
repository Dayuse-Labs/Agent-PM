"""facade.py — public iso-contract HTTP facade of the b2c-concierge (S09).

`POST /v3/chat` (JSON) + `POST /v3/chat/stream` (SSE) + `POST /v3/chat/session/reset`,
mounted on the same Starlette app as the A2A surface (serve.py), but under a
DIFFERENT identity regime: the A2A routes keep the D7 bearer (agent↔agent on the
private network); these /v3 routes take the phase-minimum internal API key
(`X-Internal-Api-Key`), because their caller is the frontend/BFF replacing
agent-usa, not a peer agent.

WHAT THIS IS — and is NOT. The response is iso-contract with agent-usa's
`/v3/chat` in SHAPE (same keys/types, so the frontend switch is invisible), NOT
in semantics: the B2C spine has no staged intake, no market engine, and answers
only fr/en — so agent-usa's staged-workflow fields are MAPPED from the spine's
real state where an equivalent exists and given honest, documented defaults
where it doesn't (see build_chat_payload). The RGPD/honesty invariant is about
never inventing a hotel/price/policy — these control booleans are not hotel data.

The spine is driven exactly as the S08 battery drives it (an in-process ADK
Runner) — the SAME code path as the A2A surface, so the two entrypoints can
never diverge. Session continuity is by session_id: the ADK session id IS the
facade's session id, so the orchestrator's Redis profile (keyed on
ctx.session.id) carries context across HTTP turns with zero extra plumbing. The
facade itself adds ZERO LLM calls — it only consumes the spine's event stream.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import uuid
from typing import Any, AsyncGenerator, Literal

from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from . import conversation_log, templates
from .agent import _US, root_agent
from .conversation_log import build_conversation_log_row, detect_is_synthetic
from .inline_tools import _format_price_eur_cents
from .profile import SessionProfile
from .profile_store import get_profile_store
from .triage import guess_language

logger = logging.getLogger(__name__)

# session id shape — mirrors agent-usa's SESSION_ID_PATTERN so a cookie/legacy id
# minted by either stack is mutually valid (invisible switch).
SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

# The always-present response keys (the golden contract SHAPE captured from
# agent-usa's response_data + its /v3 tests). Conditional keys agent-usa adds
# only for its staged intake (type/questions/booking_card/location_candidates)
# are intentionally NOT emitted: the B2C spine never sets a structured
# clarification flag (it always attempts an answer or degrades honestly).
CONTRACT_KEYS: frozenset[str] = frozenset(
    {
        "message",
        "response",
        "context",
        "hotels",
        "suggestions",
        "session_id",
        "conversation_id",
        "response_language",
        "state",
        "ready_to_search",
        "requires_clarification",
        "profile_status",
        "active_filters",
        "market",
        "market_country",
        "entry_market_country",
        "search_country",
        "turn_id",
    }
)


# --- runtime config (read per request so tests can set env without re-importing) -------------
def _cookie_name() -> str:
    return os.environ.get("CONCIERGE_SESSION_COOKIE_NAME", "du_chat_sid")


def _cookie_ttl() -> int:
    return int(os.environ.get("CONCIERGE_SESSION_TTL_SECONDS", "3600"))


def _cookie_secure() -> bool:
    return os.environ.get("CONCIERGE_SESSION_COOKIE_SECURE", "true").strip().lower() != "false"


def _cookie_samesite() -> Literal["lax", "strict", "none"]:
    # SameSite is case-insensitive per RFC 6265bis (browsers treat lax==Lax), so
    # the lowercase literal keeps mypy happy and the switch invisible.
    value = os.environ.get("CONCIERGE_SESSION_COOKIE_SAMESITE", "lax").strip().lower()
    if value == "strict":
        return "strict"
    if value == "none":
        return "none"
    return "lax"


def _session_phase() -> str:
    phase = os.environ.get("SESSION_MIGRATION_PHASE", "M1").strip().upper()
    return phase if phase in ("M1", "M2") else "M1"


def _auth_bypass() -> bool:
    return os.environ.get("AUTH_BYPASS", "").strip().lower() == "true"


def _chat_api_key() -> str:
    return os.environ.get("CHAT_API_KEY", "").strip()


def _chat_api_key_header() -> str:
    return os.environ.get("CHAT_API_KEY_HEADER", "X-Internal-Api-Key")


class _InvalidSession(Exception):
    """A supplied legacy session_id failed SESSION_ID_PATTERN (→ HTTP 400)."""


# --- auth (phase minimum: internal API key) -------------------------------------------------
def _api_key_error(request: Request) -> JSONResponse | None:
    """None when the request is authorized; a 401 JSONResponse otherwise.

    The phase takes the MINIMUM internal auth: an API key. Open (no key required)
    when AUTH_BYPASS=true or CHAT_API_KEY is unset — the honest default for local
    dev/tests; a deployment sets CHAT_API_KEY to gate the facade. The D7 A2A
    bearer is a SEPARATE regime (serve.py) and never applies to /v3."""
    if _auth_bypass():
        return None
    key = _chat_api_key()
    if not key:
        return None
    supplied = request.headers.get(_chat_api_key_header()) or ""
    if supplied and hmac.compare_digest(supplied, key):
        return None
    return JSONResponse({"error": "Unauthorized"}, status_code=401)


# --- session resolution (cookie → X-Client-Session-Id → M1 legacy body → new) ---------------
def _valid(session_id: str) -> bool:
    return bool(SESSION_ID_PATTERN.fullmatch(session_id))


def _resolve_session_id(request: Request, body: dict[str, Any]) -> str:
    cookie_sid = (request.cookies.get(_cookie_name()) or "").strip()
    if cookie_sid and _valid(cookie_sid):
        return cookie_sid
    client_sid = (request.headers.get("X-Client-Session-Id") or "").strip()
    if client_sid and _valid(client_sid):
        return client_sid
    legacy = body.get("session_id")
    if _session_phase() == "M1" and legacy is not None:
        legacy = str(legacy).strip()
        if not _valid(legacy):
            raise _InvalidSession()
        return legacy
    return uuid.uuid4().hex


def _resolve_existing_session_id(request: Request, body: dict[str, Any]) -> str | None:
    """Like _resolve_session_id but never mints a new id (reset/GET semantics)."""
    cookie_sid = (request.cookies.get(_cookie_name()) or "").strip()
    if cookie_sid and _valid(cookie_sid):
        return cookie_sid
    client_sid = (request.headers.get("X-Client-Session-Id") or "").strip()
    if client_sid and _valid(client_sid):
        return client_sid
    legacy = body.get("session_id")
    if _session_phase() == "M1" and legacy is not None:
        legacy = str(legacy).strip()
        if not _valid(legacy):
            raise _InvalidSession()
        return legacy
    return None


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=_cookie_name(),
        value=session_id,
        max_age=_cookie_ttl(),
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.set_cookie(
        key=_cookie_name(),
        value="",
        max_age=0,
        expires=0,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        path="/",
    )


# --- in-process ADK runner (lazy singleton, one InMemory session service) -------------------
_runner: InMemoryRunner | None = None


def _get_runner() -> InMemoryRunner:
    global _runner
    if _runner is None:
        _runner = InMemoryRunner(root_agent)
    return _runner


def reset_runner() -> None:
    """Test hook: drop the cached runner so each test gets a fresh in-memory
    session service (no cross-test session leakage)."""
    global _runner
    _runner = None


def _user_id(session_id: str) -> str:
    return f"v3_{session_id}"


async def _get_or_create_session(session_id: str, user_id: str) -> Any:
    runner = _get_runner()
    existing = await runner.session_service.get_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )
    if existing is not None:
        return existing
    return await runner.session_service.create_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )


def _count_user_turns(session: Any) -> int:
    """turn_index for the conversation log = user turns already in this ADK
    session (0 for the first turn), so it lines up with agent-usa's turn_count."""
    return sum(
        1
        for e in (getattr(session, "events", None) or [])
        if e.content and e.content.role == "user"
    )


# --- event-stream parsing (progress / hotels markers, token chunks, final) ------------------
def _parse_event(event: Any) -> tuple[str, Any] | None:
    """Maps one raw ADK event to a facade item, or None if it carries nothing:
    - a marker (`\\x1f{...}`) → ("progress", None) / ("hotels", list)
    - a partial text chunk → ("token", str)
    - the terminal non-partial event → ("final", str)."""
    if not event.content or not event.content.parts:
        return None
    text = "".join(p.text for p in event.content.parts if p.text)
    if not text:
        return None
    if text.startswith(_US):
        try:
            payload = json.loads(text[len(_US):])
        except (ValueError, TypeError):
            return None
        if payload.get("event") == "hotels":
            return ("hotels", payload.get("hotels") or [])
        return ("progress", None)
    if event.partial:
        return ("token", text)
    return ("final", text)


async def _drive(session_id: str, user_id: str, message: str) -> AsyncGenerator[tuple[str, Any], None]:
    """Runs one turn through the spine, yielding parsed items in order. Same ADK
    Runner path the A2A surface and the S08 battery use — never a fork."""
    runner = _get_runner()
    content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=content
    ):
        parsed = _parse_event(event)
        if parsed is not None:
            yield parsed


# --- contract mapping (spine state → v3 payload) --------------------------------------------
def normalize_hotels(hotels: list | None) -> list:
    """JSON-friendly hotel cards for the payload. Price policy is kept consistent
    with S07: a raw `priceEuro` (EUR cents) is formatted to `€X.XX` in place when
    the card doesn't already carry a display `price` (the inline details/compare
    path already formats it; a future structured search leaf might not)."""
    out: list[Any] = []
    for hotel in hotels or []:
        if not isinstance(hotel, dict):
            out.append(hotel)
            continue
        card = dict(hotel)
        if "price" not in card and "priceEuro" in card:
            card["price"] = _format_price_eur_cents(card.get("priceEuro"))
        out.append(card)
    return out


def _synth_timeslot(profile: SessionProfile) -> str | None:
    """Mirror agent-usa: expose a human-readable timeslot even when only a
    one-sided bound is set (the label field is dropped when a range is set)."""
    if profile.timeslot:
        return profile.timeslot
    start, end = profile.timeslot_start, profile.timeslot_end
    if start and end:
        return f"{start}-{end}"
    if start:
        return f"{start}-"
    if end:
        return f"-{end}"
    return None


def build_active_filters(profile: SessionProfile) -> dict[str, Any]:
    """The effective search filters the spine actually knows, under the same key
    names as agent-usa's `_build_active_filters` (subset — the spine has no geo
    resolution pipeline, so those keys are simply absent rather than faked)."""
    return {
        "city": profile.city,
        "resolved_city": profile.city,
        "state": profile.state_anchor,
        "country_code": profile.country_anchor,
        "timeslot": _synth_timeslot(profile),
        "timeslot_start": profile.timeslot_start,
        "timeslot_end": profile.timeslot_end,
        "budget_max": profile.budget_max,
        "amenities": list(profile.amenities or []),
        "named_hotel": None,
        "date_reference": None,
    }


def _infer_market_country(hotels: list | None, profile: SessionProfile) -> str | None:
    for hotel in hotels or []:
        if not isinstance(hotel, dict):
            continue
        code = hotel.get("country_code") or hotel.get("country")
        if isinstance(code, str) and code.strip():
            return code.strip().upper()
    if isinstance(profile.country_anchor, str) and profile.country_anchor.strip():
        return profile.country_anchor.strip().upper()
    return None


def _profile_status(profile: SessionProfile) -> str:
    """Honest derivation (the spine has no staged profile_status enum): 'ready'
    once a destination is known, 'collecting' when some search context exists,
    'empty' otherwise."""
    if profile.city:
        return "ready"
    has_context = any(
        [
            profile.budget_max,
            profile.timeslot,
            profile.timeslot_start,
            profile.timeslot_end,
            profile.amenities,
        ]
    )
    return "collecting" if has_context else "empty"


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize any domain object (TimeSlot/Money/Decimal…) before serialization
    — same coercion the conversation log uses, so neither boundary can 500."""
    return json.loads(
        json.dumps(payload, ensure_ascii=False, default=conversation_log._json_default)
    )


def build_chat_payload(
    *,
    session_id: str,
    final_text: str,
    hotels: list | None,
    profile: SessionProfile,
    language: str,
    turn_id: str,
) -> dict[str, Any]:
    """Assemble the iso-contract v3 payload (pure). Mapping notes:
    - message/response/context: the same synthesized text (response/context are
      agent-usa's legacy frontend aliases);
    - hotels: the shortlist (or None when no lookup produced results — ack/faq/
      degraded);
    - suggestions: the code-owned recovery chips (profile.last_suggestions) when
      a search came back empty, else [];
    - ready_to_search: True iff a lookup produced a hotel list this turn (the
      spine never gates a search behind intake, so this reflects OUTCOME);
    - requires_clarification: always False (the spine attempts an answer or
      degrades honestly — it never blocks on a structured clarification stage);
    - state/profile_status/market: honest defaults/derivations for concepts the
      spine does not model (documented per field)."""
    hotels_norm = normalize_hotels(hotels) if hotels else None
    market_country = _infer_market_country(hotels_norm, profile)
    payload: dict[str, Any] = {
        "message": final_text,
        "response": final_text,
        "context": final_text,
        "hotels": hotels_norm,
        "suggestions": list(profile.last_suggestions or []),
        "session_id": session_id,
        "conversation_id": session_id,
        "response_language": language,
        "state": "responding",
        "ready_to_search": hotels_norm is not None,
        "requires_clarification": False,
        "profile_status": _profile_status(profile),
        "active_filters": build_active_filters(profile),
        "market": {"country_code": market_country} if market_country else {},
        "market_country": market_country,
        "entry_market_country": market_country,
        "search_country": market_country,
        "turn_id": turn_id,
    }
    return _json_safe(payload)


# --- turn orchestration (shared by JSON + SSE) ----------------------------------------------
async def _finalize(
    *, session_id: str, message: str, final_text: str, hotels: list | None,
    is_synthetic: bool, turn_index: int,
) -> dict[str, Any]:
    """Build the payload from the post-turn profile and persist the conversation
    log (best-effort). Returns the payload."""
    profile = await get_profile_store().get(session_id)
    language = profile.language or guess_language(message)
    payload = build_chat_payload(
        session_id=session_id, final_text=final_text, hotels=hotels,
        profile=profile, language=language, turn_id=uuid.uuid4().hex,
    )
    row = build_conversation_log_row(
        session_id=session_id, turn_index=turn_index, user_message=message,
        assistant_message=final_text, hotels=payload["hotels"],
        active_filters=payload["active_filters"], response_language=language,
        is_synthetic=is_synthetic,
    )
    await conversation_log.persist_conversation_log(row)
    return payload


async def _read_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — a missing/invalid body is just an empty request
        return {}
    return body if isinstance(body, dict) else {}


def _empty_ack_text(message: str) -> str:
    """Empty message → the zero-LLM ack template (no pointless triage call)."""
    return templates.ack_response(guess_language(message))


# --- handlers -------------------------------------------------------------------------------
async def chat(request: Request) -> Response:
    """POST /v3/chat — the non-streamed iso-contract JSON response."""
    auth = _api_key_error(request)
    if auth is not None:
        return auth
    body = await _read_body(request)
    try:
        session_id = _resolve_session_id(request, body)
    except _InvalidSession:
        return JSONResponse({"error": "Invalid session_id"}, status_code=400)

    message = str(body.get("message") or "").strip()
    user_id = _user_id(session_id)
    session = await _get_or_create_session(session_id, user_id)
    turn_index = _count_user_turns(session)
    is_synthetic = detect_is_synthetic(request.headers)

    hotels: list | None = None
    final_text = ""
    if not message:
        final_text = _empty_ack_text(message)
    else:
        async for kind, data in _drive(session_id, user_id, message):
            if kind == "hotels":
                hotels = data or None
            elif kind == "final":
                final_text = data

    payload = await _finalize(
        session_id=session_id, message=message, final_text=final_text,
        hotels=hotels, is_synthetic=is_synthetic, turn_index=turn_index,
    )
    response = JSONResponse(payload)
    _set_session_cookie(response, session_id)
    return response


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def chat_stream(request: Request) -> Response:
    """POST /v3/chat/stream — SSE: `progress` (immediate, the TTFT marker) →
    `hotels` → token chunks → `done` (the full iso-contract payload). The
    non-streamed /v3/chat above serves the exact same payload in one shot."""
    auth = _api_key_error(request)
    if auth is not None:
        return auth
    body = await _read_body(request)
    try:
        session_id = _resolve_session_id(request, body)
    except _InvalidSession:
        return JSONResponse({"error": "Invalid session_id"}, status_code=400)

    message = str(body.get("message") or "").strip()
    user_id = _user_id(session_id)
    session = await _get_or_create_session(session_id, user_id)
    turn_index = _count_user_turns(session)
    is_synthetic = detect_is_synthetic(request.headers)

    async def _body() -> AsyncGenerator[bytes, None]:
        hotels: list | None = None
        final_text = ""
        if not message:
            yield _sse("progress", {})
            final_text = _empty_ack_text(message)
        else:
            async for kind, data in _drive(session_id, user_id, message):
                if kind == "progress":
                    yield _sse("progress", {})
                elif kind == "hotels":
                    hotels = data or None
                    yield _sse("hotels", {"hotels": normalize_hotels(data) if data else []})
                elif kind == "token":
                    yield _sse("token", {"text": data})
                elif kind == "final":
                    final_text = data
        payload = await _finalize(
            session_id=session_id, message=message, final_text=final_text,
            hotels=hotels, is_synthetic=is_synthetic, turn_index=turn_index,
        )
        yield _sse("done", payload)

    response = StreamingResponse(_body(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # let SSE flush past reverse proxies
    _set_session_cookie(response, session_id)
    return response


async def session_reset(request: Request) -> Response:
    """POST /v3/chat/session/reset — drop the server session + profile and clear
    the cookie (204). The next request with no cookie starts a fresh session."""
    auth = _api_key_error(request)
    if auth is not None:
        return auth
    body = await _read_body(request)
    try:
        session_id = _resolve_existing_session_id(request, body)
    except _InvalidSession:
        return JSONResponse({"error": "Invalid session_id"}, status_code=400)

    if session_id:
        runner = _get_runner()
        try:
            await runner.session_service.delete_session(
                app_name=runner.app_name, user_id=_user_id(session_id), session_id=session_id
            )
        except Exception as exc:  # noqa: BLE001 — reset is best-effort, never a 500
            logger.warning("b2c_concierge: reset could not drop ADK session: %s", type(exc).__name__)
        try:
            await get_profile_store().delete(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("b2c_concierge: reset could not drop profile: %s", type(exc).__name__)

    response = Response(status_code=204)
    _clear_session_cookie(response)
    return response


def register_v3_routes(app: Any) -> None:
    """Mount the /v3 facade routes onto the (already-built) Starlette app from
    to_a2a. Called by serve.py, which keeps these routes OUT of the D7 bearer
    gate (they carry their own internal-API-key check)."""
    app.add_route("/v3/chat", chat, methods=["POST"])
    app.add_route("/v3/chat/stream", chat_stream, methods=["POST"])
    app.add_route("/v3/chat/session/reset", session_reset, methods=["POST"])
