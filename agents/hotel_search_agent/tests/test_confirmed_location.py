"""Provider receipt -> real A2A transport -> geocode reuse, without model places."""
from types import SimpleNamespace

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part, convert_genai_part_to_a2a_part
from google.genai import types

from hotel_search_agent.geocode_tool import inject_profile_geo_context
from hotel_search_agent.response_bridge import capture_after_tool, emit_search_datapart, find_datapart, skip_final_generation
from hotel_search_agent.tool_budget_guard import make_per_tool_budget_callback

class _Ctx:
    def __init__(self, state=None, user_content=None):
        self.state = state if state is not None else {}
        self.user_content = user_content


class _Tool:
    def __init__(self, name):
        self.name = name

PLACE = {"provider_id": "mapbox:milano-it", "name": "Milano", "label": "Milano, Italia",
         "feature_type": "place", "country_code": "IT", "region": "MI", "latitude": 45.46, "longitude": 9.19}
OTHER = {**PLACE, "provider_id": "mapbox:milano-other", "region": "PG", "label": "Milano, Umbria"}
PENDING = {"question": "Which Milano?", "options": [PLACE, OTHER]}


def test_clarification_candidates_cross_real_a2a_and_end_tool_loop():
    ctx = _Ctx()
    ctx.invocation_id = "place-question"
    capture_after_tool(_Tool("geocode_location"), {}, ctx,
        {"ok": False, "error": "geocode_ambiguous", "diagnostics": PENDING})
    guard = make_per_tool_budget_callback({"search_offers": 2}, 2)
    assert guard(_Tool("search_offers"), {}, ctx)["error"] == "location_requires_clarification"
    final = skip_final_generation(ctx, SimpleNamespace())
    assert final.content.parts[0].text == PENDING["question"]
    out = emit_search_datapart(ctx)
    parts = [convert_a2a_part_to_genai_part(convert_genai_part_to_a2a_part(p)) for p in out.parts]
    wire = find_datapart(parts)
    assert wire["location_clarification"] == PENDING and wire["requires_clarification"]
    assert "results" not in wire


def test_confirmed_identity_outranks_leaf_copied_city_or_device(monkeypatch):
    def forbidden():
        raise AssertionError("No provider lookup on a confirmed preserving turn")
    monkeypatch.setattr("hotel_search_agent.geocode_tool.get_mapbox_client", forbidden)
    part = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {"reuse_confirmed_location": True},
        "profile_in": {"confirmed_location": PLACE, "city": "Milano", "language": "en"}}))
    ctx = _Ctx(user_content=types.Content(role="user", parts=[types.Part(text="Want pool for kids"), convert_a2a_part_to_genai_part(part)]))
    result = inject_profile_geo_context(_Tool("geocode_location"), {"city": "Orlando", "origin": "device"}, ctx)
    assert result["resolved_location"] == PLACE and result["latitude"] == 45.46
    capture_after_tool(_Tool("geocode_location"), {}, ctx, result)
    wire = find_datapart(emit_search_datapart(ctx).parts)
    assert wire["resolved_location"] == PLACE


def test_same_provider_key_reuses_identity_without_redundant_model_flag(monkeypatch):
    def forbidden():
        raise AssertionError("A repeated city cannot be geocoded to a new homonym")
    monkeypatch.setattr("hotel_search_agent.geocode_tool.get_mapbox_client", forbidden)
    part = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {},
        "profile_in": {"confirmed_location": PLACE, "city": "Milano", "language": "en"}}))
    ctx = _Ctx(user_content=types.Content(role="user", parts=[types.Part(text="Under 90 euros"), convert_a2a_part_to_genai_part(part)]))
    result = inject_profile_geo_context(_Tool("geocode_location"), {"city": "Milano"}, ctx)
    assert result["resolved_location"] == PLACE
    assert inject_profile_geo_context(_Tool("geocode_location"), {"city": "Paris", "country_code": "FR"}, ctx) is None
