"""The site's search page for the search the agent ran — the target of "Voir
tout" (mcp-dayuse#5, decision Mathias 2026-10-06).

"Voir tout" used to open the country page (`/s/france`, `/s/united-states`)
whatever was searched. The site's own search for Lyon is
`/s/france/auvergne-rhone-alpes/rhone/lyon?checkinDate=…&checkinTime=6am&checkoutTime=4pm`.
The path is never built here: `search_offers` returns `searchPage` (mcp-dayuse
!32), the site's page covering the searched point, elected from the nearest
active hotels — `{slug, label, countryCode}`, or null. Verified on the live
site 2026-10-06: the paths are the same on every Dayuse domain,
`/s/san-francisco` alone 404s (the flat slug needs a placeId) while the
canonical path works, and the page reads `checkinDate`, `checkinTime`,
`checkoutTime` and `selectedAddress`.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .hotel_urls import _resolve_market
from .timeslot import parse_hhmm, requested_hours

# The server's path verbatim, or nothing: lowercase ascii slugs under /s/.
_PATH_RE = re.compile(r"/s(?:/[a-z0-9]+(?:-[a-z0-9]+)*)+")


def search_page_from(search_offers: Any) -> dict[str, Any] | None:
    """`{name, path, country_code}` from a `search_offers` response's
    `searchPage`, or None (absent, null, or a slug that is not one)."""
    page = search_offers.get("searchPage") if isinstance(search_offers, dict) else None
    if not isinstance(page, dict) or not isinstance(page.get("slug"), str):
        return None
    path = f"/s/{page['slug'].strip('/')}"
    if not _PATH_RE.fullmatch(path):
        return None
    label = page.get("label")
    return {
        "name": label if isinstance(label, str) and label else None,
        "path": path,
        "country_code": page.get("countryCode"),
    }


def _site_hour(hour: int) -> str:
    """The site's clock format: 6 → "6am", 12 → "12pm", 16 → "4pm", 0 and 24 → "12am"."""
    hour %= 24
    return f"{hour % 12 or 12}{'am' if hour < 12 else 'pm'}"


def build_search_page_url(
    path: str,
    country_code: Any,
    *,
    name: str | None = None,
    checkin_date: str | None = None,
    timeslot_start: str | None = None,
    timeslot_end: str | None = None,
) -> str | None:
    """`https://<market-host><path>?selectedAddress=…&checkinDate=…&checkinTime=…&checkoutTime=…`
    or None when the path or the market is unknown. Hours follow the site rule
    (nearest whole hour, `b2c_common.timeslot`)."""
    if not isinstance(path, str) or not _PATH_RE.fullmatch(path):
        return None
    market = _resolve_market(country_code, None)
    if market is None:
        return None
    params: list[tuple[str, str]] = []
    if name:
        params.append(("selectedAddress", name))
    if checkin_date:
        params.append(("checkinDate", checkin_date))
    arrival, departure = requested_hours(parse_hhmm(timeslot_start), parse_hhmm(timeslot_end))
    if arrival is not None:
        params.append(("checkinTime", _site_hour(arrival)))
    if departure is not None:
        params.append(("checkoutTime", _site_hour(departure)))
    query = f"?{urlencode(params)}" if params else ""
    return f"https://{market[0]}{path}{query}"


def without_hours(url: str) -> str:
    """The same page without `checkinTime`/`checkoutTime`. When no card covers
    the requested slot, the site filtered on it lists nothing (QA 2026-10-07,
    « Miami de 6h à 23h » → "No hotel available")."""
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("checkinTime", "checkoutTime")]
    return urlunsplit(parts._replace(query=urlencode(kept)))
