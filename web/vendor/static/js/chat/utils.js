/**
 * Utility Functions
 * Time formatting, URL manipulation, etc.
 */

import { state } from './state.js';
import { appendAmplitudeIdToUrl } from './tracking.js';
import { sanitizeDayuseUrl } from './security.js';
import { buildHotelFallbackUrl, normalizeCountryCode } from './markets.js';
import { getLanguage } from './i18n.js';

/**
 * The mobile app injects `window.__DAYUSE_NATIVE__` into this page (loaded in
 * its webview) with the logged-in user's context (recent bookings, favourites,
 * geolocation). Return it as a plain object, or null when absent (web / not
 * logged in). The backend reads it from `body.native_context`.
 */
export function getNativeContext() {
    try {
        const n = typeof window !== 'undefined' ? window.__DAYUSE_NATIVE__ : null;
        return n && typeof n === 'object' ? n : null;
    } catch (e) {
        return null;
    }
}

/** Return the browser's local clock without relying on the server timezone. */
export function getClientTimeContext() {
    const now = new Date();
    const pad = value => String(value).padStart(2, '0');
    let timezone = null;
    try {
        timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || null;
    } catch (e) {
        timezone = null;
    }
    return {
        client_local_time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
        client_timezone: timezone
    };
}

/**
 * Convert 24h format to AM/PM (e.g., "08:00" → "8am", "15:00" → "3pm")
 */
export function formatTimeAMPM(time24) {
    if (!time24) return '';
    const [hourStr, minuteStr] = time24.split(':');
    let hour = parseInt(hourStr);
    const minute = parseInt(minuteStr || 0);
    const period = hour >= 12 ? 'pm' : 'am';

    if (hour === 0) hour = 12;
    else if (hour > 12) hour -= 12;

    return minute > 0 ? `${hour}:${minuteStr}${period}` : `${hour}${period}`;
}

/** ES hands the raw average through (4.666666666666667) — one decimal, in the
 *  reader's language. Non-numeric ratings pass through untouched.
 *
 *  Formatted against the CHAT language, not `undefined`: `undefined` means the
 *  OS locale, so a French card on an English-locale device rendered "4.6" —
 *  caught by rendering the card outside the browser (S-CX8).
 *
 *  S-CX9: lives here rather than in `ui/messages.js` because the shortlist card
 *  now shows the same rating as the booking card. Two formatters would be two
 *  chances to disagree about the decimal separator on the same screen. */
export function formatRating(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return String(value);
    try {
        return num.toLocaleString(getLanguage(), {
            minimumFractionDigits: 1, maximumFractionDigits: 1,
        });
    } catch (_) {
        return num.toFixed(1);
    }
}

/**
 * Replace [HOTEL_ID:xxx] tags with real URLs from previousResults
 */
export function replaceHotelIdTags(html) {
    if (!html || !state.previousResults || state.previousResults.length === 0) {
        return html;
    }

    const hotelMap = buildHotelMap();
    const parser = new DOMParser();
    const doc = parser.parseFromString(`<div id="hotel-id-rewrite-root">${String(html)}</div>`, 'text/html');
    const root = doc.getElementById('hotel-id-rewrite-root');
    if (!root) {
        return html;
    }

    root.querySelectorAll('[data-hotel-id]').forEach(element => {
        const parsedHotelId = parseHotelIdToken(element.getAttribute('data-hotel-id') || '');
        if (!parsedHotelId) return;
        element.setAttribute('data-hotel-id', parsedHotelId);
        if (element.tagName.toLowerCase() === 'a') {
            applyTrackedHotelLink(element, parsedHotelId, hotelMap);
        }
    });

    root.querySelectorAll('a[href]').forEach(anchor => {
        const rawHref = anchor.getAttribute('href') || '';
        const parsedHotelId = parseHotelIdToken(rawHref);
        if (!parsedHotelId) return;
        applyTrackedHotelLink(anchor, parsedHotelId, hotelMap);
    });

    return root.innerHTML.replace(/\[HOTEL_ID:(\d+)\]/g, (_, hotelId) => {
        const hotel = hotelMap[String(hotelId)];
        return hotel?.url || '#';
    });
}

function buildHotelMap() {
    const hotelMap = {};
    state.previousResults.forEach(hotel => {
        const id = hotel.id || hotel.hotel_id;
        if (!id) return;

        const name = String(hotel.name || '');
        const price = String(hotel.price || '');
        const fallbackUrl = buildHotelFallbackUrl(hotel);
        const trackedUrl = appendAmplitudeIdToUrl(String(hotel.url || fallbackUrl));
        const safeUrl = sanitizeDayuseUrl(trackedUrl) || '#';

        hotelMap[String(id)] = { url: safeUrl, name, price };
    });
    return hotelMap;
}

function parseHotelIdToken(rawValue) {
    const value = String(rawValue || '').trim();
    if (!value) return null;
    const tagged = value.match(/^\[HOTEL_ID:(\d+)\]$/);
    if (tagged) return tagged[1];
    if (/^\d+$/.test(value)) return value;
    return null;
}

function applyTrackedHotelLink(anchor, hotelId, hotelMap) {
    const hotelData = hotelMap[String(hotelId)] || { url: '#', name: '', price: '' };
    anchor.setAttribute('href', hotelData.url);
    anchor.setAttribute('target', '_blank');
    anchor.setAttribute('rel', 'noopener');
    anchor.setAttribute('data-track-hotel-click', '1');
    anchor.setAttribute('data-hotel-id', String(hotelId));
    anchor.setAttribute('data-hotel-name', hotelData.name);
    anchor.setAttribute('data-hotel-price', hotelData.price);
    anchor.setAttribute('data-hotel-url', hotelData.url);
}

/**
 * Handle context update from API response
 */
export function handleContextUpdate(data) {
    const responseMarket = normalizeCountryCode(data.market_country);
    if (responseMarket) {
        state.market = responseMarket;
    }

    if (data.active_filters) {
        const filters = data.active_filters;
        const filterMarket = normalizeCountryCode(filters.country_code || filters.country);
        if (filterMarket) {
            state.market = filterMarket;
        }

        if (filters.timeslot) {
            const ts = String(filters.timeslot).toLowerCase();
            if (ts === 'morning') state.selectedFilters.timeslot = 'early';
            else if (ts === 'afternoon' || ts === 'full_day') state.selectedFilters.timeslot = 'day';
            else if (ts === 'evening') state.selectedFilters.timeslot = 'late';
            else state.selectedFilters.timeslot = filters.timeslot;
        }
        if (filters.city) {
            state.selectedFilters.city = filters.city;
        } else {
            state.selectedFilters.city = '';
        }
        if (Array.isArray(filters.amenities) && filters.amenities.length > 0) {
            state.selectedFilters.amenities = filters.amenities;
        }

        if (filters.timeslot_start) {
            const start = parseInt(String(filters.timeslot_start).split(':')[0], 10);
            if (!Number.isNaN(start)) {
                state.selectedFilters.requested_start_hour = start;
            }
        }
        if (filters.timeslot_end) {
            const end = parseInt(String(filters.timeslot_end).split(':')[0], 10);
            if (!Number.isNaN(end)) {
                state.selectedFilters.requested_end_hour = end;
            }
        }
    }

    if (data.context_update) {
        console.log('Context update received:', data.context_update);

        if (data.context_update.active_hotel_ids) {
            state.activeHotelIds = data.context_update.active_hotel_ids;
        }

        if (data.context_update.should_replace_list && data.hotels_data) {
            state.previousResults = data.hotels_data;
        }

        return true;
    }
    return false;
}

export function hasEffectiveTimeslot(data = {}) {
    const filters = data.active_filters || data.context_update?.active_filters || {};
    if (
        filters.timeslot ||
        filters.timeslot_start ||
        filters.timeslot_end ||
        filters.requested_start_hour != null ||
        filters.requested_end_hour != null
    ) {
        return true;
    }

    const selected = state.selectedFilters || {};
    return Boolean(
        selected.timeslot ||
        selected.requested_start_hour != null ||
        selected.requested_end_hour != null
    );
}
