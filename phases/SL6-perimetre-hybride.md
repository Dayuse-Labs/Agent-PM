# S-L6 — Périmètre hybride annoncé (« dedans d'abord, puis juste à côté »)

| | |
|---|---|
| **Mode** | Piloté — politique de périmètre et formulation = jugement produit encadré |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `git worktree add ../AgentB2C-sl6 -b sl6-hybrid-scope` |
| **Zone autorisée** | `agents/hotel_search_agent/hotel_search_agent/response_bridge.py`, `named_hotel.py` et leurs tests · `agents/b2c_concierge/**` (libellés jusqu'à la synthèse) · `libs/b2c_common/b2c_common/scores.py` (garde #19 seulement si D-3 la retient) |
| **Prérequis** | S-L5 mergée · décision **D-5** (seuil « juste à côté » pour un lieu sans frontière) |
| **Durée cible** | non estimée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-LEAF-GEO-2026-10-08.md` (§1 L4 et L6) · `response_bridge.py` (`inject_landmark_radius`, `normalize_hotel` : la carte garde le slug `cityName` dans `city`, ligne 559) · `named_hotel.py` (`follow_named_hotel` : l'enchaînement « hôtel puis voisins » fait en code, le patron à suivre).

## Périmètre
**IN** :
1. **Table de politique**, fonction pure testée (type de lieu × relation → stratégie) :
   - arrondissement à slug connu (Paris, Lyon, Marseille, Prague) : « dedans » = même slug `cityName`, puis les voisins ;
   - monument, gare, rue, adresse, hôtel : tri par distance ; au-delà du seuil D-5, une carte est annoncée « juste à côté » avec sa distance ;
   - quartier sans frontière connue : tri par distance, formulé « autour de », jamais « dans » ;
   - ville : comportement inchangé (rayon et ordre du MCP).
2. **Partage en code** sur la page triée par distance (`sortBy: distance`, anneau du site). Si une 2e requête MCP est nécessaire, le code la lance dans le même appel d'outil (patron `follow_named_hotel`) — jamais un appel d'outil de plus côté LLM ; le test des limites de S-L1 reste vert.
3. **Libellés** (dedans / juste à côté + distance) portés par chaque carte jusqu'au bloc de vérité de la synthèse, qui les annonce.
4. **Garde #19** (si D-3) : une réponse qui présente « dans le quartier » une carte libellée « juste à côté » est corrigée en code ; ajout en fin de `GUARD_SCORE_NAMES`.

**OUT** : polygones de quartier (hors phase 1) · rayon ou ordre des villes · retrait de règles (S-L7).

## Étapes
1. Tests de la table d'abord, un par ligne ; évaluateur `first_hotels_city_slug` (S-L2) sur les cas d'arrondissement.
2. Partage + libellés + garde éventuelle.
3. Stack locale, `GEO_LEAF_MODE=on` : jeux géo comparés à la sortie de S-L5.

## DoD (exécutable)
```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```
Live : sur les cas d'arrondissement, les hôtels du slug demandé sortent d'abord ; aucune carte « juste à côté » sans distance ; limites d'outils inchangées.

## Fin de session
HANDOFF (seuil appliqué, résultats par famille, phrases d'annonce retenues) · commit + MR.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-LEAF-GEO-2026-10-08.md (§1), puis phases/SL6-perimetre-hybride.md, et
exécute cette phase dans ce périmètre exactement.
Règles : la politique de périmètre est une fonction pure testée ligne par ligne ; tout enchaînement de requêtes
se fait en code, jamais par un appel d'outil de plus côté LLM ; un quartier sans frontière n'est jamais annoncé
« dans » ; fin = DoD verte + HANDOFF + commit sur branche, jamais de merge.
```
