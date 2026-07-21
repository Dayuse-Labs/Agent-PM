"""geocode_location — the one deterministic, code-owned geocoding tool.

MCP_B2C's `search_offers` requires numeric `lat`/`lon` and does no geocoding
server-side (HANDOFF S2 finding). Letting the LLM invent coordinates from its
own world knowledge is exactly what produced the audited prod failures this
leaf's 3 guards fix (geo_guards.py). So geocoding is a TOOL the model calls,
but every decision inside it — demoting a generic city word, picking the
qualifying US state, validating the geocoder's answer actually echoes the
request, updating the state anchor — is deterministic code, never a second
LLM judgement call. A guard never re-runs a loop: one Mapbox call (+1 retry
inside the client), one echo-back check, done — reject or accept, never ask
the model to try again.

profile_state_context / profile_location_hint: this leaf holds no session
(decision B3) — the caller already received `profile_in` as part of the
request and reads the relevant fields back out to pass them in here. The
returned `profile_delta` is what changed and must be forwarded to next
turn's `profile_in` by whoever owns the session (the orchestrator, S5).
"""
from __future__ import annotations

import os

from hotel_search_agent.geo_guards import (
    anchor_state_context,
    demote_generic_city,
    geocode_echo_matches,
    resolve_state_hint,
    select_us_postal_anchor,
)
from hotel_search_agent.mapbox_client import MapboxClient

_client: MapboxClient | None = None


def build_mapbox_client() -> MapboxClient:
    """MAPBOX_ACCESS_TOKEN is read lazily, same posture as MCP_B2C_AUTH_TOKEN:
    an empty token is not a boot-time failure (Mapbox isn't a D7 identity
    concern) — a call made with it simply fails geocoding, and the tool
    degrades honestly (see `geocode_location`)."""
    return MapboxClient(
        access_token=os.environ.get("MAPBOX_ACCESS_TOKEN", ""),
        timeout_seconds=float(os.environ.get("MAPBOX_GEOCODE_TIMEOUT_SECONDS", "1.5")),
    )


def get_mapbox_client() -> MapboxClient:
    global _client
    if _client is None:
        _client = build_mapbox_client()
    return _client


def geocode_location(
    city: str,
    zone: str | None = None,
    metro: str | None = None,
    country_code: str | None = None,
    raw_user_message: str = "",
    profile_state_context: str | None = None,
    profile_location_hint: str | None = None,
) -> dict:
    """Resolve a destination to coordinates for `search_offers`, guarded.

    Args:
        city: The destination city as extracted from the request (may be a
            generic word like "airport" — demoted to a zone hint, never
            geocoded literally).
        zone: A sub-city area/landmark, if any.
        metro: A metro-area name, if distinct from city.
        country_code: A trusted ISO-3166-1 alpha-2 country to scope the
            geocode to, if already known. When omitted, a 5-digit US ZIP
            anywhere in the request (`select_us_postal_anchor`) deterministically
            forces "US" — never a locale→country guess otherwise.
        raw_user_message: The turn's raw text — feeds state-hint extraction
            ("Milford ct") and the state anchor.
        profile_state_context: The US state anchored on an earlier turn
            (from profile_in), if any.
        profile_location_hint: The city/location profile_in last recorded,
            used both as a state-hint text source and to detect an explicit
            city switch that should clear a stale state anchor.

    Returns a dict — NEVER raises. On success:
        {"ok": True, "latitude", "longitude", "resolved_place", "country_code",
         "profile_delta"}
    On any guard rejection or geocoder failure, a clean diagnostic:
        {"ok": False, "error": "<reason>", "diagnostics": {...}}
    """
    demoted = demote_generic_city({"city": city, "zone": zone, "metro": metro})
    effective_city: str | None = demoted.get("city")
    effective_zone: str | None = demoted.get("zone")
    effective_metro: str | None = demoted.get("metro")

    if not effective_city and not effective_metro:
        return {
            "ok": False,
            "error": "no_geocodable_location",
            "diagnostics": {
                "reason": "generic_location_only" if effective_zone else "missing_city",
                "zone_hint": effective_zone,
            },
        }

    # A 5-digit US ZIP anywhere in the request is stronger, deterministic
    # evidence than trusting the model to also extract country_code — without
    # this, an unscoped ZIP can geocode worldwide (prod bug: "near 11580"
    # resolved outside the US). Only fills the gap when the model gave no
    # country signal at all; an explicit country_code always wins.
    effective_country_code = country_code
    if not effective_country_code and select_us_postal_anchor(
        raw_user_message, effective_city, effective_zone, effective_metro
    ):
        effective_country_code = "US"

    state_hint = resolve_state_hint(
        city=effective_city,
        zone=effective_zone,
        profile_location_hint=profile_location_hint,
        raw_user_message=raw_user_message,
        profile_state_context=profile_state_context,
        country_code=effective_country_code,
    )

    query = ", ".join(
        part for part in (effective_zone, effective_city or effective_metro, state_hint) if part
    )
    result = get_mapbox_client().geocode(query, country=effective_country_code)
    if result is None:
        return {
            "ok": False,
            "error": "geocode_unavailable",
            "diagnostics": {"query": query},
        }

    if not geocode_echo_matches(
        result.place_name,
        city=effective_city or effective_metro,
        zone=effective_zone,
        state_hint=state_hint,
    ):
        return {
            "ok": False,
            "error": "geocode_echo_mismatch",
            "diagnostics": {"query": query, "resolved_place": result.place_name},
        }

    _, profile_delta = anchor_state_context(
        city=effective_city,
        raw_user_message=raw_user_message,
        profile_in={
            "last_state_context": profile_state_context,
            "last_city": profile_location_hint,
        },
    )

    return {
        "ok": True,
        "latitude": result.latitude,
        "longitude": result.longitude,
        "resolved_place": result.place_name,
        "country_code": result.country_code,
        "profile_delta": profile_delta,
    }
