/**
 * Security utilities for chat rendering and URL validation.
 */

// Every real per-market booking host root. MUST stay a superset of the hosts
// the backend builds from `_MARKET` in libs/b2c_common/b2c_common/hotel_urls.py
// (the old pointer here named agent-usa's `_BOOKING_HOST_BY_COUNTRY`, which
// does not exist in this repo): a host missing here makes sanitizeDayuseUrl
// reject the card URL, and since UX6 removed the name-slugifying fallback the
// card then shows NO hotel-page link at all for that market. Honest, but still
// a silent loss of every booking click — hence the drift test below.
//
// Enforced by `tests/test_market_table_drift.py`, which fails if this list ever
// stops admitting a `_MARKET` host. That test is the whole reason the list can
// stay hand-kept.
//
// Hand-kept on both sides, so it drifts silently. Checked 2026-08-28 (UX6
// audit, reports/AUDIT-MAPPINGS-2026-08-28.md): all 22 `_MARKET` hosts are
// still admitted (0 rejected) — the subdomain rule in isHostMatch covers the
// *.dayuse.com markets. The next market with a genuinely new eTLD is what
// breaks it. `scripts/measure_market_table_drift.py` re-checks this in one run.
const DAYUSE_HOSTS = [
    'dayuse.com',
    'dayuse.fr',
    'dayuse.sg',
    'dayuse.co.uk',
    'dayuse.de',
    'dayuse.es',
    'dayuse.nl',
    'dayuse.be',
    'dayuse.ch',
    'dayuse.at',
    'dayuse.ie',
    'dayuse.se',
    'dayuse.com.hk',
    'dayuse.ae',
    'dayuse-hotels.it',
    'dayuse.net.br',
];
const EXTRA_IMAGE_HOSTS = ['dayuse.twic.pics', 'images.dayuse.com'];

export function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

export function escapeAttr(value) {
    return escapeHtml(value);
}

function isHostMatch(hostname, host) {
    return hostname === host || hostname.endsWith(`.${host}`);
}

export function isDayuseHost(hostname) {
    const normalized = String(hostname || '').toLowerCase();
    return DAYUSE_HOSTS.some(host => isHostMatch(normalized, host));
}

export function isAllowedImageHost(hostname) {
    const normalized = String(hostname || '').toLowerCase();
    return isDayuseHost(normalized) || EXTRA_IMAGE_HOSTS.some(host => isHostMatch(normalized, host));
}

export function sanitizeUrl(rawUrl, options = {}) {
    const {
        requireDayuse = false,
        allowRelative = false,
        allowHost = null,
    } = options;

    if (typeof rawUrl !== 'string') return null;
    const trimmed = rawUrl.trim();
    if (!trimmed) return null;

    if (allowRelative && trimmed.startsWith('/')) {
        return trimmed;
    }

    let url;
    try {
        url = new URL(trimmed);
    } catch (err) {
        return null;
    }

    const protocol = String(url.protocol || '').toLowerCase();
    if (protocol !== 'http:' && protocol !== 'https:') {
        return null;
    }

    const hostname = String(url.hostname || '').toLowerCase();
    if (!hostname) return null;

    if (requireDayuse && !isDayuseHost(hostname)) {
        return null;
    }

    if (typeof allowHost === 'function' && !allowHost(hostname)) {
        return null;
    }

    return url.toString();
}

export function sanitizeDayuseUrl(rawUrl) {
    return sanitizeUrl(rawUrl, { requireDayuse: true });
}

export function sanitizeImageUrl(rawUrl) {
    return sanitizeUrl(rawUrl, { allowHost: isAllowedImageHost });
}
