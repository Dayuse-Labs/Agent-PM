/**
 * Response Handlers
 * Handle different API response types
 */

import { state } from '../state.js';
import { addMessage } from '../ui/messages.js';
import { replaceHotelIdTags, handleContextUpdate, hasEffectiveTimeslot } from '../utils.js';
import { appendAmplitudeIdToUrl, trackEvent } from '../tracking.js';
import { createHotelCarousel } from '../hotels/carousel.js';
import { addFollowUpMessage } from '../filters/search.js';
import { suggestionsInlineHtml } from '../filters/chips.js';
import { t } from '../i18n.js';
import { escapeAttr, escapeHtml, sanitizeDayuseUrl } from '../security.js';
import {
    getMarketMeta,
    getMarketMetaFromHotels,
    inferCountryCodeFromHotel,
    normalizeCountryCode,
} from '../markets.js';

function updateMarketFromResults(results, explicitMarket = null) {
    const inferredMarket = normalizeCountryCode(explicitMarket)
        || inferCountryCodeFromHotel(Array.isArray(results) ? results[0] : null);
    if (inferredMarket) {
        state.market = inferredMarket;
    }
}

/**
 * Append a suggestion-chip row under the previous bot message when the
 * backend supplied `data.suggestions` (currently emitted on SOCIAL_ACK
 * turns — 3 i18n strings like "Compare the first two options"). No-op when
 * the list is empty or malformed.
 */
export function renderSuggestionsRow(data) {
    const raw = data && Array.isArray(data.suggestions) ? data.suggestions : null;
    if (!raw || raw.length === 0) return;
    const html = suggestionsInlineHtml(raw);
    if (!html) return;
    const msg = addMessage(html, false, false, true, true);
    if (msg && msg.classList) msg.classList.add('message--actions');
}

/**
 * Build a combined "intro + meta + carousel" HTML block so a single bot message
 * (and a single AI avatar) is rendered for a results response. Returns trusted HTML.
 */
function buildResultsBlock(introText, count, hotelsHtml) {
    const intro = String(introText || '').trim();
    const introHtml = intro ? `<div class="results-intro">${escapeHtml(intro)}</div>` : '';
    const seeAll = getMarketFallbackLink();
    const seeAllHref = escapeAttr(seeAll.url);
    const seeAllMarket = escapeAttr(seeAll.market);
    const metaHtml = `
        <div class="results-meta">
            <span class="results-count">${t('hotels_selected_for_you', { count: Math.max(0, Number(count) || 0) })}</span>
            <a href="${seeAllHref}" target="_blank" rel="noopener noreferrer"
               class="results-see-all"
               data-track-see-all="meta"
               data-market="${seeAllMarket}">
                ${t('see_all')} <span aria-hidden="true">→</span>
            </a>
        </div>
    `;
    return `${introHtml}${metaHtml}${hotelsHtml || ''}`;
}

/**
 * Handle FAQ response
 */
export function handleFaqResponse(data) {
    const safeText = escapeHtml(data.faq_answer || data.response || '');
    const faqHtml = `
        <div class="faq-response">
            <p class="faq-response__text">${safeText}</p>
        </div>
    `;
    addMessage(faqHtml, false, false, false, true);
    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle support response
 */
export function handleSupportResponse(data) {
    const supportUrl = sanitizeDayuseUrl(data.support_url || '') || 'https://support.dayuse.com/hc/en-us';
    const safeBody = escapeHtml(data.response || '');
    const supportHtml = `
        <div class="response-card response-card--support">
            <div class="response-card__header">
                <span class="response-card__icon">💬</span>
                <strong class="response-card__title response-card__title--support">${t('support_title')}</strong>
            </div>
            <p class="response-card__body response-card__body--with-link">${safeBody}</p>
            <a href="${supportUrl}" target="_blank" rel="noopener" class="response-card__link">
                ${t('support_link')}
            </a>
        </div>
    `;
    addMessage(supportHtml, false, false, false, true);
    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle special request response
 */
export function handleSpecialRequestResponse(data) {
    const safeBody = escapeHtml(data.response || '');
    const specialHtml = `
        <div class="response-card response-card--special">
            <div class="response-card__header">
                <span class="response-card__icon">📋</span>
                <strong class="response-card__title response-card__title--special">${t('special_request_title')}</strong>
            </div>
            <p class="response-card__body">${safeBody}</p>
        </div>
    `;
    addMessage(specialHtml, false, false, false, true);
    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle policy response
 */
export function handlePolicyResponse(data) {
    const safeBody = escapeHtml(data.response || '');
    const policyHtml = `
        <div class="response-card response-card--policy">
            <div class="response-card__header">
                <span class="response-card__icon">✓</span>
                <strong class="response-card__title response-card__title--policy">${t('policy_title')}</strong>
            </div>
            <p class="response-card__body">${safeBody}</p>
        </div>
    `;
    addMessage(policyHtml, false, false, false, true);
    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle UI response (tables, etc.)
 */
export function handleUiResponse(data) {
    const processedResponse = replaceHotelIdTags(data.response);
    addMessage(processedResponse);
    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle timeslot response
 */
export function handleTimeslotResponse(data) {
    const processedResponse = replaceHotelIdTags(data.response);
    addMessage(processedResponse);
    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle booking intent response
 */
export function handleBookingIntentResponse(data) {
    const processedResponse = replaceHotelIdTags(data.response);
    addMessage(processedResponse);
    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle booking response
 */
export function handleBookingResponse(data) {
    console.log('BOOKING detected for:', data.hotel);
    addMessage(data.response);
    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle hotel focus response
 */
export function handleHotelFocusResponse(data) {
    console.log('FOCUS MODE activated on:', data.focused_hotel);
    const processedResponse = replaceHotelIdTags(data.response);
    addMessage(processedResponse);
    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle refinement response
 */
export function handleRefinementResponse(data) {
    console.log('REFINEMENT triggered:', data.reason, data.filter_type);

    if (data.response) {
        addMessage(data.response);
    }

    if (data.results && data.results.length > 0) {
        updateMarketFromResults(data.results, data.market_country);
        const enrichedResults = data.results.map(hotel => {
            const id = hotel.id || hotel.hotel_id;
            const existingHotel = state.previousResults.find(h => (h.id || h.hotel_id) === id);
            return existingHotel ? { ...existingHotel, ...hotel } : hotel;
        });

        state.previousResults = enrichedResults;
        state.activeHotelIds = enrichedResults.map(h => h.id || h.hotel_id).filter(id => id);

        const hotelCards = createHotelCarousel(enrichedResults);
        addMessage(hotelCards, false, true);

        addFollowUpMessage(false);
    }

    renderSuggestionsRow(data);

    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle new search response
 */
export function handleNewSearchResponse(data, message) {
    console.log('NEW SEARCH triggered:', data.reason);

    const hasResults = data.results && data.results.length > 0;

    if (hasResults) {
        updateMarketFromResults(data.results, data.market_country);
        state.previousResults = data.results;
        state.activeHotelIds = data.results.map(h => h.id).filter(id => id);
        state.currentUserQuery = message;

        const hotelCards = createHotelCarousel(data.results);
        const combined = buildResultsBlock(data.response, data.results.length, hotelCards);
        addMessage(combined, false, true, false, true);

        const hasTimeslot = state.selectedFilters.timeslot;
        addFollowUpMessage(hasTimeslot);
    } else if (data.response) {
        addMessage(data.response);
    }

    renderSuggestionsRow(data);

    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle text response without results
 */
export function handleTextResponse(data) {
    if (data.hotels_data && data.hotels_data.length > 0) {
        console.log('Updating previousResults with hotels from follow-up:', data.hotels_data.length);
        updateMarketFromResults(data.hotels_data, data.market_country);
        data.hotels_data.forEach(newHotel => {
            if (!state.previousResults.find(h => h.id === newHotel.id)) {
                state.previousResults.push(newHotel);
            }
        });
    }

    const processedResponse = replaceHotelIdTags(data.response);
    addMessage(processedResponse);
    renderSuggestionsRow(data);
}

/**
 * Build the "see all hotels in X" CTA pointing to the right Dayuse TLD.
 *
 * Reads from state.marketContext (kept in sync by applyMarketFromResponse on
 * every chat response). Falls back to the US/dayuse.com default until the
 * first response is processed. Display name uses the resolved market when
 * available so the CTA reads "Voir tous les hôtels en France →" on dayuse.fr.
 */
export function getMarketFallbackLink() {
    const ctx = state.marketContext || {};
    const ctxCountry = normalizeCountryCode(ctx.country_code);
    const searchCountry = normalizeCountryCode(state.selectedFilters?.country_code);
    const marketMeta = getMarketMeta(searchCountry || ctxCountry || state.market, 'US');
    const useSearchMarket = Boolean(searchCountry);
    const rawUrl = (
        useSearchMarket
            ? marketMeta.browseUrl
            : (ctx.browse_url || marketMeta.browseUrl)
    ) || 'https://www.dayuse.com/s/united-states';
    const url = sanitizeDayuseUrl(appendAmplitudeIdToUrl(rawUrl)) || '#';
    const marketName = useSearchMarket
        ? (marketMeta.label || searchCountry || 'USA')
        : (ctx.display_name || marketMeta.label || 'USA');
    return {
        url,
        label: t('see_all_hotels_in', { market: marketName }).replace('→', '').trim(),
        market: String(searchCountry || ctxCountry || marketMeta.code || 'US').toUpperCase(),
    };
}

/**
 * Handle search results response
 */
export function handleResultsResponse(data, hasTimeslotRequest) {
    const results = data.results || data.hotels_data || state.previousResults;

    // Update state if not already done by context_update
    if (!data.context_update || !data.context_update.should_replace_list) {
        if (results && results.length > 0) {
            state.previousResults = results;
            if (!data.context_update || !data.context_update.active_hotel_ids) {
                state.activeHotelIds = results.map(h => h.id).filter(id => id);
            }
        }
    }

    if (results && results.length > 0) {
        updateMarketFromResults(results, data.market_country);
        // Single bot message: intro text + meta count line + carousel under one avatar.
        const introText = data.context || t('found_options_intro', { count: results.length });
        const hotelsToShow = results.slice(0, 6);
        const hotelsHtml = createHotelCarousel(hotelsToShow);
        const combined = buildResultsBlock(introText, results.length, hotelsHtml);
        const carouselMessage = addMessage(combined, false, true, false, true);
        const contextMsg = carouselMessage; // for downstream scrollIntoView
        const firstHotel = hotelsToShow[0] || {};
        const matchLevelCounts = hotelsToShow.reduce((acc, hotel) => {
            const level = String(hotel.timeslot_match_level || 'unknown').toLowerCase();
            if (level === 'exact') acc.exact += 1;
            else if (level === 'close') acc.close += 1;
            else if (level === 'none') acc.none += 1;
            else acc.unknown += 1;
            return acc;
        }, { exact: 0, close: 0, none: 0, unknown: 0 });
        trackEvent('results_rendered', {
            results_count: results.length,
            shown_count: hotelsToShow.length,
            response_type: String(data.type || 'results'),
            has_soft_nudge: Boolean(data.soft_nudge),
            has_timeslot_request: Boolean(hasTimeslotRequest),
            has_effective_timeslot: hasEffectiveTimeslot(data),
            market: String(firstHotel.country_code || state.market || ''),
            geo_version: String(data.active_filters?.geo_version || ''),
            geo_outcome: String(data.active_filters?.geo_outcome || ''),
            geo_reason: String(data.active_filters?.geo_reason || ''),
            geo_repair_count: data.active_filters?.geo_repair_count || 0,
            geo_resolution_ms: data.active_filters?.geo_resolution_ms ?? null,
            geo_review_ms: data.active_filters?.geo_review_ms ?? null,
            timeslot_match_exact_count: matchLevelCounts.exact,
            timeslot_match_close_count: matchLevelCounts.close,
        });

        // Scroll to intro message (not carousel) so user sees the context first
        setTimeout(() => {
            contextMsg.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 150);

        if (data.soft_nudge) {
            addMessage(data.soft_nudge, false, false, true);
        } else {
            addFollowUpMessage(hasTimeslotRequest);
        }

        renderSuggestionsRow(data);
    } else {
        // The last successful shortlist belongs to another location version.
        // Empty results must never build their CTA from those stale cards.
        state.previousResults = [];
        state.activeHotelIds = [];
        handleEmptyResults(data);
    }

    if (data.conversation_id) {
        state.currentConversationId = data.conversation_id;
    }
}

/**
 * Handle empty results
 */
function handleEmptyResults(data) {
    const errorMessage = data.message || t('empty_results');
    addMessage(errorMessage);

    if (data.unsupported_city && data.redirect_url) {
        const safeRedirectUrl = sanitizeDayuseUrl(data.redirect_url);
        if (!safeRedirectUrl) {
            return;
        }
        const redirectHtml = `
                <a href="${safeRedirectUrl}" target="_blank" rel="noopener"
               class="book-button fallback-cta"
               data-fallback-type="unsupported_city"
               data-city="${escapeAttr(String(data.unsupported_city || ''))}">
                ${t('city_redirect', { city: escapeHtml(String(data.unsupported_city)) })}
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M7 17L17 7M17 7H7M17 7V17"/>
                </svg>
            </a>
        `;
        addMessage(redirectHtml, false, true);
    } else {
        const market = getMarketFallbackLink();
        const searchLinkHtml = `
            <a href="${market.url}" target="_blank" rel="noopener"
               class="book-button fallback-cta"
               data-fallback-type="market_browse"
               data-market="${market.market}">
                ${market.label}
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M7 17L17 7M17 7H7M17 7V17"/>
                </svg>
            </a>
        `;
        addMessage(searchLinkHtml, false, true);
    }
}
