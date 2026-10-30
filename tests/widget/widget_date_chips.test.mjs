/**
 * 2026-10-30: the day chips under next-day cards. The backend sends them in
 * `suggestions`, in order, and their kind in `suggestion_types` ({label: kind}):
 * « Ce soir quand même (3,9 km) » (date_tonight), « Après-demain » (date_day),
 * « Pas de date précise » (date_flexible). The widget renders them in that
 * order, tracks each click with its own `suggestion_type`, and sends the label
 * as the message (the backend recognizes the chip it offered).
 *
 * Run by `tests/test_market_table_drift.py::TestWidgetUrlContract` with every
 * other suite of this directory.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const CHAT = new URL('../../web/vendor/static/js/chat/', import.meta.url);
const CONTRACT = JSON.parse(
    readFileSync(new URL('../../contracts/amplitude_events.json', import.meta.url), 'utf8'),
);

globalThis.window = globalThis;
globalThis.addEventListener = globalThis.addEventListener || (() => {});
globalThis.location = { href: 'http://localhost:8090/?locale=fr&currency=EUR',
    origin: 'http://localhost:8090', hostname: 'localhost', pathname: '/', search: '?locale=fr&currency=EUR' };
const input = { value: '' };
globalThis.document = {
    referrer: '',
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: (id) => (id === 'user-input' ? input : null),
    addEventListener: () => {},
    createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, setAttribute() {}, appendChild() {} }),
    body: { classList: { add() {}, remove() {}, toggle() {} }, style: {} },
    documentElement: { style: { setProperty() {} }, classList: { add() {}, remove() {}, toggle() {} } },
};

const tracking = await import(new URL('tracking.js', CHAT));
const { suggestionsInlineHtml, applySuggestion } = await import(new URL('filters/chips.js', CHAT));
const { normalizeV3Response } = await import(new URL('handlers/send.js', CHAT));

const sdk = {
    sent: [],
    init() {},
    add() {},
    track(name, properties) { this.sent.push({ name, properties }); },
    getDeviceId: () => 'device-1',
    getSessionId: () => 1760000000000,
};
tracking.startAmplitude(sdk);

const CLOSER = {
    message: "Ce soir, l'offre encore ouverte la plus proche est à 3,9 km : voici celles du samedi 31 octobre 2026, plus près.",
    hotels: [{ hotel_id: 5, name: 'The Westin Grand Munich' }],
    suggestions: ['Ce soir quand même (3,9 km)', 'Après-demain', 'Pas de date précise'],
    suggestion_types: {
        'Ce soir quand même (3,9 km)': 'date_tonight',
        'Après-demain': 'date_day',
        'Pas de date précise': 'date_flexible',
    },
    near_me: null,
};

function chips(html) {
    return [...html.matchAll(/data-suggestion-type="([^"]+)"[^>]*data-suggestion="([^"]+)">([^<]+)</g)]
        .map(([, type, label, text]) => ({ type, label, text }));
}

test('a results payload keeps the chip kinds through normalization', () => {
    const data = normalizeV3Response(CLOSER);
    assert.deepEqual(data.suggestions, CLOSER.suggestions);
    assert.deepEqual(data.suggestion_types, CLOSER.suggestion_types);
});

test('the three day chips render in order, each with its own kind', () => {
    const data = normalizeV3Response(CLOSER);
    const html = suggestionsInlineHtml(data.suggestions, 'recovery', data.near_me, data.suggestion_types);
    assert.deepEqual(chips(html), [
        { type: 'date_tonight', label: 'Ce soir quand même (3,9 km)', text: 'Ce soir quand même (3,9 km)' },
        { type: 'date_day', label: 'Après-demain', text: 'Après-demain' },
        { type: 'date_flexible', label: 'Pas de date précise', text: 'Pas de date précise' },
    ]);
});

test('today closed: two chips, never today', () => {
    const html = suggestionsInlineHtml(['Après-demain', 'Pas de date précise'], 'recovery', null,
        { 'Après-demain': 'date_day', 'Pas de date précise': 'date_flexible' });
    assert.deepEqual(chips(html).map((c) => c.text), ['Après-demain', 'Pas de date précise']);
    assert.doesNotMatch(html, /Aujourd/);
});

test('an untyped chip stays recovery, and a malformed kind is never written', () => {
    const html = suggestionsInlineHtml(['élargir la zone', 'Demain'], 'recovery', null,
        { Demain: 'date_day" onclick="x', 'élargir la zone': 42 });
    assert.deepEqual(chips(html).map((c) => c.type), ['recovery', 'recovery']);
    assert.doesNotMatch(html, /onclick/);
    // No kinds at all (an older backend): unchanged.
    assert.deepEqual(chips(suggestionsInlineHtml(['Demain'], 'recovery')).map((c) => c.type), ['recovery']);
});

test('a click is tracked with its kind and 1-based place, and sends the label', () => {
    const html = suggestionsInlineHtml(CLOSER.suggestions, 'recovery', null, CLOSER.suggestion_types);
    const rendered = chips(html);
    const buttons = rendered.map(({ type, label }) => ({
        dataset: { suggestion: label, suggestionType: type, turnId: 's_t2' },
    }));
    const row = { querySelectorAll: () => buttons };
    buttons.forEach((b) => { b.parentElement = row; });
    const sent = [];
    window.chatApp = { sendMessage: (source) => sent.push({ source, message: input.value }) };

    sdk.sent.length = 0;
    applySuggestion(buttons[0]);
    applySuggestion(buttons[2]);

    const clicks = sdk.sent.filter((e) => e.name === 'ai_agent__suggestion_click');
    assert.deepEqual(clicks.map((e) => [e.properties.suggestion_type, e.properties.position]),
        [['date_tonight', 1], ['date_flexible', 3]]);
    assert.ok(clicks.every((e) => e.properties.turn_id === 's_t2'));
    assert.deepEqual(sent, [
        { source: 'suggestion', message: 'Ce soir quand même (3,9 km)' },
        { source: 'suggestion', message: 'Pas de date précise' },
    ]);
});

test('the contract names the three day kinds, added to the open suggestion_type', () => {
    const description = CONTRACT.events.ai_agent__suggestion_click.properties.suggestion_type.description;
    for (const kind of ['date_tonight', 'date_day', 'date_flexible']) assert.match(description, new RegExp(kind));
    // Still the kinds it named before (never renamed).
    for (const kind of ['search_example', 'welcome', 'recovery', 'near_me']) assert.match(description, new RegExp(kind));
});

test('the filter path hands the kinds to the chip row too', () => {
    const search = readFileSync(new URL('filters/search.js', CHAT), 'utf8');
    assert.match(search, /suggestion_types: rawData\.suggestion_types/);
});
