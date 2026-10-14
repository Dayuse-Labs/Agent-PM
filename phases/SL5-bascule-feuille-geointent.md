# S-L5 — Bascule : la feuille de recherche consomme le `GeoIntent`

| | |
|---|---|
| **Mode** | Piloté — changement de comportement sur le chemin principal |
| **Modèle** | **Opus** (`claude-opus-4-8`) |
| **Branche/worktree** | `git worktree add ../AgentB2C-sl5 -b sl5-geo-intent-consumed` |
| **Zone autorisée** | `agents/hotel_search_agent/**` · `agents/b2c_concierge/**` (transmission du `GeoIntent` et repli uniquement) · `libs/b2c_common/b2c_common/scores.py` (ajout en fin de tuple, D-3) |
| **Prérequis** | S-L4 mergée · mesures d'ombre jugées suffisantes par Fabien (**D-4**) · décision **D-3** |
| **Durée cible** | non estimée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-LEAF-GEO-2026-10-08.md` (§3 en entier) · `geocode_tool.py:338-470` et `:881-937` (`inject_profile_geo_context`, le pont déterministe actuel) · `equipment_ids.py:150` (`inject_amenities_declaration`, patron de déclaration modifiée) · `agent.py:303-392` de la feuille (chaîne de callbacks) · `contract.py` de la feuille.

## Périmètre
**IN** :
1. **Concierge** : en `GEO_LEAF_MODE=on`, le `GeoIntent` validé part dans `query_params.geo_intent` (dict ouvert de `contract.py`).
2. **Feuille, pont déterministe** : avec un `GeoIntent` valide, le code appelle `geocode_location` lui-même selon la table du plan §3, retire l'outil de géocodage des déclarations du modèle pour ce tour, et le LLM ne fait plus qu'un appel (`search_offers`). Compteur à l'appui : 1 appel au modèle dans la feuille sur un tour de recherche nominal.
3. **Reprise en code** : `carryover = new` → rien n'est repris de `profile_in` (aujourd'hui toute case vide est remplie, `geocode_tool.py:913-936`) ; `replace_place_keep_city` → la ville seule ; `keep` → comportement actuel.
4. **Questions** : `ambiguity` → gabarits existants (`geo_resolver.py:193` `_CLARIFY_MANY`, `:236` `_CITY_NEEDED`). Aucune question nouvelle écrite par un LLM.
5. **Repli** : `GeoIntent` absent, invalide, leaf en erreur ou en timeout → chemin actuel inchangé, et score `fallback_geo_leaf` (`FALLBACK_SCORE_NAMES`, ajouté en fin de tuple ; config de score Langfuse à créer par Fabien).
6. **Ce qui ne bouge pas** : gardes de faits (écho, #14, inventaire, question sans ville ni GPS), limites d'outils (test de S-L1), règles de langage (retirées en S-L7, pas ici).

**OUT** : politique de périmètre hybride (S-L6) · retrait d'une règle de langage (S-L7) · déploiement et bascule en production (S-L8).

## Étapes
1. Tests d'abord, table par table : chaque ligne de la correspondance du plan §3 = un test nommé ; contrôle négatif sur `main`.
2. Pont déterministe + reprise + questions + repli.
3. Stack locale, `GEO_LEAF_MODE=on` : jeux géo (`b2c/geo-preservation`, `b2c/geo-poi`, `b2c/geo-class-2026-10-06`, `b2c/dialogue-state`) comparés à la référence de S-L2 ; puis rejeu `validation` du banc, apparié avec `off`.
4. Latence : `scripts/measure_latency_e2e.py` en `on` contre `off`.

## DoD (exécutable)
```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```
Live : aucune régression sur les jeux géo par rapport à la référence de S-L2 ; « Je cherche Saint Paul à Londres » sans question sur 5 rejeux sur 5 ; p50 d'une recherche dans le budget D-4.

## Fin de session
HANDOFF (résultats par famille, latence `on` contre `off`, appels au modèle par tour) · commit + MR, `GEO_LEAF_MODE` reste à `off` par défaut.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-LEAF-GEO-2026-10-08.md (§3 en entier), puis
phases/SL5-bascule-feuille-geointent.md, et exécute cette phase dans ce périmètre exactement.
Règles : chaque ligne de la table de correspondance = un test nommé ; le géocodage reste du code et les gardes de
faits ne bougent pas ; repli = chemin actuel inchangé ; aucune règle de langage retirée ici ; fin = DoD verte +
jeux géo sans régression + HANDOFF + commit sur branche, jamais de merge.
```
