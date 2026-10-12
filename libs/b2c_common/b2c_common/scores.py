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
guard #13) — see CLAUDE.md's "17 guards déterministes" — plus
`poi_anchor_coherence` (#14), `filter_relaxation_honored` (#15, UX1),
`date_served` (#16) and `window_match` (#17, both mcp-dayuse#8), and
`refinement_unchanged` (#18, mcp-dayuse#6).

Seven of the 15 (the geo/date guards + `filter_relaxation_honored`) fire
inside `hotel_search_agent`, out of the OBS3 phase's zone
(`libs/b2c_common/**` + `agents/b2c_concierge/**`).

⚠️ Updated 2026-08-26. This used to say those names were "reserved here but
nothing in this repo emits them yet; a later session wires their call sites" —
and that session had not happened, so `score_guards` was publishing SIX of the
names as 0.0 on every turn, indefinitely. That is worse than a gap: it reads as
"the guard did not fire" rather than "the guard is not measured", and it is
exactly why `guard_geocode_echo_back = false` on the Toulon trace looked like a
structural false negative. The leaf now reports what fired through a
`guards_fired` key on its A2A DataPart, which the spine folds into
`budget.fired` (`b2c_concierge.agent`).

**Every name in `GUARD_SCORE_NAMES` is now wired** — the last two,
`date_hallucinated_year_rolled_forward` and `date_carryover_stale_floored`,
were connected the same day: they fire in pure helpers inside
`hotel_search_agent.datetime_resolver`, so `resolve_search_date` threads a
local accumulator through them and hands it to
`response_bridge.record_guards_fired` (the single writer of the leaf's guard
state), which the DataPart already carries. A 0.0 on any of these names now
means "did not fire" and nothing else.
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
    # --- 3 AgentB2C-specific additions (beyond the ported spec) --------------
    "booking_confirmation",
    "hotel_link_truthfulness",
    # #14 (2026-08-26): a tier-2 landmark POI absurdly far from the turn's own
    # anchor is thrown away. The echo guard above validates the NAME, which a
    # homonym passes perfectly ("Champs Elysées", a shop in Toulon, 830 km from
    # the avenue) — audit M4. This one validates the PLACE. Fires in
    # `hotel_search_agent.geocode_tool`, reaches here through the leaf's
    # `guards_fired` DataPart key.
    "poi_anchor_coherence",
    # #15 (UX1, 2026-08-27): the user retracted an amenity filter ("enleve le
    # spa") and the search actually went out WITHOUT it. Filters accumulate by
    # design across turns, so until now the profile could only grow: the
    # retraction turn replayed the identical search. Fires in
    # `hotel_search_agent.equipment_ids.enforce_equipment_filters` when a
    # removal key really took a key out of the set that would have been
    # applied; reaches here through the leaf's `guards_fired` DataPart key.
    # APPENDED, never reordered — the contract at the top of this module.
    "filter_relaxation_honored",
    # #16 (mcp-dayuse#8, 2026-10-06): the search ran on another day than the
    # one the user named (QA Côte d'Azur: 3 October asked, 30/09 served).
    # Fires in `b2c_concierge.agent`, which then says which day is on screen.
    "date_served",
    # #17 (mcp-dayuse#8, 2026-10-06): a card shown as a match did not cover
    # the requested slot by the site rule (`b2c_common.timeslot`) — QA Lyon
    # 22h01–23h01, cards closing at 22:00. Fires in `b2c_concierge.agent`,
    # which drops those cards (or labels them all as the closest offers).
    "window_match",
    # #18 (mcp-dayuse#6, 2026-10-06): a follow-up search put back on screen
    # exactly the offers already there ("élargir la zone": same 5 hotels, and
    # the reply claimed it had widened). Fires in `b2c_concierge.agent`, which
    # then says the change did not alter the results.
    "refinement_unchanged",
)

#: Degraded paths that still answer (mcp-dayuse#8): each becomes the BOOLEAN
#: score `f"fallback_{name}"`, a full 0/1 snapshot every turn like the guards.
#: Same contract as `GUARD_SCORE_NAMES`: append, never rename or remove.
#: Kept apart from the `degraded` CATEGORICAL score on purpose — its Langfuse
#: config pins the category list, so a new value there would be rejected.
FALLBACK_SCORE_NAMES: tuple[str, ...] = (
    # The synthesis produced nothing usable (exception, empty content or
    # finish_reason=length): the code-built fallback text was served.
    "synthesis",
    # An MCP tool answered with an error (invalid argument, server error):
    # the user got a degraded answer instead of results.
    "mcp_error",
    # A hotel the user named could not be found. When the turn still shows
    # other hotels (city-wide search), the answer now says so first.
    "named_hotel_not_found",
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
#: name absent here simply emits without one; the score still ingests fine,
#: just without that UI-side validation.
#:
#: ONE name is permanently absent and cannot be fixed:
#: `guard_date_hallucinated_year_rolled_forward` is 43 chars, and Langfuse
#: hard-caps a score config `name` at 35 (verified 2026-08-24: the server
#: itself returns 400 `too_big maximum:35`, not just the MCP tool's schema).
#: A config is only applied when its name EQUALS the score name, and this
#: score name is frozen by the GUARD_SCORE_NAMES contract above and already
#: carries production data — so shortening either side is off the table.
#: Nothing to retry here; the guard emits fine without a config.
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
    "guard_poi_anchor_coherence": "bad09ed2-8066-4c84-864d-09a445377773",
    "guard_filter_relaxation_honored": "964592d3-2214-44c4-9754-aae6fe9ca5aa",
    "hotels_returned": "1bd1f4bb-483b-4c17-bffc-4724b338d7c5",
    "empty_shortlist": "e4f02fd6-63c1-424a-989f-db337f1fd8c3",
    "llm_calls": "db37879d-1a74-4d53-8ce8-51fb8e88c361",
    "ttft_ms": "b0b1e82e-7987-43bd-83b2-0159208ad505",
    "degraded": "5499df51-d40d-43ca-ad99-f79247af1959",
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


def score_fallbacks(fell_back: Iterable[str]) -> None:
    """One BOOLEAN score per `FALLBACK_SCORE_NAMES` entry on the CURRENT trace,
    1.0 if present in `fell_back`. No-op when disabled; never raises."""
    client = get_langfuse()
    if client is None:
        return
    fell_back_set = set(fell_back)
    for name in FALLBACK_SCORE_NAMES:
        _score(client, f"fallback_{name}", 1.0 if name in fell_back_set else 0.0, "BOOLEAN")


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
