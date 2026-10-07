"""mcp-dayuse#5: "Voir tout" opens the site's search page for the search that
ran — the `searchPage` search_offers returns (mcp-dayuse !32), never built."""
from __future__ import annotations

from b2c_common.search_page import build_search_page_url, search_page_from

_LYON = {"name": "Lyon", "path": "/s/france/auvergne-rhone-alpes/rhone/lyon"}
_SF = {"name": "San Francisco", "path": "/s/united-states/california/san-francisco-county/san-francisco"}


def test_the_mcp_search_page_is_read_as_the_site_path():
    """Shape of search_offers on mcp-dayuse main (2026-10-07)."""
    response = {"results": [], "searchPage": {
        "slug": "france/auvergne-rhone-alpes/rhone/lyon", "label": "Lyon", "countryCode": "FR",
    }}
    assert search_page_from(response) == {
        "name": "Lyon", "path": "/s/france/auvergne-rhone-alpes/rhone/lyon", "country_code": "FR",
    }


def test_no_search_page_when_the_mcp_has_none():
    assert search_page_from({"results": [], "searchPage": None}) is None
    assert search_page_from({"results": []}) is None
    assert search_page_from(None) is None


def test_a_slug_that_is_not_a_site_path_is_refused():
    for slug in ("https://evil.example/lyon", "France/Lyon", "lyon?x=1", "", 42):
        assert search_page_from({"searchPage": {"slug": slug, "label": "Lyon"}}) is None


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
