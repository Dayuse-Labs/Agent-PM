---
id: Q26
title: "A bare postcode is searched around its centroid, not across its whole city"
phase: 3
model: sonnet
model_reason: "One origin type in one branch of geocode_core, plus offline tests on the H5 fixtures; the radius rule (S4) already exists."
effort: medium
depends_on: [Q25]
parallel_batch: 3M
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/tests/test_postcode_origin_radius.py
  - agents/hotel_search_agent/tests/test_postcode_resolution.py
resources: []
prerequisites: [E2, H5]
context_budget: 30%
token_estimate: 1.0M
max_turns: 40
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests tests/test_leaf_concierge_seam.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test reproducing H3' on gpt-6-luna (`qa14707-postcode-only-fr` « un hôtel dans le 75009 demain après-midi », run `h3-2026-10-15-luna-plan-r3`: geocoding correct, origin « 75009, Paris, France » type `city_centroid`, so `search_offers` ran with the city-wide radius and returned hotels at 3.3 km, 6.4 km and in Gennevilliers): through the real `geocode_location` FunctionTool with the H5 fixture `postcode_75009.json` (Mapbox mocked), a GeoIntent with `postal_code` 75009 and no zone returns `distance_origin_type` \"poi\", and `inject_landmark_radius` then gives `search_offers` the site ring (`site_radius_km`, sized by inventory density) and `sort=distance` around the 75009 centroid, as for a POI. The test drives the tool through `FunctionTool(geocode_location).run_async(args=..., tool_context=...)`, as `test_postcode_resolution.py` does, not by calling the Python function. On the parent commit the origin type is `city_centroid` and no ring is injected: the report quotes the failing assertions and the observed values of that run."
  - "Negative controls, unchanged behaviour: an address with its postcode (Q08, `address_2_bd_poissonniere_75009.json`) keeps its own `poi` origin on the address; a city alone keeps `city_centroid`; the follow-up turn after a bare postcode still persists the city only, with no zone (Q08/Q10 persistence tests pass without change to their assertions). One exception: in `test_postcode_resolution.py`, `test_a_bare_postcode_is_searched_around_its_centroid_with_no_zone` asserted the origin type `city_centroid`, which is the bug this task fixes; that one assertion becomes \"poi\", and its zone-persistence assertions stay unchanged."
  - "Rural or wide postcodes: the report states, with file:line, what happens when the 3 km disc returns no offer (the existing empty-result widening, if any, or the `no_offers` path), and a test pins that a bare postcode with 0 offers in 3 km is not a silent empty answer (it widens, or the reply says no hotel near that postcode, as the existing code does for a POI)."
  - "The H5 fixtures `postcode_13001_marseille.json` and `postcode_11580.json` (DQ8 tie-breaks) pass through the same branch with a `poi` origin, and the DQ8 and Q16 tests (`test_postcode_resolution.py`) pass without change to their assertions, apart from the one origin-type assertion named above."
  - "`MAX_LLM_CALLS_PER_TURN` is unchanged, no Mapbox or MCP call is added, and the diff adds no regex or word list."
  - "Every docstring added or changed in the tests says what the file really does (a copied harness reading the same H5 fixtures is described as a copy)."
---

## Launch prompt
You carry out Q26 on the branch task/Q26. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, DQ8, the Q08, Q16 and H3 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- H3' on gpt-6-luna (2026-10-15) passed except `qa14707-postcode-only-fr` 2/3: in all 3 runs the geocoding was identical and correct (origin « 75009, Paris, France », 48.875676, 2.343131, type `city_centroid`, country FR); run 3 failed `hotels_within_km` (3 km) because the search ran with the city-wide radius and the inventory ranking surfaced hotels 3.3 km, 6.4 km away and in Gennevilliers.
- `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`, the bare-postcode branch of `geocode_core` (search `« dans le 75009 »: the postcode is the place`): it returns `distance_origin_type="city_centroid"`.
- The S4 radius rule (same file, search `S4 (2026-08-26)`): `inject_landmark_radius` tightens the `search_offers` disc to 3 km only when the origin type is \"poi\".
- `response_bridge.py` (search `distance_origin_type") or "city_centroid"`) carries the type into `active_filters.distance_origin`.
- H5 fixtures: `agents/hotel_search_agent/tests/fixtures/mapbox_v6/postcode_75009.json`, `postcode_13001_marseille.json`, `postcode_11580.json`, `address_2_bd_poissonniere_75009.json`.

## Implementation notes
1. A bare postcode names a small area the user chose: search around its centroid like a POI (3 km), not across the city. Keep the city in the profile delta and persist no zone, as Q08 decided.
2. Do not change the address branch, the city branch or the DQ8 tie-breaks.
3. **Live proof:** a later replay of `qa14707-postcode-only-fr` (not required for this task's merge).

## Out of scope
- The radius values themselves (3 km POI disc, city radius).
- Any change to the follow-up-turn persistence (Q10 pins it).
