---
id: Q12
title: "Documentation: HANDOFF, CHANTIERS, S-L plan"
phase: 5
model: sonnet
model_reason: "Source plan's model, kept: documentation that must state exactly what the code does; not mechanical."
effort: medium
depends_on: []
parallel_batch: 5A
owned_files:
  - HANDOFF.md
  - CHANTIERS.md
  - reports/PLAN-LEAF-GEO-2026-10-08.md
  - SESSIONS-CLAUDE-CODE.md
  - phases/SL2-contrat-geointent-evals.md
  - phases/SL5-bascule-feuille-geointent.md
  - phases/SL7-retraits-regles-langage.md
resources: []
prerequisites: [E2]
context_budget: 30%
token_estimate: 1.6M
max_turns: 40
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "`HANDOFF.md` starts with a dated QA14707 block (done / remaining / pitfalls)."
  - "Each claim of that block cites a verifiable file, test or commit."
  - "`CHANTIERS.md` has the QA14707 entry."
  - "The L section of `CHANTIERS.md` reflects DQ1, and the rules removed by Q09, Q10 and Q11 are out of its S-L7 list."
  - "The S-L plan has `postal_code` and `ambiguity` without `options` in its §3 contract. It notes that the S5 rule is carried by `ambiguity.reason` (DQ6), and it states the postcode country rule (DQ8)."
  - "S-L7f (`select_us_postal_anchor`) is marked removed by Q10 (DQ7), in the S-L plan and in `phases/SL7-retraits-regles-langage.md`."
  - "`phases/SL2…`, `SL5…` and `SL7…` carry a banner saying what this plan delivered in their place (Q06, Q07, Q09-Q11), and their rows have up-to-date statuses."
  - "`SESSIONS-CLAUDE-CODE.md`: the S-L section points to this plan."
  - "The dated QA14707 block of `HANDOFF.md` states that the eval `clarify_options_from_geocoder` is a weak live signal (listed place names only), and that the exact guarantee is Q04's offline rendering tests, citing their test file."
  - "The dated QA14707 block of `HANDOFF.md` documents the shape of `profile.pending_clarification` = `{clarification, request, asked}` (with the meaning of `asked`) as the model the port of #134 must conform to, citing `agents/b2c_concierge/b2c_concierge/profile.py`."
  - "The dated QA14707 block of `HANDOFF.md` lists, under remaining (H3), the live checks of the GeoIntent interface: the rates of valid=0, mentions_discarded and canonicals_rejected on the `dayuse_metric=geo_intent` lines, traces A and B, and the S5 flag on « gare de Lyon », citing `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`."
  - "The DQ8 country rule written in `reports/PLAN-LEAF-GEO-2026-10-08.md` §3, and the dated QA14707 block of `HANDOFF.md`, state where the market's country comes from: the request's `entry_market_country`, stored in the profile (Q16), then the locale region, then the language prior. They cite `_market_country` in `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`."
  - "`reports/PLAN-LEAF-GEO-2026-10-08.md` §3 states the mapping as `_place_args` implements it (agents/hotel_search_agent/hotel_search_agent/geocode_tool.py): zone = the first place that is neither a city nor a hotel, a city place counts at any rank, and city precedence is the zone place's own city, then a city place, then the `city` field."
  - "The dated QA14707 block of `HANDOFF.md` does not repeat that `places[1]` is used only when places[0] is a hotel or was discarded."
  - "The H3 checklist in the dated QA14707 block of `HANDOFF.md` also lists the `city_conflicts` rate on the `dayuse_metric=geo_intent` lines, citing `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`."
  - "The DQ8 country rule written in `reports/PLAN-LEAF-GEO-2026-10-08.md` §3 gives the tie-break order of `_postcode_match` (`agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`): the turn's named city (`context.place`), then the LLM's guess, then the market's country, then Mapbox's order."
  - "The dated QA14707 block of `HANDOFF.md` states what a postcode turn persists (bare postcode: its city only, no zone, `city_centroid` radius; address: Mapbox's name without the postcode in `zone`, `poi` radius; a low-confidence address match is refused), citing `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`."
  - "The dated QA14707 block of `HANDOFF.md` documents `region_anchor` as a concierge-owned field of the session profile, part of the model the #134 port must conform to. The block says: written only from the stored `Clarification`'s chosen option, sent in `profile_in`, stored in Redis under the existing TTL, wiped on a city change. It also says the leaf uses it only to narrow homonym candidates while the city is unchanged: a state named this turn or anchored wins, an unmatched region narrows nothing, and it is not applied on a postcode turn. The block cites `agents/b2c_concierge/b2c_concierge/profile.py` and `_fill_place_from_profile` in `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`."
  - "The H3 checklist in the dated QA14707 block of `HANDOFF.md` defines `city_conflicts` as Q14 implements it: a user-written city of this turn that differs after folding from any non-empty city on the zone place, not only an inferred one, and nothing counted under `city_needed`. It cites `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`."
  - "`reports/PLAN-LEAF-GEO-2026-10-08.md` §3 states the exception to the city precedence: a city mentioned in the user's own words of this turn (`read_user_words`) and checked by `_verified_city` beats the zone place's city, and the country guess then comes from the winning city first. A city carried only by the EARLIER REQUEST prefix keeps the zone place's own city first."
  - "The dated QA14707 block of `HANDOFF.md` lists the session profile field `entry_market_country`, with the following facts. Writer: the facade, from the request body, ISO2-checked, an invalid value carried over. It is concierge-owned and not cleared by a city change. It is persisted in Redis under the existing TTL and sent to the hotel-search leaf in `profile_in`. The block presents it as part of the profile shape the port of #134 must carry, citing `agents/b2c_concierge/b2c_concierge/profile.py` and `agents/b2c_concierge/b2c_concierge/facade.py`. It states that this is not the response payload's `entry_market_country` / `market_country`, which `_infer_market_country` derives from the results."
  - "The H3 checklist in the dated QA14707 block of `HANDOFF.md` lists the `repaired` field of the `dayuse_metric=geo_intent` line. It defines the field as the number of repairs carried by the intent the tool used: a bare-string `city` turned into a `CityRef`, and a place with an unknown string `kind` removed. It also explains how to read it: valid=0 with repaired>0 means salvaged, and valid=0 with repaired=0 means discarded whole. It cites `_repaired` / `_valid_intent` in `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`."
  - "The H3 checklist in the dated QA14707 block of `HANDOFF.md` lists `qa14707-versailles-address-fr` and `qa14707-poissonniere-75009-no-country-en` (3/3 required). It states that a street/address turn with no postcode now makes one more Mapbox v6 call (types address,street) before the generic path, citing `_street_match` in `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`."
  - "The H3 checklist in the dated QA14707 block of `HANDOFF.md` lists `geo7-manhattan-answer` (3/3 required). On the answer turn it must resolve « Manhattan, État de New York » (locality), and a pass through a business POI named Manhattan does not count. The block cites `TestTheManhattanAnswer` in `agents/hotel_search_agent/tests/test_picked_option_query.py` as the offline proof."
  - "The dated QA14707 block of `HANDOFF.md` states the Q21 refinement of the `region_anchor` rule. While a chosen region applies, the v6 query of the picked option carries no state term. A state named this turn, anchored or read from the text still steers the resolver (`region_hint`) and the echo guard. The narrowing keeps only the chosen region's candidates that this state's echo accepts, and only when at least one is left, so a state that contradicts the pick narrows nothing and the resolver follows the state. The block cites agents/hotel_search_agent/tests/test_picked_option_query.py and `geocode_core` in `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`."
---

## Launch prompt
You carry out Q12 on the branch task/Q12. Read DISCOVERY.md and HANDOFF.md
of the plan first (all decisions and the task entries written during the run),
then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- CLAUDE.md, section "Fin de session".
- `phases/QA14707/README.md`: decisions D-Q1 to D-Q3, and "Articulation avec les chantiers ouverts".
- The plan's HANDOFF: DQ1 to DQ6, and the entries of tasks Q01-Q11.
- The commits `task Q01: …` to `task Q11: …` on the integration branch (`git log`).
- Memory `project-chantiers-source-of-truth`: CHANTIERS.md is the verified list, and the `### Reste` blocks of HANDOFF get copied over after delivery.

## Implementation notes
The docs of the repository are in French: write in French in these files, as they already are.

1. **`HANDOFF.md`**: a dated block at the top.
   - **Done**: per task, with the evidence (file, test, commit).
   - **Remaining**: H3 and H4 if not done, and the question to Raphael about the locale.
   - **Pitfalls discovered**: from the reports and from the plan's HANDOFF.
   - Remove the "remaining" items this plan settled.
2. **`CHANTIERS.md`**:
   - add a QA14707 entry (done / remaining);
   - update the L section according to DQ1: the search leaf produces the `GeoIntent`, and S-L3/S-L4 become conditional;
   - take the rules removed by Q09, Q10 and Q11 out of the S-L7 list.
3. **`reports/PLAN-LEAF-GEO-2026-10-08.md`**:
   - §3: contract v1.1 (`postal_code`, `mention`/`canonical`, `ambiguity` = `reason` only per DQ5, S5 carried by `ambiguity.reason` per DQ6);
   - §4: the sequence changed by DQ1;
   - S-L7 list: `select_us_postal_anchor` is already there as S-L7f. Mark it removed by Q10, with decision DQ7. The source plan's claim that S-L7 "had forgotten" it is wrong: don't repeat it;
   - §3 mapping: the country rule of a postcode (DQ8);
   - fix stale line numbers (the plan's are those of `cbe88b9`).
4. **`SESSIONS-CLAUDE-CODE.md`**: the S-L section points to this plan (`plans/qa14707/`, `phases/QA14707/`).
5. **Phase files `phases/SL2…`, `SL5…`, `SL7…`**: a dated banner at the top saying what QA14707 delivered in their place, plus row statuses. Examples: the contract by Q06; the leaf-side mapping by Q07 under DQ1; S-L7 rows removed by Q09, Q10 and Q11.

## Out of scope
Any code file.
