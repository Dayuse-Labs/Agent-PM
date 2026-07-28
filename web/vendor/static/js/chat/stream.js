/**
 * SSE transport for POST /v3/chat/stream.
 *
 * EventSource cannot POST (and cannot carry the chat auth headers), so the
 * stream is read straight off the fetch response body. The facade's frame
 * contract is `progress → hotels → token* → booking_card? → done`, and `done`
 * is ALWAYS terminal — a degraded payload included.
 *
 * No build step: plain ES module, same as every other file under chat/.
 */

/**
 * Parse one raw SSE frame ("event: hotels\ndata: {...}") into {event, data}.
 * Returns null for anything that carries no JSON data (keep-alive comments,
 * malformed frames) — a bad frame must never kill the turn.
 */
function parseFrame(raw) {
    let event = 'message';
    const dataLines = [];
    for (const line of raw.split(/\r?\n/)) {
        if (!line || line.startsWith(':')) continue;  // blank line / keep-alive comment
        const sep = line.indexOf(':');
        const field = sep === -1 ? line : line.slice(0, sep);
        const value = sep === -1 ? '' : line.slice(sep + 1).replace(/^ /, '');
        if (field === 'event') event = value;
        else if (field === 'data') dataLines.push(value);
    }
    if (dataLines.length === 0) return null;
    try {
        return { event, data: JSON.parse(dataLines.join('\n')) };
    } catch (_e) {
        return null;
    }
}

/**
 * Async iterator over the SSE frames of a fetch Response, in arrival order.
 * Yields each frame as soon as the network delivers it — that is the whole
 * point: the `hotels` frame lands seconds before `done`.
 */
export async function* readSseFrames(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
        for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const frames = buffer.split(/\r?\n\r?\n/);
            buffer = frames.pop();
            for (const raw of frames) {
                const frame = parseFrame(raw);
                if (frame) yield frame;
            }
        }
        // A stream closed without its trailing blank line still holds one frame.
        const tail = parseFrame(buffer);
        if (tail) yield tail;
    } finally {
        reader.cancel().catch(() => {});  // release the connection on early exit
    }
}

/**
 * Open the streamed turn. Throws on any failure BEFORE the first frame, which
 * is the caller's cue to fall back to the blocking POST for this turn.
 */
export async function openChatStream(endpoint, headers, requestBody) {
    const response = await fetch(endpoint, {
        method: 'POST',
        headers: { ...headers, Accept: 'text/event-stream' },
        body: JSON.stringify(requestBody),
    });
    if (!response.ok) {
        throw new Error(`stream HTTP ${response.status}`);
    }
    if (!response.body || typeof response.body.getReader !== 'function') {
        throw new Error('stream unsupported: response has no readable body');
    }
    return response;
}
