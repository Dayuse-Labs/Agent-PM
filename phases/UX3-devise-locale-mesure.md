# UX3 — Devise locale de l'hôtel : mesurer d'abord, demander à MCP ensuite

> Issu de la liste Fabien du 2026-08-27, item 3.
> **Arbitrage Fabien du 2026-08-27 : si une conversion est nécessaire, on bloque sur MCP_B2C.**
> Pas de taux de change côté AgentB2C : un prix de réservation est un engagement, pas une
> estimation.

## Symptôme rapporté

> « Utiliser la devise locale de l'hôtel pour tous les prix. »

## Pourquoi cette phase commence par une mesure et non par du code

`agents/b2c_concierge/b2c_concierge/inline_tools.py:235-245` — la docstring de
`_format_price_eur_cents` :

> « `priceEuro` is EUR cents. […] MCP performs no conversion server-side (verified: a hotel's
> `priceEuro` is **identical** whether its own `currencyCode` is EUR or USD/GBP). Display
> therefore stays EUR here — the simple, honest default »

**Cette phrase admet deux lectures, et personne n'a écrit laquelle est vraie.**

- **Lecture A** — le champ est réellement en EUR. Afficher la devise locale exige alors une
  **conversion**, que ni AgentB2C ni MCP ne savent faire.
- **Lecture B** — le champ est **mal nommé** : il porte le montant dans la devise locale de
  l'hôtel, et « identique quelle que soit la devise » veut simplement dire *« le serveur ne
  reformate rien »*. Dans ce cas il n'y a **aucune conversion à faire** : le nombre est déjà
  bon, seul le symbole `€` codé en dur est faux. La correction devient un pur changement
  d'affichage, de l'ordre d'une demi-journée.

L'écart de charge entre les deux est d'un facteur dix, et la lecture B est plausible : le site
de prod affiche bien des prix en `$` sur les hôtels américains. **Écrire du code avant de
trancher serait deviner.**

Indice à charge de la lecture A, à ne pas ignorer : le champ s'appelle littéralement
`priceEuro`, et `web/vendor/static/js/chat/hotels/card.js:56` maintient une table
`CURRENCY_SYMBOLS` + `marketCurrencySymbol()` qui prend la devise du **marché du widget**, pas
de l'hôtel — ce qui suggère que le backend n'a jamais envoyé de devise exploitable.

## Phase 1 — la mesure (obligatoire, aucun code de production)

Objectif : répondre par un chiffre à « `priceEuro` est-il en EUR, ou dans la devise de
l'hôtel ? »

Protocole :

1. Choisir des hôtels dont la `currencyCode` **n'est pas** EUR — les marchés non-euro de
   `_MARKET` (`libs/b2c_common/b2c_common/hotel_urls.py:29-53`) : US, GB, CH, BR, SG, HK, AE,
   AU, CA, NZ, TH, MY. Les plus lisibles : US (USD), GB (GBP), CH (CHF), TH (THB — l'ordre de
   grandeur y est décisif : ~1 200 THB pour ~30 €, aucune ambiguïté possible).
2. Pour chacun, `search_offers` puis `get_hotel_details`, et relever `priceEuro` **et**
   `currencyCode`.
3. Comparer au prix affiché **par le site de prod** pour le même hôtel, le même jour, la même
   formule. C'est l'arbitre : le site sait, lui, quelle devise il affiche.
4. THB est le test qui tranche seul : si `priceEuro ≈ 1200`, le champ est en devise locale
   (lecture B). Si `priceEuro ≈ 3000` (30 € en cents), il est en EUR (lecture A).

⚠️ Rappel du repo : MCP renvoie des **429 sur les appels chaînés**. Espacer les appels.
⚠️ Rappel du repo : toute offre a un `cutoffDeadlineUtc` **le jour même** (au plus tard 16h
Paris) — après ~16h, `date=today` rend 0 résultat sur tout le pool. Sonder sur `demain`.

**Livrable de la phase 1** : un tableau dans `reports/` — hôtel, pays, `currencyCode`,
`priceEuro`, prix du site de prod, verdict. Plus la réponse écrite : lecture A ou lecture B.
Puis **STOP et rapport à Fabien**. La suite dépend du verdict.

## Phase 2A — si lecture B (le champ est déjà local)

Travail d'affichage, entièrement dans notre périmètre :

- `inline_tools.py:_format_price_eur_cents` → formater avec le symbole de
  `hotel["currencyCode"]` au lieu du `€` codé en dur. `_iso_currency` existe déjà
  (`inline_tools.py:267`) et `currency_code` est **déjà** propagé sur la carte
  (`inline_tools.py:311-313`).
- Miroir côté feuille : `hotel_search_agent/response_bridge.py` a son propre
  `_price_eur_cents` / `_iso_currency` (duplication assumée, décision B3 — « each side owns
  its own tiny formatting helper »). **Les deux côtés doivent changer**, sinon la carte de
  recherche et la carte de détail affichent deux devises différentes pour le même hôtel.
- Widget : `card.js:parsePrice` sait déjà lire `"CAD 120.00"` et `detectCurrencySymbol`
  couvre `€ £ ¥ ₩ ฿ ₺` + les codes ISO (`card.js:56-95`). Vérifier que le backend émet une
  forme que ce parseur accepte **déjà** — si oui, zéro changement widget.
- Renommer la fonction backend (`_format_price_eur_cents` → `_format_price_cents`) : garder
  « eur » dans le nom d'une fonction qui formate du THB est la prochaine ambiguïté à 6 mois.

## Phase 2B — si lecture A (le champ est en EUR)

Aucun code de production dans AgentB2C. Deux livrables :

1. **Une demande écrite à MCP_B2C**, sur le modèle de `reports/PROMPT-MCP-B2C-RATEPLANS.md`
   (qui a déjà obtenu `originalPriceEuro`, `ratePlanName`, `includedAmenities`, `bedding`,
   `capacity` — le canal fonctionne) : exposer, par offre, le montant **dans la devise que
   l'hôtel facture réellement**, aux côtés de `priceEuro`. C'est MCP qui a la donnée à la
   source ; toute conversion en aval serait un prix inventé.
2. **Rendre l'existant honnête en attendant.** `agent.py::_synthesize_with_guards` divulgue
   déjà le mismatch selon la docstring de `_format_price_eur_cents` — le **vérifier
   réellement en prod** sur un hôtel non-euro, et si la divulgation ne sort pas, c'est ça le
   correctif de la phase (une ligne honnête, pas une conversion).

Ne PAS, dans les deux cas : ajouter une source de taux, un cache FX, ou un « ~ » devant le
prix. Décision de Fabien : on ne fait pas atterrir un prix approximatif sur un parcours de
réservation.

## Pièges

- 🪤 `profile.currency` **existe** (`profile.py:202`) et est alimenté par la façade
  (`facade.py:668-670`) : c'est la devise du **client / marché**, pas celle de l'hôtel. Les
  deux ne doivent pas être confondues — la demande de Fabien porte explicitement sur *« la
  devise locale de l'hôtel »*.
- 🪤 `card.js:marketCurrencySymbol()` prend la devise du marché du widget en **fallback**. Si
  le backend passe en devise hôtel sans que le widget le sache, un prix en THB peut s'afficher
  avec un `€`. Vérifier le chemin de fallback, pas seulement le chemin nominal.
- 🪤 `ground_truth.py:212` compose un texte avec `€` en dur (« Wide price spread: X-Y € ») et
  alimente le bloc de ground-truth de la synthèse. Un prix en devise locale qui traverse ce
  chemin ressort avec le mauvais symbole **dans le prompt du LLM** — donc dans la réponse.
  Ne pas l'oublier en 2A.
- 🪤 Les guards de vérité (`link_guard`, `amenity_guard`) ne couvrent pas les prix. Si 2A est
  retenue, se demander si un 16e guard « la devise affichée est celle que MCP a renvoyée » est
  justifié — un prix est une **affirmation**, exactement l'argument qui a fait naître
  `discount_pct` côté backend.

## DoD

**Phase 1 (toujours) :** tableau de mesure dans `reports/`, verdict écrit, rapport à Fabien,
`HANDOFF.md` mis à jour. Zéro ligne de code de production. **Aucune** des deux phases 2 ne
démarre sans le GO de Fabien sur le verdict.

**Phase 2A :** les deux côtés (concierge + feuille) formatent la devise de l'hôtel ; test par
devise (EUR, USD, GBP, CHF, THB) ; `ground_truth.py` corrigé ; preuve prod sur un hôtel
non-euro, capture de la carte ; suite verte (baseline 1452 passed, 1 skipped) + ruff + mypy +
guardrails.

**Phase 2B :** demande MCP_B2C écrite dans `reports/` ; divulgation du mismatch **vérifiée en
prod** (trace + texte rendu) ou corrigée ; suite verte ; `HANDOFF.md` disant explicitement que
l'item est **bloqué côté MCP_B2C**, avec ce qui a été demandé et à qui.
