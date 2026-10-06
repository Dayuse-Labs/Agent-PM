"""Local-only replay launcher: a per-request historical clock, never a public API.

Imports a chosen checkout unmodified, patches only its date/datetime bindings,
and propagates replay context solely between loopback test services. Telemetry,
timeouts, Redis expiry, and third-party libraries retain the real clock.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import json
from contextvars import ContextVar
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

HEADERS = ("x-replay-clock", "x-replay-source-today", "x-replay-case", "x-replay-turn", "x-replay-variant",
           "x-replay-session-id")
replay_headers: ContextVar[dict[str, str]] = ContextVar("replay_headers", default={})


def current_clock() -> datetime | None:
    raw = replay_headers.get().get("x-replay-clock")
    return datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None


class ReplayDate(date):
    @classmethod
    def today(cls) -> date:
        value = current_clock()
        return value.date() if value else date.today()


class ReplayDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        value = current_clock()
        if value is None:
            return datetime.now(tz)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    @classmethod
    def utcnow(cls) -> datetime:
        value = current_clock()
        return value.astimezone(UTC).replace(tzinfo=None) if value else datetime.now(UTC).replace(tzinfo=None)


def install_clock() -> None:
    for name, module in list(sys.modules.items()):
        if name.split(".")[0] not in {"b2c_concierge", "hotel_search_agent", "faq_agent"}:
            continue
        if getattr(module, "date", None) is date:
            module.date = ReplayDate
        if getattr(module, "datetime", None) is datetime:
            module.datetime = ReplayDatetime


def install_propagation() -> None:
    send = httpx.AsyncClient.send

    async def with_context(self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if request.url.host in {"127.0.0.1", "localhost", "::1"}:
            for name, value in replay_headers.get().items():
                request.headers[name] = value
        return await send(self, request, **kwargs)

    httpx.AsyncClient.send = with_context  # type: ignore[method-assign]
    # MCP's long-lived transport writer inherits the context of the FIRST
    # request. Per-call metadata, unlike a writer's HTTP headers, survives that
    # task boundary without pinning every later conversation to its clock.
    from mcp import ClientSession
    call_tool = ClientSession.call_tool

    async def with_tool_context(self: Any, name: str, arguments: Any = None,
                                *args: Any, meta: Any = None, **kwargs: Any) -> Any:
        context = replay_headers.get()
        merged = dict(meta or {})
        if context:
            merged["dayuse_replay"] = context
        return await call_tool(self, name, arguments, *args, meta=merged, **kwargs)

    ClientSession.call_tool = with_tool_context  # type: ignore[method-assign]


class ClockMiddleware:
    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        selected = {k: headers[k] for k in HEADERS if k in headers}
        if selected:
            # Fail on malformed context before invoking the agent, never silently use today.
            value = datetime.fromisoformat(selected["x-replay-clock"].replace("Z", "+00:00"))
            if value.tzinfo is None:
                raise ValueError("replay clock must include timezone")
            date.fromisoformat(selected["x-replay-source-today"])
        token = replay_headers.set(selected)
        try:
            await self.app(scope, receive, send)
        finally:
            replay_headers.reset(token)


def install_metric_capture(path: Path) -> None:
    """Mirror existing KPI events locally, with no message or profile content."""
    from dayuse_agent_common.metrics_pg import enqueue_metric_event
    allowed = {"service", "model", "ms", "prompt_tokens", "completion_tokens", "total_tokens",
               "thoughts_tokens", "status", "cost_usd", "error_type", "llm_calls", "route", "family",
               "hotels_returned", "tool", "phase", "reason"}
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def capture(event_type: str, **kwargs: Any) -> Any:
        context = replay_headers.get()
        if context.get("x-replay-case"):
            payload = {"event_type": event_type, **context,
                       **{k: v for k, v in kwargs.items() if k in allowed}}
            # One local file per process, one short write per event. No credentials.
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            path.chmod(0o600)
        return enqueue_metric_event(event_type, **kwargs)

    for name, module in list(sys.modules.items()):
        if name.split(".")[0] in {"dayuse_agent_common", "b2c_concierge", "hotel_search_agent", "faq_agent"}:
            if getattr(module, "enqueue_metric_event", None) is enqueue_metric_event:
                module.enqueue_metric_event = capture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--service", choices=["b2c_concierge", "hotel_search_agent", "faq_agent"], required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--metrics", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    from dotenv import load_dotenv
    load_dotenv(root / ".env", override=True)
    os.environ["PORT"] = str(args.port)
    offset = int(os.environ["PORT_OFFSET"])
    os.environ["HOTEL_SEARCH_CARD_URL"] = f"http://127.0.0.1:{8101+offset}/.well-known/agent-card.json"
    os.environ["FAQ_AGENT_CARD_URL"] = f"http://127.0.0.1:{8102+offset}/.well-known/agent-card.json"
    os.environ["HOTEL_SEARCH_A2A_TOKEN"] = os.environ["A2A_BEARER_TOKEN"]
    os.environ["FAQ_AGENT_A2A_TOKEN"] = os.environ["A2A_BEARER_TOKEN"]
    sys.path[:0] = [str(root / "agents" / args.service), str(root / "libs/b2c_common")]
    app = importlib.import_module(args.service + ".serve").app
    install_clock()
    install_propagation()
    if args.metrics:
        install_metric_capture(args.metrics)
    import uvicorn
    uvicorn.run(ClockMiddleware(app), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
