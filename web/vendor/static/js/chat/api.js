/**
 * Chat API helpers.
 */

import { state } from './state.js';

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
    const market = state.marketContext || {};
    if (market.domain) {
        headers['X-Dayuse-Domain'] = String(market.domain);
    }
    if (market.language) {
        headers['Accept-Language'] = String(market.language);
    }

    return headers;
}
