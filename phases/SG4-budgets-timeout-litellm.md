# S-G4 — Budgets timeout par famille + retries LiteLLM + root-cause Chester (∥ possible avec S-G1, S-G3)

| | |
|---|---|
| **Mode** | Piloté |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `sg4-timeout-budgets` (∥ S-G1 : fichiers disjoints — `agent.py` consts vs `profile.py` ; merger S-G1 d'abord, rebase) |
| **Zone autorisée** | `agents/b2c_concierge/**` (consts timeout `agent.py`, config LiteLLM) + instrumentation feuille (`agents/hotel_search_agent/**` compteurs par phase) + tests |
| **Prérequis** | Arbitrage **A5-a** (budgets statiques par famille v1 ; deadline propagation = phase ultérieure, hors scope) |
| **Durée cible** | ½–1 journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/research/timeouts-latency-memo.md` (EN ENTIER — méthode false-timeout-rate, params LiteLLM vérifiés, flags §fin) · `reports/research/code-verification-memo.md` (claim 6) · HANDOFF addendum 2026-07-22 Railway (le 10 s → 30 s en env, les mesures cold/FAQ).

## Périmètre
**IN** :
1. **Budgets par famille** : remplacer l'unique `CONCIERGE_LEAF_TIMEOUT_SECONDS` par `…_SEARCH` et `…_FAQ` (fallback sur la variable legacy si posée — ne pas casser le déploiement Railway existant). Défauts posés depuis les mesures disponibles (Railway : FAQ ~9 s à chaud, 1er appel search >10 s à froid ; méthode du memo : percentile sain + marge, PAS l'intuition) — proposition de départ : search 15 s, faq 25 s, à ajuster sur constat. La méthode et les chiffres source documentés en commentaire.
2. **Toujours 0 retry orchestrateur→feuille** (invariant conservé — règle SRE une-seule-couche).
3. **LiteLLM** : `RetryPolicy` par exception (Timeout/RateLimit : 1 retry ; BadRequest/Auth/ContentPolicy : 0) sur les appels concierge (triage + synthèse) ; `stream_timeout` posé pour protéger le TTFT de la synthèse. ⚠️ Flag du memo à lever par un test local de 10 lignes : `num_retries` × `timeout` — chaque tentative a-t-elle son plein timeout ou le partage-t-elle ?
4. **Instrumentation par phase (feuille)** : compteurs `dayuse_metric` par étape (geocode ms / MCP ms / LLM ms / total) — flags et durées SEULES, jamais de contenu (règle S10/S14). C'est le prérequis pour poser des budgets honnêtes et, plus tard, la deadline propagation.
5. **Root-cause Chester GB** : bug de latence bimodale (timeout même isolé, replay compris). Probe avec l'instrumentation ci-dessus : quelle phase pend ? (hypothèses : géocode echo-mismatch → retry ? boucle LLM d'extraction ? MCP ?). Le corriger si la cause est dans le repo ; sinon documenter précisément (item MCP-B2C).

**OUT** : deadline propagation bout-en-bout (A5-b, phase ultérieure — ne pas commencer) · hedging (rejeté à l'arbitrage) · warm-up post-deploy (noté HANDOFF Railway, décision infra séparée) · tout changement des timeouts Mapbox 1,5 s / MCP 5 s (propriétaires uniques, corrects).

## Étapes
1. Test local LiteLLM (num_retries × timeout) → constat HANDOFF.
2. Budgets par famille + fallback legacy + tests (env var précédence).
3. RetryPolicy + stream_timeout + tests.
4. Instrumentation par phase (tests RGPD : aucune valeur métier dans les métriques).
5. Probe Chester en live (3 services, .env) → fix ou diagnostic documenté.

## DoD (exécutable)
```bash
pytest -q && .venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
# live : un tour search + un tour faq passent sous leurs budgets respectifs (métriques par phase visibles)
```

## Fin de session
HANDOFF (constat num_retries×timeout + budgets retenus + verdict Chester) · commit + MR.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/research/timeouts-latency-memo.md (en entier),
reports/research/code-verification-memo.md (claim 6), puis phases/SG4-budgets-timeout-litellm.md
et exécute cette phase, dans ce périmètre exactement.
Règles : 0 retry orchestrateur→feuille (invariant) ; budgets posés depuis des mesures, méthode documentée ;
Chester = bug de correctness à tracer par l'instrumentation, pas un timeout à élargir ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```
