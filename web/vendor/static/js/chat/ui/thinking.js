/**
 * Thinking Animation
 * Loading states and dynamic progress messages
 */

import { state } from '../state.js';
import { t } from '../i18n.js';

const AI_AVATAR_SVG = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2 13.9 8.1 20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2Z"/><path d="M19 14l.95 3.05L23 18l-3.05.95L19 22l-.95-3.05L15 18l3.05-.95L19 14Z" opacity=".7"/></svg>';

function buildThinkingMessageHtml(text) {
    return `
        <div class="avatar avatar--ai" aria-hidden="true">${AI_AVATAR_SVG}</div>
        <div class="message-content thinking-content">
            <div class="thinking-loader">
                <div class="thinking-text" id="loading-text">${text}</div>
            </div>
        </div>
    `;
}

/**
 * Show thinking animation with dynamic messages
 */
export function showThinkingAnimation(isFollowUp = false) {
    const loadingMessage = document.createElement('div');
    loadingMessage.id = 'loading-message';
    loadingMessage.className = 'message bot thinking-message';
    loadingMessage.innerHTML = buildThinkingMessageHtml(
        isFollowUp ? t('thinking_analyzing') : t('thinking_understanding')
    );
    document.getElementById('chat-messages').appendChild(loadingMessage);
    return loadingMessage;
}

/**
 * Create dynamic thinking steps animation
 * Returns both the loading message element and the interval for cleanup
 */
export function createThinkingSteps(isFollowUp = false) {
    const cityHint = state.selectedFilters.city || state.selectedFilters.metro || '';
    const searchStep = cityHint
        ? t('thinking_searching_city', { city: cityHint })
        : t('thinking_searching');

    const steps = isFollowUp ? [
        t('thinking_analyzing'),
        t('thinking_refining'),
        t('thinking_finding_matches'),
    ] : [
        t('thinking_understanding'),
        searchStep,
        t('thinking_matching'),
        t('thinking_finding_options'),
    ];

    // Create loading message element
    const loadingMessage = document.createElement('div');
    loadingMessage.id = 'loading-message';
    loadingMessage.className = 'message bot thinking-message';
    loadingMessage.innerHTML = buildThinkingMessageHtml(steps[0]);
    document.getElementById('chat-messages').appendChild(loadingMessage);

    // Start stepping through messages
    let stepIndex = 0;
    const interval = setInterval(() => {
        stepIndex++;
        if (stepIndex < steps.length) {
            const loadingText = document.getElementById('loading-text');
            if (loadingText) {
                loadingText.textContent = steps[stepIndex];
            }
        }
    }, 1500);

    return { loadingMessage, interval };
}

/**
 * Hide thinking animation
 */
export function hideThinkingAnimation() {
    const loadingMsg = document.getElementById('loading-message');
    if (loadingMsg) loadingMsg.remove();
}

/**
 * Show simple filter thinking animation
 */
export function showFilterThinking() {
    const loadingMessage = document.createElement('div');
    loadingMessage.id = 'loading-message';
    loadingMessage.className = 'message bot thinking-message';
    loadingMessage.innerHTML = buildThinkingMessageHtml(t('thinking_filtering'));
    document.getElementById('chat-messages').appendChild(loadingMessage);
}
