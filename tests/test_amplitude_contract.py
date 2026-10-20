"""Widget analytics contract (`contracts/amplitude_events.json`) ↔ the server's
`turn_facts` block: the widget copies every property marked
`"source": "turn_facts"` from it, so both sides must name and enumerate the
same values. A drift on either side fails here, offline."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest

from b2c_common.scores import FALLBACK_SCORE_NAMES, GUARD_SCORE_NAMES
from b2c_concierge import turn_facts
from b2c_concierge.triage import FAMILIES

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "amplitude_events.json"
EVENT_NAME = re.compile(r"^(pageview|ai_agent__[a-z0-9_]+)$")
SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
# The widget renames this one key; every other turn_facts key keeps its name.
WIDGET_NAME = {"trace_id": "langfuse_trace_id"}


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _turn_facts_properties(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for event in contract["events"].values():
        for name, spec in event["properties"].items():
            if spec.get("source") == "turn_facts":
                assert found.get(name, spec) == spec, f"{name} is declared twice, differently"
                found[name] = spec
    return found


def test_event_names_follow_the_naming_rule(contract):
    assert contract["events"]
    for name in contract["events"]:
        assert EVENT_NAME.fullmatch(name), name


def test_property_names_are_snake_case(contract):
    names = set(contract["common_properties"])
    for event in contract["events"].values():
        names |= set(event["properties"])
    for name in names:
        assert SNAKE_CASE.fullmatch(name), name


def test_turn_facts_keys_are_exactly_the_turn_facts_properties(contract):
    server_keys = {WIDGET_NAME.get(key, key) for key in turn_facts.TurnFacts.__required_keys__}
    assert server_keys == set(_turn_facts_properties(contract))


@pytest.mark.parametrize(
    ("prop", "server_values"),
    [
        ("family", (*FAMILIES, turn_facts.UNKNOWN_FAMILY)),
        ("response_type", get_args(turn_facts.ResponseType)),
        ("empty_reason", get_args(turn_facts.EmptyReason)),
        ("clarification_reason", get_args(turn_facts.ClarificationReason)),
    ],
)
def test_enums_match_what_the_server_emits(contract, prop, server_values):
    assert set(_turn_facts_properties(contract)[prop]["enum"]) == set(server_values)


def test_status_enum_is_what_the_server_can_send(contract):
    assert set(_turn_facts_properties(contract)["status"]["enum"]) == set(
        get_args(turn_facts.FactsStatus)
    )


def test_every_enum_carried_by_turn_facts_is_checked(contract):
    enumerated = {name for name, spec in _turn_facts_properties(contract).items() if "enum" in spec}
    assert enumerated == {"family", "status", "response_type", "empty_reason", "clarification_reason"}


@pytest.mark.parametrize(
    ("prop", "names"), [("guards_fired", GUARD_SCORE_NAMES), ("fallbacks", FALLBACK_SCORE_NAMES)]
)
def test_score_name_lists_are_string_arrays(contract, prop, names):
    spec = _turn_facts_properties(contract)[prop]
    assert spec["type"] == "array" and spec["items"] == "string"
    assert all(SNAKE_CASE.fullmatch(name) for name in names)


def test_built_facts_only_carry_known_score_names():
    facts = turn_facts.spine_turn_facts(
        family="search", route="leaf:hotel_search", status="ok", hotels_returned=0,
        fired={"window_match", "not_a_guard"}, fallbacks={"mcp_error", "not_a_fallback"},
    )
    assert facts["guards_fired"] == ["window_match"]
    assert facts["fallbacks"] == ["mcp_error"]
