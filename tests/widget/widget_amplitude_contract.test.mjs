/**
 * Every event the widget sends to Amplitude matches `contracts/amplitude_events.json`.
 *
 * Run by `tests/test_market_table_drift.py::TestWidgetUrlContract` with every
 * other suite of this directory. Loads the REAL `tracking.js` against a fake
 * Amplitude SDK and the few browser globals it reads.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const CHAT = new URL('../../web/vendor/static/js/chat/', import.meta.url);
const CONTRACT = JSON.parse(
    readFileSync(new URL('../../contracts/amplitude_events.json', import.meta.url), 'utf8'),
);

const PROD_KEY = 'ba76a8f0fdbac6f02609480ab477de4f';
const DEV_KEY = '4490e59977a700c2c1651fde48670583';

function installBrowser(url, { native, referrer = '', agentVersion = 'abc1234' } = {}) {
    const page = new URL(url);
    globalThis.window = globalThis;
    globalThis.location = {
        href: page.href,
        origin: page.origin,
        hostname: page.hostname,
        pathname: page.pathname,
        search: page.search,
    };
    const metas = { 'agent-version': agentVersion };
    globalThis.document = {
        referrer,
        querySelector(selector) {
            const name = /meta\[name="([^"]+)"\]/.exec(selector)?.[1];
            return name && metas[name] != null ? { content: metas[name] } : null;
        },
    };
    if (native) globalThis.__DAYUSE_NATIVE__ = native;
    else delete globalThis.__DAYUSE_NATIVE__;
}

function fakeAmplitude() {
    return {
        sent: [],
        init(apiKey, userId, options) {
            this.initArgs = { apiKey, userId, options };
        },
        track(name, properties) {
            this.sent.push({ name, properties });
        },
        added: [],
        add(plugin) {
            this.added.push(plugin);
        },
        getDeviceId: () => 'device-123',
        getSessionId: () => 1760000000000,
    };
}

let loadCount = 0;
async function loadTracking(url, options = {}) {
    installBrowser(url, options);
    loadCount += 1;
    const tracking = await import(new URL(`tracking.js?load=${loadCount}`, CHAT));
    const sdk = fakeAmplitude();
    tracking.startAmplitude(sdk, options.replay);
    return { tracking, sdk };
}

function fakeReplay() {
    return {
        configs: [],
        plugin(config) {
            this.configs.push(config);
            return { name: 'session-replay', config };
        },
    };
}

function typeOf(value) {
    if (Array.isArray(value)) return 'array';
    if (Number.isInteger(value)) return 'integer';
    return typeof value;
}

function assertMatches(spec, value, where) {
    assert.equal(typeOf(value), spec.type, `${where}: type`);
    if (spec.enum) assert.ok(spec.enum.includes(value), `${where}: ${JSON.stringify(value)} not in enum`);
    if (spec.type === 'array') {
        for (const item of value) {
            assert.equal(typeOf(item), spec.items, `${where}: item ${JSON.stringify(item)}`);
        }
    }
}

function assertContractEvent({ name, properties }) {
    const event = CONTRACT.events[name];
    assert.ok(event, `${name} is not a contract event`);
    const allowed = { ...CONTRACT.common_properties, ...event.properties };
    for (const key of Object.keys(properties)) {
        assert.ok(key in allowed, `${name}.${key} is not in the contract`);
        assertMatches(allowed[key], properties[key], `${name}.${key}`);
    }
    for (const [key, spec] of Object.entries(allowed)) {
        if (!spec.optional) assert.ok(key in properties, `${name} misses ${key}`);
    }
}

const TURN_FACTS = {
    trace_id: null,
    family: 'search',
    route: 'leaf:hotel_search',
    status: 'ok',
    response_type: 'results',
    results_count: 2,
    empty_reason: 'none',
    clarification_reason: 'none',
    guards_fired: ['window_match'],
    fallbacks: [],
    resolved_city: null,
};

test('the Production key is used on ai.dayuse.{tld} only', async () => {
    const { tracking } = await loadTracking('https://ai.dayuse.com/');
    assert.equal(tracking.amplitudeApiKeyFor('ai.dayuse.com'), PROD_KEY);
    assert.equal(tracking.amplitudeApiKeyFor('ai.dayuse.fr'), PROD_KEY);
    assert.equal(tracking.amplitudeApiKeyFor('ai.dayuse.co.uk'), PROD_KEY);
    for (const host of [
        'www.dayuse.com', 'localhost', '127.0.0.1', 'widget-production.up.railway.app',
        'ai.dayuse.com.evil.io', 'preprod.ai.dayuse.com',
    ]) {
        assert.equal(tracking.amplitudeApiKeyFor(host), DEV_KEY, host);
    }
});

test('the SDK starts on the EU zone through the alitude proxy with the host key', async () => {
    const { sdk } = await loadTracking('https://ai.dayuse.fr/');
    assert.equal(sdk.initArgs.apiKey, PROD_KEY);
    assert.equal(sdk.initArgs.options.serverZone, 'EU');
    assert.equal(sdk.initArgs.options.serverUrl, 'https://alitude.dayuse.com/2/httpapi');
    const local = await loadTracking('http://localhost:8090/');
    assert.equal(local.sdk.initArgs.apiKey, DEV_KEY);
});

test('Session Replay samples the contract share, on the EU zone', async () => {
    const replay = fakeReplay();
    const { sdk } = await loadTracking('https://ai.dayuse.com/', { replay });
    assert.equal(CONTRACT.session_replay.sample_rate, 0.05);
    assert.equal(replay.configs.length, 1);
    assert.equal(replay.configs[0].sampleRate, CONTRACT.session_replay.sample_rate);
    assert.equal(replay.configs[0].serverZone, 'EU');
    assert.equal(replay.configs[0].configServerUrl, 'https://ai.dayuse.com/sr-config');
    assert.equal(sdk.added.length, 1);
});

test('a synthetic run never loads Session Replay', async () => {
    const replay = fakeReplay();
    const { sdk } = await loadTracking('https://ai.dayuse.com/?du_synthetic=1', { replay });
    assert.equal(replay.configs.length, 0);
    assert.equal(sdk.added.length, 0);
});

test('a Session Replay failure never stops tracking', async () => {
    const replay = { plugin() { throw new Error('boom'); } };
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/', { replay });
    assert.equal(sdk.initArgs.apiKey, PROD_KEY);
    tracking.trackConversationReset();
    assert.equal(sdk.sent.length, 1);
});

test('without a Session Replay plugin the SDK still starts', async () => {
    const { sdk } = await loadTracking('https://ai.dayuse.com/');
    assert.equal(sdk.added.length, 0);
    assert.equal(sdk.initArgs.apiKey, PROD_KEY);
});

test('the market is "unknown" until the app, the deep link or the server gives one', async () => {
    const state = (await import(new URL('state.js', CHAT))).state;
    state.knownMarket = null;
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    tracking.trackConversationReset();
    assert.equal(sdk.sent[0].properties.market_country, 'unknown');
    assertContractEvent(sdk.sent[0]);
    state.knownMarket = 'FR';
    tracking.trackConversationReset();
    assert.equal(sdk.sent[1].properties.market_country, 'FR');
    state.knownMarket = null;

    const app = await loadTracking('https://ai.dayuse.com/', { native: { market_country: 'gb' } });
    app.tracking.trackConversationReset();
    assert.equal(app.sdk.sent[0].properties.market_country, 'GB');
    const link = await loadTracking('https://ai.dayuse.com/?market_country=es');
    link.tracking.trackConversationReset();
    assert.equal(link.sdk.sent[0].properties.market_country, 'ES');
});

test('the app identity is handed to the SDK, the URL identity otherwise', async () => {
    const app = await loadTracking('https://ai.dayuse.com/?amp_device_id=url-dev&amp_session_id=111', {
        native: { amp_device_id: 'native-dev', amp_session_id: '1760000000999', app_platform: 'ios' },
    });
    assert.equal(app.sdk.initArgs.options.deviceId, 'native-dev');
    assert.equal(app.sdk.initArgs.options.sessionId, 1760000000999);
    const web = await loadTracking('https://ai.dayuse.com/?amp_device_id=url-dev&amp_session_id=111');
    assert.equal(web.sdk.initArgs.options.deviceId, 'url-dev');
    assert.equal(web.sdk.initArgs.options.sessionId, 111);
});

test('events queued before the SDK loads are sent once it starts', async () => {
    installBrowser('https://ai.dayuse.com/');
    const tracking = await import(new URL('tracking.js?load=queued', CHAT));
    tracking.trackPageview();
    const sdk = fakeAmplitude();
    tracking.startAmplitude(sdk);
    assert.deepEqual(sdk.sent.map(e => e.name), ['pageview']);
});

test('a pageview queued before the app injects its context is sent as an app event', async () => {
    installBrowser('https://ai.dayuse.com/');
    const tracking = await import(new URL('tracking.js?load=late-native', CHAT));
    tracking.trackPageview();
    globalThis.__DAYUSE_NATIVE__ = { amp_device_id: 'app-dev', amp_session_id: '1760000000555', app_platform: 'ios' };
    const sdk = fakeAmplitude();
    tracking.startAmplitude(sdk);
    delete globalThis.__DAYUSE_NATIVE__;
    const [pageview] = sdk.sent;
    assertContractEvent(pageview);
    assert.equal(pageview.properties.tracking_surface, 'mobile_app');
    assert.equal(pageview.properties.app_platform, 'ios');
    assert.equal(pageview.properties.entry_source, 'app');
    assert.equal(sdk.initArgs.options.deviceId, 'app-dev');
    assert.equal(sdk.initArgs.options.sessionId, 1760000000555);
});

test('pageview carries the page and its referrer', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/chat?du_entry_source=banner_home', {
        referrer: 'https://www.dayuse.com/fr/',
    });
    tracking.trackPageview();
    const [event] = sdk.sent;
    assertContractEvent(event);
    assert.equal(event.properties.url, 'https://ai.dayuse.com/chat?du_entry_source=banner_home');
    assert.equal(event.properties.url_path, '/chat');
    assert.equal(event.properties.url_and_query_string, '/chat?du_entry_source=banner_home');
    assert.equal(event.properties.referrer, 'https://www.dayuse.com/fr/');
    assert.equal(event.properties.referrer_domain, 'www.dayuse.com');
    assert.equal(event.properties.page_type, 'ai_agent');
    assert.equal(event.properties.entry_source, 'banner_home');
    assert.equal(event.properties.domain, 'ai.dayuse.com');
    assert.equal(event.properties.agent_version, 'abc1234');
});

test('an empty referrer is "none"', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    tracking.trackPageview();
    assert.equal(sdk.sent[0].properties.referrer, 'none');
    assert.equal(sdk.sent[0].properties.referrer_domain, 'none');
});

test('common properties on the web: direct entry, no app platform, unknown agent version', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/', { agentVersion: null });
    tracking.trackConversationReset();
    const [event] = sdk.sent;
    assertContractEvent(event);
    const props = event.properties;
    assert.equal(props.tracking_surface, 'web');
    assert.equal(props.app_platform, 'none');
    assert.equal(props.entry_source, 'direct');
    assert.equal(props.agent_version, 'unknown');
    assert.equal(props.is_synthetic, false);
    assert.match(props.dayuse_event_id, /^[0-9a-f-]{36}$/);
    assert.match(props.conversation_id, /^[0-9a-f-]{36}$/);
});

test('every event gets its own dayuse_event_id', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    tracking.trackConversationReset();
    tracking.trackConversationReset();
    assert.notEqual(sdk.sent[0].properties.dayuse_event_id, sdk.sent[1].properties.dayuse_event_id);
});

test('without crypto.randomUUID (insecure context, old WebView) events still get a UUID v4', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    const realCrypto = globalThis.crypto;
    Object.defineProperty(globalThis, 'crypto', {
        value: { getRandomValues: bytes => realCrypto.getRandomValues(bytes) },
        configurable: true,
    });
    try {
        tracking.trackConversationReset();
    } finally {
        Object.defineProperty(globalThis, 'crypto', { value: realCrypto, configurable: true });
    }
    assert.equal(sdk.sent.length, 1);
    assert.match(
        sdk.sent[0].properties.dayuse_event_id,
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
});

test('inside the app: mobile_app surface, the app platform and the app entry', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/', {
        native: { amp_device_id: 'd', app_platform: 'android' },
    });
    tracking.trackConversationReset();
    const props = sdk.sent[0].properties;
    assertContractEvent(sdk.sent[0]);
    assert.equal(props.tracking_surface, 'mobile_app');
    assert.equal(props.app_platform, 'android');
    assert.equal(props.entry_source, 'app');
});

test('a deep link with q is a deeplink entry; an unknown du_entry_source is ignored', async () => {
    const deeplink = await loadTracking('https://ai.dayuse.com/?q=spa+paris&source=dayuse_box');
    deeplink.tracking.trackConversationReset();
    assert.equal(deeplink.sdk.sent[0].properties.entry_source, 'deeplink');
    const bogus = await loadTracking('https://ai.dayuse.com/?du_entry_source=newsletter');
    bogus.tracking.trackConversationReset();
    assert.equal(bogus.sdk.sent[0].properties.entry_source, 'direct');
});

test('?du_synthetic=1 marks every event synthetic', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/?du_synthetic=1');
    tracking.trackPageview();
    tracking.trackConversationReset();
    assert.ok(sdk.sent.every(e => e.properties.is_synthetic === true));
    assert.equal(tracking.isSyntheticRun(), true);
});

test('message_sent truncates the prompt to 500 and counts the full message', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    const message = 'x'.repeat(700);
    tracking.trackMessageSent({ turnId: 'cs_t1', turnIndex: 1, message, promptSource: 'typed' });
    const [event] = sdk.sent;
    assertContractEvent(event);
    assert.equal(event.properties.prompt.length, 500);
    assert.equal(event.properties.message_length, 700);
    assert.equal(event.properties.turn_id, 'cs_t1');
    assert.equal(event.properties.turn_index, 1);
    assert.equal(event.properties.prompt_source, 'typed');
});

test('message_sent keeps the prompt source of a button and refuses an unknown one', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    tracking.trackMessageSent({ turnId: 't1', turnIndex: 1, message: 'a', promptSource: 'initial_prompt' });
    tracking.trackMessageSent({ turnId: 't2', turnIndex: 2, message: 'b', promptSource: 'hotel_pick' });
    tracking.trackMessageSent({ turnId: 't3', turnIndex: 3, message: 'c', promptSource: 'voice' });
    assert.deepEqual(
        sdk.sent.map(e => e.properties.prompt_source),
        ['initial_prompt', 'typed', 'typed'],
    );
});

test('response_received copies turn_facts; a null trace is "none", a null city "unknown"', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    tracking.trackResponseReceived({
        turnId: 't1',
        turnIndex: 1,
        payload: {
            turn_facts: TURN_FACTS,
            hotels: [{ id: 42 }, { hotel_id: '7' }],
            search_country: 'FR',
            booking_card: null,
        },
        latencyMs: 5400,
        ttftMs: 180,
    });
    const [event] = sdk.sent;
    assertContractEvent(event);
    const props = event.properties;
    assert.equal(props.langfuse_trace_id, 'none');
    assert.equal(props.resolved_city, 'unknown');
    assert.equal(props.family, 'search');
    assert.equal(props.route, 'leaf:hotel_search');
    assert.equal(props.status, 'ok');
    assert.equal(props.response_type, 'results');
    assert.equal(props.results_count, 2);
    assert.deepEqual(props.guards_fired, ['window_match']);
    assert.deepEqual(props.fallbacks, []);
    assert.deepEqual(props.hotel_ids, [42, 7]);
    assert.equal(props.has_booking_card, false);
    assert.equal(props.search_country, 'FR');
    assert.equal(props.latency_ms, 5400);
    assert.equal(props.ttft_ms, 180);
});

test('response_received on the JSON transport has no ttft_ms and keeps a real trace', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    const traceId = 'a'.repeat(32);
    tracking.trackResponseReceived({
        turnId: 't1',
        turnIndex: 1,
        payload: {
            turn_facts: { ...TURN_FACTS, trace_id: traceId, resolved_city: 'Paris' },
            hotels: [],
            booking_card: { url: 'https://www.dayuse.com/checkout', hotel_id: 9 },
        },
        latencyMs: 3000,
        ttftMs: null,
    });
    const props = sdk.sent[0].properties;
    assertContractEvent(sdk.sent[0]);
    assert.ok(!('ttft_ms' in props));
    assert.equal(props.langfuse_trace_id, traceId);
    assert.equal(props.resolved_city, 'Paris');
    assert.equal(props.has_booking_card, true);
    assert.equal(props.search_country, 'unknown');
    assert.equal(tracking.traceIdOfTurn('t1'), traceId);
});

test('search_country is the searched country only on a turn that ran a search', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    const answerFacts = { ...TURN_FACTS, family: 'faq', response_type: 'answer', results_count: 0 };
    const turn = (turnId, facts) => tracking.trackResponseReceived({
        turnId, turnIndex: 1, payload: { turn_facts: facts, hotels: [], search_country: 'FR' }, latencyMs: 1,
    });
    turn('faq', answerFacts);
    turn('empty-search', { ...answerFacts, family: 'search', empty_reason: 'no_offers', resolved_city: 'Lyon' });
    turn('results', TURN_FACTS);
    sdk.sent.forEach(assertContractEvent);
    assert.deepEqual(sdk.sent.map(e => e.properties.search_country), ['unknown', 'FR', 'FR']);
});

test('response_received without turn_facts (older server) does not throw', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    tracking.trackResponseReceived({
        turnId: 't1', turnIndex: 1, payload: { hotels: [{ id: 3 }] }, latencyMs: 10, ttftMs: null,
    });
    const props = sdk.sent[0].properties;
    assert.equal(props.langfuse_trace_id, 'none');
    assert.equal(props.response_type, 'results');
    assert.equal(props.results_count, 1);
    assert.equal(props.family, 'unknown');
    assert.equal(props.route, 'unknown');
    assert.equal(props.status, 'unknown');
    assert.equal(props.empty_reason, 'none');
    assert.equal(props.clarification_reason, 'none');
    assert.deepEqual(props.guards_fired, []);
    assert.deepEqual(props.fallbacks, []);
    assert.equal(props.resolved_city, 'unknown');
});

async function rejectionOf(promise) {
    try {
        await promise;
    } catch (error) {
        return error;
    }
    assert.fail('expected a rejection');
}

test('response_failed: an HTTP status is http, a widget exception is client', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    const httpError = Object.assign(new Error('HTTP 502'), { httpStatus: 502 });
    tracking.trackResponseFailed({ turnId: 't1', turnIndex: 1, error: httpError, traceId: 'b'.repeat(32) });
    tracking.trackResponseFailed({ turnId: 't2', turnIndex: 2, error: new SyntaxError('Unexpected token <') });
    tracking.trackResponseFailed({ turnId: 't3', turnIndex: 3, error: new TypeError('x is undefined') });
    sdk.sent.forEach(assertContractEvent);
    const [http, badJson, renderBug] = sdk.sent.map(e => e.properties);
    assert.equal(http.error_type, 'http');
    assert.equal(http.http_status, 502);
    assert.equal(http.langfuse_trace_id, 'b'.repeat(32));
    assert.equal(badJson.error_type, 'client');
    assert.ok(!('http_status' in badJson));
    assert.ok(!('langfuse_trace_id' in badJson));
    assert.equal(renderBug.error_type, 'client');
});

test('response_failed: a failure of fetch or of the stream reader is network', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    const stream = await import(new URL('stream.js', CHAT));
    const realFetch = globalThis.fetch;
    globalThis.fetch = () => Promise.reject(Object.assign(new Error('t'), { name: 'TimeoutError' }));
    let fetchFailure;
    try {
        fetchFailure = await rejectionOf(stream.openChatStream('/v3/chat/stream', {}, {}));
    } finally {
        globalThis.fetch = realFetch;
    }
    const droppedStream = { body: { getReader: () => ({
        read: () => Promise.reject(new TypeError('network error')),
        cancel: () => Promise.resolve(),
    }) } };
    const readerFailure = await rejectionOf(stream.readSseFrames(droppedStream).next());
    const postFailure = stream.asNetworkFailure(new TypeError('Failed to fetch'));
    for (const [index, error] of [fetchFailure, readerFailure, postFailure].entries()) {
        tracking.trackResponseFailed({ turnId: `t${index}`, turnIndex: index + 1, error });
    }
    sdk.sent.forEach(assertContractEvent);
    assert.deepEqual(sdk.sent.map(e => e.properties.error_type), ['network', 'network', 'network']);
});

test('card clicks carry the turn that rendered them, with its trace', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    const traceId = 'c'.repeat(32);
    tracking.trackMessageSent({ turnId: 't2', turnIndex: 2, message: 'spa', promptSource: 'typed' });
    tracking.noteTurnTrace('t2', traceId);
    tracking.trackHotelClick({ turnId: 't2', hotelId: '42', position: 3, clickedElement: 'card_cta' });
    tracking.trackBookingCardClick({ turnId: 't2', hotelId: '42', ratePlanId: 'uuid-1' });
    tracking.trackBookingCardClick({ turnId: 't9', hotelId: '42', ratePlanId: '' });
    const [, hotel, booking, orphan] = sdk.sent;
    [hotel, booking, orphan].forEach(assertContractEvent);
    assert.deepEqual(
        [hotel.properties.turn_id, hotel.properties.turn_index, hotel.properties.langfuse_trace_id],
        ['t2', 2, traceId],
    );
    assert.equal(hotel.properties.hotel_id, 42);
    assert.equal(hotel.properties.position, 3);
    assert.equal(hotel.name, 'ai_agent__hotel_click');
    assert.equal(hotel.properties.clicked_element, 'card_cta');
    assert.equal(booking.properties.rate_plan_id, 'uuid-1');
    assert.equal(booking.properties.langfuse_trace_id, traceId);
    assert.equal(orphan.properties.rate_plan_id, 'unknown');
    assert.equal(orphan.properties.langfuse_trace_id, 'none');
});

test('suggestion_click omits turn_id for chips shown before any turn', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    tracking.trackSuggestionClick({ suggestionType: 'search_example', position: 2 });
    tracking.trackSuggestionClick({ turnId: 't1', suggestionType: 'recovery', position: 1 });
    sdk.sent.forEach(assertContractEvent);
    assert.ok(!('turn_id' in sdk.sent[0].properties));
    assert.equal(sdk.sent[1].properties.turn_id, 't1');
});

test('feedback_submit maps the thumb and carries no comment', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    tracking.trackMessageSent({ turnId: 't1', turnIndex: 1, message: 'a', promptSource: 'typed' });
    const traceId = 'd'.repeat(32);
    tracking.noteTurnTrace('t1', traceId);
    tracking.trackFeedbackSubmit({ turnId: 't1', traceId, value: 'down', comment: 'ignored' });
    tracking.trackFeedbackSubmit({ turnId: 't1', traceId, value: 'up' });
    const [, down, up] = sdk.sent;
    [down, up].forEach(assertContractEvent);
    assert.equal(down.properties.value, 'down');
    assert.ok(!('comment' in down.properties));
    assert.equal(down.properties.turn_index, 1);
    assert.equal(down.properties.langfuse_trace_id, 'd'.repeat(32));
    assert.ok(!('comment' in up.properties));
});

test('feedback_submit carries the trace the Langfuse score was posted to', async () => {
    const { tracking, sdk } = await loadTracking('https://ai.dayuse.com/');
    tracking.trackMessageSent({ turnId: 't1', turnIndex: 1, message: 'a', promptSource: 'typed' });
    tracking.noteTurnTrace('t1', 'd'.repeat(32));
    tracking.trackFeedbackSubmit({ turnId: 't1', traceId: 'e'.repeat(32), value: 'up' });
    const feedback = sdk.sent[1];
    assertContractEvent(feedback);
    assert.equal(feedback.properties.langfuse_trace_id, 'e'.repeat(32));
    assert.equal(feedback.properties.turn_index, 1);
});

function unescapeAttr(value) {
    return value.replaceAll('&amp;', '&').replaceAll('&quot;', '"');
}

test('every rate-plan row of a booking card links with the Amplitude ids', async () => {
    installBrowser('https://ai.dayuse.com/');
    const tracking = await import(new URL('tracking.js', CHAT));
    tracking.startAmplitude(fakeAmplitude());
    const { createBookingCard } = await import(new URL('ui/messages.js', CHAT));
    const html = createBookingCard({
        hotel_name: 'Hotel X',
        hotel_id: 7,
        url: 'https://www.dayuse.com/checkout?offer=a',
        rate_plans: [
            { offer_id: 'a', url: 'https://www.dayuse.com/checkout?offer=a', selected: true, name: 'Pool', start_time: '10:00', end_time: '15:00' },
            { offer_id: 'b', url: 'https://www.dayuse.com/checkout?offer=b', name: 'Spa', start_time: '12:00', end_time: '17:00' },
        ],
    });
    const planUrls = [...html.matchAll(/data-plan-url="([^"]*)"/g)].map(m => new URL(unescapeAttr(m[1])));
    assert.equal(planUrls.length, 2);
    for (const url of planUrls) {
        assert.equal(url.searchParams.get('amp_device_id'), 'device-123');
        assert.equal(url.searchParams.get('amp_session_id'), '1760000000000');
        assert.ok(url.searchParams.get('offer'));
    }
});

test('outgoing dayuse links carry the Amplitude device and session ids only', async () => {
    const { tracking } = await loadTracking('https://ai.dayuse.com/');
    const stamped = new URL(tracking.appendAmplitudeIdToUrl('https://www.dayuse.com/hotels/fr/x?utm_source=old'));
    assert.equal(stamped.searchParams.get('amp_device_id'), 'device-123');
    assert.equal(stamped.searchParams.get('amp_session_id'), '1760000000000');
    assert.deepEqual(
        [...stamped.searchParams.keys()].sort(),
        ['amp_device_id', 'amp_session_id', 'utm_source'],
    );
});

test('/v3 calls carry X-Dayuse-Synthetic only on a synthetic run', async () => {
    installBrowser('https://ai.dayuse.com/?du_synthetic=1');
    const api = await import(new URL('api.js', CHAT));
    assert.equal(api.getChatHeaders()['X-Dayuse-Synthetic'], '1');
    globalThis.location.search = '';
    assert.ok(!('X-Dayuse-Synthetic' in api.getChatHeaders()));
});
