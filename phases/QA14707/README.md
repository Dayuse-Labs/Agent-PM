# QA14707 — Lieu compris, clarification tenue par le code, créneau localisé

> Plan source pour `/orchestre:prepare phases/QA14707` (conversion en `plans/<name>/`).
> Origine : retours QA de Raphael du 2026-10-14 sur https://gitlab.com/dayuse/dayuse/dayuse-com/-/work_items/14707.
> Preuves et causes racines : [`DIAGNOSTIC.md`](DIAGNOSTIC.md) (14 traces Langfuse, release `cbe88b9`). Tâches : `Q01-…` à `Q13-…` dans ce dossier.
> Écrit le 2026-10-14 contre `main` `49d5bd3`, puis recalé sur `origin/main` `2bac3eb` (PORT1, #137). Les numéros de ligne du concierge dans les tâches sont ceux de `2bac3eb` ; ceux de `DIAGNOSTIC.md` sont ceux de `49d5bd3`. PORT1 n'a touché ni la feuille géo ni le widget.

## Objectif

Les trois retours de Raphael ne reviennent pas, sous aucune variante :
1. le créneau d'une carte s'affiche dans la langue de la conversation (`10h – 16h` en français, `10am – 4pm` en anglais) ;
2. une ville, une adresse ou un code postal écrits dans le message ne déclenchent jamais de question sur la ville ;
3. quand une question est légitime, une seule réponse (« oui », « je confirme », « Pari vers 14h ») lance la recherche, avec la date et le créneau d'origine. La même question n'est jamais posée deux fois et aucune option n'est inventée.

## Principe (non négociable)

- **Le LLM comprend dans un schéma fermé, le code possède les valeurs et les vérifie** contre les faits du fournisseur (Mapbox, inventaire). Sources : CLAUDE.md, mémoire `feedback-llm-extraction-over-regex`, plan S-L §1.
- **Aucune nouvelle regex ni liste de mots pour comprendre le langage.** Les règles existantes impliquées sont retirées une par une en phase 4, chacune couverte par un test et un cas d'éval (décision L3).
- **Aucun nouvel appel LLM par tour** : le plafond `MAX_LLM_CALLS_PER_TURN = 3` reste inchangé. Les tours de clarification en font un de moins.
- `GUARD_SCORE_NAMES` et `FALLBACK_SCORE_NAMES` (`libs/b2c_common/b2c_common/scores.py`) ne perdent aucun nom ; une garde dont la mesure change garde son nom.

## Décisions tranchées (Fabien, 2026-10-14 : « prends tes recommandations »)

| # | Décision |
|---|---|
| **D-Q1** | Le `GeoIntent` est d'abord produit **par la feuille de recherche actuelle**, comme argument structuré de `geocode_location`, à la place des chaînes `city` / `zone` / `raw_user_message`. Pas de leaf dédiée, pas de 4e appel LLM, pas de décision D-1. Le contrat et la correspondance vers le géocodage sont ceux du plan S-L (§3), plus `postal_code`. S-L3/S-L4 (leaf dédiée) ne déplaceraient ensuite que la **production** de l'objet, et seulement si les rejeux montrent que gpt-4o-mini ne tient pas le schéma dans la feuille. Seule la séquence de L1 change, pas la cible. |
| **D-Q2** | Une question de clarification (ville manquante, homonyme) est **rendue par gabarit dans le concierge, sans passer par la synthèse**. Le ton est moins rédigé, mais aucune option inventée n'est possible et le tour coûte un appel LLM de moins. |
| **D-Q3** | **Déployer `main` maintenant** (#135 : reprise des critères après une question, hôtel nommé, garde #18), dès que le rejeu de référence (H1) ne montre aucune régression. La QA teste un build qui n'a pas les correctifs du 30/09. La regex `fc5cbd9` est acceptée comme transition et retirée en Q09. Action humaine : H2. |

## Questions hors plan (ne bloquent aucune tâche)

- **Raphael** : sur quelle URL et quel marché a-t-il testé ? Toutes ses traces portent `locale:"en"` et `currency:"USD"`.

## Découpage

| ID | Tâche | Phase | Dépend de | Modèle | Zone principale |
|---|---|---|---|---|---|
| Q01 | Banc de preuve : jeu d'éval QA14707 et évaluateurs | 1 | — | sonnet | `evals/` |
| Q02 | Créneau dans la langue de la conversation | 1 | — | sonnet | `web/vendor/static/js/chat/`, `tests/widget/` |
| Q03 | Contrat `Clarification` et émission structurée par la feuille | 2 | — | opus | `libs/b2c_common/`, feuille de recherche |
| Q04 | Concierge : clarification rendue par gabarit, état persistant, anti-boucle sur l'état | 2 | Q03 | opus | concierge |
| Q05 | Routage : la réponse à la question passe avant la réservation | 2 | Q04 | opus | concierge (triage, routage) |
| Q06 | Contrat `GeoIntent` v1.1 et preuve ADK hors ligne | 2 | — | opus | `libs/b2c_common/`, `contracts/` |
| Q07 | La feuille extrait le lieu dans un `GeoIntent` | 3 | Q06 | opus | feuille de recherche |
| Q08 | Adresse et code postal résolus par le géocodeur | 3 | Q07 | opus | feuille (`mapbox_client`, `geocode_tool`) |
| Q09 | Retrait : sauvetage de ville par préposition, correspondance de texte `pending_place` | 4 | Q08 | sonnet | `geocode_tool.py` |
| Q10 | Retrait : ZIP américain par regex | 4 | Q09 | sonnet | `geo_guards.py`, `geocode_tool.py` |
| Q11 | Retrait : question extraite par regex et oui/non par liste de mots, sur la route de clarification | 4 | — | sonnet | concierge (`profile.py`) |
| Q12 | Documentation : HANDOFF, CHANTIERS, plan S-L | 5 | — | sonnet | docs |
| Q13 | Revue globale (lecture seule) | 5 | Q12 | opus | — |

```text
Phase 1 : Q01 ∥ Q02
Phase 2 : Q03 → Q04 → Q05      ∥  Q06
Phase 3 : Q07 → Q08
          (H3 : rejeu live, tenue du GeoIntent par 4o-mini)
Phase 4 : Q09 → Q10            ∥  Q11
Phase 5 : Q12 → Q13
```

Q03 et Q07/Q08 touchent tous les deux `geocode_tool.py`. Ils sont dans deux phases différentes, donc jamais en parallèle.

## Prérequis (actions humaines et environnement)

| ID | Type | Prérequis | Bloque |
|---|---|---|---|
| D-Q1, D-Q2, D-Q3 | decision | Tranchées ci-dessus | — |
| H1 | manual | **Rejeu de référence** du jeu Q01 et des jeux géo existants (`b2c-geo-poi`, `b2c-geo-class-2026-10-06`, `b2c-dialogue-state`, `b2c-qa-2026-09-30`), 3× chacun, sur `cbe88b9` puis sur `main`. Stack locale `bash scripts/run_local.sh` avec les modèles de prod. Seed : `scripts/langfuse_seed_datasets.py --only …` ; run : `evals/langfuse_experiment.py --datasets … --run-name …`. Ce rejeu coûte (OpenAI, Mapbox, MCP) et doit être lancé par Fabien. | H2 (pas une tâche) |
| H2 | manual | **Déployer `main`** sur Railway selon `DEPLOY.md` (D-Q3) : `LANGFUSE_RELEASE` estampillé avant `railway up`, puis vérification de la release dans une trace. | — |
| H3 | manual | **Rejeu après la phase 3** : jeu Q01 et jeux géo existants, 3×, configuration de prod. Barre : aucune régression par rapport à H1 sur les `regression_guard`, et les cas A, B, C de Raphael verts au moins 3 fois sur 3. Sans ça, les retraits de la phase 4 affaiblissent le repli. | Q09, Q10, Q11 |
| H4 | manual | Déploiement final, retest par Raphael, réponse sur le ticket point par point (build, preuve, reste). | — |
| E1 | environment | `node --version` ≥ 18 (tests `node:test` du widget, lancés aussi par pytest). | Q02 |
| E2 | environment | Venv du checkout principal opérationnel : `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest --version`. | toutes |

## Avant `/orchestre:prepare`

- `/orchestre:prepare` exige un arbre propre sur `main` à jour. Or le checkout principal contient des documents non commités : `CHANTIERS.md`, `HANDOFF.md`, `SESSIONS-CLAUDE-CODE.md`, `reports/MCP-B2C-REQUESTS.md`, `reports/PLAN-LEAF-GEO-2026-10-08.md`, `phases/SL*`, `phases/PR134-*`, et ce dossier. Les commiter, sur `main` ou via une PR de docs, puis `git pull`.
- Commande : `/orchestre:prepare phases/QA14707`.

## Critères d'acceptation globaux

- Conversation FR : `10h – 16h` sur la carte de liste et sur la carte de réservation. EN : `10am – 4pm` (règle du site, `dayuse-com/apps/frontend/web/utils/formatTime.ts`).
- « I want a room in paris Gare du nord for 10 am tomorrow », « Trouve moi une chambre à Boulevard de la République Versailles pour 13h demain », « Un hôtel près du 2 boulevard Poissonnière 75009 demain » : **zéro question**, recherche lancée, cartes autour du lieu, créneau demandé appliqué.
- Après une question légitime (« un hôtel près de la Gare du Nord demain à 14h », sans ville) : « Pari », « Paris » ou « je confirme » + ville lancent la recherche à 14h le lendemain. « Je confirme » seul n'emprunte jamais la route réservation. La même question n'est jamais reposée à l'identique.
- Toute option citée dans une question vient du géocodeur et du palier d'inventaire ; aucune n'est écrite par un LLM.
- Cas à préserver : « Gare du Nord » sans ville demande toujours la ville ; Budapest, La Défense, gare de Lyon et « near 11580 » gardent leur comportement.
- Gates (CLAUDE.md), sur chaque tâche : `pytest -q` (garde calendrier +400 j comprise), `ruff check .`, `mypy agents libs`, `bash scripts/dayuse_guardrails.sh .`.

## Articulation avec les chantiers ouverts

- **Plan S-L** (`reports/PLAN-LEAF-GEO-2026-10-08.md`) :
  - Q06 reprend la partie contrat de S-L2, avec `postal_code` et la sémantique `mention` / `canonical` en plus ;
  - Q07 et Q08 font en avance la correspondance prévue en S-L5, mais dans la feuille (D-Q1) ;
  - Q09 et Q10 sont des retraits de S-L7, et S-L7 avait oublié `select_us_postal_anchor` ;
  - S-L3 et S-L4 deviennent conditionnels, comme le dit D-Q1. Q12 met le plan S-L à jour.
- **#134 (Victor)** : elle a ses propres `pending_clarification`, `pending_location` et un `location_intent` dans le triage. Décision du 2026-10-12 : #134 est portée sur `main` par familles, et la famille géo vient après L1. Ce plan **fixe le modèle** de la clarification et du lieu ; le portage de la famille géo de #134 devra s'y conformer, et non l'inverse.

## Pièges connus (à reporter dans DISCOVERY)

- **Vérifications en worktree** : il n'y a pas de `.venv` dans un worktree. Utiliser `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/{pytest,ruff,mypy}`. Le `-e libs/b2c_common` du venv pointe sur le checkout principal (`_editable_impl_b2c_common.pth`), mais `pytest.ini` (`pythonpath = … libs/b2c_common`) et `mypy.ini` (`mypy_path`) placent celui du worktree devant. Le vérifier une fois en tête de run : `b2c_common.__file__` doit pointer dans le worktree.
- `import litellm` charge le `.env` local, d'où les variables neutralisées dans `conftest.py` (HANDOFF 2026-10-07). Toute nouvelle variable de modèle s'y ajoute.
- **ADK** : un paramètre d'outil sans valeur par défaut est rejeté avant l'exécution de la fonction, et ça se lit comme du non-déterminisme du modèle (mémoire `reference-adk-mandatory-tool-params`). Chaque champ du `GeoIntent` a donc un défaut. ADK 2.4 construit la déclaration d'un paramètre pydantic (`google/adk/tools/_function_parameter_parse_util.py:169-178`) et le reconvertit par `model_validate` (`google/adk/tools/function_tool.py:173-182`).
- **Search Box** sans `proximity` est biaisé par l'IP de l'appelant (mémoire `reference-mapbox-searchbox-ip-proximity`) : les rejeux A/B doivent partager une IP.
- Dans le shell de session, `cat` est un alias vers `bat` : utiliser `command cat` ou Edit/Write.
- Une date en dur dans un test fait tomber `tests/test_calendar_rot.py` : dates relatives à l'horloge, selon l'idiome de la fonction testée.
- Le LLM recopie une phrase qu'on lui montre même quand on le lui interdit : tout texte imposé se dédoublonne en code, ou ne passe pas par le LLM (D-Q2).
