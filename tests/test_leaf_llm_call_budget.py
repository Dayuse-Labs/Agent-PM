"""The leaves' LLM calls are bounded, and the concierge waits for the bound
(prod session 7e296e4b, 2026-10-27).

The search leaf's LLM call had no timeout: the OpenAI SDK waited up to 600 s
(two prod calls hung 604 s that day), and a 34.7 s one outlived the concierge's
30 s deadline — the user read « I can't reach the hotel search ».

Each leaf now passes `LLM_CALL_KWARGS` to its `LiteLlm`. Proven here on the real
path — ADK `LiteLlm` -> `litellm.acompletion` -> OpenAI SDK — against a local
socket, with the leaf's own kwargs and only the timeout shortened:
- a request that never answers is sent twice, a full timeout apart, then fails;
- a 400 is sent once (a relaunch cannot fix it).
`num_retries=1` would have sent 3: litellm 1.90.2 also hands it to the SDK as
`max_retries` (probed 2026-10-28).
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import litellm
import pytest
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from b2c_concierge.agent import _leaf_timeout
from b2c_concierge.routing import LEAF_FAQ, LEAF_HOTEL_SEARCH
from b2c_concierge.triage import _TRIAGE_ATTEMPTS, _TRIAGE_TIMEOUT
from faq_agent import agent as faq_agent
from hotel_search_agent import agent as search_agent

_LEAVES = [pytest.param(search_agent, id="search"), pytest.param(faq_agent, id="faq")]

_BAD_REQUEST_BODY = json.dumps(
    {"error": {"message": "bad", "type": "invalid_request_error", "param": None, "code": None}}
).encode()
_BAD_REQUEST = (
    b"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\n"
    b"Content-Length: " + str(len(_BAD_REQUEST_BODY)).encode() + b"\r\n"
    b"Connection: close\r\n\r\n" + _BAD_REQUEST_BODY
)


class _LocalServer:
    """Accepts every connection and counts the POSTs; answers each one with
    `reply`, or never when `reply` is None."""

    def __init__(self, reply: bytes | None) -> None:
        self.reply = reply
        self.posts: list[float] = []
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self._conns: list[socket.socket] = []
        threading.Thread(target=self._accept, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._sock.getsockname()[1]}/v1"

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            self._conns.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        while True:
            try:
                data = conn.recv(65536)
            except OSError:
                return
            if not data:
                return
            if b"POST " in data:
                self.posts.append(time.monotonic())
                if self.reply is not None:
                    conn.sendall(self.reply)
                    conn.close()
                    return

    def close(self) -> None:
        for conn in [self._sock, *self._conns]:
            conn.close()


def _call(leaf, server: _LocalServer, timeout: float) -> tuple[BaseException, float]:
    """One leaf LLM call with the leaf's own kwargs, `timeout` shortened."""
    model = LiteLlm(
        model=leaf.MODEL.model,
        **{**leaf.MODEL._additional_args, "timeout": timeout},
        api_base=server.url,
        api_key="test-key",
    )
    request = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="hi")])])

    async def run() -> None:
        async for _ in model.generate_content_async(request):
            pass

    t0 = time.monotonic()
    with pytest.raises(Exception) as raised:
        asyncio.run(run())
    return raised.value, t0


@pytest.mark.parametrize("leaf", _LEAVES)
def test_a_call_that_never_answers_is_relaunched_once_then_fails(leaf):
    server = _LocalServer(reply=None)
    try:
        error, _ = _call(leaf, server, timeout=0.3)
    finally:
        server.close()

    assert isinstance(error, litellm.Timeout)
    assert len(server.posts) == 2
    # The relaunch waited out a full timeout: it is LiteLLM's, not an SDK retry.
    assert server.posts[1] - server.posts[0] >= 0.3


@pytest.mark.parametrize("leaf", _LEAVES)
def test_a_bad_request_is_never_relaunched(leaf):
    server = _LocalServer(reply=_BAD_REQUEST)
    try:
        error, _ = _call(leaf, server, timeout=2.0)
    finally:
        server.close()

    assert isinstance(error, litellm.BadRequestError)
    assert len(server.posts) == 1


class TestTheConciergeWaitsForTheBound:
    """The concierge's leaf budget holds a stuck call and its relaunch, both at
    T, plus the leaf's tools — and still fits the widget proxy's 60 s silence
    window. Shorter T would cut the slow episodes (calls of 12-18 s that answer)."""

    _MAPBOX_WORST = 2 * 1.5  # 1.5 s + 1 retry (geocode_tool)
    _PROXY_SILENCE_LIMIT = 60.0  # scripts/run_widget_proxy.py, urlopen(timeout=60)

    @staticmethod
    def _defaults(monkeypatch):
        for name in (
            "CONCIERGE_LEAF_TIMEOUT_SECONDS",
            "CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS",
            "CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS",
        ):
            monkeypatch.delenv(name, raising=False)

    def test_search_covers_a_stuck_call_and_its_relaunch(self, monkeypatch):
        self._defaults(monkeypatch)
        t = search_agent.LLM_CALL_KWARGS["timeout"]
        mcp = search_agent.build_connection_params().timeout
        assert _leaf_timeout(LEAF_HOTEL_SEARCH) >= 2 * t + self._MAPBOX_WORST + mcp

    def test_faq_covers_a_stuck_call_and_its_relaunch(self, monkeypatch):
        self._defaults(monkeypatch)
        t = faq_agent.LLM_CALL_KWARGS["timeout"]
        mcp = faq_agent.build_connection_params().timeout
        assert _leaf_timeout(LEAF_FAQ) >= 2 * t + mcp

    def test_triage_and_leaf_stay_under_the_proxy_silence_limit(self, monkeypatch):
        # A `progress` frame follows every leaf call (agent.py), so the
        # synthesis opens a silence window of its own.
        self._defaults(monkeypatch)
        longest_leaf = max(_leaf_timeout(LEAF_HOTEL_SEARCH), _leaf_timeout(LEAF_FAQ))
        assert _TRIAGE_ATTEMPTS * _TRIAGE_TIMEOUT + longest_leaf < self._PROXY_SILENCE_LIMIT
