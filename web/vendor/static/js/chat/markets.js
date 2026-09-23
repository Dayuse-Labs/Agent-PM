/**
 * Market helpers.
 *
 * Keep country/market resolution deterministic. Prices are not a reliable
 * market signal because several Dayuse markets can display dollar-prefixed
 * amounts in upstream payloads.
 */

/**
 * The market tables are GENERATED from the Python referential
 * (`_MARKET` / `_BROWSE_PATH` / `_LABEL` in
 * libs/b2c_common/b2c_common/hotel_urls.py) by
 * scripts/generate_widget_markets.py — they used to be hand-written here, a
 * second copy of the same referential. Measured 2026-08-28 before the switch:
 * 8 of 22 market hosts already disagreed with the backend, and
 * `www.dayuse.com/s/brazil` + `/s/malaysia` were live 404s. Edit the Python
 * table, run the generator; CI fails if the generated file is stale.
 */
import { COUNTRY_META, COUNTRY_SLUG_TO_CODE } from './markets.generated.js';

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
    // An unmapped market gets NO browseUrl rather than a guessed one — same rule
    // as the backend builder and as the card link (UX6 2026-08-28). It used to
    // return 'https://www.dayuse.com' plus a `hotelCountrySlug` guessed from the
    // ISO code; the slug's only reader was the removed name-slugifying fallback,
    // and the bare host sent every unmapped market to the US home page.
    return COUNTRY_META[code] || { code, label: code, browseUrl: null };
}

export function getMarketMetaFromHotels(hotels, fallbackCountryCode = 'US') {
    const firstHotel = Array.isArray(hotels) && hotels.length > 0 ? hotels[0] : null;
    return getMarketMeta(inferCountryCodeFromHotel(firstHotel), fallbackCountryCode);
}

/**
 * Market of the hotels actually on screen, or null when they carry no country.
 * The "see all" CTA above a results carousel must follow THIS market, not the
 * page's entry market: a Singapore search opened from the default widget host
 * sent "Voir tout" to www.dayuse.com/s/united-states (QA 2026-09-23) while the
 * carousel's own link, already hotel-based, correctly said Singapore.
 */
export function getResultsMarketMeta(hotels) {
    const code = inferCountryCodeFromHotel(Array.isArray(hotels) ? hotels[0] : null);
    return code ? getMarketMeta(code) : null;
}

// `buildHotelFallbackUrl` was REMOVED here (UX6 audit, 2026-08-28, arbitrated by
// Fabien). It slugified the hotel's DISPLAY NAME and served it on a guessed
// host, which is exactly what the backend builder forbids itself from doing —
// `libs/b2c_common/b2c_common/hotel_urls.py`: "nothing in this repo may ever
// slugify a display name into a URL ... an unmapped country yields None, the
// card honestly has no link rather than a guessed one".
//
// The widget was silently defeating that contract. Measured before removal, on
// the real modules: a hotel in a country absent from `_ISO_BY_COUNTRY_NAME`
// (so the backend correctly sent NO url) rendered as
//   'Hôtel Métropole & Spa' (Poland) -> https://dayuse.com/hotels/usa/h-tel-m-tropole-spa
// — wrong market (every unmapped country fell through to the 'US' default of
// `getMarketMeta`, since `inferCountryCodeFromHotel` needs a 2-letter code and
// a full name like "Poland" yields ''), invented accent-mangled slug, and it
// PASSED `sanitizeDayuseUrl`, so it rendered as a live booking link that 404s.
//
// There is deliberately no replacement: no url from the server means no
// hotel-page link on the card. See reports/AUDIT-MAPPINGS-2026-08-28.md §6.2.
