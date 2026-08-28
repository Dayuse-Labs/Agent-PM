/**
 * GENERATED FILE — DO NOT EDIT BY HAND.
 *
 * Source of truth: `_MARKET` / `_BROWSE_PATH` / `_LABEL` in
 * libs/b2c_common/b2c_common/hotel_urls.py
 * Regenerate:      .venv/bin/python scripts/generate_widget_markets.py
 * Enforced by:     tests/test_market_table_drift.py::TestGeneratedFileIsCurrent
 *
 * Hand-editing this file will fail CI. Change the Python table instead — that
 * is the whole point: two hand-kept market tables drifting apart is what shipped
 * a 4-day 404 outage in agent-usa on 2026-07-06 (UX6, 2026-08-28).
 *
 * `browseUrl` is null where the market has no browse page (MY: dayuse-com's
 * en-MY config defines no defaultSearchPageLink, and /s/malaysia is a measured
 * 404). Render no link rather than a guessed one.
 */


export const COUNTRY_META = {
    AE: {
        code: 'AE',
        label: 'United Arab Emirates',
        browseUrl: 'https://www.dayuse.ae/s/united-arab-emirates',
        hotelCountrySlug: 'united-arab-emirates',
    },
    AT: {
        code: 'AT',
        label: 'Austria',
        browseUrl: 'https://www.dayuse.at/s/austria',
        hotelCountrySlug: 'austria',
    },
    AU: {
        code: 'AU',
        label: 'Australia',
        browseUrl: 'https://au.dayuse.com/s/australia',
        hotelCountrySlug: 'australia',
    },
    BE: {
        code: 'BE',
        label: 'Belgium',
        browseUrl: 'https://www.dayuse.be/s/belgique',
        hotelCountrySlug: 'belgium',
    },
    BR: {
        code: 'BR',
        label: 'Brazil',
        browseUrl: 'https://www.dayuse.net.br/s/brasil',
        hotelCountrySlug: 'brazil',
    },
    CA: {
        code: 'CA',
        label: 'Canada',
        browseUrl: 'https://ca.dayuse.com/s/canada',
        hotelCountrySlug: 'canada',
    },
    CH: {
        code: 'CH',
        label: 'Switzerland',
        browseUrl: 'https://www.dayuse.ch/s/suisse',
        hotelCountrySlug: 'switzerland',
    },
    DE: {
        code: 'DE',
        label: 'Germany',
        browseUrl: 'https://www.dayuse.de/s/deutschland',
        hotelCountrySlug: 'germany',
    },
    ES: {
        code: 'ES',
        label: 'Spain',
        browseUrl: 'https://www.dayuse.es/s/espana',
        hotelCountrySlug: 'spain',
    },
    FR: {
        code: 'FR',
        label: 'France',
        browseUrl: 'https://www.dayuse.fr/s/france',
        hotelCountrySlug: 'france',
    },
    GB: {
        code: 'GB',
        label: 'United Kingdom',
        browseUrl: 'https://www.dayuse.co.uk/s/united-kingdom',
        hotelCountrySlug: 'united-kingdom',
    },
    HK: {
        code: 'HK',
        label: 'Hong Kong',
        browseUrl: 'https://www.dayuse.com.hk/s/hong-kong',
        hotelCountrySlug: 'hong-kong',
    },
    IE: {
        code: 'IE',
        label: 'Ireland',
        browseUrl: 'https://www.dayuse.ie/s/ireland',
        hotelCountrySlug: 'ireland',
    },
    IT: {
        code: 'IT',
        label: 'Italy',
        browseUrl: 'https://www.dayuse-hotels.it/s/italia',
        hotelCountrySlug: 'italy',
    },
    KR: {
        code: 'KR',
        label: 'South Korea',
        browseUrl: 'https://kr.dayuse.com/s/south-korea/seoul',
        hotelCountrySlug: 'south-korea',
    },
    MY: {
        code: 'MY',
        label: 'Malaysia',
        browseUrl: null,
        hotelCountrySlug: 'malaysia',
    },
    NL: {
        code: 'NL',
        label: 'Netherlands',
        browseUrl: 'https://www.dayuse.nl/s/nederland',
        hotelCountrySlug: 'netherlands',
    },
    NZ: {
        code: 'NZ',
        label: 'New Zealand',
        browseUrl: 'https://nz.dayuse.com/s/new-zealand',
        hotelCountrySlug: 'new-zealand',
    },
    PT: {
        code: 'PT',
        label: 'Portugal',
        browseUrl: 'https://pt.dayuse.com/s/portugal',
        hotelCountrySlug: 'portugal',
    },
    QA: {
        code: 'QA',
        label: 'Qatar',
        browseUrl: 'https://qa.dayuse.com/s/qatar',
        hotelCountrySlug: 'qatar',
    },
    SE: {
        code: 'SE',
        label: 'Sweden',
        browseUrl: 'https://www.dayuse.se/s/sweden',
        hotelCountrySlug: 'sweden',
    },
    SG: {
        code: 'SG',
        label: 'Singapore',
        browseUrl: 'https://www.dayuse.sg/s/singapore',
        hotelCountrySlug: 'singapore',
    },
    TH: {
        code: 'TH',
        label: 'Thailand',
        browseUrl: 'https://th.dayuse.com/s/thailand',
        hotelCountrySlug: 'thailand',
    },
    TR: {
        code: 'TR',
        label: 'Turkey',
        browseUrl: 'https://tr.dayuse.com/s/turkiye',
        hotelCountrySlug: 'turkey',
    },
    US: {
        code: 'US',
        label: 'USA',
        browseUrl: 'https://www.dayuse.com/s/united-states',
        hotelCountrySlug: 'usa',
    },
};

// Reverse of `hotelCountrySlug`, for reading a market back out of a hotel
// URL path (`inferCountryCodeFromUrl`). Aliases the backend never emits but
// that appear in real Dayuse links are appended after the generated block.
export const COUNTRY_SLUG_TO_CODE = {
    'united-arab-emirates': 'AE',
    austria: 'AT',
    australia: 'AU',
    belgium: 'BE',
    brazil: 'BR',
    canada: 'CA',
    switzerland: 'CH',
    germany: 'DE',
    spain: 'ES',
    france: 'FR',
    'united-kingdom': 'GB',
    'hong-kong': 'HK',
    ireland: 'IE',
    italy: 'IT',
    'south-korea': 'KR',
    malaysia: 'MY',
    netherlands: 'NL',
    'new-zealand': 'NZ',
    portugal: 'PT',
    qatar: 'QA',
    sweden: 'SE',
    singapore: 'SG',
    thailand: 'TH',
    turkey: 'TR',
    usa: 'US',
    // Hand-kept aliases (not produced by the backend builder):
    'united-states': 'US',
    uk: 'GB',
};
