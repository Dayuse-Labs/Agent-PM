# S-G6 — Dates, durées, demi-heures de bout en bout (après S-G1, S-G2 ; feuille + concierge)

| | |
|---|---|
| **Mode** | Piloté (piège gpt-4o-mini sur l'extraction → vérifs live obligatoires) |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `sg6-dates-durations-minutes` — séquentiel après S-G5 (mêmes fichiers feuille : instruction + response_bridge) |
| **Zone autorisée** | `agents/hotel_search_agent/**` (instruction, schéma d'extraction, capture, post-filtre) + `agents/b2c_concierge/**` (résolution date relative en code) + tests |
| **Prérequis** | **S-G1 mergée** (champs `date`/`date_reference`) · **S-G2 mergée** (`client_local_time`/`client_timezone` au profil) · Arbitrage **A4-c** (filtre client maintenant + demande de schéma MCP en parallèle) |
| **Durée cible** | 1 journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` (§4, A4) · `reports/research/multiturn-state-memo.md` (§e time handling — LLM étiquette, le code calcule) · `reports/research/code-verification-memo.md` (claim 5) · `tasks/lessons.md` (leçon S10 #4 : négation/hallucination gpt-4o-mini) · HANDOFF addendum eval 2026-07-22 (bugs `core-e2e-084` et `core-e2e-201`).

## Bugs cibles (les 3 sont la spec)
1. **`core-e2e-084`** : « 7h30-13h30 » tronqué en 07:00-13:00 — le schéma envoyé au MCP n'a que des heures entières ; la capture force minute=0 (`response_bridge.py:202-203`).
2. **`core-e2e-201`** : « for 1 hour » = une DURÉE, extraite comme fenêtre absolue « 00:00-01:00 » — même famille que l'incident prod « 20 minutes → 20 € ».
3. **Suites date/disponibilité 0/3 de l'audit** : la date donnée au tour 1 n'existe nulle part au tour 2.

## Périmètre
**IN** :
1. **Schéma d'extraction feuille étendu** (l'appel LLM existant, zéro appel en plus) : `timeSlot` passe à `startHour/startMinute/endHour/endMinute` (minutes ∈ {0,15,30,45}, défaut 0) ; nouveau label `duration` (ISO-8601 style « PT1H », DISTINCT de timeSlot — une durée n'est JAMAIS convertie en fenêtre absolue par le LLM) ; nouveau label `date {type: absolute|relative, value, expression}` — le LLM ÉTIQUETTE, il ne calcule jamais.
2. **Résolution en code (concierge)** : date relative résolue en ISO avec `client_local_time`/`client_timezone` du profil (fallback horloge serveur documenté si absents) → `profile.date` + `date_reference {expression, resolved_from, client_tz}`. Une durée + heure de début → fenêtre calculée en code ; une durée seule → stockée, PAS de fenêtre inventée.
3. **Demi-heures vers le MCP (A4-c intérim)** : envoi des heures englobantes (floor/ceil) à `search_offers`, puis **post-filtre déterministe des offres par les minutes exactes** côté feuille — possible car les offres RENVOIENT `startMinute`/`endMinute` (déjà parsées, `response_bridge.py:263-265`). Si le post-filtre vide la liste : disclosure honnête (« aucune offre couvrant 07:30 précises ; voici les plus proches ») plutôt que 0 silencieux.
4. **Capture** : `_budget_timeslot_from_args` capture les minutes réelles (`_hhmm(h, m)`) ; profil déjà en « HH:MM » (rien à migrer).
5. **Affichage** : `templates._format_time_slot` cesse de forcer `:00`.
6. **Doc cross-repo** : `reports/MCP-B2C-REQUESTS.md` (neuf ou complété) — demande de `startMinute`/`endMinute` sur `search_offers` (A4-a), avec date d'échéance du retrait du post-filtre intérim.

**OUT** : tout changement dans MCP_B2C lui-même · pagination (S-G5) · le calendrier/disponibilité MCP (la date n'est PAS encore un paramètre de `search_offers` — vérifier au probe si un param date existe ; sinon la date sert au contexte de synthèse + à `active_filters`, et la limite est documentée honnêtement).

## Étapes
1. Probe : `search_offers` a-t-il un paramètre date ? (constat HANDOFF — conditionne le point OUT).
2. Tests d'abord : matrice extraction (demi-heures fr/en, « for 1 hour », « le 28 », « demain » avec timezone, minuit, formulations vagues → RIEN d'extrait).
3. Schéma + instruction + capture + résolution code + post-filtre.
4. **Vérif LIVE obligatoire (leçon S10 #4)** : « entre 7h30 et 13h30 » → filtre exact ; « une chambre pour une heure » → AUCUNE fenêtre 00:00-01:00, AUCUN budget inventé ; « demain » → date ISO correcte au profil ; formulation vague (« plus tôt ») → rien d'inventé.
5. Doc MCP-B2C.

## DoD (exécutable)
```bash
pytest -q          # +~30 tests
.venv/bin/ruff check . && .venv/bin/mypy agents libs && bash scripts/dayuse_guardrails.sh .
# live : les 4 vérifications de l'étape 4, résultats structurels dans HANDOFF
```

## Fin de session
HANDOFF (constat param date + preuves live) · commit + MR.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§4 A4),
reports/research/multiturn-state-memo.md (§e), tasks/lessons.md, puis phases/SG6-dates-durees-demiheures.md
et exécute cette phase, dans ce périmètre exactement.
Règles : le LLM étiquette (date/durée/fenêtre), le code calcule — jamais l'inverse ; une durée n'est jamais
une fenêtre absolue ; vérifs live des formulations pièges obligatoires (leçon S10 #4) ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```
