# S-L8 — Déploiement Railway, registre de la flotte, bascule `on`

| | |
|---|---|
| **Mode** | Piloté, **jamais en boucle** — infrastructure de production ; validation explicite de Fabien avant la bascule |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche** | `sl8-geo-leaf-deploy` (documentation et variables seulement) ; registre : MR sur `dayuse-agent-fleet` |
| **Zone autorisée** | Railway (nouveau service, variables du concierge) · `agents/geo_understanding_agent/Dockerfile` si besoin · `HANDOFF.md` · `agents-registry.yaml` du dépôt `dayuse-agent-fleet` (commit GitLab = HITL) |
| **Prérequis** | S-L5 et S-L6 mergées · D-4 validée · go explicite de Fabien |
| **Durée cible** | non estimée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` (blocs de déploiement : `railway up --service … --environment production --detach`, estampille `LANGFUSE_RELEASE` posée APRÈS le SUCCESS, feuille avant concierge) · `reports/PLAN-LEAF-GEO-2026-10-08.md` (§4-6) · skill `use-railway`.

## Périmètre
**IN** :
1. **Service Railway** de la leaf (nom à choisir, sur le modèle `hotel-search` / `faq`) : réseau privé, min-instances 1 comme les autres (coût : donnée à collecter), variables `A2A_BEARER_TOKEN`, `A2A_HOST` (hôte privé), `PORT`, `DAYUSE_MODEL_GEO`, `LANGFUSE_*`, argument de build `FLEET_READ_TOKEN`. Jamais `--ci` (les journaux de build exposent `FLEET_READ_TOKEN`).
2. **Concierge** : `GEO_UNDERSTANDING_CARD_URL`, `GEO_UNDERSTANDING_A2A_TOKEN`, `CONCIERGE_LEAF_TIMEOUT_GEO_SECONDS` (valeur de S-L4), puis `GEO_LEAF_MODE=shadow`.
3. **Vérification en production** : carte servie, 401 sans bearer, tours de recherche synthétiques (`X-Dayuse-Synthetic: 1`) : latence du saut A2A réel, accord en ombre.
4. **Bascule** `GEO_LEAF_MODE=on` après le go de Fabien ; retour arrière = remettre `shadow` (aucun redéploiement).
5. **Registre** : entrée dans `agents-registry.yaml` de `dayuse-agent-fleet` (`name`, `description`, `card_url`, `env`, `owner`, `writes: false`), via MR GitLab (HITL).
6. **Option A′** (leaf en parallèle du triage) : seulement si la latence mesurée dépasse le budget D-4 — à proposer, pas à faire.

**OUT** : toute modification de code applicatif · retrait de règles (S-L7) · passage à oidc-mtls (CHANTIERS A1).

## Étapes
1. Variables d'abord, service ensuite ; feuille déployée avant le concierge.
2. Vérifications 3 en `shadow`, puis go de Fabien, puis `on`.
3. Registre.

## DoD (exécutable)
```bash
# en shadow, puis en on (le script envoie X-Dayuse-Synthetic: 1 et lit CHAT_API_KEY)
CONCIERGE_URL=https://<concierge> .venv/bin/python scripts/measure_latency_e2e.py --runs 3 \
  --out reports/latency/sl8-shadow.jsonl
```
Service SUCCESS ; dans les journaux du concierge, `concierge_metric=leaf_call leaf=geo_understanding … status=ok` ; un appel sans bearer refusé (401) depuis le réseau privé ; latence et accord en `shadow` dans HANDOFF ; `on` posé après le go écrit.

## Fin de session
HANDOFF (services, estampilles, mesures, heure de la bascule, chemin de retour arrière) · MR du registre.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md (blocs de déploiement Railway), reports/PLAN-LEAF-GEO-2026-10-08.md (§4 à §6), puis
phases/SL8-deploiement-registre.md, et exécute cette phase dans ce périmètre exactement.
Règles : jamais railway up --ci ; feuille avant concierge ; estampille LANGFUSE_RELEASE après le SUCCESS ;
shadow d'abord, on seulement après le go écrit de Fabien ; retour arrière = shadow ; registre par MR GitLab ;
fin = HANDOFF à jour.
```
