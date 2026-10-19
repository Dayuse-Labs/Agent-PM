import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// card.js pulls DOM-bound modules, so the pure helper is evaluated from its source.
const src = readFileSync(new URL('../../web/vendor/static/js/chat/hotels/card.js', import.meta.url), 'utf8');
const body = /export function humanizeZone[\s\S]*?\n}\n/.exec(src)[0].replace('export ', '');
const humanizeZone = new Function(`${body}; return humanizeZone;`)();

test('slug zones become names', () => {
    assert.equal(humanizeZone('marina-del-rey'), 'Marina Del Rey');
    assert.equal(humanizeZone('culver-city'), 'Culver City');
    assert.equal(humanizeZone('chelsea'), 'Chelsea');
});

test('already readable zones are untouched', () => {
    assert.equal(humanizeZone('Santa Monica'), 'Santa Monica');
    assert.equal(humanizeZone('Beverly Hills'), 'Beverly Hills');
    assert.equal(humanizeZone(''), '');
    assert.equal(humanizeZone(undefined), '');
});

test('the card header uses it', () => {
    assert.match(src, /const location = humanizeZone\(/);
});
