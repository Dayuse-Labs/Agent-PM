"""QA14707 Q22 (DQ10) — a hotel named in a city, not found on Dayuse: the
leaf searches that city itself, in code.

H3 (`geo7-named-not-found`, plan-r1 trace 1e280675c3d6247559669aed231c13a0):
« Bidule Imaginaire à Lyon » → `find_hotel_by_name` → `HotelNotFoundError`,
and the model's next generation called no tool, so the user got no hotel at
all. `main` geocoded Lyon and searched it (trace 69ee504e3ff8c8c8e6747c94ceb0f406).

Offline: the real `MapboxClient` over an `httpx.MockTransport`, a fake MCP
toolset, the real leaf chain around the call (`prepare_named_hotel_lookup`,
`follow_named_hotel`, `capture_after_tool`, `skip_final_generation`,
`emit_search_datapart`)."""
from __future__ import annotations

import asyncio
import logging
import re
from types import SimpleNamespace

import httpx
import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from hotel_search_agent import geocode_tool, named_hotel
from hotel_search_agent.mapbox_client import MapboxClient
from hotel_search_agent.response_bridge import (
    STATE_NAMED_HOTEL_KEY,
    _STATE_ANCHOR_KEY,
    _STATE_RESULTS_KEY,
    capture_after_tool,
    emit_search_datapart,
    find_datapart,
    skip_final_generation,
)

NAME = "Bidule Imaginaire"
TEXT = "Je cherche l'hôtel Bidule Imaginaire à Lyon demain"
LYON = (45.764, 4.8357)
TOMORROW = {"type": "relative", "value": "tomorrow"}


def _lyon_feature() -> dict:
    return {
        "geometry": {"coordinates": [LYON[1], LYON[0]]},
        "properties": {
            "name": "Lyon",
            "full_address": "Lyon, Auvergne-Rhône-Alpes, France",
            "feature_type": "place",
            "context": {
                "country": {"country_code": "fr"},
                "region": {"name": "Auvergne-Rhône-Alpes"},
            },
        },
    }


def _not_found() -> dict:
    return {
        "isError": True,
        "structuredContent": {"error": {"kind": "HotelNotFoundError", "retryable": False, "query": NAME}},
    }


def _card(hotel_id: int, lat: float, lon: float) -> dict:
    return {"hotelId": hotel_id, "name": f"H{hotel_id}", "lat": lat, "lon": lon,
            "offers": [{"priceEuro": 9000, "startHour": 10, "endHour": 17}]}


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


class _EmptySearchBox:
    """The geocoder's tier 2, finding nothing; records each query's proximity."""

    def __init__(self):
        self.proximities: list = []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.proximities.append(proximity)
        return []


class _Inventory:
    def count_near(self, lat, lon, *, radius_km=25.0):
        return 100


def _ctx(text: str = TEXT, profile_in: dict | None = None) -> SimpleNamespace:
    """The leaf's `tool_context`: the user's words, then the A2A DataPart, as
    the real a2a→genai converter hands them to the leaf."""
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=text), convert_a2a_part_to_genai_part(datapart)]
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


@pytest.fixture
def mapbox(monkeypatch):
    """Mapbox v6 answering `features` to every request; records each request's
    params. The Search Box finds nothing, the inventory is flat."""
    recorded = SimpleNamespace(
        requests=[], features=[_lyon_feature()], searchbox=_EmptySearchBox()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.requests.append(dict(request.url.params))
        return httpx.Response(200, json={"features": list(recorded.features)})

    client = MapboxClient("test-token", client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: client)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: recorded.searchbox)
    monkeypatch.setattr(geocode_tool, "get_inventory", _Inventory)
    return recorded


@pytest.fixture
def statuses(monkeypatch):
    """The `status` of each `named_hotel_city_search` metric line: the fallback
    swallows every exception, so an `error` must never pass for a miss."""
    seen: list[str] = []

    def info(fmt, *args):
        if fmt.startswith("dayuse_metric=named_hotel_city_search"):
            seen.append(args[0])

    monkeypatch.setattr(named_hotel._metrics_logger, "info", info)
    return seen


@pytest.fixture
def search():
    """The bound `search_offers`, with a before callback recording the args it
    is called with, and the real `capture_after_tool` after it."""
    tool = _Tool("search_offers", [{"structuredContent": {"results": [
        _card(11, 45.7600, 4.8400), _card(12, 45.7700, 4.8300),
    ]}}])
    tool.seen = []
    named_hotel.bind(
        _Toolset(tool),
        [lambda t, args, ctx: tool.seen.append(dict(args))],
        [capture_after_tool],
    )
    yield tool
    named_hotel.bind(None, [], [])


def _turn(ctx: SimpleNamespace, args: dict, find: _Tool) -> dict:
    """One `find_hotel_by_name` call through the leaf's callbacks: the before
    callback, the MCP answer (not found), the after callbacks in agent.py's
    order. Returns the args as the after callbacks saw them."""
    named_hotel.prepare_named_hotel_lookup(find, args, ctx)
    response = _not_found()
    asyncio.run(named_hotel.follow_named_hotel(find, args, ctx, response))
    capture_after_tool(find, args, ctx, response)
    return args


def _datapart(ctx: SimpleNamespace) -> dict:
    content = emit_search_datapart(SimpleNamespace(state=ctx.state, user_content=None))
    return find_datapart(content.parts)


def _next_generation_skipped(ctx: SimpleNamespace) -> bool:
    return skip_final_generation(SimpleNamespace(state=ctx.state, user_content=None), None) is not None


class TestNotFoundInANamedCity:
    def test_the_named_city_is_geocoded_and_searched_on_the_asked_day(
        self, mapbox, search, statuses
    ):
        ctx = _ctx()
        find = _Tool("find_hotel_by_name", [_not_found()])  # the retry without the city

        _turn(ctx, {"name": NAME, "cityName": "Lyon", "date": TOMORROW}, find)

        # The lookup ran twice, as before: with the slug, then without it.
        assert find.calls == [{"name": NAME}]
        # The city as the model wrote it went to the geocoder, with no GPS bias.
        assert [r["q"] for r in mapbox.requests] == ["Lyon"]
        assert all("proximity" not in r for r in mapbox.requests)
        # One bound search, on Lyon's coordinates and the turn's date label.
        assert search.seen == [{"lat": LYON[0], "lon": LYON[1], "date": TOMORROW}]
        assert len(search.calls) == 1
        # The geocode is stashed like one the model makes: city centroid origin.
        assert ctx.state[_STATE_ANCHOR_KEY]["type"] == "city_centroid"
        assert ctx.state[_STATE_ANCHOR_KEY]["latitude"] == LYON[0]
        # The model's next generation is skipped: no extra LLM call.
        assert _next_generation_skipped(ctx)
        # What the concierge reads: the city's hotels, and the named one not found.
        data = _datapart(ctx)
        assert [card["id"] for card in data["results"]] == [11, 12]
        assert data["named_hotel_not_found"] == NAME
        assert "named_hotel" not in data
        assert "named_hotel_not_found" in data["fallbacks_fired"]
        assert STATE_NAMED_HOTEL_KEY not in ctx.state
        assert statuses == ["ok"]

    def test_the_geocoded_city_reaches_the_profile(self, mapbox, search):
        ctx = _ctx()
        _turn(ctx, {"name": NAME, "cityName": "Lyon"}, _Tool("find_hotel_by_name", [_not_found()]))
        assert _datapart(ctx)["profile_delta"]["city"] == {"op": "set", "value": "Lyon"}


class TestNegativeControls:
    def test_not_found_without_a_city_geocodes_nothing_and_searches_nothing(
        self, mapbox, search, statuses
    ):
        # The concierge's « tell me the city » reply stays.
        ctx = _ctx("Je cherche l'hôtel Bidule Imaginaire demain")
        find = _Tool("find_hotel_by_name")

        _turn(ctx, {"name": NAME, "date": TOMORROW}, find)

        assert find.calls == []
        assert mapbox.requests == []
        assert search.calls == [] and search.seen == []
        assert _STATE_RESULTS_KEY not in ctx.state
        assert not _next_generation_skipped(ctx)
        assert statuses == []
        data = _datapart(ctx)
        assert data["named_hotel_not_found"] == NAME
        assert "results" not in data

    def test_a_city_that_does_not_geocode_searches_nothing_even_with_a_device_fix(
        self, mapbox, search, statuses
    ):
        mapbox.features = []
        # A device GPS fix in the profile is never a stand-in for the city.
        ctx = _ctx(profile_in={"search_anchor": {"lat": 48.8566, "lon": 2.3522}})

        _turn(ctx, {"name": NAME, "cityName": "Lyon"}, _Tool("find_hotel_by_name", [_not_found()]))

        assert mapbox.requests, "the city was never geocoded"
        assert all("proximity" not in r for r in mapbox.requests)
        assert all(p is None for p in mapbox.searchbox.proximities)
        assert search.calls == [] and search.seen == []
        assert _STATE_RESULTS_KEY not in ctx.state
        assert _STATE_ANCHOR_KEY not in ctx.state
        assert statuses == ["no_place"]
        data = _datapart(ctx)
        assert data["named_hotel_not_found"] == NAME
        assert "results" not in data

    def test_an_earlier_lookup_city_is_not_inherited(self, mapbox, search, statuses):
        # Two lookups in one turn: the second names no city, so its not-found
        # searches no city, not even the first lookup's.
        ctx = _ctx()
        named_hotel.prepare_named_hotel_lookup(
            _Tool("find_hotel_by_name"), {"name": "Other", "cityName": "Lyon"}, ctx
        )

        _turn(ctx, {"name": NAME}, _Tool("find_hotel_by_name"))

        assert mapbox.requests == []
        assert search.calls == []
        assert statuses == []


# --- the metric lines carry no text (Q23, the user's ruling on Q22) ----------------
#
# GDPR invariant « zero message content in metrics »: the two lines the
# named-hotel path logs carry a fixed status and an integer duration, nothing
# else — no word of the message, no hotel name, no city.

_LINE = re.compile(
    r"dayuse_metric=(named_hotel_city_search|named_hotel_search) agent=b2c_hotel_search "
    r"status=(ok|no_place|blocked|unbound|error) ms=\d+"
)
_WORDS = sorted({*TEXT.split(), *NAME.split(), "Lyon"})


@pytest.fixture
def metric_lines(caplog):
    """The real `dayuse.metrics` records of the turn, formatted. caplog's
    handler is put on the logger itself: the metrics logger is configured on
    its own and may not propagate to the root logger caplog listens on."""
    logger = logging.getLogger("dayuse.metrics")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="dayuse.metrics")
    try:
        yield lambda: [
            r.getMessage() for r in caplog.records
            if r.name == "dayuse.metrics" and r.getMessage().startswith(
                ("dayuse_metric=named_hotel_city_search ", "dayuse_metric=named_hotel_search ")
            )
        ]
    finally:
        logger.removeHandler(caplog.handler)


def _found(hotel_id: int = 11) -> dict:
    return {"structuredContent": {"hotel": {
        "hotelId": hotel_id, "name": NAME, "lat": 45.7600, "lon": 4.8400,
    }}}


def _found_turn(ctx: SimpleNamespace) -> None:
    find = _Tool("find_hotel_by_name")
    args = {"name": NAME, "cityName": "Lyon", "date": TOMORROW}
    named_hotel.prepare_named_hotel_lookup(find, args, ctx)
    asyncio.run(named_hotel.follow_named_hotel(find, args, ctx, _found()))
    capture_after_tool(find, args, ctx, _found())


def _assert_content_free(line: str) -> None:
    assert _LINE.fullmatch(line), line
    for word in _WORDS:
        assert word.casefold() not in line.casefold(), (word, line)


class TestTheMetricLinesCarryNoText:
    def test_not_found_in_lyon(self, mapbox, search, metric_lines):
        _turn(_ctx(), {"name": NAME, "cityName": "Lyon", "date": TOMORROW},
              _Tool("find_hotel_by_name", [_not_found()]))

        lines = metric_lines()
        assert [line.split()[0] for line in lines] == ["dayuse_metric=named_hotel_city_search"]
        assert " status=ok " in lines[0]
        for line in lines:
            _assert_content_free(line)

    def test_a_city_that_does_not_geocode(self, mapbox, search, metric_lines):
        mapbox.features = []

        _turn(_ctx(), {"name": NAME, "cityName": "Lyon"}, _Tool("find_hotel_by_name", [_not_found()]))

        lines = metric_lines()
        assert [line.split()[0] for line in lines] == ["dayuse_metric=named_hotel_city_search"]
        assert " status=no_place " in lines[0]
        for line in lines:
            _assert_content_free(line)

    def test_a_found_hotel(self, search, metric_lines):
        _found_turn(_ctx())

        lines = metric_lines()
        assert [line.split()[0] for line in lines] == ["dayuse_metric=named_hotel_search"]
        assert " status=ok " in lines[0]
        assert len(search.calls) == 1
        for line in lines:
            _assert_content_free(line)

    def test_a_found_hotel_with_no_bound_toolset_reports_unbound(self, metric_lines):
        named_hotel.bind(None, [], [])

        _found_turn(_ctx())

        lines = metric_lines()
        assert [line.split()[0] for line in lines] == ["dayuse_metric=named_hotel_search"]
        assert " status=unbound " in lines[0]
        for line in lines:
            _assert_content_free(line)
