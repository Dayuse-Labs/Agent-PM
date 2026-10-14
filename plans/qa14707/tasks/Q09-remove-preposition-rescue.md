---
id: Q09
title: "Removal: city rescue by preposition, `pending_place` text matching"
phase: 4
model: sonnet
model_reason: "Source plan's model, kept: a bounded removal, replaced by code already delivered in phases 2 and 3."
effort: medium
depends_on: [Q08]
parallel_batch: 4A
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/hotel_search_agent/response_bridge.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2, H1, H3]
context_budget: 30%
token_estimate: 1.6M
max_turns: 40
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "`git grep -n -e _CITY_AFTER_PREPOSITION_RE -e _city_named_in_message -e _complete_pending_place -- agents libs` returns nothing, and `_ARTICLES` is gone from `geocode_tool.py` (diff)."
  - "The leaf no longer writes `pending_place`: neither `geocode_tool.py` nor `response_bridge.py` (diff)."
  - "The assertions of the tests \"St Paul's à Londres\" and \"champs élysées\" pass without change; only their inputs move to a `GeoIntent`."
  - "The Manhattan → \"New York\" behaviour is covered by a test through the `GeoIntent` path. The tests of the removed mechanism (`test_geocode_tool.py:415-418`, `:782-803`, which assert on `pending_place`) are deleted and listed in the report."
  - "No new regex or word list in the diff."
  - "If the leaf reads `query_params.clarification`, it validates the value with `Clarification.model_validate` and ignores an off-contract one. A test covers a valid and an off-contract value."
---

## Launch prompt
You carry out Q09 on the branch task/Q09. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **`geocode_tool.py:230-270`** (`fc5cbd9`, on `main`): `_CITY_AFTER_PREPOSITION_RE`, `_ARTICLES` and `_city_named_in_message`, with up to 3 probes. Run on Raphael's cases, it fails on all three:
  - A: "room in" is swallowed, and "paris" is never tried;
  - B: only "Boulevard de" and "Boulevard" are tried;
  - C: nothing is captured.
- **`pending_place`** is written by the leaf on a homonym (`geocode_tool.py:771`) and relayed by `response_bridge.py:1637-1638` into `profile_delta`. It is then read back from `profile_in` by `_complete_pending_place` (`:944-968`, called at `:1003`), which matches exact words between the answer and the options, so « Pari » fails.
- **Replacements**:
  - `city.mention` / `city.canonical` of the `GeoIntent` (Q07);
  - the answer to a `Clarification` by option index (Q05);
  - the city the leaf extracts from the answer (Q04 + Q07).

  Since Q03, the homonym options travel in the `Clarification`, not in `pending_place`.
- **Line numbers** are those of `main`, before phases 2 and 3: search by name.

## Implementation notes
- Delete `_CITY_AFTER_PREPOSITION_RE`, `_ARTICLES`, `_city_named_in_message` and the call to it.
- Delete `_complete_pending_place` and the leaf's writing of `pending_place`, in `geocode_tool.py` and in `response_bridge.py`.
  - A homonym option is chosen by index (Q05), or by the city the leaf extracts from the answer.
  - Q11 starts once this task is merged, and removes the field on the concierge side (`profile.py:280/343/773`, `agent.py:1714-1715`).
- The tests of `fc5cbd9` (« près de St Paul's à Londres », « autour des champs élysées ») stay the **specification**. They must pass through the new path: adapt their inputs (a `GeoIntent`), never their assertions.
- For Manhattan → « New York », the behaviour is the specification, not the mechanism: the answer « New York » must lead to Manhattan in New York through the `GeoIntent`.

## Out of scope
- The other language rules of `geo_guards.py` (generic words, state read from the text, exonyms): S-L7.
- The concierge's `pending_place` field (Q11).
