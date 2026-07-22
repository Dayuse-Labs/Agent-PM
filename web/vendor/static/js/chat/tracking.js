/**
 * Amplitude Tracking
 * Analytics and event tracking helpers
 */

import { state } from './state.js';

function safeString(value, maxLen = 128) {
    return String(value || '').trim().slice(0, maxLen);
}

function getAmplitudeDeviceId() {
    try {
        if (typeof amplitude !== 'undefined' && typeof amplitude.getDeviceId === 'function') {
            const sdkDeviceId = safeString(amplitude.getDeviceId(), 128);
            if (sdkDeviceId) return sdkDeviceId;
        }
    } catch (_e) {
        // no-op
    }
    try {
        const bootstrapDeviceId = window.__DAYUSE_AMPLITUDE_CONTEXT__?.deviceId;
        if (bootstrapDeviceId) return safeString(bootstrapDeviceId, 128);
        return safeString(window.__DAYUSE_NATIVE__?.amp_device_id, 128);
    } catch (_e) {
        return '';
    }
}

function getAmplitudeSessionId() {
    try {
        if (typeof amplitude !== 'undefined' && typeof amplitude.getSessionId === 'function') {
            const sdkSessionId = Number(amplitude.getSessionId());
            if (Number.isSafeInteger(sdkSessionId) && sdkSessionId > 0) {
                return String(sdkSessionId);
            }
        }
    } catch (_e) {
        // no-op
    }
    try {
        const contextSessionId = Number(window.__DAYUSE_AMPLITUDE_CONTEXT__?.sessionId);
        if (Number.isSafeInteger(contextSessionId) && contextSessionId > 0) {
            return String(contextSessionId);
        }
        const nativeSessionId = Number(window.__DAYUSE_NATIVE__?.amp_session_id);
        return Number.isSafeInteger(nativeSessionId) && nativeSessionId > 0
            ? String(nativeSessionId)
            : '';
    } catch (_e) {
        return '';
    }
}

function getTrackingSurface() {
    try {
        const context = window.__DAYUSE_AMPLITUDE_CONTEXT__ || {};
        return {
            tracking_surface: context.surface === 'mobile_app' ? 'mobile_app' : 'web',
            app_platform: context.surface === 'mobile_app'
                ? safeString(context.appPlatform || 'unknown', 32).toLowerCase()
                : null,
            amplitude_identity_source: safeString(context.identitySource || 'sdk_generated', 32),
            amplitude_session_id_present: Boolean(context.sessionId),
        };
    } catch (_e) {
        return {
            tracking_surface: state.entrySource === 'mobile_app' ? 'mobile_app' : 'web',
            app_platform: state.entrySource === 'mobile_app' ? 'unknown' : null,
            amplitude_identity_source: 'sdk_generated',
            amplitude_session_id_present: false,
        };
    }
}

function createEventId() {
    return `ev_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function setOrDeleteSearchParam(url, key, value) {
    const safeValue = safeString(value, 256);
    if (!safeValue) {
        url.searchParams.delete(key);
        return;
    }
    url.searchParams.set(key, safeValue);
}

/**
 * Append amplitude device ID to URL for cross-domain tracking
 */
export function appendAmplitudeIdToUrl(href) {
    try {
        const url = new URL(href);
        const amplitudeDeviceId = getAmplitudeDeviceId();
        const amplitudeSessionId = getAmplitudeSessionId();
        // The Dayuse web/app bundle consumes the amp_* contract before its
        // Amplitude SDK init. Keep amplitude_id temporarily for older landings.
        setOrDeleteSearchParam(url, 'amp_device_id', amplitudeDeviceId);
        setOrDeleteSearchParam(url, 'amp_session_id', amplitudeSessionId);
        setOrDeleteSearchParam(url, 'amplitude_id', amplitudeDeviceId);
        setOrDeleteSearchParam(url, 'du_client_session_id', state.clientSessionId);
        setOrDeleteSearchParam(url, 'du_conversation_id', state.currentConversationId);
        setOrDeleteSearchParam(url, 'du_entry_source', state.entrySource);
        setOrDeleteSearchParam(url, 'du_app_platform', getTrackingSurface().app_platform);
        setOrDeleteSearchParam(url, 'du_dayuse_session_id', state.dayuseSessionId);
        return url.href;
    } catch (e) {
        console.warn('appendAmplitudeIdToUrl error:', e);
        return href;
    }
}

/**
 * Track event to Amplitude and backend
 */
export function trackEvent(event, payload = {}) {
    try {
        const eventId = createEventId();
        const amplitudeDeviceId = getAmplitudeDeviceId();
        const trackingSurface = getTrackingSurface();
        const clickedHotel = event === 'hotel_card_click'
            ? state.previousResults.find(hotel => {
                const hotelId = String(hotel?.id || hotel?.hotel_id || '');
                const payloadId = String(payload.hotel_id || '');
                const hotelName = String(hotel?.name || '');
                const payloadName = String(payload.hotel_name || '');
                return (payloadId && hotelId === payloadId)
                    || (payloadName && hotelName === payloadName);
            })
            : null;
        const resultCountries = [...new Set(
            state.previousResults
                .map(hotel => String(hotel?.country_code || hotel?.country || '').toUpperCase())
                .filter(country => /^[A-Z]{2}$/.test(country))
        )];
        const resolvedSearchCountry = payload.search_country
            || clickedHotel?.country_code
            || clickedHotel?.country
            || (resultCountries.length === 1 ? resultCountries[0] : null)
            || state.selectedFilters?.country_code
            || null;
        const eventProperties = {
            ...payload,
            ...trackingSurface,
            event_id: eventId,
            event_version: 'v2',
            conversation_id: state.currentConversationId,
            client_session_id: state.clientSessionId,
            market_country: payload.market_country || state.market,
            entry_market_country:
                payload.entry_market_country || state.marketContext?.country_code || state.market,
            search_country: resolvedSearchCountry,
            turn_id: payload.turn_id || state.currentTurnId || null,
            response_language: payload.response_language || state.responseLanguage,
            entry_source: state.entrySource,
            dayuse_session_id: state.dayuseSessionId,
            amplitude_device_id: amplitudeDeviceId,
        };

        amplitude.track(event, eventProperties);

        // Send to backend tracking API
        const data = JSON.stringify({
            event: event,
            payload: eventProperties,
            conversation_id: state.currentConversationId,
            client_session_id: state.clientSessionId,
            entry_source: state.entrySource,
            dayuse_session_id: state.dayuseSessionId,
            amplitude_device_id: amplitudeDeviceId,
            event_id: eventId,
        });

        // Use sendBeacon to guarantee delivery even if page closes
        if (navigator.sendBeacon) {
            const blob = new Blob([data], { type: 'application/json' });
            const success = navigator.sendBeacon('/api/track', blob);
            if (!success) {
                console.warn('sendBeacon failed, falling back to fetch');
                fetchTrack(data);
            }
        } else {
            fetchTrack(data);
        }
    } catch (e) {
        console.error('Track error:', e);
    }
}

function fetchTrack(data) {
    fetch('/api/track', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: data
    }).catch(err => console.error('Track error:', err));
}

/**
 * Track chat open event
 */
export function trackChatOpen() {
    trackEvent('chat_open', {
        source: document.referrer || 'direct',
        locale: navigator.language
    });
}
