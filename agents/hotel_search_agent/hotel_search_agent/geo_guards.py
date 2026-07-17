"""Deterministic geo guards — ported from agent-usa's 2026-06 production audit fixes.

Spec (agent-usa, read-only reference — never copy the whole file):
`tests/unit/application/test_audit_fixes_2026_06.py`, sections geocode echo-back
(incl. state hints + ZIP anchor), generic place words, state anchoring.
Source consulted only for those sections: `search_tool.py::_geocode_echo_matches`
/ `extract_state_hint_from_text` / `_resolve_state_hint`,
`search_profile.py::is_generic_location_token` / `_select_us_postal_anchor` /
the `last_state_context` anchor block in `apply_request_data`.

Adapted to THIS leaf's STATELESS contract (decision B3, CLAUDE.md): agent-usa
mutates a long-lived `Conversation.preferences` dict across turns. Here there is
no session — every function is pure, and the two guards that need cross-turn
memory (state anchoring) read their prior state from `profile_in` and return
what changed as a `profile_delta`, per contract.py. The caller (agent.py /
geocode_tool.py) is responsible for round-tripping `profile_delta` back as next
turn's `profile_in` (owned by the orchestrator's session — S5).

A guard never re-runs a loop: every function here is a single deterministic
pass — reject/accept/demote once, never retry the reasoning.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ── US state tables (echo-back + state-hint extraction) ─────────────────────

US_STATE_ABBREV_TO_NAME = {
    "al": "Alabama",
    "ak": "Alaska",
    "az": "Arizona",
    "ar": "Arkansas",
    "ca": "California",
    "co": "Colorado",
    "ct": "Connecticut",
    "de": "Delaware",
    "fl": "Florida",
    "ga": "Georgia",
    "hi": "Hawaii",
    "id": "Idaho",
    "il": "Illinois",
    "in": "Indiana",
    "ia": "Iowa",
    "ks": "Kansas",
    "ky": "Kentucky",
    "la": "Louisiana",
    "me": "Maine",
    "md": "Maryland",
    "ma": "Massachusetts",
    "mi": "Michigan",
    "mn": "Minnesota",
    "ms": "Mississippi",
    "mo": "Missouri",
    "mt": "Montana",
    "ne": "Nebraska",
    "nv": "Nevada",
    "nh": "New Hampshire",
    "nj": "New Jersey",
    "nm": "New Mexico",
    "ny": "New York",
    "nc": "North Carolina",
    "nd": "North Dakota",
    "oh": "Ohio",
    "ok": "Oklahoma",
    "or": "Oregon",
    "pa": "Pennsylvania",
    "ri": "Rhode Island",
    "sc": "South Carolina",
    "sd": "South Dakota",
    "tn": "Tennessee",
    "tx": "Texas",
    "ut": "Utah",
    "vt": "Vermont",
    "va": "Virginia",
    "wa": "Washington",
    "wv": "West Virginia",
    "wi": "Wisconsin",
    "wy": "Wyoming",
}
US_STATE_NAME_TO_CANONICAL = {name.lower(): name for name in US_STATE_ABBREV_TO_NAME.values()}
# Common shorthand ("west springfield mass" — prod session 5d7c8813).
US_STATE_NAME_TO_CANONICAL["mass"] = "Massachusetts"
# "washington" is hopelessly ambiguous (DC vs the state) in free text — never
# infer the state from it.
US_STATE_NAME_TO_CANONICAL.pop("washington", None)
_STATE_NAME_TO_ABBREV = {name.lower(): abbrev for abbrev, name in US_STATE_ABBREV_TO_NAME.items()}

# Two-letter abbreviations that collide with common words across the
# languages we serve (EN/FR/ES/IT/PT) — never treated as state hints in
# free text. Structured LLM keywords keep using the full table.
_TEXT_UNSAFE_STATE_ABBREVS = {
    "or",
    "me",
    "in",
    "hi",
    "ok",
    "de",
    "la",
    "id",
    "oh",
    "al",
    "ca",
    "ma",
    "mi",
    "ne",
    "il",
    "va",
    "co",
    "pa",
    "mo",
    "so",
    "no",
    "wa",
    "ut",
}


def extract_state_hint_from_text(*texts: str | None) -> str | None:
    """Scan free text for an explicit US state reference.

    Full state names win over two-letter abbreviations, and ambiguous
    abbreviations ("or", "in", "la", …) are ignored entirely. Sources are
    scanned in order, so put the most location-specific text first.
    """
    for text in texts:
        raw = str(text or "").lower()
        if not raw.strip():
            continue
        normalized = " " + re.sub(r"[^a-z]+", " ", raw) + " "
        for name, canonical in US_STATE_NAME_TO_CANONICAL.items():
            if f" {name} " in normalized:
                return canonical
        for token in normalized.split():
            if token in _TEXT_UNSAFE_STATE_ABBREVS:
                continue
            abbrev_match = US_STATE_ABBREV_TO_NAME.get(token)
            if abbrev_match:
                return abbrev_match
    return None


def resolve_state_hint(
    *,
    keywords: list[str] | None = None,
    city: str | None = None,
    zone: str | None = None,
    profile_location_hint: str | None = None,
    raw_user_message: str | None = None,
    profile_state_context: str | None = None,
    country_code: str | None = None,
    country_resolved: bool = True,
) -> str | None:
    """Resolve the US state qualifying this search, most explicit first.

    1. LLM keywords — exact extracted tokens, so the full abbreviation table
       is safe (ambiguous codes like "or"/"me" can't collide with prose
       words here).
    2. Free text (city string, zone, stored profile location, raw message)
       via `extract_state_hint_from_text` — skips word-colliding
       abbreviations.
    3. The profile's anchored state context ("Milford ct" → CT, stored on an
       earlier turn): the search turn's message is often just a budget
       number, and without this fallback the bare city geocodes to the
       wrong state's homonym (prod session 3d3618c1 resolved the
       Massachusetts Milford → Boston, 200 km from Milford CT).

    A non-US `country_code` skips the text tiers only when it is a *trusted*
    resolution (`country_resolved`). An untrusted non-US default must not
    blind the search to an explicit US state.
    """
    for kw in keywords or []:
        kw_l = str(kw).lower().strip().rstrip(".")
        canonical = US_STATE_ABBREV_TO_NAME.get(kw_l) or US_STATE_NAME_TO_CANONICAL.get(kw_l)
        if canonical:
            return canonical
    # An UNKNOWN country (None — no signal at all yet) must not skip the text
    # tiers the same way a resolved non-US country does: only a truthy,
    # trusted non-US code blinds the search to an explicit US state hint.
    if country_code and country_code != "US" and country_resolved:
        return None
    state_hint = extract_state_hint_from_text(city, zone, profile_location_hint, raw_user_message)
    if state_hint:
        return state_hint
    psc = str(profile_state_context or "").lower().strip().rstrip(".")
    if psc:
        state_hint = US_STATE_ABBREV_TO_NAME.get(psc) or US_STATE_NAME_TO_CANONICAL.get(psc)
        if state_hint:
            return state_hint
    return None


# ── Generic location words — guard 2 ─────────────────────────────────────────

# Words that describe a *kind* of place, not an actual place. Accepting them
# as a city sends garbage to the geocoder (prod: city='airport' resolved to
# Modesto CA; 'Terminal 5' was searched as a literal city).
_GENERIC_LOCATION_WORDS = frozenset(
    {
        "airport",
        "airports",
        "the airport",
        "aeroport",
        "aéroport",
        "aeropuerto",
        "terminal",
        "downtown",
        "city center",
        "city centre",
        "centre ville",
        "centre-ville",
        "near me",
        "nearby",
        "close by",
        "current location",
        "station",
        "train station",
        "bus station",
        "gare",
        "centro",
    }
)


def is_generic_location_token(value: str | None) -> bool:
    """True when `value` is a generic place word ("airport", "terminal 2")
    rather than a real city/locality name."""
    token = " ".join(str(value or "").lower().split())
    if not token:
        return False
    if token in _GENERIC_LOCATION_WORDS:
        return True
    return bool(re.fullmatch(r"terminal\s*\d{0,2}", token))


def demote_generic_city(query_params: dict) -> dict:
    """Single-turn version of agent-usa's generic-city demotion.

    A generic word in `city`/`metro` is never geocoded: `city` is cleared
    (demoted to `zone` when no zone is already set) and `metro` is dropped
    outright, so the caller re-asks for the real city instead of sending
    "airport" to Mapbox.
    """
    params = dict(query_params)
    city = params.get("city")
    metro = params.get("metro")
    if city and is_generic_location_token(city):
        if not params.get("zone"):
            params["zone"] = city
        params["city"] = None
    if metro and is_generic_location_token(metro):
        params["metro"] = None
    return params


# ── Geocode echo-back — guard 1 ──────────────────────────────────────────────

_ENDONYM_LIGATURES: tuple[tuple[str, str], ...] = (
    ("ß", "ss"),
    ("ø", "o"),
    ("æ", "ae"),
    ("œ", "oe"),
    ("ð", "d"),
    ("þ", "th"),
    ("ł", "l"),
    ("đ", "d"),
)


def _echo_fold(value: str | None) -> str:
    """Lower-case, transliterate endonym ligatures (ß→ss, ø→o, æ→ae, …) and
    strip combining accents, so a geocoded endonym echoes the ASCII a user
    typed ("Gießen" must echo "giessen", prod f4ef0259)."""
    text = str(value or "").lower()
    for src, dst in _ENDONYM_LIGATURES:
        text = text.replace(src, dst)
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


_ECHO_NOISE_WORDS = frozenset(
    {
        "airport",
        "station",
        "terminal",
        "downtown",
        "city",
        "area",
        "near",
        "north",
        "south",
        "east",
        "west",
        "train",
        "center",
        "centre",
        "beach",
        "county",
        "ville",
        "saint",
    }
)


def geocode_echo_matches(
    place_name: str | None,
    *,
    city: str | None,
    zone: str | None,
    state_hint: str | None,
) -> bool:
    """Validate that a geocoding result echoes the requested location.

    Returns False when the resolved `place_name` matches neither the
    explicitly stated US state nor any distinctive token of the requested
    city/zone — the signature of a Mapbox limit=1 mis-resolution.
    """
    place = " " + re.sub(r"[^a-z0-9]+", " ", _echo_fold(place_name)) + " "
    if not place.strip():
        return True
    if state_hint:
        state_l = _echo_fold(state_hint)
        abbrev = next(
            (a for a, n in US_STATE_ABBREV_TO_NAME.items() if n.lower() == state_l),
            None,
        )
        if f" {state_l} " not in place and (not abbrev or f" {abbrev} " not in place):
            return False
    request_tokens = {
        tok
        for tok in re.split(r"[^a-z0-9]+", _echo_fold(f"{zone or ''} {city or ''}"))
        if len(tok) >= 4
    }
    # State words and generic location words don't identify the place.
    request_tokens -= set(US_STATE_NAME_TO_CANONICAL)
    request_tokens -= _ECHO_NOISE_WORDS
    if not request_tokens:
        # A city/zone written in a non-Latin script (Greek, Cyrillic, CJK…)
        # produces zero Latin tokens, so it cannot be validated against the
        # Latin place_name. Returning True here would vacuously accept a US
        # homonym (prod 57c626f5: "Κηφισιά, Αττική" → Buffalo NY). When the
        # request HAS letters but none are Latin, treat it as unvalidated and
        # discard. (Empty / all-short-Latin requests keep the lenient pass.)
        _raw_request = f"{zone or ''} {city or ''}"
        _has_letters = any(ch.isalpha() for ch in _raw_request)
        _has_latin = bool(re.search(r"[a-z]", _raw_request.lower()))
        if _has_letters and not _has_latin:
            return False
        # A bare 1-3 digit token (FR département "77", area code) carries no
        # ≥4-char token to validate against — require the resolved place to
        # actually echo the digits instead of vacuously passing.
        _digits = re.sub(r"\D", "", _raw_request)
        if _digits and len(_digits) <= 3 and _digits not in place.replace(" ", ""):
            return False
        return True
    compact_place = place.replace(" ", "")

    def _token_matches(tok: str) -> bool:
        if f" {tok} " in place or tok in compact_place:
            return True
        if tok.startswith("saint") and tok.replace("saint", "st", 1) in compact_place:
            return True
        if tok.startswith("st") and len(tok) > 4 and tok.replace("st", "saint", 1) in compact_place:
            return True
        return False

    # The MOST distinctive token (the longest) must echo — any-token matching
    # would accept "South Port, Florida" for "port canaveral" (a Mapbox fuzz
    # on the generic half of the name, 90 km from the port). Length ties
    # accept any of the tied tokens ("salt lake", exonym pairs like "francfort
    # allemagne"). Legitimate partial echoes survive: their distinctive head
    # IS the longest token ("kingston upon thames" → Kingston).
    longest_len = max(len(tok) for tok in request_tokens)
    return any(_token_matches(tok) for tok in request_tokens if len(tok) == longest_len)


# ── ZIP anchor (part of the echo-back guard's spec section) ─────────────────

US_STATE_CODES = set(US_STATE_ABBREV_TO_NAME) | {"dc"}
US_STATE_NAMES = set(US_STATE_NAME_TO_CANONICAL.values()) | {"District of Columbia"}
US_STATE_NAMES = {name.lower() for name in US_STATE_NAMES} | {"washington"}
STREET_SUFFIX_TOKENS = {
    "aly",
    "alley",
    "ave",
    "avenue",
    "blvd",
    "boulevard",
    "cir",
    "circle",
    "ct",
    "court",
    "dr",
    "drive",
    "hwy",
    "highway",
    "ln",
    "lane",
    "pkwy",
    "parkway",
    "pl",
    "place",
    "rd",
    "road",
    "st",
    "street",
    "ter",
    "terrace",
    "trl",
    "trail",
    "way",
}


@dataclass(frozen=True)
class PostalAnchor:
    value: str
    candidates: list[str]
    reason: str
    conflict: bool


def select_us_postal_anchor(*texts: str | None) -> PostalAnchor | None:
    """Select the best US ZIP candidate from free text without city-specific rules."""
    combined = " ".join(str(text or "") for text in texts if str(text or "").strip()).strip()
    if not combined:
        return None

    raw_tokens = re.findall(r"[A-Za-z]+|\d{5}(?:-\d{4})?|\d+(?:st|nd|rd|th)?", combined)
    if not raw_tokens:
        return None
    tokens = [token.lower().strip(".") for token in raw_tokens]

    candidate_indexes = [
        index for index, token in enumerate(tokens) if re.fullmatch(r"\d{5}(?:-\d{4})?", token)
    ]
    if not candidate_indexes:
        return None

    state_indexes = {
        index
        for index, token in enumerate(tokens)
        if token in US_STATE_CODES or token in US_STATE_NAMES
    }
    scored: list[tuple[int, int, str, str]] = []
    for index in candidate_indexes:
        value = tokens[index][:5]
        score = 0
        reasons: list[str] = []
        if index == len(tokens) - 1:
            score += 30
            reasons.append("terminal_postal_token")
        if any(0 < index - state_index <= 3 for state_index in state_indexes):
            score += 60
            reasons.append("after_state")
        if any(0 < state_index - index <= 3 for state_index in state_indexes):
            score += 20
            reasons.append("before_state")
        following = set(tokens[index + 1 : index + 5])
        looks_like_street_number = index == 0 and bool(following.intersection(STREET_SUFFIX_TOKENS))
        if looks_like_street_number:
            score -= 70
            reasons.append("street_number_like")
        if len(candidate_indexes) == 1 and not looks_like_street_number:
            score += 10
            reasons.append("single_candidate")
        scored.append((score, -index, value, "+".join(reasons) or "postal_candidate"))

    scored.sort(reverse=True)
    top_score, _neg_index, selected, reason = scored[0]
    if top_score < -20:
        return None
    candidates = []
    for index in candidate_indexes:
        value = tokens[index][:5]
        if value not in candidates:
            candidates.append(value)
    conflict = len(candidates) > 1 or "street_number_like" in reason
    return PostalAnchor(value=selected, candidates=candidates, reason=reason, conflict=conflict)


# ── State anchoring — guard 3 ────────────────────────────────────────────────


def anchor_state_context(
    *,
    city: str | None,
    raw_user_message: str,
    profile_in: dict,
) -> tuple[str | None, dict]:
    """State-anchored search guard, adapted to the stateless contract.

    agent-usa persists `last_state_context` directly on the long-lived
    `Conversation`; here the anchor travels turn-to-turn through
    `profile_in`/`profile_delta` (contract.py) instead. Given this turn's
    city + raw message and the profile snapshot the caller forwarded in:

    - an explicit US state named this turn (city string or raw message)
      anchors/refreshes the state, forwarded in `profile_delta` so next
      turn's `profile_in` carries it;
    - naming a NEW city this turn, with no state token, clears a stale
      anchor (it would mis-qualify the new city's geocoding);
    - otherwise the anchor carried in `profile_in` is reused as-is.

    Returns `(effective_state_or_None, profile_delta)`. `profile_delta` only
    ever contains keys that changed (`last_state_context` set to a 2-letter
    code, or explicitly `None` to signal "clear it").
    """
    previous_city = profile_in.get("last_city")
    anchored = (profile_in.get("last_state_context") or None) or None
    delta: dict = {}

    state_hint = extract_state_hint_from_text(city, raw_user_message)
    if state_hint:
        code = _STATE_NAME_TO_ABBREV.get(state_hint.lower(), state_hint).upper()
        if code != anchored:
            delta["last_state_context"] = code
        anchored = code
    elif anchored and previous_city and city and city.lower() != previous_city.lower():
        anchored = None
        delta["last_state_context"] = None

    if city and city != previous_city:
        delta["last_city"] = city

    return anchored, delta
