"""Agents ↔ MCP_B2C contract test (mcp-dayuse#8, structural fix).

QA trace 9bc5feb6: the leaf sent `search_offers` an argument its `.strict()`
schema refuses, and nothing in CI could have seen it — every test used a
hand-written stub schema. Here the reference is `contracts/mcp_b2c_tools.json`,
the schemas the server itself publishes (`scripts/refresh_mcp_contract.py`).

- The leaf's `search_offers` / `find_hotel_by_name` arguments, as the REAL
  before-tool chain rewrites them from what the model emits, validate against
  the published schema — WITHOUT the last-line `schema_guard`, so a key the
  code itself injects can never hide behind it.
- Every equipment id the leaf can send exists in the live `list_amenities`
  catalogue (id 3001 did not, ticket mcp-dayuse#4).

The concierge's inline calls are checked by `assert_mcp_contract` inside
`agents/b2c_concierge/tests/test_inline_tools.py`'s fake session.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from hotel_search_agent.agent import root_agent
from hotel_search_agent.equipment_ids import EQUIPMENT_IDS
from hotel_search_agent.schema_guard import drop_args_outside_schema

CONTRACT = Path(__file__).resolve().parent.parent / "contracts" / "mcp_b2c_tools.json"


def _contract() -> dict[str, Any]:
    assert CONTRACT.exists(), (
        "contracts/mcp_b2c_tools.json is missing — run scripts/refresh_mcp_contract.py"
    )
    return json.loads(CONTRACT.read_text())


def assert_mcp_contract(tool_name: str, arguments: dict[str, Any]) -> None:
    schema = _contract()["tools"].get(tool_name)
    assert schema is not None, f"{tool_name} is not a tool the MCP publishes"
    jsonschema.validate(arguments, schema)


class _ToolContext:
    invocation_id = "contract-test"
    agent_name = "b2c_hotel_search"

    def __init__(self, profile_in: dict[str, Any]):
        self.state: dict[str, Any] = {}
        datapart = a2a_types.Part(
            root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in})
        )
        self.user_content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text="un hôtel"), convert_a2a_part_to_genai_part(datapart)],
        )


def _arguments_sent(tool_name: str, model_args: dict[str, Any], profile_in: dict[str, Any]) -> dict:
    """The arguments MCP would receive: the model's call rewritten by every
    before-tool callback of the leaf, minus the schema guard."""
    schema = _contract()["tools"][tool_name]
    tool = SimpleNamespace(name=tool_name, raw_mcp_tool=SimpleNamespace(inputSchema=schema))
    args = copy.deepcopy(model_args)
    ctx = _ToolContext(profile_in)
    callbacks = root_agent.before_tool_callback
    assert isinstance(callbacks, list)
    for callback in callbacks:
        if callback is drop_args_outside_schema:
            continue
        short_circuit = callback(tool, args, ctx)
        assert short_circuit is None, f"{getattr(callback, '__name__', callback)} refused the call"
    return args


_PROFILE = {
    "language": "fr",
    "client_timezone": "Europe/Paris",
    "budget_max": 150,
    "amenities": ["spa"],
    "adults": 2,
    "children": 1,
    "search_cursor": 1,
    "shown_hotel_ids": [1, 2],
}


@pytest.mark.parametrize(
    "model_args",
    [
        # What the model emits on a rich search: virtual params included.
        {
            "lat": 45.764, "lon": 4.8357,
            "date": {"type": "relative", "value": "tomorrow", "expression": "demain"},
            "timeSlot": {"startHour": 22, "startMinute": 1, "endHour": 23, "endMinute": 1},
            "amenities": ["pool"],
            "priceRangeMax": 120,
        },
        {
            "lat": 43.7, "lon": 7.27,
            "date": {"type": "absolute", "value": "10-03", "expression": "3 octobre"},
            "duration": "PT2H",
            "timeSlot": {"startHour": 14},
        },
        {"lat": 48.85, "lon": 2.35},
    ],
    ids=["rich", "duration", "minimal"],
)
def test_search_offers_arguments_match_the_published_schema(model_args):
    assert_mcp_contract("search_offers", _arguments_sent("search_offers", model_args, _PROFILE))


def test_find_hotel_by_name_arguments_match_the_published_schema():
    args = _arguments_sent("find_hotel_by_name", {"name": "Pullman Lyon"}, _PROFILE)
    assert_mcp_contract("find_hotel_by_name", args)


# Known drift, kept on purpose: 3001 is in the server's own pool OR-group
# (`pool-equipment-ids.ts`) but not in `list_amenities` (2026-10-06). In an OR
# group it changes nothing when absent; dropping it could exclude a hotel
# tagged only 3001. The decision belongs to mcp-dayuse#4.
_KNOWN_OUTSIDE_CATALOGUE = {3001}


def test_every_equipment_id_exists_in_the_live_catalogue():
    catalogue = {item["id"] for item in _contract().get("amenities", [])}
    assert catalogue, "the snapshot carries no list_amenities catalogue"
    unknown = {
        key: [i for i in ids if i not in catalogue and i not in _KNOWN_OUTSIDE_CATALOGUE]
        for key, ids in EQUIPMENT_IDS.items()
    }
    assert {k: v for k, v in unknown.items() if v} == {}
    # The exception list must not outlive its reason.
    assert _KNOWN_OUTSIDE_CATALOGUE - catalogue == _KNOWN_OUTSIDE_CATALOGUE
