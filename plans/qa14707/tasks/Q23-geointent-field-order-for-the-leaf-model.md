---
id: Q23
title: "GeoIntent asks the place's city and country right after its name (production leaf model)"
phase: 3
model: opus
model_reason: "Changes the frozen GeoIntent declaration the LLM reads and the leaf's prompt; guard cases at stake."
effort: high
depends_on: [Q22]
parallel_batch: 3K
owned_files:
  - libs/b2c_common/b2c_common/geo_intent.py
  - libs/b2c_common/tests/test_geo_intent.py
  - contracts/geo_intent.schema.json
  - tests/test_geo_intent_contract.py
  - agents/hotel_search_agent/hotel_search_agent/agent.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2, DQ11]
context_budget: 40%
token_estimate: 2.3M
max_turns: 60
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q libs/b2c_common/tests tests/test_geo_intent_contract.py agents/hotel_search_agent/tests tests/test_mcp_contract.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests/test_named_hotel_city_fallback.py"
definition_of_done:
  - "Test reproducing the cause measured in H3 (the declaration the model reads): through `google.adk.models.lite_llm._function_declaration_to_tool_param` on the real `geocode_location` FunctionTool, `Place` lists its properties in the order mention, kind, canonical, city, country, postal_code, region, city_inferred, and its `required` holds mention, kind, canonical, city, country and postal_code. On the parent commit, city is the 5th property, country the 7th, and `required` is absent (the report quotes that run)."
  - "Negative control: a partial dict (`{places: [{mention: x}]}`, and `{}`) still validates to a `GeoIntent` with the same defaults. The JSON-schema `required` binds only the model's output, never the tool's input, and Q06's 'a default on every field' invariant test passes without change to its assertions."
  - "Mapping tests on the recorded gpt-6-luna probe intents (copied verbatim from `scratchpad/h3/probe_out_luna-v1.json` into the test, Mapbox mocked): Buckingham Palace with `city: London` geocodes the palace in London; « dans le 75009 » with `postal_code: 75009` takes the Q08 postcode path; « Gare du Nord » with `city: null` gives the city_needed question; « gare de Lyon » with `ambiguity.reason: city_needed` gives the city_needed question; the « Pari » answer with `city: {mention: Pari, canonical: Paris}` geocodes Gare du Nord in Paris."
  - "`contracts/geo_intent.schema.json` is regenerated, and the diff shows only property order, descriptions and the `required` list (no field, type or enum change). `SCHEMA_VERSION` stays 1.1, unless the report justifies a bump as a `decision`."
  - "The leaf prompt states that a postcode the user writes goes in that place's `postal_code`, also when the postcode alone is the place (diff). The S5 bullet and the Gare du Nord example are unchanged."
  - "`MAX_LLM_CALLS_PER_TURN` is unchanged, and the diff adds no regex or word list."
  - "In agents/hotel_search_agent/tests/test_named_hotel_city_fallback.py, a test captures the real `dayuse.metrics` records (caplog, formatted message) of the Q22 not-found-in-Lyon turn, of the city-that-does-not-geocode turn, and of a found-hotel turn. It asserts that each `named_hotel_city_search` / `named_hotel_search` line is exactly `dayuse_metric=<name> agent=b2c_hotel_search status=<ok|no_place|blocked|unbound|error> ms=<integer>`, and that no word of the user's message, of the hotel name (« Bidule Imaginaire ») or of the city (« Lyon ») appears on it. A second case asserts that `named_hotel_search` reports status=unbound when no toolset is bound."
---

## Launch prompt
You carry out Q23 on the branch task/Q23. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, DQ1, DQ5, DQ6, DQ11, the Q06 and Q07 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Measured (H3).** gpt-4o-mini filled `places[].city` on 9 of 222 places and `places[].country` on 0. Every landmark without a typed city got the city question. This is RC1, 15 of the 26 `resolved_country_code` regressions on geo-poi (`scratchpad/h3-diagnosis.md`).
- **LLM-only probe** (`scratchpad/h3/probe_geointent.py`): the leaf's real instruction and the real declaration, 9 H3 messages.
  - gpt-4o-mini, today's schema: landmark city 0/25.
  - gpt-6-luna, today's schema: landmark city 25/25; the gare de Lyon question in only 2 calls out of 5.
  - gpt-6-luna, this task's schema (V1): 15/15; Gare du Nord asks 3/3; gare de Lyon `city_needed` 3/3; « Pari » 3/3; postcode extracted 3/3; 0 invalid intents.
  - gpt-4o-mini, V1: the landmark city is filled, but **both guards break** (Gare du Nord given Paris 5/5, gare de Lyon asks 0/5).
  - So this task is only for gpt-6-luna. Hence DQ11.
- `geo_intent.py` docstring: descriptions are prompt; the declaration form; why every field has a default; how to regenerate the snapshot. `tests/test_geo_intent_contract.py` holds the LiteLLM conversion proof.
- The V1 variant used in the probe is `v1()` in `scratchpad/h3/probe_geointent.py`, with exact descriptions.

## Implementation notes
1. Pydantic: put the `Place` fields in the order above, and add the `required` list to `Place`'s JSON schema (for example `json_schema_extra`) while every field keeps its default.
2. Wording: positive for `city` (from your knowledge for a well-known place) with the two null cases kept. Add `country` from knowledge, and the `postal_code` example « dans le 75009 ».
3. **Live proof:** H3' only. This task changes what the model reads. The offline tests prove the declaration and the mapping of the stronger model's shapes, not the model's behaviour.

## Out of scope
- Renaming `GeoIntent.city` (a contract change, not measured).
- Any change for gpt-4o-mini.
