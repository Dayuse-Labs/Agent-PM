/**
 * Q02: a card's time slot follows the language of the conversation, by the
 * site's rule (en 10am / zh-HK, zh-SG 10:00 / others 10h, 10h30).
 * Pure module, no DOM: runs in bare node.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

const CHAT = new URL('../../web/vendor/static/js/chat/', import.meta.url);
const { formatSlotTime, formatSlotRange } = await import(new URL('slot_time.js', CHAT));

test('fr: 10h - 16h, 10h30', () => {
    assert.equal(formatSlotRange('10:00', '16:00', 'fr'), '10h – 16h');
    assert.equal(formatSlotTime('10:30', 'fr'), '10h30');
});

test('en: 10am - 4pm, 4:30pm, midnight and noon', () => {
    assert.equal(formatSlotRange('10:00', '16:00', 'en'), '10am – 4pm');
    assert.equal(formatSlotTime('16:30', 'en'), '4:30pm');
    assert.equal(formatSlotTime('00:00', 'en'), '12am');
    assert.equal(formatSlotTime('12:00', 'en'), '12pm');
});

test('zh-HK and zh-SG: 10:00', () => {
    assert.equal(formatSlotTime('10:00', 'zh-HK'), '10:00');
    assert.equal(formatSlotTime('9:05', 'zh-SG'), '09:05');
});

test('another language (de, es): hour-h format', () => {
    assert.equal(formatSlotRange('10:00', '16:30', 'de'), '10h – 16h30');
    assert.equal(formatSlotTime('08:00', 'es'), '8h');
});

test('empty input gives an empty string', () => {
    assert.equal(formatSlotTime('', 'fr'), '');
});
