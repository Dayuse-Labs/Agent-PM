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

**12 guards déterministes** — la spec exécutable est dans agent-usa : `tests/unit/application/test_audit_fixes_2026_06.py` (+ `test_loop_enforcement_and_name_lookup.py`, `test_named_hotel_card.py`, ~150 tests). Le 12e = R9 : `generate_booking_link` inappelable sans flag de confirmation dans l'état du tour.

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
  -r agents/b2c_concierge/requirements.txt -r requirements-dev.txt -e libs/b2c_common \
  "google-adk[eval]==2.4.0"
git config core.hooksPath .githooks   # guardrails en pre-commit

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

CI GitHub Actions : `.github/workflows/ci.yml` (ruff, mypy, pytest, guardrails, job eval non bloquant). Secrets requis : `FLEET_READ_TOKEN` (lecture du repo fleet privé), `OPENAI_API_KEY` (job eval).

## Fin de session — OBLIGATOIRE

1. Tests + guardrails verts (jamais de HANDOFF « fait » sur du rouge).
2. **Mettre à jour `HANDOFF.md`** : bloc daté en tête (fait / reste / pièges découverts), remplacer les sections périmées.
3. Commit sur branche + MR — la review humaine de Fabien est le gate, ne jamais merger soi-même.
