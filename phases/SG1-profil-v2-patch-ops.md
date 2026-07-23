# S-G1 — Profil v2 : schéma complet + patch ops typées (concierge) (∥ possible avec S-G3, S-G4)

| | |
|---|---|
| **Mode** | Piloté (tests d'abord), loop possible sur la matrice de transitions |
| **Modèle** | Sonnet (`claude-sonnet-5`) — le design est arbitré, la spec est exécutable |
| **Branche/worktree** | `git worktree add ../AgentB2C-sg1 -b sg1-profile-v2` si ∥ S-G3/S-G4 |
| **Zone autorisée** | `agents/b2c_concierge/**` (surtout `profile.py`, `facade.py::build_active_filters`) + tests — NE PAS toucher `agents/hotel_search_agent/**` (zones S-G3/S-G5) |
| **Prérequis** | Arbitrage 2026-07-23 : **A3-a** (ops typées, absent = carryover) |
| **Durée cible** | 1 journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` (§4 axe M) · `reports/research/multiturn-state-memo.md` (patterns SOM-DST/Diable, RFC 7386, §synthèse) · `reports/research/code-verification-memo.md` (claims 3, 4, 9 — l'état exact du code).

## Périmètre
**IN** :
1. **Nouveaux champs `SessionProfile`** : `named_hotel {hotel_id, name, source}` · `zone` · `metro` · `date` (ISO 8601) + `date_reference {expression, resolved_from, client_tz}` · `currency` · `locale` · `domain` · `search_anchor {type: gps|address|zone|poi|city_centroid, lat, lon, label, set_at_turn}` · `distance_origin` · `shown_hotel_ids` (liste accumulée, cap 25) · `search_cursor` (int). Tous optionnels, `to_dict`/`from_dict` symétriques.
2. **`apply_profile_delta` v2 = reducer à ops typées** : chaque slot du delta accepte `{op: "set"|"clear", value}` ; **absent = carryover** (jamais de perte par omission). **Rétro-compat obligatoire** : le format plat actuel de la feuille (`clé: valeur`) est traité comme `set` implicite — la feuille ne migre qu'en S-G5/S-G6, rien ne casse entre-temps. Chaque `clear` est loggé (compteur RGPD-safe : noms de slots, jamais les valeurs).
3. **Règles d'invalidation en code** (la partie subtile, tests exhaustifs) : changement de `city` → clear `zone`/`metro`/`search_anchor`/`state_anchor`/`country_anchor` + reset `shown_hotel_ids`/`search_cursor` (comportement actuel des anchors conservé) ; changement de `zone` seul → **conserver** `date`, `timeslot_*`, `budget_max`, `amenities` (le cas 0/3 de l'audit) ; « autres options » → tout conserver, avancer le curseur.
4. **`schema_version`** stampé dans le DataPart `profile_in` (et attendu-toléré dans le delta).
5. **`build_active_filters` dé-nullé** : exposer `named_hotel`, `date_reference`, `zone`, `currency`, `distance_origin` depuis le profil. ⚠️ Champs DANS `active_filters` uniquement — `CONTRACT_KEYS` (facade.py:59-80) ne bouge pas (iso-contrat).
6. **`shown_hotel_ids`** : `record_search_shortlist` accumule (en plus du remplacement de `last_results` qui reste tel quel pour l'ordinal S07).

**OUT** : extraction/émission côté feuille (S-G5, S-G6) · intake facade des champs request (S-G2) · toute logique geo (S-G3) · résolution de dates relatives (S-G6 — ici on ne fait que STOCKER).

## Étapes
1. **Tests d'abord** : matrice de transitions du reducer (≥25 cas) — les 3 variantes zone-change de l'eval pack, conservation date sur changement de zone, named_hotel set/clear, rétro-compat delta plat, `clear` explicite vs absent, shown_ids accumulation + reset, cap 25.
2. Schéma + reducer + invalidation.
3. `active_filters` + tests golden du contrat (mêmes clés top-level qu'avant).
4. Compteur RGPD-safe des ops (`dayuse_metric=profile_ops set=<n> clear=<n> slots=<names>` — jamais de valeur).

## DoD (exécutable)
```bash
pytest agents/b2c_concierge -q          # +~30 tests, les ~240 existants inchangés
pytest -q && .venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Fin de session
HANDOFF (schéma final + sémantique du reducer + ce qui reste émis à plat par la feuille) · commit + MR. Si ∥ S-G3/S-G4 : **merger S-G1 en premier** (les autres rebasent).

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§4),
reports/research/multiturn-state-memo.md, reports/research/code-verification-memo.md (claims 3/4/9),
puis phases/SG1-profil-v2-patch-ops.md et exécute cette phase, dans ce périmètre exactement.
Règles : un seul scope (schéma profil + reducer ops côté concierge) ; tests de transitions AVANT le code ;
rétro-compat du delta plat obligatoire ; CONTRACT_KEYS intouché ; fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```
