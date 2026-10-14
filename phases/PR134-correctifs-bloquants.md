# PR134-FIX — Correctifs des régressions de #134 (avant tout merge)

| | |
|---|---|
| **Mode** | Piloté — chaque correctif part d'un test rouge, revue humaine de Fabien avant tout merge |
| **Modèle** | Opus |
| **Branche** | `fix/pr134-blockers`, créée depuis `origin/codex/production-context-and-proximity` @ `5d9218b` (PR #134, Victor). PR **vers la branche de #134**, pas vers `main` |
| **Zone autorisée** | `agents/**` · `libs/b2c_common/**` · `tests/**` · `HANDOFF.md`. **Interdit** : `contracts/*.json` (seul `scripts/refresh_mcp_contract.py`, lancé par un humain, y écrit), `evals/**` (rapports de Victor), `agent-usa/`, `baseline/` |
| **Prérequis** | aucun réseau, aucune clé : tout se prouve hors ligne (pytest) |
| **Durée cible** | 1 session |

## Contexte (revue du 2026-10-12, ne pas refaire)
#134 (+28k lignes, 131 commits) fiabilise le multi-tour, mais son propre rapport dit `"release_decision": "NO GO"` (`evals/PRODUCTION_PARITY_2026_10_10.json`). La revue a rejoué les **anciens tests** (`cbe88b9`) contre le code de #134 : **47 échecs** (25 concierge, 22 feuille search). Certains sont des changements voulus, d'autres des régressions. Les régressions ci-dessous ont été **reproduites en exécutant le code**, sauf mention « lu ».

État de `main` au 2026-10-12 : #115 (garde calendrier +400 j), #133 (« Voir tout » sans heures), #120 (`DEPLOY.md`) et #135 (= #124 + #125 ramenées sur `main`) mergées.

## Étape 0 — base de travail
```bash
git -c credential.helper='!gh auth git-credential' fetch https://github.com/Dayuse-Labs/AgentB2C.git '+refs/heads/*:refs/remotes/origin/*'   # ssh ne marche pas
git worktree add -b fix/pr134-blockers ../AgentB2C-pr134 origin/codex/production-context-and-proximity
cd ../AgentB2C-pr134 && git merge 8ec57f1   # = #115 seul (garde calendrier), 0 conflit vérifié
```
⚠️ Le checkout principal `/Users/fabiendauvergne/Projects/AgentB2C` contient des fichiers non commités de Fabien : **ne jamais y travailler**, toujours dans le worktree.

⛔ **Ne PAS merger `origin/main`.** Depuis le 2026-10-12, `main` contient #135 (`49d5bd3`), qui implémente autrement les mêmes fonctions que #134 (question en attente, homonyme, hôtel nommé, « oui » nu, garde #18). Merger donnerait 13 fichiers en conflit et deux machines à états côte à côte. Cette session corrige #134 **tel quel**. Le portage sur `main` se fait ensuite, par famille (voir « Suite »).

Les tests passent `libs/b2c_common` du worktree en premier : `PYTHONPATH=$PWD/libs/b2c_common /Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q -p no:cacheprovider`. Sans ça, le `-e` du venv pointe sur le `libs/` du checkout principal. Même chose pour mypy.

Attendu après le merge : 1 échec, `tests/test_calendar_rot.py`. Il désigne `agents/b2c_concierge/tests/test_location_confirmation.py::test_yes_cannot_choose_homonym_and_date_answer_is_preserved`, qui contient le littéral « 12 novembre 2026 ».

## Étape 1 — le filet : les anciens tests comme spécification
Copier chaque fichier de test **modifié** par #134 dans sa version `cbe88b9`, sous un suffixe (`*_cbe88b9.py`), dans un dossier jetable non commité. Lancer, puis classer **chaque** échec dans `HANDOFF.md` avec l'un de ces verdicts :
- **RESTAURÉ** : l'ancien test repasse grâce à un correctif ci-dessous ;
- **VOULU** : changement assumé par #134, avec le test qui le remplace ;
- **À TRANCHER** : décision produit, à laisser à Fabien.

Ne pas commiter les copies : on porte l'assertion dans le fichier courant quand c'est un RESTAURÉ.

Seules les signatures de faux leaf ont bougé (`query_params=`, `allow_text_name=`) : adapter ces signatures, jamais les assertions.

Verdicts déjà établis comme **VOULU** (ne pas restaurer) :
- les angles de synthèse « Only ONE hotel » et « outside the centre » ;
- « ZERO results » sur une clé `results` absente ;
- la devise non supportée différée ;
- la formulation de `no_offers` (minutes gardées telles quelles) ;
- le gabarit « seen every hotel » ;
- la liste de créneaux dans `window_guard` ;
- `more_options` et `booking_confirmation` pilotés par le LLM ;
- triage `max_tokens` 768 ;
- faq : 3 callbacks ;
- la fermeture fermée des équipements (`AMENITY_KEYS`) ;
- `timeSlotMode="contain"` ;
- la ville nommée qui passe avant le GPS ;
- la chaîne de callbacks qui passe de 12 à 19 (sauf l'ordre, voir R6).

## Périmètre
**IN** : chaque point part d'un test qui échoue sur `5d9218b` et passe après le correctif. Contrôle négatif : on retire le correctif et le test retombe.

**B1 — Disjoncteur MCP ouvert sans panne MCP (bloquant, prouvé).**
- ADK 2.4 exécute les `after_tool_callback` même quand un `before_tool_callback` a court-circuité l'appel : `google/adk/flows/llm_flows/functions.py`, étapes 4 à 6.
- Les refus locaux de #134 renvoient `{"ok": False, "error": …}` : `tool_budget_guard.py` vers les lignes 73 et 80 (`location_requires_clarification`, « Area search already completed… »), `named_destination_plan.py:57` (`named_destination_required`), `budget_pages.py:69`, `area_scope.py:330`.
- `mcp_guard._is_tool_failure` les compte comme pannes. Le disjoncteur est **global au module** : 3 refus de n'importe quels utilisateurs donnent 30 s de « service indisponible » pour tout le monde.
- Même défaut côté métriques : `status=error error_type=tool_returned_error` sur un appel qui n'a pas eu lieu.
- **Correctif** : le disjoncteur et la métrique ne doivent observer que les appels **réellement envoyés** au MCP. Préférer un marqueur posé par le court-circuit plutôt qu'une liste de chaînes d'erreur à tenir à jour.
- **Test** : passer par la vraie chaîne `root_agent.canonical_after_tool_callbacks`. 3 refus locaux laissent `breaker.allow()` à True. 3 réponses `isError` réelles l'ouvrent toujours.

**B2 — Piscine, spa, sauna ou jacuzzi remplacent toute la réponse (bloquant, prouvé).**
- `agent.py`, vers la ligne 2525 : `elif response.get("results") and unverified_access(...)` met `synth = conditional_access_message(...)` à la place de la synthèse.
- `unverified_access(None, ["pool"])` vaut True : toute recherche avec piscine, à chaque tour de la session, perd la description des hôtels.
- **Correctif** : la synthèse normale tourne, et l'avertissement d'accès est **ajouté** par le code (jamais par le LLM), une seule fois par ensemble d'équipements demandé.
- **Test** : « un hôtel avec piscine à Nice » avec résultats donne un appel de synthèse et l'avertissement en fin de réponse. Au tour suivant, sans changement d'équipement, l'avertissement ne revient pas.

**B3 — Budget sans devise : la recherche est bloquée (bloquant, prouvé par la revue).**
- « à Paris pour moins de 100 » renvoie « Dans quelle devise ? » avec 0 appel au leaf. Sur `main`, la recherche part.
- Un « 100 » nu ne vaut plus budget (il exige un `answer_to`).
- `agent.py`, vers les lignes 2238-2249 : pose la question de budget **après** une recherche réussie et jette ses résultats hors marché dollar (lu, à prouver d'abord par un test).
- **Correctif** : sans devise écrite, on prend la devise d'affichage du marché, comme sur `main`. On ne jette jamais des résultats obtenus pour poser une question.
- **Spécification** : les anciens tests du budget nu et de l'auto-élargissement de `test_spine_profile.py` (`cbe88b9`).

**B4 — Littéral de date pourrissant.** Rendre la date de `test_yes_cannot_choose_homonym_and_date_answer_is_preserved` relative à l'horloge, selon l'idiome de la fonction testée (cf. #115, `CLAUDE.md`). `tests/test_calendar_rot.py` doit passer.

**R5 — Géographie plus stricte qui perd des cas (prouvé par les anciens tests).**
- **« NYC »** rejeté avec le libellé « New York, New York, United States » : la fixture du nouveau test a été changée en « New York City ». Remettre l'ancienne fixture en plus de la nouvelle.
- **« Milano, Lombardia »** : un indice de région non confirmé par le fournisseur renvoie `none` (`test_region_hint_that_matches_nothing_does_not_zero_out`).
- **Homonymes** : quand un homonyme rate l'écho, le client reçoit `geocode_echo_mismatch` sans options au lieu d'une question (`test_clarify_surfaces_when_search_box_misses_too`, `geocode_tool.py` vers la ligne 1040).
- **Ville géocodée par le leaf** : jetée si elle n'apparaît pas littéralement dans le message (`b2c_concierge/agent.py` vers les lignes 2176-2187). « Londres » donne `city=None`, et le test de dégradation « Marseille » a été réécrit en « Paris » pour rester vert.

**R6 — Coût et charge (lus, à prouver par un test chacun).**
- **Règle SKU Search Box perdue** (`geocode_tool.py` vers la ligne 1117 : `eligible_candidates` au lieu de `candidates`). Spécification : `test_no_zone_never_calls_search_box` et `test_bare_city_miss_with_candidates_still_never_calls_search_box`.
- **Recherche par zones** : jusqu'à 5 appels MCP parallèles **hors plafond** de 2 par outil, car `search_areas_before_tool` sort avant `reserve_mcp_read`. Le MCP renvoie des 429 sur les appels enchaînés. Les faire compter dans le plafond.
- **Ordre des callbacks** : `search_areas_before_tool` ajoute `sortBy`, `radiusKm` et `size` **après** `drop_args_outside_schema`, qui doit rester le dernier filtre. Rétablir l'ordre et le figer dans `test_agent`.
- **Contrat MCP** : `contracts/mcp_b2c_tools.json` a été édité à la main (`sortBy`, `timeSlotMode` ajoutés sans bump de `generated_at`). **Ne pas y toucher** : noter dans HANDOFF que Fabien doit relancer `scripts/refresh_mcp_contract.py` pour vérifier que le MCP déployé expose bien ces clés.

**D — Comparaison de l'expression de date** (`datetime_resolver.py`, vers la ligne 320, `expression not in message`). La comparer sans casse ni accents (« 6 aout » contre « 6 août »). Le concierge rattrape déjà « demain », « 6 août », « mañana » et « morgen » (vérifié), mais pas « le 20/10 ».

**OUT** (sessions suivantes, ne pas commencer ici) :
- **Les ~17 nouvelles sorties en clarification avant recherche** (cartes dans 84 réponses sur 280, contre 142 en prod). À mesurer par rejeu (`evals/production_replay.py`), pas à corriger à l'aveugle.
- **Le prompt de triage passé de 7,4k à 35k caractères** avec un timeout de 5 s. À mesurer.
- **La réconciliation avec #135** (états concurrents : `pending_search` contre `pending_clarification`, `pending_place` contre `pending_location`, garde #18).
- **Le `location_intent` dans le triage**, contre la feuille géo (décision L1, `reports/PLAN-LEAF-GEO-2026-10-08.md`).
- **Le lien chatgpt.com** dans `evals/TEAM_REVIEW_2026_10_12.md:11` : question RGPD pour Fabien et Victor.

## Suite (sessions suivantes, décidé le 2026-10-12)
#134 ne sera pas mergée en bloc, même corrigée. Elle sera **portée sur `main` (avec #135) par famille**, dans cet ordre :
1. **Vérité des cartes** : offres datées revalidées, frais, devise, capacité. Pas de concurrent dans #135.
2. **Dates et créneaux** : trancher d'abord la règle « une nouvelle heure de début remplace tout le créneau » (#135) contre la règle d'une heure de #134.
3. **Géographie**, après la décision L1 (feuille géo contre `location_intent` dans le triage).

Pour les fonctions communes, on garde le modèle de #135 et on y porte les tests de #134, sauf si un rejeu sur la configuration de prod (triage 4o-mini) montre mieux. D'où la règle « un commit par point » ci-dessous.

## Règles
- Aucune nouvelle regex ni liste de mots pour comprendre le langage : le LLM extrait, le code possède les valeurs (CLAUDE.md, mémoire `feedback-llm-extraction-over-regex`).
- Un commit par point (B1, B2, …), message qui cite le test, pour pouvoir les **cherry-picker** sur un autre socle si #134 est découpée plus tard.
- Pas de nouvel appel LLM. Les 17 gardes et `GUARD_SCORE_NAMES` restent inchangés.
- Bloqué deux fois sur le même point : s'arrêter, le noter dans HANDOFF, passer au suivant.

## Définition du fini
```bash
PYTHONPATH=$PWD/libs/b2c_common /Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q -p no:cacheprovider   # 0 échec, calendrier compris
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
PYTHONPATH=$PWD/libs/b2c_common /Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```
- Les anciens tests (`cbe88b9`) rejoués : chaque échec restant est classé VOULU ou À TRANCHER dans HANDOFF, aucun n'est sans verdict.
- B1, B2, B3 et B4 sont RESTAURÉS, chacun avec son contrôle négatif. R5, R6 et D sont restaurés ou explicitement À TRANCHER.
- Bloc daté en tête de `HANDOFF.md` : fait / reste / pièges, plus le tableau des verdicts.
- Push via https, PR `fix/pr134-blockers` → `codex/production-context-and-proximity` (base = la branche de Victor), corps en français, sans merger.
- ⚠️ Pièges des PR empilées (mémoire `project-stacked-pr-merged-not-on-main`) :
  - si #134 est mergée avant cette PR, **retargeter cette PR sur `main` avant** toute suppression de branche ;
  - une PR mergée dans une base morte n'arrive jamais sur `main`.
