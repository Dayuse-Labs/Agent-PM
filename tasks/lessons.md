# Lessons — corrections de Fabien à réappliquer

## 2026-07-27 — scx3a/scx3c (auto-correction, design 3c réfuté en live)

1. **Un test offline ne peut pas valider un changement d'ARGUMENT envoyé à MCP.**
   J'avais élargi `priceRangeMax` (budget × 1,15) et écrit un test « ne pousse jamais
   un hôtel in-budget hors de la page » — il PASSAIT, parce qu'il partitionnait une
   page FIXE. Le serveur renvoie une page *différente* quand le cap change (le pool
   de candidats change, pas seulement le découpage) : en live, 10 hôtels in-budget
   → 7, et aucune taille de page atteignable ne les récupère. Règle : tout changement
   d'un argument envoyé à un service externe se vérifie par un probe live comparant
   ANCIEN vs NOUVEAU sur le même marché, avant de croire le moindre test vert.
2. **Vérifier les commentaires « live-probed » avant de les traiter comme un contrat.**
   `inject_pagination_offset` documentait « size max 50 » (probe 2026-07-23) ; en
   2026-07-27, `size` ≥ 16 renvoie un structuredContent VIDE sans `isError`. J'ai
   construit un design sur ce commentaire. Les probes vieillissent — re-probe quand
   une décision en dépend, et corrige le commentaire dans le même commit.
3. **Un référentiel de repo sœur répond souvent à la question « ce champ existe-t-il ? »**
   sans probe : `MCP_B2C/src/application/dtos/hotel-summary.dto.ts` donnait `totalReview`
   (et `search-offers.use-case.ts` le `score` + sa pondération) en 2 lectures. Le probe
   live sert ensuite à savoir si le champ est POPULÉ — les deux étapes, dans cet ordre.

## 2026-07-24 — scx1-facade-shield (review PR #34)

1. **Langue des templates : une locale déclarée non supportée → ANGLAIS, jamais le guess.**
   Les clients Dayuse couvrent de nombreux pays/langues ; le spine ne traduit que fr/en.
   J'avais chaîné `locale supportée → sinon guess_language(message)` — or les hints
   français du guess se déclenchent sur d'autres langues romanes (es/it/pt), donc un
   client espagnol pouvait recevoir du FRANÇAIS. Règle : locale déclarée mais non
   traduite → "en" directement ; le guess sur le message ne sert QUE quand aucune
   locale n'est fournie. À réappliquer à tout nouveau point de sélection de langue
   de template (le `response_language` des textes LLM, lui, reflète le texte généré).
2. **Un push forcé refusé deux fois = changer d'approche, pas insister** : reconstruire
   l'historique compatible origin (merge de la base + cherry-pick) et pousser en
   fast-forward normal.

## 2026-07-20 — s10-amenity-filters (rejet du 1er plan)

1. **Référentiels : le code des repos sœurs prime sur le probing live.** J'ai reconstruit
   le référentiel équipements en probant `get_hotel_details` sur staging alors que
   `MCP_B2C/src/shared/reference/hotel-equipment.json` + `pool-equipment-ids.ts` sont
   la source officielle (et contenaient le OR-group piscine complet que mon probe avait
   raté). L'interdit CLAUDE.md « ne pas relire le code MCP_B2C » vise la logique, pas
   les fichiers de référence — demander/regarder d'abord si un référentiel existe en local.
2. **Extraction d'intention : Fabien préfère le LLM déjà en place à une regex déterministe,**
   tant que le code garde la propriété du filtre (validation liste fermée + mapping IDs
   côté code). Ne pas sur-appliquer « déterministe partout » aux étapes de compréhension
   du langage ; l'invariant spine porte sur les DÉCISIONS (routing, valeurs de filtre),
   pas sur l'extraction.
3. **Localisation : le traitement d'un concern de recherche vit dans la feuille search,**
   pas dans le concierge — même si le concierge semblait le chemin « minimal ». Le
   concierge re-apprend via `profile_delta` (chemin déjà testé), zéro code concierge.
4. **Piège gpt-4o-mini vérifié live** : une consigne de négation (« sans piscine ») peut
   être INVERSÉE par le modèle (il a émis les 8 autres clés → AND → 0 résultat). Toujours
   tester la formulation négative en live après un changement de prompt d'extraction.
