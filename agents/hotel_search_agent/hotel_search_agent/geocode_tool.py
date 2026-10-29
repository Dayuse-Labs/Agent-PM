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

QA14707 (Q07, decision DQ1): the tool the model sees, `geocode_location`, takes
a `GeoIntent` (`b2c_common.geo_intent`) instead of free `city`/`zone`/
`raw_user_message` strings. It is a thin wrapper: it checks the model's claims
against the leaf's real input text, maps the object onto the flat arguments of
`geocode_core` (the pipeline described above), fills the blanks from
`profile_in` as before, and calls it. The model understands; the code owns the
values. Tests and `scripts/probe_geo_landmarks.py` call `geocode_core` directly.
"""
from __future__ import annotations

import difflib
import logging
import os
import unicodedata
from typing import Any, get_args

from b2c_common.clarification import MAX_OPTIONS, Clarification, ClarificationOption
from b2c_common.geo_intent import CityRef, GeoIntent, Place, PlaceKind
from b2c_common.observability import mark_level
from google.adk.tools.tool_context import ToolContext
from pydantic import ValidationError

from hotel_search_agent import geo_resolver
from hotel_search_agent.fr_departments import department
from hotel_search_agent.geo_guards import (
    US_STATE_ABBREV_TO_NAME,
    US_STATE_NAME_TO_CANONICAL,
    extract_state_hint_from_text,
    anchor_state_context,
    demote_generic_city,
    geocode_echo_matches,
    is_generic_location_token,
    resolve_state_hint,
)
from hotel_search_agent.inventory import get_inventory, haversine_km
from hotel_search_agent.mapbox_client import (
    ADDRESS_TYPES,
    AREA_TYPES,
    POSTCODE_TYPES,
    GeocodeCandidate,
    GeocodeResult,
    MapboxClient,
)
from hotel_search_agent.response_bridge import (
    read_input_text,
    read_profile_in,
    read_query_params,
    read_user_words,
)
from hotel_search_agent.searchbox_client import SearchBoxClient

# Same stdout metrics logger as the other leaf modules. GDPR: counts and closed
# enumerations only, never a place name or a word of the message.
_metrics_logger = logging.getLogger("dayuse.metrics")

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


def _mapbox_language(locale: str | None, language_hint: str | None) -> str | None:
    """The Mapbox `language` param: the client's locale, else the conversation
    language (see `geocode_core`'s `language_hint`)."""
    return (
        (locale or "").strip().lower()[:2]
        or (language_hint or "").strip().lower()[:2]
        or None
    )


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
    with `country=effective_country_code`, which was only populated when the
    user NAMED a country or typed a US ZIP (the regex US-ZIP anchor, removed
    since by QA14707 Q10) — so in the common case it was an
    unscoped, worldwide, limit=1 lookup. That is what let a business called
    "Champs Elysées" in another hemisphere win: the echo guard validates the
    NAME, so a perfect name match in the wrong country sails through it (M4).
    A country scope is the only signal that separates those two."""
    return named or _iso2(guess) or _locale_country(locale)


def _market_country(locale: str | None, entry_market_country: str | None = None) -> str | None:
    """The market's country, the last tie-break of a postcode (DQ8): the
    market the request came from (`profile_in.entry_market_country`, QA14707
    Q16 — the widget's market, set by the concierge), else the region of the
    client's locale tag ("en-US" -> "US", "pt-PT" -> "PT"), else the language
    prior above. A bare "en" names no country — which is what the en/USD
    market sends, hence the first source. Structured fields only, never a
    word; a malformed code is ignored."""
    parts = (locale or "").replace("_", "-").split("-")
    region = _iso2(parts[1]) if len(parts) > 1 else None
    return _iso2(entry_market_country) or region or _locale_country(locale)


def _postcode_match(
    candidates: list[GeocodeCandidate],
    postal_code: str,
    *,
    city: str | None,
    guess: str | None,
    market: str | None,
) -> GeocodeCandidate | None:
    """The candidate a postcode the user wrote designates, or None (DQ8).

    Only a candidate whose `context.postcode` equals the written code is
    kept: an equality of structured fields, so a geocoder fuzz to another
    postcode (« 2 Rue Poissonnière, 75002 ») is refused outright. The same
    code exists in several countries (75009: Paris and Celina, Texas), so
    among those left: one in the city the user named, if any is, then the
    country the model guessed, then the market's country, then Mapbox's own
    order. The guess and the market only break a tie, they never filter: a
    country the user NAMED is the one hard filter, applied by Mapbox itself.

    The named city goes first because it is the user's own word, stronger
    than both a guess and a market (« 75009 Paris » on a US market is Paris)."""
    wanted = _comparable(postal_code)
    same = [c for c in candidates if wanted and _comparable(c.postcode) == wanted]
    if city:
        in_city = [c for c in same if _comparable(c.place) == _comparable(city)]
        same = in_city or same
    if not same:
        return None
    return min(
        same,
        key=lambda c: (c.country_code != guess, c.country_code != market, c.rank),
    )


def _with_postcode(zone: str, postal_code: str) -> str:
    """« 2 Boulevard Poissonnière » + « 75009 » -> one address query; the code
    is not appended twice when the zone already holds it."""
    if f" {_comparable(postal_code)} " in f" {_comparable(zone)} ":
        return zone
    return f"{zone} {postal_code}"


def _street_match(
    candidates: list[GeocodeCandidate],
    zone: str,
    *,
    city: str | None,
    state_hint: str | None = None,
    region_chosen: str | None = None,
) -> GeocodeCandidate | None:
    """The street or address a zone with no postcode designates, or None
    (QA14707 Q20). Mapbox's first candidate that passes, in its own order.

    With a city, the candidate must lie in it: its `context.place` equals the
    city. A street carries no `match_code`, so that equality is its only test.
    With no city, the zone's own text must have carried the place or the
    postcode (`match_code.place` or `.postcode` is "matched": « 2 Boulevard
    Poissonnière, 75009 Paris »), which no street can show, so a bare street
    name is never taken in some other country. Either way a "low" match
    (Mapbox matched the city, not the street) is refused, and the name must
    echo the zone, as on every other path. Structured fields only.

    Q21: the US state of the turn holds here as on the generic path. A state
    named, anchored or read in the message (`state_hint`) must echo in the
    candidate's name, and the region of a picked homonym option
    (`region_chosen`, Mapbox's own `context.region`) must equal the
    candidate's. A candidate that fails either is skipped; when none is left,
    the turn falls through to the generic lookup, which applies the state."""
    for c in candidates:
        if c.match_confidence == "low":
            continue
        if city:
            if _comparable(c.place) != _comparable(city):
                continue
        elif "matched" not in (c.match_place, c.match_postcode):
            continue
        if region_chosen and _comparable(c.region) != _comparable(region_chosen):
            continue
        if _echoes(c.place_name, city=None, zone=zone, state_hint=state_hint):
            return c
    return None


def _echoes(place_name: str, *, city: str | None, zone: str | None, state_hint: str | None) -> bool:
    return geocode_echo_matches(place_name, city=city, zone=zone, state_hint=state_hint)


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
#: city coordinate `_city_coordinate` introduces below.
_POI_ANCHOR_MAX_KM = 40.0

#: Mapbox v6 types below a city: a district or a borough, never a whole city.
_DISTRICT_FEATURE_TYPES = frozenset({"locality", "neighborhood"})

#: `GeoIntent` kinds of a place that is an administrative AREA, not a spot: a
#: French département (« le 06 » -> Alpes-Maritimes, the LLM's reading), a
#: region (« Puglia »). The kind is the leaf model's understanding; the code
#: only checks, against Mapbox, that such an area exists and where it is.
_AREA_KINDS = frozenset({"admin_district", "region"})
#: The Mapbox feature types an area resolves to (`AREA_TYPES`).
_AREA_FEATURE_TYPES = frozenset({"region", "district"})


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


#: `GeoIntent` kinds of a place that is an AREA, administrative or not: Search
#: Box may answer one with a `poi`, which must then be the area itself.
_AREA_LIKE_KINDS = frozenset({*_AREA_KINDS, "neighborhood"})


def _business_named_after_the_area(
    poi: GeocodeCandidate, *, zone_kind: str | None, names: tuple[str, ...]
) -> bool:
    """Is this Search-Box poi a business that only borrows the area's name?

    Prod 2026-10-15/28, area places that came back as a poi: « long island » ->
    The Long Island Bar (Brooklyn, a 2 km ring), « metro Detroit » ->
    Metropolitan Detroit Area Hospital Services, « centro » -> Centro Lampo Roma,
    « Bergen County » -> Bergen County Islamic Center. The echo guard passes them
    all: their name CONTAINS the area's. The area itself keeps to its own words
    (« Châtelet », « Lago como » for Lago di Como): a word of the poi's name that
    is in none of `names` (the area, the city) makes it a business.

    Landmarks, stations, airports and addresses are pois by nature: never here."""
    if zone_kind not in _AREA_LIKE_KINDS or poi.feature_type != "poi":
        return False
    requested = {word for name in names for word in _comparable(name).split()}
    return bool(set(_comparable(poi.name or "").split()) - requested)


def _mark_business_named_after_the_area(guards_fired: list[str]) -> None:
    """The echo guard's veto: the answer does not name the requested area."""
    mark_level("WARNING", status_message="area_resolved_to_a_business")
    if "geocode_echo_back" not in guards_fired:
        guards_fired.append("geocode_echo_back")


#: `_district_of_namesakes` (2026-10-29): at least this many places named
#: after the district, all within this distance of their median point.
_DISTRICT_MIN_NAMESAKES = 3
_DISTRICT_SPREAD_KM = 2.0


def _district_of_namesakes(
    candidates: list[GeocodeCandidate],
    *,
    zone_kind: str | None,
    names: tuple[str, ...],
    anchor: tuple[float, float] | None,
    city: str | None,
) -> GeocodeCandidate | None:
    """A neighbourhood Mapbox does not know as such, located by the places
    named after it — or None.

    Prod session 4919ffbc (2026-10-28): « Ostia lido », a seaside district of
    Rome 25 km from its centre. Neither v6 nor Search Box has a feature for
    it; Search Box returns ten businesses called « … Ostia Lido », each one
    rightly refused as a business (`_business_named_after_the_area`), and the
    search ran on the centre of Rome four times. Those businesses stand
    together, within a few hundred metres: where they are IS the district.

    Facts only: the candidates whose name holds every word of one of the
    district's names (`_comparable`), within `_POI_ANCHOR_MAX_KM` of the
    city's anchor when there is one; their median point; at least
    `_DISTRICT_MIN_NAMESAKES` of them within `_DISTRICT_SPREAD_KM` of it, and
    most of the namesakes. Scattered namesakes (a region, a chain) are no
    district. A neighbourhood only (`zone_kind`), the kind the model gives
    such a place; a landmark or an area keeps its own path."""
    if zone_kind != "neighborhood":
        return None
    wanted = [set(_comparable(n).split()) for n in names if _comparable(n)]
    if not wanted:
        return None
    namesakes = [
        c for c in candidates
        if any(words <= set(_comparable(c.name).split()) for words in wanted)
        and (
            anchor is None
            or haversine_km(anchor[0], anchor[1], c.latitude, c.longitude) <= _POI_ANCHOR_MAX_KM
        )
    ]
    if len(namesakes) < _DISTRICT_MIN_NAMESAKES:
        return None
    lats = sorted(c.latitude for c in namesakes)
    lons = sorted(c.longitude for c in namesakes)
    mid_lat, mid_lon = lats[len(lats) // 2], lons[len(lons) // 2]
    close = [
        c for c in namesakes
        if haversine_km(mid_lat, mid_lon, c.latitude, c.longitude) <= _DISTRICT_SPREAD_KM
    ]
    if len(close) < _DISTRICT_MIN_NAMESAKES or 2 * len(close) <= len(namesakes):
        return None
    label = names[0]
    _metrics_logger.info(
        "dayuse_metric=district_of_namesakes agent=b2c_hotel_search namesakes=%d close=%d",
        len(namesakes), len(close),
    )
    return GeocodeCandidate(
        latitude=round(sum(c.latitude for c in close) / len(close), 6),
        longitude=round(sum(c.longitude for c in close) / len(close), 6),
        name=label,
        place_name=f"{label}, {city}" if city else label,
        place_formatted=city or "",
        feature_type="neighborhood",
        country_code=close[0].country_code,
        region=close[0].region,
        bbox=None,
        rank=0,
    )


def _city_coordinate(
    city: str,
    *,
    country: str | None,
    locale_country: str | None,
    language: str | None,
    scope: str | None = None,
) -> tuple[float, float] | None:
    """The coordinate of a city the user NAMED, geocoded on purpose.

    2026-08-26, found while auditing why "aéroport de nice" resolved to a
    shuttle company on the Promenade des Anglais, 6 km from the airport, while
    every Paris landmark resolved cleanly. The `city_anchor` loop below is
    SCAVENGING: it only yields a coordinate when one of the v6 candidates for
    THIS turn's combined query ("aéroport de nice, Nice") happens to echo the
    city AND carry real inventory. When none does, the city is demoted to a
    query STRING (`_searchbox_query`), which buys the position and loses the
    label — and it loses more than the label. Measured:
      `"aéroport de nice, Nice"`  → 10 businesses, no airport (winner: a
                                    sandwich shop AT the airport)
      `"champs élysées, Paris"`   → 10 businesses, no avenue (winner: a
                                    competitor HOTEL, 1,2 km off)
    The clean feature is not out-ranked, it is ABSENT from the list, so no
    ranker can recover it. Paris only ever looked safe because its turns take
    the anchored path; nothing in the code favours it.

    A city NAME with no coordinate is a gap we can just close: geocoding the
    bare city is the same v6 operation this tool already performs for a city
    search, and it hands back the very `proximity` that lets the query stay
    bare. Measured on the failing case: Nice → (43.7101, 7.2618), after which
    Search Box does return "Aéroport de Nice, 06200 Nice" and the exact-name
    bonus wins it outright (7.57, against 4.67 for the sandwich shop).

    `in_inventory_tier` stays the credibility test, for exactly the reason the
    scavenging loop has it (S-G9): the bare-city lookup for "Paris" also
    returns the neighbourhood literally named Paris in ROANNE, and an anchor
    that aims a lookup and vetoes its result must be credible on its own.
    Verified on this path: Paris proper (783 hotels) passes, Roanne (2) does
    not.

    `scope` (2026-10-27): the country the request says the city is in, when
    the user did not name one (`country`, the hard filter). It scopes the
    lookup first, for the IP-bias reason `geocode_core` gives; the lookup
    runs once more without it when the scoped one yields nothing credible."""

    def lookup(restrict: str | None) -> tuple[float, float] | None:
        candidates = get_mapbox_client().geocode_candidates(
            city, country=restrict, language=language, proximity=None
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
        for scored in resolution.scored:
            if not scored.in_inventory_tier:
                continue
            if _echoes(scored.candidate.place_name, city=city, zone=None, state_hint=None):
                return (scored.candidate.latitude, scored.candidate.longitude)
        return None

    scoped = country or scope
    found = lookup(scoped)
    if found is None and scoped and not country:
        found = lookup(None)
    return found


def _anchor_state(
    *,
    city: str | None,
    raw_user_message: str,
    profile_state_context: str | None,
    profile_location_hint: str | None,
    guards_fired: list[str],
    resolved: GeocodeCandidate | None = None,
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
    # 2026-10-29 (prod session 12665ef3, « 53088 » then « try a nearby
    # area »): the US state of the place the geocoder resolved is anchored
    # with it, so the next turn, which carries only the city's NAME, looks it
    # up in that state. Stockbridge, Wisconsin came back as Stockbridge,
    # Georgia — the homonym with hotels around it. A state named this turn
    # stays first (`anchor_state_context` above).
    state = _us_state_code(resolved)
    if state and extract_state_hint_from_text(city, raw_user_message) is None:
        if state != (str(anchored).upper() if anchored else None):
            delta["last_state_context"] = state
        anchored = state
    if anchored or "last_state_context" in delta:
        guards_fired.append("state_anchoring")
    return delta


def _us_state_code(candidate: GeocodeCandidate | None) -> str | None:
    """The 2-letter code of a US candidate's state, from Mapbox's own
    `context.region` name (« Wisconsin » -> « WI »), else None."""
    if candidate is None or candidate.country_code != "US":
        return None
    name = US_STATE_NAME_TO_CANONICAL.get((candidate.region or "").strip().lower())
    if not name:
        return None
    return next((abbr.upper() for abbr, full in US_STATE_ABBREV_TO_NAME.items() if full == name), None)


def _city_point(chosen: GeocodeCandidate) -> GeocodeResult:
    """The point a search over a whole city starts from: the geocoder's,
    unless the city's hotels clearly sit elsewhere (2026-10-29,
    `SnapshotInventory.dense_centre`: New York's point is City Hall, its
    hotels are in Midtown). A city (`place`) only, never a district, an area
    or a spot the user named — those are searched around themselves."""
    result = chosen.as_result()
    if chosen.feature_type != "place":
        return result
    centre = getattr(get_inventory(), "dense_centre", None)
    point = centre(chosen.latitude, chosen.longitude) if callable(centre) else None
    if not point:
        return result
    _metrics_logger.info("dayuse_metric=city_centre agent=b2c_hotel_search moved=1")
    return GeocodeResult(
        latitude=point[0], longitude=point[1], place_name=result.place_name,
        country_code=result.country_code, region=result.region,
    )


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


def _names(*names: str | None) -> tuple[str, ...]:
    """The distinct non-empty names, in order (a destination and its aliases)."""
    return tuple(dict.fromkeys(n.strip() for n in names if n and n.strip()))


def _area_match(
    area: str,
    names: tuple[str, ...],
    *,
    scope: str | None,
    hard: bool,
    language: str | None,
    proximity: str | None,
    exact: str | None = None,
) -> GeocodeCandidate | None:
    """The administrative area the request names, as Mapbox knows it, or None.

    One `region,district` lookup scoped to the request's country, Mapbox's
    own order, and the first area feature whose name echoes one of `names`.
    The country is a scope, never a filter, unless the user named it (`hard`):
    when the scoped lookup holds no such area, the lookup runs once more
    without it.

    `exact` (2026-10-28): the area's name from reference data (a French
    département, `fr_departments`). Only an area of exactly that name is
    taken: « Val-de-Marne » echoes « Marne » by its longest word, and the
    département table says which one the user's number is."""
    mapbox = get_mapbox_client()

    def first(candidates: list[GeocodeCandidate]) -> GeocodeCandidate | None:
        if exact:
            return next(
                (
                    c for c in candidates
                    if c.feature_type in _AREA_FEATURE_TYPES and _comparable(c.name) == _comparable(exact)
                ),
                None,
            )
        for c in candidates:
            if c.feature_type in _AREA_FEATURE_TYPES and any(
                _echoes(c.place_name, city=None, zone=n, state_hint=None) for n in names
            ):
                return c
        return None

    hit = first(mapbox.geocode_candidates(
        area, country=scope, language=language, proximity=proximity, types=AREA_TYPES
    ))
    if hit is None and scope and not hard:
        hit = first(mapbox.geocode_candidates(
            area, country=None, language=language, proximity=proximity, types=AREA_TYPES
        ))
    return hit


def _unresolved(subject: str, language: str | None, diagnostics: dict, guards_fired: list[str]) -> dict:
    """The honest end of a lookup that found nothing the user named: a
    question by template (`Clarification` kind `unresolved`), never the
    "search unavailable" line. Same channel as the other place questions
    (`error` = `geocode_ambiguous`), so the leaf asks instead of searching and
    the concierge renders it without the synthesis."""
    mark_level("WARNING", status_message="geocode_unresolved")
    return _fail(
        "geocode_ambiguous",
        {
            "question": geo_resolver.unresolved_question(subject, language),
            "options": [],
            "reason": "unresolved",
            **diagnostics,
        },
        guards_fired,
        None,
        Clarification(kind="unresolved", subject=subject),
    )


def _option_label(candidate: GeocodeCandidate) -> str:
    """How a homonym option reads in the question — the very formula
    `geo_resolver._clarify_question` uses for each label, so a consumer that
    renders the options says exactly what the leaf's own question says."""
    context = candidate.place_formatted or candidate.country_code or ""
    return f"{candidate.name} ({context})" if context else candidate.name


def _homonym_clarification(
    subject: str, candidates: list[GeocodeCandidate]
) -> Clarification | None:
    """QA14707 / DQ5: the homonym question as data, its options taken ONLY
    from the candidates the resolver kept (`Resolution.options`: same
    inventory tier as the winner, a genuinely different place). Nothing here
    adds, renames or reorders a place. A candidate with no name is left out:
    it has no city to answer with, and the text question shows it as a bare
    context nobody can pick. A question left with nothing to pick carries no
    object (the text question still goes out)."""
    options = []
    # The resolver already caps a question at 3 options; the slice only keeps
    # the contract bound from ever raising in a tool that never raises.
    for c in candidates[:MAX_OPTIONS]:
        if not c.name:
            continue
        options.append(
            ClarificationOption(
                label=_option_label(c),
                city=c.name,
                region=c.region,
                country_code=_iso2(c.country_code),
            )
        )
    if not subject or not options:
        return None
    return Clarification(kind="homonym", subject=subject, options=options)


def _fail(
    error: str,
    diagnostics: dict,
    guards_fired: list[str] | None = None,
    profile_delta: dict | None = None,
    clarification: Clarification | None = None,
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
    # QA14707: a clarify also carries its question as data (`Clarification`),
    # which `response_bridge` relays to the concierge in the DataPart. The
    # `diagnostics.question` text is unchanged, so a concierge that ignores the
    # object keeps working.
    if clarification is not None:
        payload["clarification"] = clarification.model_dump(mode="json")
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
    zone_kind: str | None = None,
) -> dict:
    # S-G5: zone/metro were accepted by this tool and validated by the echo
    # guard, but never reached the profile before now (audit gap — "a zone is
    # lost across turns"). Only-when-present: no zone/metro this turn is
    # carryover at the concierge (S-G1), never a clear.
    delta = dict(profile_delta)
    if zone:
        delta["zone"] = zone
        if zone_kind:
            # 2026-10-28: what the zone is travels with it, so a follow-up turn
            # looks the centre of a city up as one (`_fill_place_from_profile`).
            delta["zone_kind"] = zone_kind
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


def geocode_core(
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
    region_named: str | None = None,
    postal_code: str | None = None,
    zone_kind: str | None = None,
    region_chosen: str | None = None,
    market_country: str | None = None,
    aliases: tuple[str, ...] = (),
    area_exact: str | None = None,
    area_seat: str | None = None,
    zone_aliases: tuple[str, ...] = (),
) -> dict:
    """Resolve a destination to coordinates for `search_offers`, guarded — the
    deterministic pipeline behind the `geocode_location` tool.

    QA14707 (Q07): the model no longer calls this directly and never sees this
    docstring. `geocode_location` maps the model's `GeoIntent` onto these flat
    arguments (checked against the message, blanks filled from `profile_in`)
    and calls this; tests and the landmark probe call it with them directly.
    Every argument keeps a default: an absent one is a legitimate shape.

    Args:
        city: The destination city (may be a generic word like "airport" —
            demoted to a zone hint, never geocoded literally). From the
            `GeoIntent`: a `city` place, else the place's own city, else the
            city the user named.

            Defaults to "", deliberately. It used to have no default, so ADK
            declared it mandatory and rejected the whole tool call with "the
            following mandatory input parameters are not present: city"
            whenever the model omitted the key — which it does precisely when
            the user named a landmark and no city. 14 such dead turns in the
            traces between 2026-08-15 and 08-26 (champs élysées, louvre, gare
            de lyon, eiffel tower, la défense, buckingham palace). An absent
            `city` is a legitimate shape, so it degrades to the landmark path
            instead of killing the turn. The tool keeps that property
            (`geocode_location`: every parameter has a default).
        zone: A sub-city area/landmark, if any. A landmark/POI here ("La Défense",
            "Tour Eiffel") is what triggers the Search-Box tier-2 fallback when
            v6 can't resolve it.
        metro: A metro-area name, if distinct from city.
        country_code: A trusted ISO-3166-1 alpha-2 country to scope the
            geocode to, if already known. When omitted, nothing is forced: a
            postcode's country follows DQ8 (`_postcode_match`), never a locale→
            country guess. A named country is a HARD filter on the candidates,
            never a boost.
        raw_user_message: The user's own words this turn — feeds state-hint
            extraction ("Milford ct") and the state anchor. The tool reads it
            from the invocation (`response_bridge.read_user_words`); the model
            no longer copies it.
        profile_state_context: The US state anchored on an earlier turn
            (from profile_in), if any.
        country_guess: The ISO-3166-1 alpha-2 country this place is
            world-famously in, from the model's own world knowledge, when it is
            confident ("champs élysées" -> FR, "times square" -> US) — the
            `GeoIntent`'s `places[].country` or `city.country`, normalized by
            `_iso2` before it gets here. A SOFT
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
        region_named: A US state the user NAMED (`GeoIntent.region_named`,
            "Milford ct" -> "CT"). It is the most explicit tier of
            `resolve_state_hint` (an extracted token, so even the codes the
            free-text tier must skip, "OR"/"ME"/"IN", are safe), and it is
            ignored whenever a country other than the US is in play: "WA" is
            Western Australia as well as Washington.
        postal_code: A postcode the user wrote (`GeoIntent` `places[].postal_code`,
            checked against the message), QA14707 Q08. It is resolved by the
            geocoder before anything else, under DQ8's country rule
            (`_postcode_match`): `country_code` is the only hard filter, then
            `context.postcode` equality, then the named city, the guess and the
            market break ties. An address or a street (`zone_kind`) is looked up
            with its postcode and searched around; a postcode alone is searched
            around its own centroid; with any other zone, the postcode's city
            (`context.place`) is the city the zone is searched in — so a
            postcode is enough to never ask which city.
        zone_kind: The `GeoIntent` kind of the place `zone` came from
            ("address", "street", "station", ...), or None. An address or a
            street with no postcode is first looked up as one, in the city when
            there is one (QA14707 Q20, `_street_match`); with nothing designated,
            the zone is searched as any other.
        region_chosen: The region of the homonym option the user picked by
            its number (QA14707 Q14, `profile_in.region_anchor`, filled by
            `_fill_place_from_profile`). It narrows the candidates Mapbox
            returned to those whose `context.region` is that region — a
            structured equality, applied only when it keeps at least one. A
            state in play this turn wins: the narrowing keeps only candidates
            that state's echo accepts. Never a query term, never a
            coordinate: « Springfield » option 2 is the Missouri candidate.
            While it is set, the turn's state is not a query term either
            (Q21, H3 RC6: « Manhattan » picked by « New York » was looked up
            as « Manhattan, New York » and resolved New York City); the state
            still steers the resolver and the echo. The street branch keeps
            only a candidate of this region (Q21).
        market_country: The market the request came from (QA14707 Q16,
            `profile_in.entry_market_country`, read by `geocode_location`).
            The market tie-break of a postcode (`_market_country`), and the
            soft scope of a metro written alone (2026-10-28): it
            comes after the named city and the guess, and is never a filter.
        aliases: Other names of the destination the request carried — the
            user's own word when the city is looked up by its canonical name,
            and the reverse (`GeoIntent` `mention` / `canonical`). The echo
            guard accepts a candidate that echoes any of them: asked
            « Malines » (canonical « Mechelen »), Mapbox answers in the
            conversation's language, « Malines, province d'Anvers », which is
            the user's word, not the query's (prod 2026-10-27). Names the
            request itself carried, never a translation table.
        area_exact: The name of the administrative area `zone` is, from
            reference data (a French département read from its number,
            `fr_departments`): only an area of exactly this name is taken.
        area_seat: That area's prefecture, searched around when Mapbox's
            administrative layer does not know the area.
        zone_aliases: The other names the request gave the zone (the user's
            own word next to the canonical name: « UNESCO » for « UNESCO
            Headquarters »). A landmark found by Search Box may echo either.

    Returns a dict — NEVER raises. On success:
        {"ok": True, "latitude", "longitude", "resolved_place",
         "resolved_feature_type", "distance_origin_type", "country_code",
         "profile_delta"}
    On an ambiguous homonym — or on a named zone that arrived with NO anchor at
    all (no city, no metro, no device fix), where the answer would otherwise be
    a function of this container's egress IP — a clarify request (ask ONE
    question, don't search):
        {"ok": False, "error": "geocode_ambiguous", "diagnostics": {"question", "options"},
         "clarification": <b2c_common.clarification.Clarification, as a dict>}
    On any guard rejection or geocoder failure, a clean diagnostic:
        {"ok": False, "error": "<reason>", "diagnostics": {...}}
    """
    guards_fired: list[str] = []
    demoted = demote_generic_city({"city": city, "zone": zone, "metro": metro})
    effective_city: str | None = demoted.get("city")
    effective_zone: str | None = demoted.get("zone")
    effective_metro: str | None = demoted.get("metro")
    if effective_city != city or effective_metro != metro:
        mark_level("WARNING", status_message="generic_location_demoted")
        guards_fired.append("generic_location_demotion")
    # Prod session 1eb2430a (2026-10-27), « Dans toute Ile de France autour de
    # paris »: a region named with a city in it was looked up as a landmark of
    # that city (« Île-de-France, Paris » → « Parcs, Romainville »), searched on
    # a 5 km ring. A region is wider than the city: the city is the search. The
    # region stays a state hint (« Springfield », « Illinois »). `admin_district`
    # is left alone: an arrondissement or a borough may arrive under that kind.
    if zone_kind == "region" and effective_zone and (effective_city or effective_metro):
        region_named = region_named or effective_zone
        effective_zone = zone_kind = None
    # 2026-10-28 (prod session c2f47e81, « Di pomeriggio e in centro », Rome):
    # the centre of a city is measured from the city itself. Looked up as a
    # place, « centro di Roma » came back as « Centro Lampo Roma », a business
    # 6 km out, and the search ran around it. The model says what the place is
    # (`city_centre`); the code searches around the city's own point, on the
    # tight distance-sorted ring of a named spot (origin "poi").
    centre_zone: str | None = None
    if zone_kind == "city_centre" and (effective_city or effective_metro):
        centre_zone, effective_zone, zone_kind = effective_zone, None, None

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
    lang = _mapbox_language(locale, language_hint)
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

    # QA14707 (Q08, DQ8): a postcode the user wrote is resolved first, from the
    # geocoder's own fields. Trace C, « près du 2 boulevard Poissonnière 75009 »:
    # the code was thrown away and the user was asked which city.
    postal = (postal_code or "").strip()
    if postal:
        market = _market_country(locale, market_country)
        mapbox = get_mapbox_client()
        if effective_zone and zone_kind in ("address", "street"):
            address = _postcode_match(
                mapbox.geocode_candidates(
                    _with_postcode(effective_zone, postal),
                    country=country_code,
                    language=lang,
                    proximity=proximity_str,
                    types=ADDRESS_TYPES,
                ),
                postal,
                city=effective_city,
                guess=guess_iso,
                market=market,
            )
            # Mapbox grades an address match itself: a "low" one matched the
            # postcode, not the street. The echo guard checks the name, as on
            # every other path.
            if (
                address is not None
                and address.match_confidence != "low"
                and _echoes(address.place_name, city=None, zone=effective_zone, state_hint=None)
            ):
                return _ok(
                    address.as_result(),
                    feature_type=address.feature_type,
                    profile_delta=_anchor_state(
                        city=address.place or effective_city,
                        raw_user_message=raw_user_message,
                        profile_state_context=profile_state_context,
                        profile_location_hint=profile_location_hint,
                        guards_fired=guards_fired,
                        resolved=address,
                    ),
                    distance_origin_type="poi",
                    # Mapbox's own name of the address, without its postcode:
                    # the zone carried to the next turn never holds a bare code.
                    zone=address.name or effective_zone,
                    metro=effective_metro,
                    guards_fired=guards_fired,
                )
        area = _postcode_match(
            mapbox.geocode_candidates(
                " ".join(part for part in (postal, effective_city) if part),
                country=country_code,
                language=lang,
                proximity=proximity_str,
                types=POSTCODE_TYPES,
            ),
            postal,
            city=effective_city,
            guess=guess_iso,
            market=market,
        )
        if area is not None and not effective_zone:
            # « dans le 75009 »: the postcode is the place. Its centroid, its
            # city; no zone persisted, since a carried bare code would come back
            # next turn without the postcode rule. Q26: the user named a small
            # area, so it is a "poi" origin (S4 tight disc), not the city-wide
            # radius that let hotels 3-6 km away and in the suburbs through.
            return _ok(
                area.as_result(),
                feature_type=area.feature_type,
                profile_delta=_anchor_state(
                    city=area.place or effective_city,
                    raw_user_message=raw_user_message,
                    profile_state_context=profile_state_context,
                    profile_location_hint=profile_location_hint,
                    guards_fired=guards_fired,
                    resolved=area,
                ),
                distance_origin_type="poi",
                metro=effective_metro,
                guards_fired=guards_fired,
            )
        if area is not None:
            # Any other zone (a station, or an address the lookup above did not
            # confirm) is searched as before, in the postcode's city: that city
            # counts as named, so the city question below never fires for it.
            effective_city = effective_city or area.place or None
            guess_iso = guess_iso or _iso2(area.country_code)
        elif not (effective_zone or effective_city or effective_metro):
            # Nothing else to search: an honest miss. Never the device fix in
            # place of a postcode the user wrote (Gate 3).
            return _fail("geocode_no_match", {"query": postal}, guards_fired)

    region_in_play = (country_code or guess_iso or "US").upper() == "US"
    state_hint = resolve_state_hint(
        keywords=[region_named] if region_named and region_in_play else None,
        city=effective_city,
        zone=effective_zone,
        profile_location_hint=profile_location_hint,
        raw_user_message=raw_user_message,
        profile_state_context=profile_state_context,
        country_code=country_code,
    )

    # QA14707 (Q20, H3 RC5): a street or an address with no postcode. The
    # lookup below never returns a street (`CANDIDATE_TYPES`), so « Boulevard
    # de la République, Versailles » resolved to Leipzig, and « 2 Boulevard
    # Poissonnière, Paris » to a Paris homonym question. The address lookup the
    # postcode branch uses comes first; when it designates nothing
    # (`_street_match`), the turn goes on exactly as before. Only a NAMED
    # country, or the carried `country_anchor` of the same city (Q19,
    # `_fill_place_from_profile`), filters it (DQ8). Q21: a named, anchored or chosen state holds
    # here too — « Main Street, Springfield » with Illinois named never
    # resolves a Missouri street.
    if zone_is_specific and zone_kind in ("address", "street") and not postal:
        street = _street_match(
            get_mapbox_client().geocode_candidates(
                ", ".join(part for part in (effective_zone, effective_city) if part),
                country=country_code,
                language=lang,
                proximity=proximity_str,
                types=ADDRESS_TYPES,
            ),
            effective_zone or "",
            city=effective_city,
            state_hint=state_hint,
            region_chosen=region_chosen,
        )
        if street is not None:
            return _ok(
                street.as_result(),
                feature_type=street.feature_type,
                profile_delta=_anchor_state(
                    city=street.place or effective_city,
                    raw_user_message=raw_user_message,
                    profile_state_context=profile_state_context,
                    profile_location_hint=profile_location_hint,
                    guards_fired=guards_fired,
                    resolved=street,
                ),
                distance_origin_type="poi",
                # Mapbox's name of the street or address, as the postcode
                # branch persists it.
                zone=street.name or effective_zone,
                metro=effective_metro,
                guards_fired=guards_fired,
            )

    # 2026-10-27 (prod: « Dans le 06 ou le 83 », « l'Hérault », « Puglia »): an
    # administrative area named as the destination is searched as one, around
    # the point Mapbox gives the area (its main city), on the city-wide radius.
    # It used to reach the zone-without-city question below, asked again and
    # again even after « peu importe la ville ». The area becomes the session's
    # destination (`last_city`), so a follow-up looks the same area up again.
    if (
        zone_kind in _AREA_KINDS and effective_zone and not postal
        and not effective_city and not effective_metro
    ):
        area_names = _names(effective_zone, *aliases)
        # 2026-10-29 (prod session ef12e6e0, « going north » around a device
        # fix in California): an area for which neither the user nor the
        # model gave a country was looked up worldwide, and « North,
        # Lebanon » became the destination of the next turns too. Like a
        # metro written alone (2026-10-28), it is looked up in the market's
        # country only; nothing there is the honest « where is that? ».
        market_scope = None if (country_code or guess_iso) else _market_country(locale, market_country)
        area = _area_match(
            effective_zone,
            area_names,
            scope=country_code or guess_iso or market_scope,
            hard=bool(country_code) or market_scope is not None,
            language=lang,
            proximity=proximity_str,
            exact=area_exact,
        )
        seat = (
            _city_coordinate(
                area_seat, country=country_code, locale_country=guess_iso, language=lang,
                scope=guess_iso,
            )
            if area is None and area_seat else None
        )
        if seat is not None:
            area = GeocodeCandidate(
                latitude=seat[0], longitude=seat[1], name=effective_zone,
                place_name=f"{effective_zone}, {area_seat}", place_formatted=area_seat or "",
                feature_type="region", country_code=guess_iso or "", region=effective_zone,
                bbox=None, rank=0,
            )
        if area is not None:
            return _ok(
                area.as_result(),
                feature_type=area.feature_type,
                profile_delta={
                    **_anchor_state(
                        city=area.name or effective_zone,
                        raw_user_message=raw_user_message,
                        profile_state_context=profile_state_context,
                        profile_location_hint=profile_location_hint,
                        guards_fired=guards_fired,
                        resolved=area,
                    ),
                    # Carried as an area, not a city (`_fill_place_from_profile`).
                    "city_is_area": True,
                },
                distance_origin_type="city_centroid",
                guards_fired=guards_fired,
            )
        # Not an area Mapbox's admin layer knows (« Lago di Como », a coast):
        # the Search-Box tier, scoped to the request's country like any
        # landmark, and the echo guard as the veto.
        natural = geo_resolver.rank_landmark(
            get_searchbox_client().forward_candidates(
                effective_zone,
                country=market_scope or _soft_country(country_code, guess_iso, locale),
                language=lang,
                proximity=proximity_str,
            ),
            requested_zone=effective_zone,
            inventory=get_inventory(),
            proximity=proximity_tuple,
        )
        if natural is not None and _business_named_after_the_area(
            natural, zone_kind=zone_kind, names=area_names
        ):
            # No city to fall back on: the honest outcome below.
            _mark_business_named_after_the_area(guards_fired)
        elif natural is not None and any(
            _echoes(natural.place_name, city=None, zone=n, state_hint=None) for n in area_names
        ):
            return _ok(
                natural.as_result(),
                feature_type=natural.feature_type,
                profile_delta={},
                distance_origin_type="poi",
                zone=effective_zone,
                guards_fired=guards_fired,
            )
        return _unresolved(effective_zone, lang, {"query": effective_zone}, guards_fired)

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
                    # QA14707: no option, by design — see `city_needed_question`.
                    # `zone_is_specific` guarantees a non-empty subject here.
                    Clarification(kind="city_needed", subject=effective_zone or ""),
                )
            landmark_candidates = get_searchbox_client().forward_candidates(
                # No city to append here by definition (this branch is "no city
                # and no metro"), so the landmark goes alone — `_searchbox_query`
                # would return exactly that. This is the one path that stays
                # exposed to Mapbox's IP-biased ranking, which is why it ranks
                # the whole candidate list instead of trusting top-1.
                effective_zone or "",
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
                elif _business_named_after_the_area(
                    landmark, zone_kind=zone_kind, names=_names(effective_zone, *aliases)
                ):
                    _mark_business_named_after_the_area(guards_fired)
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

    # QA14707 (Q21, H3 RC6): a picked option is looked up by its own name. The
    # reply that picked it (« New York » for « Manhattan ») yields a state; in
    # the query it made Mapbox answer New York City, which the echo of
    # « Manhattan » refused. The state still steers the resolver (`region_hint`)
    # and the echo below; only the query of a picked option leaves it out.
    query = ", ".join(
        part
        for part in (
            effective_zone,
            effective_city or effective_metro,
            None if region_chosen else state_hint,
        )
        if part
    )
    echo_city = effective_city or effective_metro
    # The names the destination may come back under: the one looked up and
    # the request's other form of it (`aliases`, the user's own word). Only for
    # a bare destination: next to a zone, a short alias (a typo, « Pari ») would
    # tie with the zone's words in the echo's longest-token rule and let a
    # namesake of the zone through.
    city_names = (
        _names(echo_city, *aliases) if echo_city and not effective_zone
        else _names(echo_city) if echo_city else ()
    )

    def echoes_request(place_name: str) -> bool:
        if not city_names:
            return _echoes(place_name, city=None, zone=effective_zone, state_hint=state_hint)
        return any(
            _echoes(place_name, city=name, zone=effective_zone, state_hint=state_hint)
            for name in city_names
        )

    # 2026-10-27 (prod: Galveston -> Alveston GB, Ojai -> Oost NL, Salzburg ->
    # Sulzburg DE). Unscoped, Mapbox biases its list by the caller's IP — the
    # container's region — and our inventory tier then promotes a namesake
    # near our hotels over the town asked for (agent-usa #157 measured the
    # same bias). The country the model knows the place is in scopes the
    # lookup first; it stays a scope, not a filter: when nothing the scoped
    # lookup returns echoes the request, the lookup runs again worldwide, so a
    # wrong guess costs one call and never the right answer. A country the
    # user NAMED stays the one hard filter.
    mapbox = get_mapbox_client()
    # Replay 2026-10-28 (« dans la métropole lilloise »): a metro written
    # alone, with no country from the user or the model, went out unscoped
    # and the echo's longest word (« métropole ») accepted « Jardim
    # Metrópole », Brazil. The market's country scopes it, and stays the
    # scope: a request with no country from anyone is not looked up
    # worldwide (nothing that echoes there → the honest « where is that? »);
    # a city keeps its own rule.
    scope_iso = guess_iso or (
        _market_country(locale, market_country) if effective_metro and not effective_city else None
    )
    candidates = mapbox.geocode_candidates(
        query, country=country_code or scope_iso, language=lang, proximity=proximity_str
    )
    def echoes_the_city(place_name: str) -> bool:
        return any(
            _echoes(place_name, city=name, zone=None, state_hint=state_hint) for name in city_names
        )

    # 2026-10-28 (prod session b4703f31, « Paris possiblement à côté de
    # l'unesco »): with a zone named, the scoped list holds the city (« Paris,
    # France ») but no candidate echoes the zone too, and the worldwide lookup
    # replaced it with Paris in Maine, in Roanne, and Headquarters, Kentucky:
    # the homonym question then left out the capital. The city the scoped
    # lookup found is enough to keep its scope.
    if not country_code and guess_iso and not any(
        echoes_request(c.place_name) or (effective_zone and city_names and echoes_the_city(c.place_name))
        for c in candidates
    ):
        candidates = mapbox.geocode_candidates(
            query, country=None, language=lang, proximity=proximity_str
        )
    # Candidates the echo guard would refuse are not candidates (prod: Cuneo
    # -> Luneo, Venezia, chosen for its 30 nearby hotels against Cuneo's 0,
    # then refused by the echo guard). A bare destination is ranked among the
    # ones that echo it, when any does; with a zone named, the list is left to
    # the paths below (the Search-Box tier wants the city's own candidates).
    contained = False
    if not effective_zone:
        echoing = [c for c in candidates if echoes_request(c.place_name)]
        if echoing:
            candidates = echoing
    elif zone_kind == "neighborhood" and city_names:
        # A neighbourhood of the named city (« Westall, Clayton », Melbourne):
        # the candidate that names the neighbourhood and lies within the
        # city's reach is the place asked for, even though its own name does
        # not repeat the city's (« Clayton, Victoria, Australia »). Facts only:
        # the name echoes the zone, and the distance to a candidate that
        # echoes the city is at most `_POI_ANCHOR_MAX_KM`.
        cities = [
            c for c in candidates
            if any(_echoes(c.place_name, city=n, zone=None, state_hint=state_hint) for n in city_names)
        ]
        within = [
            c for c in candidates
            if c not in cities
            and _echoes(c.place_name, city=None, zone=effective_zone, state_hint=state_hint)
            and any(
                haversine_km(c.latitude, c.longitude, h.latitude, h.longitude) <= _POI_ANCHOR_MAX_KM
                for h in cities
            )
        ]
        if within:
            candidates, contained = within, True
    # QA14707 (Q14): the option the user picked among homonyms that share a
    # name and a country (Springfield IL / MO). Without it the same question
    # came back. A state named this turn (or anchored) speaks for itself: Q21,
    # the pick narrows only to candidates that state's echo accepts, so a
    # contradicting state (« Springfield IL » after picking Missouri) narrows
    # nothing and the resolver follows the state.
    if region_chosen:
        chosen_region = _comparable(region_chosen)
        narrowed = [
            c for c in candidates
            if _comparable(c.region) == chosen_region
            and (not state_hint or _echoes(c.place_name, city=None, zone=None, state_hint=state_hint))
        ]
        if narrowed:
            candidates = narrowed

    resolution = geo_resolver.resolve(
        candidates,
        inventory=get_inventory(),
        country_hint=country_code,
        region_hint=state_hint,
        # P0-2 fix 3: the model's world-knowledge guess enters here, sharing
        # the locale prior's BOUNDED weight (_W_LOCALE) — a boost among
        # candidates, never a filter, so a wrong guess costs a rank and cannot
        # erase the right answer. A named country stays the hard filter above.
        locale_country=guess_iso or _locale_country(locale),
        proximity=proximity_tuple,
        requested_name=effective_city or effective_metro,
        # S-CX2: the clarify question can reach the customer verbatim — ask it
        # in the conversation language (same 2-letter hint Mapbox already got).
        language=lang,
        # 2026-10-29: every spelling the request gave the city (« Milano » and
        # « Milan »): a far bigger city of one of them outweighs a hamlet.
        requested_names=city_names,
    )

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
    if echo_city:
        for scored in resolution.scored:
            if not scored.in_inventory_tier:
                continue
            if _echoes(scored.candidate.place_name, city=echo_city, zone=None, state_hint=None):
                city_anchor = (scored.candidate.latitude, scored.candidate.longitude)
                break
    poi_anchor: tuple[float, float] | None = proximity_tuple or city_anchor

    clarify_response: dict | None = None
    if resolution.decision == "clarify":
        mark_level("WARNING", status_message="geocode_ambiguous")
        options = [
            {
                "name": c.name,
                "country_code": c.country_code,
                "region": c.region,
                "place_formatted": c.place_formatted,
            }
            for c in resolution.options
        ]
        clarify_response = _fail(
            "geocode_ambiguous",
            {"question": resolution.question, "options": options},
            guards_fired,
            # Same reason as the unanchored gate above: this clarify can also be
            # returned with a zone in hand (line ~758, once tier 2 has missed
            # too), and the answer turn needs it. mcp-dayuse#7: without a zone,
            # the homonym options travel in the Clarification below.
            {"zone": effective_zone} if effective_zone else None,
            # The question is about the name the resolver was asked to resolve
            # (`requested_name` above), its options the resolver's own.
            _homonym_clarification(echo_city or "", resolution.options),
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
        if echoes_request(chosen.place_name) or (
            contained
            and _echoes(chosen.place_name, city=None, zone=effective_zone, state_hint=state_hint)
        ):
            profile_delta = _anchor_state(
                city=effective_city,
                raw_user_message=raw_user_message,
                profile_state_context=profile_state_context,
                profile_location_hint=profile_location_hint,
                guards_fired=guards_fired,
                resolved=chosen,
            )
            if not (effective_zone or centre_zone) and chosen.feature_type in ("place", "locality"):
                # 2026-10-29 (replay of prod session d057ac6e): « Milano » asked
                # as « Milan » (the model's canonical) resolved to Milano, but
                # the name carried to the next turn was « Milan », and « Vorrei
                # jacuzzi » re-asked « Milano o Milan (Zero Branco) ? ». The
                # destination carried is the name of the place found.
                if chosen.name and chosen.name != profile_location_hint:
                    profile_delta["last_city"] = chosen.name
                else:
                    profile_delta.pop("last_city", None)
            return _ok(
                _city_point(chosen) if not (effective_zone or centre_zone) else chosen.as_result(),
                feature_type=chosen.feature_type,
                profile_delta=profile_delta,
                # S4: a named specific zone means "around X" even when it was v6
                # that answered, so the 3 km disc applies here too. Without this
                # the same landmark got 3 km via Search Box and 20 km via v6.
                # mcp-dayuse#7: same for a district typed as the destination
                # (« Manhattan »): no search page of its own, the site's rule.
                distance_origin_type=(
                    "poi" if centre_zone or chosen.feature_type in _DISTRICT_FEATURE_TYPES
                    else zone_origin_type
                ),
                zone=effective_zone or centre_zone,
                zone_kind="city_centre" if centre_zone else None,
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
    #   1. `poi_anchor` — the device GPS fix, or the v6 candidate that echoed
    #      the city the user named. A coordinate, so the query stays the BARE
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
    # A city NAME with no city COORDINATE means the scavenging loop above found
    # nothing credible among THIS turn's candidates. Rather than fall straight
    # to folding the city into the query — which measurably drops the clean
    # feature out of the candidate list entirely (`_city_coordinate`) — ask v6
    # for the city itself. One extra call, only on this path (a turn resolved by
    # tier 1 has already returned above), and it converts the lossy fallback
    # into the anchored path that works. Guard #14 also stops being a no-op
    # here: with an anchor it can finally reject a POI in the wrong place.
    if poi_anchor is None and echo_city and effective_zone:
        city_anchor = _city_coordinate(
            echo_city,
            country=country_code,
            locale_country=guess_iso or _locale_country(locale),
            language=lang,
            scope=guess_iso,
        )
        poi_anchor = city_anchor

    searchbox_proximity = (
        f"{poi_anchor[1]},{poi_anchor[0]}" if poi_anchor is not None else None
    )
    if searchbox_proximity is not None:
        searchbox_query = effective_zone or effective_city or effective_metro or ""
    else:
        searchbox_query = _searchbox_query(effective_zone, effective_city, effective_metro)
    if not effective_zone and candidates:
        # A bare-city miss that HAS v6 candidates still never reaches Search Box
        # (worse for cities, separate SKU) — unchanged.
        searchbox_query = ""
    if searchbox_query:
        poi_candidates = get_searchbox_client().forward_candidates(
            searchbox_query,
            country=_soft_country(country_code, country_guess, locale),
            language=lang,
            proximity=searchbox_proximity,
        )
        poi = geo_resolver.rank_landmark(
            poi_candidates,
            requested_zone=effective_zone or effective_city or effective_metro or "",
            inventory=get_inventory(),
            proximity=proximity_tuple,
            city_anchor=city_anchor,
            city_query=not effective_zone,
        )
        if poi is not None and any(
            _echoes(poi.place_name, city=echo_city, zone=name, state_hint=state_hint)
            for name in (_names(effective_zone, *zone_aliases) or (effective_zone,))
        ):
            # Guard #14 (`poi_anchor_coherence`): the echo above proved the NAME,
            # this proves the PLACE. Rejecting falls through to the honest
            # outcomes below — never a fabricated coordinate, never a retry.
            if _poi_anchor_incoherent(poi, anchor=poi_anchor):
                guards_fired.append("poi_anchor_coherence")
                mark_level("WARNING", status_message="poi_anchor_incoherent")
            elif _business_named_after_the_area(
                poi,
                zone_kind=zone_kind,
                names=_names(effective_zone, *aliases, effective_city, effective_metro),
            ):
                _mark_business_named_after_the_area(guards_fired)
                district = _district_of_namesakes(
                    poi_candidates,
                    zone_kind=zone_kind,
                    names=_names(effective_zone, *zone_aliases),
                    anchor=poi_anchor,
                    city=echo_city,
                )
                if district is not None:
                    return _ok(
                        district.as_result(),
                        feature_type=district.feature_type,
                        profile_delta=_anchor_state(
                            city=effective_city,
                            raw_user_message=raw_user_message,
                            profile_state_context=profile_state_context,
                            profile_location_hint=profile_location_hint,
                            guards_fired=guards_fired,
                        ),
                        distance_origin_type="poi",
                        zone=effective_zone,
                        metro=effective_metro,
                        guards_fired=guards_fired,
                    )
                if effective_city or effective_metro:
                    # Prod 7e296e4b (« new york city or long island »): the city
                    # is the search, as for a region named with its city (above).
                    whole_city = geocode_core(
                        city=city, metro=metro, country_code=country_code,
                        raw_user_message=raw_user_message,
                        profile_state_context=profile_state_context,
                        profile_location_hint=profile_location_hint,
                        locale=locale, language_hint=language_hint,
                        proximity_lat=proximity_lat, proximity_lon=proximity_lon,
                        country_guess=country_guess,
                        region_named=region_named or effective_zone,
                        postal_code=postal_code, region_chosen=region_chosen,
                        market_country=market_country, aliases=aliases,
                    )
                    whole_city["guards_fired"] = sorted(
                        {*guards_fired, *whole_city.get("guards_fired", ())}
                    )
                    if whole_city.get("ok") and effective_zone:
                        # 2026-10-29 (prod session 4919ffbc, « Ostia lido » four
                        # times, four searches on the centre of Rome, 25 km
                        # away): the city alone is searched, and the reply says
                        # the spot could not be placed, as for any landmark
                        # dropped (`_without_the_landmark`).
                        _mark_landmark_unresolved(whole_city, effective_zone)
                    return whole_city
            else:
                profile_delta = _anchor_state(
                    city=effective_city,
                    raw_user_message=raw_user_message,
                    profile_state_context=profile_state_context,
                    profile_location_hint=profile_location_hint,
                    guards_fired=guards_fired,
                    resolved=poi,
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


def _folded(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _fill_place_from_profile(args: dict, profile_in: dict) -> None:
    """The destination half of the profile→geocode bridge (P0 #4 fix, S-G5):
    a `city`/`zone`/`metro`/`country_code` THIS turn gave always wins; a blank
    one is filled from `profile_in` (the city-reuse case the leaf's instruction
    used to spell out in prose). Never rewrites a fresh extraction.

    QA14707 (Q07): applied by `geocode_location` right after it maps the
    model's `GeoIntent`, no longer by the before-tool callback. These four are
    not tool arguments any more, and ADK drops any key a tool does not
    declare, so a callback could only ever fill what the model sees.

    QA14707 (Q08): a postcode written this turn names a new place by itself, so
    nothing of the earlier one is carried onto it: not the zone (it would be
    searched instead of the postcode), not the city (it would outrank the
    postcode's own city and bias its lookup), and not the country, a HARD
    filter, while DQ8 keeps only a country the user named as one.

    QA14707 (Q14): `region_anchor` is the region of the homonym option the
    user picked by its number (the concierge sets it from the stored
    `Clarification`, never from the message). It goes with the city it was
    chosen for: applied only while the turn's city is that same city.

    Prod session 1eb2430a (2026-10-27), two rules:
    - an AREA carried as the destination (`city_is_area`, set by the area
      branch) is carried as an area when the turn names no place: it was
      looked up as a city instead, and « Île-de-France » came back as a
      homonym question (Les Ulis or île de Ré);
    - a city named THIS turn that is not the carried one does not inherit the
      carried zone or metro: « Île-de-France » stayed the zone of « autour de
      Saint-Ouen » and made it a 2 km search."""
    if not _is_blank(args.get("postal_code")):
        return
    carried_city = profile_in.get("city") if isinstance(profile_in.get("city"), str) else None
    if (
        profile_in.get("city_is_area") and carried_city and carried_city.strip()
        and all(_is_blank(args.get(key)) for key in ("city", "zone", "metro"))
    ):
        args["zone"], args["zone_kind"] = carried_city.strip(), "region"
        if _is_blank(args.get("country_code")) and profile_in.get("country_anchor"):
            args["country_code"] = profile_in["country_anchor"]
        return
    new_city = (
        not _is_blank(args.get("city")) and bool(carried_city and carried_city.strip())
        and _comparable(carried_city or "") != _comparable(str(args.get("city")))
    )
    if _is_blank(args.get("city")) and profile_in.get("city"):
        args["city"] = profile_in["city"]
    if _is_blank(args.get("zone")) and profile_in.get("zone") and not new_city:
        args["zone"] = profile_in["zone"]
        # 2026-10-28: the centre of the city stays the centre on a follow-up.
        if profile_in.get("zone_kind") == "city_centre" and _is_blank(args.get("zone_kind")):
            args["zone_kind"] = "city_centre"
    if _is_blank(args.get("metro")) and profile_in.get("metro") and not new_city:
        args["metro"] = profile_in["metro"]
    # QA14707 (Q19): the carried country is the country of the CARRIED city. It
    # is a hard Mapbox filter, so it goes only with that city: « actually make
    # it paris » from London must not look for Paris inside GB.
    carried_anchor_city = profile_in.get("city")
    if (
        _is_blank(args.get("country_code")) and profile_in.get("country_anchor")
        and (
            not (isinstance(carried_anchor_city, str) and carried_anchor_city.strip())
            or _comparable(carried_anchor_city) == _comparable(str(args.get("city") or ""))
        )
    ):
        args["country_code"] = profile_in["country_anchor"]
    region, carried_city = profile_in.get("region_anchor"), profile_in.get("city")
    if (
        isinstance(region, str) and region.strip()
        and isinstance(carried_city, str) and carried_city.strip()
        and _comparable(carried_city) == _comparable(str(args.get("city") or ""))
    ):
        args["region_chosen"] = region.strip()


def inject_profile_geo_context(tool: object, args: dict, tool_context: object) -> None:
    """`before_tool_callback` (P0 #4 fix, S-G5) — the profile-signal half of
    the deterministic profile→tool-args bridge for `geocode_location`, same
    pattern as `equipment_ids.enforce_equipment_filters`: the leaf's own
    instruction used to ask the model to COPY `city`/`state_anchor` into
    `profile_location_hint`/`profile_state_context` itself (the audit's P0 #4
    — "the model stops being a copy machine" is this fix):
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
    - `language_hint`: the conversation language, same category.
    The destination itself (`city`/`zone`/`metro`/`country_code`) is filled
    from the same `profile_in` by the tool, once it has mapped the model's
    `GeoIntent` (`_fill_place_from_profile`, QA14707 Q07).
    A profile with nothing to offer (first turn, no DataPart) leaves `args`
    exactly as the model wrote them."""
    if getattr(tool, "name", "") != "geocode_location":
        return None
    profile_in = read_profile_in(tool_context)

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


# --- the tool the model sees (QA14707, Q07) ----------------------------------


def _comparable(text: str) -> str:
    """Case, accents and punctuation folded away, words kept apart: « Gare-du-
    Nord, » and « gare du nord » compare equal. Character classes only — no
    word list, nothing about any language."""
    spaced = "".join(ch if ch.isalnum() else " " for ch in _folded(text))
    return " ".join(spaced.split())


# Q18: a claim is anchored by similarity when its comparable text is at least
# this close (difflib ratio, 0..1) to a window of the input text of the same
# number of words. Measured: « les champs elysees » / « des champs elysees »
# 0.94, « pres des champs elysees » / « pres des champ elysee » 0.955,
# « champs elysees » / « champ elysee » 0.923; refused: « bruxelles » vs the
# best window of « un hotel pres de la gare du nord demain » 0.46, « london » /
# « londres » 0.62, « tour eiffel » vs any 2-word window of « un hotel a paris
# demain » < 0.4.
_MENTION_SIMILARITY = 0.85


def _similar_in(claim: str, said: str) -> bool:
    """Whether `claim` is close, character by character, to a window of `said`
    with the same number of words. No word list, no language rule."""
    words = said.split()
    size = len(claim.split())
    if not claim or size == 0 or len(words) < size:
        return False
    return any(
        difflib.SequenceMatcher(None, claim, " ".join(words[i : i + size])).ratio()
        >= _MENTION_SIMILARITY
        for i in range(len(words) - size + 1)
    )


class _Claims:
    """The model's claims about the message, checked by the code — and what
    that check discarded, as counts only (GDPR: never a word of the message).

    A `mention` is the model's claim of what the user wrote. `anchored` keeps
    a place or a city, in this order, when (1) its mention (the canonical name
    when there is no mention) is in the leaf's real input text
    (`read_input_text`, the concierge's EARLIER REQUEST prefix included),
    whole words, case, accents and punctuation aside; else (2) its canonical
    name is in the text the same way; else (3) its mention or canonical is
    similar above `_MENTION_SIMILARITY` to a window of the text's words (an
    added article, a corrected typo), counted in `mentions_fuzzy`. Otherwise
    it is dropped. That checks a claim; it does not understand the language.

    `user_words` is the user's own words of this turn (`read_user_words`, the
    last text part, without the concierge's prefix): `typed` tells a place
    the user wrote now from one only carried in the earlier request."""

    def __init__(self, text: str, user_words: str = ""):
        self._said = f" {_comparable(text)} "
        self._typed = f" {_comparable(user_words)} "
        self.mentions_discarded = 0
        self.mentions_fuzzy = 0
        self.canonicals_rejected = 0
        self.countries_discarded = 0
        self.city_conflicts = 0

    def typed(self, ref: Place | CityRef) -> bool:
        claim = _comparable(ref.mention) or _comparable(ref.canonical)
        return bool(claim) and f" {claim} " in self._typed

    def anchored(self, ref: Place | CityRef) -> bool:
        mention, canonical = _comparable(ref.mention), _comparable(ref.canonical)
        claim = mention or canonical
        if claim and f" {claim} " in self._said:
            return True
        if canonical and f" {canonical} " in self._said:
            return True
        said = self._said.strip()
        if any(_similar_in(c, said) for c in (mention, canonical) if c):
            self.mentions_fuzzy += 1
            return True
        if ref.mention.strip():
            self.mentions_discarded += 1
        return False

    def written(self, value: str | None) -> str | None:
        """A value the model reports as written (a postcode), kept only when it
        is in the input text, whole words. It stays exact: no canonical step and
        no similarity step, unlike `anchored`."""
        text = (value or "").strip()
        claim = _comparable(text)
        if claim and f" {claim} " in self._said:
            return text
        if text:
            self.mentions_discarded += 1
        return None

    def country(self, value: str | None) -> str | None:
        """Every country value goes through `_iso2` before it becomes a hard
        filter or a soft hint: "fr" -> "FR"; a name, an alpha-3 code or noise
        ("France", "USA", "FRA") is discarded — no hint, never a wrong scope."""
        code = _iso2(value)
        if code is None and (value or "").strip():
            self.countries_discarded += 1
        return code


_PLACE_KINDS = frozenset(get_args(PlaceKind))


def _repaired(raw: dict) -> tuple[dict, int]:
    """A copy of the model's raw intent with exactly two known shape slips
    fixed (Q17, H3: 31 of 220 calls), and how many fixes were applied:

    - a bare-string intent-level `city` (the model mixes it up with
      `Place.city`) becomes a `CityRef` with that canonical and no mention, so
      `_Claims.anchored` still keeps it only when that canonical is in the
      text word for word or similar to a window of it;
    - a place whose `kind` is a string outside `PlaceKind` (« date ») is
      removed alone.

    Nothing else is touched: any other slip — a `kind` that is not a string
    (a list, an object) included — still fails validation. The caller's dict
    is never modified."""
    fixed = dict(raw)
    repairs = 0
    if isinstance(fixed.get("city"), str):
        fixed["city"] = {"canonical": fixed["city"], "mention": ""}
        repairs += 1
    places = fixed.get("places")
    if isinstance(places, list):
        kept = [
            p for p in places
            if not (isinstance(p, dict) and isinstance(p.get("kind"), str) and p["kind"] not in _PLACE_KINDS)
        ]
        repairs += len(places) - len(kept)
        fixed["places"] = kept
    return fixed, repairs


def _valid_intent(intent: object) -> tuple[GeoIntent, bool, int]:
    """The model's `intent` as a `GeoIntent`, whether it validated as sent,
    and how many repairs (`_repaired`) the intent used carries.

    ADK 2.4 converts the model's dict with `model_validate` (the parameter is
    declared as the class itself, see `geocode_location`), but an argument that
    fails validation — an unknown `kind`, a third place, an extra key — is NOT
    rejected: ADK logs a warning and passes the raw dict through. It is
    re-validated here once repaired; if it still fails, NOTHING of it is used:
    the turn goes on as with an empty intent (0 repairs), so the carry-over
    from `profile_in` still applies. Never raises."""
    if isinstance(intent, GeoIntent):
        return intent, True, 0
    if intent is None:
        return GeoIntent(), True, 0
    try:
        return GeoIntent.model_validate(intent), True, 0
    except ValidationError:
        pass
    if isinstance(intent, dict):
        fixed, repairs = _repaired(intent)
        if repairs:
            try:
                return GeoIntent.model_validate(fixed), False, repairs
            except ValidationError:
                pass
    return GeoIntent(), False, 0


def asks_nearby(intent: object) -> bool:
    """« Try a nearby area » (prod session 8a6576a4, 2026-10-27): the request
    names no new place and asks to search around the earlier destination.
    `geocode_location` marks its result `nearby`, and the code, not the model,
    turns it into a wider ring (`inject_landmark_radius`)."""
    geo, _, _ = _valid_intent(intent)
    return geo.relation == "near" and not geo.places and geo.city is None


def _marked_nearby(result: dict, nearby: bool) -> dict:
    if nearby and result.get("ok"):
        result["nearby"] = True
    return result


def _verified_city(
    ref: Place | CityRef,
    claims: _Claims,
    *,
    country: str | None,
    locale_country: str | None,
    language: str | None,
    scope: str | None = None,
) -> str | None:
    """The city to geocode for a city the user wrote as `ref.mention`.

    `canonical` is the model's spelling of it (« Pari » -> « Paris »). It is
    kept only when it geocodes to a city with real inventory (`_city_coordinate`,
    the city anchor's own credibility test); otherwise the user's own words are
    what gets geocoded. Free when both name the same thing: the user wrote it,
    and `geocode_core` checks it as always."""
    mention, canonical = ref.mention.strip(), ref.canonical.strip()
    if not mention or not canonical or _comparable(mention) == _comparable(canonical):
        return canonical or mention or None
    if _city_coordinate(
        canonical, country=country, locale_country=locale_country, language=language, scope=scope
    ):
        return canonical
    claims.canonicals_rejected += 1
    return mention


def _place_args(
    geo: GeoIntent, claims: _Claims, *, locale: str | None, language_hint: str | None
) -> dict[str, Any]:
    """The `GeoIntent` as `geocode_core` arguments — the S-L plan's §3 mapping:

    - a `city` place → `city`;
    - the first place of any other kind but `hotel` → `zone` = its name, with
      `city` = the place's own city (inferred or not, as today), else the city
      the user named (a `city` place, then the `city` field) — except that a
      city the user wrote THIS turn (`_Claims.typed`) and that differs from
      the place's own city wins over it, checked by `_verified_city`, and is
      counted as `city_conflicts` (Q14);
    - `country_named` → `country_code`, the hard filter; a country not named
      (the zone place's, else a city's) → `country_guess`, a hint;
    - `region_named` → the state tier;
    - `ambiguity.reason == "city_needed"` (DQ6, the S5 rule): no city at all,
      so `geocode_core` asks which one — the code decides the question, the
      model only flags it. `homonym` and `too_vague` are logged, not mapped:
      the geocoder keeps deciding homonyms;
    - a `postal_code` (Q08), from the zone place else a city place, checked
      against the message → `postal_code`, with the zone place's kind as
      `zone_kind`: `geocode_core` resolves it under DQ8's country rule.

    A place or a city that `_Claims.anchored` does not keep (neither its
    mention nor its canonical in the message, nor similar to a part of it) is
    dropped first.
    A hotel is never a zone (it has its own path, `find_hotel_by_name`).
    `relation`, `carryover` and `exclusions` are read, not applied (S-L5)."""
    places = [p for p in geo.places if claims.anchored(p)]
    # Rank in `places` decides nothing: « Gare du nord Paris » listed as two
    # places, in either order, must lose neither Paris (the city question of
    # trace A again) nor the station (a city-wide search).
    zone_place = next((p for p in places if p.kind not in ("city", "hotel")), None)
    city_places = [p for p in places if p.kind == "city"]
    # 2026-10-28 (prod session 72c83c93, « Dans le 94 »): an administrative
    # area holds many cities. The city the model attached to it from its own
    # knowledge (`city_inferred`: Paris for the 94), and a city that names the
    # area itself (`city`: « 94 » / « Val-de-Marne »), are not a city to search
    # in: with either, the area was looked up as « Val-de-Marne, Paris » and
    # came back as « Marne, Neuilly-Plaisance », in the 93. A French
    # département the model reported by its number is checked against the
    # INSEE table (`fr_departments`): its name there is the area searched.
    area_place = zone_place if zone_place is not None and zone_place.kind in _AREA_KINDS else None
    dept = None
    if area_place is not None and _iso2(area_place.country) in (None, "FR"):
        dept = department(area_place.mention, area_place.canonical, area_place.postal_code)
    if area_place is not None and dept is None and (area_place.postal_code or "").strip():
        area_place = None  # « dans le 75009 »: a postcode, its own path (Q08)
    area_words = (
        {_comparable(area_place.mention), _comparable(area_place.canonical)}
        | ({_comparable(dept[0])} if dept else set())
        if area_place is not None else set()
    ) - {""}

    def names_the_area(ref: Place | CityRef) -> bool:
        return bool({_comparable(ref.mention), _comparable(ref.canonical)} & area_words)

    city_places = [p for p in city_places if not names_the_area(p)]
    # Q08: the postcode the user wrote, read from the zone place first, then
    # from a city place (« 13001 marseille »), and checked against the message
    # like a mention. A place that is nothing but that code (« dans le 75009 »)
    # is neither a zone nor a city: the postcode lookup resolves it.
    postal_place = next(
        (
            p for p in [zone_place, *city_places]
            if p is not None and (p.postal_code or "").strip() and not (dept and p is area_place)
        ),
        None,
    )
    postal_code = claims.written(postal_place.postal_code) if postal_place is not None else None

    def only_the_code(ref: Place) -> bool:
        code = _comparable(postal_code or "")
        return bool(code) and code in (_comparable(ref.mention), _comparable(ref.canonical))

    cities: list[Place | CityRef] = [p for p in city_places if not only_the_code(p)]
    if geo.city is not None and claims.anchored(geo.city) and not names_the_area(geo.city):
        cities.append(geo.city)
    city_needed = geo.ambiguity is not None and geo.ambiguity.reason == "city_needed"
    inferred = (
        (zone_place.city or "").strip()
        if zone_place is not None and not (area_place is not None and area_place.city_inferred)
        else ""
    )
    # Q14 (the user's ruling on Q07's open point): « Gare du Nord à Bruxelles »
    # with Paris inferred for the station. A city the user wrote THIS turn
    # beats the place's inferred city — the place's whole inference (its
    # country too) is then set aside. A city carried only by the concierge's
    # EARLIER REQUEST prefix keeps the place's own city first, as before.
    typed = next((ref for ref in cities if claims.typed(ref)), None)
    overruled = (
        not city_needed
        and bool(inferred)
        and typed is not None
        and _comparable(inferred) not in (_comparable(typed.mention), _comparable(typed.canonical))
    )
    if overruled:
        claims.city_conflicts += 1
    named = claims.country(geo.country_named)
    guess: str | None = None
    first: Place | CityRef | None = typed if overruled else zone_place
    for ref in ([first] if first is not None else []) + cities:
        guess = claims.country(ref.country)
        if guess:
            break

    def verified(ref: Place | CityRef) -> str | None:
        return _verified_city(
            ref,
            claims,
            country=named,
            locale_country=guess or _locale_country(locale),
            language=_mapbox_language(locale, language_hint),
            scope=guess,
        )

    zone: str | None = None
    city: str | None = None
    city_ref: Place | CityRef | None = None
    if dept is not None:
        zone, guess = dept[0], "FR"
    elif zone_place is not None and not only_the_code(zone_place):
        zone = (zone_place.canonical or zone_place.mention).strip() or None
    if overruled and typed is not None:
        city_ref = typed
        city = verified(typed)
    elif not city_needed:
        if not inferred and cities:
            city_ref = cities[0]
        city = inferred or (verified(city_ref) if city_ref is not None else None)
    # 2026-10-27: the other form of the destination the request carried (the
    # user's word next to the canonical name, and the reverse). The echo guard
    # accepts either; a retry may look the other one up (`geocode_location`).
    named_ref: Place | CityRef | None = zone_place if zone and city is None else city_ref
    aliases: tuple[str, ...] = ()
    if named_ref is not None:
        aliases = _names(named_ref.mention, named_ref.canonical)
    if dept is not None:
        aliases = _names(dept[0], *aliases)
    return {
        "city": city or "",
        "zone": zone,
        "country_code": named,
        "country_guess": guess,
        "region_named": (geo.region_named or "").strip() or None,
        "postal_code": postal_code,
        "zone_kind": zone_place.kind if zone and zone_place is not None else None,
        "aliases": aliases,
        "area_exact": dept[0] if dept else None,
        "area_seat": dept[1] if dept else None,
        # The user's own word for a landmark, next to its canonical name:
        # « UNESCO » is what the place found is called (« 7 Pl. de
        # Fontenoy-Unesco »), « UNESCO Headquarters » is not. A generic word
        # (« centro », « gare ») never names one place, and is left out.
        "zone_aliases": (
            tuple(
                n for n in _names(zone_place.mention, zone_place.canonical)
                if len(_comparable(n)) >= 4 and not is_generic_location_token(n)
            )
            if zone and zone_place is not None and dept is None else ()
        ),
    }


def geocode_location(
    intent: GeoIntent = GeoIntent(),
    metro: str | None = None,
    profile_state_context: str | None = None,
    profile_location_hint: str | None = None,
    locale: str | None = None,
    language_hint: str | None = None,
    proximity_lat: float | None = None,
    proximity_lon: float | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    """Resolve where the user wants to search into coordinates for search_offers.

    Fill `intent` with what the message says about the place (its fields are
    described in its schema): the user's own words in each `mention`, never
    coordinates. When the message names no new place, send an empty `intent`
    ({}): the system reuses the earlier destination. The system reads the
    user's message itself, checks every place you report against it and
    against the geocoder, and fills in the earlier destination, the state
    anchor, the GPS bias and the client's locale from profile_in.

    `metro`: a metro-area name the user gave, distinct from the city; usually
    omitted. Never set the other arguments: the system sets them.

    Returns {"ok": true, "latitude", "longitude", "resolved_place", ...} or
    {"ok": false, "error", "diagnostics"}. On error "geocode_ambiguous", do not
    search: the user is asked the question in diagnostics.
    """
    # The declaration form is load-bearing: `GeoIntent = GeoIntent()` is the
    # only one ADK 2.4 converts from the model's dict (`GeoIntent | None`
    # never does, `tests/test_geo_intent_contract.py`), and the default keeps
    # the argument optional. The frozen default instance is safe to share.
    geo, valid, repaired = _valid_intent(intent)
    # The message is read from the invocation, never copied by the model.
    user_words = read_user_words(tool_context)
    claims = _Claims(read_input_text(tool_context), user_words)
    args = _place_args(geo, claims, locale=locale, language_hint=language_hint)
    # The model often repeats a place of this turn as `metro` too (replay
    # 2026-10-28: « métropole lilloise » as a region AND as metro). A second
    # copy of a name already in the request adds no place, only a second,
    # looser lookup: dropped. A metro of its own is kept.
    named = {_comparable(n) for n in (args.get("city"), args.get("zone"), *(args.get("aliases") or ())) if n}
    for place in geo.places:
        named |= {_comparable(n) for n in (place.mention, place.canonical) if n}
    args["metro"] = None if metro and _comparable(metro) in named else metro
    args["raw_user_message"] = user_words
    # What THIS message said, before the carry-over below fills the blanks.
    own = dict(args)
    profile_in = read_profile_in(tool_context)
    if args.get("zone_kind") not in _AREA_KINDS:
        # An area named this turn is the destination by itself: the earlier
        # city is never searched in it (prod: « Lago di Como » looked up as
        # « Lago di Como, Sirmione »).
        _fill_place_from_profile(args, profile_in)
    args["country_code"] = _iso2(args.get("country_code"))
    # Q16: the market is read here, not declared: the model neither writes nor
    # sees it. Added only when valid, so the core's arguments are otherwise
    # unchanged. Read on a postcode turn too (`_fill_place_from_profile`
    # returns early there), which is the one place it is used.
    market = profile_in.get("entry_market_country")
    market_country = _iso2(market) if isinstance(market, str) else None
    if market_country:
        args["market_country"] = market_country
    _metrics_logger.info(
        "dayuse_metric=geo_intent agent=b2c_hotel_search valid=%d repaired=%d places=%d "
        "mentions_discarded=%d mentions_fuzzy=%d canonicals_rejected=%d countries_discarded=%d "
        "city_conflicts=%d ambiguity=%s carryover=%s",
        int(valid),
        repaired,
        len(geo.places),
        claims.mentions_discarded,
        claims.mentions_fuzzy,
        claims.canonicals_rejected,
        claims.countries_discarded,
        claims.city_conflicts,
        (geo.ambiguity.reason if geo.ambiguity is not None else None) or "none",
        geo.carryover,
    )
    if geo.near_user and not (own.get("city") or own.get("zone") or own.get("postal_code")):
        return _near_user(proximity_lat, proximity_lon)
    offered = _default_place(args, read_query_params(tool_context), proximity_lat, proximity_lon)
    if offered is not None:
        result = geocode_core(
            city=offered[0], country_code=offered[1], locale=locale, language_hint=language_hint,
            market_country=args.get("market_country"),
        )
        if result.get("ok"):
            result["default_place"] = offered[0]
            # A city nobody named anchors no US state: the next place the user
            # names is looked up on its own (replay 2026-10-29: New York by
            # default, then « Atlanta ga » resolved to Atlanta, New York).
            delta = {k: v for k, v in (result.get("profile_delta") or {}).items() if k != "last_state_context"}
            result["profile_delta"] = {**delta, "default_place": offered[0]}
            _metrics_logger.info("dayuse_metric=geocode_default_place agent=b2c_hotel_search status=ok")
            return result
    context: dict[str, Any] = {
        "profile_state_context": profile_state_context,
        "profile_location_hint": profile_location_hint,
        "locale": locale,
        "language_hint": language_hint,
        "proximity_lat": proximity_lat,
        "proximity_lon": proximity_lon,
    }
    nearby = asks_nearby(geo)
    result = geocode_core(**args, **context)
    if _zone_homonym(result, args):
        # The homonyms of a city asked about because of the landmark next to it:
        # the city's own lookup decides (2026-10-28, see `_without_the_landmark`).
        return _marked_nearby(_without_the_landmark(args, context) or result, nearby)
    if not _refused(result):
        return _marked_nearby(result, nearby)
    # 2026-10-27: the echo guard refused what came back, or nothing came back.
    # ONE more lookup, with another form of the same request, before giving
    # up: without what the earlier turns carried in (prod: « Alpes-Maritimes,
    # Monaco », « Lago di Como, Sirmione »), else under the other name the
    # request gave the place (the user's word / the canonical name). Never a
    # loop, never a third lookup.
    retry = _retry_args(args, own)
    first_guards = list(result.get("guards_fired") or [])
    if retry is not None:
        reason, retry_args = retry
        second = geocode_core(**retry_args, **context)
        _metrics_logger.info(
            "dayuse_metric=geocode_retry agent=b2c_hotel_search reason=%s status=%s",
            reason, "ok" if second.get("ok") else "refused" if _refused(second) else "other",
        )
        if second.get("ok") and first_guards:
            second["guards_fired"] = sorted(set(first_guards) | set(second.get("guards_fired") or []))
        dropped_zone = (args.get("zone") or "").strip()
        if second.get("ok") and dropped_zone and not (retry_args.get("zone") or "").strip():
            # 2026-10-28: the spot carried from an earlier turn could not be
            # placed; the search runs without it, and says so — and the
            # profile forgets it, or every later turn would look it up again.
            _mark_landmark_unresolved(second, dropped_zone)
        if not _refused(second):
            return _marked_nearby(second, nearby)
        result = second
    fallback = _without_the_landmark(args, context)
    if fallback is not None:
        return _marked_nearby(fallback, nearby)
    # Still nothing the user named: say so and ask, never "search unavailable".
    subject = _subject(own, args)
    if not subject:
        return result
    guards = sorted(set(first_guards) | set(result.get("guards_fired") or []))
    diagnostics = {k: v for k, v in (result.get("diagnostics") or {}).items() if k in ("query", "resolved_place")}
    return _unresolved(subject, _mapbox_language(locale, language_hint), diagnostics, guards)


def _default_place(
    args: dict[str, Any], query_params: dict[str, Any], lat: float | None, lon: float | None
) -> tuple[str, str | None] | None:
    """(city, country) the concierge offers when the place question it asked
    got an answer naming no place (2026-10-29, `query_params.default_place`:
    the visitor market's main city). Used only when nothing else locates the
    search: no place in the request, none carried, no device position."""
    offered = query_params.get("default_place")
    if not isinstance(offered, dict) or lat is not None or lon is not None:
        return None
    if any(not _is_blank(args.get(key)) for key in ("city", "zone", "metro", "postal_code")):
        return None
    city = offered.get("city")
    if not isinstance(city, str) or not city.strip():
        return None
    return city.strip(), _iso2(offered.get("country_code"))


def _mark_landmark_unresolved(result: dict, zone: str) -> dict:
    """A city searched without the spot named in it: said in the reply, and
    the spot cleared from the profile (`response_bridge.emit_search_datapart`)."""
    result["landmark_unresolved"] = zone
    result["profile_delta"] = {**(result.get("profile_delta") or {}), "landmark_unresolved": zone}
    return result


def _zone_homonym(result: dict, args: dict[str, Any]) -> bool:
    """A homonym question about the city, asked on a turn that also named a
    spot in it: its options came from the lookup of « <spot>, <city> »."""
    clarification = result.get("clarification") or {}
    return (
        result.get("error") == "geocode_ambiguous"
        and clarification.get("kind") == "homonym"
        and _landmark_and_city(args) is not None
    )


def _landmark_and_city(args: dict[str, Any]) -> tuple[str, str] | None:
    """(zone, city) when the request named a spot inside a city — not an
    area, not a postcode, not an address or a street (their own lookups)."""
    zone = (args.get("zone") or "").strip()
    city = (args.get("city") or args.get("metro") or "").strip()
    if not zone or not city or not _is_blank(args.get("postal_code")):
        return None
    if args.get("zone_kind") in _AREA_KINDS or args.get("zone_kind") in ("address", "street"):
        return None
    return zone, city


def _without_the_landmark(args: dict[str, Any], context: dict[str, Any]) -> dict | None:
    """The city alone, when the spot named in it could not be placed.

    Prod session b4703f31 (2026-10-27): « Paris possiblement à côté de
    l'unesco » got a homonym question between Paris (Roanne) and Paris (Maine),
    then « Paris la capitale de la France » got « Je n'ai pas réussi à situer
    « UNESCO Headquarters » » — with `resolved_place` « Paris, France » in the
    very same result. The city was found; only the spot was not. So: ONE
    lookup of the city alone. Found → the search runs on the city, and
    `landmark_unresolved` names the spot, for the reply to say so and for the
    profile to forget it (`response_bridge`). A homonym question → that one,
    with the city's own options, the spot kept for the answer turn. Anything
    else → None, and the caller's honest question stands."""
    pair = _landmark_and_city(args)
    if pair is None:
        return None
    zone, _city = pair
    bare = {**args, "zone": None, "zone_kind": None, "zone_aliases": ()}
    result = geocode_core(**bare, **context)
    _metrics_logger.info(
        "dayuse_metric=geocode_landmark_dropped agent=b2c_hotel_search status=%s",
        "ok" if result.get("ok") else str(result.get("error") or "other"),
    )
    if result.get("ok"):
        return _mark_landmark_unresolved(result, zone)
    if result.get("error") == "geocode_ambiguous" and (result.get("clarification") or {}).get("kind") == "homonym":
        result["profile_delta"] = {**(result.get("profile_delta") or {}), "zone": zone}
        return result
    return None


#: The failures that mean "the geocoder answered, nothing it gave is the place
#: asked for" — as opposed to a question, a missing destination, or an outage.
_REFUSALS = frozenset({"geocode_echo_mismatch", "geocode_no_match"})


def _near_user(lat: float | None, lon: float | None) -> dict:
    """« Près de moi » with no other place in THIS message (2026-10-28).

    With the device position the profile carries (`search_anchor`, set by the
    facade from the browser's or the app's fix this turn): the search runs
    around it, and the earlier destination is dropped (`near_user` in the
    delta), so a follow-up (« avec piscine ») stays around the user instead of
    falling back on the city searched before — agent-usa's « keep the near-me
    GPS origin across refinement turns ». Without a position: no place to
    search, said as such (`missing_city`), and the concierge asks for one —
    never the earlier city passed off as « near you »."""
    if lat is None or lon is None:
        return _fail("no_geocodable_location", {"reason": "missing_city", "zone_hint": None})
    return _ok(
        GeocodeResult(
            latitude=float(lat), longitude=float(lon), place_name="your current location",
            country_code="", region="",
        ),
        feature_type="gps",
        profile_delta={"near_user": True},
        distance_origin_type="gps",
    )


def _refused(result: dict) -> bool:
    if result.get("ok"):
        return False
    if result.get("error") in _REFUSALS:
        return True
    diagnostics = result.get("diagnostics") or {}
    return (
        result.get("error") == "no_geocodable_location"
        and diagnostics.get("reason") == "landmark_not_resolved"
    )


def _retry_args(args: dict[str, Any], own: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The one other form of the request worth a second lookup, or None.

    First choice: the request without what `_fill_place_from_profile` carried
    in, when this message named a place of its own. Else: the destination
    under its other name (`aliases`). Structured fields only."""
    # A place carried in, not a country: the carried country goes with the
    # carried city (Q19), and it is a hard filter only when that city is the
    # one searched — dropping it would be dropping a filter, not a stale place.
    carried = any(args.get(k) != own.get(k) for k in ("city", "zone", "metro"))
    if carried and (own.get("city") or own.get("zone")):
        bare = dict(own)
        bare["country_code"] = _iso2(bare.get("country_code"))
        if "market_country" in args:
            bare["market_country"] = args["market_country"]
        return "profile", bare
    looked_up = (args.get("city") or "").strip()
    if looked_up:
        other = next(
            (a for a in args.get("aliases") or () if _comparable(a) != _comparable(looked_up)),
            None,
        )
        if other:
            return "alias", {**args, "city": other}
    return None


def _subject(own: dict[str, Any], args: dict[str, Any]) -> str:
    """What the user is told could not be placed: the place this message
    named, in the user's own words when the request carried them, else the
    destination that was looked up."""
    for source in (own, args):
        name = (source.get("zone") or source.get("city") or "").strip()
        if name:
            aliases = source.get("aliases") or ()
            if source is own and aliases:
                return str(aliases[0])
            return name
    return ""


