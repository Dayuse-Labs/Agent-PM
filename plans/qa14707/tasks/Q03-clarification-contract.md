---
id: Q03
title: "`Clarification` contract and structured emission by the leaf"
phase: 2
model: opus
model_reason: "Source plan's model, kept: design of a contract shared by the leaf and the concierge, on a sensitive geo path."
effort: high
depends_on: []
parallel_batch: 2A
owned_files:
  - libs/b2c_common/b2c_common/clarification.py
  - libs/b2c_common/tests/test_clarification.py
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/hotel_search_agent/response_bridge.py
  - agents/hotel_search_agent/hotel_search_agent/contract.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2]
context_budget: 40%
token_estimate: 3.1M
max_turns: 60
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests libs/b2c_common/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "A test shows that a city_needed question (a `geocode_ambiguous` error with status `geocode_city_needed`, `geocode_tool.py:596-599`) brings up a `Clarification(kind=\"city_needed\", subject=\"Gare du Nord\", options=[])` in the leaf's DataPart."
  - "A test shows that a homonym brings up options that are exactly the geocoder's candidates kept by the inventory tier, and no other."
  - "A test shows that the model refuses an unknown field and holds no coordinate."
  - "The existing tests of the leaf pass without any change to their assertions."
  - "`libs/b2c_common/b2c_common/__init__.py` is untouched (Q06 runs in parallel)."
---

## Launch prompt
You carry out Q03 on the branch task/Q03. Read DISCOVERY.md and HANDOFF.md
of the plan first (decisions DQ2, DQ5), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- `phases/QA14707/DIAGNOSTIC.md` §1 describes the failure:
  - The code produces the `city_needed` question with no option.
  - The synthesis rewrites it and invents options (« Bruxelles », « Versailles (78) », « plusieurs communes »).
  - The next turn keeps only a paraphrase.
- Sources of the question:
  - `geocode_tool.py:595-610`: `geocode_city_needed`, template `geo_resolver.city_needed_question`, `options: []`;
  - `geocode_tool.py:750-780` and `:910`: homonym (`geo_resolver.py:486-525`, template `_CLARIFY_MANY`).
- The leaf already passes structured facts to the concierge, outside the text, through the same channel: `search_context` (HANDOFF 2026-10-06, mcp-dayuse#5). It is the model to follow.
- `evals/PRESERVATION.md`: the question without a city is a case to keep.

## Implementation notes
1. **`clarification.py`**: a pydantic model `Clarification`.
   - Fields: `schema_version="1"`, `kind ∈ {city_needed, homonym}`, `subject` (the place mention to clarify), and `options[]`.
   - Each option has a label, a city, a region and a `country_code`. There are at most 5 options.
   - `extra="forbid"`, and no coordinate.
   - Import it as a submodule (`b2c_common.clarification`), without touching `__init__.py`. Pydantic is already in the venv (through ADK); Q06, which runs in parallel, declares it in `libs/b2c_common/pyproject.toml`.
2. **Emission.** The leaf attaches this object to `geocode_ambiguous` and to `geocode_city_needed`, and sends it up to the concierge in its DataPart, by the same channel as `search_context`.
   - The `options` come **only** from the geocoder's candidates kept by the inventory tier, never from the LLM (DQ5).
   - `city_needed` keeps `options: []`. The question goes out before any geocoding, and that is intended (a case to keep, PRESERVATION.md).
3. **Text unchanged.** The leaf's text doesn't change, so the current concierge, which ignores the new object, keeps working. Q04 consumes it.

## Out of scope
- Rendering and persistence on the concierge side (Q04).
- Routing (Q05).
- Changing when `city_needed` fires.
