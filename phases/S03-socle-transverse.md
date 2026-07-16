# S03 — Socle transverse : lib commune, CI, observabilité, harnais d'éval

| | |
|---|---|
| **Mode** | Session pilotée |
| **Modèle** | Sonnet (`claude-sonnet-5`) — plomberie bien spécifiée |
| **Branche** | `s3-socle-transverse` |
| **Prérequis** | S2 mergée |
| **Durée cible** | ½ à 1 journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `SCAFFOLDING-BRIEF-PH2.md` §3-4 · fleet : `libs/dayuse_agent_common/` (metrics.py, metrics_pg.py, identity/) et `.gitlab-ci.yml`

## Périmètre
**IN** : dépendance `dayuse_agent_common`, métriques, CI, conversion evalset au format ADK.
**OUT** : logique métier.

## Étapes
1. `dayuse_agent_common` en dépendance (⚠️ mode d'installation — path local vs git — **à confirmer avec Fabien si ambigu, ne pas décider seul**). Interdiction de copier le code de la lib.
2. Métriques jour 1 : callbacks `metrics.py` + `metrics_pg` sur orchestrateur et feuilles, `service=b2c-concierge|b2c-hotel-search|b2c-faq`. No-op sans `DATABASE_URL` (contrat existant de la lib). Test RGPD : **aucun contenu de message dans les événements** (verrouillé par assertion).
3. Identité intérimaire consolidée : vérification bearer partagée via la lib (pattern booking_qa), `dev-insecure` utilisable en local UNIQUEMENT (test CI qui échoue si `dev-insecure` dans une config de déploiement).
4. CI `.gitlab-ci.yml` : lint (ruff), typecheck (mypy), pytest, `dayuse_guardrails.sh`, job `adk eval`.
5. Convertir `evalset/evalset-v0.json` (32 scénarios) au format evalset ADK → `evalset/evalset-v0.adk.json` + brancher `adk eval` (échecs fonctionnels tolérés à ce stade : le squelette ne sait pas encore chercher).
6. Postgres jetable local (`docker run postgres`) pour vérifier l'écriture `llm_metric_events`.

## DoD (exécutable)
```bash
ruff check . && mypy src/ && pytest -q && bash scripts/dayuse_guardrails.sh .
adk eval <agent> evalset/evalset-v0.adk.json   # s'exécute (score libre)
psql $DATABASE_URL -c "SELECT service, count(*) FROM llm_metric_events GROUP BY 1;"
```

## Fin de session
HANDOFF · commit + MR. Noter dans HANDOFF le mode d'install retenu pour la lib commune.
