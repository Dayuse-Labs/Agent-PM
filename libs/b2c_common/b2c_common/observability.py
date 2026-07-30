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
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None  # langfuse.Langfuse | None — Any keeps the import lazy

#: The leaf's root observation for the A2A request being served, so an ADK
#: callback (which runs deep inside it) can still set its input. Set by
#: `A2aTurnObservation`, read by `stamp_a2a_turn`.
_a2a_root_observation: ContextVar[Any] = ContextVar("b2c_a2a_root_observation", default=None)


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
    # ADK emits BOTH the legacy `call_llm` span and the semconv
    # `generate_content` span for every model call, each carrying identical
    # gen_ai.usage.* attributes — Langfuse sums usage per GENERATION-typed
    # observation, so a turn's tokens/cost were counted 2x on any agent that
    # goes through ADK's own model layer (the leaves). `call_llm`'s creation
    # (google/adk/flows/llm_flows/base_llm_flow.py, `_call_llm_async`) is
    # UNCONDITIONAL — `ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN=2` does NOT drop it
    # despite ADK's own telemetry/_schema_version.py migration-plan comment
    # listing "the call_llm span is removed" as a step; that step hasn't
    # shipped in google-adk==2.4.0 (verified against a real trace, OBS2 +
    # follow-up). The opt-in still matters for the OTHER schema-v2 change
    # (the `invocation` root span becomes `invoke_workflow`), so it stays.
    # `_mask_call_llm_usage` below is the actual fix for the usage double
    # count: it strips every gen_ai.* attribute (and the duplicated content
    # keys) from `call_llm` at export time, leaving `generate_content` as the
    # sole source of usage/cost/content for that span.
    os.environ.setdefault("ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN", "2")
    # Keep prompt/response content on the leaf generations (audit channel).
    os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")

    from langfuse import Langfuse

    _client = Langfuse(
        should_export_span=_should_export_span, mask_otel_spans=_mask_call_llm_usage
    )
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


#: Instrumentation scopes Langfuse's default filter drops but we need:
#: - `gcp.vertex.agent`: ADK's attribute-less `invoke_workflow` root span, whose
#:   loss would orphan the whole agent subtree (OBS1).
#: - `a2a-python-sdk`: the a2a-sdk decorates its transports and handlers with
#:   `@trace_class` (a2a/utils/telemetry.py), and those spans sit BETWEEN the
#:   concierge's leg span and the leaf's ADK spans, on BOTH sides of the A2A
#:   hop. Dropping them punched two holes in the joined trace: the leaf subtree
#:   and our own leaf root observation surfaced as extra TOP-LEVEL nodes instead
#:   of nesting under the concierge — one trace, but not one TREE, so no Agent
#:   Graph edge either (measured on a real turn, OBS4). Keeping them also puts
#:   the A2A network hop's own timing in the trace, which the latency work wants.
_EXTRA_EXPORT_SCOPES = ("gcp.vertex.agent", "a2a-python-sdk")

#: ...but NOT the a2a event plumbing: `@trace_class` also wraps EventQueue /
#: EventConsumer / InMemoryQueueManager, whose per-event methods
#: (enqueue/dequeue/task_done) fire dozens of times per turn — measured: 76
#: observations instead of ~31 on one search turn, all of it churn carrying no
#: information about the turn. Excluded by MODULE prefix rather than by an
#: allowlist of the path's method names on purpose: this fails OPEN (a2a-sdk
#: renames something → a few noisy spans) instead of failing CLOSED (a hole in
#: the tree, which is what we just fixed), and `a2a-sdk==0.3.26` is pinned
#: precisely because 0.3.x moves.
_A2A_NOISY_SPAN_PREFIX = "a2a.server.events."


def _should_export_span(span: Any) -> bool:
    from langfuse.span_filter import is_default_export_span

    scope = getattr(span, "instrumentation_scope", None)
    if scope is not None and scope.name == "a2a-python-sdk":
        return not getattr(span, "name", "").startswith(_A2A_NOISY_SPAN_PREFIX)
    return bool(is_default_export_span(span)) or (
        scope is not None and scope.name in _EXTRA_EXPORT_SCOPES
    )


#: Non-usage attributes `call_llm` also carries the full duplicate of, that
#: make Langfuse treat it as a billable generation even with gen_ai.usage.*
#: gone: without also stripping these, the backend falls back to estimating
#: usage from the request/response content itself once it sees a known model
#: name — verified live (OBS2 follow-up): a usage.* -only strip left `call_llm`
#: reporting a DIFFERENT, tokenizer-estimated, still-nonzero usage, not zero.
_CALL_LLM_CONTENT_KEYS = ("gcp.vertex.agent.llm_request", "gcp.vertex.agent.llm_response")


def _mask_call_llm_usage(*, params: Any) -> Any:
    """Export-stage fix for ADK's usage double count (see the comment in
    `setup_langfuse`): ADK's `call_llm` span duplicates every `gen_ai.*`
    attribute (usage, model, content) of its child `generate_content {model}`
    span. Stripping `gen_ai.*` and the two `gcp.vertex.agent.llm_*` content
    keys leaves `call_llm` a plain, contentless timing span — `generate_content`
    is untouched and stays the sole source of usage/cost/content for that
    model call. Langfuse has no attribute of its own that means "generation,
    but don't count usage": there is no lighter-touch fix than removing every
    signal that makes the backend treat the span as billable.

    Never raises: `mask_otel_spans` drops the WHOLE export batch on an
    exception (langfuse/_client/client.py docstring), so a bug here must
    degrade to "no masking", never to "no export"."""
    try:
        from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

        patches = {}
        for identifier, span in params.spans.items():
            if span.name != "call_llm":
                continue
            drop = tuple(k for k in span.attributes if k.startswith("gen_ai.")) + tuple(
                k for k in _CALL_LLM_CONTENT_KEYS if k in span.attributes
            )
            if drop:
                patches[identifier] = OtelSpanPatch(delete_attributes=drop)
        return MaskOtelSpansResult(span_patches=patches)
    except Exception:  # noqa: BLE001 — observability must never break export
        logger.debug("_mask_call_llm_usage failed, exporting batch unmasked", exc_info=True)
        return None


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

    OBS4: session + user also travel to the leaves in OTel baggage, so the leaf
    observations that join this trace carry them too (aggregations only count
    observations that have the attribute set). `as_baggage` is a per-CALL flag,
    not per-field, hence the nested pair: everything in the outer call leaves
    the process in plain HTTP headers, so only opaque identifiers go there
    (see `trace_context_carrier`); the turn's tags and metadata stay local.
    """
    if _client is None:
        yield None
        return
    from langfuse import propagate_attributes

    with _client.start_as_current_observation(as_type="span", name=name, input=message) as span:
        with propagate_attributes(user_id=user_id, session_id=session_id, as_baggage=True):
            with propagate_attributes(
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

    Raw OTel attribute writes (like `stamp_langfuse_turn_session`), NOT
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


#: Langfuse's own baggage entry for "this trace already has an application root
#: upstream". The receiving SDK compares it to the trace id of every span it
#: starts and skips its own app-root claim when they match
#: (`_client/span_processor.py::_mark_app_root_candidate`,
#: `suppressed_by_parent_claim`) — without it a joined leaf would open a SECOND
#: root observation on the same trace. Pinned against the SDK constant by
#: test_observability.py so a langfuse bump fails loudly here.
_LANGFUSE_TRACE_ID_BAGGAGE_KEY = "langfuse_trace_id"

_TRACEPARENT_HEADER = b"traceparent"


def trace_context_carrier() -> dict[str, str]:
    """W3C trace context of the ACTIVE span, as a flat carrier dict — THE wire
    format for every cross-process hop we own (OBS4, see
    OBS4-TRACE-PROPAGATION-CONTRACT.md).

    Two call sites, both explicit: the A2A leg's outgoing HTTP headers, and the
    `_meta` field of an inline MCP `tools/call` (ADK's own McpToolset already
    does exactly this for the leaves' MCP calls — mcp_tool.py, `inject(carrier)`
    → `call_tool(meta=...)`, so this mirrors an existing wire format instead of
    inventing one). Deliberately NOT a global httpx instrumentation: baggage
    would then reach every third party (Mapbox) instead of only our own peers.

    Keys come from the global OTel propagator (`traceparent`, `tracestate` when
    an upstream set one, `baggage`), plus the Langfuse app-root claim (see
    `_LANGFUSE_TRACE_ID_BAGGAGE_KEY`). The SDK adds that claim itself whenever
    one of its own spans is active (the /v3 facade path); setting it here also
    covers the A2A-driven path, where only ADK spans exist.

    GDPR/security: this travels in plain HTTP headers, so it carries opaque
    identifiers ONLY — trace/span ids, the conversation's session id,
    `v3_<session id>`. Never message content, never a secret.

    Empty dict when tracing is disabled or no span is active; never raises."""
    if _client is None:
        return {}
    try:
        from opentelemetry import baggage, propagate, trace

        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            return {}
        context = baggage.set_baggage(
            _LANGFUSE_TRACE_ID_BAGGAGE_KEY, trace.format_trace_id(span_context.trace_id)
        )
        carrier: dict[str, str] = {}
        propagate.inject(carrier, context=context)
        return carrier
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("trace_context_carrier skipped", exc_info=True)
        return {}


class A2aTurnObservation:
    """Pure-ASGI wrapper for an A2A-served turn (BearerAuthMiddleware
    precedent): joins the caller's trace and opens the service's ROOT
    observation. Mounted on the two leaves' whole app, and on the concierge's
    A2A surface only (`/v3/*` has its own root, `turn_observation`).

    Why ASGI and not a before_agent_callback: the OTel context must be active
    BEFORE ADK creates its invocation span, or the served subtree already lives
    in a trace of its own and an observation opened with an explicit
    `trace_context=` would sit in a DIFFERENT trace than the ADK spans around
    it (3 traces per turn instead of 1). The A2A metadata channel that carries
    `dayuse_trace_id` is only readable at callback time — structurally too
    late; the W3C headers are readable here. Full reasoning and the proofs:
    OBS4-TRACE-PROPAGATION-CONTRACT.md §1.

    Called with NO upstream context (peer agent, eval battery, isolated smoke),
    nothing is attached and this observation is simply the root of a new trace:
    `stamp_a2a_turn` gives it the inbound request as input, so the trace stays
    named and readable instead of anonymous.

    Typed `span`, not `agent`: ADK 2.4.0 already types `invoke_agent <name>` as
    AGENT natively (OBS2 finding), and the concierge's own `v3.chat` root has
    the same shape — a second agent-typed node would just duplicate the node
    for that service in the Agent Graph.

    POSTs only: the agent-card GET must never open a trace."""

    def __init__(self, app: Any, *, name: str) -> None:
        self._app = app
        self._name = f"a2a.{name}"

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if _client is None or scope["type"] != "http" or scope.get("method") != "POST":
            await self._app(scope, receive, send)
            return
        token = _attach_upstream_trace_context(scope.get("headers") or [])
        try:
            with observation(as_type="span", name=self._name) as obs:
                reset = _a2a_root_observation.set(obs)
                try:
                    await self._app(scope, receive, send)
                finally:
                    _a2a_root_observation.reset(reset)
        finally:
            _detach_trace_context(token)


def _attach_upstream_trace_context(headers: Any) -> Any:
    """Makes the caller's W3C context (traceparent + baggage) current for this
    request; returns the detach token, None when there was nothing to attach.

    No traceparent → attach NOTHING rather than an empty extracted context:
    `propagate.extract` with no context builds a fresh one, and attaching that
    would wipe whatever is ambient instead of simply starting a new trace."""
    try:
        if not any(key == _TRACEPARENT_HEADER for key, _ in headers):
            return None
        from opentelemetry import context as otel_context
        from opentelemetry import propagate

        carrier = {key.decode("latin-1"): value.decode("latin-1") for key, value in headers}
        return otel_context.attach(propagate.extract(carrier))
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("upstream trace context not attached", exc_info=True)
        return None


def _detach_trace_context(token: Any) -> None:
    if token is None:
        return
    try:
        from opentelemetry import context as otel_context

        otel_context.detach(token)
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("trace context detach skipped", exc_info=True)


def mark_a2a_turn_output(text: str) -> None:
    """Sets the A2A root observation's OUTPUT — the turn's final answer, which
    is what becomes the trace output on the A2A-driven path (peer agents, eval
    battery, smoke). OBS1 left that path with no output at all.

    No-op, by design, on the /v3 facade path: `A2aTurnObservation` is not
    mounted there, so there is no A2A root observation and `facade.py` owns
    `v3.chat`'s own output. No-op when tracing is off; never raises."""
    if _client is None or not text:
        return
    try:
        root = _a2a_root_observation.get()
        if root is not None:
            root.update(output=text)
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("mark_a2a_turn_output skipped", exc_info=True)


def _stamp_root_observation_input(callback_context: Any) -> None:
    """Feeds the A2A root observation (opened by `A2aTurnObservation`) the
    inbound request text. No-op when there is none — which is exactly the /v3
    facade path, where `turn_observation` already set the input from the HTTP
    body and must stay the trace's input."""
    root = _a2a_root_observation.get()
    if root is None:
        return
    request_text = _content_text(getattr(callback_context, "user_content", None))
    if request_text:
        root.update(input=request_text)


def stamp_a2a_turn(callback_context: Any) -> None:
    """Leaf before_agent_callback — replaces OBS1's `stamp_langfuse_session`.

    Gives the leaf's root observation (opened by `A2aTurnObservation`) the
    inbound request as its INPUT: the root observation's input/output is what
    becomes the trace's input/output, which is what let the two trace-level
    enrichment attributes OBS1 stamped here (trace input, trace name) go — both
    are deprecated in Langfuse v4 (brief §12.4), and they were this codebase's
    only deprecated surface. `test_no_deprecated_trace_attributes.py` keeps them
    out for good; the name now comes from the root observation itself.

    `langfuse.session.id` from the inbound A2A `dayuse_trace_id`: on a joined
    trace the concierge already propagated the same value in baggage (idempotent
    write), and on a direct call it is what keeps the leaf's own trace in the
    Sessions view — falling back to the leaf's own ADK session id when the
    caller sends no fleet metadata.

    Enrichment only: never raises, always returns None so the ADK callback
    chain continues."""
    if _client is None:
        return None
    try:
        from opentelemetry import trace

        run_config = getattr(callback_context, "run_config", None)
        meta = (getattr(run_config, "custom_metadata", None) or {}).get("a2a_metadata") or {}
        session_id = meta.get("dayuse_trace_id")
        if not (isinstance(session_id, str) and session_id):
            # Direct A2A caller without fleet metadata: group by own session.
            session_id = getattr(getattr(callback_context, "session", None), "id", None)
        if isinstance(session_id, str) and session_id:
            trace.get_current_span().set_attribute("langfuse.session.id", session_id)
        _stamp_root_observation_input(callback_context)
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("stamp_a2a_turn skipped", exc_info=True)
    return None


def stamp_langfuse_turn_session(callback_context: Any) -> None:
    """Concierge before_agent_callback: stamp session + user on the trace, so
    A2A-driven turns (peer agents, eval battery, smoke) land in the Sessions
    view too. The /v3 facade path sets the same values via turn_observation —
    same session id (the ADK session id IS the facade session id), so the
    double write is idempotent.

    KEPT by OBS4 (which removed its leaf sibling `stamp_langfuse_session`): this
    is still the only thing that puts session + user on an A2A-driven concierge
    turn, where there is no `turn_observation`. It writes no deprecated
    attribute — session/user are first-class in v4.

    It also feeds the A2A root observation its input, which on that path is the
    ONLY input the trace gets (OBS1 deliberately left it empty). No-op on the
    facade path: `A2aTurnObservation` is mounted on the concierge's A2A surface
    only, so `/v3/*` keeps `v3.chat`'s own input."""
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
        _stamp_root_observation_input(callback_context)
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("stamp_langfuse_turn_session skipped", exc_info=True)
    return None


def _content_text(content: Any) -> str:
    """Text parts of a genai Content, joined — empty string when none."""
    parts = getattr(content, "parts", None) or []
    texts = [t for t in (getattr(p, "text", None) for p in parts) if isinstance(t, str) and t]
    return "\n".join(texts)
