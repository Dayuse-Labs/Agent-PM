/**
 * Hotel Carousel
 * Horizontal scrolling carousel of hotel cards
 */

import { state } from '../state.js';
import { appendAmplitudeIdToUrl } from '../tracking.js';
import { createHotelCard } from './card.js';
import { t } from '../i18n.js';
import { escapeAttr, sanitizeDayuseUrl } from '../security.js';
import { getMarketMetaFromHotels } from '../markets.js';

function getCarouselStep(wrapper) {
    const firstCard = wrapper.querySelector('.hotel-card');
    if (!firstCard) return 336; // Fallback: desktop card width + default gap

    const cardWidth = firstCard.getBoundingClientRect().width;
    const wrapperStyles = window.getComputedStyle(wrapper);
    const gap = parseFloat(wrapperStyles.columnGap || wrapperStyles.gap || '0') || 0;

    return cardWidth + gap;
}

/**
 * Create hotel carousel HTML
 */
export function createHotelCarousel(hotels) {
    const carouselId = 'carousel-' + Date.now();

    const marketMeta = getMarketMetaFromHotels(hotels, state.market);
    // `browseUrl` is null for a market with no browse page (MY) and for an
    // unmapped one — render no "see all" link at all rather than a dead '#'
    // (UX6 2026-08-28, same rule the card now follows for its hotel link).
    // This URL is interpolated into innerHTML. Without attribute escaping,
    // `&amp_session_id=...` is parsed as the legacy `&amp` HTML entity and
    // becomes `&_session_id=...`, silently breaking Amplitude session handoff.
    const marketLinkRaw = marketMeta.browseUrl
        ? appendAmplitudeIdToUrl(marketMeta.browseUrl)
        : '';
    const marketLink = escapeAttr(sanitizeDayuseUrl(marketLinkRaw) || '');
    const marketCode = escapeAttr(marketMeta.code);

    let html = `
        <div class="hotel-cards-container" id="${carouselId}">
            <button class="carousel-nav-button prev" data-action="scroll-carousel" data-carousel-id="${carouselId}" data-direction="-1" aria-label="Previous">←</button>
            <div class="hotel-cards-wrapper">
    `;

    hotels.forEach(h => html += createHotelCard(h));

    html += `
            </div>
            <button class="carousel-nav-button next" data-action="scroll-carousel" data-carousel-id="${carouselId}" data-direction="1" aria-label="Next">→</button>
        </div>
        <div class="carousel-indicator">
            <span class="carousel-count" id="${carouselId}-indicator">1 / ${hotels.length}</span>
            ${marketLink ? `<a href="${marketLink}" target="_blank" rel="noopener" class="see-all-link" data-market="${marketCode}">${t('see_all_hotels_in', { market: marketMeta.label })}</a>` : ''}
        </div>
    `;

    // Initialize listeners after DOM is created
    setTimeout(() => initCarouselListeners(carouselId), 100);

    return html;
}

/**
 * Scroll carousel by direction
 */
export function scrollCarousel(carouselId, direction) {
    const container = document.getElementById(carouselId);
    if (!container) return;

    const wrapper = container.querySelector('.hotel-cards-wrapper');
    if (!wrapper) return;

    const step = getCarouselStep(wrapper);

    wrapper.scrollBy({
        left: direction * step,
        behavior: 'smooth'
    });

    setTimeout(() => updateCarouselIndicator(carouselId), 300);
}

/**
 * Update carousel indicator and button visibility
 */
export function updateCarouselIndicator(carouselId) {
    const container = document.getElementById(carouselId);
    if (!container) return;

    const wrapper = container.querySelector('.hotel-cards-wrapper');
    const indicator = document.getElementById(carouselId + '-indicator');
    const prevBtn = container.querySelector('.prev');
    const nextBtn = container.querySelector('.next');
    if (!wrapper) return;

    const totalCards = wrapper.children.length;
    const step = getCarouselStep(wrapper);
    const rawIndex = step > 0 ? Math.round(wrapper.scrollLeft / step) + 1 : 1;
    const currentIndex = Math.min(Math.max(rawIndex, 1), Math.max(totalCards, 1));

    if (indicator) {
        indicator.textContent = `${currentIndex} / ${totalCards}`;
    }

    // Handle prev button visibility
    if (prevBtn) {
        if (wrapper.scrollLeft <= 10) {
            prevBtn.style.opacity = '0';
            prevBtn.style.pointerEvents = 'none';
        } else {
            prevBtn.style.opacity = '1';
            prevBtn.style.pointerEvents = 'auto';
        }
    }

    // Handle next button visibility
    if (nextBtn) {
        const maxScroll = wrapper.scrollWidth - wrapper.clientWidth;
        if (wrapper.scrollLeft >= maxScroll - 10) {
            nextBtn.style.opacity = '0';
            nextBtn.style.pointerEvents = 'none';
        } else {
            nextBtn.style.opacity = '1';
            nextBtn.style.pointerEvents = 'auto';
        }
    }
}

/**
 * Normalize card heights in carousel
 */
export function normalizeCarouselHeights(carouselId) {
    const container = document.getElementById(carouselId);
    if (!container) return;

    const cards = container.querySelectorAll('.hotel-card');
    if (!cards.length) return;

    // Reset heights
    cards.forEach(card => {
        card.style.height = 'auto';
    });

    // Find max height
    let maxHeight = 0;
    cards.forEach(card => {
        const h = card.offsetHeight;
        if (h > maxHeight) maxHeight = h;
    });

    // Apply max height to all
    cards.forEach(card => {
        card.style.height = maxHeight + 'px';
    });
}

/**
 * Initialize carousel event listeners
 */
function initCarouselListeners(carouselId) {
    const container = document.getElementById(carouselId);
    if (!container) return;

    const wrapper = container.querySelector('.hotel-cards-wrapper');
    wrapper.addEventListener('scroll', () => {
        updateCarouselIndicator(carouselId);
    });

    updateCarouselIndicator(carouselId);
    normalizeCarouselHeights(carouselId);
}

/**
 * Legacy carousel functions (for main slide carousel)
 */
export function updateCarousel() {
    const wrapper = document.querySelector('.carousel-wrapper');
    if (!wrapper) return;

    wrapper.style.transform = `translateX(-${state.currentSlide * (100 / 2)}%)`;

    document.querySelectorAll('.carousel-dot').forEach((dot, index) => {
        dot.classList.toggle('active', index === state.currentSlide);
    });
}

export function nextSlide() {
    if (state.currentSlide < Math.ceil(state.totalSlides / 2) - 1) {
        state.currentSlide++;
        updateCarousel();
    }
}

export function prevSlide() {
    if (state.currentSlide > 0) {
        state.currentSlide--;
        updateCarousel();
    }
}
