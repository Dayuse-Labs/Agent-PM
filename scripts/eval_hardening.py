#!/usr/bin/env python3
"""eval_hardening.py — S-G8: an annotation/scoring layer OVER dayuse_eval_pack
results, implementing the 8 "Durcissements du harness" items from
`REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md`. The pack itself
(`dayuse_eval_pack/eval_pack/**`) is NEVER read as writable and NEVER modified —
this module only reads its case fixtures (read-only) and a run report already
produced by the untouched `eval_pack.runner` (schema: `{summary, results:[...]}`
as built by `runner.build_report`), and adds checks/classifications on top, in a
brand-new output file the caller names explicitly.

Deliberately standalone stdlib (no import from `dayuse_eval_pack/` or
`agents/`): the pack's own philosophy is outcome-based / black-box ("the
colleague's implementation does not need to share Dayuse's internal class
names") and this harness layer holds itself to the same rule — it only reads
the public `/v3/chat`-shaped response fields any adapter could produce.

Convention for every check below, because a false green here would corrupt the
audit exactly like a fabricated field would in `run_eval_adapter.py`:
  - "pass"/"fail": the check applies AND the field it needs exists.
  - "skipped" (with a `field_missing` reason): the check would apply, but the
    response schema does not expose the key at all (`key not in dict`) — e.g.
    an older architecture, or a wave (S-G3/S-G5/S-G6/S-G7) not merged yet.
    Never counted as a pass.
  - Not applicable (the check's precondition isn't met on this turn, e.g. no
    destination was ever searched): the function returns nothing for that
    turn — silently omitted, not reported as skipped (that would be noise,
    not disclosure).

Usage:
    python3 scripts/eval_hardening.py \\
        --cases-dir dayuse_eval_pack/eval_pack/cases \\
        --report /path/to/candidate.json \\
        --output /path/to/candidate.annotated.json
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# --- shared response accessors (small, deliberate re-implementation of
# eval_pack.runner's private helpers — see module docstring for why) ---------
def _hotels(response: dict[str, Any]) -> list[dict[str, Any]]:
    value = response.get("hotels")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _filters(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("active_filters")
    return value if isinstance(value, dict) else {}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def _hotel_key(hotel: dict[str, Any]) -> str:
    return str(hotel.get("id") or hotel.get("hotel_id") or _norm(hotel.get("name")))


def _hotel_currency(hotel: dict[str, Any]) -> str | None:
    for key in ("display_currency", "currency"):
        value = hotel.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return None


def _turn_responses(case: dict[str, Any], result: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Zip case turns with their result turns, by index. A case/result turn
    count mismatch (e.g. a client-side exception aborted early) truncates to
    the shorter of the two rather than raising — the caller sees fewer pairs,
    never an invented one."""
    case_turns = case.get("turns") or []
    result_turns = result.get("turns") or []
    pairs = []
    for case_turn, result_turn in zip(case_turns, result_turns):
        response = result_turn.get("response")
        if isinstance(response, dict):
            pairs.append((case_turn, response))
    return pairs


def _skip(check: str, turn: int, detail: str) -> dict[str, Any]:
    return {"check": check, "turn": turn, "status": "skipped", "detail": detail}


def _outcome(check: str, turn: int, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": check, "turn": turn, "status": "pass" if passed else "fail", "detail": detail}


# --- item 1: min_hotels coverage gap on geo cases ----------------------------
def geo_cases_missing_min_hotels(cases: list[dict[str, Any]]) -> list[str]:
    """Geo-suite case ids whose OWN fixture assertions already imply a
    resolvable, non-ambiguous destination (a `hotel_countries` allow-list) but
    never assert `min_hotels`/`max_hotels` anywhere — the pack's own coverage
    gap. Generated purely from the fixtures (assertion types present), never
    hand-picked."""
    missing = []
    for case in cases:
        if case.get("suite") != "geo":
            continue
        types = {
            str(assertion.get("type"))
            for turn in case.get("turns") or []
            for assertion in turn.get("expect") or []
        }
        if "hotel_countries" in types and "min_hotels" not in types and "max_hotels" not in types:
            missing.append(str(case["id"]))
    return missing


def check_min_hotels_added(
    case: dict[str, Any], result: dict[str, Any], *, min_value: int = 1
) -> list[dict[str, Any]]:
    """The added `min_hotels >= min_value` check for a case flagged by
    `geo_cases_missing_min_hotels` — applied to every turn (these cases are
    single-turn today, but nothing here assumes it)."""
    outcomes = []
    for index, (_, response) in enumerate(_turn_responses(case, result), start=1):
        count = len(_hotels(response))
        outcomes.append(
            _outcome("min_hotels_added", index, count >= min_value, f"{count} hotels, expected >= {min_value}")
        )
    return outcomes


# --- item 2: 3(+1)-class turn/case outcome -----------------------------------
# Mirrors the wording of agents/b2c_concierge/b2c_concierge/templates.py's
# _DEGRADED_FR/_DEGRADED_EN (hardcoded here, not imported — this harness stays
# outcome-based/black-box like the rest of the pack, per its own README).
_DEGRADED_PHRASES = (
    "i can't reach the hotel search",
    "i can't look up the dayuse conditions",
    "je n'arrive pas a joindre la recherche d'hotels",
    "je n'arrive pas a consulter les conditions dayuse",
)

_TIMEOUT_HTTP_STATUSES = {408, 504, 599}


def classify_turn_outcome(response: dict[str, Any]) -> str:
    """One of: technical_degradation, safe_clarification, successful_search,
    no_result_honest (a legitimate empty/non-search answer — kept distinct so
    it is never silently folded into "successful_search")."""
    status = response.get("_http_status")
    message = _norm(response.get("message") or response.get("response"))
    if (isinstance(status, int) and status not in (200,)) or response.get("_client_error"):
        return "technical_degradation"
    if any(phrase in message for phrase in _DEGRADED_PHRASES):
        return "technical_degradation"
    if bool(response.get("requires_clarification")):
        return "safe_clarification"
    if _hotels(response):
        return "successful_search"
    return "no_result_honest"


def classify_case_outcome(result: dict[str, Any]) -> str | None:
    """The case's terminal outcome = its last turn's classification (the
    conversation's actual ending state)."""
    turns = result.get("turns") or []
    if not turns:
        return None
    response = turns[-1].get("response")
    if not isinstance(response, dict):
        return None
    return classify_turn_outcome(response)


# --- item 3: country + anchor resolved even with an empty shortlist ----------
def check_anchor_resolved_when_empty(case: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    """Applies only when a destination was actually targeted (`city` truthy)
    and the search came back empty — the exact "honest 0-hotel" scenario the
    review flags. A destination that was never searched (FAQ/non-search
    turns) yields nothing for that turn (not applicable, not a skip)."""
    outcomes = []
    for index, (_, response) in enumerate(_turn_responses(case, result), start=1):
        filters = _filters(response)
        if not filters.get("city") or _hotels(response):
            continue
        if "country_code" not in filters or "resolved_city" not in filters:
            outcomes.append(
                _skip("anchor_resolved_empty_shortlist", index, "country_code/resolved_city not in active_filters")
            )
            continue
        resolved = bool(filters.get("country_code")) and bool(filters.get("resolved_city"))
        outcomes.append(
            _outcome(
                "anchor_resolved_empty_shortlist",
                index,
                resolved,
                f"country_code={filters.get('country_code')!r} resolved_city={filters.get('resolved_city')!r}",
            )
        )
    return outcomes


# --- item 4: per-turn field assertions (date, zone, horaires, devise, named_hotel) --
def check_currency_per_turn(case: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = str((case.get("request") or {}).get("currency") or "").strip().upper()
    if not expected:
        return []
    outcomes = []
    for index, (_, response) in enumerate(_turn_responses(case, result), start=1):
        filters = _filters(response)
        hotels = _hotels(response)
        seen = {c for h in hotels if (c := _hotel_currency(h))}
        has_filter_currency = "currency" in filters
        if not has_filter_currency and not hotels:
            continue  # nothing to check this turn (no cards, no filter key)
        if not has_filter_currency and not seen:
            outcomes.append(_skip("currency_per_turn", index, "no currency field on active_filters or hotel cards"))
            continue
        actual = {str(filters.get("currency")).upper()} if filters.get("currency") else set()
        actual |= seen
        outcomes.append(
            _outcome(
                "currency_per_turn", index, actual == {expected} if actual else False, f"actual={sorted(actual)}, expected={expected}"
            )
        )
    return outcomes


# HH:MM / HHhMM with an explicit non-zero minute, optional am/pm suffix. No
# trailing \b (digit+letter is not a word-boundary transition — "7:30am"
# would otherwise be missed).
_TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:h]([0-5]\d)(?:\s*([ap]\.?m\.?))?", re.IGNORECASE)


def _explicit_nonzero_minutes(message: str) -> set[str]:
    return {minute for _, minute, _ in _TIME_RE.findall(message) if minute != "00"}


def check_timeslot_minutes(case: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    """A4 regression guard: if the user's turn explicitly names a non-zero
    minute ("7:30am", "14h30"...), at least one of timeslot_start/timeslot_end
    must carry that SAME minute — never silently rounded to :00."""
    outcomes = []
    for index, (case_turn, response) in enumerate(_turn_responses(case, result), start=1):
        minutes = _explicit_nonzero_minutes(case_turn.get("message") or "")
        if not minutes:
            continue
        filters = _filters(response)
        start, end = filters.get("timeslot_start"), filters.get("timeslot_end")
        if "timeslot_start" not in filters and "timeslot_end" not in filters:
            outcomes.append(_skip("timeslot_minutes", index, "timeslot_start/timeslot_end not in active_filters"))
            continue
        observed = {
            str(value).split(":")[-1]
            for value in (start, end)
            if isinstance(value, str) and ":" in value
        }
        preserved = bool(observed & minutes)
        outcomes.append(
            _outcome(
                "timeslot_minutes",
                index,
                preserved,
                f"message minutes={sorted(minutes)}, timeslot_start={start!r} timeslot_end={end!r}",
            )
        )
    return outcomes


def check_zone_change(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    """For cases tagged `zone_change` (fixture-driven, not hand-picked): the
    LAST refinement should actually have moved the PLACE — recorded wherever
    the agent records it (`zone` for a sub-city area, `city`/`resolved_city`
    for a neighboring city, decision D2-a 2026-07-23: "Fort Lauderdale" is a
    city, so pinning this check to `zone` made the family structurally
    unpassable)."""
    if "zone_change" not in (case.get("tags") or []):
        return None
    pairs = _turn_responses(case, result)
    if len(pairs) < 2:
        return None
    last_filters = _filters(pairs[-1][1])
    prev_filters = _filters(pairs[-2][1])
    place_keys = ("zone", "city", "resolved_city")
    if not any(key in last_filters for key in place_keys):
        return _skip("zone_change", len(pairs), "no place field in active_filters")
    changed = any(
        bool(last_filters.get(key)) and last_filters.get(key) != prev_filters.get(key)
        for key in place_keys
    )
    moves = {key: (prev_filters.get(key), last_filters.get(key)) for key in place_keys}
    return _outcome("zone_change", len(pairs), changed, f"place moves={moves}")


def check_named_hotel_present(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    """For cases tagged `named_hotel_present`: once the named hotel is
    resolved it must not silently disappear from `active_filters` on a later
    turn (state carryover, S-G1)."""
    if "named_hotel_present" not in (case.get("tags") or []):
        return None
    pairs = _turn_responses(case, result)
    if not pairs:
        return None
    last_filters = _filters(pairs[-1][1])
    if "named_hotel" not in last_filters:
        return _skip("named_hotel_present", len(pairs), "named_hotel not in active_filters")
    named = last_filters.get("named_hotel")
    resolved = isinstance(named, dict) and bool(named.get("hotel_id"))
    return _outcome("named_hotel_present", len(pairs), resolved, f"named_hotel={named!r}")


_TOMORROW_TERMS = ("tomorrow", "demain")
_TODAY_TERMS = ("today", "aujourd'hui", "aujourdhui")


def check_date_reference(case: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    """Mechanically derived, no hand-authored expected date: the case's own
    frozen `clock` + an explicit "today"/"tomorrow" (or fr equivalent) mention
    fixes the expected calendar date; compares against `active_filters.date`
    (the resolved ISO date, NOT `date_reference` — that field is a dict
    {expression, resolved_from, client_tz}, a documented pre-existing gap,
    see HANDOFF S-A, out of scope here)."""
    clock = case.get("clock")
    if not isinstance(clock, str):
        return []
    try:
        clock_date = datetime.fromisoformat(clock.replace("Z", "+00:00")).date()
    except ValueError:
        return []
    outcomes = []
    for index, (case_turn, response) in enumerate(_turn_responses(case, result), start=1):
        message = _norm(case_turn.get("message") or "")
        wants_tomorrow = any(term in message for term in _TOMORROW_TERMS)
        wants_today = any(term in message for term in _TODAY_TERMS)
        if wants_tomorrow == wants_today:
            continue  # neither mentioned, or both (ambiguous) — not applicable
        expected = clock_date + timedelta(days=1) if wants_tomorrow else clock_date
        filters = _filters(response)
        if "date" not in filters:
            outcomes.append(_skip("date_reference", index, "date not in active_filters"))
            continue
        raw = filters.get("date")
        actual_date = None
        if isinstance(raw, str):
            try:
                actual_date = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
            except ValueError:
                actual_date = None
        outcomes.append(
            _outcome("date_reference", index, actual_date == expected, f"date={raw!r}, expected={expected.isoformat()}")
        )
    return outcomes


def check_turn_fields(case: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    """Item 4 entry point: every per-turn field check, concatenated."""
    outcomes = list(check_currency_per_turn(case, result))
    outcomes += check_timeslot_minutes(case, result)
    outcomes += check_date_reference(case, result)
    zone = check_zone_change(case, result)
    if zone is not None:
        outcomes.append(zone)
    named_hotel = check_named_hotel_present(case, result)
    if named_hotel is not None:
        outcomes.append(named_hotel)
    return outcomes


# --- item 5: distance verifiability ------------------------------------------
_PROXIMITY_ASSERTION_TYPES = {"distance_accuracy", "distance_disclosure", "local_before_far"}


def case_requires_proximity(case: dict[str, Any]) -> bool:
    return any(
        assertion.get("type") in _PROXIMITY_ASSERTION_TYPES
        for turn in case.get("turns") or []
        for assertion in turn.get("expect") or []
    )


def check_distance_verifiable(case: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    """When a case's OWN fixture demands proximity, an unverifiable distance
    on a returned card is a FAIL, not a skip — the review's item 5 verbatim
    ("échouer... quand le cas impose la proximité"). Distinguishes "the
    architecture doesn't expose distance_km at all" (skipped) from "it does,
    but this specific card has none" (fail)."""
    if not case_requires_proximity(case):
        return []
    outcomes = []
    for index, (_, response) in enumerate(_turn_responses(case, result), start=1):
        hotels = _hotels(response)
        if not hotels:
            continue  # empty shortlist is item 3's concern, not item 5's
        supports_distance = any("distance_km" in h for h in hotels)
        if not supports_distance:
            outcomes.append(_skip("distance_verifiable", index, "distance_km not present on any hotel card"))
            continue
        unverifiable = [h.get("name") for h in hotels if h.get("distance_km") is None]
        outcomes.append(
            _outcome(
                "distance_verifiable",
                index,
                not unverifiable,
                f"{len(unverifiable)}/{len(hotels)} cards missing distance_km: {unverifiable[:5]}",
            )
        )
    return outcomes


# --- item 6: "autres options" — minimum new IDs or exhaustion disclosure ----
_OTHER_OPTIONS_RE = re.compile(
    r"\b(other|different|more|cheaper)\s+options?\b|\bautres?\s+options?\b", re.IGNORECASE
)
_EXHAUSTION_PHRASES = (
    "widening the budget",
    "elargi le budget",  # accent-stripped by _norm
    "try a different city",
    "essayez une autre ville",
    "no more options",
    "aucune autre option",
)


def other_options_turns(case: dict[str, Any]) -> list[int]:
    """1-indexed turn numbers whose message explicitly asks for alternates.
    turn 1 never qualifies (there is nothing to be "other" than yet) — this
    is derived purely from message text, not hand-picked case ids."""
    turns = []
    for index, turn in enumerate(case.get("turns") or [], start=1):
        if index > 1 and _OTHER_OPTIONS_RE.search(turn.get("message") or ""):
            turns.append(index)
    return turns


def check_other_options(case: dict[str, Any], result: dict[str, Any], *, min_new: int = 1) -> list[dict[str, Any]]:
    targets = set(other_options_turns(case))
    if not targets:
        return []
    pairs = _turn_responses(case, result)
    outcomes = []
    for index, (_, response) in enumerate(pairs, start=1):
        if index not in targets:
            continue
        previous_response = pairs[index - 2][1] if index >= 2 else {}
        previous_ids = {_hotel_key(h) for h in _hotels(previous_response)}
        if not previous_ids:
            continue  # nothing to compare a "new" shortlist against
        current_hotels = _hotels(response)
        current_ids = {_hotel_key(h) for h in current_hotels}
        new_ids = current_ids - previous_ids
        message = _norm(response.get("message") or response.get("response"))
        exhausted = any(phrase in message for phrase in _EXHAUSTION_PHRASES)
        passed = len(new_ids) >= min_new or exhausted
        outcomes.append(
            _outcome(
                "other_options",
                index,
                passed,
                f"new_ids={len(new_ids)}/{min_new} required, exhaustion_disclosed={exhausted}",
            )
        )
    return outcomes


# --- item 7: triple report -----------------------------------------------------
def _turn_is_timeout(response: dict[str, Any]) -> bool:
    status = response.get("_http_status")
    if isinstance(status, int) and status in _TIMEOUT_HTTP_STATUSES:
        return True
    error = _norm(response.get("_client_error"))
    return "timeout" in error


def build_triple_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Item 7: raw score / score excluding technical-degradation cases /
    timeout rate — reported SEPARATELY, never blended into one number."""
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    degraded_ids = {
        str(r["id"]) for r in results if classify_case_outcome(r) == "technical_degradation"
    }
    excl_results = [r for r in results if str(r.get("id")) not in degraded_ids]
    excl_total = len(excl_results)
    excl_passed = sum(1 for r in excl_results if r.get("passed"))

    all_turns = [turn for r in results for turn in (r.get("turns") or [])]
    timed_out_turns = [t for t in all_turns if isinstance(t.get("response"), dict) and _turn_is_timeout(t["response"])]
    cases_with_timeout = {
        str(r["id"])
        for r in results
        if any(
            isinstance(t.get("response"), dict) and _turn_is_timeout(t["response"]) for t in (r.get("turns") or [])
        )
    }

    return {
        "raw": {"total": total, "passed": passed, "pass_rate": round(passed / total, 4) if total else 0.0},
        "excluding_technical_degradation": {
            "total": excl_total,
            "passed": excl_passed,
            "pass_rate": round(excl_passed / excl_total, 4) if excl_total else 0.0,
            "excluded_case_ids": sorted(degraded_ids),
        },
        "timeout_rate": {
            "turn_total": len(all_turns),
            "turn_timeouts": len(timed_out_turns),
            "turn_timeout_rate": round(len(timed_out_turns) / len(all_turns), 4) if all_turns else 0.0,
            "case_timeout_rate": round(len(cases_with_timeout) / total, 4) if total else 0.0,
            "case_ids_with_timeout": sorted(cases_with_timeout),
        },
    }


# --- orchestration --------------------------------------------------------------
def load_cases(cases_dir: Path) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for path in sorted(cases_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                cases[str(case["id"])] = case
    return cases


def annotate_result(case: dict[str, Any] | None, result: dict[str, Any]) -> dict[str, Any]:
    case_outcome = classify_case_outcome(result)
    turn_outcomes = [
        classify_turn_outcome(turn["response"])
        for turn in result.get("turns") or []
        if isinstance(turn.get("response"), dict)
    ]
    annotation: dict[str, Any] = {
        "id": result.get("id"),
        "suite": result.get("suite"),
        "case_outcome": case_outcome,
        "turn_outcomes": turn_outcomes,
        "checks": [],
    }
    if case is None:
        annotation["checks"].append(_skip("case_lookup", 0, "case id not found in --cases-dir fixtures"))
        return annotation

    checks: list[dict[str, Any]] = []
    if case.get("id") in geo_cases_missing_min_hotels([case]):
        checks += check_min_hotels_added(case, result)
    checks += check_anchor_resolved_when_empty(case, result)
    checks += check_turn_fields(case, result)
    checks += check_distance_verifiable(case, result)
    checks += check_other_options(case, result)
    annotation["checks"] = checks
    return annotation


def annotate_report(report: dict[str, Any], cases_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    results = report.get("results") or []
    annotations = [annotate_result(cases_by_id.get(str(r.get("id"))), r) for r in results]
    return {
        "schema_version": "1.0",
        "source_endpoint": report.get("endpoint"),
        "triple_report": build_triple_report(results),
        "outcome_counts": {
            outcome: sum(1 for a in annotations if a["case_outcome"] == outcome)
            for outcome in ("successful_search", "safe_clarification", "technical_degradation", "no_result_honest")
        },
        "cases": annotations,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", required=True, help="A run report already produced by eval_pack.runner")
    parser.add_argument("--cases-dir", required=True, help="dayuse_eval_pack/eval_pack/cases (read-only)")
    parser.add_argument("--output", required=True, help="Where to write the annotated report (never inside eval_pack/)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    cases = load_cases(Path(args.cases_dir))
    annotated = annotate_report(report, cases)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(annotated, ensure_ascii=False, indent=2), encoding="utf-8")
    triple = annotated["triple_report"]
    print(f"raw: {triple['raw']['passed']}/{triple['raw']['total']} ({triple['raw']['pass_rate']:.1%})")
    excl = triple["excluding_technical_degradation"]
    print(f"excluding technical degradation: {excl['passed']}/{excl['total']} ({excl['pass_rate']:.1%})")
    timeout = triple["timeout_rate"]
    print(f"timeout rate: turns {timeout['turn_timeout_rate']:.1%}, cases {timeout['case_timeout_rate']:.1%}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
