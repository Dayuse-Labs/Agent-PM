# S10 — Shadow-run : parité vs agent-usa sur ES de PROD

| | |
|---|---|
| **Mode** | Session pilotée — **JAMAIS de loop** (données réelles, analyse) |
| **Modèle** | Sonnet (`claude-sonnet-5`) pour le harness ; l'analyse du rapport peut se faire en session Cowork avec Fabien |
| **Branche** | `s10-shadow-run` |
| **Prérequis** | S09 mergée · **MCP_B2C déployé (ticket 5.1) et pointé sur l'ES de PROD (lecture seule)** · agent-usa local ou staging accessible pour la comparaison |
| **Durée cible** | 1 journée + analyse |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `PLAN-REWORK-AGENT-USA.md` §5 Ph3.3 et §8 (gate hybride) · `AUDIT-REWORK-2026-07.md` §5 (P1/P4 à revalider sur prod)

## Périmètre
**IN** : harness dual-run (mêmes requêtes → agent-usa ET AgentB2C), rapport de parité chiffré.
**OUT** : tout déploiement de trafic réel (S11).

## Étapes
1. **Revalider P1/P4 sur ES prod d'abord** (notes/avis denses ? Kimpton présent ?) — si P1 est confirmé sur prod, STOP : décision enrichissement notes avec Fabien avant de continuer.
2. Harness : rejouer les 32 scénarios + un échantillon élargi de requêtes réelles (tirées de l'evalset, jamais du CSV brut) contre les deux stacks.
3. Mesures : recouvrement top-N des shortlists, pertinence jugée (judge S08 sur les deux sorties, à l'aveugle), latence par tour (A/B synthétique — mêmes conditions), fraîcheur/réservabilité (offres AgentB2C réservables à la date vs cartes agent-usa), taux de recherches vides.
4. Rapport `SHADOW-RUN-REPORT.md` : verdict par métrique vs cibles D4, recommandation GO / fallback hybride (gate du plan §8).

## DoD
Rapport généré, chiffré, avec verdict argumenté — **la décision GO/hybride appartient à Fabien**.

## Fin de session
HANDOFF · commit + MR · présenter le rapport à Fabien (gate).
