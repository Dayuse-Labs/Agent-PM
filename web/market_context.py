# VENDORED from agent-usa src/application/services/market_context.py (13c5c05, 2026-10-12)
# — verbatim, so the widget resolves the visitor's market exactly as prod does today
# (?locale/?currency from dayuse-com's banner URL, then the Referer). Stdlib only: the
# widget image ships no fleet libs. Sync check: tests/test_widget_proxy_market.py.

"""Market context resolved from the client's frontend domain.

Step 1 of the worldwide rollout: instead of a single global ``MARKET`` env var
fixed at boot, each request can carry an ``X-Dayuse-Domain`` header (or fall
back to ``Origin`` / ``Referer``) that identifies which Dayuse TLD the user is
browsing. We map that to a :class:`MarketContext` carrying the response
language, the display currency, and the canonical country code.

The mapping is intentionally explicit (no fuzzy domain matching) so that an
unrecognised or spoofed domain falls back to the safe USA / English / USD
default — preserving today's dayuse.com behaviour.
"""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

_DEFAULT_DOMAIN = "dayuse.com"


def _slug_display_name(name: str) -> str:
    """ASCII-fold + kebab-case a market display name for use in /s/<slug>."""
    decomposed = unicodedata.normalize("NFKD", str(name or ""))
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    out: list[str] = []
    for ch in ascii_only.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-") or "world"


@dataclass(frozen=True)
class MarketContext:
    """Per-request market scope derived from the client's domain.

    ``country_code`` is the ISO-3166 alpha-2 of the **market** (not necessarily
    of the user). It scopes booking/legal context. ``currency`` is what we
    display prices in; if the underlying rate plan uses a different currency,
    callers must convert. ``language`` is the preferred reply language.
    """

    country_code: str
    currency: str
    language: str
    display_name: str
    domain: str
    source: str = "domain_mapping"
    # Raw Dayuse locale the frontend passed in the URL (e.g. "pt-BR", "zh-HK").
    # Persisted for attribution; the language is used only as a *hint* (the
    # reply still follows the language the user actually writes in).
    locale: str = ""
    # Raw ``?currency=`` value exactly as received — recorded even when we can't
    # parse it (symbol, word, …) so we can SEE the real format in the logs and
    # adjust the parser. ``currency`` above is the resolved/applied ISO code.
    raw_currency: str = ""

    @property
    def browse_url(self) -> str:
        """Public Dayuse search URL for this market (e.g. dayuse.fr/s/france).

        Built from ``domain`` + a slug of ``display_name``. ``www.`` is prepended
        so the link lands on the canonical web host the user already trusts.
        """
        slug = _slug_display_name(self.display_name)
        host = self.domain if self.domain.startswith("www.") else f"www.{self.domain}"
        return f"https://{host}/s/{slug}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["browse_url"] = self.browse_url
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> MarketContext | None:
        if not data:
            return None
        try:
            return cls(
                country_code=str(data["country_code"]),
                currency=str(data["currency"]),
                language=str(data["language"]),
                display_name=str(data["display_name"]),
                domain=str(data["domain"]),
                source=str(data.get("source") or "domain_mapping"),
                locale=str(data.get("locale") or ""),
                raw_currency=str(data.get("raw_currency") or ""),
            )
        except (KeyError, TypeError, ValueError):
            return None


# Domain → MarketContext mapping. Keys are normalised lowercase hostnames
# (no scheme, no path, no port). When the frontend sends ``dayuse.fr`` we want
# French replies in EUR; ``dayuse.com.br`` Portuguese in BRL; etc.
_DOMAIN_TABLE: dict[str, MarketContext] = {
    "dayuse.com": MarketContext("US", "USD", "en", "United States", "dayuse.com"),
    "www.dayuse.com": MarketContext("US", "USD", "en", "United States", "dayuse.com"),
    "dayuse.fr": MarketContext("FR", "EUR", "fr", "France", "dayuse.fr"),
    "www.dayuse.fr": MarketContext("FR", "EUR", "fr", "France", "dayuse.fr"),
    "dayuse.es": MarketContext("ES", "EUR", "es", "Spain", "dayuse.es"),
    "www.dayuse.es": MarketContext("ES", "EUR", "es", "Spain", "dayuse.es"),
    "dayuse.it": MarketContext("IT", "EUR", "it", "Italy", "dayuse.it"),
    "www.dayuse.it": MarketContext("IT", "EUR", "it", "Italy", "dayuse.it"),
    "dayuse.co.uk": MarketContext("GB", "GBP", "en", "United Kingdom", "dayuse.co.uk"),
    "www.dayuse.co.uk": MarketContext("GB", "GBP", "en", "United Kingdom", "dayuse.co.uk"),
    "dayuse.de": MarketContext("DE", "EUR", "de", "Germany", "dayuse.de"),
    "www.dayuse.de": MarketContext("DE", "EUR", "de", "Germany", "dayuse.de"),
    "dayuse.be": MarketContext("BE", "EUR", "fr", "Belgium", "dayuse.be"),
    "www.dayuse.be": MarketContext("BE", "EUR", "fr", "Belgium", "dayuse.be"),
    "dayuse.nl": MarketContext("NL", "EUR", "nl", "Netherlands", "dayuse.nl"),
    "www.dayuse.nl": MarketContext("NL", "EUR", "nl", "Netherlands", "dayuse.nl"),
    "dayuse.ch": MarketContext("CH", "CHF", "fr", "Switzerland", "dayuse.ch"),
    "www.dayuse.ch": MarketContext("CH", "CHF", "fr", "Switzerland", "dayuse.ch"),
    "dayuse.com.br": MarketContext("BR", "BRL", "pt", "Brazil", "dayuse.com.br"),
    "www.dayuse.com.br": MarketContext("BR", "BRL", "pt", "Brazil", "dayuse.com.br"),
    "dayuse.com.mx": MarketContext("MX", "MXN", "es", "Mexico", "dayuse.com.mx"),
    "www.dayuse.com.mx": MarketContext("MX", "MXN", "es", "Mexico", "dayuse.com.mx"),
    "dayuse.ae": MarketContext("AE", "AED", "en", "United Arab Emirates", "dayuse.ae"),
    "www.dayuse.ae": MarketContext("AE", "AED", "en", "United Arab Emirates", "dayuse.ae"),
    "dayuse.sg": MarketContext("SG", "SGD", "en", "Singapore", "dayuse.sg"),
    "www.dayuse.sg": MarketContext("SG", "SGD", "en", "Singapore", "dayuse.sg"),
    # Additional markets present in the worldwide data dump (May 2026).
    # These let users on dayuse.at / dayuse.ca / etc. get native currency
    # + local language instead of falling back to US / USD / English.
    "dayuse.at": MarketContext("AT", "EUR", "de", "Austria", "dayuse.at"),
    "www.dayuse.at": MarketContext("AT", "EUR", "de", "Austria", "dayuse.at"),
    "dayuse.com.au": MarketContext("AU", "AUD", "en", "Australia", "dayuse.com.au"),
    "www.dayuse.com.au": MarketContext("AU", "AUD", "en", "Australia", "dayuse.com.au"),
    "dayuse.ca": MarketContext("CA", "CAD", "en", "Canada", "dayuse.ca"),
    "www.dayuse.ca": MarketContext("CA", "CAD", "en", "Canada", "dayuse.ca"),
    "dayuse.cz": MarketContext("CZ", "CZK", "en", "Czech Republic", "dayuse.cz"),
    "www.dayuse.cz": MarketContext("CZ", "CZK", "en", "Czech Republic", "dayuse.cz"),
    "dayuse.com.hk": MarketContext("HK", "HKD", "en", "Hong Kong", "dayuse.com.hk"),
    "www.dayuse.com.hk": MarketContext("HK", "HKD", "en", "Hong Kong", "dayuse.com.hk"),
    "dayuse.ie": MarketContext("IE", "EUR", "en", "Ireland", "dayuse.ie"),
    "www.dayuse.ie": MarketContext("IE", "EUR", "en", "Ireland", "dayuse.ie"),
    "dayuse.kr": MarketContext("KR", "KRW", "en", "South Korea", "dayuse.kr"),
    "www.dayuse.kr": MarketContext("KR", "KRW", "en", "South Korea", "dayuse.kr"),
    "dayuse.lu": MarketContext("LU", "EUR", "fr", "Luxembourg", "dayuse.lu"),
    "www.dayuse.lu": MarketContext("LU", "EUR", "fr", "Luxembourg", "dayuse.lu"),
    "dayuse.mo": MarketContext("MO", "HKD", "en", "Macau", "dayuse.mo"),
    "www.dayuse.mo": MarketContext("MO", "HKD", "en", "Macau", "dayuse.mo"),
    "dayuse.co.nz": MarketContext("NZ", "NZD", "en", "New Zealand", "dayuse.co.nz"),
    "www.dayuse.co.nz": MarketContext("NZ", "NZD", "en", "New Zealand", "dayuse.co.nz"),
    "dayuse.pt": MarketContext("PT", "EUR", "pt", "Portugal", "dayuse.pt"),
    "www.dayuse.pt": MarketContext("PT", "EUR", "pt", "Portugal", "dayuse.pt"),
    "dayuse.qa": MarketContext("QA", "QAR", "en", "Qatar", "dayuse.qa"),
    "www.dayuse.qa": MarketContext("QA", "QAR", "en", "Qatar", "dayuse.qa"),
    "dayuse.com.sa": MarketContext("SA", "SAR", "en", "Saudi Arabia", "dayuse.com.sa"),
    "www.dayuse.com.sa": MarketContext("SA", "SAR", "en", "Saudi Arabia", "dayuse.com.sa"),
    "dayuse.se": MarketContext("SE", "SEK", "en", "Sweden", "dayuse.se"),
    "www.dayuse.se": MarketContext("SE", "SEK", "en", "Sweden", "dayuse.se"),
    "dayuse.co.th": MarketContext("TH", "THB", "en", "Thailand", "dayuse.co.th"),
    "www.dayuse.co.th": MarketContext("TH", "THB", "en", "Thailand", "dayuse.co.th"),
    "dayuse.com.tr": MarketContext("TR", "TRY", "en", "Turkey", "dayuse.com.tr"),
    "www.dayuse.com.tr": MarketContext("TR", "TRY", "en", "Turkey", "dayuse.com.tr"),
    "dayuse.com.bh": MarketContext("BH", "BHD", "en", "Bahrain", "dayuse.com.bh"),
    "www.dayuse.com.bh": MarketContext("BH", "BHD", "en", "Bahrain", "dayuse.com.bh"),
    # ── REAL production domains (Amplitude raw-event export 2026-07-06) ──
    # The keys above were the *assumed* market domains; several markets actually
    # serve on a different host, so a user arriving on the real domain used to
    # miss the lookup and fall back to US/USD (only ?locale= params saved them).
    # These map the REAL hosts to the same (correct) market context.
    # Italy runs on dayuse-hotels.it (NOT dayuse.it); Brazil on dayuse.net.br.
    "dayuse-hotels.it": MarketContext("IT", "EUR", "it", "Italy", "dayuse-hotels.it"),
    "www.dayuse-hotels.it": MarketContext("IT", "EUR", "it", "Italy", "dayuse-hotels.it"),
    "dayuse.net.br": MarketContext("BR", "BRL", "pt", "Brazil", "dayuse.net.br"),
    "www.dayuse.net.br": MarketContext("BR", "BRL", "pt", "Brazil", "dayuse.net.br"),
    # Markets served as <cc>.dayuse.com subdomains.
    "au.dayuse.com": MarketContext("AU", "AUD", "en", "Australia", "au.dayuse.com"),
    "ca.dayuse.com": MarketContext("CA", "CAD", "en", "Canada", "ca.dayuse.com"),
    "nz.dayuse.com": MarketContext("NZ", "NZD", "en", "New Zealand", "nz.dayuse.com"),
    "pt.dayuse.com": MarketContext("PT", "EUR", "pt", "Portugal", "pt.dayuse.com"),
    "th.dayuse.com": MarketContext("TH", "THB", "en", "Thailand", "th.dayuse.com"),
    "my.dayuse.com": MarketContext("MY", "MYR", "en", "Malaysia", "my.dayuse.com"),
    # Language subdomains observed in prod.
    "en.dayuse.com.hk": MarketContext("HK", "HKD", "en", "Hong Kong", "en.dayuse.com.hk"),
    "de.dayuse.ch": MarketContext("CH", "CHF", "de", "Switzerland", "de.dayuse.ch"),
    "nl.dayuse.be": MarketContext("BE", "EUR", "nl", "Belgium", "nl.dayuse.be"),
}

# Fallback used when the request carries no domain header at all or the domain
# cannot be parsed. Kept identical to dayuse.com to preserve current behaviour.
DEFAULT_MARKET_CONTEXT = _DOMAIN_TABLE[_DEFAULT_DOMAIN]


_COUNTRY_MARKET_TABLE: dict[str, MarketContext] = {}
for _host, _ctx in _DOMAIN_TABLE.items():
    if _host.startswith("www."):
        continue
    _COUNTRY_MARKET_TABLE.setdefault(_ctx.country_code, _ctx)

_COUNTRY_MARKET_TABLE.setdefault("TW", MarketContext("TW", "TWD", "zh", "Taiwan", "dayuse.com"))


def _build_single_country_currency() -> dict[str, str]:
    """Currencies used by exactly ONE market → that market's country.

    Derived from the market table (single source of truth), not hand-listed: a
    currency is a reliable COUNTRY signal only when one country uses it. EUR
    (FR/ES/IT/DE/BE/NL/AT/IE/PT/LU) and HKD (HK + Macau) are dropped as
    multi-country; USD is dropped explicitly because it is the weak dayuse.com
    default — mapping it would re-introduce the US-homonym bias. Adding a market
    to ``_DOMAIN_TABLE`` updates this automatically.
    """
    by_currency: dict[str, set[str]] = {}
    for cc, ctx in _COUNTRY_MARKET_TABLE.items():
        by_currency.setdefault(ctx.currency.upper(), set()).add(cc.upper())
    return {
        currency: next(iter(countries))
        for currency, countries in by_currency.items()
        if len(countries) == 1 and currency != "USD"
    }


# Single-country currency → ISO country. A currency is the strongest market
# signal the widget actually sends (the embed passes ?currency= far more often
# than a region-locale), so it grounds the COUNTRY too — not just the display
# currency (prod: locale=en + currency=GBP must resolve GB, not US).
SINGLE_COUNTRY_CURRENCY: dict[str, str] = _build_single_country_currency()


# Dayuse front-end locales (passed in the chat URL as ``?locale=…``) →
# (response-language hint, market country, default currency). The language is
# a hint only; the reply follows the language the user actually writes in, and
# zh/ko/tr aren't supported reply languages yet (they still drive currency +
# attribution). An explicit ``?currency=`` param overrides the default below.
_LOCALE_TABLE: dict[str, tuple[str, str, str]] = {
    # (language, country_code, default_currency). Covers the app's locale list
    # (Mathias 2026-06-18). The app also sends an explicit ?currency= which wins
    # over these defaults; the country here drives display/attribution and the
    # language drives the reply-language hint.
    "fr": ("fr", "FR", "EUR"),
    "en": ("en", "US", "USD"),
    "de": ("de", "DE", "EUR"),
    "it": ("it", "IT", "EUR"),
    "es": ("es", "ES", "EUR"),
    "nl": ("nl", "NL", "EUR"),
    "pt": ("pt", "PT", "EUR"),
    "pt-pt": ("pt", "PT", "EUR"),
    "pt-br": ("pt", "BR", "BRL"),
    "tr": ("tr", "TR", "TRY"),
    "ar": ("ar", "AE", "AED"),
    "ar-ae": ("ar", "AE", "AED"),
    "ar-bh": ("ar", "BH", "BHD"),
    "ar-qa": ("ar", "QA", "QAR"),
    "cz": ("cs", "CZ", "CZK"),
    "cs": ("cs", "CZ", "CZK"),
    "se": ("sv", "SE", "SEK"),
    "sv": ("sv", "SE", "SEK"),
    "ko": ("ko", "KR", "KRW"),
    "ko-kr": ("ko", "KR", "KRW"),
    "zh": ("zh", "HK", "HKD"),
    "zh-hk": ("zh", "HK", "HKD"),
    "zh-sg": ("zh", "SG", "SGD"),
    "zh-tw": ("zh", "TW", "TWD"),
    # English regional variants with their own country/currency (the bare-base
    # fallback in normalize_locale would otherwise collapse them to US/USD).
    "en-gb": ("en", "GB", "GBP"),
    "en-au": ("en", "AU", "AUD"),
    "en-ca": ("en", "CA", "CAD"),
    "en-nz": ("en", "NZ", "NZD"),
    "en-ie": ("en", "IE", "EUR"),
    "en-sg": ("en", "SG", "SGD"),
    "en-hk": ("en", "HK", "HKD"),
    "en-ae": ("en", "AE", "AED"),
    "en-tr": ("en", "TR", "TRY"),
    "en-us": ("en", "US", "USD"),
    # Other regional variants whose currency differs from the base.
    "de-ch": ("de", "CH", "CHF"),
    "de-at": ("de", "AT", "EUR"),
    "fr-ca": ("fr", "CA", "CAD"),
    "fr-ch": ("fr", "CH", "CHF"),
    "fr-be": ("fr", "BE", "EUR"),
    "fr-lu": ("fr", "LU", "EUR"),
    "nl-be": ("nl", "BE", "EUR"),
    "it-ch": ("it", "CH", "CHF"),
}


def normalize_locale(raw: str | None) -> str | None:
    """Canonicalise a locale string to a key in :data:`_LOCALE_TABLE`.

    Accepts ``fr``, ``fr-FR``, ``pt_BR``, ``ZH-HK`` … and maps region-only
    variants to the table key. Returns ``None`` for blanks/unknown.
    """
    if not raw:
        return None
    token = str(raw).strip().lower().replace("_", "-")
    if not token:
        return None
    if token in _LOCALE_TABLE:
        return token
    # Bare language part (e.g. "fr-CA" → "fr", "de-AT" → "de") when supported.
    base = token.split("-", 1)[0]
    if base in _LOCALE_TABLE:
        return base
    return None


def locale_language_hint(raw: str | None) -> str | None:
    """Return the response-language hint for a locale (or None)."""
    key = normalize_locale(raw)
    return _LOCALE_TABLE[key][0] if key else None


def _country_market_context(country_code: str, fallback: MarketContext) -> MarketContext:
    return _COUNTRY_MARKET_TABLE.get(str(country_code or "").upper()) or fallback


def get_country_currency(country_code: str | None) -> str | None:
    """Resolve a country's default display currency from the market table.

    Inverse of :data:`SINGLE_COUNTRY_CURRENCY` but works for EVERY market
    (including the multi-country EUR block), reusing the same single source of
    truth (``_DOMAIN_TABLE`` → ``_COUNTRY_MARKET_TABLE``). Returns the ISO 4217
    code (e.g. ``"EUR"`` for FR) or ``None`` when the country is unmapped.

    Used to ground the display currency on the *resolved hotel country* when the
    only currency signal was the weak ``dayuse.com`` domain default — a French
    user who reached the bare ``.com`` URL must see EUR for Paris hotels, not USD.
    """
    ctx = _COUNTRY_MARKET_TABLE.get(str(country_code or "").upper())
    return ctx.currency if ctx else None


def normalize_domain(raw: str | None) -> str | None:
    """Strip scheme/port/path and lowercase a hostname.

    Accepts already-clean ``"dayuse.fr"`` as well as full URLs like
    ``"https://www.dayuse.fr/search?x=1"``. Returns ``None`` for blanks.
    """
    if not raw:
        return None
    candidate = raw.strip().strip(".")
    if not candidate:
        return None
    if "://" in candidate:
        parsed = urlparse(candidate)
        host = (parsed.hostname or "").strip(".")
    else:
        # Bare hostname (possibly with port).
        host = candidate.split("/", 1)[0].split(":", 1)[0]
    host = host.lower().strip()
    return host or None


def locale_currency_from_referer(referer: str | None) -> tuple[str, str]:
    """Extract ``?locale`` / ``?currency`` from a trusted Dayuse Referer URL.

    The chat widget is served at ``ai.dayuse.com/?...&locale=fr&currency=EUR``
    and calls the *same-origin* ``/v3/chat`` endpoint, so the full page URL
    (with the market params) arrives in the ``Referer`` header — yet the widget
    does not forward those params on the API call itself, so the market always
    fell back to US/USD (prod 3ac05da5: a ``locale=fr&currency=EUR`` user served
    in USD). Read them from the Referer as a fallback.

    Restricted to ``*dayuse.*`` hosts so an arbitrary external embedder can't
    spoof the market. Returns ``("", "")`` when absent or untrusted. The values
    are still validated downstream by :func:`resolve_market_context`.
    """
    if not referer or "://" not in referer:
        return "", ""
    try:
        parsed = urlparse(referer)
    except ValueError:
        return "", ""
    host = (parsed.hostname or "").lower()
    if "dayuse." not in host:
        return "", ""
    qs = parse_qs(parsed.query)
    locale = (qs.get("locale", [""])[0] or "").strip()
    currency = (qs.get("currency", [""])[0] or "").strip()
    return locale, currency


def resolve_market_context(
    *,
    explicit_domain: str | None = None,
    origin: str | None = None,
    referer: str | None = None,
    locale: str | None = None,
    currency: str | None = None,
) -> MarketContext:
    """Resolve a :class:`MarketContext` from the client's request.

    Signal priority:
      1. ``?locale=`` / ``?currency=`` URL params (set explicitly by the
         front-end embed) — the most reliable market signal.
      2. ``X-Dayuse-Domain`` header, then ``Origin``, then ``Referer``.
      3. :data:`DEFAULT_MARKET_CONTEXT` (dayuse.com / US / USD / en).

    The URL params are layered ON TOP of the header/default base so a
    ``?currency=EUR`` still applies even when the domain is unknown. Until this
    was added the params were dropped and every request defaulted to US/USD.
    """
    base = DEFAULT_MARKET_CONTEXT
    base_source = "domain_mapping"
    for source, raw in (
        ("x_dayuse_domain", explicit_domain),
        ("origin", origin),
        ("referer", referer),
    ):
        host = normalize_domain(raw)
        if not host:
            continue
        ctx = _lookup_domain(host)
        if ctx is not None:
            base, base_source = ctx, source
            break

    locale_key = normalize_locale(locale)
    raw_currency = str(currency or "").strip()
    currency_code = raw_currency.upper()
    valid_currency = currency_code if len(currency_code) == 3 and currency_code.isalpha() else ""

    # Nothing from the URL → preserve the exact legacy header/default behaviour
    # (including returning the DEFAULT_MARKET_CONTEXT singleton on no match, so
    # identity checks elsewhere keep holding). A raw currency we couldn't parse
    # still counts as "something" so it gets recorded for observation below.
    if not locale_key and not raw_currency:
        if base is DEFAULT_MARKET_CONTEXT:
            return DEFAULT_MARKET_CONTEXT
        return MarketContext(
            country_code=base.country_code,
            currency=base.currency,
            language=base.language,
            display_name=base.display_name,
            domain=base.domain,
            source=base_source,
        )

    sources: list[str] = []
    language, country, currency_out = base.language, base.country_code, base.currency
    display_name, domain, locale_out = base.display_name, base.domain, ""
    # A real non-US Dayuse domain is an explicit market signal. A bare language
    # locale such as ``en`` may choose the response language, but must not turn
    # dayuse.com.au back into the US market. Region locales remain explicit and
    # may intentionally select another country.
    domain_pinned_non_us = (
        base_source in {"x_dayuse_domain", "origin", "referer"} and base.country_code != "US"
    )
    if locale_key:
        loc_lang, loc_country, loc_currency = _LOCALE_TABLE[locale_key]
        language = loc_lang
        if "-" in locale_key or not domain_pinned_non_us:
            country, currency_out = loc_country, loc_currency
            country_ctx = _country_market_context(loc_country, base)
            display_name, domain = country_ctx.display_name, country_ctx.domain
        locale_out = locale_key
        sources.append("url_locale")
    # A region locale ("en-gb", "fr-ca") pins the country explicitly; a real
    # non-US domain does too. Only the bare-language locale ("en"→US) and the
    # dayuse.com default are "weak" — those are the ones a currency may correct.
    region_locale = bool(locale_key and "-" in locale_key)
    if valid_currency:
        currency_out = valid_currency  # explicit ISO currency wins over the locale default
        sources.append("url_currency")
        # Country grounding from a single-country currency. The widget routinely
        # sends a bare "en" locale + an explicit ?currency=GBP/AUD/… for non-US
        # markets; "en" collapses the country to US, so without this a GBP user
        # got US results, prices, and browse links (prod 0423d9d8/96cd9451/
        # 3b241103). Only override the WEAK default (US) — never a region locale
        # or a real non-US domain — so it can't hijack an explicit market.
        currency_country = SINGLE_COUNTRY_CURRENCY.get(valid_currency)
        if currency_country and country == "US" and not region_locale and not domain_pinned_non_us:
            country = currency_country
            currency_ctx = _country_market_context(currency_country, base)
            display_name, domain = currency_ctx.display_name, currency_ctx.domain
            sources.append("currency_country")
    elif raw_currency:
        # Received a currency we couldn't parse (symbol/word). Don't apply it —
        # keep the locale/base default — but flag it so the logs reveal the
        # real format and we can adjust the parser.
        sources.append("url_currency_unparsed")

    return MarketContext(
        country_code=country,
        currency=currency_out,
        language=language,
        display_name=display_name,
        domain=domain,
        source="+".join(sources) or base_source,
        locale=locale_out,
        raw_currency=raw_currency,
    )


def _lookup_domain(host: str) -> MarketContext | None:
    if host in _DOMAIN_TABLE:
        return _DOMAIN_TABLE[host]
    # Strip a leading "www." and retry once.
    if host.startswith("www.") and host[4:] in _DOMAIN_TABLE:
        return _DOMAIN_TABLE[host[4:]]
    # Dayuse uses language subdomains in a few European entry points. Accept
    # only known language labels and only when the remaining host is an exact
    # registered Dayuse domain; arbitrary customer/attacker subdomains remain
    # rejected.
    parts = host.split(".", 1)
    if len(parts) == 2 and parts[0] in {"en", "fr", "de", "it", "es", "nl", "pt"}:
        return _DOMAIN_TABLE.get(parts[1])
    return None


def get_market_context(preferences: dict[str, Any] | None) -> MarketContext:
    """Read the persisted market context from a conversation's preferences.

    Falls back to :data:`DEFAULT_MARKET_CONTEXT` when no market has been
    resolved yet (e.g. a brand-new conversation, or replayed test fixtures
    that pre-date the domain context).
    """
    if not preferences:
        return DEFAULT_MARKET_CONTEXT
    stored = preferences.get("market")
    parsed = MarketContext.from_dict(stored) if isinstance(stored, dict) else None
    return parsed or DEFAULT_MARKET_CONTEXT
