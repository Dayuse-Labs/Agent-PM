"""Deterministic Python evaluators (D-OBS-3) for the OBS6 Langfuse dataset
experiments — no LLM judge, no managed code evaluators (Railway would only
offer the unsandboxed `insecure-local` dispatcher for those; incompatible
with zero-lock-in). Pure functions: no network, no LLM call — offline-
testable with fabricated `output` dicts (see evals/tests/test_langfuse_evaluators.py).

Convention (mirrors scripts/eval_hardening.py's pass/fail/skipped discipline):
a key ABSENT from `expected_output` contributes no Evaluation for that name —
"an item only scores the keys it declares" (evals/datasets/README.md). A key
that IS declared but whose supporting data is unavailable (trace observation
not found, response field not on the contract yet) scores `value=None` with a
`comment` explaining why — never a fabricated pass. This is what lets a
"target" item (metadata.status="target": expected to fail today) show up
honestly red instead of silently skipped.

`output` (built by evals/langfuse_experiment.py's task function) has the shape:
    {
      "response": <the /v3/chat JSON body, or None on a transport failure>,
      "trace": {                             # facts of the LAST replayed turn's trace
        "search_offers_args": dict | None,   # TOOL observation "search_offers" input, leaf trace
        "geocode": {"ok", "error", "city_needed", "options", "country_code"} | None,
                                             # TOOL observation "geocode_location" output (the last call)
        "tool_calls": [str] | None,          # names of the TOOL observations "mcp-<tool>" (the
                                             # concierge's inline calls); None = no observation seen
        "pick": {"pick": str, "pick_position": int|None} | None,  # triage generation output
        "family": str | None,                # triage generation output
        "route": str | None,                 # derived, see _derive_route()
      },
      "previous_reply": str | None,          # the reply to the turn before the last one
      "turns_replayed": int,                 # user turns posted on the session (QA14707 DQ4)
    }
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from b2c_common.timeslot import parse_hhmm, slot_covers_window
from langfuse import Evaluation

# --- shared response accessors (deliberately re-implemented rather than
# imported from agents/b2c_concierge — evals/** must stay a black-box client
# of the /v3/chat contract, same posture as scripts/eval_hardening.py) --------
def _hotels(response: dict[str, Any] | None) -> list[dict[str, Any]]:
    value = (response or {}).get("hotels")
    return [h for h in value if isinstance(h, dict)] if isinstance(value, list) else []


def _filters(response: dict[str, Any] | None) -> dict[str, Any]:
    value = (response or {}).get("active_filters")
    return value if isinstance(value, dict) else {}


def _message(response: dict[str, Any] | None) -> str:
    return str((response or {}).get("message") or "")


def _requires_clarification(response: dict[str, Any] | None) -> bool:
    return bool((response or {}).get("requires_clarification"))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _skip(name: str, comment: str) -> Evaluation:
    # NOT value=None: Langfuse's ScoreBody rejects a null value server-side
    # (confirmed live, 2026-07-30 — the README's own None-sketch does not
    # survive a real run_experiment call). CATEGORICAL "skipped" is a real,
    # ingestible score, distinguishable in the UI from a BOOLEAN 0/1, and
    # still conveys "declared but unavailable" rather than a fabricated pass.
    return Evaluation(name=name, value="skipped", comment=comment, data_type="CATEGORICAL")


def _bool_eval(name: str, ok: bool, comment: str) -> Evaluation:
    return Evaluation(name=name, value=1 if ok else 0, comment=comment, data_type="BOOLEAN")


# --- response-level checks ---------------------------------------------------
def _eval_min_hotels(expected: dict[str, Any], response: dict[str, Any] | None) -> Evaluation | None:
    if "min_hotels" not in expected:
        return None
    n = len(_hotels(response))
    min_h = expected["min_hotels"]
    clarify_ok = bool(expected.get("clarify_allowed")) and _requires_clarification(response)
    ok = n >= min_h or clarify_ok
    reason = f"{n} hotels >= {min_h}" if n >= min_h else (
        "clarify issued (clarify_allowed)" if clarify_ok else f"only {n} hotels, expected >= {min_h}"
    )
    return _bool_eval("min_hotels", ok, reason)


def _eval_max_hotels(expected: dict[str, Any], response: dict[str, Any] | None) -> Evaluation | None:
    if "max_hotels" not in expected:
        return None
    n = len(_hotels(response))
    max_h = expected["max_hotels"]
    return _bool_eval("max_hotels", n <= max_h, f"{n} hotels, expected <= {max_h}")


def _eval_hotels_within_km(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    if "hotels_within_km" not in expected:
        return None
    spec = expected["hotels_within_km"]
    hotels = _hotels(response)
    bad: list[str] = []
    for h in hotels:
        lat, lon = h.get("latitude"), h.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            bad.append(f"{h.get('name', h.get('id'))}: no coordinates")
            continue
        dist = _haversine_km(spec["lat"], spec["lon"], lat, lon)
        if dist > spec["km"]:
            bad.append(f"{h.get('name', h.get('id'))}: {dist:.1f}km > {spec['km']}km")
    return _bool_eval("hotels_within_km", not bad, "; ".join(bad) or f"all {len(hotels)} hotels within radius")


def _resolved_country_code(response: dict[str, Any] | None) -> Any:
    return _filters(response).get("country_code")


def _eval_resolved_country_code(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    if "resolved_country_code" not in expected:
        return None
    actual = _resolved_country_code(response)
    want = expected["resolved_country_code"]
    return _bool_eval("resolved_country_code", actual == want, f"active_filters.country_code={actual!r}, expected {want!r}")


def _eval_if_resolved_country_code(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    if "if_resolved_country_code" not in expected:
        return None
    if _requires_clarification(response):
        return _skip("if_resolved_country_code", "clarify issued instead of a direct resolution — n/a")
    actual = _resolved_country_code(response)
    want = expected["if_resolved_country_code"]
    return _bool_eval("if_resolved_country_code", actual == want, f"active_filters.country_code={actual!r}, expected {want!r}")


def _eval_clarify_expected(expected: dict[str, Any], response: dict[str, Any] | None) -> Evaluation | None:
    if "clarify_expected" not in expected:
        return None
    actual = _requires_clarification(response)
    want = bool(expected["clarify_expected"])
    return _bool_eval("clarify_expected", actual == want, f"requires_clarification={actual}, expected {want}")


# ISO2 -> a few textual hints a clarifying question might use to name the
# country. Deliberately small (only codes actually used by our datasets) —
# a real "did the clarify mention country X" check would need the leaf's own
# candidate-place text, not just a code; this is best-effort (weak signal,
# same tier as message_must_contain_any per the README's own vocabulary).
_COUNTRY_HINTS: dict[str, list[str]] = {
    "FR": ["FR", "France"],
    "GB": ["GB", "UK", "United Kingdom", "Royaume-Uni", "Great Britain"],
    "US": ["US", "USA", "United States", "États-Unis", "Etats-Unis"],
}


def _eval_clarify_options_include_country(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    if "clarify_options_include_country" not in expected:
        return None
    message = _message(response)
    missing = []
    for code in expected["clarify_options_include_country"]:
        hints = _COUNTRY_HINTS.get(code, [code])
        if not any(h in message for h in hints):
            missing.append(code)
    ok = not missing
    return _bool_eval(
        "clarify_options_include_country", ok,
        "all options present" if ok else f"missing hints for {missing} (best-effort text match)",
    )


_MUST_ASK_CITY_RE = re.compile(
    r"quelle ville|dans quelle ville|which city|what city", re.IGNORECASE
)


def _eval_must_ask_city(expected: dict[str, Any], response: dict[str, Any] | None) -> Evaluation | None:
    if "must_ask_city" not in expected:
        return None
    asked = bool(_MUST_ASK_CITY_RE.search(_message(response)))
    want = bool(expected["must_ask_city"])
    return _bool_eval(
        "must_ask_city", asked == want,
        f"message {'asks' if asked else 'does not ask'} for a city (keyword heuristic, weak signal)",
    )


def _eval_message_contains(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    if "message_must_contain_any" not in expected:
        return None
    message = _message(response)
    wanted = expected["message_must_contain_any"]
    hit = [w for w in wanted if w in message]
    return _bool_eval(
        "message_must_contain_any", bool(hit), f"matched {hit}" if hit else f"none of {wanted} found"
    )


def _eval_message_not_contains(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    if "message_must_not_contain_any" not in expected:
        return None
    message = _message(response)
    forbidden = expected["message_must_not_contain_any"]
    hit = [w for w in forbidden if w in message]
    return _bool_eval(
        "message_must_not_contain_any", not hit, f"found forbidden {hit}" if hit else "none present"
    )


def _eval_active_filters_include(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    if "active_filters_include" not in expected:
        return None
    filters = _filters(response)
    mismatches: list[str] = []
    for key, want in expected["active_filters_include"].items():
        actual = filters.get(key)
        if isinstance(want, list):
            actual_list = actual if isinstance(actual, list) else []
            if not all(v in actual_list for v in want):
                mismatches.append(f"{key}: expected superset of {want}, got {actual_list}")
        elif actual != want:
            mismatches.append(f"{key}: expected {want!r}, got {actual!r}")
    return _bool_eval(
        "active_filters_include", not mismatches, "; ".join(mismatches) or "all keys matched"
    )


def _eval_offers_capacity_gte(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    if "offers_capacity_gte" not in expected:
        return None
    want = expected["offers_capacity_gte"]
    hotels = _hotels(response)
    # Field name assumed for the not-yet-shipped P0-1 fix (audit
    # AUDIT-AGENTIQUE-2026-07-30.md §4): a card-level "capacity", snake_case
    # like the card's other fields (price_eur_cents, rating_count). Update
    # here if the eventual fix names it differently.
    bad = [h.get("name", h.get("id")) for h in hotels if not isinstance(h.get("capacity"), int) or h["capacity"] < want]
    return _bool_eval(
        "offers_capacity_gte", not bad,
        "; ".join(f"{b}: capacity missing/too low" for b in bad) or f"all {len(hotels)} hotels ok",
    )


def _eval_offers_children_capacity_gte(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    if "offers_children_capacity_gte" not in expected:
        return None
    want = expected["offers_children_capacity_gte"]
    hotels = _hotels(response)
    bad = [
        h.get("name", h.get("id"))
        for h in hotels
        if not isinstance(h.get("children_capacity"), int) or h["children_capacity"] < want
    ]
    return _bool_eval(
        "offers_children_capacity_gte", not bad,
        "; ".join(f"{b}: children_capacity missing/too low" for b in bad) or f"all {len(hotels)} hotels ok",
    )


def _eval_party_total(expected: dict[str, Any], response: dict[str, Any] | None) -> Evaluation | None:
    if "party_total" not in expected:
        return None
    filters = _filters(response)
    total = (filters.get("adults") or 0) + (filters.get("children") or 0)
    want = expected["party_total"]
    clarify_ok = bool(expected.get("clarify_allowed")) and _requires_clarification(response)
    ok = total == want or clarify_ok
    reason = f"adults+children={total}" if total == want else (
        "clarify issued (clarify_allowed)" if clarify_ok else f"adults+children={total}, expected {want}"
    )
    return _bool_eval("party_total", ok, reason)


# --- mcp-dayuse#8: QA 2026-09-30 facts, expected values computed by code ----
# The slot rule is the shared oracle (b2c_common.timeslot, site parity) — the
# one thing evals import from the repo: a second copy could drift from it.
_ISO_DATE_RE = re.compile(r"(?<![\d/-])\d{4}-\d{2}-\d{2}(?![\d-])")
_URL_RE = re.compile(r"https?://\S+")
_CLOSEST_RE = re.compile(r"plus proches|closest|más cercanas|più vicine|nächstgelegenen|mais próximas|dichtstbijzijnde", re.I)


def _minutes(hhmm: Any) -> int | None:
    return parse_hhmm(hhmm)


def _eval_cards_cover_window(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    """Every card covers the slot by the site rule — or none does and the
    answer labels them as the closest offers. A mix is always a failure."""
    window = expected.get("cards_cover_window")
    if not isinstance(window, dict):
        return None
    start, end = _minutes(window.get("start")), _minutes(window.get("end"))
    hotels = _hotels(response)
    if not hotels:
        return _skip("cards_cover_window", "no card to check")
    failing = []
    for hotel in hotels:
        slots = [s for s in hotel.get("timeslots") or [] if isinstance(s, dict)]
        covered = any(
            (s_start := _minutes(s.get("start"))) is not None
            and (s_end := _minutes(s.get("end"))) is not None
            and slot_covers_window(s_start // 60, s_end // 60, start, end)
            for s in slots
        )
        if not covered:
            failing.append(str(hotel.get("name")))
    if not failing:
        return _bool_eval("cards_cover_window", True, "every card covers the slot")
    labelled = len(failing) == len(hotels) and bool(_CLOSEST_RE.search(_message(response)))
    return _bool_eval(
        "cards_cover_window", labelled,
        "none covers, labelled as closest" if labelled else f"not covering: {failing}",
    )


def _eval_offers_on_date(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    """`{"month": M, "day": D}`: every card is an offer for the next
    occurrence of that day (Europe/Paris), the way a person reads "le 3
    octobre"; `{"days_ahead": N}`: today + N."""
    wanted = expected.get("offers_on_date")
    if not isinstance(wanted, dict):
        return None
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    if "days_ahead" in wanted:
        target = today + timedelta(days=int(wanted["days_ahead"]))
    else:
        target = date(today.year, int(wanted["month"]), int(wanted["day"]))
        if target < today:
            target = date(today.year + 1, target.month, target.day)
    hotels = _hotels(response)
    if not hotels:
        return _skip("offers_on_date", "no card to check")
    wrong = sorted({str(h.get("offer_date")) for h in hotels if h.get("offer_date") != target.isoformat()})
    return _bool_eval(
        "offers_on_date", not wrong, f"expected {target.isoformat()}, got {wrong}" if wrong else "ok"
    )


def _eval_no_iso_date_in_message(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    if not expected.get("no_iso_date_in_message"):
        return None
    text = _URL_RE.sub(" ", _message(response))
    hit = _ISO_DATE_RE.findall(text)
    return _bool_eval("no_iso_date_in_message", not hit, f"found {hit}" if hit else "none")


def _eval_first_hotel_name_contains(
    expected: dict[str, Any], response: dict[str, Any] | None
) -> Evaluation | None:
    """mcp-dayuse#7: the hotel the user named is the FIRST card."""
    wanted = expected.get("first_hotel_name_contains")
    if not isinstance(wanted, str):
        return None
    hotels = _hotels(response)
    if not hotels:
        return _bool_eval("first_hotel_name_contains", False, "no card")
    first = str(hotels[0].get("name") or "")
    return _bool_eval(
        "first_hotel_name_contains", wanted.casefold() in first.casefold(), f"first card: {first}"
    )


def _same_text(a: str, b: str) -> bool:
    """Word for word, ignoring case and whitespace runs — never a fuzzy match."""
    return " ".join(a.casefold().split()) == " ".join(b.casefold().split())


def _eval_reply_differs_from_previous(
    expected: dict[str, Any], response: dict[str, Any] | None, previous_reply: str | None
) -> Evaluation | None:
    """QA14707: a turn that answers a question must not hand the same question
    back (« je confirme » → the turn-1 question again)."""
    if not expected.get("reply_differs_from_previous"):
        return None
    if not previous_reply:
        return _skip("reply_differs_from_previous", "no previous reply to compare with")
    message = _message(response)
    same = _same_text(message, previous_reply)
    return _bool_eval(
        "reply_differs_from_previous", not same,
        "reply repeats the previous one word for word" if same else "reply differs from the previous one",
    )


_RESPONSE_CHECKS = (
    _eval_min_hotels,
    _eval_max_hotels,
    _eval_hotels_within_km,
    _eval_resolved_country_code,
    _eval_if_resolved_country_code,
    _eval_clarify_expected,
    _eval_clarify_options_include_country,
    _eval_must_ask_city,
    _eval_message_contains,
    _eval_message_not_contains,
    _eval_active_filters_include,
    _eval_offers_capacity_gte,
    _eval_offers_children_capacity_gte,
    _eval_party_total,
    _eval_cards_cover_window,
    _eval_offers_on_date,
    _eval_no_iso_date_in_message,
    _eval_first_hotel_name_contains,
)


def response_evaluator(
    *, input: Any, output: Any, expected_output: Any, metadata: dict[str, Any] | None, **_: Any
) -> list[Evaluation]:
    """Response-level checks — everything readable straight off the /v3/chat
    JSON body. `output` is the task's return value (see module docstring)."""
    expected = expected_output or {}
    response = (output or {}).get("response") if isinstance(output, dict) else None
    evaluations = [e for check in _RESPONSE_CHECKS if (e := check(expected, response)) is not None]
    previous_reply = (output or {}).get("previous_reply") if isinstance(output, dict) else None
    if (e := _eval_reply_differs_from_previous(expected, response, previous_reply)) is not None:
        evaluations.append(e)
    if response is None:
        # In particular max_hotels=0 and forbidden-text checks used to pass on
        # transport failure: an absent reply isn't a correct FAQ answer.
        return [_skip(e.name, "chat response unavailable; cannot grade this assertion") for e in evaluations]
    return evaluations


# --- trace-level checks -------------------------------------------------------
def _eval_search_offers_args_include(
    expected: dict[str, Any], trace_facts: dict[str, Any]
) -> Evaluation | None:
    if "search_offers_args_include" not in expected:
        return None
    args = trace_facts.get("search_offers_args")
    if args is None:
        return _skip(
            "search_offers_args_include",
            "search_offers TOOL observation not found in the leaf trace (async export lag, or the "
            "leaf never called it)",
        )
    mismatches = [f"{k}: expected {v!r}, got {args.get(k)!r}" for k, v in expected["search_offers_args_include"].items() if args.get(k) != v]
    return _bool_eval(
        "search_offers_args_include", not mismatches, "; ".join(mismatches) or "all args matched"
    )


def _eval_search_offers_args_absent(
    expected: dict[str, Any], trace_facts: dict[str, Any]
) -> Evaluation | None:
    if "search_offers_args_absent" not in expected:
        return None
    args = trace_facts.get("search_offers_args")
    if args is None:
        return _skip(
            "search_offers_args_absent",
            "search_offers TOOL observation not found in the leaf trace (async export lag, or the "
            "leaf never called it)",
        )
    present = [k for k in expected["search_offers_args_absent"] if k in args]
    return _bool_eval(
        "search_offers_args_absent", not present, f"unexpectedly present: {present}" if present else "none present"
    )


def _eval_expected_pick(expected: dict[str, Any], trace_facts: dict[str, Any]) -> Evaluation | None:
    if "expected_pick" not in expected:
        return None
    pick = trace_facts.get("pick")
    if pick is None:
        return _skip("expected_pick", "triage generation output not found in the concierge trace")
    want = expected["expected_pick"]
    ok = pick.get("pick") == want.get("pick") and pick.get("pick_position") == want.get("pick_position")
    return _bool_eval("expected_pick", ok, f"got {pick}, expected {want}")


def _eval_expected_route(expected: dict[str, Any], trace_facts: dict[str, Any]) -> Evaluation | None:
    if "expected_route" not in expected:
        return None
    route = trace_facts.get("route")
    if route is None:
        return _skip("expected_route", "triage family/route not found in the concierge trace")
    want = expected["expected_route"]
    return _bool_eval("expected_route", route == want, f"derived route={route!r}, expected {want!r}")


def _eval_geocode_city_needed(expected: dict[str, Any], trace_facts: dict[str, Any]) -> Evaluation | None:
    """Did `geocode_location` end the turn on « which city? » (the leaf's
    `geocode_city_needed`, a question without options)?"""
    if "geocode_city_needed" not in expected:
        return None
    geocode = trace_facts.get("geocode")
    if geocode is None:
        return _skip(
            "geocode_city_needed",
            "geocode_location TOOL observation not found in the last turn's trace (async export lag, "
            "or the leaf never called it)",
        )
    want = bool(expected["geocode_city_needed"])
    actual = bool(geocode.get("city_needed"))
    return _bool_eval("geocode_city_needed", actual == want, f"city_needed={actual}, expected {want}")


# The observation name of the concierge's inline MCP calls, exactly
# (`b2c_concierge.inline_tools._call_tool`). A call under any other name is not
# counted: see `_lookup_trace_facts` in evals/langfuse_experiment.py.
_INLINE_TOOL_PREFIX = "mcp-"


def _eval_tools_not_called(expected: dict[str, Any], trace_facts: dict[str, Any]) -> Evaluation | None:
    """None of these inline tools was called in the LAST turn
    (`generate_booking_link`, `find_hotel_by_name`)."""
    if "tools_not_called" not in expected:
        return None
    calls = trace_facts.get("tool_calls")
    if calls is None:
        return _skip("tools_not_called", "no observation found in the last turn's trace (async export lag)")
    called = [name for name in expected["tools_not_called"] if f"{_INLINE_TOOL_PREFIX}{name}" in calls]
    return _bool_eval(
        "tools_not_called", not called, f"called in the last turn: {called}" if called else "none called"
    )


def _geocoder_text(geocode: dict[str, Any]) -> str:
    parts = [
        str(option.get(key) or "")
        for option in geocode.get("options") or []
        for key in ("name", "region", "place_formatted")
    ]
    return " ".join(parts).casefold()


def _eval_clarify_options_from_geocoder(
    expected: dict[str, Any],
    trace_facts: dict[str, Any],
    response: dict[str, Any] | None,
    user_text: str,
) -> Evaluation | None:
    """No invented option: of the places the assertion lists (`["Paris",
    "Bruxelles", …]`, the ones a model is tempted to offer), each one the
    reply names must be a candidate the geocoder returned — or a word the user
    wrote himself. The reply carries no structured options, so this is a text
    match on the listed names only: a weak signal, same tier as `must_ask_city`.
    With no candidate at all (`geocode_city_needed`), nothing is allowed."""
    watched = expected.get("clarify_options_from_geocoder")
    if not isinstance(watched, list):
        return None
    geocode = trace_facts.get("geocode")
    if geocode is None:
        return _skip(
            "clarify_options_from_geocoder",
            "geocode_location TOOL observation not found in the last turn's trace (async export lag, "
            "or the leaf never called it)",
        )
    message = _message(response).casefold()
    grounded = f"{_geocoder_text(geocode)} {user_text.casefold()}"
    invented = [p for p in watched if str(p).casefold() in message and str(p).casefold() not in grounded]
    return _bool_eval(
        "clarify_options_from_geocoder", not invented,
        f"offered without being a geocoder candidate: {invented}" if invented else "no invented option",
    )


_TRACE_CHECKS = (
    _eval_search_offers_args_include,
    _eval_search_offers_args_absent,
    _eval_expected_pick,
    _eval_expected_route,
    _eval_geocode_city_needed,
    _eval_tools_not_called,
)


def trace_evaluator(
    *, input: Any, output: Any, expected_output: Any, metadata: dict[str, Any] | None, **_: Any
) -> list[Evaluation]:
    """Trace-level checks — read from `output["trace"]`, populated by the task
    function via a best-effort Langfuse trace lookup (bounded retries; a miss
    degrades to a `skipped`-style Evaluation, never a false pass)."""
    expected = (expected_output or {}).get("trace") or {}
    if not expected:
        return []
    trace_facts = (output or {}).get("trace") or {} if isinstance(output, dict) else {}
    evaluations = [e for check in _TRACE_CHECKS if (e := check(expected, trace_facts)) is not None]
    response = (output or {}).get("response") if isinstance(output, dict) else None
    if (
        e := _eval_clarify_options_from_geocoder(
            expected, trace_facts, response, _user_text(input)
        )
    ) is not None:
        evaluations.append(e)
    return evaluations


def _user_text(item_input: Any) -> str:
    """Everything the user typed in the replayed turns."""
    messages = item_input.get("messages") if isinstance(item_input, dict) else None
    return " ".join(
        str(m.get("content") or "")
        for m in messages or []
        if isinstance(m, dict) and m.get("role") == "user"
    )


ALL_EVALUATORS = (response_evaluator, trace_evaluator)
