"""schema_guard.py — no argument outside the tool's published schema reaches
MCP_B2C (mcp-dayuse#8, QA trace 9bc5feb6: `currency` sent to search_offers)."""
from __future__ import annotations

from types import SimpleNamespace

from hotel_search_agent import schema_guard
from hotel_search_agent.schema_guard import drop_args_outside_schema

_SEARCH_OFFERS_SCHEMA = {
    "type": "object",
    "properties": {
        "lat": {"type": "number"},
        "lon": {"type": "number"},
        "date": {"type": "string"},
        "timeSlot": {
            "type": "object",
            "properties": {"startHour": {"type": "integer"}, "endHour": {"type": "integer"}},
            "additionalProperties": False,
        },
        "filters": {"type": "object", "properties": {"x": {"type": "integer"}}},
    },
    "required": ["lat", "lon", "date"],
    "additionalProperties": False,
}


def _tool(schema):
    return SimpleNamespace(name="search_offers", raw_mcp_tool=SimpleNamespace(inputSchema=schema))


def test_unknown_keys_are_dropped_known_ones_kept(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(
        schema_guard._metrics_logger, "info", lambda fmt, *a: lines.append(fmt % a)
    )
    args = {"lat": 1.0, "lon": 2.0, "date": "2026-10-07", "currency": "USD"}
    assert drop_args_outside_schema(_tool(_SEARCH_OFFERS_SCHEMA), args, None) is None
    assert args == {"lat": 1.0, "lon": 2.0, "date": "2026-10-07"}
    assert lines == ["dayuse_metric=schema_guard agent=b2c_hotel_search tool=search_offers dropped=currency"]


def test_nested_closed_objects_are_cleaned_too():
    args = {"lat": 1.0, "lon": 2.0, "date": "d", "timeSlot": {"startHour": 12, "endHour": 13, "startMinute": 1}}
    drop_args_outside_schema(_tool(_SEARCH_OFFERS_SCHEMA), args, None)
    assert args["timeSlot"] == {"startHour": 12, "endHour": 13}


def test_open_objects_are_left_alone():
    args = {"lat": 1.0, "lon": 2.0, "date": "d", "filters": {"x": 1, "y": 2}}
    drop_args_outside_schema(_tool(_SEARCH_OFFERS_SCHEMA), args, None)
    assert args["filters"] == {"x": 1, "y": 2}


def test_a_tool_without_a_schema_is_untouched():
    args = {"anything": 1}
    drop_args_outside_schema(SimpleNamespace(name="geocode_location"), args, None)
    assert args == {"anything": 1}
