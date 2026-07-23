# Ranking eval protocol (A8-a) — S-G9

**Purpose**: make "does AgentB2C need a hotel reranker?" decidable. AgentB2C's
`response_bridge` has no reranker today — it shows the first `MAX_RESULTS` (5)
hotels MCP_B2C's `search_offers` returns for the resolved anchor
(`agents/hotel_search_agent/hotel_search_agent/response_bridge.py`). The
07/22 audit could not measure whether that is already close to optimal or
whether a client-side reranker would meaningfully help, because the harness
at the time dropped lat/lon/distance from the record entirely. S-G3/A8-a
(2026-07-23) added that instrumentation to the cards; this is the first use
of it, exactly as planned in `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md`
§5 (A8 — "instrument first, rank later — a) instrument + eval first").

Script: `scripts/eval_ranking.py`. Never calls `/v3/chat` itself — it only
reads an already-produced `eval_pack.runner` report (no extra live LLM calls
beyond the gate replay itself) and separately queries MCP_B2C directly for
the ground-truth candidate pool.

## Method

For each case in a gate replay report, take its **first turn** that both:
- returned `hotels` (non-empty), and
- has a resolved anchor (`active_filters.distance_origin.{latitude,longitude}`), and
- has a resolved `date` (`active_filters.date` — MCP requires one).

For that turn, independently call `search_offers` with the **same anchor,
date, time window and hard filters** the leaf itself would have used
(`size=50` to get a full page instead of the leaf's `size=5`):
- `lat`/`lon` = the turn's `distance_origin`
- `date` = the turn's resolved `date`
- `priceRangeMax` = the turn's `budget_max`, when set
- `hotelEquipmentIds` = the turn's `active_filters.amenities` keys mapped
  through the same closed table the leaf's model-facing schema uses
  (`hotel_search_agent/equipment_ids.py::EQUIPMENT_IDS` — kept as a static,
  documented copy in the script so it never has to import `agents/**`, same
  black-box discipline as S-G8's `eval_hardening.py`)
- `timeSlot` = the turn's `timeslot_start`/`timeslot_end`, floored/ceiled to
  the integer-hour window MCP accepts (same floor/ceil semantics as
  `datetime_resolver.py::resolve_search_timeslot`, re-derived inline rather
  than imported)
- the pool is then strict-filtered against the EXACT minutes-of-day window
  with the leaf's own semantics (`_offer_fits_exact_window` + the A4-c
  fallback to the unfiltered pool when the strict cut empties it, re-derived
  inline — S-G10, D5): the leaf excludes hotels whose offers don't fit the
  exact window, so a ground truth that skipped this filter would unfairly
  count those correct exclusions as ranking misses

This gives an **identical candidate pool** to the one the real search drew
from (same anchor, same hard filters) — the exact requirement from the audit
("pool de candidats identique... vérité de distance depuis les coords des
cartes... contraintes dures vérifiées").

Ground truth = every candidate in that pool ranked by haversine distance from
the anchor (using the pool's own per-hotel `lat`/`lon`, confirmed present on
every `search_offers` result). AgentB2C's shown top-5 (its actual `hotels`
this turn, in order) is scored against that ranking:

- **precision@5** = `|shown_top5 ∩ true_top_k| / k`, `k = min(5, pool_size)`
- **NDCG@5** = standard position-discounted gain, relevance `= max(0, 5 - true_rank)`
  for the shown hotels (0 for anything outside the true top-5 or not found in
  the pool at all), normalized by the ideal ordering's DCG.

## Deliberate scope limits (documented, not silent)

1. **Only the case's first hotel-bearing turn is scored.** A later "autres
   options" turn would need the internal pagination cursor
   (`profile.search_cursor`) to build the matching ground-truth *page* —
   that cursor isn't exposed by the public `/v3/chat` contract. Reconstructing
   it isn't needed to answer "is a reranker needed" for the dominant
   first-page case, so later pages are left out of this first pass rather
   than faked with an assumed offset.
2. **Amenity reconstruction is closed to what the leaf's own model-facing
   schema can express** (`EQUIPMENT_IDS`, 9 keys). This is exhaustive for
   what the leaf could have asked MCP for — not an approximation — because
   the model literally cannot request an amenity outside that enum.
3. **`room_equipment_ids` is not reconstructed** (the leaf itself never sets
   it — `equipment_ids.py` documents it as "out of v1, always popped").
4. **Cases with zero hotels shown, or without a resolved anchor/date, are
   excluded** and counted in `skip_counts_pre_pool` (never silently dropped
   — see the script's summary output). A case failing the *search itself*
   is a gate-1/gate-4 concern (wrong country / empty-geo), not a ranking
   question — there is nothing to rank when nothing was found.
5. **Not an agent-usa comparison.** The plan phrase "pool identique entre
   agents" is read here as "identical to what the SAME agent's own live call
   used" — comparing AgentB2C's shown order against ground truth for its own
   resolved destination. A future cross-agent ranking comparison would reuse
   this exact script against an agent-usa report; that comparison itself is
   explicitly OUT of this session's scope (reuse of the 07/22 results only).

## A live discovery this design surfaced

Probing `search_offers` directly (2026-07-23) to build this protocol showed
each hotel in the response already carries a `score` field and a
`matchReasons` array (e.g. `HasBookableOffers`, `RatingQuality`, `HighTier`)
— MCP_B2C's own default order blends review-quality/tier signals, not pure
proximity. This was never documented anywhere in this repo before. It matters
for a *future* reranker design decision (a client-side reranker would be
competing with/complementing that signal, not starting from a naive
distance-only baseline) but does **not** change this eval's metric: the audit
explicitly asked for a **distance** ground truth ("vérité de distance"), so
`precision@5`/`NDCG@5` here measure geographic relevance specifically, not a
verdict on whether MCP's own `score` is "wrong".

## How to read the result

- **High precision@5/NDCG@5** (close to 1.0): AgentB2C's un-reranked top-5
  already tracks proximity well — a client-side reranker would have low
  marginal value on this axis, matching the audit's A8-a decision to
  instrument first rather than build one speculatively.
- **Low precision@5/NDCG@5**: the un-reranked top-5 frequently surfaces
  hotels that are not among the nearest candidates for the resolved anchor —
  concrete, measured evidence that a reranker (or at minimum sorting by
  `distance_km`, already on every card) would improve relevance, sized
  per-suite (`by_suite` in the script's output) rather than as one blended
  number.

This is a first pass on one live replay's data, not a standing baseline —
rerun as inventory/model conditions change, exactly like the gate's own ×3
stability replay.

**Temporal-skew disclosure (S-G10, D5)**: the ground-truth pool is fetched at
*scoring* time, not at replay time — inventory drifts, and a `date` that has
passed makes MCP legitimately return a different (or empty) pool. The output
now stamps `ground_truth_fetched_at` and the summary counts
`n_samples_with_past_date` (printed as a warning): only trust the numbers when
the pool fetch closely follows the replay it scores. The mono-agent scope
(limit 5 below) was reviewed and accepted as-is on 2026-07-23 (decision D5) —
a cross-agent comparison stays a separate, future run of this same script
against an agent-usa report.
