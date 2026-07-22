"""Build the shareable JSONL suites from the repository's existing batteries."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACK = Path(__file__).resolve().parent


def _prod_ref(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return hashlib.sha256(f"dayuse-eval-v1:{raw}".encode()).hexdigest()[:12]


def _assertion(kind: str, **kwargs: Any) -> dict[str, Any]:
    return {"type": kind, **kwargs}


def _merge_existing_check(check: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if check == "has_results":
        return [_assertion("min_hotels", value=int(params.get("min_results", 1)))]
    if check == "no_results":
        return [_assertion("max_hotels", value=0)]
    if check == "near_city":
        assertions = [
            _assertion(
                "allowed_geo_terms",
                terms=params.get("cities") or [],
                min_matches=int(params.get("min_results", 1)),
            )
        ]
        if params.get("forbidden_cities"):
            assertions.append(_assertion("forbidden_geo_terms", terms=params["forbidden_cities"]))
        return assertions
    if check == "price_under":
        return [
            _assertion(
                "max_price",
                value=float(params["max_price"]),
                tolerance=float(params.get("tolerance", 1.15)),
                max_over=1,
            )
        ]
    if check == "has_amenity":
        return [
            _assertion(
                "required_amenities",
                values=[params["amenity"]],
                min_hotels_each=int(params.get("min_with", 2)),
            )
        ]
    if check == "stars_min":
        return [
            _assertion(
                "min_stars",
                value=int(params["min_stars"]),
                min_hotels=int(params.get("min_with", 2)),
            )
        ]
    if check == "response_text":
        assertions: list[dict[str, Any]] = []
        if params.get("require_no_hotels"):
            assertions.append(_assertion("max_hotels", value=0))
        if params.get("must_contain_any"):
            assertions.append(_assertion("message_contains_any", terms=params["must_contain_any"]))
        if params.get("must_not_contain"):
            assertions.append(_assertion("message_not_contains", terms=params["must_not_contain"]))
        return assertions
    if check == "active_filters":
        assertions = []
        if params.get("expected"):
            assertions.append(_assertion("filter_equals", values=params["expected"]))
        if params.get("forbidden"):
            assertions.append(_assertion("filter_not_equals", values=params["forbidden"]))
        return assertions
    if check == "combined":
        assertions = []
        for nested in params.get("checks") or []:
            assertions.extend(_merge_existing_check(nested["check"], nested.get("params") or {}))
        return assertions
    raise ValueError(f"unsupported existing E2E check: {check}")


def build_core() -> list[dict[str, Any]]:
    namespace = runpy.run_path(str(ROOT / "scripts/test_e2e_search_quality.py"))
    cases = []
    for source in namespace["TEST_CASES"]:
        cases.append(
            {
                "schema_version": "1.0",
                "id": f"core-e2e-{int(source['id']):03d}",
                "suite": "core",
                "clock": "2026-03-10T10:00:00Z",
                "description": source["desc"],
                "tags": ["existing_e2e", str(source.get("tag") or "")],
                "source": {
                    "kind": "existing_battery",
                    "path": "scripts/test_e2e_search_quality.py",
                },
                "turns": [
                    {
                        "message": source["query"],
                        "expect": _merge_existing_check(
                            source["check"], source.get("params") or {}
                        ),
                    }
                ],
            }
        )
    return cases


def build_geo() -> list[dict[str, Any]]:
    namespace = runpy.run_path(str(ROOT / "scripts/run_geo_eval.py"))
    cases = []
    for source in namespace["SCENARIOS"]:
        turns = []
        for index, message in enumerate(source["turns"]):
            expect: list[dict[str, Any]] = []
            if source.get("expected_no_wrong_country"):
                expect.append(
                    _assertion(
                        "forbidden_hotel_countries",
                        values=source["expected_no_wrong_country"],
                    )
                )
            if index == len(source["turns"]) - 1:
                if source.get("expected_country"):
                    expect.append(
                        _assertion(
                            "hotel_countries",
                            allowed=[source["expected_country"]],
                            require_when_hotels=True,
                        )
                    )
                if not source.get("allow_empty") and not source.get("allow_ambiguous"):
                    expect.append(
                        _assertion(
                            "min_hotels",
                            value=int(source.get("expected_min_hotels", 1)),
                        )
                    )
            turns.append({"message": message, "expect": expect})
        source_meta: dict[str, Any] = {
            "kind": "geo_regression",
            "path": "scripts/run_geo_eval.py",
        }
        if ref := _prod_ref(source.get("prod_session")):
            source_meta["anonymized_prod_ref"] = ref
        cases.append(
            {
                "schema_version": "1.0",
                "id": f"geo-{source['id']}",
                "suite": "geo",
                "clock": "2026-06-16T10:00:00Z",
                "description": source["description"],
                "tags": ["geo", "prod_derived" if ref else "synthetic"],
                "source": source_meta,
                "request": {"payload": {"_market_context": source.get("market_context")}}
                if source.get("market_context")
                else {},
                "turns": turns,
            }
        )
    return cases


def _scenario_to_case(source: Any, suite: str, path: str) -> dict[str, Any]:
    turns = []
    for index, message in enumerate(source.turns):
        expect: list[dict[str, Any]] = []
        if source.forbidden_geo_terms:
            expect.append(_assertion("forbidden_geo_terms", terms=list(source.forbidden_geo_terms)))
        if index == len(source.turns) - 1:
            if source.require_no_hotels:
                expect.append(_assertion("max_hotels", value=0))
            else:
                expect.append(_assertion("min_hotels", value=int(source.min_results)))
            if source.expected_country:
                expect.append(
                    _assertion(
                        "hotel_countries",
                        allowed=[source.expected_country],
                        require_when_hotels=True,
                    )
                )
            if source.allowed_geo_terms and source.min_results:
                expect.append(
                    _assertion(
                        "allowed_geo_terms",
                        terms=list(source.allowed_geo_terms),
                        min_matches=1,
                    )
                )
            if source.required_amenities and source.min_results:
                expect.append(
                    _assertion(
                        "required_amenities",
                        values=list(source.required_amenities),
                        min_hotels_each=1,
                    )
                )
            if source.min_stars and source.min_results:
                expect.append(_assertion("min_stars", value=source.min_stars, min_hotels=1))
        turns.append({"message": message, "expect": expect})
    return {
        "schema_version": "1.0",
        "id": f"{suite}-{source.id}",
        "suite": suite,
        "clock": "2026-06-20T10:00:00Z",
        "description": source.id.replace("_", " "),
        "tags": [suite, "locale", "inventory"],
        "source": {"kind": "existing_battery", "path": path},
        "request": {"locale": source.locale, "currency": source.currency},
        "turns": turns,
    }


def build_international() -> list[dict[str, Any]]:
    from scripts.run_international_replay import SCENARIOS

    return [
        _scenario_to_case(source, "international", "scripts/run_international_replay.py")
        for source in SCENARIOS
    ]


def build_worldwide() -> list[dict[str, Any]]:
    from scripts.run_worldwide_locale_eval import build_scenarios

    return [
        _scenario_to_case(source, "worldwide", "scripts/run_worldwide_locale_eval.py")
        for source in build_scenarios()
    ]


def build_domain() -> list[dict[str, Any]]:
    from scripts.run_domain_battery import PROBES

    cases = []
    for probe in PROBES:
        cases.append(
            {
                "schema_version": "1.0",
                "id": f"domain-{probe.domain.replace('.', '-')}",
                "suite": "domain",
                "clock": "2026-06-20T10:00:00Z",
                "description": f"{probe.domain}: response language and card currency",
                "tags": ["domain", "currency", "language"],
                "source": {"kind": "existing_battery", "path": "scripts/run_domain_battery.py"},
                "request": {
                    "headers": {
                        "X-Dayuse-Domain": probe.domain,
                        "Origin": f"https://{probe.domain}",
                    }
                },
                "turns": [
                    {
                        "message": probe.message,
                        "expect": [
                            _assertion("response_language", allowed=[probe.expected_language]),
                            _assertion(
                                "hotel_currency",
                                value=probe.expected_currency,
                                if_present=True,
                            ),
                        ],
                    }
                ],
            }
        )
    return cases


def _dynamic_expectations(family: str, turn_count: int) -> list[list[dict[str, Any]]]:
    expects: list[list[dict[str, Any]]] = [[] for _ in range(turn_count)]
    if family == "named_hotel_present":
        expects[2] += [
            _assertion("min_hotels", value=3),
            _assertion("filter_present", keys=["named_hotel"]),
        ]
        expects[3] += [_assertion("filter_present", keys=["named_hotel"])]
        expects[4] += [
            _assertion(
                "message_not_contains", terms=["which city", "what city", "i'm here to help"]
            ),
            _assertion("clean_message_ending"),
        ]
    elif family == "named_hotel_absent":
        expects[3] += [
            _assertion("min_hotels", value=3),
            _assertion(
                "message_contains_any",
                terms=["not seeing", "not showing", "not available", "can't quote", "not found"],
            ),
        ]
        expects[4] += [_assertion("min_hotels", value=1), _assertion("clean_message_ending")]
    elif family == "carry_same_time":
        expects[-1] += [
            _assertion(
                "filter_equals",
                values={
                    "zone": "Fort Lauderdale",
                    "date_reference": "tomorrow",
                    "timeslot_start": "11:00",
                },
            )
        ]
    elif family == "budget_change":
        expects[0] += [_assertion("filter_equals", values={"budget_max": 250.0})]
        expects[1] += [
            _assertion("filter_equals", values={"budget_max": 180.0}),
            _assertion("requires_clarification", value=False),
        ]
        expects[2] += [
            _assertion("filter_equals", values={"budget_max": 250.0}),
            _assertion("requires_clarification", value=False),
        ]
    elif family == "zone_change":
        expects[1] += [
            _assertion("filter_equals", values={"zone": "Fort Lauderdale"}),
            _assertion("requires_clarification", value=False),
        ]
        expects[2] += [
            _assertion("filter_equals", values={"zone": "Boca Raton"}),
            _assertion("requires_clarification", value=False),
        ]
    elif family == "date_availability_follow_up":
        expects[0] += [_assertion("min_hotels", value=1)]
        expects[1] += [
            _assertion("max_hotels", value=0),
            _assertion(
                "message_contains_any",
                terms=["availability", "booking page", "different date", "try a different"],
            ),
        ]
    elif family == "non_search_age":
        expects[0] += [
            _assertion("max_hotels", value=0),
            _assertion("message_contains_any", terms=["18", "19", "21", "age"]),
            _assertion("message_not_contains", terms=["which city", "what city"]),
        ]
    elif family == "non_search_support":
        expects[0] += [
            _assertion("max_hotels", value=0),
            _assertion(
                "message_contains_any",
                terms=["reservation", "booking", "confirmation", "cancel", "my bookings"],
            ),
            _assertion("message_not_contains", terms=["which city", "what city"]),
        ]
    elif family == "rooftop_pool":
        expects[-1] += [
            _assertion("min_hotels", value=3),
            _assertion(
                "allowed_geo_terms",
                terms=["Los Angeles", "Hollywood", "Beverly Hills"],
                min_matches=1,
            ),
        ]
    return expects


def build_multiturn() -> list[dict[str, Any]]:
    from src.application.testing.conversation_regression import generate_scenarios

    cases = []
    for source in generate_scenarios(seed=42, per_family=3):
        expectations = _dynamic_expectations(source.family, len(source.turns))
        cases.append(
            {
                "schema_version": "1.0",
                "id": f"multiturn-{source.id}",
                "suite": "multiturn",
                "clock": "2026-07-10T10:00:00Z",
                "description": source.label,
                "tags": ["multi_turn", source.family],
                "source": {
                    "kind": "generated_regression",
                    "path": "src/application/testing/conversation_regression.py",
                    "seed": 42,
                },
                "turns": [
                    {"message": message, "expect": expectations[index]}
                    for index, message in enumerate(source.turns)
                ],
            }
        )
    return cases


def build_prod_wounds() -> list[dict[str, Any]]:
    """Anonymized, outcome-based cases from the 2026-07 production reviews."""
    common = {
        "schema_version": "1.0",
        "suite": "prod_wounds",
        "clock": "2026-07-10T10:00:00Z",
        "tags": ["prod_derived", "anonymized", "2026_07_review"],
        "source": {
            "kind": "anonymized_prod_review",
            "audit_window": "2026-07-09/2026-07-10",
            "path": "reports/conv_review_2026_07_10.md",
        },
    }
    cases = [
        {
            **common,
            "id": "prod-wound-gps-paris-refinement",
            "description": "Near-me Paris refinement keeps the device GPS distance origin",
            "request": {
                "locale": "fr-FR",
                "currency": "EUR",
                "headers": {"X-Dayuse-Domain": "dayuse.fr"},
                "native_context": {"geolocation": {"lat": 48.9385, "lon": 2.4906}},
            },
            "turns": [
                {
                    "message": "Une chambre en journée près de moi avec piscine extérieure",
                    "expect": [
                        _assertion("min_hotels", value=1),
                        _assertion("distance_accuracy", origin="native_geolocation", min_hotels=1),
                    ],
                },
                {
                    "message": "Même un peu plus loin, mais toujours avec piscine",
                    "expect": [
                        _assertion("min_hotels", value=1),
                        _assertion("distance_accuracy", origin="native_geolocation", min_hotels=1),
                        _assertion("distance_disclosure", over_km=35),
                    ],
                },
            ],
        },
        {
            **common,
            "id": "prod-wound-gps-detroit-luxury",
            "description": "Luxury refinement must not replace Farmington Hills GPS with Detroit centroid",
            "request": {
                "locale": "en-US",
                "currency": "USD",
                "native_context": {"geolocation": {"lat": 42.4828, "lon": -83.3763}},
            },
            "turns": [
                {
                    "message": "Day room near me this afternoon",
                    "expect": [
                        _assertion("distance_accuracy", origin="native_geolocation", min_hotels=1)
                    ],
                },
                {
                    "message": "Luxury",
                    "expect": [
                        _assertion("distance_accuracy", origin="native_geolocation", min_hotels=1),
                        _assertion("preserve_filters", from_turn=1, keys=["city", "country_code"]),
                    ],
                },
            ],
        },
        {
            **common,
            "id": "prod-wound-orange-county-anchor",
            "description": "Orange County distances are measured from Orange, not downtown Los Angeles",
            "request": {"locale": "en-US", "currency": "USD"},
            "turns": [
                {
                    "message": "Day hotel in Orange County California this afternoon under $250",
                    "expect": [
                        _assertion("min_hotels", value=1),
                        _assertion("distance_accuracy", origin=[33.7879, -117.8531], min_hotels=1),
                        _assertion("local_before_far", local_km=15, far_km=35),
                    ],
                }
            ],
        },
        {
            **common,
            "id": "prod-wound-rue-lafayette-anchor",
            "description": "Rue Lafayette search uses the requested address area as distance origin",
            "request": {
                "locale": "fr-FR",
                "currency": "EUR",
                "headers": {"X-Dayuse-Domain": "dayuse.fr"},
            },
            "turns": [
                {
                    "message": "Hôtel près de la rue Lafayette à Paris cet après-midi, 250 euros",
                    "expect": [
                        _assertion("min_hotels", value=1),
                        _assertion("distance_accuracy", origin=[48.8752, 2.3472], min_hotels=1),
                        _assertion("hotel_countries", allowed=["FR"]),
                    ],
                }
            ],
        },
        {
            **common,
            "id": "prod-wound-cap-ferrat-fr",
            "description": "dayuse.fr Cap Ferrat request never serves Italian homonym cards",
            "request": {
                "locale": "fr-FR",
                "currency": "EUR",
                "headers": {"X-Dayuse-Domain": "dayuse.fr", "Origin": "https://dayuse.fr"},
            },
            "turns": [
                {
                    "message": "Un hôtel vers le cap Ferrat cet après-midi, 250 euros",
                    "expect": [
                        _assertion("forbidden_hotel_countries", values=["IT"]),
                        _assertion("hotel_countries", allowed=["FR"], require_when_hotels=True),
                        _assertion("forbidden_geo_terms", terms=["Riccione", "Rimini", "Pesaro"]),
                    ],
                }
            ],
        },
        {
            **common,
            "id": "prod-wound-named-hotel-survives-city",
            "description": "Specific hotel survives a city clarification and bypasses generic budget gating",
            "request": {
                "locale": "en-HK",
                "currency": "HKD",
                "headers": {"X-Dayuse-Domain": "dayuse.com.hk"},
            },
            "turns": [
                {
                    "message": "Rambler Oasis Hotel",
                    "expect": [_assertion("filter_present", keys=["named_hotel"])],
                },
                {
                    "message": "Hong Kong",
                    "expect": [
                        _assertion("filter_present", keys=["named_hotel"]),
                        _assertion(
                            "message_not_contains", terms=["what is your budget", "max budget"]
                        ),
                    ],
                },
            ],
        },
        {
            **common,
            "id": "prod-wound-date-not-budget",
            "description": "A date answer cannot silently become a fabricated budget",
            "request": {
                "locale": "en-GB",
                "currency": "GBP",
                "headers": {"X-Dayuse-Domain": "dayuse.co.uk"},
            },
            "turns": [
                {"message": "Family hotel with pool in London", "expect": []},
                {
                    "message": "11th July",
                    "expect": [
                        _assertion("budget_not_new_without_disclosure", from_turn=1),
                        _assertion("hotel_currency", value="GBP", if_present=True),
                    ],
                },
            ],
        },
        {
            **common,
            "id": "prod-wound-amenity-no-self-contradiction",
            "description": "Amenity guard rewrites unsupported claims instead of appending a contradiction",
            "request": {
                "locale": "it-IT",
                "currency": "EUR",
                "headers": {"X-Dayuse-Domain": "dayuse.it"},
            },
            "turns": [
                {
                    "message": "Hotel con piscina e spa a Roma questo pomeriggio sotto 250 euro",
                    "expect": [_assertion("no_amenity_self_contradiction")],
                },
                {
                    "message": "Quale ha davvero entrambe?",
                    "expect": [
                        _assertion("no_amenity_self_contradiction"),
                        _assertion("clean_message_ending"),
                    ],
                },
            ],
        },
        {
            **common,
            "id": "prod-wound-auckland-nzd-sticky",
            "description": "Auckland refinements keep NZD on both prose and hotel cards",
            "request": {
                "locale": "en-NZ",
                "currency": "NZD",
                "headers": {"X-Dayuse-Domain": "dayuse.co.nz"},
            },
            "turns": [
                {
                    "message": "Day room in Auckland this afternoon under 300 NZD",
                    "expect": [_assertion("hotel_currency", value="NZD", if_present=True)],
                },
                {
                    "message": "Cheaper options",
                    "expect": [
                        _assertion("hotel_currency", value="NZD", if_present=True),
                        _assertion("preserve_filters", from_turn=1, keys=["city", "country_code"]),
                    ],
                },
            ],
        },
        {
            **common,
            "id": "prod-wound-cantonese-language",
            "description": "Cantonese payment FAQ remains in Chinese and does not invent a language limitation",
            "request": {
                "locale": "zh-HK",
                "currency": "HKD",
                "headers": {"X-Dayuse-Domain": "dayuse.com.hk"},
            },
            "turns": [
                {
                    "message": "可以用八達通付款嗎？",
                    "expect": [
                        _assertion("response_language", allowed=["zh", "zh-hk", "yue"]),
                        _assertion(
                            "message_not_contains",
                            terms=["English/Spanish/French only", "only support English"],
                        ),
                        _assertion("max_hotels", value=0),
                    ],
                }
            ],
        },
        {
            **common,
            "id": "prod-wound-more-options-not-repeat",
            "description": "More options returns a genuinely new shortlist",
            "request": {
                "locale": "en-GB",
                "currency": "GBP",
                "headers": {"X-Dayuse-Domain": "dayuse.co.uk"},
            },
            "turns": [
                {
                    "message": "Spa day hotel near London under 300 GBP",
                    "expect": [_assertion("min_hotels", value=1)],
                },
                {
                    "message": "Show me different options",
                    "expect": [
                        _assertion("min_hotels", value=1),
                        _assertion("no_repeated_shortlist", from_turn=1),
                        _assertion("clean_message_ending"),
                    ],
                },
            ],
        },
        {
            **common,
            "id": "prod-wound-booking-link-recovery",
            "description": "A reported booking 404 triggers a fresh booking link, not browser blame",
            "request": {
                "locale": "en-GB",
                "currency": "GBP",
                "headers": {"X-Dayuse-Domain": "dayuse.co.uk"},
            },
            "turns": [
                {
                    "message": "Jacuzzi hotel in Birmingham UK this afternoon under 250 GBP",
                    "expect": [_assertion("min_hotels", value=1)],
                },
                {
                    "message": "When I click the first one it says page not found",
                    "expect": [_assertion("booking_recovery")],
                },
            ],
        },
        {
            **common,
            "id": "prod-wound-tradeoff-no-loop-or-truncation",
            "description": (
                "A constrained search followed by a trade-off neither loops on the same question "
                "nor truncates the answer or repeats an identical tool call"
            ),
            "request": {
                "locale": "en-GB",
                "currency": "GBP",
                "headers": {"X-Dayuse-Domain": "dayuse.co.uk"},
            },
            "turns": [
                {
                    "message": "Spa day hotel near Ilford under 60 GBP",
                    "expect": [
                        _assertion("clean_message_ending"),
                        _assertion("no_duplicate_tool_calls", required=False, severity="warning"),
                    ],
                },
                {
                    "message": "I can go a little further and raise the budget",
                    "expect": [
                        _assertion("clean_message_ending"),
                        _assertion("no_repeated_question", from_turn=1),
                        _assertion("no_duplicate_tool_calls", required=False, severity="warning"),
                    ],
                },
            ],
        },
    ]
    return cases


def _write_jsonl(path: Path, cases: Iterable[dict[str, Any]]) -> int:
    rows = list(cases)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def build_all(output_dir: Path) -> dict[str, int]:
    suites = {
        "core": build_core(),
        "geo": build_geo(),
        "international": build_international(),
        "worldwide": build_worldwide(),
        "domain": build_domain(),
        "multiturn": build_multiturn(),
        "prod_wounds": build_prod_wounds(),
    }
    counts = {}
    ids: set[str] = set()
    for suite, cases in suites.items():
        for case in cases:
            case_id = str(case["id"])
            if case_id in ids:
                raise ValueError(f"duplicate generated case id: {case_id}")
            ids.add(case_id)
        counts[suite] = _write_jsonl(output_dir / f"{suite}.jsonl", cases)
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(PACK / "cases"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = build_all(Path(args.output_dir))
    print(json.dumps({"suites": counts, "total": sum(counts.values())}, indent=2))


if __name__ == "__main__":
    main()
