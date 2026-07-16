# S08 — Batteries conversationnelles + release gate (∥ possible avec S09)

| | |
|---|---|
| **Mode** | **LOOP possible** (famille de scénarios par itération) — ou piloté |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `git worktree add ../AgentB2C-s8 -b s8-batteries` si S09 en parallèle |
| **Zone autorisée** | `evals/**`, `scripts/**` + tests — NE PAS toucher `src/api`/façade (zone S09) |
| **Prérequis** | S07 mergée |
| **Durée cible** | 1 journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `evalset/evalset-v0.adk.json` · structure de référence (agent-usa, STRUCTURE seulement) : `scripts/run_dynamic_conversation_regression.py`, `scripts/run_release_gate.py`, `evals/judge.py`

## Périmètre
**IN** : batterie conversationnelle live par familles (8), release gate (`--quick` = units + budget ; complet = + batterie LLM), assertions budget (≤3 LLM/tour sur les scénarios types), baselines posées.
**OUT** : la façade (S09), le shadow-run (S10 — nécessite ES prod).

## Étapes (= items de boucle, une famille par itération)
1. Harness : rejoue les `user_turns` d'un scénario contre l'orchestrateur local, juge la sortie (reprendre la logique du judge d'agent-usa, adaptée), compare au comportement attendu de la famille.
2. Familles dans l'ordre : simple_search, empty_dead, empty_recovered, budget_search, timeslot_search, named_hotel, compare, multi_turn_long.
3. `run_release_gate.py` : exit 1 = don't merge ; baselines dans `evals/baselines.json` (mise à jour UNIQUEMENT via flag explicite).
4. Assertion budget : le compteur LLM/tour de S02 vérifié sur toute la batterie.

## DoD (exécutable)
```bash
python scripts/run_release_gate.py --quick
python scripts/run_release_gate.py          # gate complète verte sur 32 scénarios
```

## Fin de session
HANDOFF (baselines posées) · commit + MR. **Ordre de merge si ∥ : S08 d'abord, S09 rebase.**
