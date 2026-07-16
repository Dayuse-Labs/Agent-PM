# S06 — Synthèse streamée, SSE interne, ground-truth, anti-loop, recovery acks

| | |
|---|---|
| **Mode** | Piloté pour le streaming/architecture, puis **loop possible** pour le portage des guards restants |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche** | `s6-synthese-sse` |
| **Prérequis** | S04 ET S05 mergées |
| **Durée cible** | 1,5-2 journées |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · spec (agent-usa) : `test_audit_fixes_2026_06.py` (ground-truth block, recovery acks), `test_loop_enforcement_and_name_lookup.py` (anti-clarification-loop) ; pattern streaming : `cs_copilot` (événements de progression)

## Périmètre
**IN** : synthèse LLM unique streamée (runner ADK streaming), événements de progression internes (progress → hotels → tokens), prompt à préfixe stable (cache), ground-truth block ≤ 5 hôtels, guards anti-loop + recovery acks, i18n de sortie (réponse dans la langue du user, EN depuis le MCP).
**OUT** : endpoint HTTP/SSE public (S9 — ici on expose un flux interne consommable).

## Étapes
1. Streaming : la synthèse émet token par token ; événement `progress` émis AVANT tout travail (cible < 300 ms, mesuré par test local) ; événement `hotels` dès le retour de la feuille.
2. Prompt synthèse : préfixe statique (system) + blocs dynamiques ordonnés stables ; ground-truth block (≤ 5 hôtels, amenities plafonnées, mention explicite « ne remplace pas les tool calls » + état écran vide après recherche vide).
3. Guard **anti-clarification-loop** : question sortante répétée interceptée → 1 retry avec directive do-not-ask → 2e boucle = strip + ré-émission shortlist. JAMAIS de relance de boucle complète.
4. Guard **recovery acks** : « oui/ok » après une offre matché contre `last_suggestions` persistées (jamais regex sur la prose) ; ack social désactivé si recherches vides consécutives > 0.
5. Mini tool-loop borné (≤ 2 itérations) dans la synthèse uniquement (tours compare→details).

## DoD (exécutable)
```bash
pytest -q                                    # guards S6 portés verts
python scripts/measure_ttft_local.py         # progress < 300 ms local
python scripts/smoke_e2e.py --conversation   # 1 conversation 4 tours cohérente
```

## Fin de session
HANDOFF (compteur guards portés) · commit + MR.
