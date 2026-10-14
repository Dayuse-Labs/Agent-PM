---
id: Q08
title: Address and postcode resolved by the geocoder
phase: 3
model: opus
model_reason: "Source plan's model, kept: geo policy, with cases to keep (US ZIP, homonyms)."
effort: high
depends_on: [Q07]
parallel_batch: 3B
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/mapbox_client.py
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/hotel_search_agent/geo_resolver.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2, H5]
context_budget: 40%
token_estimate: 3.1M
max_turns: 60
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test on the real Mapbox v6 fixture recorded by H5 (`agents/hotel_search_agent/tests/fixtures/mapbox_v6/`): `GeoIntent(places=[address \"2 boulevard Poissonnière\", postal_code \"75009\"])` gives city Paris (`context.place`), and no question."
  - "Test: a candidate whose `context.postcode` differs from the extracted code is refused."
  - "Test (DQ8): with no country named, no Mapbox call carries a `country` filter; with `country_named`, the filter is that country."
  - "Test (DQ8): among candidates with the same postcode in two countries (75009 Paris FR and 75009 Celina US), the LLM's guess decides, then the market. \"2 boulevard Poissonnière 75009 Paris\" with no country named and an en/USD market is never searched in the United States."
  - "Test: \"Gare du Nord\" with neither city nor postcode still gives the city_needed question."
  - "Test: the existing case \"near 11580\" (prod US ZIP bug) keeps its behaviour."
  - "No new regex or word list in the diff."
---

## Launch prompt
You carry out Q08 on the branch task/Q08. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, DQ8, DQ9), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Trace C.** « Un hôtel près du 2 boulevard Poissonnière 75009 demain » gives `zone="2 boulevard Poissonnière"`, the postcode is thrown away, and the city_needed question follows.
- **Latent defect, proven offline.** `select_us_postal_anchor` (`geo_guards.py:458`) reads `75009` and `13001` as US ZIP codes. `geocode_tool.py:671-675` then forces `country_code="US"` when no country is given. 75009 is also a real US ZIP (Celina, TX).
- **`mapbox_client.py`** uses Geocoding v6 (`GEOCODE_URL`, `:29`).
  - It reads `context.country` and `context.region` (`:229-264`), but not `context.postcode` or `context.place`.
  - `match_code` and `confidence` exist only for an address (`:15-17`).
- **Fixtures**: real v6 responses recorded by Fabien (H5, DQ9) in `agents/hotel_search_agent/tests/fixtures/mapbox_v6/`, for `2 boulevard Poissonnière 75009`, `75009`, `13001 marseille` and `11580`. Build the tests on them. Don't fabricate a v6 shape they don't show; if one is missing, finish `blocked`.
- **From Q07**: `geocode_location` receives a `GeoIntent` (with `places[].postal_code` and `places[].country`), and maps it before calling the internal core.

## Implementation notes
1. **Reading.** `mapbox_client` also reads `context.postcode` and `context.place` on the candidates, plus `match_code` for an address.
2. **Country (DQ8).**
   - Only `country_named` is a hard `country` filter.
   - With no country named, geocode without a filter, and keep only the candidates whose `context.postcode` equals the extracted `postal_code`: an equality of structured fields, no regex.
   - Among those, the LLM's guess (`places[].country`) breaks ties first, then the market's country. The guess is never a filter.
3. **Address or street with a `postal_code`.** Geocode the full mention with its postcode, with the address and street types. The accepted candidate gives the city (`context.place`), the zone is the address, and there is no question.
4. **Postcode alone** (« dans le 75009 »). Geocode with the postcode type, under the same country rule; the city is `context.place`.
5. **`city_needed`.** A city obtained this way counts as a city for triggering `city_needed`: the postcode is enough. Make no other change to the `city_needed` rule: « Gare du Nord » alone still asks the question.
6. **`select_us_postal_anchor`** stays in place during this phase; Q10 removes it (DQ7). Don't make things worse: when the `GeoIntent` carries a `postal_code`, the rule above wins over the anchor.

## Out of scope
- Removing `select_us_postal_anchor` (Q10).
- Changing the `city_needed` rule beyond the postcode.
- Calling Mapbox: no live call, no `.env`.
