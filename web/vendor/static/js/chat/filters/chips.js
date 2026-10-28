/**
 * Filter Chips
 * UI chips for filtering hotel results
 */

import { state } from '../state.js';
import { trackSuggestionClick } from '../tracking.js';
import { addMessage } from '../ui/messages.js';
import { runSearchWithFilters } from './search.js';
import { escapeAttr, escapeHtml } from '../security.js';
import { t } from '../i18n.js';

/**
 * Apply chip filter
 */
export function applyChip(btn) {
    const type = btn.dataset.type;
    const value = btn.dataset.value;
    const min = btn.dataset.min;
    const max = btn.dataset.max;

    console.log('Chip clicked:', { type, value, min, max });

    if (type === 'timeslot') {
        state.selectedFilters.timeslot = value;
    } else if (type === 'budget') {
        if (min) state.selectedFilters.budget_min = parseFloat(min);
        if (max) state.selectedFilters.budget_max = parseFloat(max);
    } else if (type === 'amenity') {
        const list = new Set(state.selectedFilters.amenities || []);
        list.add(value);
        state.selectedFilters.amenities = Array.from(list);
        addMessage('Filter: ' + value, true);
    } else if (type === 'city') {
        state.selectedFilters.city = value;
    } else if (type === 'faq') {
        const questions = {
            'annulation': 'Comment annuler ma réservation?',
            'paiement': 'Quels modes de paiement acceptez-vous?',
            'cancel': 'How can I cancel my reservation?',
            'payment': 'What payment methods do you accept?'
        };
        const question = questions[value] || value;
        document.getElementById('user-input').value = question;
        window.chatApp.sendMessage();
        return;
    }

    runSearchWithFilters();
}

/**
 * Generate inline chips HTML
 */
export function chipsInlineHtml(chips) {
    if (!Array.isArray(chips) || chips.length === 0) return '';

    const timeslotChips = chips.filter(c => c.type === 'timeslot');
    const budgetChips = chips.filter(c => c.type === 'budget');

    let html = '';

    if (timeslotChips.length > 0) {
        html += '<div class="chip-group">';
        html += `<div class="chip-group__label">${escapeHtml(t('timeslots_heading'))}</div>`;
        html += '<div class="chips-inline">';
        timeslotChips.forEach(c => {
            const val = c.value ? ` data-value="${c.value}"` : '';
            html += `<button class="chip" data-type="timeslot" data-action="apply-chip"${val}>${c.label}</button>`;
        });
        html += '</div></div>';
    }

    if (budgetChips.length > 0) {
        html += '<div class="chip-group">';
        html += `<div class="chip-group__label">${escapeHtml(t('price_range_heading'))}</div>`;
        html += '<div class="chips-inline">';
        budgetChips.forEach(c => {
            const min = c.value && c.value.min != null ? ` data-min="${c.value.min}"` : '';
            const max = c.value && c.value.max != null ? ` data-max="${c.value.max}"` : '';
            html += `<button class="chip" data-type="budget" data-action="apply-chip"${min}${max}>${c.label}</button>`;
        });
        html += '</div></div>';
    }

    return html;
}

/**
 * Generate suggestions HTML — chips row rendered under a bot message.
 *
 * Stays a string of `.chip` buttons (no wrapping div) so consumers can drop it
 * into their own container; `renderSuggestionsRow` wraps it in `.suggestions`
 * when needed.
 */
export function suggestionsInlineHtml(sugg, suggestionType, nearMeLabel = null) {
    if (!Array.isArray(sugg) || sugg.length === 0) return '';
    const turnAttr = state.currentTurnId ? ` data-turn-id="${escapeAttr(state.currentTurnId)}"` : '';
    // 2026-10-28: the welcome view names its « near me » chip (`near_me`): that
    // button, once tapped, asks for the device's position with its message.
    const nearMe = typeof nearMeLabel === 'string' ? nearMeLabel.trim() : '';
    const items = sugg.map(text => {
        const raw = String(text || '').trim();
        if (!raw) return '';
        const isNearMe = Boolean(nearMe) && raw === nearMe;
        const nearMeAttr = isNearMe ? ' data-near-me="1"' : '';
        // The « near me » chip is tracked as its own kind, not as `welcome`
        // like the city chips next to it (review of #173).
        const type = isNearMe ? 'near_me' : suggestionType;
        return `<button class="chip chip--suggestion" data-action="apply-suggestion" data-suggestion-type="${escapeAttr(type)}"${turnAttr}${nearMeAttr} data-suggestion="${escapeAttr(raw)}">${escapeHtml(raw)}</button>`;
    }).filter(Boolean).join('');
    if (!items) return '';
    return `<div class="suggestions">${items}</div>`;
}

export function applySuggestion(button) {
    const suggestion = String(button?.dataset?.suggestion || '').trim();
    if (!suggestion) return;
    const input = document.getElementById('user-input');
    if (!input) return;

    const siblings = button.parentElement
        ? Array.from(button.parentElement.querySelectorAll('.chip--suggestion'))
        : [];
    trackSuggestionClick({
        turnId: button.dataset.turnId,
        suggestionType: button.dataset.suggestionType,
        position: siblings.indexOf(button) + 1,
    });

    if (button.dataset.nearMe === '1') state.requestDeviceLocation = true;
    input.value = suggestion;
    window.chatApp.sendMessage('suggestion');
}

/**
 * Render clarification options
 */
export function renderClarify(clarify) {
    if (!clarify || !clarify.question) return;

    let html = `<div class="suggestions">${escapeHtml(String(clarify.question))}</div>`;
    if (Array.isArray(clarify.options)) {
        const buttons = clarify.options.map(opt => {
            const option = String(opt || '').trim();
            if (!option) return '';
            return `<button class="chip" data-action="apply-clarify-option" data-clarify-option="${escapeAttr(option)}">${escapeHtml(option)}</button>`;
        }).join(' ');
        html += `<div class="chips-inline">${buttons}</div>`;
    }
    addMessage(html, false, false, false, true);
}

export function applyClarifyOption(button) {
    const option = String(button?.dataset?.clarifyOption || '').toLowerCase();
    if (option.startsWith('matin') || option.startsWith('morning')) {
        window.chatApp.state.selectedFilters.timeslot = 'morning';
    } else if (option.startsWith('ap') || option.startsWith('after')) {
        window.chatApp.state.selectedFilters.timeslot = 'afternoon';
    } else {
        window.chatApp.state.selectedFilters.timeslot = 'evening';
    }
    window.chatApp.runSearchWithFilters();
}
