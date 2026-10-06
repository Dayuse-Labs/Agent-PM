"""Redis-backed session profile store — orchestrator-only state (decision B3:
the leaves are stateless and never touch Redis; enforced statically by
tests/test_stateless_leaves.py, no `redis` import anywhere under
agents/hotel_search_agent or agents/faq_agent).

One JSON-encoded key per session, sliding TTL refreshed on every write: a
session that goes quiet simply expires (RGPD retention). Async client, kept
consistent with the fully-async spine (agent.py).
"""
from __future__ import annotations

import json
import logging
import os

import redis.asyncio as redis

from .profile import SessionProfile

logger = logging.getLogger(__name__)

_KEY_PREFIX = "b2c_concierge:profile:"
_DEFAULT_TTL_SECONDS = 1800  # 30 min of session inactivity


def _ttl_seconds() -> int:
    return int(os.environ.get("CONCIERGE_PROFILE_TTL_SECONDS", str(_DEFAULT_TTL_SECONDS)))


def _key(session_id: str) -> str:
    return f"{_KEY_PREFIX}{session_id}"


class ProfileStore:
    """One profile per session_id, TTL-bound. Wraps any redis.asyncio.Redis-
    compatible client (a real one in production, fakeredis in tests)."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    async def get(self, session_id: str) -> SessionProfile:
        """A fresh (empty) profile if Redis is unreachable — same honest-
        degradation posture as a leaf leg failure (agent.py): the turn keeps
        going without profile context rather than crashing."""
        try:
            raw = await self._client.get(_key(session_id))
        except Exception as exc:  # noqa: BLE001 — Redis outage must not crash the turn
            logger.warning("b2c_concierge: profile store unreachable (get): %s", exc)
            return SessionProfile()
        if not raw:
            return SessionProfile()
        return SessionProfile.from_dict(json.loads(raw))

    async def set(self, session_id: str, profile: SessionProfile) -> None:
        """No-op (logged) if Redis is unreachable: the turn's answer already
        went out, losing this write only means the NEXT turn starts from a
        stale profile — never a crash."""
        try:
            await self._client.set(_key(session_id), json.dumps(profile.to_dict()), ex=_ttl_seconds())
        except Exception as exc:  # noqa: BLE001 — Redis outage must not crash the turn
            logger.warning("b2c_concierge: profile store unreachable (set), not persisted: %s", exc)

    async def delete(self, session_id: str) -> None:
        """Drop a session's profile (S09 reset). Best-effort like get/set: a
        Redis outage is logged, never raised — reset must never 500."""
        try:
            await self._client.delete(_key(session_id))
        except Exception as exc:  # noqa: BLE001 — Redis outage must not crash reset
            logger.warning("b2c_concierge: profile store unreachable (delete): %s", exc)

    async def close(self) -> None:
        await self._client.aclose()


# Lazily-built, cached per process (mirrors agent.py's `_get_leg` pattern):
# the redis client owns its own connection pool, built once and reused.
_store: ProfileStore | None = None


def get_profile_store() -> ProfileStore:
    global _store
    if _store is None:
        url = os.environ.get("CONCIERGE_REDIS_URL", "redis://localhost:6379/0")
        _store = ProfileStore(redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2, socket_timeout=3,
            health_check_interval=30,
        ))
    return _store


def reset_profile_store() -> None:
    """Test hook: drop the cached store (it captures env at first use)."""
    global _store
    _store = None
