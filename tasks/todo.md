# S08 — Batteries conversationnelles + release gate

Scope (phase S08, zone `evals/**` + `scripts/**` + tests — NE PAS toucher la façade S9).

## Design decisions (adaptées d'agent-usa)
- **Driving = in-process** `InMemoryRunner(root_agent)` (pattern `measure_ttft_local.py`),
  one ADK session per scenario (turns share continuity). Justification : garde S08 HORS
  de la zone façade S9 (le HTTP `/v3/chat`+SSE est S9) ; capture du budget propre (log
  handler, pas de scraping de fichier) ; état de profil auto-contenu via fakeredis injecté
  (pas de serveur Redis requis). "Live" = LLM réel (triage/synthèse/juge), pas "sur le réseau".
- **Judge = LLM-as-judge via LiteLLM** (invariant LiteLLM, PAS de SDK direct — le juge
  d'agent-usa mélangeait client OpenAI + shape Anthropic, bug corrigé ici), temperature 0,
  sortie JSON `{verdict, score 1-5, reasoning, red_flags}`, jugée contre le `expected` du
  scénario + ancres par famille. Modèle configurable (`RELEASE_GATE_JUDGE_MODEL`, déf gpt-4o-mini).
- **Budget = zéro-tolérance** : le compteur `llm_calls` de S02 (log `concierge_metric=turn`)
  capturé par tour ; tout tour > 3 = gate rouge (ship-blocking).
- **"Gate verte" = pas de régression vs baseline** (pas "32/32 passent") — modèle agent-usa
  (`min_passed - tolerance`). Baselines posées via `--update-baseline` uniquement.

## Steps
- [ ] `evals/judge.py` — LLMJudge (litellm, JSON, temp 0, par-famille via `expected`)
- [ ] `evals/battery.py` — chargement scénarios (evalset-v0.json), driving in-process,
      capture budget/tour, fakeredis, agrégation par famille → results dict
- [ ] `scripts/run_dynamic_conversation_regression.py` — CLI battery, écrit un report JSON
- [ ] `scripts/run_release_gate.py` — gate : units (pytest) + budget + battery vs baseline,
      `--quick`, `--update-baseline`, exit 1 = don't merge
- [ ] `evals/baselines.json` — posées par un run `--update-baseline`
- [ ] `evals/tests/test_*.py` — tests OFFLINE (mock litellm) : parsing juge, parsing budget,
      agrégation, logique de comparaison baseline + exit code
- [ ] `pytest.ini` — ajouter `evals` aux testpaths/pythonpath (additif)
- [ ] `.gitignore` — `evals/reports/`

## DoD (exécutable)
- [ ] `python scripts/run_release_gate.py --quick`  (units + budget, offline)
- [ ] `python scripts/run_release_gate.py`           (gate complète verte sur 32 scénarios)
- [ ] `.venv/bin/pytest -q` vert ; `ruff check .` OK ; guardrails OK

## Review
- Harness livré : `evals/{judge,battery}.py` + `evals/tests/` (26 tests offline) +
  `scripts/run_{dynamic_conversation_regression,release_gate}.py` + `evals/baselines.json`.
- Driving in-process (justifié : hors zone façade S9, budget capté proprement, fakeredis
  auto-contenu). Juge via LiteLLM (bug OpenAI/Anthropic d'agent-usa corrigé), rubrique par famille.
- **Budget vérifié sur toute la batterie : 0 tour au-dessus de 3 LLM/tour** (invariant dur, gate ship-blocking).
- DoD verte : `--quick` PASS, gate complet PASS (3/32, 0 over-budget, no regression),
  pytest 352, ruff, mypy 30, guardrails.
- Découverte live : baseline basse (3/32) HONNÊTE — dominée par le token Mapbox (ajouté par Fabien
  en session, 1/32→3/32) + inventaire ES staging partiel (caveat S10, re-poser en S10 vs ES prod).
- Détail complet dans le bloc HANDOFF daté 2026-07-20.
