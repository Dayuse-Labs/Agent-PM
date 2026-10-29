/**
 * Send Message Handler
 * Main message sending logic and API calls
 */

import { state, resetState, applyMarketFromResponse, setSearchPage, startTurn } from '../state.js';
import {
    appendAmplitudeIdToUrl,
    noteTurnTrace,
    traceIdOfTurn,
    trackConversationReset,
    trackMessageSent,
    trackResponseFailed,
    trackResponseReceived,
} from '../tracking.js';
import { getMarketFallbackLink } from './responses.js';
import { replaceHotelIdTags, handleContextUpdate, getNativeContext, getClientTimeContext } from '../utils.js';
import { addMessage, addNotice, showTypingIndicator, hideTypingIndicator, createBookingCard, attachFeedbackControl } from '../ui/messages.js';
import { createThinkingSteps, hideThinkingAnimation } from '../ui/thinking.js';
import { createHotelCarousel } from '../hotels/carousel.js';
import { addFollowUpMessage } from '../filters/search.js';
import { getChatEndpoint, getChatHeaders, getChatTransport, getStreamEndpoint } from '../api.js';
import { asNetworkFailure, openChatStream, readSseFrames } from '../stream.js';
import { setLanguage, t } from '../i18n.js';
import { escapeAttr, escapeHtml, sanitizeDayuseUrl } from '../security.js';

function applyRuntimeLanguageLabels() {
    const chatInput = document.getElementById('user-input');
    if (chatInput) chatInput.placeholder = t('user_input_placeholder');
    const disclaimer = document.querySelector('.chat-footer .disclaimer');
    if (disclaimer) disclaimer.textContent = t('footer_disclaimer');
    const reassuranceFreeCancel = document.getElementById('reassurance-free-cancel');
    if (reassuranceFreeCancel) reassuranceFreeCancel.textContent = t('reassurance_free_cancel');
    const reassurancePayHotel = document.getElementById('reassurance-pay-hotel');
    if (reassurancePayHotel) reassurancePayHotel.textContent = t('reassurance_pay_hotel');
    const reassuranceDiscount = document.getElementById('reassurance-discount');
    if (reassuranceDiscount) reassuranceDiscount.textContent = t('reassurance_discount');
    const reassuranceLeader = document.getElementById('reassurance-leader');
    if (reassuranceLeader) reassuranceLeader.textContent = t('reassurance_leader');
    const newChatLabel = document.getElementById('new-chat-label');
    if (newChatLabel) {
        newChatLabel.textContent = t('new_chat');
    } else {
        const newChatButton = document.getElementById('new-chat-button');
        if (newChatButton) newChatButton.textContent = t('new_chat');
    }
    syncChatComposerHeight();
}
import {
    handleFaqResponse,
    handleSupportResponse,
    handleSpecialRequestResponse,
    handlePolicyResponse,
    handleUiResponse,
    handleTimeslotResponse,
    handleBookingIntentResponse,
    handleBookingResponse,
    handleHotelFocusResponse,
    handleRefinementResponse,
    handleNewSearchResponse,
    handleTextResponse,
    handleResultsResponse,
    buildResultsBlock,
    updateMarketFromResults
} from './responses.js';

function setChatViewportLock(isActive) {
    document.documentElement.classList.toggle('chat-active', isActive);
    document.body.classList.toggle('chat-active', isActive);
}

export function syncChatComposerHeight() {
    const chatContainer = document.getElementById('chat-container');
    const chatComposer = document.getElementById('chat-composer');
    if (!chatContainer || !chatComposer) return;

    const composerHeight = Math.ceil(chatComposer.getBoundingClientRect().height);
    if (!composerHeight) return;
    chatContainer.style.setProperty('--chat-composer-height', `${composerHeight}px`);
}

/**
 * Keep the fixed mobile composer above the on-screen keyboard.
 *
 * The composer is `position: fixed; bottom: 0` on mobile (glued to the layout
 * viewport). When the keyboard opens, iOS — and Android Chrome ≥108 by default —
 * shrink only the *visual* viewport, so a `bottom: 0` bar ends up hidden behind
 * the keyboard (notably after scrolling and re-focusing the field). We lift it
 * by the covered height using the VisualViewport API.
 *
 * Platform-agnostic and self-correcting: the gap is >0 only when the keyboard
 * overlays the layout viewport; if the platform resizes the layout instead
 * (older Android / `interactive-widget: resizes-content`) the gap is ~0 and this
 * is a no-op. Desktop / non-fixed composer also no-op (and reset any inline
 * offset). No effect when there's no VisualViewport support.
 */
export function syncComposerKeyboardOffset() {
    const composer = document.getElementById('chat-composer');
    if (!composer) return;
    const vv = window.visualViewport;
    if (!vv || getComputedStyle(composer).position !== 'fixed') {
        composer.style.bottom = '';
        return;
    }
    // Portion of the layout viewport hidden below the visual viewport (≈ keyboard).
    const gap = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    // >1px guard ignores sub-pixel rounding / address-bar jitter.
    composer.style.bottom = gap > 1 ? `${gap}px` : '';
}

export function syncChatViewportLock() {
    const chatContainer = document.getElementById('chat-container');
    const isChatVisible = Boolean(
        chatContainer &&
        chatContainer.classList.contains('visible') &&
        chatContainer.style.display !== 'none'
    );

    setChatViewportLock(isChatVisible);
}

window.addEventListener('pagehide', () => {
    setChatViewportLock(false);
});

window.addEventListener('pageshow', () => {
    syncChatViewportLock();
    syncChatComposerHeight();
});

window.addEventListener('resize', () => {
    syncChatComposerHeight();
    syncComposerKeyboardOffset();
});

if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', () => {
        syncChatComposerHeight();
        syncComposerKeyboardOffset();
    });
    // The visual viewport pans (offsetTop changes) as you scroll with the
    // keyboard open — keep the composer glued to its bottom.
    window.visualViewport.addEventListener('scroll', syncComposerKeyboardOffset);
}

// Re-focusing the field after a scroll is exactly when iOS leaves the composer
// under the keyboard; the resize event can lag, so nudge a couple of times.
document.addEventListener('focusin', (event) => {
    const target = event.target;
    if (target && target.id === 'user-input') {
        syncComposerKeyboardOffset();
        setTimeout(syncComposerKeyboardOffset, 150);
        setTimeout(syncComposerKeyboardOffset, 400);
    }
});

/**
 * Map v3 hotel cards to the shape the renderers expect.
 *
 * Shared by normalizeV3Response (the `done` / blocking-POST payload) and the
 * SSE `hotels` frame, which carries the very same cards — the early carousel
 * must be built from exactly the same fields as the late one.
 */
function mapV3Hotels(hotels) {
    return (Array.isArray(hotels) ? hotels : []).map(h => ({
        id: h.id || h.hotel_id,
        name: h.name,
        stars: h.stars,
        rating: h.rating,
        // S-CX9: the review count BEHIND that average. This whitelist is what
        // the card actually receives, and `rating` alone made the card render
        // "5,0/5" for a single 5-star review — the average without the count is
        // the one way this row can mislead.
        rating_count: h.rating_count ?? null,
        price: h.price,
        // The numeric side of `price` (EUR cents, or minor units of the hotel's
        // currency once the card shows it): the card formats the amount in the
        // market's locale from these rather than re-reading the string.
        price_eur_cents: h.price_eur_cents ?? null,
        display_currency: h.display_currency ?? null,
        display_price_minor: h.display_price_minor ?? null,
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
    }));
}

/**
 * Normalize v3/chat response to expected format
 * Converts new API format to match existing handler expectations
 */
// Exported for S-CX9's render harness: this whitelist is the real contract
// between the API payload and the card, so a card field has to be asserted
// THROUGH it. Asserting around it is what let a dropped `rating_count` ship.
export function normalizeV3Response(data) {
    // If it's already in old format with results, return as-is
    if (data.results) {
        return data;
    }

    // Handle v3/chat response format (has hotels instead of results)
    if (data.hotels && data.hotels.length > 0) {
        // Extract intro from message (first line before the hotel list)
        let introText = null;
        if (data.message) {
            // Get first sentence/paragraph before hotel details
            const lines = data.message.split('\n').filter(l => l.trim());
            if (lines.length > 0) {
                // Take first line if it's an intro (not starting with number or *)
                const firstLine = lines[0].trim();
                if (!firstLine.match(/^[\d\*\-]/) && !firstLine.includes('**[')) {
                    introText = firstLine;
                }
            }
        }
        
        // Default intro if parsing failed
        if (!introText) {
            if (data.response_language === 'fr') {
                introText = `J'ai trouve ${data.hotels.length} bonnes options pour vous !`;
            } else if (data.response_language === 'es') {
                introText = `Encontre ${data.hotels.length} buenas opciones para ti.`;
            } else {
                introText = `I found ${data.hotels.length} great options for you!`;
            }
        }
        
        return {
            conversation_id: data.session_id,
            response_language: data.response_language,
            // Show clean intro text (not the full markdown list)
            context: introText,
            response: introText,
            results: mapV3Hotels(data.hotels),
            suggestions: data.suggestions,
            near_me: data.near_me || null,
            active_filters: data.active_filters || null,
            market: data.market || null,
            entry_market_country: data.entry_market_country || data.market?.country_code || null,
            search_country: data.search_country || data.active_filters?.country_code || null,
            market_country: data.market_country || data.active_filters?.country_code || null
        };
    }

    // For other responses (clarification, etc.), pass through with normalized fields
    return {
        ...data,
        conversation_id: data.session_id || data.conversation_id,
        response_language: data.response_language,
        market_country: data.market_country || data.active_filters?.country_code || null,
        context: data.message || data.context || '',
        response: data.message || data.response || ''
    };
}

/**
 * Check if message has timeslot request
 */
function hasTimeslotKeywords(messageLower) {
    return messageLower.includes('check') || messageLower.includes('checkin') ||
        messageLower.includes('8am') || messageLower.includes('7am') ||
        messageLower.includes('early') || messageLower.includes('morning') ||
        /\d{1,2}(am|pm|h)/i.test(messageLower);
}

function toApiTimeslot(timeslot) {
    const mapping = {
        early: 'morning',
        day: 'day',
        late: 'evening'
    };
    const raw = String(timeslot || '').trim();
    if (!raw || /^\d{1,2}$/.test(raw)) {
        return null;
    }
    return mapping[raw] || raw;
}

function nowMs() {
    if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
        return performance.now();
    }
    return Date.now();
}

function explicitlyRequestsDeviceLocation(message) {
    return /(?:^|[\s,.;!?])(near me|around me|close to me|use my (?:location|gps)|current location|près de moi|autour de moi|à côté de moi|a cote de moi|utilise ma localisation|cerca de m[ií]|mi ubicaci[oó]n|vicino a me|bij mij in de buurt|in meiner n(?:ä|ae)he)(?=$|[\s,.;!?])/i.test(
        String(message || '')
    );
}

/**
 * The app's own fix, when it shares one (`__DAYUSE_NATIVE__.geolocation`
 * {lat, lon}, agent-usa's contract), as the device context the backend reads.
 */
function nativeDeviceFix() {
    const geo = getNativeContext()?.geolocation;
    const lat = Number(geo?.lat);
    const lon = Number(geo?.lon);
    if (!geo || !Number.isFinite(lat) || !Number.isFinite(lon) || (lat === 0 && lon === 0)) return null;
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return { device: { latitude: lat, longitude: lon, permission: 'granted' } };
}

export async function getBrowserGeoContext(message) {
    // 2026-10-28: the « near me » chip asks for the position explicitly (a
    // one-shot flag set by its click); a typed request still goes through the
    // phrase check inherited from agent-usa. Without any position, the backend
    // is told so (`unavailable`), and says it in its place question.
    const chip = state.requestDeviceLocation === true;
    state.requestDeviceLocation = false;
    if (!chip && !explicitlyRequestsDeviceLocation(message)) return null;
    const fromApp = nativeDeviceFix();
    if (fromApp) return fromApp;
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
        return chip ? { device: { permission: 'unavailable' } } : null;
    }
    return new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
            (position) => resolve({
                device: {
                    latitude: position.coords.latitude,
                    longitude: position.coords.longitude,
                    accuracy_m: position.coords.accuracy,
                    permission: 'granted'
                }
            }),
            (error) => resolve({
                device: {
                    permission: error?.code === 1 ? 'denied' : 'unavailable'
                }
            }),
            { enableHighAccuracy: false, timeout: 5000, maximumAge: 300000 }
        );
    });
}

/**
 * Build the v3/chat request body for this turn. Transport-agnostic: the
 * blocking POST and the SSE stream send the exact same payload.
 */
function buildRequestBody(isFollowUp, message, turnId, clientGeoContext) {
    const requestBody = {
        message: message,
        session_id: state.currentConversationId || state.clientSessionId || null,
        locale: state.marketContext?.language || state.responseLanguage || null,
        currency: state.marketContext?.currency || null,
        entry_market_country: state.marketContext?.country_code || null,
        turn_id: turnId,
        request_id: turnId
    };
    Object.assign(requestBody, getClientTimeContext());
    if (state.entrySource) {
        requestBody.source = state.entrySource;
    }
    if (clientGeoContext) {
        requestBody.client_geo_context = clientGeoContext;
    }
    if (state.selectedPlace) {
        requestBody.selected_place = state.selectedPlace;
    }
    // Forward the app's logged-in context (recent bookings, favourites,
    // geolocation) so the backend can personalize ranking + defaults.
    const nativeCtx = getNativeContext();
    if (nativeCtx) {
        requestBody.native_context = nativeCtx;
    }

    // Add filters if set
    if (state.selectedFilters.timeslot) {
        const apiTimeslot = toApiTimeslot(state.selectedFilters.timeslot);
        if (apiTimeslot) {
            requestBody.timeslot = apiTimeslot;
        }
    }
    if (state.selectedFilters.city) {
        requestBody.city = state.selectedFilters.city;
    }
    if (state.selectedFilters.amenities && state.selectedFilters.amenities.length > 0) {
        requestBody.amenities = state.selectedFilters.amenities;
    }
    if (state.selectedFilters.requested_start_hour != null) {
        requestBody.timeslot_start = `${String(state.selectedFilters.requested_start_hour).padStart(2, '0')}:00`;
    }
    if (state.selectedFilters.requested_end_hour != null) {
        requestBody.timeslot_end = `${String(state.selectedFilters.requested_end_hour).padStart(2, '0')}:00`;
    }

    // For follow-up, add context
    if (isFollowUp) {
        requestBody.previous_hotel_ids = state.activeHotelIds || [];
    }

    return requestBody;
}

/**
 * Make API call with retry logic
 * Now uses /v3/chat for all requests (natural language understanding)
 */
async function makeApiCall(requestBody) {
    let retryCount = 0;
    const maxRetries = 3;

    while (retryCount < maxRetries) {
        try {
            const response = await fetch(getChatEndpoint(), {
                method: 'POST',
                headers: getChatHeaders(),
                body: JSON.stringify(requestBody)
            }).catch((error) => { throw asNetworkFailure(error); });

            if (!response.ok) {
                throw Object.assign(new Error(`HTTP error! status: ${response.status}`), { httpStatus: response.status });
            }
            return response;
        } catch (error) {
            retryCount++;
            if (retryCount === maxRetries) {
                throw error;
            }
            await new Promise(resolve => setTimeout(resolve, 1000));
        }
    }
}

/**
 * Render the shortlist the moment the SSE `hotels` frame lands — measured ~4 s
 * into a search turn, 4-6 s before the synthesis text. Returns true when a
 * carousel was actually drawn, which is what makes the `done` payload skip its
 * own (no doubled carousel).
 *
 * Draws nothing on an empty frame (no inventory) or a clarifying turn — the
 * blocking-POST path answers the question without a shortlist, so streaming
 * must not paint one either. Those turns render entirely from `done`, as today.
 */
function renderHotelsEarly(frame, thinking) {
    if (frame.requires_clarification) return false;
    const results = mapV3Hotels(frame.hotels);
    if (results.length === 0) return false;

    // Localize BEFORE rendering: the card labels and the "N hotels selected for
    // you" line go through t(), and the turn's language is only known from the
    // backend. Without this the cards would paint in the page's boot language
    // and the text below them would arrive in another one.
    if (frame.response_language) {
        state.responseLanguage = frame.response_language;
        setLanguage(frame.response_language);
        applyRuntimeLanguageLabels();
        thinking.relocalize();
    }

    updateMarketFromResults(results);
    state.previousResults = results;
    state.activeHotelIds = results.map(h => h.id).filter(id => id);
    // S-CX9's booking CTA on each card is gated on `state.hotelPicks`, which the
    // blocking path fills from the `done` body. Rendering cards here without
    // this line paints every card WITHOUT its primary CTA — the whole feature
    // silently disappears in streaming mode. Assigned UNCONDITIONALLY (absent
    // ⇒ []) and BEFORE createHotelCarousel: leaving the previous turn's picks
    // in place would gate this turn's cards on last turn's shortlist, so an
    // overlapping hotel id would show a CTA sourced from stale state.
    state.hotelPicks = Array.isArray(frame.hotel_picks) ? frame.hotel_picks : [];
    setSearchPage(frame.search_page);

    const hotelsHtml = createHotelCarousel(results.slice(0, 6));
    // No intro text yet — it is still being written upstream.
    addMessage(buildResultsBlock('', results.length, hotelsHtml, results), false, true, false, true);

    // Move the thinking bubble BELOW the cards instead of removing it: the
    // synthesis is still running, and this widget's #typing-indicator element
    // does not exist (showTypingIndicator is a no-op here), so the stepping
    // thinking message is the only honest "still working" signal we have.
    const messagesDiv = document.getElementById('chat-messages');
    if (messagesDiv && thinking.loadingMessage) {
        messagesDiv.appendChild(thinking.loadingMessage);
    }
    return true;
}

/**
 * Run one turn over SSE, rendering hotels-first.
 *
 * Returns the `done` payload plus per-frame timings, or null when the stream
 * could not be opened AT ALL — the caller then falls back to the blocking POST
 * for this turn. Once a single frame has been consumed there is no fallback:
 * re-sending would run the turn twice server-side.
 */
async function runStreamedTurn(requestBody, thinking, requestStartMs, progress) {
    let framesSeen = 0;
    let skipCarousel = false;
    let bookingCard = null;

    try {
        const response = await openChatStream(getStreamEndpoint(), getChatHeaders(), requestBody);
        for await (const { event, data } of readSseFrames(response)) {
            framesSeen += 1;
            if (event === 'progress') {
                if (progress.ttftMs === null) progress.ttftMs = Math.round(nowMs() - requestStartMs);
                if (progress.traceId === null) {
                    progress.traceId = data?.trace_id || null;
                    noteTurnTrace(requestBody.turn_id, progress.traceId);
                }
            } else if (event === 'hotels') {
                skipCarousel = renderHotelsEarly(data, thinking) || skipCarousel;
            } else if (event === 'booking_card') {
                // Kept only as a safety net: the `done` payload carries the card
                // too, and a degraded `done` would otherwise lose a link that
                // the backend already generated.
                bookingCard = data.booking_card || null;
            } else if (event === 'done') {
                const rawData = data || {};
                if (!rawData.booking_card && bookingCard) {
                    rawData.booking_card = bookingCard;
                }
                return { rawData, skipCarousel };
            }
            // `token` frames arrive in a burst just before `done` and the full
            // text is in the `done` payload — nothing to render from them.
        }
        throw asNetworkFailure(new Error('stream ended without a done frame'));
    } catch (error) {
        if (framesSeen > 0) throw error;
        console.warn('[CHAT] SSE unavailable, falling back to blocking POST:', error?.message || error);
        return null;
    }
}

/**
 * Handle empty results with fallback links.
 *
 * The market fallback link comes from getMarketFallbackLink in responses.js so
 * the "Browse all hotels in X" CTA tracks the resolved market context.
 */
function handleEmptyResults(data) {
    const errorMessage = data.message || "Sorry, I couldn't find hotels matching your criteria.";
    addMessage(errorMessage);

    if (data.unsupported_city && data.redirect_url) {
        const safeRedirectUrl = sanitizeDayuseUrl(data.redirect_url || '');
        if (!safeRedirectUrl) {
            return;
        }
        const redirectHtml = `
            <a href="${safeRedirectUrl}" target="_blank" rel="noopener"
               class="book-button fallback-cta"
               data-fallback-type="unsupported_city"
               data-city="${escapeAttr(String(data.unsupported_city || ''))}">
                Find hotels in ${escapeHtml(String(data.unsupported_city || ''))} on Dayuse.com
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

/**
 * Main send message function
 */
export async function sendMessage(promptSource = 'typed') {
    if (state.isProcessing) {
        console.log('Message already processing, ignored');
        return;
    }

    const input = document.getElementById('user-input');
    const message = input.value.trim();
    if (!message) return;

    const submitButton = document.getElementById('main-submit-button');
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.classList.add('button-loading');
    }

    state.isProcessing = true;
    state.currentUserQuery = message;
    const { turnId, turnIndex } = startTurn();
    const requestStartMs = nowMs();
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    addMessage(message, true);
    showTypingIndicator();

    let thinkingInterval = null;
    const progress = { ttftMs: null, traceId: null };
    let responseTracked = false;

    try {
        const messageLower = message.toLowerCase();
        const hasTimeslotRequest = hasTimeslotKeywords(messageLower);

        const isFollowUp = state.previousResults && state.previousResults.length > 0;

        trackMessageSent({ turnId, turnIndex, message, promptSource });

        // Create thinking animation
        const thinking = createThinkingSteps(isFollowUp);
        thinkingInterval = thinking.interval;

        const clientGeoContext = await getBrowserGeoContext(message);
        const requestBody = buildRequestBody(isFollowUp, message, turnId, clientGeoContext);

        // Streamed turn when the transport meta says so: the hotel cards land on
        // the `hotels` frame, seconds before the synthesis text. Failing to OPEN
        // the stream degrades to the blocking POST for this turn.
        let turn = getChatTransport() === 'sse'
            ? await runStreamedTurn(requestBody, thinking, requestStartMs, progress)
            : null;
        if (!turn) {
            const response = await makeApiCall(requestBody);
            turn = { rawData: await response.json(), skipCarousel: false };
        }

        clearInterval(thinkingInterval);
        thinking.loadingMessage.remove();

        const rawData = turn.rawData;
        // S-CX5: this turn's pick buttons, already sorted cheapest-first by the
        // backend (empty until the request is qualified enough to book). Read
        // BEFORE any renderer runs, since addFollowUpMessage draws from it.
        state.hotelPicks = Array.isArray(rawData.hotel_picks) ? rawData.hotel_picks : [];
        // Normalize v3/chat response to expected format
        const data = normalizeV3Response(rawData);
        applyMarketFromResponse(data);
        if (data.response_language) {
            state.responseLanguage = data.response_language;
            setLanguage(data.response_language);
            applyRuntimeLanguageLabels();
        }
        // After the market and language updates: they are common properties of the event.
        trackResponseReceived({
            turnId,
            turnIndex,
            payload: rawData,
            latencyMs: nowMs() - requestStartMs,
            ttftMs: progress.ttftMs,
        });
        responseTracked = true;
        hideTypingIndicator();

        // mcp-dayuse#6: the server profile expired (30 min idle) while this
        // page lived on — mark the break before the answer that starts over.
        if (rawData.session_expired) {
            addNotice(t('session_expired'));
        }

        if (data.error) {
            addMessage(`${t('search_error')} ${data.error}`);
            return;
        }

        handleContextUpdate(data);

        // IMPORTANT: Store session_id BEFORE handlers (they may return early)
        if (data.conversation_id) {
            state.currentConversationId = data.conversation_id;
            console.log('[CHAT] Updated session_id:', state.currentConversationId);
        }

        // Handle clarification questions from v3/chat (new + legacy shapes)
        const isClarification = Boolean(
            rawData.requires_clarification ||
            data.requires_clarification ||
            data.type === 'clarification'
        );
        if (isClarification) {
            addMessage(data.response || data.context);
            // Could add question UI here if needed
            return;
        }

        // Handle booking card CTA (simplified hotel card with Book Now)
        if (rawData.booking_card && rawData.booking_card.url) {
            // Show the agent's text message, but strip raw URLs since the card handles the link
            let bookingText = data.response || data.context || '';
            if (bookingText) {
                // Remove raw URLs (https://...) that the LLM sometimes includes
                bookingText = bookingText.replace(/https?:\/\/[^\s)]+/g, '').replace(/\n{3,}/g, '\n\n').trim();
                if (bookingText) {
                    addMessage(bookingText);
                }
            }
            // Append Amplitude ID to booking URL for cross-domain tracking
            const card = { ...rawData.booking_card };
            card.url = appendAmplitudeIdToUrl(card.url);
            addMessage(createBookingCard(card), false, false, false, true);
            return;
        }

        // Route to appropriate response handler
        switch (data.type) {
            case 'faq':
                handleFaqResponse(data);
                return;
            case 'support':
                handleSupportResponse(data);
                return;
            case 'special_request':
                handleSpecialRequestResponse(data);
                return;
            case 'policy':
                handlePolicyResponse(data);
                return;
            case 'ui':
                handleUiResponse(data);
                return;
            case 'timeslot':
                handleTimeslotResponse(data);
                return;
            case 'booking_intent':
                handleBookingIntentResponse(data);
                return;
            case 'booking':
                handleBookingResponse(data);
                return;
            case 'hotel_focus':
                handleHotelFocusResponse(data);
                return;
            case 'refinement':
                handleRefinementResponse(data);
                return;
            case 'new_search':
                handleNewSearchResponse(data, message);
                return;
        }

        // Handle text response without results
        if (data.response && !data.results) {
            handleTextResponse(data);
            return;
        }

        // Handle results response
        handleResultsResponse(data, hasTimeslotRequest, turn.skipCarousel);

    } catch (error) {
        if (thinkingInterval) {
            clearInterval(thinkingInterval);
        }
        hideThinkingAnimation();
        hideTypingIndicator();
        console.error('Error:', error);
        if (!responseTracked) {
            trackResponseFailed({ turnId, turnIndex, error, traceId: progress.traceId });
        }
        addMessage(t('generic_error'));
    } finally {
        // OBS5: runs on every exit path of this turn (early returns from the
        // clarification/booking/route-dispatch branches above, the normal
        // fallthrough, AND the catch above) — the one place that reliably
        // fires once per turn regardless of which branch rendered the
        // response. No-op when the turn has no trace (Langfuse disabled
        // server-side, or the turn crashed before any trace arrived) — the
        // feedback control simply doesn't appear.
        attachFeedbackControl(traceIdOfTurn(turnId));
        state.isProcessing = false;
        const submitButton = document.getElementById('main-submit-button');
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.classList.remove('button-loading');
        }
    }
}

/**
 * Fill search input with suggested text
 */
export function fillSearch(text) {
    const initialInput = document.getElementById('initial-input');
    initialInput.value = text;
    startChat('suggestion');
}

/**
 * Start chat from initial state
 */
// Transition from the hero/landing view to the expanded chat view, WITHOUT
// sending anything. Used both by startChat() (after a typed query) and by the
// app auto-open (where we open straight into a personalized, ready chat).
export function openChatView() {
    const initialState = document.getElementById('initial-state');
    if (initialState) initialState.classList.add('hidden');

    const bottomReassurance = document.getElementById('bottom-reassurance');
    if (bottomReassurance) bottomReassurance.classList.add('hidden');

    const chatContainer = document.getElementById('chat-container');
    if (!chatContainer) return;
    chatContainer.style.display = 'flex';

    void chatContainer.offsetWidth;

    chatContainer.classList.add('visible');
    setChatViewportLock(true);
    syncChatComposerHeight();
    requestAnimationFrame(syncChatComposerHeight);

    // Reset viewport scroll (important before locking body)
    window.scrollTo(0, 0);
}

export function startChat(promptSource = 'typed') {
    const initialInput = document.getElementById('initial-input');
    const message = initialInput.value.trim();
    if (!message) return;

    const initialButton = document.getElementById('initial-submit-button');
    if (initialButton) {
        initialButton.disabled = true;
        initialButton.classList.add('button-loading');
    }

    openChatView();

    document.getElementById('user-input').value = message;

    setTimeout(() => {
        sendMessage(promptSource);
    }, 600);
}

export async function resetChatSession() {
    if (state.isProcessing) {
        return;
    }

    const resetButton = document.getElementById('new-chat-button');
    if (resetButton) {
        resetButton.disabled = true;
    }

    try {
        const response = await fetch('/v3/chat/session/reset', {
            method: 'POST',
            headers: getChatHeaders(),
            body: JSON.stringify({ session_id: state.currentConversationId || null }),
        });
        if (!response.ok) {
            console.warn('[CHAT] Session reset endpoint returned', response.status);
        }
    } catch (error) {
        console.warn('[CHAT] Session reset request failed', error);
    } finally {
        trackConversationReset();
        resetState();
        setLanguage(state.responseLanguage);
        applyRuntimeLanguageLabels();

        const messages = document.getElementById('chat-messages');
        if (messages) {
            messages.innerHTML = '';
        }
        addMessage(t('assistant_greeting'));

        const userInput = document.getElementById('user-input');
        if (userInput) {
            userInput.value = '';
            userInput.dispatchEvent(new Event('input', { bubbles: true }));
        }

        if (resetButton) {
            resetButton.disabled = false;
        }
    }
}
