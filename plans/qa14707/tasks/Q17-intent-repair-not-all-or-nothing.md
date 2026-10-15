---
id: Q17
title: "A malformed GeoIntent field no longer voids the whole intent"
phase: 3
model: opus
model_reason: "Changes how the leaf's central tool degrades on model output, and the meaning of a metric that H3 reads."
effort: high
depends_on: [Q16]
parallel_batch: 3E
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2]
context_budget: 35%
token_estimate: 1.6M
max_turns: 50
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests tests/test_mcp_contract.py tests/test_leaf_concierge_seam.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test reproducing H3 (`qa14707-versailles-address-fr`, plan-r2 trace 1dc8ced4548bd034a88c8f591e076436), core spied: the real `geocode_location` FunctionTool, input text « Trouve moi une chambre à Boulevard de la République Versailles pour 13h demain », intent exactly as recorded `{places: [{mention: Boulevard de la République, kind: street, canonical: Boulevard de la République, city: Versailles}], city: Versailles}` (the intent-level `city` is a bare string). `geocode_core` receives zone `Boulevard de la République`, zone_kind `street` and city `Versailles`. On the parent commit the same test gets zone None and city empty (the report quotes that failing run)."
  - "Test reproducing H3 (`qa14707-gare-du-nord-en` plan-r1, trace 79eea59799c55c6da69d39dfcc055b77): text « I want a room in paris Gare du nord for 10 am tomorrow », intent `{places: [{mention: Gare du nord, kind: station, canonical: Gare du Nord}], city: Paris}` -> the core receives zone `Gare du Nord` and city `Paris`; no city question."
  - "Negative control (guard kept): text « un hôtel près de la Gare du Nord demain », intent with the bare-string city `Paris`. The repaired city is not in the text, so it is dropped by the existing anchoring rule, and the tool returns the city_needed question (`geocode_city_needed`), Mapbox mocked and never called."
  - "Test: a place whose `kind` is outside the closed enum (H3's `date`, the probe's `postal_code`) is dropped alone; the other place of the same intent is kept and mapped. The recorded `ds-clarify-keeps-date-monaco` intent (two places of kind `date`) maps to no zone and no city."
  - "`TestAnInvalidIntentDegrades` and `test_adk_passes_the_raw_dict_and_the_tool_copes` (test_geo_intent_mapping.py) pass without change to their assertions: three places, an extra key such as `latitude`, and a bare-string intent are still never salvaged."
  - "The `dayuse_metric=geo_intent` line keeps `valid` = whether the model's raw intent validated, and gains `repaired=N` (the count of repairs applied). A test checks the counts and that no word of the message appears on the line."
  - "The repair runs inside the tool, before `GeoIntent.model_validate`. `libs/b2c_common/b2c_common/geo_intent.py` and `contracts/geo_intent.schema.json` are unchanged (diff), so the declaration the model reads is unchanged."
  - "`MAX_LLM_CALLS_PER_TURN` is unchanged, and the diff adds no regex or word list."
---

## Launch prompt
You carry out Q17 on the branch task/Q17. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, DQ6, the Q06, Q07 and Q14 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Measured (H3, 2026-10-15).** 31 of the 220 plan `geocode_location` calls (14%) fail `GeoIntent` validation and run on an empty intent: 29 because `intent.city` is a bare string (`"city": "Versailles"`) instead of a `CityRef` object, 1 of them also with an extra key `country`, and 2 with `places[].kind = "date"`. This is the only cause of `qa14707-versailles-address-fr` 0/3 at the leaf's input, of `gare-du-nord-en` and `answer-city-en` 2 red runs each, of `geo-poi-generic-airport-with-city` 0/3 and of `geo7-marais` 2/3. Source: `scratchpad/h3-diagnosis.md` RC3, offline replay `scratchpad/h3/replay_map.py`.
- **Why the model does it.** `GeoIntent.city` is a `CityRef` (`libs/b2c_common/b2c_common/geo_intent.py:197`) while `Place.city` is a string (`:105`), and the prompt says "The city the user NAMES always goes in `city`" (`agents/hotel_search_agent/hotel_search_agent/agent.py:168`).
- **Where.** `_valid_intent` (`geocode_tool.py:1414-1431`) is all-or-nothing. `_Claims.anchored` (`:1385-1391`): a `CityRef` with an empty mention is kept only if its canonical is in the text. `geocode_location` logs the metric line (`:1609-1621`).
- ADK 2.4 hands a failed conversion over as the raw dict (Q06/Q07 entries); the tool already validates it.

## Implementation notes
1. Before validating, on a raw dict only, apply exactly two repairs:
   - a bare-string intent-level `city` becomes `{"canonical": <the string>, "mention": ""}`, which the existing anchoring rule then checks against the text;
   - a place whose `kind` is not in `PlaceKind` is removed from `places`.
   Then validate. Anything else that fails stays all-or-nothing, as today.
2. Count each repair; `valid` keeps its meaning (the raw intent validated or not).
3. Don't touch `geo_intent.py` or the prompt: Q23 owns the schema and wording, and only once the leaf model is decided (DQ11).
4. **Live proof:** H3' (re-run). The offline tests prove the mapping. The H3 numbers show how often the shape occurs: 29 of 220 calls on gpt-4o-mini, 0 of 45 probe calls on gpt-6-luna.

## Out of scope
- GeoIntent keys the model writes at the top level of the tool arguments (87/220 calls; ADK drops them before the tool runs). Not proposed: gpt-6-luna does not do it in the probe.
- Mention anchoring tolerance (Q18).
