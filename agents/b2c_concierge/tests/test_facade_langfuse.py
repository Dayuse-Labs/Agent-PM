"""Langfuse turn observation on the /v3 facade (OBS1).

The audit contract, pinned with a duck-typed recording client (no langfuse
dep, no network): one root observation per turn, input = the user message,
output = the final text, session/user/tags propagated — and the `synthetic`
tag mirrors X-Dayuse-Synthetic. The suite-wide default (no LANGFUSE_* keys)
already regression-tests the disabled path everywhere else.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import b2c_concierge.facade as facade
from b2c_common import observability
from starlette.requests import Request

_SESSION_ID = "sess-langfuse-test"
_MESSAGE = "je cherche un hôtel à Lyon"
_FINAL = "Voici trois hôtels à Lyon."


class _RecordingSpan:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class _RecordingClient:
    def __init__(self) -> None:
        self.observations: list[dict] = []
        self.span = _RecordingSpan()

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        self.observations.append(kwargs)
        yield self.span


class _AmbientSpan:
    """Stands in for `opentelemetry.trace.get_current_span()` — OBS2's
    `mark_level`/`mark_metadata` write RAW attributes here (never through
    the langfuse client's `update_current_span`, which would mis-type an
    ADK-native span — see observability.py's docstring)."""

    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


def _make_request(headers: dict[str, str] | None = None) -> Request:
    body = json.dumps({"message": _MESSAGE, "locale": "fr"}).encode()
    all_headers = {"X-Client-Session-Id": _SESSION_ID, **(headers or {})}
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v3/chat",
        "headers": [(k.lower().encode(), v.encode()) for k, v in all_headers.items()],
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.fixture()
def recording(monkeypatch):
    """Recording langfuse client + a spine stub: no runner, no LLM, offline."""
    client = _RecordingClient()
    monkeypatch.setattr(observability, "_client", client)

    propagated: list[dict] = []

    @contextmanager
    def _propagate(**kwargs):
        propagated.append(kwargs)
        yield

    import langfuse

    monkeypatch.setattr(langfuse, "propagate_attributes", _propagate)

    ambient_span = _AmbientSpan()
    import opentelemetry.trace

    monkeypatch.setattr(opentelemetry.trace, "get_current_span", lambda: ambient_span)

    async def _session(session_id, user_id):
        return SimpleNamespace(events=[])

    async def _native(session_id, body, turn_index):
        return None

    async def _drive(session_id, user_id, message):
        yield ("progress", {})
        yield ("final", _FINAL)

    async def _finalize(**kwargs):
        return {"response": kwargs["final_text"], "session_id": kwargs["session_id"]}

    monkeypatch.setattr(facade, "_get_or_create_session", _session)
    monkeypatch.setattr(facade, "_apply_native_context", _native)
    monkeypatch.setattr(facade, "_drive", _drive)
    monkeypatch.setattr(facade, "_finalize", _finalize)
    return client, propagated, ambient_span


class TestChatTurnObservation:
    def test_root_observation_carries_input_output_and_attributes(self, recording):
        client, propagated, _ambient_span = recording
        response = asyncio.run(facade.chat(_make_request()))
        assert response.status_code == 200

        assert len(client.observations) == 1
        obs = client.observations[0]
        assert obs["name"] == "v3.chat"
        assert obs["as_type"] == "span"
        assert obs["input"] == _MESSAGE
        assert client.span.updates == [{"output": _FINAL}]

        # OBS4: two nested calls, because `as_baggage` is per-CALL, not
        # per-field — see the next test class for what that buys.
        assert len(propagated) == 2
        identity, local = propagated
        assert identity["session_id"] == _SESSION_ID
        assert identity["user_id"] == f"v3_{_SESSION_ID}"
        assert local["tags"] == []
        assert local["metadata"]["locale"] == "fr"
        assert local["metadata"]["turn_index"] == "0"

    def test_synthetic_header_becomes_the_synthetic_tag(self, recording):
        client, propagated, _ambient_span = recording
        asyncio.run(facade.chat(_make_request({"X-Dayuse-Synthetic": "true"})))
        assert propagated[1]["tags"] == ["synthetic"]


class TestObs4BaggageCarriesOpaqueIdentifiersOnly:
    """OBS4 security lock. `as_baggage=True` puts values in the HTTP headers of
    every outgoing request made inside the context, so ONLY opaque identifiers
    may ride it (session id, `v3_<session id>`). The turn's tags and metadata —
    locale, currency, domain, turn_index — must stay in-process, which is why
    `turn_observation` nests a SECOND `propagate_attributes` without baggage."""

    def test_only_session_and_user_travel_in_baggage(self, recording):
        _client, propagated, _ambient_span = recording
        asyncio.run(facade.chat(_make_request({"X-Dayuse-Synthetic": "true"})))

        on_the_wire = [attrs for attrs in propagated if attrs.get("as_baggage")]
        assert len(on_the_wire) == 1
        assert set(on_the_wire[0]) == {"session_id", "user_id", "as_baggage"}

        stays_local = [attrs for attrs in propagated if not attrs.get("as_baggage")]
        assert len(stays_local) == 1
        assert set(stays_local[0]) == {"tags", "metadata"}

    def test_the_message_never_reaches_the_baggage_call(self, recording):
        """The GDPR line: message content goes to the trace (sanctioned audit
        channel), never into a header a third party could ever see."""
        _client, propagated, _ambient_span = recording
        asyncio.run(facade.chat(_make_request()))
        wire_values = [
            str(value)
            for attrs in propagated
            if attrs.get("as_baggage")
            for value in attrs.values()
        ]
        assert all(_MESSAGE not in value for value in wire_values)

    def test_chat_stream_sets_output_before_the_done_frame(self, recording):
        client, propagated, _ambient_span = recording

        async def _consume() -> bytes:
            response = await facade.chat_stream(_make_request())
            chunks = [chunk async for chunk in response.body_iterator]
            return b"".join(
                c if isinstance(c, bytes) else c.encode() for c in chunks
            )

        raw = asyncio.run(_consume())
        assert b"event: done" in raw
        assert client.observations[0]["name"] == "v3.chat_stream"
        assert client.observations[0]["input"] == _MESSAGE
        assert client.span.updates == [{"output": _FINAL}]

    def test_progress_frame_records_a_ttft_metadata_point(self, recording):
        """OBS2: the `progress` frame is the TTFT marker (CLAUDE.md SLO) — the
        measurement point is positioned here as RAW ambient-span metadata
        (never through the langfuse client, which would mis-type an
        ADK-native span — see observability.mark_metadata's docstring). The
        score itself (OBS3) doesn't exist yet."""
        _client, _propagated, ambient_span = recording

        async def _consume() -> None:
            response = await facade.chat_stream(_make_request())
            async for _ in response.body_iterator:
                pass

        asyncio.run(_consume())
        assert "langfuse.observation.metadata.ttft_ms" in ambient_span.attributes
        assert float(ambient_span.attributes["langfuse.observation.metadata.ttft_ms"]) >= 0


class TestFacadeShieldMarksError:
    def test_marks_error_on_the_span_before_it_closes(self, recording, monkeypatch):
        """OBS2: the shield fires OUTSIDE the `with turn_observation` block —
        by then the span is already closed, so the ERROR must be recorded
        from INSIDE the block, on the RAW ambient span, before the exception
        unwinds it (never through the langfuse client — see
        observability.mark_level's docstring)."""
        _client, _propagated, ambient_span = recording

        async def _boom(**_kwargs):
            raise RuntimeError("synthesis exploded")

        monkeypatch.setattr(facade, "_finalize", _boom)
        response = asyncio.run(facade.chat(_make_request()))
        assert response.status_code == 200  # the shield still returns a contract payload
        assert ambient_span.attributes["langfuse.observation.level"] == "ERROR"
        assert ambient_span.attributes["langfuse.observation.status_message"] == "facade_shield"
