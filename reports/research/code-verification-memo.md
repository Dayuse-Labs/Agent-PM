# Verification Report: REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md vs actual code

> Code-grounding memo — 2026-07-23. Input for `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md`.
> Verified against `main` @ `453c77f` (the audit referenced `8478795`; the 2 newer commits — ordinal booking fix, Railway deploy — do not touch the geo/profile mechanics; all claims still hold).

**Bottom line: all 10 audit claims verified TRUE against the code.**

---

## Claim 1 — Mapbox geocoder requests only ONE candidate (limit=1), accept/reject only, no multi-candidate ranking

**Verdict: TRUE.**

- `limit` is hardcoded to `1` in the request params: `agents/hotel_search_agent/hotel_search_agent/mapbox_client.py:86-92`
```python
params: dict[str, str | int] = {
    "q": query, "types": types, "limit": 1,
    "language": language or "en", "access_token": self._token,
}
if country:
    params["country"] = country.lower()
```
- **Params actually sent:** `q`, `types` (default `"place,locality,neighborhood"` — `mapbox_client.py:21`, deliberately no address/POI), `limit=1`, `language`, `access_token`, and `country` (lowercased) only when provided. **No `proximity` (GPS anchor), no `bbox`, no POI types, no per-candidate scoring.**
- **`language` is never actually varied:** `geocode_tool.py:127` calls `get_mapbox_client().geocode(query, country=effective_country_code)` without passing `language`, so it always defaults to `"en"` (`mapbox_client.py:60`). Locale is not propagated to Mapbox.
- **`_parse` takes `features[0]` unconditionally** — no ranking among candidates: `mapbox_client.py:110-113` (`if not features: return None; feature = features[0]`).
- **Accept/reject guard is `geocode_echo_matches`** (`geo_guards.py:270-339`), called at `geocode_tool.py:135-145`. It validates the single `place_name` echoes the requested state and the longest distinctive city/zone token; on mismatch returns `{"ok": False, "error": "geocode_echo_mismatch"}`. Binary accept/reject of the one candidate — never a re-query, never a rank. Docstring at `geo_guards.py:281` literally calls this "the signature of a Mapbox limit=1 mis-resolution."
- No inventory-density / Dayuse-inventory awareness anywhere in the geocode path.

The audit's cited failure modes (Milano, Lisboa, La Défense, Köln/München) are consistent with this single-candidate + echo-reject design.

---

## Claim 2 — /v3/chat facade ignores `native_context.geolocation`

**Verdict: TRUE.**

- The strings `native_context` and `geolocation` **do not appear anywhere** in `agents/`, `libs/`, or `scripts/` (grep: zero hits).
- The facade reads **only two fields from the request body**:
  - `message`: `facade.py:485` (`str(body.get("message") or "").strip()`) and `:528`.
  - `session_id`: `facade.py:159`, only honored in migration phase M1 (`facade.py:160-164`), otherwise a fresh uuid is minted (`:165`). Session preferentially resolved from cookie or `X-Client-Session-Id` header (`facade.py:152-165`).
- No `locale`, `currency`, `domain`, `native_context`, or `geolocation` are read. `_read_body` (`facade.py:460-465`) returns the raw dict but nothing downstream consumes anything beyond `message`/`session_id`.
- The **response** contract keys are fixed at `facade.py:59-80` (`CONTRACT_KEYS`): `message, response, context, hotels, suggestions, session_id, conversation_id, response_language, state, ready_to_search, requires_clarification, profile_status, active_filters, market, market_country, entry_market_country, search_country, turn_id`. `response_language` derived post-hoc from `profile.language or guess_language(message)` (`facade.py:445`), not from any request locale.
- Domain/currency confirmed unmodeled: `inline_tools.py:183-188` — "This profile carries no user-currency signal today (nothing upstream ever captures one), so display is always EUR."

---

## Claim 3 — SessionProfile does NOT model named_hotel, zone, metro, absolute date, date_reference, currency, GPS coords, distance origin, already-shown IDs, pagination cursor

**Verdict: TRUE** (one nuance below).

**Complete list of ALL SessionProfile fields today** (`agents/b2c_concierge/b2c_concierge/profile.py:88-113`):

| Field | Type | Default |
|---|---|---|
| `city` | `str \| None` | `None` |
| `state_anchor` | `str \| None` | `None` |
| `country_anchor` | `str \| None` | `None` |
| `budget_max` | `float \| None` | `None` |
| `budget_request_source` | `str \| None` | `None` |
| `timeslot` | `str \| None` | `None` |
| `timeslot_start` | `str \| None` | `None` (stored `"HH:MM"`) |
| `timeslot_end` | `str \| None` | `None` (stored `"HH:MM"`) |
| `timeslot_request_source` | `str \| None` | `None` |
| `timeslot_mode` | `str \| None` | `None` (`"start_only"`/`"end_only"`/`"range"`) |
| `amenities` | `list[str]` | `[]` |
| `language` | `str \| None` | `None` |
| `consecutive_empty_searches` | `int` | `0` |
| `auto_widen_disclosure` | `dict[str, float] \| None` | `None` |
| `widen_attempt_count` | `int` | `0` |
| `search_exhausted` | `bool` | `False` |
| `last_suggestions` | `list[str] \| None` | `None` |
| `last_clarifying_question` | `str \| None` | `None` |
| `last_results` | `list[dict] \| None` | `None` |
| `pending_booking` | `dict \| None` | `None` |
| `amenity_claim_corrections` | `dict[str, list[str]] \| None` | `None` |

**Absent, as the audit claims:** `named_hotel`, `zone`, `metro`, any absolute-date / `date_reference` field, `currency`, GPS origin / resolved lat-lon, distance-origin type, a pagination cursor, and any dedicated "already-shown hotel IDs to exclude" set.

**Nuance:** `last_results` (`profile.py:111`, populated by `record_search_shortlist` `profile.py:567-589`) *does* persist the on-screen shortlist as `[{"hotel_id", "name"}, ...]` (≤5). A partial notion of "hotels currently shown" exists, but it is a **replace-on-each-search shortlist for name/ordinal resolution**, NOT an accumulating exclusion set for pagination. `pending_booking` persists a single quoted offer (`inline_tools.py:355-361`). The date gap is called out in-code: `search_context_line` docstring at `profile.py:470` — "The DATE isn't a profile field — it stays in the raw message"; and `inline_tools.py:388` HANDOFF note "profile n'a pas de champ date".

---

## Claim 4 — `active_filters` forces `named_hotel: null` and `date_reference: null`

**Verdict: TRUE.**

`build_active_filters` at `agents/b2c_concierge/b2c_concierge/facade.py:324-340`:
```python
return {
    "city": profile.city,
    "resolved_city": profile.city,
    "state": profile.state_anchor,
    "country_code": profile.country_anchor,
    "timeslot": _synth_timeslot(profile),
    "timeslot_start": profile.timeslot_start,
    "timeslot_end": profile.timeslot_end,
    "budget_max": profile.budget_max,
    "amenities": list(profile.amenities or []),
    "named_hotel": None,
    "date_reference": None,
}
```
Both are literal `None` (lines 338-339) because the profile has no field to source them from. `resolved_city` is just aliased to `profile.city` (no separate geo-resolution). Fed into the response at `facade.py:427` and the conversation log at `facade.py:454`.

---

## Claim 5 — search_offers timeSlot only accepts integer hours (0-23); 07:30 gets rounded/truncated

**Verdict: TRUE** (the real MCP schema is server-side, but every in-repo code path forces integer hours / drops minutes).

- The leaf **instruction** tells the model to send integer hours only: `agents/hotel_search_agent/hotel_search_agent/agent.py:143-146` — "Pass search_offers a `timeSlot` with integer `startHour` and `endHour` (0-23)". No `startMinute`/`endMinute` anywhere in outgoing search args.
- When capturing the model's args back into the profile, minutes are **forced to 0**: `response_bridge.py:200-207`
```python
time_slot = args.get("timeSlot")
if isinstance(time_slot, dict):
    start = _hhmm(time_slot.get("startHour"), 0)   # minute hardcoded 0
    end = _hhmm(time_slot.get("endHour"), 0)
```
- The profile *does* store `"HH:MM"` (`timeslot_start`/`timeslot_end`), and `_parse_clock_token` (`profile.py:219-232`) can parse `:30`. Minutes survive **inside** the profile, but no path ever sends them to `search_offers` — the LLM reconstructs integer `startHour` from `profile_in`, so `07:30 → startHour=7`, dropping `:30`.
- Booking-summary display also drops minutes: `templates.py:61-64` `_format_time_slot` → `f"{start_hour:02d}:00–{end_hour:02d}:00"`.
- The MCP `search_offers` schema itself lives in MCP_B2C (separate repo); the "integer hours only" constraint is confirmed indirectly via the leaf instruction and the always-`:00` handling.

---

## Claim 6 — Leaf call timeout is a fixed 10 s without retry; degradation path

**Verdict: TRUE.**

- Constant: `agents/b2c_concierge/b2c_concierge/agent.py:125` — `_LEAF_TIMEOUT = float(os.environ.get("CONCIERGE_LEAF_TIMEOUT_SECONDS", "10.0"))`
- Applied two ways, both **no retry**:
  1. httpx client timeout on the cached RemoteA2aAgent leg: `agent.py:170-176`.
  2. Authoritative deadline via `asyncio.timeout(_LEAF_TIMEOUT)` wrapping the whole A2A stream in `_run_leaf`: `agent.py:226` (docstring `:220-223`: httpx per-chunk timeout can't cap streaming totals, so `asyncio.timeout` is "the single owner of the 10 s deadline").
- **Degradation path:** any exception is caught at `agent.py:234`, logged, `_run_leaf` returns `(None, {})` (`:245`). The spine at `agent.py:701-704` emits `leaf_degraded_response` (`templates.py:162-174`) — zero-LLM honest message, no retry, no fallback search. The 10-s no-retry posture is a stated design invariant (`agent.py:121-124`: "audit lesson: today's prod stacks ~6 nested retries × 60 s").
- Related budgets: `_SYNTHESIS_TIMEOUT=15.0` with `_SYNTHESIS_NUM_RETRIES=1` at LiteLLM layer (`agent.py:126-128`); inline-MCP timeout 5.0 s no retry (`inline_tools.py:52`); leaf MCP timeout 5.0 s (`hotel_search_agent/agent.py:103`); Mapbox 1.5 s + 1 retry (`geocode_tool.py:43`, `mapbox_client.py:96`). No per-phase measurement feeds back into the leaf budget.

---

## Claim 7 — Price formatting from `priceEuro`; domain/locale/currency not propagated; lat/lon/distance dropped from cards

**Verdict: TRUE.**

- **Price from `priceEuro`, always EUR:** two identical formatters: `response_bridge.py:150-158` `_format_price_eur_cents` → `f"€{float(cents)/100:.2f}"`; `inline_tools.py:183-194` same, docstring admitting "display is always EUR… revisit if a user-currency preference is ever captured." `facade.normalize_hotels` (`facade.py:292-306`) re-formats any raw `priceEuro` to `€X.XX` in place. `_best_offer` picks min-`priceEuro` (`response_bridge.py:211-215`).
- **No domain/locale/currency propagation** into card construction (grep-confirmed, cf. Claim 2).
- **`normalize_hotel` card fields** (`response_bridge.py:233-268`): `id`, `hotel_id`, `name`, `city`, `country`, `stars`, `rating`, `amenities`, `image_urls`, `country_code` (only if server sends ISO alpha-2; `:255` notes search_offers sends none today), `price`, `timeslots`. **No `latitude`, `longitude`, or `distance`.** Same for `_normalize_hotel_for_display` (`inline_tools.py:212-227`).
- The geocoder *does* obtain lat/lon (`geocode_tool.py:158-159`), passed to `search_offers`, but **not carried into result cards** — dropped at normalization.

---

## Claim 8 — No reranker; first 5 MCP results as-is; shortlist storage

**Verdict: TRUE.**

- **First-5, no rerank:** `response_bridge.py:271-284` `normalize_search_results` — `[normalize_hotel(h) for h in (items or [])[:_MAX_RESULTS] ...]`, `_MAX_RESULTS = 5` (`response_bridge.py:53`). Slices `structured["results"]` directly — no sort, no scoring, no distance/relevance reranking. Server ordering preserved. (The local eval fixture pre-sorts by distance, so eval parity there is incidental, not earned.)
- **Shortlist storage flow:**
  - Leaf: `capture_after_tool` stashes normalized results in `tool_context.state["temp:hotel_search_results"]` (`response_bridge.py:374`), emitted as the A2A DataPart `{results, profile_delta}` by `emit_search_datapart` (`response_bridge.py:442-454`).
  - Orchestrator: `agent.py:712-714` — `record_search_outcome(...)` + `record_search_shortlist(profile, response["results"])`.
  - `record_search_shortlist` (`profile.py:567-589`) stores `profile.last_results = [{"hotel_id", "name"}, ...][:5]`. A non-empty result **replaces** the prior shortlist; empty leaves it untouched (`profile.py:571-577`).
  - `ground_truth.shortlist_hotels` (`ground_truth.py:67-74`) also takes `response["results"][:5]` — no reranking.

---

## Claim 9 — profile_in / profile_delta flow; LLM must copy country_anchor/state_anchor into geocode args

**Verdict: TRUE — the LLM must copy geo anchors itself; NO deterministic profile→geocode bridge (except amenities).**

**What the concierge sends the leaf:** the **entire** profile dict via `profile.to_dict()` at `agent.py:700`, but `query_params` sent **empty** (`agent.py:221`: `_attach_outgoing_datapart(ctx, {"query_params": {}, "profile_in": profile_in})`; comment `:219-220`: "its business schema… is S4's contract to fill, not S5's").

**Deterministic bridges from profile_in into leaf tool args — only ONE exists (amenities):**
- `equipment_ids._profile_amenities` (`equipment_ids.py:101-113`) deterministically decodes the inbound DataPart and reads `profile_in.amenities`; `enforce_equipment_filters` (`equipment_ids.py:144-178`) unions it into `hotelEquipmentIds`. Code-owned, LLM-independent.
- **No equivalent for `city`, `state_anchor`, `country_anchor`.** Only consumed via LLM prompt: `hotel_search_agent/agent.py:124-126` instructs the model to map `state_anchor`→`profile_state_context`, `city`→`profile_location_hint`, `country_anchor`→`country_code` and copy them into the `geocode_location` call. Exactly the audit's P0-#4 claim.

**`geocode_location` accepted keys** (`geocode_tool.py:54-62`): `city`, `zone`, `metro`, `country_code`, `raw_user_message`, `profile_state_context`, `profile_location_hint` — all LLM-supplied.

**`apply_profile_delta` accepted keys back** (`profile.py:273-361`): `city`, `state_anchor`, `country_anchor`, `budget_max`, `budget_request_source`, `timeslot`, `timeslot_start`, `timeslot_end`, `timeslot_request_source`, `amenities`, `language`. Does **not** accept `named_hotel`, date, zone, metro, currency, or coordinates.

**Leaf's profile_delta emission** (`emit_search_datapart`, `response_bridge.py:411-441`): remaps geocode guard's `last_city`→`city`, `last_state_context`→`state_anchor`, plus `country_anchor` (from resolved ISO code), `amenities`, `budget_max`+source, `timeslot_*`+source. `request_source` is **always** literal `"flexible_default"` (`response_bridge.py:78, 434, 440`); only the concierge P1 guard can upgrade to `"explicit"` (`profile.py:304-305`). HANDOFF notes this makes "bare number → explicit" effectively unreachable via the stateless leaf.

**Anchor round-trip mechanics:** `anchor_state_context` (`geo_guards.py:450-491`) reads prior `last_state_context`/`last_city` from `profile_in`, clears the anchor on a city change with no new state token (`:484-486`). Concierge-side `apply_profile_delta` also clears `state_anchor`/`country_anchor` when `delta.city` differs from stored city (`profile.py:284-289`). Anchor staleness is handled deterministically — but the initial copy into geocode args is LLM-dependent.

---

## Claim 10 — Pagination / "other options" mechanism

**Verdict: NONE exists.**

- Grep for `pagination`, `offset`, `cursor`, `other option`, `already.shown`, `exclude`, `seen_ids`, `next_page`, `show more`, `diversity` across `agents/**/*.py` (excl. tests): **no pagination mechanism** — only unrelated hits.
- No exclusion set, no cursor in `SessionProfile`. `last_results` is replaced (not appended) on each non-empty search, so it cannot accumulate "already shown" IDs.
- `search_offers` called with no offset/page param anywhere. "Other options" triggers `is_search_refinement_signal` → a fresh identical leaf search (`agent.py:650-651`); any diversity is LLM/backend nondeterminism. The audit's observed better diversity is luck, not a guaranteed mechanism.

---

## Deterministic guards inventory (as of today)

HANDOFF states "12/12 guards verts" (the 12 is the phase's own rollup). Concrete inventory:

**Leaf (hotel_search_agent) — geo guards:**
1. **Geocode echo-back** — `geocode_echo_matches`, `geo_guards.py:270-339`. Rejects a limit=1 result whose `place_name` doesn't echo the requested state / longest distinctive city-zone token.
2. **Generic-location demotion** — `is_generic_location_token`/`demote_generic_city`, `geo_guards.py:194-222`. Never geocodes "airport"/"downtown" as a city.
3. **State anchoring + state-hint resolution** — `anchor_state_context` (`geo_guards.py:450-491`), `resolve_state_hint` (`:112-159`), `extract_state_hint_from_text` (`:88-109`).
4. **US ZIP anchor** — `select_us_postal_anchor`, `geo_guards.py:388-444`, wired at `geocode_tool.py:110-113`.

**Leaf — tool guards:**
5. **Equipment-ID hard-filter enforcement** — `enforce_equipment_filters`/`inject_amenities_declaration`, `equipment_ids.py:116-178`.
6. **MCP circuit breaker** — `mcp_guard.py:60-96` + `CircuitBreaker` (`failure_threshold=3, cooldown_seconds=30`).
7. **Tool-call budget** — `make_tool_budget_callback(MAX_TOOL_CALLS=2)`, `hotel_search_agent/agent.py:78, 230`.

**Orchestrator (b2c_concierge):**
8. **Budget integrity (P1)** — `apply_profile_delta` + `_bare_number_value` + `_looks_like_time_derived_budget`, `profile.py:146-174, 299-307`.
9. **Timeslot sanitization (P6)** — `_split_one_sided_clock`/`_normalize_timeslot`, `profile.py:235-263`, applied `:311-349`.
10. **Auto-widen + search-exhaustion (S12)** — `maybe_auto_widen`, `profile.py:177-205`; terminal gate `agent.py:687-694`.
11. **Recovery-ack (P2)** — `is_search_refinement_signal`, `profile.py:425-450`; used `agent.py:625, 650`.
12. **Anti-clarification-loop (P10)** — `extract_final_question`/`questions_equivalent`, `profile.py:495-517`; orchestrated `agent.py:475-494`.
13. **Named-hotel lookup (S07)** — `resolve_hotel_reference`/`_strict`/`resolve_shortlist_ordinal`, `profile.py:592-685`; used in `inline_tools._resolve_hotel_id` (`inline_tools.py:120-163`).
14. **Booking confirmation (R9)** — `is_booking_confirmation_signal` (`profile.py:691-704`) + `generate_booking_link` (`inline_tools.py:375-413`); `confirmed` re-derived from server-side `pending_booking`.
15. **Amenity claim verifier (P7)** — `apply_amenity_truthfulness`/`amenity_claim_violations`, `amenity_guard.py:75-217`; wired `agent.py:496-501`.
16. **Ground-truth block** — `shortlist_ground_truth_block`, `ground_truth.py:77-87`.
17. **LLM budget** — `TurnBudget`, `budget.py` (`MAX_LLM_CALLS_PER_TURN=3`).

---

## Triage / routing (brief)

- **Families** (`triage.py:32`): `search, faq, details, compare, booking, ack`; fallback = `search` (`triage.py:33`).
- **Triage** (`triage.py:138-194`): one economy LLM classify (`{family, language}`, JSON, temp 0, 5 s timeout, no retry); regex `fallback_family` on failure (`triage.py:85-97`). Pure social message short-circuits to zero-LLM ack before triage (`agent.py:623-630`).
- **Routing table** (`routing.py:24-31`): `search`/`faq`→leaf (A2A), `details`→inline `get_hotel_details`, `compare`→inline `compare_hotels`, `booking`→inline `generate_booking_link`, `ack`→template. The LLM never routes.
- **Code-owned overrides** (`agent.py:642-651`, precedence order): (1) `is_booking_confirmation_signal` → `booking`; (2) `resolve_shortlist_ordinal` non-None → `booking`; (3) non-FAQ + `is_search_refinement_signal` → `search`.

---

## Already half-built toward these gaps (dormant / partial)

- **`select_us_postal_anchor`** — was dead code until S13; precedent that guards can ship dormant.
- **`resolve_state_hint` has a `country_resolved` parameter** (`geo_guards.py:121, 149`) distinguishing a *trusted* non-US country from an untrusted default — but `geocode_tool.py:115-122` calls it without passing `country_resolved` (defaults `True`). Trust distinction built but under-exercised.
- **Zone handling partial:** `geocode_location` accepts `zone`/`metro` (`geocode_tool.py:57-58`), folds `zone` into the Mapbox query (`geocode_tool.py:124-125`), `geocode_echo_matches` validates zone tokens — but zone/metro are **never persisted** to `SessionProfile`, so a zone is lost across turns.
- **`tool_loop.py`** exists, unit-tested, deliberately unwired (`agent.py:56-64`).
- **`country_anchor` round-trip fully built** concierge-side; only populates from the geocoder's resolved ISO code, and reaching the geocoder depends on the LLM copying it in (Claim 9).
- **Provenance machinery** (`budget_request_source`/`timeslot_request_source`) complete, but "bare number → explicit" practically unreachable through the stateless leaf.
- **`country_code` on hotel cards** preference-coded (`response_bridge.py:253-257`, `:341-344`); a market/country signal partly flows, but currency/domain do not.
