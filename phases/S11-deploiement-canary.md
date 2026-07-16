# S11 — Déploiement Railway + canary + A/B final

| | |
|---|---|
| **Mode** | Session pilotée, **validation humaine explicite à CHAQUE étape** — JAMAIS de loop, jamais d'action prod sans GO écrit de Fabien |
| **Modèle** | Opus (`claude-opus-4-8`) — jugement, risque prod |
| **Branche** | `s11-deploiement` (infra as code) |
| **Prérequis** | S10 : gate GO passée par Fabien · variables/secrets prod fournis par Fabien (jamais commités) |
| **Durée cible** | 1 journée + fenêtre d'observation |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `SCAFFOLDING-BRIEF-PH2.md` §3-4 · `PLAN-REWORK-AGENT-USA.md` Ph5 · rapport S10

## Étapes
1. **Critères de rollback ÉCRITS AVANT tout déploiement** (latence p95, taux d'erreur, score judge, plainte) + procédure de retour à froid vers agent-usa.
2. Services Railway : orchestrateur + 2 feuilles (min-instances 1, réseau privé `railway.internal`, bearer D7, env LiteLLM). Vérifier résidence EU du provider modèle (précondition RGPD — bloquant).
3. Instrumentation vérifiée en prod : `llm_metric_events` alimenté, dashboard filtre `service=b2c-*`.
4. Canary : bascule par NOUVELLES sessions uniquement, % progressif (proposition : 5 → 25 → 50 → 100, chaque palier validé par Fabien sur le dashboard), sessions Redis en cours restent sur agent-usa.
5. A/B synthétique final : mêmes scénarios chronométrés contre les deux stacks en prod → chiffres avant/après pour le rapport final (plan Ph6).
6. agent-usa gelé en standby après 100 % (pas de décommissionnement dans cette session).

## DoD
Checklist de déploiement cochée · rollback testé à froid · canary actif au premier palier avec dashboard sous les yeux de Fabien.

## Fin de session
HANDOFF · commit + MR · rapport d'étape à Fabien avant chaque palier suivant.
