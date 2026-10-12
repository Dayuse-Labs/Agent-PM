"""Last line before MCP_B2C: no argument outside the tool's published schema.

mcp-dayuse#8 (QA trace 9bc5feb6, "affiche en dollars"): the model added a
`currency` argument to `search_offers`, the server's `.strict()` schema
refused the whole call ("MCP error -32602: Input validation error ...
Unrecognized key(s) in object: 'currency'") and the user lost the search.

`drop_args_outside_schema` runs LAST in the before-tool chain — after the
callbacks that pop the virtual params the model is shown (`amenities`,
`date` label, `duration`, minutes) — and removes any key the tool's own
`inputSchema` does not declare, wherever that schema closes the object
(`additionalProperties: false`), nested objects included. The schema is the
one the server published to this session, not a copy that can drift.
"""
from __future__ import annotations

import logging
from typing import Any

# GDPR: key names only — never a value.
_metrics_logger = logging.getLogger("dayuse.metrics")


def _strip(value: dict[str, Any], schema: Any, path: str, dropped: list[str]) -> None:
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return
    if schema.get("additionalProperties") is False:
        for key in [k for k in value if k not in properties]:
            value.pop(key)
            dropped.append(f"{path}{key}")
    for key, sub_value in value.items():
        if isinstance(sub_value, dict):
            _strip(sub_value, properties.get(key), f"{path}{key}.", dropped)


def drop_args_outside_schema(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback`: mutate `args` in place, never short-circuit."""
    schema = getattr(getattr(tool, "raw_mcp_tool", None), "inputSchema", None)
    if not isinstance(schema, dict):
        return None
    dropped: list[str] = []
    _strip(args, schema, "", dropped)
    if dropped:
        _metrics_logger.info(
            "dayuse_metric=schema_guard agent=b2c_hotel_search tool=%s dropped=%s",
            getattr(tool, "name", "?"), ",".join(sorted(dropped)),
        )
    return None
