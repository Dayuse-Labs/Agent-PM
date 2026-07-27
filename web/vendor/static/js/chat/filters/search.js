/**
 * Search Filters
 * Run search with applied filters
 */

import { state, applyMarketFromResponse } from '../state.js';
import { addMessage } from '../ui/messages.js';
import { showFilterThinking, hideThinkingAnimation } from '../ui/thinking.js';
import { createHotelCarousel } from '../hotels/carousel.js';
import { parsePrice } from '../hotels/card.js';
import { renderClarify } from './chips.js';
import { getChatEndpoint, getChatHeaders } from '../api.js';
import { getNativeContext, getClientTimeContext } from '../utils.js';
import { setLanguage, t } from '../i18n.js';
import { escapeAttr, escapeHtml } from '../security.js';
import { getMarketFallbackLink, renderSuggestionsRow } from '../handlers/responses.js';

/**
 * Build the meta row shown above a results carousel — currently the count only.
 * e.g. "12 hotels selected for you".
 */
function buildResultsMetaHtml(count) {
    const safeCount = Math.max(0, Number(count) || 0);
    const seeAll = getMarketFallbackLink();
    const seeAllHref = escapeAttr(seeAll.url);
    const seeAllMarket = escapeAttr(seeAll.market);
    return `
        <div class="results-meta">
            <span class="results-count">${t('hotels_selected_for_you', { count: safeCount })}</span>
            <a href="${seeAllHref}" target="_blank" rel="noopener noreferrer"
               class="results-see-all"
               data-track-see-all="meta"
               data-market="${seeAllMarket}">
                ${t('see_all')} <span aria-hidden="true">→</span>
            </a>
        </div>
    `;
}

/**
 * Wrap a plain-text intro paragraph for the combined results message.
 */
function buildResultsIntroHtml(text) {
    const clean = String(text || '').trim();
    if (!clean) return '';
    return `<div class="results-intro">${escapeHtml(clean)}</div>`;
}

function toApiTimeslot(timeslot) {
    const mapping = {
        early: 'morning',
        day: 'day',
        late: 'evening'
    };
    return mapping[timeslot] || timeslot;
}

/**
 * Run search with current filters
 */
export async function runSearchWithFilters() {
    showFilterThinking();

    // If filtering previous results by timeslot
    if (state.selectedFilters.timeslot && state.previousResults && state.previousResults.length > 0) {
        const timeslot = state.selectedFilters.timeslot;

        const filtered = state.previousResults.filter(hotel => {
            if (!hotel.timeslots || hotel.timeslots.length === 0) return false;
            return hotel.timeslots.some(slot => {
                const hour = parseInt((slot.start || '').split(':')[0]);
                if (timeslot === 'early') return hour >= 7 && hour <= 10;
                if (timeslot === 'day') return hour >= 10 && hour < 17;
                if (timeslot === 'late') return hour >= 17;
                return false;
            });
        });

        hideThinkingAnimation();

        if (filtered.length > 0) {
            const messages = {
                'early': t('timeslot_early_results'),
                'day': t('timeslot_day_results'),
                'late': t('timeslot_late_results')
            };
            addMessage(messages[timeslot] || t('filter_results_intro'));

            const hotelsToShow = filtered.slice(0, 6);
            const hotelsHtml = createHotelCarousel(hotelsToShow);
            addMessage(hotelsHtml, false, true);
        } else {
            addMessage(t('no_hotels_for_timeslot', { timeslot }));
        }
        return;
    }

    // Build request body for v3/chat
    const q = state.currentUserQuery || document.getElementById('user-input').value || '';
    const requestBody = {
        message: q,
        session_id: state.currentConversationId || null
    };
    Object.assign(requestBody, getClientTimeContext());

    if (state.selectedFilters.city) requestBody.city = state.selectedFilters.city;
    if (state.selectedFilters.timeslot) requestBody.timeslot = toApiTimeslot(state.selectedFilters.timeslot);
    if (state.selectedFilters.requested_start_hour != null) {
        requestBody.timeslot_start = `${String(state.selectedFilters.requested_start_hour).padStart(2, '0')}:00`;
    }
    if (state.selectedFilters.requested_end_hour != null) {
        requestBody.timeslot_end = `${String(state.selectedFilters.requested_end_hour).padStart(2, '0')}:00`;
    }
    if (state.selectedFilters.budget_min != null) {
        requestBody.budget_min = state.selectedFilters.budget_min;
    }
    if (state.selectedFilters.budget_max != null) {
        requestBody.budget_max = state.selectedFilters.budget_max;
    }
    if (state.selectedFilters.amenities && state.selectedFilters.amenities.length > 0) {
        requestBody.amenities = state.selectedFilters.amenities;
    }
    requestBody.limit = state.currentLimit;
    const nativeCtx = getNativeContext();
    if (nativeCtx) {
        requestBody.native_context = nativeCtx;
    }

    try {
        const response = await fetch(getChatEndpoint(), {
            method: 'POST',
            headers: getChatHeaders(),
            body: JSON.stringify(requestBody)
        });
        const rawData = await response.json();
        if (rawData.response_language) {
            setLanguage(rawData.response_language);
            state.responseLanguage = rawData.response_language;
        }
        applyMarketFromResponse(rawData);

        // Normalize v3/chat response
        const data = {
            context: rawData.message || '',
            conversation_id: rawData.session_id,
            results: rawData.hotels ? rawData.hotels.map(h => ({
                id: h.id || h.hotel_id,
                name: h.name,
                stars: h.stars,
                rating: h.rating,
                price: h.price,
                metro: h.metro,
                zone: h.zone,
                city: h.city,
                country_code: h.country_code,
                url: h.url,
                amenities: h.amenities || [],
                highlights: h.highlights || [],
                image_urls: h.image_urls || h.images || [],
                photos_with_tags: h.photos_with_tags || [],
                timeslots: h.timeslots || [],
                matched_timeslots: h.matched_timeslots || [],
                timeslot_match_level: h.timeslot_match_level || null,
                selling_points: h.selling_points || [],
                match_reasons: h.match_reasons || [],
                mismatch_warnings: h.mismatch_warnings || [],
                match_explanation: h.match_explanation || null,
                ai_recommendation: h.ai_recommendation || null,
                has_pool: h.has_pool,
                has_spa: h.has_spa,
                score: h.score || h.relevance_score
            })) : []
        };

        hideThinkingAnimation();

        const hasResults = data.results && data.results.length;

        if (hasResults) {
            state.previousResults = data.results;
            state.activeHotelIds = data.results.map(h => h.id).filter(id => id);

            const hotelsToShow = data.results.slice(0, 6);
            const hotelsHtml = createHotelCarousel(hotelsToShow);
            // Single bot message = intro + meta line + carousel under one avatar.
            const combinedHtml = `${buildResultsIntroHtml(data.context)}${buildResultsMetaHtml(data.results.length)}${hotelsHtml}`;
            const carouselMessage = addMessage(combinedHtml, false, true, true, true);

            setTimeout(() => {
                const chatMessages = document.getElementById('chat-messages');
                const hotelContainer = carouselMessage.querySelector('.hotel-cards-container');
                if (hotelContainer && chatMessages) {
                    const scrollTarget = carouselMessage.offsetTop - 20;
                    chatMessages.scrollTo({
                        top: scrollTarget,
                        behavior: 'smooth'
                    });
                }
            }, 200);

            addFollowUpMessage();
        } else if (data.context) {
            // No results: keep the intro as a standalone bot message.
            const contextMsg = addMessage(data.context, false, false, true);
            setTimeout(() => {
                contextMsg.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 100);
        }

        // The filter path normalises the payload itself and strips suggestions;
        // pull them from the raw response so the chip row still surfaces.
        renderSuggestionsRow({ suggestions: rawData.suggestions });

        if (data.clarify && (!data.chips || data.chips.length === 0)) {
            renderClarify(data.clarify);
        }
    } catch (error) {
        hideThinkingAnimation();
        console.error('Search error:', error);
        addMessage(t('search_error'));
    }
}


/**
 * S-CX5 — hotel-pick buttons (layout L1: picking first, refining below).
 *
 * The backend owns both product rules and sends the result ready to render:
 * WHEN a pick is offered at all (`hotel_picks` is empty until a destination
 * AND a date are resolved) and IN WHICH ORDER (cheapest first). This function
 * only draws them — no filtering, no re-sorting, no "cheapest" badge.
 *
 * A click sends the button's own label as the user's message, so the
 * transcript reads like the conversation it is; the hotel itself is resolved
 * server-side from `data-hotel-id`, never from that text.
 */
function pickButtonsHtml() {
    const picks = Array.isArray(state.hotelPicks) ? state.hotelPicks : [];
    if (!picks.length) return '';
    const buttons = picks.map(pick => {
        const id = String(pick?.hotel_id ?? '').trim();
        const name = String(pick?.name || '').trim();
        if (!id || !name) return '';
        const price = String(pick?.price || '').trim();
        const label = price ? `${name} ${price}` : name;
        return `<button class="pick-button" data-action="pick-hotel"
            data-hotel-id="${escapeAttr(id)}"
            data-pick-label="${escapeAttr(label)}">${escapeHtml(name)}${
            price ? `<span class="pick-button__price">${escapeHtml(price)}</span>` : ''
        }</button>`;
    }).filter(Boolean).join('');
    if (!buttons) return '';
    return `
        <div class="pick-row">
            <p class="pick-row__label">${escapeHtml(t('pick_prompt'))}</p>
            <div class="pick-row__buttons">${buttons}</div>
        </div>
    `;
}

/**
 * Add follow-up message after results
 */
export function addFollowUpMessage(skipTimeslotChips = false) {
    if (skipTimeslotChips || state.selectedFilters.timeslot) {
        const followUpHtml = `
            <div class="follow-up-box">
                ${pickButtonsHtml()}
                <p>${t('followup_questions')}</p>
            </div>
        `;
        const msg = addMessage(followUpHtml, false, false, false, true);
        if (msg && msg.classList) msg.classList.add('message--actions');
        return;
    }

    const followUpHtml = `
        <div class="follow-up-box">
            ${pickButtonsHtml()}
            <p class="follow-up-box__refine">${t('followup_refine')}</p>
            <div class="follow-up-chips">
                <button class="chip" data-action="follow-up" data-follow-up="early">${t('chip_early')}</button>
                <button class="chip" data-action="follow-up" data-follow-up="day">${t('chip_day')}</button>
                <button class="chip" data-action="follow-up" data-follow-up="late">${t('chip_late')}</button>
            </div>
        </div>
    `;
    const msg = addMessage(followUpHtml, false, false, false, true);
    if (msg && msg.classList) msg.classList.add('message--actions');
}

/**
 * Handle follow-up action
 */
export function handleFollowUp(action) {
    const input = document.getElementById('user-input');

    if (action === 'early') {
        addMessage(t('chip_show_early'), true);
        state.selectedFilters.timeslot = 'early';
        runSearchWithFilters();
    } else if (action === 'day') {
        addMessage(t('chip_show_day'), true);
        state.selectedFilters.timeslot = 'day';
        runSearchWithFilters();
    } else if (action === 'late') {
        addMessage(t('chip_show_late'), true);
        state.selectedFilters.timeslot = 'late';
        runSearchWithFilters();
    } else if (action === 'budget') {
        if (state.previousResults && state.previousResults.length > 0) {
            // hotel.price is a formatted string ("from €139.00") — parse it to a
            // number first, otherwise the comparator is NaN and nothing sorts.
            // Missing/zero prices sink to the bottom rather than masquerade as €0.
            const priceVal = (h) => {
                const v = parsePrice(h.price, h.display_currency).value;
                return v > 0 ? v : Infinity;
            };
            const sorted = [...state.previousResults].sort((a, b) => priceVal(a) - priceVal(b));
            const cheapest = sorted.slice(0, 6);

            addMessage(t('affordable_options'), false);
            const hotelsHtml = createHotelCarousel(cheapest);
            addMessage(hotelsHtml, false, true);
        }
    } else if (action === 'question') {
        input.focus();
        input.placeholder = t('ask_anything_placeholder');
    }
}

/**
 * See more results
 */
export function seeMore() {
    state.currentLimit += 6;
    runSearchWithFilters();
}
