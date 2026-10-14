/**
 * Hotel Card
 * Render individual hotel cards with all details
 */

import { state, carousels } from '../state.js';
import { appendAmplitudeIdToUrl, trackEvent } from '../tracking.js';
import { formatRating } from '../utils.js';
import { selectBestImage } from './images.js';
import { getLanguage, t } from '../i18n.js';
import { formatSlotRange } from '../slot_time.js';
import { escapeAttr, escapeHtml, sanitizeDayuseUrl, sanitizeImageUrl } from '../security.js';

let imageCarouselInstanceCounter = 0;

function buildImageCarouselId(hotelSlug, hotelNumericId) {
    const safeSlug = String(hotelSlug || 'hotel')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '') || 'hotel';
    const safeNumericId = String(hotelNumericId || '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '');
    imageCarouselInstanceCounter += 1;
    const suffix = imageCarouselInstanceCounter.toString(36);
    return `img-${safeSlug}-${safeNumericId || 'na'}-${suffix}`;
}

/**
 * Extract direct image URL from Vercel proxy URL
 * static.dayuse.com is allowed by CSP (*.dayuse.com)
 */
function extractDirectImageUrl(url) {
    if (!url) return url;

    // Check if this is a Vercel image proxy URL - extract the source
    if (url.includes('/_vercel/image?url=')) {
        try {
            const urlObj = new URL(url);
            const directUrl = urlObj.searchParams.get('url');
            if (directUrl) {
                return directUrl;
            }
        } catch (e) {
            console.warn('Failed to parse Vercel image URL:', url);
        }
    }

    return url;
}

// Display symbol per ISO currency. Spacing is baked in: alphabetic codes get a
// trailing space ("CHF 120"), glyphs don't ("€120"). Keyed on the `currency_code`
// the card carries (MCP_B2C's per-hotel currencyCode, S-G7). There is NO backend
// mirror of this table in this repo — the comment used to claim it mirrored a
// `_CURRENCY_DISPLAY` that only ever existed in agent-usa (checked 2026-08-28,
// UX6 audit): prices reach the widget already formatted, so this table only
// decides the glyph, never a conversion.
const CURRENCY_SYMBOLS = {
    USD: '$', EUR: '€', GBP: '£', CHF: 'CHF ', CAD: 'C$', AUD: 'A$', NZD: 'NZ$',
    SGD: 'S$', HKD: 'HK$', BRL: 'R$', MXN: 'MX$', AED: 'AED ', SAR: 'SAR ',
    QAR: 'QAR ', BHD: 'BHD ', THB: '฿', JPY: '¥', KRW: '₩', SEK: 'kr ',
    CZK: 'Kč ', TRY: '₺', TWD: 'NT$',
};

/**
 * "HKD 780.00" → "HK$780.00". A hotel-currency price comes from the backend with
 * its ISO code first (the parser below keys on it); rendered as-is it would sit
 * next to "€95.00" in the booking card. Any other string is returned unchanged.
 */
export function formatBackendPrice(price) {
    const text = String(price || '').trim();
    const match = /^([A-Z]{3}) (\d[\d.,]*)$/.exec(text);
    if (!match) return text;
    const symbol = CURRENCY_SYMBOLS[match[1]];
    return symbol ? `${symbol}${match[2]}` : text;
}

function marketCurrencySymbol() {
    const code = String((state.marketContext && state.marketContext.currency) || '').toUpperCase();
    return CURRENCY_SYMBOLS[code] || '';
}

// Detect the display symbol present in a backend price string ("from CAD 120.00",
// "from €120.00", "$127.00 - $159.00"). Order matters: ISO codes first, then
// glyphs, then compound dollar marks (C$, A$…), then a bare "$" (USD) last.
function detectCurrencySymbol(str) {
    const s = String(str || '');
    // A hotel-currency price from the backend starts with its ISO code. One the
    // table below doesn't know (PLN, INR…) must show as that code, never fall
    // through to the market's symbol: "PLN 250" rendered as "€250" is a wrong price.
    const leading = /^([A-Z]{3}) \d/.exec(s.trim());
    if (leading) return CURRENCY_SYMBOLS[leading[1]] || `${leading[1]} `;
    const code = s.toUpperCase().match(
        /\b(USD|EUR|GBP|CHF|CAD|AUD|NZD|SGD|HKD|BRL|MXN|AED|SAR|QAR|BHD|THB|JPY|KRW|SEK|CZK|TRY|TWD)\b/
    );
    if (code) return CURRENCY_SYMBOLS[code[1]];
    for (const glyph of ['€', '£', '¥', '₩', '฿', '₺']) {
        if (s.includes(glyph)) return glyph;
    }
    if (s.includes('Kč')) return 'Kč ';
    for (const compound of ['C$', 'A$', 'NZ$', 'NT$', 'S$', 'HK$', 'MX$', 'R$']) {
        if (s.includes(compound)) return compound;
    }
    if (s.includes('$')) return '$';
    return '';
}

// Extract the first numeric amount, tolerant of a "from "/symbol prefix and a
// range ("$127.00 - $159.00" → 127). Backend formats with dot decimals.
function extractAmount(str) {
    const m = String(str || '').match(/\d[\d,.\s]*\d|\d/);
    if (!m) return NaN;
    return parseFloat(m[0].replace(/[,\s]/g, ''));
}

/**
 * Parse price from various formats into { value, currency, display } where
 * `currency` is a render-ready display symbol (already spaced).
 * Handles: "from €120.00", "from CAD 120.00", "$127.00 - $159.00", 127, "127".
 */
export function parsePrice(price, fallbackCurrency) {
    if (typeof price === 'number') {
        return { value: price, currency: marketCurrencySymbol(), display: Math.round(price).toString() };
    }
    if (typeof price === 'string') {
        const raw = extractAmount(price);
        const value = isNaN(raw) ? 0 : raw;
        const currency = detectCurrencySymbol(price) || marketCurrencySymbol();
        return { value, currency, display: Math.round(value).toString() };
    }
    return { value: 0, currency: marketCurrencySymbol(), display: '0' };
}

/**
 * Compute discount vs night rate from timeslot data.
 * Returns { discount: number|null, nightPrice: number|null }
 */
function computeNightDiscount(hotel, priceInfo) {
    // Look for original_price (night rate) in timeslots
    const allSlots = [
        ...(hotel.matched_timeslots || []),
        ...(hotel.timeslots || [])
    ];

    // Find the first timeslot that has an original_price
    const slotWithNightRate = allSlots.find(s => s.original_price && s.original_price > 0);

    if (!slotWithNightRate || !priceInfo.value || priceInfo.value <= 0) {
        return { discount: null, nightPrice: null };
    }

    const nightPrice = slotWithNightRate.original_price;
    if (nightPrice <= priceInfo.value) {
        return { discount: null, nightPrice: null };
    }

    const discount = Math.round(((nightPrice - priceInfo.value) / nightPrice) * 100);
    return { discount, nightPrice };
}

/**
 * Create a hotel card HTML
 */
export function createHotelCard(hotel) {
    const hotelSlug = (hotel.name || 'hotel').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const hotelNumericId = hotel.id || hotel.hotel_id || hotelSlug;
    const imageCarouselId = buildImageCarouselId(hotelSlug, hotelNumericId);

    // Server-provided url only. There is no name-slugified fallback any more
    // (UX6 2026-08-28 — see markets.js for what it used to emit and why it had
    // to go): a card with no url gets no hotel-page link, which is the contract
    // the backend builder already holds itself to.
    const sanitizedUrl = sanitizeDayuseUrl(appendAmplitudeIdToUrl(hotel.url || ''));
    if (!sanitizedUrl) {
        // The card cannot offer a hotel page. Two distinct causes, and the
        // second one used to be INVISIBLE (the old guard was `if (hotel.url &&
        // !sanitizedUrl)`, so "no url at all" was never reported — the case
        // where the widget quietly invented one). Event name kept for series
        // continuity in Amplitude; `reason` is what splits the two.
        trackEvent('booking_url_fallback', {
            hotel_id: String(hotel.id || hotel.hotel_id || ''),
            hotel_name: String(hotel.name || ''),
            reason: hotel.url ? 'rejected_by_allowlist' : 'missing_from_payload',
            rejected_url: String(hotel.url || '').slice(0, 300),
        });
    }
    const hotelUrl = sanitizedUrl || '';

    // Parse price - handles formats like "$127.00 - $159.00" or just numbers
    const priceInfo = parsePrice(hotel.price || hotel.min_price_ttc || 0, hotel.display_currency);
    const safeStars = hotel.stars || 4;

    // Compute discount from timeslot original_price (night rate) vs day-use price
    const { discount, nightPrice: originalPrice } = computeNightDiscount(hotel, priceInfo);

    // Store currency and price for footer
    hotel._currency = priceInfo.currency;
    hotel._formattedPrice = priceInfo.display;

    // Initialize carousel with smart image selection
    let images = hotel.image_urls && hotel.image_urls.length > 0
        ? hotel.image_urls.map(extractDirectImageUrl)
        : ['https://images.dayuse.com/hotels/default/default.jpg'];
    images = images
        .map(url => sanitizeImageUrl(url))
        .filter(Boolean);
    if (!images.length) {
        images = ['https://images.dayuse.com/hotels/default/default.jpg'];
    }

    images = selectBestImage(images, state.currentUserQuery, hotel);

    carousels.set(imageCarouselId, {
        currentImage: 0,
        totalImages: images.length
    });

    // S-CX9: the concierge line moved BELOW the time slot. It is the softest
    // datum on the card (often a generic "solid day room setup") and it was the
    // tallest block, pushing price and slot down; the offer now reads first.
    return `
        <div class="hotel-card">
            ${renderImageCarousel(imageCarouselId, images, hotel, discount)}
            <div class="hotel-content">
                ${renderHotelHeader(hotel, safeStars)}
                ${renderTimeslots(hotel)}
                ${renderAIRecommendation(hotel)}
                ${renderFooter(priceInfo, originalPrice, hotelUrl, hotel.name, hotelNumericId)}
            </div>
        </div>
    `;
}

function renderImageCarousel(hotelId, images, hotel, discount) {
    const safeHotelId = escapeAttr(hotelId);
    const safeAlt = escapeAttr(hotel.name || 'Hotel');
    const fallbackImage = 'https://images.dayuse.com/hotels/default/default.jpg';
    return `
        <div class="image-carousel" id="carousel-${safeHotelId}">
            <div class="image-carousel-wrapper js-image-carousel-wrapper" data-hotel-id="${safeHotelId}">
                ${images.map(url => `
                    <img
                        class="carousel-image"
                        src="${escapeAttr(url)}"
                        alt="${safeAlt}"
                        data-fallback-src="${fallbackImage}"
                    >
                `).join('')}
            </div>
            ${hotel.has_pool ? `<div class="pool-badge">${t('pool_access_included')}</div>` : ''}
            ${discount && discount > 0 ? `<div class="deal-badge">-${Math.round(discount)}%</div>` : ''}
            ${images.length > 1 ? `
                <div class="carousel-dots">
                    ${images.map((_, index) => `
                        <div class="carousel-dot ${index === 0 ? 'active' : ''}"
                             data-carousel="${safeHotelId}"
                             data-index="${index}"></div>
                    `).join('')}
                </div>
                <button class="image-carousel-button image-carousel-prev" data-action="image-prev" data-hotel-id="${safeHotelId}">←</button>
                <button class="image-carousel-button image-carousel-next" data-action="image-next" data-hotel-id="${safeHotelId}">→</button>
            ` : ''}
        </div>
    `;
}

function renderHotelHeader(hotel, safeStars) {
    // Determine location: prefer zone, then city, then extract from name
    const location = hotel.zone || hotel.city || extractLocationFromName(hotel.name) || '';

    // S-CX9: the guest rating, on the one row of the card that had spare width.
    // `rating`/`rating_count` have been on the search payload since S-CX3a
    // (response_bridge.normalize_hotel) and were only ever read by the booking
    // card — the shortlist was asking for a decision while withholding the
    // trust signal the user was going to be shown one click later.
    const rating = Number(hotel.rating);
    const ratingHtml = Number.isFinite(rating) && rating > 0
        ? `<span class="hotel-rating">${escapeHtml(formatRating(rating))}/5${
            hotel.rating_count ? ` <span class="hotel-rating__count">(${escapeHtml(String(hotel.rating_count))})</span>` : ''
        }</span>`
        : '';

    return `
        <div class="hotel-header">
            <div class="hotel-head-row">
                <div class="stars" aria-hidden="true">
                    ${Array(safeStars).fill('<img src="/static/icon/star.svg" alt="">').join('')}
                </div>
                ${location ? `<span class="hotel-neighborhood">${escapeHtml(location)}</span>` : ''}
                ${ratingHtml}
            </div>
            <div class="hotel-name">${escapeHtml(hotel.name || 'Hotel')}</div>
            ${renderBadges(hotel)}
        </div>
    `;
}

/**
 * Extract location from hotel name (e.g., "Hyatt House - White Plains" -> "White Plains")
 */
function extractLocationFromName(name) {
    if (!name) return null;
    // Try to extract location after " - " (common format)
    const dashMatch = name.match(/ - (.+)$/);
    if (dashMatch) return dashMatch[1];
    return null;
}

function renderBadges(hotel) {
    if (!hotel.badges || hotel.badges.length === 0) return '';

    const badgeConfig = {
        'best_value': { label: t('badge_best_value'), icon: '🔥', cssClass: 'hotel-badge--best-value' },
        'popular': { label: t('badge_popular'), icon: '<img src="/static/icon/star.svg" alt="">', cssClass: 'hotel-badge--popular' },
        'best_rated': { label: t('badge_best_rated'), icon: '<img src="/static/icon/star.svg" alt="">', cssClass: 'hotel-badge--best-rated' }
    };

    const badges = hotel.badges.map(badge => {
        const config = badgeConfig[badge];
        if (config) {
            return `<span class="hotel-badge ${config.cssClass}">${config.icon} ${config.label}</span>`;
        }
        return '';
    }).join('');

    return `<div class="hotel-badges">${badges}</div>`;
}

function renderAIRecommendation(hotel) {
    // Priority: personalized line > ai_recommendation > match_explanation > highlights
    const language = getLanguage();
    let text = hotel.ai_recommendation || buildPersonalizedSnippet(hotel) || (language === 'en' ? hotel.match_explanation : null);

    // If no AI text, use highlights
    if (!text && language === 'en' && hotel.highlights && hotel.highlights.length > 0) {
        // Filter out reviews (they often contain personal experiences, complaints, prices)
        const isReview = (h) => {
            if (!h) return true;
            const lower = h.toLowerCase();
            return (
                lower.includes('i ') ||           // Personal pronoun
                lower.includes('my ') ||          // Personal pronoun
                lower.includes('we ') ||          // Personal pronoun
                lower.includes('was $') ||        // Price complaint
                lower.includes('went to $') ||    // Price complaint
                lower.includes('charged') ||      // Complaint
                lower.includes('disappointed') || // Negative
                lower.includes('terrible') ||     // Negative
                lower.includes('worst') ||        // Negative
                lower.includes('never again') ||  // Negative
                lower.includes('rude') ||         // Negative
                lower.includes('dirty')           // Negative
            );
        };

        // First try to find a short, service-focused highlight (not a review)
        const serviceHighlight = hotel.highlights.find(h =>
            h && h.length < 100 && !isReview(h) && (
                h.toLowerCase().includes('free') ||
                h.toLowerCase().includes('complimentary') ||
                h.toLowerCase().includes('shuttle') ||
                h.toLowerCase().includes('breakfast') ||
                h.toLowerCase().includes('parking') ||
                h.toLowerCase().includes('wifi') ||
                h.toLowerCase().includes('pool') ||
                h.toLowerCase().includes('spa') ||
                h.toLowerCase().includes('gym') ||
                h.toLowerCase().includes('fitness') ||
                h.toLowerCase().includes('location') ||
                h.toLowerCase().includes('view') ||
                h.toLowerCase().includes('modern') ||
                h.toLowerCase().includes('spacious')
            )
        );

        if (serviceHighlight) {
            text = serviceHighlight;
        } else {
            // Find first non-review highlight
            const goodHighlight = hotel.highlights.find(h => h && !isReview(h));
            if (goodHighlight) {
                text = goodHighlight.length > 100
                    ? goodHighlight.substring(0, 97).replace(/\s+\S*$/, '') + '...'
                    : goodHighlight;
            }
        }
    }

    if (!text) return '';

    // Concierge layout — keep a single short sentence (≤ 140 chars).
    text = trimToShortSentence(text, 140);

    return `
        <div class="ai-recommendation">
            <span class="ai-glyph" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 13.9 8.1 20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2Z"/><path d="M19 14l.95 3.05L23 18l-3.05.95L19 22l-.95-3.05L15 18l3.05-.95L19 14Z" opacity=".7"/></svg>
            </span>
            <span class="ai-text">${escapeHtml(text)}</span>
        </div>
    `;
}

/**
 * Trim AI insight to a single short sentence. Keeps the first sentence terminator
 * (. ! ?) if it fits under `maxLen`; otherwise truncates on a word boundary.
 */
function trimToShortSentence(text, maxLen = 140) {
    const raw = String(text || '').trim().replace(/\s+/g, ' ');
    if (!raw) return '';

    const firstSentence = raw.match(/^[^.!?\n]+[.!?](?=\s|$)/);
    if (firstSentence && firstSentence[0].length <= maxLen) {
        return firstSentence[0].trim();
    }

    if (raw.length <= maxLen) return raw;

    const cut = raw.slice(0, maxLen - 1);
    const safeCut = cut.replace(/\s+\S*$/, '');
    return (safeCut || cut).trim() + '…';
}

function buildPersonalizedSnippet(hotel) {
    const lang = getLanguage();
    const tr = (en, fr, es) => (lang === 'fr' ? fr : (lang === 'es' ? es : en));
    const query = (state.currentUserQuery || '').toLowerCase();
    const zone = hotel.zone || hotel.city || tr('this area', 'cette zone', 'esta zona');
    const seed = String(hotel.id || hotel.hotel_id || hotel.name || '');

    const priceInfo = parsePrice(hotel.price || hotel.min_price_ttc || 0, hotel.display_currency);
    const budget = state.selectedFilters.budget_max;
    const underBudget = typeof budget === 'number' && priceInfo.value > 0 && priceInfo.value <= budget;
    const nearBudget = typeof budget === 'number' && priceInfo.value > 0 && priceInfo.value > budget * 0.8;
    const isLuxury = (hotel.stars || 0) >= 4;

    const airportLike = query.includes('layover') || query.includes('airport')
        || String(zone).toLowerCase().includes('airport');
    if (airportLike) {
        const option1 = tr(
            `Smart layover pick near ${zone}, with easy access for a quick reset between flights.`,
            `Bon choix pour une escale près de ${zone}, avec un accès simple pour se reposer entre deux vols.`,
            `Buena opción para escala cerca de ${zone}, con acceso fácil para descansar entre vuelos.`,
        );
        const option2 = tr(
            `Convenient airport-area option in ${zone}, ideal for a short daytime break.`,
            `Option pratique dans la zone de ${zone}, idéale pour une courte pause en journée.`,
            `Opción práctica en la zona de ${zone}, ideal para una pausa corta durante el día.`,
        );
        const sentence1 = pickVariant(seed + ':airport', [option1, option2]);
        const sentence2 = hotel.has_pool
            ? tr(
                `Pool access keeps it comfortable${underBudget ? ` while staying well under your $${Math.round(budget)} budget` : ''}.`,
                `L'accès piscine garde un bon niveau de confort${underBudget ? ` tout en restant sous votre budget de $${Math.round(budget)}` : ''}.`,
                `El acceso a piscina mantiene un buen nivel de confort${underBudget ? ` y se mantiene por debajo de tu presupuesto de $${Math.round(budget)}` : ''}.`,
            )
            : tr(
                `Straightforward and efficient for the window you described${underBudget ? `, and still under your $${Math.round(budget)} budget` : ''}.`,
                `Simple et efficace pour le créneau que vous avez décrit${underBudget ? `, et toujours sous votre budget de $${Math.round(budget)}` : ''}.`,
                `Simple y eficiente para la franja que describiste${underBudget ? `, y aun por debajo de tu presupuesto de $${Math.round(budget)}` : ''}.`,
            );
        return `${sentence1} ${sentence2}`;
    }

    const visualVibe = query.includes('instagram') || query.includes('view') || query.includes('rooftop')
        || query.includes('vibe') || query.includes('photogenic');
    if (visualVibe && hotel.has_pool) {
        const sentence1 = pickVariant(seed + ':vibe_pool', [
            tr(
                `Strong fit for your vibe: pool access with a ${zone} atmosphere${isLuxury ? ' and an upscale feel' : ''}.`,
                `Très bon fit avec votre ambiance : accès piscine dans une atmosphère ${zone}${isLuxury ? ' avec une touche premium' : ''}.`,
                `Muy buen encaje con tu vibra: acceso a piscina en ambiente ${zone}${isLuxury ? ' con un toque premium' : ''}.`,
            ),
            tr(
                `Rooftop-style energy in ${zone} with pool access${isLuxury ? ' and a polished feel' : ''}.`,
                `Énergie rooftop à ${zone} avec accès piscine${isLuxury ? ' et une sensation haut de gamme' : ''}.`,
                `Energía tipo rooftop en ${zone} con acceso a piscina${isLuxury ? ' y una sensación de alta gama' : ''}.`,
            ),
        ]);
        const sentence2 = nearBudget
            ? tr(
                `It gives you the "wow" factor without blowing past your budget.`,
                `Vous gardez l'effet "wow" sans dépasser votre budget.`,
                `Te da efecto "wow" sin pasarte del presupuesto.`,
            )
            : tr(
                `It balances style and value for the kind of day you asked for.`,
                `Bon équilibre entre style et valeur pour le type de journée que vous cherchez.`,
                `Equilibrio entre estilo y valor para el tipo de día que buscabas.`,
            );
        return `${sentence1} ${sentence2}`;
    }
    if (visualVibe) {
        return pickVariant(seed + ':vibe', [
            tr(
                `Stylish atmosphere in ${zone} that matches the vibe you described.`,
                `Atmosphère élégante à ${zone} qui correspond à l'ambiance décrite.`,
                `Ambiente elegante en ${zone} que encaja con la vibra que describiste.`,
            ),
            tr(
                `Aesthetic-forward option in ${zone} that stays aligned with your mood.`,
                `Option très esthétique à ${zone}, bien alignée avec votre mood.`,
                `Opción muy estética en ${zone}, alineada con tu estilo.`,
            ),
        ]);
    }

    const wantsPool = Array.isArray(state.selectedFilters.amenities)
        && state.selectedFilters.amenities.includes('pool');
    if (wantsPool && hotel.has_pool) {
        return pickVariant(seed + ':pool', [
            tr(
                `Pool access in ${zone} with a solid day-room setup for your plan.`,
                `Accès piscine à ${zone} avec une configuration day room très solide pour votre plan.`,
                `Acceso a piscina en ${zone} con una configuración day room muy sólida para tu plan.`,
            ),
            tr(
                `Pool option in ${zone}, comfortable and easy for a daytime stay.`,
                `Option piscine à ${zone}, confortable et simple pour une pause en journée.`,
                `Opción con piscina en ${zone}, cómoda y fácil para una estancia diurna.`,
            ),
            tr(
                `Day-room with pool access in ${zone}, practical and relaxed.`,
                `Day room avec accès piscine à ${zone}, pratique et détendu.`,
                `Day room con acceso a piscina en ${zone}, práctico y relajado.`,
            ),
        ]);
    }

    if (hotel.selling_points && hotel.selling_points.length > 0) {
        const point = (hotel.selling_points[0] || '').trim();
        if (point && lang === 'en' && !looksGenericBudgetLine(point)) {
            return pickVariant(seed + ':point', [
                `${point}. Keeps the experience aligned with your request.`,
                `${point}. A straightforward fit for what you described.`,
            ]);
        }
    }

    return null;
}

function looksGenericBudgetLine(text) {
    const lower = (text || '').toLowerCase();
    return lower.startsWith('within budget') || lower.includes('budget at $');
}

function pickVariant(seed, options) {
    if (!options.length) return '';
    let hash = 0;
    for (let i = 0; i < seed.length; i += 1) {
        hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
    }
    return options[hash % options.length];
}

function dedupeTimeslots(timeslots, limit = 4) {
    if (!Array.isArray(timeslots) || timeslots.length === 0) return [];
    const seen = new Set();
    const unique = [];

    for (const slot of timeslots) {
        if (!slot || !slot.start || !slot.end) continue;
        const key = `${slot.start}-${slot.end}`;
        if (seen.has(key)) continue;
        seen.add(key);
        unique.push(slot);
        if (unique.length >= limit) break;
    }

    return unique;
}

function hasExactTimeslotMatch(hotel) {
    const reasons = Array.isArray(hotel.match_reasons) ? hotel.match_reasons : [];
    if (reasons.length > 0) {
        const exactReasons = new Set([
            'time_fit=exact_start',
            'time_fit=contains_requested_start',
            'time_fit=exact_end',
            'time_fit=contains_requested_end',
            'time_fit=contains_requested_window',
        ]);
        if (reasons.some(reason => exactReasons.has(reason))) return true;

        const closeReasonPrefixes = [
            'time_fit=next_start_',
            'time_fit=closest_end_',
            'time_fit=late_start',
            'time_fit=no_start_match',
            'time_fit=early_end',
            'time_fit=no_end_match',
            'time_fit=partial_window_',
            'time_fit=minimal_window_overlap_',
            'time_fit=no_window_overlap',
        ];
        if (reasons.some(reason => closeReasonPrefixes.some(prefix => reason.startsWith(prefix)))) {
            return false;
        }
    }

    const warnings = Array.isArray(hotel.mismatch_warnings) ? hotel.mismatch_warnings : [];
    const warningText = warnings.join(' ').toLowerCase();
    if (
        warningText.includes('no exact')
        || warningText.includes('closest')
        || warningText.includes('partial overlap')
        || warningText.includes('overlap is limited')
    ) {
        return false;
    }

    return false;
}

function hasRequestedTimeslotFilter() {
    return state.selectedFilters.requested_start_hour != null
        || state.selectedFilters.requested_end_hour != null
        || Boolean(state.selectedFilters.timeslot);
}

function getTimeslotMatchLevel(hotel) {
    const explicitLevel = typeof hotel.timeslot_match_level === 'string'
        ? hotel.timeslot_match_level.toLowerCase().trim()
        : '';

    if (explicitLevel === 'exact' || explicitLevel === 'close' || explicitLevel === 'none' || explicitLevel === 'not_requested') {
        return explicitLevel;
    }

    if (!hasRequestedTimeslotFilter()) {
        return 'not_requested';
    }

    return hasExactTimeslotMatch(hotel) ? 'exact' : 'close';
}

/**
 * S-CX9 — the label next to the slot pill, DROPPED when it makes no claim.
 *
 * "Available time slots" restates what a clock pill already says, and it was
 * taking the row's spare width from the pill. The other three levels are not
 * decoration: they are the S-G6 guard telling the user this slot is not the one
 * they asked for ("closest match", "near your window"). Those stay — a card that
 * silently shows 07:00-13:00 for a 07:30 ask is the defect that guard exists to
 * prevent.
 */
function renderTimeslotLabel(matchLevel, label, labelClass) {
    if (matchLevel === 'not_requested') return '';
    return `<div class="timeslot-label ${labelClass}">${label}</div>`;
}

function renderTimeslots(hotel) {
    if (!hotel.timeslots || hotel.timeslots.length === 0) return '';

    const clockSvg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';

    // Backend already computes slots matching the requested window.
    if (hotel.matched_timeslots && hotel.matched_timeslots.length > 0) {
        const matchLevel = getTimeslotMatchLevel(hotel);
        const matchedSlots = dedupeTimeslots(hotel.matched_timeslots, 1);
        const slot = matchedSlots[0] || hotel.matched_timeslots[0];

        const label = matchLevel === 'exact'
            ? t('slot_label_matched')
            : (matchLevel === 'close'
                ? t('slot_label_near')
                : (matchLevel === 'none' ? t('closest_matching_timeslots') : t('available_timeslots')));
        const labelClass = (matchLevel === 'exact' || matchLevel === 'close')
            ? 'timeslot-label--matched'
            : 'timeslot-label--default';
        const pillClass = matchLevel === 'exact'
            ? 'timeslot-pill--matched'
            : (matchLevel === 'close' ? 'timeslot-pill--near' : 'timeslot-pill--default');

        const slotRange = formatSlotRange(slot.start, slot.end, getLanguage());

        return `
            <div class="timeslot-section">
                ${renderTimeslotLabel(matchLevel, label, labelClass)}
                <div class="timeslot-pills">
                    <span class="timeslot-pill ${pillClass}">${clockSvg} ${slotRange}</span>
                </div>
            </div>
        `;
    }

    let filteredSlots = hotel.timeslots.filter(slot => {
        const startHour = parseInt((slot.start || '00:00').split(':')[0]);
        const endHour = parseInt((slot.end || '00:00').split(':')[0]) || 24;

        if (state.selectedFilters.requested_start_hour != null && state.selectedFilters.requested_end_hour != null) {
            const reqStart = state.selectedFilters.requested_start_hour;
            const reqEnd = state.selectedFilters.requested_end_hour;
            return startHour <= reqStart && endHour >= reqEnd;
        }

        if (state.selectedFilters.timeslot) {
            if (state.selectedFilters.timeslot === 'early') return startHour >= 7 && startHour <= 10;
            if (state.selectedFilters.timeslot === 'day') return startHour >= 10 && startHour < 17;
            if (state.selectedFilters.timeslot === 'late') return startHour >= 17;
            if (!isNaN(state.selectedFilters.timeslot)) {
                const reqHour = parseInt(state.selectedFilters.timeslot);
                return startHour <= reqHour && endHour > reqHour;
            }
        }

        return true;
    });

    const hasRequestedWindow = hasRequestedTimeslotFilter();
    if (filteredSlots.length === 0) filteredSlots = hotel.timeslots;
    const dedupedFallbackSlots = dedupeTimeslots(filteredSlots, 1);
    const slot = dedupedFallbackSlots[0] || filteredSlots[0];
    const slotRange = formatSlotRange(slot.start, slot.end, getLanguage());

    return `
        <div class="timeslot-section">
            ${renderTimeslotLabel(
                hasRequestedWindow ? 'none' : 'not_requested',
                hasRequestedWindow ? t('closest_matching_timeslots') : t('available_timeslots'),
                'timeslot-label--default',
            )}
            <div class="timeslot-pills">
                <span class="timeslot-pill timeslot-pill--default">${clockSvg} ${slotRange}</span>
            </div>
        </div>
    `;
}

/**
 * The card's single action (QA 2026-09-23, replaces S-CX9's two).
 *
 * "Choisir cet hôtel" now LEAVES for the hotel page on dayuse.com. It used to
 * open the in-chat booking card (rate-plan selector) while a second, demoted
 * "Voir la fiche de l'hôtel" link did what users actually expected — product
 * decision: one button, straight to the hotel page. Evening-blue is kept: the
 * warm gradient stays reserved for `.booking-card__cta` (hotels.css).
 */
function renderFooter(priceInfo, originalPrice, hotelUrl, hotelName, hotelId) {
    // '' when the payload carried no usable url (UX6 2026-08-28). Never coerce
    // it to '#': a link that goes nowhere reads as a broken button. The card
    // drops its button instead — see `chooseHtml` below.
    const safeHotelUrl = sanitizeDayuseUrl(hotelUrl || '') || '';
    const safeHotelUrlAttr = escapeAttr(safeHotelUrl);
    const safeHotelNameAttr = escapeAttr(String(hotelName || ''));
    const safeHotelIdAttr = escapeAttr(String(hotelId || ''));
    const safeHotelPriceAttr = escapeAttr(String(priceInfo.value ? Math.round(priceInfo.value) : ''));

    // Currency spacing is already baked into the display symbol (glyphs hug the
    // number — "€139"; ISO codes carry a trailing space — "CHF 139") by
    // CURRENCY_SYMBOLS / detectCurrencySymbol, so render it as-is.
    const currencyPrefix = priceInfo.currency;
    const hasPrice = Boolean(priceInfo.value && priceInfo.value > 0);
    // The night rate this day-use price undercuts. The percentage itself now
    // lives on the photo (`deal-badge`) where it is scannable; the struck-through
    // rate stays next to the price, which is the only place it means anything.
    const hasNightRate = hasPrice && originalPrice && originalPrice > 0;

    // S-CX8: this price is the cheapest of the hotel's formulas for the day, and
    // says so. Unlabelled, it read as THE price — so a user who picked the hotel
    // and met a pricier formula in the booking card had been misled by a number
    // that was accurate but not the whole offer. S-CX9 only puts the qualifier on
    // the price's own baseline instead of on a line of its own.
    const priceHtml = hasPrice
        ? `<div class="price-section">
               <span class="price-from-label">${t('card_from_label')}</span>
               <span class="current-price">${currencyPrefix}${priceInfo.display}</span>
               ${hasNightRate ? `<span class="original-price">${currencyPrefix}${Math.round(originalPrice)}${t('night_suffix')}</span>` : ''}
           </div>`
        : '';

    // `data-track-hotel-click` + these four attributes are what tracking.js reads
    // off the hotel-page link (ui/messages.js); unchanged so the event keeps its
    // meaning now that the primary button carries it.
    const hotelLinkAttrs = `href="${safeHotelUrlAttr}" target="_blank" rel="noopener noreferrer"
               data-track-hotel-click="1"
               data-hotel-name="${safeHotelNameAttr}"
               data-hotel-id="${safeHotelIdAttr}"
               data-hotel-price="${safeHotelPriceAttr}"
               data-hotel-url="${safeHotelUrlAttr}"`;

    // No url → no button at all (UX6 2026-08-28): the card still shows its
    // price, it just stops promising a page it cannot reach. Before UX6 an
    // unmapped country got a fabricated /hotels/usa/<slugified-name> link that 404'd.
    const chooseHtml = safeHotelUrl
        ? `<a ${hotelLinkAttrs} class="pick-cta">${t('card_pick_cta')}</a>`
        : '';

    return `
        <div class="hotel-card-footer">
            ${priceHtml}
            ${chooseHtml}
        </div>
    `;
}

/**
 * Book hotel action
 */
export function bookHotel(hotelName, hotelId, hotelPrice) {
    const hotel = state.previousResults.find(h => h.name === hotelName);
    const hotelUrl = hotel && hotel.url ? sanitizeDayuseUrl(hotel.url) : null;

    trackEvent('hotel_card_click', {
        hotel_name: hotelName,
        hotel_id: hotelId,
        price: hotelPrice,
        url: hotelUrl,
        intent: 'booking'
    });

    if (hotelUrl) {
        window.open(hotelUrl, '_blank');
    }
}
