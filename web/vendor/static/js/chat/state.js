/**
 * Chat State Management
 * Global state for the chat application
 */

import { detectPreferredLanguage } from './i18n.js';

function readMeta(name) {
    return document.querySelector(`meta[name="${name}"]`)?.content?.trim() || '';
}

/**
 * One id per PAGE LOAD — deliberately NOT persisted (it used to live in
 * sessionStorage, which survives a reload). A reload wipes the visible
 * conversation, so it must start a new server session too: the id we mint here
 * is what `api.js` sends as `X-Client-Session-Id`, and the facade now trusts
 * that header over its own httponly `du_chat_sid` cookie. Persist this again
 * and the reloaded page silently resumes the previous search's criteria.
 */
function createRandomId() {
    try {
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
            return crypto.randomUUID();
        }
    } catch (_e) {
        // no-op
    }
    return `cs_${Date.now()}_${Math.random().toString(36).slice(2, 12)}`;
}

function getInitialEntrySource() {
    try {
        const native = window.__DAYUSE_NATIVE__;
        if (native && typeof native === 'object') return 'mobile_app';
    } catch (_e) {
        // no-op
    }
    return null;
}

export const DEFAULT_MARKET_CONTEXT = Object.freeze({
    country_code: (readMeta('du-chat-country') || 'US').toUpperCase(),
    currency: (readMeta('du-chat-currency') || 'USD').toUpperCase(),
    language: (readMeta('du-chat-language') || detectPreferredLanguage() || 'en').toLowerCase(),
    display_name: '',
    domain: readMeta('du-chat-domain') || 'dayuse.com',
    browse_url: readMeta('du-chat-browse-url') || '',
    source: readMeta('du-chat-country') ? 'signed_render' : 'default',
});

export const state = {
    clientSessionId: createRandomId(),
    currentConversationId: null,
    currentTurnId: null,
    turnSequence: 0,
    currentSlide: 0,
    isProcessing: false,
    totalSlides: 0,
    previousResults: [],
    // S-CX5: the hotel picks the API offered for the CURRENT screen (already
    // sorted cheapest-first server-side — never re-sorted here).
    // S-CX9: no longer drawn as its own chip row. It is now read as a PERMISSION
    // by `hotels/card.js` — an empty list means the backend judges the request
    // too vague to book (no destination resolved yet), so no card shows a pick
    // CTA. Losing that gate would put a booking button on a shortlist the
    // backend never qualified.
    hotelPicks: [],
    activeHotelIds: [],
    selectedFilters: {},
    selectedPlace: null,
    currentLimit: 8,
    currentUserQuery: '',
    responseLanguage: DEFAULT_MARKET_CONTEXT.language,
    market: DEFAULT_MARKET_CONTEXT.country_code,
    knownMarket: null,
    marketContext: { ...DEFAULT_MARKET_CONTEXT },
    searchPage: null,
    entrySource: getInitialEntrySource(),
};

// Image carousel state
export const carousels = new Map();

export function startTurn() {
    state.turnSequence += 1;
    state.currentTurnId = `${state.clientSessionId}_t${state.turnSequence}`;
    return { turnId: state.currentTurnId, turnIndex: state.turnSequence };
}

export function rememberMarket(countryCode) {
    const code = String(countryCode || '').trim().toUpperCase();
    if (/^[A-Z]{2}$/.test(code)) state.knownMarket = code;
}

/**
 * Merge a chat response's `market` payload into state.marketContext. The
 * backend resolves the right market per-turn (X-Dayuse-Domain → Origin →
 * Referer), so every response is authoritative. Missing or malformed market
 * fields fall back to the previous value, keeping `state.marketContext` valid
 * even when the backend forgets to echo it.
 */
export function applyMarketFromResponse(data) {
    const incoming = data && typeof data === 'object' ? data.market : null;
    if (!incoming || typeof incoming !== 'object') return;
    const merged = { ...state.marketContext };
    [
        'country_code',
        'currency',
        'language',
        'display_name',
        'domain',
        'browse_url',
        'source',
    ].forEach((key) => {
        const value = incoming[key];
        if (typeof value === 'string' && value.trim()) {
            merged[key] = value.trim();
        }
    });
    state.marketContext = merged;
    rememberMarket(incoming.country_code);
    // Keep the legacy two-letter `state.market` in sync for any consumer
    // that still reads it.
    if (typeof merged.country_code === 'string' && merged.country_code) {
        state.market = merged.country_code.toUpperCase();
    }
    setSearchPage(incoming.search_page);
}

/**
 * The site's search page for the last search that ran ({ name, url }), or null
 * (mcp-dayuse#5): "Voir tout" opens it instead of the country page. Set from
 * every results frame and response — absent means this search has none.
 */
export function setSearchPage(page) {
    const valid = page && typeof page === 'object' && typeof page.url === 'string' && page.url;
    state.searchPage = valid ? { url: page.url, name: String(page.name || '') } : null;
}

// Reset state
export function resetState() {
    // A new conversation gets a new client session id: the reset endpoint just
    // deleted the server session behind the old one, and reusing that id would
    // file the fresh conversation under the previous session in Langfuse/Redis.
    state.clientSessionId = createRandomId();
    state.currentConversationId = null;
    state.currentTurnId = null;
    state.turnSequence = 0;
    state.currentSlide = 0;
    state.isProcessing = false;
    state.totalSlides = 0;
    state.previousResults = [];
    state.searchPage = null;
    state.activeHotelIds = [];
    state.selectedFilters = {};
    state.selectedPlace = null;
    state.currentLimit = 8;
    state.currentUserQuery = '';
    state.responseLanguage = detectPreferredLanguage();
    state.market = 'US';
    carousels.clear();
}
