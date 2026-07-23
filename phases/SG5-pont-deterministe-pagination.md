# S-G5 — Pont déterministe profil→outils + pagination « autres options » (après S-G1 + S-G3)

| | |
|---|---|
| **Mode** | Piloté puis loop possible (spec exécutable une fois les probes faits) |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `sg5-bridge-pagination` (∥ S-G2 possible : feuille vs facade — merger S-G2 d'abord) |
| **Zone autorisée** | `agents/hotel_search_agent/**` (callback d'injection, émission ops) + `agents/b2c_concierge/**` (exclusion shown_ids, curseur, disclosure) + tests |
| **Prérequis** | **S-G1 ET S-G3 mergées** · Arbitrage **A7** (probe d'abord) |
| **Durée cible** | 1 journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` (§4 axe M points 3 et 5) · `reports/research/code-verification-memo.md` (claims 9, 10 — le flux profile_in/delta exact + « aucune pagination ») · `reports/research/multiturn-state-memo.md` (§d pagination) · le pattern de référence : `agents/hotel_search_agent/hotel_search_agent/equipment_ids.py` (le SEUL pont déterministe existant).

## Périmètre
**IN** :
1. **PROBE A7 (≤15 min, avant de coder la pagination)** : `search_offers` accepte-t-il `limit`/`offset`/un paramètre d'exclusion ? Combien de résultats renvoie-t-il par défaut (on n'en garde que 5 — y en a-t-il plus à paginer ?) — probe MCP staging direct, constat dans HANDOFF. Le mécanisme (over-fetch + filtre code vs param MCP) découle du constat ; l'ÉTAT (shown_ids, curseur) vit au profil dans tous les cas (fait en S-G1).
2. **Pont déterministe profil→geocode (le fix P0 #4)** : un `before_tool_callback` feuille (pattern exact `enforce_equipment_filters`) injecte dans les args de `geocode_location` — depuis le `profile_in` décodé — `city`/`zone`/`state`/`country_code` manquants + `proximity` depuis `search_anchor` (S-G2). Règle de précédence : **une valeur extraite par le LLM pour CE tour gagne ; le profil comble ce que le LLM a omis** ; le callback ne réécrit jamais une extraction fraîche. Le LLM cesse d'être une machine à recopier (l'instruction est allégée d'autant).
3. **Émission ops côté feuille (slots geo)** : `emit_search_datapart` passe au format ops S-G1 (`{op: set, value}`) pour les slots qu'elle possède (`city`, `state_anchor`, `country_anchor`, `zone`, `metro`) — le reducer accepte déjà les deux formats, migration sans casse.
4. **Pagination** : au retour des résultats, le concierge exclut `shown_hotel_ids` AVANT la coupe top-5 (ou passe l'exclusion au MCP selon A7) ; « autres options » → curseur avancé, nouveaux IDs exigés ; épuisement du pool filtré → **disclosure explicite + proposition de relâcher UNE contrainte nommée** — étendre le mécanisme d'exhaustion S12 existant (`search_exhausted`/templates), ne PAS créer une machine parallèle.
5. Routing : « autres options »/« show me more » doit router search SANS re-demander la ville (vérifier que `is_search_refinement_signal` couvre ces formulations ; compléter la regex sinon).

**OUT** : dates/durées/minutes (S-G6) · demande de param MCP côté MCP_B2C (doc cross-repo, pas de code ici) · tout changement du contrat `active_filters` (fait en S-G1).

## Étapes
1. Probe A7 → constat HANDOFF → mécanisme choisi.
2. Callback d'injection + tests (précédence LLM-frais vs profil, ancre GPS → proximity, profil vide → args intacts).
3. Émission ops geo + tests round-trip (feuille émet ops → reducer S-G1 les applique → profil correct).
4. Exclusion + curseur + disclosure + tests (les 3 cas : nouveaux IDs, épuisement, reset sur changement de contrainte).
5. Vérif LIVE : session multi-tours réelle — search Paris → « autres options » → 5 NOUVEAUX hôtels (IDs disjoints) → épuisement → message de relaxation.

## DoD (exécutable)
```bash
pytest -q          # feuille + concierge, +~25 tests
.venv/bin/ruff check . && .venv/bin/mypy agents libs && bash scripts/dayuse_guardrails.sh .
```

## Fin de session
HANDOFF (constat A7 + précédence du pont + preuve live pagination) · commit + MR.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§4),
reports/research/code-verification-memo.md (claims 9/10), le pattern equipment_ids.py,
puis phases/SG5-pont-deterministe-pagination.md et exécute cette phase, dans ce périmètre exactement.
Règles : probe search_offers AVANT la pagination ; le callback comble, ne réécrit jamais une extraction fraîche ;
étendre l'exhaustion S12, pas de machine parallèle ; preuve live « autres options » = nouveaux IDs obligatoire ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```
