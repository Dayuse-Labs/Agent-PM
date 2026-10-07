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
        "budget_action": {"type": "string", "enum": ["retain", "set", "clear", "cheaper"]},
        "travel_time_request": _nullable({"type": "boolean"}),
        "stay_kind": _nullable({"type": "string", "enum": ["overnight", "day_use"]}),
        "search_priority": _nullable({"type": "string", "enum": ["price", "distance", "rating", "relevance"]}),
        "search_update": _object({
            "budget_max": _nullable(_object({"value": _nullable({"type": "number"}), "evidence": text, "currency": _nullable(text)})),
            "timeslot_start": _nullable(edit),
            "timeslot_end": _nullable(edit),
        }),
        "location_evidence": _nullable(text),
        "location_update": {"anyOf": [_object({"action": {"type": "string", "enum": ["retain"]}}), _object({
            "action": {"type": "string", "enum": ["replace", "refine"]},
            "kind": _nullable({"type": "string", "enum": ["city", "area", "landmark", "unknown"]}),
            "city": {**_nullable(text), "description": "Municipality, not a state or landmark. For a well-known landmark, its known parent city is a candidate independently verified by the geocoder."},
            "zone": {**_nullable(text), "description": "Named district/borough/landmark within a city. Never a state, province or country. Keep the complete airport or station name."},
            "metro": _nullable(text),
            "country_code": {**_nullable(text), "description": "ISO2 only from an explicit country or unambiguous stated state/province."},
            "region": {**_nullable(text), "description": "State/province (expanded abbreviation); never put it in zone."},
            "clear_fields": {"type": "array", "items": {"type": "string", "enum": ["city", "zone", "metro", "country_code", "region"]}},
        })]},
    })
    return {"type": "json_schema", "json_schema": {"name": "concierge_triage", "strict": True, "schema": schema}}


def location_edit(value: object) -> dict | None:
    """Normalize the wire edit without conflating absent fields with clears."""
    if not isinstance(value, dict):
        return None
    if "clear_fields" not in value:
        return value  # Existing adapters may still supply the internal flat edit.
    clears = value["clear_fields"]
    allowed = ("city", "zone", "metro", "country_code", "region")
    if not isinstance(clears, list) or any(k not in allowed for k in clears):
        return None
    out = {"action": value.get("action")}
    if value.get("kind") is not None:
        out["kind"] = value["kind"]
    for key in allowed:
        if key in clears:
            if value.get(key) is not None:
                return None
            out[key] = None
        elif value.get(key) is not None:
            out[key] = value[key]
    return out
