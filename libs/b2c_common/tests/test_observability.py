"""observability.py (OBS1) — the Langfuse seam is opt-in and inert by default.

Locks the offline invariant: without LANGFUSE_PUBLIC_KEY/SECRET_KEY the module
must not import langfuse, install an OTel provider, or touch the network —
the whole test suite runs with it disabled, so these tests pin the OFF path
and the enrichment helpers' never-raise contract.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
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


class TestStampLeafTurn:
    """OBS4 replacement for `stamp_langfuse_session`: same session-id
    behaviour, but the inbound request text now goes on the leaf's ROOT
    observation (its input IS the trace input) instead of the deprecated
    trace-level attributes."""

    def test_noop_when_disabled(self):
        # Junk context on the disabled path: no attribute access should matter.
        assert observability.stamp_a2a_turn(object()) is None

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
            assert observability.stamp_a2a_turn(ctx) is None

    def test_stamps_session_and_feeds_the_root_observation_input(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        recorded: dict = {}
        updates: list[dict] = []

        span = SimpleNamespace(set_attribute=lambda k, v: recorded.__setitem__(k, v))
        import opentelemetry.trace

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", lambda: span)
        root = SimpleNamespace(update=lambda **kwargs: updates.append(kwargs))
        token = observability._a2a_root_observation.set(root)
        try:
            ctx = SimpleNamespace(
                run_config=SimpleNamespace(
                    custom_metadata={"a2a_metadata": {"dayuse_trace_id": "sess-42"}}
                ),
                agent_name="b2c_faq",
                user_content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text="conditions d'annulation ?"),
                        SimpleNamespace(text=None),
                    ]
                ),
            )
            assert observability.stamp_a2a_turn(ctx) is None
        finally:
            observability._a2a_root_observation.reset(token)
        # No trace-level name/input any more: the root observation carries both.
        assert recorded == {"langfuse.session.id": "sess-42"}
        assert updates == [{"input": "conditions d'annulation ?"}]

    def test_falls_back_to_own_session_without_a2a_metadata(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        recorded: dict = {}

        span = SimpleNamespace(set_attribute=lambda k, v: recorded.__setitem__(k, v))
        import opentelemetry.trace

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", lambda: span)
        ctx = SimpleNamespace(run_config=None, session=SimpleNamespace(id="own-session"))
        observability.stamp_a2a_turn(ctx)
        assert recorded["langfuse.session.id"] == "own-session"

    def test_output_goes_on_the_a2a_root_observation(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        updates: list[dict] = []
        root = SimpleNamespace(update=lambda **kwargs: updates.append(kwargs))
        token = observability._a2a_root_observation.set(root)
        try:
            observability.mark_a2a_turn_output("Voici trois hôtels à Lyon.")
        finally:
            observability._a2a_root_observation.reset(token)
        assert updates == [{"output": "Voici trois hôtels à Lyon."}]

    def test_output_is_a_noop_on_the_facade_path(self, monkeypatch):
        """No A2A root observation = the /v3 path, where `turn_observation`
        owns `v3.chat`'s output. Must not raise, must not write anywhere."""
        monkeypatch.setattr(observability, "_client", object())
        observability.mark_a2a_turn_output("anything")  # no contextvar set

    def test_output_is_a_noop_when_disabled_or_empty(self, monkeypatch):
        observability.mark_a2a_turn_output("anything")  # _client is None
        monkeypatch.setattr(observability, "_client", object())
        updates: list[dict] = []
        root = SimpleNamespace(update=lambda **kwargs: updates.append(kwargs))
        token = observability._a2a_root_observation.set(root)
        try:
            observability.mark_a2a_turn_output("")
        finally:
            observability._a2a_root_observation.reset(token)
        assert updates == []

    def test_no_root_observation_still_stamps_the_session(self, monkeypatch):
        """A leaf reached outside `A2aTurnObservation` (a future non-A2A entry
        point) must still land in the Sessions view, not crash."""
        monkeypatch.setattr(observability, "_client", object())
        recorded: dict = {}
        span = SimpleNamespace(set_attribute=lambda k, v: recorded.__setitem__(k, v))
        import opentelemetry.trace

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", lambda: span)
        ctx = SimpleNamespace(
            run_config=None,
            session=SimpleNamespace(id="own-session"),
            user_content=SimpleNamespace(parts=[SimpleNamespace(text="hello")]),
        )
        assert observability.stamp_a2a_turn(ctx) is None
        assert recorded == {"langfuse.session.id": "own-session"}


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


class _FakeLangfuseClient:
    """Minimal stand-in for the Langfuse client: `observation()` only needs a
    `start_as_current_observation` context manager. Backed by a REAL — but
    process-local and exporter-less — TracerProvider, because the OBS4
    mechanism under test IS the OpenTelemetry context, and faking that would
    test nothing. Deliberately not the global provider: setting one is a
    one-shot, process-wide side effect."""

    def __init__(self) -> None:
        from opentelemetry.sdk.trace import TracerProvider

        self.tracer = TracerProvider().get_tracer("b2c-test")
        self.observations: list[tuple[str, str]] = []
        self.updates: list[dict] = []

    @contextmanager
    def start_as_current_observation(self, *, as_type: str, name: str, **kwargs: Any) -> Any:
        self.observations.append((as_type, name))
        with self.tracer.start_as_current_span(name):
            yield SimpleNamespace(update=lambda **kw: self.updates.append(kw))


def _hex_ids(span_context: Any) -> tuple[str, str]:
    from opentelemetry.trace import format_span_id, format_trace_id

    return format_trace_id(span_context.trace_id), format_span_id(span_context.span_id)


class TestTraceContextCarrier:
    """OBS4: the ONE wire format for every cross-process hop we own — the A2A
    leg's HTTP headers and the MCP `_meta` field."""

    def test_empty_when_disabled(self):
        assert observability.trace_context_carrier() == {}

    def test_empty_without_an_active_span(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        assert observability.trace_context_carrier() == {}

    def test_carries_the_active_span_and_the_app_root_claim(self, monkeypatch):
        client = _FakeLangfuseClient()
        monkeypatch.setattr(observability, "_client", client)
        with client.tracer.start_as_current_span("outbound") as span:
            carrier = observability.trace_context_carrier()
            trace_id, span_id = _hex_ids(span.get_span_context())
        version, carried_trace, carried_span, _flags = carrier["traceparent"].split("-")
        assert (version, carried_trace, carried_span) == ("00", trace_id, span_id)
        # The app-root claim is what stops the receiving SDK from opening a
        # SECOND root observation on this trace (see the constant's docstring).
        assert f"langfuse_trace_id={trace_id}" in carrier["baggage"]

    def test_baggage_key_matches_the_langfuse_sdk_constant(self):
        """Pin-guard (test_stateless_leg.py precedent): the key is Langfuse's,
        not ours — an SDK bump that renames it must fail here, loudly, instead
        of silently letting joined leaves claim a second trace root."""
        from langfuse._client.propagation import LANGFUSE_TRACE_ID_BAGGAGE_KEY

        assert observability._LANGFUSE_TRACE_ID_BAGGAGE_KEY == LANGFUSE_TRACE_ID_BAGGAGE_KEY


class TestA2aTurnObservation:
    """OBS4: the leaf's ASGI edge is the ONLY interception point early enough
    to reparent ADK's spans — proven here by asserting on the trace id of a
    span the wrapped app creates."""

    @staticmethod
    def _app(tracer: Any, seen: list) -> Any:
        async def app(scope: Any, receive: Any, send: Any) -> None:
            span = tracer.start_span("inner")  # implicit parent = ambient context
            seen.append(span.get_span_context())
            span.end()

        return app

    @staticmethod
    def _scope(*, method: str = "POST", headers: list | None = None) -> dict:
        return {"type": "http", "method": method, "path": "/", "headers": headers or []}

    def _run(self, middleware: Any, scope: dict) -> None:
        import asyncio

        asyncio.run(middleware(scope, None, None))

    def test_passthrough_when_disabled(self):
        from opentelemetry.sdk.trace import TracerProvider

        tracer = TracerProvider().get_tracer("b2c-test")
        seen: list = []
        middleware = observability.A2aTurnObservation(
            self._app(tracer, seen), name="b2c_hotel_search"
        )
        self._run(middleware, self._scope())
        assert len(seen) == 1  # the app ran, nothing was traced around it

    def test_joins_the_callers_trace(self, monkeypatch):
        client = _FakeLangfuseClient()
        monkeypatch.setattr(observability, "_client", client)
        seen: list = []
        middleware = observability.A2aTurnObservation(
            self._app(client.tracer, seen), name="b2c_hotel_search"
        )
        with client.tracer.start_as_current_span("caller") as caller:
            carrier = observability.trace_context_carrier()
            caller_trace_id, _ = _hex_ids(caller.get_span_context())
        headers = [(key.encode(), value.encode()) for key, value in carrier.items()]

        self._run(middleware, self._scope(headers=headers))

        assert _hex_ids(seen[0])[0] == caller_trace_id
        assert client.observations == [("span", "a2a.b2c_hotel_search")]

    def test_starts_its_own_trace_without_upstream_context(self, monkeypatch):
        """Peer agent, eval battery, isolated smoke: readable, not anonymous —
        its own trace, named, and `stamp_a2a_turn` gives it an input."""
        client = _FakeLangfuseClient()
        monkeypatch.setattr(observability, "_client", client)
        seen: list = []
        middleware = observability.A2aTurnObservation(
            self._app(client.tracer, seen), name="b2c_faq"
        )
        with client.tracer.start_as_current_span("unrelated") as unrelated:
            unrelated_trace_id, _ = _hex_ids(unrelated.get_span_context())

        self._run(middleware, self._scope(headers=[(b"authorization", b"Bearer x")]))

        assert _hex_ids(seen[0])[0] != unrelated_trace_id
        assert client.observations == [("span", "a2a.b2c_faq")]

    def test_agent_card_get_is_not_traced(self, monkeypatch):
        client = _FakeLangfuseClient()
        monkeypatch.setattr(observability, "_client", client)
        seen: list = []
        middleware = observability.A2aTurnObservation(
            self._app(client.tracer, seen), name="b2c_faq"
        )
        self._run(middleware, self._scope(method="GET"))
        assert client.observations == []  # discovery must never open a trace
        assert len(seen) == 1

    def test_non_http_scope_passes_through(self, monkeypatch):
        client = _FakeLangfuseClient()
        monkeypatch.setattr(observability, "_client", client)
        seen: list = []
        middleware = observability.A2aTurnObservation(
            self._app(client.tracer, seen), name="b2c_faq"
        )
        self._run(middleware, {"type": "lifespan"})
        assert client.observations == []


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


class _RecordingObservation:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class _RecordingClient:
    """Duck-typed stand-in for langfuse.Langfuse — OBS2 helpers."""

    def __init__(self) -> None:
        self.observations: list[dict] = []
        self.updates: list[dict] = []

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        self.observations.append(kwargs)
        yield _RecordingObservation()

    def update_current_span(self, **kwargs) -> None:
        self.updates.append(kwargs)


class TestObservationDisabled:
    def test_yields_none_and_runs_the_block(self):
        ran = False
        with observability.observation(as_type="guardrail", name="check-x") as obs:
            ran = True
            assert obs is None
        assert ran


class TestObservationEnabled:
    def test_enters_with_as_type_and_name(self, monkeypatch):
        client = _RecordingClient()
        monkeypatch.setattr(observability, "_client", client)
        with observability.observation(as_type="tool", name="mcp-thing") as obs:
            assert obs is not None
        assert client.observations == [{"as_type": "tool", "name": "mcp-thing"}]

    def test_propagates_the_callers_own_exception(self, monkeypatch):
        client = _RecordingClient()
        monkeypatch.setattr(observability, "_client", client)
        with pytest.raises(ValueError, match="real bug"):
            with observability.observation(as_type="guardrail", name="check-x"):
                raise ValueError("real bug")

    def test_never_raises_when_the_sdk_fails_to_start(self, monkeypatch):
        class _BrokenClient:
            def start_as_current_observation(self, **kwargs):
                raise RuntimeError("sdk broke")

        monkeypatch.setattr(observability, "_client", _BrokenClient())
        ran = False
        with observability.observation(as_type="guardrail", name="check-x") as obs:
            ran = True
            assert obs is None
        assert ran


class TestMarkLevel:
    """Raw OTel attribute writes on the ambient span — NOT
    `Langfuse.update_current_span()`. That convenience method reconstructs a
    span wrapper from a type it can only read off a PRE-EXISTING
    `langfuse.observation.type` attribute (defaulting to "span" otherwise),
    then bakes that guess back onto the span — silently downgrading an
    ADK-native `agent`/`tool` span (typed by the backend from
    `gen_ai.operation.name`, never via that attribute) to a plain `span`.
    Caught live in OBS2 verification; see observability.mark_level."""

    def test_noop_when_disabled(self):
        observability.mark_level("ERROR", "whatever")  # must not raise

    def test_sets_raw_attributes_on_the_current_span_when_enabled(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        recorded: dict = {}
        span = SimpleNamespace(set_attribute=lambda k, v: recorded.__setitem__(k, v))
        import opentelemetry.trace

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", lambda: span)
        observability.mark_level("WARNING", "some_guard")
        assert recorded == {
            "langfuse.observation.level": "WARNING",
            "langfuse.observation.status_message": "some_guard",
        }

    def test_never_raises_when_the_span_raises(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        import opentelemetry.trace

        def _broken_span():
            raise RuntimeError("boom")

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", _broken_span)
        observability.mark_level("ERROR", "some_guard")  # must not raise


class TestMarkMetadata:
    def test_noop_when_disabled(self):
        observability.mark_metadata({"a": 1})  # must not raise

    def test_sets_raw_per_key_attributes_and_drops_empty_values(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        recorded: dict = {}
        span = SimpleNamespace(set_attribute=lambda k, v: recorded.__setitem__(k, v))
        import opentelemetry.trace

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", lambda: span)
        observability.mark_metadata(
            {"llm_calls": 2, "route": "leaf:hotel_search", "empty": None, "blank": ""}
        )
        assert recorded == {
            "langfuse.observation.metadata.llm_calls": "2",
            "langfuse.observation.metadata.route": "leaf:hotel_search",
        }

    def test_never_raises_when_the_span_raises(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        import opentelemetry.trace

        def _broken_span():
            raise RuntimeError("boom")

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", _broken_span)
        observability.mark_metadata({"a": 1})  # must not raise

    def test_never_raises_when_the_client_raises(self, monkeypatch):
        class _BrokenClient:
            def update_current_span(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(observability, "_client", _BrokenClient())
        observability.mark_metadata({"a": 1})  # must not raise
