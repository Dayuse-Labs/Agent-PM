/**
 * E (2026-10-27): the mobile app's welcome call carries the page's market, so
 * the greeting served by `/v3/chat/welcome` speaks the visitor's language.
 *
 * Run by `tests/test_market_table_drift.py::TestWidgetUrlContract` with every
 * other suite of this directory.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

const CHAT = new URL('../../web/vendor/static/js/chat/', import.meta.url);

globalThis.window = globalThis;
globalThis.location = { href: 'https://ai.dayuse.com/?source=mobile_app&locale=fr&currency=EUR',
    origin: 'https://ai.dayuse.com', hostname: 'ai.dayuse.com', pathname: '/', search: '' };
globalThis.document = { referrer: '', querySelector: () => null };

const { state } = await import(new URL('state.js', CHAT));
const api = await import(new URL('api.js', CHAT));

test('the welcome body carries the native context and the market', () => {
    state.marketContext = { ...state.marketContext, language: 'fr', currency: 'EUR' };
    const native = { lastBookings: [{ hotelCity: 'Lyon' }] };
    assert.deepEqual(api.welcomeRequestBody(native), {
        native_context: native, locale: 'fr', currency: 'EUR',
    });
});

test('the welcome endpoint is derived from the chat endpoint', () => {
    assert.equal(api.getWelcomeEndpoint(), '/v3/chat/welcome');
});
