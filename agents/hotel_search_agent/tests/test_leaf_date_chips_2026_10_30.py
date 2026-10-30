"""The day chips under next-day cards (2026-10-30), on the leaf's side.

The concierge sends `query_params.date_chip` when the message IS one of the
chips it offered (a fact it checks against its own state):
- « Ce soir quand même » (`same_day`): today, the offers still open, never the
  next day — no next-day probe, no « demain, plus près », no rescue moving to
  the day after;
- « Pas de date précise » (`first_open_day`): the same search day after day
  from today, 7 days at most, and the first day with hotels close by is shown
  (ranked like any search); none: the day with the closest, said; nothing at
  all: said too.

Fixtures: Arabellapark (München) as geocoded in prod, hotels placed at the
distances prod showed on 2026-10-29 (`test_closer_tomorrow_2026_10_30.py`);
MCP pages in the real shape (`total`, `totalBeforeCutoff`, `results`).
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from hotel_search_agent import extra_calls
from hotel_search_agent.datetime_resolver import (
    probe_next_day_after_tool,
    reference_today,
    resolve_search_date,
)
from hotel_search_agent.relaxation import rescue_empty_search_after_tool
from hotel_search_agent.response_bridge import (
    STATE_DATE_FALLBACK_KEY,
    STATE_RESCUE_KEY,
    STATE_RESOLVED_DATE_KEY,
    STATE_SEARCH_DATE_KEY,
    _STATE_ANCHOR_KEY,
    _STATE_RESULTS_KEY,
    capture_after_tool,
)

#: `datetime_resolver.STATE_FIRST_OPEN_KEY` (written out: absent before 2026-10-30).
STATE_FIRST_OPEN_KEY = "temp:hotel_search_first_open_day"
SPOT = (48.15269343, 11.62100352)
TODAY = reference_today({})


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _hotel(hotel_id: int, km_east: float, day: str) -> dict:
    return {"hotelId": hotel_id, "name": f"Hotel {hotel_id}", "lat": SPOT[0], "lon": SPOT[1] + km_east / 74.1,
            "offers": [{"priceEuro": 10500, "priceEuroWithBookingFees": 10500, "availabilityDate": day,
                        "startHour": 14, "endHour": 21}]}


def _far(day: str) -> list[dict]:
    """Tonight in prod: the offers still open 3.9-4.6 km away."""
    return [_hotel(1, -3.9, day), _hotel(2, 4.1, day), _hotel(3, 4.6, day)]


def _close(day: str, first_id: int = 10) -> list[dict]:
    return [_hotel(first_id + i, 0.2 + 0.3 * i, day) for i in range(4)]


class _Search:
    """`search_offers` answering a page per date (MCP's shape)."""
    name = "search_offers"

    def __init__(self, pages: dict[str, list[dict]] | None = None):
        self.pages = pages or {}
        self.calls: list[dict] = []

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        results = self.pages.get(args["date"], [])
        return {"structuredContent": {"total": len(results), "totalBeforeCutoff": 19, "results": results}}


def _ctx(chip: str | None, anchor_type: str = "poi", profile_in: dict | None = None) -> SimpleNamespace:
    query_params = {"date_chip": chip} if chip else {}
    datapart = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": query_params,
                                                            "profile_in": profile_in or {}}))
    parts = [genai_types.Part(text="Pas de date précise"), convert_a2a_part_to_genai_part(datapart)]
    return SimpleNamespace(state={
        _STATE_ANCHOR_KEY: {"latitude": SPOT[0], "longitude": SPOT[1], "label": "Arabellapark", "type": anchor_type},
    }, user_content=genai_types.Content(role="user", parts=parts))


def _args() -> dict:
    return {"lat": SPOT[0], "lon": SPOT[1], "radiusKm": 5, "sortBy": "distance"}


def _search(ctx, tool: _Search, first_page: list[dict], total_before: int = 19, label: dict | None = None) -> list[dict]:
    """resolve the date, run the leaf's after-tool callbacks on the model's
    own page (today's), return the cards. `label`: the model's reading of the
    chip's words (« tomorrow », the worst case), none for a plain search."""
    args = _args()
    args["date"] = label if label is not None else {"type": "relative", "value": "tomorrow"}
    if label == {}:
        del args["date"]
    resolve_search_date(tool, args, ctx)
    response = {"structuredContent": {"total": len(first_page), "totalBeforeCutoff": total_before,
                                      "results": first_page}}
    asyncio.run(probe_next_day_after_tool(tool, args, ctx, response))
    asyncio.run(rescue_empty_search_after_tool(tool, args, ctx, response))
    capture_after_tool(tool, args, ctx, response)
    return ctx.state[_STATE_RESULTS_KEY]


# --- « Ce soir quand même » ---------------------------------------------------------------------


def test_tonight_anyway_searches_today_whatever_the_model_read():
    ctx = _ctx("same_day")
    args = {**_args(), "date": {"type": "relative", "value": "tomorrow"}}
    resolve_search_date(_Search(), args, ctx)

    assert args["date"] == TODAY.isoformat()
    assert ctx.state[STATE_SEARCH_DATE_KEY] == {"date": TODAY.isoformat(), "same_day": True}
    assert ctx.state[STATE_RESOLVED_DATE_KEY]["date"] == TODAY.isoformat()
    assert ctx.state[STATE_RESOLVED_DATE_KEY]["date_reference"]["resolved_from"] == "tonight_chip"


def test_tonight_anyway_keeps_tonights_far_offers_and_never_probes_the_next_day():
    ctx = _ctx("same_day")
    tool = _Search({_day(1): _close(_day(1))})
    cards = _search(ctx, tool, _far(_day(0)))

    assert tool.calls == []  # no « demain, plus près », no next-day probe
    assert [card["hotel_id"] for card in cards] == [1, 2, 3]
    assert ctx.state[STATE_SEARCH_DATE_KEY]["date"] == TODAY.isoformat()
    assert "closer_from" not in ctx.state[STATE_SEARCH_DATE_KEY]


def test_tonight_anyway_on_a_closed_day_says_closed_and_moves_nowhere():
    ctx = _ctx("same_day")
    tool = _Search({_day(1): _close(_day(1))})
    cards = _search(ctx, tool, [])

    assert tool.calls == []  # neither the probe nor the rescue goes to the day after
    assert cards == []
    assert ctx.state[STATE_SEARCH_DATE_KEY].get("cutoff_closed") is True
    assert STATE_DATE_FALLBACK_KEY not in ctx.state and STATE_RESCUE_KEY not in ctx.state


def test_without_the_chip_the_same_evening_moves_to_the_next_day():
    """Control: the same page with no chip is « demain, plus près »."""
    ctx = _ctx(None)
    tool = _Search({_day(1): _close(_day(1))})
    cards = _search(ctx, tool, _far(_day(0)), label={})

    assert ctx.state[STATE_SEARCH_DATE_KEY].get("closer_from") == TODAY.isoformat()
    assert cards[0]["hotel_id"] == 10


# --- « Pas de date précise » --------------------------------------------------------------------


def test_no_specific_date_shows_the_first_day_with_hotels_close_by():
    ctx = _ctx("first_open_day")
    # Tonight: far only. Tomorrow: one close hotel. The day after: four.
    tool = _Search({_day(0): _far(_day(0)), _day(1): [_hotel(20, 0.5, _day(1))] + _far(_day(1)),
                    _day(2): _close(_day(2)), _day(3): _close(_day(3), 30)})
    cards = _search(ctx, tool, _far(_day(0)))

    assert [call["date"] for call in tool.calls] == [_day(0), _day(1), _day(2)]  # one round of 3
    assert [card["hotel_id"] for card in cards][:4] == [10, 11, 12, 13]
    assert ctx.state[STATE_SEARCH_DATE_KEY] == {
        "date": _day(2), "same_day": False, "first_open_from": _day(0),
        "first_open_days": 3, "first_open_found": True,
    }
    assert ctx.state[STATE_RESOLVED_DATE_KEY] == {"date": _day(2),
                                                  "date_reference": {"resolved_from": "first_open_day"}}


def test_no_specific_date_keeps_today_when_today_has_hotels_close_by():
    ctx = _ctx("first_open_day")
    tool = _Search({_day(0): _close(_day(0))})
    cards = _search(ctx, tool, _close(_day(0)))

    assert [call["date"] for call in tool.calls] == [_day(0), _day(1), _day(2)]
    assert cards[0]["hotel_id"] == 10
    assert ctx.state[STATE_SEARCH_DATE_KEY]["date"] == _day(0)
    assert ctx.state[STATE_SEARCH_DATE_KEY]["first_open_found"] is True


def test_no_day_close_by_within_7_days_shows_the_closest_day_and_says_so():
    ctx = _ctx("first_open_day")
    pages = {_day(i): _far(_day(i)) for i in range(10)}
    pages[_day(4)] = [_hotel(40, 1.0, _day(4)), _hotel(41, 1.5, _day(4))] + _far(_day(4))  # 2 close: the best
    pages[_day(8)] = _close(_day(8))  # beyond the 7 days: never looked at
    tool = _Search(pages)
    cards = _search(ctx, tool, _far(_day(0)))

    assert sorted(call["date"] for call in tool.calls) == [_day(i) for i in range(7)]
    assert cards[0]["hotel_id"] == 40
    assert ctx.state[STATE_SEARCH_DATE_KEY] == {
        "date": _day(4), "same_day": False, "first_open_from": _day(0),
        "first_open_days": 7, "first_open_found": False,
    }


def test_no_offer_at_all_within_7_days_is_said_with_no_card():
    ctx = _ctx("first_open_day")
    tool = _Search({})
    cards = _search(ctx, tool, [])

    assert len(tool.calls) == 7
    assert cards == []
    assert ctx.state[STATE_SEARCH_DATE_KEY]["first_open_days"] == 7
    assert ctx.state[STATE_SEARCH_DATE_KEY]["first_open_found"] is False
    assert STATE_RESCUE_KEY not in ctx.state  # the scan is the answer, no relaxing


def test_the_scan_stops_at_the_turns_deadline_and_says_how_many_days_it_saw(monkeypatch):
    ctx = _ctx("first_open_day")
    tool = _Search({})
    calls = {"n": 0}
    real_may_call = extra_calls.may_call

    def may_call(tool_context):
        calls["n"] += 1
        return calls["n"] <= 3 and real_may_call(tool_context)

    monkeypatch.setattr(extra_calls, "may_call", may_call)
    _search(ctx, tool, [])

    assert len(tool.calls) == 3
    assert ctx.state[STATE_FIRST_OPEN_KEY]["checked"] == 3
    assert ctx.state[STATE_SEARCH_DATE_KEY]["first_open_days"] == 3


def test_around_a_city_the_count_is_the_local_discs():
    """A city is searched by relevance over 20 km: the scan asks each day on
    the local disc, so « close by » counts the disc's hotels."""
    ctx = _ctx("first_open_day", anchor_type="city_centroid")
    ctx.state["temp:hotel_search_anchor_feature"] = "place"
    tool = _Search({_day(0): _close(_day(0))})
    args = {"lat": SPOT[0], "lon": SPOT[1], "date": {"type": "relative", "value": "today"}}
    resolve_search_date(tool, args, ctx)
    response = {"structuredContent": {"total": 4, "results": _close(_day(0))}}
    asyncio.run(probe_next_day_after_tool(tool, args, ctx, response))

    scan = [call for call in tool.calls if call["date"] == _day(0)]
    assert scan and all(call.get("radiusKm") for call in scan)
    assert ctx.state[STATE_FIRST_OPEN_KEY]["found"] is True


@pytest.mark.parametrize("chip", ["same_day", "first_open_day"])
def test_a_later_page_is_never_rescanned(chip):
    ctx = _ctx(chip)
    tool = _Search({})
    args = {**_args(), "date": TODAY.isoformat(), "from": 5}
    ctx.state[STATE_SEARCH_DATE_KEY] = {"date": TODAY.isoformat(), "same_day": True}
    asyncio.run(probe_next_day_after_tool(tool, args, ctx, {"structuredContent": {"total": 0, "results": []}}))
    assert tool.calls == []


def test_an_unknown_chip_leaves_the_day_to_the_model():
    ctx = _ctx("next_week")  # not a chip the concierge sends
    args = {**_args(), "date": {"type": "relative", "value": "tomorrow"}}
    resolve_search_date(_Search(), args, ctx)
    assert args["date"] == (date.fromisoformat(TODAY.isoformat()) + timedelta(days=1)).isoformat()


def test_a_day_chip_searches_the_day_the_concierge_set():
    ctx = _ctx("day", profile_in={"date": _day(2)})
    args = {**_args(), "date": {"type": "relative", "value": "today"}}
    resolve_search_date(_Search(), args, ctx)
    assert args["date"] == _day(2)
