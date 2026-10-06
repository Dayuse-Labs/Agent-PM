"""Strict generation contract; semantic validation remains in the concierge."""
from __future__ import annotations


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def response_format(families: tuple, languages: tuple, picks: tuple, confirmations: tuple) -> dict:
    text = {"type": "string"}
    edit = _object({"value": _nullable(text), "evidence": text})
    schema = _object({
        "family": {"type": "string", "enum": list(families)},
        "language": {"type": "string", "enum": list(languages)},
        "pick": {"type": "string", "enum": list(picks)},
        "pick_position": _nullable({"type": "integer"}),
        "affirmative": {"type": "boolean"},
        "booking_confirmation": {"type": "string", "enum": list(confirmations)},
        "wants_more_options": {"type": "boolean"},
        "bare_budget_value": _nullable({"type": "number"}),
        "hotel_name": _nullable(text),
        "display_currency": _nullable(text),
        "search_update": _object({
            "budget_max": _nullable(_object({"value": _nullable({"type": "number"}), "evidence": text, "currency": _nullable(text)})),
            "timeslot_start": _nullable(edit),
            "timeslot_end": _nullable(edit),
        }),
        "location_evidence": _nullable(text),
        "location_update": _object({
            "action": {"type": "string", "enum": ["retain", "replace", "refine"]},
            "kind": _nullable({"type": "string", "enum": ["city", "area", "landmark", "unknown"]}),
            "fields": {"type": "array", "items": _object({
                "field": {"type": "string", "enum": ["city", "zone", "metro", "country_code", "region"]},
                "value": _nullable(text),
            })},
        }),
    })
    return {"type": "json_schema", "json_schema": {"name": "concierge_triage", "strict": True, "schema": schema}}


def location_edit(value: object) -> dict | None:
    """Normalize the wire edit without conflating absent fields with clears."""
    if not isinstance(value, dict):
        return None
    if "fields" not in value:
        return value  # Existing adapters/tests may still supply the flat edit.
    fields = value["fields"]
    if not isinstance(fields, list):
        return None
    out = {"action": value.get("action")}
    if value.get("kind") is not None:
        out["kind"] = value["kind"]
    for item in fields:
        if not isinstance(item, dict) or set(item) != {"field", "value"}:
            return None
        key = item["field"]
        if key not in ("city", "zone", "metro", "country_code", "region") or key in out:
            return None
        out[key] = item["value"]
    return out
