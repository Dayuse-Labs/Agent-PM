"""D — prod 2026-10-26: six turns with `output: null` in Langfuse.

The concierge logs of each show the same thing: the turn finished
(`concierge_metric=turn ... status=ok`), then `socket.send() raised exception.`
once per `token` frame — the client had gone (in one case the mobile app's
WebView reloaded mid-turn). Starlette, under uvicorn's ASGI 2.3, cancels the
response on the disconnect and the facade's SSE generator is closed at the
`yield` it was paused on, before `lf_span.update(output=…)` and before the turn
was logged. The answer existed; the trace said there was none.

The fix records it: the rest of the spine's events (already computed) are
drained, the turn is logged, and the trace carries the answer plus
`client_disconnected`. Offline: recording Langfuse client, stub spine.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from starlette.requests import Request

import b2c_concierge.facade as facade
from b2c_common import observability

_FINAL = "For New York on Thursday, here are five day-use options near JFK."
_CHUNKS = ["For New York on Thursday, ", "here are five day-use ", "options near JFK."]


class _Span:
    trace_id = "b" * 32

    def __init__(self):
        self.updates: list[dict] = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class _Client:
    def __init__(self):
        self.span = _Span()

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        yield self.span

    def create_score(self, **kwargs):
        pass


@pytest.fixture
def stream(monkeypatch):
    client = _Client()
    monkeypatch.setattr(observability, "_client", client)

    @contextmanager
    def _propagate(**kwargs):
        yield

    import langfuse
    import opentelemetry.trace

    monkeypatch.setattr(langfuse, "propagate_attributes", _propagate)
    monkeypatch.setattr(opentelemetry.trace, "get_current_span",
                        lambda: SimpleNamespace(set_attribute=lambda *a: None))

    finalized: list[dict] = []
    spine = SimpleNamespace(finished=False)

    async def _session(session_id, user_id):
        return SimpleNamespace(events=[])

    async def _native(session_id, body, turn_index):
        return None

    async def _drive(session_id, user_id, message):
        # The spine's order (agent.py): progress, hotels, the answer's chunks,
        # the final text, the turn facts.
        yield ("progress", {})
        yield ("hotels", {"hotels": [{"id": 1, "name": "Hampton Inn NY-JFK"}]})
        for chunk in _CHUNKS:
            yield ("token", chunk)
        yield ("final", _FINAL)
        spine.finished = True

    async def _finalize(**kwargs):
        finalized.append(kwargs)
        return {"response": kwargs["final_text"]}

    monkeypatch.setattr(facade, "_get_or_create_session", _session)
    monkeypatch.setattr(facade, "_apply_native_context", _native)
    monkeypatch.setattr(facade, "_drive", _drive)
    monkeypatch.setattr(facade, "_finalize", _finalize)
    return SimpleNamespace(span=client.span, finalized=finalized, spine=spine)


def _request() -> Request:
    body = json.dumps({"message": "Need a day use near JFK", "locale": "en"}).encode()
    scope = {"type": "http", "method": "POST", "path": "/v3/chat/stream",
             "headers": [(b"x-client-session-id", b"sess-gone")], "query_string": b""}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


async def _read_then_leave(frames_before_leaving: int) -> list[bytes]:
    """Reads the SSE body like a client, then disconnects: the generator is
    closed at the `yield` it is paused on, as Starlette leaves it."""
    response = await facade.chat_stream(_request())
    body = response.body_iterator
    seen = []
    for _ in range(frames_before_leaving):
        seen.append(await body.__anext__())
    await body.aclose()
    return seen


class TestTheClientLeavesDuringTheAnswer:
    def test_the_trace_keeps_the_answer_and_says_the_client_left(self, stream, caplog):
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            seen = asyncio.run(_read_then_leave(3))  # progress, hotels, first token

        assert b"event: token" in seen[-1]
        assert stream.span.updates, "nothing recorded on the trace"
        update = stream.span.updates[-1]
        assert update["output"] == _FINAL
        assert update["metadata"] == {"client_disconnected": "true", "client_disconnected_at": "token"}
        assert update["level"] == "WARNING"
        assert any("concierge_metric=stream_client_gone stage=token" in r.getMessage()
                   for r in caplog.records)

    def test_the_turn_is_still_logged(self, stream):
        asyncio.run(_read_then_leave(3))

        assert stream.spine.finished
        assert [f["final_text"] for f in stream.finalized] == [_FINAL]

    def test_a_client_that_stays_gets_done_and_no_disconnect_mark(self, stream):
        # Negative control: the whole stream read — one `done`, the plain
        # output update, no disconnect metadata.
        async def read_all():
            response = await facade.chat_stream(_request())
            return [chunk async for chunk in response.body_iterator]

        frames = asyncio.run(read_all())

        assert frames[-1].startswith(b"event: done")
        assert stream.span.updates == [{"output": _FINAL}]
        assert len(stream.finalized) == 1
