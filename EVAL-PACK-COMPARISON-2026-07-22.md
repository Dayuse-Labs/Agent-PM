# Eval pack comparison: agent-usa vs AgentB2C (2026-07-22)

Full `dayuse_eval_pack` (249 cases, 7 suites) replayed against both stacks locally. Part of the S-A→S-F comparative-audit plan (`~/.claude/plans/dans-le-repo-j-ai-serene-wreath.md`); this is a supplementary run on top of S-A's own staging smoke, at Fabien's request, using `eval_pack.runner`/`eval_pack.compare` directly (no new code — the pack and its tools already exist from PR #18).

**Interactive dashboard**: https://claude.ai/code/artifact/7028d7ed-47c2-4474-aa88-cdffb6c32380

## Read this first — the confound dominates the headline number

- **agent-usa**: 202/249 failed. **197 of those (98%) returned zero hotels** — including for its own flagship US metros (New York, Miami, Chicago), which its documented `MarketRegistry` (README §10, 80+ US cities) explicitly covers. agent-usa's own replies say so directly: *"I couldn't find any day-use hotels available in Queens Village, NY... there are no listings available in the wider Miami area either."* This points to stale/sparse local availability data — its Postgres+Qdrant were seeded from a 2026-07-15 export and may simply lack rate-plan coverage for the dates these 249 cases request — not a reasoning defect.
- **AgentB2C**: 139/249 failed. **91 of those (65%) also returned zero hotels**, consistent with the already-documented staging-ES partial inventory (`AUDIT-REWORK-2026-07.md` §5, findings P1/P4).
- **Concretely**: for the identical query *"I need a hotel in Queens Village NY for the afternoon, budget $200"* (case `core-e2e-001`), AgentB2C returned 5 real hotels via MCP_B2C staging ES; agent-usa's own local seed returned 0 — for a US city its own product is explicitly built to cover.
- **This is not the official S-C parity gate.** Two comparisons below don't depend on either side's local hotel inventory and are the only genuinely clean signals in this run: **latency** and the **domain suite** (language/currency formatting).

## Topline

| Metric | AgentB2C (candidate) | agent-usa (baseline) |
|---|---:|---:|
| Pass rate | 110/249 (44.2%) | 47/249 (18.9%) |
| Latency p50 / case | 5043 ms | 6794 ms |
| Latency p95 / case | 11576 ms | 25397 ms |
| Latency mean / case | 5803 ms | 8779 ms |
| Zero-hotel share of failures | 91/139 (65%) | 197/202 (98%) |

Case-by-case diff (`eval_pack.compare`): **80 improvement · 122 unchanged_fail · 30 unchanged_pass · 17 regression**.

Case latency = **sum of all turns in the case** (the pack's own convention, disclosed here per its README).

## Per-suite (🟧 = >75% of failures on at least one side are zero-hotel — read as inventory, not quality)

| Suite | AgentB2C | agent-usa | Confound |
|---|---:|---:|---|
| core 🟧 | 53/95 (55.8%) | 8/95 (8.4%) | inventory |
| domain | 2/8 (25%) | 8/8 (100%) | clean — language/currency |
| geo 🟧 | 22/41 (53.7%) | 8/41 (19.5%) | inventory |
| international 🟧 | 3/13 (23.1%) | 1/13 (7.7%) | inventory |
| multiturn | 9/27 (33.3%) | 14/27 (51.9%) | mostly `active_filters` exposure gap (see below) |
| prod_wounds | 6/13 (46.2%) | 6/13 (46.2%) | tie |
| worldwide 🟧 | 15/52 (28.8%) | 2/52 (3.8%) | inventory |

## Clean signals (not inventory-confounded)

1. **Domain suite** (response language + card currency by ccTLD, 8 cases — no hotel-availability dependency): **agent-usa 8/8, AgentB2C 2/8**. A genuine, already-documented capability gap — AgentB2C is fr/en + EUR-only by design (no staged market-language engine, S9 scope decision), not a bug.
2. **Latency**: AgentB2C p95 11.6s vs agent-usa p95 25.4s — **54% faster**, consistent with the ≤3-LLM-call/turn structural budget vs agent-usa's documented 3–20+ calls/turn, and consistent with the separate 32-scenario judge bench run the same day (`JUDGE-AB-BENCH-2026-07-22.md`).

## The 17 regressions, triaged individually

Per the pack's own interpretation rule ("review every reported regression qualitatively before rejecting the new architecture"):

- **7 documented language/currency gaps**: `domain-dayuse-{co-uk,com-br,com-mx,de,es,it}`, `prod-wound-date-not-budget`. Same fr/en+EUR-only scope as the domain-suite result above.
- **6 documented `active_filters` exposure gaps**: `multiturn-carry_same_time_{0,1,2}`, `multiturn-zone_change_{1,2}`, `prod-wound-named-hotel-survives-city`. AgentB2C doesn't echo `zone`/`date_reference`/`named_hotel` in `active_filters` — a structured-field gap already in the S-A gap register (not necessarily a wrong answer to the user, just a missing structured signal the pack's assertions check for).
- **2 new, genuine bugs found by this run** (worth a real fix):
  - `core-e2e-084` — *"check-in 7:30am checkout 1:30pm"* → AgentB2C's `active_filters` shows `timeslot_start: "07:00"`, `timeslot_end: "13:00"`. Both bounds silently rounded down to the hour, dropping ":30" — the `search_offers` tool's `timeSlot` schema only accepts integer hours (0–23), no half-hour granularity, and nothing surfaces the truncation to the user.
  - `core-e2e-201` — *"hotel in Lansdale PA for 1 hour, budget $100"* → `active_filters` shows `timeslot_start: "00:00"`, `timeslot_end: "01:00"`. "1 hour" (a duration) got extracted as an absolute midnight-to-1am window instead of a reasonable 1-hour slot — same bug *class* as the historically-documented "20 minutes → €20 budget" prod incident (a relative/duration expression misread as an absolute value), different field.
- **1 known staging degradation**: `multiturn-non_search_age_1` — FAQ MCP degraded on staging (*"I can't look up the Dayuse conditions right now"*), the same environment issue S-A's smoke run already flagged.
- **1 likely transient**: `core-e2e-202` (Le Meridien DC) — full honest degradation (*"I can't reach hotel search right now, and I'd rather not make anything up"*), `active_filters` entirely empty (geocode/search never ran). Consistent with a single flaky leaf call, not a reproducible defect — worth a re-run, not a conclusion.

## Recommendation

- **`core-e2e-201`'s duration-as-absolute-time bug is worth fixing regardless of the inventory confound** — it's a real extraction defect, reproducible, and in the same bug family as a previously-documented prod incident. `core-e2e-084`'s half-hour truncation is lower severity (silent precision loss, not a wrong search) but also worth a note in the search leaf's instruction/schema.
- **Don't read the core/geo/international/worldwide suite gaps as "AgentB2C's search quality is much better"** — they're overwhelmingly explained by agent-usa's local seed data being stale/sparse (98% zero-hotel), not by AgentB2C's reasoning being superior. The domain-suite and latency results are the only clean reads from this run.
- **S-C (prod ES access for MCP_B2C) remains the blocking prerequisite** for a real apples-to-apples parity measurement — this run, if anything, reinforces why that prerequisite exists rather than substituting for it.

## Environment

Same as the S-D judge bench (`JUDGE-AB-BENCH-2026-07-22.md`): AgentB2C via `run_local.sh` + `scripts/run_eval_adapter.py` (`:8110→:8100`, field-mapping only — `country_code` full-name→ISO2, `currency`/`display_price` parsed from the façade's `€X.XX` string, never fabricated, every addition disclosed under `eval_debug.adapter_mapped`), staging MCP_B2C, dedicated Redis `:6380`. agent-usa via local Flask `:5002`, Postgres+Qdrant already seeded from the 2026-07-15 prod export (8,701 hotels/29 markets), `AUTH_BYPASS=true`.

## Reproduce

```bash
cd dayuse_eval_pack
python -m eval_pack.runner --endpoint http://127.0.0.1:8110/v3/chat \
  --output eval_pack/results/candidate.json --allow-failures
python -m eval_pack.runner --endpoint http://127.0.0.1:5002/v3/chat \
  --output eval_pack/results/agent_usa.json --allow-failures
python -m eval_pack.compare --baseline eval_pack/results/agent_usa.json \
  --candidate eval_pack/results/candidate.json \
  --output eval_pack/results/comparison.json --allow-regressions
```

Raw data: `eval_pack/results/{candidate,agent_usa,comparison}.json` (gitignored, local, synthetic-content-only artifacts).
