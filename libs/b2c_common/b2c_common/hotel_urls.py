"""Deterministic hotel-page URL from the ES slug (S-G12).

The MCP_B2C hotel payload carries the hotel's real Elasticsearch `slug`
(live-probed 2026-07-23) plus `countryName`; nothing in this repo may ever
slugify a display name into a URL — that is exactly the prod defect this
module closes (LLM-invented `a-roport`/`eurohotel` slugs on the wrong
domain). Shared lib on purpose: the search leaf (response_bridge) and the
concierge inline tools (get_hotel_details/compare) must build from ONE
market table — agent-usa 2026-07-06 shipped a 4-day 404 outage precisely
because two hand-kept host lists drifted apart.

Market tables ported from the audited prod reference (agent-usa
`src/application/shared/hotel_urls.py`): the live path is
`/hotels/<country-path>/<hotel-slug>` on the DESTINATION market's real host
(a hotel in France links to dayuse.fr whatever the widget origin). An
unmapped country or a malformed slug yields None — the card honestly has no
link rather than a guessed one.
"""
from __future__ import annotations

import re
import unicodedata

# Destination-market booking host + English country path-slug, keyed by ISO
# alpha-2. Values verified in prod traffic by agent-usa (Amplitude export
# 2026-07-06): IT is dayuse-hotels.it (dayuse.it is dead), BR is
# dayuse.net.br (NOT .com.br); US and every other market not listed here
# stays unmapped → no URL.
_MARKET: dict[str, tuple[str, str]] = {
    "US": ("www.dayuse.com", "usa"),
    "FR": ("www.dayuse.fr", "france"),
    "GB": ("www.dayuse.co.uk", "united-kingdom"),
    "DE": ("www.dayuse.de", "germany"),
    "ES": ("www.dayuse.es", "spain"),
    "IT": ("www.dayuse-hotels.it", "italy"),
    "NL": ("www.dayuse.nl", "netherlands"),
    "BE": ("www.dayuse.be", "belgium"),
    "CH": ("www.dayuse.ch", "switzerland"),
    "AT": ("www.dayuse.at", "austria"),
    "IE": ("www.dayuse.ie", "ireland"),
    "SE": ("www.dayuse.se", "sweden"),
    "PT": ("pt.dayuse.com", "portugal"),
    "SG": ("www.dayuse.sg", "singapore"),
    "HK": ("www.dayuse.com.hk", "hong-kong"),
    "AE": ("www.dayuse.ae", "united-arab-emirates"),
    "BR": ("www.dayuse.net.br", "brazil"),
    "AU": ("au.dayuse.com", "australia"),
    "CA": ("ca.dayuse.com", "canada"),
    "NZ": ("nz.dayuse.com", "new-zealand"),
    "TH": ("th.dayuse.com", "thailand"),
    "MY": ("my.dayuse.com", "malaysia"),
}

# search_offers sends `countryName`, never an ISO code — fold the English name
# to ISO. Keys are `_fold`ed. A name absent here means no URL, never a guess.
#
# NOT a dead fallback — do not shrink it (UX6 audit, re-probed 2026-08-28,
# reports/AUDIT-MAPPINGS-2026-08-28.md): 0 of 201 hotels across 21 markets
# carry a `countryCode` on search_offers, so this table is the ONLY leg
# producing a hotel URL on the card path (100 % load-bearing). It also covers
# 100 % of the countryName values MCP actually emits — no gap found.
# `get_hotel_details` DOES send countryCode (24/24), which is why leg 1 exists;
# that changes nothing for the card path.
# What a missing entry really costs, and why "honestly no link" is optimistic:
# the widget's own `buildHotelFallbackUrl` (markets.js) slugifies the DISPLAY
# NAME when the payload has no url, and renders it on the US host — so a
# country dropped from here does not lose its link, it gains an invented
# wrong-market one that passes the host allowlist.
_ISO_BY_COUNTRY_NAME: dict[str, str] = {
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "france": "FR",
    "united kingdom": "GB",
    "great britain": "GB",
    "germany": "DE",
    "spain": "ES",
    "italy": "IT",
    "netherlands": "NL",
    "belgium": "BE",
    "switzerland": "CH",
    "austria": "AT",
    "ireland": "IE",
    "sweden": "SE",
    "portugal": "PT",
    "singapore": "SG",
    "hong kong": "HK",
    "united arab emirates": "AE",
    "brazil": "BR",
    "australia": "AU",
    "canada": "CA",
    "new zealand": "NZ",
    "thailand": "TH",
    "malaysia": "MY",
}

# The ES slug shape: lowercase ascii words joined by single hyphens. Anything
# else (spaces, accents, uppercase, path separators) is NOT a slug — refuse
# rather than "repair" it, repairing is how invented slugs happen.
_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _fold(name: str) -> str:
    """Accent-stripped, lowercased, alpha-only-spaced country name."""
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]+", " ", value.lower()).strip()


def _resolve_market(country_code: object, country_name: object) -> tuple[str, str] | None:
    if isinstance(country_code, str):
        market = _MARKET.get(country_code.strip().upper())
        if market:
            return market
    if isinstance(country_name, str) and country_name.strip():
        iso = _ISO_BY_COUNTRY_NAME.get(_fold(country_name))
        if iso:
            return _MARKET[iso]
    return None


def build_hotel_page_url(
    slug: object, country_code: object = None, country_name: object = None
) -> str | None:
    """`https://<market-host>/hotels/<country-path>/<es-slug>` or None.

    `slug` must be the server-provided ES slug verbatim; the market resolves
    from `country_code` (ISO alpha-2, wins if ever sent) then `country_name`.
    None on any missing/unmappable piece — the caller simply omits the field.
    """
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        return None
    market = _resolve_market(country_code, country_name)
    if market is None:
        return None
    host, country_path = market
    return f"https://{host}/hotels/{country_path}/{slug}"
