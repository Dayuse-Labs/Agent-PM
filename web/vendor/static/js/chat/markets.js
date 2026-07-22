/**
 * Market helpers.
 *
 * Keep country/market resolution deterministic. Prices are not a reliable
 * market signal because several Dayuse markets can display dollar-prefixed
 * amounts in upstream payloads.
 */

const COUNTRY_META = {
    US: {
        code: 'US',
        label: 'USA',
        browseUrl: 'https://www.dayuse.com/s/united-states',
        hotelCountrySlug: 'usa',
    },
    SG: {
        code: 'SG',
        label: 'Singapore',
        browseUrl: 'https://www.dayuse.sg/s/singapore',
        hotelCountrySlug: 'singapore',
    },
    IT: {
        code: 'IT',
        label: 'Italy',
        browseUrl: 'https://www.dayuse-hotels.it/s/italia',
        hotelCountrySlug: 'italy',
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
    UK: {
        code: 'GB',
        label: 'United Kingdom',
        browseUrl: 'https://www.dayuse.co.uk/s/united-kingdom',
        hotelCountrySlug: 'united-kingdom',
    },
    DE: {
        code: 'DE',
        label: 'Germany',
        browseUrl: 'https://www.dayuse.de/s/germany',
        hotelCountrySlug: 'germany',
    },
    BE: {
        code: 'BE',
        label: 'Belgium',
        browseUrl: 'https://www.dayuse.be/s/belgique',
        hotelCountrySlug: 'belgium',
    },
    NL: {
        code: 'NL',
        label: 'Netherlands',
        browseUrl: 'https://www.dayuse.nl/s/nederland',
        hotelCountrySlug: 'netherlands',
    },
    CH: {
        code: 'CH',
        label: 'Switzerland',
        browseUrl: 'https://www.dayuse.ch/s/suisse',
        hotelCountrySlug: 'switzerland',
    },
    AT: {
        code: 'AT',
        label: 'Austria',
        browseUrl: 'https://www.dayuse.at/s/austria',
        hotelCountrySlug: 'austria',
    },
    PT: {
        code: 'PT',
        label: 'Portugal',
        browseUrl: 'https://pt.dayuse.com/s/portugal',
        hotelCountrySlug: 'portugal',
    },
    CA: {
        code: 'CA',
        label: 'Canada',
        browseUrl: 'https://www.dayuse.com/s/canada',
        hotelCountrySlug: 'canada',
    },
    AU: {
        code: 'AU',
        label: 'Australia',
        browseUrl: 'https://www.dayuse.com/s/australia',
        hotelCountrySlug: 'australia',
    },
    IE: {
        code: 'IE',
        label: 'Ireland',
        browseUrl: 'https://www.dayuse.ie/s/ireland',
        hotelCountrySlug: 'ireland',
    },
    SE: {
        code: 'SE',
        label: 'Sweden',
        browseUrl: 'https://www.dayuse.se/s/sweden',
        hotelCountrySlug: 'sweden',
    },
    HK: {
        code: 'HK',
        label: 'Hong Kong',
        browseUrl: 'https://www.dayuse.com/s/hong-kong',
        hotelCountrySlug: 'hong-kong',
    },
    AE: {
        code: 'AE',
        label: 'United Arab Emirates',
        browseUrl: 'https://www.dayuse.com/s/united-arab-emirates',
        hotelCountrySlug: 'united-arab-emirates',
    },
    BR: {
        code: 'BR',
        label: 'Brazil',
        browseUrl: 'https://www.dayuse.com/s/brazil',
        hotelCountrySlug: 'brazil',
    },
    NZ: {
        code: 'NZ',
        label: 'New Zealand',
        browseUrl: 'https://www.dayuse.com/s/new-zealand',
        hotelCountrySlug: 'new-zealand',
    },
    TH: {
        code: 'TH',
        label: 'Thailand',
        browseUrl: 'https://www.dayuse.com/s/thailand',
        hotelCountrySlug: 'thailand',
    },
    MY: {
        code: 'MY',
        label: 'Malaysia',
        browseUrl: 'https://www.dayuse.com/s/malaysia',
        hotelCountrySlug: 'malaysia',
    },
};

const COUNTRY_SLUG_TO_CODE = {
    usa: 'US',
    'united-states': 'US',
    singapore: 'SG',
    italy: 'IT',
    spain: 'ES',
    france: 'FR',
    'united-kingdom': 'GB',
    uk: 'GB',
    germany: 'DE',
    belgium: 'BE',
    netherlands: 'NL',
    switzerland: 'CH',
    austria: 'AT',
    portugal: 'PT',
    canada: 'CA',
    australia: 'AU',
    ireland: 'IE',
    sweden: 'SE',
    'hong-kong': 'HK',
    'united-arab-emirates': 'AE',
    brazil: 'BR',
    'new-zealand': 'NZ',
    thailand: 'TH',
    malaysia: 'MY',
};

export function normalizeCountryCode(value) {
    const code = String(value || '').trim().toUpperCase();
    if (!code) return '';
    if (code === 'UK') return 'GB';
    return /^[A-Z]{2}$/.test(code) ? code : '';
}

function inferCountryCodeFromUrl(rawUrl) {
    if (!rawUrl || typeof rawUrl !== 'string') return '';
    let url;
    try {
        url = new URL(rawUrl.startsWith('http') ? rawUrl : `https://${rawUrl}`);
    } catch (_err) {
        return '';
    }

    const host = String(url.hostname || '').toLowerCase();
    if (host.endsWith('dayuse.sg')) return 'SG';
    if (host.endsWith('dayuse.fr')) return 'FR';

    const parts = String(url.pathname || '').split('/').filter(Boolean);
    const hotelsIndex = parts.indexOf('hotels');
    if (hotelsIndex !== -1 && parts[hotelsIndex + 1]) {
        return normalizeCountryCode(COUNTRY_SLUG_TO_CODE[parts[hotelsIndex + 1]]);
    }

    const searchIndex = parts.indexOf('s');
    if (searchIndex !== -1 && parts[searchIndex + 1]) {
        return normalizeCountryCode(COUNTRY_SLUG_TO_CODE[parts[searchIndex + 1]]);
    }

    return '';
}

export function inferCountryCodeFromHotel(hotel) {
    if (!hotel || typeof hotel !== 'object') return '';
    return normalizeCountryCode(hotel.country_code || hotel.countryCode || hotel.country)
        || inferCountryCodeFromUrl(hotel.url || hotel.booking_url || '');
}

export function getMarketMeta(countryCode, fallbackCountryCode = 'US') {
    const code = normalizeCountryCode(countryCode) || normalizeCountryCode(fallbackCountryCode) || 'US';
    return COUNTRY_META[code] || {
        code,
        label: code,
        browseUrl: 'https://www.dayuse.com',
        hotelCountrySlug: code.toLowerCase(),
    };
}

export function getMarketMetaFromHotels(hotels, fallbackCountryCode = 'US') {
    const firstHotel = Array.isArray(hotels) && hotels.length > 0 ? hotels[0] : null;
    return getMarketMeta(inferCountryCodeFromHotel(firstHotel), fallbackCountryCode);
}

export function buildHotelFallbackUrl(hotel) {
    const name = String(hotel?.name || 'hotel');
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'hotel';
    const meta = getMarketMeta(inferCountryCodeFromHotel(hotel), 'US');

    if (meta.code === 'US') {
        return `https://dayuse.com/hotels/usa/${slug}`;
    }
    if (meta.code === 'SG') {
        return `https://www.dayuse.sg/hotels/singapore/${slug}`;
    }
    // Never emit the legacy /hotel/<id>/<slug> path — it 404s on every host.
    return `https://www.dayuse.com/hotels/${meta.hotelCountrySlug}/${slug}`;
}
