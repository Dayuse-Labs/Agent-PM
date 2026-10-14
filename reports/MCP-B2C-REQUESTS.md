# Cross-repo requests to MCP_B2C

Tracks capability asks against the MCP_B2C server, opened from AgentB2C sessions.
Each entry: what's requested, why, current client-side workaround, and — when
the workaround is an interim measure — the condition under which it can be
removed.

## Open

### `resolve_location`: a Dayuse-owned POI/landmark geocoder on the `poi` index

**Requested:** 2026-08-26 (geo session)
**Status:** open — this is the structural fix (P2 of `AUDIT-AGENTIQUE-2026-07-30.md`)

**What:** a tool that resolves a landmark/district/POI name to coordinates from
MCP_B2C's own `poi` Elasticsearch index (alias `POI_INDEX`, present but not
wired to any tool today). Suggested shape, mirroring `search_offers`' own
vocabulary:

```
resolve_location(query: str, locale: str, country_code: str | null,
                 near_lat: float | null, near_lon: float | null, limit: int)
  -> [{ name, lat, lon, country_code, region, city, feature_kind, hotel_count }]
```

`hotel_count` (bookable Dayuse hotels near the candidate) is the field that
matters most — see below.

**Why — the reason got much stronger this session.** We now have the mechanism,
not just the symptom. The landmark tier is Mapbox Search Box `/forward`, and
Mapbox documents for that endpoint: ***"If not provided, the default is IP
proximity."*** We send no `proximity` when the user has granted no GPS, so
**the resolution is a function of the container's egress IP** — an input we
never chose, that is absent from every trace, that differs between a laptop and
a Railway container, and that can change with no deploy at all.

Measured, not inferred:

- Production, 2026-08-25: "autour des champs élysées" resolved to
  `Champs Elysées, 32 Rue d'Alger, 83000 Toulon, France` — **830 km off**.
  The same tool arguments replayed from a laptop the next day returned Paris
  (trace `5eec27af27b79ed4b87f4c325b563bbc`).
- Mid-session, this machine's egress IP changed on its own and the identical
  query moved from Paris to a bistro in Viré, Saône-et-Loire (**329 km**);
  "gare de lyon" moved to a business in Lyon (**393 km**).
- A landmark probe over 18 cases scored **8/18 from a bad IP and 15/18 from a
  good one — same code, same commit, same minute**.

**A Dayuse POI index is immune to this by construction.** It has no notion of a
caller IP, it carries `name_<locale>` with autocomplete analyzers across the 29
markets (so it already knows "champs élysées", "gare de lyon", "sagrada
familia" in the right language), and it is the only geocoder naturally weighted
by OUR supply — the thing that actually distinguishes the Champs-Élysées from a
same-named shop in Toulon. Our client-side resolver approximates that weighting
today with `count_near` over a static snapshot; the index would answer it
directly.

**Current client-side workaround (shipped 2026-08-26, and it is a workaround):**

1. Never let Mapbox choose the bias: an explicit `proximity` built from a
   verified city coordinate (the v6 candidate that echoed the city the user
   named), or the device GPS fix.
2. Ask for the full candidate list (`limit=10`) and rank it ourselves —
   `geo_resolver.rank_landmark`: exact-name match, feature-type prior,
   inventory density, a tight city-anchor term.
3. A 14th deterministic guard, `poi_anchor_coherence`, throws away a POI more
   than 100 km from the turn's own anchor.
4. Fall back to folding the city into the query when we have a city name but no
   coordinate for it — which fixes the position but degrades the label (the
   list fills with businesses named after the landmark).

That took the probe to 17/18, but every layer of it is compensation for a
geocoder that ranks by the wrong signal. Step 4 in particular trades label
quality for correctness, and nothing we can do client-side removes the IP
dependency on the bare-landmark path (no city named, no GPS) — Mapbox offers no
way to switch the bias off.

**Removal condition:** `resolve_location` becomes tier 1 for any request naming
a zone/landmark; Mapbox stays the fallback for out-of-inventory places. The
echo-back guard and `poi_anchor_coherence` stay as-is — they verify facts and
cost nothing. Step 4 (city folded into the query) and the IP dependency both
disappear.

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

### `find_hotel_by_name`: return the hotel's coordinates (`lat`/`lon`)

**Requested:** 2026-10-08 (leaf géo plan review)
**Status:** open — pending Fabien's decision D-2 (`reports/PLAN-LEAF-GEO-2026-10-08.md` §5)

**What:** add `lat`/`lon` (from `_geoloc`) to the `find_hotel_by_name` result and
document them in the tool description. Read-only, no new indexed field.

**Why:** AgentB2C shows a named hotel together with its neighbours: once
`find_hotel_by_name` resolves the hotel, a dated `search_offers` runs centred on
it (`named_hotel.py`, PR #124). MCP `main` 08f3764d returns the identity only
(id, name, cityName slug, country, address, star rating, rating, photo — per the
tool description), so that follow-up search has no centre.

**Client-side workaround:** the named hotel is shown alone, without neighbours.
**Removal condition:** the coordinates are in the published schema and in
`contracts/mcp_b2c_tools.json`.

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
