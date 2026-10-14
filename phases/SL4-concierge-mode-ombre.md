# S-L4 — Concierge : la leaf géo appelée en mode ombre

| | |
|---|---|
| **Mode** | Piloté — invariant de budget, concurrence de deux legs A2A = jugement |
| **Modèle** | **Opus** (`claude-opus-4-8`) |
| **Branche/worktree** | `git worktree add ../AgentB2C-sl4 -b sl4-geo-shadow` |
| **Zone autorisée** | `agents/b2c_concierge/**` · `evals/battery.py` (miroir du budget) · `evals/replay_runtime.py` (service de la leaf) · `CLAUDE.md` (invariant de budget reformulé selon D-1) — NE PAS toucher `agents/hotel_search_agent/**` ni `agents/geo_understanding_agent/**` |
| **Prérequis** | S-L3 mergée · décision **D-1** (budget d'appels) |
| **Durée cible** | non estimée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-LEAF-GEO-2026-10-08.md` (§2 E1, E8-E10 ; §5 D-1) · `agents/b2c_concierge/b2c_concierge/agent.py` (docstring 1-60, legs 300-420, tour de recherche 1290-1420) · `budget.py` · `routing.py` · `leg.py` · `evals/PRESERVATION.md` (« Running and resuming »).

## Périmètre
**IN** :
1. **Routage** : `LEAF_GEO = "geo_understanding"` dans `LEAF_ENDPOINTS` (`routing.py:35`) : `GEO_UNDERSTANDING_CARD_URL`, port 8103, `GEO_UNDERSTANDING_A2A_TOKEN`.
2. **Timeout propre** : `CONCIERGE_LEAF_TIMEOUT_GEO_SECONDS`, que `CONCIERGE_LEAF_TIMEOUT_SECONDS` n'écrase pas (`agent.py:205-211`). Défaut provisoire : celui du triage (5 s, `triage.py:98`), à remplacer par la mesure de cette session.
3. **Budget (D-1)** : `budget.py:18`, `agents/b2c_concierge/tests/test_budget.py:9`, `agents/b2c_concierge/tests/test_spine.py:246` et `evals/battery.py:47` alignés sur la décision ; phase `geo_llm` chargée AVANT l'appel, comme les autres ; le CLAUDE.md reformulé.
4. **Drapeau `GEO_LEAF_MODE = off | shadow | on`** (défaut `off`). En `shadow`, sur les seuls tours dont la route est `hotel_search`, la leaf est appelée en parallèle de la feuille de recherche ; sa réponse ne change rien au tour.
5. **Leg dédié** : le message de la leaf ne passe pas par `_attach_outgoing_datapart` (`agent.py:343`), qui modifie l'événement utilisateur courant — deux legs en parallèle y liraient le DataPart de l'autre. Payload explicite (message + contexte minimal du plan §3) ; même prudence que `leg.py` sur la méthode privée d'ADK.
6. **Mesure** : métrique `concierge_metric=geo_shadow` à champs catégoriels seulement (accord sur la ville, sur le type de lieu, question attendue / posée) ; latence du leg dans `leaf_call` ; le `GeoIntent` reste dans la trace de la leaf.
7. **Banc de rejeu** : `evals/replay_runtime.py --service` accepte la leaf ; passage `python -m evals.production_replay --split dev …` avec `GEO_LEAF_MODE=shadow`, puis `python -m evals.replay_comparison` contre un passage `off` sur le même corpus.

**OUT** : toute utilisation du `GeoIntent` par la feuille (S-L5) · scores contractuels (`GUARD_SCORE_NAMES`, `FALLBACK_SCORE_NAMES` : S-L5, D-3) · tout trafic de production (pas de trafic réel, CHANTIERS §3).

## Étapes
1. Tests d'abord : en `off`, le tour est identique à aujourd'hui (aucun test existant modifié hors budget) ; en `shadow`, la leaf est appelée une fois, en parallèle, et son échec ne dégrade rien.
2. Routage, timeout, budget, drapeau, leg dédié.
3. Stack locale à 4 services ; rejeu `dev` en `shadow`, puis comparaison appariée.

## DoD (exécutable)
```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```
Rejeu : taux d'accord, latence p50 et p95 du leg géo, et latence du tour en `shadow` contre `off` (le parallélisme ne doit rien ajouter) dans HANDOFF. Données brutes sous `baseline/` uniquement, jamais commitées.

## Fin de session
HANDOFF (décision D-1 appliquée, mesures, cas de désaccord classés par famille, timeout proposé) · commit + MR. Ces mesures alimentent D-4 : Fabien décide la bascule.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-LEAF-GEO-2026-10-08.md (§2 et §5), evals/PRESERVATION.md (« Running and
resuming »), puis phases/SL4-concierge-mode-ombre.md, et exécute cette phase dans ce périmètre exactement.
Règles : GEO_LEAF_MODE=off doit laisser le tour identique ; en shadow la leaf ne change rien au tour ; jamais
_attach_outgoing_datapart pour la leaf ; budget aligné sur la décision D-1 et chargé avant l'appel ; aucune
donnée brute commitée ; fin = DoD verte + rejeu mesuré + HANDOFF + commit sur branche, jamais de merge.
```
