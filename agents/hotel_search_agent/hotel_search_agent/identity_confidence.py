"""Provider identity evidence, independent of hotel inventory and UI locale.

Adapted from production's confidence-gated geography policy (3093647).
Callers must first enforce literal identity, feature type and explicit parent /
country constraints. A missing identity is never repaired by this selector.
"""
from __future__ import annotations

from hotel_search_agent.mapbox_client import GeocodeCandidate

PROMINENCE_GAP = 3
MAX_WEAK_PRIOR_RANK = 3


def dominant_identity(candidates: list[GeocodeCandidate]) -> GeocodeCandidate | None:
    """Select a unique identity or a clearly leading provider identity.

    Original provider ranks survive filtering; adjacent homonyms remain
    ambiguous. Counts of bookable hotels cannot establish geographic intent.
    Missing provider IDs preclude deduplication, not ordinary city ranking.
    """
    unique: dict[object, GeocodeCandidate] = {}
    for candidate in candidates:
        key = candidate.mapbox_id or (candidate.name, candidate.country_code,
                                      candidate.latitude, candidate.longitude)
        previous = unique.get(key)
        if previous is None or candidate.rank < previous.rank:
            unique[key] = candidate
    ranked = sorted(unique.values(), key=lambda candidate: candidate.rank)
    if not ranked:
        return None
    if len(ranked) == 1 or ranked[1].rank - ranked[0].rank >= PROMINENCE_GAP:
        return ranked[0]
    return None
