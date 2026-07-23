# Resolution plan — geo & multi-turn regressions (AgentB2C)

**Date:** 2026-07-23
**Author:** Claude Code session (research + synthesis), for arbitration by Fabien
**Inputs:**
- `REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md` (the audit, 249-case comparison vs agent-usa)
- `reports/research/code-verification-memo.md` (every audit claim checked against `main` @ `453c77f` — **all 10 confirmed TRUE**, with file:line)
- `reports/research/geo-disambiguation-memo.md` (Mapbox v6/Search Box, Pelias, Airbnb, Expedia, toponym-resolution literature)
- `reports/research/multiturn-state-memo.md` (DST literature, RFC 7386, ADK/A2A state patterns, pagination, time handling)
- `reports/research/timeouts-latency-memo.md` (SRE deadline patterns, LiteLLM capabilities, hedging, A2A streaming)

**Status: ARBITRATED 2026-07-23 (Fabien) — all recommendations accepted.** Fabien initially thought A4 was already fixed; verified NOT fixed on `main` (leaf instruction still integer-hours `agent.py:144`, capture forces minute=0 `response_bridge.py:202-203`; only offer *display* reads minutes — likely source of the confusion, along with S14 landing "HH:MM" in the profile). A4-c stays in scope.
**Dev plan produced:** `phases/SG1-…SG9-*.md` (one autonomous phase file per session, launch prompt included) + overview/timeline in `SESSIONS-CLAUDE-CODE.md` §S-G + checklist in `tasks/todo.md`.

---

## 1. Diagnosis — one root-cause family, not two unrelated bugs

The audit reports two regressions (geo 26/41 vs 36/41; multi-turn 12/27 vs 16/27). Code verification shows they are the **same structural gap seen from two sides**: *the contract and the state don't carry the context the decisions need, and the bridge between them relies on the LLM re-copying values instead of code.*

Three concrete gaps, all confirmed in code:

1. **Geo decisions are made on one candidate with almost no context.** `mapbox_client.py:86-92` hardcodes `limit=1`, never sends `proximity`, never varies `language`, and `geocode_echo_matches` can only accept or reject that single candidate. Locale, domain, GPS, and our own inventory play no role. Mapbox v6's default limit is already 5 (max 10) — we are discarding candidates the API returns for free.
2. **The profile schema is too narrow, and what it does hold reaches the leaf's tools only if the LLM copies it.** `SessionProfile` (`profile.py:88-113`) has no `named_hotel`, `zone`, `metro`, date, `currency`, GPS/coords, distance origin, shown-IDs, or cursor. `active_filters` hardcodes `named_hotel: None, date_reference: None` (`facade.py:338-339`). And the only deterministic profile→tool-args bridge is amenities (`equipment_ids.py:144-178`); city/state/country anchors reach `geocode_location` only via prompt instructions the model must obey (`hotel_search_agent/agent.py:124-126`) — exactly the audit's P0 #4.
3. **The facade drops the request context on the floor.** Only `message` and `session_id` are read (`facade.py:485, :159`); `native_context.geolocation`, locale, domain, currency appear nowhere in the codebase. This is the P0 mobile gate (GPS Paris/Detroit/Orange County failures).

Secondary, independent issues: fixed 10 s leaf timeout below the healthy tail (`agent.py:125`, already raised to 30 s on the Railway demo via env); integer-hour timeslots (`response_bridge.py:200-207` hardcodes minutes to 0); EUR-only price formatting from `priceEuro` (`response_bridge.py:150-158`); cards drop lat/lon/distance (`response_bridge.py:233-268`); no reranker (first 5 MCP results, `response_bridge.py:271-284`); no pagination mechanism at all (grep-confirmed).

**What this means for the fix:** GPT-5.2 cannot compensate for state the contract can't store (the audit's own conclusion). The remediation is schema + deterministic bridges + a code-owned geo ranker — all consistent with the existing spine doctrine (LLM extracts, code owns values) and the ≤3 LLM calls/turn budget. No new LLM calls are needed anywhere in this plan.

---

## 2. Axis G — Geo resolution (audit P0 #1, #2, #8)

### What the research says (see geo memo for sources)

- Mapbox v6: `limit` up to 10, `proximity` (soft bias, accepts GPS or `ip`), `language` (affects scoring — directly attacks Lisboa→Arkansas), `country` (hard filter — only when the user names one), `worldview`. **v6 returns no numeric relevance score for places** — ranking must be ours, built from our signals plus list position. v6 has **no POI support**; POIs/zones are Search Box API territory, which also has a first-class `origin` param that returns per-result `distance` (the API-level template for "distance origin ≠ ranking bias").
- Industry consensus: travel players rank destinations **against their own inventory** (Airbnb location relevance; Expedia typeahead is explicitly inventory-aware). Pelias publishes the deterministic ordering rules: proximity re-ranks **within a prominence band** — it never lets a hamlet beat a capital, and never overrides an explicit distant destination.
- Dialogue disambiguation research: when ambiguity survives ranking, ask **one** clarifying question whose options are split by the most-discriminating attribute (usually country), max 2–3 options — never a candidate dump, never a loop.
- LLM division of labor (Mapbox's own MCP design, GeoAgent): LLM extracts the mention; deterministic code geocodes and ranks. Matches our doctrine; the ranker must NOT be an LLM call.

### Proposed design (option G1 — recommended)

One new code-owned module in the search leaf (`geo_resolver.py`), replacing the accept/reject step, keeping every existing geo guard as-is:

1. **Call shape:** v6 `/forward` with `limit=10`, `autocomplete=false`, `types=place,locality,neighborhood,district,region`, `language=<user locale>`, `proximity=<GPS if present, else ip>`, `country=` only when the utterance/state names one.
2. **Deterministic re-rank** of the ≤10 candidates:
   - explicit country/state hint match → **hard filter** (a stated country is never a boost);
   - **inventory density** in candidate bbox → near-hard (zero-inventory candidates demoted below any with-inventory candidate) — this signal alone kills Lisbon-AR and the Victoria homonyms;
   - locale/domain prior → bounded soft boost;
   - GPS proximity → soft, band-limited (Pelias rule);
   - Mapbox rank position + feature-type prior (`place` > `locality`/`neighborhood` > `district` > `region`).
3. **Decision policy:** top-1 margin ≥ threshold → select silently; otherwise ONE clarifying question with 2–3 `place_formatted` options split by country/region. Never loops (fits the existing 1-retry-then-deterministic doctrine). The margin threshold is tuned on the 41 geo eval cases.
4. `geocode_echo_matches` survives as a final sanity check on the *chosen* candidate (it was designed for exactly the failure it will keep catching).

### A1 — Inventory-density signal source (the real arbitration in G1)

| Option | How | Pros | Cons |
|---|---|---|---|
| **A1-a Static snapshot (recommended for v1)** | Compile a `city/bbox → hotel count` table into the leaf from the existing market data (8 701 hotels / 29 markets — same source as the eval fixture), refreshed by script | Zero runtime dependency, zero latency, ships now, deterministic & testable | Staleness (catalogue is stable per S-A; acceptable); coarse granularity |
| A1-b Live MCP probe | `search_offers` probe per surviving candidate | Exact, live | N× MCP calls per turn (latency + load), abuses a search tool as a counter |
| A1-c New MCP_B2C tool | `count_hotels_near(bbox)` read-only tool | Clean contract | Cross-repo dependency, blocks on MCP_B2C team; do later if snapshot proves insufficient |

Recommendation: **A1-a now**, design the ranker so the signal provider is swappable, revisit A1-c only if eval shows staleness failures.

### A2 — Search Box tier for POI/zone queries ("La Défense", "Orange County")

The type coverage claims (`neighborhood` for La Défense, `district` for Orange County) are **inferred from docs, not live-verified**. Recommendation: a 15-minute live probe with the leaf's token is the first task of the geo session; adopt Search Box `/forward` as tier 2 **only if** v6 fails the probe on our real zone/POI cases. (Billing note: Search Box is a separate SKU.)

### Explicitly rejected: G3 — a full destination-resolution service (Expedia-style typeahead index). Over-engineering at this stage; the G1 ranker + snapshot gets the same signals with two orders of magnitude less work.

---

## 3. Axis N — Native context intake (audit P0 #2; P0 mobile gate)

Not really an option — it's a prerequisite for three audit gates (zero silent GPS replacement, GPS cases, distance origin). Scope:

1. **Facade** reads `native_context` (geolocation lat/lon/accuracy), `locale`, `domain`, `currency`, plus the already-sent `client_local_time`/`client_timezone` (currently documented-ignored). All optional, all absent-tolerant — iso-contract preserved.
2. **Profile v2** stores a **search anchor** as a tagged union: `{type: gps|address|zone|poi|city_centroid, lat, lon, label, set_at_turn}`. Rule (deterministic, in code): *a turn may upgrade or explicitly replace the anchor; nothing silently downgrades it to a city centroid* — this is the audit's P0 mobile invariant, and it becomes testable.
3. **Leaf** receives the anchor via `profile_in` and uses it as Mapbox `proximity` bias (never a filter — "hotel in New York" typed from Paris must still resolve New York; Pelias band rule).
4. **Cards** expose `latitude`, `longitude`, `distance_km`, and `distance_origin` (needed for audit P0 #8 verifiability — today the geocoder has the coords and drops them at normalization).

Currency/locale/domain intake is shared with Axis C below.

---

## 4. Axis M — Profile v2 + patch semantics + deterministic bridge (audit P0 #3, #4, #5; multi-turn suite)

### What the research says (see multi-turn memo)

- DST literature converged on **per-slot operations** (SOM-DST: CARRYOVER/DELETE/UPDATE; Diable: table ops): carryover is the default, a slot can only be lost by an explicit, auditable clear — never by omission. Full-state re-emission is the documented cause of exactly our "date lost on zone change" failure.
- RFC 7386 merge-patch (`null`=delete, absent=unchanged) is the minimal standard; its known limitation (can't distinguish "clear" from "no preference") is why the ops enum is safer for LLM emission.
- ADK confirms **sessions are NOT shared with A2A remote agents** (maintainer statement) — the profile must ride the `DataPart` explicitly, which is what AgentB2C already does. Microsoft ISE's A2A guidance validates the design and adds one thing we lack: a **`schema_version`** on the DataPart.
- Pagination: LLMs re-emit already-shown items unless code excludes them (measured: HIT@1 −60% when only new items count). Exclusion must be state + code, not prompt.
- Dates: LLM labels (absolute vs relative + original expression), code computes against an injected reference date + client timezone; store ISO-8601 absolutes **plus** `date_reference`.

### Proposed design (option M1 — recommended)

1. **Schema extension** (SessionProfile + `apply_profile_delta` + `active_filters` + conversation-log): `named_hotel {id, name, source}`, `zone`, `metro`, `date` (ISO) + `date_reference {expression, resolved_from, client_tz}`, `currency`, `locale`, `domain`, `search_anchor` (Axis N), `distance_origin`, `shown_hotel_ids` (accumulating, capped), `search_cursor`. `active_filters` stops hardcoding `named_hotel/date_reference` to null.
2. **Typed patch ops in `profile_delta`:** each geo/constraint slot is emitted as `{op: set|clear, value}`; **absent = carryover** (default). `apply_profile_delta` becomes a reducer with per-slot logged transitions. Deterministic invalidation rules stay in code and get explicit tests: city change → clear zone/anchors + reset `shown_hotel_ids`; zone change → keep date/timeslot/budget/amenities (the audit's failing case); "other options" → keep everything, advance cursor.
3. **Deterministic profile→tool-args bridge** (the P0 #4 fix): a `before_tool_callback` in the leaf injects `city`/`zone`/`state`/`country_code`/`proximity` into `geocode_location` args from the decoded `profile_in` — same pattern as `enforce_equipment_filters` for amenities, which is already the proven template. The LLM's extracted values win for *new* mentions; the profile fills what the LLM omitted. The model stops being a copy machine.
4. **`schema_version` field** on the profile DataPart both ways (ISE pattern) so leaf and concierge can evolve independently.
5. **Pagination:** `shown_hotel_ids` excluded at result-selection time; "other options" advances the cursor; when the filtered pool is exhausted → explicit disclosure + offer to relax a named constraint (mixed-initiative relaxation; extends the existing S12 exhaustion machinery instead of adding a parallel one).

### A3 — Patch semantics

| Option | Semantics | Trade-off |
|---|---|---|
| **A3-a Typed ops (recommended)** | `{op: set/clear, value}` per slot, absent = carryover | Slightly bigger extraction schema; auditable clears; matches SOM-DST/Diable; kills silent loss |
| A3-b RFC-7386 merge-patch | `null` = clear, absent = carryover | Minimal change to today's delta; cannot express "no preference"; `null` emission by gpt-4o-mini is error-prone (negation-inversion lesson S10) |

### A4 — Half-hour timeslots end-to-end (audit P0 #5, bug `core-e2e-084`)

The profile already stores `"HH:MM"`; loss happens at the leaf→MCP boundary (integer `startHour`/`endHour`).

| Option | How | Trade-off |
|---|---|---|
| A4-a MCP schema change | Ask MCP_B2C for `startMinute`/`endMinute` (or `"HH:MM"` strings) on `search_offers` | Correct filtering server-side; cross-repo dependency |
| A4-b Client-side filter | Send floor/ceil hours to MCP, post-filter returned offers by exact minutes in the leaf | Ships now; risks over-filtering to 0 results when inventory granularity is hourly |
| **A4-c Both (recommended)** | b now as interim, a requested in parallel with a documented removal date | Honest now, correct later |

Related bug to fix in the same scope: `core-e2e-201` — "for 1 hour" is a **duration**, currently extracted as absolute window "00:00-01:00" (same family as the historic "20 minutes → 20 €" prod wound). The extraction schema must gain a `duration` label distinct from `timeslot` (LLM labels, code computes).

---

## 5. Axis T — Timeouts (audit P0 #6) · Axis C — Domain/locale/currency (P0 #7) · Axis R — Ranking verifiability (P0 #8)

### A5 — Timeout architecture

Research (SRE book, Amazon Builders' Library): set timeouts from a target false-timeout rate at the healthy downstream percentile; propagate one deadline rather than stacking fixed per-hop walls; retry at ONE layer only (our LiteLLM-only invariant is exactly this rule — keep 0 retries on the orchestrator→leaf hop). Chester GB is a bimodal-latency correctness bug in the leaf, not a timeout-tuning problem — fix separately.

| Option | Design | Trade-off |
|---|---|---|
| **A5-a Per-intent static budgets (recommended v1)** | `search: ~15 s`, `faq: ~25 s` derived from observed healthy p95/p99 per family (Railway demo already proved 10 s < healthy tail; 30 s env override in place), + LiteLLM `RetryPolicy` (retry Timeout/RateLimit once, never BadRequest) + `stream_timeout` protecting TTFT | One-session change; keeps invariants; numbers need a metrics pass to set honestly |
| A5-b Full deadline propagation | Facade-owned turn deadline, `remaining_ms` in the A2A DataPart, leaf clips each dependency to min(own cap, remaining), per-request LiteLLM `timeout` | The "right" architecture (gRPC/SRE pattern); more surface, more tests; do as phase 2 once per-phase metrics exist |

Hedging: researched and **rejected** for now (duplicates leaf fan-out, collides with the ≤3 LLM calls budget; LiteLLM `fallbacks` are the cheaper sequential alternative if ever needed). `generate_booking_link` must stay unreachable from any retried path (R9).

### A6 — Domain/locale/currency scope

This was an explicit S9 scope cut (fr/en + EUR), and it now costs 6/8 of the Domaines suite plus the international homonym prior. Full multi-currency pricing depends on what MCP_B2C exposes (the audit itself flags the local fixture doesn't reproduce MCP_B2C pricing).

| Option | Scope | Trade-off |
|---|---|---|
| **A6-a Context now, pricing staged (recommended)** | Facade captures locale/domain/currency → profile → geo prior (Axis G) + `response_language` + card `country_code`; price *display* stays EUR until MCP pricing capabilities are probed | Unblocks geo prior + honest display; defers the risky part |
| A6-b Full multi-currency now | Also convert/format prices per domain | Blocked on MCP_B2C pricing surface; highest regression risk |
| A6-c Defer entirely | Keep S9 cut | Domaines suite stays 2/8; locale prior unavailable to the geo ranker (weakens Axis G) |

### A8 — Reranker scope

The audit is explicit: shortlist relevance is currently **unmeasurable** (no coords in cards, no candidate-identical eval). Recommendation: **instrument first, rank later** — ship lat/lon/distance in cards (Axis N.4), build the dedicated ranking eval (identical candidate pools, distance ground truth, precision@5/NDCG@5), and only then decide whether a code-owned reranker (distance + constraint-fit sort) is needed. Building a reranker before the eval exists would be tuning blind.

### Harness hardening (audit §"Durcissements")

All 8 items are uncontroversial and independent of the arbitration; they become one session in the dev plan (min_hotels≥1 on geo cases, separate safe-clarification/success/degradation scoring, country+anchor assertions on empty shortlists, per-turn filter assertions, distance verifiability, new-IDs assertion on pagination, timeout-rate reporting, 3× replay on gates).

---

## 6. Decision table for arbitration

| # | Decision | Options | Recommendation | **Arbitrated (2026-07-23)** |
|---|---|---|---|---|
| A1 | Inventory signal for geo ranker | a) static snapshot · b) live MCP probe · c) new MCP tool | **a**, swappable provider | ✅ a |
| A2 | Search Box API tier 2 (POI/zones) | a) adopt now · b) decide after 15-min live probe · c) never | **b** | ✅ b (probe in S-G3) |
| A3 | Profile patch semantics | a) typed ops (set/clear, absent=carryover) · b) RFC-7386 merge-patch | **a** | ✅ a |
| A4 | Half-hour timeslots | a) MCP schema change · b) client-side filter · c) both (b interim, a requested) | **c** | ✅ c — Fabien thought it fixed; **verified NOT fixed on main** (see Status note) |
| A5 | Timeout architecture | a) per-intent static budgets v1 · b) full deadline propagation | **a** now, b later | ✅ a |
| A6 | Domain/locale/currency | a) context now, pricing staged · b) full now · c) defer | **a** | ✅ a |
| A7 | Pagination exclusion mechanism | a) over-fetch + client-side exclusion · b) MCP `excludeHotelIds`/offset param | **probe first**: does `search_offers` accept a limit/offset? | ✅ probe first (S-G5) |
| A8 | Hotel reranker | a) instrument + eval first, rank later · b) build reranker now | **a** | ✅ a |

Ops flag (no code): the audit notes production model selection rides on a deploy env var (`DAYUSE_MODEL`), defaults committed as `gpt-4o-mini` while the eval ran GPT-5.2 — platform-side control needed before any canary comparison is meaningful.

Cross-repo dependencies to open with MCP_B2C (regardless of arbitration): timeSlot minutes (A4-a), exclusion/offset params (A7-b), optional `count_hotels_near` (A1-c), pricing/currency surface (A6-b). None of them blocks Wave 1 below.

---

## 7. Proposed phasing (preview — full dev plan after arbitration)

Sized for parallel Claude Code sessions, one scope each (SESSIONS-CLAUDE-CODE.md discipline). Wave 1 items are independent of each other:

**Wave 1 — foundations (4 parallelizable sessions)**
- **S-G1 Profile v2 + patch ops + reducer** (concierge): schema extension, typed ops, invalidation rules, `schema_version`, `active_filters` un-nulling. Spec source: the 27 multi-turn + 36 filter assertions of the eval pack.
- **S-G2 Native context intake** (facade + concierge): request fields, search-anchor union, no-silent-downgrade rule + tests.
- **S-G3 Geo multi-candidate resolver** (leaf): live probe first (A2), `limit=10` + `language` + `proximity`, deterministic ranker with snapshot inventory (A1-a), clarify-once policy, echo-guard retained. Gate: the 41 geo cases + zero-wrong-country.
- **S-G4 Timeout budgets** (concierge + leaf): per-family budgets from metrics, LiteLLM RetryPolicy/stream_timeout, Chester root-cause.

**Wave 2 — behaviors on top (3 sessions)**
- **S-G5 Deterministic profile→leaf bridge + pagination** (leaf + concierge): before_tool_callback injection, shown_ids exclusion (A7), exhaustion disclosure.
- **S-G6 Dates + durations + minutes** (leaf + concierge): date/date_reference, duration-vs-timeslot labeling (`core-e2e-201`), A4 interim filter.
- **S-G7 Currency/locale propagation** (facade + leaf): A6-a scope; cards carry lat/lon/distance/distance_origin.

**Wave 3 — proof (2 sessions)**
- **S-G8 Harness hardening** (eval pack adapter side, pack itself never modified): the 8 audit items.
- **S-G9 Gate re-run + ranking eval**: 81-case geo/multi-turn/prod-wounds gate ×3 replays, ranking eval design (A8).

Rough effort: 9 sessions total; Wave 1 delivers the audit's P0 #1–#4 and #6; the canary gate (§ audit "Recommandation") is testable after Wave 3.

---

## 8. Success gates (unchanged from the audit — every axis maps to one)

| Audit gate | Covered by |
|---|---|
| Zero wrong-country resolutions | Axis G (hard hint filter + inventory demotion) |
| Zero explicit-constraint loss across turns | Axis M (carryover-by-default + reducer tests) |
| Zero silent GPS/address/zone replacement | Axis N (anchor union + no-downgrade rule) |
| No empty-geo "success" when offers exist in radius | Axis G + harness (min_hotels≥1) |
| Parity on the 81 geo/multi-turn/prod-wound cases | Waves 1–2, measured in Wave 3 |
| Technical-timeout rate below product threshold | Axis T |
| Ranking validated on identical candidates | A8 (instrument-first) |
