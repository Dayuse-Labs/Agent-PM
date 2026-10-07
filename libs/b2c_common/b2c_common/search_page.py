"""The site's search page for the search the agent ran — the target of "Voir
tout" (mcp-dayuse#5, decision Mathias 2026-10-06).

"Voir tout" used to open the country page (`/s/france`, `/s/united-states`)
whatever was searched. The site's own search for Lyon is
`/s/france/auvergne-rhone-alpes/rhone/lyon?checkinDate=…&checkinTime=6am&checkoutTime=4pm`.
The path is never built here: MCP_B2C exposes each hotel's `searchPages`, the
`/s/…` items of its indexed breadcrumb (country first, most precise last), and
this module only CHOOSES one of them. Verified on the live site 2026-10-06:
the paths are the same on every Dayuse domain, `/s/san-francisco` alone 404s
(the flat slug needs a placeId) while the breadcrumb path works, and the page
reads `checkinDate`, `checkinTime`, `checkoutTime` and `selectedAddress`.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlencode

from .hotel_urls import _resolve_market
from .timeslot import parse_hhmm, requested_hours

# The server's path verbatim, or nothing: lowercase ascii slugs under /s/.
_PATH_RE = re.compile(r"/s(?:/[a-z0-9]+(?:-[a-z0-9]+)*)+")


def _fold(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _pages(hotel: Any) -> list[dict[str, str]]:
    pages = hotel.get("searchPages") if isinstance(hotel, dict) else None
    return [
        {"name": page["name"], "path": page["path"]}
        for page in pages or []
        if isinstance(page, dict)
        and isinstance(page.get("name"), str)
        and isinstance(page.get("path"), str)
        and _PATH_RE.fullmatch(page["path"])
    ]


def pick_search_page(hotels: list[Any] | None, place_names: list[Any]) -> dict[str, str] | None:
    """The page of the place searched: the most precise page, across the
    hotels found, whose name is one of `place_names` (zone first, then city).
    Else the most precise page EVERY hotel sits in, below the country. None
    when neither exists — the caller keeps the country page."""
    per_hotel = [pages for pages in (_pages(h) for h in hotels or []) if pages]
    if not per_hotel:
        return None
    for name in place_names:
        wanted = _fold(name)
        if not wanted:
            continue
        matches = [p for pages in per_hotel for p in pages if _fold(p["name"]) == wanted]
        if matches:
            return max(matches, key=lambda p: p["path"].count("/"))
    common = [p for p in per_hotel[0] if all(p in pages for pages in per_hotel[1:])]
    deepest = max(common, key=lambda p: p["path"].count("/"), default=None)
    if deepest is None or deepest["path"].count("/") <= 2:
        return None
    return deepest


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
