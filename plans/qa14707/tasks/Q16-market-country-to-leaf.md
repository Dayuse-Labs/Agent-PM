---
id: Q16
title: "The market's country reaches the leaf's postcode tie-break"
phase: 3
model: opus
model_reason: "A data field that crosses the facade, the Redis session profile and the leaf's geocoding, in two modules."
effort: high
depends_on: [Q14]
parallel_batch: 3D
owned_files:
  - agents/b2c_concierge/b2c_concierge/facade.py
  - agents/b2c_concierge/b2c_concierge/profile.py
  - agents/b2c_concierge/tests/**
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2, H5]
context_budget: 40%
token_estimate: 2.0M
max_turns: 60
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests agents/hotel_search_agent/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q tests/test_leaf_concierge_seam.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test (facade): a request body with `entry_market_country: \"us\"` stores `US` in the session profile. An invalid value (`\"USA\"`, `\"\"`, `12`, `null`) is dropped and the stored value is carried over, never cleared, like the other native-context fields."
  - "Test (concierge): the `profile_in` sent to the hotel-search leaf carries `entry_market_country`. A leaf `profile_delta` carrying `entry_market_country` does not change the stored value (the field is concierge-owned)."
  - "Test (leaf, H5 fixture `11580`, Mapbox mocked): the real `geocode_location` FunctionTool runs with a GeoIntent with postal_code \"11580\", no country named and no model guess, and profile_in `locale: \"en\"`. With `entry_market_country: \"US\"` it resolves the United States candidate, and with `\"MX\"` the Mexican one. No Mapbox call carries a `country` filter in either case."
  - "Test: `_market_country` prefers profile_in `entry_market_country` (through `_iso2`) over the locale region, which it prefers over the language prior. A malformed value is ignored. The market never comes before the turn's named city or the model's guess in `_postcode_match`."
  - "Test: the declaration of the leaf's real `geocode_location` FunctionTool (`_get_declaration().parameters_json_schema`) has no property for the market country. The value is read from `profile_in` inside the tool, so the model can neither write it nor see it."
  - "The existing tests pass without change to their assertions: \"near 11580\", Q08's DQ8 tests and Q14's tests."
  - "`MAX_LLM_CALLS_PER_TURN` is unchanged. The diff adds no regex or word list that reads the user's words; the only format check is on the ISO2 code, a structured field."
  - "The report records the new profile field as a `decision` entry (name, writer, consumer, persisted in Redis under the existing TTL)."
---

## Launch prompt
You carry out Q16 on the branch task/Q16. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, DQ8, and the Q07 and Q08 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **What the widget sends.** `web/vendor/static/js/chat/handlers/send.js`, `buildRequestBody`: `locale` is `marketContext.language`, a bare "en" on the en/USD market. `entry_market_country` is `marketContext.country_code`, in the same body.
- **Facade.** `agents/b2c_concierge/b2c_concierge/facade.py`, `_native_context_delta`, reads locale, currency, domain, the GPS anchor and client_timezone, but not `entry_market_country`. The response's `market_country` / `entry_market_country` are inferred from the results (`_infer_market_country`): this is another value, don't reuse it.
- **Profile.** `agents/b2c_concierge/b2c_concierge/profile.py`: `to_dict` is what travels as `profile_in`, and the native-context fields (`locale`, `currency`, `domain`) are the model to follow.
- **Leaf.** `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`: `_market_country(locale)` and `_postcode_match` (order: the turn's named city, then the guess, then the market, then Mapbox rank). After Q07, ADK drops any argument `geocode_location` does not declare. Read the value from `profile_in` inside the tool, as Q14 does for the region, never through a new declared parameter.
- **Fixture.** H5's `11580` response in `agents/hotel_search_agent/tests/fixtures/mapbox_v6/`.

## Implementation notes
1. **Facade.** Parse `entry_market_country` like the other native-context fields: a valid ISO 3166-1 alpha-2 code becomes uppercase, and anything else is dropped (carryover, never a clear). Store it in a profile field `entry_market_country` that is concierge-owned (no leaf delta sets or clears it) and round-trips through the profile's serialization.
2. **Leaf.** `_market_country` takes `profile_in.entry_market_country` first (through `_iso2`), then the locale region, then the language prior. It stays a tie-break: never a `country` filter, never above the turn's named city or the model's guess.
3. Don't touch the widget, the response payload's market fields or `select_us_postal_anchor` (Q10).

## Out of scope
- Removing the US-ZIP anchor (Q10).
- The response's `market_country` and the widget.
