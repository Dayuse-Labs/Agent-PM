/**
 * Message UI
 * Add messages to chat, handle content rendering
 */

import { scrollBehavior } from '../motion.js';
import { state } from '../state.js';
import { getLanguage, t } from '../i18n.js';
import { formatSlotRange } from '../slot_time.js';
import { escapeAttr, escapeHtml, sanitizeDayuseUrl, sanitizeImageUrl } from '../security.js';
import { formatBackendPrice, parsePrice } from '../hotels/card.js';
import { formatRating } from '../utils.js';
import { submitFeedback } from '../feedback.js';
import {
    appendAmplitudeIdToUrl,
    trackBookingCardClick,
    trackFeedbackSubmit,
    trackHotelClick,
    trackSuggestionClick,
} from '../tracking.js';

function renderInlineText(rawText) {
    const text = String(rawText ?? '');
    const regex = /\*\*(.+?)\*\*/g;
    let last = 0;
    let match;
    let out = '';
    while ((match = regex.exec(text)) !== null) {
        out += escapeHtml(text.slice(last, match.index));
        out += `<strong>${escapeHtml(match[1])}</strong>`;
        last = regex.lastIndex;
    }
    out += escapeHtml(text.slice(last));
    return out;
}

function formatPlainAssistantText(content) {
    if (!content) return '';

    let normalized = String(content).replace(/\r\n/g, '\n');
    if (!normalized.includes('\n') && normalized.length > 220 && normalized.includes(' - ')) {
        const pieces = normalized.split(' - ');
        if (pieces.length >= 3) {
            const header = pieces.shift();
            normalized = `${header}\n${pieces.map(p => `- ${p}`).join('\n')}`;
        }
    }
    const lines = normalized.split('\n');
    const chunks = [];
    let inList = false;

    const closeList = () => {
        if (inList) {
            chunks.push('</ul>');
            inList = false;
        }
    };

    for (const rawLine of lines) {
        const line = rawLine.trim();

        if (!line) {
            closeList();
            chunks.push('<div class="md-spacer"></div>');
            continue;
        }

        const headingMatch = line.match(/^#{1,3}\s+(.+)/);
        if (headingMatch) {
            closeList();
            chunks.push(`<div class="md-heading">${renderInlineText(headingMatch[1])}</div>`);
            continue;
        }

        const bulletMatch = line.match(/^[-*]\s+(.+)/);
        if (bulletMatch) {
            if (!inList) {
                chunks.push('<ul class="md-list">');
                inList = true;
            }
            chunks.push(`<li>${renderInlineText(bulletMatch[1])}</li>`);
            continue;
        }

        closeList();
        chunks.push(`<div>${renderInlineText(line)}</div>`);
    }

    closeList();
    return chunks.join('');
}

/**
 * Add a message to the chat
 */
export function addMessage(content, isUser = false, isHotelResults = false, skipScroll = false, trustedHtml = false) {
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user' : 'bot'}`;
    if (!isUser && state.currentTurnId) messageDiv.dataset.turnId = state.currentTurnId;
    messageDiv.style.opacity = '0';
    messageDiv.style.transform = 'translateY(20px)';
    messageDiv.style.transition = 'opacity 0.3s ease-in-out, transform 0.3s ease-in-out';

    const avatar = document.createElement('div');
    avatar.className = `avatar ${isUser ? 'avatar--user' : 'avatar--ai'}`;
    avatar.setAttribute('aria-hidden', 'true');
    if (!isUser) {
        avatar.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2 13.9 8.1 20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2Z"/><path d="M19 14l.95 3.05L23 18l-3.05.95L19 22l-.95-3.05L15 18l3.05-.95L19 14Z" opacity=".7"/></svg>';
    }

    const messageContent = document.createElement('div');
    messageContent.className = `message-content ${isHotelResults ? 'with-hotels' : ''}`;

    if (isUser) {
        messageContent.textContent = String(content || '');
    } else if (typeof content === 'string') {
        let renderAsTrustedHtml = Boolean(trustedHtml || isHotelResults);

        // Handle [CARTE:hotelName] tags
        const cardMatch = String(content).match(/\[CARTE:(.*?)\]/);
        if (cardMatch) {
            const hotelName = cardMatch[1];
            const hotel = state.previousResults.find(h => h.name === hotelName);

            if (hotel) {
                // hotel.price is a formatted string ("from €139.00"); parse it so
                // the inline card shows the real amount + currency, not "NaNSGD".
                const priceInfo = parsePrice(hotel.price || hotel.min_price_ttc || 0, hotel.display_currency);
                const currencyPrefix = ['$', '€', '£', '¥', '₹', '₩'].includes(priceInfo.currency)
                    ? priceInfo.currency
                    : `${priceInfo.currency} `;
                const formattedPrice = priceInfo.value > 0 ? `${currencyPrefix}${priceInfo.display}` : '';
                const safeName = escapeHtml(hotel.name || '');
                const safeNameAttr = escapeAttr(hotel.name || '');
                const safeHotelId = escapeAttr(String(hotel.id || hotel.hotel_id || ''));
                const safeHotelPrice = escapeAttr(String(priceInfo.value ? Math.round(priceInfo.value) : ''));
                const safeImage = sanitizeImageUrl(
                    hotel.image_urls && hotel.image_urls.length > 0
                        ? hotel.image_urls[0]
                        : 'https://images.dayuse.com/hotels/default/default.jpg'
                ) || 'https://images.dayuse.com/hotels/default/default.jpg';
                const simplifiedCard = `
                    <div class="hotel-card simplified">
                        <img
                            class="hotel-image"
                            src="${safeImage}"
                            alt="${safeNameAttr}"
                            data-fallback-src="https://images.dayuse.com/hotels/default/default.jpg"
                        >
                        <div class="hotel-content">
                            <div>
                                <div class="hotel-name">${safeName}</div>
                                ${formattedPrice ? `<div class="current-price">${formattedPrice}</div>` : ''}
                            </div>
                            <button class="book-button"
                                data-action="book-hotel"
                                data-hotel-name="${safeNameAttr}"
                                data-hotel-id="${safeHotelId}"
                                data-hotel-price="${safeHotelPrice}">
                                ${t('card_see_hotel')}
                            </button>
                        </div>
                    </div>
                `;
                content = content.replace(/\[CARTE:.*?\]/, simplifiedCard);
                renderAsTrustedHtml = true;
            } else {
                content = content.replace(/\[CARTE:.*?\]/, '');
            }
        }

        if (renderAsTrustedHtml) {
            messageContent.innerHTML = sanitizeTrustedHtml(content);
        } else {
            messageContent.innerHTML = formatPlainAssistantText(content);
        }
    } else {
        messageContent.textContent = String(content || '');
    }

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(messageContent);
    messagesDiv.appendChild(messageDiv);

    // Bind interactive elements rendered in trusted local components.
    bindMessageContentInteractions(messageContent);

    // Force reflow for animation
    void messageDiv.offsetWidth;

    messageDiv.style.opacity = '1';
    messageDiv.style.transform = 'translateY(0)';

    // Smooth scroll to bottom
    if (!skipScroll) {
        setTimeout(() => {
            messagesDiv.scrollTo({
                top: messagesDiv.scrollHeight,
                behavior: scrollBehavior()
            });
        }, 100);
    }

    return messageDiv;
}

/**
 * Setup click handlers for booking links without valid URLs
 */
function setupBookingLinkHandlers(messageContent) {
    messageContent.querySelectorAll('a[href="#"]').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const parentDiv = link.closest('div[style*="background"]');
            if (parentDiv) {
                const hotelNameElement = parentDiv.querySelector('strong');
                if (hotelNameElement) {
                    const hotelName = hotelNameElement.textContent.replace(/🏨\s*/, '').trim();
                    const hotel = state.previousResults.find(h =>
                        h.name === hotelName || hotelName.includes(h.name) || h.name.includes(hotelName)
                    );
                    if (hotel && hotel.url) {
                        window.open(hotel.url, '_blank');
                    } else {
                        alert(t('no_booking_link_alert'));
                    }
                }
            }
        });
    });
}

function bindMessageContentInteractions(messageContent) {
    setupBookingLinkHandlers(messageContent);
    setupFallbackImages(messageContent);
    setupHotelTrackingLinks(messageContent);
    setupCtaTrackingLinks(messageContent);
    setupActionHandlers(messageContent);
    setupImageCarouselHandlers(messageContent);
}

function setupFallbackImages(messageContent) {
    messageContent.querySelectorAll('img[data-fallback-src]').forEach(img => {
        if (img.dataset.fallbackBound === '1') return;
        img.dataset.fallbackBound = '1';
        img.addEventListener('error', () => {
            const fallbackSrc = String(img.dataset.fallbackSrc || '').trim();
            if (!fallbackSrc || img.src === fallbackSrc) return;
            img.src = fallbackSrc;
        });
    });
}

function renderingTurnId(element) {
    return element.closest('.message')?.dataset.turnId || '';
}

function hotelCardPosition(card) {
    const siblings = card.parentElement
        ? Array.from(card.parentElement.querySelectorAll(':scope > .hotel-card'))
        : [];
    return Math.max(1, siblings.indexOf(card) + 1);
}

function chipPosition(chip) {
    const siblings = chip.parentElement
        ? Array.from(chip.parentElement.querySelectorAll(':scope > .chip'))
        : [];
    return Math.max(1, siblings.indexOf(chip) + 1);
}

function trackHotelCardElementClick(element, clickedElement) {
    const card = element.closest('.hotel-card');
    if (!card) return;
    trackHotelClick({
        turnId: renderingTurnId(element),
        hotelId: element.dataset.hotelId,
        position: hotelCardPosition(card),
        clickedElement,
    });
}

function setupHotelTrackingLinks(messageContent) {
    messageContent.querySelectorAll('a[data-track-hotel-click]').forEach(link => {
        if (link.dataset.trackBound === '1') return;
        link.dataset.trackBound = '1';
        link.addEventListener('click', () => {
            trackHotelCardElementClick(link, link.dataset.trackHotelClick);
        });
    });
}

function setupCtaTrackingLinks(messageContent) {
    messageContent.querySelectorAll('a[data-track-booking-card-click="1"]').forEach(link => {
        if (link.dataset.ctaTrackBound === '1') return;
        link.dataset.ctaTrackBound = '1';
        link.addEventListener('click', () => {
            trackBookingCardClick({
                turnId: renderingTurnId(link),
                hotelId: link.dataset.hotelId,
                ratePlanId: link.dataset.ratePlanId,
            });
        });
    });
}

/**
 * S-CX8 — move the card's selection to `row` and re-point everything the choice
 * governs: the tunnel link, its label, the slot fact and the headline price.
 *
 * Scoped to the row's OWN card (`closest('.booking-card')`): a thread can hold
 * several booking cards, and a global query would repaint all of them.
 */
function selectRatePlan(row) {
    const card = row.closest('.booking-card');
    if (!card || row.classList.contains('is-selected')) return;

    card.querySelectorAll('.booking-card__plan').forEach(other => {
        const isTarget = other === row;
        other.classList.toggle('is-selected', isTarget);
        other.setAttribute('aria-pressed', isTarget ? 'true' : 'false');
    });

    // Re-sanitized rather than trusted from the DOM: the attribute passed the
    // allowlist at render time, but this is the value about to become an href.
    const url = sanitizeDayuseUrl(String(row.dataset.planUrl || ''));
    const cta = card.querySelector('.booking-card__cta');
    if (cta && url) {
        cta.setAttribute('href', url);
        cta.dataset.ratePlanId = String(row.dataset.planId || '');
    }

    const title = String(row.dataset.planTitle || '');
    const ctaLabel = cta && cta.querySelector('[data-plan-cta-label="1"]');
    if (ctaLabel) {
        // Same cap as the initial render, or the button's label would fit on
        // first paint and clip after a click on a long-named formula.
        ctaLabel.textContent = row.dataset.planNamed === '1'
            && title && title.length <= CTA_PLAN_NAME_MAX
            ? t('card_book_plan', { plan: title })
            : t('card_book_cta');
    }

    const slotTarget = card.querySelector('[data-plan-slot-target="1"]');
    const slot = String(row.dataset.planSlot || '');
    if (slotTarget && slot) slotTarget.textContent = slot;

    const priceTarget = card.querySelector('[data-plan-price-target="1"]');
    const price = String(row.dataset.planPrice || '');
    if (priceTarget && price) priceTarget.textContent = formatBackendPrice(price);
}

function setupActionHandlers(messageContent) {
    messageContent.querySelectorAll('[data-action]').forEach(element => {
        if (element.dataset.actionBound === '1') return;
        element.dataset.actionBound = '1';
        element.addEventListener('click', (event) => {
            const action = String(element.dataset.action || '');
            if (!action) return;

            switch (action) {
                case 'select-rate-plan': {
                    // S-CX8: picking a formula only re-points the card at a link
                    // the backend already generated for it — no request, no turn.
                    event.preventDefault();
                    selectRatePlan(element);
                    return;
                }
                case 'book-hotel': {
                    event.preventDefault();
                    const hotelName = String(element.dataset.hotelName || '');
                    const hotelId = String(element.dataset.hotelId || '');
                    const hotelPrice = Number(element.dataset.hotelPrice || 0);
                    window.chatApp?.bookHotel?.(hotelName, hotelId, hotelPrice);
                    return;
                }
                case 'scroll-carousel': {
                    event.preventDefault();
                    const carouselId = String(element.dataset.carouselId || '');
                    const direction = Number(element.dataset.direction || 0);
                    window.chatApp?.scrollCarousel?.(carouselId, direction);
                    return;
                }
                case 'follow-up': {
                    event.preventDefault();
                    const followUp = String(element.dataset.followUp || '');
                    trackSuggestionClick({
                        turnId: renderingTurnId(element),
                        suggestionType: 'timeslot_refine',
                        position: chipPosition(element),
                    });
                    window.chatApp?.handleFollowUp?.(followUp);
                    return;
                }
                case 'apply-chip':
                    event.preventDefault();
                    window.chatApp?.applyChip?.(element);
                    return;
                case 'apply-suggestion':
                    event.preventDefault();
                    window.chatApp?.applySuggestion?.(element);
                    return;
                case 'apply-clarify-option':
                    event.preventDefault();
                    window.chatApp?.applyClarifyOption?.(element);
                    return;
                case 'image-prev':
                    event.preventDefault();
                    event.stopPropagation();
                    window.chatApp?.prevImage?.(String(element.dataset.hotelId || ''));
                    return;
                case 'image-next':
                    event.preventDefault();
                    event.stopPropagation();
                    window.chatApp?.nextImage?.(String(element.dataset.hotelId || ''));
                    return;
                case 'feedback-up':
                case 'feedback-down': {
                    event.preventDefault();
                    handleFeedbackClick(element, action === 'feedback-up' ? 1 : 0);
                    return;
                }
                default:
                    return;
            }
        });
    });
}

/**
 * OBS5 — one 👍/👎 vote for the turn this message bubble belongs to.
 *
 * Re-clicking (correcting 👍 → 👎 or back) re-submits: the backend's
 * deterministic score id makes that an overwrite, not a duplicate, so no
 * hard-disable here — only a visual "thanks" + which button is selected.
 */
function handleFeedbackClick(button, value) {
    const control = button.closest('.feedback-control');
    const messageDiv = button.closest('.message');
    const traceId = String(messageDiv?.dataset.traceId || '');
    if (!control || !traceId) return;

    submitFeedback(traceId, value);
    trackFeedbackSubmit({ turnId: String(messageDiv.dataset.turnId || ''), traceId, value: value ? 'up' : 'down' });

    control.querySelectorAll('.feedback-control__btn').forEach(btn => {
        btn.classList.toggle('is-selected', btn === button);
    });
    control.classList.add('is-submitted');
    const label = control.querySelector('.feedback-control__label');
    if (label) label.textContent = t('feedback_thanks');
}

/**
 * OBS5 — attach a 👍/👎 control to the LAST bot bubble in the transcript.
 *
 * Called once per turn, after all of that turn's rendering is done (see
 * send.js's outer `finally`) — deliberately not threaded through every
 * individual response-type renderer (faq/booking/results/clarification/…):
 * one trace_id already represents the whole turn, so tagging whichever bot
 * bubble that turn produced last is the right granularity, not an
 * approximation. No-op without a trace_id (Langfuse disabled or a crashed
 * turn) — never a dead button.
 */
export function attachFeedbackControl(traceId) {
    if (!traceId) return;
    const bubbles = document.querySelectorAll('#chat-messages .message.bot');
    const target = bubbles[bubbles.length - 1];
    const content = target?.querySelector('.message-content');
    if (!target || !content || target.dataset.traceId) return;

    target.dataset.traceId = traceId;
    const feedback = document.createElement('div');
    feedback.className = 'feedback-control';
    feedback.innerHTML = `
        <span class="feedback-control__label">${escapeHtml(t('feedback_prompt'))}</span>
        <button type="button" class="feedback-control__btn" data-action="feedback-up"
                aria-label="${escapeAttr(t('feedback_helpful'))}">👍</button>
        <button type="button" class="feedback-control__btn" data-action="feedback-down"
                aria-label="${escapeAttr(t('feedback_not_helpful'))}">👎</button>
    `;
    content.appendChild(feedback);
    bindMessageContentInteractions(content);
}

function setupImageCarouselHandlers(messageContent) {
    messageContent.querySelectorAll('.js-image-carousel-wrapper[data-hotel-id]').forEach(wrapper => {
        if (wrapper.dataset.scrollBound === '1') return;
        wrapper.dataset.scrollBound = '1';
        wrapper.addEventListener('scroll', (event) => {
            const hotelId = String(wrapper.dataset.hotelId || '');
            window.chatApp?.handleImageScroll?.(event, hotelId);
        });
    });

    messageContent.querySelectorAll('.carousel-dot[data-carousel][data-index]').forEach(dot => {
        if (dot.dataset.dotBound === '1') return;
        dot.dataset.dotBound = '1';
        dot.addEventListener('click', () => {
            const hotelId = String(dot.dataset.carousel || '');
            const index = Number(dot.dataset.index || 0);
            window.chatApp?.goToImage?.(hotelId, index);
        });
    });
}

function sanitizeTrustedHtml(rawHtml) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(`<div id="trusted-html-root">${String(rawHtml || '')}</div>`, 'text/html');
    const root = doc.getElementById('trusted-html-root');
    if (!root) return '';

    root.querySelectorAll('script').forEach(node => node.remove());
    root.querySelectorAll('*').forEach(node => {
        Array.from(node.attributes).forEach(attr => {
            const name = String(attr.name || '').toLowerCase();
            const value = String(attr.value || '').trim();
            if (name.startsWith('on')) {
                node.removeAttribute(attr.name);
                return;
            }
            if ((name === 'href' || name === 'src') && value.toLowerCase().startsWith('javascript:')) {
                node.removeAttribute(attr.name);
            }
        });
    });

    return root.innerHTML;
}

// S-CX8 — MCP_B2C's own closed enums, translated here rather than server-side:
// the backend passes the raw value through, so a new enum member shows up as a
// missing label (and the row falls back to its time slot) instead of as a raw
// `dayuse.late_break` in front of a customer.
// Both were live-probed 2026-07-28 across 4 596 real offers; see
// inline_tools._rate_plan_view for the distribution and why offerType leads.
const PLAN_TYPE_KEYS = {
    'dayuse.day': 'plan_type_day',
    'dayuse.early': 'plan_type_early',
    'dayuse.late_break': 'plan_type_late_break',
    'dayuse.dayuse_am': 'plan_type_dayuse_am',
    'dayuse.dayuse_pm': 'plan_type_dayuse_pm',
};

const BEDDING_KEYS = {
    double: 'bed_double',
    double_king: 'bed_double_king',
    double_queen: 'bed_double_queen',
    single: 'bed_single',
    twin_double: 'bed_twin_double',
    twin_singles: 'bed_twin_singles',
    twin_doubles: 'bed_twin_doubles',
    twin_two_queens: 'bed_twin_two_queens',
};

// MCP `includedAmenities` — hotel-level perks. Only 4 distinct values across the
// probed sample, so a closed table again. An unmapped value is SKIPPED rather
// than shown raw: these arrive in English, and "Free parking" inside a French
// card is a worse answer than one line fewer.
const AMENITY_KEYS = {
    'Free parking': 'amenity_free_parking',
    'Outdoor pool': 'amenity_outdoor_pool',
    'Indoor pool': 'amenity_indoor_pool',
    'Fitness room': 'amenity_fitness_room',
};

function amenityLabels(amenities) {
    if (!Array.isArray(amenities)) return [];
    return amenities
        .map(a => AMENITY_KEYS[String(a || '')])
        .filter(Boolean)
        .map(key => t(key));
}

function planTypeLabel(offerType) {
    const key = PLAN_TYPE_KEYS[String(offerType || '')];
    return key ? t(key) : '';
}

function beddingLabel(bedding) {
    const key = BEDDING_KEYS[String(bedding || '')];
    return key ? t(key) : '';
}

function capacityLabel(capacity) {
    const count = Number(capacity);
    if (!Number.isFinite(count) || count < 1) return '';
    return count === 1 ? t('plan_capacity_one') : t('plan_capacity', { count });
}

/**
 * S-CX8 — the day's rate plans as selectable rows.
 *
 * Every row is a real, already-generated tunnel link (the backend generated one
 * per plan on the pick turn), so selecting a formula is pure client-side state:
 * no round-trip, no chat turn. A plan whose URL fails the host allowlist is
 * DROPPED rather than rendered unbookable — same rule the backend applies to a
 * plan whose link generation failed.
 *
 * Returns `{html: '', selectedTitle: ''}` when there is nothing to choose
 * between, which is what makes this additive: a payload without `rate_plans`
 * renders exactly the card that shipped before this existed. `selectedTitle` is
 * handed back so the CTA can name the same thing the highlighted row does.
 */
const NO_PLANS = { html: '', selectedTitle: '' };

// Longest formula title that still fits the CTA next to "Book — " and the arrow
// glyph at the card's 400px width. Past it the CTA keeps its plain label.
const CTA_PLAN_NAME_MAX = 22;

function renderRatePlans(plans) {
    if (!Array.isArray(plans) || plans.length < 2) return NO_PLANS;

    // WHICH field titles the rows is a per-CARD decision, because neither field
    // is reliably distinctive on its own — both real failures were observed live
    // on 2026-07-29 inventory:
    //   Ibis La Ciotat — 3 formulas, all `dayuse.day`, all 10:00-15:00, differing
    //     only by room ("…with Sea view", "…with balcony"). Type-led titles give
    //     "Journée / Journée / Journée".
    //   Mercure Lyon Saxe — 3 formulas, all named "Standard King Room", differing
    //     by slot. Name-led titles give three identical rows.
    // So: the room name leads only when the type labels do NOT separate the rows
    // and the names DO. Otherwise the type leads and the always-present slot
    // pill carries the distinction.
    const typeLabels = plans.map(p => planTypeLabel(p && p.offer_type));
    const names = plans.map(p => (p && p.name) || '');
    const allDistinct = (values) =>
        values.every(Boolean) && new Set(values).size === values.length;
    const nameLeads = !allDistinct(typeLabels) && allDistinct(names);

    let selectedTitle = '';
    const rows = plans.map(plan => {
        const url = sanitizeDayuseUrl(appendAmplitudeIdToUrl(plan.url || ''));
        if (!url) return '';

        const slot = [plan.start_time, plan.end_time].every(Boolean)
            ? formatSlotRange(plan.start_time, plan.end_time, getLanguage())
            : '';
        const typeLabel = planTypeLabel(plan.offer_type);
        // The room name is the partner's own wording, shown untranslated on
        // purpose: pretending to have translated it would be worse. The
        // bedding/capacity enums (which we DO own) stand in when it is absent.
        const bedLabel = [
            beddingLabel(plan.bedding),
            plan.capacity ? capacityLabel(plan.capacity) : '',
        ].filter(Boolean).join(' · ');
        const title = (nameLeads ? plan.name : typeLabel)
            || plan.name || typeLabel || slot || t('card_slot');
        const subtitle = title === plan.name
            ? (typeLabel ? [typeLabel, bedLabel].filter(Boolean).join(' · ') : bedLabel)
            : (plan.name || bedLabel);
        if (plan.selected) selectedTitle = String(title);

        return `
            <button type="button" class="booking-card__plan${plan.selected ? ' is-selected' : ''}"
                    data-action="select-rate-plan"
                    aria-pressed="${plan.selected ? 'true' : 'false'}"
                    data-plan-id="${escapeAttr(String(plan.offer_id || ''))}"
                    data-plan-url="${escapeAttr(url)}"
                    data-plan-title="${escapeAttr(String(title))}"
                    data-plan-named="${title === slot ? '0' : '1'}"
                    data-plan-slot="${escapeAttr(slot)}"
                    data-plan-price="${escapeAttr(String(plan.price || ''))}">
                <span class="booking-card__plan-radio" aria-hidden="true"></span>
                <span class="booking-card__plan-main">
                    <span class="booking-card__plan-name">${escapeHtml(String(title))}</span>
                    ${subtitle ? `<span class="booking-card__plan-room">${escapeHtml(subtitle)}</span>` : ''}
                    ${slot && title !== slot ? `
                        <span class="booking-card__plan-meta">
                            <span class="booking-card__plan-slot">${CLOCK_SVG} ${escapeHtml(slot)}</span>
                        </span>` : ''}
                </span>
                <span class="booking-card__plan-prices">
                    ${plan.price ? `<span class="booking-card__plan-amount">${escapeHtml(formatBackendPrice(plan.price))}</span>` : ''}
                    ${plan.original_price ? `<span class="booking-card__plan-orig">${escapeHtml(formatBackendPrice(plan.original_price))}${escapeHtml(t('night_suffix'))}</span>` : ''}
                    ${plan.discount_pct ? `<span class="booking-card__plan-disc">-${escapeHtml(String(plan.discount_pct))}%</span>` : ''}
                </span>
            </button>`;
    }).filter(Boolean);

    // One survivor is not a choice — fall back to the plain card.
    if (rows.length < 2) return NO_PLANS;

    return {
        html: `
        <div class="booking-card__plans">
            <span class="booking-card__plans-label">${escapeHtml(t('card_choose_plan'))}</span>
            ${rows.join('')}
        </div>`,
        selectedTitle,
    };
}

const CLOCK_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';
const CHECK_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 13l4 4L19 7"/></svg>';
const SHIELD_SVG = '<svg viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M12.25 6.52V4.83c0-.96 0-1.44-.24-1.75-.23-.31-.77-.46-1.83-.76-.73-.21-1.37-.46-1.88-.69C7.6 1.32 7.25 1.17 7 1.17c-.25 0-.6.15-1.3.46-.51.23-1.15.48-1.88.69-1.07.3-1.6.45-1.84.76-.23.31-.23.79-.23 1.75v1.69c0 3.28 2.95 5.25 4.43 6.03.35.19.53.28.82.28.29 0 .47-.09.82-.28 1.48-.78 4.43-2.75 4.43-6.03Z" stroke="currentColor" stroke-width="1.1"/><path d="M5.25 7l1.17 1.17L8.75 5.83" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/></svg>';

/**
 * Create a simplified booking card HTML for a hotel CTA.
 * @param {Object} card - booking_card payload from the API
 * @param {string} card.hotel_name
 * @param {string} card.url
 * @param {string|null} card.image_url
 * @param {number|null} card.price
 * @param {string} card.currency
 * @param {string} card.cta_text
 * @param {Array|undefined} card.rate_plans - S-CX8: the day's formulas, one
 *        `selected`, each with its own already-generated tunnel `url`. Absent
 *        when the hotel has a single formula or the lookup degraded.
 * @returns {string} HTML string
 */
export function createBookingCard(card) {
    const name = escapeHtml(card.hotel_name || 'Hotel');
    const imageUrl = sanitizeImageUrl(card.image_url || '') || 'https://images.dayuse.com/hotels/default/default.jpg';
    const url = sanitizeDayuseUrl(card.url || '') || '#';
    const safeUrlAttr = escapeAttr(url);
    const safeHotelNameAttr = escapeAttr(card.hotel_name || 'Hotel');
    const safeHotelIdAttr = escapeAttr(String(card.hotel_id || ''));
    const selectedPlan = Array.isArray(card.rate_plans) ? card.rate_plans.find(plan => plan?.selected) : null;
    const safeRatePlanIdAttr = escapeAttr(String(selectedPlan?.offer_id || ''));

    // S-CX5 — every row is DROPPED when the offer doesn't carry it, never
    // defaulted: the whole point of this card is that it states what the link
    // books, so a placeholder would be worse than an absence.
    const subtitleBits = [
        card.city ? escapeHtml(String(card.city)) : '',
        card.stars ? `${escapeHtml(String(card.stars))}★` : '',
        card.rating ? `${escapeHtml(formatRating(card.rating))}/5${
            card.rating_count ? ` (${escapeHtml(String(card.rating_count))})` : ''
        }` : '',
    ].filter(Boolean).join(' · ');

    const slot = [card.start_time, card.end_time].every(Boolean)
        ? escapeHtml(formatSlotRange(card.start_time, card.end_time, getLanguage()))
        : '';
    const facts = [
        card.date ? { k: t('card_date'), v: escapeHtml(formatCardDate(card.date)) } : null,
        slot ? { k: t('card_slot'), v: slot } : null,
    ].filter(Boolean);
    const factsHtml = facts.length
        ? `<div class="booking-card__facts">${facts.map(f => `
            <div class="booking-card__fact">
                <span class="booking-card__fact-k">${escapeHtml(f.k)}</span>
                <span class="booking-card__fact-v"${f.k === t('card_slot') ? ' data-plan-slot-target="1"' : ''}>${f.v}</span>
            </div>`).join('')}</div>`
        : '';

    const { html: plansHtml, selectedTitle } = renderRatePlans(card.rate_plans);
    // The CTA names the SAME thing the highlighted row does (hence the title
    // coming back from the renderer, not recomputed here) — but only when it is
    // short enough to sit in a button. Real room names run long ("Standard
    // Double Room with Sea view", 33 chars) and would wrap or clip the label, so
    // past the cap the plain CTA is the better answer: the selection is already
    // unambiguous from the highlighted row, the facts grid and the price.
    const ctaLabel = selectedTitle && selectedTitle.length <= CTA_PLAN_NAME_MAX
        ? t('card_book_plan', { plan: selectedTitle })
        : t('card_book_cta');
    // Product promise, not offer data — so it is copy, shown whenever a card is
    // (there is no per-plan cancellation field to contradict it).
    // Hotel-level perks, stated ONCE above the reassurance line — never per
    // formula, where they would imply a distinction the data does not support
    // (identical on every formula across 227 probed days, different on 0).
    const amenities = amenityLabels(card.hotel_amenities);
    const reassuranceHtml = `
        <div class="booking-card__trust">
            ${amenities.length ? `
                <span class="booking-card__trust-item booking-card__trust-item--neutral">
                    ${CHECK_SVG} ${escapeHtml(amenities.join(' · '))}
                </span>` : ''}
            <span class="booking-card__trust-item">${SHIELD_SVG} ${escapeHtml(t('card_free_cancel'))}</span>
        </div>`;

    const priceHtml = card.price
        ? `<div class="booking-card__pricerow">
               <span class="booking-card__price" data-plan-price-target="1">${escapeHtml(formatBackendPrice(card.price))}</span>
               <span class="booking-card__pricenote">${escapeHtml(t('card_price_note'))}</span>
           </div>`
        : '';

    const hotelUrl = sanitizeDayuseUrl(card.hotel_url || '');
    const secondaryHtml = hotelUrl
        ? `<div class="booking-card__secondary">
               <a href="${escapeAttr(hotelUrl)}" target="_blank" rel="noopener">${escapeHtml(t('card_see_hotel'))}</a>
           </div>`
        : '';

    return `
        <div class="booking-card">
            <img
                class="booking-card__image"
                src="${imageUrl}"
                alt="${safeHotelNameAttr}"
                data-fallback-src="https://images.dayuse.com/hotels/default/default.jpg"
            >
            <div class="booking-card__body">
                <div class="booking-card__title">
                    <div class="booking-card__name">${name}</div>
                    ${subtitleBits ? `<div class="booking-card__place">${subtitleBits}</div>` : ''}
                </div>
                ${plansHtml}
                ${factsHtml}
                ${reassuranceHtml}
                ${priceHtml}
                <a href="${safeUrlAttr}" target="_blank" rel="noopener" class="booking-card__cta"
                   data-track-booking-card-click="1"
                   data-hotel-id="${safeHotelIdAttr}"
                   data-rate-plan-id="${safeRatePlanIdAttr}">
                    <span data-plan-cta-label="1">${escapeHtml(ctaLabel)}</span>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M7 17L17 7M17 7H7M17 7V17"/>
                    </svg>
                </a>
                ${secondaryHtml}
            </div>
        </div>
    `;
}

/** "2026-07-28" -> a short date in the CHAT language; anything unparsable
 *  passes through. Not `undefined` (the OS locale): the date is the one fact on
 *  this card a user checks twice before paying, and "Wed, Jul 29" inside an
 *  otherwise French card reads as someone else's booking. */
function formatCardDate(value) {
    const raw = String(value || '');
    const parsed = new Date(`${raw}T12:00:00`);
    if (Number.isNaN(parsed.getTime())) return raw;
    try {
        return parsed.toLocaleDateString(getLanguage(), {
            weekday: 'short', day: 'numeric', month: 'short',
        });
    } catch (_) {
        return raw;
    }
}

/**
 * A separator line in the conversation, not a message from anyone — e.g. the
 * session profile expired (mcp-dayuse#6). Text only, never HTML.
 */
export function addNotice(text) {
    const messagesDiv = document.getElementById('chat-messages');
    if (!messagesDiv || !text) return null;
    const notice = document.createElement('div');
    notice.className = 'chat-notice';
    notice.setAttribute('role', 'status');
    notice.textContent = String(text);
    messagesDiv.appendChild(notice);
    return notice;
}

/**
 * Show typing indicator (legacy - replaced by thinking animation)
 */
export function showTypingIndicator() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) {
        indicator.style.opacity = '0';
        indicator.classList.add('active');
        void indicator.offsetWidth;
        indicator.style.opacity = '1';
        indicator.style.transition = 'opacity 0.3s ease-in-out';
    }
}

/**
 * Hide typing indicator
 */
export function hideTypingIndicator() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) {
        indicator.style.opacity = '0';
        setTimeout(() => {
            indicator.classList.remove('active');
        }, 300);
    }
}
