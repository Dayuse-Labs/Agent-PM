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

## Already answered / not applicable

- Pagination (`from`/`size` offset) — already exists server-side (S-G5,
  live-probed 2026-07-23), no MCP change needed.
- `count_hotels_near(bbox)` inventory tool (A1-c) — not requested; the S-G3
  static snapshot (A1-a) proved sufficient, revisit only if it shows staleness
  failures.
- Pricing/currency surface (A6-b) — not requested this session; deferred to
  a future currency/locale phase (S-G7) if multi-currency display becomes a
  priority.
