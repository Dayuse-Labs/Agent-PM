/**
 * DayuseAI Chat Application
 * Main entry point - ES6 Module Architecture
 */

// State
import { state, carousels } from './state.js';

// Tracking
import {
    appendAmplitudeIdToUrl,
    loadAmplitude,
    syncAmplitudeIdentity,
    trackPageview,
    trackSuggestionClick,
} from './tracking.js';

// UI
import { addMessage, showTypingIndicator, hideTypingIndicator } from './ui/messages.js';
import { showThinkingAnimation, hideThinkingAnimation, showFilterThinking } from './ui/thinking.js';
// Voice input (dictaphone) temporarily disabled — import kept commented for an easy revert.
// import { initVoiceInput } from './ui/voice-input.js';

// Hotels
import { createHotelCard, bookHotel } from './hotels/card.js';
import { createHotelCarousel, scrollCarousel, updateCarouselIndicator, updateCarousel, nextSlide, prevSlide } from './hotels/carousel.js';
import { nextImage, prevImage, handleImageScroll, goToImage } from './hotels/images.js';

// Filters
import {
    applyChip,
    chipsInlineHtml,
    suggestionsInlineHtml,
    renderClarify,
    applySuggestion,
    applyClarifyOption,
} from './filters/chips.js';
import { runSearchWithFilters, addFollowUpMessage, handleFollowUp, seeMore } from './filters/search.js';

// Handlers
import { sendMessage, startChat, openChatView, fillSearch, resetChatSession, syncChatComposerHeight, syncChatViewportLock } from './handlers/send.js';
import { setLanguage, t } from './i18n.js';
import { getNativeContext } from './utils.js';
import { getWelcomeEndpoint, getChatHeaders, welcomeRequestBody } from './api.js';

/**
 * App entry: when the page is opened inside the mobile app's webview, the app
 * injects window.__DAYUSE_NATIVE__. Open the chat straight away (skip the hero)
 * and show personalized opening chips from /v3/chat/welcome. No-op on web.
 * Returns true when it took over the entry.
 */
async function startFromAppContext() {
    const native = getNativeContext();
    if (!native) return false;
    const chatContainer = document.getElementById('chat-container');
    if (chatContainer && chatContainer.classList.contains('visible')) return false; // deep link won
    state.entrySource = 'mobile_app';
    syncAmplitudeIdentity();

    openChatView();
    try {
        const resp = await fetch(getWelcomeEndpoint(), {
            method: 'POST',
            headers: getChatHeaders(),
            body: JSON.stringify(welcomeRequestBody(native)),
        });
        if (!resp.ok) return true;
        const data = await resp.json();
        if (data && data.is_personalized) {
            if (data.message) {
                const greeting = document.querySelector(
                    '.chat-messages .message.bot .message-content'
                );
                if (greeting) greeting.textContent = data.message;
            }
            const sugg = Array.isArray(data.suggestions) ? data.suggestions : [];
            const html = suggestionsInlineHtml(sugg, 'welcome', data.near_me);
            if (html) {
                const msg = addMessage(html, false, false, true, true);
                if (msg && msg.classList) msg.classList.add('message--actions');
            }
        }
    } catch (e) {
        /* welcome is best-effort — the chat is already open and usable */
    }
    return true;
}

function normalizeSource(rawValue) {
    return String(rawValue || '').trim().toLowerCase().slice(0, 64);
}

function normalizeQuery(rawValue) {
    return String(rawValue || '')
        .replace(/\u0000/g, '')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 400);
}

function extractEntryContextFromUrl(params) {
    const source = normalizeSource(params.get('source') || '');
    if (source) {
        state.entrySource = source;
    }
}

function startFromDeepLinkQuery() {
    const params = new URLSearchParams(window.location.search);
    const deepLinkQuery = normalizeQuery(params.get('q') || params.get('query'));
    extractEntryContextFromUrl(params);

    if (!deepLinkQuery) {
        return;
    }

    const initialInput = document.getElementById('initial-input');
    if (!initialInput) {
        return;
    }

    initialInput.value = deepLinkQuery;

    // Remove handoff params from URL and avoid re-trigger on refresh.
    params.delete('q');
    params.delete('query');
    params.delete('source');
    params.delete('dayuse_session_id');
    params.delete('du_sid');
    params.delete('du_dayuse_session_id');
    const remaining = params.toString();
    const nextUrl = `${window.location.pathname}${remaining ? `?${remaining}` : ''}${window.location.hash || ''}`;
    window.history.replaceState({}, document.title, nextUrl);

    startChat('initial_prompt');
}

/**
 * Initialize chat application
 */
function initChat() {
    setLanguage(state.responseLanguage);
    applyStaticTranslations();

    extractEntryContextFromUrl(new URLSearchParams(window.location.search));

    // Before startFromDeepLinkQuery, which strips the deep-link params from the URL.
    trackPageview();

    // Enter key handlers
    const userInput = document.getElementById('user-input');
    const mainSubmitButton = document.getElementById('main-submit-button');
    if (userInput) {
        const isTextarea = userInput.tagName === 'TEXTAREA';
        const autosize = () => {
            if (!isTextarea) return;
            userInput.style.height = 'auto';
            userInput.style.height = Math.min(userInput.scrollHeight, 140) + 'px';
            syncChatComposerHeight();
        };
        const updateSendState = () => {
            if (!mainSubmitButton) return;
            const hasContent = userInput.value.trim().length > 0;
            // Only toggle disabled if we're not in a processing/loading state.
            if (!mainSubmitButton.classList.contains('button-loading')) {
                mainSubmitButton.disabled = !hasContent;
            }
        };
        userInput.addEventListener('input', () => { autosize(); updateSendState(); });
        userInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
                e.preventDefault();
                sendMessage();
                // Reset height after submit clears the value.
                requestAnimationFrame(autosize);
            }
        });
        // Initial state.
        autosize();
        updateSendState();
    }
    if (mainSubmitButton) {
        mainSubmitButton.addEventListener('click', () => sendMessage());
    }
    const newChatButton = document.getElementById('new-chat-button');
    if (newChatButton) {
        newChatButton.addEventListener('click', () => {
            void resetChatSession();
        });
    }

    const initialInput = document.getElementById('initial-input');
    if (initialInput) {
        initialInput.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                startChat();
            }
        });
    }
    const initialSubmitButton = document.getElementById('initial-submit-button');
    if (initialSubmitButton) {
        initialSubmitButton.addEventListener('click', () => startChat());
    }

    document.querySelectorAll('[data-action="fill-search-example"]').forEach((example, index) => {
        example.addEventListener('click', () => {
            trackSuggestionClick({ suggestionType: 'search_example', position: index + 1 });
            fillSearch(String(example.textContent || '').trim());
        });
    });
    // 2026-10-28: « près de moi », agent-usa's first entry (489 conversations
    // from September to the switch, 9 in 10 with results). Tapping it is what
    // asks for the device's position — never the words of a typed message.
    const nearMe = document.getElementById('search-example-near-me');
    if (nearMe) {
        nearMe.addEventListener('click', () => {
            // Its own chip kind (contract: suggestion_type is open, added
            // here), at its 1-based place in the hero row: the first.
            trackSuggestionClick({ suggestionType: 'near_me', position: 1 });
            state.requestDeviceLocation = true;
            fillSearch(String(nearMe.textContent || '').trim());
        });
    }

    // Character counters
    setupCharacterCounters();

    // Voice input (dictaphone) temporarily disabled.
    // initVoiceInput();

    // Ensure viewport lock classes reflect actual chat visibility.
    syncChatViewportLock();
    syncChatComposerHeight();

    // Optional deep link: /?q=new+york+400$&source=dayuse_box
    startFromDeepLinkQuery();
    // App webview entry: open straight into a personalized chat (no-op on web,
    // and a no-op when a deep link already opened the chat above).
    void startFromAppContext();
}

function applyStaticTranslations() {
    const heroTitleMain = document.getElementById('hero-title-main');
    if (heroTitleMain) heroTitleMain.textContent = t('hero_title_main');

    const heroTitleEmphasis = document.getElementById('hero-title-emphasis');
    if (heroTitleEmphasis) heroTitleEmphasis.textContent = t('hero_title_emphasis');

    const heroSubtitle = document.getElementById('hero-subtitle');
    if (heroSubtitle) heroSubtitle.textContent = t('hero_subtitle');

    const nearMeExample = document.getElementById('search-example-near-me');
    if (nearMeExample) nearMeExample.textContent = t('near_me_chip');

    const example1 = document.getElementById('search-example-1');
    if (example1) example1.textContent = t('search_example_1');

    const example2 = document.getElementById('search-example-2');
    if (example2) example2.textContent = t('search_example_2');

    const example3 = document.getElementById('search-example-3');
    if (example3) example3.textContent = t('search_example_3');

    const greeting = document.querySelector('.chat-messages .message.bot .message-content');
    if (greeting) greeting.textContent = t('assistant_greeting');

    const initialInput = document.getElementById('initial-input');
    if (initialInput) initialInput.placeholder = t('initial_input_placeholder');

    const chatInput = document.getElementById('user-input');
    if (chatInput) chatInput.placeholder = t('user_input_placeholder');

    const disclaimer = document.querySelector('.chat-footer .disclaimer');
    if (disclaimer) disclaimer.textContent = t('footer_disclaimer');
    const newChatLabel = document.getElementById('new-chat-label');
    if (newChatLabel) {
        newChatLabel.textContent = t('new_chat');
    } else {
        // Fallback for legacy template without the dedicated label span.
        const newChatButton = document.getElementById('new-chat-button');
        if (newChatButton) newChatButton.textContent = t('new_chat');
    }
    const chatHeaderKicker = document.getElementById('chat-header-kicker');
    if (chatHeaderKicker) chatHeaderKicker.textContent = t('ai_concierge_kicker');

    const reassuranceFreeCancel = document.getElementById('reassurance-free-cancel');
    if (reassuranceFreeCancel) reassuranceFreeCancel.textContent = t('reassurance_free_cancel');

    const reassurancePayHotel = document.getElementById('reassurance-pay-hotel');
    if (reassurancePayHotel) reassurancePayHotel.textContent = t('reassurance_pay_hotel');

    const reassuranceDiscount = document.getElementById('reassurance-discount');
    if (reassuranceDiscount) reassuranceDiscount.textContent = t('reassurance_discount');

    const reassuranceLeader = document.getElementById('reassurance-leader');
    if (reassuranceLeader) reassuranceLeader.textContent = t('reassurance_leader');
}

/**
 * Setup character count displays
 */
function setupCharacterCounters() {
    const initialInput = document.getElementById('initial-input');
    const initialCharCount = document.getElementById('initial-char-count');
    const chatInput = document.getElementById('user-input');
    const chatCharCount = document.getElementById('chat-char-count');

    if (initialInput && initialCharCount) {
        initialInput.addEventListener('input', function () {
            const count = this.value.length;
            initialCharCount.textContent = count;
            initialCharCount.style.color = count >= 380 ? '#ff4444' : (count >= 350 ? '#ff9800' : '#999');
        });
    }

    if (chatInput && chatCharCount) {
        chatInput.addEventListener('input', function () {
            const count = this.value.length;
            chatCharCount.textContent = count;
            chatCharCount.style.color = count >= 380 ? '#ff4444' : (count >= 350 ? '#ff9800' : '#999');
        });
    }
}

loadAmplitude();

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', initChat);

/**
 * Expose chatApp to window for backwards compatibility and delegated handlers.
 */
window.chatApp = {
    // State (read-only access for handlers)
    state,
    carousels,

    // Core actions
    sendMessage,
    startChat,
    fillSearch,

    // Tracking
    appendAmplitudeIdToUrl,

    // Messages
    addMessage,

    // Hotels
    createHotelCard,
    createHotelCarousel,
    bookHotel,

    // Image carousel
    nextImage,
    prevImage,
    handleImageScroll,
    goToImage,

    // Hotel carousel
    scrollCarousel,
    updateCarouselIndicator,
    updateCarousel,
    nextSlide,
    prevSlide,

    // Filters
    applyChip,
    handleFollowUp,
    runSearchWithFilters,
    seeMore,

    // Chips
    chipsInlineHtml,
    suggestionsInlineHtml,
    renderClarify,
    applySuggestion,
    applyClarifyOption,

    // Thinking
    showThinkingAnimation,
    hideThinkingAnimation
};

// Also expose key functions globally for backwards compatibility.
window.sendMessage = sendMessage;
window.startChat = startChat;
// Exposed so the app can trigger the personalized open explicitly after it
// injects window.__DAYUSE_NATIVE__ (robust against script-load timing).
window.startFromAppContext = startFromAppContext;
window.fillSearch = fillSearch;
window.handleFollowUp = handleFollowUp;
window.applyChip = applyChip;
window.scrollCarousel = scrollCarousel;
window.nextImage = nextImage;
window.prevImage = prevImage;
window.handleImageScroll = handleImageScroll;
window.bookHotel = bookHotel;
window.syncDayuseAmplitudeContext = syncAmplitudeIdentity;
window.runSearchWithFilters = runSearchWithFilters;
window.seeMore = seeMore;
