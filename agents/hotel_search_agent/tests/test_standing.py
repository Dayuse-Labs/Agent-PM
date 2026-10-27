"""« Très classe » → 4- and 5-star hotels (prod session 1eb2430a, 2026-10-27).

The leaf's model reads the standing into a closed value; the code owns the
filter (`starRatings`), carries it from the profile and drops any value the
model wrote itself."""
from __future__ import annotations

from types import SimpleNamespace

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from hotel_search_agent.response_bridge import STATE_STANDING_KEY, emit_search_datapart
from hotel_search_agent.standing import STANDING_PROPERTY, enforce_standing

_SEARCH = SimpleNamespace(name="search_offers")


def _ctx(profile_in: dict | None = None) -> SimpleNamespace:
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    return SimpleNamespace(state={}, user_content=genai_types.Content(
        role="user",
        parts=[genai_types.Part(text="Je veux une chambre très classe"), convert_a2a_part_to_genai_part(datapart)],
    ))


def test_the_model_sees_a_closed_enum():
    assert STANDING_PROPERTY["enum"] == ["upscale", "any"]


def test_upscale_is_four_and_five_stars():
    ctx, args = _ctx(), {"standing": "upscale"}
    enforce_standing(_SEARCH, args, ctx)
    assert args == {"starRatings": [4, 5]}
    assert ctx.state[STATE_STANDING_KEY] == "upscale"


def test_it_is_carried_from_the_profile():
    ctx, args = _ctx({"standing": "upscale"}), {}
    enforce_standing(_SEARCH, args, ctx)
    assert args["starRatings"] == [4, 5]


def test_any_drops_a_carried_standing():
    ctx, args = _ctx({"standing": "upscale"}), {"standing": "any"}
    enforce_standing(_SEARCH, args, ctx)
    assert "starRatings" not in args
    assert ctx.state[STATE_STANDING_KEY] == ""


def test_a_star_filter_the_model_wrote_itself_is_dropped():
    ctx, args = _ctx(), {"starRatings": [1, 2]}
    enforce_standing(_SEARCH, args, ctx)
    assert "starRatings" not in args


def test_an_unknown_value_is_ignored():
    ctx, args = _ctx(), {"standing": "palace"}
    enforce_standing(_SEARCH, args, ctx)
    assert args == {}


def test_the_name_lookup_never_receives_it():
    args = {"name": "Ritz", "standing": "upscale"}
    enforce_standing(SimpleNamespace(name="find_hotel_by_name"), args, _ctx())
    assert args == {"name": "Ritz"}


def _delta(standing: str) -> dict:
    ctx = SimpleNamespace(state={"temp:hotel_search_results": [], STATE_STANDING_KEY: standing}, user_content=None)
    content = emit_search_datapart(ctx)
    from google.adk.a2a.converters.part_converter import convert_genai_part_to_a2a_part

    data = next(
        convert_genai_part_to_a2a_part(p).root.data for p in content.parts if p.inline_data is not None
    )
    return data


def test_the_profile_keeps_it_and_the_no_offers_line_cites_it():
    data = _delta("upscale")
    assert data["profile_delta"]["standing"] == {"op": "set", "value": "upscale"}
    assert data["search_context"]["standing"] == "upscale"


def test_a_search_without_standing_clears_it():
    assert _delta("")["profile_delta"]["standing"] == {"op": "clear"}
