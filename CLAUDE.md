# CLAUDE.md — AgentB2C

Orchestrateur conversationnel B2C (ADK Python) qui remplace `agent-usa` (POC Flask) : depuis la bascule d'ai.dayuse.com (2026-10-26), c'est la pile Railway (`DEPLOY.md`) qui sert les **vrais utilisateurs**, sur **MCP_B2C prod**. Recherche hôtelière day-use : orchestrateur + 2 feuilles A2A + serveur MCP_B2C (Elasticsearch lecture seule) + widget. Dans `HANDOFF.md`, « prod » désigne cette pile ; les blocs antérieurs à la bascule l'appellent encore « la démo ».

## À lire AVANT de travailler

1. **`CHANTIERS.md`** — la liste vérifiée des chantiers ouverts (preuve, actions, prompt prêt) et ce qu'il ne faut PAS relancer. Prouver par une commande qu'un item est encore ouvert avant de planifier dessus. `tasks/todo.md` n'est pas une liste de chantiers (l'ancienne, fausse, est archivée).
2. **`HANDOFF.md`** — ses blocs datés en tête donnent l'état exact. **Ne jamais reconstruire ce qu'il dit exister.** Les blocs antérieurs au 2026-09-14 sont dans `HANDOFF-ARCHIVE.md` : à chercher par date ou `grep`, jamais à lire en entier.
3. Si la session exécute un plan orchestre : `plans/<nom>/` (`HANDOFF.md` = décisions, `PROGRESS.md`, `PREREQUISITES.md` = étapes humaines) ; sa source est dans `phases/<NOM>/`, sa branche d'intégration est `plan/<nom>`.
4. `tasks/lessons.md` — les corrections de Fabien, à ne pas refaire.

Historique, à n'ouvrir que sur besoin précis : `SESSIONS-CLAUDE-CODE.md` (découpage S1-S11, S-G, S-L), `PLAN-REWORK-AGENT-USA.md` (décisions A1-A4/D1-D7), `AUDIT-REWORK-2026-07.md` (baseline agent-usa), `SCAFFOLDING-BRIEF-PH2.md`.

## Invariants (non négociables)

- **LiteLLM uniquement** — jamais de SDK modèle direct. Zéro lock-in cloud (OCI, cibles Cloud Run/k8s, GCP = test).
- **Modèles par rôle** (`libs/b2c_common/b2c_common/llm_params.py`) : `DAYUSE_MODEL_TRIAGE` / `DAYUSE_MODEL_SYNTHESIS` > `DAYUSE_MODEL` > défaut du code `openai/gpt-6-luna` ; les feuilles ne lisent que `DAYUSE_MODEL`. Prod Railway : feuilles `openai/gpt-6-luna` (depuis le 2026-10-15), triage `openai/gpt-6-luna` (bascule M1, le 2026-10-27), synthèse `gpt-5.2` (`DAYUSE_REASONING_EFFORT=low`). Le concierge porte aussi `DAYUSE_MODEL=gpt-5.2` : `DAYUSE_MODEL_TRIAGE` se pose, ne se supprime jamais (le triage retomberait sur gpt-5.2). Le `.env` local ne fixe aucun `DAYUSE_MODEL*` : en local tout tourne sur le défaut, pas sur le mélange de la prod. **Effort par rôle** (depuis le 2026-10-19) : `DAYUSE_REASONING_EFFORT_{ROLE}` > défaut du rôle (`TRIAGE` et `JUDGE` = `none`, `_REASONING_EFFORT_DEFAULTS`) > `DAYUSE_REASONING_EFFORT` ; le `low` de la prod n'atteint donc plus le triage. Le juge du gate (`evals/judge.py`) = `RELEASE_GATE_JUDGE_MODEL` > `DEFAULT_MODEL`, il ne suit jamais `DAYUSE_MODEL` (la pile qu'il note).
- **Piège gpt-6** : litellm 1.90.2 ne connaît pas gpt-6, `llm_params` ajoute `allowed_openai_params`, `max_completion_tokens` et `reasoning_effort="none"`. Un effort autre que `none` sur une feuille gpt-6 = tout appel d'outil en 400 : ne jamais mettre `DAYUSE_REASONING_EFFORT` dans le `.env` local (`run_local.sh` l'exporte aux 3 services), ne jamais changer de famille de modèle par la seule variable d'env. gpt-4o-mini s'arrête le 2027-01-14 : le juge du gate et le triage sont passés à luna (prompt de triage resserré en 2 itérations mesurées, `reports/TRIAGE-GPT6-AB-2026-10.md` §5 ; ce prompt fait régresser mini, donc retour arrière = code ET variable) ; les 3 évaluateurs Langfuse aussi, le 2026-10-27 (« Output token limit » coupé et « Additional options » `{"reasoning_effort": "none"}`, réglables dans l'UI seulement : `observability/langfuse/evaluators.json`) ; reste `baselines.json` à refaire depuis un réseau qui joint MCP_B2C. Mesurer le triage = `scripts/measure_triage_models.py` (vraie `classify()`, fixture `evals/triage_inputs.jsonl`).
- **A2A** entre orchestrateur et feuilles (Agent Cards servies NON signées : exception D7 jusqu'à la bascule oidc-mtls, au plus tard le 2027-01-31) ; **MCP** vers les outils. Feuilles **stateless** : profil in/out via `DataPart` A2A, le Redis de session n'appartient qu'à l'orchestrateur.
- **Identité intérimaire (D7)** : réseau privé Railway + bearer vérifié côté feuille, exception documentée avec échéance : **2027-01-31** (prolongée le 2026-10-26 pour la bascule d'ai.dayuse.com ; compensations et rotation des bearers dans `CHANTIERS.md` A1). `dev-insecure` jamais déployé.
- **RGPD** : résidence EU, zéro contenu de message dans les métriques, scores Langfuse, logs et `turn_facts` (verrouillé par test), colonne `is_synthetic` sur les logs, TTL Redis + rétention documentées. `baseline/` ne se commit JAMAIS (messages utilisateurs bruts, exports de prod). **Exception décidée (2026-10-20)** : l'événement Amplitude `ai_agent__message_sent` porte le message de l'utilisateur (`prompt`, tronqué à 500 caractères), envoyé par le widget vers Amplitude EU, accès restreint dans l'entreprise ; jamais la réponse de l'agent.
- **Analytics produit = Amplitude, depuis le widget seul** : contrat figé `contracts/amplitude_events.json` (événements `ai_agent__*` + `pageview`, propriétés, enums, Session Replay à 5 %), verrouillé côté serveur par `tests/test_amplitude_contract.py` et côté widget par `tests/widget/widget_amplitude_contract.test.mjs` : ajouter, jamais renommer ni retirer. Le serveur n'envoie rien à Amplitude ; ce que lui seul sait passe par le bloc `turn_facts` de la réponse `/v3` (`agents/b2c_concierge/b2c_concierge/turn_facts.py`). Clé Production seulement sur `ai.dayuse.{tld}`, Staging/Dev partout ailleurs ; `?du_synthetic=1` marque `is_synthetic` et pose `X-Dayuse-Synthetic`. Réconciliation avec Langfuse : `conversation_id` = `session_id` Langfuse, `langfuse_trace_id` = un tour.
- **Budget structurel : 3 créneaux LLM par tour, plafond dur** (`MAX_LLM_CALLS_PER_TURN`, `agents/b2c_concierge/b2c_concierge/budget.py` ; le 4e lève `LlmBudgetExceededError`) : triage éco + feuille (1 créneau ; la feuille recherche fait 2 appels réels) + UNE synthèse streamée (ses retries LiteLLM restent dans son créneau). La question de lieu (lieu manquant, fait de la feuille ; depuis le 2026-10-29, le lieu seul, avec l'envie lue par le triage et les puces « près de moi » + villes du marché) est un gabarit : triage + feuille, sans synthèse. Un guard ne relance jamais une boucle : correction déterministe.

## Architecture (résumé)

`b2c-concierge` (:8100) = **spine code-owned** (pattern `cs_copilot` de dayuse-agent-fleet) : triage 1 appel LLM éco + repli regex, table de routage en code, `RemoteA2aAgent` → feuilles `hotel-search-agent` (:8101 ; outil code `geocode_location` qui reçoit un `GeoIntent` v1.1, Mapbox + guards géo, MCP `search_offers`/`find_hotel_by_name`) et `faq-agent` (:8102 ; MCP `get_faq_conditions`). Tools MCP inline du concierge : `get_hotel_details`, `compare_hotels`, `generate_booking_link`, `find_hotel_by_name` (nom lu par le triage, jamais le message brut). Façade iso-contrat `POST /v3/chat` (JSON) et `POST /v3/chat/stream` (SSE : `progress` < 300 ms = TTFT mesuré, `hotels`, `booking_card`, `token`, puis toujours `done`) ; aussi `/v3/chat/session/reset`, `/v3/feedback` et `/v3/chat/welcome` (accueil de l'app mobile, sans LLM). Widget : `web/` servi par `scripts/run_widget_proxy.py` (:8090 → :8100), seul service public de la prod, non lancé par `run_local.sh`.

**État de session** (concierge seul, Redis) : `pending_clarification`, `pending_search`, `region_anchor`, `entry_market_country`, `date_checked` / `date_announced` (depuis le 2026-10-28, plus de question de date isolée : lieu connu → recherche aujourd'hui, ou demain après l'heure limite, et la réponse dit le jour retenu avec les puces de jour, une fois par session ; lieu manquant → UNE question sur le lieu seul (2026-10-29 : elle reprend l'envie `wish` du triage, puces « près de moi » + villes du marché `market_cities.py` ; une réponse sans lieu cherche la ville principale du marché, `default_place`) — remplace la règle QA du 2026-10-20 et la question lieu + jour du 2026-10-28), `entry_source` (le `source` du 1er tour : `dayuse_box` → une FAQ est suivie de la question de lieu), `device_location_refused` (un tour : « près de moi » sans position) — modèle décrit dans le bloc QA14707 du 2026-10-16 de `HANDOFF.md` ; tout portage (dont #134) s'y aligne.

**18 guards déterministes** — contrat figé = `GUARD_SCORE_NAMES` (`libs/b2c_common/b2c_common/scores.py`, compte verrouillé par `libs/b2c_common/tests/test_scores.py`) : ajouter en fin de tuple, jamais renommer ni retirer. 11 portés de l'audit prod d'agent-usa (spec d'origine dans le repo voisin `../agent-usa/tests/unit/application/`, pas ici) : 3 géo (`geocode_echo_back`, `generic_location_demotion`, `state_anchoring`), 2 date (`date_hallucinated_year_rolled_forward`, `date_carryover_stale_floored`), `budget_integrity`, `timeslot_sanitization`, `recovery_ack`, `anti_clarification_loop`, `amenity_truthfulness`, `named_hotel_lookup`. 7 propres à AgentB2C : `booking_confirmation` (R9 : `generate_booking_link` inappelable sans confirmation dans l'état du tour), `hotel_link_truthfulness` (aucun lien hôtel non vérifié), `poi_anchor_coherence` (POI tier-2 à plus de 40 km de l'ancre jeté), `filter_relaxation_honored` (« enlève le spa » retire vraiment le filtre), `date_served` (la recherche a tourné sur le jour demandé, sinon la réponse le dit), `window_match` (chaque carte couvre le créneau selon `b2c_common.timeslot`, l'unique définition), `refinement_unchanged` (un affinage qui remet les mêmes offres le dit). Les guards géo/date, `poi_anchor_coherence` et `filter_relaxation_honored` se déclenchent dans la feuille et remontent par la clé `guards_fired` du DataPart. Depuis QA14707, `anti_clarification_loop` lit l'état, jamais le texte : `pending_clarification.asked` pour les questions de lieu (gabarit ; au 3e envoi, aucune question) et `pending_search.asked` pour les questions libres (au-delà de `CLARIFICATION_MAX_ASKS = 2`, la synthèse ne demande rien). Les replis qui répondent quand même ont leurs scores `FALLBACK_SCORE_NAMES` (`synthesis`, `mcp_error`, `named_hotel_not_found`), même contrat.

**Budgets/timeouts (propriétaire unique par dépendance)** : feuille recherche → LLM 15 s + 1 relance LiteLLM, Mapbox 1,5 s + 1 retry, MCP 5 s + circuit-breaker (3 échecs, 30 s ; `mcp_guard.py`), recherches en plus (sonde J+1, sauvetage zéro résultat ≤ 2 appels sonde comprise, complétion, page locale de `geo_rank` attendue ≤ 2 s) lancées seulement dans les 20 s du début du tour de la feuille et arrêtées à la première erreur, remontée au disjoncteur (`extra_calls.py`, `HOTEL_SEARCH_EXTRA_CALLS_DEADLINE_SECONDS`) ; feuille FAQ → LLM 20 s + 1 relance LiteLLM, MCP 5 s ; concierge → MCP inline 5 s, triage 2 tentatives de 4 s (la 2e sur timeout ou erreur de connexion seulement, dans le créneau du triage ; `max_retries=0` côté SDK, sans quoi il relance lui-même, ~17 s), synthèse 15 s, appel feuille SANS retry à 45 s (un appel bloqué + sa relance, tous deux à T, + les outils : recherche 2 × 15 + 3 + 5, FAQ 2 × 20 + 5) par défaut, `CONCIERGE_LEAF_TIMEOUT_SECONDS` écrase les deux (30 s en prod tant qu'elle n'est pas retirée). La relance des feuilles (`LLM_CALL_KWARGS`) = `retry_policy` (timeout et 429 seulement) + `max_retries=0`, jamais `num_retries` : litellm 1.90.2 le passe aussi au SDK comme `max_retries`, 3 requêtes au lieu de 2 (`tests/test_leaf_llm_call_budget.py`). Un frame `progress` suit chaque appel feuille : le proxy du widget coupe un flux muet 60 s, donc triage (8 s) + feuille (45 s), puis la synthèse (2 × 15 s), sont deux fenêtres de silence distinctes. Retries LLM au seul niveau LiteLLM.

## Interdits de session (contexte)

- Ne JAMAIS lire le repo voisin `../agent-usa` en entier (~60k lignes de `src/`) : seulement les tests pointés comme spec, et un fichier source précis si un test l'exige.
- Ne pas recharger `baseline/conversation_logs.csv` (82 Mo) — les chiffres sont dans `AUDIT-REWORK-2026-07.md` et `baseline/baseline-summary.json` (local, non versionné).
- MCP_B2C (repo voisin `../MCP_B2C`, GitLab `mcp-dayuse`) : consommer ses tools, ne pas relire son code sauf un fichier précis justifié. Le contrat = `contracts/mcp_b2c_tools.json` (8 tools + catalogue `list_amenities`), vérifié hors ligne par `tests/test_mcp_contract.py`.

## Commandes

```bash
# Setup (une fois par clone) — dayuse-agent-common est une dépendance git PINNÉE vers le repo
# privé Dayuse-Labs/dayuse-agent-fleet (accès ssh requis ; en CI : FLEET_READ_TOKEN)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python \
  -r agents/hotel_search_agent/requirements.txt -r agents/faq_agent/requirements.txt \
  -r agents/b2c_concierge/requirements.txt -r requirements-dev.txt -e libs/b2c_common
git config core.hooksPath .githooks   # guardrails en pre-commit
# ⚠️ Ne jamais ajouter "google-adk[eval]" à ce venv : l'extra exige litellm<1.86 alors qu'on pin
# litellm==1.90.2 (résolution uv insatisfiable). Rien dans le repo n'en a plus besoin.

# Run local — 3 services : concierge :8100, search :8101, faq :8102 (pids + logs dans .run-logs/ ;
# source .env si présent ; aucun appel LLM/MCP au boot ; pas de reload : relancer après chaque
# modification). Stop : bash scripts/run_local.sh stop
bash scripts/run_local.sh

# Smoke e2e (les 3 services doivent tourner) — 1 tour ack + 1 search + 1 faq via l'orchestrateur
python scripts/smoke_e2e.py

# Tests (offline — ni réseau ni clé API) — ~25 s pour ~3 000 tests (2026-10-19), dont ~10 s pour
# tests/test_calendar_rot.py, qui rejoue TOUTE la suite dans un sous-processus, horloge décalée de
# +400 j (tests/timeshift_plugin.py) : tout test rouge fait aussi tomber ce garde (2 vagues de
# pourrissement : PR #71, #114). Une suite à plusieurs minutes est anormale : jusqu'au 2026-10-26,
# les tests serve-auth ouvraient une vraie session MCP_B2C à chaque import de `serve.py` (52
# requêtes par run, 5-6 min quand MCP était injoignable) ; ils la stubbent désormais. Lancer
# `pytest -q --durations=15` avant d'accuser le code. Les tests JS du widget
# (tests/widget/*.test.mjs) passent par pytest (node --test, skip sans node).
# dayuse_eval_pack/tests est hors testpaths.
.venv/bin/pytest -q

# Lint + typecheck
.venv/bin/ruff check . && .venv/bin/mypy agents libs

# Guardrails statiques Dayuse (aussi exécutés par le hook pre-commit)
bash scripts/dayuse_guardrails.sh .

# Contrats figés, vérifiés hors ligne : contracts/mcp_b2c_tools.json (tests/test_mcp_contract.py ;
# l'humain le rafraîchit après tout déploiement MCP qui touche un schéma, cf. la docstring de
# scripts/refresh_mcp_contract.py) et contracts/geo_intent.schema.json
# (tests/test_geo_intent_contract.py), régénéré par :
python libs/b2c_common/b2c_common/geo_intent.py > contracts/geo_intent.schema.json
# contracts/amplitude_events.json est écrit à la main (tests/test_amplitude_contract.py +
# tests/widget/widget_amplitude_contract.test.mjs). Tests JS seuls (Node 26 refuse un dossier) :
node --test tests/widget/*.test.mjs

# Évals live (services up ; coûtent OpenAI/Mapbox/MCP — l'humain décide). Chemin réel : les
# experiments Langfuse sur evals/datasets/*.jsonl, un jeu par appel de seed, puis le run.
# Pièges : concurrence 5 par défaut → 429 MCP, toujours 1 ; Redis réel obligatoire sinon les cas
# multi-tours échouent en silence (:6379 est pris par dayuse-redis-1 → un Redis dédié sur :6390) ;
# même IP de sortie entre deux runs comparés (biais de proximité Mapbox Search Box) ;
# `DISABLE_AIOHTTP_TRANSPORT=True` sur les services ET le harnais. Le transport aiohttp de litellm
# réutilise une connexion que le réseau local a coupée, et depuis #157 (plus de relance), l'appel
# échoue en ~0,04 s : 42 % des triages en repli regex le 2026-10-27. La prod n'est pas touchée.
# Les 2 scripts lisent `LANGFUSE_*` dans l'environnement : charger `.env` avant. Le seed est un
# upsert qui écrase les corrections faites dans Langfuse : comparer les items hébergés au repo avant.
.venv/bin/python scripts/langfuse_seed_datasets.py --only <stem>
CONCIERGE_REDIS_URL=redis://localhost:6390/0 .venv/bin/python -m evals.langfuse_experiment \
  --datasets b2c/<jeu> --run-name <nom-unique> --max-concurrency 1
# Batterie 32 scénarios / 8 familles avec juge LiteLLM (ce que lance le job CI `eval`) :
.venv/bin/python scripts/run_dynamic_conversation_regression.py
```

Déploiement de la prod (Railway, ai.dayuse.com) : **`DEPLOY.md`** (topologie, procédure pas à pas, pièges) — ne jamais déployer sans l'avoir suivi.

CI GitHub Actions **morte** : facturation coupée depuis le 2026-07-23, non réactivée (décision du 2026-09-14) — chaque run échoue en ~4 s sans exécuter d'étape. Le rouge d'une PR ne veut rien dire ; le gate = les commandes locales ci-dessus. `.github/workflows/ci.yml` reste en place (jobs `checks`, `eval`, `langfuse-experiments`).

## Fin de session — OBLIGATOIRE

1. Tests + guardrails verts (jamais de HANDOFF « fait » sur du rouge).
2. **Mettre à jour `HANDOFF.md`** : bloc daté en tête (fait / reste / pièges découverts), remplacer les sections périmées. Mettre aussi à jour `CHANTIERS.md` quand un chantier s'ouvre ou se ferme.
3. Commit sur branche + PR GitHub — la review humaine de Fabien est le gate, ne jamais merger soi-même.
