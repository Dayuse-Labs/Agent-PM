"""Replay 2026-10-28, « Dans la métropole lilloise entre 14 et 18 »: the leaf's
model sometimes sends the place as `metro` only (no country from anyone), or
both as a region place and again as `metro`. Unscoped, Mapbox answered
« Jardim Metrópole » (Brazil), and the echo's longest word (« métropole »)
accepted it. The same input failed that way on main too (leaf probe, 1 of 5):
a pre-existing weakness, fixed here on facts — the market's country scopes a
metro written alone, and a metro that only repeats a place of the request is
not looked up a second time."""
from __future__ import annotations

from types import SimpleNamespace

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from b2c_common.geo_intent import GeoIntent, Place
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.mapbox_client import GeocodeCandidate

_BRAZIL = GeocodeCandidate(
    latitude=-22.765026, longitude=-43.335934, name="Jardim Metrópole",
    place_name="Jardim Metrópole, 25575, São João de Meriti, Rio de Janeiro, Brésil",
    place_formatted="São João de Meriti, Rio de Janeiro, Brésil", feature_type="neighborhood",
    country_code="BR", region="Rio de Janeiro", bbox=None, rank=0, place="São João de Meriti",
)
_MSG = "Dans la métropole lilloise entre 14 et 18 (flexible)"


class _V6:
    def __init__(self):
        self.calls: list[tuple] = []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        return [] if country else [_BRAZIL]


class _Box:
    def forward_candidates(self, *a, **k):
        return []


class _Inventory:
    def count_near(self, *a, **k):
        return 0


def _ctx(profile_in):
    dp = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in}))
    parts = [genai_types.Part(text=_MSG), convert_a2a_part_to_genai_part(dp)]
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _patch(monkeypatch):
    v6 = _V6()
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: v6)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _Box())
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory())
    return v6


def test_a_metro_alone_is_scoped_to_the_market_and_never_lands_in_brazil(monkeypatch):
    v6 = _patch(monkeypatch)

    result = geocode_location(
        intent=GeoIntent(), metro="métropole lilloise", locale="fr",
        tool_context=_ctx({"entry_market_country": "FR"}),
    )

    assert v6.calls[0] == ("métropole lilloise", "FR")
    assert all(country == "FR" for _, country in v6.calls)
    assert result.get("country_code") != "BR"
    assert result.get("ok") is not True


def test_a_metro_that_repeats_a_place_of_the_request_is_dropped(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(geocode_tool, "geocode_core", lambda **kw: seen.append(kw) or {"ok": False, "error": "spy"})
    place = Place(mention="métropole lilloise", kind="region", canonical="Métropole européenne de Lille", country="FR")

    geocode_location(intent=GeoIntent(places=[place]), metro="métropole lilloise", tool_context=_ctx({}))
    geocode_location(intent=GeoIntent(places=[place]), metro="Lille", tool_context=_ctx({}))

    assert seen[0]["metro"] is None
    assert seen[1]["metro"] == "Lille"  # a metro of its own is kept
