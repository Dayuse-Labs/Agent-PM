/**
 * mcp-dayuse#6: the widget marks a conversation whose server profile expired.
 * The label must exist in every locale the widget speaks — a missing one
 * falls back to the raw key "session_expired" on screen.
 *
 * Run by `tests/test_market_table_drift.py::TestWidgetUrlContract` with every
 * other suite of this directory.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

const CHAT = new URL('../../web/vendor/static/js/chat/', import.meta.url);
const { setLanguage, t } = await import(new URL('i18n.js', CHAT));

test('the expiry notice is translated in all 7 locales', () => {
    for (const language of ['en', 'fr', 'es', 'it', 'pt', 'de', 'nl']) {
        setLanguage(language);
        const label = t('session_expired');
        assert.notEqual(label, 'session_expired', language);
        assert.ok(label.length > 10, language);
    }
});
