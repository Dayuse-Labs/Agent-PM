#!/usr/bin/env python3
"""Landmark geocoding probe — the deterministic measure of the tier-2 POI path.

Why this exists (2026-08-26). The leaf's landmark lookup went through Mapbox
Search Box `/forward` with `limit=1` and NO `proximity`. Mapbox's documented
default for that parameter is **IP proximity** — so the resolution was a
function of the caller's egress IP: an input we never chose, never logged, and
that differs between a laptop and a Railway container. It was caught the hard
way: the prod trace for "autour des champs élysées" resolved to a shop called
"Champs Elysées" at 32 Rue d'Alger, 83000 Toulon (830 km), while the SAME
arguments replayed locally the next day returned Paris. Mid-session, this
script's own egress IP changed and "montmartre" moved from Paris to a bistro in
Viré, Saône-et-Loire (329 km).

The OBS6 harness could never have isolated that: it runs the whole agent, so an
LLM extraction wobble and a geocoder wobble look identical in its output. This
probe calls ONLY the geo pipeline — no LLM, no services, no Redis — so at a
fixed egress IP it is deterministic, and it scores against the very coordinates
`evals/datasets/b2c-geo-poi.jsonl` asserts on.

⚠️ The egress IP is part of the experiment. It is printed in the header and MUST
be quoted alongside any before/after comparison: two runs from different IPs are
not comparable, and that is precisely the defect this probe measures.

Since 2026-08-26 the zone-only cases (a landmark with no city) call tier 2
DIRECTLY — `forward_candidates` + `geo_resolver.rank_landmark`, same query, same
scope — because `geocode_location` now asks which city on that shape rather than
resolving it under IP bias. Routing them through the tool would score that
product policy (18 clarifies) instead of the ranker this probe measures. Cases
that carry a city, and the generic-zone refusal case, still go through the tool.

Usage (needs MAPBOX_ACCESS_TOKEN; no other credential, no service running):
    set -a; . ./.env; set +a
    .venv/bin/python scripts/probe_geo_landmarks.py
    .venv/bin/python scripts/probe_geo_landmarks.py --json   # machine-readable

Deliberately NOT a pytest: it makes real network calls to a paid third party.
`pytest -q` must stay offline (CLAUDE.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_LEAF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents", "hotel_search_agent")
if _LEAF not in sys.path:
    sys.path.insert(0, _LEAF)

from hotel_search_agent import geo_resolver  # noqa: E402
from hotel_search_agent import geocode_tool as _gt  # noqa: E402
from hotel_search_agent.geocode_tool import geocode_location  # noqa: E402
from hotel_search_agent.inventory import haversine_km  # noqa: E402

#: One case per landmark shape the dataset covers, in the arg shape the MODEL
#: actually produces (observed in prod traces, not invented): a landmark goes in
#: `zone`, the city is present or absent, `country_guess` carries the model's
#: world knowledge. `tolerance_km` mirrors that item's `hotels_within_km.km`.
CASES: tuple[dict[str, object], ...] = (
    # --- bare landmark, no city: the shape that produced the Toulon defect ----
    {"id": "champs-elysees-bare", "expected": (48.8698, 2.3078), "tolerance_km": 3.0,
     "args": {"zone": "les champs élysées", "city": "", "country_guess": "FR",
              "raw_user_message": "je cherche un hôtel autour des champs élysées",
              "locale": "fr-FR", "language_hint": "fr"}},
    {"id": "champs-elysees-typo", "expected": (48.8698, 2.3078), "tolerance_km": 3.0,
     "args": {"zone": "champs elysee", "city": "", "country_code": "FR",
              "raw_user_message": "hotel pres des champ elysee pour demain",
              "locale": "fr-FR", "language_hint": "fr"}},
    {"id": "tour-eiffel-fr", "expected": (48.8584, 2.2945), "tolerance_km": 3.0,
     "args": {"zone": "tour eiffel", "city": "", "country_guess": "FR",
              "raw_user_message": "day use près de la tour eiffel demain",
              "locale": "fr-FR", "language_hint": "fr"}},
    {"id": "eiffel-tower-en", "expected": (48.8584, 2.2945), "tolerance_km": 3.0,
     "args": {"zone": "eiffel tower", "city": "", "country_guess": "FR",
              "raw_user_message": "somewhere around the eiffel tower please",
              "locale": "en-US", "language_hint": "en"}},
    {"id": "gare-de-lyon", "expected": (48.8443, 2.3743), "tolerance_km": 3.0,
     "args": {"zone": "gare de lyon", "city": "", "country_code": "FR",
              "raw_user_message": "hôtel autour de gare de lyon",
              "locale": "fr-FR", "language_hint": "fr"}},
    {"id": "gare-du-nord", "expected": (48.8809, 2.3553), "tolerance_km": 3.0,
     "args": {"zone": "gare du nord", "city": "", "country_guess": "FR",
              "raw_user_message": "je voudrais une chambre en journée vers gare du nord",
              "locale": "fr-FR", "language_hint": "fr"}},
    {"id": "la-defense", "expected": (48.8918, 2.2362), "tolerance_km": 4.0,
     "args": {"zone": "la défense", "city": "", "country_guess": "FR",
              "raw_user_message": "hôtel journée à la défense",
              "locale": "fr-FR", "language_hint": "fr"}},
    {"id": "montmartre", "expected": (48.8867, 2.3431), "tolerance_km": 3.0,
     "args": {"zone": "montmartre", "city": "", "country_guess": "FR",
              "raw_user_message": "un hôtel à montmartre pour demain après-midi",
              "locale": "fr-FR", "language_hint": "fr"}},
    {"id": "louvre-en", "expected": (48.8606, 2.3376), "tolerance_km": 3.0,
     "args": {"zone": "Louvre", "city": "", "country_code": "FR",
              "raw_user_message": "I need a day room near the Louvre tomorrow",
              "locale": "en-US", "language_hint": "en"}},
    # `geo-poi-notre-dame` is the one dataset item that allows NOT resolving
    # (`min_hotels: 0, clarify_allowed: true`): Search Box returns nothing but
    # shops called "DAME" for it, which the echo guard rightly refuses. Scoring
    # an honest refusal as a failure here would make the metric lie — so the
    # bar is "resolve it correctly OR refuse", never "resolve it wrongly".
    {"id": "notre-dame", "expected": (48.8530, 2.3499), "tolerance_km": 3.0,
     "allow_unresolved": True,
     "args": {"zone": "notre dame", "city": "", "country_code": "FR",
              "raw_user_message": "day use autour de notre dame",
              "locale": "fr-FR", "language_hint": "fr"}},
    # --- international landmarks ---------------------------------------------
    {"id": "sagrada-familia-es", "expected": (41.4036, 2.1744), "tolerance_km": 3.0,
     "args": {"zone": "sagrada familia", "city": "", "country_guess": "ES",
              "raw_user_message": "hotel cerca de la sagrada familia mañana",
              "locale": "es-ES", "language_hint": "es"}},
    {"id": "times-square", "expected": (40.7580, -73.9855), "tolerance_km": 3.0,
     "args": {"zone": "times square", "city": "", "country_guess": "US",
              "raw_user_message": "day room around times square tomorrow",
              "locale": "en-US", "language_hint": "en"}},
    {"id": "buckingham-palace", "expected": (51.5014, -0.1419), "tolerance_km": 3.0,
     "args": {"zone": "buckingham palace", "city": "", "country_code": "GB",
              "raw_user_message": "a day use hotel near buckingham palace on friday",
              "locale": "en-GB", "language_hint": "en"}},
    {"id": "jfk-layover", "expected": (40.6413, -73.7781), "tolerance_km": 10.0,
     "args": {"zone": "JFK", "city": "", "country_guess": "US",
              "raw_user_message": "Layover at JFK next Tuesday, I need a room for the day",
              "locale": "en-US", "language_hint": "en"}},
    # --- landmark WITH a city: must not regress ------------------------------
    {"id": "champs-elysees-with-city", "expected": (48.8698, 2.3078), "tolerance_km": 3.0,
     "args": {"zone": "les champs élysées", "city": "Paris", "country_guess": "FR",
              "raw_user_message": "un hôtel vers les champs élysées à paris pour cet après-midi",
              "locale": "fr-FR", "language_hint": "fr"}},
    {"id": "disneyland-paris", "expected": (48.8674, 2.7836), "tolerance_km": 10.0,
     "args": {"zone": "disneyland paris", "city": "", "country_guess": "FR",
              "raw_user_message": "hôtel en journée près de disneyland paris samedi",
              "locale": "fr-FR", "language_hint": "fr"}},
    # --- the model omits the `city` KEY entirely (not ""): pre-2026-08-26 this
    #     was a hard ADK failure, `city` having no default value. 14 such turns
    #     in the traces. Keep it as a case so the regression is measurable.
    {"id": "champs-elysees-city-key-absent", "expected": (48.8698, 2.3078), "tolerance_km": 3.0,
     "args": {"zone": "les champs élysées", "country_guess": "FR",
              "raw_user_message": "je cherche un hôtel autour des champs élysées",
              "language_hint": "fr"}},
    # --- generic zone: must NOT resolve (a generic word is not a landmark) ---
    {"id": "generic-gare-no-city", "expected": None, "tolerance_km": 0.0,
     "args": {"zone": "gare", "city": "", "country_code": "FR",
              "raw_user_message": "un hôtel près de la gare",
              "locale": "fr-FR", "language_hint": "fr"}},
)


def _rank_only(args: dict) -> dict:
    """Tier 2 called directly, for the zone-only cases.

    Since 2026-08-26 `geocode_location` ASKS which city on the zone-only shape
    instead of resolving it: unanchored, the lookup can only aim at the egress
    IP, which is the very defect this probe exists to measure. Going through the
    tool would therefore score the product policy (18 clarifies) and tell us
    nothing about the ranker. So these cases call the exact tier-2 pipeline the
    policy now gates — same query, same scope, same ranker — which keeps the 18
    cases and the same-IP protocol meaningful.
    """
    zone = str(args.get("zone") or "")
    lang = (str(args.get("locale") or "")[:2] or str(args.get("language_hint") or "")[:2]) or None
    candidates = _gt.get_searchbox_client().forward_candidates(
        zone,
        country=_gt._soft_country(
            args.get("country_code"), args.get("country_guess"), args.get("locale")
        ),
        language=lang,
        proximity=None,
    )
    winner = geo_resolver.rank_landmark(
        candidates, requested_zone=zone, inventory=_gt.get_inventory(), proximity=None
    )
    if winner is None:
        return {"ok": False, "error": "landmark_not_resolved"}
    return {
        "ok": True,
        "latitude": winner.latitude,
        "longitude": winner.longitude,
        "resolved_place": winner.place_name,
        "distance_origin_type": "poi",
    }


def _egress_ip() -> str:
    try:
        import httpx

        return httpx.get("https://api.ipify.org", timeout=8.0).text.strip()
    except Exception as exc:  # noqa: BLE001 — informational only, never fatal
        return f"(unknown: {exc})"


def run() -> tuple[list[dict[str, object]], int, int]:
    rows: list[dict[str, object]] = []
    passed = 0
    for case in CASES:
        expected = case["expected"]
        args = dict(case["args"])  # type: ignore[arg-type]
        # A generic zone must still be REFUSED by the tool's own discriminator,
        # so those cases keep the full path; a named landmark with no city goes
        # straight to the ranker (see `_rank_only`).
        rank_only = expected is not None and not args.get("city") and not args.get("metro")
        try:
            result = _rank_only(args) if rank_only else geocode_location(**args)
        except TypeError as exc:
            # A missing required parameter. In-process this is a TypeError; via
            # ADK it is the "mandatory input parameters are not present" tool
            # error that killed 14 landmark turns. Same defect, so record it as
            # a failure instead of crashing the probe — that keeps the case
            # measurable in both directions.
            rows.append({"id": case["id"], "ok": False, "verdict": "FAIL",
                         "detail": f"tool not callable: {exc}"})
            continue
        row: dict[str, object] = {"id": case["id"], "ok": bool(result.get("ok"))}
        if expected is None:
            # A generic zone must be REFUSED. Resolving it is the failure.
            ok = not result.get("ok")
            row.update({
                "verdict": "OK" if ok else "FAIL",
                "detail": str(result.get("error") or result.get("resolved_place")),
            })
        elif result.get("ok"):
            lat, lon = float(result["latitude"]), float(result["longitude"])
            km = haversine_km(expected[0], expected[1], lat, lon)  # type: ignore[index]
            ok = km <= float(case["tolerance_km"])  # type: ignore[arg-type]
            row.update({
                "verdict": "OK" if ok else "FAIL",
                "km": round(km, 1),
                "origin_type": result.get("distance_origin_type"),
                "detail": str(result.get("resolved_place")),
            })
        elif case.get("allow_unresolved"):
            ok = True
            row.update({
                "verdict": "OK*",
                "detail": f"refused honestly (allowed): {result.get('error')}",
            })
        else:
            ok = False
            row.update({
                "verdict": "FAIL",
                "detail": f"{result.get('error')} {result.get('diagnostics')}",
            })
        passed += int(ok)
        rows.append(row)
    return rows, passed, len(CASES)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    if not os.environ.get("MAPBOX_ACCESS_TOKEN"):
        print("MAPBOX_ACCESS_TOKEN is not set — source .env first", file=sys.stderr)
        return 2

    ip = _egress_ip()
    rows, passed, total = run()

    if args.json:
        print(json.dumps({"egress_ip": ip, "passed": passed, "total": total, "cases": rows},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"egress IP: {ip}   <-- quote this: the result depends on it (that IS the bug this measures)")
    print(f"{'case':<34} {'verdict':<8} {'km':>7}  {'origin':<14} resolved")
    print("-" * 108)
    for row in rows:
        km = f"{row['km']:.1f}" if "km" in row else ""
        print(f"{row['id']:<34} {row['verdict']:<8} {km:>7}  "
              f"{str(row.get('origin_type') or ''):<14} {row['detail']}")
    print("-" * 108)
    print(f"{passed}/{total} within tolerance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
