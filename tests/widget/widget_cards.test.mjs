import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = (f) => readFileSync(new URL(`../../web/vendor/static/css/chat/${f}`, import.meta.url), 'utf8');

test('hotel photo and gallery are 3:2, no fixed 160px height', () => {
    for (const f of ['hotels.css', 'carousel.css']) {
        assert.match(css(f), /aspect-ratio:\s*3\s*\/\s*2/, f);
    }
    assert.doesNotMatch(css('carousel.css'), /\.image-carousel\s*\{[^}]*height:\s*160px/);
    assert.doesNotMatch(css('hotels.css'), /\.hotel-image\s*\{[^}]*height:\s*160px/);
});

test('mobile swipe: card = row − gutter 12 − peek 32, margin 16, snap 16', () => {
    const r = css('responsive.css');
    assert.match(r, /flex:\s*0 0 calc\(100% - 44px\)/);
    assert.match(r, /scroll-padding-left:\s*16px/);
    assert.match(r, /padding:\s*8px 16px 12px/);
});

test('gallery photo gets no hover zoom (Image depth does not apply to galleries)', () => {
    assert.doesNotMatch(css('carousel.css'), /\.image-carousel[^{]*:hover[^{]*\{[^}]*(scale|width)/);
});
