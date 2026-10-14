# S-L1 — #124 réconciliée avec le MCP mergé (feuille search) (∥ possible avec S-L2)

| | |
|---|---|
| **Mode** | Piloté — contrat inter-dépôts, rejeux à juger |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche** | `fix/geo-location-class` (PR #124, existante) — rebase sur `main` d'abord |
| **Zone autorisée** | `agents/hotel_search_agent/**` · `tests/test_mcp_contract.py` · `tests/test_leaf_tool_budget.py` · `contracts/mcp_b2c_tools.json` (diff du rafraîchissement uniquement) — NE PAS toucher `agents/b2c_concierge/**` |
| **Prérequis** | MCP_B2C `main` 08f3764d déployé sur l'instance appelée · contrat rafraîchi par un humain (`scripts/refresh_mcp_contract.py`, il lit les secrets MCP) · décision **D-2** (coordonnées de l'hôtel nommé) |
| **Durée cible** | non estimée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-LEAF-GEO-2026-10-08.md` (§1, §2 E2-E6) · sur la branche, les blocs HANDOFF du 2026-10-06 (#7 classe géographique, #6 état de dialogue) : `git show origin/fix/geo-location-class:HANDOFF.md | sed -n 1,80p`.

## Preuve que l'écart est ouvert (avant tout code)
```bash
git show origin/fix/geo-location-class:agents/hotel_search_agent/hotel_search_agent/response_bridge.py | grep -n '"sort"'
grep -c sortBy contracts/mcp_b2c_tools.json      # 0 tant que le contrat n'est pas rafraîchi
git show origin/fix/geo-location-class:agents/hotel_search_agent/hotel_search_agent/named_hotel.py | sed -n 190,215p
```

## Périmètre
**IN** :
1. **`sort` → `sortBy`** dans `inject_landmark_radius` (`response_bridge.py`, vers les lignes 788-826 de la branche) : `pop` et écriture, docstring alignée sur le nom réel du paramètre MCP. Le retri local des cartes (`capture_after_tool`, vers la ligne 1115) reste comme filet.
2. **Test de contrat** : nouveau cas dans `tests/test_mcp_contract.py` avec une ancre de type lieu dans l'état du `_ToolContext` (`temp:hotel_search_anchor = {"type": "poi", "latitude": …, "longitude": …}`), pour que `radiusKm` et `sortBy` injectés par le code soient validés contre le snapshot. Contrôle négatif : le cas tombe avec `sort`.
3. **Hôtel nommé** (`named_hotel.py:196`) selon D-2 : (a) le MCP expose `lat`/`lon` dans `find_hotel_by_name` (MR MCP_B2C séparée, voir plus bas) ; (b) sinon, la carte seule est assumée et la réponse le dit. Un test fige le comportement retenu.
4. **Limites figées (L6)** : `tests/test_leaf_tool_budget.py` vérifie les valeurs par défaut de `PER_TOOL_CALL_LIMITS` (2/2/2) et de `MAX_TOOL_CALLS` (2) quand les variables `HOTEL_SEARCH_MAX_*` sont absentes.
5. **Mesure, pas de code** : fréquence de `budget_stopped=true` (préfixe `TOOL BUDGET`, `tool_budget_guard.py:37`) et de `tool_budget_exhausted` sur les traces disponibles → HANDOFF.
6. **Régression notée sur #8** (HANDOFF de la branche) : « busco un hotel con piscina en madrid mañana por la tarde » mettait Madrid en `zone`. Rejouer l'item espagnol de `b2c/language-robustness` sur `main` et sur la branche ; constat dans HANDOFF, correctif seulement s'il touche #124.

**OUT** : `GeoIntent` (S-L2+) · retrait de la regex de #124 (S-L7a) · toute nouvelle règle de langage · le concierge · toute hausse de limite d'outil.

## Étapes
1. Preuves ci-dessus, puis rebase de la branche sur `main` (elle contient déjà #125 : état de dialogue, garde #18).
2. Tests d'abord (points 2 et 4), puis correctifs 1 et 3.
3. Contrat rafraîchi par l'humain → tests de contrat verts.
4. Rejeu des jeux géo sur deux stacks (`main` et branche, `PORT_OFFSET`) : `b2c/geo-poi`, `b2c/geo-class-2026-10-06`, `b2c/dialogue-state`, `b2c/language-robustness`. Procédure : CHANTIERS E1 (6 commandes) tant que `scripts/qa_experiment.sh` n'existe pas. ⚠️ `evals/langfuse_experiment.py` n'envoie pas `X-Dayuse-Synthetic` : nommer le passage `sl1-…` pour pouvoir l'exclure.
5. Vérification live : « Je cherche Saint Paul à Londres », 5 rejeux.

## DoD (exécutable)
```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```
Live : aucune question de ville sur les 5 rejeux, top 5 à 1 km ou moins de la cathédrale ; jeux géo sans régression par rapport à `main`.

## Prérequis MCP (si D-2 = a) — session dans le dépôt MCP_B2C
```
Lis CLAUDE.md et docs/suivi-implementation.md. find_hotel_by_name ne renvoie pas les coordonnées de l'hôtel
(hotel-summary.dto.ts, description de l'outil), alors qu'AgentB2C en a besoin pour chercher ses voisins.
Expose lat/lon (depuis _geoloc) dans le résultat de find_hotel_by_name, documente-les dans la description de
l'outil, teste (cas nominal et ambigu), puis lint:fix, format, test. Branche + MR, jamais de merge.
```

## Fin de session
HANDOFF (contrat rafraîchi, D-2 appliquée, fréquence des dépassements de limite, résultats des rejeux) · commit sur la branche, PR #124 mise à jour. Jamais de merge.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-LEAF-GEO-2026-10-08.md (§1 et §2), puis phases/SL1-pr124-contrat-mcp.md,
et exécute cette phase dans ce périmètre exactement.
Règles : prouver d'abord que l'écart existe (commandes de la phase) ; tests d'abord ; aucune nouvelle règle de
langage ; les limites d'outils ne bougent pas ; rejeux nommés sl1-… ; fin = DoD verte + vérification live +
HANDOFF + commit sur la branche, jamais de merge.
```
