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


def _clarify_question(options: list[GeocodeCandidate], language: str | None = None) -> str:
    """Deterministic template — the options are differentiated by their
    `place_formatted` context (country/region), exactly what a homonym needs.
    Localized fr/en (S-CX2, audit F3/F5): this question can reach the customer
    verbatim (the emit event replaces the model's text, and the synthesis
    fallback serves leaf text as-is), so it must speak the user's language."""
    labels = []
    for c in options:
        ctx = c.place_formatted or c.country_code or ""
        labels.append(f"{c.name} ({ctx})" if ctx else c.name)
    if language == "fr":
        if len(labels) == 1:
            return f"Vouliez-vous dire {labels[0]} ?"
        joined = ", ".join(labels[:-1]) + f" ou {labels[-1]}"
        return f"Plusieurs endroits portent ce nom — lequel vouliez-vous dire : {joined} ?"
    if len(labels) == 1:
        return f"Did you mean {labels[0]}?"
    joined = ", ".join(labels[:-1]) + f", or {labels[-1]}"
    return f"There are a few places by that name — which did you mean: {joined}?"


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
) -> GeocodeCandidate | None:
    """Pick the best Search-Box candidate for a named landmark, or None.

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
        value = _LANDMARK_TYPE_PRIOR.get(candidate.feature_type, _TYPE_PRIOR_DEFAULT)
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
    Victoria) still clarify."""
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

    # 2-5 — score every survivor.
    scored: list[ScoredCandidate] = []
    for c in survivors:
        cnt = inventory.count_near(c.latitude, c.longitude, radius_km=radius_km)
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
    requested_fold = _name_fold(requested_name)
    top_name_exact = bool(requested_fold) and _name_fold(top.candidate.name) == requested_fold

    def _genuine_alternative(other: ScoredCandidate) -> bool:
        if other.in_inventory_tier != top.in_inventory_tier:
            return False
        if top.score - other.score >= _MARGIN_SELECT:
            return False
        if top_name_exact and _name_fold(other.candidate.name) != requested_fold:
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
