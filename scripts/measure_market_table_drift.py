#!/usr/bin/env python3
"""UX6 — how far apart have the market referentials in Python and JS drifted?

Why this exists (2026-08-28). `libs/b2c_common/b2c_common/hotel_urls.py:8-10`
states the lesson in its own docstring: agent-usa shipped a 4-day 404 outage
because TWO hand-kept host lists drifted apart, so the two Python callers were
made to share ONE table (`_MARKET`). That lesson was never applied across the
back/front boundary. This script counts the gap instead of asserting it.

Four hand-kept tables describe the same market referential:
  - `_MARKET`               libs/b2c_common/b2c_common/hotel_urls.py:29   (Python)
  - `COUNTRY_META`          web/vendor/static/js/chat/markets.js:9        (JS)
  - `COUNTRY_SLUG_TO_CODE`  web/vendor/static/js/chat/markets.js:150      (JS)
  - `DAYUSE_HOSTS`          web/vendor/static/js/chat/security.js:10      (JS)

Read-only: parses the JS literals, imports the Python table, prints the diff.
No network, no production code touched. NOT a pytest on purpose — it reports a
number for an audit, it does not gate a build (that would be the unification
phase's job, which UX6 is explicitly forbidden from starting).

Usage:
    .venv/bin/python scripts/measure_market_table_drift.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_ROOT, "libs", "b2c_common")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from b2c_common.hotel_urls import _MARKET  # noqa: E402

_MARKETS_JS = os.path.join(_ROOT, "web", "vendor", "static", "js", "chat", "markets.js")
_SECURITY_JS = os.path.join(_ROOT, "web", "vendor", "static", "js", "chat", "security.js")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _country_meta() -> dict[str, dict[str, str]]:
    """`COUNTRY_META` as a dict. The literal is plain enough to read with a
    scanner; every entry found is asserted against the brace count so a parse
    that silently loses entries cannot become a "no drift" conclusion."""
    source = _read(_MARKETS_JS)
    body = re.search(r"const COUNTRY_META = \{(.*?)\n\};", source, re.S)
    assert body, "COUNTRY_META literal not found — markets.js shape changed"
    entries = re.findall(
        r"(\w+):\s*\{\s*code:\s*'([^']*)',\s*label:\s*'([^']*)',\s*"
        r"browseUrl:\s*'([^']*)',\s*hotelCountrySlug:\s*'([^']*)',\s*\}",
        body.group(1),
    )
    expected = body.group(1).count("code:")
    assert len(entries) == expected, f"parsed {len(entries)} of {expected} COUNTRY_META entries"
    return {
        key: {"code": code, "label": label, "browseUrl": url, "hotelCountrySlug": slug}
        for key, code, label, url, slug in entries
    }


def _slug_to_code() -> dict[str, str]:
    source = _read(_MARKETS_JS)
    body = re.search(r"const COUNTRY_SLUG_TO_CODE = \{(.*?)\n\};", source, re.S)
    assert body, "COUNTRY_SLUG_TO_CODE literal not found"
    entries = re.findall(r"'?([a-z\-]+)'?:\s*'([A-Z]{2})'", body.group(1))
    expected = body.group(1).count(":")
    assert len(entries) == expected, f"parsed {len(entries)} of {expected} slug entries"
    return dict(entries)


def _dayuse_hosts() -> list[str]:
    source = _read(_SECURITY_JS)
    body = re.search(r"const DAYUSE_HOSTS = \[(.*?)\n\];", source, re.S)
    assert body, "DAYUSE_HOSTS literal not found"
    return re.findall(r"'([^']+)'", body.group(1))


def _host_allowed(host: str, roots: list[str]) -> bool:
    """`security.js::isHostMatch` — exact match or a subdomain of a root."""
    return any(host == root or host.endswith(f".{root}") for root in roots)


def main() -> None:
    meta = _country_meta()
    slug_to_code = _slug_to_code()
    hosts = _dayuse_hosts()

    print("=== table sizes ===")
    print(f"_MARKET (py)              : {len(_MARKET)} countries")
    print(f"COUNTRY_META (js)         : {len(meta)} keys "
          f"({len({m['code'] for m in meta.values()})} distinct codes)")
    print(f"COUNTRY_SLUG_TO_CODE (js) : {len(slug_to_code)} slugs")
    print(f"DAYUSE_HOSTS (js)         : {len(hosts)} host roots")
    print()

    py_codes = set(_MARKET)
    js_codes = {m["code"] for m in meta.values()}
    print("=== 1. country SET agreement ===")
    print(f"in _MARKET but not COUNTRY_META : {sorted(py_codes - js_codes) or 'none'}")
    print(f"in COUNTRY_META but not _MARKET : {sorted(js_codes - py_codes) or 'none'}")
    print()

    print("=== 2. hotel country-path SLUG agreement (the URL path segment) ===")
    slug_drift = []
    for code, (_host, py_slug) in sorted(_MARKET.items()):
        js_entry = next((m for m in meta.values() if m["code"] == code), None)
        js_slug = js_entry["hotelCountrySlug"] if js_entry else None
        if js_slug != py_slug:
            slug_drift.append((code, py_slug, js_slug))
    for code, py_slug, js_slug in slug_drift:
        print(f"  {code}: py={py_slug!r} js={js_slug!r}")
    print(f"  -> {len(slug_drift)}/{len(_MARKET)} markets disagree")
    print()

    print("=== 3. market HOST agreement (_MARKET host vs COUNTRY_META.browseUrl host) ===")
    host_drift = []
    for code, (py_host, _slug) in sorted(_MARKET.items()):
        js_entry = next((m for m in meta.values() if m["code"] == code), None)
        if not js_entry:
            continue
        js_host = urlparse(js_entry["browseUrl"]).hostname or ""
        if js_host != py_host:
            host_drift.append((code, py_host, js_host))
    for code, py_host, js_host in host_drift:
        print(f"  {code}: booking host={py_host:<24} widget browseUrl host={js_host}")
    print(f"  -> {len(host_drift)}/{len(_MARKET)} markets disagree")
    print()

    print("=== 4. does DAYUSE_HOSTS still admit every _MARKET host? ===")
    rejected = [
        (code, host) for code, (host, _s) in sorted(_MARKET.items())
        if not _host_allowed(host, hosts)
    ]
    for code, host in rejected:
        print(f"  REJECTED {code}: {host} -> sanitizeDayuseUrl would drop the card URL")
    print(f"  -> {len(rejected)}/{len(_MARKET)} rejected today")
    print()

    print("=== 5. reverse slug table vs _MARKET ===")
    py_slugs = {slug for _h, slug in _MARKET.values()}
    print(f"  slugs in _MARKET but unmapped by COUNTRY_SLUG_TO_CODE: "
          f"{sorted(py_slugs - set(slug_to_code)) or 'none'}")
    print(f"  slugs in COUNTRY_SLUG_TO_CODE absent from _MARKET     : "
          f"{sorted(set(slug_to_code) - py_slugs) or 'none'}")
    print()

    print("=== 6. hand-kept lines carrying the same referential ===")
    counts = {
        "_MARKET (hotel_urls.py)": len(_MARKET),
        "COUNTRY_META (markets.js)": len(meta),
        "COUNTRY_SLUG_TO_CODE (markets.js)": len(slug_to_code),
        "DAYUSE_HOSTS (security.js)": len(hosts),
    }
    print(f"  {json.dumps(counts, indent=2)}")
    print(f"  total hand-kept entries: {sum(counts.values())} across "
          f"{len(counts)} tables in 2 languages")


if __name__ == "__main__":
    main()
