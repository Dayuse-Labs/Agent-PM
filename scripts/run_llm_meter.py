#!/usr/bin/env python3
"""LLM metering proxy for the comparative audit (S-B): measures the OLD
agent-usa's LLM calls/turn and tokens without touching its code.

agent-usa's OpenAI SDK reads `OPENAI_BASE_URL` from the environment (the app
never sets base_url explicitly), so pointing that env var at this proxy meters
every call transparently:

    python3 scripts/run_llm_meter.py --log <path>/llm_meter.jsonl   # :8120
    OPENAI_BASE_URL=http://127.0.0.1:8120/v1 <boot agent-usa>

Every request is forwarded verbatim to https://api.openai.com (same path,
same headers — the Authorization key passes through and is NEVER logged).
For JSON completions/embeddings responses, one JSONL line is appended:
    {"ts": ..., "endpoint": "/v1/chat/completions", "model": ...,
     "prompt_tokens": ..., "completion_tokens": ..., "latency_ms": ...}
GDPR: usage numbers and model name only — never request/response bodies,
never message content, never headers. SSE streams (unused by agent-usa) are
passed through unmetered with a {"streamed": true} marker line.

Cost is computed at analysis time from the token counts (same price table as
the candidate's metrics), keeping this proxy free of pricing assumptions.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_HOP_BY_HOP_REQUEST_HEADERS = {"host", "content-length", "connection", "accept-encoding"}
_HOP_BY_HOP_RESPONSE_HEADERS = {"transfer-encoding", "connection", "content-length"}


def usage_record(endpoint: str, payload: dict[str, Any], latency_ms: float) -> dict[str, Any]:
    """The JSONL line for one metered LLM response — usage facts only."""
    usage = payload.get("usage") or {}
    return {
        "ts": time.time(),
        "endpoint": endpoint,
        "model": payload.get("model"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "latency_ms": round(latency_ms, 1),
    }


class LlmMeterHandler(BaseHTTPRequestHandler):
    upstream: str
    log_path: str

    def _append(self, record: dict[str, Any]) -> None:
        with open(self.log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def do_POST(self) -> None:  # noqa: N802 (stdlib method name)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(f"{self.upstream}{self.path}", data=body, method="POST")
        for key, value in self.headers.items():
            if key.lower() not in _HOP_BY_HOP_REQUEST_HEADERS:
                req.add_header(key, value)

        started = time.perf_counter()
        try:
            resp = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as exc:
            resp = exc  # HTTPError quacks like a response (status/headers/read)
        except urllib.error.URLError as exc:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"llm-meter: upstream unreachable ({exc.reason})".encode())
            return

        status = getattr(resp, "status", None) or getattr(resp, "code", 502)
        content_type = resp.headers.get("Content-Type") or ""
        endpoint = self.path.split("?", 1)[0]

        if "text/event-stream" in content_type:
            self._append({"ts": time.time(), "endpoint": endpoint, "streamed": True})
            self._stream_through(status, resp)
            return

        raw = resp.read()
        latency_ms = (time.perf_counter() - started) * 1000
        if "application/json" in content_type and status == 200:
            try:
                self._append(usage_record(endpoint, json.loads(raw), latency_ms))
            except (ValueError, TypeError):
                pass
        else:
            self._append(
                {"ts": time.time(), "endpoint": endpoint, "status": status,
                 "latency_ms": round(latency_ms, 1)}
            )
        self.send_response(status)
        for key, value in resp.getheaders():
            if key.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)

    def _stream_through(self, status: int, resp: Any) -> None:
        self.send_response(status)
        for key, value in resp.getheaders():
            if key.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("Connection", "close")
        self.end_headers()
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except BrokenPipeError:
                break

    def log_message(self, fmt: str, *args: object) -> None:  # path+status only, never a body
        print(f"llm-meter: {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8120)
    parser.add_argument("--upstream", default="https://api.openai.com")
    parser.add_argument("--log", required=True, help="JSONL output path (usage lines)")
    args = parser.parse_args()

    LlmMeterHandler.upstream = args.upstream.rstrip("/")
    LlmMeterHandler.log_path = args.log
    server = ThreadingHTTPServer(("127.0.0.1", args.port), LlmMeterHandler)
    print(f"llm-meter: http://127.0.0.1:{args.port} -> {args.upstream} (log: {args.log})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
