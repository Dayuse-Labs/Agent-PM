---
id: Q18
title: "A place survives an added article or a corrected typo in its mention"
phase: 3
model: sonnet
model_reason: "One function of the leaf's claim check, with recorded cases and a clear negative control."
effort: medium
depends_on: [Q17]
parallel_batch: 3F
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2]
context_budget: 30%
token_estimate: 1.2M
max_turns: 40
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests tests/test_leaf_concierge_seam.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test reproducing H3 (`geo-poi-champs-elysees-bare` plan-r2, trace 8830d21f7f5d605462ff7ecec7f16358), core spied: text « je cherche un hôtel autour des champs élysées », intent `{places: [{mention: les champs élysées, kind: landmark, canonical: Champs-Élysées}]}` -> the core receives zone `Champs-Élysées` (the place is anchored). On the parent commit the place is dropped and the core receives no zone (the report quotes that run)."
  - "Test reproducing H3 (`geo-poi-champs-elysees-typo` plan-r1, trace 29146395f68bfc91a11a376a4e5467df): text « hotel pres des champ elysee pour demain », mention `près des Champs-Élysées`, and the retry's mention `Champs-Élysées` -> both anchored, zone `Champs-Élysées`."
  - "Test: a mention that is not in the text but whose canonical is (whole words, `_comparable`) is anchored."
  - "Negative control: text « un hôtel près de la Gare du Nord demain », a place or a `city` whose mention is `Bruxelles` (and one with `London` for « à Londres ») is still discarded and counted in `mentions_discarded`; Q07's test 'a mention absent from the leaf's input text is discarded and counted' passes without change to its assertions."
  - "The tolerance is a character-level similarity over the comparable text (no word list, no regex), with a fixed threshold that is a named constant; the report gives the threshold and the score of each case above (accepted and refused)."
  - "Accepted-by-similarity mentions are counted (`mentions_fuzzy=N` on the `dayuse_metric=geo_intent` line); a test checks that no word of the message appears on the line."
  - "The guard tests `qa14707-guard-*` equivalents in the leaf suite (Gare du Nord with no city, gare de Lyon with `city_needed`) pass without change to their assertions."
---

## Launch prompt
You carry out Q18 on the branch task/Q18. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, the Q07 and Q14 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Measured (H3).** `_Claims.anchored` (`geocode_tool.py:1385-1391`) keeps a place only when its `mention`, whole words, is in the input text, and only looks at `canonical` when the mention is empty. The model writes « les champs élysées » for « …autour **des** champs élysées » and « près des Champs-Élysées » for « pres des champ elysee ». The place is dropped, the turn has neither zone nor city (`no_geocodable_location / missing_city`, `geocode_tool.py:920-934`), the leaf retries, and the synthesis asks the city in prose. That is 5 of the 26 `resolved_country_code` regressions on geo-poi. gpt-6-luna wrote « les champs élysées » in 1 of 5 probe calls on the same message, so this is not a model-only issue (`scratchpad/h3-diagnosis.md` RC2).
- `_comparable` (`:1351-1356`) folds case, accents and punctuation by character class. Reuse it.
- `difflib.SequenceMatcher` from the standard library, on token windows of the comparable text, is one way to get the similarity without any language rule.

## Implementation notes
1. Order of the check: exact mention, then exact canonical, then similarity of the mention (and of the canonical) to a window of the text of the same number of words, above a threshold. Anything below stays discarded and counted as today.
2. The anchoring exists to stop a place the user never wrote (an option of the YOU ASKED prefix is in the text anyway). Pick the threshold so that the negative controls fail it with margin.
3. **Live proof:** H3' (re-run). The offline tests prove the mapping.

## Out of scope
- `places[].city` / the landmark's city (RC1, model and Q23).
- The `postal_code` check `_Claims.written`: keep it exact.
