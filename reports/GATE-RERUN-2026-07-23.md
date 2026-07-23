# Gate re-run — 81 cases ×3 + ranking-eval design (S-G9)

**Date**: 2026-07-23. **Branch**: `sg9-gate-rerun`. **Scope**: measurement only — no agent
code was changed to produce this report (`agents/**` untouched; `git diff --stat` at the
end of this session shows only `scripts/**`, `tests/**`, `reports/**`, `HANDOFF.md`).
Every bug below is reported, not fixed — that is this phase's explicit rule
(`phases/SG9-gate-rerun-eval-ranking.md`).

## Run conditions (as instructed: log them, don't assume the audit's)

| | |
|---|---|
| Model | `DAYUSE_MODEL=gpt-5.2` on all 3 local services (concierge, hotel-search leaf, faq leaf) — **explicitly chosen by Fabien** to match the 07/22 audit's own conditions (that audit forced `gpt-5.2` on both agents; the repo's committed default is `gpt-4o-mini`, confirmed unset in this run's environment otherwise). Verified live via `ps eww` on all 3 service PIDs and via `dayuse_metric=llm_call ... model=gpt-5.2` in `.run-logs/hotel_search_agent.log`. |
| Inventory | MCP staging (`https://mcp-server-production-bcbe.up.railway.app/mcp`, live Railway-hosted ES) — **not** the 07/22 audit's frozen local snapshot (8,701 hotels/22,177 plans/29 markets exported 2026-07-15). This is a *different* inventory source by design (the phase's own prerequisite says "MCP staging (ou prod ES si S-C débloquée)"); the audit's `frozen-snapshot vs live-staging` gap is a known, already-documented confound (`AUDIT-REWORK-2026-07.md` §5), not new here. |
| Execution | **Sequential**, one case at a time, 3 full passes back-to-back (`scripts/eval_replay_stability.py`, itself calling `python -u -m eval_pack.runner` 3×) — never concurrent, exactly to avoid the 07/22 run's own documented confound ("trois partitions concurrentes… expose les limites de timeout"). |
| Services | 3 local services (`bash scripts/run_local.sh`), smoke-tested green before the runs (`scripts/smoke_e2e.py`: ack 73 ms, search 18.5 s, faq 26.4 s — faq's slow/degraded reply is the already-known staging FAQ-MCP flakiness, see Finding 7). |
| Case set | The 81-case critical gate: `geo.jsonl` (41) + `multiturn.jsonl` (27) + `prod_wounds.jsonl` (13), read straight from the fixtures via `eval_replay_stability.critical_suite_case_ids()` — never hand-picked. |
| Harness | S-G8's hardening layer (`scripts/eval_hardening.py`) run on every raw report, unmodified. `dayuse_eval_pack/eval_pack/**` never touched (verified via `git status`/`git diff --stat`). |

## Executive summary

**Raw parity is far below both the 58/81 target and the audit's own 41/81 AgentB2C
baseline on this set: 29/81 (35.8%), 22/81 (27.2%), 24/81 (29.6%) across the 3 replays
(mean 25/81, 30.9%).** That headline number is real and should not be waved away — but
reading it as "the S-G1→S-G8 waves regressed geo/multi-turn" would be wrong. Digging into
*why*, case by case, surfaces a small number of concrete, mostly non-capability root
causes that account for the overwhelming majority of the gap:

1. **A confirmed code bug blocks Gate 7 entirely** (`distance_origin` never reaches the
   profile — see Finding 1). One-line fix, precisely located.
2. **A dominant, previously-uncharacterized failure mode** — the search genuinely
   succeeds (MCP called, no timeout, no exception) but the leaf returns no text, so the
   concierge honestly (and correctly, per its own contract) reports a degraded leaf. This
   is concentrated almost entirely in multi-turn conversations under `gpt-5.2` and alone
   accounts for 14–15 of ~52–59 failures per run (Finding 2).
3. **A documented, intentional design choice** (`requires_clarification` hardcoded
   `False`) means the harness can never credit "the agent asked a sensible disambiguating
   question" as safe — it always reads as a hard failure, even when the agent's prose is
   doing exactly the right thing (Finding 3; 5–7 cases/run).
4. **2 confirmed, 3/3-reproducible wrong-country resolutions** (Gate 1, the audit's most
   safety-critical gate) — real, and worth Fabien's attention regardless of the other
   confounds (Finding 4).
5. **A fixture/contract mismatch**, not an agent bug, affects 2 of the 4 GPS-flavored
   `prod_wounds` cases (Finding 5).
6. The remainder is the long-documented **staging-inventory confound** (city/country
   resolved correctly, 0 offers on this date/budget) plus a couple of narrower, precisely
   isolated gaps (Wien/Vienna exonym rejection, named-hotel follow-up turns).

Gate 6 (technical-timeout rate) is a clean, real **PASS**: 0.0% HTTP-level timeouts
across all 243 case-runs — a genuine, measured improvement over the audit's Chester/Milano
timeout instability, confirming S-G4's per-family budget work holds under `gpt-5.2`. That
success sits right next to Finding 2's *different* failure mode, which the timeout metric
was never built to see.

## Per-gate verdict

| # | Gate | Verdict | Basis |
|---|---|---|---|
| 1 | Zero wrong-country resolutions | **FAIL** | 2 confirmed, reproducible 3/3 across all runs (Finding 4). |
| 2 | Zero explicit-constraint loss across turns | **NON-MEASURABLE** | 0 `preserve_filters` check failures in any run — but the 2 families the audit specifically named as weak (`carry_same_time`, `zone_change`) are the same families Finding 2's bug hits 9/9 times (3 variants × 3 runs), so the comparison this gate needs never actually runs. A clean "0 failures" here is not evidence of "fixed." |
| 3 | Zero silent GPS/address/zone replacement | **FAIL / partially non-measurable** | 4/13 `prod_wounds` cases fail this axis every run: 2 are a fixture/contract mismatch (Finding 5, not an agent bug), 2 are a genuine, already-audit-documented address/zone geocoding gap (Finding 6). The `distance_origin` bug (Finding 1) also blocks a finer per-turn verification of this gate beyond the pack's own `distance_accuracy` assertion. |
| 4 | No empty-geo success when an offer exists in radius | **Confounded, not cleanly measurable** | Dominated by (a) safe clarifications mislabeled as failures (Finding 3), (b) the known staging-inventory gap (Finding 8), (c) one precisely-isolated echo-guard defect (Finding 9). |
| 5 | Parity ≥ 58/81 | **FAIL** | 29/81, 22/81, 24/81 (mean 25/81, 30.9%); even the S-G8 "excluding technical degradation" view (43.3%/33.3%/35.8%, mean 37.5%) stays well under target. |
| 6 | Technical-timeout rate below threshold | **PASS** | 0.0% HTTP-level timeout rate, all 3 runs, 243 case-runs, 0 timeouts. Real, measured improvement over the audit (S-G4 holds). |
| 7 | Ranking validated on identical candidates | **NON-MEASURABLE** | Blocked by Finding 1 (0 usable samples this run) — design + tooling are ready (`scripts/eval_ranking.py`, 15/15 unit tests, live MCP-probe-validated) and will produce real numbers the moment the 1-line fix lands. |

## Findings (root-caused, not fixed)

### Finding 1 — `distance_origin` never reaches the profile (blocks Gate 7) — confirmed code bug

`hotel_search_agent/response_bridge.py::emit_search_datapart` computes the search anchor
correctly and attaches it to the outgoing A2A payload — but as a **top-level sibling key**
of `profile_delta`, not nested inside it:

```python
payload: dict[str, Any] = {}
if results is not None:
    payload["results"] = results
if profile_delta:
    payload["profile_delta"] = profile_delta
distance_origin = state.get(_STATE_DISTANCE_ORIGIN_KEY)
if distance_origin and results:
    payload["distance_origin"] = distance_origin   # <- sibling of profile_delta, not inside it
```

The concierge only ever reads `profile_delta`:

```python
# agents/b2c_concierge/b2c_concierge/agent.py:843
delta = response.get("profile_delta") or {}
apply_profile_delta(profile, delta, message)
```

So `distance_origin` is silently dropped on **every single search turn**, GPS-anchored or
not — confirmed empirically: across all 17 hotel-bearing turns sampled from run 1,
`active_filters.distance_origin` was `None` in 100% of them, even though the per-hotel
`latitude`/`longitude`/`distance_km` (a separate, correctly-wired code path stamped
directly onto card dicts) were present and correct. Neither side's existing unit tests
catch this: `test_response_bridge.py::test_emit_includes_distance_origin_when_results_present`
only checks the leaf's (buggy) top-level placement in isolation, and
`test_active_filters.py`/`test_profile.py`'s `distance_origin` tests construct a
`SessionProfile(distance_origin=...)` directly, bypassing the real leaf→concierge wire
entirely — no test exercises the actual seam.

**Fix shape** (not applied — out of this session's zone): nest it inside `profile_delta`
before that dict is assigned to `payload["profile_delta"]`, and update the leaf's own test
to assert `data["profile_delta"]["distance_origin"]`. One line, precisely located.

**Impact**: this is why `scripts/eval_ranking.py` (Finding/Gate 7, see below) scored 0
samples this run — not a design flaw in the ranking eval, a direct, mechanical
consequence of this one nesting bug.

### Finding 2 — search succeeds, leaf returns no text, concentrated in multi-turn under gpt-5.2

The dominant driver of the low raw pass rate. Confirmed via `.run-logs/hotel_search_agent.log`
+ `.run-logs/b2c_concierge.log` cross-reference for representative cases (e.g.
`multiturn-carry_same_time_1`): every turn shows `concierge_metric=leaf_call
leaf=hotel_search ms=... status=ok` (no exception, no timeout) and a real
`tool_call agent=b2c_hotel_search tool=search_offers status=ok` — yet the concierge emits
`status=degraded` and the honest fallback *"I can't reach the hotel search right now, and
I'd rather not make anything up."* This is `agent.py`'s `leaf_text is None` branch
(`_run_leaf`, `agents/b2c_concierge/b2c_concierge/agent.py:288-337`): the leaf's own ADK
completion loop produced **zero usable text** this turn, with no exception thrown at all.

Measured concentration (exact phrase match on the fallback text, per run):

| Run | geo | multiturn | prod_wounds |
|---|---:|---:|---:|
| 1 | 0 | 37 | 0 |
| 2 | 0 | 38 | 1 |
| 3 | 2 | 33 | 0 |

Overwhelmingly (>94%) concentrated in multi-turn conversations, essentially absent from
single-turn geo searches and prod-wound cases. In the case-level failure ledger below this
maps to `multiturn-carry_same_time`, `multiturn-budget_change`, `multiturn-zone_change`,
`multiturn-date_availability_follow_up` (all 3 variants of each, **every run, 12/12
deterministic**) plus an intermittent `rooftop_pool` variant.

The most likely mechanism (documented as a hypothesis, not proven down to the exact ADK
internal call count): `hotel_search_agent`'s hard tool-call cap
(`MAX_TOOL_CALLS = 2`, `agent.py:85`, enforced by the shared library's
`dayuse_agent_common.tool_budget.make_tool_budget_callback`) interacts badly with
`gpt-5.2`'s tool-calling style specifically on **follow-up** turns (longer accumulated
context). The shared library's own docstring already flags this exact failure shape for a
*different* model ("some models (notably glm-5.2) ignore [soft guidance] and loop") — the
same shape shows up here for `gpt-5.2`, previously undetected because every prior live
verification in this project's history ran the committed default (`gpt-4o-mini`), never
`gpt-5.2` at this volume. Aggregate log counts across the (contiguous) service uptime show
leaf invocations split roughly 159:75:17 between 2, 3, and 1 LLM calls — consistent with,
but not conclusive proof of, a completion sometimes ending before a final summarization
turn happens. **Recommended next step for a dedicated fix session**: reproduce one
`carry_same_time`-style 2-turn conversation with verbose ADK/LiteLLM logging to see the
literal content of the leaf's last completion, then decide between raising
`MAX_TOOL_CALLS` for amendment-style routes or adding a forced-final-completion safety net
(same idea `tool_budget.py`'s own stop-message already uses, applied even when the budget
wasn't technically exceeded).

**This is not a timeout** (Gate 6 is a clean, real 0.0%) — it is a distinct mechanism the
timeout metric cannot see, and conflating the two would misread a real Gate-6 improvement
as covering a problem it doesn't.

### Finding 3 — `requires_clarification` is hardcoded `False` (documented, intentional — not a bug)

`agents/b2c_concierge/b2c_concierge/facade.py:435-452` documents this explicitly: *"the
spine attempts an answer or degrades honestly — it never blocks on a structured
clarification stage."* This is a real, deliberate architecture choice, not an oversight.
Its side effect: the S-G8 hardening layer's `outcome_counts.safe_clarification` is **0 in
all 3 runs** — not because the agent never asks for clarification (it clearly does, in
prose — see below), but because the field the classifier reads for that signal can never
be true.

Concretely, these cases get sensible, well-formed disambiguation prose but are scored as
outright raw failures (both by the pack's `min_hotels≥1` assertion and by the S-G8
3-way split, since neither can see the clarification):

- `geo-victoria-bc-e8076547`: *"…which "Victoria" you mean: Victoria (British Columbia,
  Canada), Victoria (Prince Edward Island, Canada), or Victoria (Newfoundland and
  Labrador)…"* — a real, previously-known-hard homonym (the audit itself rates this case
  "pas satisfaisant" for BOTH agents already; not new).
- `geo-nurnberg-de-c56de7e0` / `geo-nurnberg-umlaute`: *"did you mean Nürnberg (Bavaria,
  Germany) or Kürnberg (Schopfheim, Baden-Württemberg, Germany)?"*
- `geo-parma-it-not-in-table`: *"Parma (Italy) or Parma (Ohio, USA)?"*
- `geo-heidelberg-de-not-in-table`: *"Heidelberg (Baden-Württemberg, Germany) or
  Heidelberg (Victoria, Australia)?"*
- `geo-salerno-it-not-in-table`: *"Salerno (Italie) ou Balerno (City of Edinburgh,
  Écosse)?"*
- `geo-bremen-de-not-in-table`: *"Bremen (Bremen, Germany) or Bremen (Georgia, United
  States)?"*

Several of these ("not-in-table") are cities the S-G3 multi-candidate resolver was
specifically built to generalize to *without* a fixed disambiguation table — the fact that
it correctly identifies BOTH real candidates (rather than silently picking the wrong one,
Finding 4's failure mode) is exactly the resolver working as designed. It just gets zero
credit today. **This is a product/measurement decision for Fabien**, not a code defect:
either accept that the pack's raw score will always under-count safe behavior on
ambiguous-geo cases, or invest in wiring a real clarification signal end to end (a bigger
change, touching triage/facade/contract, explicitly out of this session's scope).

### Finding 4 — 2 confirmed, reproducible wrong-country resolutions (Gate 1)

Both reproduce identically in **all 3 runs** (not noise):

- **`geo-budapest-4d5b6c69`** — message: *"Hotel in Budapest **near Keleti station**,
  budget 150 euro"* (Keleti pályaudvar is an unambiguous, famous Budapest-Hungary
  landmark). Result: `country_code="US"`, **1 real hotel served**, priced in USD. This is
  the single most serious finding in this report — a wrong-country hotel was actually
  shown to a (synthetic) user, not just an empty/honest miss. Hypothesis (not proven):
  `geo_resolver.py`'s inventory-density tiebreak (`_W_INVENTORY`) can be gamed by a
  same-named-but-obscure US homonym when the correct major city currently has **zero**
  matching inventory on MCP staging — i.e., the tiebreaker built to prefer candidates
  *with* inventory can end up preferring the wrong candidate precisely because the
  staging snapshot doesn't yet reflect the correct city's real inventory. Needs a live
  probe (Mapbox candidate list + per-candidate inventory count for both "Budapest"s)
  before a fix is attempted.
- **`geo-la-defense-59b7c3f6`** — message: *"Hôtel près de La Défense, budget 200 euro"*
  (La Défense is Paris's well-known business district). Result: `country_code="AE"`
  (United Arab Emirates) every run, **0 hotels served** — so this specific instance never
  surfaced a wrong hotel, but the internal state is wrong regardless, and it is completely
  **invisible to the pack's own `hotel_countries`/`forbidden_hotel_countries` checks**,
  which only evaluate when hotels are actually returned (a harness blind spot worth its own
  note: a wrong-country resolution that also happens to have 0 inventory currently scores
  as if nothing happened). Root cause not diagnosed this session (ran out of scope/time
  for a live Mapbox probe) — flagged as an open, high-priority item for the next
  geo-focused session.

### Finding 5 — `native_context.geolocation` fixture shape ≠ the real facade contract (not an agent bug)

2 of the 4 GPS-flavored `prod_wounds` cases (`prod-wound-gps-paris-refinement`,
`prod-wound-gps-detroit-luxury`) send:

```json
"native_context": {"geolocation": {"lat": 48.9385, "lon": 2.4906}}
```

but the facade's `_parse_gps_anchor` (`agents/b2c_concierge/b2c_concierge/facade.py:580-611`)
only ever reads `client_geo_context.device.{latitude, longitude, accuracy_m, permission}` —
the shape S-G2 confirmed live against the actual vendored widget JS
(`handlers/send.js`). The code even documents, in a comment, that coding against
`native_context.geolocation` "would be coding against a guess with zero evidence — NOT
done here." Both cases fail `min_hotels≥1` and `distance_accuracy` with `checked=0` (no
anchor ever reached the profile, and the messages — *"a room in the daytime near me"* /
*"Day room near me this afternoon"* — carry no city name at all as a fallback). This is a
**fixture/contract mismatch in `dayuse_eval_pack`'s own request shape**, not a regression
in AgentB2C's (correctly-implemented, per the real widget) GPS handling. `dayuse_eval_pack/**`
is untouchable this session — flagged for Fabien to decide whether/how to update those 2
fixtures to the real `client_geo_context.device.*` shape.

### Finding 6 — 2 genuine, already-documented address/zone geocoding gaps (not new)

`prod-wound-orange-county-anchor` (a literal lat/lon origin, not GPS-fixture-dependent) and
`prod-wound-rue-lafayette-anchor` both resolve to 0 hotels with `distance_accuracy
checked=0` — real address/zone-precision misses, matching the audit's own prior finding
("Orange County: zone/metro et ancre exacte absentes"). Not a new regression; Axis G's
S-G3 multi-candidate resolver improved city-level resolution but zone/address-level
precision was explicitly flagged as still-open in the plan.

### Finding 7 — FAQ MCP staging degradation (already known, S-A)

`multiturn-non_search_support_1` flips PASS/FAIL across runs (unstable, see below) purely
because of the already-documented intermittent staging FAQ-MCP degradation (*"I can't
look up the Dayuse conditions right now"*) — same signature noted since S-A. Not
re-investigated further.

### Finding 8 — staging-inventory confound, still the largest single bucket

15–22 failures per run (`geo-milano-*`, `geo-zuerich-*`, `geo-munchen-umlaute`,
`geo-lisboa-accent`, `geo-barcelona-vs-barcelone`, several `-not-in-table` cases, etc.)
resolve `city`/`resolved_city`/`country_code` **correctly**, disclose the (possibly
auto-widened) budget honestly, and correctly report 0 offers with a real next-step
suggestion — this is the long-documented staging-vs-audit-snapshot inventory gap
(`AUDIT-REWORK-2026-07.md` §5), not a resolution defect. Included in full in the failure
ledger below for completeness, not re-litigated per case.

### Finding 9 — Wien/Vienna exonym rejected by the echo-guard (narrow, precise, easy fix candidate)

`geo-wien-german-endonym` fails distinctly from Finding 8: the response says the search
was flatly **rejected**, not empty: *"the location 'Wien' was rejected because it was
resolved as 'Vienna, Austria' and our geocoder flagged a mismatch
('geocode_echo_mismatch')."* `geo_guards.py::geocode_echo_matches` transliterates
diacritic/script endonyms (`_echo_fold`, e.g. "Gießen"→"giessen" correctly echoes) but has
no entry for **translated** exonym pairs like Wien/Vienna, München/Munich (München itself
passes, because Mapbox happens to echo "München" verbatim for that query) — Wien/Vienna is
a genuinely different word in each language, not a diacritic variant, so no transliteration
rule can bridge it. Reproduces 3/3 runs. A synonym-table entry (a handful of well-known
exonym pairs) would close this cleanly — small, contained, easy to verify.

### Finding 10 — named-hotel follow-up turns (matches the audit's known gap, more nuanced than "0/3")

`multiturn-named_hotel_present_*`/`multiturn-named_hotel_absent_*` (all 3 variants each)
and `prod-wound-named-hotel-survives-city` fail every run — matching the audit's
already-documented "hôtel nommé: AgentB2C 0/3" gap. Looking at the actual turn-by-turn
text (not just the final pass/fail), the picture is more nuanced than a blanket miss:
turns 1–3 of `named_hotel_present` correctly identify **"Kimpton Hotel Palomar Los Angeles
Beverly Hills"** by name across 3 different phrasings — the named-hotel lookup itself
works. It's turn 4 (a follow-up about the same hotel) that fails to carry the context, and
turn 5 falls back to the **generic ack/greeting template** as if the session had reset.
This suggests the gap is narrower than "named-hotel lookup doesn't work" — it's
specifically about carrying named-hotel context into later follow-up turns. Left as a
residual/known-family finding, not re-scoped or fixed here.

## ×3 stability (variance across identical replays)

```
n_runs: 3, total_cases: 81, complete_cases: 81, incomplete: 0
stability_rate: 87.65% (71/81 agree on pass/fail across all 3 runs)
by_suite: geo 34/41 stable (7 unstable) · multiturn 24/27 stable (3 unstable) · prod_wounds 13/13 stable (0 unstable)
```

Unstable case IDs (flip at least once across the 3 runs — real LLM-driven jitter, not a
harness bug, consistent with the S-G4 finding that gpt-5.2 shows ~2× latency swings on
identical requests): `geo-dublin-ie-homonym`, `geo-firenze-endonym`, `geo-geneve-accent`,
`geo-genoa-it-not-in-table`, `geo-lyon-fr-not-in-table`, `geo-reading-gb-homonym`,
`geo-rotterdam-nl-accent`, `multiturn-non_search_support_1` (Finding 7),
`multiturn-rooftop_pool_0`, `multiturn-rooftop_pool_1`.

Latency stayed stable and un-timed-out across all 3 runs: p50 9.6–10.3 s, p95 26.0–27.3 s
(pack latency = **sum of a case's turns**, per the S-A pitfall note — a multi-turn case's
"latency" is not comparable to a single-turn one).

## Ranking eval (A8-a) — design done, blocked by Finding 1

`scripts/eval_ranking.py` + `reports/RANKING-EVAL-PROTOCOL-2026-07-23.md`: reads an
already-produced gate report (no extra live LLM calls), independently queries MCP_B2C
directly for a same-anchor/date/filters ground-truth candidate pool (size=50), and scores
the shown top-5 with precision@5/NDCG@5 against distance-from-anchor ground truth. 15/15
unit tests pass (pure functions: haversine, hour-window floor/ceil, amenity→equipment-ID
mapping, distance-ranking, precision/NDCG scoring — including an order-sensitivity test
that NDCG catches a same-set-different-order case that precision@5 cannot).

Run against this session's real replay data: **0 usable samples** — 17 of 81 cases had
hotels but no resolved anchor (`active_filters.distance_origin` always `None`, per Finding
1), the other 64 had no hotel-bearing turn at all this run. This is a direct, documented
consequence of Finding 1, not a design gap in the eval itself — the moment that one-line
fix lands, this script needs no further changes to start producing real precision@5/NDCG@5
numbers.

A genuinely new discovery made while building this protocol (not previously documented
anywhere in this repo): every `search_offers` result already carries a `score` field and a
`matchReasons` array (`HasBookableOffers`, `RatingQuality`, `HighTier`) — MCP_B2C's own
default order blends review-quality/tier signals, not pure proximity. Relevant context for
a *future* reranker design decision; does not change what this eval measures (the audit
explicitly asked for **distance** ground truth, "vérité de distance" — that's what
precision@5/NDCG@5 compute here, not a verdict on MCP's own score).

## Full failure ledger (every failing case, all 3 runs, bucketed)

Generated mechanically from each run's raw report (`scripts/eval_ranking.py`'s sibling
one-off classifier, not committed — the bucket assignment is manual/verified for the
first 5 buckets below, pattern-matched for the rest; every case ID is accounted for, none
dropped silently).

| Bucket | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| Inventory confound, resolved correctly (Finding 8) | 15 | 22 | 22 |
| Tool-budget/empty-text, multi-turn (Finding 2) | 14 | 14 | 14 |
| Named-hotel follow-up family (Finding 10) + 1 fr/en-scope case | 9 | 9 | 9 |
| Safe clarification, mislabeled (Finding 3) | 7 | 6 | 5 |
| Wrong country (Finding 4) | 2 | 2 | 2 |
| GPS fixture/contract mismatch (Finding 5) | 2 | 2 | 2 |
| Known address/zone geocoding gap (Finding 6) | 2 | 2 | 2 |
| Echo-guard exonym rejection (Finding 9) | 1 | 1 | 1 |
| FAQ MCP staging degradation (Finding 7) | 0 | 1 | 0 |
| **Total failing** | **52** | **59** | **57** |

Every case ID behind each bucket is listed in Findings 2–10 above, or is one of the
following (Finding 8, listed in full for completeness — these are the correctly-resolved,
0-inventory cases, run 1's instance of each): `geo-milano-1623bc4a`,
`geo-milano-followup-3d3618c1`, `geo-zuerich-schweiz-a6810cc26`,
`geo-frankfurt-de-not-in-table`, `geo-marseille-fr-not-in-table`,
`geo-bordeaux-fr-not-in-table`, `geo-granada-es-homonym`, `geo-bonn-de-not-in-table`,
`geo-milano-no-state`, `geo-munchen-umlaute`, `geo-zurich-no-qualifier`,
`geo-lisboa-accent`, `geo-barcelona-vs-barcelone`, `multiturn-rooftop_pool_2` (this specific
run only), `prod-wound-booking-link-recovery`. Runs 2/3 add `geo-victoria-bc-e8076547`
(clarification text but no "?"-pattern match that run — borderline classifier case, safe
to read as Finding 3's family), `geo-lyon-fr-not-in-table`, `geo-reading-gb-homonym`,
`geo-dublin-ie-homonym`, `geo-genoa-it-not-in-table`, `geo-rotterdam-nl-accent`,
`geo-geneve-accent`, `geo-firenze-endonym` — all same signature (correct resolution, 0
staging inventory).

## DoD

```
$ pytest -q            → 858 passed (843 baseline before this session + 15 new
                          tests/test_eval_ranking.py), 1 pre-existing unrelated failure
                          (tests/test_llm_meter_usage.py, untracked S-B artifact,
                          documented in prior addenda, untouched)
$ ruff check .          → All checks passed!
$ mypy agents libs      → unchanged (scripts/** is outside this command's scope, same as
                          eval_hardening.py/eval_replay_stability.py precedent)
$ bash scripts/dayuse_guardrails.sh .  → OK
$ ls reports/GATE-RERUN-*.md → this file
```

## What this means for the canary decision (instructs, does not decide — that's Fabien's)

- Gate 6 (timeouts) is a clean, real win.
- Gate 5 (parity) fails numerically, but a meaningful share of the gap is measurement
  artifact (Findings 1, 3) or a specific, well-characterized, likely-fixable interaction
  bug (Finding 2) rather than a broad capability regression.
- Gate 1 (wrong country) has 2 confirmed, reproducible, real violations — the audit's own
  most safety-critical gate — and should weigh heavily regardless of the other confounds.
- Gates 2, 3, 4, 7 are either confounded or blocked by the bugs above and are not cleanly
  resolvable from this run alone.

**Recommendation for next steps** (not a decision): a short, targeted follow-up session
fixing Finding 1 (1 line) + Finding 9 (small synonym table) + investigating Finding 2's
exact mechanism would likely unblock Gate 7 entirely and materially change the Gate 5
number, before any canary conversation.
