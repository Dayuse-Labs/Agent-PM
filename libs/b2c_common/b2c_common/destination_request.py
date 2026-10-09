"""Customer destination intent, independent of provider-resolved identity.

Only the concierge creates this record from grounded semantic extractions.
The search leaf consumes it; neither model deltas nor provider labels edit it.
Names here are search requests, never proof of coordinates or membership.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .search_areas import validate_areas


class LandmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=200)
    country_guess: str | None = None

    @model_validator(mode="after")
    def coherent(self) -> LandmarkRequest:
        if not self.query.strip() or (self.city is not None and not self.city.strip()):
            raise ValueError("Landmark names cannot be blank")
        if self.country_guess is not None and (
            len(self.country_guess) != 2 or not self.country_guess.isascii()
            or not self.country_guess.isalpha()
        ):
            raise ValueError("Country hint must be ISO2 shaped")
        return self


class DestinationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["landmark", "landmarks", "hotel", "areas", "device"]
    query: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=200)
    country_guess: str | None = None
    areas: list[dict[str, str]] | None = None
    landmarks: list[LandmarkRequest] | None = Field(default=None, min_length=2, max_length=3)

    @model_validator(mode="after")
    def coherent(self) -> DestinationRequest:
        if self.kind != "landmarks" and self.landmarks is not None:
            raise ValueError("Only an alternative-landmark request carries landmarks")
        if self.kind == "landmarks":
            if not self.landmarks or any((self.query, self.city, self.country_guess, self.areas)):
                raise ValueError("Alternative landmarks retain their separate requests")
        elif self.kind in {"landmark", "hotel"}:
            if not self.query or not self.query.strip() or self.areas is not None:
                raise ValueError("A landmark needs a requested name, not area geometry")
            if self.city is not None and not self.city.strip():
                raise ValueError("An absent parent is null")
            if self.country_guess is not None and (
                len(self.country_guess) != 2 or not self.country_guess.isascii()
                or not self.country_guess.isalpha()
            ):
                raise ValueError("Country hint must be ISO2 shaped")
        elif self.kind == "areas":
            if validate_areas(self.areas) is None or any((self.query, self.city, self.country_guess)):
                raise ValueError("Areas retain their existing grounded request contract")
        elif any((self.query, self.city, self.country_guess, self.areas)):
            raise ValueError("Device intent cannot carry model-supplied locations")
        return self


def destination_request(value: Any) -> DestinationRequest | None:
    try:
        return DestinationRequest.model_validate(value)
    except (ValidationError, TypeError):
        return None


def requested_parent(value: Any) -> str | None:
    """Return a previous customer parent label, never a provider confirmation."""
    request = destination_request(value)
    if request is None:
        return None
    if request.kind in {"landmark", "hotel"}:
        return request.city
    if request.kind == "areas" and request.areas and len(request.areas) == 1:
        area = request.areas[0]
        if area["kind"] == "municipality":
            return area["query"]
    return None


def refine_landmark(update: dict | None, previous: Any, action: str | None,
                    parent_city: str | None) -> dict | None:
    """Reduce typed corrections without treating earlier request text as proof.

    A new destination never inherits a parent implicitly. A correction of the
    same target can retain the customer's parent even before geocoding succeeds.
    """
    request = destination_request(previous)
    if update is not None:
        result = dict(update)
        if not result.get("city") and action in {"correct", "refine"}:
            result["city"] = parent_city or requested_parent(previous)
        return result
    if request and request.kind == "landmark" and action == "refine" and parent_city:
        return {"query": request.query, "city": parent_city, "country_guess": None}
    return None


def refine_hotel(name: str | None, previous: Any, action: str | None,
                 parent_city: str | None, message: str) -> dict | None:
    """Keep the named property when its containing city is clarified.

    Request names are literal user evidence, not provider identities. A new
    named hotel has no inherited city; a parent-only answer keeps its old name.
    """
    request = destination_request(previous)
    if name and name.strip().casefold() in message.casefold():
        return {"kind": "hotel", "query": name.strip()}
    if request and request.kind == "hotel" and action == "refine" and parent_city:
        return {**request.model_dump(exclude_none=True), "city": parent_city}
    return None
