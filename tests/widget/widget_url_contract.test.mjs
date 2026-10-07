/**
 * The widget must not invent a hotel URL — UX6, arbitrated by Fabien 2026-08-28.
 *
 * `libs/b2c_common/b2c_common/hotel_urls.py` holds itself to: "nothing in this
 * repo may ever slugify a display name into a URL ... an unmapped country
 * yields None — the card honestly has no link rather than a guessed one".
 * The widget used to defeat that: `buildHotelFallbackUrl` slugified the display
 * name onto a guessed host, and it PASSED the host allowlist, so it rendered as
 * a live booking link that 404s. Audit: reports/AUDIT-MAPPINGS-2026-08-28.md §6.2.
 *
 * Run by `tests/test_market_table_drift.py::TestWidgetUrlContract` (which is
 * what puts it in `pytest -q` and therefore in CI). Runnable directly too:
 *     node --test tests/widget/
 *
 * These load the REAL widget modules. `markets.js` and `security.js` import
 * nothing, so they evaluate in bare node with no DOM.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const CHAT = new URL('../../web/vendor/static/js/chat/', import.meta.url);

const markets = await import(new URL('markets.js', CHAT));
const { sanitizeDayuseUrl } = await import(new URL('security.js', CHAT));

test('the name-slugifying fallback is gone from markets.js', () => {
    assert.equal(
        markets.buildHotelFallbackUrl,
        undefined,
        'buildHotelFallbackUrl is back. It slugified hotel.name onto a guessed '
        + 'host; the backend forbids itself from doing exactly this.',
    );
});

test('no markets.js export builds a hotel-page URL out of a display name', () => {
    // The shape that used to produce https://dayuse.com/hotels/usa/h-tel-m-tropole-spa
    const hotel = { name: 'Hôtel Métropole & Spa', country: 'Poland', slug: 'hotel-metropole-spa' };
    for (const [name, value] of Object.entries(markets)) {
        if (typeof value !== 'function') continue;
        let out;
        try {
            out = value(hotel);
        } catch {
            continue; // not a hotel-shaped callee
        }
        const text = typeof out === 'string' ? out : JSON.stringify(out ?? '');
        assert.ok(
            !/\/hotels\//.test(text),
            `markets.js export ${name}() produced a hotel-page path from a display name: ${text}`,
        );
    }
});

test('the fabricated URL WOULD have passed the allowlist — the fix was not cosmetic', () => {
    // Kept as a live assertion, not a comment: it is the reason the fabricated
    // link reached customers instead of being dropped by the sanitizer.
    assert.ok(
        sanitizeDayuseUrl('https://dayuse.com/hotels/usa/h-tel-m-tropole-spa'),
        'if this ever stops being truthy the sanitizer changed shape; re-read §6.2',
    );
});

test('an unmapped country yields no country code — why the old fallback said "usa"', () => {
    // `inferCountryCodeFromHotel` needs a 2-letter code; a full name yields ''.
    // getMarketMeta then fell back to its 'US' default. Documented by test so
    // the next reader does not rediscover it in prod.
    assert.equal(markets.inferCountryCodeFromHotel({ country: 'Poland' }), '');
    assert.equal(markets.getMarketMeta('', 'US').code, 'US');
});

test('deleting the dead COUNTRY_META.UK alias did not break UK resolution', () => {
    // The alias was unreachable: getMarketMeta routes every key through
    // normalizeCountryCode, which maps UK -> GB BEFORE the lookup.
    assert.equal(markets.normalizeCountryCode('UK'), 'GB');
    assert.equal(markets.getMarketMeta('UK').code, 'GB');
    assert.equal(markets.getMarketMeta('uk').code, 'GB');
    assert.equal(markets.getMarketMeta('UK').hotelCountrySlug, 'united-kingdom');
    assert.match(markets.getMarketMeta('UK').browseUrl, /dayuse\.co\.uk/);
});

test('the "uk" slug key IS still reachable — it is a different table', () => {
    // COUNTRY_SLUG_TO_CODE['uk'] matches a /s/uk URL path segment, unlike the
    // COUNTRY_META alias that was removed. Do not "clean up" this one too.
    assert.equal(
        markets.inferCountryCodeFromHotel({ url: 'https://www.dayuse.co.uk/s/uk' }),
        'GB',
    );
});

test('a hotel with no url resolves to no url, not to a guess', () => {
    const hotel = { name: 'Grand Hyatt Tokyo', country: 'Japan' };
    assert.equal(markets.inferCountryCodeFromHotel(hotel), '');
    // Nothing in the module hands back a URL for it any more.
    assert.equal(markets.buildHotelFallbackUrl, undefined);
});

test('card.js still links — no dangling import of the removed function', async () => {
    // card.js pulls in DOM-dependent modules, so it cannot be EVALUATED in bare
    // node. But ESM parses and links the whole graph before evaluating any of
    // it, so a stale `import { buildHotelFallbackUrl }` surfaces as a link-time
    // SyntaxError, which this catches, while a ReferenceError on `document`
    // means linking succeeded — the only thing under test here.
    let error = null;
    try {
        await import(new URL('hotels/card.js', CHAT));
    } catch (err) {
        error = err;
    }
    if (error) {
        assert.ok(
            !/does not provide an export named/.test(String(error.message)),
            `card.js imports something markets.js no longer exports: ${error.message}`,
        );
    }
});

test('option B: the market tables come from the generated file', async () => {
    const gen = await import(new URL('markets.generated.js', CHAT));
    assert.ok(gen.COUNTRY_META, 'markets.generated.js must export COUNTRY_META');
    assert.ok(gen.COUNTRY_SLUG_TO_CODE, 'and COUNTRY_SLUG_TO_CODE');
    // 25 since 2026-08-28: KR/TR/QA added — the 3 unmapped markets that had
    // live MCP inventory and therefore cards with no link at all.
    assert.equal(Object.keys(gen.COUNTRY_META).length, 25);
    // markets.js must consume them, not redefine them.
    const src = await readFile(new URL('markets.js', CHAT), 'utf8');
    assert.ok(
        !/^const COUNTRY_META = \{/m.test(src),
        'markets.js redefines COUNTRY_META — it must import the generated table',
    );
    assert.match(src, /from '\.\/markets\.generated\.js'/);

    // The artifact must announce itself, so nobody hand-edits it.
    const artifact = await readFile(new URL('markets.generated.js', CHAT), 'utf8');
    assert.match(artifact, /GENERATED FILE — DO NOT EDIT BY HAND/);
});

test('the browse hosts are per-market, not the global one', async () => {
    const { getMarketMeta } = await import(new URL('markets.js', CHAT));
    // These 8 all pointed at www.dayuse.com before option B; dayuse-com's own
    // per-locale configs say otherwise, and /s/brazil + /s/malaysia were 404s.
    const expected = {
        TH: 'th.dayuse.com', CA: 'ca.dayuse.com', AU: 'au.dayuse.com',
        NZ: 'nz.dayuse.com', HK: 'www.dayuse.com.hk', AE: 'www.dayuse.ae',
        BR: 'www.dayuse.net.br',
    };
    for (const [code, host] of Object.entries(expected)) {
        const url = getMarketMeta(code).browseUrl;
        assert.equal(new URL(url).hostname, host, `${code} browse host`);
    }
    assert.equal(getMarketMeta('BR').browseUrl, 'https://www.dayuse.net.br/s/brasil');
});

test('a market with no browse page yields null, and no guessed URL', async () => {
    const { getMarketMeta } = await import(new URL('markets.js', CHAT));
    assert.equal(getMarketMeta('MY').browseUrl, null, 'MY has no browse page');
    // An entirely unmapped market must not fall back to a bare host either.
    const unknown = getMarketMeta('ZZ');
    assert.equal(unknown.browseUrl, null);
    assert.equal(unknown.hotelCountrySlug, undefined,
        'the guessed hotelCountrySlug is gone — its only reader was the removed fabricator');
});

test('utils.js still links — same check for the second call site', async () => {
    let error = null;
    try {
        await import(new URL('utils.js', CHAT));
    } catch (err) {
        error = err;
    }
    if (error) {
        assert.ok(
            !/does not provide an export named/.test(String(error.message)),
            `utils.js imports something markets.js no longer exports: ${error.message}`,
        );
    }
});

test('the results "see all" follows the hotels on screen, not the entry market', () => {
    // QA 2026-09-23: a Singapore search on the default widget host sent
    // "Voir tout" to www.dayuse.com/s/united-states — the page's market context
    // won over the results. The carousel link, hotel-based, already said Singapore.
    const sg = markets.getResultsMarketMeta([{ name: 'Studio M Hotel', country_code: 'SG' }]);
    assert.equal(sg.code, 'SG');
    assert.equal(sg.browseUrl, 'https://www.dayuse.sg/s/singapore');
    // Same answer as the carousel's own link for the same hotels.
    assert.deepEqual(sg, markets.getMarketMetaFromHotels([{ country_code: 'SG' }], 'US'));
    // Country recovered from the hotel URL when the card has no code.
    assert.equal(
        markets.getResultsMarketMeta([{ url: 'https://www.dayuse.fr/hotels/france/drawing-house' }]).code,
        'FR',
    );
});

test('no country on the hotels means no results market — the caller falls back', () => {
    assert.equal(markets.getResultsMarketMeta([{ name: 'Villa', country: 'Poland' }]), null);
    assert.equal(markets.getResultsMarketMeta([]), null);
    assert.equal(markets.getResultsMarketMeta(null), null);
});

test('the search page URL of « Voir tout » passes the allowlist intact (mcp-dayuse#5)', () => {
    const url = 'https://www.dayuse.fr/s/france/auvergne-rhone-alpes/rhone/lyon'
        + '?selectedAddress=Lyon&checkinDate=2026-10-07&checkinTime=6am&checkoutTime=4pm';
    assert.equal(sanitizeDayuseUrl(url), url);
});
