"""Langfuse observability (OBS1) — opt-in via LANGFUSE_PUBLIC_KEY/SECRET_KEY.

Fully inert without the two keys: no langfuse import, no OTel provider, no
network — the offline test suite never touches it. Message content goes ONLY
to the self-hosted EU Langfuse (the sanctioned audit channel, mirror of
conversation_logs); metric events and b2c_concierge.* logs stay content-free
(GDPR locks in test_spine.py).

Init lives in each service's serve.py — never in modules the tests import.
In the leaves setup MUST run before the agent module is imported: ADK's
lite_llm binds `from litellm import acompletion` at import time, and the
openinference instrumentor patches the litellm module attributes.
"""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None  # langfuse.Langfuse | None — Any keeps the import lazy


def setup_langfuse(service_name: str, *, instrument_litellm: bool = True) -> Any:
    """Idempotent per-process init; returns the client, or None when disabled.

    instrument_litellm: True where litellm is called directly (the concierge
    spine — no ADK model layer wraps triage/synthesis). False in the leaves:
    ADK's own `generate_content` span already carries model/usage/content
    there, and a second generation span per call double-counts every token
    and cost in Langfuse.
    """
    global _client
    if _client is not None:
        return _client
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None

    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    # ADK schema v1 (default) emits BOTH the legacy `call_llm` span and the
    # semconv `generate_content` span, each carrying gen_ai.usage.* — Langfuse
    # sums usage per span, so a turn's tokens/cost were counted 3x (call_llm +
    # generate_content + acompletion). Schema v2 drops call_llm (ADK's own
    # documented migration knob).
    os.environ.setdefault("ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN", "2")
    # Keep prompt/response content on the leaf generations (audit channel).
    os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")

    from langfuse import Langfuse

    _client = Langfuse(should_export_span=_should_export_span)
    if instrument_litellm:
        from openinference.instrumentation.litellm import LiteLLMInstrumentor

        # Registers on the global provider Langfuse just set up, so the litellm
        # generations nest under the active ADK/facade spans.
        LiteLLMInstrumentor().instrument()
    # Own handler (metrics_logger precedent): the root logger defaults to
    # WARNING, and this one boot line is the ops proof that tracing is ON.
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
        logger.setLevel(logging.INFO)
    logger.info("langfuse tracing enabled service=%s", service_name)
    return _client


def _should_export_span(span: Any) -> bool:
    # Langfuse's default filter drops ADK's attribute-less legacy `invocation`
    # root span (scope gcp.vertex.agent), which would orphan the agent subtree.
    from langfuse.span_filter import is_default_export_span

    scope = getattr(span, "instrumentation_scope", None)
    return bool(is_default_export_span(span)) or (
        scope is not None and scope.name == "gcp.vertex.agent"
    )


def get_langfuse() -> Any:
    return _client


def flush_langfuse() -> None:
    """Flush pending export batches — lifespan shutdown hook.

    Deliberately flush(), NOT shutdown(): the langfuse client registers its own
    atexit shutdown, and shutting it down from a lifespan makes any subsequent
    lifespan cycle in the same process hang on the dead export worker (Starlette
    TestClient runs one lifespan per test — this froze the serve-auth suite)."""
    if _client is not None:
        _client.flush()


@contextmanager
def turn_observation(
    *,
    name: str,
    session_id: str,
    user_id: str,
    message: str,
    is_synthetic: bool,
    metadata: dict[str, Any],
) -> Iterator[Any]:
    """Root Langfuse observation for one /v3 facade turn.

    Yields the span handle (None when disabled) so the caller can set the
    output once the final text is known. Input/output of the root observation
    become the trace input/output — the audit surface.
    """
    if _client is None:
        yield None
        return
    from langfuse import propagate_attributes

    with _client.start_as_current_observation(as_type="span", name=name, input=message) as span:
        with propagate_attributes(
            user_id=user_id,
            session_id=session_id,
            tags=["synthetic"] if is_synthetic else [],
            metadata={k: str(v) for k, v in metadata.items() if v not in (None, "")},
        ):
            yield span


@contextmanager
def observation(*, as_type: str, name: str, **kwargs: Any) -> Iterator[Any]:
    """A nested Langfuse observation of a given type (OBS2) — `agent`/`tool`/
    `chain`/`guardrail`/... No-op (yields None) when disabled. Entering the
    span never raises: a broken SDK must degrade to "no span", never break
    the guard/tool logic it wraps. Once entered, exceptions from the CALLER's
    own block propagate normally (observability never swallows a real turn
    error) — only the SDK's own enter machinery is guarded.

    Deliberately NOT used for `agent`/`tool` on ADK-driven code: ADK's own
    OTel instrumentation already emits `invoke_agent`/`execute_tool` spans
    that Langfuse recognizes as `agent`/`tool` types (verified live, OBS2
    inventory) — adding our own here would be the exact double-span mistake
    OBS1 already paid for. This helper is for the genuinely untyped gap:
    our own pure-Python guard/tool call sites that ADK never wraps."""
    if _client is None:
        yield None
        return
    try:
        cm = _client.start_as_current_observation(as_type=as_type, name=name, **kwargs)
        obs = cm.__enter__()
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("observation(%s) failed to start", name, exc_info=True)
        yield None
        return
    try:
        yield obs
    except BaseException:
        cm.__exit__(*sys.exc_info())
        raise
    else:
        cm.__exit__(None, None, None)


def mark_level(level: str, status_message: str) -> None:
    """Marks the CURRENT observation (ours, ADK's, or litellm's — whichever is
    ambient) with a level/status_message. `status_message` is a stable rule
    name ONLY — never user content (RGPD). No-op when disabled; never raises,
    regardless of what (if anything) is currently active.

    Raw OTel attribute writes (like `stamp_langfuse_session`), NOT
    `Langfuse.update_current_span()`: that convenience method reconstructs a
    span wrapper via a type lookup that only recognizes a PRE-EXISTING
    `langfuse.observation.type` attribute and defaults to "span" otherwise —
    then bakes that guess back onto the span. An ADK-native `agent`/`tool`
    span carries no such attribute (the backend infers its type from
    `gen_ai.operation.name` at ingestion instead), so calling the convenience
    method on it silently downgrades a correctly-typed observation to a
    plain `span` — caught live in OBS2 verification (the concierge's own
    `invoke_agent` span lost its `agent` type this way)."""
    if _client is None:
        return
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        span.set_attribute("langfuse.observation.level", level)
        span.set_attribute("langfuse.observation.status_message", status_message)
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("mark_level(%s) skipped", level, exc_info=True)


def mark_metadata(metadata: dict[str, Any]) -> None:
    """Adds filterable, first-level metadata keys to the CURRENT observation
    (e.g. route, feeder leaf, llm_calls, turn status). No-op when disabled;
    never raises. Never message content — counters/enums only (RGPD).

    Raw OTel attribute writes — see `mark_level`'s docstring for why."""
    if _client is None:
        return
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        for key, value in metadata.items():
            if value in (None, ""):
                continue
            span.set_attribute(f"langfuse.observation.metadata.{key}", str(value))
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("mark_metadata skipped", exc_info=True)


def stamp_langfuse_session(callback_context: Any) -> None:
    """Leaf before_agent_callback: enrich the leaf trace so it reads well in
    the Langfuse UI — session id from the inbound A2A dayuse_trace_id (the
    Sessions view then groups the leaf trace with the concierge turn), the
    agent name as the trace name, and the inbound request text as the trace
    input. The langfuse.trace.* attributes are trace-level: they apply from
    any span of the trace (ADK's root `invocation` span carries no attributes,
    which is why the trace would otherwise show as unnamed with no input).
    Enrichment only: never raises, always returns None so the ADK callback
    chain continues."""
    if _client is None:
        return None
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        run_config = getattr(callback_context, "run_config", None)
        meta = (getattr(run_config, "custom_metadata", None) or {}).get("a2a_metadata") or {}
        trace_id = meta.get("dayuse_trace_id")
        if not (isinstance(trace_id, str) and trace_id):
            # Direct A2A caller without fleet metadata: group by own session.
            trace_id = getattr(getattr(callback_context, "session", None), "id", None)
        if isinstance(trace_id, str) and trace_id:
            span.set_attribute("langfuse.session.id", trace_id)
        agent_name = getattr(callback_context, "agent_name", None)
        if isinstance(agent_name, str) and agent_name:
            span.set_attribute("langfuse.trace.name", agent_name)
        request_text = _content_text(getattr(callback_context, "user_content", None))
        if request_text:
            span.set_attribute("langfuse.trace.input", request_text)
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("stamp_langfuse_session skipped", exc_info=True)
    return None


def stamp_langfuse_turn_session(callback_context: Any) -> None:
    """Concierge before_agent_callback: stamp session + user on the trace, so
    A2A-driven turns (peer agents, eval battery, smoke) land in the Sessions
    view too. The /v3 facade path sets the same values via turn_observation —
    same session id (the ADK session id IS the facade session id), so the
    double write is idempotent. Deliberately does NOT set the trace name or
    input: on the facade path those belong to the v3.chat root span."""
    if _client is None:
        return None
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        session = getattr(callback_context, "session", None)
        session_id = getattr(session, "id", None)
        if isinstance(session_id, str) and session_id:
            span.set_attribute("langfuse.session.id", session_id)
        user_id = getattr(session, "user_id", None)
        if isinstance(user_id, str) and user_id:
            span.set_attribute("langfuse.user.id", user_id)
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("stamp_langfuse_turn_session skipped", exc_info=True)
    return None


def _content_text(content: Any) -> str:
    """Text parts of a genai Content, joined — empty string when none."""
    parts = getattr(content, "parts", None) or []
    texts = [t for t in (getattr(p, "text", None) for p in parts) if isinstance(t, str) and t]
    return "\n".join(texts)
