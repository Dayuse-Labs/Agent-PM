"""Repo-root pytest conftest — offline invariant, enforced.

`import litellm` calls `load_dotenv()` (litellm/__init__.py), so any secret in
the developer's repo-root `.env` silently lands in os.environ of EVERY test
process. With real LANGFUSE_* keys that turned the suite into a live span
exporter (and hung the serve-auth tests on repeated TestClient lifespans).

Neutralize by setting the keys to EMPTY strings before any test module import:
load_dotenv(override=False) never overwrites an existing variable, and
b2c_common.observability treats empty as disabled. Same treatment for any
future opt-in observability key — the suite must stay network-free whatever
the local .env contains.
"""
import os

import pytest

for _key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
    os.environ[_key] = ""

# Same for the prod-parity knobs a local .env carries (per-role models,
# reasoning cap, leaf timeout): the suite asserts the code defaults.
for _key in (
    "DAYUSE_MODEL_TRIAGE",
    "DAYUSE_MODEL_SYNTHESIS",
    "DAYUSE_REASONING_EFFORT",
    "DAYUSE_REASONING_EFFORT_TRIAGE",
    "DAYUSE_REASONING_EFFORT_SYNTHESIS",
    "DAYUSE_REASONING_EFFORT_JUDGE",
    "RELEASE_GATE_JUDGE_MODEL",
    "CONCIERGE_LEAF_TIMEOUT_SECONDS",
):
    os.environ[_key] = ""


@pytest.fixture(autouse=True)
def _search_date_already_settled(request, monkeypatch):
    """2026-10-28: a search with no day says which day it ran on, with the
    day chips, and a place question asks the day too (b2c_concierge agent.py,
    `SessionProfile.date_checked` / `date_announced`). Tests written before
    it drive such a search to test something else, so every session starts
    with its day settled. The day's own tests, and the store's, opt out with
    `@pytest.mark.date_unsettled`."""
    if request.node.get_closest_marker("date_unsettled"):
        return
    from b2c_concierge.profile_store import ProfileStore

    real_get = ProfileStore.get

    async def get(self, session_id):
        profile = await real_get(self, session_id)
        profile.date_checked = True
        profile.date_announced = True
        return profile

    monkeypatch.setattr(ProfileStore, "get", get)


@pytest.fixture(autouse=True)
def _closed_mcp_breaker():
    """The search leaf's MCP circuit breaker is a process-wide singleton
    (`mcp_guard.breaker`). Since R2 (review of #173) the extra calls made from
    callbacks feed it too: a test driving a failing fake MCP must not leave it
    open for the next one."""
    try:
        from hotel_search_agent import mcp_guard
    except ImportError:  # a suite run without the leaf on the path
        yield
        return
    mcp_guard.breaker.reset()
    yield
    mcp_guard.breaker.reset()
