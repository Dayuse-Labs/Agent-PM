"""A page the code's filters thinned is filled from MCP (2026-10-30).

Prod after #175 (100 real conversations): « no more than £60 », London → 0
card twice while MCP counted 233 offers; « spa in Paris under £100 » → 0 card
in 4 turns; « Sunnyvale, this afternoon » → 1 card of 5. MCP returns pages of
5 hotels; the leaf then checks, in code, what MCP cannot (`search_card_filters`:
a budget in another currency than EUR, « cheaper » than the cards shown, the
part of the day covered, the bed, a party whose composition is not known). A
page of 5 checked after the fact can lose all 5 while the pool holds hundreds.

So, from facts only (the cards the filters kept, MCP's `total`):
- a budget in another currency than EUR that did not reach MCP (no rate
  known yet): the page's own quotes give MCP's rate (`eur_per_unit`), and the
  search runs ONCE more with the converted cap — its hotels replace the page's;
- otherwise, when fewer than `MAX_RESULTS` cards are left and MCP counts
  more hotels than the page held: the next `FILL_PAGES` pages, in parallel.

Every call goes through `extra_calls` (the 20 s window, the turn's deadline,
the breaker); `capture_after_tool` merges what came back
(`response_bridge._with_filter_pages`). Always returns None. Counts only in
the logs.
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

from b2c_common.search_budget import converted_eur_cap

from hotel_search_agent.budget_injection import MCP_CAP_HEADROOM, STATE_BUDGET_RATE_KEY
from hotel_search_agent.extra_calls import extra_call
from hotel_search_agent.response_bridge import (
    MAX_RESULTS,
    STATE_FILTER_PAGES_KEY,
    normalize_search_results,
    read_structured_payload,
    search_card_filters,
)
from hotel_search_agent.schema_guard import drop_args_outside_schema

_metrics_logger = logging.getLogger("dayuse.metrics")

#: Pages fetched beyond the first when the filters thinned it (5 hotels each).
FILL_PAGES = 2


def _failed(tool_response: Any) -> bool:
    return not isinstance(tool_response, dict) or bool(
        tool_response.get("isError") or tool_response.get("error") or tool_response.get("ok") is False
    )


def _calls(args: dict[str, Any], structured: dict[str, Any], budget: Any, state: Any) -> list[tuple[str, dict]]:
    currency = budget.get("currency") if isinstance(budget, dict) else None
    rate = budget.get("eur_per_unit") if isinstance(budget, dict) else None
    if currency not in (None, "EUR") and "priceRangeMax" not in args and isinstance(rate, Decimal):
        cap = converted_eur_cap(budget, rate)
        if cap is not None:
            state[STATE_BUDGET_RATE_KEY] = str(rate)
            capped = {key: value for key, value in args.items() if key != "from"}
            capped["priceRangeMax"] = float(int(Decimal(str(cap)) * MCP_CAP_HEADROOM * 100) / 100)
            return [("budget", capped)]
    page = structured.get("results") or []
    try:
        total = int(structured.get("total") or 0)
        start = int(args.get("from") or 0)
        size = int(args.get("size") or len(page) or MAX_RESULTS)
    except (TypeError, ValueError):
        return []
    end = start + len(page)
    return [
        ("page", {**args, "from": end + i * size})
        for i in range(FILL_PAGES) if end + i * size < total
    ]


async def fill_filtered_page_after_tool(
    tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any
) -> None:
    """`after_tool_callback`, after the completion and before
    `capture_after_tool` (which merges what it stashes)."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    state = tool_context.state
    state[STATE_FILTER_PAGES_KEY] = None
    if _failed(tool_response):
        return None
    structured = read_structured_payload(tool_response)
    if not isinstance(structured, dict) or not structured.get("results"):
        return None  # an empty page is the rescue's (`relaxation.py`)
    exclude, window, budget, comparison, party_total, room = search_card_filters(tool_context, structured)
    if window is None and not budget and not comparison and party_total is None and not room:
        return None  # nothing filters the cards after MCP
    kept = normalize_search_results(structured, exclude, window, budget, comparison, party_total, room)
    if len(kept) >= MAX_RESULTS:
        return None
    calls = _calls(args, structured, budget, state)
    if not calls:
        return None
    for _kind, call_args in calls:
        drop_args_outside_schema(tool, call_args, tool_context)
    started = time.monotonic()
    answers = await asyncio.gather(*(
        extra_call(tool, call_args, tool_context, kind="filter_page") for _kind, call_args in calls
    ))
    found: list[Any] = []
    total: Any = None
    for (kind, _call_args), (status, payload) in zip(calls, answers):
        results = payload.get("results") if status == "ok" and isinstance(payload, dict) else None
        if isinstance(results, list):
            found.extend(results)
            if kind == "budget":
                total = payload.get("total") if isinstance(payload, dict) else None
    replace = calls[0][0] == "budget"
    _log(calls[0][0], started, len(kept), len(found))
    if not found:
        return None
    state[STATE_FILTER_PAGES_KEY] = {"results": found, "replace": replace, **({"total": total} if replace else {})}
    return None


def _log(kind: str, started: float, kept: int, found: int) -> None:
    _metrics_logger.info(
        "dayuse_metric=filter_pages agent=b2c_hotel_search kind=%s kept=%d found=%d ms=%d",
        kind, kept, found, int((time.monotonic() - started) * 1000),
    )
