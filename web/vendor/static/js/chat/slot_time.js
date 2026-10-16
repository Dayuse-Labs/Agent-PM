/**
 * Time-slot formatting in the language of the conversation (Q02).
 *
 * The site's rule (dayuse-com `formatTime.ts`), reproduced as is:
 *   en            -> 11am, 5pm, 11:30am
 *   zh-HK, zh-SG  -> 11:00
 *   other         -> 11h, 11h30
 *
 * No DOM and no import, so it runs in bare node (tests/widget).
 */
export function formatSlotTime(hhmm, lang) {
    if (!hhmm) return '';
    const match = /^(\d{1,2}):(\d{2})/.exec(String(hhmm));
    if (!match) return String(hhmm);
    const hour = parseInt(match[1], 10);
    const minute = match[2];
    const code = String(lang || '').toLowerCase().replace('_', '-');

    if (code === 'zh-hk' || code === 'zh-sg') {
        return `${String(hour).padStart(2, '0')}:${minute}`;
    }
    if (code === 'en' || code.startsWith('en-')) {
        const period = hour >= 12 ? 'pm' : 'am';
        const h12 = hour % 12 === 0 ? 12 : hour % 12;
        return minute === '00' ? `${h12}${period}` : `${h12}:${minute}${period}`;
    }
    return minute === '00' ? `${hour}h` : `${hour}h${minute}`;
}

export function formatSlotRange(start, end, lang) {
    return `${formatSlotTime(start, lang)} – ${formatSlotTime(end, lang)}`;
}
