# S-L2 — Contrat `GeoIntent` v1 et jeux d'évals géo (∥ possible avec S-L1)

| | |
|---|---|
| **Mode** | Piloté — conception du contrat = jugement |
| **Modèle** | **Opus** (`claude-opus-4-8`) |
| **Branche/worktree** | `git worktree add ../AgentB2C-sl2 -b sl2-geo-intent-contract` |
| **Zone autorisée** | `libs/b2c_common/b2c_common/geo_intent.py` (neuf) + ses tests · `contracts/geo_intent.schema.json` (neuf) · `tests/test_geo_intent_contract.py` (neuf) · `evals/datasets/b2c-geo-intent.jsonl` et `b2c-geo-preservation.jsonl` (neufs) · `evals/langfuse_evaluators.py` (+ évaluateurs, tests associés) · `scripts/langfuse_seed_datasets.py` (enregistrement des jeux) — NE PAS toucher `agents/**` |
| **Prérequis** | Décisions L1-L6 (plan §1) |
| **Durée cible** | non estimée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-LEAF-GEO-2026-10-08.md` (§1, §3) · `evals/geo_preservation_registry.json` (les 24 cas, en entier) · `evals/PRESERVATION.md` (passages géo) · `evals/datasets/README.md` (format OBS6, vocabulaire d'assertions) · `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py:338-395` (docstring de `geocode_location` : la sémantique à préserver) · `geo_guards.py:88-225`.

## Périmètre
**IN** :
1. **`geo_intent.py`** : modèle pydantic `GeoIntent` v1 exactement selon le plan §3 — énumérations fermées, `extra="forbid"`, aucun champ de coordonnée, `schema_version = "1"`, au plus 2 lieux.
2. **Contrat figé** : `contracts/geo_intent.schema.json` (généré depuis le modèle) et `tests/test_geo_intent_contract.py` : le modèle et le snapshot ne divergent pas ; tout ajout de champ est un diff visible.
3. **Jeu de la leaf** `evals/datasets/b2c-geo-intent.jsonl` : message + contexte du tour précédent → `GeoIntent` attendu sur les champs qui comptent (`kind`, `canonical`, `city.canonical`, `country_named`, `region_named`, `relation`, `carryover`, `ambiguity.reason`). Coupé en `dev` et `test` (`metadata.split`) : le prompt de S-L3 se règle sur `dev`, jamais sur `test`.
   Familles : les 24 du registre, plus « Saint Paul à Londres », le 1er arrondissement sans ville, la gare de Lyon (Paris) contre Part-Dieu (Lyon), les reprises d'un tour à l'autre, les demandes sans lieu, les 7 langues. **Phrases synthétiques uniquement** : les séquences du registre sont privées, `baseline/` ne se commit jamais.
4. **Jeu bout en bout** `evals/datasets/b2c-geo-preservation.jsonl` (format OBS6) dérivé des attendus du registre, statuts `target` / `regression_guard`.
5. **Évaluateurs** : `geo_intent_fields` (comparaison champ à champ, pour la leaf) et `first_hotels_city_slug` (les hôtels « dedans » d'abord, pour S-L6). Réutiliser l'existant : `clarify_expected`, `must_ask_city`, `hotels_within_km`, `resolved_country_code`.

**OUT** : la leaf (S-L3), le concierge (S-L4), la feuille (S-L5) · la correspondance vers `geocode_location` (documentée au plan §3, codée en S-L5).

## Étapes
1. Relire les 24 cas du registre et vérifier que chacun est exprimable avec le contrat. Un cas qui ne l'est pas : STOP, le noter dans HANDOFF, demander à Fabien (pas de champ ajouté en solo).
2. Modèle + snapshot + test de contrat.
3. Jeux (validation locale : `scripts/langfuse_seed_datasets.py --dry-run`), puis évaluateurs et leurs tests.
4. Passage de référence bout en bout sur `main` (`b2c/geo-preservation`) : il fixe la barre que S-L5 devra tenir. Passage nommé `sl2-ref-…` (pas de `X-Dayuse-Synthetic` dans `evals/langfuse_experiment.py`).

## DoD (exécutable)
```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
.venv/bin/python scripts/langfuse_seed_datasets.py --dry-run
```

## Fin de session
HANDOFF (contrat v1, couverture des 24 familles, passage de référence et seuils proposés pour S-L3/S-L5) · commit + MR. Si ∥ S-L1 : merger S-L1 d'abord.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-LEAF-GEO-2026-10-08.md (§1 et §3), evals/geo_preservation_registry.json
(en entier), evals/datasets/README.md, puis phases/SL2-contrat-geointent-evals.md, et exécute cette phase dans
ce périmètre exactement.
Règles : le contrat suit le plan §3 à la lettre ; un cas du registre non exprimable = STOP et question à Fabien ;
aucune coordonnée dans le contrat ; jeux en phrases synthétiques uniquement ; fin = DoD verte + HANDOFF + commit
sur branche, jamais de merge.
```
