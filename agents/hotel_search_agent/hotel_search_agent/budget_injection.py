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
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from b2c_common.price_comparison import comparison_budget
from b2c_common.search_budget import converted_eur_cap, eur_per_unit, native_eur_cap

from hotel_search_agent.response_bridge import find_datapart, positive_budget

_metrics_logger = logging.getLogger("dayuse.metrics")

# --- MCP's own rate for a budget in another currency (2026-10-30) ----------------------------
#
# Prod after #175: « Cheap hotel no more than £60 » in London → 0 card twice,
# 233 offers; « spa in Paris under £100 » → 0 card in 4 turns. MCP's
# `priceRangeMax` is in EUR, so a pound budget never reached it: the search
# ran without a cap, the leaf kept the 5 hotels of the first page and checked
# them in pounds afterwards — none under £60. The cap now reaches MCP in EUR,
# converted at the rate MCP's own quotes carry (`eur_per_unit`: the same total
# in EUR and in the hotel's currency, on every offer), learnt from the searches
# this process has seen, or from the page just returned (`filter_pages` then
# runs the search once more with the cap). No outside FX feed.

#: A learnt rate is used this long (seconds): MCP re-indexes daily.
RATE_MAX_AGE_SECONDS = 12 * 3600
#: MCP's cap gets this headroom over the converted amount: two offers of the
#: same total in pounds can differ by a cent in euros (rounding at indexing);
#: the cards are still checked exactly, in the budget's currency.
MCP_CAP_HEADROOM = Decimal("1.02")
#: The rate of each currency, from MCP's quotes: (EUR per unit, when).
_RATES: dict[str, tuple[Decimal, float]] = {}
#: The rate this call's budget used (str of a Decimal), for the cards' check.
STATE_BUDGET_RATE_KEY = "temp:hotel_search_budget_rate"


def learn_rates(structured: Any) -> None:
    """Record MCP's rate for every hotel currency quoted in `structured`."""
    hotels = structured.get("results") if isinstance(structured, dict) else None
    if not isinstance(hotels, list):
        return
    currencies = {
        offer.get("hotelCurrency")
        for hotel in hotels if isinstance(hotel, dict)
        for offer in hotel.get("offers") or [] if isinstance(offer, dict)
    }
    now = time.monotonic()
    for currency in currencies:
        if isinstance(currency, str) and currency != "EUR":
            rate = eur_per_unit(hotels, currency)
            if rate is not None:
                _RATES[currency] = (rate, now)


def known_rate(currency: str) -> Decimal | None:
    entry = _RATES.get(currency)
    if entry is None or time.monotonic() - entry[1] > RATE_MAX_AGE_SECONDS:
        return None
    return entry[0]


def rate_for(tool_context: Any, currency: str, structured: Any = None) -> Decimal | None:
    """The rate the cards of this call are checked at: the one its MCP cap
    used, else the page's own quotes, else the one learnt."""
    stamped = tool_context.state.get(STATE_BUDGET_RATE_KEY)
    if isinstance(stamped, str):
        try:
            return Decimal(stamped)
        except InvalidOperation:
            pass
    hotels = structured.get("results") if isinstance(structured, dict) else None
    return eur_per_unit(hotels, currency) or known_rate(currency)


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

    content = getattr(tool_context, "user_content", None)
    data = find_datapart(getattr(content, "parts", None))
    profile = data.get("profile_in") if isinstance(data, dict) else None
    if isinstance(profile, dict) and isinstance(profile.get("requested_budget"), dict):
        # PORT1 slice 3: the concierge's grounded request owns the cap. MCP's
        # filter is EUR: only an EUR total reaches it; any other currency is
        # checked on the cards (response_bridge), never converted here.
        args.pop("priceRangeMax", None)
        args.pop("priceRangeMin", None)
        state = getattr(tool_context, "state", None)
        if state is not None:
            state[STATE_BUDGET_RATE_KEY] = None
        cap = native_eur_cap(profile["requested_budget"])
        currency = profile["requested_budget"].get("currency")
        rate = known_rate(currency) if cap is None and isinstance(currency, str) else None
        converted = converted_eur_cap(profile["requested_budget"], rate)
        if converted is not None and rate is not None:
            # 2026-10-30: another currency, at MCP's own rate.
            cap = float(int(Decimal(str(converted)) * MCP_CAP_HEADROOM * 100) / 100)
            if state is not None:
                state[STATE_BUDGET_RATE_KEY] = str(rate)
            _metrics_logger.info("dayuse_metric=budget_converted agent=b2c_hotel_search source=learnt")
        if cap is not None:
            args["priceRangeMax"] = cap
        # PORT1 slice 4: "cheaper" in EUR narrows MCP's cap too — never
        # loosens a stated one.
        relative_cap = native_eur_cap(comparison_budget(profile.get("price_comparison")))
        if relative_cap is not None:
            args["priceRangeMax"] = min(cap, relative_cap) if cap is not None else relative_cap
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
