"""Fixtures for the S09 facade suite (offline — no network, no Redis, no API key).

The facade is driven through the REAL composed ASGI app (serve.app) so the D7 /
internal-API-key split and the /v3 routing are exercised as shipped. A fakeredis
ProfileStore is injected into BOTH call sites (agent + facade) so the spine's
post-turn profile is the one the facade reads back — no real Redis required.
"""
from __future__ import annotations

import os

# serve.py reads A2A_BEARER_TOKEN at import (D7 fail-closed) — set it before the
# import below. Cookie set non-secure so it round-trips over http in TestClient.
os.environ["A2A_BEARER_TOKEN"] = "test-token-s9"
os.environ["CONCIERGE_SESSION_COOKIE_SECURE"] = "false"
os.environ.pop("DATABASE_URL", None)

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import b2c_concierge.agent as agent_module  # noqa: E402
import b2c_concierge.conversation_log as conversation_log_module  # noqa: E402
import b2c_concierge.facade as facade_module  # noqa: E402
import b2c_concierge.serve as serve_module  # noqa: E402
from b2c_concierge.profile_store import ProfileStore  # noqa: E402


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Facade OPEN by default (no key, not synthetic, no DB). Auth/synthetic
    tests override these explicitly."""
    monkeypatch.delenv("CHAT_API_KEY", raising=False)
    monkeypatch.delenv("AUTH_BYPASS", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SESSION_MIGRATION_PHASE", "M1")
    monkeypatch.setenv("CONCIERGE_SESSION_COOKIE_SECURE", "false")


@pytest.fixture(autouse=True)
def store(monkeypatch):
    """Shared fakeredis profile store + fresh in-memory ADK runner per test."""
    s = ProfileStore(fakeredis.aioredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(agent_module, "get_profile_store", lambda: s)
    monkeypatch.setattr(facade_module, "get_profile_store", lambda: s)
    facade_module.reset_runner()
    yield s
    facade_module.reset_runner()


@pytest.fixture
def captured_logs(monkeypatch):
    """Capture conversation_log rows instead of persisting them (offline)."""
    rows: list[dict] = []

    async def _capture(row):
        rows.append(row)

    monkeypatch.setattr(conversation_log_module, "persist_conversation_log", _capture)
    return rows


@pytest.fixture
def client():
    with TestClient(serve_module.app) as test_client:
        yield test_client


@pytest.fixture
def fresh_client():
    """Factory for a cookie-isolated client (no shared cookie jar) — for the
    M1 legacy-body-session tests where no cookie must be present."""

    def _make():
        return TestClient(serve_module.app)

    return _make
