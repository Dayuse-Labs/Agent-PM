"""Party size (`adults`/`children`) carried across turns into `search_offers`.

P0-1 of `AUDIT-AGENTIQUE-2026-07-30.md` §2, **narrowed by measurement**. The
audit assumed the model never emits `adults`/`children` "faute de description
par champ" and prescribed a virtual-declaration enrichment like
`equipment_ids.inject_amenities_declaration`. The OBS6 baseline run measured the
opposite (`HANDOFF.md`, 2026-07-30): `search_offers_args_include` for
adults/children was already at **75-78 % on a single turn** — MCP_B2C's own
`search_offers` schema documents both fields ("minimum adult/children capacity
the offer must accommodate"), which is enough for gpt-4o-mini to emit them
unprompted. There is therefore no declaration to enrich here.

What was measured at **0 %** is everything downstream of that emission:

1. **Capture** — `response_bridge._budget_timeslot_from_args` mapped only
   `priceRangeMax`/`timeSlot`, so an emitted party size was read by nobody.
   Closed by `response_bridge.occupancy_from_args`.
2. **Persistence** — `SessionProfile` had no slot, so even a captured value died
   with the turn (the leaf is stateless, `include_contents="none"`).
3. **Carryover** — nothing re-injected it, so turn 2 ("moins cher") silently
   dropped the party size and offered rooms the family cannot book. That is this
   module's job.

Precedence, owned by `inject_profile_occupancy`:

    the model's value for THIS turn wins; otherwise carry the profile's forward.

That is the **date** rule (a fresh statement supersedes), not the **amenities**
one (`equipment_ids` unions profile and LLM keys, because filters accumulate). A
party size does not accumulate: "actually just me now" must replace 2 adults,
never union with them.

Non-invention is the hard rule the eval dataset pins (`occ-solo-no-invention`,
`occ-no-invention-plain-search`): when neither the model nor the profile states a
party size, **no key is written at all**. An unstated occupancy must never become
`adults=1` — `search_offers` reads these as MINIMUM-capacity filters, so a
guessed value silently hides inventory the user never excluded.

Depends on `response_bridge` (for `find_datapart` and the shared `party_count`
validator) in the same direction `equipment_ids` already does — the bridge owns
the wire format and the capture; this module owns only the before-tool carryover.
"""

from __future__ import annotations

import logging
from typing import Any

from hotel_search_agent.response_bridge import find_datapart, party_count

_metrics_logger = logging.getLogger("dayuse.metrics")

# `search_offers` arg name -> concierge profile slot. Identical today, spelled
# out so a future rename on either side cannot silently desync the two.
_ARG_TO_SLOT = {"adults": "adults", "children": "children"}


def _profile_occupancy(tool_context: Any) -> dict[str, int]:
    """`profile_in.adults`/`.children` off the request DataPart riding
    `tool_context.user_content` (the a2a→genai conversion re-wraps the inbound
    DataPart in the same tag envelope `find_datapart` decodes). Missing or
    undecodable → `{}`: the carryover simply doesn't happen, never a crash."""
    content = getattr(tool_context, "user_content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    data = find_datapart(parts)
    if not isinstance(data, dict):
        return {}
    profile = data.get("profile_in")
    if not isinstance(profile, dict):
        return {}
    out: dict[str, int] = {}
    for arg_name, slot in _ARG_TO_SLOT.items():
        count = party_count(profile.get(slot))
        if count is None or (arg_name == "adults" and count == 0):
            continue
        out[arg_name] = count
    return out


def inject_profile_occupancy(
    tool: Any, args: dict[str, Any], tool_context: Any
) -> dict[str, Any] | None:
    """`before_tool_callback`: carry a previously-stated party size into this
    turn's `search_offers` args when the model omitted it, and normalise what it
    did send. Always returns None so the chain proceeds; mutates `args` in place
    (ADK passes the same dict to the real call).

    Only `search_offers` takes occupancy. The other leaf tools have
    `additionalProperties: false` schemas, so a stray key would be rejected
    outright by MCP — it is dropped there rather than forwarded."""
    name = getattr(tool, "name", "") or ""
    if name != "search_offers":
        for arg_name in _ARG_TO_SLOT:
            args.pop(arg_name, None)
        return None

    profile_occupancy = _profile_occupancy(tool_context)
    carried = 0
    for arg_name in _ARG_TO_SLOT:
        sent = arg_name in args
        count = party_count(args.get(arg_name))
        if count is not None and arg_name == "adults" and count == 0:
            count = None
        if count is not None:
            args[arg_name] = count  # normalised ("2" -> 2)
            continue
        if sent:
            # The model sent something unusable — drop it rather than hand MCP
            # garbage, then let the profile fill the slot if it can.
            args.pop(arg_name, None)
        if arg_name in profile_occupancy:
            args[arg_name] = profile_occupancy[arg_name]
            carried += 1

    # Content-free counter (flags only): says whether the party size came from
    # this message or from the profile — i.e. whether the carryover is working.
    if any(arg_name in args for arg_name in _ARG_TO_SLOT):
        _metrics_logger.info(
            "dayuse_metric=occupancy agent=b2c_hotel_search "
            "has_adults=%d has_children=%d carried=%d",
            int("adults" in args),
            int("children" in args),
            carried,
        )
    return None
