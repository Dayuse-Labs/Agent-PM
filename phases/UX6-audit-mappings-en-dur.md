# UX6 — Audit des mappings en dur : lesquels sont légitimes, lesquels sont de la dette

> Issu de la liste Fabien du 2026-08-27, item 6 : « On commence à avoir plusieurs mappings en
> dur. Voir comment on pourrait s'en passer. »
> **C'est une phase d'étude**, pas une phase de refactor. Le livrable principal est un
> rapport ; les suppressions ne se font que là où la preuve est faite.

## La thèse à défendre ou à réfuter

Le repo contient une vingtaine de tables en dur, mais **elles ne sont pas un seul problème**.
Trois catégories, et une seule est de la dette :

### Catégorie 1 — contrats code-owned : à GARDER, et à défendre

Ce sont des tables qui existent **parce qu'un LLM ne doit pas décider de leur valeur**. Les
supprimer réintroduirait le bug qu'elles ferment.

- `EQUIPMENT_IDS` (`hotel_search_agent/equipment_ids.py:42`) — **le cas le plus important à ne
  pas toucher.** Sa docstring : laissé à lui-même le modèle hallucine un ID (« piscine » →
  `[1]`), et un filtre dur sur un ID inexistant rend zéro offre en ayant l'air d'une recherche
  saine (reproduit live le 2026-07-20 : Miami `[33]` → 44 hôtels, `[1]` → 0). La table encode
  aussi une asymétrie serveur non déductible (les IDs de piscine sont OR-groupés, les autres
  AND-requis) et des **non-mappings délibérés** (parking, rooftop). C'est de l'ingénierie, pas
  de la dette.
- `GUARD_SCORE_NAMES` (`libs/b2c_common/scores.py`) — contrat de séries temporelles Langfuse.
  Renommer casse l'historique. Immuable par construction.
- `_AMENITY_CLAIM_PATTERNS` / `_CLAIM_NEGATION_MARKERS` (`amenity_guard.py`) — les motifs d'un
  guard de vérité. Un guard dont les motifs sont dynamiques n'est plus un guard.
- `ROUTES` / `LEAF_ENDPOINTS` (`routing.py`) — la table de routage **est** le pattern
  `cs_copilot` imposé par CLAUDE.md (« table de routage en code »).
- `PICKS`, `BOOKING_CONFIRMATIONS`, `LANGUAGES` (`triage.py`) — enums fermées validées côté
  code, dont la docstring explique que c'est précisément le mécanisme qui empêche le LLM de
  décider (`triage.py:54-57`).

**Livrable pour cette catégorie : une justification écrite par table**, pour que la prochaine
personne qui lit « mappings en dur » ne les supprime pas par hygiène mal placée.

### Catégorie 2 — duplication entre langages : la vraie dette, et elle a déjà coûté cher

`_MARKET` (`libs/b2c_common/b2c_common/hotel_urls.py:29-53`, 22 lignes, Python) et
`COUNTRY_META` (`web/vendor/static/js/chat/markets.js:9`, JS) décrivent **le même référentiel
de marchés** — hosts et slugs pays — dans deux langages, tenus à la main.

Le module lui-même dit pourquoi c'est grave (`hotel_urls.py:8-10`) :

> « Shared lib on purpose: the search leaf and the concierge inline tools must build from ONE
> market table — **agent-usa 2026-07-06 shipped a 4-day 404 outage precisely because two
> hand-kept host lists drifted apart.** »

La leçon a été appliquée **entre les deux agents Python** et pas **entre le back et le front**.
La même panne est reproductible aujourd'hui.

Piste à évaluer (ne pas l'implémenter avant l'accord de Fabien) : une source unique — un JSON
du référentiel, servi par la façade ou généré au build du widget — plutôt qu'un troisième
recopiage. Chiffrer le coût, dire ce que ça casse, laisser trancher.

### Catégorie 3 — tables dont MCP a déjà la donnée : candidats à la suppression

C'est ici qu'on peut réellement « s'en passer ».

- **`_ISO_BY_COUNTRY_NAME` (`hotel_urls.py:57-83`, 25 lignes)** — le meilleur candidat. Elle
  existe pour une raison datée : *« search_offers sends `countryName`, never an ISO code
  (probed 2026-07-20) »*. Mais depuis, **`countryCode` est bien présent dans le payload** et
  les deux appelants le passent déjà en premier argument :
  `inline_tools.py:319` et `response_bridge.py:571` appellent
  `build_hotel_page_url(slug, hotel.get("countryCode"), countryName…)`.
  → **À mesurer** : sur un échantillon réel, quel pourcentage d'hôtels porte un `countryCode`
  exploitable ? Si c'est 100 %, la table de noms devient un fallback mort et peut se réduire
  ou disparaître. Si c'est 97 %, elle reste — et on l'écrit.
- `_LOCALE_COUNTRY` (`geocode_tool.py:50`) — même question : la locale native arrive
  maintenant par la façade (S-G2), vérifier si la table est encore sur le chemin chaud.
- `_EXONYM_EQUIVALENTS` (`geo_guards.py:274`) — probablement irréductible (les exonymes ne
  sont dans aucune API qu'on interroge), mais le dire après avoir regardé.
- `US_STATE_*` (`geo_guards.py:49-56`) — **déjà** dérivées du paquet `us`, pas en dur.
  Exemple de ce à quoi ressemble le bon état final : citer comme référence.

## Méthode

1. **Inventaire exhaustif** — les greps de départ (à re-lancer, la liste ci-dessous est du
   2026-08-27) :
   ```bash
   grep -rn "^_\?[A-Z_]\{3,\}\(: *[Dd]ict\| *= *{\)" agents libs --include='*.py' | grep -v "/tests/"
   grep -rn "^const [A-Z_]\{3,\} = {\|^const [A-Z_]\{3,\} = \[" web/vendor/static/js/chat/
   ```
2. **Classer** chaque table dans une des 3 catégories, avec la justification et la ligne de
   code qui la soutient.
3. **Mesurer** les candidats de la catégorie 3 (le seul travail live de la phase).
4. **Exécuter uniquement les suppressions prouvées** — celles où la mesure montre que la table
   n'est plus atteinte, ou n'est plus qu'un fallback pour un cas que MCP couvre.
5. **Rapport** dans `reports/AUDIT-MAPPINGS-<date>.md`, avec la catégorie 2 chiffrée et
   proposée à l'arbitrage.

## Hors périmètre

- Toute suppression en catégorie 1. Si la phase conclut qu'une table de catégorie 1 doit
  bouger, elle **s'arrête et pose la question** — c'est une décision de Fabien, pas un
  sous-produit d'un audit.
- Unifier `_MARKET` / `COUNTRY_META` **dans cette phase**. On chiffre, on propose. Le faire
  touche la façade, le widget et le builder d'URL en même temps : c'est sa propre phase, avec
  sa propre preuve prod (les URLs d'hôtel sont exactement ce que S-G12 garde).
- `i18n.js` : ce n'est pas un mapping en dur, c'est un fichier de traduction. Et UX2 y touche.

## Pièges

- 🪤 Le réflexe « une table en dur est une dette » est **faux dans ce repo**, et le prouver
  fait partie du livrable. `EQUIPMENT_IDS` est le correctif d'un bug de prod, pas sa cause.
- 🪤 Ne pas mesurer la présence de `countryCode` sur un seul marché : le champ peut être
  fiable sur FR et absent ailleurs. Échantillonner **plusieurs pays**, dont un non-euro.
- 🪤 MCP renvoie des 429 sur les appels chaînés — espacer les sondes.
- 🪤 Ne pas relire le code de MCP_B2C (interdit de session, CLAUDE.md) : mesurer ses réponses,
  pas son implémentation.
- 🪤 `dayuse_guardrails.sh` peut avoir des règles sur les constantes/hosts en dur : le lancer
  **avant** de commencer, pour ne pas confondre un signal du guardrail avec un constat d'audit.

## DoD

1. `reports/AUDIT-MAPPINGS-<date>.md` : chaque table inventoriée, classée, justifiée, avec sa
   référence `fichier:ligne`.
2. La mesure de `countryCode` chiffrée sur ≥ 4 pays dont un non-euro, avec le verdict sur
   `_ISO_BY_COUNTRY_NAME`.
3. La duplication `_MARKET` / `COUNTRY_META` chiffrée et proposée, **non implémentée**.
4. Les suppressions prouvées exécutées, chacune avec son test ; les autres listées comme
   « gardées, et pourquoi ».
5. `pytest -q` vert (baseline 1452 passed, 1 skipped), `ruff`, `mypy`, guardrails verts.
6. `HANDOFF.md` : bloc daté renvoyant au rapport.
7. **Nettoyage du chantier** (décision Fabien du 2026-08-27) : si UX6 est la dernière
   phase mergée, exécuter la checklist « Nettoyage en fin de chantier » de
   `PROMPTS-UX-2026-08-27.md` — supprimer les 8 fichiers de planification APRÈS avoir
   vérifié que chaque constat durable a été recopié dans `HANDOFF.md` ou `reports/`.
   Ne jamais toucher `tasks/todo.md` (tracker OBS4).
