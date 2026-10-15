---
id: Q19
title: "A carried country is a hard filter only for the city it was carried with"
phase: 3
model: sonnet
model_reason: "One carry-over rule in the leaf, mirroring Q14's region rule, with recorded Mapbox fixtures."
effort: medium
depends_on: [Q18]
parallel_batch: 3G
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2, H6]
context_budget: 30%
token_estimate: 1.2M
max_turns: 40
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests agents/b2c_concierge/tests tests/test_leaf_concierge_seam.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test reproducing H3 (`geo-poi-multiturn-country-switch` plan-r1, trace 170d28eb4eae0642dd09cca3a0cd6e4d), Mapbox v6 served from the H6 fixtures `place_paris_gb_en.json` (country gb: 0 features) and `place_paris_en.json` (no country), Search Box mocked to return « Paris Baguette, London » for country GB: the real `geocode_location` FunctionTool, text « actually make it paris », profile_in `{city: London, country_anchor: GB, locale: en-GB}`, intent `{places: [{mention: paris, kind: city, canonical: Paris}]}`. No Mapbox call carries a `country` filter and the result is Paris, FR. On the parent commit the v6 call carries `country=gb` and the result is « Paris Baguette » GB (the report quotes that run)."
  - "Negative control: the same profile and an empty intent (a follow-up such as « moins cher ») -> the v6 call still carries `country=gb` (the anchor goes with the carried city)."
  - "Test: a new zone in the carried city (profile `{city: Paris, country_anchor: FR}`, intent `{places: [{mention: les champs élysées, kind: landmark, canonical: Champs-Élysées, city: Paris}]}`) keeps the FR filter."
  - "Test: Q05/Q14's chosen-option path keeps its country. `test_an_option_index_searches_the_city_of_that_option` (Victoria CA/US) and Q14's Springfield tests pass without change to their assertions."
  - "Q08's postcode early return and Q16's market tests pass without change to their assertions; the carried country is never turned into a soft guess for another city."
  - "`MAX_LLM_CALLS_PER_TURN` is unchanged, and the diff adds no regex or word list (the city comparison is `_comparable` equality, as for `region_anchor`)."
---

## Launch prompt
You carry out Q19 on the branch task/Q19. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, DQ8, the Q07, Q08 and Q14 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Measured (H3).** `_fill_place_from_profile` fills `country_code` from `profile_in.country_anchor` whenever the turn has none (`geocode_tool.py:1287-1288`), and `geocode_core` sends it as Mapbox's hard `country` (`:963-964`). Since Q07 the model can no longer override it: main's model sent `country_code="FR"` for « actually make it paris », and DQ8 keeps the soft guess out of the filter. The concierge's city-change wipe runs after the leaf has answered. Live core probe: `geocode_core(city="Paris", country_code="GB")` -> v6 returns nothing -> Search Box -> « Paris Baguette, … London », while the same call without the anchor -> « Paris, France ». This is a model-independent code defect (`scratchpad/h3-diagnosis.md` RC4).
- **The rule to mirror.** Q14 applies `region_anchor` only while the turn's city equals the carried city (`geocode_tool.py:1289-1295`).
- **Fixtures (H6).** `place_paris_gb_en.json` and `place_paris_en.json`, recorded on 2026-10-15 with `types=place,locality,neighborhood,district,region`, `limit=10`, `autocomplete=false`, `language=en`, with and without `country=gb`. Draft copies are in the diagnosis scratchpad (`scratchpad/h3/proposed_fixtures/`); H6 commits them under `agents/hotel_search_agent/tests/fixtures/mapbox_v6/`.

## Implementation notes
1. In `_fill_place_from_profile`, carry `country_anchor` into `country_code` only when the turn's city was blank (and is filled from the profile) or equals the carried city after `_comparable`. Otherwise leave `country_code` empty: a carried anchor for London says nothing about Paris.
2. Keep the order with `pending_place` and Q14's region rule.
3. **Live proof:** H3' (`geo-poi-multiturn-country-switch` 3/3 on `resolved_country_code`).

## Out of scope
- The concierge's city-change wipe.
- Turning a named country (`country_named`) into anything other than the hard filter.
