"""geo_resolver — deterministic, code-owned re-ranking of Mapbox candidates.

100% deterministic: ZERO LLM calls (CLAUDE.md ≤3-LLM budget + the doctrine "LLM
extracts, code ranks" — geo memo §B, Mapbox's own MCP design). v6 returns no
numeric relevance for place candidates (probed live 2026-07-23), so the ranking
is entirely ours: list position plus signals Mapbox cannot know — our own
inventory, the user's locale, an explicitly named country/region, GPS.

The ranking rules, in priority order (geo memo §C, Pelias §B.1, Airbnb §B.2):

  1. Explicit country/region hint = HARD filter. A stated country is never a
     boost; it removes every other-country candidate. If it removes everyone,
     we resolve NOTHING (honest) rather than a wrong-country homonym.
  2. Inventory density = NEAR-HARD, above a small minimum. A candidate with a
     real inventory footprint (≥ _MIN_TIER_INVENTORY hotels nearby) is ranked
     strictly above any candidate without one — this rule kills "Lisbon,
     Arkansas" and the Victoria homonyms a prominence-ranked geocoder gets
     wrong. The minimum exists because S-G9 proved the 0-vs-1 version of this
     tier causes wrong-country resolutions (Budapest→Georgia US, La Défense→
     Al Aïn AE): a 1-hotel micro-homonym must never silently outrank a
     world-famous zero-inventory city — that configuration falls through to
     the same-tier scoring and, when genuinely close cross-country, to ONE
     clarifying question. Below the minimum (and among same-tier candidates),
     the count still contributes its bounded soft weight.
  3. Locale prior = bounded soft boost (a pt user's "Lisboa" leans PT).
  4. GPS proximity = bounded, BAND-LIMITED soft boost (Pelias: proximity breaks
     ties within a prominence band; it must NEVER override an explicit distant
     destination — "hotel in New York" typed from Paris still resolves New York).
  5. Feature-type prior + Mapbox rank position (the only relevance proxy v6 gives).

Decision policy (geo memo §C.6): a decisive top-1 selects silently; a genuine
cross-country/region near-tie asks ONE clarifying question built as a template
from the candidates' `place_formatted` — never a candidate dump, never a loop
(the concierge's anti-clarification-loop guard already enforces "ask once").
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

from hotel_search_agent.inventory import DEFAULT_RADIUS_KM, InventoryProvider, haversine_km
from hotel_search_agent.mapbox_client import GeocodeCandidate

# ── Ranking weights (named constants — tune on the 41-case geo eval) ────────────
# Feature-type prior: a city (`place`) is the best hotel-destination anchor; a
# whole state/county (`region`/`district`) the worst. Probed live: "Orange County"
# is a district, "La Défense" is not a v6 place at all (→ Search-Box tier).
_TYPE_PRIOR = {"place": 5.0, "locality": 4.0, "neighborhood": 4.0, "district": 2.0, "region": 1.0}
_TYPE_PRIOR_DEFAULT = 3.0

_W_RANK = 0.3          # Mapbox list position: rank 0 best; weak (position is a proxy, not truth)
_W_LOCALE = 1.0       # candidate country == user locale country
_W_INVENTORY = 2.0    # soft magnitude among candidates that HAVE inventory (the hard tier does the rest)
_W_PROXIMITY = 0.5    # GPS closeness — deliberately small so it can only break ties (band rule)

_INVENTORY_SOFT_CAP = 30   # counts above this add no more soft weight (bounded)
_MIN_TIER_INVENTORY = 3    # the NEAR-HARD tier needs at least this many hotels nearby (S-G10:
                           # 1-2 can be a single hotel in a neighboring town — micro-homonym trap)
_PROXIMITY_FULL_KM = 25.0  # within this, full (small) proximity credit; decays to 0 by _PROXIMITY_ZERO_KM
_PROXIMITY_ZERO_KM = 500.0

# A decisive lead: top-1 beats top-2 by this within the same inventory tier → select
# silently; otherwise, if they differ by country/region, ask. Scaled to the weights
# above (a full feature-type band ≈ 1.0, a strong inventory edge ≈ 2.0).
_MARGIN_SELECT = 1.5

# Only ask about candidates that are a GENUINELY different place — at least this far
# from the top candidate. Adjacent near-duplicates (NYC vs "West New York, NJ" ~8 km,
# a city vs its own suburb) resolve to essentially the same search area, so asking
# about them is noise; true homonyms (Victoria BC vs Australia, Chester GB vs PA) are
# thousands of km apart and worth one question.
_MIN_CLARIFY_SEPARATION_KM = 100.0

_MAX_CLARIFY_OPTIONS = 3

# 2026-10-29 (prod, 97 conversations after #173): « Milano » asked against a
# hamlet called Milan near Treviso, « Brooklyn » against Brooklyn (Maryland),
# « Palm Springs » against a neighbourhood of Hialeah, and « Mantova » resolved
# to « Cascina Mantova », a farmstead near Monza with Milan's inventory around
# it. Mapbox gives no population, but every place it returns carries its own
# extent (`bbox`): a fact about the place, not about the words. A candidate
# this many times smaller than an exact-name city of the request is not the
# place a traveller names (`_important_survivors`).
_EXTENT_DOMINANCE = 8.0
#: The Mapbox types whose extent says how big a destination is. A region, a
#: district or a country has an administrative extent of another order: it
#: never outweighs a city this way.
_EXTENT_TYPES = frozenset({"place", "locality", "neighborhood"})


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: GeocodeCandidate
    score: float
    inventory: int

    @property
    def in_inventory_tier(self) -> bool:
        """NEAR-HARD tier membership — requires _MIN_TIER_INVENTORY, not just >0
        (see module docstring rule 2: the 0-vs-1 version of this tier is exactly
        the S-G9 Budapest→Georgia / La Défense→Al Aïn wrong-country mechanism)."""
        return self.inventory >= _MIN_TIER_INVENTORY


@dataclass(frozen=True)
class Resolution:
    """Outcome of `resolve`. `decision`:
    - "select"  → `chosen` is the winning candidate (run the echo sanity check on it);
    - "clarify" → `options` (2-3) + `question` (template) — ask, do not geocode;
    - "none"    → no candidate survived (empty input or an empty hard-filter)."""

    decision: str
    chosen: GeocodeCandidate | None = None
    options: list[GeocodeCandidate] = field(default_factory=list)
    question: str | None = None
    scored: list[ScoredCandidate] = field(default_factory=list)


def _proximity_credit(candidate: GeocodeCandidate, proximity: tuple[float, float] | None) -> float:
    if proximity is None:
        return 0.0
    dist = haversine_km(proximity[0], proximity[1], candidate.latitude, candidate.longitude)
    if dist <= _PROXIMITY_FULL_KM:
        return 1.0
    if dist >= _PROXIMITY_ZERO_KM:
        return 0.0
    # Linear decay between the two radii — a bounded [0,1] closeness, never enough
    # (× _W_PROXIMITY) to flip a feature-type band or the inventory tier.
    return (_PROXIMITY_ZERO_KM - dist) / (_PROXIMITY_ZERO_KM - _PROXIMITY_FULL_KM)


def extent_km2(candidate: GeocodeCandidate) -> float | None:
    """The area of the candidate's bounding box in km², or None without one."""
    if candidate.bbox is None:
        return None
    min_lon, min_lat, max_lon, max_lat = candidate.bbox
    mid = math.radians((min_lat + max_lat) / 2)
    height = abs(max_lat - min_lat) * 111.0
    width = abs(max_lon - min_lon) * 111.0 * max(math.cos(mid), 0.01)
    return height * width


def _is_named(candidate: GeocodeCandidate, names: frozenset[str]) -> bool:
    return bool(names) and _name_fold(candidate.name) in names


def _important_survivors(
    survivors: list[GeocodeCandidate],
    names: frozenset[str],
    inventory_of: dict[int, int],
) -> list[GeocodeCandidate]:
    """`survivors` without the candidates a far bigger city of the request
    outweighs (2026-10-29). A candidate X goes when some candidate Y is named
    exactly as asked (`names`, the request's own spellings), is a city-scale
    feature (`_EXTENT_TYPES`) and covers at least `_EXTENT_DOMINANCE` times
    X's extent, and:
    - X does not carry the name as asked (« Cascina Mantova » for
      « Mantova »): a bigger place of that very name exists, whatever the
      inventory around X;
    - or X does, and Y has a real inventory footprint too (`_MIN_TIER_INVENTORY`):
      between two credible homonyms, the city outweighs the hamlet (Milano /
      Milan near Treviso, Brooklyn NY / MD, Palm Springs CA / Hialeah). A
      homonym without hotels never outweighs one with them: Saint-Denis of
      La Réunion is larger than the 93's and stays behind it.
    Both extents must be known: a candidate without a `bbox` (Search Box, an
    older fixture) is never removed nor removes anything."""
    if not names:
        return survivors
    bigger = [
        (y, extent_km2(y)) for y in survivors
        if y.feature_type in _EXTENT_TYPES and _is_named(y, names) and extent_km2(y)
    ]
    if not bigger:
        return survivors
    kept: list[GeocodeCandidate] = []
    for x in survivors:
        x_extent = extent_km2(x)
        outweighed = x_extent is not None and any(
            y is not x
            and y_extent is not None
            and y_extent >= _EXTENT_DOMINANCE * x_extent
            and (not _is_named(x, names) or inventory_of[id(y)] >= _MIN_TIER_INVENTORY)
            for y, y_extent in bigger
        )
        if not outweighed:
            kept.append(x)
    return kept or survivors


def _region_matches(candidate: GeocodeCandidate, region_hint: str) -> bool:
    needle = region_hint.strip().lower()
    if not needle:
        return True
    hay = f"{candidate.region} {candidate.place_formatted} {candidate.place_name}".lower()
    return needle in hay


def _score(
    candidate: GeocodeCandidate,
    inventory_count: int,
    *,
    locale_country: str | None,
    proximity: tuple[float, float] | None,
) -> float:
    type_prior = _TYPE_PRIOR.get(candidate.feature_type, _TYPE_PRIOR_DEFAULT)
    score = type_prior - _W_RANK * candidate.rank
    if inventory_count > 0:
        score += _W_INVENTORY * (min(inventory_count, _INVENTORY_SOFT_CAP) / _INVENTORY_SOFT_CAP)
    if locale_country and candidate.country_code == locale_country.upper():
        score += _W_LOCALE
    score += _W_PROXIMITY * _proximity_credit(candidate, proximity)
    return score


def _name_fold(value: str | None) -> str:
    """Case/diacritic-insensitive name for EXACT-name comparison ("Défense" ==
    "defense") — deliberately simpler than geo_guards' transliterating echo
    fold: this compares two short proper names, not free text."""
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _tokens(folded: str) -> list[str]:
    """Alphanumeric words of an already-folded name. Punctuation is dropped
    rather than kept as a token: "74 - Disneyland" must count 1 extra word, not 2."""
    return [tok for tok in re.split(r"[^a-z0-9]+", folded) if tok]


def _landmark_key(value: str | None) -> tuple[str, ...]:
    """Comparable word tuple for a landmark name: diacritics folded, punctuation
    dropped, a leading article removed.

    Punctuation MUST go through the same normalisation as the request, not just
    the diacritics `_name_fold` handles: "Champs-Élysées" folds to
    "champs-elysees", which is not the string "champs elysees", so comparing the
    folded strings denied the exact-name bonus to the real Paris district and
    handed it to a same-named district in Évry 27 km away — which then won."""
    words = _tokens(_name_fold(value))
    if words and words[0] in _LEADING_ARTICLE_WORDS:
        return tuple(words[1:])
    return tuple(words)


def _differs_by_place(a: GeocodeCandidate, b: GeocodeCandidate) -> bool:
    """True when two candidates denote genuinely different places (different
    country, or different region within a country) — the case worth asking about.
    Same country + same region = the same place expressed twice (city vs its
    province), not a user-visible ambiguity."""
    if a.country_code != b.country_code:
        return True
    return a.region.strip().lower() != b.region.strip().lower()


_CLARIFY_ONE: dict[str, str] = {
    "fr": "Vouliez-vous dire {label} ?",
    "en": "Did you mean {label}?",
    "es": "¿Querías decir {label}?",
    "it": "Intendevi {label}?",
    "de": "Meintest du {label}?",
    "pt": "Quis dizer {label}?",
    "nl": "Bedoelde je {label}?",
}

_CLARIFY_MANY: dict[str, str] = {
    "fr": "Plusieurs endroits portent ce nom — lequel vouliez-vous dire : {joined} ?",
    "en": "There are a few places by that name — which did you mean: {joined}?",
    "es": "Hay varios lugares con ese nombre — ¿cuál querías decir: {joined}?",
    "it": "Ci sono più luoghi con questo nome — quale intendevi: {joined}?",
    "de": "Es gibt mehrere Orte mit diesem Namen — welchen meintest du: {joined}?",
    "pt": "Há vários lugares com esse nome — qual quis dizer: {joined}?",
    "nl": "Er zijn meerdere plaatsen met deze naam — welke bedoelde je: {joined}?",
}

# The separator before the LAST item in a joined list ("A, B{sep}C") — French/
# Portuguese drop the comma before the conjunction, English/German/Dutch keep
# it; Spanish/Italian follow the French convention here.
_CLARIFY_LAST_SEP: dict[str, str] = {
    "fr": " ou ",
    "en": ", or ",
    "es": " o ",
    "it": " o ",
    "de": ", oder ",
    "pt": " ou ",
    "nl": ", of ",
}


def _clarify_question(options: list[GeocodeCandidate], language: str | None = None) -> str:
    """Deterministic template — the options are differentiated by their
    `place_formatted` context (country/region), exactly what a homonym needs.
    Localized for the 7 languages the concierge can answer in (S-CX2, audit
    F3/F5, widened by UX2): this question can reach the customer verbatim (the
    emit event replaces the model's text, and the synthesis fallback serves
    leaf text as-is), so it must speak the user's language."""
    labels = []
    for c in options:
        ctx = c.place_formatted or c.country_code or ""
        labels.append(f"{c.name} ({ctx})" if ctx else c.name)
    lang = language if language in _CLARIFY_ONE else "en"
    if len(labels) == 1:
        return _CLARIFY_ONE.get(lang, _CLARIFY_ONE["en"]).format(label=labels[0])
    sep = _CLARIFY_LAST_SEP.get(lang, _CLARIFY_LAST_SEP["en"])
    joined = ", ".join(labels[:-1]) + sep + labels[-1]
    return _CLARIFY_MANY.get(lang, _CLARIFY_MANY["en"]).format(joined=joined)


_CITY_NEEDED: dict[str, str] = {
    "fr": "Près de « {label} » — dans quelle ville cherchez-vous ?",
    "en": 'Near "{label}" — which city are you looking in?',
    "es": 'Cerca de "{label}" — ¿en qué ciudad buscas?',
    "it": 'Vicino a "{label}" — in quale città stai cercando?',
    "de": "„{label}“ in der Nähe — in welcher Stadt suchst du?",
    "pt": 'Perto de "{label}" — em que cidade está a procurar?',
    "nl": 'In de buurt van "{label}" — in welke stad zoek je?',
}


def city_needed_question(zone: str, language: str | None = None) -> str:
    """Ask WHICH CITY, for a named zone that arrived with no anchor at all.

    Deterministic template, localized for the 7 languages like
    `_clarify_question` above and for the same reason (S-CX2: this text can
    reach the customer verbatim).

    Option-less ON PURPOSE, unlike every other clarify in this module. The only
    city we could put in front of the user here is the one an IP-biased lookup
    returns, and naming it would anchor them on precisely the answer we just
    decided we cannot trust: measured from the prod container, "gare de lyon"
    yields ten Lyon tram stops and the Paris station the user means is absent
    from the candidate list entirely. A question with no options is honest; a
    question offering only Lyon is a wrong answer wearing a question mark.
    """
    label = (zone or "").strip()
    template = _CITY_NEEDED.get(language or "", _CITY_NEEDED["en"])
    return template.format(label=label)


_UNRESOLVED: dict[str, str] = {
    "fr": "Je n'ai pas réussi à situer « {label} ». Vous pouvez préciser la ville ou le pays ?",
    "en": 'I couldn\'t place "{label}". Could you tell me the city or the country?',
    "es": 'No he conseguido ubicar "{label}". ¿Puedes indicarme la ciudad o el país?',
    "it": 'Non sono riuscito a localizzare "{label}". Puoi indicarmi la città o il paese?',
    "de": "Ich konnte „{label}“ nicht finden. Kannst du mir die Stadt oder das Land nennen?",
    "pt": 'Não consegui localizar "{label}". Pode indicar a cidade ou o país?',
    "nl": 'Ik kon "{label}" niet plaatsen. Kun je de stad of het land noemen?',
}


def unresolved_question(place: str, language: str | None = None) -> str:
    """Say the place could not be placed, and ask for its city or country.

    2026-10-27, prod traces (Galveston, Ojai, Cuneo, Salzburg): the geocoder
    answered, but with a fuzzy namesake the echo guard rightly refused, and the
    turn then read as a search outage. Option-less for the reason
    `city_needed_question` gives: every candidate left is one the echo guard
    has just refused. Same 7 languages, same template-only rendering."""
    label = (place or "").strip()
    template = _UNRESOLVED.get(language or "", _UNRESOLVED["en"])
    return template.format(label=label)


#: Landmark (tier-2 / Search Box) feature-type prior. Deliberately NOT
#: `_TYPE_PRIOR`: the priors genuinely INVERT between the two questions. For a
#: city query a `place` is the best possible answer, so it scores highest up
#: there. For a landmark query a `place` is the WORST — the user named
#: something finer than a city ("les champs élysées"), so resolving to the city
#: itself silently widens the search to the whole metro. The named district and
#: the POI are what "around X" means.
_LANDMARK_TYPE_PRIOR = {
    "neighborhood": 4.5, "poi": 4.0, "locality": 4.0,
    "address": 3.0, "place": 2.0, "district": 1.5, "region": 1.0,
}

#: Mapbox's own list position, for landmarks only — 6x weaker than `_W_RANK`.
#: On the city path Mapbox's order is the only relevance proxy v6 gives, so it
#: earns 0.3. Here it is the very thing we distrust: this endpoint's ordering IS
#: the IP-biased ordering. At 0.3 it contributes up to 2.7 points across a
#: 10-candidate list — more than the whole city-anchor term — and it showed:
#: a district 27 km outside the named city outranked the real one purely for
#: being 5 positions higher. Keep it only as a deterministic last tie-break.
_W_LANDMARK_RANK = 0.05

#: Landmark ranking weights, on top of the shared ones above.
#: An EXACT name match is the strongest signal a POI list offers: querying
#: "gare de lyon" returns both a business literally called "gare lyon" in the
#: 19th (4 km off) and the actual "Gare de Lyon" station — only the name tells
#: them apart, and Mapbox ranks the wrong one first.
_W_LANDMARK_EXACT_NAME = 3.0
#: Businesses NAMED AFTER a landmark ("Onitsuka Tiger Champs Elysées, Paris
#: Flagship", "Le Relais de Montmartre") are usually geographically fine but
#: make a terrible search-origin label — `resolved_place` reaches the customer
#: through `active_filters.distance_origin`. A small penalty per word Mapbox
#: added that the user never said breaks position ties in favour of the clean
#: feature.
#:
#: Counted as "tokens the candidate name has and the request doesn't", NOT as
#: "the request is a substring of the name": the substring version measured the
#: wrong thing and picked the worst candidate. Probed on "disneyland paris" —
#: a rental listing called "74 - Disneyland in Paris" (in the 3rd
#: arrondissement, 30 km off) escaped the penalty entirely because the
#: interleaved "in" broke the substring, while "Parking Disneyland Paris" at
#: the actual park was penalised for its one extra word.
_W_LANDMARK_NAME_BLOAT = 0.25
#: …and the penalty is capped, so a landmark whose official name is simply long
#: ("JFK" → "John F. Kennedy International Airport") cannot be demoted below a
#: worse-placed candidate on verbosity alone. Below both the exact-name bonus
#: and the inventory weight, on purpose: this only ever breaks near-ties.
_MAX_LANDMARK_NAME_BLOAT = 1.5

#: Leading articles, dropped from BOTH sides before the exact-name comparison.
#: Users type them and official feature names don't ("les champs élysées" vs the
#: "Champs Élysées" neighborhood), so without this the article denies the bonus
#: to the real place and hands it to any homonym business that happens to
#: include it. Measured: it made "Les Champs Elysées", a venue in Le Havre
#: 200 km away, outrank the actual Paris district.
_LEADING_ARTICLE_WORDS = frozenset({"les", "le", "la", "l", "the", "des", "de", "du"})

#: A VERIFIED city anchor — the v6 candidate that echoed the city the user
#: actually named — is a far sharper prior than a GPS fix, and it gets its own
#: tight scale. `_W_PROXIMITY`'s 25→500 km band exists to stop a device fix
#: overriding an explicit distant destination (the Pelias rule) and is
#: deliberately kept for that; applied to a landmark inside a named city it is
#: useless: it scored the real Champs-Élysées and a same-named district in Évry
#: 27 km away within 0.002 of each other, and the Évry one won on its feature
#: type. Within a named city, 27 km is not a near-tie — it is the wrong place.
#:
#: Only ever a BONUS for being near the anchor, never a penalty for being far,
#: and only fed from a city the user named — so it cannot reproduce the failure
#: the band rule guards against ("a hotel in New York" typed from Paris).
_W_LANDMARK_CITY_ANCHOR = 2.5
_LANDMARK_ANCHOR_FULL_KM = 5.0
_LANDMARK_ANCHOR_ZERO_KM = 40.0

#: The landmark ranker's own inventory cap, far above the city resolver's 30.
#: For CITY disambiguation 30 is plenty — the question is only "does this
#: candidate have a real footprint". For a POI homonym the MAGNITUDE is the
#: discriminator: Paris (785 hotels within 25 km) and Le Havre (a couple of
#: dozen) both blow past 30, so at that cap they score identically and a tie is
#: settled by whichever name Mapbox happened to phrase like the request. A
#: wider range restores the signal that actually separates them.
_LANDMARK_INVENTORY_SOFT_CAP = 300
#: A candidate with NO bookable inventory anywhere near it cannot be the place
#: a day-use customer meant. Demoted hard (below every candidate that has
#: some), never removed — if they ALL have none, the least-bad one still wins
#: and the echo guard remains the final say.
_LANDMARK_NO_INVENTORY_PENALTY = 6.0


def _city_anchor_credit(
    candidate: GeocodeCandidate, anchor: tuple[float, float] | None
) -> float:
    """[0,1] closeness to a verified city anchor, on the tight landmark scale."""
    if anchor is None:
        return 0.0
    dist = haversine_km(anchor[0], anchor[1], candidate.latitude, candidate.longitude)
    if dist <= _LANDMARK_ANCHOR_FULL_KM:
        return 1.0
    if dist >= _LANDMARK_ANCHOR_ZERO_KM:
        return 0.0
    return (_LANDMARK_ANCHOR_ZERO_KM - dist) / (
        _LANDMARK_ANCHOR_ZERO_KM - _LANDMARK_ANCHOR_FULL_KM
    )


def rank_landmark(
    candidates: list[GeocodeCandidate],
    *,
    requested_zone: str,
    inventory: InventoryProvider,
    proximity: tuple[float, float] | None = None,
    city_anchor: tuple[float, float] | None = None,
    radius_km: float = DEFAULT_RADIUS_KM,
    city_query: bool = False,
) -> GeocodeCandidate | None:
    """Pick the best Search-Box candidate for a named landmark, or None.

    `city_query` (2026-10-29): the request named a CITY and nothing finer —
    the Search-Box tier only runs for one when the geocoder returned nothing
    (a timeout). The priors are then the city ones (`_TYPE_PRIOR`: a `place`
    first), not the landmark ones, which rank a business above the town.

    SELECT-ONLY on purpose — no clarify branch. `resolve` above asks the user
    when two CITIES are a genuine near-tie, which is a real question; a POI
    list is not ("did you mean Azur Café or Unisex?"). So this ranks and
    commits, and the caller's echo-back guard stays the veto.

    Exists because Mapbox's top-1 for this endpoint is biased by the caller's
    egress IP (`searchbox_client` docstring): trusting it made the leaf's
    landmark resolution a function of which datacenter the container runs in.
    Ranking the whole list on signals Mapbox cannot know — our inventory, the
    exact name asked for — is what makes the outcome ours and reproducible.
    """
    if not candidates:
        return None
    wanted = _landmark_key(requested_zone)
    wanted_tokens = set(wanted)

    def score(candidate: GeocodeCandidate) -> float:
        count = inventory.count_near(candidate.latitude, candidate.longitude, radius_km=radius_km)
        priors = _TYPE_PRIOR if city_query else _LANDMARK_TYPE_PRIOR
        value = priors.get(candidate.feature_type, _TYPE_PRIOR_DEFAULT)
        value -= _W_LANDMARK_RANK * candidate.rank
        if count > 0:
            value += _W_INVENTORY * (
                min(count, _LANDMARK_INVENTORY_SOFT_CAP) / _LANDMARK_INVENTORY_SOFT_CAP
            )
        else:
            value -= _LANDMARK_NO_INVENTORY_PENALTY
        value += _W_PROXIMITY * _proximity_credit(candidate, proximity)
        value += _W_LANDMARK_CITY_ANCHOR * _city_anchor_credit(candidate, city_anchor)
        name = _landmark_key(candidate.name)
        if name == wanted:
            value += _W_LANDMARK_EXACT_NAME
        elif wanted_tokens:
            extra = len([t for t in name if t not in wanted_tokens])
            value -= min(_W_LANDMARK_NAME_BLOAT * extra, _MAX_LANDMARK_NAME_BLOAT)
        return value

    # `max` keeps the first of equal scores, and the input is in Mapbox rank
    # order — so a true tie falls back to the vendor's opinion, deterministically.
    return max(candidates, key=score)


def resolve(
    candidates: list[GeocodeCandidate],
    *,
    inventory: InventoryProvider,
    country_hint: str | None = None,
    region_hint: str | None = None,
    locale_country: str | None = None,
    proximity: tuple[float, float] | None = None,
    radius_km: float = DEFAULT_RADIUS_KM,
    requested_name: str | None = None,
    language: str | None = None,
    requested_names: tuple[str, ...] = (),
) -> Resolution:
    """Re-rank `candidates` and decide select / clarify / none. Pure and
    deterministic given the injected `inventory` provider.

    `requested_name` (the city label the user actually typed) powers ONE
    asymmetric rule: when the top candidate's name is an EXACT (fold-
    insensitive) match for what was asked and a would-be clarify option's
    name is not, that option is not a genuine alternative — "Fort
    Lauderdale" typed exactly must not trigger "did you mean Lauderdale,
    Minnesota?" (S-G10). Asymmetric on purpose: it only ever TRIMS options
    when the top is exact; a non-exact top (fuzzy resolution) never
    suppresses anything, and two exact-name homonyms (Budapest HU/GA,
    Victoria) still clarify.

    `requested_names` (2026-10-29): every spelling the request gave the place
    (`requested_name` included) — the user's word and the canonical name. A
    candidate a far bigger city of one of these names outweighs is dropped
    before ranking (`_important_survivors`)."""
    survivors = list(candidates)

    # 1 — hard filters (a stated country/region removes, never boosts).
    if country_hint:
        ch = country_hint.upper()
        survivors = [c for c in survivors if c.country_code == ch]
    if region_hint:
        matched = [c for c in survivors if _region_matches(c, region_hint)]
        # Only apply the region filter when it actually matches something —
        # a hint expressed differently from Mapbox's context must not zero out.
        if matched:
            survivors = matched

    if not survivors:
        return Resolution(decision="none")

    counts = {id(c): inventory.count_near(c.latitude, c.longitude, radius_km=radius_km) for c in survivors}
    names = frozenset(
        _name_fold(n) for n in (requested_name, *requested_names) if n and _name_fold(n)
    )
    survivors = _important_survivors(survivors, names, counts)

    # 2-5 — score every survivor.
    scored: list[ScoredCandidate] = []
    for c in survivors:
        cnt = counts[id(c)]
        scored.append(
            ScoredCandidate(
                candidate=c,
                score=_score(c, cnt, locale_country=locale_country, proximity=proximity),
                inventory=cnt,
            )
        )
    # Sort by inventory tier first (near-hard), then score. Stable within ties on
    # Mapbox rank (survivors kept their input order, which is rank order).
    scored.sort(key=lambda s: (s.in_inventory_tier, s.score), reverse=True)

    top = scored[0]
    if len(scored) == 1:
        return Resolution(decision="select", chosen=top.candidate, scored=scored)

    second = scored[1]

    # A candidate with a REAL inventory footprint always beats one without →
    # decisive, select. (Micro-inventory candidates are not in the tier, so
    # they can't win silently on 1 hotel — S-G9 findings.)
    if top.in_inventory_tier and not second.in_inventory_tier:
        return Resolution(decision="select", chosen=top.candidate, scored=scored)

    # Same inventory tier: a clear score lead selects silently.
    if top.score - second.score >= _MARGIN_SELECT:
        return Resolution(decision="select", chosen=top.candidate, scored=scored)

    # Close call. Ask ONLY about candidates that are a genuinely different place AND
    # competitive: a different country/region, far enough to be a distinct
    # destination (not an adjacent suburb sharing the same search area), in the same
    # inventory tier, and within the selection margin of the top.
    top_name_exact = _is_named(top.candidate, names)

    def _genuine_alternative(other: ScoredCandidate) -> bool:
        if other.in_inventory_tier != top.in_inventory_tier:
            return False
        if top.score - other.score >= _MARGIN_SELECT:
            return False
        if top_name_exact and not _is_named(other.candidate, names):
            return False
        if not _differs_by_place(top.candidate, other.candidate):
            return False
        sep = haversine_km(
            top.candidate.latitude, top.candidate.longitude,
            other.candidate.latitude, other.candidate.longitude,
        )
        return sep >= _MIN_CLARIFY_SEPARATION_KM

    contenders = [top.candidate] + [s.candidate for s in scored[1:] if _genuine_alternative(s)]
    if len(contenders) < 2:
        return Resolution(decision="select", chosen=top.candidate, scored=scored)

    options = contenders[:_MAX_CLARIFY_OPTIONS]
    return Resolution(
        decision="clarify",
        options=options,
        question=_clarify_question(options, language),
        scored=scored,
    )
