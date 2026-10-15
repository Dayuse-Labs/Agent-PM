"""A hotel the user names: resolved by name, then shown with its offers.

mcp-dayuse#7 (QA « St Paul's Hotel », trace 6ef04c80). `find_hotel_by_name`
returns an identity, not offers: the card came back alone, with no price and no
time slot, on whatever day the user asked for. And its `cityName` filter only
ever matched the indexed slug (`london`), so the « London » the model passes
found nothing and the turn fell back, silently, on the whole city.

What code does around the call:
- `prepare_named_hotel_lookup` (before): the city hint goes out as a slug — an
  MCP older than mcp-dayuse#3 only knows the slug — and the `date` label the
  model was shown on this tool is kept for the search below;
- `follow_named_hotel` (after): a found hotel is searched for on the asked day,
  centred on the hotel and sorted by distance, through the same before/after
  callbacks as a search the model makes. The named hotel is the first card when
  it has offers that day, its nearest neighbours follow; when it has none, the
  concierge says so (`named_hotel.offered`). Several matches → their names and
  cities are kept, and the concierge asks which one. No hotel by that name,
  even without the city hint, while the model named a city → that city is
  geocoded (`geocode_core`, its echo guard decides whether it is a place) and
  searched on the asked day, through the same callbacks: the concierge says
  the hotel was not found and shows the city's hotels (QA14707 Q22, DQ10).

One extra MCP call on a found-hotel turn, no extra LLM call: the leaf's final
generation is skipped as on any search turn. A not-found turn in a named city
makes one LLM call where it used to take three (find, geocode, search).
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import re
import time
import unicodedata
from types import SimpleNamespace
from typing import Any, Callable

from hotel_search_agent.datetime_resolver import _DATE_LABEL_PROPERTY
from hotel_search_agent.geocode_tool import geocode_core
from hotel_search_agent.response_bridge import (
    _STATE_ANCHOR_KEY as STATE_ANCHOR_KEY,
    _STATE_RESULTS_KEY as STATE_RESULTS_KEY,
    STATE_NAMED_AMBIGUOUS_KEY,
    STATE_NAMED_HOTEL_KEY,
    capture_after_tool,
    read_profile_in,
    read_structured_payload,
    read_user_words,
)

_metrics_logger = logging.getLogger("dayuse.metrics")

TOOL_NAME = "find_hotel_by_name"
_STATE_DATE_LABEL_KEY = "temp:hotel_search_named_date_label"
# The city as the model wrote it (« Lyon », « New York »): `cityName` itself
# leaves as a slug, which is no input for the geocoder.
_STATE_CITY_LABEL_KEY = "temp:hotel_search_named_city_label"
_MAX_CANDIDATES = 5
# What `capture_after_tool` keys a geocode on: the fallback's geocode is
# stashed exactly like one the model makes.
_GEOCODE_TOOL = SimpleNamespace(name="geocode_location")

_toolset: Any = None
_search_before: list[Callable[..., Any]] = []
_search_after: list[Callable[..., Any]] = []


def bind(toolset: Any, search_before: list[Callable[..., Any]], search_after: list[Callable[..., Any]]) -> None:
    """Wired once by agent.py: the MCP toolset that holds `search_offers`, and
    the callbacks a search goes through when the model makes it."""
    global _toolset, _search_before, _search_after
    _toolset = toolset
    _search_before = list(search_before)
    _search_after = list(search_after)


def city_slug(label: str) -> str:
    """« London », « Saint-Étienne », « paris-10 » → `london`, `saint-etienne`,
    `paris-10` — the shape `cityName` is indexed in (same rule as the MCP)."""
    folded = unicodedata.normalize("NFD", label)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def inject_named_hotel_declaration(callback_context: Any, llm_request: Any) -> None:
    """`before_model_callback`: shows the model the same `date` label on
    `find_hotel_by_name` as on `search_offers` — « le St Paul's Hotel demain »
    must reach the search that follows with its day."""
    config = getattr(llm_request, "config", None)
    for tool_entry in getattr(config, "tools", None) or []:
        for decl in getattr(tool_entry, "function_declarations", None) or []:
            if getattr(decl, "name", None) != TOOL_NAME:
                continue
            schema = getattr(decl, "parameters_json_schema", None)
            if not isinstance(schema, dict):
                return None
            widened = copy.deepcopy(schema)
            widened.setdefault("properties", {})["date"] = copy.deepcopy(_DATE_LABEL_PROPERTY)
            decl.parameters_json_schema = widened
            return None
    return None


def prepare_named_hotel_lookup(
    tool: Any, args: dict[str, Any], tool_context: Any
) -> dict[str, Any] | None:
    """`before_tool_callback`. Short-circuits a second lookup that brings no
    new city after an ambiguous one: picking among the candidates is the
    user's call (product decision 2026-10-06), and the model would otherwise
    re-ask with the full name of one of them."""
    if getattr(tool, "name", "") != TOOL_NAME:
        return None
    label = args.pop("date", None)
    if isinstance(label, dict):
        tool_context.state[_STATE_DATE_LABEL_KEY] = label
    city = args.get("cityName")
    slug = city_slug(city) if isinstance(city, str) else ""
    if slug:
        args["cityName"] = slug
    else:
        args.pop("cityName", None)
    # `None`, not a delete: ADK's `State` has no `pop`. A later lookup without
    # a city must not inherit an earlier one's.
    tool_context.state[_STATE_CITY_LABEL_KEY] = city.strip() if slug and isinstance(city, str) else None
    ambiguous = tool_context.state.get(STATE_NAMED_AMBIGUOUS_KEY)
    if isinstance(ambiguous, dict) and slug == ambiguous.get("city_slug", ""):
        return {
            "isError": True,
            "content": [{"type": "text", "text": "Several hotels match: the user will choose."}],
            "structuredContent": {
                "error": {
                    "kind": "AmbiguousHotelError",
                    "retryable": False,
                    "query": ambiguous.get("query"),
                    "candidates": [
                        {"name": c["name"], "cityName": c["city"]}
                        for c in ambiguous.get("candidates") or []
                    ],
                }
            },
        }
    return None


def _ambiguous_candidates(tool_response: dict[str, Any]) -> list[dict[str, str]] | None:
    envelope = (tool_response.get("structuredContent") or {}).get("error")
    if not isinstance(envelope, dict) or envelope.get("kind") != "AmbiguousHotelError":
        return None
    candidates = []
    for raw in envelope.get("candidates") or []:
        if isinstance(raw, dict) and isinstance(raw.get("name"), str):
            candidates.append({"name": raw["name"], "city": str(raw.get("cityName") or "")})
    return candidates[:_MAX_CANDIDATES] or None


def _not_found(tool_response: dict[str, Any]) -> bool:
    envelope = (tool_response.get("structuredContent") or {}).get("error")
    return isinstance(envelope, dict) and envelope.get("kind") == "HotelNotFoundError"


async def _search_tool() -> Any:
    if _toolset is None:
        return None
    for candidate in await _toolset.get_tools():
        if getattr(candidate, "name", "") == "search_offers":
            return candidate
    return None


async def _run_callbacks(callbacks: list[Callable[..., Any]], *args: Any) -> Any:
    for callback in callbacks:
        outcome = callback(*args)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        if outcome is not None:
            return outcome
    return None


async def _dated_search(
    tool_context: Any, lat: float, lon: float, *, anchor: dict[str, Any] | None = None
) -> str:
    """The bound `search_offers` around (lat, lon) on the turn's `date` label,
    through the same before/after callbacks as a search the model makes; its
    `capture_after_tool` stashes the cards the DataPart reads. `anchor` (label
    and type) becomes the cards' distance origin. Returns the metric status."""
    search = await _search_tool()
    if search is None:
        return "unbound"
    if anchor is not None:
        tool_context.state[STATE_ANCHOR_KEY] = {"latitude": lat, "longitude": lon, **anchor}
    search_args: dict[str, Any] = {"lat": lat, "lon": lon}
    label = tool_context.state.get(_STATE_DATE_LABEL_KEY)
    if isinstance(label, dict):
        search_args["date"] = label
    if await _run_callbacks(_search_before, search, search_args, tool_context) is not None:
        return "blocked"
    response = await search.run_async(args=search_args, tool_context=tool_context)
    await _run_callbacks(_search_after, search, search_args, tool_context, response)
    return "ok"


async def _search_the_city(tool_context: Any, city: str) -> None:
    """No hotel by that name, with or without the city hint (QA14707 Q22,
    DQ10): the city the model named is searched, in code. H3 measured the
    model calling no tool after `HotelNotFoundError` (0/3), where `main`
    geocoded the city and searched it.

    The city is the model's wording, already used for the lookup; the
    geocoder and its echo guard decide whether it is a place. No device fix
    and no guessed coordinate: a city that does not geocode searches nothing,
    and the concierge's not-found reply stands. The geocode is stashed like one
    the model makes (`capture_after_tool`: distance origin, profile delta), so
    the concierge says the hotel was not found and shows that city's hotels."""
    started = time.monotonic()
    status = "error"
    try:
        profile_in = read_profile_in(tool_context)
        # The same profile signals `inject_profile_geo_context` gives the
        # tool, the GPS bias excepted.
        geo = await asyncio.to_thread(
            geocode_core,
            city=city,
            raw_user_message=read_user_words(tool_context),
            profile_state_context=profile_in.get("state_anchor"),
            profile_location_hint=profile_in.get("city"),
            locale=profile_in.get("locale"),
            language_hint=profile_in.get("language"),
        )
        if not geo.get("ok"):
            status = "no_place"
            return
        capture_after_tool(_GEOCODE_TOOL, {"city": city}, tool_context, geo)
        status = await _dated_search(tool_context, float(geo["latitude"]), float(geo["longitude"]))
    except Exception:  # noqa: BLE001 — the fallback never breaks the turn
        status = "error"
    finally:
        _metrics_logger.info(
            "dayuse_metric=named_hotel_city_search agent=b2c_hotel_search status=%s ms=%d",
            status, int((time.monotonic() - started) * 1000),
        )


async def follow_named_hotel(
    tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any
) -> None:
    """`after_tool_callback`, before `capture_after_tool`. Always returns None
    (a truthy return would end the after-tool chain)."""
    if getattr(tool, "name", "") != TOOL_NAME or not isinstance(tool_response, dict):
        return None
    if tool_response.get("isError") and args.get("cityName") and _not_found(tool_response):
        # The city hint is the model's wording (« Londres » is not the indexed
        # `london`): one lookup without it, never more.
        try:
            tool_response = await tool.run_async(
                args={"name": args.get("name")}, tool_context=tool_context
            )
        except Exception:  # noqa: BLE001 — the first answer stands
            return None
        if not isinstance(tool_response, dict):
            return None
    if tool_response.get("isError"):
        candidates = _ambiguous_candidates(tool_response)
        if candidates:
            query = args.get("name")
            previous = tool_context.state.get(STATE_NAMED_AMBIGUOUS_KEY)
            if not isinstance(previous, dict):
                tool_context.state[STATE_NAMED_AMBIGUOUS_KEY] = {
                    "query": query if isinstance(query, str) else "",
                    "candidates": candidates,
                    "city_slug": args.get("cityName") or "",
                }
            return None
        city = tool_context.state.get(_STATE_CITY_LABEL_KEY)
        if _not_found(tool_response) and isinstance(city, str) and city:
            await _search_the_city(tool_context, city)
        return None
    structured = read_structured_payload(tool_response) or {}
    hotel = structured.get("hotel")
    if not isinstance(hotel, dict):
        return None
    lat, lon = hotel.get("lat"), hotel.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None  # an MCP without hotel coordinates: the identity card stays as before

    started = time.monotonic()
    status = "error"
    try:
        status = await _dated_search(
            tool_context,
            float(lat),
            float(lon),
            anchor={"label": hotel.get("name"), "type": "poi"},
        )
    except Exception:  # noqa: BLE001 — the follow-up never breaks the turn
        return None
    finally:
        _metrics_logger.info(
            "dayuse_metric=named_hotel_search agent=b2c_hotel_search status=%s ms=%d",
            status, int((time.monotonic() - started) * 1000),
        )
    if status != "ok":
        return None

    results = tool_context.state.get(STATE_RESULTS_KEY)
    if not isinstance(results, list):
        return None
    hotel_id = hotel.get("hotelId")
    named = [card for card in results if isinstance(card, dict) and card.get("id") == hotel_id]
    if named:
        tool_context.state[STATE_RESULTS_KEY] = named + [c for c in results if c not in named]
    tool_context.state[STATE_NAMED_HOTEL_KEY] = {
        "name": hotel.get("name") or "",
        "offered": bool(named),
    }
    return None

