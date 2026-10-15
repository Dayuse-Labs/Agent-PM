---
id: Q22
title: "A named hotel not found in a named city falls back to that city's search in code"
phase: 3
model: opus
model_reason: "Async after-tool machinery of the leaf (named_hotel), geocoding and the bound search, with the LLM budget at stake."
effort: high
depends_on: [Q21]
parallel_batch: 3J
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/named_hotel.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2, DQ10]
context_budget: 35%
token_estimate: 1.6M
max_turns: 50
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests tests/test_mcp_contract.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test reproducing H3 (`geo7-named-not-found`, plan-r1 trace 1e280675c3d6247559669aed231c13a0), fake MCP toolset and Mapbox mocked: `find_hotel_by_name(name=Bidule Imaginaire, cityName=lyon)` returns `HotelNotFoundError` (and again on the retry without cityName). The after-tool callback then geocodes the city with `geocode_core` (Mapbox mock -> Lyon) and runs the bound `search_offers` once with Lyon's coordinates and the turn's date label, through the same before/after callbacks as today's named-hotel search. The results land in the state the DataPart reads. On the parent commit no search runs (the report quotes that run)."
  - "Negative control: `HotelNotFoundError` with no `cityName` runs no geocode and no search (the concierge's 'tell me the city' reply stays)."
  - "Negative control: a city that does not geocode (Mapbox mock returns nothing) runs no search and never falls back to the device fix or a guessed coordinate."
  - "The `AmbiguousHotelError` path and the found-hotel follow-up (`agents/hotel_search_agent/tests/test_named_hotel.py`) pass without change to their assertions."
  - "The leaf makes no extra LLM call for this path (the model's own geocode/search calls are no longer needed); `MAX_LLM_CALLS_PER_TURN` is unchanged; the diff adds no regex or word list."
---

## Launch prompt
You carry out Q22 on the branch task/Q22. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, DQ10), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Measured (H3).** `geo7-named-not-found` is 3/3 on main and 0/3 on the plan. After `HotelNotFoundError`, the plan's second leaf generation calls no tool. Main geocoded Lyon and searched it (trace 69ee504e3ff8c8c8e6747c94ceb0f406). The prompt rule ("HotelNotFoundError with a city in THIS message -> geocode_location + search_offers", `agents/hotel_search_agent/hotel_search_agent/agent.py`) is unchanged, and so is `named_hotel.py`.
- **Not reproduced in isolation.** The same tool result sent to gpt-4o-mini outside the stack gives a `geocode_location` call 3 times out of 3. The in-stack cause is not determined (`scratchpad/h3-diagnosis.md` RC9).
- **Machinery to reuse.** `follow_named_hotel` (`named_hotel.py:162-254`) already retries without `cityName` and runs the bound dated search for a found hotel (`bind`, `_search_before` / `_search_after`). `geocode_core` is the leaf's deterministic geocoder.

## Implementation notes
1. On `HotelNotFoundError` after the retry, with a non-empty `cityName`: geocode it, then run the bound search on the coordinates, exactly as the found-hotel branch runs its search. Record the outcome so the concierge says the hotel was not found and shows the city's hotels, as main's reply did.
2. `cityName` is the model's wording, already used for the MCP lookup. The geocoder and its echo guard decide whether it is a place.
3. **Live proof:** H3' (`geo7-named-not-found`).

## Out of scope
- The prompt's wording for the not-found case.
- `find_hotel_by_name` on the concierge's details route (Q11).
