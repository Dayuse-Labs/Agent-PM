/**
 * Chat State Management
 * Global state for the chat application
 */

import { detectPreferredLanguage } from './i18n.js';

function readMeta(name) {
    return document.querySelector(`meta[name="${name}"]`)?.content?.trim() || '';
}

const CLIENT_SESSION_STORAGE_KEY = 'du_chat_client_session_id';

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

function getOrCreateClientSessionId() {
    try {
        const existing = sessionStorage.getItem(CLIENT_SESSION_STORAGE_KEY);
        if (existing) return String(existing);
        const next = createRandomId();
        sessionStorage.setItem(CLIENT_SESSION_STORAGE_KEY, next);
        return next;
    } catch (_e) {
        // Privacy mode / storage restrictions fallback.
        return createRandomId();
    }
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
    clientSessionId: getOrCreateClientSessionId(),
    currentConversationId: null,
    currentTurnId: null,
    turnSequence: 0,
    currentSlide: 0,
    isProcessing: false,
    totalSlides: 0,
    previousResults: [],
    activeHotelIds: [],
    selectedFilters: {},
    selectedPlace: null,
    currentLimit: 8,
    currentUserQuery: '',
    responseLanguage: DEFAULT_MARKET_CONTEXT.language,
    market: DEFAULT_MARKET_CONTEXT.country_code,
    marketContext: { ...DEFAULT_MARKET_CONTEXT },
    pendingClarification: null,
    entrySource: getInitialEntrySource(),
    dayuseSessionId: null,
};

// Image carousel state
export const carousels = new Map();

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
    // Keep the legacy two-letter `state.market` in sync for any consumer
    // that still reads it (amplitude tagging, etc.).
    if (typeof merged.country_code === 'string' && merged.country_code) {
        state.market = merged.country_code.toUpperCase();
    }
}

// Reset state
export function resetState() {
    state.currentConversationId = null;
    state.currentTurnId = null;
    state.turnSequence = 0;
    state.currentSlide = 0;
    state.isProcessing = false;
    state.totalSlides = 0;
    state.previousResults = [];
    state.activeHotelIds = [];
    state.selectedFilters = {};
    state.selectedPlace = null;
    state.currentLimit = 8;
    state.currentUserQuery = '';
    state.responseLanguage = detectPreferredLanguage();
    state.market = 'US';
    state.pendingClarification = null;
    carousels.clear();
}
