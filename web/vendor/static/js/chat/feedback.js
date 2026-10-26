/**
 * OBS5 — user feedback (👍/👎) on a turn's response.
 *
 * Posted to the concierge's own `/v3/feedback` route, NOT straight to
 * Langfuse with a public key (the pattern the OBS2-LANGFUSE-BRIEF §3
 * originally sketched): self-hosted Langfuse has no documented/built-in CORS
 * support on its ingestion endpoint, while every /v3/* path here is already
 * proxied same-origin by the widget service. See
 * phases/OBS5-user-feedback.md for the full reasoning. Net effect: the
 * browser never holds any Langfuse key at all — only the turn's trace_id
 * (already public via the `progress` SSE frame) and the same internal API
 * key that already gates every other /v3/* route.
 *
 * Fire-and-forget: a feedback click must never block or break the chat UI.
 */
import { getFeedbackEndpoint, getChatHeaders } from './api.js';

export function submitFeedback(traceId, value, comment) {
    if (!traceId) return;
    const body = { trace_id: traceId, value };
    if (comment) body.comment = comment;
    fetch(getFeedbackEndpoint(), {
        method: 'POST',
        headers: getChatHeaders(),
        body: JSON.stringify(body),
    }).catch(err => console.warn('[CHAT] feedback POST failed:', err));
}
