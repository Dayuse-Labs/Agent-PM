/**
 * Voice Input — Mic button → MediaRecorder → /v3/chat/transcribe (Whisper) → textarea.
 *
 * Cross-browser notes:
 *  - iOS Safari pre-18.4 only supports `audio/mp4` for MediaRecorder; Chrome /
 *    Android / desktop Safari 18.4+ also support `audio/webm;codecs=opus`.
 *  - `MediaRecorder.isTypeSupported('audio/webm')` lies on some older Safari
 *    builds: the constructor still rejects. We test the chosen MIME by trying
 *    `new MediaRecorder(stream, {mimeType})` and fall back to a bare
 *    `new MediaRecorder(stream)` (browser default) if every candidate throws.
 *  - `audioBitsPerSecond` is ignored by Safari and can cause hangs on some
 *    iOS versions, so we only set it for webm.
 *  - `getUserMedia` must be invoked synchronously from the click handler;
 *    `controller.start()` is `async` but its first statement is the
 *    `getUserMedia` call, so the user-gesture is preserved.
 *  - HTTPS (or localhost) is required for `getUserMedia` on iOS — this is an
 *    infra concern, not handled here.
 */

import { getLanguage } from '../i18n.js';

const TRANSCRIBE_ENDPOINT = '/v3/chat/transcribe';
const MAX_RECORDING_MS = 60_000; // hard cap → 60 s of speech

// Ordered from "best size/quality on modern browsers" to "iOS-friendly".
// The constructor is the real source of truth — isTypeSupported lies on
// older Safari versions — so we try each candidate against
// `new MediaRecorder(stream, {mimeType})` and keep the first one that works.
const MIME_CANDIDATES = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4;codecs=mp4a.40.2',
    'audio/mp4',
];

function readMeta(name) {
    return document.querySelector(`meta[name="${name}"]`)?.content?.trim() || '';
}

function buildTranscribeHeaders() {
    const headers = {};
    const token = readMeta('du-chat-public-token');
    const tokenHeader = readMeta('du-chat-public-token-header') || 'X-Chat-Public-Token';
    if (token) headers[tokenHeader] = token;
    return headers;
}

function fileExtForMime(mime) {
    const m = String(mime || '').toLowerCase();
    if (m.includes('mp4') || m.includes('m4a')) return 'm4a';
    if (m.includes('ogg')) return 'ogg';
    if (m.includes('wav')) return 'wav';
    if (m.includes('mpeg') || m.includes('mp3')) return 'mp3';
    return 'webm';
}

function isSupported() {
    return Boolean(
        typeof navigator !== 'undefined'
        && navigator.mediaDevices
        && typeof navigator.mediaDevices.getUserMedia === 'function'
        && typeof MediaRecorder !== 'undefined'
    );
}

/**
 * Try each candidate MIME until the MediaRecorder constructor succeeds.
 * Returns the live recorder + the MIME it ended up using (which is the only
 * MIME we can trust for blob construction + the multipart filename).
 */
function buildRecorder(stream) {
    for (const candidate of MIME_CANDIDATES) {
        if (typeof MediaRecorder.isTypeSupported === 'function'
            && !MediaRecorder.isTypeSupported(candidate)) {
            continue;
        }
        try {
            // Only push audioBitsPerSecond for webm — Safari can choke on it.
            const options = candidate.startsWith('audio/webm')
                ? { mimeType: candidate, audioBitsPerSecond: 32_000 }
                : { mimeType: candidate };
            const recorder = new MediaRecorder(stream, options);
            return { recorder, mimeType: recorder.mimeType || candidate };
        } catch (_e) {
            // Try the next candidate.
        }
    }
    // Last resort — let the browser pick whatever it wants.
    const recorder = new MediaRecorder(stream);
    return { recorder, mimeType: recorder.mimeType || '' };
}

function setBusy(button, busy) {
    if (!button) return;
    button.disabled = Boolean(busy);
}

function setState(button, state) {
    if (!button) return;
    button.classList.toggle('is-recording', state === 'recording');
    button.classList.toggle('is-processing', state === 'processing');
    button.classList.toggle('is-error', state === 'error');
}

function flashError(button) {
    setState(button, 'error');
    setTimeout(() => setState(button, 'idle'), 1500);
}

function insertTranscriptIntoInput(text) {
    const input = document.getElementById('user-input');
    const initial = document.getElementById('initial-input');
    const target = input && input.offsetParent !== null ? input : initial;
    if (!target) return;

    const clean = String(text || '').trim();
    if (!clean) return;

    const existing = String(target.value || '').trim();
    target.value = existing ? `${existing} ${clean}` : clean;
    target.focus();
    target.dispatchEvent(new Event('input', { bubbles: true }));
}

async function postAudio(blob, mimeType) {
    const ext = fileExtForMime(mimeType);
    const form = new FormData();
    // Force the multipart filename to carry a useful extension so the backend
    // (and OpenAI Whisper, which inspects the filename hint) can pick the
    // correct decoder regardless of what Safari labels the blob.
    const file = new File([blob], `voice-input.${ext}`, {
        type: mimeType || 'application/octet-stream',
    });
    form.append('audio', file);
    const language = getLanguage();
    if (language) {
        form.append('language', String(language));
    }

    const response = await fetch(TRANSCRIBE_ENDPOINT, {
        method: 'POST',
        body: form,
        headers: buildTranscribeHeaders(),
        credentials: 'same-origin',
    });

    if (!response.ok) {
        let detail = '';
        try {
            const body = await response.json();
            detail = body && (body.message || body.error) ? String(body.message || body.error) : '';
        } catch (_e) {
            // ignore JSON parse failures — fall back to status
        }
        throw new Error(detail || `transcribe failed: HTTP ${response.status}`);
    }

    const data = await response.json();
    return String(data && data.text ? data.text : '').trim();
}

function createController(button) {
    const state = {
        recorder: null,
        stream: null,
        chunks: [],
        timer: null,
        mimeType: '',
        cancelled: false,
        active: false,
    };

    function teardownStream() {
        if (state.stream) {
            state.stream.getTracks().forEach(track => track.stop());
            state.stream = null;
        }
        if (state.timer) {
            clearTimeout(state.timer);
            state.timer = null;
        }
        state.recorder = null;
        state.chunks = [];
        state.active = false;
    }

    async function start() {
        if (state.active) return;
        if (!isSupported()) {
            console.warn('Voice input not supported in this browser');
            return;
        }

        let stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (err) {
            // NotAllowedError = user denied; NotFoundError = no mic; NotReadableError = busy
            console.warn('Microphone permission denied or unavailable', err);
            flashError(button);
            return;
        }
        state.stream = stream;

        let built;
        try {
            built = buildRecorder(stream);
        } catch (err) {
            console.warn('MediaRecorder constructor failed for every candidate MIME', err);
            teardownStream();
            return;
        }
        state.recorder = built.recorder;
        state.mimeType = built.mimeType;

        state.chunks = [];
        state.cancelled = false;
        state.active = true;

        state.recorder.addEventListener('dataavailable', (event) => {
            if (event.data && event.data.size > 0) {
                state.chunks.push(event.data);
            }
        });

        state.recorder.addEventListener('error', (event) => {
            console.warn('MediaRecorder error', event && event.error);
        });

        state.recorder.addEventListener('stop', async () => {
            const chunks = state.chunks.slice();
            const mime = state.mimeType || (state.recorder && state.recorder.mimeType) || 'audio/webm';
            const wasCancelled = state.cancelled;
            teardownStream();

            if (wasCancelled || chunks.length === 0) {
                setState(button, 'idle');
                setBusy(button, false);
                return;
            }

            setState(button, 'processing');
            setBusy(button, true);

            try {
                const blob = new Blob(chunks, { type: mime });
                const text = await postAudio(blob, mime);
                insertTranscriptIntoInput(text);
            } catch (err) {
                console.warn('Voice transcription failed', err);
                flashError(button);
            } finally {
                setBusy(button, false);
                if (!button.classList.contains('is-error')) {
                    setState(button, 'idle');
                }
            }
        });

        try {
            state.recorder.start();
        } catch (err) {
            console.warn('MediaRecorder.start() failed', err);
            teardownStream();
            return;
        }
        setState(button, 'recording');
        state.timer = setTimeout(() => stop(), MAX_RECORDING_MS);
    }

    function stop() {
        if (!state.active || !state.recorder) return;
        if (state.recorder.state !== 'inactive') {
            try { state.recorder.stop(); } catch (_e) { teardownStream(); }
        } else {
            teardownStream();
        }
    }

    function cancel() {
        state.cancelled = true;
        stop();
    }

    return { start, stop, cancel, isActive: () => state.active };
}

export function initVoiceInput() {
    if (typeof window === 'undefined') return;
    const button = document.getElementById('voice-input-btn');
    if (!button) return;

    if (!isSupported()) {
        button.hidden = true;
        button.setAttribute('aria-hidden', 'true');
        return;
    }

    const controller = createController(button);
    // pointerup/touchend are NOT reliable on iOS for triggering getUserMedia;
    // a plain click handler (which fires after touchend) keeps the user
    // gesture intact and works across Chrome, Safari (incl. iOS), Firefox.
    button.addEventListener('click', (event) => {
        event.preventDefault();
        if (button.disabled) return;
        if (controller.isActive()) {
            controller.stop();
        } else {
            controller.start();
        }
    });
}
