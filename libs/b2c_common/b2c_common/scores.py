"""Deterministic Langfuse scores (OBS3) — zero LLM calls, opt-in via the same
client observability.py sets up. Every function here is no-op when Langfuse
is disabled and never raises (observability must never break a turn).

`GUARD_SCORE_NAMES` is a CONTRACT: each entry becomes the Langfuse score name
`f"guard_{name}"` — a permanent per-guard time series (OBS2-LANGFUSE-BRIEF.md
§2). Renaming or dropping an entry breaks its history: add new guards, never
rename or remove one. 11 are ported from agent-usa's 2026-06 production audit
(`tests/unit/application/test_audit_fixes_2026_06.py` + the loop-enforcement/
named-hotel-card specs); 2 are AgentB2C-specific additions beyond that spec
(`booking_confirmation` = R9/guard #12, `hotel_link_truthfulness` = S-G12,
guard #13) — see CLAUDE.md's "13 guards déterministes".

Five of the 13 (the geo/date guards) fire inside `hotel_search_agent`, out of
this phase's zone (`libs/b2c_common/**` + `agents/b2c_concierge/**`) — their
names are reserved here (the contract is frozen once) but nothing in this
repo emits them yet; a later session wires their call sites (see HANDOFF).
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Literal

from .observability import get_langfuse

logger = logging.getLogger(__name__)

GUARD_SCORE_NAMES: tuple[str, ...] = (
    # --- 11 ported from agent-usa's 2026-06 production audit -----------------
    "geocode_echo_back",
    "generic_location_demotion",
    "state_anchoring",
    "date_hallucinated_year_rolled_forward",
    "date_carryover_stale_floored",
    "budget_integrity",
    "timeslot_sanitization",
    "recovery_ack",
    "anti_clarification_loop",
    "amenity_truthfulness",
    "named_hotel_lookup",
    # --- 2 AgentB2C-specific additions (beyond the ported spec) --------------
    "booking_confirmation",
    "hotel_link_truthfulness",
)

#: Closed set for the `degraded` CATEGORICAL score (RGPD: a rule id, never
#: free text) — only the reasons the concierge can itself observe. The
#: leaf-only root causes (mcp_circuit_open, mapbox_retry_exhausted) are not
#: visible from this process pre-OBS4 (traces are still separate) and are
#: deliberately not guessed at here.
DegradedReason = Literal["leaf_call_failed", "facade_shield"]
_DEGRADED_REASONS: frozenset[str] = frozenset(("leaf_call_failed", "facade_shield"))

#: Langfuse score-config ids (observability/langfuse/score-configs.json is the
#: versioned source of truth — this project has ONE Langfuse instance shared
#: across environments, so hardcoding is correct, not an environment leak).
#: `config_id` is what makes a score's min/max/category validation apply and
#: what makes it usable in an annotation queue (OBS2-LANGFUSE-BRIEF.md §2) — a
#: name absent here (the 43-char guard name, `degraded`) simply emits without
#: one; the score still ingests fine, just without that UI-side validation.
_SCORE_CONFIG_IDS: dict[str, str] = {
    "guard_geocode_echo_back": "544fbf28-27a0-44e9-a73a-4e9a1851f507",
    "guard_generic_location_demotion": "82c3932a-6815-4390-9343-9f152e1713c9",
    "guard_state_anchoring": "cd2a03b3-e943-48b5-b422-39c747ee5026",
    "guard_date_carryover_stale_floored": "c8779d65-cd76-47e6-bb03-936376b7ad2e",
    "guard_budget_integrity": "6eb7b23e-7e1a-4dde-ac32-f5229cb93e3c",
    "guard_timeslot_sanitization": "fe0733fc-5199-49d3-9960-fceb1fbc0cf4",
    "guard_recovery_ack": "8bd7574b-2b67-4236-ab44-84731d41066a",
    "guard_anti_clarification_loop": "e202146e-050a-467a-b3b7-4a39f6d7a2af",
    "guard_amenity_truthfulness": "871219e0-affd-4fcd-999a-5c3907daa031",
    "guard_named_hotel_lookup": "a615105a-2f7d-492f-a749-052eda8a02bf",
    "guard_booking_confirmation": "20abf459-1e56-4c48-bd9c-e464ac9b0de1",
    "guard_hotel_link_truthfulness": "f474dd88-aac9-490d-99a3-e4e41060df35",
    "hotels_returned": "1bd1f4bb-483b-4c17-bffc-4724b338d7c5",
    "empty_shortlist": "e4f02fd6-63c1-424a-989f-db337f1fd8c3",
    "llm_calls": "db37879d-1a74-4d53-8ce8-51fb8e88c361",
    "ttft_ms": "b0b1e82e-7987-43bd-83b2-0159208ad505",
}


def score_guards(fired: Iterable[str]) -> None:
    """One BOOLEAN score per `GUARD_SCORE_NAMES` entry on the CURRENT trace —
    1.0 if present in `fired`, 0.0 otherwise (never `True`/`False` — Langfuse
    BOOLEAN scores are 0/1). No-op when disabled; never raises."""
    client = get_langfuse()
    if client is None:
        return
    fired_set = set(fired)
    for name in GUARD_SCORE_NAMES:
        _score(client, f"guard_{name}", 1.0 if name in fired_set else 0.0, "BOOLEAN")


def score_turn(*, hotels_returned: int, llm_calls: int) -> None:
    """The 3 turn-level scores every exit point of a turn can compute:
    `hotels_returned` (NUMERIC), `empty_shortlist` (BOOLEAN, derived from the
    same count) and `llm_calls` (NUMERIC, mirrors `TurnBudget`, the ≤3/turn
    structural budget). No-op when disabled; never raises."""
    client = get_langfuse()
    if client is None:
        return
    _score(client, "hotels_returned", float(hotels_returned), "NUMERIC")
    _score(client, "empty_shortlist", 1.0 if hotels_returned == 0 else 0.0, "BOOLEAN")
    _score(client, "llm_calls", float(llm_calls), "NUMERIC")


def score_degraded(reason: DegradedReason) -> None:
    """CATEGORICAL score for the one kind of dependency degradation this
    process can itself observe. Anything outside `_DEGRADED_REASONS` is
    dropped rather than emitted — a defensive backstop, not an expected path
    (RGPD: this value must never become a free-text field). No-op when
    disabled; never raises."""
    client = get_langfuse()
    if client is None:
        return
    if reason not in _DEGRADED_REASONS:
        logger.debug("score_degraded(%s) skipped: not in the closed set", reason)
        return
    _score(client, "degraded", reason, "CATEGORICAL")


def score_ttft(ttft_ms: float) -> None:
    """NUMERIC score for the `progress` frame's time-to-first-token (the
    CLAUDE.md SLO: < 300 ms), measured by the caller (facade.py) and posted
    here so it aggregates as p95 in the Metrics API/dashboards, not just
    read off individual traces. No-op when disabled; never raises."""
    client = get_langfuse()
    if client is None:
        return
    _score(client, "ttft_ms", float(ttft_ms), "NUMERIC")


def _score(client: Any, name: str, value: Any, data_type: str) -> None:
    try:
        client.score_current_trace(
            name=name, value=value, data_type=data_type, config_id=_SCORE_CONFIG_IDS.get(name)
        )
    except Exception:  # noqa: BLE001 — observability must never break a turn
        logger.debug("score(%s) skipped", name, exc_info=True)
