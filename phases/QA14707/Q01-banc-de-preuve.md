# Q01 — Banc de preuve : jeu d'éval QA14707 et évaluateurs

| | |
|---|---|
| **Phase** | 1 |
| **Modèle** | sonnet — écriture de cas et d'évaluateurs sur un format existant (OBS6), sans conception d'architecture |
| **Effort** | medium |
| **Dépend de** | — |
| **Prérequis** | E2 |
| **Zone (owned_files)** | `evals/datasets/b2c-qa-14707-2026-10-14.jsonl` (neuf) · `evals/langfuse_evaluators.py` · `evals/tests/test_langfuse_evaluators.py` · `scripts/langfuse_seed_datasets.py` (enregistrement du jeu) · `evals/datasets/README.md` (vocabulaire) |

## Contexte utile
`phases/QA14707/DIAGNOSTIC.md` · `evals/datasets/README.md` (format OBS6, vocabulaire d'assertions, `target` / `regression_guard`) · `evals/datasets/b2c-dialogue-state.jsonl` (exemples multi-tours : la liste `input.messages` est rejouée, la dernière réponse est évaluée) · `evals/langfuse_evaluators.py` (`response_evaluator`, évaluateurs existants `clarify_expected`, `must_ask_city`, `hotels_within_km`, `resolved_country_code`, `active_filters_include`, `offers_on_date`, assertions `trace.*`).

## Notes d'implémentation
Le jeu sert de barre au rejeu live H1 (référence, avant tout correctif) puis H3 (après la phase 3). Phrases synthétiques ou phrases de test de Raphael uniquement, jamais rien de `baseline/`.

Cas `target` (rouges aujourd'hui) :
1. `I want a room in paris Gare du nord for 10 am tomorrow` → au moins une carte, toutes à ≤ 2 km de la Gare du Nord (48.8809, 2.3553), créneau `10:00`, offres du lendemain, aucune question.
2. La même en français (« Une chambre à Paris Gare du Nord demain à 10h »).
3. `Trouve moi une chambre à Boulevard de la République Versailles pour 13h demain` → cartes à ≤ 4 km du centre de Versailles (48.8049, 2.1204), créneau `13:00`, aucune question.
4. `Un hôtel près du 2 boulevard Poissonnière 75009 demain` → pays `FR`, cartes à ≤ 2 km de (48.8713, 2.3467), aucune question.
5. `un hôtel dans le 75009 demain après-midi` → pays `FR`, cartes dans Paris 9e (≤ 3 km du même point).
6. `hotel near 2 boulevard Poissonnière 75009 Paris tomorrow` (aucun pays nommé) → pays `FR`. Ce cas couvre le défaut latent « 75009 lu comme un ZIP américain ».
7. Deux tours : `un hôtel près de la Gare du Nord demain à 14h` puis `Pari` → cartes à ≤ 2 km de la Gare du Nord, créneau `14:00`, offres du lendemain.
8. Deux tours : la même question puis `Je confirme` → la route n'est **pas** `booking` et aucun `generate_booking_link` n'est appelé. La réponse n'est pas la question du tour 1 à l'identique.
9. Deux tours en anglais : `hotel near Gare du Nord tomorrow 2pm` puis `yes, Paris` → comme le cas 7.

Cas `regression_guard` (verts aujourd'hui, à garder verts) :
- `un hôtel près de la Gare du Nord demain` → la ville est demandée. Les options, s'il y en a, viennent toutes du géocodeur.
- `un hôtel à la gare de Lyon demain` → la ville est demandée (règle S5, HANDOFF 2026-08-26).
- Ne pas recopier les cas Budapest, La Défense et `near 11580` : ils existent déjà dans les jeux géo, que H1 et H3 rejouent.

Évaluateurs : ajouter seulement ceux qui manquent, chacun avec ses tests dans `evals/tests/test_langfuse_evaluators.py`. Pistes :
- « aucune question avant la recherche » : des cartes, et pas de clarify ;
- `trace.route_is_not` (la route du concierge est dans la trace) ;
- « options de la question ⊆ candidats du géocodeur » (lit le résultat de `geocode_location` dans la trace).

Documenter chaque nouvelle assertion dans le vocabulaire de `evals/datasets/README.md`.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/python scripts/langfuse_seed_datasets.py --dry-run
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- `evals/datasets/b2c-qa-14707-2026-10-14.jsonl` contient au moins les 9 cas `target` et les 2 `regression_guard` listés, chacun avec `metadata.bug_ref = "dayuse-com#14707"`.
- `scripts/langfuse_seed_datasets.py --dry-run` valide le fichier ; le jeu est enregistré dans le script.
- Chaque nouvel évaluateur a au moins un test qui passe et un test qui échoue, dans `evals/tests/test_langfuse_evaluators.py`.
- Le vocabulaire de `evals/datasets/README.md` documente chaque nouvelle assertion.

## Hors périmètre
Lancer le rejeu live : c'est H1 et H3, faits par Fabien, parce qu'ils coûtent des appels OpenAI, Mapbox et MCP. Toucher `agents/**`.
