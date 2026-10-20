/**
 * Amplitude tracking: the only emitter of the agent's product analytics.
 * Event names and properties are fixed by contracts/amplitude_events.json.
 */

import { state } from './state.js';

const AMPLITUDE_SDK_URL = 'https://cdn.amplitude.com/libs/analytics-browser-2.11.2-min.js.gz';
const SESSION_REPLAY_URL = 'https://cdn.amplitude.com/libs/plugin-session-replay-browser-1.13.2-min.js.gz';
const SESSION_REPLAY_SAMPLE_RATE = 0.05;
const SESSION_REPLAY_LOAD_TIMEOUT_MS = 3000;
const AMPLITUDE_PROXY_URL = 'https://alitude.dayuse.com/2/httpapi';
const AMPLITUDE_API_KEYS = {
    production: 'ba76a8f0fdbac6f02609480ab477de4f',
    development: '4490e59977a700c2c1651fde48670583',
};

const UNKNOWN = 'unknown';
const NONE = 'none';
const MAX_TEXT_LENGTH = 500;
const PROMPT_SOURCES = ['typed', 'initial_prompt', 'suggestion'];
const DAYUSE_ENTRY_SOURCES = ['banner_home', 'banner_search', 'section_home'];
const DEEPLINK_PARAMS = ['q', 'query', 'source'];

// Captured at load: index.js strips the deep-link params from the URL right after.
const landingParams = new URLSearchParams(window.location.search);

const pendingEvents = [];
let amplitude = null;
const turnsById = new Map();

function truncate(text, maxLength = MAX_TEXT_LENGTH) {
    return String(text ?? '').slice(0, maxLength);
}

function stringOr(value, sentinel) {
    const text = String(value ?? '').trim();
    return text || sentinel;
}

function readMeta(name) {
    return document.querySelector(`meta[name="${name}"]`)?.content?.trim() || '';
}

function nativeContext() {
    const native = window.__DAYUSE_NATIVE__;
    return native && typeof native === 'object' ? native : null;
}

function cleanDeviceId(value) {
    const deviceId = String(value || '').trim().slice(0, 128);
    return /^(null|undefined|none)$/i.test(deviceId) ? '' : deviceId;
}

function cleanSessionId(value) {
    const sessionId = Number(value);
    return Number.isSafeInteger(sessionId) && sessionId > 0 ? sessionId : undefined;
}

function handedOverIdentity() {
    const native = nativeContext();
    return {
        deviceId: cleanDeviceId(native?.amp_device_id) || cleanDeviceId(landingParams.get('amp_device_id')),
        sessionId: cleanSessionId(native?.amp_session_id) ?? cleanSessionId(landingParams.get('amp_session_id')),
    };
}

function appPlatformOf(native) {
    const declared = String(native.app_platform || native.appPlatform || native.platform || '').toLowerCase();
    if (['ios', 'iphone', 'ipad'].includes(declared)) return 'ios';
    if (declared === 'android') return 'android';
    const userAgent = String(window.navigator?.userAgent || '').toLowerCase();
    if (/iphone|ipad|ipod/.test(userAgent)) return 'ios';
    if (/android/.test(userAgent)) return 'android';
    // The contract's app_platform enum has no "unknown".
    return NONE;
}

function entrySource(native) {
    const declared = String(landingParams.get('du_entry_source') || '').trim().toLowerCase();
    if (DAYUSE_ENTRY_SOURCES.includes(declared)) return declared;
    if (native) return 'app';
    if (DEEPLINK_PARAMS.some(name => landingParams.get(name))) return 'deeplink';
    return 'direct';
}

function countryCode(value) {
    const code = String(value || '').trim().toUpperCase();
    return /^[A-Z]{2}$/.test(code) ? code : UNKNOWN;
}

function hostnameOf(url) {
    try {
        return new URL(url).hostname || NONE;
    } catch (_e) {
        return NONE;
    }
}

function declaredMarket() {
    const native = nativeContext();
    return countryCode(
        native?.market_country || native?.country_code || landingParams.get('market_country') || state.knownMarket,
    );
}

function uuidV4() {
    const webCrypto = globalThis.crypto;
    if (typeof webCrypto?.randomUUID === 'function') return webCrypto.randomUUID();
    const bytes = new Uint8Array(16);
    if (typeof webCrypto?.getRandomValues === 'function') webCrypto.getRandomValues(bytes);
    else bytes.forEach((_byte, index) => { bytes[index] = Math.floor(Math.random() * 256); });
    // RFC 9562 §5.4: version nibble 4, variant bits 10.
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function commonProperties() {
    const native = nativeContext();
    return {
        conversation_id: stringOr(state.clientSessionId, UNKNOWN),
        tracking_surface: native ? 'mobile_app' : 'web',
        app_platform: native ? appPlatformOf(native) : NONE,
        entry_source: entrySource(native),
        domain: stringOr(window.location.hostname, UNKNOWN),
        market_country: declaredMarket(),
        language: stringOr(state.responseLanguage, UNKNOWN).toLowerCase(),
        agent_version: stringOr(readMeta('agent-version'), UNKNOWN),
        is_synthetic: isSyntheticRun(),
        dayuse_event_id: uuidV4(),
    };
}

function turnReference(turnId) {
    const turn = turnsById.get(turnId);
    return {
        turn_id: stringOr(turnId, UNKNOWN),
        turn_index: turn?.turnIndex ?? 0,
        langfuse_trace_id: turn?.traceId || NONE,
    };
}

function toHotelId(value) {
    const id = Number(value);
    return Number.isSafeInteger(id) ? id : 0;
}

export function amplitudeApiKeyFor(hostname) {
    return /^ai\.dayuse\.[a-z]{2,3}(?:\.[a-z]{2})?$/.test(String(hostname || ''))
        ? AMPLITUDE_API_KEYS.production
        : AMPLITUDE_API_KEYS.development;
}

export function isSyntheticRun() {
    return new URLSearchParams(window.location.search).get('du_synthetic') === '1';
}

function addSessionReplay(sdk, replay) {
    if (!replay || isSyntheticRun()) return;
    try {
        sdk.add(replay.plugin({
            sampleRate: SESSION_REPLAY_SAMPLE_RATE,
            serverZone: 'EU',
            configServerUrl: new URL('/sr-config', window.location.origin).href,
        }));
    } catch (e) {
        console.error('Session Replay error:', e);
    }
}

export function startAmplitude(sdk, replay = null) {
    const identity = handedOverIdentity();
    addSessionReplay(sdk, replay);
    sdk.init(amplitudeApiKeyFor(window.location.hostname), null, {
        serverUrl: AMPLITUDE_PROXY_URL,
        serverZone: 'EU',
        fetchRemoteConfig: true,
        deviceId: identity.deviceId || undefined,
        sessionId: identity.sessionId,
        defaultTracking: false,
    });
    amplitude = sdk;
    pendingEvents.splice(0).forEach(({ name, properties }) => send(name, properties));
}

function loadScript(url, onSettled) {
    const script = document.createElement('script');
    script.src = url;
    script.async = true;
    script.onload = onSettled;
    script.onerror = onSettled;
    document.head.appendChild(script);
}

function startWithOptionalReplay() {
    if (!window.amplitude) return;
    if (isSyntheticRun()) {
        startAmplitude(window.amplitude);
        return;
    }
    let started = false;
    const start = () => {
        if (started) return;
        started = true;
        startAmplitude(window.amplitude, window.sessionReplay);
    };
    loadScript(SESSION_REPLAY_URL, start);
    setTimeout(start, SESSION_REPLAY_LOAD_TIMEOUT_MS);
}

export function loadAmplitude() {
    loadScript(AMPLITUDE_SDK_URL, startWithOptionalReplay);
}

/**
 * The app can inject window.__DAYUSE_NATIVE__ after the page scripts ran; it
 * calls this (window.syncDayuseAmplitudeContext) so events join its identity.
 */
export function syncAmplitudeIdentity() {
    const identity = handedOverIdentity();
    if (amplitude && identity.deviceId) amplitude.setDeviceId?.(identity.deviceId);
    if (amplitude && identity.sessionId) amplitude.setSessionId?.(identity.sessionId);
    return identity;
}

function currentDeviceId() {
    return cleanDeviceId(amplitude?.getDeviceId?.()) || handedOverIdentity().deviceId;
}

function currentSessionId() {
    return cleanSessionId(amplitude?.getSessionId?.()) ?? handedOverIdentity().sessionId;
}

/**
 * dayuse.com reads amp_device_id / amp_session_id before its own SDK starts,
 * which is what joins its checkout and purchase events to this conversation.
 */
export function appendAmplitudeIdToUrl(href) {
    try {
        const url = new URL(href);
        const deviceId = currentDeviceId();
        const sessionId = currentSessionId();
        if (deviceId) url.searchParams.set('amp_device_id', deviceId);
        else url.searchParams.delete('amp_device_id');
        if (sessionId) url.searchParams.set('amp_session_id', String(sessionId));
        else url.searchParams.delete('amp_session_id');
        return url.href;
    } catch (_e) {
        return href;
    }
}

// Common properties are read when the event reaches the SDK, not when it is
// queued: the app may inject __DAYUSE_NATIVE__ after the pageview fired.
function send(name, properties) {
    try {
        amplitude.track(name, { ...properties, ...commonProperties() });
    } catch (e) {
        console.error('Track error:', e);
    }
}

export function trackEvent(name, properties = {}) {
    if (amplitude) send(name, properties);
    else pendingEvents.push({ name, properties });
}

export function noteTurnTrace(turnId, traceId) {
    const turn = turnsById.get(turnId);
    if (turn && traceId) turn.traceId = String(traceId);
}

export function traceIdOfTurn(turnId) {
    return turnsById.get(turnId)?.traceId || null;
}

export function trackPageview() {
    const { href, pathname, search } = window.location;
    const referrer = document.referrer || '';
    trackEvent('pageview', {
        url: href,
        url_path: pathname,
        url_and_query_string: `${pathname}${search}`,
        referrer: referrer || NONE,
        referrer_domain: referrer ? hostnameOf(referrer) : NONE,
        page_type: 'ai_agent',
    });
}

export function trackMessageSent({ turnId, turnIndex, message, promptSource }) {
    turnsById.set(turnId, { turnIndex, traceId: null });
    const text = String(message ?? '');
    trackEvent('ai_agent__message_sent', {
        turn_id: turnId,
        turn_index: turnIndex,
        prompt: truncate(text),
        prompt_source: PROMPT_SOURCES.includes(promptSource) ? promptSource : 'typed',
        message_length: text.length,
    });
}

function responseTypeWithoutFacts(payload, hotelIds) {
    if (payload.requires_clarification) return 'clarification';
    return hotelIds.length > 0 ? 'results' : 'answer';
}

function stringList(value) {
    return Array.isArray(value) ? value.map(String) : [];
}

/** `payload` is the `done` frame or the JSON response of the turn. */
export function trackResponseReceived({ turnId, turnIndex, payload, latencyMs, ttftMs }) {
    const facts = payload?.turn_facts || {};
    const hotels = Array.isArray(payload?.hotels) ? payload.hotels : [];
    const hotelIds = payload?.requires_clarification
        ? []
        : hotels.map(hotel => toHotelId(hotel?.id ?? hotel?.hotel_id)).filter(Boolean);
    if (!turnsById.has(turnId)) turnsById.set(turnId, { turnIndex, traceId: null });
    noteTurnTrace(turnId, facts.trace_id);

    const responseType = stringOr(facts.response_type, responseTypeWithoutFacts(payload || {}, hotelIds));
    // The server echoes the last country anchor on FAQ/ack/details turns too.
    const searchRan = responseType === 'results' || Boolean(facts.resolved_city);

    const properties = {
        turn_id: turnId,
        turn_index: turnIndex,
        langfuse_trace_id: traceIdOfTurn(turnId) || NONE,
        response_type: responseType,
        results_count: Number.isInteger(facts.results_count) ? facts.results_count : hotelIds.length,
        hotel_ids: hotelIds,
        empty_reason: stringOr(facts.empty_reason, NONE),
        clarification_reason: stringOr(facts.clarification_reason, NONE),
        family: stringOr(facts.family, UNKNOWN),
        route: stringOr(facts.route, UNKNOWN),
        status: stringOr(facts.status, UNKNOWN),
        guards_fired: stringList(facts.guards_fired),
        fallbacks: stringList(facts.fallbacks),
        resolved_city: stringOr(facts.resolved_city, UNKNOWN),
        has_booking_card: Boolean(payload?.booking_card?.url),
        search_country: searchRan ? countryCode(payload?.search_country || payload?.active_filters?.country_code) : UNKNOWN,
        latency_ms: Math.round(latencyMs),
    };
    if (Number.isFinite(ttftMs)) properties.ttft_ms = Math.round(ttftMs);
    trackEvent('ai_agent__response_received', properties);
}

function failureOf(error) {
    if (Number.isInteger(error?.httpStatus)) return { error_type: 'http', http_status: error.httpStatus };
    if (error?.networkFailure) return { error_type: 'network' };
    return { error_type: 'client' };
}

export function trackResponseFailed({ turnId, turnIndex, error, traceId = null }) {
    trackEvent('ai_agent__response_failed', {
        turn_id: turnId,
        turn_index: turnIndex,
        ...(traceId ? { langfuse_trace_id: String(traceId) } : {}),
        ...failureOf(error),
    });
}

export function trackHotelClick({ turnId, hotelId, position, clickedElement }) {
    trackEvent('ai_agent__hotel_click', {
        ...turnReference(turnId),
        hotel_id: toHotelId(hotelId),
        position,
        clicked_element: clickedElement,
    });
}

export function trackBookingCardClick({ turnId, hotelId, ratePlanId }) {
    trackEvent('ai_agent__booking_card_click', {
        ...turnReference(turnId),
        hotel_id: toHotelId(hotelId),
        rate_plan_id: stringOr(ratePlanId, UNKNOWN),
    });
}

export function trackSuggestionClick({ turnId, suggestionType, position }) {
    trackEvent('ai_agent__suggestion_click', {
        ...(turnId ? { turn_id: turnId } : {}),
        suggestion_type: stringOr(suggestionType, UNKNOWN),
        position,
    });
}

export function trackFeedbackSubmit({ turnId, traceId, value }) {
    trackEvent('ai_agent__feedback_submit', {
        ...turnReference(turnId),
        langfuse_trace_id: stringOr(traceId, NONE),
        value,
    });
}

export function trackConversationReset() {
    trackEvent('ai_agent__conversation_reset', {});
}
