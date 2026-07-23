# Cross-repo requests to MCP_B2C

Tracks capability asks against the MCP_B2C server, opened from AgentB2C sessions.
Each entry: what's requested, why, current client-side workaround, and — when
the workaround is an interim measure — the condition under which it can be
removed.

## Open

### `search_offers`: sub-hour `timeSlot` (startMinute/endMinute)

**Requested:** 2026-07-23 (S-G6)
**Status:** open

**What:** `search_offers`'s `timeSlot` parameter today only accepts integer
`startHour`/`endHour` (0-23) — live-probed against MCP_B2C staging
2026-07-23, real schema:

```json
"timeSlot": {
  "type": "object",
  "properties": {
    "startHour": {"type": "integer", "minimum": 0, "maximum": 23},
    "endHour": {"type": "integer", "minimum": 0, "maximum": 23}
  },
  "additionalProperties": false
}
```

Ask: add `startMinute`/`endMinute` (or accept `"HH:MM"` strings) so a request
for "7:30am to 1:30pm" can be expressed exactly, server-side, instead of only
in whole hours.

**Why:** `core-e2e-084` ("check-in 7:30am checkout 1:30pm") truncated to
07:00-13:00 because the client could only ever send whole hours. The
individual OFFERS `search_offers` returns already carry exact
`startMinute`/`endMinute` (probed live, unrelated to the request schema) —
only the REQUEST side lacks minute precision.

**Interim (A4-c, shipped this session):** the leaf sends the floored/ceiled
HOUR window that fully contains the exact ask (e.g. 7:30-13:30 →
`startHour=7, endHour=14`), then post-filters the returned offers/hotels
client-side by the EXACT requested minutes
(`hotel_search_agent/response_bridge.py::normalize_search_results`,
`_offer_fits_exact_window`). A hotel whose only offer doesn't survive the
exact filter is dropped from the shortlist; if the exact filter would empty
the whole result set, the leaf falls back to the coarser hour-rounded results
with an honest disclosure ("no offer covers the exact requested time window;
showing the closest matches instead") rather than a silent 0.

**Removal condition:** once `search_offers` accepts minute-precise request
bounds, `resolve_search_timeslot`
(`hotel_search_agent/datetime_resolver.py`) can send the exact window
directly and the client-side post-filter/fallback in `response_bridge.py`
becomes dead code — remove both together, plus the now-unneeded
`STATE_EXACT_WINDOW_KEY` state hand-off.

---

### `search_offers`: `date` requires a fully-resolved value (informational — no ask, honest constraint)

**Not a request, documented for completeness.** `search_offers`'s `date` is
REQUIRED (`"required": ["lat", "lon", "date"]`) and is `"the target date in
ISO format (yyyy-MM-dd), already resolved"` — MCP does zero date math
server-side (exactly like geocoding: MCP_B2C never resolves a relative
expression). This is by design and correct; the caller (AgentB2C) owns
resolving "tomorrow"/"the 28th"/weekday names into an absolute ISO date
before calling — done in `hotel_search_agent/datetime_resolver.py`
(`resolve_search_date`), never by the LLM.

---

### Pricing/currency surface (A6-a probe, S-G7) — constat only, no ask this session

**Live-probed 2026-07-23** (`search_offers` + `get_hotel_details`, staging):
both now expose a per-hotel `currencyCode` (e.g. `"EUR"` for Paris, `"USD"`
for Miami, `"GBP"` for London — confirmed varying correctly by market). This
is new signal AgentB2C did not have before this session (S-G1/S-G2 only
captured the USER's own currency context, never the hotel's).

**But it changes nothing about the pricing gate.** The only numeric price
fields remain `priceEuro`/`priceEuroWithBookingFees`, and they stay EUR cents
REGARDLESS of `currencyCode` — verified directly: the Cadillac Hotel & Beach
Club (Miami, `currencyCode="USD"`) returns `priceEuro=11933` (€119.33), the
exact EUR quote already seen in the 2026-07-22 Railway demo addendum, not a
USD amount mislabeled. MCP performs no server-side conversion and exposes no
native-currency numeric field — `currencyCode` is descriptive metadata only.

**What AgentB2C does with this (S-G7, shipped this session, not a pricing
change):** `currencyCode` is now stamped on hotel cards as `currency_code`
(`hotel_search_agent/response_bridge.py::normalize_hotel`,
`b2c_concierge/inline_tools.py::_normalize_hotel_for_display`) and used as a
second, independent trigger (alongside the user's own `profile.currency`) for
the honest "prices shown in EUR, no conversion" disclosure in the synthesis
prompt (`b2c_concierge/agent.py::_synthesize_with_guards`, `CURRENCY:`
marker) — display-only, zero conversion, zero new ask.

**Removal condition for the underlying gate (A6-b, real multi-currency
pricing):** would need MCP_B2C to expose either a converted numeric price in
the hotel's own currency, or a live FX rate to convert `priceEuro` ourselves
— neither exists today. Not requested this session (A6-a scope: context now,
pricing staged); open for a future phase if multi-currency display becomes a
priority.

## Already answered / not applicable

- Pagination (`from`/`size` offset) — already exists server-side (S-G5,
  live-probed 2026-07-23), no MCP change needed.
- `count_hotels_near(bbox)` inventory tool (A1-c) — not requested; the S-G3
  static snapshot (A1-a) proved sufficient, revisit only if it shows staleness
  failures.
- Pricing/currency surface (A6-b) — probed this session (S-G7, see above):
  `currencyCode` now exists per-hotel but no native-currency numeric price or
  conversion does; still not requested, open for a future phase if
  multi-currency display becomes a priority.
