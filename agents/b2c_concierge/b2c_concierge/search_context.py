"""Keep requested geography across failures, separate from verified profile state."""
from typing import Any

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
    profile.search_location_request = requested
    view["search_location_request"] = requested
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
