"""Snapshot the MCP_B2C contract the agents rely on (mcp-dayuse#8, item 5).

Writes `contracts/mcp_b2c_tools.json`: every tool's `inputSchema` as the
server publishes it, plus the live equipment catalogue (`list_amenities`).
`tests/test_mcp_contract.py` checks the agents' tool calls and the
`EQUIPMENT_IDS` table against it, offline, in CI.

Re-run after any MCP_B2C deploy that touches a tool schema, then commit the
diff — it IS the contract change, reviewed like code:

    set -a; . ./.env; set +a; .venv/bin/python scripts/refresh_mcp_contract.py

Reads MCP_B2C_URL / MCP_B2C_AUTH_TOKEN, the same two variables as the leaf.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

OUT = Path(__file__).resolve().parent.parent / "contracts" / "mcp_b2c_tools.json"


def _amenities(result: Any) -> list[dict[str, Any]]:
    payload = result.structuredContent
    if not isinstance(payload, dict):
        text = "".join(getattr(c, "text", "") for c in result.content)
        payload = json.loads(text) if text else {}
    items = payload.get("amenities") or payload.get("items") or payload.get("data") or []
    keep = ("id", "slug", "name", "label", "group", "category")
    return sorted(
        ({k: item[k] for k in keep if k in item} for item in items if isinstance(item, dict)),
        key=lambda item: item.get("id", 0),
    )


async def main() -> int:
    url = os.environ.get("MCP_B2C_URL", "").strip()
    if not url:
        print("MCP_B2C_URL is not set", file=sys.stderr)
        return 2
    token = os.environ.get("MCP_B2C_AUTH_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            snapshot: dict[str, Any] = {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "tools": {tool.name: tool.inputSchema for tool in sorted(tools, key=lambda t: t.name)},
            }
            if any(tool.name == "list_amenities" for tool in tools):
                snapshot["amenities"] = _amenities(await session.call_tool("list_amenities", {}))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}: "
          f"{len(snapshot['tools'])} tools, {len(snapshot.get('amenities', []))} amenities")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
