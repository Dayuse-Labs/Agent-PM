"""Loopback read-only MCP proxy with shared contemporary inventory fixtures.

Historical dates are shifted by a documented whole-day offset for retrieval,
then mapped back in structured search results. This tests historical dialogue
logic against contemporary supply, NOT historical availability. Both revisions
share content-addressed successful tool results. No booking-management actions
are exposed. Credentials never enter the cache.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from evals.production_corpus import atomic_json

READ_ONLY = {"search_offers", "find_hotel_by_name", "get_hotel_details", "compare_hotels",
             "generate_booking_link", "get_faq_conditions", "list_amenities"}


def shift_request(name: str, arguments: dict, source_today: str | None, inventory_day: str) -> tuple[dict, int]:
    args = copy.deepcopy(arguments)
    days = (date.fromisoformat(inventory_day) - date.fromisoformat(source_today)).days if source_today else 0
    if name == "search_offers" and isinstance(args.get("date"), str):
        args["date"] = (date.fromisoformat(args["date"]) + timedelta(days=days)).isoformat()
    return args, days


def restore_dates(value: Any, days: int, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: restore_dates(v, days, k) for k, v in value.items()}
    if isinstance(value, list):
        return [restore_dates(v, days, key) for v in value]
    if isinstance(value, str) and key in {"date", "resolvedDate", "checkinDate", "checkoutDate"}:
        try:
            return (date.fromisoformat(value) - timedelta(days=days)).isoformat()
        except ValueError:
            pass
    return value


def decode_rpc(response: httpx.Response) -> dict:
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        messages = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
        return next(x for x in reversed(messages) if "result" in x or "error" in x)
    return response.json()


class FixtureProxy:
    def __init__(self, upstream: str, token: str, cache: Path, inventory_day: str):
        self.upstream = upstream
        self.cache = cache
        self.inventory_day = inventory_day
        self.client = httpx.AsyncClient(timeout=30, headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        self.lock = asyncio.Lock()
        self.key_locks: dict[str, asyncio.Lock] = {}
        self.initialized = False
        self.catalog: dict | None = None
        self.rpc_lock = asyncio.Lock()
        self.tokens = 8.0
        self.refilled_at = time.monotonic()
        self.error_count = 0
        self.blocked_until = 0.0

    async def post_rpc(self, method: str, params: dict, request_id: int = 2) -> httpx.Response:
        # The shared staging service advertises a 100-request rate limit. A
        # single global pacer prevents workers from multiplying that allowance.
        # Rate-limited fixture acquisition invalidates a turn; never hide it as
        # model variance or spend the leaf's short timeout on a long retry.
        async with self.rpc_lock:
            await asyncio.sleep(max(0.0, self.blocked_until - time.monotonic()))
            now = time.monotonic()
            self.tokens = min(8.0, self.tokens + (now - self.refilled_at) * 1.2)
            self.refilled_at = now
            if self.tokens < 1.0:
                await asyncio.sleep((1.0 - self.tokens) / 1.2)
                self.tokens = 0.0
                self.refilled_at = time.monotonic()
            else:
                self.tokens -= 1.0
        # The pacing lock does not serialize network I/O. Eight initial tokens
        # plus 72/min sustained remains below the advertised 100/min allowance.
        response = await self.client.post(self.upstream, json={"jsonrpc": "2.0",
            "id": request_id, "method": method, "params": params})
        if response.status_code == 429:
            retry = response.headers.get("retry-after", "60")
            self.blocked_until = time.monotonic() + (float(retry) if retry.isdigit() else 60)
        return response

    async def status(self, request: Request) -> Response:
        return JSONResponse({"error_count": self.error_count,
                             "ready": time.monotonic() >= self.blocked_until})

    async def rpc(self, method: str, params: dict) -> dict:
        async with self.lock:
            if not self.initialized:
                response = await self.post_rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "dayuse-preservation-replay", "version": "1"}}, 1)
                init = decode_rpc(response)
                if "error" in init:
                    raise ValueError("upstream initialization failed")
                if response.headers.get("mcp-session-id"):
                    self.client.headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
                self.initialized = True
        return decode_rpc(await self.post_rpc(method, params))

    async def tools(self) -> dict:
        if self.catalog is None:
            path = self.cache / "catalog.json"
            if path.exists():
                self.catalog = json.loads(path.read_text())
            else:
                rpc = await self.rpc("tools/list", {})
                self.catalog = {"tools": [t for t in rpc["result"]["tools"] if t["name"] in READ_ONLY]}
                atomic_json(path, self.catalog)
        return self.catalog

    async def tool(self, name: str, args: dict, source_today: str | None) -> dict:
        if name not in READ_ONLY:
            raise ValueError("tool outside read-only replay allowlist")
        mapped, days = shift_request(name, args, source_today, self.inventory_day)
        key = hashlib.sha256(json.dumps([self.upstream, self.inventory_day, name, mapped],
                                      sort_keys=True).encode()).hexdigest()
        path = self.cache / (key + ".json")
        async with self.key_locks.setdefault(key, asyncio.Lock()):
            if path.exists():
                result = json.loads(path.read_text())["result"]
            else:
                rpc = await self.rpc("tools/call", {"name": name, "arguments": mapped})
                if "error" in rpc:
                    raise ValueError("upstream RPC error")
                result = rpc["result"]
                if not result.get("isError"):
                    atomic_json(path, {"tool": name, "arguments": mapped, "result": result,
                        "inventory_day": self.inventory_day})
        result = copy.deepcopy(result)
        if name == "search_offers" and days:
            if "structuredContent" in result:
                result["structuredContent"] = restore_dates(result["structuredContent"], days)
            for block in result.get("content", []):
                if block.get("type") == "text":
                    try:
                        block["text"] = json.dumps(restore_dates(json.loads(block["text"]), days))
                    except (ValueError, KeyError):
                        pass
        return result

    async def handle(self, request: Request) -> Response:
        if request.method != "POST":
            return Response(status_code=405)
        body = await request.json()
        if "id" not in body:
            return Response(status_code=202)
        method, params = body.get("method"), body.get("params", {})
        try:
            if method == "initialize":
                result = {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
                          "serverInfo": {"name": "dayuse-eval-fixtures", "version": "1"}}
            elif method == "tools/list":
                result = await self.tools()
            elif method == "tools/call":
                context = (params.get("_meta") or {}).get("dayuse_replay", {})
                result = await self.tool(params["name"], params.get("arguments", {}),
                                         context.get("x-replay-source-today"))
            elif method == "ping":
                result = {}
            else:
                return JSONResponse({"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32601, "message": "Method not available"}})
            return JSONResponse({"jsonrpc": "2.0", "id": body["id"], "result": result})
        except (ValueError, KeyError, httpx.HTTPError) as exc:
            self.error_count += 1
            # Error type only: do not leak headers, credentials or upstream bodies.
            return JSONResponse({"jsonrpc": "2.0", "id": body["id"], "error": {
                "code": -32603, "message": "Fixture dependency failed: " + type(exc).__name__}})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--inventory-day", required=True)
    parser.add_argument("--port", type=int, default=8370)
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(args.env_file)
    proxy = FixtureProxy(args.upstream, os.environ["MCP_B2C_AUTH_TOKEN"], args.cache, args.inventory_day)
    app = Starlette(routes=[Route("/mcp", proxy.handle, methods=["POST", "GET", "DELETE"]),
                           Route("/status", proxy.status)])
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
