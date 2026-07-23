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
- [x] HANDOFF.md + commit + MR (PR #18 — review Fabien = gate)

## S-B — Baseline agent-usa local (BLOQUÉ : procédure de boot :5002 + inventaire prod → Fabien)
- [ ] `scripts/run_llm_meter.py` (comptage tokens old agent) + baseline `local_5002.json`

## S-C — Run-of-record prod ES + compare (BLOQUÉ : creds MCP_B2C prod read-only + DATABASE_URL → Fabien)
- [ ] `candidate.json`, `comparison.json`, `annotate_inventory_confound.py`, `measure_ab_perceived_latency.py`, coût SQL

## S-D — Judge A/B — `scripts/run_judge_ab.py` (evalset-v0, 32 scénarios × 2 agents)
## S-E — Load probe — `scripts/load_probe.py` (1/5/10/20 concurrents, les 2 stacks locales)
## S-F — Rapport `AUDIT-COMPARATIF-AB-2026-07.md` + HANDOFF final

---

# TODO — Railway deploy: AgentB2C hosted demo (widget front + 3 services)

**Goal**: reproduce `localhost:8090` (agent-usa chat widget → AgentB2C `/v3` facade → 2 A2A leaves → **staging** MCP) as a hosted Railway demo in a **new project "AgentB2C"**. Synthetic/demo traffic only — no prod-ES, no real users.

**Decisions (Fabien, 2026-07-22)**: hosted demo on staging MCP · vendor widget + proxy as 4th service · new Railway project.

## Target topology (project `AgentB2C`, env `production`)

| Service | Source | Public? | Role |
|---|---|---|---|
| `redis` | Railway managed Redis | private | concierge session store |
| `hotel-search` | `agents/hotel_search_agent/Dockerfile` | private | A2A leaf (Mapbox + MCP) |
| `faq` | `agents/faq_agent/Dockerfile` | private | A2A leaf (MCP) |
| `concierge` | `agents/b2c_concierge/Dockerfile` | private | orchestrator + `/v3` facade |
| `widget` | new `web/Dockerfile` (`run_widget_proxy.py`) | **PUBLIC** | serves widget, forwards `/v3/*` → concierge (private) |

Only `widget` gets a public domain. Browser talks to one origin (proxy); proxy forwards server-side over the private net. Concierge stays private.

## Phase 0 — Prerequisite (BLOCKING, needs Fabien)
- [ ] `FLEET_READ_TOKEN` (fine-grained read PAT on `Dayuse-Labs/dayuse-agent-fleet`) — needed at **build time** for the pinned private `dayuse-agent-common` dep. Same secret CI uses. Without it, no image builds.

## Phase 1 — Code changes on branch `s-railway-deploy-demo` (reviewable, testable locally) ✅ DONE
- [x] Branch `s-railway-deploy-demo`.
- [x] Vendored full widget manifest into `web/vendor/` (39 files, 1.2 MB — hero JPGs + font dominate). Complete: every `@import`/`src`/`href`/JS-module ref is local (js/chat imports are all relative → dir is self-contained). Only external dep = Google Fonts CDN (client-side, degrades gracefully).
- [x] Patched `scripts/run_widget_proxy.py`: honors `PORT`/`HOST`/`WIDGET_BACKEND` env; **dual-stack IPv6 bind** (`_WidgetProxyServer` — http.server defaults AF_INET, can't bind `::`); auto-prefers vendored dir (no longer needs sibling repo).
- [x] New `web/Dockerfile` (stdlib only, no token). **Built + ran + smoke-tested in container**: binds `:::8090` dual-stack, all assets 200, chat meta `/v3/chat`, `/v3/*` forwards (502 when upstream down = forward path proven).
- [x] Patched 3 backend Dockerfiles: `# syntax=docker/dockerfile:1`, `apt-get install git` (the real reason they never built), fleet token via BuildKit secret-mount OR build ARG + CI's `insteadOf`, token scrubbed same-layer.
- [x] Gates: ruff ✅, mypy (34 files) ✅, guardrails ✅, `pytest -q` → 528 pass / 1 fail (pre-existing, untracked S-B `test_llm_meter_usage.py`, unrelated to this branch).
- [ ] **NOT YET**: build the 3 backend images (needs `FLEET_READ_TOKEN`) — will do locally with `--secret` to prove them BEFORE deploying.

## Phase 2 — Railway provisioning ✅ DONE
- [x] Project `AgentB2C` (a200e208-863d-4771-8b4d-03b5a6280904, workspace Inno Labs); Redis + 4 Dockerfile services (RAILWAY_DOCKERFILE_PATH per service, context = repo root); public domain on `widget` only → https://widget-production-3f56.up.railway.app

## Phase 3 — Env wiring ✅ DONE
- [x] 3 generated A2A bearers, cross-service card URLs, `CONCIERGE_REDIS_URL=${{Redis.REDIS_URL}}`, staging MCP + Mapbox + OpenAI from `.env`, `FLEET_READ_TOKEN` as build ARG on the 3 backends, `DAYUSE_MODEL=gpt-4o-mini`. Demo deviation: `CONCIERGE_LEAF_TIMEOUT_SECONDS=30` (see HANDOFF).

## Phase 4 — Deploy + verify ✅ DONE (evidence in HANDOFF)
- [x] All 5 services up (`Application startup complete`, bind `[::]`). Live via public URL: SEARCH (5 real hotels + pool filter), FAQ (real answer), ACK (template). Fixed en route: git-in-slim, Railway rejects BuildKit secret mount → build ARG, http.server IPv6 `::` bind.

## Phase 5 — Close out
- [x] `HANDOFF.md` dated block (topology, URL, env matrix, gotchas, timeout deviation).
- [ ] Commit on branch + push + MR (Fabien's review = gate, never self-merge) — pending Fabien's go on push/MR.
- [ ] Fabien to open the URL and confirm the widget renders cards visually (I verified API+page+assets via curl only).

## Caveats
- Staging MCP = sparse inventory → some "0 offres" cities, faithful to local not a quality signal.
- `DAYUSE_MODEL=gpt-4o-mini` mirrors local (`.env` `OPENAI_MODEL=gpt-5.2` is dead config, not read).
- 4 always-on services + Redis = small non-zero cost.

# Remédiation geo/multi-turn (S-G series, arbitrée 2026-07-23)

Plan : `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` · phases : `phases/SG1…SG9.md` · vue d'ensemble : `SESSIONS-CLAUDE-CODE.md` §S-G.

- [ ] S-G1 profil v2 + ops reducer (concierge)
- [ ] S-G2 intake contexte natif (facade) — après S-G1
- [ ] S-G3 résolveur géo multi-candidats (feuille, Opus, probe live d'abord)
- [x] S-G4 budgets timeout + RetryPolicy + Chester — branche `sg4-timeout-budgets`, Chester résolu (GPT-5.2 latency + ancien budget 10s, pas un bug), voir HANDOFF
- [ ] S-G5 pont déterministe + pagination — après S-G1+S-G3
- [ ] S-G6 dates/durées/demi-heures — après S-G5
- [ ] S-G7 locale/devise propagation — après S-G6
- [ ] S-G8 durcissement harness (∥ possible)
- [ ] S-G9 gate 81 cas ×3 + éval ranking — dernier
- [ ] Cross-repo MCP_B2C : ouvrir les demandes (minutes timeSlot, offset/exclusion, pricing) — `reports/MCP-B2C-REQUESTS.md` créé en S-G6/S-G7
- [ ] Ops : contrôle plateforme `DAYUSE_MODEL` (défaut committé = gpt-4o-mini, eval = gpt-5.2)
