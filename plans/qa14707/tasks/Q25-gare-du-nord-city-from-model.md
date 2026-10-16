---
id: Q25
title: "A bare « Gare du Nord » gets its city from the model (DQ12): no 'several cities' null case in the GeoIntent declaration or the leaf prompt"
phase: 3
model: sonnet
model_reason: "Bounded wording change in the declaration and the leaf prompt, plus offline tests; the rule is settled by DQ12 and DQ6."
effort: medium
depends_on: [Q23]
parallel_batch: 3L
owned_files:
  - libs/b2c_common/b2c_common/geo_intent.py
  - contracts/geo_intent.schema.json
  - tests/test_geo_intent_contract.py
  - agents/hotel_search_agent/hotel_search_agent/agent.py
  - agents/hotel_search_agent/tests/test_agent.py
  - agents/hotel_search_agent/tests/test_gare_du_nord_city_from_model.py
resources: []
prerequisites: [E2, DQ6, DQ11, DQ12]
context_budget: 30%
token_estimate: 1.2M
max_turns: 40
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests/test_gare_du_nord_city_from_model.py agents/hotel_search_agent/tests/test_geo_intent_field_order.py agents/hotel_search_agent/tests/test_agent.py tests/test_geo_intent_contract.py libs/b2c_common/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test reproducing the cause (agents/hotel_search_agent/tests/test_gare_du_nord_city_from_model.py): through `google.adk.models.lite_llm._function_declaration_to_tool_param` on the real `geocode_location` FunctionTool, the `Place.city` description contains neither « Gare du Nord » nor a null case for places of the same name in several cities. It still contains the « gare de Lyon » null case (S5, DQ6) and the null case of a place that is itself a city. On the parent commit the test fails (the report quotes that run)."
  - "The same test file asserts that the leaf instruction (agents/hotel_search_agent/hotel_search_agent/agent.py) no longer tells the model to leave a place's city null because places of that name exist in several cities, and no longer cites « Gare du Nord » as such a case. The S5 bullet (« gare de lyon » ... `ambiguity.reason` ... \"city_needed\") is unchanged in the diff, and the existing test_agent.py assertions on the S5 bullet pass unchanged."
  - "The instruction and the description say that homonyms are decided by the tool (the geocoder), in line with DQ6. The diff adds no example city for « Gare du Nord » and no other city name the geocoder would not verify."
  - "Negative control, code unchanged: `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py` is not in the diff, and agents/hotel_search_agent/tests/test_geo_intent_field_order.py passes without change. A landmark that the model leaves without a city, with no device fix, still gets the `city_needed` question (safe fallback). « gare de Lyon » with `ambiguity.reason: city_needed` still asks."
  - "`contracts/geo_intent.schema.json` is regenerated, and its diff touches only the `Place.city` description: no field, type, enum, order or `required` change. `SCHEMA_VERSION` stays 1.1."
  - "`tests/test_geo_intent_contract.py` and `agents/hotel_search_agent/tests/test_agent.py` assert the new wording: an assertion that required « Gare du Nord » in the city description or in the prompt is replaced by one requiring its absence, and the report lists every changed assertion."
  - "`MAX_LLM_CALLS_PER_TURN` is unchanged, and the diff adds no regex or word list."
  - "The eval items `qa14707-guard-gare-du-nord-asks-city-fr` (evals/datasets/b2c-qa-14707-2026-10-14.jsonl) and `geo-poi-gare-du-nord` (evals/datasets/b2c-geo-poi.jsonl) are not touched, and the report quotes their current `clarify_expected: false` expectation (DQ12, Q24)."
---

## Launch prompt
You carry out Q25 on the branch task/Q25. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, DQ6, DQ11, DQ12, the Q23 and Q24 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- DQ12 (settled by the user on 2026-10-15): a bare « Gare du Nord » searches Paris. It is not an S5 case, `main` and prod already do it, and the QA asked for fewer city questions. The « gare de Lyon » guard (S5, DQ6) stays.
- DQ6: `homonym` and `too_vague` are read and logged, and the geocoder keeps deciding homonyms. The only LLM-side city rule is S5, through `ambiguity.reason = "city_needed"`.
- `libs/b2c_common/b2c_common/geo_intent.py:127-137`: the `Place.city` description (Q23's V1 wording). The null case « places of that name are in several cities ("Gare du Nord": Paris and Brussels) » goes.
- `agents/hotel_search_agent/hotel_search_agent/agent.py:176-183`: the bullet « A place's own `city` is your world knowledge ... Leave it null when places of that name exist in several cities ("Gare du Nord": Paris, Brussels) and the user names none: the tool then asks the user which city. » The last sentence goes. The S5 bullet (`agent.py:184-192`) stays word for word.
- The probe recorded for Q23 shows that gpt-6-luna writes `city: null` for a bare « Gare du Nord » under both the old and the V1 wording, so the bare-landmark branch (`geocode_tool.py:982-1000`) asks for the city. That branch is the safe fallback and does not change.
- Existing assertions on the old wording: `tests/test_geo_intent_contract.py:187` (`"Gare du Nord" in city`) and `agents/hotel_search_agent/tests/test_agent.py:277` (the « ("Gare du Nord": Paris, Brussels) and the user names none » line).
- Regenerate the snapshot with `python libs/b2c_common/b2c_common/geo_intent.py > contracts/geo_intent.schema.json`.

## Implementation notes
1. Wording only: the descriptions and the prompt are written for gpt-6-luna (DQ11). Keep the positive examples (Buckingham Palace, le Louvre, times square) and the city-place and S5 null cases.
2. Do not touch `geocode_tool.py`: the code keeps asking when the model gives no city and there is no device fix.
3. **Live proof:** H3' only (both DQ12 items 3/3 searched near Gare du Nord in Paris, and `qa14707-guard-gare-de-lyon-asks-city-fr` still 3/3 asked). The offline tests prove what the model reads, not what it does.

## Out of scope
- Any change to the bare-landmark branch or to Search Box proximity.
- Any change to the eval datasets (Q24 already applied DQ12).
- Any change for gpt-4o-mini.
