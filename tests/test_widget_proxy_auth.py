"""Offline tests for the widget proxy's server-side injection of the facade's
internal API key (scripts/run_widget_proxy.py::_proxy).

Why this matters: the concierge facade gates /v3 on `CHAT_API_KEY` in
`CHAT_API_KEY_HEADER` (b2c_concierge/facade.py::_api_key_error). A browser
cannot hold that secret, so the proxy must add it. If it ever stopped, every
widget turn against a gated facade would 401 — the demo would be dead with no
test to catch it.

No network: `_proxy` is exercised with a fake upstream (urlopen monkeypatched)
and a hand-built handler, so we assert on the outgoing `urllib` Request.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_widget_proxy.py"
_spec = importlib.util.spec_from_file_location("run_widget_proxy", _SCRIPT)
assert _spec is not None and _spec.loader is not None
wp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wp)


class _Headers(dict):
    """Case-insensitive-enough stand-in for http.client.HTTPMessage: the proxy
    only calls .get() and .items() on it."""

    def get(self, key, default=None):  # noqa: ANN001
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class _FakeResponse:
    status = 200

    def getheaders(self):
        return [("Content-Type", "application/json")]

    def read1(self, _n):
        return b""

    def read(self, _n=-1):
        # `_proxy` does getattr(resp, "read1", resp.read) — Python evaluates the
        # default eagerly, so `read` must exist even though `read1` is what runs.
        return b""


class _Wfile:
    def write(self, _b):  # noqa: ANN001
        return None

    def flush(self):
        return None


def _run_proxy(monkeypatch, browser_headers: dict) -> "object":
    """Drive `_proxy` once and return the outgoing urllib Request."""
    captured = {}

    def _fake_urlopen(req, timeout=None):  # noqa: ANN001, ARG001
        captured["req"] = req
        return _FakeResponse()

    monkeypatch.setattr(wp.urllib.request, "urlopen", _fake_urlopen)

    handler = wp.WidgetProxyHandler.__new__(wp.WidgetProxyHandler)
    handler.backend = "http://concierge.railway.internal:8100"
    handler.path = "/v3/chat"
    handler.headers = _Headers(browser_headers)
    handler.wfile = _Wfile()
    handler.send_response = lambda *a, **k: None
    handler.send_header = lambda *a, **k: None
    handler.end_headers = lambda *a, **k: None

    handler._proxy("POST")
    return captured["req"]


# urllib's Request.add_header stores keys .capitalize()'d, so this is the shape
# the default header name takes on the outgoing request.
_DEFAULT_KEY = "X-internal-api-key"


class TestKeyInjection:
    def test_key_is_injected_when_set(self, monkeypatch):
        monkeypatch.setenv("CHAT_API_KEY", "s3cret")
        monkeypatch.delenv("CHAT_API_KEY_HEADER", raising=False)
        req = _run_proxy(monkeypatch, {"Content-Type": "application/json"})
        assert req.headers[_DEFAULT_KEY] == "s3cret"

    def test_nothing_injected_when_unset(self, monkeypatch):
        """The no-op path: local dev and an un-gated facade must be untouched."""
        monkeypatch.delenv("CHAT_API_KEY", raising=False)
        monkeypatch.delenv("CHAT_API_KEY_HEADER", raising=False)
        req = _run_proxy(monkeypatch, {"Content-Type": "application/json"})
        assert _DEFAULT_KEY not in req.headers

    def test_blank_key_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("CHAT_API_KEY", "   ")
        req = _run_proxy(monkeypatch, {"Content-Type": "application/json"})
        assert _DEFAULT_KEY not in req.headers

    def test_custom_header_name_is_honored(self, monkeypatch):
        """Must read the SAME override the facade reads, or the two drift apart
        and a gated facade rejects every turn."""
        monkeypatch.setenv("CHAT_API_KEY", "s3cret")
        monkeypatch.setenv("CHAT_API_KEY_HEADER", "X-Custom-Key")
        req = _run_proxy(monkeypatch, {})
        assert req.headers["X-custom-key"] == "s3cret"
        assert _DEFAULT_KEY not in req.headers

    def test_header_default_matches_the_facade(self):
        """Locks the shared default against facade.py's own literal."""
        facade = (
            Path(__file__).resolve().parents[1]
            / "agents" / "b2c_concierge" / "b2c_concierge" / "facade.py"
        ).read_text(encoding="utf-8")
        assert f'"{wp._CHAT_API_KEY_HEADER_DEFAULT}"' in facade


class TestKeyHeaderIsProxyOwned:
    def test_browser_supplied_key_is_replaced_not_forwarded(self, monkeypatch):
        """A page must not be able to forge the key: ours wins."""
        monkeypatch.setenv("CHAT_API_KEY", "real-key")
        monkeypatch.delenv("CHAT_API_KEY_HEADER", raising=False)
        req = _run_proxy(monkeypatch, {"X-Internal-Api-Key": "forged-by-the-page"})
        assert req.headers[_DEFAULT_KEY] == "real-key"
        # Not just "ours is there" — theirs must be gone from EVERY header, not
        # merely shadowed under a differently-cased key.
        assert "forged-by-the-page" not in req.headers.values()

    @pytest.mark.parametrize("sent_as", ["X-Internal-Api-Key", "x-internal-api-key"])
    def test_browser_supplied_key_is_dropped_when_we_have_none(self, monkeypatch, sent_as):
        """Even un-gated: never let a browser-supplied key reach the facade, in
        any casing — otherwise gating the facade could be bypassed from the page."""
        monkeypatch.delenv("CHAT_API_KEY", raising=False)
        monkeypatch.delenv("CHAT_API_KEY_HEADER", raising=False)
        req = _run_proxy(monkeypatch, {sent_as: "forged-by-the-page"})
        assert _DEFAULT_KEY not in req.headers
        assert "forged-by-the-page" not in req.headers.values()


class TestOtherHeadersStillForwarded:
    def test_ordinary_headers_survive(self, monkeypatch):
        monkeypatch.setenv("CHAT_API_KEY", "s3cret")
        req = _run_proxy(
            monkeypatch,
            {"Content-Type": "application/json", "X-Dayuse-Synthetic": "1"},
        )
        assert req.headers["Content-type"] == "application/json"
        # The synthetic marker must keep flowing — it's what keeps verification
        # turns out of the Langfuse judges' sampling.
        assert req.headers["X-dayuse-synthetic"] == "1"

    def test_hop_by_hop_headers_are_still_stripped(self, monkeypatch):
        req = _run_proxy(monkeypatch, {"Host": "widget.example", "Connection": "keep-alive"})
        assert "Host" not in req.headers
        assert "Connection" not in req.headers
