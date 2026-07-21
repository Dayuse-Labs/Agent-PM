# S14 — Combler le gap budget/timeslot → profile_delta (feuille search)

| | |
|---|---|
| **Mode** | Piloté — trop court/mécanique pour une loop, mais un choix de wording d'instruction LLM à valider en live |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | pas de worktree nécessaire (zone disjointe de tout autre travail en cours) |
| **Zone autorisée** | feuille search (`agents/hotel_search_agent/**`) + ses tests — **NE PAS toucher** `agents/b2c_concierge/**` : le contrat existe déjà côté concierge, zéro changement attendu là |
| **Prérequis** | S12 mergée (fait, 2026-07-21, PR #14) — pas un blocage technique dur (le contrat `apply_profile_delta` existe depuis S5, avant même S12), mais c'est ce qui rend ce travail utile : 3 des 4 guards S12 sont dormants tant que ce gap n'est pas comblé |
| **Durée cible** | ½ journée |

## Contexte (déjà diagnostiqué pendant S12 — ne pas redécouvrir)

`HANDOFF.md`, addendum S12 (2026-07-20/21), section « Reste » : les guards **search-exhaustion**, **budget-vs-durée** et **provenance** (portés en S12, `agents/b2c_concierge/**`) sont des machines à états correctes mais **jamais exercées en trafic réel**, car `hotel_search_agent` n'émet toujours pas `budget_max`/`timeslot_*` dans son `profile_delta` — gap documenté depuis S9 (« budget/timeslot du tour ne sont pas encore réémis en profile_delta »), jamais comblé.

Diagnostic technique précis (vérifié 2026-07-21, live contre MCP_B2C staging) :

- `agents/hotel_search_agent/hotel_search_agent/agent.py::INSTRUCTION` ne mentionne **jamais** budget/prix/créneau — le modèle n'a aucune consigne pour extraire un budget ou un horaire du message et les transmettre à `search_offers`.
- **Rien à inventer côté schéma MCP** (contrairement aux amenities en S10, qui ont nécessité l'injection d'un paramètre virtuel car MCP n'a aucun champ texte) : `search_offers` a **déjà** des paramètres natifs, confirmés par probe live du schéma réel :
  - `priceRangeMin` / `priceRangeMax` (number, EUR, borne basse/haute du budget par offre)
  - `timeSlot: {startHour, endHour}` (integer 0-23 chacun)
- `response_bridge.py::capture_after_tool` reçoit déjà `args` (les arguments RÉELS envoyés à `search_offers` par le modèle) mais ne les regarde que pour `hotelEquipmentIds`/country — jamais pour budget/timeslot.
- `response_bridge.py::emit_search_datapart` construit `profile_delta` depuis `tool_context.state` (ville/état/pays/amenities) — jamais de budget/timeslot.
- **Côté concierge, zéro changement nécessaire** : `b2c_concierge/profile.py::apply_profile_delta` (existe depuis S5) attend déjà exactement ces clés :
  - `budget_max` (float)
  - `budget_request_source` (str — la feuille doit TOUJOURS envoyer une valeur non-explicite, ex. `"flexible_default"` ; le guard P1 côté concierge upgrade automatiquement vers `"explicit"` si le message était un nombre nu — la feuille n'a pas à être intelligente sur la provenance)
  - `timeslot_start` / `timeslot_end` (strings au format `"HH:MM"` — même format que le helper `_hhmm()` déjà utilisé dans `response_bridge.py` pour formater les horaires d'offre)
  - `timeslot_request_source` (str, même logique de provenance que le budget)

## Périmètre

**IN** :
1. **INSTRUCTION du leaf** (`agent.py`) — ajouter une consigne (même style que les bullets existants pour dates/amenities) : quand l'utilisateur mentionne un budget explicite, passer `priceRangeMax` (et `priceRangeMin` si une fourchette basse est donnée) à `search_offers` ; quand un créneau horaire est mentionné, passer `timeSlot.startHour`/`endHour`. Ne jamais halluciner une valeur non mentionnée dans le message.
2. **`capture_after_tool`** — capturer les `args` RÉELS envoyés à `search_offers` (déjà reçus en paramètre de la fonction) et stasher `priceRangeMax`/`timeSlot` dans `tool_context.state` sous une nouvelle clé `temp:` (pattern identique à `_STATE_COUNTRY_KEY`/`STATE_APPLIED_AMENITIES_KEY`).
3. **`emit_search_datapart`** — mapper cet état vers `profile_delta` avec les clés EXACTES ci-dessus. Only-when-present (jamais écraser avec `None`/vide) — même philosophie que amenities/country_anchor déjà en place. `budget_request_source`/`timeslot_request_source` = constante fixe (`"flexible_default"` ou équivalent), jamais `"explicit"`.
4. **Tests** (pattern `test_response_bridge.py` existant) : `capture_after_tool` stashe les bons state keys depuis des `args` scriptés ; `emit_search_datapart` mappe correctement vers `profile_delta` ; absence de budget/timeslot dans les args → aucune clé dans le delta (jamais un delta vide/cassé qui écraserait le profil).

**OUT** :
- Tout changement côté concierge (`agents/b2c_concierge/**`) — le contrat existe déjà.
- `priceRangeMin` sans destination profil (le concierge n'a pas de champ "budget_min") — capturer si présent si ça simplifie le code, sinon documenter comme non consommé, ne pas inventer un champ profil pour ça.
- Toute mécanique de provenance "explicite" côté feuille — la feuille reste `"flexible_default"` toujours, le concierge décide (guard P1 déjà en place).
- Rejouer/adapter la baseline batterie S8 (hors périmètre, comme S12/S13).

## Étapes

1. Ajouter la consigne budget/timeslot dans `INSTRUCTION` (agent.py).
2. Étendre `capture_after_tool` : nouvelle clé `temp:`, capture de `args.get("priceRangeMax")`/`args.get("timeSlot")` sur l'appel `search_offers` (rien à faire sur `find_hotel_by_name`, qui n'a pas ces params).
3. Étendre `emit_search_datapart` : mapper vers `profile_delta["budget_max"]`/`["budget_request_source"]`/`["timeslot_start"]`/`["timeslot_end"]`/`["timeslot_request_source"]`. Réutiliser un helper équivalent à `_hhmm()` (déjà dans le fichier) pour formatter `startHour`/`endHour` en `"HH:MM"`.
4. Tests offline (pattern existant, cf. tests actuels sur `_STATE_COUNTRY_KEY`/amenities dans `test_response_bridge.py`).
5. **Vérification LIVE (obligatoire, pas de "done" sans ça)** :
   - Lancer les 3 services (`scripts/run_local.sh stop && scripts/run_local.sh` — pas de hot-reload).
   - Une recherche avec budget/horaire explicite dans le message (ex. « un hotel a paris demain sous 80 euros entre 14h et 20h ») → vérifier `/v3/chat`'s `active_filters.budget_max`/`timeslot` sont bien posés (avant ce fix : toujours `None`).
   - Vérifier dans `.run-logs/hotel_search_agent.log` que `search_offers` est bien appelé avec `priceRangeMax`/`timeSlot` (compteur greppable, pas de contenu — cohérent RGPD).
   - **Idéalement** : un scénario budget bas + ville à faible inventaire sur plusieurs tours vides, pour prouver que l'auto-widen / le guard d'exhaustion (S12) se déclenchent enfin en conditions réelles — première preuve live de ce mécanisme depuis sa création (S05/S06).

## DoD (exécutable)

```bash
pytest agents/hotel_search_agent -q
pytest -q && bash scripts/dayuse_guardrails.sh .
ruff check . && mypy agents libs
```
+ vérification live ci-dessus (captures/logs à l'appui, pas juste "ça a l'air bon").

## Fin de session

`HANDOFF.md` (bloc daté : le gap S9/S12 marqué comblé, les guards S12 enfin actifs en trafic réel) · commit sur branche · PR pour review Fabien — **jamais de merge auto**.

## Prompt de lancement (à coller dans une session Claude Code fraîche)

```
Lis CLAUDE.md, HANDOFF.md (addendum S12, section « Reste »), puis phases/S14-search-leaf-budget-timeslot-delta.md et exécute cette phase, dans ce périmètre exactement.
Règles : un seul scope (feuille search uniquement, zéro changement concierge) ; fin = DoD verte + vérification LIVE avec preuves (logs/captures) + HANDOFF à jour + commit branche, jamais de merge.
```
