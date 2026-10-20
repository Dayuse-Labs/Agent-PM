"""turn_facts — what only the server knows about a turn, handed to the widget
in the /v3 payload so its analytics event can carry it.

Every value is an enum, a count, a score name or a geocoded city: never
message content (RGPD). The enums are those of `contracts/amplitude_events.json`
(locked by `tests/test_amplitude_contract.py`): append only, like the contract.
"""
from __future__ import annotations

from typing import Iterable, Literal, TypedDict

from b2c_common.scores import FALLBACK_SCORE_NAMES, GUARD_SCORE_NAMES

UNKNOWN_FAMILY = "unknown"

ResponseType = Literal["results", "clarification", "answer"]
TurnStatus = Literal["ok", "degraded", "synthesis_fallback"]
FactsStatus = Literal[TurnStatus, "unknown"]
EmptyReason = Literal[
    "none", "no_offers", "filters_too_strict", "date_unavailable", "error"
]
ClarificationReason = Literal["none", "location", "homonym", "party", "budget", "other"]


class TurnFacts(TypedDict):
    trace_id: str | None
    family: str
    route: str
    status: FactsStatus
    response_type: ResponseType
    results_count: int
    empty_reason: EmptyReason
    clarification_reason: ClarificationReason
    guards_fired: list[str]
    fallbacks: list[str]
    resolved_city: str | None


def _response_type(hotels_returned: int, clarification_reason: ClarificationReason) -> ResponseType:
    if hotels_returned > 0:
        return "results"
    if clarification_reason != "none":
        return "clarification"
    return "answer"


def spine_turn_facts(
    *,
    family: str,
    route: str,
    status: FactsStatus,
    hotels_returned: int,
    fired: Iterable[str] = (),
    fallbacks: Iterable[str] = (),
    empty_reason: EmptyReason = "none",
    clarification_reason: ClarificationReason = "none",
    resolved_city: str | None = None,
) -> TurnFacts:
    """`trace_id` stays None here: only the facade holds the turn's span."""
    return TurnFacts(
        trace_id=None,
        family=family,
        route=route,
        status=status,
        response_type=_response_type(hotels_returned, clarification_reason),
        results_count=hotels_returned,
        empty_reason="none" if hotels_returned > 0 else empty_reason,
        clarification_reason=clarification_reason,
        guards_fired=sorted(set(fired) & set(GUARD_SCORE_NAMES)),
        fallbacks=sorted(set(fallbacks) & set(FALLBACK_SCORE_NAMES)),
        resolved_city=resolved_city,
    )


def facade_turn_facts(
    route: str,
    *,
    family: str = UNKNOWN_FAMILY,
    status: FactsStatus = "ok",
    empty_reason: EmptyReason = "none",
) -> TurnFacts:
    """A turn the spine never ran (empty message, last-resort shield), or one
    that ran without reporting (`status="unknown"`)."""
    return spine_turn_facts(
        family=family, route=route, status=status, hotels_returned=0, empty_reason=empty_reason,
    )
