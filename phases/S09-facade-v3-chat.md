# S09 — Façade `POST /v3/chat` iso-contrat + endpoint SSE (∥ possible avec S08)

| | |
|---|---|
| **Mode** | Session pilotée (contrat = zone à jugement, PAS de loop) |
| **Modèle** | Sonnet (`claude-sonnet-5`) — passer sur Opus si arbitrages de contrat imprévus |
| **Branche/worktree** | `git worktree add ../AgentB2C-s9 -b s9-facade` si S08 en parallèle |
| **Zone autorisée** | façade/API + ses tests — NE PAS toucher `evals/**` (zone S08) |
| **Prérequis** | S07 mergée (le contrat s'appuie sur le comportement complet) |
| **Durée cible** | 1 journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · contrat de sortie d'agent-usa : `src/api/routes/chat.py` — UNIQUEMENT le schéma JSON de réponse (`message, hotels, suggestions, session_id, active_filters, …`) et les tests API existants comme fixtures golden. NE PAS lire le reste du fichier (1 872 lignes).

## Périmètre
**IN** : endpoint `POST /v3/chat` iso-contrat (mêmes clés/formes — bascule invisible), endpoint SSE (events `progress`/`hotels`/tokens de S06 exposés), persistance `conversation_logs` AVEC colonne `is_synthetic` (header interne), cookie/session id compatibles, reset de session.
**OUT** : canary/déploiement (S11), auth interne complète (reprendre le minimum : API key interne).

## Étapes
1. Golden tests D'ABORD : capturer le schéma de réponse exact d'agent-usa depuis ses tests API (pas depuis la prod), en faire des fixtures de non-régression de contrat.
2. Façade : mapping état orchestrateur → contrat v3 (hotels serialisés comme aujourd'hui, active_filters, suggestions). Prix : depuis `priceEuro` centimes → format d'affichage (cohérent avec S07).
3. SSE : `GET /v3/chat/stream` (ou POST + Accept, suivre la convention front la plus simple) — event `progress` < 300 ms, `hotels`, puis tokens ; le JSON non-streamé reste servi à l'identique.
4. `conversation_logs` : mêmes colonnes qu'agent-usa + `is_synthetic` (détection par header interne type `X-Dayuse-Synthetic`) — les batteries S08 doivent le poser.
5. TTL Redis sessions + doc rétention (README section données).

## DoD (exécutable)
```bash
pytest tests/api -q                    # golden tests contrat verts
curl -N localhost:<port>/v3/chat/stream ... | head   # progress arrive immédiatement
python scripts/smoke_e2e.py --contract # aller-retour complet via la façade
```

## Fin de session
HANDOFF · commit + MR. **Merger APRÈS S08 si parallèle.**
