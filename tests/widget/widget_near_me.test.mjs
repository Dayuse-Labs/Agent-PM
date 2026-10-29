/**
 * 2026-10-28: the « près de moi » chip is back (agent-usa's first entry, 489
 * conversations from September to the switch, 9 in 10 with results; none on
 * AgentB2C since). Its click — on the web hero, or on the app's welcome chip
 * named by `/v3/chat/welcome` — asks for the device's position with the
 * message: the app's own fix first, else the browser's; without one, the
 * backend is told so and says it.
 *
 * Run by `tests/test_market_table_drift.py::TestWidgetUrlContract` with every
 * other suite of this directory.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const CHAT = new URL('../../web/vendor/static/js/chat/', import.meta.url);

globalThis.window = globalThis;
globalThis.addEventListener = globalThis.addEventListener || (() => {});
globalThis.location = { href: 'https://ai.dayuse.com/?locale=fr&currency=EUR',
    origin: 'https://ai.dayuse.com', hostname: 'ai.dayuse.com', pathname: '/', search: '' };
const nodes = {};
globalThis.document = {
    referrer: '',
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: (id) => nodes[id] || null,
    addEventListener: () => {},
    createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, setAttribute() {}, appendChild() {} }),
    body: { classList: { add() {}, remove() {}, toggle() {} }, style: {} },
    documentElement: { style: { setProperty() {} }, classList: { add() {}, remove() {}, toggle() {} } },
};

const { state } = await import(new URL('state.js', CHAT));
const { suggestionsInlineHtml } = await import(new URL('filters/chips.js', CHAT));
const { getBrowserGeoContext } = await import(new URL('handlers/send.js', CHAT));
const i18n = readFileSync(new URL('i18n.js', CHAT), 'utf8');
const hero = readFileSync(new URL('../../../templates/chat_clean.html', CHAT), 'utf8');

function setNavigator(value) {
    Object.defineProperty(globalThis, 'navigator', { value, configurable: true, writable: true });
}

function browser(outcome) {
    setNavigator({
        geolocation: {
            getCurrentPosition: (ok, ko) => (outcome === 'granted'
                ? ok({ coords: { latitude: 41.39, longitude: 2.16, accuracy: 30 } })
                : ko({ code: outcome === 'denied' ? 1 : 2 })),
        },
    });
}

test('the welcome chip named near_me is the one marked, and only it', () => {
    const html = suggestionsInlineHtml(['Chambre en journée à Lyon', 'Chambre en journée près de moi'],
        'welcome', 'Chambre en journée près de moi');
    assert.equal((html.match(/data-near-me="1"/g) || []).length, 1);
    assert.match(html, /data-near-me="1" data-suggestion="Chambre en journée près de moi"/);
    // Tracked as its own kind, the city chip stays `welcome` (review of #173).
    assert.match(html, /data-suggestion-type="near_me"[^>]*data-near-me="1"/);
    assert.match(html, /data-suggestion-type="welcome"[^>]*data-suggestion="Chambre en journée à Lyon"/);
    assert.doesNotMatch(suggestionsInlineHtml(['Demain'], 'recovery'), /data-near-me/);
});

test('the chip asks the browser, whatever its words', async () => {
    browser('granted');
    window.__DAYUSE_NATIVE__ = undefined;
    state.requestDeviceLocation = true;
    const ctx = await getBrowserGeoContext('Quarto de dia perto de mim');
    assert.deepEqual(ctx, { device: { latitude: 41.39, longitude: 2.16, accuracy_m: 30, permission: 'granted' } });
    assert.equal(state.requestDeviceLocation, false, 'one-shot');
});

test("the app's own fix comes first", async () => {
    browser('denied');
    window.__DAYUSE_NATIVE__ = { geolocation: { lat: 48.86, lon: 2.35 } };
    state.requestDeviceLocation = true;
    assert.deepEqual(await getBrowserGeoContext('Day room near me'),
        { device: { latitude: 48.86, longitude: 2.35, permission: 'granted' } });
    window.__DAYUSE_NATIVE__ = undefined;
});

test('a refusal is sent as such, so the backend can say it', async () => {
    browser('denied');
    state.requestDeviceLocation = true;
    assert.deepEqual(await getBrowserGeoContext('Chambre en journée près de moi'),
        { device: { permission: 'denied' } });
    setNavigator({});
    state.requestDeviceLocation = true;
    assert.deepEqual(await getBrowserGeoContext('Chambre en journée près de moi'),
        { device: { permission: 'unavailable' } });
});

test('without the chip, an ordinary message asks nothing', async () => {
    browser('granted');
    state.requestDeviceLocation = false;
    assert.equal(await getBrowserGeoContext('Un hôtel à Lyon demain'), null);
});

test('the hero carries the chip and the seven languages label it', () => {
    assert.match(hero, /data-action="near-me" id="search-example-near-me"/);
    assert.equal((i18n.match(/near_me_chip: '/g) || []).length, 7);
});

test('the hero chip is tracked as near_me at its 1-based place', () => {
    const index = readFileSync(new URL('index.js', CHAT), 'utf8');
    assert.match(index, /suggestionType: 'near_me', position: 1 /);
    assert.doesNotMatch(index, /position: 0/);
});

test('2026-10-29: the place question names its « près de moi » chip through the payload', async () => {
    const { normalizeV3Response } = await import(new URL('handlers/send.js', CHAT));
    // A results payload is whitelisted field by field: `near_me` must survive it.
    const withHotels = normalizeV3Response({
        hotels: [{ hotel_id: 1, name: 'Hôtel A' }], suggestions: ['Demain'], near_me: null,
    });
    assert.equal(withHotels.near_me, null);
    const question = normalizeV3Response({
        message: 'Dans quelle ville cherchez-vous ?', hotels: null,
        suggestions: ['Près de moi', 'Paris'], near_me: 'Près de moi',
    });
    assert.equal(question.near_me, 'Près de moi');
    const html = suggestionsInlineHtml(question.suggestions, 'recovery', question.near_me);
    assert.match(html, /data-suggestion-type="near_me"[^>]*data-near-me="1" data-suggestion="Près de moi"/);
    assert.match(html, /data-suggestion-type="recovery"[^>]*data-suggestion="Paris"/);
    // The row renderer hands the label over.
    const responses = readFileSync(new URL('handlers/responses.js', CHAT), 'utf8');
    assert.match(responses, /suggestionsInlineHtml\(raw, 'recovery', nearMe\)/);
});
