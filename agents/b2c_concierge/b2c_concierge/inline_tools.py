"""Inline MCP tools of the orchestrator — STUBS in S2 (details / compare / booking-link).

The real implementations call the MCP_B2C tools `get_hotel_details`,
`compare_hotels` and `generate_booking_link` inside the bounded synthesis
tool-loop (S6, <= 2 iterations). `generate_booking_link` is additionally
guarded by R9 when the guards land (S4-S7): NEVER callable without the
turn-state confirmation flag. Until then these stubs return a deterministic
no-op payload and the spine answers with an honest template (zero extra LLM)
— never an invented detail, price, or link.
"""
from __future__ import annotations

from collections.abc import Callable


def _stub(tool: str) -> dict:
    return {
        "tool": tool,
        "status": "stub_s2",
        "results": [],
        "diagnostics": {"note": "inline MCP tool not wired yet (S4+); honest template served"},
    }


def get_hotel_details(hotel_id: str | None = None) -> dict:
    return _stub("get_hotel_details")


def compare_hotels(hotel_ids: list[str] | None = None) -> dict:
    return _stub("compare_hotels")


def generate_booking_link(offer_id: str | None = None) -> dict:
    # R9 (S4-S7): the real tool must be uncallable without the turn-state
    # confirmation flag. The stub returns NO link by construction.
    return _stub("generate_booking_link")


STUBS: dict[str, Callable[..., dict]] = {
    "get_hotel_details": get_hotel_details,
    "compare_hotels": compare_hotels,
    "generate_booking_link": generate_booking_link,
}
