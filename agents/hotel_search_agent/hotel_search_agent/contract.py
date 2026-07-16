"""Stateless contract of the hotel_search_agent leaf (A2A DataPart payloads).

The orchestrator sends a SearchRequest as an A2A DataPart and gets a
SearchResponse back the same way — the leaf keeps NO state between calls
(decision B3): the session Redis belongs to the orchestrator only, so the
profile travels in (profile_in) and any learning travels out (profile_delta).

S1 freezes only the ENVELOPE. The business fields inside query_params /
results / profile_* are specified by S4 (geo guards) and S5 (profile), so they
stay open dicts here on purpose — do not tighten them before those sessions.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Inbound DataPart: one search turn, self-contained."""

    query_params: dict = Field(
        default_factory=dict,
        description="Search intent (destination, dates, filters, hotel name…) — business schema fixed in S4.",
    )
    profile_in: dict = Field(
        default_factory=dict,
        description="Caller-owned user profile snapshot; the leaf never stores it — schema fixed in S5.",
    )


class SearchResponse(BaseModel):
    """Outbound DataPart: search outcome + what this turn taught, no hidden state."""

    results: list = Field(
        default_factory=list,
        description="Offers/hotels as returned by the MCP_B2C tools (never fabricated).",
    )
    profile_delta: dict = Field(
        default_factory=dict,
        description="Only the NEW profile facts learned this turn; empty if none — schema fixed in S5.",
    )
    diagnostics: dict = Field(
        default_factory=dict,
        description="Tool calls made, degradations, errors — for observability, never user-facing.",
    )
