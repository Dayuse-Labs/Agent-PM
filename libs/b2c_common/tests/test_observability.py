"""observability.py (OBS1) — the Langfuse seam is opt-in and inert by default.

Locks the offline invariant: without LANGFUSE_PUBLIC_KEY/SECRET_KEY the module
must not import langfuse, install an OTel provider, or touch the network —
the whole test suite runs with it disabled, so these tests pin the OFF path
and the enrichment helpers' never-raise contract.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from b2c_common import observability


@pytest.fixture(autouse=True)
def _disabled(monkeypatch):
    """Default state for every test here: no keys, no cached client."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(observability, "_client", None)


class TestSetupDisabledByDefault:
    def test_returns_none_without_keys(self):
        assert observability.setup_langfuse("test-service") is None
        assert observability.get_langfuse() is None

    def test_does_not_import_langfuse_without_keys(self):
        before = "langfuse" in sys.modules
        observability.setup_langfuse("test-service")
        # setup must not pull langfuse in as a side effect (offline suite);
        # tolerate another test having imported it deliberately.
        assert ("langfuse" in sys.modules) == before

    def test_one_key_alone_is_not_enough(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
        assert observability.setup_langfuse("test-service") is None

    def test_idempotent_returns_cached_client(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(observability, "_client", sentinel)
        assert observability.setup_langfuse("test-service") is sentinel

    def test_flush_is_a_noop_when_disabled(self):
        observability.flush_langfuse()  # must not raise

    def test_empty_string_keys_stay_disabled(self, monkeypatch):
        """The root conftest neutralizes leaked .env keys with EMPTY strings
        (litellm's load_dotenv can't override an existing var) — empty must
        read as disabled."""
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
        assert observability.setup_langfuse("test-service") is None


class TestTurnObservationDisabled:
    def test_yields_none_and_runs_the_block(self):
        ran = False
        with observability.turn_observation(
            name="v3.chat", session_id="s1", user_id="v3_s1", message="bonjour",
            is_synthetic=False, metadata={"turn_index": 0},
        ) as span:
            ran = True
            assert span is None
        assert ran


class TestStampLangfuseSession:
    def test_noop_when_disabled(self):
        # Junk context on the disabled path: no attribute access should matter.
        assert observability.stamp_langfuse_session(object()) is None

    def test_never_raises_on_junk_contexts_when_enabled(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        for ctx in (
            object(),                                            # no run_config
            SimpleNamespace(run_config=None),                    # run_config None
            SimpleNamespace(run_config=SimpleNamespace(custom_metadata=None)),
            SimpleNamespace(run_config=SimpleNamespace(custom_metadata={})),
            SimpleNamespace(run_config=SimpleNamespace(
                custom_metadata={"a2a_metadata": {"dayuse_trace_id": 123}}  # non-str
            )),
        ):
            assert observability.stamp_langfuse_session(ctx) is None

    def test_stamps_session_name_and_input_from_the_inbound_request(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        recorded: dict = {}

        span = SimpleNamespace(set_attribute=lambda k, v: recorded.__setitem__(k, v))
        import opentelemetry.trace

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", lambda: span)
        ctx = SimpleNamespace(
            run_config=SimpleNamespace(
                custom_metadata={"a2a_metadata": {"dayuse_trace_id": "sess-42"}}
            ),
            agent_name="b2c_faq",
            user_content=SimpleNamespace(
                parts=[SimpleNamespace(text="conditions d'annulation ?"), SimpleNamespace(text=None)]
            ),
        )
        assert observability.stamp_langfuse_session(ctx) is None
        assert recorded == {
            "langfuse.session.id": "sess-42",
            "langfuse.trace.name": "b2c_faq",
            "langfuse.trace.input": "conditions d'annulation ?",
        }

    def test_falls_back_to_own_session_without_a2a_metadata(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        recorded: dict = {}

        span = SimpleNamespace(set_attribute=lambda k, v: recorded.__setitem__(k, v))
        import opentelemetry.trace

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", lambda: span)
        ctx = SimpleNamespace(run_config=None, session=SimpleNamespace(id="own-session"))
        observability.stamp_langfuse_session(ctx)
        assert recorded["langfuse.session.id"] == "own-session"


class TestStampLangfuseTurnSession:
    def test_noop_when_disabled(self):
        assert observability.stamp_langfuse_turn_session(object()) is None

    def test_never_raises_on_junk_contexts_when_enabled(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        for ctx in (object(), SimpleNamespace(session=None)):
            assert observability.stamp_langfuse_turn_session(ctx) is None

    def test_stamps_session_and_user_from_the_adk_session(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        recorded: dict = {}

        span = SimpleNamespace(set_attribute=lambda k, v: recorded.__setitem__(k, v))
        import opentelemetry.trace

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", lambda: span)
        ctx = SimpleNamespace(session=SimpleNamespace(id="sess-9", user_id="v3_sess-9"))
        assert observability.stamp_langfuse_turn_session(ctx) is None
        assert recorded == {
            "langfuse.session.id": "sess-9",
            "langfuse.user.id": "v3_sess-9",
        }


def _otel_span(name: str, span_id: str, attributes: dict) -> Any:
    from langfuse.types import OtelSpanData

    return OtelSpanData(
        trace_id="t" * 32,
        span_id=span_id,
        parent_span_id=None,
        name=name,
        instrumentation_scope_name="gcp.vertex.agent",
        instrumentation_scope_version="2.4.0",
        attributes=attributes,
        resource_attributes={},
    )


class TestMaskCallLlmUsage:
    """ADK's `call_llm` span duplicates every gen_ai.* attribute (usage,
    model, content) of its child `generate_content` span — Langfuse sums
    usage per GENERATION-typed observation, so left unmasked this doubles
    every leaf's token/cost. A usage-only strip is NOT enough: verified live
    that Langfuse then falls back to estimating usage from the remaining
    model+content attributes, landing on a different but still-nonzero
    number. `_mask_call_llm_usage` strips every gen_ai.* key plus the two
    content-duplicating gcp.vertex.agent.llm_* keys, leaving `call_llm` a
    contentless timing span and `generate_content` the sole source of
    usage/cost/content."""

    def test_strips_all_gen_ai_and_content_keys_from_call_llm_only(self):
        from langfuse.types import MaskOtelSpansParams, OtelSpanIdentifier

        call_llm_id = OtelSpanIdentifier(trace_id="t" * 32, span_id="a" * 16)
        gen_content_id = OtelSpanIdentifier(trace_id="t" * 32, span_id="b" * 16)
        params = MaskOtelSpansParams(
            spans={
                call_llm_id: _otel_span(
                    "call_llm",
                    "a" * 16,
                    {
                        "gen_ai.usage.input_tokens": 4561,
                        "gen_ai.usage.output_tokens": 48,
                        "gen_ai.request.model": "gpt-4o-mini",
                        "gen_ai.system": "gcp.vertex.agent",
                        "gcp.vertex.agent.llm_request": "{...}",
                        "gcp.vertex.agent.llm_response": "{...}",
                        "gcp.vertex.agent.invocation_id": "inv-1",
                        "gcp.vertex.agent.session_id": "sess-1",
                    },
                ),
                gen_content_id: _otel_span(
                    "generate_content gpt-4o-mini",
                    "b" * 16,
                    {"gen_ai.usage.input_tokens": 4561, "gen_ai.usage.output_tokens": 48},
                ),
            }
        )
        result = observability._mask_call_llm_usage(params=params)
        assert set(result.span_patches.keys()) == {call_llm_id}
        patch = result.span_patches[call_llm_id]
        assert set(patch.delete_attributes) == {
            "gen_ai.usage.input_tokens",
            "gen_ai.usage.output_tokens",
            "gen_ai.request.model",
            "gen_ai.system",
            "gcp.vertex.agent.llm_request",
            "gcp.vertex.agent.llm_response",
        }
        # Correlation ids are not gen_ai.* / content keys — left alone.
        assert "gcp.vertex.agent.invocation_id" not in patch.delete_attributes
        assert "gcp.vertex.agent.session_id" not in patch.delete_attributes
        assert patch.set_attributes == {}

    def test_call_llm_with_nothing_to_strip_is_untouched(self):
        """A `call_llm` SPAN with no gen_ai.*/content keys at all (e.g. one
        already fully masked in an earlier batch) — nothing to patch, must
        not invent an empty/no-op patch for it."""
        from langfuse.types import MaskOtelSpansParams, OtelSpanIdentifier

        span_id = OtelSpanIdentifier(trace_id="t" * 32, span_id="c" * 16)
        params = MaskOtelSpansParams(
            spans={span_id: _otel_span("call_llm", "c" * 16, {"gcp.vertex.agent.event_id": "e-1"})}
        )
        result = observability._mask_call_llm_usage(params=params)
        assert result.span_patches == {}

    def test_non_call_llm_spans_are_never_patched(self):
        from langfuse.types import MaskOtelSpansParams, OtelSpanIdentifier

        span_id = OtelSpanIdentifier(trace_id="t" * 32, span_id="d" * 16)
        params = MaskOtelSpansParams(
            spans={
                span_id: _otel_span(
                    "execute_tool search_offers",
                    "d" * 16,
                    {"gen_ai.usage.input_tokens": 100},
                )
            }
        )
        result = observability._mask_call_llm_usage(params=params)
        assert result.span_patches == {}

    def test_never_raises_on_malformed_params(self):
        assert observability._mask_call_llm_usage(params=object()) is None
