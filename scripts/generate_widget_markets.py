#!/usr/bin/env python3
"""UX6 option B — emit the widget's market tables from the Python referential.

Arbitrated by Fabien 2026-08-28 ("C now and B later", then "do option B").

The problem this closes, in the words of the module it generates from
(`libs/b2c_common/b2c_common/hotel_urls.py:8-10`): "agent-usa 2026-07-06
shipped a 4-day 404 outage precisely because two hand-kept host lists drifted
apart". That lesson was applied between the two Python callers and never across
the back/front boundary, so the widget carried its own copy — measured
2026-08-28 with 8 of 22 market hosts already disagreeing, `www.dayuse.com/s/brazil`
and `/s/malaysia` returning a real 404, and DE's browse slug one redirect off.

After this, `markets.generated.js` is a build artifact: `_MARKET` /
`_BROWSE_PATH` / `_LABEL` in `hotel_urls.py` are the ONE source, and
`tests/test_market_table_drift.py::TestGeneratedFileIsCurrent` fails if the
committed file stops matching what this script produces. So the tables cannot
drift silently again — the point of the whole exercise.

Deliberately NOT generated: `DAYUSE_HOSTS` in `security.js`. It is a security
allowlist of host ROOTS, intentionally BROADER than the market table (the
subdomain rule admits `de.dayuse.ch`, `nl.dayuse.be`, `en.dayuse.com.hk` —
real Dayuse hosts absent from `_MARKET`). Narrowing it to exactly the 22
market hosts would reject legitimate URLs and reintroduce the "no link"
failure this phase just fixed. It stays hand-kept and is guarded instead by
`TestHostAllowlistStillAdmitsEveryMarket`, which fails if it ever stops
admitting a `_MARKET` host.

Usage:
    .venv/bin/python scripts/generate_widget_markets.py          # write
    .venv/bin/python scripts/generate_widget_markets.py --check  # CI/diff mode
"""
from __future__ import annotations

import argparse
import difflib
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "libs", "b2c_common")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from b2c_common.hotel_urls import market_referential  # noqa: E402

TARGET = os.path.join(
    _ROOT, "web", "vendor", "static", "js", "chat", "markets.generated.js"
)

_HEADER = """\
/**
 * GENERATED FILE — DO NOT EDIT BY HAND.
 *
 * Source of truth: `_MARKET` / `_BROWSE_PATH` / `_LABEL` in
 * libs/b2c_common/b2c_common/hotel_urls.py
 * Regenerate:      .venv/bin/python scripts/generate_widget_markets.py
 * Enforced by:     tests/test_market_table_drift.py::TestGeneratedFileIsCurrent
 *
 * Hand-editing this file will fail CI. Change the Python table instead — that
 * is the whole point: two hand-kept market tables drifting apart is what shipped
 * a 4-day 404 outage in agent-usa on 2026-07-06 (UX6, 2026-08-28).
 *
 * `browseUrl` is null where the market has no browse page (MY: dayuse-com's
 * en-MY config defines no defaultSearchPageLink, and /s/malaysia is a measured
 * 404). Render no link rather than a guessed one.
 */
"""


def _js_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def render() -> str:
    rows = market_referential()
    out = [_HEADER, "", "export const COUNTRY_META = {"]
    for row in rows:
        iso = str(row["iso"])
        browse = row["browse_url"]
        out.append(f"    {iso}: {{")
        out.append(f"        code: {_js_string(iso)},")
        out.append(f"        label: {_js_string(str(row['label']))},")
        out.append(
            f"        browseUrl: {_js_string(str(browse)) if browse else 'null'},"
        )
        out.append(
            f"        hotelCountrySlug: {_js_string(str(row['country_path']))},"
        )
        out.append("    },")
    out.append("};")
    out.append("")
    out.append("// Reverse of `hotelCountrySlug`, for reading a market back out of a hotel")
    out.append("// URL path (`inferCountryCodeFromUrl`). Aliases the backend never emits but")
    out.append("// that appear in real Dayuse links are appended after the generated block.")
    out.append("export const COUNTRY_SLUG_TO_CODE = {")
    for row in rows:
        slug = str(row["country_path"])
        key = slug if slug.replace("-", "").isalnum() and "-" not in slug else _js_string(slug)
        out.append(f"    {key}: {_js_string(str(row['iso']))},")
    out.append("    // Hand-kept aliases (not produced by the backend builder):")
    out.append("    'united-states': 'US',")
    out.append("    uk: 'GB',")
    out.append("};")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="exit 1 if the committed file differs from what would be generated",
    )
    args = parser.parse_args()

    rendered = render()
    if args.check:
        try:
            with open(TARGET, encoding="utf-8") as handle:
                current = handle.read()
        except FileNotFoundError:
            print(f"MISSING: {TARGET}\nRun: .venv/bin/python scripts/generate_widget_markets.py")
            return 1
        if current != rendered:
            print("STALE: markets.generated.js does not match the Python referential.\n")
            print("".join(difflib.unified_diff(
                current.splitlines(keepends=True), rendered.splitlines(keepends=True),
                fromfile="committed markets.generated.js", tofile="generated from hotel_urls.py",
            )))
            print("Fix: .venv/bin/python scripts/generate_widget_markets.py")
            return 1
        print("OK: markets.generated.js matches the Python referential.")
        return 0

    with open(TARGET, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    print(f"wrote {TARGET} ({len(market_referential())} markets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
