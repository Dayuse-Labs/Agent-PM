# HANDOFF — AgentB2C

État du chantier pour reprise en session fraîche. **Lire en entier avant d'agir ; ne pas reconstruire ce qui existe.** Mettre à jour en fin de CHAQUE session (bloc daté en tête).

## ⏱ État au 2026-07-16 — S1 terminée (socle repo + feuille hotel-search-agent)

**Fait (branche `s1-socle-feuille-search`, poussée sur GitHub — merge en attente de review)** :
- Remote : `github.com/Dayuse-Labs/AgentB2C` (privé — décision du 2026-07-16, GitHub Dayuse-Labs et non GitLab). **PR #1 ouverte** (`s1-socle-feuille-search` → `main`) : la review de Fabien reste le gate, rien n'est mergé.
- `git init` (main = docs seuls), `.gitignore` (baseline/ jamais commité), branche `s1-socle-feuille-search`.
- `agents/hotel_search_agent/` complet (pattern booking_qa de la fleet + overlay Dayuse) : `agent.py` (LiteLlm `DAYUSE_MODEL`→`gpt-4o-mini`, `McpToolset` streamable-http avec allowlist `["search_offers", "find_hotel_by_name"]`, timeout 5 s), `contract.py` (enveloppe stateless `SearchRequest{query_params, profile_in}` → `SearchResponse{results, profile_delta, diagnostics}` — champs métier volontairement ouverts, spec S4/S5), `resilience.py` (CircuitBreaker réel + testé, branché nulle part — TODO S4 Mapbox), `serve.py` (carte custom via `AgentCardBuilder` avec `securitySchemes.bearer-interim` + **middleware ASGI bearer D7 fail-closed**), Dockerfile (python:3.12-slim, non-root 10001, `--host ::`), agent-card.json statique, README (exception D7 + RGPD + staging≠shadow-run), .env.example.
- Racine : `scripts/dayuse_guardrails.sh` (copié fleet), `scripts/run_local.sh`, `.githooks/pre-commit` (activé via `core.hooksPath`), `pytest.ini`, `requirements-dev.txt`, `.venv` (uv, python 3.12), section Commandes de `CLAUDE.md` remplie.
- **DoD exécutée verte** : boot réel sur :8101 ; carte servie SANS bearer (`.name == "hotel_search_agent"`, `bearer-interim` déclaré) ; `GET /` sans bearer → 401, mauvais bearer → 401, bon bearer → 405 (≠401, gate passée) ; boot sans token → RuntimeError (fail-closed) ; `pytest -q` → 30 passed ; guardrails OK.

**Reste** :
- Fabien : review + merge de la PR #1 (github.com/Dayuse-Labs/AgentB2C/pull/1).
- S2 : faq-agent + orchestrateur (voir `phases/S02-faq-orchestrateur.md`).
- S3 : brancher `dayuse_agent_common` (`build_model()`, metrics, budget tool-calls), CI complète.
- Exception D7 ouverte : carte NON signée + bearer statique — bascule oidc-mtls au plus tard avant le canary S11 (documentée dans le README de la feuille).

**Pièges découverts en S1** :
- Le hook PreToolUse du plugin a été patché **dans le cache** (`~/.claude/plugins/cache/...`) — à corriger à la source du plugin, sinon toute réinstallation/mise à jour restaure le matcher divergent.
- `dayuse_guardrails.sh` : ajout obligatoire de `--exclude-dir='.venv*'` vs la version fleet — les site-packages de google-adk/litellm contiennent `import vertexai` et font échouer le check 2 quand on lance le script à la racine avec un venv local. Seule adaptation de fond.
- La fleet ne vérifie AUCUN bearer entrant ; AgentB2C oui (D7) — écart assumé, spec de la phase.
- `AgentCardBuilder.build()` tente une session MCP pour lister les tools (échec gracieux et instantané hors ligne) — l'import de `serve.py` reste offline-safe, mais ne pas s'étonner du warning.
- `to_a2a()` n'expose que POST sur `/` : un `GET /` authentifié répond 405 — c'est la preuve « ≠401 » de la DoD, pas une erreur.

**Port + env vars (feuille search)** : port **8101** (plage AgentB2C : 8100 concierge / 8101 search / 8102 faq ; la fleet occupe 8092/8093). Env : `DAYUSE_MODEL` (déf. `gpt-4o-mini`), `OPENAI_API_KEY`, `MCP_B2C_URL`, `MCP_B2C_AUTH_TOKEN` (header omis si vide), `HOTEL_SEARCH_MCP_TIMEOUT_SECONDS` (déf. `5.0`), `A2A_HOST` (écrit dans l'URL de la carte), `PORT`, `A2A_BEARER_TOKEN` (**obligatoire**, fail-closed). Détail : `agents/hotel_search_agent/README.md` + `.env.example`.

## ⏱ État au 2026-07-16 (initialisation, avant toute session de dev)

**Fait (hors de ce repo)** :
- Phase 0 complète : audit + baseline prod nettoyée + evalset → `AUDIT-REWORK-2026-07.md`, `evalset/evalset-v0.json` (32 scénarios, 8 familles), `baseline/` (données brutes, NE PAS COMMITER).
- MCP_B2C : les 6 tools sont codés et verts (459 tests, 98,6 %) — **les 2 derniers (`get_faq_conditions`, `generate_booking_link`) sont en review par Fabien, non mergés**. Docker/README du MCP (5.1/5.2) volontairement en attente.
- Design review D1 : GO avec réserves, décisions actées dans `PLAN-REWORK-AGENT-USA.md` §9 (D1 : 2 feuilles A2A — décision produit ; D7 : identité intérimaire ; B3 : feuilles stateless ; spine code-owned).

**Pas fait (ce repo)** : tout le code. Aucun scaffolding lancé. Pas de `git init`.

**Prochaine étape** : ~~lancer S1~~ (faite, voir bloc du 2026-07-16 ci-dessus) → S2 avec le prompt de `PROMPTS-SESSIONS.md`. Le suivi d'avancement des items de phase se tient ICI (compteurs par session).

**Pièges connus** :
- Le hook `PreToolUse` du plugin peut bloquer les écritures locales si la build installée est divergente (matcher sain = `mcp__gitlab__…|mcp__notion__…` uniquement — vérifier avant S1).
- Le MCP_B2C accessible en dev pointe sur l'ES de **staging** : notes/avis quasi vides, inventaire partiel. OK pour développer, INTERDIT pour le shadow-run/parité (exige ES prod, cf. plan Ph3.3).
- `oidc-mtls` de `dayuse_agent_common` est un stub `NotImplementedError` — d'où D7 intérimaire.
- La fleet a évolué : `cs_copilot` (spine code-owned conversationnel) et `booking_qa` (feuille cliente MCP streamable-http) sont les précédents à imiter.
