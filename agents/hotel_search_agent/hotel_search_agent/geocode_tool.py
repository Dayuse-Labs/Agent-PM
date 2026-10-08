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

from b2c_common.observability import mark_level
from hotel_search_agent import geo_resolver
from b2c_common.search_areas import AreaRequest, preserve_area_boundary, requires_area_membership, validate_areas
from hotel_search_agent.area_scope import STATE_FAILED, resolve_areas
from hotel_search_agent.geo_guards import (
    _echo_fold,
    anchor_state_context,
    demote_generic_city,
    geocode_echo_matches,
    is_generic_location_token,
    resolve_state_hint,
    select_us_postal_anchor,
)
from hotel_search_agent.inventory import get_inventory, haversine_km
from hotel_search_agent.mapbox_client import GeocodeCandidate, GeocodeResult, MapboxClient
from hotel_search_agent.response_bridge import find_datapart, read_profile_in
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


def _iso2(value: str | None) -> str | None:
    """A 2-letter ISO country code, uppercased, or None. Anything else from the
    model (a country NAME, "FRA", noise) is discarded rather than guessed at —
    a malformed hint must degrade to "no hint", never to a wrong scope."""
    token = (value or "").strip().upper()
    return token if len(token) == 2 and token.isalpha() else None


def _soft_country(
    named: str | None, guess: str | None, locale: str | None
) -> str | None:
    """The country to SCOPE the Search-Box fallback with, in confidence order:
    a country the user named (already a hard filter upstream) > the model's
    world-knowledge guess > the locale prior.

    This is P0-2 fix 2 (audit §1 M3). Before it, the tier-2 POI lookup was sent
    with `country=effective_country_code`, which is only populated when the user
    NAMED a country or typed a US ZIP — so in the common case it was an
    unscoped, worldwide, limit=1 lookup. That is what let a business called
    "Champs Elysées" in another hemisphere win: the echo guard validates the
    NAME, so a perfect name match in the wrong country sails through it (M4).
    A country scope is the only signal that separates those two."""
    return named or _iso2(guess) or _locale_country(locale)


_AIRPORT_WORDS = frozenset({"airport", "airports", "aeroport", "aeroports", "aeropuerto", "aeroporto", "flughafen", "luchthaven"})


def _place_words(value: str) -> list[str]:
    """Tokenize a place label without regular expressions."""
    return "".join(ch if ch.isalnum() else " " for ch in _echo_fold(value)).split()


def _landmark_query(zone: str) -> str:
    # Search Box does not reliably understand a translated generic category
    # alongside an IATA identifier (e.g. French 'aéroport JFK' returns nothing).
    # Preserve the actual identifier and terminal number, not a guessed place.
    words = zone.split()
    kept = [word for word in words if _echo_fold(word) not in _AIRPORT_WORDS]
    has_identifier = (
        len(kept) == 1 and len(kept[0]) == 3 and kept[0].isalpha()
    ) or any(len(word) == 3 and word.isalpha() and word.isupper() for word in kept)
    return " ".join(kept) if kept and has_identifier else zone


def _echoes(place_name: str, *, city: str | None, zone: str | None, state_hint: str | None) -> bool:
    # Matching only the parent city must not turn its centroid into a named
    # landmark. Reuse the existing validator on the zone independently, then
    # let the normal city/state check and POI anchor guard do their work.
    if zone and not is_generic_location_token(zone):
        zone_words = _place_words(_landmark_query(zone))
        place_words = _place_words(place_name)
        # A terminal number is part of the landmark identity, not a weak hint.
        if any(word.isdigit() and word not in place_words for word in zone_words):
            return False
        letters = [word for word in zone_words if word.isalpha()]
        if len(letters) == 1 and len(letters[0]) <= 3:
            code = letters[0]
            initials = "".join(word[0] for word in place_words if word.isalpha())
            if code not in place_words and not initials.startswith(code):
                return False
        elif not geocode_echo_matches(
            place_name, city=None, zone=_landmark_query(zone), state_hint=None
        ):
            return False
    return geocode_echo_matches(
        place_name, city=city, zone=_landmark_query(zone) if zone else None, state_hint=state_hint
    )


#: How far a tier-2 POI may sit from THIS turn's anchor before the 14th guard
#: (`poi_anchor_coherence`, 2026-08-26) throws it away.
#:
#: Tightened from 100 km to 40 km on 2026-08-26 (Fabien: "100 km c'est beaucoup
#: trop", and he is right — at 100 km this was a check against the ABSURD, not a
#: coherence check on a city). The window is bounded at both ends by measured
#: distances, so it is not a taste call:
#:   must KEEP    Orly 14,7 km · Versailles 17,5 · CDG 22,7 · Évry 25,7 (a
#:                homonym, but the near cases belong to the anchoring fix, not
#:                to this veto) · Disneyland Paris 31,3 ← the binding case
#:   must REJECT  Saint-Quentin 130 km · Viré 329 · Lyon 393 · Toulon 830
#: Anything in (32, 130) is therefore defensible; 100 was the loosest end of it
#: and 40 is the tight end that still clears Disneyland with ~8 km of headroom.
#: Beauvais (69 km, marketed as a "Paris" airport) is now rejected against a
#: Paris anchor — deliberate: it is a different city, and the user who means it
#: says Beauvais.
#:
#: This applies to EVERY anchor, the device GPS fix included — not only to the
#: city coordinate `_city_candidate` introduces below.
_POI_ANCHOR_MAX_KM = 40.0


def _poi_anchor_incoherent(
    poi: GeocodeCandidate,
    *,
    anchor: tuple[float, float] | None,
) -> bool:
    """Guard #14 — is this tier-2 POI absurdly far from where the turn is about?

    The echo-back guard validates the NAME; this one validates the PLACE, which
    is the hole the audit called M4 ("a business called « Champs Elysées » in
    Toulon echoes « champs élysées » perfectly — the name is right, the place is
    wrong"). It is a distance check against the anchor the turn already
    established: the device GPS fix, or the best tier-1 candidate.

    Honest limit: with NO anchor (bare landmark, no city, no GPS) there is
    nothing to compare to, so it does not fire and does not block. That case is
    covered upstream by putting the city in the Search-Box query — this guard
    is the net under that fix, not a substitute for it."""
    if anchor is None:
        return False
    return haversine_km(anchor[0], anchor[1], poi.latitude, poi.longitude) > _POI_ANCHOR_MAX_KM


def _city_candidate(
    city: str,
    *,
    country: str | None,
    locale_country: str | None,
    language: str | None,
) -> GeocodeCandidate | None:
    """Resolve the named city independently of a fuzzy city + landmark query.

    An exact municipality can anchor geography even without Dayuse inventory.
    A neighborhood named after a city cannot: keep the inventory credibility
    requirement for those candidates (the Paris/Roanne regression). An ambiguous
    resolution supplies no authoritative anchor.
    """
    candidates = get_mapbox_client().geocode_candidates(
        # A localized combined query can omit the named city's canonical
        # candidate entirely (London + French labels returned only Canada).
        # This dedicated lookup keeps the customer's place string and uses
        # neutral labels; locale remains a bounded prior in the resolver.
        city, country=country, language=None, proximity=None
    )
    resolution = geo_resolver.resolve(
        candidates,
        inventory=get_inventory(),
        country_hint=country,
        region_hint=None,
        locale_country=locale_country,
        proximity=None,
        requested_name=city,
        language=language,
    )
    if resolution.decision != "select" or resolution.chosen is None:
        return None
    chosen = resolution.chosen
    for scored in resolution.scored:
        if scored.candidate != chosen:
            continue
        municipality = (
            chosen.feature_type == "place"
            and _echo_fold(chosen.name) == _echo_fold(city)
        )
        if (scored.in_inventory_tier or municipality) and _echoes(
            chosen.place_name, city=city, zone=None, state_hint=None
        ):
            return chosen
    return None


def _anchor_state(
    *,
    city: str | None,
    raw_user_message: str,
    profile_state_context: str | None,
    profile_location_hint: str | None,
    guards_fired: list[str],
) -> dict:
    """`anchor_state_context` plus the OBS3 wiring its guard never had.

    The `state_anchoring` guard is one of the 5 that fire in this leaf and whose
    Langfuse score was structurally stuck at 0.0 — nothing reported them to the
    concierge (`scores.py`: "a later session wires their call sites"). It counts
    as having fired when it actually did something: a US state is in effect for
    this geocode, or it cleared a stale one."""
    anchored, delta = anchor_state_context(
        city=city,
        raw_user_message=raw_user_message,
        profile_in={
            "last_state_context": profile_state_context,
            "last_city": profile_location_hint,
        },
    )
    if anchored or "last_state_context" in delta:
        guards_fired.append("state_anchoring")
    return delta


def _searchbox_query(zone: str | None, city: str | None, metro: str | None) -> str:
    """`"<zone>, <city>"` when a city or metro is known, the landmark alone
    otherwise — the LAST-RESORT way to tell Search Box which city we mean.

    Only used when we have a city NAME but no city COORDINATE (see the caller:
    a coordinate is strictly better, because it goes in `proximity` and leaves
    the query bare). The 2026-07-23 comment this partially reverses said "the
    landmark ALONE — appending the city biases Search Box toward businesses
    named after the landmark (probed: 'La Défense, Paris' → a hotel 'Citadines
    La Défense')". That was right, and measurement confirms it: `"les champs
    élysées, Paris"` returns 10 businesses and no clean feature at all. What it
    got wrong is the conclusion — the bare landmark is not safe either, because
    Mapbox then ranks it by our egress IP (130-400 km errors). Both readings
    hold: appending the city buys the right POSITION at the cost of the LABEL,
    so it is the fallback, not the default."""
    anchor = (city or "").strip() or (metro or "").strip()
    zone_part = (zone or "").strip()
    if anchor and zone_part:
        return f"{zone_part}, {anchor}"
    return zone_part or anchor


def _fail(
    error: str,
    diagnostics: dict,
    guards_fired: list[str] | None = None,
    profile_delta: dict | None = None,
) -> dict:
    """A guarded failure. Carries `guards_fired` like `_ok` does: a guard that
    fired and then made the turn fail honestly is exactly the event OBS3 wants
    to see — scoring only the successes would report the opposite of reality.

    `profile_delta` exists for ONE case: a clarify. When this tool asks the user
    a question, whatever the question was ABOUT has to survive the answer turn —
    otherwise the answer arrives with nothing to attach itself to. Measured in
    prod on 2026-08-26: asked "gare de lyon — which city?", answered "paris",
    and the search ran on the bare Paris centroid (Saint-Denis 7,4 km, Orly
    12,6 km) because the zone was never persisted. S-G5's own rationale ("a zone
    is lost across turns") applied to the clarify path it had missed."""
    payload: dict = {"ok": False, "error": error, "diagnostics": diagnostics}
    if guards_fired:
        payload["guards_fired"] = sorted(set(guards_fired))
    if profile_delta:
        payload["profile_delta"] = profile_delta
    return payload


def _ok(
    result: GeocodeResult,
    *,
    feature_type: str,
    profile_delta: dict,
    distance_origin_type: str,
    zone: str | None = None,
    metro: str | None = None,
    guards_fired: list[str] | None = None,
) -> dict:
    # S-G5: zone/metro were accepted by this tool and validated by the echo
    # guard, but never reached the profile before now (audit gap — "a zone is
    # lost across turns"). Only-when-present: no zone/metro this turn is
    # carryover at the concierge (S-G1), never a clear.
    delta = dict(profile_delta)
    if zone:
        delta["zone"] = zone
    if metro:
        delta["metro"] = metro
    payload = {
        "ok": True,
        "latitude": result.latitude,
        "longitude": result.longitude,
        "resolved_place": result.place_name,
        "resolved_feature_type": feature_type,
        "distance_origin_type": distance_origin_type,
        "country_code": result.country_code,
        "profile_delta": delta,
    }
    # OBS3: which deterministic guards actually fired this turn, so the
    # concierge can score them (`response_bridge` stashes this, the spine folds
    # it into `budget.fired`). Only-when-non-empty: the model never needs to
    # read it, and an empty list would just be noise in the tool payload.
    if guards_fired:
        payload["guards_fired"] = sorted(set(guards_fired))
    return payload


def geocode_location(
    city: str = "",
    zone: str | None = None,
    metro: str | None = None,
    country_code: str | None = None,
    raw_user_message: str = "",
    profile_state_context: str | None = None,
    profile_location_hint: str | None = None,
    locale: str | None = None,
    language_hint: str | None = None,
    proximity_lat: float | None = None,
    proximity_lon: float | None = None,
    country_guess: str | None = None,
    areas: list[AreaRequest] | None = None,
) -> dict:
    """Resolve a destination to coordinates for `search_offers`, guarded.

    Args:
        city: The destination city as extracted from the request (may be a
            generic word like "airport" — demoted to a zone hint, never
            geocoded literally).

            Defaults to "" and is NOT a mandatory parameter, deliberately. It
            used to have no default, so ADK declared it mandatory and rejected
            the whole tool call with "the following mandatory input parameters
            are not present: city" whenever the model omitted the key — which
            it does precisely when the user named a landmark and no city. 14
            such dead turns in the traces between 2026-08-15 and 08-26 (champs
            élysées, louvre, gare de lyon, eiffel tower, la défense, buckingham
            palace). An absent `city` is a legitimate shape, so it degrades to
            the landmark path instead of killing the turn.
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
        country_guess: The ISO-3166-1 alpha-2 country this place is
            world-famously in, from the model's own world knowledge, when it is
            confident ("champs élysées" -> FR, "times square" -> US). A SOFT
            prior only: it is scored with the same bounded weight as the locale
            prior and scopes the Search-Box fallback, but it NEVER filters
            candidates and never becomes coordinates. `country_code` above stays
            the hard filter for a country the user actually NAMED.

            This is the deliberate reversal of P0-2 (audit 2026-07-30 §1): the
            anti-hallucination doctrine correctly forbids the model from
            emitting COORDINATES, and had been over-extended to forbid it
            emitting a verifiable HINT — so the pipeline threw away the one
            signal that disambiguates a world-famous landmark, then tried to
            rebuild it in code (exonym tables, inventory tiers, echo rules).
            The model proposes, the code disposes: the echo guard and the
            inventory tier remain the verifiers.
        profile_location_hint: The city/location profile_in last recorded,
            used both as a state-hint text source and to detect an explicit
            city switch that should clear a stale state anchor.
        locale: The client's own locale tag (profile_in.locale, S-G2 native-
            context — e.g. "pt-PT"; NOT profile_in.language, which is triage's
            conversation-language guess and carries only the 2-letter code
            itself, e.g. "pt", never the region) — a SOFT signal: it biases
            Mapbox scoring/localisation and gives the same-country candidate a
            bounded prior. Never a filter. Injected deterministically by
            `inject_profile_geo_context` below (S-G7) — never expected from
            the model itself (it has no reliable way to know the client's UI
            locale).
        language_hint: The conversation language (profile_in.language,
            triage's recognized-language guess, one of the 7 in
            triage.LANGUAGES since P1-2/UX2), injected deterministically like
            `locale`. Used ONLY as a fallback for the Mapbox `language`
            request param when no real locale exists — NEVER for the
            resolver's country prior
            (`_locale_country` stays locale-only: a triage language guess must
            not boost a country, S-G7 pitfall). Why it matters: S-G9 showed
            Mapbox's candidate LIST itself changes with `language` — the bare
            "La Défense" query returns the Puteaux-FR candidates only when a
            language is sent, and without them the resolver can only pick
            among foreign fuzz.
        proximity_lat: GPS latitude bias (profile_in.search_anchor, S-G2/S-G5)
            — a SOFT, band-limited signal (Pelias rule): it never overrides an
            explicit distant destination ("hotel in New York" typed from Paris
            still resolves New York). Injected deterministically by the leaf's
            `inject_profile_geo_context` before_tool_callback — never expected
            from the model itself (it has no real GPS awareness).
        proximity_lon: paired with `proximity_lat`; either alone is ignored.
        areas: For administrative destinations or multiple alternative cities,
            up to three objects with query (full area name), kind (administrative
            or municipality), country (ISO2), evidence (literal customer quote),
            and optional code (department/state code explicitly given). Example:
            78 or 92 in France means Yvelines code 78 and Hauts-de-Seine code 92.
            Never supply coordinates. Omit for an ordinary single-city/POI search.

    Returns a dict — NEVER raises. On success:
        {"ok": True, "latitude", "longitude", "resolved_place",
         "resolved_feature_type", "distance_origin_type", "country_code",
         "profile_delta"}
    On an ambiguous homonym — or on a named zone that arrived with NO anchor at
    all (no city, no metro, no device fix), where the answer would otherwise be
    a function of this container's egress IP — a clarify request (ask ONE
    question, don't search):
        {"ok": False, "error": "geocode_ambiguous", "diagnostics": {"question", "options"}}
    On any guard rejection or geocoder failure, a clean diagnostic:
        {"ok": False, "error": "<reason>", "diagnostics": {...}}
    """
    if areas is not None:
        validated = validate_areas(areas, raw_user_message)
        if validated is None:
            return _fail("invalid_area_request", {"reason": "Area identity needs literal current-message evidence."})
        if requires_area_membership(validated):
            return resolve_areas(validated, get_mapbox_client(), (locale or language_hint or "en")[:2])
        city, country_code = validated[0]["query"], validated[0]["country"]
    guards_fired: list[str] = []
    demoted = demote_generic_city({"city": city, "zone": zone, "metro": metro})
    effective_city: str | None = demoted.get("city")
    effective_zone: str | None = demoted.get("zone")
    effective_metro: str | None = demoted.get("metro")
    if effective_city != city or effective_metro != metro:
        mark_level("WARNING", status_message="generic_location_demoted")
        guards_fired.append("generic_location_demotion")

    # S4 (2026-08-26): the search RADIUS derives from what the user asked for,
    # not from the geocoder's taxonomy. `inject_landmark_radius` tightens the
    # `search_offers` disc to 3 km only when this says "poi"; before this it was
    # whichever tier happened to answer, so the same landmark got a 3 km disc
    # via Search Box and a 20 km one via v6 (`neighborhood` → `city_centroid`).
    # A specific named zone means "around X" whoever resolved it.
    zone_is_specific = bool(effective_zone) and not is_generic_location_token(effective_zone or "")
    zone_origin_type = "poi" if zone_is_specific else "city_centroid"

    # Computed BEFORE the early return below, because the zone-only landmark
    # path now needs both (P0-2 fix 1) — they depend only on the call's own
    # arguments, so hoisting them changes nothing for the paths further down.
    lang = (
        (locale or "").strip().lower()[:2]
        or (language_hint or "").strip().lower()[:2]
        or None
    )
    # GPS proximity (S-G5): a Mapbox "lon,lat" bias string for the API call,
    # and a (lat, lon) tuple for the resolver's own bounded scoring credit —
    # both derived from the SAME two floats, present only when BOTH are given
    # (a lone lat or lon is meaningless and ignored).
    proximity_str: str | None = None
    proximity_tuple: tuple[float, float] | None = None
    if proximity_lat is not None and proximity_lon is not None:
        proximity_str = f"{proximity_lon},{proximity_lat}"
        proximity_tuple = (proximity_lat, proximity_lon)
    # The model's world-knowledge hint, validated to a real ISO2 shape. Kept
    # separate from `country_code` all the way down: one is a soft prior, the
    # other a hard filter, and conflating them would turn a model guess into a
    # candidate filter — exactly what the doctrine forbids.
    guess_iso = _iso2(country_guess)

    if not effective_city and not effective_metro:
        # Pure "near me" (S-G10, D1 follow-up): no geocodable destination
        # anywhere in the request, but the profile carries a device GPS fix
        # (search_anchor → proximity_lat/lon, always code-injected) — resolve
        # to the fix itself instead of failing the turn; before this, a
        # GPS-only request could never search at all. ONLY when no
        # zone/landmark was named either: a stated landmark must never be
        # silently replaced by the user's own location (Gate 3).
        if not effective_zone and proximity_lat is not None and proximity_lon is not None:
            return _ok(
                GeocodeResult(
                    latitude=float(proximity_lat),
                    longitude=float(proximity_lon),
                    place_name="your current location",
                    country_code="",
                    region="",
                ),
                feature_type="gps",
                profile_delta={},
                distance_origin_type="gps",
            )
        # P0-2 fix 1 (audit §1 M2): a NAMED LANDMARK with no city used to die
        # right here, before the Search-Box tier ever ran — the only path that
        # reached tier 2 was `city="champs élysées"` plus zero v6 candidates, so
        # the outcome depended on which field the model happened to put the
        # string in. That is the documented non-determinism (Fabien got Paris,
        # the replay got La Garde).
        #
        # The discriminator is deterministic and already exists: a GENERIC zone
        # word ("the airport", "la gare", "downtown") is not a landmark and must
        # not be looked up — Search Box would happily return some airport on
        # another continent. A specific name ("champs élysées", "gare de lyon")
        # is. `is_generic_location_token` is the same helper `demote_generic_city`
        # uses, and its exact-set membership is what makes "gare" generic while
        # "gare de lyon" is not — precisely the case that was failing.
        #
        # Gate 3 is untouched: this runs AFTER the GPS branch above, so a named
        # landmark still never gets silently replaced by the user's own fix.
        # No `zone_is_landmark` model flag is needed (the audit listed one as a
        # bonus): the code can tell, and a signal the code owns cannot be
        # hallucinated.
        if zone_is_specific:
            # 2026-08-26, found by the post-deploy verification of `fa08813`: with
            # no city, no metro AND no device fix, this lookup has nothing to aim
            # at but the container's egress IP (Mapbox's documented default for
            # `proximity`). Measured from the prod container: "gare de lyon"
            # returns ten Lyon tram stops and the Paris station the user means is
            # NOT in the candidate list — it only appears once the bias already
            # points at Paris. So no re-ranking can recover it (the ranker cannot
            # rank what was never returned) and no honest option list can be built
            # from what came back. The same turn with "à paris" lands 0,5 km from
            # the station, which is what proves the resolver itself is fine.
            #
            # The doubt is therefore real AND undecidable here, so we ask instead
            # of shipping an IP-dependent guess as a fact (product decision,
            # 2026-08-26: "si il y a un doute possible il vaut mieux demander
            # laquelle"). Cheaper too — the question costs zero geocoder calls.
            #
            # Runs AFTER the GPS branch above, so Gate 3 still holds; and when a
            # device fix DOES exist the ranker keeps the case exactly as before.
            if proximity_tuple is None:
                mark_level("WARNING", status_message="geocode_city_needed")
                return _fail(
                    "geocode_ambiguous",
                    {
                        "question": geo_resolver.city_needed_question(
                            effective_zone or "", lang
                        ),
                        "options": [],
                    },
                    guards_fired,
                    # The zone is the whole subject of the question — persist it
                    # so the answering turn resolves "<zone> + <city>" instead of
                    # the bare city (verified broken in prod before this).
                    {"zone": effective_zone} if effective_zone else None,
                )
            landmark_candidates = get_searchbox_client().forward_candidates(
                # No city to append here by definition (this branch is "no city
                # and no metro"), so the landmark goes alone — `_searchbox_query`
                # would return exactly that. This is the one path that stays
                # exposed to Mapbox's IP-biased ranking, which is why it ranks
                # the whole candidate list instead of trusting top-1.
                effective_zone or "",
                # The raw `country_code` param, not `effective_country_code`:
                # the US-ZIP anchor that derives the latter runs further down,
                # after this early return. A bare landmark with no city and a US
                # ZIP is not a real shape, so nothing is lost.
                country=_soft_country(country_code, country_guess, locale),
                language=lang,
                proximity=proximity_str,
            )
            landmark = geo_resolver.rank_landmark(
                landmark_candidates,
                requested_zone=effective_zone or "",
                inventory=get_inventory(),
                proximity=proximity_tuple,
            )
            if landmark is not None and _echoes(
                landmark.place_name, city=None, zone=effective_zone, state_hint=None
            ):
                # Guard #14 — with no city named, `proximity_tuple` (the device
                # fix) is the only anchor available; without one the guard is a
                # no-op here and the ranker above is what carries the case.
                if _poi_anchor_incoherent(landmark, anchor=proximity_tuple):
                    guards_fired.append("poi_anchor_coherence")
                    mark_level("WARNING", status_message="poi_anchor_incoherent")
                else:
                    return _ok(
                        landmark.as_result(),
                        feature_type=landmark.feature_type,
                        profile_delta={},
                        distance_origin_type="poi",
                        zone=effective_zone,
                        guards_fired=guards_fired,
                    )
        return _fail(
            "no_geocodable_location",
            {
                # A specific landmark that simply failed to resolve is NOT a
                # "generic location" — reporting it as one sent readers of this
                # diagnostic looking for a demotion that never happened
                # (`is_generic_location_token("notre dame")` is False).
                "reason": (
                    "landmark_not_resolved" if zone_is_specific
                    else "generic_location_only" if effective_zone else "missing_city"
                ),
                "zone_hint": effective_zone,
            },
            guards_fired,
        )

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
    candidates = get_mapbox_client().geocode_candidates(
        query, country=effective_country_code, language=lang, proximity=proximity_str
    )

    resolution = geo_resolver.resolve(
        candidates,
        inventory=get_inventory(),
        country_hint=effective_country_code,
        region_hint=state_hint,
        # P0-2 fix 3: the model's world-knowledge guess enters here, sharing
        # the locale prior's BOUNDED weight (_W_LOCALE) — a boost among
        # candidates, never a filter, so a wrong guess costs a rank and cannot
        # erase the right answer. A named country stays the hard filter above.
        locale_country=guess_iso or _locale_country(locale),
        proximity=proximity_tuple,
        requested_name=effective_city or effective_metro,
        prefer_municipality=bool(effective_city) and not effective_zone,
        # S-CX2: the clarify question can reach the customer verbatim — ask it
        # in the conversation language (same 2-letter hint Mapbox already got).
        language=lang,
    )

    echo_city = effective_city or effective_metro

    # The turn's geographic anchor for guard #14. An anchor that vetoes another
    # resolution must itself be verified first, so this is deliberately NOT
    # v6's top candidate: by the time tier 2 runs, that candidate is the one the
    # echo guard just REJECTED. Anchoring on it would let v6 fuzzing to another
    # continent ("La Défense, Paris" → Al Ain, AE) veto the correct Search-Box
    # answer — precisely the case P0-2 fixed. So: the device GPS fix, else the
    # best v6 candidate that independently echoes the CITY the user named.
    # No named city (the bare-landmark shape) ⇒ no anchor and no guard; that
    # case belongs to `_searchbox_query`, not to this guard.
    #
    # `city_anchor` is kept SEPARATE from the GPS fix on purpose. It is the
    # coordinate of the city the user themselves named, verified by the echo
    # guard, so `rank_landmark` may lean on it hard. A GPS fix stays on the
    # weak, band-limited `_W_PROXIMITY` — conflating the two would let a device
    # fix in Paris pull a landmark search for Lyon back to Paris, which is the
    # failure the Pelias band rule exists to prevent.
    # ⚠️ The candidate must ALSO carry a real inventory footprint, not just
    # echo the city's name. Echoing alone is the S-G9 micro-homonym trap the
    # resolver's own docstring warns about, and it bit here on the first
    # post-deploy check (2026-08-26): for "gare de lyon" + city "Paris", the
    # ONLY v6 candidate echoing "Paris" was a neighbourhood literally named
    # Paris in ROANNE — 2 hotels nearby, 390 km away. It became "the verified
    # Paris", aimed Search Box at Roanne, and the turn died on a clarify. An
    # anchor that aims a lookup and vetoes its result has to be credible on
    # its own, and `in_inventory_tier` is exactly that test (>= 3 hotels).
    # No credible candidate ⇒ no anchor, and the city falls back to being
    # folded into the query — which is what resolves this case correctly.
    city_anchor: tuple[float, float] | None = None
    city_country: str | None = None
    if echo_city:
        for scored in resolution.scored:
            if not scored.in_inventory_tier:
                continue
            if _echoes(scored.candidate.place_name, city=echo_city, zone=None, state_hint=None):
                city_anchor = (scored.candidate.latitude, scored.candidate.longitude)
                city_country = scored.candidate.country_code
                break
    # A named destination outranks device location. GPS remains the fallback
    # when the destination has no verified city anchor.
    poi_anchor: tuple[float, float] | None = city_anchor or proximity_tuple

    # Tier 1 can also return a landmark homonym in another province. Establish
    # the city anchor before accepting either provider, at most once per call.
    if echo_city and effective_zone and city_anchor is None:
        city_candidate = _city_candidate(
            echo_city,
            country=effective_country_code,
            locale_country=guess_iso or _locale_country(locale),
            language=lang,
        )
        if city_candidate is not None:
            city_anchor = (city_candidate.latitude, city_candidate.longitude)
            city_country = city_candidate.country_code
        poi_anchor = city_anchor or proximity_tuple

    clarify_response: dict | None = None
    if resolution.decision == "clarify":
        mark_level("WARNING", status_message="geocode_ambiguous")
        clarify_response = _fail(
            "geocode_ambiguous",
            {
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
            guards_fired,
            # Same reason as the unanchored gate above: this clarify can also be
            # returned with a zone in hand (line ~758, once tier 2 has missed
            # too), and the answer turn needs it. When there is no zone the
            # early return below carries None, so nothing changes there.
            {"zone": effective_zone} if effective_zone else None,
        )
        # A named zone/landmark can make v6's whole candidate list fuzz (the
        # real place isn't a v6 feature at all — "La Défense" only exists in
        # the Search-Box tier). Don't ask the user to pick among fuzzy
        # homonyms before trying tier 2 below: an echo-validated POI hit IS
        # the answer; the clarify is only surfaced when tier 2 misses too
        # (S-G10 — same fall-through the failed-echo select path already had).
        if not effective_zone:
            return clarify_response

    if resolution.decision == "select" and resolution.chosen is not None:
        chosen = resolution.chosen
        incoherent = bool(effective_zone) and _poi_anchor_incoherent(chosen, anchor=poi_anchor)
        if incoherent:
            guards_fired.append("poi_anchor_coherence")
            mark_level("WARNING", status_message="poi_anchor_incoherent")
        if not incoherent and _echoes(
            chosen.place_name, city=echo_city, zone=effective_zone, state_hint=state_hint
        ):
            profile_delta = _anchor_state(
                city=effective_city,
                raw_user_message=raw_user_message,
                profile_state_context=profile_state_context,
                profile_location_hint=profile_location_hint,
                guards_fired=guards_fired,
            )
            return _ok(
                chosen.as_result(),
                feature_type=chosen.feature_type,
                profile_delta=profile_delta,
                # S4: a named specific zone means "around X" even when it was v6
                # that answered, so the 3 km disc applies here too. Without this
                # the same landmark got 3 km via Search Box and 20 km via v6.
                distance_origin_type=zone_origin_type,
                zone=effective_zone,
                metro=effective_metro,
                guards_fired=guards_fired,
            )
        # The chosen candidate failed the echo sanity check — fall through to the
        # Search-Box tier-2 fallback below if a zone/landmark was named.
        guards_fired.append("geocode_echo_back")

    # Tier 2 (A2-b): v6 gave us nothing acceptable. When the request named a
    # zone/landmark ("La Défense", "Tour Eiffel"), retry ONCE via Search Box,
    # which v6 can't resolve (POI support dropped). Never on a bare-city miss
    # (Search Box is worse for cities and a separate SKU) — EXCEPT when v6
    # returned ZERO candidates (S-G11, "Layover in JFK"): an airport/landmark
    # used AS the destination is a POI, invisible to v6's city feature types,
    # so the zone-only trigger left it unreachable; a bare-city miss that HAS
    # candidates still never reaches Search Box, unchanged.
    #
    # How the city reaches Search Box (2026-08-26). Leaving `proximity` unset
    # does NOT mean "unbiased": Mapbox then biases by our egress IP, which is
    # what resolved "les champs élysées" to a shop in Toulon. So we always give
    # it a bias WE chose when we have one, in this order:
    #   1. `poi_anchor` — the verified named city, otherwise the device fix.
    #      The city has priority over the current device position. A coordinate, so the query stays the BARE
    #      landmark, which is what keeps the clean feature in the list.
    #   2. no coordinate but a city STRING → fold the city into the query
    #      (`_searchbox_query`). Last resort: it does fix the position, but it
    #      also floods the list with businesses named after the landmark and one
    #      of them becomes `resolved_place`, which the customer sees.
    #   3. neither → the bare landmark, IP-biased, and `rank_landmark` is the
    #      only defence. The documented residual.
    # Measured on "les champs élysées": bare query + Paris proximity → the
    # "Champs-Élysées" neighborhood; `"les champs élysées, Paris"` → 10
    # businesses, top one "Onitsuka Tiger Champs Elysées, Paris Flagship".
    # Same 0.1-0.3 km position, very different label.
    searchbox_proximity = (
        f"{poi_anchor[1]},{poi_anchor[0]}" if poi_anchor is not None else None
    )
    if searchbox_proximity is not None:
        searchbox_query = _landmark_query(effective_zone) if effective_zone else effective_city or effective_metro or ""
    else:
        searchbox_query = _searchbox_query(effective_zone, effective_city, effective_metro)
    if not effective_zone and candidates:
        # A bare-city miss that HAS v6 candidates still never reaches Search Box
        # (worse for cities, separate SKU) — unchanged.
        searchbox_query = ""
    if searchbox_query:
        poi_candidates = get_searchbox_client().forward_candidates(
            searchbox_query,
            # A verified destination is stronger than UI language or a model
            # guess. Otherwise a French visitor searching New York can send
            # JFK to Search Box with country=FR after geocoding NYC correctly.
            country=_iso2(effective_country_code) or city_country or _soft_country(
                None, country_guess, locale
            ),
            language=lang,
            proximity=searchbox_proximity,
        )
        poi = geo_resolver.rank_landmark(
            poi_candidates,
            requested_zone=effective_zone or effective_city or effective_metro or "",
            inventory=get_inventory(),
            proximity=proximity_tuple,
            city_anchor=city_anchor,
        )
        if poi is not None and _echoes(
            poi.place_name, city=echo_city, zone=effective_zone, state_hint=state_hint
        ):
            # Guard #14 (`poi_anchor_coherence`): the echo above proved the NAME,
            # this proves the PLACE. Rejecting falls through to the honest
            # outcomes below — never a fabricated coordinate, never a retry.
            if _poi_anchor_incoherent(poi, anchor=poi_anchor):
                guards_fired.append("poi_anchor_coherence")
                mark_level("WARNING", status_message="poi_anchor_incoherent")
            else:
                profile_delta = _anchor_state(
                    city=effective_city,
                    raw_user_message=raw_user_message,
                    profile_state_context=profile_state_context,
                    profile_location_hint=profile_location_hint,
                    guards_fired=guards_fired,
                )
                return _ok(
                    poi.as_result(),
                    feature_type=poi.feature_type,
                    profile_delta=profile_delta,
                    distance_origin_type="poi",
                    zone=effective_zone,
                    metro=effective_metro,
                    guards_fired=guards_fired,
                )

    # Administrative districts can be absent from Search Box while the combined
    # v6 city+district query returns only the parent city. One bounded district
    # lookup recovers that feature, scoped to a verified destination country and
    # coordinate. Never accept a same-name distant district or a business POI.
    if effective_zone and city_anchor is not None and city_country:
        districts = get_mapbox_client().geocode_candidates(
            effective_zone, country=city_country, language=lang,
            proximity=f"{city_anchor[1]},{city_anchor[0]}",
        )
        districts = [c for c in districts if
                     c.feature_type in {"place", "locality", "neighborhood", "district"}
                     and c.country_code == city_country
                     and _echoes(c.place_name, city=echo_city, zone=effective_zone, state_hint=state_hint)
                     and not _poi_anchor_incoherent(c, anchor=city_anchor)]
        district_resolution = geo_resolver.resolve(
            districts, inventory=get_inventory(), country_hint=city_country,
            region_hint=state_hint, locale_country=city_country, proximity=city_anchor,
            requested_name=effective_zone, language=lang,
        )
        district = district_resolution.chosen
        if district_resolution.decision == "select" and district is not None:
            return _ok(
                district.as_result(), feature_type=district.feature_type,
                profile_delta=_anchor_state(
                    city=effective_city, raw_user_message=raw_user_message,
                    profile_state_context=profile_state_context,
                    profile_location_hint=profile_location_hint, guards_fired=guards_fired,
                ),
                distance_origin_type="poi", zone=effective_zone, metro=effective_metro,
                guards_fired=guards_fired,
            )

    # Tier 2 missed too — a pending clarify (homonym near-tie) is the honest
    # outcome now, ahead of the generic diagnostics below.
    if clarify_response is not None:
        return clarify_response

    # Nothing survived: distinguish "no candidate at all" from "resolved to the
    # wrong place" for honest diagnostics (both degrade — never a fabricated coord).
    if not candidates:
        # Named "no_match", not "unavailable": the geocoder DID answer, the
        # query just matched nothing it can see (and the Search-Box fallback
        # above missed too) — the model used to dress "unavailable" up as a
        # service outage for the user (S-G11, "geolocation service unavailable").
        return _fail("geocode_no_match", {"query": query}, guards_fired)
    resolved_place = resolution.chosen.place_name if resolution.chosen is not None else None
    mark_level("WARNING", status_message="geocode_echo_mismatch")
    if "geocode_echo_back" not in guards_fired:
        guards_fired.append("geocode_echo_back")
    return _fail(
        "geocode_echo_mismatch",
        {"query": query, "resolved_place": resolved_place},
        guards_fired,
    )


def _is_blank(value: object) -> bool:
    """True for a missing/empty destination arg — an empty string counts as
    "the model omitted this" exactly like an absent key (P0 #4: the model is
    never trusted to reliably copy a stale value forward on its own)."""
    return value is None or (isinstance(value, str) and not value.strip())


def inject_profile_geo_context(tool: object, args: dict, tool_context: object) -> dict | None:
    """`before_tool_callback` (P0 #4 fix, S-G5) — the deterministic
    profile→tool-args bridge for `geocode_location`, same pattern as
    `equipment_ids.enforce_equipment_filters`: the leaf's own instruction used
    to ask the model to COPY `city`/`state_anchor` into
    `profile_location_hint`/`profile_state_context` itself (the audit's P0 #4
    — "the model stops being a copy machine" is this fix). Precedence:
    - `city`/`zone`/`metro`/`country_code`: a value the model DID extract for
      THIS turn always wins; a blank one is filled from `profile_in` only
      while the destination is unchanged. A new city/country must not inherit
      the previous city's area, metro, or hard country restriction.
      Never rewrites a fresh extraction.
    - `profile_state_context`/`profile_location_hint`: PURE profile lookups by
      definition (an earlier turn's anchor, never something extracted from
      THIS message) — always set here, deterministically, whatever the model
      passed.
    - `proximity_lat`/`proximity_lon`: the GPS soft bias (S-G2's
      `search_anchor`) — likewise always profile-sourced; the model has no
      real GPS awareness to extract from text.
    - `locale` (S-G7): same category as the two above — the client's own
      native-context locale (profile_in.locale), always profile-sourced.
      The leaf's instruction used to ask the model to copy `profile_in.language`
      here instead; that field is triage's conversation-language guess and
      carries only the bare 2-letter code (e.g. "pt"), never a region, so it
      could never actually carry the Lisboa case's locale prior ("pt-PT").
      Fixed by injecting the real field deterministically, same doctrine as
      everything else in this callback.
    A profile with nothing to offer (first turn, no DataPart) leaves `args`
    exactly as the model wrote them."""
    if getattr(tool, "name", "") != "geocode_location":
        return None
    profile_in = read_profile_in(tool_context)

    city, prior_city = args.get("city"), profile_in.get("city")
    city_changed = (
        isinstance(city, str) and bool(city.strip())
        and isinstance(prior_city, str) and bool(prior_city.strip())
        and _echo_fold(city.strip()) != _echo_fold(prior_city.strip())
    )
    country, prior_country = _iso2(args.get("country_code")), _iso2(profile_in.get("country_anchor"))
    destination_changed = city_changed or bool(country and prior_country and country != prior_country)
    # Virtual area extraction is verified against the actual A2A customer text,
    # never the model's raw_user_message argument. Carryover is profile-owned.
    content = getattr(tool_context, "user_content", None)
    message = " ".join(part.text for part in (getattr(content, "parts", None) or [])
                       if isinstance(getattr(part, "text", None), str))
    failed_scope = getattr(tool_context, "state", {}).get(STATE_FAILED)
    if failed_scope:
        return failed_scope
    fresh_areas = args.pop("areas", None)
    envelope = find_datapart(getattr(content, "parts", None)) or {}
    authoritative = (envelope.get("query_params") or {}).get("areas_authoritative") is True
    carried = validate_areas(profile_in.get("search_areas"))
    if carried and any(_echo_fold(area["query"]) == _echo_fold(city or "") for area in carried):
        # Provider display labels ("provincia di Brescia") and the owned query
        # ("Brescia") identify the same carried destination. A copied leaf city
        # cannot narrow the area or one member of a union on a generic follow-up.
        destination_changed = bool(country and prior_country and country != prior_country)
    # A copied prior extraction is carryover, not a new claim requiring the
    # old area name to appear in "cheaper" or "remove the jacuzzi".
    copied = validate_areas(fresh_areas)
    same_identity = bool(copied and carried and
        [{k: a.get(k, "") for k in ("query", "kind", "country", "code")} for a in copied]
        == [{k: a.get(k, "") for k in ("query", "kind", "country", "code")} for a in carried])
    if authoritative or (same_identity and not destination_changed):
        scoped = carried
    elif fresh_areas is not None:
        scoped = validate_areas(fresh_areas, message)
        if scoped is None:
            failed = _fail("invalid_area_request", {"reason": "Area identity needs literal current-message evidence; do not replace the requested areas with their parent city."})
            getattr(tool_context, "state", {})[STATE_FAILED] = failed
            return failed
    else:
        # A new explicit city/zone replaces a previously broad area request.
        fresh_zone = any(
            isinstance(args.get(field), str) and args[field].strip()
            and _echo_fold(args[field]) in _echo_fold(message)
            for field in ("zone", "metro")
        )
        new_place = destination_changed or fresh_zone
        scoped = None if new_place else validate_areas(profile_in.get("search_areas"))
    scoped = preserve_area_boundary(carried, scoped)
    if authoritative and not carried:
        # The concierge interpreted a single ordinary city. A stateless leaf
        # cannot turn that into strict city limits or revive an old destination.
        if profile_in.get("city"):
            args["city"] = profile_in["city"]
            args["country_code"] = profile_in.get("country_anchor")
            for field in ("zone", "metro"):
                value = args.get(field)
                if not isinstance(value, str) or _echo_fold(value) not in _echo_fold(message):
                    args.pop(field, None)
            destination_changed = False  # Owned profile already cleared old scope.
    if scoped and not requires_area_membership(scoped):
        args["city"], args["country_code"] = scoped[0]["query"], scoped[0]["country"]
        destination_changed = (_echo_fold(args["city"]) != _echo_fold(prior_city or "")
                               or args["country_code"] != prior_country)
        if destination_changed:
            for field in ("zone", "metro"):
                value = args.get(field)
                if not isinstance(value, str) or _echo_fold(value) not in _echo_fold(message):
                    args.pop(field, None)
        scoped = None
    if scoped:
        resolved = resolve_areas(scoped, get_mapbox_client(), str(profile_in.get("locale") or profile_in.get("language") or "en")[:2])
        if not resolved.get("ok"):
            getattr(tool_context, "state", {})[STATE_FAILED] = resolved
        return resolved

    if _is_blank(args.get("city")) and profile_in.get("city"):
        args["city"] = profile_in["city"]
    if destination_changed:
        # The model can copy an old area into its fresh args too. A repeated
        # name belongs to the new destination only when the actual current
        # customer message says it; do not trust raw_user_message supplied by
        # the model as proof of that. Fresh, different areas remain untouched.
        content = getattr(tool_context, "user_content", None)
        message = " ".join(
            part.text for part in (getattr(content, "parts", None) or [])
            if isinstance(getattr(part, "text", None), str)
        )
        for field in ("zone", "metro"):
            value, prior = args.get(field), profile_in.get(field)
            if (isinstance(value, str) and value.strip() and isinstance(prior, str)
                    and _echo_fold(value) == _echo_fold(prior)
                    and _echo_fold(value) not in _echo_fold(message)):
                args.pop(field, None)
    if not destination_changed:
        if _is_blank(args.get("zone")) and profile_in.get("zone"):
            args["zone"] = profile_in["zone"]
        if _is_blank(args.get("metro")) and profile_in.get("metro"):
            args["metro"] = profile_in["metro"]
        if _is_blank(args.get("country_code")) and profile_in.get("country_anchor"):
            args["country_code"] = profile_in["country_anchor"]

    if profile_in.get("state_anchor"):
        args["profile_state_context"] = profile_in["state_anchor"]
    if profile_in.get("city"):
        args["profile_location_hint"] = profile_in["city"]
    if profile_in.get("locale"):
        args["locale"] = profile_in["locale"]
    if profile_in.get("language"):
        args["language_hint"] = profile_in["language"]

    anchor = profile_in.get("search_anchor")
    if isinstance(anchor, dict):
        lat, lon = anchor.get("lat"), anchor.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            args["proximity_lat"] = float(lat)
            args["proximity_lon"] = float(lon)
    return None
