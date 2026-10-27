/**
 * Chat API helpers.
 */

import { state } from './state.js';
import { isSyntheticRun } from './tracking.js';

function readMeta(name) {
    return document.querySelector(`meta[name="${name}"]`)?.content?.trim() || '';
}

export function getChatEndpoint() {
    return readMeta('du-chat-endpoint') || '/v3/chat';
}

// Personalized opening-chips endpoint, derived from the chat endpoint so it
// keeps the same auth surface (/v3/chat → /v3/chat/welcome, the /public variant
// → /v3/chat/welcome/public).
export function getWelcomeEndpoint() {
    return getChatEndpoint().replace('/v3/chat', '/v3/chat/welcome');
}

/**
 * The body of the mobile app's welcome call: the app's native context, and
 * the page's market so the greeting speaks its language (2026-10-27 — the
 * concierge serves /v3/chat/welcome again; without a locale it answers in
 * English).
 */
export function welcomeRequestBody(native) {
    return {
        native_context: native,
        locale: state.marketContext?.language || null,
        currency: state.marketContext?.currency || null,
    };
}

// SSE endpoint, derived the same way (/v3/chat → /v3/chat/stream).
export function getStreamEndpoint() {
    return getChatEndpoint().replace('/v3/chat', '/v3/chat/stream');
}

// OBS5: user-feedback endpoint, same derivation, same origin, same auth
// headers as /v3/chat — the widget proxy already forwards any /v3/* path, so
// this needs no server-side wiring beyond the concierge route itself.
export function getFeedbackEndpoint() {
    return getChatEndpoint().replace('/v3/chat', '/v3/feedback');
}

/**
 * Transport for a chat turn. 'sse' streams /v3/chat/stream so the hotel cards
 * render on the `hotels` frame — seconds before the synthesis text — while
 * anything else keeps the blocking POST /v3/chat. Server-substituted meta
 * (WIDGET_CHAT_TRANSPORT in the widget proxy) so flipping it is an env change,
 * not a JS redeploy. Defaults to the blocking POST.
 */
export function getChatTransport() {
    return readMeta('du-chat-transport').toLowerCase() === 'sse' ? 'sse' : 'json';
}

export function getChatHeaders() {
    const headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    };

    const token = readMeta('du-chat-public-token');
    const tokenHeader = readMeta('du-chat-public-token-header') || 'X-Chat-Public-Token';

    if (token) {
        headers[tokenHeader] = token;
    }

    if (state.clientSessionId) {
        headers['X-Client-Session-Id'] = state.clientSessionId;
    }
    if (isSyntheticRun()) {
        headers['X-Dayuse-Synthetic'] = '1';
    }
    const market = state.marketContext || {};
    if (market.domain) {
        headers['X-Dayuse-Domain'] = String(market.domain);
    }
    if (market.language) {
        headers['Accept-Language'] = String(market.language);
    }

    return headers;
}
