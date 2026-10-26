#!/usr/bin/env python3
"""Dev-only reverse proxy: serves agent-usa's chat WIDGET (static/js/chat/**
+ templates/chat_clean.html) standalone and forwards every /v3/chat* call to
the AgentB2C facade (default :8100) — so the legacy front can be exercised
against this stack without agent-usa's own Flask backend running at all.

Every API call from the browser goes to ONE origin (this proxy): no CORS, no
CSP connect-src issue, no cross-origin cookie problem. Analytics are the only
exception: the page loads the Amplitude SDK and its Session Replay plugin from
cdn.amplitude.com, sends events through alitude.dayuse.com and replays to
api-sr.eu.amplitude.com.

chat_clean.html has exactly 10 Jinja `{{ var | default('...') }}` meta tags
(no loops/conditionals) — substituted here with a tiny regex, no Jinja2
dependency needed. Overridden: `chat_endpoint` (kept at '/v3/chat', same-origin
relative — the facade's own auth is CHAT_API_KEY-based and injected by this
proxy, never by the page, so agent-usa's public-token/cookie dance is
irrelevant here), `chat_transport` and `agent_version` (see `_meta_overrides`),
and the 4 market metas, resolved per request from the banner URL's
`?locale` / `?currency` / `?market_country` and the Referer, as agent-usa does
(see `resolve_page_market`; resolver vendored at web/market_context.py).

The widget assets are VENDORED into this repo at `web/vendor/` (templates/ +
static/ mirror agent-usa's layout) so the proxy is self-contained — no sibling
repo needed, and the container image can COPY them in. `AGENT_USA_DIR` (or
`--agent-usa-dir`) still overrides, e.g. to test against a live agent-usa tree.

Container/deploy knobs (Railway): `PORT` and `HOST` env are honored (bind `::`
for the IPv6 private network), `WIDGET_BACKEND` sets the upstream facade,
`WIDGET_CHAT_TRANSPORT=sse` switches the widget to the streamed turn,
`LANGFUSE_RELEASE` becomes the page's `agent-version` meta (Amplitude's
`agent_version`), and
`CHAT_API_KEY` (+ optional `CHAT_API_KEY_HEADER`) is injected server-side into
every forwarded /v3 request so a gated facade accepts us. Set that pair on THIS
service before setting `CHAT_API_KEY` on the concierge — the concierge starts
rejecting the instant it has the key, and the browser can never carry it.

Usage:
    python3 scripts/run_widget_proxy.py                    # :8090 -> :8100, vendored widget
    WIDGET_CHAT_TRANSPORT=sse python3 scripts/run_widget_proxy.py   # streamed turns
    python3 scripts/run_widget_proxy.py --port 8090 --backend http://127.0.0.1:8100
    AGENT_USA_DIR=/path/to/agent-usa python3 scripts/run_widget_proxy.py   # live agent-usa tree
    HOST=:: PORT=8090 WIDGET_BACKEND=http://concierge.railway.internal:8100 python3 scripts/run_widget_proxy.py
"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import mimetypes
import os
import re
import json
import socket
import sys
import threading
import time
from collections import deque
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs

# Vendored widget lives at <repo>/web/vendor (this file is <repo>/scripts/…).
_VENDORED_WIDGET_DIR = Path(__file__).resolve().parent.parent / "web" / "vendor"

# Prefer an explicit AGENT_USA_DIR; else the vendored copy if present; else the
# historical sibling-repo path (kept so an un-vendored checkout still works).
if os.environ.get("AGENT_USA_DIR"):
    DEFAULT_AGENT_USA_DIR = Path(os.environ["AGENT_USA_DIR"])
elif (_VENDORED_WIDGET_DIR / "templates" / "chat_clean.html").is_file():
    DEFAULT_AGENT_USA_DIR = _VENDORED_WIDGET_DIR
else:
    DEFAULT_AGENT_USA_DIR = Path.home() / "Projects" / "agent-usa"


def _load_market_context() -> ModuleType:
    """agent-usa's market resolver, vendored verbatim at web/market_context.py
    (stdlib only). Loaded by path: the widget image has no package layout. It is
    registered in sys.modules before exec because its dataclass resolves string
    annotations through its own module."""
    path = Path(__file__).resolve().parent.parent / "web" / "market_context.py"
    spec = importlib.util.spec_from_file_location("widget_market_context", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"widget-proxy: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


market_context = _load_market_context()

# Languages the widget has copy for (web/vendor/static/js/chat/i18n.js
# SUPPORTED_LANGUAGES). Another locale (zh, ko, tr…) still sets the country and
# currency, but the language meta is left empty so the widget falls back to the
# browser's language instead of an untranslated hero.
_WIDGET_LANGUAGES = frozenset({"en", "fr", "es", "it", "pt", "de", "nl"})
_ISO2_RE = re.compile(r"[A-Z]{2}")


def _first_param(params: dict[str, list[str]], name: str) -> str:
    """First value of a query param; dayuse-com writes the literal 'null' when it
    has no value (lib/ai-agent-url.ts), which counts as absent."""
    value = (params.get(name) or [""])[0].strip()
    return "" if value.lower() in {"null", "undefined"} else value


def resolve_page_market(query: str, referer: str | None):  # noqa: ANN201 (vendored type)
    """The visitor's market, resolved when the page is rendered — as agent-usa's
    `/` route does in prod (src/api/routes/frontend.py): `?locale` / `?currency`
    from the dayuse-com banner URL win, then the Referer's Dayuse domain, then
    dayuse.com / US / USD / en. On top, dayuse-com's `?market_country` (MR
    !15273, its domain config's country) pins the country when it is a known
    market; an explicit `?currency` still wins over that market's currency."""
    params = parse_qs(query or "", keep_blank_values=False)
    ctx = market_context.resolve_market_context(
        referer=referer,
        locale=_first_param(params, "locale") or None,
        currency=_first_param(params, "currency") or None,
    )
    declared = _first_param(params, "market_country").upper()
    country_ctx = market_context._COUNTRY_MARKET_TABLE.get(declared) if _ISO2_RE.fullmatch(declared) else None
    if country_ctx is not None and country_ctx.country_code != ctx.country_code:
        explicit_currency = "url_currency" in ctx.source.split("+")
        ctx = replace(
            ctx,
            country_code=country_ctx.country_code,
            display_name=country_ctx.display_name,
            domain=country_ctx.domain,
            currency=ctx.currency if explicit_currency else country_ctx.currency,
            source=f"{ctx.source}+url_market_country",
        )
    return ctx


def _market_meta(query: str, referer: str | None) -> dict[str, str]:
    """The 4 market metas of chat_clean.html. `market_browse_url` is left to the
    template default (empty): the widget then takes the browse link from
    markets.generated.js, the drift-guarded table (UX6) — agent-usa's own
    browse slugs are the ones that table was built to replace."""
    ctx = resolve_page_market(query, referer)
    language = ctx.language if ctx.language in _WIDGET_LANGUAGES else ""
    return {
        "market_language": html.escape(language, quote=True),
        "market_currency": html.escape(ctx.currency, quote=True),
        "market_country": html.escape(ctx.country_code, quote=True),
        "market_domain": html.escape(ctx.domain, quote=True),
    }


_JINJA_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*(?:\|\s*default\(\s*'([^']*)'\s*\)\s*)?\}\}")


def _meta_overrides() -> dict[str, str]:
    """Only override what matters for wiring the widget to a different backend —
    everything else keeps the template's own default (cosmetic, overwritten by
    the first real /v3/chat response anyway via applyMarketFromResponse).

    `chat_transport` is the exception: `WIDGET_CHAT_TRANSPORT=sse` switches the
    widget to `POST /v3/chat/stream` (hotel cards render on the `hotels` frame,
    seconds before the synthesis). Read per request, so flipping the transport
    is an env change + reload, never a JS redeploy. Unset keeps the template's
    `json` default — the blocking POST.
    """
    overrides = {"chat_endpoint": "/v3/chat"}
    transport = os.environ.get("WIDGET_CHAT_TRANSPORT", "").strip().lower()
    if transport:
        overrides["chat_transport"] = transport
    release = os.environ.get("LANGFUSE_RELEASE", "").strip()
    if release:
        overrides["agent_version"] = html.escape(release, quote=True)
    return overrides

_HOP_BY_HOP_REQUEST_HEADERS = {"host", "content-length", "connection", "accept-encoding"}
_HOP_BY_HOP_RESPONSE_HEADERS = {"transfer-encoding", "connection", "content-length"}

# Facade auth (b2c_concierge/facade.py::_api_key_error): when the concierge has
# CHAT_API_KEY set, every /v3 request must carry it in CHAT_API_KEY_HEADER. The
# browser can't hold that secret, so the PROXY injects it server-side — same two
# env var names as the facade, so the pair can never drift apart. Unset here =
# nothing injected, which is the correct no-op for local dev and for a facade
# that isn't gated yet.
_CHAT_API_KEY_HEADER_DEFAULT = "X-Internal-Api-Key"


def _chat_api_key() -> str:
    return os.environ.get("CHAT_API_KEY", "").strip()


def _chat_api_key_header() -> str:
    return os.environ.get("CHAT_API_KEY_HEADER", _CHAT_API_KEY_HEADER_DEFAULT)


def render_index(agent_usa_dir: Path, query: str = "", referer: str | None = None) -> bytes:
    """`query` / `referer` are the page request's: they carry the visitor's
    market (see `resolve_page_market`)."""
    html = (agent_usa_dir / "templates" / "chat_clean.html").read_text(encoding="utf-8")
    overrides = {**_market_meta(query, referer), **_meta_overrides()}

    def repl(match: "re.Match[str]") -> str:
        name, default = match.group(1), match.group(2) or ""
        return overrides.get(name, default)

    return _JINJA_VAR_RE.sub(repl, html).encode("utf-8")


SESSION_REPLAY_CONFIG = (
    b'{"configs":{"sessionReplay":{"sr_sampling_config":'
    b'{"capture_enabled":true,"sample_rate":0.05}}}}'
)


# --- public-edge protection -------------------------------------------------------------
# This proxy is the ONLY public service and injects the facade key itself, so
# anything that reaches it reaches the LLMs. agent-usa had flask-limiter (20 chat
# turns/min/IP), Talisman headers + CSP and a 500-char message cap; this is the
# stdlib equivalent. Limits are per process (one replica on Railway today): with
# several replicas, each counts on its own.

# Only the routes the concierge facade serves (facade.py::register_v3_routes).
_CHAT_ROUTES = frozenset({"/v3/chat", "/v3/chat/stream"})
_OTHER_POST_ROUTES = frozenset({"/v3/chat/session/reset", "/v3/feedback"})
_CSP_REPORT_PATH = "/csp-report"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


class SlidingWindowLimiter:
    """Per-key request timestamps over fixed windows; thread-safe (the server is
    a ThreadingHTTPServer). `hit` records the request only when it is allowed."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    def hit(self, key: str, limits: list[tuple[int, float]], now: float | None = None) -> float:
        """0 when allowed, else the seconds to wait. `limits` = [(max, window_s)];
        a max ≤ 0 disables that window."""
        now = time.monotonic() if now is None else now
        active = [(n, w) for n, w in limits if n > 0]
        if not active:
            return 0.0
        horizon = max(w for _, w in active)
        with self._lock:
            self._sweep(now, horizon)
            stamps = self._hits.setdefault(key, deque())
            while stamps and now - stamps[0] >= horizon:
                stamps.popleft()
            wait = 0.0
            for max_hits, window in active:
                recent = [t for t in stamps if now - t < window]
                if len(recent) >= max_hits:
                    wait = max(wait, window - (now - recent[-max_hits]))
            if wait > 0:
                return wait
            stamps.append(now)
            return 0.0

    def _sweep(self, now: float, horizon: float) -> None:
        if now - self._last_sweep < 60:
            return
        self._last_sweep = now
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= horizon]:
            del self._hits[key]


_LIMITER = SlidingWindowLimiter()


def _limits_for(path: str) -> tuple[str, list[tuple[int, float]]]:
    if path in _CHAT_ROUTES:
        return "chat", [
            (_env_int("WIDGET_CHAT_PER_MINUTE", 20), 60.0),
            (_env_int("WIDGET_CHAT_PER_HOUR", 200), 3600.0),
        ]
    return "other", [(_env_int("WIDGET_OTHER_PER_MINUTE", 30), 60.0)]


def client_ip(headers, peer: str) -> str:  # noqa: ANN001 (HTTPMessage)
    """The visitor's IP behind Railway's edge. `WIDGET_CLIENT_IP_HEADER`
    (default X-Real-IP, set by the edge) wins; else the RIGHTMOST X-Forwarded-For
    entry — the one the edge appended, the leftmost ones are client-supplied and
    forgeable; else the socket peer."""
    header = os.environ.get("WIDGET_CLIENT_IP_HEADER", "X-Real-IP")
    value = (headers.get(header) or "").strip()
    if value:
        return value
    forwarded = [part.strip() for part in (headers.get("X-Forwarded-For") or "").split(",")]
    forwarded = [part for part in forwarded if part]
    return forwarded[-1] if forwarded else peer


def cross_site_refusal(headers) -> str | None:  # noqa: ANN001
    """Why a browser POST must be refused as cross-site, or None. A page on
    another site can make a visitor's browser call /v3 (the proxy adds the key);
    browsers always send Origin on a cross-origin POST, so it must name this
    host (or WIDGET_ALLOWED_ORIGINS). No Origin = not a browser request: allowed,
    the rate limit covers it."""
    if (headers.get("Sec-Fetch-Site") or "").strip().lower() == "cross-site":
        return "sec-fetch-site cross-site"
    origin = (headers.get("Origin") or "").strip()
    if not origin:
        return None
    host = urllib.parse.urlsplit(origin).netloc.lower()
    own = {
        (headers.get(name) or "").split(",")[0].strip().lower()
        for name in ("X-Forwarded-Host", "Host")
    }
    allowed = {
        urllib.parse.urlsplit(o.strip()).netloc.lower() or o.strip().lower()
        for o in os.environ.get("WIDGET_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    }
    if host and host in (own | allowed) - {""}:
        return None
    return f"origin {origin[:100]}"


def message_too_long(body: bytes | None) -> bool:
    """agent-usa's MAX_MESSAGE_LENGTH (500): the input caps at 400, so only a
    scripted client goes over. An unparsable body is left to the facade."""
    if not body:
        return False
    try:
        message = json.loads(body).get("message")
    except (ValueError, AttributeError):
        return False
    return isinstance(message, str) and len(message) > _env_int("WIDGET_MAX_MESSAGE_CHARS", 500)


# Prod agent-usa's enforced policy (Talisman, non-strict), plus what this
# widget loads: Amplitude Session Replay (worker + api-sr), hotel photos.
_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.amplitude.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: https://dayuse.twic.pics https://images.dayuse.com "
    "https://static.dayuse.com https://*.dayuse.com",
    "connect-src 'self' https://alitude.dayuse.com https://sr-client-cfg.eu.amplitude.com "
    "https://api-sr.eu.amplitude.com https://*.dayuse.com",
    "worker-src 'self' blob:",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "form-action 'self'",
])


def security_headers() -> list[tuple[str, str]]:
    """Sent on every response. The CSP starts REPORT-ONLY (`WIDGET_CSP_MODE`:
    report-only | enforce | off): this widget loads more than agent-usa's did
    (Session Replay), so watch the `csp-report` log lines before enforcing."""
    headers = [
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("X-Frame-Options", "DENY"),
        ("Strict-Transport-Security", "max-age=31536000"),
        ("Permissions-Policy", "camera=(), microphone=(), payment=()"),
    ]
    mode = os.environ.get("WIDGET_CSP_MODE", "report-only").strip().lower()
    if mode == "enforce":
        headers.append(("Content-Security-Policy", _CSP))
    elif mode != "off":
        headers.append(
            ("Content-Security-Policy-Report-Only", f"{_CSP}; report-uri {_CSP_REPORT_PATH}")
        )
    return headers


class WidgetProxyHandler(BaseHTTPRequestHandler):
    agent_usa_dir: Path
    backend: str
    # No version banner; and a socket timeout so a client that opens a
    # connection and never finishes its request cannot hold a thread forever.
    server_version = "widget"
    sys_version = ""
    timeout = 30

    def end_headers(self) -> None:
        for name, value in security_headers():
            self.send_header(name, value)
        super().end_headers()

    # --- routing -------------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
        path, _, query = self.path.partition("?")
        if path == "/":
            self._respond_html(
                render_index(self.agent_usa_dir, query, self.headers.get("Referer"))
            )
        elif path == "/sr-config":
            self._respond_session_replay_config()
        elif path.startswith("/static/"):
            self._serve_static(path)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == _CSP_REPORT_PATH:
            self._csp_report()
            return
        if path not in _CHAT_ROUTES and path not in _OTHER_POST_ROUTES:
            self.send_error(404)
            return
        refusal = cross_site_refusal(self.headers)
        if refusal:
            print(f"widget-proxy: refused cross-site POST {path} ({refusal})")
            self._json_error(403, "forbidden")
            return
        ip = client_ip(self.headers, self.client_address[0] if self.client_address else "-")
        bucket, limits = _limits_for(path)
        wait = _LIMITER.hit(f"{bucket}:{ip}", limits)
        if wait > 0:
            print(f"widget-proxy: rate_limit_hit path={path} ip={ip}")
            self._json_error(429, "rate_limited", retry_after=max(1, int(wait + 0.999)))
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > _env_int("WIDGET_MAX_BODY_BYTES", 16384):
            self._json_error(413, "payload_too_large")
            return
        body = self.rfile.read(length) if length else None
        if path in _CHAT_ROUTES and message_too_long(body):
            self._json_error(413, "message_too_long")
            return
        self._proxy("POST", body=body)

    def _json_error(self, status: int, error: str, retry_after: int | None = None) -> None:
        payload = json.dumps({"error": error}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        self.wfile.write(payload)

    def _csp_report(self) -> None:
        """Log a CSP violation (report-only phase), rate-limited, then 204."""
        ip = client_ip(self.headers, self.client_address[0] if self.client_address else "-")
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        body = self.rfile.read(length) if length else b""
        if _LIMITER.hit(f"csp:{ip}", [(_env_int("WIDGET_CSP_REPORTS_PER_MINUTE", 30), 60.0)]) == 0:
            print(f"widget-proxy: csp-report {body[:600].decode('utf-8', 'replace')}")
        self.send_response(204)
        self.end_headers()

    # --- static / index --------------------------------------------------------------------
    def _if_none_match_hits(self, etag: str) -> bool:
        """Weak comparison over the client's `If-None-Match` list (RFC 9110
        §13.1.2 — that header ALWAYS uses the weak function, and may carry
        several etags or `*`).

        Not pedantry: Railway's edge rewrites our strong ETag as weak (`W/"…"`)
        when it compresses the response, so Chrome echoes `W/"…"` back. Measured
        against prod on 2026-08-27, an exact string compare here answered 200
        with the full body on 36 of 38 assets — the browser revalidated (which
        was the point) but never got a 304 out of it.
        """
        header = self.headers.get("If-None-Match") or ""
        if header.strip() == "*":
            return True
        return any(
            candidate.strip().removeprefix("W/") == etag
            for candidate in header.split(",")
            if candidate.strip()
        )

    def _send_cacheable(self, body: bytes, content_type: str) -> None:
        """Serve `body` with a content ETag and `Cache-Control: no-cache`.

        The widget assets are UNVERSIONED (no content hash in the filename, and
        the page loads them at fixed paths), and this handler used to send no
        validator and no cache directive at all — leaving the browser free to
        reuse a heuristically-cached copy without asking. That is a correctness
        problem, not a performance one: a page holding an old `state.js` against
        a newer facade is exactly the class of bug the 2026-08-27 session-reload
        fix was about. `no-cache` means "you may store it, but revalidate before
        every use", so the client still gets a cheap 304 instead of the bytes.
        """
        etag = f'"{hashlib.sha256(body).hexdigest()[:32]}"'
        if self._if_none_match_hits(etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _respond_session_replay_config(self) -> None:
        body = SESSION_REPLAY_CONFIG
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _respond_html(self, body: bytes) -> None:
        self._send_cacheable(body, "text/html; charset=utf-8")

    def _serve_static(self, path: str) -> None:
        root = (self.agent_usa_dir / "static").resolve()
        target = (self.agent_usa_dir / path.lstrip("/")).resolve()
        if root not in target.parents and target != root:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send_cacheable(target.read_bytes(), content_type)

    # --- reverse proxy (streams incrementally — SSE-safe) -----------------------------------
    def _proxy(self, method: str, body: bytes | None = None) -> None:
        if body is None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
        url = f"{self.backend}{self.path}"
        req = urllib.request.Request(url, data=body, method=method)
        # The API-key header is PROXY-OWNED: always dropped from what the browser
        # sent (a page must not be able to forge or probe it), then re-added below
        # from our own env. Dropped unconditionally, so an un-gated facade doesn't
        # start accepting a browser-supplied key either.
        api_key_header = _chat_api_key_header().lower()
        for key, value in self.headers.items():
            lowered = key.lower()
            if lowered in _HOP_BY_HOP_REQUEST_HEADERS or lowered == api_key_header:
                continue
            req.add_header(key, value)
        api_key = _chat_api_key()
        if api_key:
            req.add_header(_chat_api_key_header(), api_key)

        try:
            resp = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as exc:
            resp = exc  # HTTPError quacks like a response (status/headers/read)
        except urllib.error.URLError as exc:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"widget-proxy: backend unreachable ({exc.reason})".encode())
            return

        status = getattr(resp, "status", None) or getattr(resp, "code", 502)
        self.send_response(status)
        for key, value in resp.getheaders():
            if key.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("Connection", "close")
        self.end_headers()
        # read1, NOT read: on a chunked upstream, read(4096) BLOCKS until it
        # has accumulated the full 4096 bytes — which held the ~20-byte SSE
        # `progress` frame hostage until the synthesis flooded the buffer, so
        # every frame of a turn arrived in ONE burst at the end (measured
        # 2026-07-28, local and through Railway: progress=hotels=done to the
        # millisecond). read1 returns as soon as ANY data is available — the
        # whole point of the facade's frame-by-frame stream.
        read_available = getattr(resp, "read1", resp.read)
        while True:
            chunk = read_available(4096)
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except BrokenPipeError:
                break

    def log_message(self, fmt: str, *args: object) -> None:  # quieter default logging
        print(f"widget-proxy: {self.address_string()} {fmt % args}")


class _WidgetProxyServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that can bind an IPv6 literal (e.g. `::`). http.server
    defaults to AF_INET and raises `Address family for hostname not supported` on
    `::`; Railway's private network is IPv6, so the container binds `::` and needs
    AF_INET6 with V6ONLY disabled (dual-stack: also accepts IPv4)."""

    def __init__(self, server_address, handler_class):  # noqa: ANN001
        if ":" in server_address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(server_address, handler_class)

    def server_bind(self) -> None:
        if self.address_family == socket.AF_INET6:
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except (AttributeError, OSError):
                pass  # kernel without dual-stack: IPv6-only bind is still correct on Railway
        super().server_bind()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # PORT/HOST env win over the defaults so Railway (which injects PORT) needs no flags.
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8090")))
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument(
        "--backend", default=os.environ.get("WIDGET_BACKEND", "http://127.0.0.1:8100")
    )
    parser.add_argument("--agent-usa-dir", default=str(DEFAULT_AGENT_USA_DIR))
    args = parser.parse_args()

    agent_usa_dir = Path(args.agent_usa_dir)
    if not (agent_usa_dir / "templates" / "chat_clean.html").is_file():
        raise SystemExit(
            f"widget-proxy: no templates/chat_clean.html under {agent_usa_dir} "
            "— pass --agent-usa-dir or set AGENT_USA_DIR"
        )

    WidgetProxyHandler.agent_usa_dir = agent_usa_dir
    WidgetProxyHandler.backend = args.backend.rstrip("/")

    server = _WidgetProxyServer((args.host, args.port), WidgetProxyHandler)
    print(
        f"widget-proxy: listening on {args.host}:{args.port} "
        f"(widget: {agent_usa_dir}, backend: {args.backend})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
