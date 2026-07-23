# S-G8 — Durcissement du harness d'éval (les 8 items de l'audit ; le pack reste byte-identique)

| | |
|---|---|
| **Mode** | Piloté puis loop possible (8 items indépendants, spec exécutable) |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `sg8-harness-hardening` (∥ possible avec S-G6/S-G7 : zone `scripts/` disjointe des agents) |
| **Zone autorisée** | `scripts/**` + `tests/**` — **INTERDIT** : `dayuse_eval_pack/eval_pack/**` (le pack ne se modifie JAMAIS, invariant S-A) et `agents/**` |
| **Prérequis** | Aucun (indépendant des waves 1-2) · Arbitrage : les 8 items acceptés tels quels |
| **Durée cible** | 1 journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` (addendum S-A 2026-07-21 : architecture adapter/runner, triage des échecs) · `REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md` (§ « Durcissements du harness ») · `scripts/run_eval_adapter.py` (le pattern existant : mapping divulgué, jamais d'invention).

## Périmètre
**IN** — une couche d'annotation/scoring PAR-DESSUS les résultats du pack (pattern `annotate_inventory_confound` prévu en S-C), en scripts autonomes stdlib :
1. `min_hotels >= 1` exigé sur les cas geo censés trouver une offre (liste des case-ids concernés générée depuis les fixtures, pas à la main).
2. Score séparé en 3 classes : `safe_clarification` / `successful_search` / `technical_degradation` (aujourd'hui confondues dans « passed »).
3. Vérification pays + ancre résolus même à shortlist vide (lit `active_filters.country_code`/`resolved_city` — exposés depuis S-G1).
4. Assertions par tour : date, zone, horaires (minutes comprises), devise, named_hotel après chaque tour (lit `active_filters` — dé-nullé en S-G1).
5. Une distance invérifiable = échec quand le cas impose la proximité (lit `distance_km`/`distance_origin` des cartes — exposés depuis S-G3).
6. « Autres options » : minimum de NOUVEAUX IDs ou divulgation d'épuisement exigés (S-G5).
7. Rapport triple : score brut / score hors outils indisponibles / taux de timeout — séparés.
8. Replay ×3 des gates critiques (les 81 cas geo+multiturn+prod-wounds) avec rapport de stabilité (variance pass/fail par cas).

**OUT** : modification du pack (jamais) · modification des agents (les items 3-6 CONSOMMENT ce que les waves 1-2 exposent ; si un champ manque encore, l'assertion sort `skipped: field_missing`, jamais un faux vert) · le run de gate lui-même (S-G9).

## Étapes
1. Inventaire des champs disponibles dans un résultat de run actuel (un JSON de `eval_pack/results/` en local) → mapping item→champ, constat HANDOFF.
2. Items 1-2-7 (ne dépendent d'aucune wave) — tests unitaires sur fixtures de résultats synthétiques.
3. Items 3-6 avec dégradation `skipped: field_missing` tant que les waves ne sont pas mergées.
4. Item 8 (orchestration replay ×3 + rapport variance).
5. `python3 -u` pour tout runner détaché ; artefacts long-running → scratchpad puis `cp` (piège sandbox documenté S-A).

## DoD (exécutable)
```bash
pytest tests/ -q                        # tests des scripts d'annotation
.venv/bin/ruff check . && bash scripts/dayuse_guardrails.sh .
# démo : annotation d'un results/*.json existant → rapport 3-classes + assertions par tour générés
```

## Fin de session
HANDOFF (mapping item→champ + items en `skipped` restants) · commit + MR.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md (addendum S-A), REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md (§ Durcissements),
scripts/run_eval_adapter.py, puis phases/SG8-durcissement-harness.md et exécute cette phase,
dans ce périmètre exactement.
Règles : le pack eval est INTOUCHABLE (byte-identique) ; tout vit dans scripts/ ; une assertion sans champ
disponible = skipped divulgué, jamais un faux vert ; fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```
