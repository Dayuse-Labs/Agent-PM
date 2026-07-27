/**
 * Message UI
 * Add messages to chat, handle content rendering
 */

import { state } from '../state.js';
import { t } from '../i18n.js';
import { escapeAttr, escapeHtml, sanitizeDayuseUrl, sanitizeImageUrl } from '../security.js';
import { parsePrice } from '../hotels/card.js';

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
                                ${t('book_now')}
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
                behavior: 'smooth'
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

function setupHotelTrackingLinks(messageContent) {
    messageContent.querySelectorAll('a[data-track-hotel-click="1"]').forEach(link => {
        if (link.dataset.trackBound === '1') return;
        link.dataset.trackBound = '1';
        link.addEventListener('click', () => {
            emitTrackEvent('hotel_card_click', {
                hotel_name: String(link.dataset.hotelName || ''),
                hotel_id: String(link.dataset.hotelId || ''),
                price: String(link.dataset.hotelPrice || ''),
                url: String(link.dataset.hotelUrl || ''),
                intent: 'booking',
            });
        });
    });
}

function setupCtaTrackingLinks(messageContent) {
    messageContent.querySelectorAll('a[data-track-booking-card-click="1"]').forEach(link => {
        if (link.dataset.ctaTrackBound === '1') return;
        link.dataset.ctaTrackBound = '1';
        link.addEventListener('click', () => {
            emitTrackEvent('booking_card_click', {
                hotel_name: String(link.dataset.hotelName || ''),
                hotel_id: String(link.dataset.hotelId || ''),
                url: String(link.dataset.bookingUrl || link.getAttribute('href') || ''),
                cta_label: String(link.textContent || '').trim().slice(0, 80),
            });
        });
    });

    messageContent.querySelectorAll('a.results-see-all').forEach(link => {
        if (link.dataset.ctaTrackBound === '1') return;
        link.dataset.ctaTrackBound = '1';
        link.addEventListener('click', () => {
            emitTrackEvent('market_see_all_click', {
                market: String(link.dataset.market || ''),
                url: String(link.getAttribute('href') || ''),
            });
        });
    });

    messageContent.querySelectorAll('a.fallback-cta').forEach(link => {
        if (link.dataset.ctaTrackBound === '1') return;
        link.dataset.ctaTrackBound = '1';
        link.addEventListener('click', () => {
            emitTrackEvent('fallback_cta_click', {
                fallback_type: String(link.dataset.fallbackType || 'unknown'),
                city: String(link.dataset.city || ''),
                market: String(link.dataset.market || ''),
                url: String(link.getAttribute('href') || ''),
            });
        });
    });

    messageContent.querySelectorAll('a.response-card__link').forEach(link => {
        if (link.dataset.ctaTrackBound === '1') return;
        link.dataset.ctaTrackBound = '1';
        link.addEventListener('click', () => {
            emitTrackEvent('support_link_click', {
                url: String(link.getAttribute('href') || ''),
                label: String(link.textContent || '').trim().slice(0, 80),
            });
        });
    });
}

function emitTrackEvent(eventName, payload = {}) {
    const trackEvent = window.chatApp?.trackEvent;
    if (typeof trackEvent !== 'function') return;
    trackEvent(eventName, payload);
}

function setupActionHandlers(messageContent) {
    messageContent.querySelectorAll('[data-action]').forEach(element => {
        if (element.dataset.actionBound === '1') return;
        element.dataset.actionBound = '1';
        element.addEventListener('click', (event) => {
            const action = String(element.dataset.action || '');
            if (!action) return;

            switch (action) {
                case 'pick-hotel': {
                    // S-CX5: the label goes into the transcript as the user's
                    // own message; the id rides the next request so the
                    // backend resolves the hotel without matching that text.
                    event.preventDefault();
                    const hotelId = String(element.dataset.hotelId || '');
                    const label = String(element.dataset.pickLabel || '');
                    emitTrackEvent('hotel_pick_click', { hotel_id: hotelId });
                    window.chatApp?.pickHotel?.(hotelId, label);
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
                    emitTrackEvent('carousel_nav_click', {
                        carousel_id: carouselId,
                        direction,
                    });
                    window.chatApp?.scrollCarousel?.(carouselId, direction);
                    return;
                }
                case 'follow-up': {
                    event.preventDefault();
                    const followUp = String(element.dataset.followUp || '');
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
                default:
                    return;
            }
        });
    });
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

/**
 * Create a simplified booking card HTML for a hotel CTA.
 * @param {Object} card - booking_card payload from the API
 * @param {string} card.hotel_name
 * @param {string} card.url
 * @param {string|null} card.image_url
 * @param {number|null} card.price
 * @param {string} card.currency
 * @param {string} card.cta_text
 * @returns {string} HTML string
 */
export function createBookingCard(card) {
    const name = escapeHtml(card.hotel_name || 'Hotel');
    const imageUrl = sanitizeImageUrl(card.image_url || '') || 'https://images.dayuse.com/hotels/default/default.jpg';
    const url = sanitizeDayuseUrl(card.url || '') || '#';
    const safeUrlAttr = escapeAttr(url);
    const safeHotelNameAttr = escapeAttr(card.hotel_name || 'Hotel');
    const safeHotelIdAttr = escapeAttr(String(card.hotel_id || ''));

    // S-CX5 — every row is DROPPED when the offer doesn't carry it, never
    // defaulted: the whole point of this card is that it states what the link
    // books, so a placeholder would be worse than an absence.
    const subtitleBits = [
        card.city ? escapeHtml(String(card.city)) : '',
        card.stars ? `${escapeHtml(String(card.stars))}★` : '',
        card.rating ? `${escapeHtml(String(card.rating))}/5${
            card.rating_count ? ` (${escapeHtml(String(card.rating_count))})` : ''
        }` : '',
    ].filter(Boolean).join(' · ');

    const slot = [card.start_time, card.end_time].every(Boolean)
        ? `${escapeHtml(String(card.start_time))} – ${escapeHtml(String(card.end_time))}`
        : '';
    const facts = [
        card.date ? { k: t('card_date'), v: escapeHtml(formatCardDate(card.date)) } : null,
        slot ? { k: t('card_slot'), v: slot } : null,
    ].filter(Boolean);
    const factsHtml = facts.length
        ? `<div class="booking-card__facts">${facts.map(f => `
            <div class="booking-card__fact">
                <span class="booking-card__fact-k">${escapeHtml(f.k)}</span>
                <span class="booking-card__fact-v">${f.v}</span>
            </div>`).join('')}</div>`
        : '';

    const priceHtml = card.price
        ? `<div class="booking-card__pricerow">
               <span class="booking-card__price">${escapeHtml(String(card.price))}</span>
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
                ${factsHtml}
                ${priceHtml}
                <a href="${safeUrlAttr}" target="_blank" rel="noopener" class="booking-card__cta"
                   data-track-booking-card-click="1"
                   data-hotel-name="${safeHotelNameAttr}"
                   data-hotel-id="${safeHotelIdAttr}"
                   data-booking-url="${safeUrlAttr}">
                    ${escapeHtml(t('card_book_cta'))}
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M7 17L17 7M17 7H7M17 7V17"/>
                    </svg>
                </a>
                ${secondaryHtml}
            </div>
        </div>
    `;
}

/** "2026-07-28" -> a short local date; anything unparsable passes through. */
function formatCardDate(value) {
    const raw = String(value || '');
    const parsed = new Date(`${raw}T12:00:00`);
    if (Number.isNaN(parsed.getTime())) return raw;
    try {
        return parsed.toLocaleDateString(undefined, {
            weekday: 'short', day: 'numeric', month: 'short',
        });
    } catch (_) {
        return raw;
    }
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
