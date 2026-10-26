/**
 * Prix dans la locale du marché (retour PO du 2026-10-26 : « €165.10 » sur un
 * marché francophone).
 *
 * Le backend envoie des prix déjà mis en forme, toujours dans le même gabarit :
 * « €165.10 » (EUR, `_format_price_eur_cents`) ou « HKD 780.00 » (devise de
 * l'hôtel, `b2c_common.pricing.format_minor_amount`). Ce module en relit le
 * montant et la devise, puis les rend avec `Intl.NumberFormat` dans la locale du
 * marché : fr « 165,10 € », de « 165,10 € », en-US « $187.00 », en-GB
 * « £120.00 ». Il ne choisit JAMAIS la devise : celle du prix reçu est gardée.
 *
 * Pas de DOM ni d'import : il tourne tel quel sous node (tests/widget).
 */

// Symboles que le backend ou un ancien payload peut porter, du plus long au plus
// court : « HK$ » doit gagner sur « $ ». « $ » seul = USD (règle de l'ancien
// tableau CURRENCY_SYMBOLS de hotels/card.js).
const SYMBOL_CODES = [
    ['HK$', 'HKD'], ['NZ$', 'NZD'], ['NT$', 'TWD'], ['MX$', 'MXN'], ['US$', 'USD'],
    ['C$', 'CAD'], ['A$', 'AUD'], ['S$', 'SGD'], ['R$', 'BRL'], ['Kč', 'CZK'],
    ['€', 'EUR'], ['£', 'GBP'], ['¥', 'JPY'], ['₩', 'KRW'], ['฿', 'THB'], ['₺', 'TRY'],
    ['₹', 'INR'], ['$', 'USD'],
];

/**
 * Locale BCP 47 d'un marché `{ language, country_code }` : « fr » + « FR » →
 * « fr-FR », « en » + « GB » → « en-GB ». Une langue déjà régionale (« pt-br »)
 * est gardée telle quelle. Repli « en » si rien n'est exploitable.
 */
export function marketLocale(market) {
    const language = String((market && market.language) || '').trim().replace('_', '-');
    const country = String((market && market.country_code) || '').trim().toUpperCase();
    const candidates = [];
    if (language.includes('-')) candidates.push(language);
    if (language && /^[A-Z]{2}$/.test(country)) candidates.push(`${language}-${country}`);
    if (language) candidates.push(language.split('-')[0]);
    for (const candidate of candidates) {
        try {
            const [canonical] = Intl.getCanonicalLocales(candidate);
            if (canonical) return canonical;
        } catch (_) {
            // locale mal formée : on essaie la suivante
        }
    }
    return 'en';
}

/** Code ISO 4217 porté par une chaîne de prix, ou ''. */
export function detectCurrencyCode(text) {
    const s = String(text || '').trim();
    // Gabarit du backend pour la devise de l'hôtel : le code ISO en tête. Un code
    // inconnu (PLN…) reste ce code : jamais remplacé par la devise du marché.
    const leading = /^([A-Z]{3})\s*\d/.exec(s);
    if (leading) return leading[1];
    const anywhere = /\b([A-Z]{3})\b/.exec(s);
    if (anywhere && isCurrencyCode(anywhere[1])) return anywhere[1];
    for (const [symbol, code] of SYMBOL_CODES) {
        if (s.includes(symbol)) return code;
    }
    return '';
}

/** Premier montant d'une chaîne, décimales à point (« from €1,249.00 » → 1249). */
export function extractAmount(text) {
    const m = String(text || '').match(/\d[\d,.\s]*\d|\d/);
    if (!m) return NaN;
    return parseFloat(m[0].replace(/[,\s]/g, ''));
}

// Intl n'accepte qu'une forme (3 lettres), pas l'existence : la liste des devises
// connues du navigateur évite de lire « THE » ou « SPA » comme une devise.
let knownCurrencies = null;
function isCurrencyCode(code) {
    if (knownCurrencies === null) {
        try {
            knownCurrencies = new Set(Intl.supportedValuesOf('currency'));
        } catch (_) {
            knownCurrencies = new Set();
        }
    }
    return knownCurrencies.has(code);
}

/** Nombre de décimales de la devise (EUR 2, JPY 0, BHD 3). */
export function currencyDigits(code) {
    try {
        return new Intl.NumberFormat('en', { style: 'currency', currency: code })
            .resolvedOptions().maximumFractionDigits;
    } catch (_) {
        return 2;
    }
}

/**
 * `amount` dans la devise `code`, mis en forme pour `locale`.
 * `wholeUnits` : sans décimales (le prix d'appel des cartes, arrondi comme avant).
 * Une devise ou une locale que le navigateur refuse donne « CODE 165.10 ».
 */
export function formatMoney(amount, code, locale, { wholeUnits = false } = {}) {
    const value = Number(amount);
    if (!Number.isFinite(value)) return '';
    const currency = String(code || '').toUpperCase();
    const digits = wholeUnits ? { minimumFractionDigits: 0, maximumFractionDigits: 0 } : {};
    try {
        return new Intl.NumberFormat(locale || 'en', { style: 'currency', currency, ...digits }).format(value);
    } catch (_) {
        const fixed = wholeUnits ? Math.round(value).toString() : value.toFixed(currencyDigits(currency));
        return currency ? `${currency} ${fixed}` : fixed;
    }
}

/**
 * Une chaîne de prix du backend (« €165.10 », « HKD 780.00 »), remise en forme
 * pour `locale`. `fallbackCode` sert quand la chaîne ne porte aucune devise.
 * Une chaîne sans montant ou sans devise reconnaissable est rendue telle quelle.
 */
export function formatPriceString(text, locale, { fallbackCode = '', wholeUnits = false } = {}) {
    const raw = String(text || '').trim();
    const amount = extractAmount(raw);
    const code = detectCurrencyCode(raw) || String(fallbackCode || '').toUpperCase();
    if (!Number.isFinite(amount) || !code) return raw;
    return formatMoney(amount, code, locale, { wholeUnits });
}
