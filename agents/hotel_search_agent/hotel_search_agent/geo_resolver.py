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
  2. Inventory density = NEAR-HARD. A candidate with zero bookable Dayuse hotels
     nearby is ranked strictly below ANY candidate that has some — this one rule
     kills "Lisbon, Arkansas" and the Victoria homonyms a prominence-ranked
     geocoder gets wrong. Among candidates that all have (or all lack) inventory,
     the magnitude is a bounded soft weight.
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
    def has_inventory(self) -> bool:
        return self.inventory > 0


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


def _differs_by_place(a: GeocodeCandidate, b: GeocodeCandidate) -> bool:
    """True when two candidates denote genuinely different places (different
    country, or different region within a country) — the case worth asking about.
    Same country + same region = the same place expressed twice (city vs its
    province), not a user-visible ambiguity."""
    if a.country_code != b.country_code:
        return True
    return a.region.strip().lower() != b.region.strip().lower()


def _clarify_question(options: list[GeocodeCandidate]) -> str:
    """Deterministic template — the options are differentiated by their
    `place_formatted` context (country/region), exactly what a homonym needs."""
    labels = []
    for c in options:
        ctx = c.place_formatted or c.country_code or ""
        labels.append(f"{c.name} ({ctx})" if ctx else c.name)
    if len(labels) == 1:
        return f"Did you mean {labels[0]}?"
    joined = ", ".join(labels[:-1]) + f", or {labels[-1]}"
    return f"There are a few places by that name — which did you mean: {joined}?"


def resolve(
    candidates: list[GeocodeCandidate],
    *,
    inventory: InventoryProvider,
    country_hint: str | None = None,
    region_hint: str | None = None,
    locale_country: str | None = None,
    proximity: tuple[float, float] | None = None,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> Resolution:
    """Re-rank `candidates` and decide select / clarify / none. Pure and
    deterministic given the injected `inventory` provider."""
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
    scored.sort(key=lambda s: (s.has_inventory, s.score), reverse=True)

    top = scored[0]
    if len(scored) == 1:
        return Resolution(decision="select", chosen=top.candidate, scored=scored)

    second = scored[1]

    # A candidate WITH inventory always beats one without → decisive, select.
    if top.has_inventory and not second.has_inventory:
        return Resolution(decision="select", chosen=top.candidate, scored=scored)

    # Same inventory tier: a clear score lead selects silently.
    if top.score - second.score >= _MARGIN_SELECT:
        return Resolution(decision="select", chosen=top.candidate, scored=scored)

    # Close call. Ask ONLY about candidates that are a genuinely different place AND
    # competitive: a different country/region, far enough to be a distinct
    # destination (not an adjacent suburb sharing the same search area), in the same
    # inventory tier, and within the selection margin of the top.
    def _genuine_alternative(other: ScoredCandidate) -> bool:
        if other.has_inventory != top.has_inventory:
            return False
        if top.score - other.score >= _MARGIN_SELECT:
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
        question=_clarify_question(options),
        scored=scored,
    )
