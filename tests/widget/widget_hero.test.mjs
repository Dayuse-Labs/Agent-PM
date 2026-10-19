import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = (f) => readFileSync(new URL(`../../web/vendor/static/css/chat/${f}`, import.meta.url), 'utf8');

test('hero title is Display: 56/64/-2 desktop, 32/40/-1.1 mobile, weight 700', () => {
    const h = css('hero.css');
    assert.match(h, /\.initial-state h1\s*\{[^}]*font-size:\s*56px[^}]*font-weight:\s*700[^}]*line-height:\s*64px[^}]*letter-spacing:\s*-2px/s);
    const r = css('responsive.css');
    assert.match(r, /\.initial-state h1\s*\{[^}]*font-size:\s*32px[^}]*line-height:\s*40px[^}]*letter-spacing:\s*-1\.1px/s);
});

test('Maison Neue Extended is declared 700, the weight of its file', () => {
    assert.match(css('base.css'), /MaisonNeueExtended-Bold[\s\S]*?font-weight:\s*700/);
});

test('nothing coloured or shadowed on the hero photo', () => {
    const h = css('hero.css');
    assert.doesNotMatch(h, /text-shadow:\s*0/);
    assert.doesNotMatch(h, /#FEB900|#FD7030|#FDAA9A|#B7D5D5/i);
});

test('thinking is plain secondary text, no animated gradient; AI marks use Universe Sunny', () => {
    const a = css('animations.css');
    assert.doesNotMatch(a, /#F55F30|#FFB800/i);
    assert.match(a, /\.thinking-text\s*\{[^}]*var\(--fg-secondary\)/s);
    assert.match(css('layout.css'), /\.avatar--ai\s*\{[^}]*--universe-sunny-default/s);
    assert.doesNotMatch(css('layout.css') + css('hotels.css'), /dy-gradient-primary/);
});
