---
id: Q21
title: "A homonym option picked by the user is resolved without the reply's state in the query"
phase: 3
model: opus
model_reason: "Changes how Q14's region pick and the state tier interact in the leaf's core, with homonym cases to keep."
effort: high
depends_on: [Q20]
parallel_batch: 3I
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2, H6]
context_budget: 35%
token_estimate: 1.6M
max_turns: 50
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests agents/b2c_concierge/tests tests/test_leaf_concierge_seam.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test reproducing H3 (`geo7-manhattan-answer` plan-r1, trace 0fbae06a9ce3f6d01179f2954134307a), v6 served from the H6 fixtures `place_manhattan_us_fr.json` (q Manhattan) and `place_manhattan_new_york_us_fr.json` (q « Manhattan, New York »): the real `geocode_location` FunctionTool, reply text « New York », profile_in `{city: Manhattan, country_anchor: US, region_anchor: État de New York, language: fr}`, intent `{places: [{mention: Manhattan, kind: city, canonical: Manhattan}]}`. Result: ok on « Manhattan, État de New York, États-Unis » (locality); the v6 query is « Manhattan », with no state term appended. On the parent commit the same test gives `geocode_echo_mismatch` on « New York, État de New York » (the report quotes that run)."
  - "Negative control: with no `region_anchor`, a state written in the message still feeds the state tier and the query as today (the existing « Milford ct » and state-anchoring tests pass without change to their assertions)."
  - "Q14's Springfield IL/MO tests and the Victoria CA/US concierge test pass without change to their assertions."
  - "The report records, as a `decision` entry, how Q14's minor decision 'a state named this turn or anchored wins over an earlier pick' now applies: the state still steers the resolver, and no longer rewrites the query of a picked option."
  - "`MAX_LLM_CALLS_PER_TURN` is unchanged, and the diff adds no regex or word list."
---

## Launch prompt
You carry out Q21 on the branch task/Q21. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, the Q05 and Q14 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Measured (H3 + live core probe).** On the answer turn the concierge sets city = the option's city (« Manhattan »), `country_anchor` and `region_anchor`, and clears the zone (`agents/b2c_concierge/b2c_concierge/agent.py:1378-1383`). In the leaf, the reply « New York » yields a state hint (`geocode_tool.py:950-958`). The hint is appended to the query (`:960-962`) and disables the Q14 narrowing (`:969`). v6 then returns NYC, the echo of « Manhattan » fails, and with no zone there is no tier 2 (`:1148-1151`).
  - Live: the same call gives `geocode_echo_mismatch`.
  - With no state term from the reply and `region_chosen` set, it gives « Manhattan, État de New York » (locality).
  - Main's 2/3 passes went through a business POI named « Manhattan », not a correct resolution (`scratchpad/h3-diagnosis.md` RC6).
- The region in `region_anchor` is Mapbox's own localized `context.region` of the option (« État de New York » with language fr), so the narrowing compares like with like.
- **Fixtures (H6).** `place_manhattan_us_fr.json` and `place_manhattan_new_york_us_fr.json`, recorded on 2026-10-15 with `country=us`, `language=fr` and the default candidate types. Draft copies are in `scratchpad/h3/proposed_fixtures/`.

## Implementation notes
1. When `region_chosen` is set, build the query without the state term. The state hint, if any, may still go to the resolver as `region_hint`. Apply the narrowing whenever it keeps at least one candidate.
2. Leave the concierge side unchanged: the pick is already resolved from the stored `Clarification`.
3. **Live proof:** H3' (`geo7-manhattan-answer`).

## Out of scope
- The `_city_named_in_message` subject « Manhattan demain » (Q09 removes the preposition regex).
