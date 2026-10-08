"""Stateless contract of the faq_agent leaf (A2A DataPart payloads).

Same envelope as hotel_search_agent (the two leaves share the {query_params,
profile_in} → {results, profile_delta, diagnostics} shape fixed by the Ph2
brief §3): the orchestrator sends a FaqRequest as an A2A DataPart and gets a
FaqResponse back the same way — the leaf keeps NO state between calls
(decision B3): the session Redis belongs to the orchestrator only, so the
profile travels in (profile_in) and any learning travels out (profile_delta).

S2 freezes only the ENVELOPE. The business fields inside query_params /
results / profile_* stay open dicts on purpose — the FAQ business schema
follows the same hardening sessions as search (S4/S5); do not tighten before.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FaqRequest(BaseModel):
    """Inbound DataPart: one FAQ turn, self-contained."""

    query_params: dict = Field(
        default_factory=dict,
        description="FAQ intent (question, topic…) — business schema fixed with S4/S5.",
    )
    profile_in: dict = Field(
        default_factory=dict,
        description="Caller-owned user profile snapshot; the leaf never stores it — schema fixed in S5.",
    )


class FaqResponse(BaseModel):
    """Outbound DataPart: grounded FAQ outcome + what this turn taught, no hidden state."""

    results: list = Field(
        default_factory=list,
        description="Conditions/policy content as returned by get_faq_conditions (never fabricated).",
    )
    faq_evidence: list[dict] = Field(
        default_factory=list,
        description="Original MCP policy payloads, preserving general and property scope.",
    )

    profile_delta: dict = Field(
        default_factory=dict,
        description="Only the NEW profile facts learned this turn; empty if none — schema fixed in S5.",
    )
    diagnostics: dict = Field(
        default_factory=dict,
        description="Tool calls made, degradations, errors — for observability, never user-facing.",
    )
