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

test('mobile swipe: card = viewport − margin 16 − gutter 12 − peek 32, snap 16', () => {
    const r = css('responsive.css');
    assert.match(r, /flex:\s*0 0 calc\(100% - 28px\)/);
    assert.match(r, /scroll-padding-left:\s*16px/);
    assert.match(r, /padding:\s*8px 16px 12px/);
});

test('mobile swipe row runs edge to edge: out of the chat padding and the avatar column', () => {
    assert.match(
        css('responsive.css'),
        /\.hotel-cards-container\s*\{[^}]*margin:\s*12px -16px 12px calc\(-16px - 28px - var\(--space-2\)\)/
    );
});

test('hotel results message can shrink beside the avatar (no clipped arrow or "See all")', () => {
    assert.match(css('hotels.css'), /\.message-content\.with-hotels\s*\{[^}]*min-width:\s*0/);
});

test('gallery photo gets no hover zoom (Image depth does not apply to galleries)', () => {
    assert.doesNotMatch(css('carousel.css'), /\.image-carousel[^{]*:hover[^{]*\{[^}]*(scale|width)/);
});

test('carousel arrows are centred on the 3:2 photo, not on the card', () => {
    assert.match(css('carousel.css'), /\.carousel-nav-button\s*\{[^}]*top:\s*calc\(16px \+ 320px \/ 3\)/);
    assert.match(css('responsive.css'), /with-hotels \.carousel-nav-button\s*\{\s*top:\s*calc\(8px \+ 256px \/ 3\)/);
});

test('hotel name reserves two lines so slots align across cards', () => {
    assert.match(css('hotels.css'), /\.hotel-name\s*\{[^}]*min-height:\s*2lh/);
});

// Retour PO du 2026-10-26 : le badge « -X% » en rouge pastèque détonnait. dayuse.com affiche
// ses remises en pastille Shadow Black, texte blanc gras (`bg-shadow-black text-white
// font-bold rounded-full`), comme déjà la remise des formules de la booking card.
test('badge de remise : pastille Shadow Black, texte blanc, comme dayuse.com', () => {
    const hotels = readFileSync(new URL('../../web/vendor/static/css/chat/hotels.css', import.meta.url), 'utf8');
    const deal = /\.deal-badge\s*\{([^}]*)\}/.exec(hotels)[1];
    assert.match(deal, /background:\s*var\(--bg-invert\)/);
    assert.match(deal, /color:\s*var\(--fg-invert\)/);
    assert.match(deal, /border-radius:\s*var\(--radius-action\)/);
    // Contre-épreuve : plus de rouge d'alerte.
    assert.ok(!/watermelon|feedback-error|#f45c5a/i.test(deal), deal);
    const plan = /\.booking-card__plan-disc\s*\{([^}]*)\}/.exec(hotels)[1];
    assert.match(plan, /background:\s*var\(--bg-invert\)/);
    const tokens = readFileSync(new URL('../../web/vendor/static/css/chat/tokens.css', import.meta.url), 'utf8');
    assert.match(tokens, /--bg-invert:\s*#292935/);
});
