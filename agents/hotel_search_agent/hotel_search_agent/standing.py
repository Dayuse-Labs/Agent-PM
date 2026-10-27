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

from hotel_search_agent.response_bridge import STATE_STANDING_KEY, read_profile_in

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
        "entirely when the message says nothing about standing."
    ),
}


def enforce_standing(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback`: the ONLY writer of search_offers' `starRatings`.
    Mutates `args` in place, always returns None. The model sees MCP's own
    schema, so a `starRatings` it writes itself is dropped."""
    name = getattr(tool, "name", "") or ""
    if name == "find_hotel_by_name":
        args.pop("standing", None)
        return None
    if name != "search_offers":
        return None
    args.pop("starRatings", None)
    asked = args.pop("standing", None)
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
