# S01 — Socle repo + feuille `hotel-search-agent`

| | |
|---|---|
| **Mode** | Session pilotée (PAS de loop — choix de structure) |
| **Modèle** | Opus (`claude-opus-4-8`) — fondations, le coût d'une mauvaise structure dépasse le coût tokens |
| **Branche** | `s1-socle-feuille-search` (après `git init`) |
| **Prérequis** | Hook PreToolUse du plugin vérifié (matcher sain = `mcp__gitlab__…\|mcp__notion__…` seulement) |
| **Durée cible** | ½ journée |

## Entrées à lire (et rien d'autre)
`CLAUDE.md` · `HANDOFF.md` · `SCAFFOLDING-BRIEF-PH2.md` §1-3 · en référence de pattern : `~/Projects/DayuseAgency/dayuse-agent-fleet/agents/booking_qa/` (feuille cliente MCP streamable-http)

## Périmètre
**IN** : init du repo, scaffolding et exposition A2A de la feuille search (squelette fonctionnel, pas les guards géo — c'est S4).
**OUT** : faq-agent, orchestrateur (S2), guards géo/Mapbox réel (S4), CI complète (S3).

## Étapes
1. `git init` + `.gitignore` (`baseline/`, `.env`, `.run-logs/`, `__pycache__/`, `.venv*`) + premier commit des docs existants (PLAN, AUDIT, BRIEF, SESSIONS, phases/, CLAUDE.md, HANDOFF.md, evalset/ — PAS baseline/).
2. `/scaffold-agent` → `hotel-search-agent` : ADK Python 3.12, LiteLLM (`DAYUSE_MODEL`), client MCP_B2C streamable-http (`MCP_B2C_URL`, `MCP_B2C_AUTH_TOKEN` — staging OK en dev), tools `search_offers` + `find_hotel_by_name`.
3. Contrat stateless dans le squelette : entrée `{query_params, profile_in}` → sortie `{results, profile_delta, diagnostics}` (`DataPart`). 0-1 appel LLM interne. AUCUN accès Redis.
4. `/wire-a2a` : Agent Card signée servie sur `/.well-known/agent-card.json`, `securitySchemes` = bearer intérimaire (D7) vérifié dans `serve.py` — documenter l'exception + échéance dans le README du service.
5. Timeouts propriétaires : MCP 5 s + circuit-breaker (stub acceptable, TODO S4 pour Mapbox).
6. Reprendre `dayuse_guardrails.sh` de la fleet (adapter les chemins) + le brancher en pre-commit local.
7. Remplir la section **Commandes** de `CLAUDE.md` (run local, tests, guardrails).

## DoD (exécutable)
```bash
bash scripts/run_local.sh          # la feuille boote
curl -s localhost:<port>/.well-known/agent-card.json | jq .name
pytest -q                          # squelette de tests vert
bash scripts/dayuse_guardrails.sh .
```

## Fin de session
HANDOFF.md mis à jour (bloc daté : fait/reste/pièges) · commit + MR (review Fabien) · noter le port choisi et les env vars dans HANDOFF.
