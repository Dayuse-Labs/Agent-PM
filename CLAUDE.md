# CLAUDE.md — AgentB2C

Orchestrateur conversationnel B2C (ADK Python) remplaçant `agent-usa` (POC Flask en prod). Recherche hôtelière day-use : orchestrateur + 2 feuilles A2A + serveur MCP_B2C (Elasticsearch lecture seule).

## À lire AVANT de travailler

1. **`HANDOFF.md`** — état exact du chantier. **Ne jamais reconstruire ce qu'il dit exister.**
2. `SESSIONS-CLAUDE-CODE.md` — le découpage en sessions : une session = un scope, pas plus.
3. Selon la session : `SCAFFOLDING-BRIEF-PH2.md` (exécution Ph2), `PLAN-REWORK-AGENT-USA.md` (décisions A1-A4/D1-D7), `AUDIT-REWORK-2026-07.md` (baseline, spec des guards).

## Invariants (non négociables)

- **LiteLLM uniquement** (`DAYUSE_MODEL`, départ `gpt-4o-mini`) — jamais de SDK modèle direct. Zéro lock-in cloud (OCI, cibles Cloud Run/k8s, GCP = test).
- **A2A** entre orchestrateur et feuilles (Agent Cards signées) ; **MCP** vers les outils. Feuilles **stateless** : profil in/out via `DataPart` A2A, le Redis de session n'appartient qu'à l'orchestrateur.
- **Identité intérimaire (D7)** : réseau privé Railway + bearer vérifié côté feuille, exception documentée avec échéance. `dev-insecure` jamais déployé.
- **RGPD** : résidence EU, zéro contenu de message dans les métriques (verrouillé par test), colonne `is_synthetic` sur les logs, TTL Redis + rétention documentées. `baseline/` ne se commit JAMAIS (messages utilisateurs bruts).
- **Budget structurel ≤ 3 appels LLM/tour** typique (triage éco + LLM feuille éventuel + UNE synthèse streamée). Un guard ne relance jamais une boucle : 1 retry borné, puis correction déterministe.

## Architecture cible (résumé)

`b2c-concierge` = **spine code-owned** (pattern `cs_copilot` de dayuse-agent-fleet) : triage 1 appel LLM éco + fallback regex, table de routage en code, `RemoteA2aAgent` → feuilles `hotel-search-agent` (Mapbox + guards géo + MCP `search_offers`/`find_hotel_by_name`) et `faq-agent` (MCP `get_faq_conditions`) ; tools MCP inline : `get_hotel_details`, `compare_hotels`, `generate_booking_link`. Façade iso-contrat `POST /v3/chat` + SSE (event `progress` < 300 ms = TTFT mesuré, event `hotels`, puis tokens).

**15 guards déterministes** (recompté 2026-08-27, contre le code réel — `GUARD_SCORE_NAMES` dans `libs/b2c_common/b2c_common/scores.py` en est le contrat figé) : 11 portés depuis l'audit prod d'agent-usa (`tests/unit/application/test_audit_fixes_2026_06.py` + `test_loop_enforcement_and_name_lookup.py`, `test_named_hotel_card.py`, ~150 tests) — 3 guards géo (`geocode_echo_back`, `generic_location_demotion`, `state_anchoring`), 2 guards date (`date_hallucinated_year_rolled_forward`, `date_carryover_stale_floored`), `budget_integrity`, `timeslot_sanitization`, `recovery_ack`, `anti_clarification_loop`, `amenity_truthfulness`, `named_hotel_lookup` — plus 2 ajouts spécifiques à AgentB2C : le 12e = R9 (`booking_confirmation`) : `generate_booking_link` inappelable sans flag de confirmation dans l'état du tour ; le 13e = S-G12 (`hotel_link_truthfulness`, 2026-07-24) : aucun lien hôtel non vérifié contre le ground-truth du tour ; le 14e = M4 (`poi_anchor_coherence`, 2026-08-26) : un POI tier-2 à plus de 40 km de l'ancre du tour est jeté ; le 15e = UX1 (`filter_relaxation_honored`, 2026-08-27) : une rétraction de filtre d'équipement (« enlève le spa ») a réellement retiré la clé de la recherche.

**Budgets/timeouts (propriétaire unique par dépendance)** : feuille → Mapbox 1,5 s (1 retry), MCP 5 s (circuit-breaker) ; orchestrateur → appel feuille 10 s SANS retry (dégradation honnête) ; retries LLM au seul niveau LiteLLM. Min-instances 1 partout.

## Interdits de session (contexte)

- Ne JAMAIS lire `agent-usa/` en entier (53k lignes) : seulement les fichiers de tests pointés comme spec, et un fichier source précis si un test l'exige.
- Ne pas recharger le CSV de `baseline/` (82 Mo) — les chiffres sont dans `AUDIT-REWORK-2026-07.md` et `baseline-summary.json`.
- MCP_B2C : consommer ses tools, ne pas relire son code (repo séparé, contrat = descriptions des 6 tools).

## Commandes

```bash
# Setup (une fois par clone) — dayuse-agent-common est une dépendance git PINNÉE vers le repo
# privé Dayuse-Labs/dayuse-agent-fleet (accès ssh requis ; en CI : FLEET_READ_TOKEN)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python \
  -r agents/hotel_search_agent/requirements.txt -r agents/faq_agent/requirements.txt \
  -r agents/b2c_concierge/requirements.txt -r requirements-dev.txt -e libs/b2c_common
git config core.hooksPath .githooks   # guardrails en pre-commit

# ⚠️ NE PAS ajouter "google-adk[eval]==2.4.0" à la commande ci-dessus : l'extra tire
# google-cloud-aiplatform[evaluation], qui exige litellm<1.86 alors qu'on pin litellm==1.90.2
# -> résolution uv insatisfiable (les versions PyPI ont bougé depuis S3). google-adk[a2a] des
# requirements suffit pour pytest, run_local.sh et smoke. L'extra eval n'est nécessaire QUE pour
# `adk eval` : l'installer dans un venv jetable dédié (litellm y sera downgradé), comme le fait le
# job CI `eval` séparé — jamais dans le venv de dev.

# Run local — 3 services : concierge :8100, search :8101, faq :8102 (pids + logs dans .run-logs/ ;
# source .env si présent ; aucun appel LLM/MCP au boot). Stop : bash scripts/run_local.sh stop
bash scripts/run_local.sh

# Smoke e2e (les 3 services doivent tourner) — 1 tour ack + 1 search + 1 faq via l'orchestrateur
python scripts/smoke_e2e.py

# Tests (offline — ni réseau ni clé API)
.venv/bin/pytest -q

# Lint + typecheck (mêmes jobs qu'en CI)
.venv/bin/ruff check . && .venv/bin/mypy agents libs

# Guardrails statiques Dayuse (aussi exécutés par le hook pre-commit)
bash scripts/dayuse_guardrails.sh .

# Eval ADK (32 scénarios, 8 familles — score libre au stade squelette ; services up requis)
.venv/bin/adk eval agents/b2c_concierge/b2c_concierge evalset/evalset-v0.adk.json \
  --config_file_path evalset/test_config.json
```

Déploiement de la démo Railway : **`DEPLOY.md`** (topologie, procédure pas à pas, pièges) — ne jamais déployer sans l'avoir suivi.

CI GitHub Actions : `.github/workflows/ci.yml` (ruff, mypy, pytest, guardrails, job eval non bloquant). Secrets requis : `FLEET_READ_TOKEN` (lecture du repo fleet privé), `OPENAI_API_KEY` (job eval).

## Fin de session — OBLIGATOIRE

1. Tests + guardrails verts (jamais de HANDOFF « fait » sur du rouge).
2. **Mettre à jour `HANDOFF.md`** : bloc daté en tête (fait / reste / pièges découverts), remplacer les sections périmées.
3. Commit sur branche + MR — la review humaine de Fabien est le gate, ne jamais merger soi-même.
