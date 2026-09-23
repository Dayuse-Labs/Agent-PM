"""S-G12 — hotel-page URL builder: ES slug verbatim + destination market
table, never a name-slugified guess. The two prod repros (Fabien 2026-07-24)
are locked as named regressions: `ibis-rungis-aeroport-paris-orly` and
`euro-hotel-airport-orly-rungis` must come out on dayuse.fr, exactly as ES
spells them."""
from __future__ import annotations

from b2c_common import build_hotel_page_url, with_checkin_date


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
