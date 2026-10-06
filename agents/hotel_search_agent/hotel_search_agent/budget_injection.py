"""Budget cap carried across turns into `search_offers` (mirrors
`occupancy.py` for `adults`/`children` — same shape, one scalar).

Why it exists (UX1 follow-up, measured + arbitrated by Fabien 2026-08-27).
`response_bridge._budget_timeslot_from_args` captures `priceRangeMax` INTO
the profile whenever the model sends it, and `facade.py` displays it in
`active_filters` — but nothing re-injects it into a LATER turn's
`search_offers` when the model omits it. Measured (mirror image of UX1's
amenities bug): turn 1 "max 80 euros" → turn 2 "montre m'en d'autres" (no
price mentioned) → `active_filters.budget_max` still shows `80.0`, but
`priceRangeMax` is absent from the actual MCP call — a filter the UI keeps
showing has silently stopped applying.

Precedence, same as `occupancy.py` and for the same reason: `budget_max` is
a SCALAR, not a set — the amenities union/retraction machinery does not
apply here. The model's value for THIS turn wins; otherwise carry the
profile's forward. A budget does not accumulate: a fresh "max 50" must
replace 80, never combine with it.
"""
from __future__ import annotations

import logging
from typing import Any

from hotel_search_agent.response_bridge import find_datapart, positive_budget, read_profile_in

_metrics_logger = logging.getLogger("dayuse.metrics")


def _profile_budget_max(tool_context: Any) -> float | None:
    """`profile_in.budget_max` off the request DataPart riding
    `tool_context.user_content` — same envelope `occupancy.py` reads.
    Missing or undecodable → None: the carryover simply doesn't happen,
    never a crash."""
    content = getattr(tool_context, "user_content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    data = find_datapart(parts)
    if not isinstance(data, dict):
        return None
    profile = data.get("profile_in")
    if not isinstance(profile, dict):
        return None
    return positive_budget(profile.get("budget_max"))


def inject_profile_budget(tool: Any, args: dict[str, Any], tool_context: Any) -> dict[str, Any] | None:
    """`before_tool_callback`: carry a previously-stated budget cap into this
    turn's `search_offers` args when the model omitted it, and normalise
    what it did send. Always returns None so the chain proceeds; mutates
    `args` in place (ADK passes the same dict to the real call).

    Only `search_offers` has a `priceRangeMax` param — the other leaf tools
    never receive one, so there is nothing to pop on them."""
    name = getattr(tool, "name", "") or ""
    if name != "search_offers":
        return None

    profile = read_profile_in(tool_context)
    if profile.get("constraint_edits_managed") and profile.get("budget_request_source") == "explicit":
        args.pop("priceRangeMax", None)
        cap = positive_budget(profile.get("budget_max"))
        if cap is not None:
            args["priceRangeMax"] = cap
        return None

    sent = positive_budget(args.get("priceRangeMax"))
    carried = False
    if sent is not None:
        args["priceRangeMax"] = sent  # normalised ("80" -> 80.0)
    else:
        args.pop("priceRangeMax", None)  # the model sent unusable junk — drop it
        profile_budget = _profile_budget_max(tool_context)
        if profile_budget is not None:
            args["priceRangeMax"] = profile_budget
            carried = True

    if "priceRangeMax" in args:
        # Content-free counter (flag only): whether the budget came from this
        # message or was carried from the profile.
        _metrics_logger.info(
            "dayuse_metric=budget_injection agent=b2c_hotel_search carried=%d",
            int(carried),
        )
    return None
