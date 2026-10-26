// Boutons (fondations Dayuse : Depth, Effects, Motion) : plus de soulèvement au survol,
// descente de 2 px à l'appui, soleil (dégradé Sunny) réservé aux boutons Universe.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const css = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../web/vendor/static/css/chat');
const read = (f) => readFileSync(path.join(css, f), 'utf8');
const sheets = readdirSync(css).filter((f) => f.endsWith('.css'));

test('aucun survol ne déplace un bouton (translateY négatif ou scale)', () => {
    for (const f of sheets) {
        const src = read(f);
        const hover = src.match(/[^{}]*:hover[^{}]*\{[^}]*\}/g) || [];
        for (const rule of hover) {
            assert.ok(!/translateY\(-?[12]px\)|scale\(1\.\d+\)/.test(rule), `${f} : mouvement au survol :\n${rule}`);
        }
    }
});

test('aucun transition: all', () => {
    for (const f of sheets) assert.ok(!/transition:\s*all/.test(read(f)), `${f} : transition: all`);
});

test('boutons.css : appui = +2 px, Primary (jaune Dayuse) en 3 états', () => {
    const b = read('buttons.css');
    assert.match(b, /translateY\(var\(--press-offset\)\)/);
    assert.match(b, /--action-primary-default/);
    assert.match(b, /--action-primary-hover/);
    assert.match(b, /--action-primary-press/);
    assert.match(read('tokens.css'), /--press-offset:\s*2px/);
    assert.match(read('index.css'), /buttons\.css/);
});

// Retour PO du 2026-10-26 : les boutons d'action portent le jaune Dayuse, comme le bouton
// primaire de dayuse.com (#FFAF36 → Sunshine Yellow #FFC536, texte Shadow Black #292935).
test('jaune Dayuse : valeurs de la marque, texte sombre', () => {
    const t = read('tokens.css');
    assert.match(t, /--action-primary-default:\s*linear-gradient\(62deg, #ffaf36 0%, #ffc536 100%\)/);
    assert.match(t, /--action-primary-hover:\s*linear-gradient\(62deg, #ff9f26 0%, #ffb526 100%\)/);
    assert.match(t, /--action-primary-fg:\s*#292935/);
});

test('envoi, CTA des cartes et réservation sont en jaune ; puces et liens restent calmes', () => {
    const b = read('buttons.css');
    const primary = /\/\* ===== Primary[^\n]*\n([^{]*)\{([^}]*)\}/.exec(b);
    assert.ok(primary, 'bloc Primary absent');
    const selectors = primary[1].split(',').map((x) => x.trim());
    for (const sel of ['#initial-submit-button', '.composer-send-btn', '.pick-cta', '.booking-card__cta', '.book-button']) {
        assert.ok(selectors.includes(sel), `${sel} hors du jaune`);
    }
    for (const sel of ['.chip', '.search-example', '.response-card__link', '.chat-header-reset']) {
        assert.ok(!selectors.includes(sel), `${sel} ne doit pas être jaune`);
    }
    assert.match(primary[2], /background:\s*var\(--action-primary-default\)/);
    assert.match(primary[2], /color:\s*var\(--action-primary-fg\)/);
    // Contre-épreuve : plus aucun bouton sur le dégradé Sunny (orange → corail).
    assert.ok(!/--universe-sunny/.test(b), 'Universe Sunny encore sur un bouton');
    // Le CTA de carte n'a plus de fond sombre propre qui écraserait le jaune.
    const pick = /\.pick-cta\s*\{([^}]*)\}/.exec(read('hotels.css'))[1];
    assert.ok(!/background/.test(pick), `.pick-cta garde un fond : ${pick}`);
});

test('Sunny : ellipse 300 % x 200 %, centre sur le bord haut, stops 13/50/75/87', () => {
    const t = read('tokens.css');
    for (const x of ['150%', '50%', '-50%']) {
        assert.ok(t.includes(`radial-gradient(ellipse 300% 200% at ${x} 0%`), `centre ${x}`);
    }
    assert.match(t, /#ffc536 13%, #fa9f64 50%, #f78584 75%, #f66236 87%/);
});

test('le bouton global n\'a plus le dégradé jaune fixe', () => {
    assert.ok(!/FFAF36|ffaf36/.test(read('forms.css').split('/* ===== CHIPS')[0]));
});
