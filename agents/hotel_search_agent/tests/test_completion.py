"""A thin first page is completed from one wider search (prod session 1eb2430a).

« Autour de saint ouen sur seine », pool + spa, €300: a 2 km ring returned 1
hotel while 19 matched within 20 km. `completion.py` runs ONE more search, wider
and nearest first, without the optional wishes; `capture_after_tool` appends its
hotels after the first page's. Offline: the MCP tool is a fake that records the
arguments of the completion call.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from google.adk.a2a.converters.part_converter import convert_genai_part_to_a2a_part

from hotel_search_agent.completion import complete_thin_search_after_tool
from hotel_search_agent.response_bridge import (
    STATE_APPLIED_AMENITIES_KEY,
    STATE_COMPLETION_KEY,
    STATE_NEARBY_KEY,
    STATE_PREFERRED_AMENITIES_KEY,
    STATE_SEARCH_DATE_KEY,
    capture_after_tool,
    emit_search_datapart,
)


def _hotel(i: int) -> dict:
    return {
        "hotelId": i, "name": f"Hotel {i}", "cityName": "Paris", "countryName": "France",
        "starRating": 4, "globalAverageRating": 4.5,
        "offers": [{"priceEuro": 9000 + i, "startHour": 10, "startMinute": 0, "endHour": 17,
                    "endMinute": 0, "availabilityDate": "2026-11-19", "ratePlanId": 1}],
    }


def _response(*ids: int, total: int | None = None) -> dict:
    return {"structuredContent": {"resolvedDate": "2026-11-19", "total": len(ids) if total is None else total,
                                  "results": [_hotel(i) for i in ids]}}


class _Search:
    """The MCP `search_offers` tool, as the after-tool callback receives it."""

    name = "search_offers"

    def __init__(self, response: dict | Exception, schema: dict | None = None):
        self.response = response
        self.calls: list[dict] = []
        self.raw_mcp_tool = SimpleNamespace(inputSchema=schema) if schema else None

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


#: What the before-tool callbacks sent on T5 (Saint-Ouen as a landmark, 2 km).
_SENT = {"lat": 48.91177, "lon": 2.333646, "date": "2026-11-19", "priceRangeMax": 300, "from": 0,
         "radiusKm": 2.0, "sortBy": "distance", "hotelEquipmentIds": [33, 34, 2982, 3000, 3001, 35]}


def _state(**extra) -> dict:
    return {STATE_APPLIED_AMENITIES_KEY: ["pool", "spa"], STATE_PREFERRED_AMENITIES_KEY: [],
            STATE_SEARCH_DATE_KEY: {"date": "2026-11-19", "same_day": False}, **extra}


def _run(tool: _Search, args: dict, state: dict, first: dict) -> SimpleNamespace:
    ctx = SimpleNamespace(state=state, user_content=None)
    assert asyncio.run(complete_thin_search_after_tool(tool, dict(args), ctx, first)) is None
    return ctx


def test_a_thin_page_is_completed_from_a_wider_search_nearest_first():
    tool = _Search(_response(1, 2, 3, 4, 5, 6))
    ctx = _run(tool, _SENT, _state(), _response(1))
    [sent] = tool.calls
    assert sent["radiusKm"] == 50.0
    assert sent["sortBy"] == "distance"
    assert "from" not in sent
    assert sent["hotelEquipmentIds"] == _SENT["hotelEquipmentIds"]  # required filters kept
    assert ctx.state[STATE_COMPLETION_KEY]["radius_km"] == 50.0


def test_an_optional_wish_is_relaxed_and_a_city_search_widened():
    """« une piscine intérieure et idéalement un massage », a city (no radius)."""
    tool = _Search(_response(7, 8))
    sent = {**_SENT, "hotelEquipmentIds": [34, 35]}
    sent.pop("radiusKm")
    _run(tool, sent, _state(**{STATE_APPLIED_AMENITIES_KEY: ["indoor_pool"],
                               STATE_PREFERRED_AMENITIES_KEY: ["spa"]}), _response(1, 2))
    assert tool.calls[0]["hotelEquipmentIds"] == [34]
    assert tool.calls[0]["radiusKm"] == 50.0


def test_a_nearby_ask_completes_further():
    tool = _Search(_response(2))
    _run(tool, {**_SENT, "radiusKm": 50.0}, _state(**{STATE_NEARBY_KEY: True}), _response())
    assert tool.calls[0]["radiusKm"] == 100.0


def test_no_filter_left_drops_the_equipment_ids():
    tool = _Search(_response(2))
    _run(tool, _SENT, _state(**{STATE_APPLIED_AMENITIES_KEY: [], STATE_PREFERRED_AMENITIES_KEY: ["spa"]}),
         _response())
    assert "hotelEquipmentIds" not in tool.calls[0]


def test_an_argument_the_live_schema_lacks_is_dropped():
    schema = {"type": "object", "additionalProperties": False,
              "properties": {k: {} for k in ("lat", "lon", "date", "priceRangeMax", "radiusKm", "hotelEquipmentIds")}}
    tool = _Search(_response(2), schema=schema)
    _run(tool, _SENT, _state(), _response(1))
    assert "sortBy" not in tool.calls[0]


def test_never_fires_when_there_is_nothing_to_gain():
    cases = [
        (_SENT, _state(), _response(1, 2, 3, 4, 5)),  # a full page
        ({**_SENT, "from": 5}, _state(), _response(6)),  # a later page
        ({**_SENT, "radiusKm": 50.0}, _state(), _response(1)),  # already the widest, no wish
        # Same-day dead end: hotels exist, all past cutoff — the D+1 probe's case.
        (_SENT, _state(**{STATE_SEARCH_DATE_KEY: {"date": "2026-11-19", "same_day": True}}),
         _response(total=12)),
        (_SENT, _state(), {"isError": True, "content": []}),
        (_SENT, _state(), {"ok": False, "error": "mcp_circuit_open"}),
    ]
    for args, state, first in cases:
        tool = _Search(_response(9))
        ctx = _run(tool, args, state, first)
        assert tool.calls == [] and STATE_COMPLETION_KEY not in ctx.state, (args, first)


def test_other_tools_are_untouched():
    tool = _Search(_response(9))
    tool.name = "find_hotel_by_name"
    _run(tool, _SENT, _state(), _response(1))
    assert tool.calls == []


def test_a_failure_is_swallowed():
    ctx = _run(_Search(RuntimeError("429")), _SENT, _state(), _response(1))
    assert STATE_COMPLETION_KEY not in ctx.state


def test_an_empty_completion_stashes_nothing():
    ctx = _run(_Search(_response()), _SENT, _state(), _response(1))
    assert STATE_COMPLETION_KEY not in ctx.state


# --- capture_after_tool appends, the concierge is told ------------------------------------


def _captured(first: dict, completion_ids: tuple[int, ...], **state) -> tuple[SimpleNamespace, dict]:
    ctx = SimpleNamespace(state=_state(**state), user_content=None)
    ctx.state[STATE_COMPLETION_KEY] = {"payload": _response(*completion_ids)["structuredContent"],
                                       "radius_km": 50.0, "relaxed": ["spa"]}
    capture_after_tool(SimpleNamespace(name="search_offers"), dict(_SENT), ctx, first)
    content = emit_search_datapart(ctx)
    data = next(convert_genai_part_to_a2a_part(p).root.data for p in content.parts if p.inline_data is not None)
    return ctx, data


def test_the_first_page_comes_first_then_the_completion_without_duplicates():
    _, data = _captured(_response(1), (1, 2, 3, 4, 5, 6))
    assert [card["hotel_id"] for card in data["results"]] == [1, 2, 3, 4, 5]
    assert data["completion"] == {"added": 4, "radius_km": 50.0, "relaxed": ["spa"]}


def test_an_optional_wish_is_stamped_on_the_first_page_only():
    _, data = _captured(_response(1), (2,), **{STATE_APPLIED_AMENITIES_KEY: ["pool"],
                                               STATE_PREFERRED_AMENITIES_KEY: ["spa"]})
    by_id = {card["hotel_id"]: card["amenities"] for card in data["results"]}
    assert by_id == {1: ["pool", "spa"], 2: ["pool"]}


def test_a_full_first_page_takes_nothing_from_a_stale_completion():
    _, data = _captured(_response(1, 2, 3, 4, 5), (6,))
    assert [card["hotel_id"] for card in data["results"]] == [1, 2, 3, 4, 5]
    assert "completion" not in data
