"""mcp-dayuse#7 — a hotel the user names: slug city hint, dated search around
the hotel, ambiguity kept for the user. Offline: fake tools, fake toolset."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from hotel_search_agent import named_hotel
from hotel_search_agent.response_bridge import (
    STATE_NAMED_AMBIGUOUS_KEY,
    STATE_NAMED_HOTEL_KEY,
    _STATE_ANCHOR_KEY,
    _STATE_RESULTS_KEY,
    capture_after_tool,
    emit_search_datapart,
    find_datapart,
)


class _Ctx:
    def __init__(self, state=None):
        self.state = state if state is not None else {}
        self.user_content = None


class _Tool:
    def __init__(self, name, responses=()):
        self.name = name
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        return self.responses.pop(0)


class _Toolset:
    def __init__(self, *tools):
        self.tools = list(tools)

    async def get_tools(self):
        return self.tools


def _found(hotel_id=7, name="St Paul's Hotel", lat=51.4935, lon=-0.2153):
    return {"structuredContent": {"hotel": {"hotelId": hotel_id, "name": name, "lat": lat, "lon": lon}}}


def _error(kind, **extra):
    return {"isError": True, "structuredContent": {"error": {"kind": kind, **extra}}}


_AMBIGUOUS = _error(
    "AmbiguousHotelError",
    query="Leonardo Royal",
    candidates=[
        {"hotelId": 1, "name": "Leonardo Royal Hotel London City", "cityName": "london"},
        {"hotelId": 2, "name": "Leonardo Royal Hotel London St Pauls", "cityName": "london"},
    ],
)


def _card(hotel_id, lat, lon):
    return {"hotelId": hotel_id, "name": f"H{hotel_id}", "lat": lat, "lon": lon,
            "offers": [{"priceEuro": 9000, "startHour": 10, "endHour": 17}]}


@pytest.fixture
def bound(monkeypatch):
    """Binds a fake toolset; the search callbacks record what they saw."""

    def _bind(search_responses, before=(), after=(capture_after_tool,)):
        search = _Tool("search_offers", search_responses)
        named_hotel.bind(_Toolset(search), list(before), list(after))
        return search

    yield _bind
    named_hotel.bind(None, [], [])


@pytest.mark.parametrize(
    ("label", "slug"),
    [("London", "london"), ("LONDON", "london"), ("Saint-Étienne", "saint-etienne"),
     ("  New York ", "new-york"), ("paris-10", "paris-10")],
)
def test_city_slug(label, slug):
    assert named_hotel.city_slug(label) == slug


class TestPrepare:
    def test_the_city_hint_goes_out_as_the_indexed_slug(self):
        args = {"name": "St Paul's Hotel", "cityName": "London"}
        named_hotel.prepare_named_hotel_lookup(_Tool("find_hotel_by_name"), args, _Ctx())
        assert args == {"name": "St Paul's Hotel", "cityName": "london"}

    def test_a_blank_city_hint_is_dropped(self):
        args = {"name": "Pullman", "cityName": "  "}
        named_hotel.prepare_named_hotel_lookup(_Tool("find_hotel_by_name"), args, _Ctx())
        assert args == {"name": "Pullman"}

    def test_the_date_label_is_kept_for_the_search_and_never_sent(self):
        ctx = _Ctx()
        args = {"name": "Pullman", "date": {"type": "relative", "value": "tomorrow"}}
        named_hotel.prepare_named_hotel_lookup(_Tool("find_hotel_by_name"), args, ctx)
        assert "date" not in args
        assert ctx.state["temp:hotel_search_named_date_label"]["value"] == "tomorrow"

    def test_after_an_ambiguity_a_lookup_without_a_new_city_is_not_made(self):
        # The model re-asked with one candidate's full name: the user picks, not it.
        ctx = _Ctx({STATE_NAMED_AMBIGUOUS_KEY: {
            "query": "Leonardo Royal", "city_slug": "london",
            "candidates": [{"name": "Leonardo Royal Hotel London City", "city": "london"}],
        }})
        args = {"name": "Leonardo Royal Hotel London City", "cityName": "London"}
        short = named_hotel.prepare_named_hotel_lookup(_Tool("find_hotel_by_name"), args, ctx)
        assert short["structuredContent"]["error"]["kind"] == "AmbiguousHotelError"

    def test_after_an_ambiguity_a_new_city_may_narrow_it(self):
        ctx = _Ctx({STATE_NAMED_AMBIGUOUS_KEY: {"query": "Hilton", "city_slug": "", "candidates": []}})
        args = {"name": "Hilton", "cityName": "London"}
        assert named_hotel.prepare_named_hotel_lookup(_Tool("find_hotel_by_name"), args, ctx) is None

    def test_other_tools_are_untouched(self):
        args = {"lat": 1.0, "lon": 2.0, "cityName": "London"}
        named_hotel.prepare_named_hotel_lookup(_Tool("search_offers"), args, _Ctx())
        assert args == {"lat": 1.0, "lon": 2.0, "cityName": "London"}


def test_the_model_is_shown_a_date_label_on_find_hotel_by_name():
    decl = SimpleNamespace(name="find_hotel_by_name",
                           parameters_json_schema={"type": "object", "properties": {"name": {}}})
    request = SimpleNamespace(config=SimpleNamespace(tools=[SimpleNamespace(function_declarations=[decl])]))
    named_hotel.inject_named_hotel_declaration(None, request)
    assert "date" in decl.parameters_json_schema["properties"]


class TestFollow:
    def _run(self, tool, args, ctx, response):
        return asyncio.run(named_hotel.follow_named_hotel(tool, args, ctx, response))

    def test_a_found_hotel_is_searched_on_the_asked_day_and_shown_first(self, bound):
        seen = []
        search = bound(
            [{"structuredContent": {"results": [_card(3, 51.4940, -0.2160), _card(7, 51.4935, -0.2153)]}}],
            before=[lambda tool, args, ctx: seen.append(dict(args))],
        )
        ctx = _Ctx({"temp:hotel_search_named_date_label": {"type": "relative", "value": "tomorrow"}})
        assert self._run(_Tool("find_hotel_by_name"), {"name": "St Paul's Hotel"}, ctx, _found()) is None
        assert seen == [{"lat": 51.4935, "lon": -0.2153, "date": {"type": "relative", "value": "tomorrow"}}]
        assert search.calls[0]["lat"] == 51.4935
        assert [c["id"] for c in ctx.state[_STATE_RESULTS_KEY]][0] == 7
        assert ctx.state[_STATE_ANCHOR_KEY]["type"] == "poi"
        assert ctx.state[STATE_NAMED_HOTEL_KEY] == {"name": "St Paul's Hotel", "offered": True}

    def test_a_hotel_with_nothing_to_book_that_day_is_reported(self, bound):
        bound([{"structuredContent": {"results": [_card(3, 51.4940, -0.2160)]}}])
        ctx = _Ctx()
        self._run(_Tool("find_hotel_by_name"), {"name": "St Paul's Hotel"}, ctx, _found())
        assert ctx.state[STATE_NAMED_HOTEL_KEY] == {"name": "St Paul's Hotel", "offered": False}

    def test_an_mcp_without_hotel_coordinates_keeps_the_identity_card(self, bound):
        search = bound([])
        ctx = _Ctx()
        self._run(_Tool("find_hotel_by_name"), {"name": "X"}, ctx, _found(lat=None, lon=None))
        assert search.calls == [] and STATE_NAMED_HOTEL_KEY not in ctx.state

    def test_an_open_breaker_blocks_the_follow_up(self, bound):
        search = bound([], before=[lambda tool, args, ctx: {"ok": False, "error": "mcp_circuit_open"}])
        ctx = _Ctx()
        self._run(_Tool("find_hotel_by_name"), {"name": "X"}, ctx, _found())
        assert search.calls == [] and STATE_NAMED_HOTEL_KEY not in ctx.state

    def test_several_matches_are_kept_for_the_user(self, bound):
        bound([])
        ctx = _Ctx()
        args = {"name": "Leonardo Royal", "cityName": "london"}
        self._run(_Tool("find_hotel_by_name"), args, ctx, _AMBIGUOUS)
        assert ctx.state[STATE_NAMED_AMBIGUOUS_KEY] == {
            "query": "Leonardo Royal",
            "city_slug": "london",
            "candidates": [
                {"name": "Leonardo Royal Hotel London City", "city": "london"},
                {"name": "Leonardo Royal Hotel London St Pauls", "city": "london"},
            ],
        }

    def test_not_found_with_a_city_is_looked_up_once_more_without_it(self, bound):
        # « Londres » is not the indexed `london`.
        bound([{"structuredContent": {"results": [_card(7, 51.4935, -0.2153)]}}])
        find = _Tool("find_hotel_by_name", [_found()])
        ctx = _Ctx()
        self._run(find, {"name": "St Paul's Hotel", "cityName": "londres"}, ctx,
                  _error("HotelNotFoundError", query="St Paul's Hotel"))
        assert find.calls == [{"name": "St Paul's Hotel"}]
        assert ctx.state[STATE_NAMED_HOTEL_KEY]["offered"] is True

    def test_not_found_without_a_city_is_left_alone(self, bound):
        find = _Tool("find_hotel_by_name")
        self._run(find, {"name": "Zorbalix"}, _Ctx(), _error("HotelNotFoundError", query="Zorbalix"))
        assert find.calls == []


def test_capture_keeps_the_cards_of_the_search_around_the_hotel():
    ctx = _Ctx({STATE_NAMED_HOTEL_KEY: {"name": "St Paul's Hotel", "offered": True},
                _STATE_RESULTS_KEY: [{"id": 7, "name": "St Paul's Hotel"}, {"id": 3, "name": "H3"}]})
    capture_after_tool(_Tool("find_hotel_by_name"), {"name": "St Paul's Hotel"}, ctx, _found())
    assert [c["id"] for c in ctx.state[_STATE_RESULTS_KEY]] == [7, 3]


def test_an_ambiguity_is_a_question_not_an_mcp_error():
    ctx = _Ctx({STATE_NAMED_AMBIGUOUS_KEY: {"query": "Leonardo Royal", "candidates": []}})
    capture_after_tool(_Tool("find_hotel_by_name"), {"name": "Leonardo Royal"}, ctx, _AMBIGUOUS)
    assert "temp:hotel_search_fallbacks" not in ctx.state


def _emitted(state):
    content = emit_search_datapart(SimpleNamespace(state=state, user_content=None))
    return find_datapart(content.parts)


def test_emit_reports_the_named_hotel_with_the_cards():
    data = _emitted({_STATE_RESULTS_KEY: [{"id": 7, "name": "St Paul's Hotel"}],
                     STATE_NAMED_HOTEL_KEY: {"name": "St Paul's Hotel", "offered": True}})
    assert data["named_hotel"] == {"name": "St Paul's Hotel", "offered": True}


def test_emit_reports_an_ambiguity_as_a_clarification():
    ambiguous = {"query": "Leonardo Royal", "candidates": [{"name": "A", "city": "london"}]}
    data = _emitted({STATE_NAMED_AMBIGUOUS_KEY: ambiguous})
    assert data["named_hotel_ambiguous"] == ambiguous
    assert data["requires_clarification"] is True
