# S-G10 — fixes issus de l'audit S-G9 (branche `sg10-geo-fixes`, 2026-07-23)

Périmètre approuvé par Fabien : 4 fixes + tests + re-vérification live.

- [x] **Fix 1 (P0) — `distance_origin` niché dans `profile_delta`** (`response_bridge.py::emit_search_datapart`)
  - [x] Nester le dict dans `profile_delta` ; corriger le test feuille (assertion top-level → nichée)
  - [x] Test de soudure côté concierge (`tests/test_leaf_concierge_seam.py` — emit réel → `apply_profile_delta` → `build_active_filters`)
  - [x] Corriger le type vestige `profile.py` (`str | None` → `dict[str, Any] | None`) + tests concierge qui passaient une string
- [x] **Fix 2 (P0) — Gate 1 : tier inventaire gamé par micro-homonymes** (`geo_resolver.py`)
  - [x] Le tier quasi-dur exige `inventory >= 3` (`_MIN_TIER_INVENTORY`) ; en dessous, inventaire = poids soft seulement
  - [x] Tests nommés : Budapest HU vs GA (inv=1) → clarify ; La Défense/Al Aïn ; gros marchés (inv≥3) inchangés
- [x] **Fix 3 (P0-bis) — fallback `language` Mapbox** (`geocode_tool.py` + injection `language_hint`)
  - [x] Injecté depuis `profile_in.language`, utilisé SEULEMENT pour le param Mapbox `language` — test verrouille que le prior pays (`_locale_country`) n'est jamais nourri par le triage
- [x] **Fix 4 (P1) — filet concierge** (`agent.py`) : dégrade seulement si `leaf_text is None` ET `response` vide ; double échec → template dégradé, jamais de message vide
- [x] **Fix 5 (P1) — exonymes echo-guard** (`geo_guards.py`) : table Wien/Vienna + 15 paires (« vienne » exclu exprès — vraie ville FR)
- [x] **Fix 6 (découvert au probe) — clarify → tier-2 Search-Box** (`geocode_tool.py`) : un clarify avec zone nommée tente d'abord le POI Search-Box (echo-validé) avant de poser la question
- [x] **DoD** : 872 passed (+14) · ruff OK · mypy 38 fichiers OK · guardrails OK (1 échec préexistant `test_llm_meter_usage`, hors zone, documenté)
- [x] **Live (gpt-5.2)** : geo-budapest → **PASS 2/2** (`country_code=HU`, le POI « Keleti station » désambiguïse) ; geo-la-defense → plus jamais AE 2/2 (clarify honnête) ; `distance_origin` présent sur tous les tours de recherche ; `eval_ranking.py` → **2 échantillons scorés** (precision@5=0.4, NDCG@5=0.27 — pipeline débloquée, pas un baseline)
- [x] HANDOFF.md (bloc daté) + commit + MR (review Fabien = gate, pas de merge)

## Review S-G10 (commit 1 — fixes audit)
6 changements, tous petits et localisés : 2 fichiers feuille cœur (`geo_resolver.py` ~10 lignes, `geocode_tool.py` ~30), 2 guards (`geo_guards.py` table + 3 lignes, `response_bridge.py` 4 lignes), concierge (`agent.py` 10 lignes, `profile.py` 1 ligne de type). 14 tests neufs, dont 2 cas d'échec S-G9 nommés en régression et 1 test de soudure cross-package qui manquait structurellement.

# S-G10 bis — décisions Fabien D1-a/D2-a/D3-a + arbitrages D5/D6/D7 (même branche, commit 2)

- [x] **D1-a — fixtures GPS** : `native_context.geolocation` → `client_geo_context.device.{latitude,longitude,permission:"granted"}` (2 cas prod_wounds) ; runner forwarde `client_geo_context` + `_resolve_origin` lit les 2 formes
- [x] **D1 follow-up (découvert live)** : la feuille n'avait AUCUN chemin de recherche GPS-only — `geocode_location` résout désormais sur le fix GPS du profil quand rien n'est géocodable (jamais quand une zone/landmark est nommée — Gate 3) ; vérifié live : Detroit « near me » → 4 hôtels, `distance_origin.type="gps"`
- [x] **D2-a — zone vs city** : nouveau type d'assertion `filter_place` (zone OU city OU resolved_city) dans le runner + 9 assertions migrées ; `filter_equals` accepte un dict structuré (`date_reference`) contre le token littéral via `expression` ; `check_zone_change` S-G8 accepte le déplacement en `city` ; + règle nom-exact du resolver (« Fort Lauderdale » tapé exactement ne clarifie plus contre « Lauderdale, MN ») — vérifié live : `carry_same_time_0` et `zone_change_0` **PASSENT** (0/3 avant)
- [x] **D3-a — `requires_clarification` minimal non-bloquant** : chaîne feuille (capture geocode_ambiguous → DataPart flag + question déterministe) → marker concierge → façade ; vérifié live : la-defense → `requires_clarification: true`, `outcome_counts.safe_clarification: 1` (structurellement 0 avant)
- [x] **D5 (mon arbitrage)** : limite mono-agent acceptée + documentée ; skew temporel divulgué (`ground_truth_fetched_at`, `n_samples_with_past_date` + warning) ; post-filtre minute-exact reproduit dans le pool (mêmes sémantiques + fallback A4-c)
- [x] **D6 (mon arbitrage)** : la règle nom-exact du resolver EST le poli principal (supprime le pire cas) ; le filtrage écho des options résiduelles (fuzz colombien de la-defense) volontairement non fait — risque de sur-filtrage > gain
- [x] **D7 (mon arbitrage) : DIFFÉRÉ** — honorer `_eval_clock` (horloge fournie par le client) = surface d'injection ; à designer gated (env flag éval) dans une session dédiée ; `check_date_reference` reste approximatif tant que les runs sont same-day
- [x] DoD : 889 passed (+17), pack tests 11 passed, ruff/mypy/guardrails OK
- [x] Live (gpt-5.2) : budapest PASS, carry_same_time_0 PASS, zone_change_0 PASS, detroit GPS tour 1 = 4 hôtels ancrés GPS, la-defense = clarify honnête flaggé, ranking eval 1 échantillon (precision@5=1.0, NDCG@5=0.83)

---

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
