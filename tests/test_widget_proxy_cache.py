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
the emitted status line + headers are captured — except `TestHeadOverHttp`,
which talks to a real proxy on a loopback port (HEAD is about the wire).

Since 2026-10-29 the page names every asset by its content digest
(`/static/x?v=<digest>`): that URL is cached a year (`immutable`), the page and
any unversioned URL keep `no-cache` + ETag (below, unchanged).
"""
from __future__ import annotations

import http.client
import importlib.util
import re
import shutil
import threading
from pathlib import Path

import pytest

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


def _get(path: str, request_headers: dict | None = None, vendor: Path = _VENDOR) -> dict:
    """Drive one GET through the real routing and return status/headers/body."""
    handler = wp.WidgetProxyHandler.__new__(wp.WidgetProxyHandler)
    handler.agent_usa_dir = vendor
    handler.backend = "http://127.0.0.1:8100"
    handler.command = "GET"
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


_VERSIONED_REF_RE = re.compile(r"/static/[\w./-]+\?v=[0-9a-f]{12}")


def _page() -> str:
    return _get("/")["body"].decode("utf-8")


def _versioned(page: str, suffix: str) -> str:
    """The versioned URL the page uses for the static file ending in `suffix`."""
    urls = [u for u in _VERSIONED_REF_RE.findall(page) if u.split("?")[0].endswith(suffix)]
    assert urls, f"the page does not reference {suffix}"
    return urls[0]


class TestVersionedAssetsAreImmutable:
    def test_every_static_reference_of_the_page_is_versioned(self):
        page = _page()
        bare = re.findall(r"/static/[\w./-]+\.\w+(?!\?v=)(?=[\"'\s,)])", page)
        assert bare == []
        assert len(set(_VERSIONED_REF_RE.findall(page))) >= 15

    def test_the_versioned_bundle_is_cached_a_year(self):
        r = _get(_versioned(_page(), "/dist/chat.js"))
        assert r["status"] == 200
        assert r["headers"]["Cache-Control"] == "public, max-age=31536000, immutable"
        assert r["headers"]["ETag"].startswith('"')

    def test_the_page_itself_still_revalidates(self):
        assert _get("/")["headers"]["Cache-Control"] == "no-cache"

    def test_a_stale_digest_gets_the_current_bytes_without_immutable(self):
        """A page from the previous deploy asks for the old digest: it gets the
        current file, but that URL must not be pinned to these bytes for a year."""
        r = _get("/static/dist/chat.js?v=000000000000")
        assert r["status"] == 200
        assert r["headers"]["Cache-Control"] == "no-cache"
        assert r["body"] == _get(_versioned(_page(), "/dist/chat.js"))["body"]

    def test_a_304_on_a_versioned_url_keeps_immutable(self):
        url = _versioned(_page(), "/dist/chat.css")
        again = _get(url, {"If-None-Match": _get(url)["headers"]["ETag"]})
        assert again["status"] == 304
        assert again["headers"]["Cache-Control"] == "public, max-age=31536000, immutable"

    def test_the_stylesheet_names_its_font_and_photos_by_digest_too(self):
        css = _get(_versioned(_page(), "/dist/chat.css"))["body"].decode("utf-8")
        assert re.search(r"url\(/static/fonts/MaisonNeueExtended-Bold\.woff2\?v=[0-9a-f]{12}\)", css)

    def test_the_card_star_named_in_the_script_is_versioned(self):
        js = _get(_versioned(_page(), "/dist/chat.js"))["body"].decode("utf-8")
        assert re.search(r"/static/icon/star\.svg\?v=[0-9a-f]{12}", js)

    def test_preloads_and_their_targets_use_the_same_url(self):
        """A preload is only reused when its URL is the one the page then asks
        for: the font preload and the @font-face, the hero preload and the
        <picture> source."""
        page = _page()
        css = _get(_versioned(page, "/dist/chat.css"))["body"].decode("utf-8")
        font = _versioned(page, "MaisonNeueExtended-Bold.woff2")
        assert f'<link rel="preload" href="{font}"' in page
        assert f"url({font})" in css
        for hero in ("hero_usa_mobile-1080.avif", "hero_usa_desktop-1920.avif"):
            assert page.count(_versioned(page, hero)) == 2  # head preload + <picture>

    def test_dynamic_routes_are_not_cached_for_long(self):
        """/v3 is POST-only (GET 404s, see TestHeadOverHttp), health answers
        are live, and /sr-config is a constant cached 5 minutes at most."""
        assert _get("/healthz")["headers"]["Cache-Control"] == "no-store"
        assert _get("/sr-config")["headers"]["Cache-Control"] == "private, max-age=300"


class TestDigestFollowsContent:
    """On a copy of the vendored tree: editing a file renames it, and renames
    the stylesheet that points at it (its digest covers the versioned refs)."""

    @pytest.fixture()
    def vendor(self, tmp_path: Path) -> Path:
        shutil.copytree(_VENDOR, tmp_path / "vendor")
        return tmp_path / "vendor"

    def test_a_new_font_renames_the_font_and_the_stylesheet(self, vendor: Path):
        static = vendor / "static"
        css_before = _versioned(_get("/", vendor=vendor)["body"].decode(), "/dist/chat.css")
        font = static / "fonts" / "MaisonNeueExtended-Bold.woff2"
        font.write_bytes(font.read_bytes() + b"\0")
        page = _get("/", vendor=vendor)["body"].decode()
        assert _versioned(page, "/dist/chat.css") != css_before
        assert _get(css_before, vendor=vendor)["headers"]["Cache-Control"] == "no-cache"

    def test_an_unchanged_file_keeps_its_url_across_edits_elsewhere(self, vendor: Path):
        before = _versioned(_get("/", vendor=vendor)["body"].decode(), "/dayuse.svg")
        js = vendor / "static" / "dist" / "chat.js"
        js.write_text(js.read_text() + "\n")
        assert _versioned(_get("/", vendor=vendor)["body"].decode(), "/dayuse.svg") == before

    def test_a_reference_to_a_missing_file_is_left_alone(self, vendor: Path):
        static = (vendor / "static").resolve()
        text = 'url("/static/nope.png") src="/static/dayuse.svg"'
        out = wp.version_static_refs(text, static)
        assert 'url("/static/nope.png")' in out
        assert re.search(r'src="/static/dayuse\.svg\?v=[0-9a-f]{12}"', out)

    def test_a_reference_outside_static_is_left_alone(self, vendor: Path):
        static = (vendor / "static").resolve()
        assert wp.version_static_refs('"/static/../templates/chat_clean.html"', static) == (
            '"/static/../templates/chat_clean.html"'
        )


@pytest.fixture(scope="class")
def live_proxy():
    """A real proxy on a loopback port; its backend is a closed port (only
    /health* would try it, and only for the readiness answer)."""
    wp.WidgetProxyHandler.agent_usa_dir = _VENDOR
    wp.WidgetProxyHandler.backend = "http://127.0.0.1:9"
    server = wp._WidgetProxyServer(("127.0.0.1", 0), wp.WidgetProxyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def _fetch(port: int, method: str, path: str) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    headers = {k: v for k, v in resp.getheaders() if k.lower() != "date"}
    return resp.status, headers, body


@pytest.mark.usefixtures("live_proxy")
class TestHeadOverHttp:
    """HEAD answered 501 until 2026-10-29; uptime probes and link checkers use it."""

    @pytest.mark.parametrize("path", ["/", "/static/dist/chat.css", "/sr-config", "/healthz", "/nope", "/v3/chat"])
    def test_head_answers_like_get_without_a_body(self, live_proxy: int, path: str):
        get_status, get_headers, get_body = _fetch(live_proxy, "GET", path)
        head_status, head_headers, head_body = _fetch(live_proxy, "HEAD", path)
        assert head_status == get_status != 501
        assert head_body == b""
        assert head_headers == get_headers
        if get_status == 200:
            assert int(head_headers["Content-Length"]) == len(get_body) > 0

    def test_head_on_a_versioned_asset_is_immutable(self, live_proxy: int):
        _, _, page = _fetch(live_proxy, "GET", "/")
        url = _versioned(page.decode(), "/dist/chat.js")
        status, headers, body = _fetch(live_proxy, "HEAD", url)
        assert (status, body) == (200, b"")
        assert headers["Cache-Control"] == "public, max-age=31536000, immutable"
