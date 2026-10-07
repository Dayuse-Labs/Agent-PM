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
  cities are kept, and the concierge asks which one.

One extra MCP call on a found-hotel turn, no extra LLM call: the leaf's final
generation is skipped as on any search turn.
"""
from __future__ import annotations

import copy
import inspect
import logging
import re
import time
import unicodedata
from typing import Any, Callable

from hotel_search_agent.datetime_resolver import _DATE_LABEL_PROPERTY
from hotel_search_agent.response_bridge import (
    _STATE_ANCHOR_KEY as STATE_ANCHOR_KEY,
    _STATE_RESULTS_KEY as STATE_RESULTS_KEY,
    STATE_NAMED_AMBIGUOUS_KEY,
    STATE_NAMED_HOTEL_KEY,
    read_structured_payload,
)

_metrics_logger = logging.getLogger("dayuse.metrics")

TOOL_NAME = "find_hotel_by_name"
_STATE_DATE_LABEL_KEY = "temp:hotel_search_named_date_label"
_MAX_CANDIDATES = 5

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
    structured = read_structured_payload(tool_response) or {}
    hotel = structured.get("hotel")
    if not isinstance(hotel, dict):
        return None
    lat, lon = hotel.get("lat"), hotel.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None  # an MCP without hotel coordinates: the identity card stays as before

    started = time.monotonic()
    status = "ok"
    try:
        search = await _search_tool()
        if search is None:
            return None
        tool_context.state[STATE_ANCHOR_KEY] = {
            "latitude": float(lat),
            "longitude": float(lon),
            "label": hotel.get("name"),
            "type": "poi",
        }
        search_args: dict[str, Any] = {"lat": float(lat), "lon": float(lon)}
        label = tool_context.state.get(_STATE_DATE_LABEL_KEY)
        if isinstance(label, dict):
            search_args["date"] = label
        if await _run_callbacks(_search_before, search, search_args, tool_context) is not None:
            status = "blocked"
            return None
        response = await search.run_async(args=search_args, tool_context=tool_context)
        await _run_callbacks(_search_after, search, search_args, tool_context, response)
    except Exception:  # noqa: BLE001 — the follow-up never breaks the turn
        status = "error"
        return None
    finally:
        _metrics_logger.info(
            "dayuse_metric=named_hotel_search agent=b2c_hotel_search status=%s ms=%d",
            status, int((time.monotonic() - started) * 1000),
        )

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

