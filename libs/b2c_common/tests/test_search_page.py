"""mcp-dayuse#5: "Voir tout" opens the site's search page for the search that
ran, chosen among the breadcrumb pages MCP_B2C exposes — never built."""
from __future__ import annotations

from b2c_common.search_page import build_search_page_url, pick_search_page

# Breadcrumb pages as seen on the live site (dayuse.fr / dayuse.com SSR, 2026-10-06).
_FR = {"name": "France", "path": "/s/france"}
_ARA = {"name": "Auvergne-Rhône-Alpes", "path": "/s/france/auvergne-rhone-alpes"}
_RHONE = {"name": "Rhône", "path": "/s/france/auvergne-rhone-alpes/rhone"}
_LYON = {"name": "Lyon", "path": "/s/france/auvergne-rhone-alpes/rhone/lyon"}
_LYON3 = {
    "name": "Lyon 3eme arrondissement",
    "path": "/s/france/auvergne-rhone-alpes/rhone/lyon/lyon-3eme-arrondissement",
}
_BRON = {"name": "Bron", "path": "/s/france/auvergne-rhone-alpes/rhone/bron"}
_LYON3_HOTEL = {"searchPages": [_FR, _ARA, _RHONE, _LYON, _LYON3]}
_BRON_HOTEL = {"searchPages": [_FR, _ARA, _RHONE, _BRON]}

_US = {"name": "United States", "path": "/s/united-states"}
_CA = {"name": "California", "path": "/s/united-states/california"}
_SF_COUNTY = {"name": "San Francisco County", "path": "/s/united-states/california/san-francisco-county"}
_SF = {"name": "San Francisco", "path": "/s/united-states/california/san-francisco-county/san-francisco"}
_SAN_MATEO = {"name": "San Mateo County", "path": "/s/united-states/california/san-mateo-county"}
_SSF = {
    "name": "South San Francisco",
    "path": "/s/united-states/california/san-mateo-county/south-san-francisco",
}


def test_the_searched_city_page_is_picked_even_when_some_hotels_are_in_suburbs():
    assert pick_search_page([_BRON_HOTEL, _LYON3_HOTEL], [None, "Lyon"]) == _LYON


def test_a_flat_us_slug_is_never_used_the_breadcrumb_path_is():
    """`/s/san-francisco` alone 404s on the live site without a placeId."""
    hotels = [
        {"searchPages": [_US, _CA, _SAN_MATEO, _SSF]},
        {"searchPages": [_US, _CA, _SF_COUNTY, _SF]},
    ]
    assert pick_search_page(hotels, [None, "San Francisco"]) == _SF


def test_the_zone_wins_over_the_city_when_the_site_has_a_page_for_it():
    assert pick_search_page([_LYON3_HOTEL], ["Lyon 3eme arrondissement", "Lyon"]) == _LYON3


def test_names_compare_without_case_or_accents():
    assert pick_search_page([_LYON3_HOTEL], [None, "rhone"]) == _RHONE


def test_no_name_match_falls_back_to_the_deepest_page_shared_by_every_hotel():
    """A POI search ("Gare du Nord") has no page of its own."""
    assert pick_search_page([_BRON_HOTEL, _LYON3_HOTEL], ["Gare de Lyon-Part-Dieu", "Villeurbanne"]) == _RHONE


def test_hotels_sharing_only_the_country_give_no_page():
    other = {"searchPages": [_FR, {"name": "Paris", "path": "/s/france/ile-de-france/paris"}]}
    assert pick_search_page([_BRON_HOTEL, other], [None, "Nowhere"]) is None


def test_no_pages_or_a_malformed_path_give_no_page():
    assert pick_search_page([], [None, "Lyon"]) is None
    assert pick_search_page([{"name": "x"}], [None, "Lyon"]) is None
    bad = {"searchPages": [{"name": "Lyon", "path": "https://evil.example/s/lyon"}]}
    assert pick_search_page([bad], [None, "Lyon"]) is None


def test_the_url_carries_the_day_and_the_hours_in_the_site_format():
    url = build_search_page_url(
        _LYON["path"], "FR", name="Lyon", checkin_date="2026-10-07",
        timeslot_start="06:00", timeslot_end="16:00",
    )
    assert url == (
        "https://www.dayuse.fr/s/france/auvergne-rhone-alpes/rhone/lyon"
        "?selectedAddress=Lyon&checkinDate=2026-10-07&checkinTime=6am&checkoutTime=4pm"
    )


def test_minutes_round_like_the_filter_and_noon_midnight_read_right():
    url = build_search_page_url(
        _SF["path"], "US", checkin_date="2026-10-07", timeslot_start="11:40", timeslot_end="23:50",
    )
    assert url is not None
    assert url.startswith("https://www.dayuse.com/s/united-states/")
    assert url.endswith("checkinTime=12pm&checkoutTime=12am")


def test_no_window_means_no_hours():
    url = build_search_page_url(_LYON["path"], "FR", checkin_date="2026-10-07")
    assert url == "https://www.dayuse.fr/s/france/auvergne-rhone-alpes/rhone/lyon?checkinDate=2026-10-07"


def test_an_unknown_market_or_path_gives_no_url():
    assert build_search_page_url(_LYON["path"], "ZZ") is None
    assert build_search_page_url("/hotels/france/x", "FR") is None
