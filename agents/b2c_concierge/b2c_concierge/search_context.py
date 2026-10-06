"""Keep requested geography across failures, separate from verified profile state."""
from typing import Any

from b2c_common.resolved_location import request_identity, verified_resolution
from b2c_common.search_location import location_request, parse_location_update

from .profile import SessionProfile, leaf_profile_view


def prepare_search_context(profile: SessionProfile, update: dict | None) -> dict[str, Any]:
    view = leaf_profile_view(profile)
    edit = parse_location_update(update)
    if edit is None:
        return view  # Old callers / failed triage keep the existing leaf contract.
    previous = profile.search_location_request
    if previous is None:
        previous = {
            "city": profile.city, "zone": profile.zone, "metro": profile.metro,
            "country_code": profile.country_anchor, "region": profile.state_anchor,
        }
    requested = location_request(previous, edit)
    if edit["action"] != "retain" and request_identity(requested) != request_identity(previous):
        profile.resolved_search_location = None
    profile.search_location_request = requested
    view["search_location_request"] = requested
    if edit["action"] == "retain" and verified_resolution(profile.resolved_search_location, requested):
        view["resolved_search_location"] = profile.resolved_search_location
    # The leaf sees the effective requested fields; the stored resolved fields
    # only change later through the geocoder's profile_delta.
    for source, target in (("city", "city"), ("zone", "zone"), ("metro", "metro"),
                           ("country_code", "country_anchor"), ("region", "state_anchor")):
        view[target] = requested[source]
    if requested.get("city") or requested.get("metro") or edit["action"] == "replace":
        view["search_anchor"] = None
    if edit["action"] == "replace":
        view["last_results"] = []
    return view


def triage_search_context(profile: SessionProfile) -> dict:
    """Bounded durable state; history may have scrolled past the first request."""
    return {
        "requested_location": profile.search_location_request,
        "verified_location": {"city": profile.city, "region": profile.state_anchor,
                              "country_code": profile.country_anchor, "zone": profile.zone},
        "budget_max": profile.budget_max,
        "timeslot_start": profile.timeslot_start, "timeslot_end": profile.timeslot_end,
        "amenities": profile.amenities, "date": profile.date,
        "named_hotel": profile.named_hotel,
        "visible_hotels": [{"hotel_id": h.get("hotel_id"), "name": str(h.get("name") or "")[:160]}
                           for h in (profile.last_results or [])[:5]],
        "last_clarifying_question": (profile.last_clarifying_question or "")[:400],
    }
