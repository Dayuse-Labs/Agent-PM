"""Bounded provider facts tied to the exact priced offer, never inferred from prose."""
from __future__ import annotations

from typing import Any


def _text(value: Any) -> str | None:
    # Do not truncate a room name into a potentially different claim.
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= 1000 else None


def selected_offer_facts(hotel: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    """No merging across formulas or dates; missing evidence stays unknown."""
    offer_id, offer_date = _text(offer.get("ratePlanUuid")), _text(offer.get("availabilityDate"))
    hotel_id = hotel.get("hotelId") or hotel.get("id")
    if not hotel_id or not offer_id or not offer_date:
        return {}
    facts: dict[str, Any] = {"hotel_id": hotel_id, "offer_id": offer_id, "offer_date": offer_date}
    for source, target in (("ratePlanName", "name"), ("bedding", "bedding"), ("roomType", "room_type")):
        value = _text(offer.get(source))
        if value:
            facts[target] = value
    # The provider has separate adult/child capacity fields. Keep zero (no
    # child capacity) and reject booleans/strings rather than guessing occupancy
    # from a commercial room name or a bedding code.
    for source, target in (("capacity", "capacity"), ("childrenCapacity", "children_capacity")):
        value = offer.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            facts[target] = value
    inclusions = offer.get("includedAmenities")
    if isinstance(inclusions, list):
        labels = list(dict.fromkeys(label for item in inclusions if (label := _text(item))))
        if labels:
            facts["provider_listed_amenities"] = labels[:48]
            if len(labels) > 48:
                facts["amenities_truncated"] = True
    return facts if len(facts) > 3 else {}


def matching_offer_facts(card: dict[str, Any]) -> dict[str, Any]:
    """A changed card must not reuse evidence for the previous hotel/formula/day."""
    facts = card.get("offer_facts")
    if not isinstance(facts, dict):
        return {}
    if any(not facts.get(key) or facts[key] != card.get(card_key) for key, card_key in
           (("hotel_id", "id"), ("offer_id", "offer_id"), ("offer_date", "offer_date"))):
        return {}
    # Re-normalize stored data as well: no arbitrary keys become prompt facts.
    normalized = selected_offer_facts({"hotelId": card["id"]}, {
        "ratePlanUuid": facts["offer_id"], "availabilityDate": facts["offer_date"],
        "ratePlanName": facts.get("name"), "bedding": facts.get("bedding"),
        "roomType": facts.get("room_type"), "includedAmenities": facts.get("provider_listed_amenities"),
        "capacity": facts.get("capacity"), "childrenCapacity": facts.get("children_capacity"),
    })
    if normalized and facts.get("amenities_truncated") is True:
        normalized["amenities_truncated"] = True
    return normalized
