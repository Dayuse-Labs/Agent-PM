"""Per-family leaf timeout budgets (S-G4): search vs faq, with the legacy
singular env var still winning for either when set (Railway demo override).

`_leaf_timeout` reads env at CALL time (same pattern as
hotel_search_agent.agent.build_connection_params), so plain monkeypatch.setenv
exercises every precedence case — no module reload, no cross-test pollution
of the shared `root_agent` singleton other test modules import by reference.
"""
from __future__ import annotations

from types import SimpleNamespace

from b2c_concierge.agent import _get_leg, _leaf_timeout, _reset_legs
from b2c_concierge.routing import LEAF_FAQ, LEAF_HOTEL_SEARCH


class TestDefaults:
    def test_search_defaults_to_15_seconds(self, monkeypatch):
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS", raising=False)
        assert _leaf_timeout(LEAF_HOTEL_SEARCH) == 15.0

    def test_faq_defaults_to_25_seconds(self, monkeypatch):
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS", raising=False)
        assert _leaf_timeout(LEAF_FAQ) == 25.0


class TestPerFamilyOverride:
    def test_search_specific_var_wins_over_default(self, monkeypatch):
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", raising=False)
        monkeypatch.setenv("CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS", "12.0")
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS", raising=False)
        assert _leaf_timeout(LEAF_HOTEL_SEARCH) == 12.0
        assert _leaf_timeout(LEAF_FAQ) == 25.0  # untouched

    def test_faq_specific_var_wins_over_default(self, monkeypatch):
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", raising=False)
        monkeypatch.setenv("CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS", "20.0")
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS", raising=False)
        assert _leaf_timeout(LEAF_FAQ) == 20.0
        assert _leaf_timeout(LEAF_HOTEL_SEARCH) == 15.0  # untouched


class TestLegacyFallback:
    def test_legacy_var_applies_to_both_families_when_no_specific_var_set(self, monkeypatch):
        # The Railway demo's existing CONCIERGE_LEAF_TIMEOUT_SECONDS=30 override
        # (HANDOFF 2026-07-22) must keep working unchanged after this session.
        monkeypatch.setenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", "30.0")
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS", raising=False)
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS", raising=False)
        assert _leaf_timeout(LEAF_HOTEL_SEARCH) == 30.0
        assert _leaf_timeout(LEAF_FAQ) == 30.0

    def test_specific_var_wins_over_legacy(self, monkeypatch):
        monkeypatch.setenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", "30.0")
        monkeypatch.setenv("CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS", "12.0")
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS", raising=False)
        assert _leaf_timeout(LEAF_HOTEL_SEARCH) == 12.0
        assert _leaf_timeout(LEAF_FAQ) == 30.0  # still legacy, no faq-specific var


class TestLegWiring:
    def test_get_leg_uses_the_per_family_timeout(self, monkeypatch):
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", raising=False)
        monkeypatch.setenv("CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS", "12.0")
        monkeypatch.setenv("CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS", "20.0")
        _reset_legs()
        try:
            search_leg = _get_leg(LEAF_HOTEL_SEARCH)
            faq_leg = _get_leg(LEAF_FAQ)
            assert search_leg._httpx_client.timeout.connect == 12.0
            assert faq_leg._httpx_client.timeout.connect == 20.0
        finally:
            _reset_legs()  # never leak a leg cached with test-only timeouts

    def test_get_leg_sends_the_session_id_as_dayuse_trace_id(self):
        """OBS1: the A2A request metadata carries the facade session id — the
        fleet metrics' trace_id AND the leaves' Langfuse session correlation."""
        _reset_legs()
        try:
            leg = _get_leg(LEAF_HOTEL_SEARCH)
            ctx = SimpleNamespace(session=SimpleNamespace(id="sess-77"))
            assert leg._a2a_request_meta_provider is not None
            assert leg._a2a_request_meta_provider(ctx, None) == {"dayuse_trace_id": "sess-77"}
        finally:
            _reset_legs()
