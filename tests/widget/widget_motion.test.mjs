// Mouvement réduit (fondations Dayuse, loi 11) : le défilement lissé retombe sur l'instantané.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../web/vendor/static');
const { scrollBehavior, prefersReducedMotion } = await import(`${root}/js/chat/motion.js`);

test('sans window (node) : mouvement normal', () => {
    delete globalThis.window;
    assert.equal(prefersReducedMotion(), false);
    assert.equal(scrollBehavior(), 'smooth');
});

test('prefers-reduced-motion: reduce -> scroll instantané', () => {
    globalThis.window = { matchMedia: (q) => ({ matches: q.includes('reduce') }) };
    assert.equal(scrollBehavior(), 'auto');
    delete globalThis.window;
});

test('aucun scroll lissé en dur dans le JS du widget', () => {
    const files = ['filters/search.js', 'ui/messages.js', 'hotels/carousel.js', 'hotels/images.js', 'handlers/responses.js'];
    for (const f of files) {
        const src = readFileSync(`${root}/js/chat/${f}`, 'utf8');
        assert.ok(!/behavior:\s*['"]smooth['"]/.test(src), `${f} : behavior smooth en dur`);
    }
});

test('viewport : le zoom utilisateur n\'est pas bloqué', () => {
    const html = readFileSync(`${root}/../templates/chat_clean.html`, 'utf8');
    assert.ok(!/user-scalable\s*=\s*no/.test(html));
    assert.ok(!/maximum-scale/.test(html));
});

test('feuilles de style : reduced-motion et ring de focus présents', () => {
    const anim = readFileSync(`${root}/css/chat/animations.css`, 'utf8');
    const base = readFileSync(`${root}/css/chat/base.css`, 'utf8');
    assert.match(anim, /prefers-reduced-motion:\s*reduce/);
    assert.match(base, /:focus-visible/);
    assert.match(base, /var\(--focus-ring\)/);
});
