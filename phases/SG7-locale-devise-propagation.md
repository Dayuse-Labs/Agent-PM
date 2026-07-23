# S-G7 — Propagation locale/devise/domaine (A6-a : contexte maintenant, pricing plus tard)

| | |
|---|---|
| **Mode** | Piloté |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `sg7-locale-currency` — séquentiel après S-G6 (mêmes fichiers feuille) |
| **Zone autorisée** | `agents/hotel_search_agent/**` (param `language` Mapbox, cartes) + `agents/b2c_concierge/**` (response_language, active_filters currency) + tests |
| **Prérequis** | **S-G2 mergée** (locale/domain/currency au profil) · **S-G3 mergée** (le client Mapbox expose `language`) · Arbitrage **A6-a** |
| **Durée cible** | ½ journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` (§5 axe C) · `reports/research/code-verification-memo.md` (claims 2, 7).

## Périmètre
**IN** :
1. **Locale → géo** : la feuille passe la locale du `profile_in` au param `language` de Mapbox (hook S-G3) — c'est le prior qui attaque Lisboa→Arkansas ; boost locale/domaine actif dans le ranker (constantes déjà prévues en S-G3, valeurs branchées ici).
2. **Locale → sortie** : `response_language` préfère la locale de la requête (fait en S-G2 côté facade — vérifier le bout-en-bout, compléter si la synthèse feuille l'ignore).
3. **Devise (display SEULEMENT, pricing hors scope)** : `currency` stockée (S-G1/S-G2) exposée dans `active_filters` ; l'affichage prix reste EUR (provenance `priceEuro`) tant que le probe pricing MCP n'a pas parlé — MAIS le formatteur cesse d'être trompeur : si `profile.currency` est connue et ≠ EUR, la synthèse divulgue (« prix en EUR ») via le mécanisme de note existant (pattern `PROVENANCE:`/`AUTO_WIDEN:` S06/S12). Jamais de conversion inventée.
4. **Probe pricing MCP** (constat seulement) : `search_offers`/`get_hotel_details` renvoient-ils autre chose que `priceEuro` (devise locale, code devise) ? → constat dans `reports/MCP-B2C-REQUESTS.md` ; le pricing multi-devises réel reste une phase ultérieure gated sur ce constat.
5. **Cartes** : `country_code` (déjà pref-codé) — vérifier que le stamping géocode S-G3 alimente bien les cartes ; compléter sinon.

**OUT** : conversion/affichage multi-devises réel (gated sur le probe) · i18n des templates au-delà de fr/en (décision produit séparée) · domaine → routage de marché (rien d'arbitré là-dessus).

## Étapes
1. Locale → Mapbox `language` + boost ranker + tests (cas Lisboa-pt de l'audit = test nommé).
2. Bout-en-bout response_language + test.
3. Disclosure devise + tests (currency connue ≠ EUR → note ; EUR/inconnue → rien).
4. Probe pricing → `reports/MCP-B2C-REQUESTS.md`.
5. Vérif live : « hôteis em Lisboa » (message pt, locale pt) → Lisbonne Portugal, réponse en pt.

## DoD (exécutable)
```bash
pytest -q
.venv/bin/ruff check . && .venv/bin/mypy agents libs && bash scripts/dayuse_guardrails.sh .
```

## Fin de session
HANDOFF (constat pricing + preuve live Lisboa) · commit + MR.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§5 axe C),
reports/research/code-verification-memo.md (claims 2/7), puis phases/SG7-locale-devise-propagation.md
et exécute cette phase, dans ce périmètre exactement.
Règles : display EUR conservé, disclosure honnête, jamais de conversion inventée ; le pricing réel est
gated sur le probe MCP (constat, pas de code) ; preuve live Lisboa-pt obligatoire ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```
