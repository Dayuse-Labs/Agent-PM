"""S-G12 — hotel-page URL builder: ES slug verbatim + destination market
table, never a name-slugified guess. The two prod repros (Fabien 2026-07-24)
are locked as named regressions: `ibis-rungis-aeroport-paris-orly` and
`euro-hotel-airport-orly-rungis` must come out on dayuse.fr, exactly as ES
spells them."""
from __future__ import annotations

import pytest

from b2c_common import build_hotel_page_url, on_user_site, site_host, with_checkin_date
from b2c_common.hotel_urls import _HOME_MARKET, _LANGUAGE_HOST, _MARKET, _SITE_LANGUAGE


class TestProdRepros:
    def test_ibis_rungis_keeps_the_es_slug_and_fr_domain(self):
        assert build_hotel_page_url(
            "ibis-rungis-aeroport-paris-orly", None, "France"
        ) == "https://www.dayuse.fr/hotels/france/ibis-rungis-aeroport-paris-orly"

    def test_euro_hotel_keeps_the_es_hyphenation(self):
        assert build_hotel_page_url(
            "euro-hotel-airport-orly-rungis", None, "France"
        ) == "https://www.dayuse.fr/hotels/france/euro-hotel-airport-orly-rungis"


class TestMarketResolution:
    def test_country_code_wins_over_name(self):
        assert build_hotel_page_url("some-hotel", "US", "France") == (
            "https://www.dayuse.com/hotels/usa/some-hotel"
        )

    def test_us_uses_the_usa_path_slug(self):
        assert build_hotel_page_url("some-hotel", None, "United States") == (
            "https://www.dayuse.com/hotels/usa/some-hotel"
        )

    def test_country_name_is_folded_before_lookup(self):
        assert build_hotel_page_url("some-hotel", None, "  FRANCE ") is not None
        # Accented/localized spellings of a mapped country still resolve.
        assert build_hotel_page_url("some-hotel", None, "États-Unis") is None  # not English → honest None

    def test_special_market_hosts(self):
        assert build_hotel_page_url("some-hotel", "IT", None) == (
            "https://www.dayuse-hotels.it/hotels/italy/some-hotel"
        )
        assert build_hotel_page_url("some-hotel", "BR", None) == (
            "https://www.dayuse.net.br/hotels/brazil/some-hotel"
        )
        assert build_hotel_page_url("some-hotel", "CA", None) == (
            "https://ca.dayuse.com/hotels/canada/some-hotel"
        )

    def test_unmapped_market_yields_none_never_a_guess(self):
        assert build_hotel_page_url("some-hotel", "JP", "Japan") is None
        assert build_hotel_page_url("some-hotel", None, None) is None


class TestSlugValidation:
    def test_non_slug_shapes_are_refused_not_repaired(self):
        for bad in (
            "Ibis Rungis Aéroport",  # display name, not a slug
            "a--roport",  # doubled hyphen
            "-leading",
            "trailing-",
            "UPPER-case",
            "path/inject",
            "",
            None,
            42,
        ):
            assert build_hotel_page_url(bad, "FR", "France") is None, bad


class TestCheckinDate:
    """QA 2026-09-08 n°4: a user-given date must reach the hotel page, in the
    live site's own parameter (product, 2026-09-23)."""

    def test_the_product_example(self):
        assert with_checkin_date(
            "https://www.dayuse.fr/hotels/france/hotel-paris-montparnasse-tgv", "2026-09-27"
        ) == "https://www.dayuse.fr/hotels/france/hotel-paris-montparnasse-tgv?checkinDate=2026-09-27"

    def test_replaces_a_previous_date_and_keeps_other_params(self):
        assert with_checkin_date(
            "https://www.dayuse.fr/hotels/france/x?a=1&checkinDate=2026-01-01", "2026-09-27"
        ) == "https://www.dayuse.fr/hotels/france/x?a=1&checkinDate=2026-09-27"

    def test_a_bad_date_or_url_leaves_the_link_untouched(self):
        url = "https://www.dayuse.fr/hotels/france/x"
        assert with_checkin_date(url, "demain") == url
        assert with_checkin_date(url, None) == url
        assert with_checkin_date("", "2026-09-27") == ""
        assert with_checkin_date("/hotels/france/x", "2026-09-27") == "/hotels/france/x"


class TestUserSite:
    """2026-10-28 (Fabien): a French user asking for Berlin landed on dayuse.de
    in German. The link now opens on the user's site, in the language the
    conversation is in — the country path stays the hotel's."""

    def test_the_reported_case(self):
        assert build_hotel_page_url(
            "arcotel-john-f-berlin", None, "Germany", host=site_host("fr", "FR")
        ) == "https://www.dayuse.fr/hotels/germany/arcotel-john-f-berlin"

    @pytest.mark.parametrize(("language", "market", "host"), [
        # The visitor's market speaks the language: its host, so its currency.
        ("fr", "FR", "www.dayuse.fr"),
        ("en", "GB", "www.dayuse.co.uk"),
        ("fr", "CH", "www.dayuse.ch"),
        ("fr", "BE", "www.dayuse.be"),
        ("pt", "BR", "www.dayuse.net.br"),
        # The market's other-language site.
        ("nl", "BE", "nl.dayuse.be"),
        ("de", "CH", "de.dayuse.ch"),
        ("en", "HK", "en.dayuse.com.hk"),
        # The market does not speak it (a French message on the en/US default
        # market of a direct visit): the language's home site.
        ("fr", "US", "www.dayuse.fr"),
        ("en", "DE", "www.dayuse.com"),
        ("it", None, "www.dayuse-hotels.it"),
        ("pt", "FR", "pt.dayuse.com"),
        # A full locale reads as its language.
        ("fr-FR", "US", "www.dayuse.fr"),
        ("de-AT", "AT", "www.dayuse.at"),
    ])
    def test_site_host(self, language, market, host):
        assert site_host(language, market) == host

    def test_an_unknown_language_keeps_the_destination_host(self):
        assert site_host(None, "FR") is None
        assert site_host("ja", "FR") is None
        assert site_host("", None) is None
        assert build_hotel_page_url("x", None, "Germany", host=None) == (
            "https://www.dayuse.de/hotels/germany/x"
        )

    def test_the_host_never_rescues_an_unmapped_hotel(self):
        assert build_hotel_page_url("x", "JP", "Japan", host="www.dayuse.fr") is None
        assert build_hotel_page_url("Not A Slug", "DE", None, host="www.dayuse.fr") is None

    def test_every_market_has_a_site_language(self):
        assert set(_SITE_LANGUAGE) == set(_MARKET)

    def test_every_language_host_is_a_real_market_variant(self):
        for (country, language), host in _LANGUAGE_HOST.items():
            assert country in _MARKET
            assert _SITE_LANGUAGE[country] != language, "the www host already speaks it"
            assert host.endswith(_MARKET[country][0].removeprefix("www."))

    def test_every_reply_language_has_a_home_site(self):
        # The 7 languages the concierge replies in (triage.TEMPLATE_LANGUAGES).
        assert set(_HOME_MARKET) == {"en", "fr", "es", "it", "pt", "de", "nl"}
        for language, country in _HOME_MARKET.items():
            assert _SITE_LANGUAGE[country] == language


class TestOnUserSite:
    """MCP's booking tunnel link comes on the hotel's market host; the same
    query opens in the user's language on their site (probed 2026-10-28)."""

    _TUNNEL = "https://www.dayuse.de/tunnel/booking?offerId=abc&checkinDate=2026-10-29&utm_source=x"

    def test_a_market_link_moves_with_its_query(self):
        assert on_user_site(self._TUNNEL, "www.dayuse.fr") == (
            "https://www.dayuse.fr/tunnel/booking?offerId=abc&checkinDate=2026-10-29&utm_source=x"
        )
        assert on_user_site("https://www.dayuse.fr/tunnel/x", "nl.dayuse.be") == "https://nl.dayuse.be/tunnel/x"

    def test_anything_else_is_left_alone(self):
        assert on_user_site(self._TUNNEL, None) == self._TUNNEL
        for url in ("https://evil.example/tunnel/booking", "http://www.dayuse.de/x",
                    "https://static.dayuse.com/x.png", "/tunnel/booking", "", None, 42):
            assert on_user_site(url, "www.dayuse.fr") == url
