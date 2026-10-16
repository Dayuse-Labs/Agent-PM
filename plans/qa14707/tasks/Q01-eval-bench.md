---
id: Q01
title: Proof bench — QA14707 eval set, evaluators and multi-turn replay
phase: 1
model: sonnet
model_reason: "Source plan's model, kept: cases and evaluators on an existing format (OBS6) plus a bounded harness extension (DQ4), no architecture design."
effort: high
depends_on: []
parallel_batch: 1A
owned_files:
  - evals/datasets/b2c-qa-14707-2026-10-14.jsonl
  - evals/datasets/README.md
  - evals/langfuse_evaluators.py
  - evals/langfuse_experiment.py
  - evals/tests/test_langfuse_evaluators.py
  - evals/tests/test_langfuse_experiment.py
  - scripts/langfuse_seed_datasets.py
resources: []
prerequisites: [E2]
context_budget: 35%
token_estimate: 2.7M
max_turns: 60
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/python scripts/langfuse_seed_datasets.py --dry-run"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "`evals/datasets/b2c-qa-14707-2026-10-14.jsonl` holds at least the 9 `target` cases and the 2 `regression_guard` cases listed below, each with `metadata.bug_ref = \"dayuse-com#14707\"`."
  - "The set is registered in `DATASET_NAMES` of `scripts/langfuse_seed_datasets.py`, and `--dry-run` validates it (7 files counted instead of 6)."
  - "Offline test in `evals/tests/test_langfuse_experiment.py`: an item whose `input.messages` holds two user turns posts both turns, in order, on the same session, and evaluates the reply to the last one."
  - "Offline test: the tool facts extracted from fake trace observations (result of `geocode_location`, calls to `generate_booking_link` / `find_hotel_by_name`) are scoped to the last turn."
  - "Each new evaluator has at least one passing test and one failing test in `evals/tests/test_langfuse_evaluators.py`."
  - "The tool facts are keyed on the exact observation names: `mcp-generate_booking_link`, `mcp-find_hotel_by_name`, and the ADK TOOL span `geocode_location`. A test shows that a fake observation under another name (e.g. bare `generate_booking_link`) doesn't count as a call."
  - "`evals/datasets/README.md` documents each new assertion and the multi-turn replay semantics."
---

## Launch prompt
You carry out Q01 on the branch task/Q01. Read DISCOVERY.md and HANDOFF.md
of the plan first (decision DQ4), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- `phases/QA14707/DIAGNOSTIC.md`: Raphael's cases A, B and C, and the traces.
- `evals/datasets/README.md`: the OBS6 format, the assertion vocabulary, and `target` / `regression_guard`.
- `evals/datasets/b2c-dialogue-state.jsonl`: multi-turn examples, which carry an empty profile today.
- `evals/langfuse_evaluators.py`:
  - `response_evaluator`;
  - the existing evaluators `clarify_expected`, `must_ask_city`, `hotels_within_km`, `resolved_country_code`, `active_filters_include` and `offers_on_date`;
  - the `trace.*` assertions;
  - `_RESPONSE_CHECKS` `:392-411` and `_TRACE_CHECKS` `:487-492`.
- `evals/langfuse_experiment.py`:
  - `_last_user_message` `:77-81`;
  - `_derive_route` `:128-140`;
  - trace facts `:146-226`;
  - `task` `:234`.
- Decision **DQ4** in the plan's HANDOFF.

## Implementation notes
The set is the bar of the live replays: H1 (reference, before any fix) and then H3 (after phase 3). Use only synthetic sentences or Raphael's test sentences, never anything from `baseline/`.

**`target` cases** (red today):
1. `I want a room in paris Gare du nord for 10 am tomorrow` → at least one card, all ≤ 2 km from the Gare du Nord (48.8809, 2.3553), slot `10:00`, offers for tomorrow, no question.
2. The same in French: « Une chambre à Paris Gare du Nord demain à 10h ».
3. `Trouve moi une chambre à Boulevard de la République Versailles pour 13h demain` → cards ≤ 4 km from the centre of Versailles (48.8049, 2.1204), slot `13:00`, no question.
4. `Un hôtel près du 2 boulevard Poissonnière 75009 demain` → country `FR`, cards ≤ 2 km from (48.8713, 2.3467), no question.
5. `un hôtel dans le 75009 demain après-midi` → country `FR`, cards in Paris 9e (≤ 3 km from the same point).
6. `hotel near 2 boulevard Poissonnière 75009 Paris tomorrow` (no country named) → country `FR`. This case covers the latent defect "75009 read as a US ZIP".
7. Two turns: `un hôtel près de la Gare du Nord demain à 14h`, then `Pari` → cards ≤ 2 km from the Gare du Nord, slot `14:00`, offers for tomorrow.
8. Two turns: the same question, then `Je confirme` → neither `generate_booking_link` nor `find_hotel_by_name` is called in the last turn, and the reply is not the turn-1 question word for word.
9. Two turns in English: `hotel near Gare du Nord tomorrow 2pm`, then `yes, Paris` → as case 7.

**`regression_guard` cases** (green today, to keep green):
- `un hôtel près de la Gare du Nord demain` → the city is asked. Any options all come from the geocoder.
- `un hôtel à la gare de Lyon demain` → the city is asked (rule S5, HANDOFF 2026-08-26, kept by DQ6).
- Don't copy the Budapest, La Défense and `near 11580` cases: they are already in the geo sets that H1 and H3 replay.

**Harness (DQ4)**, in `evals/langfuse_experiment.py`:
- Replay every user turn of `input.messages`, in order, on one session (same conversation id), after priming `input.profile` as today, and evaluate the reply to the last turn. Keep the previous assistant reply available to the evaluators, for case 8.
- Extract from the trace:
  - the result of `geocode_location` (ok/error, `geocode_city_needed` / `geocode_ambiguous`, candidates);
  - the calls to `generate_booking_link` and `find_hotel_by_name`.

  The names are known (DISCOVERY, Quick map):
  - the concierge's inline calls are TOOL observations `mcp-generate_booking_link` and `mcp-find_hotel_by_name` (`inline_tools.py:106`);
  - the leaf's tools are ADK `execute_tool` spans, a TOOL observation named after the tool (`geocode_location`), as `langfuse_experiment.py:177` already does for `search_offers`.

  The harness reads every trace of the session (`:165-176`), one trace per turn since OBS4: scope the facts to the last turn's trace. An evaluator keyed on a wrong name would stay green forever, so the fake observations of the tests use these exact names.
- Don't assert case 8 on `_derive_route`. It deduces the route from the triage family, and after Q05 a turn triaged `booking` can be routed to search. Assert on the tool facts.

**Evaluators**: add only the missing ones, each with its tests. Leads:
- "no question before the search": cards, and no clarify;
- "tool not called in the last turn";
- "question options ⊆ geocoder candidates": it reads the `geocode_location` fact;
- "the reply is not the previous assistant question word for word".

Document each new assertion in the vocabulary of `evals/datasets/README.md`.

## Out of scope
- Running the live replay: that is H1 and H3, done by Fabien, because they cost OpenAI, Mapbox and MCP calls.
- Touching `agents/**`. If a fact the evaluators need is missing from the traces, note it in the report as a finding for Q04/Q05.
