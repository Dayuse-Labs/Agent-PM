"""Concierge-owned location confirmation; leaves only return provider evidence."""
from __future__ import annotations

from b2c_common.confirmed_location import pending_location, verified_place

from .profile import SessionProfile


def selected_place(profile: SessionProfile, intent: dict | None, areas: list[dict] | None = None) -> dict | None:
    pending = pending_location(profile.pending_location)
    if not pending:
        return None
    if intent and intent.get("action") == "select":
        n = intent.get("position")
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= len(pending["options"]):
            return None
        return dict(pending["options"][n - 1])
    # The existing, current-message-grounded area extraction may already name
    # one candidate (e.g. city + provider administrative code). Do not require
    # the model to emit a redundant selection flag, or parse the reply again.
    if not areas or len(areas) != 1:
        return None
    area = areas[0]
    if area.get("subarea") or area.get("boundary_evidence"):
        return None
    matches = [o for o in pending["options"]
               if o["name"].casefold() == area.get("query", "").casefold()
               and o["country_code"] == area.get("country")
               and (not area.get("code") or area["code"] == o.get("administrative_code"))]
    return dict(matches[0]) if len(matches) == 1 else None


def commit_place(profile: SessionProfile, place: dict) -> None:
    profile.confirmed_location = dict(place)
    profile.pending_location = None
    profile.city = place["name"]
    profile.country_anchor = place["country_code"]
    # A foreign province code is not a US state.
    profile.state_anchor = place["region"] if place["country_code"] == "US" else None


def receive_location(profile: SessionProfile, response: dict) -> None:
    pending = pending_location(response.get("location_clarification"))
    if pending and response.get("requires_clarification"):
        profile.pending_location = pending
        profile.confirmed_location = None
        profile.pending_booking = None
        profile.last_results = None
        return
    place = verified_place(response.get("resolved_location"))
    if place:
        commit_place(profile, place)
    elif profile.confirmed_location:
        old = verified_place(profile.confirmed_location)
        if (not old or (profile.city or "").casefold() != old["name"].casefold()
                or (profile.country_anchor and profile.country_anchor != old["country_code"])):
            profile.confirmed_location = None

