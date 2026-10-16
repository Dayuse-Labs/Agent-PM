---
id: Q29
title: "Live eval item for « near 11580 » without a named country"
phase: 5
model: sonnet
model_reason: "One dataset item and its offline test, in eval files only; not purely mechanical because the item must test the DQ8 path without a named country."
effort: low
depends_on: []
parallel_batch: 5A
owned_files:
  - evals/datasets/b2c-qa-14707-2026-10-14.jsonl
  - evals/datasets/README.md
  - evals/tests/test_qa14707_near_11580_item.py
resources: []
prerequisites: [E2, DQ7, DQ8]
context_budget: 20%
token_estimate: 0.5M
max_turns: 25
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/python scripts/langfuse_seed_datasets.py --dry-run"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q evals/tests/test_qa14707_near_11580_item.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q evals/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "`evals/datasets/b2c-qa-14707-2026-10-14.jsonl` has one new item `qa14707-near-11580-en`: a single English user message that contains the bare ZIP « 11580 » and names no country or US state (for example « a hotel near 11580 tomorrow »), `profile: {}`, `expected_output` with `resolved_country_code: \"US\"`, and `metadata` with `family: \"qa14707\"`, `locale: \"en\"`, `status: \"regression_guard\"` and notes that cite the prod bug « near 11580 », DQ7 and DQ8 (no named country, the model's guess decides; the harness sends no market)."
  - "The 11 existing items of that file are byte-for-byte unchanged (diff)."
  - "Test `evals/tests/test_qa14707_near_11580_item.py`: it loads the dataset file, finds `qa14707-near-11580-en`, and asserts that its message contains « 11580 », names neither a country nor « USA » / « US » / « United States », and that `expected_output.resolved_country_code == \"US\"`."
  - "The same test runs `_eval_resolved_country_code` from `evals/langfuse_evaluators.py` on the item's `expected_output`: a response whose active filters carry `country_code` \"US\" passes, and one with \"MX\" (Mapbox's first 11580 candidate, H5 fixture `postcode_11580.json`) fails."
  - "`evals/datasets/README.md` gives 12 items for `b2c-qa-14707-2026-10-14.jsonl`, with 3 `regression_guard`, and names the new item."
  - "`scripts/langfuse_seed_datasets.py --dry-run` validates every dataset file."
  - "No live run is made by the task: the 3/3 replay is a human step recorded in the plan's HANDOFF."
---

## Launch prompt
You carry out Q29 on the branch task/Q29. Read DISCOVERY.md and HANDOFF.md
of the plan first (DQ7, DQ8, and the Q10 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- Q10 removed the US-ZIP anchor (DQ7). For a user who names no country, « near 11580 » now stays in the United States only when the leaf extracts `postal_code`; then the model's guess or the market breaks the tie (DQ8, `_postcode_match` in agents/hotel_search_agent/hotel_search_agent/geocode_tool.py). Offline proof: `TestNear11580` and `TestNear11580OnTheEnglishMarket` in agents/hotel_search_agent/tests/test_postcode_resolution.py.
- No dataset under evals/ contains « 11580 » today, so the prod case has no live check.
- The item format and evaluators: see the existing items of `evals/datasets/b2c-qa-14707-2026-10-14.jsonl` (for example `qa14707-poissonniere-75009-no-country-en`) and `_eval_resolved_country_code` in `evals/langfuse_evaluators.py`.
- The Langfuse experiment harness sends no market (`entry_market_country`), so the live item tests the model's own guess for a bare US ZIP in English.

## Implementation notes
1. Append the item; do not reorder or reformat the existing lines.
2. Do not add `min_hotels` or `hotels_within_km`: the US inventory near Valley Stream is not known, and the item checks the country only.

## Out of scope
Any code under agents/ or libs/, the evaluators themselves, and any live run.
