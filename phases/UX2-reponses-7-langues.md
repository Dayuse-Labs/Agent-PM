# UX2 — Répondre dans les 7 langues déjà reconnues

> Issu de la liste Fabien du 2026-08-27, item 2 (« tester avec des langues plus exotiques »).
> **Scope arbitré par Fabien le 2026-08-27 : élargir aux 7 langues déjà reconnues.** Pas de
> langue arbitraire (japonais / arabe / thaï), qui serait un chantier d'architecture séparé.

## État des lieux — le clamp est volontaire, documenté, et aujourd'hui incohérent

Trois faits, tous dans le code :

1. **Le triage reconnaît 7 langues.** `agents/b2c_concierge/b2c_concierge/triage.py:86-88`
   ```python
   LANGUAGES = ("fr", "en", "es", "it", "de", "pt", "nl")
   TEMPLATE_LANGUAGES = ("fr", "en")
   FALLBACK_RESPONSE_LANGUAGE = "en"
   ```
2. **`response_language()` clampe toute réponse à fr/en** (`triage.py:193-210`), et sa
   docstring cite explicitement une review de Fabien (PR #34) : élargir la *reconnaissance*
   ne doit pas élargir silencieusement ce dans quoi on *répond*. Le clamp était le bon choix
   à ce moment-là.
3. **Le widget, lui, est déjà traduit dans les 7 langues.** `web/vendor/static/js/chat/i18n.js`
   porte `en, fr, es, it, pt, de, nl` (lignes 39, 147, 255, 363, 471, 579, 687).

Conséquence actuelle : un utilisateur italien reçoit une **coquille d'interface en italien
autour d'une réponse en anglais**. Ce n'est pas une limite assumée, c'est une incohérence
visible. Et P1-1 a déjà payé le prix d'entrée : le triage lit correctement « sí » / « sì » /
« ja » depuis l'élargissement à 7 langues (`triage.py:61-65`) — la compréhension marche déjà,
seule la production est bloquée.

## Ce qui est déjà multilingue (ne pas le refaire)

- La **synthèse** : `agent.py:600` passe `LANG: {language}` au prompt de synthèse. Le LLM sait
  déjà répondre dans n'importe laquelle des 7. Le travail porte sur les **templates
  déterministes**, pas sur la synthèse.
- `amenity_guard._CLAIM_NEGATION_MARKERS` (`amenity_guard.py:40-49`) contient déjà les
  marqueurs es/it/de/nl et les traductions du hedge (`non confermato`, `nicht bestätigt`,
  `niet bevestigd`). Quelqu'un a déjà anticipé ce chantier.
- `_AMENITY_CLAIM_PATTERNS` (`amenity_guard.py:25-38`) couvre déjà es/it partiellement
  (`piscinas`, `desayuno`, `colazione`, `parcheggio`, `aparcamiento`).

## Périmètre — les sites du clamp

À traiter (liste établie par grep, à re-vérifier en début de phase) :

| Fichier | Site | Nature |
|---|---|---|
| `b2c_concierge/templates.py` | tout le module | **le gros du volume** : `_pick()` binaire l.11, `_INLINE_UNRESOLVED_FR/EN` l.27/41, branches `if language == "fr"` l.83/108, `_DEGRADED_FR/EN` l.145/149, textes inline l.211-213 |
| `b2c_concierge/triage.py` | `TEMPLATE_LANGUAGES` l.87 | lever le clamp |
| `b2c_concierge/triage.py` | `template_language()` l.178-190 | `valid = ... in ("fr","en")` → les 7 |
| `b2c_concierge/triage.py` | `locale_response_language()` l.165-176 | rend `None` hors fr/en → rendre les 7 |
| `b2c_concierge/agent.py` | l.1080 | `if triage.language in ("fr","en")` → les 7 |
| `hotel_search_agent/response_bridge.py` | `_profile_language()` l.1101-1107 | `in ("fr","en") else "en"` → les 7 |
| `b2c_concierge/amenity_guard.py` | `_HEDGE_FR` l.166 | le hedge doit suivre la langue de réponse |

## Ce qu'il faut faire

### 1. Remplacer `_pick` binaire par une table par langue

`templates.py:11` (`return fr if language == "fr" else en`) ne s'étend pas. Le passer en
lookup avec **fallback explicite sur `en`** — le fallback doit rester dans le code, pas dans
une clé manquante qui rendrait `KeyError` en prod.

Contrainte de forme : les tables restent des **constantes de module** et les fonctions gardent
leur signature `(*, ..., language: str) -> str`. Aucun appelant ne doit changer.

### 2. Traduire

~93 chaînes littérales dans `templates.py` × 5 nouvelles langues. C'est du volume mécanique —
c'est ce qui rend cette phase adaptée à Sonnet.

Source de vérité de style : **`web/vendor/static/js/chat/i18n.js`**. Les 7 blocs y sont déjà
rédigés par langue ; réutiliser leur registre, leur tutoiement/vouvoiement et leur vocabulaire
métier (« créneau » / « franja » / « fascia »…) au lieu d'inventer une seconde voix. Une
divergence de ton entre la bulle de chat et l'UI autour serait le même défaut, déplacé.

### 3. Lever le clamp, en dernier

`TEMPLATE_LANGUAGES = LANGUAGES` **seulement quand toutes les tables sont complètes**. Sinon
le fallback `en` masque les trous et on livre du franglais par langue.

## Hors périmètre

- Le japonais, l'arabe, le thaï, et toute langue hors des 7. Décision de Fabien.
  Un `LANGUAGES` élargi impliquerait un RTL côté widget et une refonte des templates
  déterministes en génération — autre chantier.
- Le nom de chambre du partenaire (`ratePlanName`) reste **non traduit**, comme aujourd'hui,
  et pour la raison déjà écrite dans `messages.js:667-669` : « pretending to have translated
  it would be worse ». Ne pas « améliorer » ça.
- `evalset/` et `dayuse_eval_pack/` : un élargissement des scénarios d'eval par langue est
  légitime mais c'est UX2-bis, pas UX2.

## Pièges

- 🪤 **`locale_response_language` est le vrai point d'entrée en prod**, pas
  `guess_language`. Sa docstring l.178-184 dit pourquoi : les indices français de
  `guess_language` **se déclenchent à tort sur les autres langues romanes**. En élargissant, ce
  faux positif devient beaucoup plus probable (un message italien qui matche `_FR_HINTS`).
  Vérifier que la locale déclarée garde la priorité et que le guess reste le dernier recours.
- 🪤 `_ACK_RE` / `_ACK_WORDS` (`triage.py:97-105`) est fr/en seulement. Un « grazie » ou un
  « danke » nu ne matche pas et part au triage LLM — ce n'est **pas un bug** (le triage LLM
  gère), mais ça coûte un appel. Le mesurer, décider ensuite. Ne pas gonfler la regex par
  réflexe.
- 🪤 Le fallback `en` doit rester **atteignable et testé** : une langue reconnue mais dont une
  table est incomplète doit rendre de l'anglais propre, jamais un `KeyError` en prod.
- 🪤 `pt` : le repo ne distingue pas pt-PT de pt-BR, et les deux marchés existent
  (`_MARKET` a `PT` → `pt.dayuse.com` et `BR` → `www.dayuse.net.br`). Choisir **une** variante,
  l'écrire dans le fichier, et ne pas ouvrir le sujet ici.
- 🪤 UX5 doit être mergée **avant** cette phase (elle réécrit `booking_link_response`, que UX2
  va traduire).

## DoD

1. Table complète pour les 7 langues sur **toutes** les fonctions de `templates.py`, avec un
   test paramétré qui itère `LANGUAGES` et assère qu'aucune ne retombe sur l'anglais par
   accident (comparaison à la chaîne EN → doit différer, sauf cas légitime documenté).
2. Test du fallback : une langue hors table rend l'anglais, sans exception.
3. Test de non-régression fr/en : les chaînes existantes sont **inchangées** (c'est le
   contrat iso avec agent-usa sur les marchés fr/en, les deux plus gros).
4. `pytest -q` vert (baseline 1452 passed, 1 skipped), `ruff`, `mypy`, guardrails verts.
5. **Preuve prod, 5 langues × 1 tour minimum** via le proxy widget (`x-dayuse-synthetic: 1`),
   session fraîche chacun : es, it, de, pt, nl. Vérifier qu'aucune réponse ne **mélange** deux
   langues (le vrai risque : template traduit + synthèse dans une autre langue, ou l'inverse).
   Coller les 5 réponses dans le HANDOFF.
6. Vérifier `response_language` dans l'event SSE `progress` (`agent.py:514`) : le widget boote
   dans cette langue, un mismatch produit un rendu mixte sur 6 des 7 locales — c'est
   exactement le bug S-PERF4 déjà corrigé, ne pas le rouvrir.
7. `HANDOFF.md` : bloc daté.
