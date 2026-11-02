"""Explore offers for an unresolved party without inventing its composition.

Ported from #134 (PORT1 slice 5).
"""
from __future__ import annotations

from typing import Any


def discovery_total(params: Any) -> int | None:
    value = params.get("party_total") if isinstance(params, dict) else None
    return value if type(value) is int and 1 <= value <= 30 else None


def possible_party(offer: dict, total: int) -> bool:
    """Existence of a possible composition, NEVER proof for this customer.

    The provider exposes separate adult and child limits. Missing limits do
    not prove capacity. At least one adult must be possible. Booking still
    requires the customer's actual composition and ordinary eligibility.
    """
    adults, children = offer.get("capacity"), offer.get("childrenCapacity")
    return (type(adults) is int and adults >= 1 and (adults >= total or (
        type(children) is int and children >= 0 and adults + children >= total)))
