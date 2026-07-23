# S-G9 — Re-run du gate 81 cas (×3) + design de l'éval ranking (dernière session — JAMAIS en loop)

| | |
|---|---|
| **Mode** | Piloté, jamais loop (mesure + jugement, données réelles) |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `sg9-gate-rerun` |
| **Zone autorisée** | `scripts/**` (runs + rapport) + `reports/**` — AUCUN changement `agents/**` (si le gate révèle un bug : le DOCUMENTER, pas le corriger ici) |
| **Prérequis** | **Waves 1-2 mergées (S-G1→S-G7)** · **S-G8 mergée** (le harness durci est l'instrument de mesure) · 3 services up + MCP staging (ou prod ES si S-C débloquée d'ici là — le rapport DIT lequel) · Arbitrage **A8-a** |
| **Durée cible** | 1 journée (runs longs — lancer tôt) |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md` (§ gates + § pertinence) · `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` (§8 mapping gates→axes) · HANDOFF S-A (pièges runner : latence = somme des tours, `python3 -u`, scratchpad).

## Périmètre
**IN** :
1. **Gate re-run** : les **81 cas** (41 geo + 27 multi-turn + 13 blessures production) **×3 replays** via l'adapter S-A + le harness durci S-G8. Mêmes conditions documentées que le run du 22/07 (modèle via env — noter `DAYUSE_MODEL` réel, inventaire, partitions séquentielles pour éviter le confond timeout du run concurrent).
2. **Rapport de gate** (`reports/GATE-RERUN-<date>.md`) contre les 7 critères de l'audit : zéro mauvais pays · zéro perte de contrainte explicite entre tours · zéro remplacement silencieux GPS/adresse/zone · aucun succès geo vide quand une offre existe · parité ≥ 58/81 (le score agent-usa) · taux de timeout < seuil produit · stabilité inter-replay. Chaque échec restant trié UN PAR UN (règle du pack) : bug résiduel / gap connu / confond d'inventaire.
3. **Éval ranking (design + première exécution, A8-a)** : pool de candidats IDENTIQUE entre agents (destination résolue imposée), vérité distance depuis les coords des cartes (S-G3), contraintes dures vérifiées, métriques `precision@5`/`NDCG@5` — script + doc de protocole. Objectif : rendre la question « faut-il un reranker ? » DÉCIDABLE ; pas de reranker ici.

**OUT** : tout fix agent (documenter → nouvelle session ciblée) · le canary lui-même (gate humaine Fabien, S11) · comparaison agent-usa live (réutiliser les résultats du 22/07 comme référence, sauf si Fabien demande un re-run miroir).

## Étapes
1. Vérifier l'environnement (services, MCP, `DAYUSE_MODEL`) → conditions loggées en tête de rapport.
2. Lancer les 3 replays (nohup `python3 -u`, artefacts scratchpad puis `cp`).
3. Annotation S-G8 + triage un-par-un des échecs.
4. Script + protocole éval ranking, première mesure.
5. Rapport final + verdict par gate (PASS/FAIL/NON-MESURABLE avec cause).

## DoD (exécutable)
```bash
# les 3 runs terminés, rapport généré :
ls reports/GATE-RERUN-*.md
# le rapport contient : 7 gates avec verdict, triage complet des échecs, variance ×3, conditions du run
```

## Fin de session
HANDOFF (verdict par gate + liste des bugs résiduels pour sessions suivantes) · commit + MR. **Le GO canary reste une décision Fabien** — le rapport instruit, il ne décide pas.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md (§ gates),
reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§8), puis phases/SG9-gate-rerun-eval-ranking.md
et exécute cette phase, dans ce périmètre exactement.
Règles : mesure seulement, zéro fix agent (documenter les bugs trouvés) ; chaque échec trié un par un ;
conditions du run loggées (modèle, inventaire, séquentiel) ; le GO canary appartient à Fabien ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```
