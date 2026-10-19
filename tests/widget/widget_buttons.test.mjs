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

test('boutons.css : appui = +2 px, Universe en 3 positions', () => {
    const b = read('buttons.css');
    assert.match(b, /translateY\(var\(--press-offset\)\)/);
    assert.match(b, /--universe-sunny-default/);
    assert.match(b, /--universe-sunny-hover/);
    assert.match(b, /--universe-sunny-press/);
    assert.match(read('tokens.css'), /--press-offset:\s*2px/);
    assert.match(read('index.css'), /buttons\.css/);
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
