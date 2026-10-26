"""agent-usa's health probes survive the switch of ai.dayuse.com (scripts/run_widget_proxy.py).

agent-usa answered /health (Innovation Monitor: always 200, criticality in
`status`, Bearer HEALTH_TOKEN when set), /healthz and /readyz on that host. The
widget proxy takes the host over, so it answers them with the same keys; the one
dependency it checks is the concierge, through its open agent card.
"""
from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_widget_proxy.py"
_spec = importlib.util.spec_from_file_location("run_widget_proxy_health", _SCRIPT)
assert _spec is not None and _spec.loader is not None
wp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wp)

_REAL_PROBE = wp.concierge_reachable
_CONCIERGE = {"up": True}


def _get(path: str, headers: dict | None = None, concierge_up: bool = True):
    """Run do_GET on a hand-built handler; returns (status, response headers, JSON body)."""
    handler = wp.WidgetProxyHandler.__new__(wp.WidgetProxyHandler)
    handler.path = path
    handler.backend = "http://concierge.test:8100"
    handler.headers = {**(headers or {})}
    out: dict = {"status": None, "headers": {}}
    written = bytearray()
    handler.wfile = type("W", (), {"write": lambda self, b: written.extend(b)})()
    handler.send_response = lambda code, *a: out.__setitem__("status", code)  # noqa: ARG005
    handler.send_header = lambda k, v: out["headers"].__setitem__(k, v)
    handler.end_headers = lambda: None
    handler._proxy = lambda *a, **k: pytest.fail(f"{path} was proxied")
    _CONCIERGE["up"] = concierge_up
    handler.do_GET()
    return out["status"], out["headers"], json.loads(bytes(written))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for var in ("HEALTH_TOKEN", "LANGFUSE_RELEASE", "RAILWAY_ENVIRONMENT_NAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(wp, "concierge_reachable", lambda backend: _CONCIERGE["up"])  # noqa: ARG005


class TestHealthz:
    def test_liveness_never_probes_the_concierge(self):
        status, _, body = _get("/healthz", concierge_up=False)
        assert status == 200 and body == {"status": "healthy", "service": "dayuse-search"}


class TestReadyz:
    def test_ready_when_the_concierge_answers(self):
        status, _, body = _get("/readyz")
        assert status == 200 and body["status"] == "ready"
        assert body["checks"] == {"concierge": {"healthy": True}}

    def test_503_when_it_does_not(self):
        status, _, body = _get("/readyz", concierge_up=False)
        assert status == 503 and body["status"] == "not_ready"


class TestHealth:
    def test_innovation_monitor_contract(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_RELEASE", "68e0f75")
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        status, headers, body = _get("/health")
        assert status == 200 and headers["Cache-Control"] == "no-store"
        assert body == {
            "service": "dayuse-search", "status": "ok", "version": "68e0f75", "env": "production",
            "dependencies": [{"name": "concierge", "critical": True, "status": "ok"}],
        }

    def test_a_down_concierge_is_critical_but_still_200(self):
        status, _, body = _get("/health", concierge_up=False)
        assert status == 200 and body["status"] == "critical"
        assert body["dependencies"][0]["status"] == "down"

    def test_the_token_is_required_once_set(self, monkeypatch):
        monkeypatch.setenv("HEALTH_TOKEN", "s3cret")
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "s3cret"}):
            status, resp_headers, _ = _get("/health", headers)
            assert status == 401 and resp_headers["WWW-Authenticate"] == "Bearer"
        assert _get("/health", {"Authorization": "Bearer s3cret"})[0] == 200

    def test_the_token_never_guards_the_k8s_probes(self, monkeypatch):
        monkeypatch.setenv("HEALTH_TOKEN", "s3cret")
        assert _get("/healthz")[0] == 200 and _get("/readyz")[0] == 200


class TestConciergeProbe:
    """The real probe, against a real socket."""

    @staticmethod
    def _serve(status: int):
        class Card(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(status if self.path == "/.well-known/agent-card.json" else 404)
                self.end_headers()

            def log_message(self, *a):  # noqa: ANN002
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Card)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def test_an_agent_card_means_up(self):
        server = self._serve(200)
        try:
            assert _REAL_PROBE(f"http://127.0.0.1:{server.server_port}") is True
        finally:
            server.shutdown()

    def test_an_error_status_means_down(self):
        server = self._serve(500)
        try:
            assert _REAL_PROBE(f"http://127.0.0.1:{server.server_port}") is False
        finally:
            server.shutdown()

    def test_nothing_listening_means_down(self):
        server = self._serve(200)
        port = server.server_port
        server.shutdown()
        server.server_close()
        assert _REAL_PROBE(f"http://127.0.0.1:{port}") is False
