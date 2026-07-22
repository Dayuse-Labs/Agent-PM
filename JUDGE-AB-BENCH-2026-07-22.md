# S-D — Judge A/B bench: agent-usa vs AgentB2C (2026-07-22)

Preliminary quality + latency comparison, part of the S-A→S-F comparative-audit plan (`~/.claude/plans/dans-le-repo-j-ai-serene-wreath.md`, `tasks/todo.md`). S-A (eval-pack adapter + staging smoke) is done, PR #18. S-B/S-C are blocked on Fabien (agent-usa local-boot procedure; prod ES/DB creds for the run-of-record). This session picked up **S-D**, which needs neither, and — at Fabien's request — actually ran it end-to-end against both stacks rather than stopping at harness-only.

**Interactive dashboard**: https://claude.ai/code/artifact/0e3d665a-4269-4602-8e16-eb91ac7e0131

## Read this before the numbers

This is a real bench, not a mock — but it is **not** the official S-C run-of-record and should not be used alone for a GO/hybrid call:

- **Inventory asymmetry.** agent-usa ran against a locally-seeded, prod-derived catalog (8,701 hotels / 29 markets, regenerated from the 2026-07-15 agent-usa exports — the same fixture S-A already produced). AgentB2C's candidate went through MCP_B2C on **staging** ES only — partial inventory, per `AUDIT-REWORK-2026-07.md` §5 (findings P1/P4: near-empty reviews, some hotels missing from the bookable staging index). The comparison isn't apples-to-apples until MCP_B2C gets prod ES access.
- **Language coverage.** Several of the 32 evalset-v0 scenarios are in de/es/it/pt (drawn from real historical prod conversations). Neither spine covers all of them: AgentB2C is fr/en-first by design (no staged intake, no market-language engine); agent-usa's README documents EN/FR/ES. Most "fails" on non-fr/en/es scenarios trace to this documented gap, not search quality.
- **A harness bug was caught and fixed mid-run** (see Findings below) — the numbers here are from the corrected re-run.

## Topline

| Metric | AgentB2C (candidate) | agent-usa (baseline) |
|---|---:|---:|
| Judge pass rate | 5/32 (15.6%) | 6/32 (18.8%) |
| Mean score (1–5) | 2.44 | 2.50 |
| Latency p50 / turn | 4185 ms | 6904 ms |
| Latency p95 / turn | 9088 ms | 14319 ms |
| Latency mean / turn | 4181 ms | 7348 ms |

Both stacks score low in absolute terms — expected, given the language-coverage gap above accounts for a meaningful share of both columns' failures, and the candidate is additionally handicapped by the staging-ES inventory. **Latency is the clean, structural signal here**: AgentB2C is 37-43% faster across the board, consistent with its ≤3 LLM-calls/turn structural budget vs. agent-usa's documented 3-20+ calls/turn (`AUDIT-REWORK-2026-07.md`).

## Per-family

| Family | AgentB2C passed | AgentB2C mean | agent-usa passed | agent-usa mean |
|---|---:|---:|---:|---:|
| simple_search | 1/4 (25%) | 2.75 | 1/4 (25%) | 2.75 |
| empty_dead | 4/4 (100%) | 5.00 | 2/4 (50%) | 3.50 |
| empty_recovered | 0/4 (0%) | 2.00 | 1/4 (25%) | 2.75 |
| budget_search | 0/4 (0%) | 2.00 | 0/4 (0%) | 2.00 |
| timeslot_search | 0/4 (0%) | 2.00 | 1/4 (25%) | 2.75 |
| named_hotel | 0/4 (0%) | 2.00 | 0/4 (0%) | 2.00 |
| compare | 0/4 (0%) | 1.75 | 0/4 (0%) | 1.50 |
| multi_turn_long | 0/4 (0%) | 2.00 | 1/4 (25%) | 2.75 |

## Notable findings

**1. Harness bug caught mid-run: session continuity silently broken.** The first candidate run defaulted to Fabien's personal Redis (`redis://localhost:6379/0` — `profile_store.py`'s hardcoded default when `CONCIERGE_REDIS_URL` is unset, and `bash scripts/run_local.sh` doesn't set it), instead of AgentB2C's own dedicated Redis (`agentb2c-redis-6380`). Every turn ran with zero profile memory. Symptom: a Paris-area search ("Bercy Village") returned hotels in **Toronto and Markham** — a geocoding fallback with no city context to anchor it. This also wrote 31 synthetic `b2c_concierge:profile:*` keys into Fabien's real Redis (left in place at his request, flagged here for cleanup on his own schedule). Fixed by launching with `CONCIERGE_REDIS_URL=redis://localhost:6380/0` and re-running; the anomaly disappeared and city context held correctly across every subsequent turn. **Recommendation**: consider whether `profile_store.py`'s default should point somewhere less collision-prone than the standard Redis port, or whether `run_local.sh` should set `CONCIERGE_REDIS_URL` explicitly — every prior live-verification session in HANDOFF.md had to remember this by hand.

**2. `empty_dead`: AgentB2C never dead-ends; agent-usa sometimes still asks for the city.** AgentB2C passed all 4 (its S6 anti-dead-end guard). agent-usa passed 2/4 — e.g. user: *"Vorrei una camera... zona Sassuolo Rubiera e limitrofi"* (zone already given) → agent-usa: *"Perfetto, prima cosa: in quale città stai cercando?"* (asks for the city again). Judge: "creates a dead-end situation instead of providing a useful response."

**3. Language gap on both sides, not a regression.** User: *"modena"* (Italian scenario) → AgentB2C correctly finds 4 Modena hotels but replies partly in English. Neither spine covers it/de/pt/zh; this single documented gap likely explains a large share of both columns' failures across families.

## Environment

- AgentB2C: `bash scripts/run_local.sh` (concierge :8100, search :8101, faq :8102), staging MCP_B2C, `CONCIERGE_REDIS_URL=redis://localhost:6380/0`.
- agent-usa: local Flask (`flask --app src.api.app:create_app run --port 5002`), Postgres + Qdrant seeded from the 2026-07-15 prod export (8,701 hotels / 29 markets, already migrated/seeded before this session — `alembic current` showed head on first check), `AUTH_BYPASS=true` (local dev only). `.env`'s `DATABASE_URL`/`REDIS_URL` ports were wrong on disk (pointed at an unrelated Postgres and at AgentB2C's own Redis respectively) — corrected to match the actually-running `dayuse-postgres`/`dayuse-redis` containers (5433/6381) before boot.
- Judge: `gpt-4o-mini`, temperature 0, same rubric both sides (`evals/judge.py::LLMJudge`, unchanged).
- Harness: `scripts/run_judge_ab.py` (new, this session) — stdlib HTTP replay of `evalset/evalset-v0.json` against one `/v3/chat` endpoint at a time, `X-Dayuse-Synthetic: 1` always set, `canonical-eval-` session prefix.

## Reproduce

```bash
# AgentB2C candidate
bash scripts/run_local.sh
python scripts/run_judge_ab.py --endpoint http://127.0.0.1:8100/v3/chat --label candidate --out reports/judge_candidate.json

# agent-usa baseline (from the agent-usa checkout)
set -a && source .env && set +a && AUTH_BYPASS=true .venv/bin/python -m flask --app src.api.app:create_app run --port 5002
python scripts/run_judge_ab.py --endpoint http://127.0.0.1:5002/v3/chat --label agent_usa --out reports/judge_agent_usa.json
```

Raw transcripts + judge reasoning for all 64 scenario-runs: `reports/judge_candidate.json`, `reports/judge_agent_usa.json` (gitignored — local, synthetic-content-only artifacts, not committed).

## Not covered here (S-C, blocked)

Prod-ES-parity inventory, cost/turn, load/scalability, the official GO/hybrid gate. This bench's only job was: prove `run_judge_ab.py` works end-to-end against a real, unaffiliated system, and get an honest first read on quality + latency shape while S-C's prerequisites are pending.
