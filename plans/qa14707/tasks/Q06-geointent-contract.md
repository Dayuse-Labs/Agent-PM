---
id: Q06
title: "`GeoIntent` v1.1 contract and offline ADK proof"
phase: 2
model: opus
model_reason: "Source plan's model, kept: contract design; takes over S-L2 with the additions Raphael's reports require (plus DQ5)."
effort: high
depends_on: []
parallel_batch: 2A
owned_files:
  - libs/b2c_common/b2c_common/geo_intent.py
  - libs/b2c_common/tests/test_geo_intent.py
  - contracts/geo_intent.schema.json
  - tests/test_geo_intent_contract.py
  - libs/b2c_common/pyproject.toml
resources: []
prerequisites: [E2]
context_budget: 30%
token_estimate: 2.0M
max_turns: 50
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q tests/test_geo_intent_contract.py libs/b2c_common/tests/test_geo_intent.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "`geo_intent.py` exists and follows §3 of the S-L plan, plus `postal_code` and the `mention` / `canonical` semantics. `ambiguity` holds only `reason` (DQ5)."
  - "A test proves the model has no coordinate field."
  - "A test proves `ambiguity` has no `options`."
  - "`contracts/geo_intent.schema.json` is identical to the generated schema (test)."
  - "Offline tests prove the 4 ADK properties of point 4. If one fails, the report ends `blocked` and describes the failure: DQ1 would have to be revisited."
  - "`libs/b2c_common/b2c_common/__init__.py` is untouched (Q03 runs in parallel)."
  - "`libs/b2c_common/pyproject.toml` declares `pydantic` (diff)."
---

## Launch prompt
You carry out Q06 on the branch task/Q06. Read DISCOVERY.md and HANDOFF.md
of the plan first (decisions DQ1, DQ5, DQ6), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **The contract to follow**:
  - `reports/PLAN-LEAF-GEO-2026-10-08.md` §3 holds the `GeoIntent` v1 contract and its mapping to `geocode_location`;
  - the contract part of `phases/SL2-contrat-geointent-evals.md`.
- **Decisions** in the plan's HANDOFF:
  - **DQ1**: the current search leaf will fill this object, as an argument of `geocode_location` (Q07).
  - **DQ5**: `ambiguity` without `options`.
  - **DQ6**: `ambiguity.reason = "city_needed"` carries the S5 rule.
- **ADK 2.4**:
  - builds the declaration of a pydantic parameter (`.venv/lib/python3.12/site-packages/google/adk/tools/_function_parameter_parse_util.py:169-178`, `:496-497`);
  - converts the arguments back with `model_validate` (`google/adk/tools/function_tool.py:173-182`);
  - hands the declaration to LiteLLM (`google/adk/models/lite_llm.py`).
- **Pitfall** (DISCOVERY): a parameter without a default is rejected before the function runs.

## Implementation notes
1. **Model** `GeoIntent`, following §3 of the plan.
   - Fields: `schema_version`, `places[]` (at most 2, each `{mention, kind, canonical, city, region, country, city_inferred}`), `city`, `country_named`, `region_named`, `relation`, `carryover`, `exclusions[]`, `ambiguity`.
   - Closed enumerations, `extra="forbid"`, **no coordinate**, a default on every field.
   - Import it as a submodule (`b2c_common.geo_intent`), without touching `__init__.py`.
2. **Additions** (version `"1.1"`), justified by `DIAGNOSTIC.md` and by the decisions:
   - `places[].postal_code`: the postcode as written. In trace C it was thrown away.
   - Explicit `mention` and `canonical` semantics, for `city` too. `mention` is the user's exact text. `canonical` is the name normalized by the LLM (« Pari » → « Paris », « paris » → « Paris »). The code will check that the `mention` is anchored in the message and that `canonical` is real (Q07).
   - `ambiguity: null | {reason ∈ homonym | city_needed | too_vague}`, **without `options`** (DQ5).
3. **Field descriptions.** They end up in the tool declaration the LLM reads, so they are part of the prompt. Write them for gpt-4o-mini, and keep them short. Two rules belong in them:
   - `places[].city` (with `city_inferred=true` when the user didn't write it): the city the place is in, **only when the place's name leaves no doubt** ("les champs élysées" → Paris). Null when a place of that name exists in several cities ("Gare du Nord": Paris, Brussels). That is today's prompt rule (`hotel_search_agent/agent.py:164-172`, `:189-190`), moved, not changed: Q07 maps `places[0].city` to `city` as today.
   - `ambiguity.reason = "city_needed"` (DQ6): a place named after a city it is not in, e.g. gare de Lyon in Paris.
   - Declare `pydantic` in `libs/b2c_common/pyproject.toml`: these are the first pydantic models of the package.
4. **Snapshot** `contracts/geo_intent.schema.json`, generated from the model. `tests/test_geo_intent_contract.py` checks they don't diverge.
5. **Offline ADK proof**: build a `FunctionTool` whose parameter is a `GeoIntent`, and prove four properties:
   - the declaration builds, with the nested object and the enumerations;
   - the LiteLLM conversion produces a valid tool schema;
   - a call with `dict` arguments arrives in the function as a `GeoIntent`;
   - a call without the argument, or with a partial one, is not rejected before the function.

## Out of scope
- Wiring the contract into the leaf (Q07).
- The eval sets of S-L2: this plan's end-to-end set is Q01.
- `contracts/mcp_b2c_tools.json`: only `scripts/refresh_mcp_contract.py`, run by a human, writes it.
