# HANDOFF — AgentB2C

État du chantier pour reprise en session fraîche. **Lire en entier avant d'agir ; ne pas reconstruire ce qui existe.** Mettre à jour en fin de CHAQUE session (bloc daté en tête).

## ⏱ État au 2026-07-17 — S2 terminée (feuille faq-agent + orchestrateur b2c-concierge)

**Fait (branche `s2-faq-orchestrateur`, PR ouverte — la review de Fabien reste le gate, rien n'est mergé)** :
- `agents/faq_agent/` : miroir exact de la feuille S1 (allowlist `["get_faq_conditions"]`, `FAQ_MCP_TIMEOUT_SECONDS` 5 s, bearer D7 fail-closed, carte non signée, Dockerfile :8102, README = D1 + parades latence + RGPD). ⚠️ côté serveur MCP_B2C, `get_faq_conditions` est **en review non mergé** : l'allowlist filtre à zéro tool en attendant, la feuille répond en le disant dans `diagnostics`.
- `agents/b2c_concierge/` : **spine code-owned** custom `BaseAgent` (pattern `cs_copilot`, PAS de LlmAgent+sub_agents) —
  - ack fast-path regex (0 LLM) → template ; **triage** 1 appel LLM éco `{family, language}` + **fallback regex** sur tout échec (aucun retry : LiteLLM est la seule couche de retry) ;
  - **table de routage EN CODE** (`routing.py`) : search/faq → `RemoteA2aAgent` (clients httpx **persistants** avec bearer D7 sortant par feuille ; **`asyncio.timeout` 10 s SANS retry** = le vrai plafond, le timeout httpx ne borne pas un stream) ; details/compare/booking → **stubs inline** (`inline_tools.py`, réponse template honnête, 0 LLM de plus ; le stub `generate_booking_link` ne produit AUCUN lien par construction = posture R9) ; ack → template ;
  - **dégradation honnête** (`templates.py`) : feuille injoignable → message qui le dit, zéro invention, pas de synthèse ;
  - **UNE synthèse** litellm par tour (squelette S6) ; échec → texte feuille servi verbatim (grounded) ;
  - **compteur LLM/tour** (`budget.py`) : cap 3, `LlmBudgetExceededError` au-delà ; test `test_spine.py::test_simple_search_turn_stays_within_llm_budget` échoue si > 3 ; métriques logs `b2c_concierge.metrics` **sans contenu de message** (verrouillé par `test_logs_never_contain_message_content`).
- **Restructuration nécessaire** : `serve.py` déplacé DANS chaque package (`<pkg>.serve:app`, Dockerfiles mis à jour) + `pytest --import-mode=importlib` + pythonpath des 3 agents — sans ça, collision du module `serve` entre les 3 services co-testés.
- `scripts/run_local.sh` : boote les 3 services (pids + logs `.run-logs/`, readiness = carte, `stop`) ; `scripts/smoke_e2e.py` : 3 tours (ack + search + faq) via l'orchestrateur.
- **DoD exécutée** : `pytest -q` → **110 passed** ; guardrails OK ; boot des 3 services OK ; **smoke PASS** — d'abord sans clé (dégradation honnête exercée de bout en bout), puis **avec `OPENAI_API_KEY` (.env ajouté par Fabien le 2026-07-17)** : chemin nominal LLM confirmé aux métriques runtime — ack `llm_calls=0` (6 ms), search et faq `llm_calls=3 phases=triage,leaf_llm,synthesis status=ok` (~6,8 s). ⚠️ `OPENAI_MODEL` (ajouté aussi) n'est lu par RIEN — le knob modèle est `DAYUSE_MODEL`.
- **MCP toujours absent du .env** (`MCP_B2C_URL` manquant) : les feuilles répondent SANS données tool. Observation importante : sans tool, le LLM feuille **dérive vers du savoir générique** (« Les conditions d'annulation dépendent de l'hôtel… ») au lieu de refuser strictement — c'est exactement la classe de fabrication que les guards S4-S7 doivent verrouiller (l'instruction seule ne suffit pas, confirmé empiriquement). À re-smoker avec `MCP_B2C_URL` staging pour le chemin nominal complet LLM+MCP.

**Reste** :
- Fabien : review + merge de la PR S2 ; re-run du smoke avec un `.env` réel (validation du chemin nominal).
- S3 : `dayuse_agent_common` (`build_model()` per-phase — le triage doit rester éco quand le modèle de synthèse montera —, `metrics_pg` → `llm_metric_events` + verrou test contenu, budget tool-calls), CI complète.
- Notes S4/S5 : l'enveloppe DataPart `{query_params, profile_in}` n'est **pas encore émise par le spine** (les feuilles reçoivent le texte utilisateur transmis par `RemoteA2aAgent` ; mécanisme identifié pour S4/S5 : encodage `inline_data` `<a2a_datapart_json>` du part converter ADK) ; sessions du concierge en mémoire process (Redis + TTL = S5) ; comportement historique de `RemoteA2aAgent` en multi-tour à trancher en S5 (`full_history_when_stateless`).
- Exception D7 toujours ouverte — désormais sur **3 services** (cartes non signées + bearers statiques) ; échéance inchangée : oidc-mtls avant le canary S11.

**Pièges découverts en S2** :
- `RemoteA2aAgent` construit le message sortant à partir des **événements de session** (aucun hook « message override ») ; le spine consomme les événements du leg **sans les re-yield** → réponse A2A propre côté client, MAIS la réponse feuille n'est pas persistée en session (le multi-tour se règle en S5 avec le profil).
- Le timeout httpx ne plafonne PAS une réponse streamée (reset à chaque chunk) : le budget 10 s réel est l'`asyncio.timeout` de `_run_leaf`.
- `.env` / `.env.example` sont **refusés par les permission settings** de l'agent Claude Code — les variables sont documentées dans les README de chaque service à la place.
- Un token sortant vide n'est pas fatal au boot du concierge : la feuille fail-closed répond 401 et le tour dégrade honnêtement (jamais d'auth contournée) — comportement voulu, documenté dans le README concierge.

**Ports + env (concierge)** : port **8100**. Env : `DAYUSE_MODEL` (déf. `gpt-4o-mini`), `OPENAI_API_KEY`, `HOTEL_SEARCH_CARD_URL` / `FAQ_AGENT_CARD_URL` (déf. localhost:8101/8102), `HOTEL_SEARCH_A2A_TOKEN` / `FAQ_AGENT_A2A_TOKEN` (bearers D7 sortants, par feuille), `CONCIERGE_LEAF_TIMEOUT_SECONDS` (10), `CONCIERGE_TRIAGE_TIMEOUT_SECONDS` (5), `CONCIERGE_SYNTHESIS_TIMEOUT_SECONDS` (15), `CONCIERGE_SYNTHESIS_NUM_RETRIES` (1), `A2A_HOST`, `PORT`, `A2A_BEARER_TOKEN` (**obligatoire**, fail-closed). Feuille faq : mêmes vars que la feuille search avec `FAQ_MCP_TIMEOUT_SECONDS`, port **8102**. Détail : README de chaque service.

## ⏱ État au 2026-07-16 — S1 terminée (socle repo + feuille hotel-search-agent)

**Fait (branche `s1-socle-feuille-search`, poussée sur GitHub — merge en attente de review)** :
- Remote : `github.com/Dayuse-Labs/AgentB2C` (privé — décision du 2026-07-16, GitHub Dayuse-Labs et non GitLab). **PR #1 ouverte** (`s1-socle-feuille-search` → `main`) : la review de Fabien reste le gate, rien n'est mergé.
- `git init` (main = docs seuls), `.gitignore` (baseline/ jamais commité), branche `s1-socle-feuille-search`.
- `agents/hotel_search_agent/` complet (pattern booking_qa de la fleet + overlay Dayuse) : `agent.py` (LiteLlm `DAYUSE_MODEL`→`gpt-4o-mini`, `McpToolset` streamable-http avec allowlist `["search_offers", "find_hotel_by_name"]`, timeout 5 s), `contract.py` (enveloppe stateless `SearchRequest{query_params, profile_in}` → `SearchResponse{results, profile_delta, diagnostics}` — champs métier volontairement ouverts, spec S4/S5), `resilience.py` (CircuitBreaker réel + testé, branché nulle part — TODO S4 Mapbox), `serve.py` (carte custom via `AgentCardBuilder` avec `securitySchemes.bearer-interim` + **middleware ASGI bearer D7 fail-closed**), Dockerfile (python:3.12-slim, non-root 10001, `--host ::`), agent-card.json statique, README (exception D7 + RGPD + staging≠shadow-run), .env.example.
- Racine : `scripts/dayuse_guardrails.sh` (copié fleet), `scripts/run_local.sh`, `.githooks/pre-commit` (activé via `core.hooksPath`), `pytest.ini`, `requirements-dev.txt`, `.venv` (uv, python 3.12), section Commandes de `CLAUDE.md` remplie.
- **DoD exécutée verte** : boot réel sur :8101 ; carte servie SANS bearer (`.name == "hotel_search_agent"`, `bearer-interim` déclaré) ; `GET /` sans bearer → 401, mauvais bearer → 401, bon bearer → 405 (≠401, gate passée) ; boot sans token → RuntimeError (fail-closed) ; `pytest -q` → 30 passed ; guardrails OK.

**Reste** :
- ~~Fabien : review + merge de la PR #1~~ (mergée le 2026-07-16).
- ~~S2 : faq-agent + orchestrateur~~ (faite, voir bloc du 2026-07-17 ci-dessus).
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
