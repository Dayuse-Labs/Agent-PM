"""The hotel standing the user asks for, as a star filter.

Prod session 1eb2430a (2026-10-27): « une chambre hyper belle », then « je veux
une chambre très classe »: nothing in the search could express it. The leaf's
model reads the wish into a closed value (`standing` on search_offers), the
code owns the filter it maps to (MCP `starRatings`) and carries it across turns
from `profile_in.standing` — same doctrine as `equipment_ids`: the LLM
understands the phrasing, the code owns the filter value. Fabien's ruling: « très
classe » is 4 and 5 stars.
"""
from __future__ import annotations

from typing import Any

import logging

from hotel_search_agent.response_bridge import STATE_STANDING_KEY, read_input_text, read_profile_in

_metrics_logger = logging.getLogger("dayuse.metrics")

STANDING_STARS: dict[str, list[int]] = {"upscale": [4, 5]}
#: Drops a standing stated earlier (« peu importe le standing »).
STANDING_ANY = "any"

STANDING_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": [*STANDING_STARS, STANDING_ANY],
    "description": (
        "The hotel standing the user asks for: 'upscale' for a chic, luxury, "
        "high-end or very classy hotel or room ('très classe', 'haut de gamme', "
        "'luxe', 'une chambre hyper belle', 'something fancy'); 'any' when they "
        "drop a standing stated earlier ('peu importe le standing'). Omit "
        "entirely when the message says nothing about standing: a mood, an "
        "amenity or a price ('romantic', 'a spa hotel', 'nice and cheap') is "
        "not a standing, and neither is a question about a star rating."
    ),
}
#: 2026-10-30 (prod after #175, « a spa like hotel … under £70 » → 4-5★ added,
#: 0 card in 4 turns): the user's own words that ask for the standing.
STANDING_EVIDENCE_PROPERTY: dict[str, Any] = {
    "type": "string",
    "description": (
        "REQUIRED with standing 'upscale': the user's exact words of THIS request "
        "that ask for it ('très classe', 'luxury'), copied as written."
    ),
}


def enforce_standing(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback`: the ONLY writer of search_offers' `starRatings`.
    Mutates `args` in place, always returns None. The model sees MCP's own
    schema, so a `starRatings` it writes itself is dropped."""
    name = getattr(tool, "name", "") or ""
    if name == "find_hotel_by_name":
        args.pop("standing", None)
        args.pop("standing_evidence", None)
        return None
    if name != "search_offers":
        return None
    args.pop("starRatings", None)
    asked = args.pop("standing", None)
    evidence = args.pop("standing_evidence", None)
    if asked in STANDING_STARS and not _quoted(evidence, read_input_text(tool_context)):
        # 2026-10-30: a standing is applied only when the user's own words
        # for it are in the request — a fact about the quote, the model reads.
        _metrics_logger.info("dayuse_metric=standing_unquoted agent=b2c_hotel_search")
        asked = None
    if asked == STANDING_ANY:
        standing = None
    elif asked in STANDING_STARS:
        standing = asked
    else:
        carried = read_profile_in(tool_context).get("standing")
        standing = carried if carried in STANDING_STARS else None
    if standing is not None:
        args["starRatings"] = list(STANDING_STARS[standing])
    # "" = this search ran with no standing (the profile slot is cleared).
    tool_context.state[STATE_STANDING_KEY] = standing or ""
    return None


def _quoted(evidence: Any, text: str) -> bool:
    """`evidence` is a non-empty quote of `text` (case and spacing aside)."""
    if not isinstance(evidence, str) or not evidence.strip():
        return False
    return " ".join(evidence.split()).casefold() in " ".join(text.split()).casefold()
