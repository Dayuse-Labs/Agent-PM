"""The public edge is protected (scripts/run_widget_proxy.py).

The widget proxy is the only public service and adds the facade key itself:
whatever reaches it reaches the LLMs. agent-usa, which it replaces on
ai.dayuse.com, had flask-limiter (20 chat turns/min/IP), Talisman headers +
CSP and a 500-char message cap. These tests pin the stdlib equivalent.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_widget_proxy.py"
_spec = importlib.util.spec_from_file_location("run_widget_proxy_protection", _SCRIPT)
assert _spec is not None and _spec.loader is not None
wp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wp)


class _Headers(dict):
    def get(self, key, default=None):  # noqa: ANN001
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


def _post(path: str, body: dict | None = None, headers: dict | None = None, ip: str = "203.0.113.7"):
    """Run do_POST on a hand-built handler; returns (status, response headers,
    response body, forwarded body or None when nothing was proxied)."""
    raw = json.dumps(body).encode() if body is not None else b""
    handler = wp.WidgetProxyHandler.__new__(wp.WidgetProxyHandler)
    handler.path = path
    handler.client_address = (ip, 1234)
    handler.headers = _Headers(
        {"Host": "ai.dayuse.com", "Content-Length": str(len(raw)), "X-Real-IP": ip, **(headers or {})}
    )
    handler.rfile = io.BytesIO(raw)
    out: dict = {"status": None, "headers": {}, "forwarded": None}
    written = bytearray()
    handler.wfile = type("W", (), {"write": lambda self, b: written.extend(b), "flush": lambda self: None})()
    handler.send_response = lambda code, *a: out.__setitem__("status", code)  # noqa: ARG005
    handler.send_header = lambda k, v: out["headers"].__setitem__(k, v)
    handler.send_error = lambda code, *a, **k: out.__setitem__("status", code)  # noqa: ARG005
    handler.end_headers = lambda: None

    def fake_proxy(method, body=None):  # noqa: ANN001
        out["status"], out["forwarded"] = 200, body if body is not None else b""

    handler._proxy = fake_proxy
    handler.do_POST()
    return out["status"], out["headers"], bytes(written), out["forwarded"]


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(wp, "_LIMITER", wp.SlidingWindowLimiter())
    for var in ("WIDGET_CHAT_PER_MINUTE", "WIDGET_CHAT_PER_HOUR", "WIDGET_ALLOWED_ORIGINS",
                "WIDGET_CLIENT_IP_HEADER", "WIDGET_CSP_MODE", "WIDGET_MAX_MESSAGE_CHARS"):
        monkeypatch.delenv(var, raising=False)


_TURN = {"message": "un day use à Paris demain"}
_SAME_ORIGIN = {"Origin": "https://ai.dayuse.com", "Sec-Fetch-Site": "same-origin"}


class TestRateLimit:
    def test_twenty_turns_a_minute_then_429(self):
        statuses = [_post("/v3/chat", _TURN, _SAME_ORIGIN)[0] for _ in range(21)]
        assert statuses[:20] == [200] * 20
        status, headers, body, forwarded = _post("/v3/chat", _TURN, _SAME_ORIGIN)
        assert status == 429 and forwarded is None
        assert int(headers["Retry-After"]) >= 1
        assert json.loads(body) == {"error": "rate_limited"}

    def test_json_and_stream_share_one_budget(self, monkeypatch):
        monkeypatch.setenv("WIDGET_CHAT_PER_MINUTE", "2")
        assert _post("/v3/chat", _TURN)[0] == 200
        assert _post("/v3/chat/stream", _TURN)[0] == 200
        assert _post("/v3/chat/stream", _TURN)[0] == 429

    def test_the_budget_is_per_visitor(self, monkeypatch):
        monkeypatch.setenv("WIDGET_CHAT_PER_MINUTE", "1")
        assert _post("/v3/chat", _TURN, ip="203.0.113.1")[0] == 200
        assert _post("/v3/chat", _TURN, ip="203.0.113.2")[0] == 200
        assert _post("/v3/chat", _TURN, ip="203.0.113.1")[0] == 429

    def test_the_window_slides(self):
        limiter = wp.SlidingWindowLimiter()
        assert limiter.hit("k", [(1, 60.0)], now=0.0) == 0
        assert limiter.hit("k", [(1, 60.0)], now=30.0) == pytest.approx(30.0)
        assert limiter.hit("k", [(1, 60.0)], now=60.0) == 0

    def test_a_disabled_window_never_limits(self):
        limiter = wp.SlidingWindowLimiter()
        assert all(limiter.hit("k", [(0, 60.0)]) == 0 for _ in range(100))


class TestClientIp:
    def test_the_edge_header_wins(self):
        assert wp.client_ip(_Headers({"X-Real-IP": "1.1.1.1", "X-Forwarded-For": "9.9.9.9"}), "10.0.0.1") == "1.1.1.1"

    def test_a_forged_leftmost_forwarded_for_is_ignored(self):
        headers = _Headers({"X-Forwarded-For": "6.6.6.6, 2.2.2.2"})
        assert wp.client_ip(headers, "10.0.0.1") == "2.2.2.2"

    def test_no_header_falls_back_to_the_peer(self):
        assert wp.client_ip(_Headers(), "10.0.0.1") == "10.0.0.1"


class TestCrossSite:
    def test_another_site_cannot_drive_the_agent(self):
        status, _, _, forwarded = _post("/v3/chat", _TURN, {"Origin": "https://evil.example"})
        assert status == 403 and forwarded is None

    def test_sec_fetch_site_cross_site_is_refused(self):
        assert _post("/v3/chat", _TURN, {"Sec-Fetch-Site": "cross-site"})[0] == 403

    def test_the_forwarded_host_counts_as_own(self):
        headers = {"Origin": "https://ai.dayuse.com", "Host": "widget.railway.internal",
                   "X-Forwarded-Host": "ai.dayuse.com"}
        assert _post("/v3/chat", _TURN, headers)[0] == 200

    def test_an_allowed_origin_passes(self, monkeypatch):
        monkeypatch.setenv("WIDGET_ALLOWED_ORIGINS", "https://widget-production-3f56.up.railway.app")
        headers = {"Origin": "https://widget-production-3f56.up.railway.app"}
        assert _post("/v3/chat", _TURN, headers)[0] == 200

    def test_no_origin_is_not_a_browser_and_is_left_to_the_rate_limit(self):
        assert _post("/v3/chat", _TURN, {})[0] == 200


class TestPayload:
    def test_a_message_over_500_chars_never_reaches_the_concierge(self):
        status, _, body, forwarded = _post("/v3/chat", {"message": "x" * 501})
        assert status == 413 and forwarded is None
        assert json.loads(body) == {"error": "message_too_long"}

    def test_500_chars_pass_and_the_body_is_forwarded_untouched(self):
        status, _, _, forwarded = _post("/v3/chat", {"message": "x" * 500})
        assert status == 200 and json.loads(forwarded) == {"message": "x" * 500}

    def test_an_oversized_body_is_refused(self):
        status, _, _, forwarded = _post("/v3/feedback", {"comment": "y" * 20000})
        assert status == 413 and forwarded is None


class TestRoutes:
    @pytest.mark.parametrize("path", ["/v3/chat/logs", "/v3/chat/welcome", "/v3/anything", "/a2a"])
    def test_only_the_facade_routes_are_forwarded(self, path):
        status, _, _, forwarded = _post(path, _TURN)
        assert status == 404 and forwarded is None

    @pytest.mark.parametrize("path", ["/v3/chat/session/reset", "/v3/feedback"])
    def test_the_other_facade_routes_are_forwarded(self, path):
        assert _post(path, {})[0] == 200

    def test_get_on_v3_is_not_forwarded(self):
        handler = wp.WidgetProxyHandler.__new__(wp.WidgetProxyHandler)
        handler.path = "/v3/chat"
        errors: list[int] = []
        handler.send_error = lambda code, *a, **k: errors.append(code)
        handler._proxy = lambda *a, **k: pytest.fail("GET /v3 was proxied")
        handler.do_GET()
        assert errors == [404]

    def test_a_csp_report_is_accepted_and_not_forwarded(self):
        status, _, _, forwarded = _post("/csp-report", {"csp-report": {"blocked-uri": "x"}})
        assert status == 204 and forwarded is None


class TestSecurityHeaders:
    def test_baseline_headers(self):
        names = dict(wp.security_headers())
        assert names["X-Content-Type-Options"] == "nosniff"
        assert names["X-Frame-Options"] == "DENY"
        assert "max-age=" in names["Strict-Transport-Security"]

    def test_csp_is_report_only_by_default(self):
        names = dict(wp.security_headers())
        assert "Content-Security-Policy" not in names
        assert "frame-ancestors 'none'" in names["Content-Security-Policy-Report-Only"]
        assert "report-uri /csp-report" in names["Content-Security-Policy-Report-Only"]

    def test_csp_can_be_enforced(self, monkeypatch):
        monkeypatch.setenv("WIDGET_CSP_MODE", "enforce")
        names = dict(wp.security_headers())
        assert "Content-Security-Policy-Report-Only" not in names
        assert "default-src 'self'" in names["Content-Security-Policy"]
        # enforced, a block must still reach the logs
        assert "report-uri /csp-report" in names["Content-Security-Policy"]

    def test_every_response_carries_them(self):
        handler = wp.WidgetProxyHandler.__new__(wp.WidgetProxyHandler)
        handler.request_version = "HTTP/1.1"
        handler._headers_buffer = []
        handler.wfile = io.BytesIO()
        handler.end_headers()
        assert b"X-Content-Type-Options: nosniff" in handler.wfile.getvalue()

    def test_no_python_version_banner(self):
        assert wp.WidgetProxyHandler.server_version == "widget"
        assert wp.WidgetProxyHandler.sys_version == ""
