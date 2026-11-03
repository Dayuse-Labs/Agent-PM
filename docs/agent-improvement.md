# Fiche agent : B2C (recherche et réservation)

Vérifiée le 2026-11-02 sur `origin/main` `fab2e8f` (#185) ; `hotel-search` et `concierge` déployés sur `ba44795` (#183) d'après `HANDOFF.md`, non revérifié.
Propriétaire : <à confirmer> · Revue : Fabien · Merge : jamais par l'auteur de la PR

## Lire d'abord
- `CLAUDE.md`, puis `CHANTIERS.md`, `HANDOFF.md` (blocs datés en tête ; ne pas reconstruire ce qui y est décrit) et `tasks/lessons.md`. Prouver par une commande qu'un chantier est encore ouvert avant de planifier dessus.
- `DEPLOY.md`, `evals/datasets/README.md`.

## Flux et points de décision
- Chaîne : `b2c-concierge` (:8100) → triage (1 appel LLM) → table de routage en code → feuilles A2A `hotel-search-agent` (:8101, `GeoIntent` typé, Mapbox, guards, MCP `search_offers`) ou `faq-agent` (:8102), ou outils MCP inline (détails, comparaison, lien de réservation) → synthèse.
- Où se lit l'intention : `agents/b2c_concierge/b2c_concierge/triage.py` (JSON extrait du texte, pas de `response_format`).
- Dates : étiquetées par le modèle, résolues en code (`hotel_search_agent/datetime_resolver.py`).
- État : Redis côté concierge (`profile.py` : `pending_clarification`, `pending_search`, `suggestion_kinds`, `last_suggestions`). Un clic sur une puce se reconnaît à l'égalité exacte du libellé de notre gabarit.
- Gates : 18 guards (`GUARD_SCORE_NAMES`, `libs/b2c_common/b2c_common/scores.py`), dont `booking_confirmation` (pas de lien de réservation sans confirmation dans l'état). Budget dur de 3 appels LLM par tour, échéance 60 s.

## Matière réelle et rejeu
- Unité : conversation et tour. Traces Langfuse (`session_id` = `conversation_id`), Postgres `conversation_logs`, profil Redis.
- Horloge historique : `evals/replay_runtime.py`.
- Commandes :
  - jeux multi-tours : `scripts/langfuse_seed_datasets.py --only <stem>` puis `CONCIERGE_REDIS_URL=redis://localhost:6390/0 python -m evals.langfuse_experiment --datasets b2c/<jeu> --run-name <x> --max-concurrency 1` ;
  - rejeu d'exports prod : `evals/production_corpus.py`, `production_replay.py`, `replay_mcp_proxy.py` (MCP en cache local) ;
  - rejeu des conversations réelles : stack locale de 3 services avec les variables prod via `railway run` (Langfuse et base coupés), POST `/v3/chat` tour par tour, main contre branche.
- Protections : concurrence 1 (sinon 429 MCP), Redis dédié :6390, même IP de sortie entre deux runs comparés. Le MCP de recherche est lu en live : le dire.
- Interdits : viser `ai.dayuse.com` pour un rejeu ; lire en entier `../agent-usa`, `../MCP_B2C` ou `conversation_logs.csv`.

## Évaluation du modèle
- Corpus annoté : messages réels annotés pour une capacité précise, sonde du vrai `classify()` par bras, plusieurs tirages pour le bruit. Exemple : `scripts/measure_party_reading.py` sur `evals/party_reading_inputs.jsonl`, avec un mode `compare` contre les 114 entrées de `evals/triage_inputs.jsonl` pour vérifier qu'une retouche de prompt ne change ni famille ni langue ailleurs (`scripts/measure_triage_models.py` pour le triage entier).
- Rejouer les entrées **exactes** reçues par le modèle (message, messages récents, question précédente, tirés de la génération dans Langfuse) : hors contexte, les formes de prod ne reproduisent presque pas l'erreur. Ces entrées restent hors dépôt (messages d'utilisateurs).
- Batterie juge : `evalset/`, `evals/battery.py`, `evals/judge.py`, `scripts/run_release_gate.py` ; `evals/baselines.json` de juillet, jamais refaite avec le modèle de triage actuel ; JSON du juge extrait du texte.
- Boîte noire : `dayuse_eval_pack/` (`eval_pack.runner`, `eval_pack.compare`), 249 cas ; trier chaque régression (biais d'inventaire).

## KPI
| Rôle | Indicateur | Définition, dénominateur, instrument |
|---|---|---|
| Nord | Conversations avec résultat | `reach_results` : au moins un hôtel affiché ; unité conversation, synthétiques exclus, `MIN_SAMPLE=20` (`dashboard_bascule/metrics.py`) |
| Nord | Clic sur résultats | `ctr_on_results` : conversations avec clic hôtel / conversations avec résultats (Amplitude) |
| Business | Conversion | Entonnoirs Amplitude page → message → achat (24 h), clic → achat (7 j). Pas de taux de réservation attribué dans le dépôt |
| Invariant | Lien ou réservation non confirmés | Guards `booking_confirmation`, `hotel_link_truthfulness`, `amenity_truthfulness` |
| Diagnostic | Pertinence | Distance médiane des cartes, part au-delà de 5/10 km, couverture du créneau, date servie = date demandée |
| Diagnostic | Friction | `bounce`, `clar_loop`, `turns_to_result`, `zero_result_engaged` |
| Diagnostic | Coût et latence | `llm_calls`, `ttft_ms`, p50/p90 ; `cost_usd` absent sur le modèle de triage actuel |

Pièges de mesure : `clar_turn_rate` (un « ? » en fin de réponse) et `error_turn_rate` (`ERROR_RE`) sont lexicaux, les remplacer par `turn_facts` (`clarification_reason`, `empty_reason`) ; exclure le trafic synthétique (`X-Dayuse-Synthetic`, `?du_synthetic=1`).

## Traces
- Langfuse auto-hébergé, projet `b2c-concierge` (`observability/langfuse/`) : une trace par tour, scores `guard_*`, `hotels_returned`, `empty_shortlist`, `llm_calls`, `ttft_ms`, `degraded`. Évaluateurs LLM Langfuse non calibrés contre une revue humaine connue.
- `turn_facts.py` côté serveur ; événements Amplitude du widget (`contracts/amplitude_events.json`).
- Tableau de bascule hors dépôt : `dayuse_aisearchagent_USA-worldwide/dashboard_bascule/` (`collect.py`, `metrics.py`).

## Dette lexicale
- Encore présente : repli de famille du triage quand le LLM échoue (`_FAQ_RE`, `_COMPARE_RE`, `_BOOKING_RE`, `_PICK_CHEAPEST_RE`, `fallback_family` ; 42 % des triages en repli le 2026-10-27), `_ACK_RE`, `_FR_HINTS` ; `profile.py` (`_AFFIRMATIVE_RE`, `_CONFIRMATION_RE` / `_CONFIRMATION_NEGATION_RE` utilisés par la gate de réservation, `_REFINEMENT_KEYWORDS_RE`, `_MORE_OPTIONS_RE`, `is_bare_affirmative` additif) ; jours relatifs et `parse_requested_date` (`requested_date.py`, listes de mots présentées comme format strict) ; `_ALREADY_SAID_RE` (`window_guard.py`), `_ALREADY_DISCLOSED_RE` (`currency_guard.py`), motifs d'`amenity_guard.py` ; `message_must_contain_any` / `message_must_not_contain_any` dans les jeux d'éval.
- Encore présent malgré #183 : `_party_quote_ok` exige une citation contenant au moins une lettre (`triage.py`, test de caractères sur la citation) ; la branche `fix/party-from-dates-20261102` (`34445b1`, pas encore sur `main`) le remplace par le booléen typé `names_people`.
- Déjà remplacée, à imiter : `GeoIntent` (fin des regex de prépositions), oui/non lus sur la question attendue (`leaf_question`), `anti_clarification_loop` lu sur l'état, puces typées et clic reconnu par égalité de libellé (`clicked_suggestion_kind`), `Triage.wish` / `day_stated` / `answers_pending`, `pick` en liste fermée résolu par `select_cheapest_hotel` qui ne lit jamais le message (verrouillé par `test_it_never_reads_the_message`), `requested_occupancy.counts` (#183 : ce que compte le nombre cité).

## Données privées
- Aucun contenu de message dans les métriques, scores, logs ou `turn_facts` (verrouillé par test). `baseline/` ne se commit jamais. Secrets injectés par `railway run`, jamais affichés.

## Méthode du dépôt
1. **Constat** sur les conversations réelles depuis le dernier déploiement (traces Langfuse complètes, croisées avec les clics Amplitude), parfois un comparatif côte à côte avec l'ancien agent ; rapport hors dépôt dans `dashboard_bascule/data/investigation/`.
2. **Un commit par point**, plus les correctifs trouvés au rejeu.
3. **Contre-épreuve** : les nouveaux tests rejoués sur les sources d'`origin/main` doivent être rouges, sauf les témoins (vrais cas qui doivent rester inchangés). Un test vert avant et après ne prouve rien.
4. **Mesure live** du vrai modèle sur les entrées exactes, plusieurs tirages, main contre branche ; contrôle des effets de bord sur la fixture complète.
5. **Rejeu local** des conversations réelles, bras en parallèle, jamais `ai.dayuse.com`. Quand le comportement dépend de l'heure locale (offres fermées le soir), simuler l'heure dans le rejeu (`REPLAY_SIM_NOW_UTC` dans un `sitecustomize` hors dépôt), jamais en prod.
6. **Bloc `HANDOFF.md`** (Constat / Fait / Preuves / Pièges / Reste), PR, revue de Fabien.
7. **Déploiement** puis bloc 🚀 : pré-vol pytest sur le commit exact, estampille, services déployés et ceux qui restent, preuve par sessions synthétiques sur la release, **signal à prouver en prod sous 48 h**, commande de retour arrière.

Avant tout run live : vérifier l'IP de sortie (`curl -4 ifconfig.me`), un appel MCP, et lire les `status=` des tours ; une pile dégradée produit des scores faux. Un changement d'argument envoyé à MCP se prouve par une sonde live ancien contre nouveau sur le même marché, pas par un test hors ligne.

## Améliorations récentes et effet mesuré
Détail et preuves dans les blocs datés de `HANDOFF.md`.

| Date | PR | Changement | Effet mesuré au rejeu |
|---|---|---|---|
| 27/10 | #158, #160 | Triage sur gpt-6-luna ; échecs des premières conversations réelles | Lot de 24 conversations en échec : erreurs visibles 11 → 1, tours en panne 8 → 0 |
| 28/10 | #168-#173 | Budgets de temps des feuilles, jour et lieu demandés ensemble, accès aux résultats (« près de moi », replis « aucune offre ») | Départ : conversations avec résultats 58 % contre 74-81 % sur l'ancien agent. Lot du soir (16 conversations) : avec résultats 8 → 13, tours « aucune offre » 15 → 9 |
| 29/10 | #174, #175, #177 | Contexte de dialogue partagé, échéance unique par tour, pertinence de l'entrée, chargement du widget | Pertinence : chiffres dans la PR #175 (+1,4 s de latence médiane au rejeu, à mesurer en prod) ; chargement 4G lente ≈ 4 s → 1,4 s |
| 30/10 | #179 | Leviers de clic (lendemain classé, lieux précis, budgets hors EUR, priorité prix) | Tours de recherche vides 32 → 17 ; cartes à plus de 10 km 28 % → 23,5 % ; latence inchangée |
| 30/10 | #181 | Lendemain annoncé en code et puces de jour | Annonce garantie 4/4, puces 4/4 (main 0/4) |
| 02/11 | #183 | Un nombre n'est un groupe que s'il compte des personnes | Faux groupes sur les entrées exactes de prod 10/40 → 0/40, vrais groupes 39/39 gardés |
| 03/11 | `fix/geo-explicit-state-20261103` | Un État écrit avec le lieu compte (`region` typée) ; une aire qui ne partage qu'un mot est une autre aire | « Auburn, AL » : question WA/CA 1/6 → 0/6 ; « Amelia Island » : Virginie 3/3 → Floride 3/3 ; « Auburn, WA », « Springfield, MO » : question 3/3 → résolu 3/3 ; 99 appels réels touchés : 2 changements, les 2 visés |

## Livrer
- Une PR par point, revue de Fabien, jamais de merge par l'auteur.
- Gate local (CI GitHub arrêtée) : `pytest -q`, `ruff`, `mypy agents libs`, `scripts/dayuse_guardrails.sh`.
- Déploiement selon `DEPLOY.md` : `LANGFUSE_RELEASE=<sha>` avec `--skip-deploys`, puis `railway up --service <s>` depuis un checkout détaché propre (`../AgentB2C-deploy`).
- Où consigner : bloc daté de `HANDOFF.md`, jeu `b2c-prod-<date>` en `target`, leçons dans `tasks/lessons.md`.

## Pièges datés
- 2026-11-03 : le défaut d'un tour peut n'être qu'un tirage du modèle (« Auburn, AL » échoue 1 fois sur 6 sur `main`). Rejouer d'abord l'intent exact de la trace sur le vrai outil (`geocode_location`, Mapbox live), puis la conversation entière sur plusieurs passages.
- 2026-11-03 : `pip install` des requirements exige l'accès SSH à `dayuse-agent-fleet` ; sans lui, réutiliser un venv existant, les sources du worktree en tête de `PYTHONPATH`.
- 2026-11-02 : le checkout principal local datait de juillet ; partir d'`origin/main`.
- 2026-11-02 : les scripts de rejeu des conversations réelles vivaient dans un scratchpad hors dépôt ; les verser dans `evals/` s'ils servent encore.
- 2026-11-02 : une liste d'exemples longue dans le prompt du triage l'a fait répondre dans la langue des exemples ; toute retouche se mesure avec `compare` sur les 114 entrées.
- 2026-10-28 : un appel LLM ajouté décale les réponses scriptées (`ScriptedLlm`) ; aligner chaque script de test traversé et lire `--durations` pour repérer un test parti en ligne.
- 2026-10-20 : mesurer l'état persisté (profil Redis) en A/B, pas seulement la réponse.
