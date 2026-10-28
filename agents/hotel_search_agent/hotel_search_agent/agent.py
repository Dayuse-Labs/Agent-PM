"""hotel_search_agent — Dayuse B2C leaf agent (ADK + LiteLLM, portable).

Day-use hotel search for the b2c-concierge orchestrator: given structured query
params plus an inbound profile, it calls the read-only MCP_B2C tools
(`search_offers`, `find_hotel_by_name`) over Streamable HTTP and returns results
plus a profile delta (see contract.py — the leaf is STATELESS, decision B3: no
Redis, no session store; all state travels in the A2A DataPart).

Least privilege: `tool_filter` is an explicit allowlist of 2 of the 6 MCP_B2C
tools — the FAQ and booking-link tools belong to other components (faq-agent,
orchestrator inline tools) and must never be reachable from here.

S4 wired the geo guards + a real Mapbox client (geo_guards.py, mapbox_client.py,
geocode_tool.py) — `geocode_location` is a code-owned FunctionTool the model
calls before `search_offers` so `search_offers` gets real, guard-validated
lat/lon instead of the model's own world knowledge (MCP_B2C does no
geocoding server-side). The MCP circuit breaker (resilience.py, wired via
mcp_guard.py) degrades the 2 MCP tools honestly when MCP_B2C is down — a
clean diagnostic dict, never an exception.

S3 wired dayuse_agent_common: day-1 metrics callbacks (stdout +
llm_metric_events, no-op without DATABASE_URL, never any message content) and
the tool budget. The agent NAME is the metrics `service` label — b2c_ prefixed
so B2C rows are distinguishable from fleet rows in the shared Postgres.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from b2c_common import DEFAULT_MODEL, reasoning_kwargs_for
from b2c_common.observability import stamp_a2a_turn
from dayuse_agent_common import (
    llm_error_metric,
    llm_timing_after,
    llm_timing_before,
    tool_error_metric,
    tool_timing_after,
    tool_timing_before,
)
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

from hotel_search_agent.tool_budget_guard import make_per_tool_budget_callback
from hotel_search_agent.datetime_resolver import (
    inject_datetime_declaration,
    probe_next_day_after_tool,
    resolve_search_date,
    resolve_search_timeslot,
)
from hotel_search_agent.equipment_ids import (
    EQUIPMENT_IDS,
    enforce_equipment_filters,
    inject_amenities_declaration,
)
from hotel_search_agent.geocode_tool import geocode_location, inject_profile_geo_context
from hotel_search_agent.budget_injection import inject_profile_budget
from hotel_search_agent.occupancy import inject_profile_occupancy
from hotel_search_agent.standing import enforce_standing
from hotel_search_agent.completion import complete_thin_search_after_tool
from hotel_search_agent.relaxation import (
    apply_relax_request,
    inject_relaxation_declaration,
    read_relax_request,
    rescue_empty_search_after_tool,
)
from hotel_search_agent import named_hotel
from hotel_search_agent.mcp_guard import (
    mcp_circuit_after_tool,
    mcp_circuit_before_tool,
    mcp_circuit_on_error,
)
from hotel_search_agent.schema_guard import drop_args_outside_schema
from hotel_search_agent.response_bridge import (
    capture_after_tool,
    emit_search_datapart,
    inject_landmark_radius,
    inject_pagination_offset,
    skip_final_generation,
    stamp_turn_start,
)

# The only MCP_B2C tools this leaf may call, passed to McpToolset(tool_filter=...)
# so the other 4 server tools are never presented to the model.
ALLOWED_MCP_TOOLS = [
    "search_offers",
    "find_hotel_by_name",
]

# D3: LiteLLM model. B2C keeps its OWN departure default (b2c_common's — the
# lib's DEFAULT_MODEL is an OpenRouter slug and must never silently take over)
# and its OWN reasoning kwargs: the lib's `build_model` only knows the
# OpenRouter shape, while gpt-6-luna needs `reasoning_effort="none"` on the
# OpenAI-direct path or every tool call is a 400 (llm_params, probed 2026-10-15).
_MODEL_SLUG = os.environ.get("DAYUSE_MODEL", DEFAULT_MODEL)
MODEL = LiteLlm(model=_MODEL_SLUG, **reasoning_kwargs_for(_MODEL_SLUG))

# Hard cap on real tool calls per turn (the instruction says one reasoning pass;
# geocode_location + search_offers covers a destination search, find_hotel_by_name
# covers the named-hotel edge in 1). Beyond it the call is short-circuited
# deterministically — never a loop.
MAX_TOOL_CALLS = int(os.environ.get("HOTEL_SEARCH_MAX_TOOL_CALLS", "2"))

# The cap is PER TOOL, not a flat total (prod 2026-07-29 — see tool_budget_guard):
# a nominal turn already spends geocode_location + search_offers, so with a flat
# budget of 2 one failed geocode starved the search and the concierge reported a
# backend outage that never happened. Each tool keeps its own bounded retry.
MAX_GEOCODE_CALLS = int(os.environ.get("HOTEL_SEARCH_MAX_GEOCODE_CALLS", "2"))
MAX_MCP_CALLS = int(os.environ.get("HOTEL_SEARCH_MAX_MCP_CALLS", "2"))
PER_TOOL_CALL_LIMITS = {
    "geocode_location": MAX_GEOCODE_CALLS,
    "search_offers": MAX_MCP_CALLS,
    "find_hotel_by_name": MAX_MCP_CALLS,
}


def build_connection_params() -> StreamableHTTPConnectionParams:
    """Connection params for the MCP_B2C Streamable-HTTP server (read-only ES).

    MCP_B2C_AUTH_TOKEN travels as a standard RFC 6750 Bearer header (the
    server initially compared the raw header value and rejected the Bearer
    scheme; fixed server-side and deployed on 2026-07-17). It never enters
    the model context. Only send Authorization when a token is actually set:
    an empty value ("Bearer ") is an ILLEGAL header (h11 rejects the trailing
    whitespace) and would fail MCP session creation. .strip() guards a stray
    newline. Not validated eagerly — a bad URL/token fails loudly on the first
    tool call (connection is lazy, same pattern as the fleet leaves).

    The 5 s default timeout is this leaf's OWNED budget for its MCP dependency
    (single-owner rule); the circuit breaker lands on this path in S4.
    """
    token = os.environ.get("MCP_B2C_AUTH_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return StreamableHTTPConnectionParams(
        # Local placeholder default — dev points at the staging MCP_B2C via .env
        # (staging is OK to develop against, FORBIDDEN for the shadow-run).
        url=os.environ.get("MCP_B2C_URL", "http://localhost:8099/mcp"),
        headers=headers,
        timeout=float(os.environ.get("HOTEL_SEARCH_MCP_TIMEOUT_SECONDS", "5.0")),
    )


def build_mcp_toolset() -> McpToolset:
    return McpToolset(
        connection_params=build_connection_params(),
        tool_filter=ALLOWED_MCP_TOOLS,
    )


INSTRUCTION = """You are hotel_search_agent, the Dayuse day-use hotel search leaf.

You receive ONE search request as structured data: `query_params` (the search
intent — destination, dates, filters, or a hotel name) and `profile_in` (the
caller-owned user profile snapshot). You are STATELESS: you hold no session,
no memory of previous turns — everything you know about the user is in the
request, and everything you learned must be returned in the response.

How to act, frugally (at most ONE reasoning pass — no tool-call loops):
- A destination/area search → FIRST call geocode_location with `intent`: WHERE
  the user wants to search, as the message says it (each field is described in
  the tool). It is a deterministic, guarded tool — never geocode a destination
  yourself, and never rank or pick among places yourself. The system reads the
  user's message itself and checks every place you report against it, and it
  fills in the previous destination, state/city anchor, GPS bias, and the
  client's locale automatically from profile_in — you never need to copy any of
  those yourself. A FOLLOW-UP with no new destination in THIS message → send an
  empty `intent` ({{}}).
  How to fill `intent`:
  * Each place the user names goes in `places`: `mention` = their exact words,
    `kind` = what it is, `canonical` = its correct full name. A LANDMARK, a
    district, a station, a street or an address ("les champs élysées", "gare du
    nord", "times square", "boulevard de la république") is not a city: give
    it its own kind, and the tool has a dedicated lookup for it. When the user
    names a landmark by a SHORT form, `canonical` is its full name ("près de St
    Paul's à Londres" -> mention "St Paul's", canonical "St Paul's Cathedral",
    city "London"): the short form is also the name of smaller places elsewhere
    in that city, and the lookup would take the wrong one.
  * The city the user NAMES always goes in `city`, even when they write it
    inside the name of a place or right after an address ("Gare du nord Paris"
    -> city "Paris"; "Boulevard de la République Versailles" -> city
    "Versailles", place "Boulevard de la République").
  * A place's own `city` is your world knowledge, and it IS wanted when the
    place's NAME leaves no doubt about which city it is in ("les champs élysées"
    -> Paris, "le louvre" -> Paris, "times square" -> New York, "la sagrada
    familia" -> Barcelona), even when the user never typed the city: the tool
    uses it to aim the lookup and verifies it, so a wrong guess costs a rank and
    nothing more. Homonyms are decided by the tool (the geocoder), not by you.
  * A place NAMED AFTER A CITY IT IS NOT IN ("gare de lyon" is a station in
    PARIS, named after where its trains go): that city name is a false lead.
    When nothing else in the message says which city is meant, set
    `ambiguity.reason` to "city_needed" and give no city anywhere: the tool asks
    the user which one, and that question IS the right answer, while a confident
    guess there is a silent wrong answer nobody downstream can catch. This
    applies ONLY to that conflict. When the place IS in the city its name
    mentions ("vieux lyon" is in Lyon, "aéroport de nice" is in Nice), there is
    no conflict and no doubt: the city is known.
  * A country the user NAMED in words goes in `country_named`. The country you
    know a place is world-famously in ("les champs élysées" -> FR, "times
    square" -> US) goes in that place's `country`: a soft hint the tool scores
    and verifies, never a filter. Never coordinates: latitude and longitude only
    ever come from the tool.
  * A postcode the user writes goes in that place's `postal_code`, exactly as
    written, also when the postcode alone is the place ("dans le 75009" -> a
    place with mention "75009" and postal_code "75009").
  If it returns ok=False with error "geocode_ambiguous", DO NOT search: ask the
  user the exact clarifying question in its diagnostics (the place is a homonym).
  For any other ok=False, DO NOT call search_offers: relay its diagnostics
  honestly instead (never invent coordinates or guess a nearby city).
  If it returns ok=True, call search_offers with its latitude/longitude plus
  the rest of the query params, and fold its profile_delta into your own.
- `query_params.repeat_previous_search` true → the user only changed how prices
  are DISPLAYED (e.g. "show the prices in the local currency"). Repeat the
  previous search as-is: call geocode_location with an empty `intent`, then
  search_offers with no new filter — the destination, date and filters come back
  from profile_in automatically. Never ask a question on such a turn.
- Pass search_offers an `amenities` argument ONLY when the user asked FOR one
  or more amenities, using ONLY these canonical keys: {amenity_keys}. Include
  ONLY what the user asked for — never any other key from the list. A negated
  or excluded amenity ("sans piscine", "no pool") is NOT a request: do not
  include it and do NOT compensate with the remaining keys — when nothing was
  asked for, OMIT the argument entirely (an omitted argument means an
  unfiltered search, which is what an exclusion wants). Never set
  hotelEquipmentIds or roomEquipmentIds yourself: equipment-ID filters are
  code-owned and applied automatically from your `amenities` keys plus the
  request profile.
- Pass search_offers an `amenities_removed` argument (same canonical keys)
  when the user DROPS an amenity constraint ("enlève le spa", "finalement
  sans le spa", "drop the pool filter") or NEGATES one ("un hôtel sans
  piscine", "no pool") — the filters they stated on earlier turns are still
  applied, and this is the only way to take one back. Never put the same key
  in `amenities` and `amenities_removed`, and omit the argument entirely when
  nothing was dropped or negated.
- `amenities_must_have`: true ONLY when the user makes the amenities a strict
  condition ("only with a jacuzzi", "il me faut absolument un spa", or insisting
  after being told none had it). Otherwise omit it: when no hotel has a plain
  requested amenity, the system shows the closest ones without it and says so.
- `relax`: ONLY when THIS message asks to loosen the current search without a
  new value ("élargir la zone", "try a nearby area" -> "area"; "retirer un
  filtre", "quitar un filtro" -> "filters"; "une autre heure", "any time" ->
  "time"; "augmenter le budget", "increase the budget" -> "budget"). The system
  applies it to the search itself: never answer that you cannot widen or remove
  anything.
- An indoor or covered pool ("piscine intérieure", "piscine couverte", "indoor
  pool") is `indoor_pool`, never `pool`; a pool with no such word is `pool`.
- An amenity the user wants but marks as OPTIONAL ("idéalement un massage", "si
  possible avec piscine", "ideally a gym", "un jacuzzi serait un plus") goes in
  `amenities_preferred` (same canonical keys), NEVER in `amenities`: the system
  searches with it first and completes the page without it. A massage is
  `spa`. Omit the argument when no wish is marked optional.
- `standing`: "upscale" when the user wants a chic, luxury, high-end or very
  classy hotel or room ("très classe", "haut de gamme", "luxe", "une chambre
  hyper belle", "something fancy"); "any" when they drop a standing they stated
  earlier ("peu importe le standing"). The system turns it into a star filter:
  never set `starRatings` yourself. Omit `standing` when the message says
  nothing about it — a standing stated earlier is carried forward automatically.
- Pass search_offers a `priceRangeMax` (a number, in euros) ONLY when the user
  states an explicit maximum budget ("under 80 euros", "max 120€", "no more
  than 90€"); also pass `priceRangeMin` if they give a lower bound too. Pass
  search_offers a `timeSlot` with `startHour`/`endHour` (0-23) ONLY when the
  user states explicit clock hours ("between 2pm and 8pm", "from 14h to 20h",
  "checkout by 6pm"), plus `startMinute`/`endMinute` (0/15/30/45) ONLY when
  they state minutes too ("7:30am", "13h30"). NEVER invent a budget or a time
  slot the user did not state, and do NOT turn a vague "cheaper"/"earlier"
  into a number — when none is mentioned, OMIT these arguments (an omitted
  argument means no budget or time-slot constraint).
- Pass search_offers `adults` and/or `children` (whole numbers) ONLY when the
  user states who is travelling ("2 adults and 1 child", "pour deux", "on est
  4", "with my wife and our baby"). A CHILD'S AGE IS NOT A COUNT: "ma fille de
  8 ans" is children=1, never children=8. A bare group size with no breakdown
  ("on est 4") is adults=4. COUNT THE SPEAKER when they include themselves:
  "avec ma femme"/"with my wife" is adults=2 (them plus one), "moi et mes deux
  amis" is adults=3 — a named companion is an ADDITIONAL adult, never the only
  one. A baby or an infant is children=1, never an adult.
  NEVER invent a party size the user did not state —
  when nobody is mentioned, OMIT both arguments: these are MINIMUM-capacity
  filters, so a guessed `adults=1` silently hides offers the user never
  excluded. You do not need to repeat a party size already established earlier
  in the conversation — the system carries it forward automatically.
- A DURATION ("for 1 hour", "for 30 minutes", "pour 2 heures") is NOT a clock
  time: pass it as `duration` (ISO-8601, e.g. "PT1H", "PT30M") — NEVER as
  `timeSlot` and NEVER converted into a start/end window yourself ("for 1
  hour" is not "00:00-01:00"). The system computes any real window from it.
- `date`: LABEL what the user said, you never resolve it. It has 3 fields:
  `type`, `value`, and `expression` (their exact wording). For
  "today"/"tomorrow"/"the day after tomorrow"/a bare weekday, set
  type="relative" and value to one of: today, tomorrow, day_after_tomorrow, or
  an English weekday name (a weekday name always means its NEXT occurrence,
  never today). For an explicit calendar date ("the 28th", "July 28",
  "2026-08-05"), set type="absolute" and value to YYYY-MM-DD if they gave a
  year, else MM-DD — NEVER add or guess a year yourself. A count from now
  ("in 2 weeks", "dans 3 jours") is type="offset" with value "P2W" / "P3D". A
  month named without its day ("en novembre", "mes de noviembre") is
  type="month" with value MM. A day left open ("peu importe le jour", "any
  date", "da igual") is type="flexible" with value "any"; ruling out today
  only ("pas pour aujourd'hui", "nicht für heute") is type="flexible" with
  value "not_today". A CORRECTION of the day counts: label the new one. OMIT
  `date` entirely when no day/date is mentioned at all — the system keeps
  searching the same date already established, or today if none was ever
  given.
- A FOLLOW-UP that only changes the date/budget/filters, or just asks for OTHER
  options, with NO new destination (e.g. "for the 28th instead", "cheaper",
  "earlier", "any other options") → still call geocode_location first (with an
  empty `intent`, per above) then run a fresh search with the new constraint. Do
  not ask the user to repeat the city they already gave.
- A message that starts with "EARLIER REQUEST" and/or "YOU ASKED" is the user
  REPLYING to the question you asked on the previous turn. Read the earlier
  request and the reply as ONE message: every criterion of the earlier request
  (date, hours, budget, amenities, party) still applies unless the reply
  changes it, and so does the place it named. A bare "yes"/"oui" accepts what
  the question proposed.
- `query_params.clarification`, when present, is the place question the system
  asked on the previous turn (its kind, its subject and the options it offered),
  and THIS message answers it. Read it as data, only to understand the reply:
  never copy it, its subject, its options or their labels into a tool argument.
  A city the user types in the reply goes in `intent` as they typed it; an option
  the user picks by its number or its position is applied by the system, so
  name no place for it.
- A specific hotel named by the user (`query_params.hotel_name`, when set, is
  that name) → call find_hotel_by_name directly (no geocoding needed): `name`,
  `cityName` = the city THIS message places it in, by its English or local
  name ("London", never "Londres"; omit it when none), and the
  same `date` label as for search_offers. A hotel name is never a place of
  geocode_location's `intent`. Once
  it is found, the system shows it with its offers and its nearest neighbours
  itself — do not call search_offers after it. AmbiguousHotelError → if THIS
  message names a city, call it ONCE more with that cityName; otherwise stop,
  the system asks the user which hotel. HotelNotFoundError with a city in THIS
  message → geocode_location + search_offers on that city, so the user sees
  other hotels there (the system tells them the named one was not found).
- On a SUCCESSFUL search, reply with a SHORT one-line outcome in plain language
  (how many day-use offers, and in which city). Do NOT format a detailed hotel
  list and NEVER paste the raw tool payload — the structured top-5 results are
  attached to the response for the caller AUTOMATICALLY, and the caller has a
  strict latency budget, so keep this text to a single sentence.
- On FAILURE (geocode ok=False, no offers, or MCP_B2C degraded), do NOT call
  further tools: explain honestly in one or two sentences what happened.

Never fabricate hotels, prices, availability, or coordinates: only report what
the tools returned. If the request lacks enough to search, say so plainly
instead of guessing.""".format(amenity_keys=", ".join(EQUIPMENT_IDS))
# ^ .format at module level: the instruction stays a plain str (the A2A card
#   builder rejects a callable) and can never drift from the enum the model
#   is offered in the widened search_offers declaration.


def inject_today_before_model(callback_context: Any, llm_request: Any) -> None:
    """Injects TODAY into the model's context on every LLM call — informational
    only. S-G6: the model has no clock and must NEVER compute or convert a
    date/duration itself (the historic bug this replaces: the model resolving
    "tomorrow"/"for 1 hour" into a concrete date/window itself, error-prone
    exactly like the S10 negation-inversion lesson generalizes — never trust
    LLM arithmetic on a value code can compute deterministically). The actual
    resolution — against the CLIENT's own timezone when known, never just this
    server's clock — happens in code (datetime_resolver.resolve_search_date),
    using the `date`/`duration` LABELS the model extracts per the instruction.
    Done here (not via a callable instruction) because the A2A card builder
    regex-scans `instruction` and rejects a callable."""
    today = date.today()
    llm_request.append_instructions(
        [
            f"TODAY is {today.isoformat()} ({today.strftime('%A')}), for context only — you have "
            "no clock and must NEVER compute a calendar date or a time window yourself. Always "
            "emit the `date`/`duration`/`timeSlot` fields exactly as labels of what the user "
            "said (see their descriptions); the system resolves them."
        ]
    )
    return None

_MCP_TOOLSET = build_mcp_toolset()

# The dated search that follows a hotel found by name (named_hotel.py) goes
# through the same callbacks as a search the model makes.
named_hotel.bind(
    _MCP_TOOLSET,
    search_before=[
        mcp_circuit_before_tool,
        enforce_equipment_filters,
        enforce_standing,
        inject_profile_occupancy,
        inject_profile_budget,
        inject_pagination_offset,
        inject_landmark_radius,
        resolve_search_date,
        resolve_search_timeslot,
        drop_args_outside_schema,
    ],
    search_after=[mcp_circuit_after_tool, probe_next_day_after_tool, capture_after_tool],
)

# Metrics callbacks (fleet contract, booking_qa precedent). Deliberately NO
# switch_model_callback: B2C serves the public — a per-request MODEL: override
# must never be honored here.
root_agent = Agent(
    name="b2c_hotel_search",
    model=MODEL,
    description=(
        "Searches Dayuse day-use hotel offers (by destination or by hotel name) via the "
        "read-only MCP_B2C server; stateless — profile in/out through the A2A DataPart."
    ),
    instruction=INSTRUCTION,
    # Stateless leaf, enforced (latency audit 2026-07-28): the model sees ONLY
    # the current turn — its user text + profile DataPart + this turn's tool
    # calls (ADK 'none' = _get_current_turn_contents, verified). All cross-turn
    # state travels in profile_in by contract; without this, any A2A caller
    # reusing a contextId regrows the prompt with the whole session history.
    include_contents="none",
    tools=[_MCP_TOOLSET, geocode_location],
    # S-G4: stamps t0 for the turn's total-ms counter (emit_search_datapart logs
    # it) — runs before anything else so it covers every path, not just search.
    # stamp_a2a_turn gives the leaf's root observation (opened by
    # A2aTurnObservation in serve.py) the inbound request as its input, and
    # mirrors the inbound A2A dayuse_trace_id as the Langfuse session id
    # (no-op unless tracing is enabled in serve.py).
    before_agent_callback=[stamp_turn_start, stamp_a2a_turn],
    # skip_final_generation is FIRST: once the search tool has run, it short-circuits
    # the model's wasted final-prose call (emit_search_datapart overwrites that prose
    # and the orchestrator re-synthesizes anyway) — 3 → 2 internal LLM calls. Being
    # first means a skipped call never stamps an orphaned llm_timing_before timer
    # (the short-circuit returns before after_model_callback/llm_timing_after runs).
    # inject_today_before_model gives the (clockless) model TODAY for context
    # only (S-G6: it must never compute a date/window itself — see the
    # function's own docstring). inject_amenities_declaration /
    # inject_datetime_declaration widen the search_offers declaration with the
    # virtual `amenities`/`date`/`duration`/timeSlot-minutes params
    # (skip_final_generation staying first means a short-circuited final call
    # correctly skips both injections too).
    before_model_callback=[
        skip_final_generation,
        llm_timing_before,
        inject_today_before_model,
        inject_amenities_declaration,
        inject_relaxation_declaration,
        inject_datetime_declaration,
        named_hotel.inject_named_hotel_declaration,
    ],
    after_model_callback=[llm_timing_after],
    on_model_error_callback=llm_error_metric,
    # Order matters: timing stamps t0 first; the budget callback short-circuits
    # a tool beyond ITS own cap (PER_TOOL_CALL_LIMITS); the MCP circuit guard
    # short-circuits the 2 MCP
    # tools while the breaker is open. First non-None wins (ADK semantics).
    # enforce_equipment_filters / inject_profile_geo_context / inject_pagination_offset /
    # resolve_search_date / resolve_search_timeslot are LAST: each mutates args
    # in place for its own tool (equipment ids, geocode_location's
    # state/locale/proximity — its place comes from the `GeoIntent` and is
    # completed from profile_in by the tool itself, QA14707 Q07 — search_offers'
    # `from`/`date`/`timeSlot`), so
    # they must only run when the call proceeds — order between them doesn't
    # matter, they touch disjoint tool names/keys.
    before_tool_callback=[
        tool_timing_before,
        make_per_tool_budget_callback(PER_TOOL_CALL_LIMITS, MAX_TOOL_CALLS),
        mcp_circuit_before_tool,
        # Point 3: pops `relax`/`amenities_must_have`; « area » feeds the ring.
        read_relax_request,
        enforce_equipment_filters,
        enforce_standing,
        inject_profile_occupancy,
        inject_profile_budget,
        inject_profile_geo_context,
        inject_pagination_offset,
        inject_landmark_radius,
        resolve_search_date,
        resolve_search_timeslot,
        named_hotel.prepare_named_hotel_lookup,
        # Point 3: « retirer un filtre / augmenter le budget », once every
        # writer of the arguments has run.
        apply_relax_request,
        # LAST: the virtual params are gone by now; anything else the tool's
        # published schema does not declare would make MCP refuse the call.
        drop_args_outside_schema,
    ],
    # capture_after_tool is LAST: it may return a truncated payload (which breaks
    # the after-tool chain), so it must never run before mcp_circuit_after_tool
    # observes the real tool outcome. It stashes normalized results + the geocode
    # profile_delta and shrinks the ~24k-token search_offers payload the model
    # ingests (response_bridge.py).
    # probe_next_day_after_tool sits between them (S-CX6): it must see the real
    # outcome (so after the breaker's observer) and run BEFORE capture_after_tool,
    # which is what consumes the D+1 payload it stashes. It is async — ADK
    # awaits an awaitable one mixed among sync ones — and it always returns
    # None, so it never breaks the chain.
    # complete_thin_search_after_tool (prod session 1eb2430a) follows the same
    # rules, and never fires on the dead end the D+1 probe handles.
    after_tool_callback=[
        tool_timing_after,
        mcp_circuit_after_tool,
        probe_next_day_after_tool,
        # Point 3: an EMPTY first page is relaxed step by step (≤ 2 MCP calls,
        # the probe's included); the completion stands down after it.
        rescue_empty_search_after_tool,
        complete_thin_search_after_tool,
        named_hotel.follow_named_hotel,
        capture_after_tool,
    ],
    on_tool_error_callback=[tool_error_metric, mcp_circuit_on_error],
    # Emits the structured {results, profile_delta} A2A DataPart the orchestrator
    # decodes — the leaf's prose answer alone left `hotels` empty (S4/S5/S6 gap).
    after_agent_callback=[emit_search_datapart],
)
