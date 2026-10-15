---
id: Q13
title: Global review (read-only)
phase: 5
model: opus
model_reason: "Source plan's model, kept: a skeptical review of the whole plan, read-only."
effort: high
depends_on: [Q12]
parallel_batch: 5B
owned_files: []
resources: []
prerequisites: [E2]
context_budget: 40%
token_estimate: 2.6M
max_turns: 50
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Review report: each of the 10 points below marked OK, or KO with its evidence (file:line, command)."
  - "Each KO is written up as a `review` or `debt` entry for the plan's HANDOFF."
  - "No file changed (empty diff)."
  - "Point 7 also checks that Q04's offline tests for `city_needed` without options and for homonym options exactly from the `Clarification` exist and are green (file:line)."
  - "Point 4 also checks, with file:line evidence, that `find_hotel_by_name` never receives the raw message on the booking path (test_clarification_routing.py) or on the details route (Q11's test), or it reports the remaining `debt` entry."
  - "Point 9 (DQ8) also checks, with file:line, that the model-facing `geocode_location` has no `country_code` or `country_guess` parameter, and that every value reaching the Mapbox `country` filter went through `_iso2`."
  - "Point 9 (DQ8) also checks, with file:line, that the facade stores the request's `entry_market_country` after an ISO2 check, that the profile sends it in `profile_in`, and that the leaf reads it only as a tie-break in `_postcode_match`, never as the Mapbox `country` filter."
  - "Point 8 also checks, with file:line, that §3 of `reports/PLAN-LEAF-GEO-2026-10-08.md` describes the rank-independent mapping of `_place_args` (agents/hotel_search_agent/hotel_search_agent/geocode_tool.py) and that Q07's tests for `[station, city]` and `[city, station]` exist and are green."
  - "Point 9 also checks, with file:line, that a user-written city beats the zone place's inferred city (Q08's « Gare du Nord à Bruxelles » test), and that a city carried only by the EARLIER REQUEST prefix keeps the zone's own city first."
  - "Point 9 (DQ8) also checks, with file:line, that `_postcode_match` applies the named-city step before the guess and the market, that this step only narrows, and that Q10's test of « 75009 Paris » without the anchor exists and is green."
  - "Point 5 (GDPR) also checks, with file:line, that no address or postcode text reaches a metric line (the `dayuse_metric=geo_intent` line and the `mentions_discarded` counter carry counts only), and that the persisted `zone` lives only in the Redis profile under the existing TTL."
  - "Point 5 (GDPR) also checks, with file:line, that `region_anchor` lives only in the Redis profile under the existing TTL and in `profile_in`, that it reaches no metric line, and that it is not in the `search_offers` arguments."
  - "Point 9 also checks, with file:line, that `region_chosen` only narrows the candidates Mapbox returned and is never the Mapbox `country` filter, and that `agents/hotel_search_agent/tests/test_homonym_option_region.py` exists and is green."
  - "Point 5 (GDPR) also checks, with file:line, that `city_conflicts` on the `dayuse_metric=geo_intent` line is an integer count, and that a test asserts no word of the message appears on that line (agents/hotel_search_agent/tests/test_geo_intent_mapping.py)."
  - "Point 5 (GDPR) also checks, with file:line, that the profile field `entry_market_country` holds only an uppercase ISO2 code, lives only in the Redis session profile under the existing TTL, and appears on no `dayuse_metric` line. It also checks that a leaf `profile_delta` can neither set nor clear the field (`agents/b2c_concierge/tests/test_entry_market_country.py`)."
  - "Point 5 (GDPR) also checks, with file:line, that `repaired` on the `dayuse_metric=geo_intent` line is an integer count, and that agents/hotel_search_agent/tests/test_geo_intent_mapping.py asserts its values, 0 on an intent that still fails validation after the repair included, and that no word of the message appears on that line."
  - "Point 2 (Budget) also checks, with file:line, that the Q20 address lookup runs only for a specific `street`/`address` zone with no postcode (agents/hotel_search_agent/hotel_search_agent/geocode_tool.py), and that `agents/hotel_search_agent/tests/test_street_without_postcode.py` exists and is green."
  - "Point 9 also checks, with file:line, two things about the Q20 street branch (`_street_match` in agents/hotel_search_agent/hotel_search_agent/geocode_tool.py). The Mapbox `country` filter comes only from a named country. A candidate whose region contradicts a named, anchored or chosen state is never kept, as Q21's Springfield test shows, and that test exists and is green."
  - "Point 6 also checks, with file:line, that `TestTheManhattanAnswer` in `agents/hotel_search_agent/tests/test_picked_option_query.py` exists and is green, and that it asserts the locality « Manhattan, État de New York » with a v6 query that carries no state term."
  - "Point 9 also checks, with file:line, three things in agents/hotel_search_agent/hotel_search_agent/geocode_tool.py. While `region_chosen` is set, the v6 query carries no state term. A state still reaches the resolver as `region_hint`. The narrowing keeps only chosen-region candidates accepted by the state's echo, and only when at least one remains. The point also checks that agents/hotel_search_agent/tests/test_picked_option_query.py and `test_a_state_named_this_turn_speaks_for_itself` (agents/hotel_search_agent/tests/test_homonym_option_region.py) exist and are green."
  - "Point 2 (Budget) also checks, with file:line, that the Q22 fallback (`_search_the_city` in agents/hotel_search_agent/hotel_search_agent/named_hotel.py) makes no LLM call and that the leaf's final generation is skipped on that turn. It also checks that agents/hotel_search_agent/tests/test_named_hotel_city_fallback.py exists and is green, its negative controls included (no city: no geocode, no search; a city that does not geocode: no search and no device fix)."
  - "Point 5 (GDPR) also checks, with file:line, that the `named_hotel_city_search` and `named_hotel_search` lines (agents/hotel_search_agent/hotel_search_agent/named_hotel.py) carry only a fixed status and an integer duration, and that agents/hotel_search_agent/tests/test_named_hotel_city_fallback.py asserts that no word of the message, the hotel name or the city appears on them."
---

## Launch prompt
You carry out Q13, a read-only review of the whole plan on the integration
branch. Read DISCOVERY.md and HANDOFF.md of the plan first (decisions DQ1 to
DQ9, Principle, and every task entry), then the points below.
Change no file. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, the verdict per point
with its evidence, and the entries to add to the plan's HANDOFF.

## Useful context
- The total diff: `git diff main...plan/qa14707`.
- `phases/QA14707/README.md`, "Critères d'acceptation globaux".
- The task files of the plan and their reports in the plan's HANDOFF.

## Implementation notes
Points to check:
1. **Principle.** The total diff adds no new regex or word list to understand language. Each removed rule (Q09, Q10, Q11) is really gone: `git grep … -- agents libs`. `plans/` and `phases/` still quote the names, legitimately.
2. **Budget.**
   - `MAX_LLM_CALLS_PER_TURN` is unchanged.
   - A clarification turn no longer makes a synthesis call.
   - There is no new LLM call anywhere else.
3. **Frozen contracts.**
   - `GUARD_SCORE_NAMES` and `FALLBACK_SCORE_NAMES` have lost no name.
   - `contracts/geo_intent.schema.json` is identical to the model, and has no `ambiguity.options` (DQ5).
   - `contracts/mcp_b2c_tools.json` was not touched.
4. **R9.** `generate_booking_link` stays uncallable without a confirmation, and without a pending offer or a list on screen.
5. **GDPR.**
   - The triage receives the pending question, never the profile.
   - No message content goes into the metrics: the existing test is green, and the new discarded-`mention` counter carries no text.
   - No file of `baseline/` is in the diff.
6. **Cases to keep.** Each of these has a green test: "Gare du Nord" without a city, gare de Lyon (through `ambiguity.reason`, DQ6), Budapest, La Défense, "near 11580", Saint-Paul, Manhattan.
7. **Eval harness (DQ4).** Multi-turn items are replayed turn by turn on one session, and the trace facts are scoped to the last turn (offline tests).
8. **Truth of the documents.** HANDOFF, CHANTIERS, the S-L plan, the code comments and the plan's own DISCOVERY / HANDOFF say what the code does.
9. **Geo decisions.**
   - DQ6: gare de Lyon goes through `ambiguity.reason`.
   - DQ7: `select_us_postal_anchor` is gone.
   - DQ8: no `country` filter without a named country; the guess only breaks ties.
   - DQ9: Q08's tests rest on H5's recorded fixtures, not on a fabricated shape.
10. **Gates.** The 4 commands are green, the +400-day calendar guard included.

## Out of scope
Any change to a file.
