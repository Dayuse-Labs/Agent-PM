"""Offline tests for the widget proxy's asset revalidation
(scripts/run_widget_proxy.py::_send_cacheable).

Why this matters: the widget assets are UNVERSIONED — `chat_clean.html` loads
`/static/js/chat/*.js` at fixed paths, so a browser holding an old copy of
`state.js` runs it against a newer facade. The handler used to send neither a
validator nor a cache directive, which leaves the copy's freshness to browser
heuristics. Found on 2026-08-27 while deploying the session-reload fix, whose
whole point was a `state.js` change: `Cache-Control` + `ETag` were absent from
every asset response in prod (only `Content-Length` came back).

No network: the handler is built by hand (as in test_widget_proxy_auth.py) and
the emitted status line + headers are captured.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "run_widget_proxy.py"
_spec = importlib.util.spec_from_file_location("run_widget_proxy_cache", _SCRIPT)
assert _spec is not None and _spec.loader is not None
wp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wp)

_VENDOR = _REPO / "web" / "vendor"


class _Headers(dict):
    def get(self, key, default=None):  # noqa: ANN001
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class _Wfile:
    def __init__(self) -> None:
        self.written = b""

    def write(self, b):  # noqa: ANN001
        self.written += b

    def flush(self):
        return None


def _get(path: str, request_headers: dict | None = None) -> dict:
    """Drive one GET through the real routing and return status/headers/body."""
    handler = wp.WidgetProxyHandler.__new__(wp.WidgetProxyHandler)
    handler.agent_usa_dir = _VENDOR
    handler.backend = "http://127.0.0.1:8100"
    handler.path = path
    handler.headers = _Headers(request_headers or {})
    handler.wfile = _Wfile()

    captured: dict = {"status": None, "headers": {}}
    handler.send_response = lambda code, *a: captured.__setitem__("status", code)  # noqa: ARG005
    handler.send_header = lambda k, v: captured["headers"].__setitem__(k, v)
    handler.end_headers = lambda: None

    handler.do_GET()
    captured["body"] = handler.wfile.written
    return captured


class TestAssetsAlwaysRevalidate:
    def test_static_js_carries_etag_and_no_cache(self):
        r = _get("/static/js/chat/state.js")
        assert r["status"] == 200
        assert r["headers"]["Cache-Control"] == "no-cache"
        assert r["headers"]["ETag"].startswith('"')
        assert b"clientSessionId" in r["body"]

    def test_index_html_carries_etag_and_no_cache(self):
        r = _get("/")
        assert r["status"] == 200
        assert r["headers"]["Cache-Control"] == "no-cache"
        assert r["headers"]["ETag"].startswith('"')

    def test_matching_if_none_match_gets_304_without_the_body(self):
        first = _get("/static/js/chat/state.js")
        again = _get("/static/js/chat/state.js", {"If-None-Match": first["headers"]["ETag"]})
        assert again["status"] == 304
        assert again["body"] == b""
        assert again["headers"]["ETag"] == first["headers"]["ETag"]
        assert again["headers"]["Cache-Control"] == "no-cache"

    def test_weak_etag_from_the_edge_still_gets_a_304(self):
        """Railway's edge rewrites the strong ETag as weak when it compresses,
        so the browser echoes `W/"…"`. RFC 9110 §13.1.2: If-None-Match uses the
        WEAK comparison, and an exact compare cost a 200-with-body on 36 of 38
        assets in Chrome against prod (2026-08-27)."""
        etag = _get("/static/js/chat/state.js")["headers"]["ETag"]
        r = _get("/static/js/chat/state.js", {"If-None-Match": f"W/{etag}"})
        assert r["status"] == 304
        assert r["body"] == b""

    def test_if_none_match_list_is_honored(self):
        """A client may send several etags; ours matching anywhere is a hit."""
        etag = _get("/static/js/chat/state.js")["headers"]["ETag"]
        r = _get("/static/js/chat/state.js", {"If-None-Match": f'"other-build", W/{etag}'})
        assert r["status"] == 304

    def test_star_if_none_match_gets_a_304(self):
        r = _get("/static/js/chat/state.js", {"If-None-Match": "*"})
        assert r["status"] == 304

    def test_stale_if_none_match_gets_the_new_bytes(self):
        """The point of the whole thing: a client holding a PREVIOUS version's
        etag must be handed the current file, never a 304."""
        r = _get("/static/js/chat/state.js", {"If-None-Match": '"etag-of-an-older-build"'})
        assert r["status"] == 200
        assert r["body"]

    def test_etag_follows_the_content(self):
        state_js = _get("/static/js/chat/state.js")["headers"]["ETag"]
        index_js = _get("/static/js/chat/index.js")["headers"]["ETag"]
        assert state_js != index_js
