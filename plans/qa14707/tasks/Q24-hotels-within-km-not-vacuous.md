---
id: Q24
title: "`hotels_within_km` no longer passes on an empty hotel list"
phase: 3
model: sonnet
model_reason: "One evaluator and its tests, in eval code only."
effort: low
depends_on: []
parallel_batch: 3E
owned_files:
  - evals/langfuse_evaluators.py
  - evals/tests/test_langfuse_evaluators.py
  - evals/datasets/b2c-qa-14707-2026-10-14.jsonl
resources: []
prerequisites: [E2, DQ12]
context_budget: 20%
token_estimate: 0.8M
max_turns: 30
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/python scripts/langfuse_seed_datasets.py --dry-run"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q evals/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test reproducing H3's artefact: a response with `hotels: []` (and with `hotels: null`) on an item expecting `hotels_within_km` scores `skipped`, never 1. On the parent commit it scores 1 with the comment 'all 0 hotels within radius' (the report quotes that run)."
  - "Negative controls: one hotel outside the radius scores 0; all hotels inside score 1; a hotel without coordinates scores 0, as today."
  - "The report gives, from the stored H1/H3 run outputs (`scratchpad/h3/runs.json` or the Langfuse experiment traces), the re-scored `hotels_within_km` of geo-poi, geo-class and qa14707 for both builds, so that H3' compares like with like (geo-class today: main 2 real passes, plan 0, plus 11 vacuous plan passes)."
  - "No other evaluator changes; the evaluator names the release gate and H1/H3 read are unchanged."
  - "DQ12: the item `qa14707-guard-gare-du-nord-asks-city-fr` (same id, so the seed upsert replaces the hosted item) no longer expects the city question for a bare « Gare du Nord »: it expects a search near Gare du Nord, Paris, with the same expectations as `geo-poi-gare-du-nord` in `evals/datasets/b2c-geo-poi.jsonl` (clarify_expected false, the same hotels_within_km and min_hotels), and its notes cite DQ12. `qa14707-guard-gare-de-lyon-asks-city-fr` (S5, DQ6) is unchanged."
  - "`scripts/langfuse_seed_datasets.py --dry-run` validates every dataset file."
---

## Launch prompt
You carry out Q24 on the branch task/Q24. Read DISCOVERY.md and HANDOFF.md
of the plan first (the Q01 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- `_eval_hotels_within_km` (`evals/langfuse_evaluators.py:108-124`) loops over the hotels and passes when none is outside the radius, so 0 hotels passes.
  - H3 geo-class: 11 of 11 plan passes had 0 hotels, which turned "33% -> 92%" into an artefact.
  - geo-poi: 42 of 48 plan passes had 0 hotels; qa14707: 14 of 24.
- The skip helper and its use for a clarify-only turn already exist (`_eval_if_resolved_country_code`, `:141-150`).

## Implementation notes
1. Return `_skip("hotels_within_km", ...)` when there is no hotel. `min_hotels` already scores the absence.
2. **No live proof needed.** Re-scoring the stored outputs is enough, and the next H3' run uses the fixed evaluator for both builds.

## Out of scope
