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
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None  # langfuse.Langfuse | None — Any keeps the import lazy


def setup_langfuse(service_name: str) -> Any:
    """Idempotent per-process init; returns the client, or None when disabled."""
    global _client
    if _client is not None:
        return _client
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None

    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)

    from langfuse import Langfuse
    from openinference.instrumentation.litellm import LiteLLMInstrumentor

    _client = Langfuse(should_export_span=_should_export_span)
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


def shutdown_langfuse() -> None:
    """Flush pending export batches — lifespan shutdown hook."""
    if _client is not None:
        _client.shutdown()


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


def stamp_langfuse_session(callback_context: Any) -> None:
    """Leaf before_agent_callback: mirror the inbound A2A dayuse_trace_id onto
    the current span as langfuse.session.id, so the Langfuse Sessions view
    groups the leaf trace with the concierge turn. Enrichment only: never
    raises, always returns None so the ADK callback chain continues."""
    if _client is None:
        return None
    try:
        run_config = getattr(callback_context, "run_config", None)
        meta = (getattr(run_config, "custom_metadata", None) or {}).get("a2a_metadata") or {}
        trace_id = meta.get("dayuse_trace_id")
        if isinstance(trace_id, str) and trace_id:
            from opentelemetry import trace

            trace.get_current_span().set_attribute("langfuse.session.id", trace_id)
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("stamp_langfuse_session skipped", exc_info=True)
    return None
