# HANDOFF — AgentB2C

État du chantier pour reprise en session fraîche. **Lire en entier avant d'agir ; ne pas reconstruire ce qui existe.** Mettre à jour en fin de CHAQUE session (bloc daté en tête).

## ⏱ État au 2026-07-17 — S4 terminée (feuille search : Mapbox réel + 3 guards géo + circuit-breaker MCP)

**Fait (branche `s4-guards-geo`, worktree dédié, ∥ avec S5 sur l'orchestrateur — zone touchée : `agents/hotel_search_agent/**` UNIQUEMENT)** :
- **`geo_guards.py`** : les 3 guards portés depuis `agent-usa/tests/unit/application/test_audit_fixes_2026_06.py` (sections geocode echo-back + state hints + ZIP anchor, generic place words, state anchoring) : `extract_state_hint_from_text`, `resolve_state_hint`, `geocode_echo_matches` (endonymes ß/ø/æ, alias courts, script non-latin, folding Saint/St), `select_us_postal_anchor`, `is_generic_location_token` / `demote_generic_city`, `anchor_state_context`. **26/26 tests de spec portés** (`tests/test_geo_guards.py`, 22 verbatim + 4 adaptés) + 2 tests de couverture supplémentaires = 28 tests dans ce fichier. **Adaptation assumée (pas un affaiblissement)** : agent-usa mute un `Conversation.preferences` long-lived ; cette feuille est stateless (B3) — la démotion générique et l'ancre d'état sont re-testées sur les fonctions pures dict-in/dict-out réellement utilisées ici (`demote_generic_city`, `anchor_state_context`), même scénario/même verdict, sans `Conversation`. **Hors périmètre volontaire** (ni nommé dans la phase, ni porté) : country-anchoring (`last_country_context`), currency-prior (`_geo_country_preferences`), homonyme ambigu (`ambiguous_homonym_pending`) — même fichier de spec agent-usa, audits différents, pas les 3 guards de cette phase.
- **`mapbox_client.py`** : client Mapbox Geocoding API v6 réel (`httpx.Client`, `limit=1`), budget 1,5 s + 1 retry (single-owner rule), cache mémoire borné (`OrderedDict`, éviction FIFO). 12 tests mockés (`httpx.MockTransport`, zéro réseau réel) : parsing, timeout+retry, 5xx, cache positif/négatif, bornage.
- **`geocode_tool.py`** : tool code-owned `geocode_location` (FunctionTool ADK, schéma généré sans erreur — vérifié) composant démotion → résolution d'état → appel Mapbox → validation echo-back → mise à jour de l'ancre ; **ne raise JAMAIS** — tout rejet devient `{"ok": False, "error": ..., "diagnostics": {...}}`. Câblé dans `root_agent.tools` (2e tool, après le McpToolset) ; instruction mise à jour (geocode AVANT `search_offers`, jamais de coordonnées inventées). 8 tests avec un faux client.
- **`mcp_guard.py`** : `CircuitBreaker` de `resilience.py` (S1, jusqu'ici non branché) posé sur `search_offers`/`find_hotel_by_name` via `before_tool_callback`/`after_tool_callback`/`on_tool_error_callback` — 3 échecs consécutifs → court-circuit instantané (`mcp_circuit_open`, zéro appel réseau, zéro exception), reset après 30 s. Classifieur de réponse MCP (isError/`error`/`structuredContent.ok=False`/`ok=False`), avec exemption explicite du stop `TOOL BUDGET` (pas un échec MCP). 15 tests (horloge fake, pas de sleep).
- **Bug trouvé en cours de câblage** : `resolve_state_hint` héritait de l'agent-usa d'origine un `country_code != "US"` qui traitait `None` (aucun signal pays) comme un pays non-US *résolu* et coupait la résolution texte à tort. Corrigé (`if country_code and country_code != "US" and country_resolved`) — sans régression sur les tests portés (qui passent toujours `"US"`/`"ES"` explicitement, jamais `None`).
- **`agent.py`** : `MAX_TOOL_CALLS` inchangé (2 = geocode + search, ou find_hotel_by_name seul) ; ordre des callbacks avant-tool = timing → budget → circuit MCP (premier non-None gagne, sémantique ADK). `README.md` + `requirements.txt` (pin explicite `httpx==0.28.1`, déjà tiré transitivement) mis à jour ; `.env.example` non touché (refusé par les permission settings, comme en S1/S2).
- **DoD exécutée verte** : `pytest agents/hotel_search_agent -q` → **96 passed** (63 nouveaux : 28 guards + 12 mapbox + 8 geocode_tool + 15 mcp_guard) ; `pytest -q` (repo entier) → **192 passed** ; `ruff check .` OK ; `mypy agents libs` OK ; `bash scripts/dayuse_guardrails.sh .` OK.
- **Addendum post-review (même jour, PR #5 ouverte, question de Fabien)** : `geo_guards.py` sourçait à la main le référentiel générique — table des 50 états US et folding des ligatures d'endonymes. Recherche faite (aucune lib géo utilisée nulle part dans l'écosystème Dayuse, y compris agent-usa qui hardcode pareil) → remplacé par `us==3.2.0` (unitedstates/python-us, CC0, exclut DC/territoires par défaut — vérifié 1:1 identique à l'ancien dict à la main) et `anyascii==0.3.3` (ISC, translittération Unicode→ASCII bien plus large que les 8 ligatures hardcodées, successeur d'Unidecode). Les listes réellement Dayuse-spécifiques (`_TEXT_UNSAFE_STATE_ABBREVS`, `_GENERIC_LOCATION_WORDS`, `_ECHO_NOISE_WORDS`, `STREET_SUFFIX_TOKENS`) restent en dur — jugement produit issu des audits prod, aucune lib ne les connaît. `usaddress` (parseur d'adresse probabiliste pour l'ancre ZIP) et `pycountry` (si les guards pays sont repris) évalués mais PAS adoptés maintenant — dépendance plus lourde/moins déterministe pour le premier, rien à remplacer aujourd'hui pour le second. Les 28 tests de `test_geo_guards.py` restent verts INCHANGÉS après le swap (même DoD que ci-dessus, re-exécuté).

**Reste** :
- L'enveloppe DataPart `SearchRequest`/`SearchResponse` (contract.py) n'est toujours PAS le mécanisme qui alimente réellement `root_agent` — l'agent lit toujours `query_params`/`profile_in` via l'instruction texte, pas via un pont pydantic. `geocode_location` accepte `profile_state_context`/`profile_location_hint` en paramètres explicites que le modèle doit recopier depuis ce qu'il voit de `profile_in` dans le prompt — le pontage propre (session → `ToolContext.state` → tool) reste à faire quand le profil de session (S5) sera posé côté orchestrateur.
- **Jamais testé contre le vrai Mapbox** (uniquement mocké) : `MAPBOX_ACCESS_TOKEN` à poser par Fabien avant tout smoke réel ; posture volontairement NON fail-closed (absent/vide → dégradation honnête, pas un crash au boot, à la différence du bearer D7).
- S5 (orchestrateur, ∥) : round-trip effectif de `profile_delta` → `profile_in` du tour suivant (le Redis de session lui appartient) ; c'est lui qui devra transmettre `profile_state_context`/`profile_location_hint` à cette feuille.
- Guards non portés dans cette session (voir ci-dessus) : country-anchoring / currency-prior / homonyme ambigu — à qualifier dans une session ultérieure si le besoin business se confirme.

**Pièges découverts en S4** :
- Le job CI `checks` (celui qui bloque) installe SANS `google-adk[eval]` — seul le job `eval` séparé l'installe (litellm y est downgradé à 1.85.x pour satisfaire `google-cloud-aiplatform[evaluation]`, sans effet sur `checks`). Reproduire le setup dev en incluant `google-adk[eval]` dans la MÊME commande `uv pip install` que les autres requirements est un résolveur insatisfiable (conflit `litellm` 1.90.2 vs <1.86.0) — installer sans cet extra pour tout ce qui n'est pas `adk eval`.
- `mypy` : réutiliser une variable de boucle for-unpacking (`for name, canonical in dict.items()`) puis la réassigner à un type `X | None` plus loin dans la même fonction fait échouer le typecheck même si la valeur est correcte à l'exécution — renommer la seconde variable.
- Ordre de vérification `_is_tool_failure` : le dict de court-circuit du tool-budget (`{"ok": False, "error": "TOOL BUDGET..."}）` a `ok=False` ET un `error` — le préfixe `TOOL BUDGET` doit être vérifié EN PREMIER (return anticipé), sinon le fallback `ok is False` le classe à tort comme un échec MCP et ouvre le breaker sur du contrôle de flux, pas une vraie panne.

## ⏱ État au 2026-07-17 — S3 terminée (socle transverse : lib commune, métriques, CI, éval)

**Fait (branche `s3-socle-transverse`, PR ouverte)** :
- **`dayuse_agent_common` en dépendance git PINNÉE** (mode d'install **acté avec Fabien** — décision de session) : `dayuse-agent-common @ git+ssh://…dayuse-agent-fleet.git@8071917…#subdirectory=libs/dayuse_agent_common` dans les requirements des 3 agents. Jamais de copie du code ; bump du SHA délibéré. ⚠️ repo fleet PRIVÉ : la CI et les builds d'image ont besoin d'un accès lecture (`FLEET_READ_TOKEN`, insteadOf https) — **secret à créer par Fabien sur le repo GitHub** ; wiring build Docker complet en S10/S11.
- **`libs/b2c_common`** (nouveau package interne, layout fleet, COPY dans les 3 Dockerfiles) : identité intérimaire D7 consolidée en UN point (`require_bearer_token` fail-closed + `BearerAuthMiddleware`) — la lib fleet ne vérifie AUCUN bearer entrant, le régime AgentB2C reste plus strict ; la bascule oidc-mtls (échéance S11) se fera dans ce seul module. **Verrou `dev-insecure`** : `test_no_dev_insecure_in_deploy_configs` échoue si la chaîne atteint Dockerfiles/workflows/manifests.
- **Métriques jour 1** : feuilles = `build_model()` (défaut B2C `gpt-4o-mini` conservé — ⚠️ le défaut de la lib est un slug OpenRouter) + callbacks lib (llm/tool timing + erreurs) + `make_tool_budget_callback(2)` ; PAS de `switch_model_callback` (trafic public). Spine = `enqueue_metric_event` sur `turn`/`leaf_call`/`llm_call` (phase=triage|synthesis, tokens+coût). **Noms d'agents renommés `b2c_hotel_search`/`b2c_faq`** (le nom EST le label `service` des métriques — dashes de la spec → underscores, contrainte identifiant ADK ; cartes + tests alignés, l'orchestrateur résout par URL donc zéro impact A2A). **Verrou RGPD étendu aux événements** (`test_metric_events_never_contain_message_content`) en plus des logs.
- **CI GitHub Actions** (`.github/workflows/ci.yml` — transposition du plan GitLab au host réel du repo, décision S1) : ruff + mypy + pytest + guardrails (bloquants), job `adk eval` non bloquant (skippé sans `OPENAI_API_KEY`). Configs : `ruff.toml` (défauts, py312), `mypy.ini` (pragmatique, tests exclus — 3 packages `tests` homonymes).
- **Evalset ADK** : `scripts/convert_evalset.py` (rejouable, validé pydantic) → `evalset/evalset-v0.adk.json` (32 cas, 118 tours, multi-tours préservés ; la rubrique `expected` = référence du dernier tour) + `evalset/test_config.json` (ROUGE 0,1 — indicatif en attendant un juge LLM).
- **DoD exécutée verte** : `ruff check .` OK ; `mypy agents libs` OK (19 fichiers — `mypy src/` adapté au layout réel) ; `pytest -q` → **129 passed** ; guardrails OK ; **`adk eval` complet : 32 cas exécutés, 2 passed / 30 failed** (score libre assumé : squelette + rubrique≠verbatim) ; **Postgres jetable docker** : `SELECT service, count(*) FROM llm_metric_events GROUP BY 1` → `b2c_concierge=8, b2c_faq=3, b2c_hotel_search=3` sur un smoke (feuilles via callbacks lib, spine via enqueues) + **0 row contenant du contenu de message** (vérifié en SQL).

**Reste** :
- Fabien : review + merge PR S3 ; créer le secret **`FLEET_READ_TOKEN`** (PAT lecture fleet) et `OPENAI_API_KEY` sur le repo GitHub — sans le premier, le job CI `checks` échoue à l'install.
- S4 (feuille search) : Mapbox + guards géo/date — l'eval montre exactement pourquoi (30/32 échecs dont la latence feuille > 10 s et l'absence de géocodage/ancrage date).
- `GET /model` (serving.py de la lib) volontairement NON branché : sa résolution (`resolved_model()`) divergerait du défaut B2C `gpt-4o-mini` — à brancher quand `DAYUSE_MODEL` sera posé partout en env de déploiement.

**Pièges découverts en S3** :
- `mypy` ne tolère pas les 3 packages `tests` homonymes (importlib pytest oui) → tests exclus du typecheck, source seulement.
- `adk eval` exige l'extra **`google-adk[eval]`** (rouge-score…) — absent des requirements des agents, installé par la CI eval et le setup dev.
- L'historique d'eval s'écrit dans `agents/…/.adk/eval_history/` → gitignoré (`**/.adk/`).
- Le process `adk eval` configure le root logging → les lignes `concierge_metric=` sortent en double dans ses logs (handler dédié + propagation) — cosmétique, pas un double comptage en base.

## ⏱ État au 2026-07-17 (suite) — post-merge S2 : MCP_B2C complet + retour au Bearer standard

**Fait (branche `fix-mcp-bearer-standard`, PR ouverte)** :
- ⚠️ **La PR #2 a été mergée à `b36a2e0`, AVANT les 2 derniers commits de la branche S2** (`d6dab14` compteur LLM visible au runtime, `0137c93` contrat MCP + date smoke + drain run_local) — ils n'étaient PAS dans main. **Cherry-pickés dans cette PR.** Leçon : après un push tardif sur une PR déjà mergée, GitHub ne re-merge rien et ne prévient pas.
- Côté MCP_B2C (fix de Fabien déployé le 2026-07-17, vérifié au probe) : **`Bearer <token>` accepté** (token brut toujours toléré en rétro-compat), et **les 6 tools sont exposés** (`get_faq_conditions` et `generate_booking_link` inclus). Les 2 feuilles sont **rebasculées sur le header Bearer standard** (RFC 6750) + tests/README alignés.
- `.env` : renommage `MCP_B2C_TOKEN` → `MCP_B2C_AUTH_TOKEN` fait par Fabien — plus aucun mapping nécessaire, `run_local.sh` + `smoke_e2e.py` tournent tels quels.

**Reste** : review + merge de cette PR, puis S3 (prompt dans `PROMPTS-SESSIONS.md`).

## ⏱ État au 2026-07-17 — S2 terminée (feuille faq-agent + orchestrateur b2c-concierge)

**Fait (branche `s2-faq-orchestrateur`, **PR #2 mergée le 2026-07-17** — mais voir bloc « suite » ci-dessus : les 2 derniers commits ont raté le merge)** :
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
- **MCP_B2C staging branché le 2026-07-17** (URL + token ajoutés par Fabien) — validé par probe direct : session OK, **vraies données** (`search_offers` Paris → NH Paris Gare de l'Est, 6 offres, payload 28 Ko). Découvertes de contrat, TOUTES vérifiées empiriquement :
  - ~~**Auth = token BRUT dans `Authorization`**~~ (résolu le 2026-07-17 : fix serveur déployé, Bearer standard accepté — voir bloc « suite ») ; renommage `.env` fait.
  - ~~Le staging n'expose que **4 tools**~~ (résolu : les 6 tools sont exposés depuis le redeploy du 2026-07-17).
  - `search_offers` **exige `lat`/`lon` numériques + `date`** — aucun géocodage serveur : le Mapbox de S4 est indispensable (aujourd'hui gpt-4o-mini fournit les coords de tête — les guards géo S4 rendront ça déterministe) ; « demain » sans date explicite part n'importe où (date anchoring S4 — le smoke épingle une date absolue).
- **Latence feuille search sur payload réel : ~10,5 s** (2 passes LLM internes obligatoires avec ADK — le modèle doit INGÉRER les 28 Ko — même avec l'instruction « top 5 compact » ajoutée) → **dépasse le budget 10 s de l'orchestrateur** → le tour search via concierge dégrade honnêtement de façon quasi systématique. Le budget 10 s est un invariant, on n'y touche PAS : la correction appartient à S4/S6 (troncature code-owned du payload tool AVANT le modèle, ground-truth ≤ 5, streaming). Preuve du chemin data : appel direct feuille = offres réelles compactes en 10,5 s.
- **Dérive de grounding observée** : sans tool disponible, le LLM feuille (faq) répond du savoir générique au lieu de refuser strictement — l'instruction seule ne suffit pas, confirmé empiriquement = spec vivante des guards S4-S7.
- Piège `run_local.sh` corrigé : après `kill`, attendre la mort effective du process (un uvicorn en drain tient encore le port et répond au probe de readiness à la place de son successeur → « Connection refused » juste après « ready »).

**Reste** :
- ~~Fabien : review + merge de la PR S2 ; re-run du smoke avec un `.env` réel~~ (faits le 2026-07-17).
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
