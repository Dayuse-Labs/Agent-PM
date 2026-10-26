"""ProfileStore tests — fakeredis stands in for a real Redis (offline, no
broker required to run the suite). Async calls driven via asyncio.run, the
same convention as test_spine.py (no pytest-asyncio dependency)."""
from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from b2c_concierge.profile import SessionProfile
from b2c_concierge.profile_store import ProfileStore, _ttl_seconds

# The store itself is under test: no settled-day seam (root conftest).
pytestmark = pytest.mark.date_unsettled


@pytest.fixture
def store():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return ProfileStore(client)


class TestProfileStore:
    def test_missing_session_returns_a_fresh_profile(self, store):
        profile = asyncio.run(store.get("unknown-session"))
        assert profile == SessionProfile()

    def test_round_trips_a_written_profile(self, store):
        original = SessionProfile(city="Paris", budget_max=150.0, amenities=["pool"])

        async def go():
            await store.set("s1", original)
            return await store.get("s1")

        assert asyncio.run(go()) == original

    def test_two_sessions_are_isolated(self, store):
        async def go():
            await store.set("s1", SessionProfile(city="Paris"))
            await store.set("s2", SessionProfile(city="Lyon"))
            return (await store.get("s1")).city, (await store.get("s2")).city

        assert asyncio.run(go()) == ("Paris", "Lyon")

    def test_write_sets_a_ttl(self, store):
        async def go():
            await store.set("s1", SessionProfile(city="Paris"))
            return await store._client.ttl("b2c_concierge:profile:s1")

        ttl = asyncio.run(go())
        assert 0 < ttl <= _ttl_seconds()

    def test_ttl_env_override(self, store, monkeypatch):
        monkeypatch.setenv("CONCIERGE_PROFILE_TTL_SECONDS", "60")

        async def go():
            await store.set("s1", SessionProfile(city="Paris"))
            return await store._client.ttl("b2c_concierge:profile:s1")

        ttl = asyncio.run(go())
        assert 0 < ttl <= 60


class _DeadClient:
    """Stands in for a redis client whose connection is down — every call
    raises, mirroring a real ConnectionError from redis.asyncio."""

    async def get(self, *args, **kwargs):
        raise ConnectionError("redis unreachable")

    async def set(self, *args, **kwargs):
        raise ConnectionError("redis unreachable")


class TestProfileStoreDegradesHonestlyWhenRedisIsDown:
    def test_get_returns_a_fresh_profile_instead_of_raising(self):
        store = ProfileStore(_DeadClient())
        profile = asyncio.run(store.get("s1"))
        assert profile == SessionProfile()

    def test_set_swallows_the_error_instead_of_raising(self):
        store = ProfileStore(_DeadClient())
        asyncio.run(store.set("s1", SessionProfile(city="Paris")))  # must not raise
