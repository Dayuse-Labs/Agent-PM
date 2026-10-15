---
id: Q20
title: "A street or an address without a postcode is resolved by the address lookup"
phase: 3
model: opus
model_reason: "Geo policy in the leaf's core, a new structured provider field, cases to keep (DQ8, the city question)."
effort: high
depends_on: [Q19]
parallel_batch: 3H
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/hotel_search_agent/mapbox_client.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2, H6]
context_budget: 40%
token_estimate: 2.6M
max_turns: 60
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests tests/test_leaf_concierge_seam.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test reproducing the Versailles failure, v6 served from the H6 fixtures `street_bd_republique_versailles.json` (types address,street) and `place_bd_republique_versailles_cand.json` (default types): `geocode_core(city=Versailles, zone=Boulevard de la République, zone_kind=street)` returns ok on « Boulevard de la République, 78000 Versailles, France », distance_origin `poi`, the zone persisted is Mapbox's street name, and no call carries a `country` filter. On the parent commit the same call returns `geocode_echo_mismatch` on « Leipzig, Saxony, Germany » (the report quotes that run)."
  - "End-to-end test (after Q17): the real `geocode_location` FunctionTool with H3's recorded Versailles intent (plan-r2) and text « Trouve moi une chambre à Boulevard de la République Versailles pour 13h demain » gives the same result and no city question."
  - "Test, H6 fixture `address_2_bd_poissonniere_paris_no_postcode.json`: zone `2 Boulevard Poissonnière`, zone_kind `address`, city `Paris`, no postcode -> ok on the 75009 address (its `context.place` equals the city, `match_code.confidence` medium)."
  - "Test, H6 fixture `address_2_bd_poissonniere_75009_paris_in_zone.json`: zone `2 Boulevard Poissonnière, 75009 Paris`, zone_kind `address`, no city, no postcode -> ok on the 75009 address, accepted because Mapbox reports `match_code.place == matched` for it (the user's own string carried the place)."
  - "Negative control, H6 fixture `street_bd_republique_no_city.json`: zone `Boulevard de la République`, zone_kind `street`, no city, no device fix -> the city_needed question exactly as today (no Algerian street is accepted)."
  - "Negative control: a candidate whose `context.place` differs from the city, or whose `match_code.confidence` is `low` (« 2 Rue Poissonnière, 75002 »), is refused; with nothing accepted the turn follows today's path unchanged."
  - "`mapbox_client` parses `match_code.place` and `match_code.postcode` into new candidate fields with empty defaults; Q08's tests (H5 fixtures, DQ8 order, « near 11580 ») pass without change to their assertions."
  - "No Mapbox call is added on any path other than a `street`/`address` zone with no postcode; `MAX_LLM_CALLS_PER_TURN` is unchanged; the diff adds no regex or word list (structured equality on `context.place` and `match_code` only)."
---

## Launch prompt
You carry out Q20 on the branch task/Q20. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, DQ8, DQ9, the Q08 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Measured (H3 + live core probe).** The address/street lookup (`types=address,street`) runs only inside the postcode branch (`geocode_tool.py:713-754`). Without a postcode, a street goes through the generic lookup (`:960-965`) with `CANDIDATE_TYPES` (`mapbox_client.py:40`), which never returns a street. « Boulevard de la République, Versailles » then resolves to Leipzig: echo mismatch with no guess, and a Leipzig / Versailles (Louisiana) question with `locale=fr-FR`. Main passed 1 run in 3 only because its model sent a hard `country_code=FR`. gpt-6-luna's correct intent fails the same way, so this is a code defect (`scratchpad/h3-diagnosis.md` RC5).
- The same defect explains `qa14707-poissonniere-75009-no-country-en`: in r1 the address plus Paris with no postcode gave a Paris TX/TN question, and in r3 the whole address sat in one zone with no city and got the city question.
- **Mapbox facts (fixtures).** Streets carry no `match_code` (only addresses do), so for a street the criterion is `context.place` equal to the turn's city. An address the user wrote with its city gets `match_code.place = matched`.
- **Fixtures (H6).** All recorded on 2026-10-15, `limit=10`, `autocomplete=false`, no `country`:
  - `street_bd_republique_versailles.json`: q « Boulevard de la République, Versailles », types address,street, language fr;
  - `street_bd_republique_no_city.json`: q « Boulevard de la République », same params;
  - `place_bd_republique_versailles_cand.json`: same q as the first, default candidate types, no language;
  - `address_2_bd_poissonniere_paris_no_postcode.json`: q « 2 Boulevard Poissonnière, Paris », types address,street, language en;
  - `address_2_bd_poissonniere_75009_paris_in_zone.json`: q « 2 Boulevard Poissonnière, 75009 Paris », same params.
  Draft copies are in `scratchpad/h3/proposed_fixtures/`.

## Implementation notes
1. In `geocode_core`, for a `street`/`address` zone with no postcode, before the city question and before the generic lookup:
   - with a city, look up « zone, city » with `ADDRESS_TYPES` and keep a candidate whose `context.place` equals the city (`_comparable`), whose confidence is not `low` and which echoes the zone;
   - with no city, look up the zone alone and keep a candidate with `match_code.place` or `match_code.postcode` = `matched` and a confidence that is not `low`.
   Return as the Q08 address branch does (`_ok`, distance_origin `poi`, zone = Mapbox's name, city = `context.place`). If nothing is kept, fall through to today's code.
2. The named country stays the only hard filter (DQ8).
3. **Live proof:** H3' (`qa14707-versailles-address-fr` and `poissonniere-75009-no-country-en` must reach 3/3 for the bar).

## Out of scope
- A postcode the model did not extract (RC7: model, or Q23).
- The generic resolver's homonym ranking.
