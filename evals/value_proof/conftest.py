"""Shared fixtures for b2c_concierge tests."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

import b2c_concierge.agent as agent_module
from b2c_concierge.profile_store import ProfileStore


@pytest.fixture(autouse=True)
def fake_profile_store(monkeypatch):
    """Every test gets an isolated in-memory profile store (fakeredis) — no
    real Redis required to run the suite offline."""
    store = ProfileStore(fakeredis.aioredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(agent_module, "get_profile_store", lambda: store)
    return store
