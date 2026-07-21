# Audit comparatif agent-usa vs AgentB2C — suivi

Plan complet : `~/.claude/plans/dans-le-repo-j-ai-serene-wreath.md`
(session précédente S09 : voir bloc HANDOFF 2026-07-20 + git history de ce fichier)

## S-A — Adapter + smoke staging (branche s15-eval-adapter)
- [x] `scripts/run_eval_adapter.py` (proxy :8110→:8100, 3 règles de mapping, disclosure `eval_debug.adapter_mapped`)
- [x] `tests/test_eval_adapter_mapping.py` (15 tests offline, fonctions pures) — verts
- [x] Gates verts (526 pytest, ruff, mypy, guardrails)
- [x] Smoke run : 249 cas via l'adapter sur staging ES → 110/249 (44,2 %) — plumbing validé, PAS un chiffre d'audit
- [x] Triage : 90 cas zéro-hôtel (staging), ~20 hors-zone US à investiguer sur prod, 20 gap-only (36 assertions < budget ≈45), adapter 541+23 mappings divulgués
- [x] Fixture inventaire régénérée (exports agent-usa 2026-07-15, 8 701 hôtels / 29 marchés)
- [ ] HANDOFF.md + commit + MR (en cours)

## S-B — Baseline agent-usa local (BLOQUÉ : procédure de boot :5002 + inventaire prod → Fabien)
- [ ] `scripts/run_llm_meter.py` (comptage tokens old agent) + baseline `local_5002.json`

## S-C — Run-of-record prod ES + compare (BLOQUÉ : creds MCP_B2C prod read-only + DATABASE_URL → Fabien)
- [ ] `candidate.json`, `comparison.json`, `annotate_inventory_confound.py`, `measure_ab_perceived_latency.py`, coût SQL

## S-D — Judge A/B — `scripts/run_judge_ab.py` (evalset-v0, 32 scénarios × 2 agents)
## S-E — Load probe — `scripts/load_probe.py` (1/5/10/20 concurrents, les 2 stacks locales)
## S-F — Rapport `AUDIT-COMPARATIF-AB-2026-07.md` + HANDOFF final
