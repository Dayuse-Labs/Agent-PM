"""Per-family leaf timeout budgets (S-G4, sized again 2026-10-28 on the leaves'
own LLM relaunch): search vs faq, with the legacy singular env var still
winning for either when set (Railway override).

`_leaf_timeout` reads env at CALL time (same pattern as
hotel_search_agent.agent.build_connection_params), so plain monkeypatch.setenv
exercises every precedence case — no module reload, no cross-test pollution
of the shared `root_agent` singleton other test modules import by reference.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
from b2c_common import observability
from b2c_concierge.agent import _get_leg, _leaf_timeout, _reset_legs
from b2c_concierge.routing import LEAF_FAQ, LEAF_HOTEL_SEARCH
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import format_span_id, format_trace_id


class TestDefaults:
    def test_search_defaults_to_45_seconds(self, monkeypatch):
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS", raising=False)
        assert _leaf_timeout(LEAF_HOTEL_SEARCH) == 45.0

    def test_faq_defaults_to_45_seconds(self, monkeypatch):
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS", raising=False)
        assert _leaf_timeout(LEAF_FAQ) == 45.0


class TestPerFamilyOverride:
    def test_search_specific_var_wins_over_default(self, monkeypatch):
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", raising=False)
        monkeypatch.setenv("CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS", "12.0")
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS", raising=False)
        assert _leaf_timeout(LEAF_HOTEL_SEARCH) == 12.0
        assert _leaf_timeout(LEAF_FAQ) == 45.0  # untouched

    def test_faq_specific_var_wins_over_default(self, monkeypatch):
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SECONDS", raising=False)
        monkeypatch.setenv("CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS", "20.0")
        monkeypatch.delenv("CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS", raising=False)
        assert _leaf_timeout(LEAF_FAQ) == 20.0
        assert _leaf_timeout(LEAF_HOTEL_SEARCH) == 45.0  # untouched


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


class TestTraceContextInjection:
    """OBS4: the leg is the concierge's ONE outbound injection point for the
    W3C trace context (the inline MCP client is the other) — never a global
    httpx instrumentation, so no third party ever receives our baggage."""

    @staticmethod
    def _hook_and_request():
        leg = _get_leg(LEAF_HOTEL_SEARCH)
        hooks = leg._httpx_client.event_hooks["request"]
        assert len(hooks) == 1
        return hooks[0], httpx.Request("POST", "http://leaf.internal/")

    def test_no_headers_added_when_tracing_is_disabled(self):
        _reset_legs()
        try:
            hook, request = self._hook_and_request()
            asyncio.run(hook(request))
            assert "traceparent" not in request.headers
        finally:
            _reset_legs()

    def test_injects_the_current_traceparent_and_baggage(self, monkeypatch):
        _reset_legs()
        try:
            hook, request = self._hook_and_request()
            tracer = TracerProvider().get_tracer("b2c-test")
            monkeypatch.setattr(observability, "_client", object())
            with tracer.start_as_current_span("leaf_call") as span:
                asyncio.run(hook(request))
                context = span.get_span_context()
            # Flags deliberately not asserted: OTel 1.42 also sets the `random`
            # trace flag (03, not 01) — the identity is what matters here.
            version, trace_id, span_id, _flags = request.headers["traceparent"].split("-")
            assert (version, trace_id, span_id) == (
                "00", format_trace_id(context.trace_id), format_span_id(context.span_id)
            )
            assert format_trace_id(context.trace_id) in request.headers["baggage"]
        finally:
            _reset_legs()
