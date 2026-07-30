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
import math
import os
import re
import time
import uuid
from typing import Any, AsyncGenerator, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from b2c_common.observability import mark_level, mark_metadata, turn_observation
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from dayuse_agent_common import enqueue_metric_event

from . import conversation_log, templates
from .agent import _US, metrics_logger, root_agent
from .conversation_log import build_conversation_log_row, detect_is_synthetic
from .inline_tools import _format_price_eur_cents
from .profile import SessionProfile, apply_profile_delta, build_hotel_picks
from .profile_store import get_profile_store
from .triage import SERVICE, guess_language
from .triage import locale_response_language as _locale_response_language

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
        "hotel_picks",
        "booking_card",
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
    - a marker (`\\x1f{...}`) → ("progress", None) / ("hotels", full marker
      payload dict — carries `hotels` plus per-turn flags like
      `requires_clarification`, S-G10)
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
            return ("hotels", payload)
        if payload.get("event") == "booking":
            return ("booking", payload)
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
    resolution pipeline, so those keys are simply absent rather than faked).

    S-G1 (2026-07-23): `named_hotel`/`date_reference`/`zone`/`currency`/
    `distance_origin` are no longer hardcoded null — the profile schema now
    has a field for each (still legitimately None until a leaf actually
    populates them — S-G3/S-G5/S-G6/S-G7 — this only stops FAKING absence
    when the profile does hold a value). These keys live INSIDE
    `active_filters` only; `CONTRACT_KEYS` (the top-level response shape) is
    untouched — iso-contract.

    S-G2 (2026-07-23): `locale`/`domain`/`search_anchor` join the same
    pattern — the facade is now their producer (native-context intake), so
    they follow `currency`/`zone`/etc. in being surfaced instead of omitted.

    S-G6 (2026-07-23): `date` (the resolved ISO date) joins `date_reference` —
    previously ONLY `date_reference` was exposed, so a live/eval check reading
    the resolved calendar date (`scripts/eval_hardening.py::check_date_reference`)
    could never find it. `client_timezone` is surfaced too, same pattern."""
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
        "named_hotel": profile.named_hotel,
        "date": profile.date,
        "date_reference": profile.date_reference,
        "zone": profile.zone,
        "currency": profile.currency,
        "distance_origin": profile.distance_origin,
        "locale": profile.locale,
        "domain": profile.domain,
        "search_anchor": profile.search_anchor,
        "client_timezone": profile.client_timezone,
    }


def _iso_alpha2(value: Any) -> str | None:
    """ISO alpha-2 country code or None. The widget's market table is ISO-keyed:
    a full country name uppercased into a pseudo-code ("FRANCE") is strictly
    worse than None (None lets the widget fall back to its entry market)."""
    if isinstance(value, str):
        candidate = value.strip()
        if len(candidate) == 2 and candidate.isalpha():
            return candidate.upper()
    return None


def _infer_market_country(hotels: list | None, profile: SessionProfile) -> str | None:
    for hotel in hotels or []:
        if not isinstance(hotel, dict):
            continue
        code = _iso_alpha2(hotel.get("country_code")) or _iso_alpha2(hotel.get("country"))
        if code:
            return code
    return _iso_alpha2(profile.country_anchor)


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
    requires_clarification: bool = False,
    booking_card: dict | None = None,
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
    - requires_clarification: True ONLY when the search leaf reported a
      geocode homonym clarify THIS turn (deterministic signal from the leaf's
      DataPart, S-G10) — the spine still never BLOCKS on a clarification
      stage, this is honest reporting so the harness can credit a safe
      clarifying question instead of scoring it as a hard failure;
    - state/profile_status/market: honest defaults/derivations for concepts the
      spine does not model (documented per field)."""
    hotels_norm = normalize_hotels(hotels) if hotels else None
    market_country = _infer_market_country(hotels_norm, profile)
    payload: dict[str, Any] = {
        "message": final_text,
        "response": final_text,
        "context": final_text,
        "hotels": hotels_norm,
        # S-CX5: the pick buttons (cheapest first) and, on the turn a hotel was
        # chosen, the offer card carrying the tunnel link. Both absent-by-empty
        # rather than absent-by-key: the contract shape stays stable.
        "hotel_picks": build_hotel_picks(profile),
        "booking_card": booking_card,
        "suggestions": list(profile.last_suggestions or []),
        "session_id": session_id,
        "conversation_id": session_id,
        "response_language": language,
        "state": "responding",
        "ready_to_search": hotels_norm is not None,
        "requires_clarification": requires_clarification,
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
    is_synthetic: bool, turn_index: int, requires_clarification: bool = False,
    booking_card: dict | None = None,
) -> dict[str, Any]:
    """Build the payload from the post-turn profile and persist the conversation
    log (best-effort). Returns the payload."""
    profile = await get_profile_store().get(session_id)
    language = (
        profile.language or _locale_response_language(profile.locale) or guess_language(message)
    )
    payload = build_chat_payload(
        session_id=session_id, final_text=final_text, hotels=hotels,
        profile=profile, language=language, turn_id=uuid.uuid4().hex,
        requires_clarification=requires_clarification, booking_card=booking_card,
    )
    row = build_conversation_log_row(
        session_id=session_id, turn_index=turn_index, user_message=message,
        assistant_message=final_text, hotels=payload["hotels"],
        active_filters=payload["active_filters"], response_language=language,
        is_synthetic=is_synthetic,
    )
    await conversation_log.persist_conversation_log(row)
    return payload


def _parse_picked_hotel_id(body: dict[str, Any]) -> int | None:
    """S-CX5: `hotel_id` in the request body — a pick BUTTON was clicked. The
    button also sends its label as the user's message (so the transcript reads
    naturally), but the hotel is resolved from THIS id, never by matching that
    text: two hotels of the same chain in one shortlist would otherwise be a
    coin flip. Anything unparsable is ignored, exactly like the other
    native-context fields."""
    raw = body.get("hotel_id")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def _read_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — a missing/invalid body is just an empty request
        return {}
    return body if isinstance(body, dict) else {}


# --- native context intake (S-G2, 2026-07-23) ------------------------------------------------
# Probed against the vendored widget (web/vendor/static/js/chat/) BEFORE writing any of this —
# the real POST /v3/chat body is the spec, not the phase brief's original assumption. Verified
# (handlers/send.js:298-362, filters/search.js:98-127, utils.js:17-40):
#   - `locale`/`currency` are top-level string fields (state.marketContext.language/.currency),
#     NOT nested under `native_context`.
#   - GPS is `client_geo_context.device.{latitude, longitude, accuracy_m, permission}` — sent
#     ONLY when the message explicitly asks for device location AND geolocation succeeded
#     (handlers/send.js:266-292); `permission` is "granted"/"denied"/"unavailable", lat/lon
#     present only when "granted".
#   - `native_context` (the mobile app's `window.__DAYUSE_NATIVE__`) is an OPAQUE blob: its own
#     comment (utils.js:12-15) says it carries "recent bookings, favourites, geolocation" but no
#     field name/shape is defined anywhere in this vendored snapshot. Inventing a
#     `native_context.geolocation` sub-shape (the brief's original assumption) would be coding
#     against a guess with zero evidence — NOT done here. `native_context` never errors the
#     request; it is simply not decoded. Open item for whenever the mobile schema is specified.
#   - `domain` is NOT actually sent in the body by this widget (baked server-side into an HTML
#     `<meta>` tag, never echoed back) — parsed here defensively/for forward-compat, not
#     exercised by the real traffic this probe captured.
#   - `client_local_time`/`client_timezone` ARE sent (confirmed, `getClientTimeContext()`).
#     S-G6 (2026-07-23) decided `client_timezone`'s home: a dedicated, carryover profile field
#     (`SessionProfile.client_timezone`) — parsed/validated here exactly like locale/currency,
#     so it reaches the leaf via `profile_in` from turn 1, before any date has ever been
#     resolved. `client_local_time` (the raw per-request instant) stays deliberately UNUSED: a
#     device clock can be wrong, and the server's own clock plus a validated IANA timezone is a
#     safer, simpler "now" anchor for date-label resolution than trusting the client's literal
#     reading — see hotel_search_agent.datetime_resolver.reference_today.
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


def _parse_locale(raw: Any) -> str | None:
    if isinstance(raw, str) and _LOCALE_RE.fullmatch(raw.strip()):
        return raw.strip()
    return None


def _parse_currency(raw: Any) -> str | None:
    if isinstance(raw, str) and _CURRENCY_RE.fullmatch(raw.strip()):
        return raw.strip().upper()
    return None


def _parse_domain(raw: Any) -> str | None:
    if isinstance(raw, str) and _DOMAIN_RE.fullmatch(raw.strip()):
        return raw.strip().lower()
    return None


def _parse_client_timezone(raw: Any) -> str | None:
    """A valid IANA timezone name (e.g. "Europe/Paris"), else None — an
    invalid/garbage value is dropped silently (absent from the delta =
    carryover), never persisted as a broken anchor for date resolution."""
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return candidate


# `_locale_response_language` moved to triage.locale_response_language (S-CX2:
# the spine's template paths need the same locale→fr/en mapping as this facade)
# — imported under its historical local name above.


def _parse_gps_anchor(body: dict[str, Any], turn_index: int) -> dict[str, Any] | None:
    """`search_anchor` sourced from `client_geo_context.device` — ONLY when
    the browser granted a fresh fix THIS turn (`permission == "granted"` and
    both coordinates present and in-range). Anything else (denied/
    unavailable/absent/malformed) returns None so the caller omits the delta
    key entirely — absent-from-delta is carryover under the typed-ops
    reducer (profile.py), which IS the no-silent-downgrade rule: a
    permission blip on turn N never erases a fix acquired on an earlier
    turn, and a turn with no location signal at all never invents one."""
    ctx = body.get("client_geo_context")
    if not isinstance(ctx, dict):
        return None
    device = ctx.get("device")
    if not isinstance(device, dict) or device.get("permission") != "granted":
        return None
    lat, lon = device.get("latitude"), device.get("longitude")
    if isinstance(lat, bool) or not isinstance(lat, (int, float)) or not math.isfinite(lat):
        return None
    if isinstance(lon, bool) or not isinstance(lon, (int, float)) or not math.isfinite(lon):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return {
        "type": "gps",
        "lat": float(lat),
        "lon": float(lon),
        "label": None,
        "set_at_turn": turn_index,
    }


def _native_context_delta(body: dict[str, Any], turn_index: int) -> dict[str, Any]:
    """The profile delta for every optional native-context field this facade
    recognizes in `body` — a field simply absent/invalid here is carryover
    (never a clear), so a request carrying none of this is a full no-op."""
    delta: dict[str, Any] = {}
    locale = _parse_locale(body.get("locale"))
    if locale is not None:
        delta["locale"] = locale
    currency = _parse_currency(body.get("currency"))
    if currency is not None:
        delta["currency"] = currency
    domain = _parse_domain(body.get("domain"))
    if domain is not None:
        delta["domain"] = domain
    anchor = _parse_gps_anchor(body, turn_index)
    if anchor is not None:
        delta["search_anchor"] = anchor
    client_timezone = _parse_client_timezone(body.get("client_timezone"))
    if client_timezone is not None:
        delta["client_timezone"] = client_timezone
    return delta


async def _apply_native_context(session_id: str, body: dict[str, Any], turn_index: int) -> None:
    """Merges this turn's native-context delta into the STORED profile before
    the spine runs, so a leaf reading `profile_in` this same turn already
    sees it (actually USING GPS/locale — Mapbox proximity, response
    generation language, price display — is later phases' job: S-G3/S-G5/
    S-G7; this only makes the signal reach the profile). Zero Redis round-
    trip when the request carries none of these optional fields."""
    delta = _native_context_delta(body, turn_index)
    picked = _parse_picked_hotel_id(body)
    if not delta and picked is None:
        return
    store = get_profile_store()
    profile = await store.get(session_id)
    if delta:
        apply_profile_delta(profile, delta, "")
    # S-CX5: NOT part of the delta reducer — this is one-shot turn state the
    # spine consumes and clears, not a carryover slot.
    profile.picked_hotel_id = picked
    await store.set(session_id, profile)


def _empty_ack_text(message: str, locale: str | None = None) -> str:
    """Empty message → the zero-LLM ack template (no pointless triage call).
    `locale`, when it resolves to a supported response language, beats the
    "en" default `guess_language` falls back to when there is no message
    text to detect a language from at all."""
    return templates.ack_response(_locale_response_language(locale) or guess_language(message))


# --- last-resort shield (S-CX1) --------------------------------------------------------------
def _shield_payload(
    session_id: str, body: dict[str, Any], message: str, path: str, exc: Exception
) -> dict[str, Any]:
    """An unexpected exception escaped every inner degradation net (spine legs
    each catch their own failures — this is the seam around them). Build a full
    iso-contract payload from PURE inputs only: fresh profile, no Redis/DB/ADK
    round-trip — any of those may be exactly what just failed. The widget always
    receives the shape it parses, with an honest localized message instead of a
    bare 500 or a dead SSE stream. Metric is count-only (error type, never
    message content — RGPD)."""
    logger.exception("b2c_concierge: facade shield caught an unhandled error on %s", path)
    metrics_logger.info(
        "concierge_metric=facade_shield path=%s error_type=%s", path, type(exc).__name__
    )
    enqueue_metric_event(
        "facade_shield", service=SERVICE, invocation_id=session_id,
        path=path, error_type=type(exc).__name__,
    )
    # Customers span many countries/languages; templates exist in fr/en only.
    # A DECLARED locale we have no translation for answers in ENGLISH (Fabien,
    # PR #34 review) — never via guess_language, whose French hints can misfire
    # on other Romance languages (es/it/pt). The message-language guess remains
    # only for requests that carry no locale at all.
    locale = _parse_locale(body.get("locale"))
    if locale:
        language = _locale_response_language(locale) or "en"
    else:
        language = guess_language(message)
    return build_chat_payload(
        session_id=session_id,
        final_text=templates.service_degraded_response(language),
        hotels=None, profile=SessionProfile(), language=language,
        turn_id=uuid.uuid4().hex,
    )


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
    try:
        user_id = _user_id(session_id)
        session = await _get_or_create_session(session_id, user_id)
        turn_index = _count_user_turns(session)
        is_synthetic = detect_is_synthetic(request.headers)
        await _apply_native_context(session_id, body, turn_index)

        # Langfuse audit trace for the turn (no-op without LANGFUSE_* keys).
        # Content goes ONLY to the self-hosted EU Langfuse — the metric events
        # and b2c_concierge.* logs below stay content-free (GDPR locks).
        with turn_observation(
            name="v3.chat", session_id=session_id, user_id=user_id, message=message,
            is_synthetic=is_synthetic,
            metadata={"turn_index": turn_index, "locale": body.get("locale"),
                      "currency": body.get("currency"), "domain": body.get("domain")},
        ) as lf_span:
            hotels: list | None = None
            booking_card: dict | None = None
            requires_clarification = False
            final_text = ""
            try:
                if not message:
                    final_text = _empty_ack_text(message, _parse_locale(body.get("locale")))
                else:
                    async for kind, data in _drive(session_id, user_id, message):
                        if kind == "hotels":
                            hotels = data.get("hotels") or None
                            requires_clarification = bool(data.get("requires_clarification"))
                        elif kind == "booking":
                            booking_card = data.get("booking_card") or None
                        elif kind == "final":
                            final_text = data

                payload = await _finalize(
                    session_id=session_id, message=message, final_text=final_text,
                    hotels=hotels, is_synthetic=is_synthetic, turn_index=turn_index,
                    requires_clarification=requires_clarification, booking_card=booking_card,
                )
                if lf_span is not None:
                    lf_span.update(output=final_text)
            except Exception:
                # OBS2: mark ERROR while the span is still open — by the time
                # the outer except (below) runs, `with turn_observation` has
                # already exited and closed it.
                mark_level("ERROR", status_message="facade_shield")
                raise
    except Exception as exc:  # noqa: BLE001 — last-resort shield: contract payload, never a bare 500
        payload = _shield_payload(session_id, body, message, "json", exc)
    response = JSONResponse(payload)
    _set_session_cookie(response, session_id)
    return response


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _sse_response(body: AsyncGenerator[bytes, None], session_id: str) -> StreamingResponse:
    response = StreamingResponse(body, media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # let SSE flush past reverse proxies
    _set_session_cookie(response, session_id)
    return response


async def chat_stream(request: Request) -> Response:
    """POST /v3/chat/stream — SSE: `progress` (immediate, the TTFT marker) →
    `hotels` → token chunks → `done` (the full iso-contract payload). The
    non-streamed /v3/chat above serves the exact same payload in one shot.
    The stream ALWAYS ends with a `done` frame (S-CX1): once the 200 +
    event-stream headers are committed, a mid-stream failure can no longer
    change the status — a degraded `done` is the only honest terminal signal
    the widget can act on (no separate `error` frame: zero widget change)."""
    t_request_start = time.monotonic()
    auth = _api_key_error(request)
    if auth is not None:
        return auth
    body = await _read_body(request)
    try:
        session_id = _resolve_session_id(request, body)
    except _InvalidSession:
        return JSONResponse({"error": "Invalid session_id"}, status_code=400)

    message = str(body.get("message") or "").strip()
    try:
        user_id = _user_id(session_id)
        session = await _get_or_create_session(session_id, user_id)
        turn_index = _count_user_turns(session)
        is_synthetic = detect_is_synthetic(request.headers)
        await _apply_native_context(session_id, body, turn_index)
    except Exception as exc:  # noqa: BLE001 — setup failed before the stream opened: still stream a terminal done
        crash_payload = _shield_payload(session_id, body, message, "sse_setup", exc)

        async def _crash_body() -> AsyncGenerator[bytes, None]:
            yield _sse("progress", {})
            yield _sse("done", crash_payload)

        return _sse_response(_crash_body(), session_id)

    async def _body() -> AsyncGenerator[bytes, None]:
        hotels: list | None = None
        booking_card: dict | None = None
        requires_clarification = False
        final_text = ""
        try:
            # Langfuse audit trace for the turn (no-op without LANGFUSE_* keys):
            # span open + updates are local, export is a background batch — the
            # `progress` frame (TTFT marker) still fires before any LLM work.
            with turn_observation(
                name="v3.chat_stream", session_id=session_id, user_id=user_id, message=message,
                is_synthetic=is_synthetic,
                metadata={"turn_index": turn_index, "locale": body.get("locale"),
                          "currency": body.get("currency"), "domain": body.get("domain")},
            ) as lf_span:
                try:
                    if not message:
                        yield _sse("progress", {})
                        # OBS2: TTFT measurement point (CLAUDE.md SLO: progress < 300 ms).
                        # No score yet (OBS3 wires the score mechanism) — metadata for now.
                        mark_metadata(
                            {"ttft_ms": round((time.monotonic() - t_request_start) * 1000, 1)}
                        )
                        final_text = _empty_ack_text(message, _parse_locale(body.get("locale")))
                    else:
                        async for kind, data in _drive(session_id, user_id, message):
                            if kind == "progress":
                                yield _sse("progress", {})
                                mark_metadata(
                                    {"ttft_ms": round((time.monotonic() - t_request_start) * 1000, 1)}
                                )
                            elif kind == "hotels":
                                hotels = data.get("hotels") or None
                                requires_clarification = bool(data.get("requires_clarification"))
                                # `requires_clarification`, `response_language` and
                                # `hotel_picks` ride the frame (additive) so a
                                # hotels-first client decides whether to paint the
                                # shortlist — in WHICH language, and with WHICH cards
                                # bookable — from the same inputs the `done` payload
                                # carries. Without them a streaming widget shows a
                                # shortlist a clarifying turn withholds, in the page's
                                # boot language, with no booking CTA (S-CX9 gates that
                                # CTA on `hotel_picks`, which used to reach the widget
                                # only in the blocking JSON body).
                                yield _sse("hotels", {
                                    "hotels": normalize_hotels(hotels) if hotels else [],
                                    "requires_clarification": requires_clarification,
                                    "response_language": data.get("response_language") or "",
                                    "hotel_picks": data.get("hotel_picks") or [],
                                })
                            elif kind == "booking":
                                booking_card = data.get("booking_card") or None
                                yield _sse("booking_card", {"booking_card": booking_card})
                            elif kind == "token":
                                yield _sse("token", {"text": data})
                            elif kind == "final":
                                final_text = data
                    payload = await _finalize(
                        session_id=session_id, message=message, final_text=final_text,
                        hotels=hotels, is_synthetic=is_synthetic, turn_index=turn_index,
                        requires_clarification=requires_clarification, booking_card=booking_card,
                    )
                    if lf_span is not None:
                        lf_span.update(output=final_text)
                except Exception:
                    # OBS2: mark ERROR while the span is still open — by the time
                    # the outer except (below) runs, `with turn_observation` has
                    # already exited and closed it.
                    mark_level("ERROR", status_message="facade_shield")
                    raise
        except Exception as exc:  # noqa: BLE001 — mid-stream shield: status is committed, only `done` can signal
            payload = _shield_payload(session_id, body, message, "sse_stream", exc)
        yield _sse("done", payload)

    return _sse_response(_body(), session_id)


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
