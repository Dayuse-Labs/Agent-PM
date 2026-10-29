"""The cities the place question offers as chips, per visitor market (2026-10-29).

Prod 2026-10-28/29 (97 real conversations after #173): 45 opened on « Où et
pour quel jour ? » with day chips only; the visitor clicked a day and got a
second, bare « Dans quelle ville ? »; 16 never saw a hotel. The place question
now offers the place itself: « près de moi » and the market's main cities.

Data, not a word list: for each market (ISO 3166-1 alpha-2 of
`entry_market_country`), the cities with the most Dayuse hotels in the
catalogue export of July 2026 (agent-usa `data/structured_hotels_<cc>.json`,
hotels counted by `metro`), at most three, under the name the site's own pages
use. A chip is sent back as the user's message when clicked: the search leaf
geocodes it like any typed city. A market absent here offers no city chip.
"""
from __future__ import annotations

#: Hotel counts of the export, for the record (largest first).
MARKET_CITIES: dict[str, tuple[str, ...]] = {
    "FR": ("Paris", "Lyon", "Bordeaux"),  # 843, 84, 51
    "GB": ("London", "Manchester", "Birmingham"),  # 392, 41, 40
    "US": ("New York", "Los Angeles", "Houston"),  # 291, 207, 116
    "IT": ("Roma", "Milano", "Napoli"),  # 118, 104, 44
    "DE": ("Frankfurt", "München", "Berlin"),  # 100, 61, 56
    "ES": ("Madrid", "Barcelona", "Sevilla"),  # 58, 36, 8
    "BE": ("Bruxelles", "Antwerpen", "Liège"),  # 58, 19, 11
    "NL": ("Amsterdam", "Den Haag", "Rotterdam"),  # 67, 25, 11
    "CH": ("Zürich", "Genève", "Basel"),  # 40, 28, 13
    "AT": ("Wien",),  # 31
    "PT": ("Lisboa", "Porto"),  # 8, 7
    "IE": ("Dublin",),  # 18
    "LU": ("Luxembourg",),  # 16
    "CA": ("Toronto", "Montréal", "Calgary"),  # 55, 46, 22
    "AU": ("Melbourne", "Sydney", "Brisbane"),  # 118, 105, 31
    "NZ": ("Auckland", "Wellington", "Christchurch"),  # 42, 11, 8
    "SG": ("Singapore",),  # 144
    "HK": ("Hong Kong",),  # 138
    "AE": ("Dubai", "Abu Dhabi"),  # 86, 29
    "TH": ("Bangkok",),  # 59
    "BR": ("São Paulo",),  # 14
    "KR": ("Seoul", "Busan"),  # 4, 3
    "CZ": ("Praha",),  # 13
    "SE": ("Stockholm",),  # 4
    "QA": ("Doha",),  # 7
    "TR": ("Istanbul",),  # 12
    "MO": ("Macau",),  # 5
}

#: How many city chips a question offers, next to « près de moi ».
MAX_CITY_CHIPS = 3


def market_cities(country: object) -> list[str]:
    """The market's chip cities, largest first; [] for an unknown market."""
    if not isinstance(country, str):
        return []
    return list(MARKET_CITIES.get(country.strip().upper(), ())[:MAX_CITY_CHIPS])


def default_place(country: object) -> dict[str, str] | None:
    """The city a search falls back on when the visitor answered the place
    question without a place (a day only): the market's largest, with its
    country so the geocoder looks it up there. None for an unknown market."""
    cities = market_cities(country)
    if not cities or not isinstance(country, str):
        return None
    return {"city": cities[0], "country_code": country.strip().upper()}
