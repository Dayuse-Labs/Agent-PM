/**
 * Prix dans la locale du marché (retour PO du 2026-10-26 : « €165.10 » sur un
 * marché francophone). fr « 165,10 € », de « 165,10 € », en-US « $187.00 »,
 * en-GB « £120.00 ». La devise reste celle du prix reçu : seule la mise en forme
 * suit le marché. Module pur (price_format.js) : il tourne sous node.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const CHAT = new URL('../../web/vendor/static/js/chat/', import.meta.url);
const {
    marketLocale, detectCurrencyCode, extractAmount, currencyDigits, formatMoney, formatPriceString,
} = await import(new URL('price_format.js', CHAT));
const read = (rel) => readFileSync(new URL(rel, CHAT), 'utf8');

// Intl sépare montant et symbole par une espace insécable (U+00A0 ou U+202F selon
// la locale) : elle est voulue (« 165,10 / € » ne doit jamais se couper). Les
// attentes s'écrivent avec une espace simple, la présence de l'insécable est
// vérifiée à part.
const plain = (s) => s.replace(/[  ]/g, ' ');

test('locale du marché : langue + pays du marché', () => {
    assert.equal(marketLocale({ language: 'fr', country_code: 'FR' }), 'fr-FR');
    assert.equal(marketLocale({ language: 'de', country_code: 'DE' }), 'de-DE');
    assert.equal(marketLocale({ language: 'en', country_code: 'US' }), 'en-US');
    assert.equal(marketLocale({ language: 'en', country_code: 'GB' }), 'en-GB');
    assert.equal(marketLocale({ language: 'pt-br', country_code: 'BR' }), 'pt-BR');
    assert.equal(marketLocale({ language: 'fr' }), 'fr');
    assert.equal(marketLocale({}), 'en');
    assert.equal(marketLocale(null), 'en');
    assert.equal(marketLocale({ language: '!!', country_code: 'FR' }), 'en');
});

test('prix du backend en EUR : symbole après le montant en fr et de, avant en en-US', () => {
    assert.equal(plain(formatPriceString('€165.10', 'fr-FR')), '165,10 €');
    assert.equal(plain(formatPriceString('€165.10', 'de-DE')), '165,10 €');
    assert.equal(plain(formatPriceString('€165.10', 'es-ES')), '165,10 €');
    // Contre-épreuve : la locale décide, pas un gabarit en dur. En anglais
    // américain, l'euro reste devant (c'est l'usage), avec le point décimal.
    assert.equal(formatPriceString('€165.10', 'en-US'), '€165.10');
    // Et en fr le rendu n'est plus jamais celui d'avant.
    assert.notEqual(formatPriceString('€165.10', 'fr-FR'), '€165.10');
});

test('montant et symbole ne se séparent pas à la ligne (espace insécable)', () => {
    const fr = formatPriceString('€165.10', 'fr-FR');
    assert.match(fr, /^165,10[  ]€$/);
    assert.ok(!/ /.test(fr), `espace sécable dans ${JSON.stringify(fr)}`);
});

test('devise de l\'hôtel (« CODE 0.00 ») : chaque marché a son usage', () => {
    assert.equal(formatPriceString('USD 187.00', 'en-US'), '$187.00');
    assert.equal(formatPriceString('GBP 120.00', 'en-GB'), '£120.00');
    assert.equal(formatPriceString('HKD 780.00', 'en-US'), 'HK$780.00');
    assert.equal(plain(formatPriceString('CHF 120.00', 'fr-FR')), '120,00 CHF');
    // Un code que l'ancien tableau ne connaissait pas reste ce code.
    assert.equal(plain(formatPriceString('PLN 250.00', 'fr-FR')), '250,00 PLN');
});

test('la devise affichée ne change jamais, seule la mise en forme suit le marché', () => {
    // Un prix en dollars sur un marché français reste en dollars.
    assert.equal(plain(formatPriceString('USD 187.00', 'fr-FR')), '187,00 $US');
    // Un prix en euros sur le marché britannique reste en euros.
    assert.equal(formatPriceString('€165.10', 'en-GB'), '€165.10');
    assert.equal(detectCurrencyCode('€165.10'), 'EUR');
    assert.equal(detectCurrencyCode('from CAD 120.00'), 'CAD');
    assert.equal(detectCurrencyCode('HK$780'), 'HKD');
    assert.equal(detectCurrencyCode('$127.00 - $159.00'), 'USD');
    // Un mot en capitales n'est pas une devise.
    assert.equal(detectCurrencyCode('SPA €120'), 'EUR');
});

test('une chaîne sans devise ou sans montant est rendue telle quelle', () => {
    assert.equal(formatPriceString('165.10', 'fr-FR'), '165.10');
    assert.equal(formatPriceString('sur demande', 'fr-FR'), 'sur demande');
    assert.equal(formatPriceString('', 'fr-FR'), '');
    assert.equal(formatPriceString(undefined, 'fr-FR'), '');
});

test('prix d\'appel des cartes : unités entières, séparateur de milliers de la locale', () => {
    assert.equal(plain(formatMoney(165.1, 'EUR', 'fr-FR', { wholeUnits: true })), '165 €');
    assert.equal(formatMoney(165.1, 'EUR', 'en-US', { wholeUnits: true }), '€165');
    assert.equal(formatMoney(187, 'USD', 'en-US', { wholeUnits: true }), '$187');
    assert.equal(plain(formatMoney(1249, 'EUR', 'fr-FR', { wholeUnits: true })), '1 249 €');
    assert.equal(plain(formatMoney(289, 'EUR', 'de-DE', { wholeUnits: true })), '289 €');
    // Arrondi identique à l'ancien Math.round.
    assert.equal(formatMoney(245.5, 'USD', 'en-US', { wholeUnits: true }), '$246');
    assert.equal(formatMoney(NaN, 'EUR', 'fr-FR'), '');
});

test('décimales de la devise et montant lu à point décimal', () => {
    assert.equal(currencyDigits('EUR'), 2);
    assert.equal(currencyDigits('JPY'), 0);
    assert.equal(currencyDigits('BHD'), 3);
    assert.equal(extractAmount('€1,249.00'), 1249);
    assert.equal(extractAmount('from HKD 780.00'), 780);
    assert.ok(Number.isNaN(extractAmount('—')));
});

test('devise invalide : repli lisible, jamais d\'exception', () => {
    assert.equal(formatMoney(12.5, 'ZZ', 'fr-FR'), 'ZZ 12.50');
});

// --- Branchement dans le widget ------------------------------------------------------------

test('la carte formate prix et prix nuit barré dans la locale du marché', () => {
    const card = read('hotels/card.js');
    assert.ok(!/CURRENCY_SYMBOLS|currencyPrefix|detectCurrencySymbol/.test(card), 'ancien gabarit symbole + montant');
    assert.match(card, /class="current-price">\$\{escapeHtml\(formatCardAmount\(priceInfo\.value, priceInfo\.code\)\)\}/);
    assert.match(card, /class="original-price">\$\{escapeHtml\(formatCardAmount\(originalPrice, priceInfo\.code\)\)\}/);
    assert.match(card, /marketLocale\(state\.marketContext\)/);
});

test('carte simplifiée et booking card passent par les mêmes formateurs', () => {
    const messages = read('ui/messages.js');
    assert.match(messages, /formatCardAmount\(priceInfo\.value, priceInfo\.code\)/);
    assert.ok(!/currencyPrefix/.test(messages));
    for (const field of ['plan.price', 'plan.original_price', 'card.price']) {
        assert.ok(messages.includes(`formatBackendPrice(${field})`), field);
    }
    assert.match(messages, /priceTarget\.textContent = formatBackendPrice\(price\)/);
});

test('la carte reçoit le montant numérique (whitelist de mapV3Hotels)', () => {
    const send = read('handlers/send.js');
    for (const field of ['price_eur_cents', 'display_currency', 'display_price_minor']) {
        assert.match(send, new RegExp(`${field}: h\\.${field} \\?\\? null`), field);
    }
});

// cardPrice() vit dans hotels/card.js, qui importe des modules liés au DOM : sa
// logique est évaluée depuis la source, avec les vrais helpers de price_format.js.
function loadCardPrice(market) {
    const src = read('hotels/card.js');
    const pick = (name) => new RegExp(`(?:export )?function ${name}\\([\\s\\S]*?\\n}\\n`).exec(src)[0].replace('export ', '');
    const body = ['marketCurrencyCode', 'parsePrice', 'cardPrice'].map(pick).join('\n');
    return new Function('state', 'extractAmount', 'detectCurrencyCode', 'currencyDigits',
        `${body}; return cardPrice;`)({ marketContext: market }, extractAmount, detectCurrencyCode, currencyDigits);
}

test('cardPrice : le montant numérique quand il est dans la devise affichée', () => {
    const cardPrice = loadCardPrice({ currency: 'USD' });
    assert.deepEqual(cardPrice({ price: '€165.10', price_eur_cents: 16510 }), { value: 165.1, code: 'EUR' });
    assert.deepEqual(
        cardPrice({ price: 'HKD 780.00', display_currency: 'HKD', display_price_minor: 78000, price_eur_cents: 9300 }),
        { value: 780, code: 'HKD' },
    );
    assert.deepEqual(
        cardPrice({ price: 'JPY 1600', display_currency: 'JPY', display_price_minor: 1600 }),
        { value: 1600, code: 'JPY' },
    );
    // Contre-épreuve : un montant numérique d'une AUTRE devise que la chaîne
    // affichée n'est jamais pris (la carte resterait en EUR avec un montant HKD).
    assert.deepEqual(cardPrice({ price: 'HKD 780.00', price_eur_cents: 9300 }), { value: 780, code: 'HKD' });
    // Sans montant numérique : la chaîne ; sans devise : celle du marché.
    assert.deepEqual(cardPrice({ price: '€89.00' }), { value: 89, code: 'EUR' });
    assert.deepEqual(cardPrice({ min_price_ttc: 120 }), { value: 120, code: 'USD' });
});
