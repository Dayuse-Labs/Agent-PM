"""Run canonical Dayuse evaluations against any compatible chat endpoint.

The runner intentionally depends only on the Python standard library.  A new
architecture only needs to expose a small HTTP adapter compatible with the
request/response contract documented in ``eval_pack/README.md``.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    check_type: str
    passed: bool
    message: str
    severity: str = "critical"


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().replace("ﬁ", "fi").split())


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", value.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group().replace(",", "."))
    except ValueError:
        return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _hotels(response: dict[str, Any]) -> list[dict[str, Any]]:
    value = response.get("hotels")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _filters(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("active_filters")
    return value if isinstance(value, dict) else {}


def _hotel_geo_blob(hotel: dict[str, Any]) -> str:
    return _norm(
        " ".join(
            str(hotel.get(key) or "")
            for key in (
                "name",
                "city",
                "metro",
                "zone",
                "primary_zone",
                "country",
                "country_code",
            )
        )
    )


def _hotel_amenity_blob(hotel: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("amenities", "highlights", "selling_points", "match_reasons"):
        raw = hotel.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    for key in ("name", "ai_recommendation"):
        values.append(str(hotel.get(key) or ""))
    for key in ("has_pool", "has_spa", "has_air_conditioning", "in_room_jacuzzi"):
        if hotel.get(key):
            values.append(key)
    return _norm(" ".join(values)).replace("_", " ")


AMENITY_ALIASES: dict[str, tuple[str, ...]] = {
    "pool": ("pool", "piscina", "piscine", "schwimmbad", "zwembad"),
    "spa": ("spa", "wellness", "sauna", "hammam"),
    "jacuzzi": ("jacuzzi", "hot tub", "whirlpool", "spa bath", "in room jacuzzi"),
    "air_conditioning": (
        "air conditioning",
        "air conditioned",
        "climatisation",
        "aria condizionata",
        "ar condicionado",
        "klimaanlage",
    ),
    "wifi": ("wifi", "wi fi", "internet"),
}


def _has_amenity(hotel: dict[str, Any], amenity: str) -> bool:
    blob = _hotel_amenity_blob(hotel)
    aliases = AMENITY_ALIASES.get(amenity, (amenity.replace("_", " "),))
    return any(_norm(alias) in blob for alias in aliases)


def _hotel_price(hotel: dict[str, Any]) -> float | None:
    for key in ("display_price", "price", "min_price"):
        value = _number(hotel.get(key))
        if value is not None:
            return value
    return None


def _hotel_currency(hotel: dict[str, Any]) -> str:
    for key in ("display_currency", "currency"):
        value = str(hotel.get(key) or "").strip().upper()
        if value:
            return value
    for slot in hotel.get("timeslots") or []:
        if isinstance(slot, dict):
            value = str(slot.get("currency") or "").strip().upper()
            if value:
                return value
    return ""


def _tool_calls(response: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return optional adapter telemetry without making it part of the core contract."""
    value = response.get("tool_calls")
    if value is None:
        debug = response.get("eval_debug")
        value = debug.get("tool_calls") if isinstance(debug, dict) else None
    if value is None:
        return None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _tool_call_key(call: dict[str, Any]) -> str:
    name = str(call.get("name") or call.get("tool") or call.get("function") or "")
    arguments = call.get("arguments", call.get("args", call.get("input", {})))
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = arguments.strip()
    try:
        normalized_arguments = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    except TypeError:
        normalized_arguments = repr(arguments)
    return f"{name}:{normalized_arguments}"


def _check(
    check_type: str,
    passed: bool,
    message: str,
    severity: str = "critical",
) -> CheckResult:
    return CheckResult(
        check_type=check_type, passed=bool(passed), message=message, severity=severity
    )


def _resolve_origin(case: dict[str, Any], assertion: dict[str, Any]) -> tuple[float, float] | None:
    origin = assertion.get("origin")
    if isinstance(origin, list) and len(origin) == 2:
        return float(origin[0]), float(origin[1])
    if origin == "native_geolocation":
        request = case.get("request") or {}
        # Real widget contract (S-G2, verified against the vendored JS):
        # client_geo_context.device.{latitude, longitude}.
        device = (request.get("client_geo_context") or {}).get("device") or {}
        if (
            isinstance(device, dict)
            and device.get("latitude") is not None
            and device.get("longitude") is not None
        ):
            return float(device["latitude"]), float(device["longitude"])
        # Legacy fixture shape, kept readable for any old report replays.
        geo = (request.get("native_context") or {}).get("geolocation") or {}
        if isinstance(geo, dict) and geo.get("lat") is not None and geo.get("lon") is not None:
            return float(geo["lat"]), float(geo["lon"])
    return None


def _evaluate_assertion(
    assertion: dict[str, Any],
    *,
    case: dict[str, Any],
    turn_index: int,
    response: dict[str, Any],
    prior_responses: list[dict[str, Any]],
) -> CheckResult:
    kind = str(assertion.get("type") or "")
    severity = str(assertion.get("severity") or "critical")
    hotels = _hotels(response)
    filters = _filters(response)
    message = str(response.get("message") or response.get("response") or "")

    if kind == "http_status":
        allowed = assertion.get("allowed") or [200]
        actual = response.get("_http_status")
        return _check(
            kind, actual in allowed, f"HTTP {actual}, expected one of {allowed}", severity
        )

    if kind == "min_hotels":
        expected = int(assertion.get("value", 1))
        return _check(
            kind, len(hotels) >= expected, f"{len(hotels)} hotels, expected >= {expected}", severity
        )

    if kind == "max_hotels":
        expected = int(assertion.get("value", 0))
        return _check(
            kind, len(hotels) <= expected, f"{len(hotels)} hotels, expected <= {expected}", severity
        )

    if kind in {"requires_clarification", "ready_to_search"}:
        expected = bool(assertion.get("value"))
        actual = bool(response.get(kind))
        return _check(kind, actual == expected, f"{kind}={actual}, expected {expected}", severity)

    if kind == "filter_equals":
        expected = assertion.get("values") or {}

        def _filter_matches(actual: Any, value: Any) -> bool:
            if actual == value:
                return True
            # A structured filter (e.g. date_reference is a dict with
            # {expression, resolved_from, ...}) matches a plain string
            # expectation via its `expression` — the fixture asserts the
            # user's literal token, not the resolved internals.
            if isinstance(actual, dict) and isinstance(value, str):
                return actual.get("expression") == value
            return False

        failures = {
            key: (filters.get(key), value)
            for key, value in expected.items()
            if not _filter_matches(filters.get(key), value)
        }
        return _check(
            kind,
            not failures,
            f"filter mismatches={failures}" if failures else "filters match",
            severity,
        )

    if kind == "filter_place":
        # The place moved to `value` — recorded wherever the agent records
        # places (`zone` for a sub-city area, `city`/`resolved_city` for a
        # neighboring city). Cross-field on purpose: "Fort Lauderdale" is a
        # city, not a zone of Miami, and the assertion must not encode one
        # modeling choice (decision D2-a, 2026-07-23).
        expected = assertion.get("value")
        actual = {key: filters.get(key) for key in ("zone", "city", "resolved_city")}
        return _check(
            kind,
            expected in actual.values(),
            f"place {expected!r} not in {actual}",
            severity,
        )

    if kind == "filter_not_equals":
        forbidden = assertion.get("values") or {}
        failures = {key: value for key, value in forbidden.items() if filters.get(key) == value}
        return _check(
            kind,
            not failures,
            f"forbidden filters={failures}" if failures else "no forbidden filters",
            severity,
        )

    if kind == "filter_present":
        keys = list(assertion.get("keys") or [])
        missing = [key for key in keys if filters.get(key) in (None, "", [])]
        return _check(
            kind,
            not missing,
            f"missing filters={missing}" if missing else "filters present",
            severity,
        )

    if kind == "filter_absent":
        keys = list(assertion.get("keys") or [])
        present = [key for key in keys if filters.get(key) not in (None, "", [])]
        return _check(
            kind,
            not present,
            f"unexpected filters={present}" if present else "filters absent",
            severity,
        )

    if kind == "preserve_filters":
        source_turn = int(assertion.get("from_turn", max(1, turn_index - 1))) - 1
        if source_turn < 0 or source_turn >= len(prior_responses):
            return _check(kind, False, f"source turn {source_turn + 1} unavailable", severity)
        previous = _filters(prior_responses[source_turn])
        keys = list(assertion.get("keys") or [])
        changes = {
            key: (previous.get(key), filters.get(key))
            for key in keys
            if previous.get(key) != filters.get(key)
        }
        return _check(
            kind,
            not changes,
            f"changed filters={changes}" if changes else "filters preserved",
            severity,
        )

    if kind == "hotel_countries":
        allowed = {str(value).upper() for value in assertion.get("allowed") or []}
        actual = {str(h.get("country_code") or h.get("country") or "").upper() for h in hotels}
        actual.discard("")
        invalid = sorted(actual - allowed)
        require = bool(assertion.get("require_when_hotels", True))
        ok = not invalid and (not require or not hotels or bool(actual))
        return _check(kind, ok, f"countries={sorted(actual)}, invalid={invalid}", severity)

    if kind == "forbidden_hotel_countries":
        forbidden = {str(value).upper() for value in assertion.get("values") or []}
        actual = {str(h.get("country_code") or h.get("country") or "").upper() for h in hotels}
        hits = sorted((actual - {""}) & forbidden)
        return _check(
            kind,
            not hits,
            f"forbidden country hits={hits}" if hits else "no forbidden countries",
            severity,
        )

    if kind == "allowed_geo_terms":
        terms = [_norm(value) for value in assertion.get("terms") or []]
        min_matches = int(assertion.get("min_matches", 1))
        matching = [
            hotel for hotel in hotels if any(term in _hotel_geo_blob(hotel) for term in terms)
        ]
        return _check(
            kind,
            len(matching) >= min_matches,
            f"{len(matching)}/{len(hotels)} match {terms}",
            severity,
        )

    if kind == "forbidden_geo_terms":
        terms = [_norm(value) for value in assertion.get("terms") or []]
        hits = sorted(
            {term for hotel in hotels for term in terms if term and term in _hotel_geo_blob(hotel)}
        )
        return _check(
            kind,
            not hits,
            f"forbidden geo hits={hits}" if hits else "no forbidden geography",
            severity,
        )

    if kind == "required_amenities":
        requested = [str(value) for value in assertion.get("values") or []]
        minimum = int(assertion.get("min_hotels_each", 1))
        counts = {
            amenity: sum(_has_amenity(hotel, amenity) for hotel in hotels) for amenity in requested
        }
        failed = {key: value for key, value in counts.items() if value < minimum}
        return _check(kind, not failed, f"amenity counts={counts}, minimum={minimum}", severity)

    if kind == "min_stars":
        stars = float(assertion.get("value", 4))
        minimum = int(assertion.get("min_hotels", 1))
        count = sum(float(h.get("stars") or 0) >= stars for h in hotels)
        return _check(
            kind, count >= minimum, f"{count}/{len(hotels)} hotels have >= {stars} stars", severity
        )

    if kind == "max_price":
        maximum = float(assertion.get("value"))
        tolerance = float(assertion.get("tolerance", 1.0))
        max_over = int(assertion.get("max_over", 0))
        prices = [price for hotel in hotels if (price := _hotel_price(hotel)) is not None]
        over = [price for price in prices if price > maximum * tolerance]
        require = bool(assertion.get("require_prices", True))
        ok = len(over) <= max_over and (not require or bool(prices))
        return _check(
            kind, ok, f"prices={prices}, over={over}, cap={maximum}x{tolerance}", severity
        )

    if kind == "hotel_currency":
        expected = str(assertion.get("value") or "").upper()
        actual = {_hotel_currency(hotel) for hotel in hotels}
        actual.discard("")
        if not hotels and assertion.get("if_present", False):
            return _check(kind, True, "no hotel cards; currency check not applicable", severity)
        return _check(
            kind,
            bool(actual) and actual == {expected},
            f"currencies={sorted(actual)}, expected={expected}",
            severity,
        )

    if kind == "response_language":
        allowed = {_norm(value) for value in assertion.get("allowed") or []}
        actual = _norm(response.get("response_language"))
        return _check(
            kind,
            actual in allowed,
            f"response_language={actual!r}, allowed={sorted(allowed)}",
            severity,
        )

    if kind == "message_contains_any":
        terms = [_norm(value) for value in assertion.get("terms") or []]
        normalized = _norm(message)
        return _check(
            kind,
            any(term in normalized for term in terms),
            f"expected one of {terms}; message={message[:180]!r}",
            severity,
        )

    if kind == "message_not_contains":
        terms = [_norm(value) for value in assertion.get("terms") or []]
        normalized = _norm(message)
        hits = [term for term in terms if term and term in normalized]
        return _check(
            kind,
            not hits,
            f"forbidden message terms={hits}" if hits else "no forbidden wording",
            severity,
        )

    if kind == "clean_message_ending":
        stripped = message.rstrip()
        dangling = bool(
            re.search(r"(?:\(|\[|\{|\be\.g\.|\bi\.e\.|,|:|;|\bor|\band)\s*$", stripped, re.I)
        )
        balanced = stripped.count("(") == stripped.count(")") and stripped.count(
            "["
        ) == stripped.count("]")
        return _check(
            kind,
            bool(stripped) and not dangling and balanced,
            f"ending={stripped[-60:]!r}",
            severity,
        )

    if kind == "no_repeated_shortlist":
        source_turn = int(assertion.get("from_turn", max(1, turn_index - 1))) - 1
        if source_turn < 0 or source_turn >= len(prior_responses):
            return _check(kind, False, f"source turn {source_turn + 1} unavailable", severity)
        previous = _hotels(prior_responses[source_turn])

        def key(hotel: dict[str, Any]) -> str:
            return str(hotel.get("id") or _norm(hotel.get("name")))

        before = [key(hotel) for hotel in previous]
        after = [key(hotel) for hotel in hotels]
        return _check(
            kind,
            bool(after) and before != after,
            f"previous={before[:5]}, current={after[:5]}",
            severity,
        )

    if kind == "no_repeated_question":
        source_turn = int(assertion.get("from_turn", max(1, turn_index - 1))) - 1
        if source_turn < 0 or source_turn >= len(prior_responses):
            return _check(kind, False, f"source turn {source_turn + 1} unavailable", severity)
        previous_message = _norm(prior_responses[source_turn].get("message"))
        current_message = _norm(message)
        previous_questions = {
            part.strip() for part in previous_message.split("?") if len(part.split()) >= 4
        }
        current_questions = {
            part.strip() for part in current_message.split("?") if len(part.split()) >= 4
        }
        repeats = sorted(previous_questions & current_questions)
        return _check(
            kind,
            not repeats,
            f"repeated questions={repeats}" if repeats else "no repeated question",
            severity,
        )

    if kind == "no_duplicate_tool_calls":
        calls = _tool_calls(response)
        if calls is None:
            required = bool(assertion.get("required", False))
            return _check(
                kind,
                not required,
                "tool-call telemetry unavailable; adapter check skipped",
                severity,
            )
        keys = [_tool_call_key(call) for call in calls]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        return _check(
            kind,
            not duplicates,
            f"duplicate tool calls={duplicates}"
            if duplicates
            else f"{len(keys)} unique tool calls",
            severity,
        )

    if kind == "distance_accuracy":
        origin = _resolve_origin(case, assertion)
        if origin is None:
            return _check(kind, False, "distance origin is missing", severity)
        tolerance_km = float(assertion.get("tolerance_km", 2.0))
        tolerance_ratio = float(assertion.get("tolerance_ratio", 0.15))
        min_checked = int(assertion.get("min_hotels", 1))
        checked = 0
        failures: list[str] = []
        for hotel in hotels:
            lat = _number(hotel.get("latitude"))
            lon = _number(hotel.get("longitude"))
            reported = _number(hotel.get("distance_km"))
            if lat is None or lon is None or reported is None:
                continue
            expected = _haversine_km(origin[0], origin[1], lat, lon)
            allowed_error = max(tolerance_km, expected * tolerance_ratio)
            error = abs(reported - expected)
            checked += 1
            if error > allowed_error:
                failures.append(
                    f"{hotel.get('name')}: reported={reported:.1f} expected={expected:.1f} error={error:.1f}"
                )
        ok = checked >= min_checked and not failures
        return _check(kind, ok, f"checked={checked}; failures={failures[:5]}", severity)

    if kind == "distance_disclosure":
        threshold = float(assertion.get("over_km", 35))
        distant = [h for h in hotels if (_number(h.get("distance_km")) or 0) >= threshold]
        normalized = _norm(message)
        disclosed = " km" in f" {normalized}" or any(
            str(round(_number(h.get("distance_km")) or 0)) in normalized for h in distant
        )
        return _check(
            kind,
            not distant or disclosed,
            f"distant={len(distant)}, disclosed={disclosed}",
            severity,
        )

    if kind == "local_before_far":
        local_km = float(assertion.get("local_km", 15))
        far_km = float(assertion.get("far_km", 35))
        distances = [_number(h.get("distance_km")) for h in hotels]
        distances = [value for value in distances if value is not None]
        if not distances:
            return _check(kind, False, "no distance data", severity)
        ok = not (min(distances) <= local_km and distances[0] >= far_km)
        return _check(kind, ok, f"ordered distances={distances[:5]}", severity)

    if kind == "budget_not_new_without_disclosure":
        source_turn = int(assertion.get("from_turn", max(1, turn_index - 1))) - 1
        previous_budget = None
        if 0 <= source_turn < len(prior_responses):
            previous_budget = _filters(prior_responses[source_turn]).get("budget_max")
        current_budget = filters.get("budget_max")
        changed = current_budget not in (None, previous_budget)
        disclosure_terms = assertion.get("disclosure_terms") or (
            "default",
            "assumed",
            "par défaut",
            "supposé",
            "standard budget",
        )
        disclosed = any(_norm(term) in _norm(message) for term in disclosure_terms)
        return _check(
            kind,
            not changed or disclosed,
            f"budget {previous_budget!r}->{current_budget!r}, disclosed={disclosed}",
            severity,
        )

    if kind == "no_amenity_self_contradiction":
        normalized = _norm(message)
        correction = any(
            token in normalized
            for token in (
                "correction",
                "correction :",
                "correzione",
                "does not list",
                "ne liste pas",
            )
        )
        positive = any(
            token in normalized
            for token in (
                "includes",
                "with pool",
                "avec piscine",
                "con piscina",
                "spa",
                "jacuzzi",
                "hot tub",
            )
        )
        return _check(
            kind,
            not (correction and positive),
            f"positive_claim={positive}, correction={correction}",
            severity,
        )

    if kind == "booking_recovery":
        card = response.get("booking_card")
        has_card = isinstance(card, dict) and bool(card.get("url") or card.get("booking_url"))
        normalized = _norm(message)
        has_link = "http://" in message or "https://" in message
        generic = any(
            token in normalized for token in ("incognito", "ad blocker", "vpn", "different browser")
        )
        return _check(
            kind,
            (has_card or has_link) and not generic,
            f"booking_card={has_card}, inline_link={has_link}, generic_blame={generic}",
            severity,
        )

    return _check(kind or "unknown", False, f"unknown assertion type: {kind!r}", severity)


def evaluate_turn(
    *,
    case: dict[str, Any],
    turn_index: int,
    turn: dict[str, Any],
    response: dict[str, Any],
    prior_responses: list[dict[str, Any]],
) -> list[CheckResult]:
    assertions = list(turn.get("expect") or [])
    if not any(item.get("type") == "http_status" for item in assertions):
        assertions.insert(0, {"type": "http_status", "allowed": [200]})
    return [
        _evaluate_assertion(
            assertion,
            case=case,
            turn_index=turn_index,
            response=response,
            prior_responses=prior_responses,
        )
        for assertion in assertions
    ]


class HttpChatClient:
    def __init__(self, endpoint: str, api_key: str, timeout: int):
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout

    def send(self, *, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        effective_headers = {"Content-Type": "application/json", **headers}
        if self.api_key:
            effective_headers["X-Internal-Api-Key"] = self.api_key
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=effective_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
                parsed = json.loads(body) if body else {}
                parsed["_http_status"] = response.status
                return parsed
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else {}
            except json.JSONDecodeError:
                parsed = {"_raw": body[:2000]}
            parsed["_http_status"] = exc.code
            parsed["_http_error"] = str(exc)
            return parsed


def _case_payload(case: dict[str, Any], turn: dict[str, Any], session_id: str) -> dict[str, Any]:
    request = case.get("request") or {}
    payload: dict[str, Any] = {
        "session_id": session_id,
        "message": turn["message"],
    }
    for key in ("locale", "currency", "native_context", "client_geo_context"):
        if request.get(key) is not None:
            payload[key] = request[key]
    if case.get("clock"):
        # Architecture adapters should use this test-only value as their notion
        # of "now". The current Dayuse endpoint safely ignores unknown fields.
        payload["_eval_clock"] = case["clock"]
    payload.update(request.get("payload") or {})
    payload.update(turn.get("payload") or {})
    return payload


def run_case(
    case: dict[str, Any],
    *,
    client: HttpChatClient,
    pause_ms: int,
) -> dict[str, Any]:
    case_id = str(case["id"])
    session_id = f"canonical-eval-{case_id[:40]}-{uuid.uuid4().hex[:8]}"
    headers = {
        str(key): str(value)
        for key, value in (case.get("request") or {}).get("headers", {}).items()
    }
    responses: list[dict[str, Any]] = []
    turn_results: list[dict[str, Any]] = []
    total_latency = 0.0

    for index, turn in enumerate(case.get("turns") or [], start=1):
        payload = _case_payload(case, turn, session_id)
        started = time.perf_counter()
        try:
            response = client.send(payload=payload, headers=headers)
        except Exception as exc:  # noqa: BLE001
            response = {"_http_status": 599, "_client_error": f"{type(exc).__name__}: {exc}"}
        latency_ms = (time.perf_counter() - started) * 1000
        total_latency += latency_ms
        checks = evaluate_turn(
            case=case,
            turn_index=index,
            turn=turn,
            response=response,
            prior_responses=responses,
        )
        responses.append(response)
        turn_results.append(
            {
                "turn": index,
                "message": turn["message"],
                "latency_ms": round(latency_ms, 2),
                "passed": all(check.passed or check.severity != "critical" for check in checks),
                "checks": [asdict(check) for check in checks],
                "response": response,
            }
        )
        if pause_ms:
            time.sleep(pause_ms / 1000)

    passed = bool(turn_results) and all(result["passed"] for result in turn_results)
    return {
        "id": case_id,
        "suite": case.get("suite"),
        "description": case.get("description"),
        "passed": passed,
        "turn_count": len(turn_results),
        "latency_ms": round(total_latency, 2),
        "turns": turn_results,
    }


def load_cases(paths: list[Path]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                case = json.loads(line)
                case_id = str(case.get("id") or "")
                if not case_id:
                    raise ValueError(f"{path}:{line_number}: missing case id")
                if case_id in seen:
                    raise ValueError(f"duplicate case id: {case_id}")
                if not case.get("turns"):
                    raise ValueError(f"{path}:{line_number}: case has no turns")
                seen.add(case_id)
                cases.append(case)
    return cases


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def build_report(endpoint: str, case_results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(result.get("latency_ms") or 0) for result in case_results]
    suites: dict[str, dict[str, int]] = {}
    for result in case_results:
        suite = str(result.get("suite") or "unknown")
        row = suites.setdefault(suite, {"total": 0, "passed": 0, "failed": 0})
        row["total"] += 1
        row["passed" if result.get("passed") else "failed"] += 1
    passed = sum(bool(result.get("passed")) for result in case_results)
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "endpoint": endpoint,
        "summary": {
            "total": len(case_results),
            "passed": passed,
            "failed": len(case_results) - passed,
            "pass_rate": round(passed / max(1, len(case_results)), 4),
            "latency_ms": {
                "mean": round(statistics.fmean(latencies), 2) if latencies else 0,
                "p50": round(_percentile(latencies, 0.50), 2),
                "p95": round(_percentile(latencies, 0.95), 2),
            },
            "by_suite": suites,
        },
        "results": case_results,
    }


def discover_case_files(root: Path, suites: set[str]) -> list[Path]:
    files = sorted((root / "cases").glob("*.jsonl"))
    if not suites:
        return files
    selected = [path for path in files if path.stem in suites]
    missing = suites - {path.stem for path in selected}
    if missing:
        raise ValueError(f"unknown suites: {sorted(missing)}")
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the portable Dayuse canonical eval pack.")
    parser.add_argument(
        "--endpoint", required=True, help="Full POST endpoint, e.g. http://127.0.0.1:5002/v3/chat"
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Internal API key; prefer CHAT_API_KEY env via shell expansion",
    )
    parser.add_argument("--pack-dir", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--suites", default="", help="Comma-separated suite file stems")
    parser.add_argument("--ids", default="", help="Comma-separated case ids")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--pause-ms", type=int, default=0)
    parser.add_argument("--output", default="eval_pack/results/run.json")
    parser.add_argument("--allow-failures", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.pack_dir)
    suites = {item.strip() for item in args.suites.split(",") if item.strip()}
    cases = load_cases(discover_case_files(root, suites))
    selected_ids = {item.strip() for item in args.ids.split(",") if item.strip()}
    if selected_ids:
        cases = [case for case in cases if case["id"] in selected_ids]
        missing = selected_ids - {case["id"] for case in cases}
        if missing:
            raise ValueError(f"unknown case ids: {sorted(missing)}")
    if args.max_cases > 0:
        cases = cases[: args.max_cases]

    client = HttpChatClient(args.endpoint, args.api_key, args.timeout)
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        result = run_case(case, client=client, pause_ms=max(0, args.pause_ms))
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{index}/{len(cases)}] {status} {result['id']} ({result['latency_ms']:.0f} ms)")

    report = build_report(args.endpoint, results)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    print(f"\n{summary['passed']}/{summary['total']} passed ({summary['pass_rate']:.1%})")
    print(f"Report: {output}")
    if summary["failed"] and not args.allow_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
