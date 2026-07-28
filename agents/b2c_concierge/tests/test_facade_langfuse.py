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
    return client, propagated


class TestChatTurnObservation:
    def test_root_observation_carries_input_output_and_attributes(self, recording):
        client, propagated = recording
        response = asyncio.run(facade.chat(_make_request()))
        assert response.status_code == 200

        assert len(client.observations) == 1
        obs = client.observations[0]
        assert obs["name"] == "v3.chat"
        assert obs["as_type"] == "span"
        assert obs["input"] == _MESSAGE
        assert client.span.updates == [{"output": _FINAL}]

        assert len(propagated) == 1
        attrs = propagated[0]
        assert attrs["session_id"] == _SESSION_ID
        assert attrs["user_id"] == f"v3_{_SESSION_ID}"
        assert attrs["tags"] == []
        assert attrs["metadata"]["locale"] == "fr"
        assert attrs["metadata"]["turn_index"] == "0"

    def test_synthetic_header_becomes_the_synthetic_tag(self, recording):
        client, propagated = recording
        asyncio.run(facade.chat(_make_request({"X-Dayuse-Synthetic": "true"})))
        assert propagated[0]["tags"] == ["synthetic"]

    def test_chat_stream_sets_output_before_the_done_frame(self, recording):
        client, propagated = recording

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
