# Q02 — Créneau dans la langue de la conversation

| | |
|---|---|
| **Phase** | 1 |
| **Modèle** | sonnet — correctif borné au widget, la règle à reproduire est donnée |
| **Effort** | low |
| **Dépend de** | — |
| **Prérequis** | E1, E2 |
| **Zone (owned_files)** | `web/vendor/static/js/chat/utils.js` · `web/vendor/static/js/chat/hotels/card.js` · `web/vendor/static/js/chat/ui/messages.js` · `tests/widget/widget_slot_time.test.mjs` (neuf) |

## Contexte utile
- Retour 1 de Raphael. Capture : conversation en français, carte « B&B HOTEL Lyon Nord » avec la pastille `10am - 4pm`. Raphael écrit « cut-off », mais il parle bien du créneau : confirmé par Fabien le 2026-10-14.
- `web/vendor/static/js/chat/utils.js:46` `formatTimeAMPM` : am/pm en dur, aucune langue en entrée. Appelé à `hotels/card.js:677-678` et `:717-718`.
- `web/vendor/static/js/chat/ui/messages.js:663` : la carte de réservation affiche `${plan.start_time} – ${plan.end_time}` brut (`10:00 – 16:00`), un 3e format.
- `formatRating` dans `utils.js` se formate déjà selon la langue de la **conversation** (S-CX8). Suivre le même modèle : `getLanguage()` de `i18n.js`.
- Règle du site, à reproduire telle quelle (`~/PhpstormProjects/dayuse-com/apps/frontend/web/utils/formatTime.ts`) :
  - `en` → `11am`, `5pm`, `11:30am` ;
  - `zh-HK` et `zh-SG` → `11:00` ;
  - toutes les autres langues → `11h`, `11h30`.
- Les tests `node:test` de `tests/widget/` sont aussi lancés par pytest (`tests/test_market_table_drift.py`).

## Notes d'implémentation
- Un seul formateur, par exemple `formatSlotTime(hhmm)`, calculé depuis `HH:MM`. Pas de `replace` sur une chaîne Intl : les heures arrivent déjà en `HH:MM`.
- Il remplace `formatTimeAMPM` aux 3 endroits. Supprimer `formatTimeAMPM` s'il n'a plus d'appelant.
- Ne pas toucher `libs/b2c_common/b2c_common/search_page.py:48` (`6am`) : c'est le format d'URL du site, pas un affichage.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
node --test tests/widget/
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- `tests/widget/widget_slot_time.test.mjs` couvre `fr` (`10h – 16h`, `10h30`), `en` (`10am – 4pm`, `4:30pm`), `zh-HK` (`10:00`) et une autre langue du widget.
- La carte de liste et la carte de réservation passent par le même formateur (visible dans le diff).
- Contrôle négatif : avec l'ancien `utils.js`, le cas `fr` du nouveau test échoue (noté dans le rapport).
- Aucun appelant restant de `formatTimeAMPM`.

## Hors périmètre
Toute modification backend.
