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
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    # Added 2026-08-28: the 3 markets that had live MCP inventory while being
    # unmapped here, so their cards carried NO link at all (measured: KR 2
    # hotels, TR 6, QA 7; 11 other unmapped countries returned total=0).
    # Host + country path verified against a REAL hotel URL per market
    # (supplied by Fabien, each 200):
    #   kr.dayuse.com/hotels/south-korea/hotel-nafore
    #   tr.dayuse.com/hotels/turkey/hilton-istanbul-bomonti-hotel-conference-center
    #   www.dayuse.com/hotels/qatar/ibis-doha
    # QA deliberately uses qa.dayuse.com rather than the www host of that third
    # URL: both serve the page (200), but the SAME hotel reads
    # `"currency":"USD"` on www and `"currency":"QAR"` on qa — the market host
    # is the one that prices in the local currency. Same reason the widget's
    # browse hosts were corrected earlier this day.
    "KR": ("kr.dayuse.com", "south-korea"),
    "TR": ("tr.dayuse.com", "turkey"),
    "QA": ("qa.dayuse.com", "qatar"),
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
    # 2026-08-28. The primary name of each is the one MCP_B2C actually sent on
    # the probe that found these markets ("South Korea", "Turkey", "Qatar");
    # the extra keys are the same-country variants a server rename could plausibly
    # produce, in the spirit of the "usa"/"great britain" aliases above. Keys are
    # `_fold`ed, so "Türkiye" arrives here as "turkiye".
    "south korea": "KR",
    "korea": "KR",
    "republic of korea": "KR",
    "turkey": "TR",
    "turkiye": "TR",
    "qatar": "QA",
}

# Browse ("see all hotels in X") path segment per market: `/s/<segment>`.
#
# NOT derivable from `_MARKET`'s country path above — these are LOCALIZED while
# the hotel path is English (DE: hotels use `germany`, browse uses
# `deutschland`; BR: `brazil` vs `brasil`; ES `espana`, IT `italia`, NL
# `nederland`, BE `belgique`, CH `suisse`). That asymmetry is why the widget
# could not compute one from the other and kept a second hand-written table.
#
# Values are `defaultSearchPageLink` from the dayuse-com monorepo's own
# per-locale configs (`apps/frontend/web/config/config.<locale>.ts`), read
# 2026-08-28 — the authoritative referential, cross-checked against
# `apps/frontend/web/i18n/production.js`'s domain list. Where a country has
# several locales (CH de/fr, BE fr/nl, HK en/zh) the entry is the one whose
# host matches `_MARKET` above.
#
# MY is deliberately ABSENT: dayuse-com's `en-MY` config has no
# `defaultSearchPageLink` at all (my.dayuse.com is a "NEW DOMAIN" market with
# no browse page), and `https://www.dayuse.com/s/malaysia` is a measured 404.
# No entry means no browse link, never a guessed one — same rule as `_MARKET`.
_BROWSE_PATH: dict[str, str] = {
    "US": "united-states",
    "FR": "france",
    "GB": "united-kingdom",
    "DE": "deutschland",
    "ES": "espana",
    "IT": "italia",
    "NL": "nederland",
    "BE": "belgique",
    "CH": "suisse",
    "AT": "austria",
    "IE": "ireland",
    "SE": "sweden",
    "PT": "portugal",
    "SG": "singapore",
    "HK": "hong-kong",
    "AE": "united-arab-emirates",
    "BR": "brasil",
    "AU": "australia",
    "CA": "canada",
    "NZ": "new-zealand",
    "TH": "thailand",
    # 2026-08-28, from the same dayuse-com configs (ko-KR, tr-TR, ar-QA), each
    # verified 200. KR's is the only entry in this table that carries a CITY —
    # dayuse-com's own `defaultSearchPageLink` for ko-KR is "south-korea/seoul",
    # which is also where its whole inventory is (2 hotels, both in Seoul).
    "KR": "south-korea/seoul",
    "TR": "turkiye",
    "QA": "qatar",
}

# English display label per market, for the widget's "see all hotels in X".
# Kept here so ONE module owns the whole market referential (the point of this
# file — see the outage in the docstring). English on purpose: the widget
# translates around it, and dayuse-com's own `country` field is localized per
# locale ("Deutschland", "香港"), which is not what this label is for.
_LABEL: dict[str, str] = {
    "US": "USA",
    "FR": "France",
    "GB": "United Kingdom",
    "DE": "Germany",
    "ES": "Spain",
    "IT": "Italy",
    "NL": "Netherlands",
    "BE": "Belgium",
    "CH": "Switzerland",
    "AT": "Austria",
    "IE": "Ireland",
    "SE": "Sweden",
    "PT": "Portugal",
    "SG": "Singapore",
    "HK": "Hong Kong",
    "AE": "United Arab Emirates",
    "BR": "Brazil",
    "AU": "Australia",
    "CA": "Canada",
    "NZ": "New Zealand",
    "TH": "Thailand",
    "MY": "Malaysia",
    "KR": "South Korea",
    "TR": "Turkey",
    "QA": "Qatar",
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


def market_referential() -> list[dict[str, str | None]]:
    """The whole market referential, one row per ISO alpha-2, sorted.

    Exists so `scripts/generate_widget_markets.py` can emit the widget's tables
    from THIS module instead of a hand-kept copy — the duplication that caused
    agent-usa's 4-day 404 outage (see module docstring) had simply moved to the
    back/front boundary. `browse_url` is None where the market has no browse
    page (MY), and callers must render no link rather than a guess.
    """
    rows: list[dict[str, str | None]] = []
    for iso in sorted(_MARKET):
        host, country_path = _MARKET[iso]
        browse_path = _BROWSE_PATH.get(iso)
        rows.append({
            "iso": iso,
            "host": host,
            "country_path": country_path,
            "browse_url": f"https://{host}/s/{browse_path}" if browse_path else None,
            "label": _LABEL.get(iso, iso),
        })
    return rows


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


# The hotel page's own date parameter, as the live site uses it
# (https://www.dayuse.fr/hotels/france/hotel-paris-montparnasse-tgv?checkinDate=2026-09-27,
# supplied by product 2026-09-23). Without it the page opens on today, so a
# user who asked for another day landed on the wrong day's offers.
CHECKIN_DATE_PARAM = "checkinDate"


def with_checkin_date(url: str, checkin_date: str | None) -> str:
    """`url` with `?checkinDate=<YYYY-MM-DD>` set (replacing any previous
    value, keeping every other parameter). Anything that is not a Dayuse URL
    string plus a valid ISO date comes back UNCHANGED — the link is never
    dropped or mangled because of a bad date."""
    if not isinstance(url, str) or not url or not isinstance(checkin_date, str):
        return url
    try:
        iso = date.fromisoformat(checkin_date).isoformat()
    except ValueError:
        return url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != CHECKIN_DATE_PARAM]
    query.append((CHECKIN_DATE_PARAM, iso))
    return urlunsplit(parts._replace(query=urlencode(query)))
