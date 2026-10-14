---
id: Q14
title: "A chosen homonym option reaches the leaf with its region"
phase: 3
model: opus
model_reason: "Touches the concierge-to-leaf interface and the leaf's geocoding across two modules, with homonym cases to keep."
effort: high
depends_on: [Q07, Q08]
parallel_batch: 3C
owned_files:
  - agents/b2c_concierge/b2c_concierge/agent.py
  - agents/b2c_concierge/b2c_concierge/profile.py
  - agents/b2c_concierge/tests/**
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2]
context_budget: 40%
token_estimate: 3.2M
max_turns: 60
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests agents/hotel_search_agent/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test (concierge, fake leaf): with a pending homonym `Clarification` whose options 1 and 2 share `city` and `country_code` (`Springfield (Illinois, US)` / `Springfield (Missouri, US)`), a triage `answers_pending=yes, answer_option=2` sends the leaf the chosen option's `region` (`Missouri`) as data. It goes in `query_params` or `profile_in`, it is taken from the stored `Clarification` and never from the message text, and the leaf call is the only search call."
  - "Test (leaf, Mapbox mocked): with that chosen option on the answer turn, `geocode_location` resolves the Missouri candidate and returns no homonym question again."
  - "Test: options that differ by city or country keep today's behaviour. `test_an_option_index_searches_the_city_of_that_option` (agents/b2c_concierge/tests/test_clarification_routing.py, Victoria CA/US) passes without change to its assertions."
  - "The existing geo tests (Budapest, La Défense, gare de Lyon, Saint-Paul, Manhattan, \"near 11580\") pass without change to their assertions."
  - "`MAX_LLM_CALLS_PER_TURN` is unchanged, and the diff adds no regex or word list."
  - "The report records the new field of the concierge-to-leaf data as a `decision` entry (name, location, consumer)."
  - "The chosen option's region is read and applied inside the tool (`geocode_location` / `_fill_place_from_profile`, from `profile_in` or `query_params`), never as a new argument written by a before-tool callback. A test runs the leaf's real `geocode_location` FunctionTool with the region in the inbound DataPart and Mapbox mocked, and gets the chosen candidate."
  - "Test (Mapbox mocked): message « Gare du Nord à Bruxelles », `GeoIntent(places=[station \"Gare du Nord\" city \"Paris\"], city={mention \"Bruxelles\"})`: `geocode_core` receives city Bruxelles (checked by `_verified_city`), not Paris. (Moved from Q08, merged: in `_place_args` the zone place's inferred city must no longer beat a city the user wrote in this turn.)"
  - "Test (Mapbox mocked): on an answer turn whose city comes only from the concierge's EARLIER REQUEST prefix (no mention in the user's own words, `read_user_words`), the zone place's own city keeps precedence, as after Q07."
  - "Test: a disagreement between the zone place's inferred city and a user-written city is counted as `city_conflicts` on the `dayuse_metric=geo_intent` log line, which carries no message text."
  - "Q07's tests for `places=[station, city Paris]` and `[city Paris, station]` pass without change to their assertions."
  - "Test (Mapbox mocked, H5 fixture): `GeoIntent(places=[city \"Paris\", address \"2 boulevard Poissonnière\" postal_code \"75009\"])` and the same two places in the reverse order give the same result: zone = the address, city Paris, the postcode applied, and no city-wide search and no question. (Moved from Q08, merged.)"
---

## Launch prompt
You carry out Q14 on the branch task/Q14. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, the Q03, Q04 and Q05 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Q05's resolution** of a chosen option: `chosen_clarification_option` (`profile.py`) and the branch `answers_clarification` in `agent.py` (search `profile.country_anchor = option.get("country_code")`). It sets `city` and `country_anchor` and clears `zone`, `metro`, `state_anchor` and `search_anchor`. It does not pass `region`, because `state_anchor` is a US-state anchor for the `state_anchoring` guard and not a generic region (Q05 HANDOFF entry).
- **Q03's options**: `label`, `city` (bare name), `region`, `country_code` (`libs/b2c_common/b2c_common/clarification.py`). Two options can share `city` (Q03 HANDOFF entry).
- **Q04's interface**: on the answer turn, the concierge sends the `Clarification` in `query_params.clarification` and as text in the EARLIER REQUEST / YOU ASKED / REPLY prefix (`agent.py`, search `pending_clarification_context`).
- **Leaf carry-over**: `inject_profile_geo_context` (`geocode_tool.py`, search `profile_in.get("country_anchor")`) fills `country_code` from `country_anchor` and `profile_state_context` from `state_anchor`. `_anchor_state` (`geocode_tool.py`, search `def _anchor_state`) feeds the `state_anchoring` guard.
- After Q07, the tool takes a `GeoIntent`, and the core keeps the flat arguments. After Q08, the postcode and country rules apply (DQ8).

## Implementation notes
1. **Concierge.** When the chosen option carries a `region`, pass it to the leaf as data, next to the city and country Q05 already sets. Either reuse an existing anchor if its meaning fits, or add a dedicated key, and justify the choice in the report. The option is resolved in code from the stored `Clarification` (Q05), never re-read from the message.
2. **Leaf.** Use that region to pick the candidate among homonyms that share city and country. The geocoder still decides: the region narrows the candidates Mapbox returned, and is never a coordinate written by an LLM.
3. Don't change how options are built (Q03) or how they are rendered (Q04).

## Out of scope
- Mapping `ambiguity.reason = homonym` from the `GeoIntent` (Q07 out of scope).
- Removing `pending_place` (Q09, Q11).
