# UX3 phase 1 — `priceEuro` est-il en EUR, ou déjà dans la devise de l'hôtel ?

> Item 3 de la liste Fabien du 2026-08-27. Phase 1 seulement (mesure, zéro code de
> production) — voir `phases/UX3-devise-locale-mesure.md`.

## Verdict

**Lecture A confirmée : `priceEuro` est réellement en EUR (cents).** Ni AgentB2C ni MCP_B2C
n'exposent aujourd'hui le montant dans la devise que l'hôtel facture réellement — les sites
dayuse.com/.co.uk/.ch/th.dayuse.com font eux-mêmes une conversion de change côté leur propre
backend, en aval de ce que MCP_B2C nous renvoie.

**Conséquence, par l'arbitrage de Fabien du 2026-08-27** (« si une conversion est nécessaire, on
bloque sur MCP_B2C — pas de taux de change côté AgentB2C ») : cet item passe en **phase 2B**,
pas 2A. Aucun code de production touché dans cette session.

## Méthode

Pour 4 marchés non-euro (`_MARKET` — `libs/b2c_common/b2c_common/hotel_urls.py`), un hôtel a
été choisi par `search_offers` (lat/lon de la ville, date = demain, `2026-08-28`), puis
`get_hotel_details` sur son `hotelId`. Le `priceEuro` de la meilleure offre a été comparé au
prix **affiché en direct par le site de prod pour ce MÊME hôtel, ce MÊME jour, la MÊME
formule** (chargement de la page hôtel avec `?date=2026-08-28`, piloté en Chrome headless/CDP —
pas le `priceRange` générique du JSON-LD de la page, qui s'est avéré être un minimum
toutes-dates confondues et non comparable).

Script : `scripts/probe_currency_priceeuro.py` (pas un pytest — appels réseau réels à MCP_B2C,
même posture que `scripts/probe_geo_landmarks.py`).

⚠️ Espacé les appels MCP de 2 s (429 sur les appels chaînés, piège connu du repo). Sondé sur
demain, pas aujourd'hui (`cutoffDeadlineUtc` même-jour ~16h Paris).

## Résultats

| Marché | Hôtel | `priceEuro` (cents) | → EUR | Prix affiché sur le site (même hôtel, même jour) | Ratio site/EUR | Devise EUR/marché implicite |
|---|---|---:|---:|---|---:|---|
| TH (THB) | lyf Sukhumvit 8 Bangkok, id 18488 | 2461 | 24,61 € | **THB 935** (`th.dayuse.com`, chambre 8h-18h, -55 %) | 37,99 | ≈ le cours EUR/THB réel |
| US (USD) | Hyatt Place Fort Lee/GWB, id 13758 | 9989 | 99,89 € | **US$114** (`dayuse.com`, chambre 10h-15h, -34 %) | 1,141 | ≈ le cours EUR/USD réel |
| GB (GBP) | Novotel London Wembley, id 7477 | 10449 | 104,49 € | **£90** (`dayuse.co.uk`, 10h-18h, -33 %) | 0,861 | ≈ le cours EUR/GBP réel |
| CH (CHF) | Hotel Allegra Lodge, id 8074 | 10724 | 107,24 € | **105 CHF** (`dayuse.ch`, 10h-18h, -34 %) | 0,979 | ≈ le cours EUR/CHF réel |

Les 4 ratios site/EUR tombent chacun, indépendamment, dans la fourchette plausible du taux de
change réel de la devise correspondante — et avec un écart inférieur à 1 % à un arrondi
d'affichage près (ex. TH : 24,61 € × 37,99 = 935,2, contre 935 affiché). Ce n'est pas une
coïncidence isolée : c'est le signal d'une conversion de change appliquée de façon cohérente sur
les 4 marchés, en aval de `priceEuro`.

### Le cas THB, décisif à lui seul (comme prévu par le plan)

Les deux lectures sont plausibles a priori pour un day-use à Bangkok (24,61 € comme 2 461 THB
brut ≈ 61-65 € sont tous deux des prix crédibles) — l'ordre de grandeur seul ne suffisait donc
pas à trancher, contrairement à l'hypothèse du plan. Le chargement de la page hôtel EN DIRECT
pour le 28/08/2026 a tranché : **THB 935**, à 0,2 % de `24,61 € × 38`. Concordance trop précise
pour être un hasard.

## Ce qui n'est PAS confirmé

- Le taux de change exact utilisé par les sites (37,99 / 1,141 / 0,861 / 0,979) — probablement
  un service de conversion côté booking-tunnel, hors MCP_B2C et hors périmètre AgentB2C. Non
  investigué plus loin : ce n'est pas nécessaire pour trancher la lecture A/B.
- Si MCP_B2C a EN INTERNE la donnée dans la devise locale mais ne l'expose pas (le plus probable,
  vu que le site final l'a) — c'est précisément l'objet de la demande à écrire en phase 2B.

## Suite — phase 2B (attend le GO de Fabien)

1. Demande écrite à MCP_B2C (sur le modèle de `reports/PROMPT-MCP-B2C-RATEPLANS.md`) : exposer,
   par offre, le montant dans la devise que l'hôtel facture réellement, aux côtés de `priceEuro`.
2. Vérifier en prod si `agent.py::_synthesize_with_guards` divulgue honnêtement le mismatch
   EUR/devise-hôtel aujourd'hui (la docstring de `_format_price_eur_cents` l'annonce) — et sinon,
   corriger cette ligne de divulgation (pas une conversion).

Ne PAS : ajouter une source de taux, un cache FX, ou un « ~ » devant le prix côté AgentB2C —
décision de Fabien, un prix de réservation est un engagement.

## Preuve brute

`scripts/probe_currency_priceeuro.py --json`, sortie complète : 4/4 marchés répondus, aucune
erreur MCP, `detail_offer_count` 40 sur les 4 hôtels (pas de troncature). Comparaison manuelle
contre les pages `th.dayuse.com` / `dayuse.com` / `dayuse.co.uk` / `dayuse.ch` en Chrome headless
pour `2026-08-28`, texte de page capturé.
