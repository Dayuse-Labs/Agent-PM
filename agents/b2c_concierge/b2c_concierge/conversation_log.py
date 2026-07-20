"""conversation_logs persistence for the public /v3 facade (S09).

Mirrors agent-usa's `conversation_logs` columns (src/api/routes/chat.py) and adds
the one column the Dayuse RGPD invariant requires on the LOGS (never on the
metrics): `is_synthetic`, so synthetic traffic (batteries, shadow-run) is
filterable out of any analytics/export. Detection is a single internal header,
`X-Dayuse-Synthetic` — the caller marks its own traffic.

Two intentional distinctions from the metrics channel (dayuse_agent_common.metrics_pg):
- conversation_logs DO carry raw message content (user + assistant text) — that
  is the whole point of the export table, and exactly why it must never be
  confused with the metrics (metrics stay content-free, locked by test). Its
  RGPD control is retention (documented in the concierge README) + is_synthetic,
  not content-stripping.
- best-effort, fire-and-forget, and a complete NO-OP when `DATABASE_URL` is
  unset (same posture as metrics_pg): losing an analytics row must never turn a
  successful chat turn into a 500, and local/CI runs need no Postgres. The live
  Postgres path is therefore exercised only in a deployment with DATABASE_URL
  (S10/S11), like metrics_pg — the pure row builder + header detection below are
  what the offline suite covers.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Truthy values for the synthetic-traffic marker header. A missing/empty/"0"/
# "false" header means real end-user traffic (the safe default: NOT synthetic,
# so nothing is accidentally excluded from analytics).
_SYNTHETIC_HEADER = "x-dayuse-synthetic"
_TRUTHY = {"1", "true", "yes", "on", "synthetic"}


def detect_is_synthetic(headers: Any) -> bool:
    """True when the internal `X-Dayuse-Synthetic` header marks this turn as
    synthetic (battery / shadow-run traffic). `headers` is any case-insensitive
    mapping (Starlette request.headers); the lookup is case-insensitive."""
    try:
        value = headers.get(_SYNTHETIC_HEADER)
    except AttributeError:
        value = None
    return bool(value) and str(value).strip().lower() in _TRUTHY


def _json_default(value: Any) -> Any:
    """Same domain-object coercion agent-usa uses for both the HTTP payload and
    the log row, so a TimeSlot/Money/Decimal in a hotel card can never turn a
    successful turn into a serialization 500."""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return str(value)


def build_conversation_log_row(
    *,
    session_id: str,
    turn_index: int,
    user_message: str,
    assistant_message: str,
    hotels: list | None,
    active_filters: dict,
    response_language: str,
    is_synthetic: bool,
    client_domain: str | None = None,
    detected_market: dict | None = None,
) -> dict[str, Any]:
    """One conversation_logs row (pure — no I/O). jsonb columns are pre-encoded
    to strings here so the persister stays a thin CAST-and-insert. Same column
    set as agent-usa + `is_synthetic`."""
    safe_hotels = hotels if isinstance(hotels, list) else []
    safe_filters = active_filters if isinstance(active_filters, dict) else {}
    return {
        "session_id": session_id,
        "turn_index": int(turn_index),
        "user_message": str(user_message or ""),
        "assistant_message": str(assistant_message or ""),
        "hotels": json.dumps(safe_hotels, ensure_ascii=False, default=_json_default),
        "active_filters": json.dumps(safe_filters, ensure_ascii=False, default=_json_default),
        "response_language": str(response_language or "")[:8] or None,
        "client_domain": (str(client_domain)[:128] if client_domain else None),
        "detected_market": (
            json.dumps(detected_market, ensure_ascii=False, default=_json_default)
            if isinstance(detected_market, dict)
            else None
        ),
        "is_synthetic": bool(is_synthetic),
    }


# --- best-effort Postgres persistence (no-op without DATABASE_URL) ---------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS conversation_logs (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts                TIMESTAMPTZ NOT NULL DEFAULT now(),
  session_id        TEXT NOT NULL,
  turn_index        INTEGER,
  user_message      TEXT,
  assistant_message TEXT,
  hotels            JSONB,
  active_filters    JSONB,
  response_language TEXT,
  client_domain     TEXT,
  detected_market   JSONB,
  is_synthetic      BOOLEAN NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX IF NOT EXISTS conversation_logs_session_turn_idx
  ON conversation_logs (session_id, turn_index) WHERE turn_index IS NOT NULL;
CREATE INDEX IF NOT EXISTS conversation_logs_ts_idx ON conversation_logs (ts DESC);
CREATE INDEX IF NOT EXISTS conversation_logs_synthetic_idx ON conversation_logs (is_synthetic);
"""

_INSERT_SQL = """
INSERT INTO conversation_logs
  (session_id, turn_index, user_message, assistant_message, hotels, active_filters,
   response_language, client_domain, detected_market, is_synthetic)
VALUES (%(session_id)s, %(turn_index)s, %(user_message)s, %(assistant_message)s,
        CAST(%(hotels)s AS jsonb), CAST(%(active_filters)s AS jsonb),
        %(response_language)s, %(client_domain)s, CAST(%(detected_market)s AS jsonb),
        %(is_synthetic)s)
ON CONFLICT DO NOTHING
"""


def _database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def _persist_blocking(row: dict[str, Any]) -> None:
    """Synchronous guarded insert (run off the event loop by the async wrapper).
    One short-lived connection per turn: conversation_logs is low-volume analytics
    off the answer's hot path, so simplicity beats a pooled background writer here
    (metrics, the high-volume channel, keeps its own batched writer)."""
    import psycopg  # imported lazily: never needed when DATABASE_URL is unset
    from psycopg.types.json import Jsonb  # noqa: F401 — imported for parity/availability check

    url = _database_url()
    if not url:
        return
    with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(_DDL)
            cur.execute(_INSERT_SQL, row)


async def persist_conversation_log(row: dict[str, Any]) -> None:
    """Best-effort persist: a complete no-op when DATABASE_URL is unset, and a
    swallowed WARNING on any DB error — a lost analytics row must never break
    the turn (the answer already went out)."""
    if not _database_url():
        return
    import asyncio

    try:
        await asyncio.to_thread(_persist_blocking, row)
    except Exception as exc:  # noqa: BLE001 — analytics persistence must never crash a turn
        logger.warning(
            "b2c_concierge: conversation_log persist failed for session=%s: %s",
            row.get("session_id"),
            type(exc).__name__,
        )
