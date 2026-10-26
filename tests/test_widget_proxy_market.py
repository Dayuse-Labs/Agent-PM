"""The widget page is rendered in the visitor's market (scripts/run_widget_proxy.py).

dayuse-com opens the agent in a new tab at
`https://ai.dayuse.com/?amp_device_id=…&dayuse_session_id=…&locale=fr&currency=EUR&q=…`
(components/common/AiConciergeSection, AiAgentBanner; MR !15273 adds
`du_entry_source` + `market_country`). agent-usa reads those params — then the
Referer — when it renders `/`, and the widget seeds its market from the 4 metas.
Before this, the proxy rendered the template defaults (en / USD / US) for every
visitor: a dayuse.fr visitor got an English hero, USD and `entry_market_country=US`
on every turn.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "run_widget_proxy.py"
_spec = importlib.util.spec_from_file_location("run_widget_proxy_market", _SCRIPT)
assert _spec is not None and _spec.loader is not None
wp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wp)

_VENDOR = _REPO / "web" / "vendor"
_VENDORED_RESOLVER = _REPO / "web" / "market_context.py"
_AGENT_USA_RESOLVER = (
    _REPO.parent / "agent-usa" / "src" / "application" / "services" / "market_context.py"
)

# What dayuse-com's lib/ai-agent-url.ts builds today (Amplitude ids elided).
_BANNER = "amp_device_id=abc&amp_session_id=123&dayuse_session_id=s1"


def _metas(query: str = "", referer: str | None = None) -> dict[str, str]:
    page = wp.render_index(_VENDOR, query, referer).decode("utf-8")
    return {
        name: re.search(rf'<meta name="du-chat-{name}" content="([^"]*)">', page).group(1)
        for name in ("language", "currency", "country", "domain", "browse-url")
    }


class TestBannerUrl:
    def test_dayuse_fr_banner_renders_french_eur_france(self):
        m = _metas(f"{_BANNER}&locale=fr&currency=EUR&q=piscine", "https://www.dayuse.fr/")
        assert (m["language"], m["currency"], m["country"]) == ("fr", "EUR", "FR")

    def test_the_locale_alone_sets_the_market(self):
        m = _metas(f"{_BANNER}&locale=de&currency=EUR")
        assert (m["language"], m["currency"], m["country"]) == ("de", "EUR", "DE")

    def test_a_single_country_currency_grounds_a_bare_english_locale(self):
        # prod 0423d9d8: locale=en + currency=GBP is a British visitor, not a US one.
        m = _metas(f"{_BANNER}&locale=en&currency=GBP")
        assert (m["language"], m["currency"], m["country"]) == ("en", "GBP", "GB")

    def test_null_values_fall_back_to_the_referer(self):
        # dayuse-com writes the literal 'null' when it has no lang/currency.
        m = _metas(f"{_BANNER}&locale=null&currency=null", "https://www.dayuse.co.uk/")
        assert (m["language"], m["currency"], m["country"]) == ("en", "GBP", "GB")

    def test_no_signal_keeps_the_dayuse_com_default(self):
        m = _metas()
        assert (m["language"], m["currency"], m["country"], m["domain"]) == (
            "en", "USD", "US", "dayuse.com",
        )

    def test_a_foreign_referer_is_ignored(self):
        m = _metas(referer="https://evil.example/?locale=fr&currency=EUR")
        assert (m["language"], m["currency"], m["country"]) == ("en", "USD", "US")

    def test_a_language_the_widget_has_no_copy_for_leaves_the_language_to_the_browser(self):
        m = _metas("locale=zh-hk&currency=HKD")
        assert (m["language"], m["currency"], m["country"]) == ("", "HKD", "HK")

    def test_the_browse_url_is_left_to_the_generated_market_table(self):
        assert _metas("locale=fr&currency=EUR")["browse-url"] == ""


class TestMarketCountry:
    """MR !15273: `market_country` = the site's domain config country."""

    def test_it_pins_a_country_the_locale_cannot_tell(self):
        m = _metas("locale=fr&currency=EUR&market_country=BE&du_entry_source=banner_home")
        assert (m["language"], m["currency"], m["country"]) == ("fr", "EUR", "BE")

    def test_without_currency_the_country_brings_its_own(self):
        m = _metas("locale=fr&market_country=CH")
        assert (m["currency"], m["country"]) == ("CHF", "CH")

    def test_an_explicit_currency_still_wins(self):
        m = _metas("locale=fr&currency=EUR&market_country=CH")
        assert (m["currency"], m["country"]) == ("EUR", "CH")

    @pytest.mark.parametrize("raw", ["XX", "fra", "\"><script>", "null", ""])
    def test_an_unknown_or_malformed_country_is_ignored(self, raw):
        m = _metas(f"locale=fr&currency=EUR&market_country={raw}")
        assert m["country"] == "FR"
        assert '"><script>' not in wp.render_index(_VENDOR, f"market_country={raw}").decode()


class TestRouting:
    def test_get_root_renders_with_the_request_query_and_referer(self):
        handler = wp.WidgetProxyHandler.__new__(wp.WidgetProxyHandler)
        handler.agent_usa_dir = _VENDOR
        handler.path = f"/?{_BANNER}&locale=it&currency=EUR"
        handler.headers = {"Referer": "https://www.dayuse-hotels.it/"}
        bodies: list[bytes] = []
        handler._respond_html = bodies.append
        handler.do_GET()
        assert b'<meta name="du-chat-country" content="IT">' in bodies[0]
        assert b'<meta name="du-chat-language" content="it">' in bodies[0]


class TestVendoredResolver:
    def test_every_bookable_market_is_known_to_the_resolver(self):
        from b2c_common import hotel_urls

        missing = sorted(set(hotel_urls._MARKET) - set(wp.market_context._COUNTRY_MARKET_TABLE))
        assert missing == []

    @pytest.mark.skipif(not _AGENT_USA_RESOLVER.is_file(), reason="agent-usa not checked out next to AgentB2C")
    def test_it_still_matches_agent_usa(self):
        vendored = _VENDORED_RESOLVER.read_text(encoding="utf-8")
        body = vendored[vendored.index('"""Market context'):]
        assert body == _AGENT_USA_RESOLVER.read_text(encoding="utf-8")
