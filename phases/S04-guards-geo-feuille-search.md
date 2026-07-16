# S04 — Feuille search réelle : Mapbox + guards géo (∥ possible avec S05)

| | |
|---|---|
| **Mode** | **LOOP ENGINEERING recommandé** (portage test-driven) — ou piloté |
| **Modèle** | Sonnet (`claude-sonnet-5`) — y compris dans la boucle |
| **Branche/worktree** | `git worktree add ../AgentB2C-s4 -b s4-guards-geo` si S05 tourne en parallèle |
| **Zone autorisée** | `agents/hotel_search_agent/**` + ses tests UNIQUEMENT (S05 travaille sur l'orchestrateur) |
| **Prérequis** | S3 mergée · tools MCP_B2C mergés (review Fabien) |
| **Durée cible** | 1-2 journées (ou ~10-15 itérations de boucle) |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · **spec exécutable (agent-usa)** : `tests/unit/application/test_audit_fixes_2026_06.py` (sections geocode echo-back, state anchoring, generic place words — ~30 tests) ; source à consulter SEULEMENT si un test l'exige : `search_tool.py::_geocode_echo_matches`, `search_profile.py::is_generic_location_token` et `last_state_context`

## Périmètre
**IN** : client Mapbox réel (httpx, timeout 1,5 s, 1 retry, cache mémoire borné), portage des 3 guards géo avec leurs tests, circuit-breaker MCP.
**OUT** : profil de session (S05), synthèse (S06).

## Étapes (= items de boucle, UN par itération)
1. Client Mapbox + timeouts/retry/cache (tests unitaires mockés).
2. Guard **geocode echo-back** : un résultat limit=1 doit refléter l'état US + un token distinctif, sinon rejeté (exemption codes aéroport). Porter les tests un par un.
3. Guard **generic place words** : « airport », « downtown »… jamais acceptés comme ville → hint de zone + demande de la vraie ville.
4. Guard **state anchoring** : l'état US nommé est ancré, forwardé, qualifie le géocodage ; effacé si nouvelle ville explicite sans état.
5. Circuit-breaker MCP 5 s + tests de dégradation (MCP down → diagnostics propre dans la sortie DataPart, pas d'exception).

## Règles de loop (si mode boucle)
Les tests portés sont LA spec : **interdiction de les affaiblir** (tout diff sur un test porté = STOP). Même test rouge 2 itérations de suite = STOP et question. Commits locaux sur la branche, JAMAIS de push dans la boucle.

## DoD (exécutable)
```bash
pytest agents/hotel_search_agent -q      # dont ~30 tests géo portés
pytest -q && bash scripts/dayuse_guardrails.sh .
```

## Fin de session
HANDOFF (guards portés : liste + compteur x/30) · commit + MR. **Ordre de merge si ∥ : S04 d'abord, S05 rebase ensuite.**
