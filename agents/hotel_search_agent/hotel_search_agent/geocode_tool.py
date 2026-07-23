"""geocode_location — the one deterministic, code-owned geocoding tool.

MCP_B2C's `search_offers` requires numeric `lat`/`lon` and does no geocoding
server-side (HANDOFF S2 finding). Letting the LLM invent coordinates from its
own world knowledge is exactly what produced the audited prod failures this
leaf's guards fix (geo_guards.py). So geocoding is a TOOL the model calls, but
every decision inside it — demoting a generic city word, picking the qualifying
US state, RANKING the geocoder's candidates, validating the winner echoes the
request, updating the state anchor — is deterministic code, never a second LLM
judgement call. A guard never re-runs a loop: at most one v6 candidate call
(+1 retry in the client), an optional single Search-Box fallback, one echo
check — reject / accept / ask, never ask the model to try again.

S-G3 replaced the old limit=1 accept/reject with a multi-candidate resolver
(`geo_resolver`, 100% deterministic, inventory-aware). The echo-back guard
survives as the final sanity check on the CHOSEN candidate — it was designed
for exactly the mis-resolution it will keep catching.

profile_state_context / profile_location_hint: this leaf holds no session
(decision B3) — the caller already received `profile_in` as part of the
request and reads the relevant fields back out to pass them in here. The
returned `profile_delta` is what changed and must be forwarded to next
turn's `profile_in` by whoever owns the session (the orchestrator, S5).
"""
from __future__ import annotations

import os

from hotel_search_agent import geo_resolver
from hotel_search_agent.geo_guards import (
    anchor_state_context,
    demote_generic_city,
    geocode_echo_matches,
    resolve_state_hint,
    select_us_postal_anchor,
)
from hotel_search_agent.inventory import get_inventory
from hotel_search_agent.mapbox_client import GeocodeResult, MapboxClient
from hotel_search_agent.searchbox_client import SearchBoxClient

_client: MapboxClient | None = None
_searchbox: SearchBoxClient | None = None

# Language → home-country ISO2 for the bounded locale prior (geo memo §C.3). Only
# the unambiguous mappings among the 29 markets — English is intentionally absent
# (en spans US/GB/CA/AU/…, a prior would mislead more than it helps).
_LOCALE_COUNTRY = {
    "fr": "FR", "pt": "PT", "it": "IT", "de": "DE", "es": "ES", "nl": "NL",
}


def build_mapbox_client() -> MapboxClient:
    """MAPBOX_ACCESS_TOKEN is read lazily, same posture as MCP_B2C_AUTH_TOKEN:
    an empty token is not a boot-time failure (Mapbox isn't a D7 identity
    concern) — a call made with it simply fails geocoding, and the tool
    degrades honestly (see `geocode_location`)."""
    return MapboxClient(
        access_token=os.environ.get("MAPBOX_ACCESS_TOKEN", ""),
        timeout_seconds=float(os.environ.get("MAPBOX_GEOCODE_TIMEOUT_SECONDS", "1.5")),
    )


def build_searchbox_client() -> SearchBoxClient:
    return SearchBoxClient(
        access_token=os.environ.get("MAPBOX_ACCESS_TOKEN", ""),
        timeout_seconds=float(os.environ.get("MAPBOX_GEOCODE_TIMEOUT_SECONDS", "1.5")),
    )


def get_mapbox_client() -> MapboxClient:
    global _client
    if _client is None:
        _client = build_mapbox_client()
    return _client


def get_searchbox_client() -> SearchBoxClient:
    global _searchbox
    if _searchbox is None:
        _searchbox = build_searchbox_client()
    return _searchbox


def _locale_country(locale: str | None) -> str | None:
    if not locale:
        return None
    return _LOCALE_COUNTRY.get(locale.strip().lower()[:2])


def _echoes(place_name: str, *, city: str | None, zone: str | None, state_hint: str | None) -> bool:
    return geocode_echo_matches(place_name, city=city, zone=zone, state_hint=state_hint)


def _ok(
    result: GeocodeResult,
    *,
    feature_type: str,
    profile_delta: dict,
    distance_origin_type: str,
) -> dict:
    return {
        "ok": True,
        "latitude": result.latitude,
        "longitude": result.longitude,
        "resolved_place": result.place_name,
        "resolved_feature_type": feature_type,
        "distance_origin_type": distance_origin_type,
        "country_code": result.country_code,
        "profile_delta": profile_delta,
    }


def geocode_location(
    city: str,
    zone: str | None = None,
    metro: str | None = None,
    country_code: str | None = None,
    raw_user_message: str = "",
    profile_state_context: str | None = None,
    profile_location_hint: str | None = None,
    locale: str | None = None,
) -> dict:
    """Resolve a destination to coordinates for `search_offers`, guarded.

    Args:
        city: The destination city as extracted from the request (may be a
            generic word like "airport" — demoted to a zone hint, never
            geocoded literally).
        zone: A sub-city area/landmark, if any. A landmark/POI here ("La Défense",
            "Tour Eiffel") is what triggers the Search-Box tier-2 fallback when
            v6 can't resolve it.
        metro: A metro-area name, if distinct from city.
        country_code: A trusted ISO-3166-1 alpha-2 country to scope the
            geocode to, if already known. When omitted, a 5-digit US ZIP
            anywhere in the request (`select_us_postal_anchor`) deterministically
            forces "US" — never a locale→country guess otherwise. A named country
            is a HARD filter on the candidates, never a boost.
        raw_user_message: The turn's raw text — feeds state-hint extraction
            ("Milford ct") and the state anchor.
        profile_state_context: The US state anchored on an earlier turn
            (from profile_in), if any.
        profile_location_hint: The city/location profile_in last recorded,
            used both as a state-hint text source and to detect an explicit
            city switch that should clear a stale state anchor.
        locale: The user's language tag from profile_in (e.g. "fr", "pt") — a
            SOFT signal: it biases Mapbox scoring/localisation and gives the
            same-country candidate a bounded prior. Never a filter. (GPS
            proximity, a separate soft signal, is wired from the profile in S-G5.)

    Returns a dict — NEVER raises. On success:
        {"ok": True, "latitude", "longitude", "resolved_place",
         "resolved_feature_type", "distance_origin_type", "country_code",
         "profile_delta"}
    On an ambiguous homonym, a clarify request (ask ONE question, don't search):
        {"ok": False, "error": "geocode_ambiguous", "diagnostics": {"question", "options"}}
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
    lang = (locale or "").strip().lower()[:2] or None
    candidates = get_mapbox_client().geocode_candidates(
        query, country=effective_country_code, language=lang
    )

    resolution = geo_resolver.resolve(
        candidates,
        inventory=get_inventory(),
        country_hint=effective_country_code,
        region_hint=state_hint,
        locale_country=_locale_country(locale),
        # proximity (GPS) is accepted by the client + resolver but wired from the
        # profile in S-G5 — none is sourced here yet (band rule already enforced).
        proximity=None,
    )

    echo_city = effective_city or effective_metro

    if resolution.decision == "clarify":
        return {
            "ok": False,
            "error": "geocode_ambiguous",
            "diagnostics": {
                "question": resolution.question,
                "options": [
                    {
                        "name": c.name,
                        "country_code": c.country_code,
                        "region": c.region,
                        "place_formatted": c.place_formatted,
                    }
                    for c in resolution.options
                ],
            },
        }

    if resolution.decision == "select" and resolution.chosen is not None:
        chosen = resolution.chosen
        if _echoes(chosen.place_name, city=echo_city, zone=effective_zone, state_hint=state_hint):
            _, profile_delta = anchor_state_context(
                city=effective_city,
                raw_user_message=raw_user_message,
                profile_in={
                    "last_state_context": profile_state_context,
                    "last_city": profile_location_hint,
                },
            )
            return _ok(
                chosen.as_result(),
                feature_type=chosen.feature_type,
                profile_delta=profile_delta,
                distance_origin_type="city_centroid",
            )
        # The chosen candidate failed the echo sanity check — fall through to the
        # Search-Box tier-2 fallback below if a zone/landmark was named.

    # Tier 2 (A2-b): v6 gave us nothing acceptable. When the request named a
    # zone/landmark ("La Défense", "Tour Eiffel"), retry ONCE via Search Box,
    # which v6 can't resolve (POI support dropped). Never on a bare-city miss
    # (Search Box is worse for cities and a separate SKU).
    if effective_zone:
        # The landmark ALONE — appending the city biases Search Box toward
        # businesses named after the landmark (probed: "La Défense, Paris" →
        # a hotel "Citadines La Défense"; bare "La Défense" → the district).
        poi = get_searchbox_client().forward(
            effective_zone, country=effective_country_code, language=lang
        )
        if poi is not None and _echoes(
            poi.place_name, city=echo_city, zone=effective_zone, state_hint=state_hint
        ):
            _, profile_delta = anchor_state_context(
                city=effective_city,
                raw_user_message=raw_user_message,
                profile_in={
                    "last_state_context": profile_state_context,
                    "last_city": profile_location_hint,
                },
            )
            return _ok(
                poi,
                feature_type="poi",
                profile_delta=profile_delta,
                distance_origin_type="poi",
            )

    # Nothing survived: distinguish "no candidate at all" from "resolved to the
    # wrong place" for honest diagnostics (both degrade — never a fabricated coord).
    if not candidates:
        return {"ok": False, "error": "geocode_unavailable", "diagnostics": {"query": query}}
    resolved_place = resolution.chosen.place_name if resolution.chosen is not None else None
    return {
        "ok": False,
        "error": "geocode_echo_mismatch",
        "diagnostics": {"query": query, "resolved_place": resolved_place},
    }
