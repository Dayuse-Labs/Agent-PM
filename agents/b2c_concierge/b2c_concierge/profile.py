"""Typed session profile of the b2c-concierge spine + its deterministic guards.

The profile is orchestrator-owned state (the leaves are stateless — decision B3):
it travels OUT to a leaf as `profile_in` and comes back as `profile_delta` (the
A2A DataPart envelope, see a2a_datapart.py), never the reverse. Storage is
Redis (profile_store.py); this module is pure and Redis-free on purpose so the
guards stay unit-testable without a broker.

Two guards port the P1/P6 production-audit fixes from agent-usa onto this
schema (behavior ported, not code — the old implementation lived in a very
different, workflow-based architecture):
  - budget integrity: a bare-number reply ("180", "$40") is ALWAYS the user's
    explicit budget, regardless of what a leaf's own extraction claims, and an
    explicit budget is never silently auto-widened;
  - timeslot sanitization: a one-sided clock label ("15:00-") is salvaged into
    a start/end bound, never persisted as a corrupted free-text string; an
    anchored bound (e.g. an end-only "before 9am") is never inverted by a
    later turn's re-extraction that carries no new time-of-day text.

S06 adds two more, both deterministic and code-owned (never LLM-decided):
  - recovery-ack (P2): a bare "ok"/"sure" is NEVER a social celebration when
    the last search came back empty — the ack fast-path must be disabled so
    the turn re-runs the search instead of dead-ending on a canned template.
    Matching is against the PERSISTED `last_suggestions` list (code-set when a
    search returns zero results), never a regex over the assistant's own
    prose (agent-usa's older approach — the synthesis text here is
    LLM-authored and streamed, so its exact wording is not a stable regex
    target).
  - anti-clarification-loop (P10): `extract_final_question`/
    `questions_equivalent` are the pure detectors the spine (agent.py) uses
    to notice a synthesized reply repeats the PREVIOUS turn's trailing
    question — the retry-then-strip orchestration itself lives in agent.py
    since it must re-invoke the synthesis LLM, which this module intentionally
    stays free of (guards here are pure, Redis/LLM-free, unit-testable alone).

S07 adds the `_last_results` equivalent this spine was structurally missing
(S06's HANDOFF noted the difference from agent-usa on purpose — inline tools
now need it back):
  - named-hotel lookup: `resolve_hotel_reference`/`resolve_hotel_references`
    fuzzy-match a hotel mentioned in a message against the PERSISTED on-screen
    shortlist (`last_results`, set by `record_search_shortlist`) before the
    caller (inline_tools.py) falls back to the MCP `find_hotel_by_name` tool —
    a hotel this session just recommended must never dead-end.
  - booking confirmation (R9, guard #12): `is_booking_confirmation_signal`
    is the ack-fast-path override for a bare "yes"/"ok" while `pending_booking`
    is set — symmetric to `is_search_refinement_signal` (P2). The actual
    confirmed=false/true decision is NEVER made from this signal alone: it
    is re-derived in code from `pending_booking` at the inline-tool call site
    (inline_tools.py) — this function only keeps the turn from being swallowed
    by the zero-LLM ack template before it can reach that gate.

S-G1 (2026-07-23 geo/multi-turn remediation, arbitrated option A3-a) widens
the schema with the audit-identified missing slots (`named_hotel`, `zone`,
`metro`, `date`/`date_reference`, `currency`/`locale`/`domain`,
`search_anchor`, `distance_origin`, `shown_hotel_ids`, `search_cursor`) and
turns `apply_profile_delta` into a typed-ops reducer: any slot MAY arrive as
`{"op": "set"|"clear", "value": ...}` instead of a bare value — an explicit,
auditable clear, never a silent loss (SOM-DST/Diable carryover-by-default
semantics, preferred over RFC-7386 null-as-clear because a bare `null` from
an LLM extraction is error-prone, cf. the S10 negation-inversion lesson).
A slot simply ABSENT from the delta is always carryover. The leaf still
emits today's flat `{key: value}` shape (it migrates in S-G5/S-G6) — that
shape is treated as an implicit "set", so nothing here breaks in the
meantime. A city change clears the geo-scoped slots (`zone`/`metro`/
`search_anchor`/`state_anchor`/`country_anchor`) and resets the pagination
state (`shown_hotel_ids`/`search_cursor`); a zone-only change deliberately
keeps everything else (date/timeslot/budget/amenities) — the audit's
"context lost on a suburb change" failure.
"""
from __future__ import annotations

import logging
import re
from dataclasses import MISSING, dataclass, field
from typing import Any

BUDGET_SOURCE_EXPLICIT = "explicit"
BUDGET_SOURCE_FLEXIBLE_DEFAULT = "flexible_default"

AUTO_WIDEN_STREAK_THRESHOLD = 2
AUTO_WIDEN_FACTOR = 1.5
AUTO_WIDEN_MAX_ATTEMPTS = 2

# S-G1: profile schema version stamped on the outgoing `profile_in` DataPart
# (`to_dict()`) so leaf and concierge can evolve independently (ISE A2A
# pattern) — NOT a SessionProfile field itself, tolerated-but-ignored on the
# way back in (`from_dict`/`apply_profile_delta` both silently drop unknown
# keys).
PROFILE_SCHEMA_VERSION = "2.0"

# S-G1: pagination exclusion set cap (`shown_hotel_ids`) — oldest ids drop
# first once a session has been shown more hotels than this across turns.
MAX_SHOWN_HOTEL_IDS = 25

_metrics_logger = logging.getLogger("b2c_concierge.metrics")

# Recovery suggestions (P2): code-owned, localized (7 languages since UX2,
# 2026-08-27) — set on the profile the moment a search returns zero results so
# a later bare "ok"/"sure" can be matched against them deterministically
# (never against the LLM's own prose). Matching (`is_search_refinement_signal`
# below) is a verbatim membership check against the PERSISTED list, so it
# works identically whatever language the labels are in.
_RECOVERY_SUGGESTIONS: dict[str, list[str]] = {
    "fr": ["augmenter le budget", "élargir la zone", "retirer un filtre"],
    "en": ["increase the budget", "try a nearby area", "remove a filter"],
    "es": ["aumentar el presupuesto", "ampliar la zona", "quitar un filtro"],
    "it": ["aumentare il budget", "ampliare la zona", "rimuovere un filtro"],
    "de": ["Budget erhöhen", "Umkreis erweitern", "einen Filter entfernen"],
    "pt": ["aumentar o orçamento", "alargar a zona", "retirar um filtro"],
    "nl": ["budget verhogen", "gebied vergroten", "een filter verwijderen"],
}

# S-CX6: a SAME-DAY dead end has exactly one cure, and it is not in the trio
# above — day-use booking cutoffs land on the stay date itself (latest ~16h
# local, measured), so from mid-afternoon "today" is closed market-wide and
# budget/zone/filter chips send the user chasing a problem that isn't there.
# The fr/en labels are deliberately worded so `_DATE_MENTION_RE` ALSO matches
# them as a belt-and-suspenders path when they come back as a message (a
# click then relaunches a dated search through the refinement path that
# already exists, with no new plumbing) — that regex stays fr/en-only
# (out of UX2's scope), so the 5 new languages rely solely on the verbatim
# membership check above, which is unconditional and sufficient on its own.
_DATE_SUGGESTIONS: dict[str, list[str]] = {
    "fr": ["voir demain", "après-demain", "élargir la zone"],
    "en": ["see tomorrow", "the day after tomorrow", "try a nearby area"],
    "es": ["ver mañana", "pasado mañana", "ampliar la zona"],
    "it": ["vedi domani", "dopodomani", "ampliare la zona"],
    "de": ["morgen ansehen", "übermorgen", "Umkreis erweitern"],
    "pt": ["ver amanhã", "depois de amanhã", "alargar a zona"],
    "nl": ["morgen bekijken", "overmorgen", "gebied vergroten"],
}

# A bare affirmative — narrower than triage.is_social_ack (which also matches
# greetings/thanks/farewells): only THESE words, alone, signal "yes, do that"
# and must be reinterpreted as a search refinement when the screen is empty.
_AFFIRMATIVE_RE = re.compile(
    r"^\s*(?:ok(?:ay)?|d'accord|sure|yes|yeah|oui|super|parfait|great|perfect|cool)"
    r"[\s!,.?;:🙂😊👍❤️✨]*\s*$",
    re.IGNORECASE,
)


def is_bare_affirmative(message: str, llm_affirmative: bool | None = None) -> bool:
    """True when `message` is ONLY an affirmative token, nothing else — the
    search-exhaustion gate's inverse of this decides whether a reply carries
    a new constraint worth retrying the search for (S12 audit 2026-07-20).

    P1-1: `llm_affirmative` is triage's `affirmative` slot (None when the
    classify produced nothing usable). It is applied ADDITIVELY — it can only
    turn a False into a True, never the reverse.

    Additive rather than "LLM primary, regex fallback" on purpose. The regex is
    anchored `^…$` over a closed word list, so on the cases it already matches
    it is not merely a heuristic, it is exact — there is nothing for a model to
    correct. What it cannot do is match "sí"/"sì"/"ja", and that is precisely
    what the slot adds. Letting the model also VETO a match would put the ~150
    guard tests at the mercy of one classify call for zero upside; this way they
    stay green by construction and the new signal is pure coverage.
    """
    return bool(llm_affirmative) or bool(_AFFIRMATIVE_RE.match((message or "").strip()))


# Explicit confirmation phrasing — ONLY consulted while `pending_booking` is
# set (is_booking_confirmation_signal). The R9 prompt literally asks
# « Confirmez-vous cette réservation ? », so users echo a confirmation VERB
# ("oui je confirme", "je valide", "yes I confirm") — which the bare-affirmative
# regex above rejects by design, and prod 2026-07-28 answered with the greeting
# template instead of the link. Kept verb-anchored (confirm/valide/réserve/
# book/vas-y), never a lone "oui" inside a sentence.
_CONFIRMATION_RE = re.compile(
    r"\b(?:confirm\w*|valide[rsz]?|r[ée]serve[rz]?|book(?:\s+it)?|vas[- ]?y|allons[- ]?y|go)\b",
    re.IGNORECASE,
)
# Refusals/changes of mind that may still contain a confirmation verb
# (« non je ne confirme pas », "cancel the booking") — these must NEVER route
# to the confirmation gate: a false positive would generate the link.
_CONFIRMATION_NEGATION_RE = re.compile(
    r"\b(?:non|ne|n'|pas|plus|jamais|annul\w*|cancel\w*|attend\w*|wait|stop|autre|chang\w*|plut[oô]t)\b"
    r"|n'",
    re.IGNORECASE,
)


@dataclass
class SessionProfile:
    """One session's accumulated search context — the orchestrator's only
    state; the leaves never store this (stateless contract, decision B3)."""

    city: str | None = None
    state_anchor: str | None = None
    country_anchor: str | None = None
    budget_max: float | None = None
    budget_request_source: str | None = None
    timeslot: str | None = None
    timeslot_start: str | None = None
    timeslot_end: str | None = None
    timeslot_request_source: str | None = None
    timeslot_mode: str | None = None  # "start_only" | "end_only" | "range"
    amenities: list[str] = field(default_factory=list)
    language: str | None = None
    consecutive_empty_searches: int = 0
    auto_widen_disclosure: dict[str, float] | None = None
    widen_attempt_count: int = 0
    search_exhausted: bool = False
    last_suggestions: list[str] | None = None
    last_clarifying_question: str | None = None
    last_results: list[dict[str, Any]] | None = None
    pending_booking: dict[str, Any] | None = None
    amenity_claim_corrections: dict[str, list[str]] | None = None
    # S-PERF5: the angle key the synthesis led on last turn, so the next one
    # picks a different fact instead of repeating it near-verbatim when the
    # shortlist barely moved (ground_truth.synthesis_angle).
    last_synthesis_angle: str | None = None
    # S-G1 (2026-07-23): audit-identified missing slots — all optional, all
    # absent-tolerant, so a leaf that hasn't migrated yet (S-G5/S-G6) never
    # breaks by omitting them.
    named_hotel: dict[str, Any] | None = None  # {hotel_id, name, source}
    zone: str | None = None
    metro: str | None = None
    date: str | None = None  # ISO 8601
    date_reference: dict[str, Any] | None = None  # {expression, resolved_from, client_tz}
    currency: str | None = None
    locale: str | None = None
    domain: str | None = None
    search_anchor: dict[str, Any] | None = None  # {type, lat, lon, label, set_at_turn}
    distance_origin: dict[str, Any] | None = None  # {latitude, longitude, label, type}
    shown_hotel_ids: list[Any] = field(default_factory=list)
    search_cursor: int = 0
    # S-G6 (2026-07-23): the client's own IANA timezone (facade native-context
    # intake, `getClientTimeContext()` — S-G2 confirmed it is sent every
    # request but punted its "home" to this session). A dedicated, carryover
    # field rather than nesting solely under `date_reference.client_tz`: a
    # date can only be resolved AFTER a label is extracted, but the timezone
    # is needed for the FIRST resolution too, so it must be readable from
    # turn 1 independent of whether any date has been mentioned yet. Also
    # copied into `date_reference.client_tz` at the moment a date IS resolved
    # (the leaf, `datetime_resolver.resolve_search_date`), so a specific
    # resolution's provenance stays self-contained.
    client_timezone: str | None = None
    # S-CX5: a hotel the USER clicked (a pick button carries its id in the
    # request body). One-shot turn state, not a preference: the spine reads it
    # and clears it within the same turn. It lives on the profile because that
    # is the only channel between the facade's intake and the spine — and
    # resolving a click BY ID is the point: the label the button also sends is
    # for the transcript, never for matching.
    picked_hotel_id: int | None = None
    # P0-1 (audit 2026-07-30 §2): party size, carried across turns. The leaf
    # already emits adults/children to search_offers ~78% of the time on the
    # turn they are stated (measured, OBS6 baseline) — what was missing is a
    # slot to remember them in, so turn 2 ("moins cher") stopped filtering on
    # capacity. Both stay None until the user states a party size: an unstated
    # occupancy must never become adults=1, because search_offers reads these
    # as MINIMUM-capacity filters and would silently drop valid inventory.
    # `children = 0` is a real statement ("adults only"), distinct from None.
    adults: int | None = None
    children: int | None = None
    # Prices are shown in EUR unless the user asked for the hotel's own
    # currency ("HOTEL"), kept for the rest of the conversation until they ask
    # for euros again (product decision 2026-09-25).
    display_currency: str | None = None
    # mcp-dayuse#8, option B: "morning" | "afternoon" | "evening" — a soft
    # time filter read in code by the leaf, exclusive with a clock window.
    daypart: str | None = None
    # mcp-dayuse#7: the hotels the last turn asked the user to choose between
    # (a name several hotels share). Read on the next turn only, then cleared.
    named_candidates: list[str] | None = None
    # mcp-dayuse#7: a homonym the last turn asked about (« which Manhattan? »)
    # with the options offered, so the answer completes it. Next search only.
    pending_place: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "city": self.city,
            "state_anchor": self.state_anchor,
            "country_anchor": self.country_anchor,
            "budget_max": self.budget_max,
            "budget_request_source": self.budget_request_source,
            "timeslot": self.timeslot,
            "timeslot_start": self.timeslot_start,
            "timeslot_end": self.timeslot_end,
            "timeslot_request_source": self.timeslot_request_source,
            "timeslot_mode": self.timeslot_mode,
            "amenities": list(self.amenities),
            "language": self.language,
            "consecutive_empty_searches": self.consecutive_empty_searches,
            "auto_widen_disclosure": self.auto_widen_disclosure,
            "widen_attempt_count": self.widen_attempt_count,
            "search_exhausted": self.search_exhausted,
            "last_suggestions": self.last_suggestions,
            "last_clarifying_question": self.last_clarifying_question,
            "last_results": self.last_results,
            "pending_booking": self.pending_booking,
            "amenity_claim_corrections": self.amenity_claim_corrections,
            "last_synthesis_angle": self.last_synthesis_angle,
            "named_hotel": self.named_hotel,
            "zone": self.zone,
            "metro": self.metro,
            "date": self.date,
            "date_reference": self.date_reference,
            "currency": self.currency,
            "locale": self.locale,
            "domain": self.domain,
            "search_anchor": self.search_anchor,
            "distance_origin": self.distance_origin,
            "shown_hotel_ids": list(self.shown_hotel_ids),
            "search_cursor": self.search_cursor,
            "client_timezone": self.client_timezone,
            "picked_hotel_id": self.picked_hotel_id,
            "adults": self.adults,
            "children": self.children,
            "display_currency": self.display_currency,
            "daypart": self.daypart,
            "named_candidates": self.named_candidates,
            "pending_place": self.pending_place,
            "schema_version": PROFILE_SCHEMA_VERSION,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionProfile":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)


# Profile slots the LEAVES never read (verified against every `profile_in`
# consumer in the leaf packages, 2026-07-28: geocode_tool, datetime_resolver,
# equipment_ids, response_bridge; the faq leaf reads nothing at all). They are
# concierge-internal turn state — and the whole profile_in lands VERBATIM in
# the leaf's LLM prompt (DataPart text/*), so every extra byte here is prompt
# tokens paid on both leaf LLM calls, every turn. `last_clarifying_question` /
# `last_suggestions` also carry message-derived content that has no business
# shipping to the leaf (GDPR: data minimization).
_CONCIERGE_ONLY_KEYS = (
    "pending_booking",
    "last_suggestions",
    "last_clarifying_question",
    "amenity_claim_corrections",
    "last_synthesis_angle",
    "auto_widen_disclosure",
    "named_hotel",
    "distance_origin",
    "picked_hotel_id",
    "display_currency",
    "named_candidates",
)


def leaf_profile_view(profile: SessionProfile) -> dict[str, Any]:
    """The A2A copy of the profile — NOT the profile. Redis, the booking card,
    the picks and the ground-truth block all keep reading the full
    `profile.last_results` (offer identity, price, photo, rating, S-CX5);
    only what travels to the leaf is slimmed.

    `last_results` shrinks to `{hotel_id, name}` per entry: the leaf uses the
    shortlist solely as model-visible context for name references — the offer
    identity the booking path needs never leaves the concierge. Measured
    before this view existed (S-CX5 shortlist, 5 hotels): ~+535 prompt tokens
    per leaf LLM call, ×2 calls per turn, growing with every prior turn still
    replayed."""
    view = profile.to_dict()
    for key in _CONCIERGE_ONLY_KEYS:
        view.pop(key, None)
    view["last_results"] = [
        {"hotel_id": entry.get("hotel_id"), "name": entry.get("name")}
        for entry in (profile.last_results or [])
        if isinstance(entry, dict)
    ] or None  # keep the slot's no-shortlist shape (None, not [])
    return view


def _slot_default(name: str) -> Any:
    """The dataclass-declared zero-value for `name` — what an explicit
    `{"op": "clear"}` resets a slot to (its own natural "nothing here" value,
    e.g. `None` for an optional field, `[]` for `shown_hotel_ids`, `0` for
    `search_cursor`)."""
    f = SessionProfile.__dataclass_fields__[name]
    if f.default_factory is not MISSING:
        return f.default_factory()
    if f.default is not MISSING:
        return f.default
    return None


# --- Budget integrity (P1) --------------------------------------------------

_BARE_NUMBER_RE = re.compile(r"^\s*[$€£]?\s*(\d+(?:[.,]\d+)?)\s*[$€£]?\s*$")


def _bare_number_value(message: str) -> float | None:
    """The message IS a plain number (currency symbol tolerated) — nothing
    else. "180" and "$40" match; "under 180" or "180 max" do not."""
    match = _BARE_NUMBER_RE.match(message or "")
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _looks_like_time_derived_budget(message: str, budget_max: float) -> bool:
    """True when `budget_max` more plausibly came from a duration/distance
    mention ("less than 20 minutes away") than a real currency amount —
    ported from agent-usa's guard of the same name (prod audit 2026-07-19,
    Hillsborough session). A currency marker on the SAME number always wins,
    so a real €20/$20 budget is never dropped."""
    text = (message or "").lower()
    token = re.escape(str(int(budget_max)) if float(budget_max).is_integer() else str(budget_max))
    currency = (
        rf"(?:[$€£]\s*{token}\b|\b{token}\s*[$€£]|\b{token}\s*(?:euros?|dollars?|pounds?)\b)"
    )
    if re.search(currency, text):
        return False
    unit = rf"\b{token}\s*(?:am|pm|h|hours?|hrs?|minutes?|mins?|kilometers?|kilometres?|km|miles?|mi)\b"
    return bool(re.search(unit, text))


def maybe_auto_widen(profile: SessionProfile) -> bool:
    """Auto-widen the budget after a streak of empty searches — SKIPPED when
    the current budget is the user's own explicit figure (never silently
    override what they typed). Sets the mandatory disclosure payload when it
    does widen; a later synthesis step (S06) must surface it to the user.

    Capped at `AUTO_WIDEN_MAX_ATTEMPTS` (S12 audit 2026-07-20 — prod session
    034c97c4, Rimini: an uncapped version widened ×1.5 on EVERY empty turn
    forever). Once a widen attempt fails (explicit budget, no budget, or the
    cap already reached) AFTER at least `AUTO_WIDEN_MAX_ATTEMPTS` real widens
    happened, `search_exhausted` is set — the spine's pre-leaf gate (agent.py)
    then stops searching until the user provides a new constraint."""
    if profile.consecutive_empty_searches < AUTO_WIDEN_STREAK_THRESHOLD:
        return False
    old_budget = profile.budget_max
    can_widen = (
        profile.budget_request_source != BUDGET_SOURCE_EXPLICIT
        and old_budget is not None
        and profile.widen_attempt_count < AUTO_WIDEN_MAX_ATTEMPTS
    )
    if not can_widen or old_budget is None:
        if profile.widen_attempt_count >= AUTO_WIDEN_MAX_ATTEMPTS:
            profile.search_exhausted = True
        return False
    new_budget = round(old_budget * AUTO_WIDEN_FACTOR, 2)
    profile.budget_max = new_budget
    profile.auto_widen_disclosure = {"from": old_budget, "to": new_budget}
    profile.widen_attempt_count += 1
    return True


# --- Timeslot sanitization (P6) ---------------------------------------------

_CLOCK_TOKEN_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$", re.IGNORECASE)

_TIME_MENTION_RE = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|h)\b|\b\d{1,2}:\d{2}\b|"
    r"\b(?:morning|afternoon|evening|night|matin|midi|apr[eè]s-midi|soir(?:ée)?)\b",
    re.IGNORECASE,
)


def _parse_clock_token(token: str) -> str | None:
    match = _CLOCK_TOKEN_RE.match(token)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _split_one_sided_clock(value: str | None) -> tuple[str | None, str | None]:
    """A one-sided bound ("15:00-", "-09:00", "9am-") salvaged into
    (start, None) or (None, end). A non-clock free-text label ("morning")
    is left alone — (None, None), the caller keeps it as-is."""
    if not value:
        return (None, None)
    stripped = value.strip()
    if len(stripped) < 2:
        return (None, None)
    if stripped[-1] in "-_" and stripped[0] not in "-_":
        start = _parse_clock_token(stripped[:-1])
        return (start, None) if start else (None, None)
    if stripped[0] in "-_" and stripped[-1] not in "-_":
        end = _parse_clock_token(stripped[1:])
        return (None, end) if end else (None, None)
    return (None, None)


def _normalize_timeslot(value: str | None) -> str | None:
    """None if `value` is a malformed one-sided clock label (the caller
    salvages the bound separately via `_split_one_sided_clock`) — such a
    string must NEVER be persisted as the free-text timeslot. Any other
    value (including a clean clock string or a day-part word) passes through."""
    if not value:
        return None
    start, end = _split_one_sided_clock(value)
    if start or end:
        return None
    return value


def _mentions_explicit_time(message: str) -> bool:
    return bool(_TIME_MENTION_RE.search(message or ""))


# --- Combined delta application ---------------------------------------------


def _normalize_delta(delta: dict[str, Any]) -> tuple[dict[str, Any], set[str], set[str]]:
    """Splits an incoming (possibly mixed) delta into (`values` — the
    effective flat value per "set" slot, `clears` — the slot names carrying
    an explicit `{"op": "clear"}`, `explicit_sets` — the slot names that
    arrived as a typed `{"op": "set"}` rather than a bare value). A slot
    absent from `delta` never appears in any output — that IS carryover,
    enforced by construction (the caller only ever reads a slot it finds in
    `values`/`clears`). A slot NOT shaped as a typed op (`{"op":
    "set"|"clear", ...}`) is today's plain `{key: value}` leaf format —
    treated as an implicit "set" (S-G1 retro-compat: the leaf migrates to
    typed ops in S-G5/S-G6, nothing breaks before then).

    UX1: `explicit_sets` is what lets a slot distinguish "the leaf sent me the
    authoritative state of this slot" from "the leaf sent me something to fold
    in". It matters for exactly one slot today, `amenities`, whose flat form
    is append-only and therefore cannot express a retraction — and for which
    an empty typed set is a meaningful value, not a no-op."""
    values: dict[str, Any] = {}
    clears: set[str] = set()
    explicit_sets: set[str] = set()
    for key, raw in delta.items():
        if isinstance(raw, dict) and raw.get("op") in ("set", "clear"):
            if raw["op"] == "clear":
                clears.add(key)
            else:
                values[key] = raw.get("value")
                explicit_sets.add(key)
        else:
            values[key] = raw
    return values, clears, explicit_sets


def _log_profile_ops(set_slots: set[str], clear_slots: set[str]) -> None:
    """RGPD-safe reducer counter: slot NAMES and counts only, never a value —
    same discipline as the leaf's `amenity_filter`/`budget_timeslot` metrics."""
    if not set_slots and not clear_slots:
        return
    slots = ",".join(sorted(set_slots | clear_slots))
    _metrics_logger.info(
        "dayuse_metric=profile_ops set=%d clear=%d slots=%s",
        len(set_slots), len(clear_slots), slots,
    )


def apply_profile_delta(
    profile: SessionProfile,
    delta: dict[str, Any],
    user_message: str,
    fired: set[str] | None = None,
) -> SessionProfile:
    """Merge a leaf-returned `profile_delta` into the stored profile, with the
    budget-integrity and timeslot-sanitization guards applied in-place.
    Mutates and returns `profile`. `delta` is untrusted wire data — read-only,
    never mutated.

    `fired` (OBS3, optional — omitted by every pre-existing caller): when
    given, "budget_integrity"/"timeslot_sanitization" are added to it exactly
    when that guard actually did something this turn (rejected a bogus value
    or corrected a mis-derived one) — the per-turn accumulator score_guards
    reads from (see agent.py's `TurnBudget.fired`).

    S-G1: each slot may arrive as a typed op (`{"op": "set"|"clear", "value":
    ...}`) or today's flat value — `_normalize_delta` resolves both into a
    single `values` dict (drop-in replacement for the old `delta` everywhere
    below, byte-for-byte retro-compatible with a flat delta) plus a `clears`
    set applied generically at the end, after every field-specific guard has
    run, plus (UX1) an `explicit_sets` set naming the slots that arrived as a
    typed set — read by `amenities` alone, to tell an authoritative
    replacement apart from a fragment to merge."""
    values, clears, explicit_sets = _normalize_delta(dict(delta))
    known_fields = set(SessionProfile.__dataclass_fields__)

    # City change clears the geo anchors/zone/metro/search-anchor (S04 +
    # S-G1) and resets the pagination state — unless the SAME delta also
    # carries a fresh anchor/zone, applied right after.
    if values.get("city"):
        new_city = values["city"]
        if profile.city and new_city != profile.city:
            profile.state_anchor = None
            profile.country_anchor = None
            profile.zone = None
            profile.metro = None
            profile.search_anchor = None
            profile.shown_hotel_ids = []
            profile.search_cursor = 0
        profile.city = new_city
    if "state_anchor" in values:
        profile.state_anchor = values["state_anchor"]
    if "country_anchor" in values:
        profile.country_anchor = values["country_anchor"]

    # Budget integrity (P1): a bare-number reply is ALWAYS explicit, whatever
    # the delta's own source claim says. A number that looks time/distance-
    # derived ("less than 20 minutes away") is never persisted as a budget at
    # all (S12 audit 2026-07-20) — profile.budget_max is simply left as-is.
    if values.get("budget_max") is not None:
        new_budget = float(values["budget_max"])
        if _looks_like_time_derived_budget(user_message, new_budget):
            if fired is not None:
                fired.add("budget_integrity")
        else:
            profile.budget_max = new_budget
            source = values.get("budget_request_source")
            if _bare_number_value(user_message) == new_budget:
                source = BUDGET_SOURCE_EXPLICIT
                if fired is not None:
                    fired.add("budget_integrity")
            if source is not None:
                profile.budget_request_source = source

    # Timeslot sanitization (P6): salvage a raw one-sided clock label into a
    # bound instead of persisting the corrupted string.
    if "timeslot" in values:
        raw = values.get("timeslot")
        normalized = _normalize_timeslot(raw) if raw else None
        if raw and normalized is None:
            start, end = _split_one_sided_clock(raw)
            if start:
                values.setdefault("timeslot_start", start)
            if end:
                values.setdefault("timeslot_end", end)
            if (start or end) and fired is not None:
                fired.add("timeslot_sanitization")
        else:
            profile.timeslot = normalized

    start_candidate = values.get("timeslot_start")
    end_candidate = values.get("timeslot_end")
    reject_start = bool(
        start_candidate
        and profile.timeslot_mode == "end_only"
        and profile.timeslot_end == start_candidate
        and not _mentions_explicit_time(user_message)
    )
    reject_end = bool(
        end_candidate
        and profile.timeslot_mode == "start_only"
        and profile.timeslot_start == end_candidate
        and not _mentions_explicit_time(user_message)
    )
    if (reject_start or reject_end) and fired is not None:
        fired.add("timeslot_sanitization")
    if start_candidate and not reject_start:
        profile.timeslot_start = start_candidate
    if end_candidate and not reject_end:
        profile.timeslot_end = end_candidate
    if (start_candidate and not reject_start) or (end_candidate and not reject_end):
        if profile.timeslot_start and profile.timeslot_end:
            profile.timeslot_mode = "range"
        elif profile.timeslot_start:
            profile.timeslot_mode = "start_only"
        elif profile.timeslot_end:
            profile.timeslot_mode = "end_only"
    if "timeslot_request_source" in values:
        profile.timeslot_request_source = values["timeslot_request_source"]

    # UX1 — the amenity filter is the one slot the user must be able to SHRINK
    # ("enleve le spa"). A typed `{"op": "set"}` from the leaf carries the
    # whole filter state of the turn (equipment_ids unions the profile in
    # before it subtracts), so it REPLACES — an empty value included, which is
    # exactly what a full retraction looks like. The flat form stays
    # append-only: it is an explicit contract of `_normalize_delta` ("today's
    # plain `{key: value}` leaf format") that existing callers and tests rely
    # on, and a plain list genuinely is a fragment with no authority to wipe.
    if "amenities" in explicit_sets:
        profile.amenities = list(values.get("amenities") or [])
    elif values.get("amenities"):
        merged = list(profile.amenities)
        for amenity in values["amenities"]:
            if amenity not in merged:
                merged.append(amenity)
        profile.amenities = merged

    if values.get("language"):
        profile.language = values["language"]

    # S-G1 new slots: plain carryover-by-default copy, no extra guard (guards
    # land once a leaf actually extracts these — S-G5/S-G6). `zone`/`metro`/
    # `search_anchor` deliberately do NOT reset `shown_hotel_ids`/
    # `search_cursor` — only an actual city change does (see above); a
    # zone-only change is exactly the audit's "keep everything else" case.
    if "zone" in values:
        profile.zone = values["zone"]
    if "pending_place" in values:
        profile.pending_place = values["pending_place"]
    if "metro" in values:
        profile.metro = values["metro"]
    if "named_hotel" in values:
        profile.named_hotel = values["named_hotel"]
    if "date" in values:
        profile.date = values["date"]
    if "date_reference" in values:
        profile.date_reference = values["date_reference"]
    if "currency" in values:
        profile.currency = values["currency"]
    if "locale" in values:
        profile.locale = values["locale"]
    if "domain" in values:
        profile.domain = values["domain"]
    if "search_anchor" in values:
        profile.search_anchor = values["search_anchor"]
    if "distance_origin" in values:
        profile.distance_origin = values["distance_origin"]
    if "shown_hotel_ids" in values:
        profile.shown_hotel_ids = list(values["shown_hotel_ids"] or [])[-MAX_SHOWN_HOTEL_IDS:]
    if "search_cursor" in values:
        profile.search_cursor = int(values["search_cursor"])
    if "client_timezone" in values:
        profile.client_timezone = values["client_timezone"]
    if "daypart" in values:
        profile.daypart = values["daypart"]
    # P0-1: party size. Coerced through int() like `search_cursor` — the value
    # arrives from untrusted wire data, and the leaf's own `party_count`
    # validator already refused anything non-integral, so anything odd reaching
    # here is a contract break worth failing loudly rather than storing. A slot
    # is only written when present: a refinement turn that mentions nobody must
    # never wipe a party size stated three turns ago.
    if values.get("adults") is not None:
        profile.adults = int(values["adults"])
    if values.get("children") is not None:
        profile.children = int(values["children"])

    # Explicit clears (A3-a: an auditable per-slot clear, never a silent
    # omission) — each slot resets to its OWN dataclass default. Applied last
    # so a clear always wins over any earlier field-specific derivation for
    # the SAME slot (a slot can only be in `values` XOR `clears`, never both,
    # so there is no ordering conflict — this is just the generic path for
    # slots the guards above don't already special-case).
    for slot in clears:
        if slot in known_fields:
            setattr(profile, slot, _slot_default(slot))

    _log_profile_ops(
        {k for k in values if k in known_fields},
        {k for k in clears if k in known_fields},
    )

    return profile


def record_search_outcome(
    profile: SessionProfile,
    results_count: int,
    language: str = "en",
    same_day_dead_end: bool = False,
) -> None:
    """Tracks the empty-search streak that feeds `maybe_auto_widen` — called
    once per search turn with the leaf's returned result count. A zero-result
    outcome also sets the code-owned recovery suggestions (P2) so a later
    bare "ok"/"sure" can be matched deterministically; fresh results clear
    them (a stale offer must never be replayed after the screen changes).

    `same_day_dead_end` (S-CX6, from the leaf's `search_date` DataPart key)
    swaps in the date-first suggestions: the searched day is today and today's
    booking window has closed, so no budget/zone/filter change can produce a
    single offer."""
    profile.consecutive_empty_searches = (
        0 if results_count > 0 else profile.consecutive_empty_searches + 1
    )
    if results_count > 0:
        profile.last_suggestions = None
        profile.widen_attempt_count = 0
        profile.search_exhausted = False
    elif same_day_dead_end:
        profile.last_suggestions = list(_DATE_SUGGESTIONS.get(language, _DATE_SUGGESTIONS["en"]))
    else:
        profile.last_suggestions = list(
            _RECOVERY_SUGGESTIONS.get(language, _RECOVERY_SUGGESTIONS["en"])
        )


# --- Recovery ack + refinement (P2 / multi-turn) ------------------------

# Month names (fr + en) shared by the date detectors below.
_MONTHS = (
    "janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre|"
    "january|february|march|april|may|june|july|august|september|october|november|december"
)
# A date the user might give to CHANGE a prior search's date: a relative day, a
# weekday, a "le 28"/"28 juillet"/ISO date, or a bare month.
_DATE_MENTION_RE = re.compile(
    r"\b(?:aujourd'hui|demain|apr[eè]s[- ]demain|today|tomorrow|"
    r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\b(?:" + _MONTHS + r")\b"
    r"|\ble\s+\d{1,2}\b|\b\d{1,2}\s+(?:" + _MONTHS + r")\b|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
# Budget / zone / "cheaper" / "change the date" refinement keywords.
_REFINEMENT_KEYWORDS_RE = re.compile(
    r"\b(?:moins\s+cher|cheaper|pas\s+trop\s+cher|budget|"
    r"[ée]largir|autour|nearby|plus\s+pr[eè]s|plus\s+t[ôo]t|plus\s+tard|earlier|later|"
    r"chang\w*\s+(?:la\s+)?date|autre\s+date|other\s+date|autre\s+quartier|arrondissement)\b"
    r"|[€$£]",
    re.IGNORECASE,
)

# S-G5: "show me more of the same search" — no new constraint at all, just the
# NEXT page (advances profile.search_cursor). Deliberately separate from
# `_REFINEMENT_KEYWORDS_RE` (a real new constraint like "cheaper") since only
# THIS phrasing should advance the pagination cursor.
_MORE_OPTIONS_RE = re.compile(
    r"\b(?:autres?\s+options?|autre\s+chose|d'autres?\s+h[ôo]tels?|encore\s+des?\s+h[ôo]tels?|"
    r"other\s+options?|more\s+options?|show\s+me\s+more|anything\s+else|what\s+else|"
    r"any\s+other(?:\s+ones?)?)\b",
    re.IGNORECASE,
)


def is_more_options_signal(message: str, llm_wants_more: bool | None = None) -> bool:
    """True when `message` asks for MORE of the same search (audit multi-turn
    "other options" case) — no new constraint, just the next page. Distinct
    from `is_search_refinement_signal`'s other modifiers: this is the ONLY
    signal that should advance `profile.search_cursor` (S-G1's
    `advance_search_cursor`, wired in agent.py).

    P1-1: `llm_wants_more` is triage's `wants_more_options` slot, applied
    additively for the same reason as `is_bare_affirmative` above — it adds
    "otras opciones"/"altre opzioni"/"noch andere", it never vetoes a phrase
    the regex already recognizes."""
    return bool(llm_wants_more) or bool(_MORE_OPTIONS_RE.search((message or "").strip()))


def _has_refinement_modifier(message: str, llm_bare_budget: float | None = None) -> bool:
    """A follow-up that adjusts a prior search's parameters — a date, a budget/
    price (keyword, symbol, or a bare number), a time-of-day, or a zone keyword.

    P1-1: `llm_bare_budget` is triage's `bare_budget_value` slot. Note this is
    the ROUTING use of that slot; the budget-integrity guard in
    `apply_profile_delta` keeps calling `_bare_number_value` directly and must
    NOT be switched over — it exists to cross-check the leaf's claimed budget
    against the literal user text, and sourcing both sides from the same model
    would delete the independence that makes it a guard."""
    return bool(
        _DATE_MENTION_RE.search(message)
        or _REFINEMENT_KEYWORDS_RE.search(message)
        or _TIME_MENTION_RE.search(message)
        or _bare_number_value(message) is not None
        or llm_bare_budget is not None
    )


def _has_prior_search_context(profile: SessionProfile) -> bool:
    return bool(profile.city) or bool(profile.last_results) or profile.consecutive_empty_searches > 0


def is_search_refinement_signal(
    message: str,
    profile: SessionProfile,
    *,
    llm_affirmative: bool | None = None,
    llm_wants_more: bool | None = None,
    llm_bare_budget: float | None = None,
) -> bool:
    """True when `message` continues/refines a PRIOR search and must be routed to
    a fresh search rather than the ack template OR a mis-triaged booking/detail:
    - a bare affirmative ("ok"/"sure") while the last search came back empty;
    - a verbatim `last_suggestions` recovery-chip click;
    - a "show me more"/"other options" request while a prior search context
      exists (S-G5 — pagination, no new constraint at all);
    - a follow-up carrying a search-parameter modifier (a new date, a budget, a
      time-of-day, a zone/"cheaper" keyword) while a prior search context exists
      (`city`/`last_results`/empty streak) AND NOT naming a specific shortlist
      hotel (naming one stays a booking/details intent). Never a regex over the
      assistant's own prose.
    """
    stripped = (message or "").strip()
    if not stripped:
        return False
    if profile.consecutive_empty_searches > 0 and is_bare_affirmative(stripped, llm_affirmative):
        return True
    suggestions = profile.last_suggestions or []
    if stripped.lower() in {s.strip().lower() for s in suggestions}:
        return True
    if _has_prior_search_context(profile) and is_more_options_signal(stripped, llm_wants_more):
        return True
    if (
        _has_prior_search_context(profile)
        and _has_refinement_modifier(stripped, llm_bare_budget)
        and resolve_hotel_reference(stripped, profile.last_results) is None
    ):
        return True
    return False


def _timeslot_label(profile: SessionProfile) -> str | None:
    """Human-readable time-of-day: a free-text label, or the start/end bounds."""
    if profile.timeslot:
        return profile.timeslot
    start, end = profile.timeslot_start, profile.timeslot_end
    if start and end:
        return f"{start}-{end}"
    if start:
        return f"{start}-"
    if end:
        return f"-{end}"
    return None


def search_context_line(profile: SessionProfile) -> str:
    """One-line summary of the understood search params (destination/budget/time/
    amenities), for the synthesis to restate to the user (transparency). Empty
    when nothing is known. The DATE isn't a profile field — it stays in the raw
    message the synthesis already sees."""
    bits: list[str] = []
    if profile.city:
        bits.append(f"destination: {profile.city}")
    if profile.budget_max:
        bits.append(f"budget max: €{profile.budget_max:.0f}")
    slot = _timeslot_label(profile) or profile.daypart
    if slot:
        bits.append(f"time of day: {slot}")
    if profile.amenities:
        bits.append("amenities: " + ", ".join(profile.amenities))
    return "; ".join(bits)


# --- Anti-clarification-loop (P10) --------------------------------------

_FINAL_QUESTION_RE = re.compile(r"([^.!?\n]*\?)\s*$")

# Cheap normalization for fuzzy equivalence: lowercase, drop punctuation, and
# collapse whitespace — "Which airport area exactly should I prioritize?" and
# "Which airport area, exactly, should I prioritize?" must compare equal.
_NORMALIZE_RE = re.compile(r"[^\w\s]")


def extract_final_question(text: str) -> str | None:
    """The last sentence of `text` if it is a question, else None. Used to
    detect a synthesized reply that ends by asking something — the shape a
    repeated clarifying question always takes (prod sessions 493b86e8 /
    cfa9c579 repeated the SAME trailing question up to 7 times)."""
    if not text:
        return None
    match = _FINAL_QUESTION_RE.search(text.strip())
    if not match:
        return None
    question = match.group(1).strip()
    return question or None


def questions_equivalent(a: str | None, b: str | None) -> bool:
    """Fuzzy equality tolerant of punctuation/whitespace drift — the LLM
    rarely repeats a question byte-for-byte, but a human recognizes it as
    the same question."""
    if not a or not b:
        return False
    norm_a = _NORMALIZE_RE.sub("", a).lower().split()
    norm_b = _NORMALIZE_RE.sub("", b).lower().split()
    return bool(norm_a) and norm_a == norm_b


# --- Named-hotel lookup (S07) — the `_last_results` equivalent -------------

MAX_SHORTLIST = 5  # same cap as ground_truth.MAX_HOTELS; not imported to avoid
# a circular import (ground_truth.py already imports SessionProfile from here).

_MIN_MATCHABLE_NAME_LEN = 4  # same floor as agent-usa's own matcher: below
# this a hotel name is too short/generic to match reliably by substring.

_NAME_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Generic hospitality words are never distinctive enough to identify ONE
# hotel among a shortlist ("compare the Hampton Inn and the Ibis Hotel" must
# match on "hampton"/"ibis", never on the shared "hotel"/"inn").
_NAME_STOPWORDS = {
    "hotel", "hotels", "inn", "the", "and", "de", "le", "la", "les", "el",
    "resort", "resorts", "suite", "suites", "spa",
}


def _significant_name_tokens(name: str) -> set[str]:
    tokens = _NAME_TOKEN_RE.findall(name.lower())
    return {t for t in tokens if len(t) >= _MIN_MATCHABLE_NAME_LEN and t not in _NAME_STOPWORDS}


def _substring_match(stripped: str, name: str) -> bool:
    """The STRONG tier: `name` and `stripped` contain each other, either
    direction (a short reference "Kimpton" matches the full on-screen name
    "Kimpton - Hotel Palomar South Beach"). The only tier trusted with zero
    verification against the global catalogue (S12 audit 2026-07-20)."""
    if len(name) < _MIN_MATCHABLE_NAME_LEN:
        return False
    name_l = name.lower()
    return name_l in stripped or stripped in name_l


def _hotel_matches(stripped: str, message_tokens: set[str], hotel: dict[str, Any]) -> bool:
    name = str(hotel.get("name") or "").strip()
    if _substring_match(stripped, name):
        return True
    # Free-text fallback (no upstream entity extraction here, unlike
    # agent-usa's NamedHotelTool which received an already-isolated
    # hotel_name argument): a distinctive word from the name showing up
    # anywhere in the message is enough — "compare Kimpton and the Hampton
    # Inn" must resolve both without either name appearing verbatim.
    significant = _significant_name_tokens(name)
    return bool(significant) and bool(significant & message_tokens)


def named_hotel_in_results(name: str, results: list[dict[str, Any]] | None) -> bool:
    """Whether a hotel the MCP name lookup missed is on screen anyway — the
    lookup is stricter than the search (mcp-dayuse#3: "Pullman Lyon" not
    found by name, then returned by the city search). Same strong tier as
    the shortlist matcher, plus: every distinctive word of the name is in
    the hotel's name."""
    wanted = name.strip().lower()
    wanted_tokens = _significant_name_tokens(wanted)
    for hotel in results or []:
        if not isinstance(hotel, dict):
            continue
        hotel_name = str(hotel.get("name") or "").strip()
        if _substring_match(wanted, hotel_name) or (
            wanted_tokens and wanted_tokens <= set(_NAME_TOKEN_RE.findall(hotel_name.lower()))
        ):
            return True
    return False


def choose_named_candidate(
    message: str, candidates: list[str], position: int | None = None
) -> str | None:
    """The hotel a reply picks among the candidates the last turn listed:
    by position (« le deuxième »), or by the words that set it apart from the
    others (« celui de St Pauls » → « Leonardo Royal Hotel London St Pauls »,
    « Leonardo Royal » being shared by all three). Words win over a position:
    triage reads « celui de … » as « the first one » often enough. None when
    the reply designates no single one."""
    tokens = [set(_NAME_TOKEN_RE.findall(name.lower())) for name in candidates]
    shared = set.intersection(*tokens) if tokens else set()
    said = set(_NAME_TOKEN_RE.findall((message or "").lower())) - _NAME_STOPWORDS - shared
    scores = [len(said & (t - shared)) for t in tokens]
    best = max(scores, default=0)
    if best > 0:
        return candidates[scores.index(best)] if scores.count(best) == 1 else None
    if position is not None and 1 <= position <= len(candidates):
        return candidates[position - 1]
    return None


def record_search_shortlist(profile: SessionProfile, results: list[dict[str, Any]] | None) -> None:
    """Persists the on-screen shortlist so a LATER turn can reference a hotel
    by name without a fresh MCP round-trip (named-hotel lookup guard). A
    non-empty result REPLACES the previous shortlist (the screen now shows
    THESE hotels); an empty result leaves it untouched on purpose — the user
    must still be able to say "book the one you showed me" right after a
    later, unrelated empty search (never dead-end on a hotel just
    recommended). Defensive about the hotel-id key name: the leaf's own
    response shape is not schema-fixed yet (S1-S6), so `hotel_id`/`hotelId`/
    `id` are all accepted.

    S-G1: also accumulates every shown hotel id into `shown_hotel_ids` (the
    pagination exclusion set — schema only here; wiring it into
    `search_offers` args is S-G5). Unlike `last_results`, this NEVER resets on
    an empty search — only an actual city change does (`apply_profile_delta`).

    S-CX5: each entry also keeps the identity of the offer the card was priced
    on (`offer_id` = the tunnel's `offerId`, `offer_date`, plus the price and
    slot as displayed) when the card carries them. That is what lets a later
    booking turn quote the offer the user actually saw instead of re-deriving
    one from a fresh lookup (prod defect 2026-07-27: a card at €87 /
    11:00-19:00 / tomorrow produced a link for €90 / 17:00-23:00 / today).
    Only-when-present, so a card without an offer degrades to today's
    behaviour rather than storing a null that reads as data."""
    if not results:
        return
    shortlist: list[dict[str, Any]] = []
    for hotel in results:
        if not isinstance(hotel, dict):
            continue
        name = str(hotel.get("name") or "").strip()
        if not name:
            continue
        hotel_id = hotel.get("hotel_id", hotel.get("hotelId", hotel.get("id")))
        entry: dict[str, Any] = {"hotel_id": hotel_id, "name": name}
        # The offer identity, plus what a booking card has to STATE about the
        # hotel (S-CX5) — all of it already on the card the user is looking at,
        # so the recap can be built later without a second lookup.
        for key in (
            "offer_id", "offer_date", "price", "price_eur_cents",
            "image_urls", "url", "city", "rating", "rating_count", "stars",
            "hotel_currency_code",
        ):
            if hotel.get(key) is not None:
                entry[key] = hotel[key]
        slot = (hotel.get("timeslots") or [None])[0]
        if isinstance(slot, dict) and slot.get("start") and slot.get("end"):
            entry["start_time"], entry["end_time"] = slot["start"], slot["end"]
        shortlist.append(entry)
    if shortlist:
        profile.last_results = shortlist[:MAX_SHORTLIST]
        _accumulate_shown_hotel_ids(profile, [entry["hotel_id"] for entry in shortlist])


def build_hotel_picks(profile: SessionProfile) -> list[dict[str, Any]]:
    """The hotel-pick buttons (S-CX5, Fabien 2026-07-27): one entry per hotel on
    screen the user can choose, CHEAPEST FIRST.

    Why the backend owns this rather than the widget deriving it from `hotels`:
    both product rules live here, where the session state is. WHEN they may
    appear — a destination must be resolved. A date is NOT required (Fabien
    2026-07-28): the search and the booking quote both default the date to
    today, so a date-less shortlist IS bookable — requiring the date dead-ended
    the pick row for every "hôtel à Paris" search. And in WHICH ORDER — sorted
    by price, so "the cheapest" is answerable by eye and the first button is
    always it. Deliberately NO "cheapest" badge: that would be a claim, and
    claims need a guard.

    Empty list when nothing qualifies — the widget then renders no pick row at
    all rather than an empty one. Entries without a price sort last (they are
    still pickable; they just can't be compared).

    Lives HERE rather than in the facade (S-PERF4) because the spine has to
    call it too: a hotels-first client paints the cards on the `hotels` frame,
    long before the `done` payload exists, and S-CX9 gates the card's booking
    CTA on these picks. Both callers running the SAME function over the SAME
    profile is what makes the frame's picks and the payload's picks equal by
    construction rather than by review."""
    if not profile.city:
        return []
    picks = [
        {
            "hotel_id": hotel.get("hotel_id"),
            "name": hotel.get("name"),
            "price": hotel.get("price"),
            "price_eur_cents": hotel.get("price_eur_cents"),
        }
        for hotel in profile.last_results or []
        if isinstance(hotel, dict) and hotel.get("hotel_id") is not None and hotel.get("name")
    ]
    picks.sort(key=lambda p: (p["price_eur_cents"] is None, p["price_eur_cents"] or 0))
    return picks


def _accumulate_shown_hotel_ids(profile: SessionProfile, hotel_ids: list[Any]) -> None:
    """Moves each id in `hotel_ids` to the end of `shown_hotel_ids` (deduped —
    a re-shown hotel is now the MOST recently shown, not a stale entry),
    capped at `MAX_SHOWN_HOTEL_IDS` — the oldest ids drop first once a
    session has been shown more hotels than that."""
    merged = list(profile.shown_hotel_ids)
    for hotel_id in hotel_ids:
        if hotel_id is None:
            continue
        if hotel_id in merged:
            merged.remove(hotel_id)
        merged.append(hotel_id)
    profile.shown_hotel_ids = merged[-MAX_SHOWN_HOTEL_IDS:]


def advance_search_cursor(profile: SessionProfile) -> None:
    """The pure "other options" step (audit multi-turn case): every other
    filter stays exactly as-is, only the pagination cursor moves forward.
    Detecting the "other options" signal and wiring this into a leaf call is
    S-G5 — this function is the deterministic step it will call."""
    profile.search_cursor += 1


def reset_search_cursor(profile: SessionProfile) -> None:
    """Any search that is NOT "show me more of the same" starts at page 1.

    S-CX5: the cursor used to survive every later turn (only a city change
    cleared it), and the leaf excludes already-shown hotels whenever it is
    non-zero — so one "other options" turn permanently hid the hotels the user
    had already seen, including from a REFINED search. That is how "book the
    cheapest" answered with pricier hotels: the five cheapest had just been
    displayed, so they were filtered out of the very search meant to rank
    them (prod session 2026-07-27). A new constraint means a new result set;
    `shown_hotel_ids` keeps accumulating for the pagination safety net, it is
    simply not consulted at page 1."""
    profile.search_cursor = 0


def resolve_hotel_reference(
    text: str, last_results: list[dict[str, Any]] | None
) -> dict[str, Any] | None:
    """The first shortlist entry `text` refers to — case-insensitive
    substring match (either direction, so a short reference "Kimpton"
    matches the full on-screen name "Kimpton - Hotel Palomar South Beach"),
    falling back to a distinctive-word match for free text that never
    contains the name verbatim. Names under `_MIN_MATCHABLE_NAME_LEN` chars
    are skipped as too generic to match reliably (same floor as agent-usa's
    own matcher, prod session 34d216e3)."""
    stripped = (text or "").strip().lower()
    if not stripped or not last_results:
        return None
    tokens = set(_NAME_TOKEN_RE.findall(stripped))
    for hotel in last_results:
        if _hotel_matches(stripped, tokens, hotel):
            return hotel
    return None


def resolve_hotel_reference_strict(
    text: str, last_results: list[dict[str, Any]] | None
) -> dict[str, Any] | None:
    """Same lookup as `resolve_hotel_reference`, but ONLY the strong substring
    tier — never the distinctive-token fallback (S12 audit 2026-07-20). A
    stale shortlist entry that merely SHARES ONE WORD with an explicitly-named
    (different) hotel must never be trusted with zero verification: the
    caller (`inline_tools._resolve_hotel_id`) uses this to decide whether a
    shortlist hit is safe to return immediately, or must still be checked
    against the global `find_hotel_by_name` catalogue first."""
    stripped = (text or "").strip().lower()
    if not stripped or not last_results:
        return None
    for hotel in last_results:
        if _substring_match(stripped, str(hotel.get("name") or "").strip()):
            return hotel
    return None


def resolve_hotel_references(
    text: str, last_results: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Every shortlist entry `text` mentions (compare_hotels: a user naming
    two or more hotels in one message) — same matching rule as
    `resolve_hotel_reference`, but collecting all hits instead of the first."""
    stripped = (text or "").strip().lower()
    if not stripped or not last_results:
        return []
    tokens = set(_NAME_TOKEN_RE.findall(stripped))
    return [hotel for hotel in last_results if _hotel_matches(stripped, tokens, hotel)]


# A hotel picked by its LIST POSITION ("2", "#3", "option 1", "the first") from
# the numbered shortlist the concierge just showed. Deliberately TIGHT so it can
# only be a bare selection: a leading "le "/"the " + number is EXCLUDED because
# "le 2"/"le 28" is a French date refinement, not a pick. `search_offers` is
# never re-run and MCP `find_hotel_by_name` is never touched — the shortlist
# already carries each hotel's id, and MCP's exact-city filter is a poor match
# for greater-metro inventory (a "Miami" search returns hotels indexed under
# Miami Beach / Doral / Aventura, which find_hotel_by_name(cityName="Miami")
# then reports as "no hotel found").
_BARE_ORDINAL_RE = re.compile(
    r"^\s*(?:#\s*|n[°o]\s*|option\s+|choix\s+)?(\d{1,2})\s*$", re.IGNORECASE
)
_ORDINAL_WORDS = {
    "first": 1, "1st": 1, "premier": 1, "premiere": 1, "première": 1,
    "second": 2, "2nd": 2, "deuxieme": 2, "deuxième": 2,
    "third": 3, "3rd": 3, "troisieme": 3, "troisième": 3,
    "fourth": 4, "4th": 4, "quatrieme": 4, "quatrième": 4,
    "fifth": 5, "5th": 5, "cinquieme": 5, "cinquième": 5,
}


def resolve_shortlist_ordinal(
    text: str, last_results: list[dict[str, Any]] | None
) -> dict[str, Any] | None:
    """The shortlist entry `text` picks BY POSITION, or None when `text` is not
    a bare ordinal / the position is out of range. Lets a user reply to the
    numbered "which hotel?" prompt with "2" (or "the first") and resolve the
    RIGHT hotel from the on-screen shortlist — no MCP round-trip."""
    if not last_results:
        return None
    stripped = (text or "").strip()
    match = _BARE_ORDINAL_RE.match(stripped)
    if match:
        position: int | None = int(match.group(1))
    else:
        # word ordinals can't collide with a date, so a leading article is safe
        # to strip here (unlike the digit path, which must reject "le 2"/"le 28").
        word = re.sub(r"^(?:the|le|la)\s+", "", stripped.lower()).strip()
        position = _ORDINAL_WORDS.get(word)
    if position is None or not 1 <= position <= len(last_results):
        return None
    return last_results[position - 1]


def select_hotel_by_position(
    last_results: list[dict[str, Any]] | None, position: int | None
) -> dict[str, Any] | None:
    """The 1-based `position`-th entry of the on-screen shortlist, or None when
    it is out of range.

    S-CX5, the decision half of a positional pick. `resolve_shortlist_ordinal`
    stays for the LLM-down path (and for a bare "2" typed into the composer);
    this one takes the number triage already extracted, so "ok pour la
    première" — a sentence the bare-ordinal matcher rejects, which dead-ended
    into "Quel hôtel ?" in the prod session — resolves like any other pick."""
    if position is None or not last_results:
        return None
    if not 1 <= position <= len(last_results):
        return None
    return last_results[position - 1]


def select_cheapest_hotel(
    last_results: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """The cheapest entry of the on-screen shortlist, or None when nothing on
    screen carries a price.

    S-CX5 — the DECISION half of "le moins cher": triage's `pick` field carries
    whether the user asked for it (a comprehension step, owned by the LLM that
    already runs every turn — Fabien, 2026-07-20: don't push determinism into
    language understanding); WHICH hotel that is stays pure code over the
    prices the user is actually looking at. This function never reads the
    message.

    It has to exist because MCP has no price ordering to delegate to:
    `search_offers` takes no sort parameter and the server ranks on
    availability/quality/commission/rpm/tier. Prod session 2026-07-27: "ok je
    veux booké le moins cher" ran another relevance search instead, and
    answered with hotels pricier than the ones already on screen.

    Entries without a numeric price are skipped rather than guessed at."""
    priced = [
        hotel
        for hotel in last_results or []
        if isinstance(hotel, dict) and isinstance(hotel.get("price_eur_cents"), (int, float))
    ]
    if not priced:
        return None
    return min(priced, key=lambda hotel: hotel["price_eur_cents"])


# --- Booking confirmation (R9, guard #12) -----------------------------------


def is_booking_confirmation_signal(
    message: str,
    profile: SessionProfile,
    *,
    llm_booking_confirmation: str | None = None,
) -> bool:
    """True when `message` is a bare affirmative WHILE a booking offer is
    awaiting the user's explicit confirmation (`pending_booking` set) — the
    zero-LLM ack template and any other family must not swallow it, or the
    confirmation could never reach the code-owned gate that turns
    confirmed=false into confirmed=true (inline_tools.generate_booking_link).
    This function only routes the turn; it never decides the confirmed flag
    itself — that decision is re-derived from `pending_booking` at the call
    site, so this signal alone can never be the thing that authorizes a link.

    Matches a bare affirmative ("oui") OR an explicit confirmation verb
    ("oui je confirme", "je valide", "yes I confirm" — prod 2026-07-28: these
    fell through to triage and the greeting template, dead-ending R9's own
    confirmation question). Any negation/change-of-mind marker wins over a
    confirmation verb (« non je ne confirme pas » must never confirm), and a
    question is never a confirmation.

    P1-1: `llm_booking_confirmation` is triage's `booking_confirmation` slot
    ("confirm"/"refuse"/"change"/"none", or None when the classify produced
    nothing usable). It is consulted BEFORE the regexes, but `"none"` falls
    THROUGH to them rather than returning False — the model is told to judge the
    message on its own, and it cannot see that a booking is pending, so a bare
    "oui" may legitimately come back as `none`. Treating that as a refusal would
    re-break the exact prod defect PR #47 fixed (a written confirmation
    dead-ending on the greeting template). So the slot can only ADD coverage
    ("sí, confírmalo") or ADD protection ("refuse"/"change"); it can never
    remove a confirmation the regexes already recognize.
    """
    if not profile.pending_booking:
        return False
    stripped = (message or "").strip()
    if not stripped:
        return False
    if llm_booking_confirmation == "confirm":
        return True
    if llm_booking_confirmation in ("refuse", "change"):
        return False
    if _AFFIRMATIVE_RE.match(stripped):
        return True
    if "?" in stripped or _CONFIRMATION_NEGATION_RE.search(stripped):
        return False
    return bool(_CONFIRMATION_RE.search(stripped))
