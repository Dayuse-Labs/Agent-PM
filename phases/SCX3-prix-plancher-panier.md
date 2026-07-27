# S-CX3 — Prix plancher & optimisation du panier : topo de cadrage

Brief autoporteur pour la (les) session(s) d'implémentation. Condense l'audit CX
(`reports/AUDIT-CX-2026-07-24.md`, reco R4) et l'état de l'art
(`reports/RESEARCH-SCX3-PRIX-PLANCHER-2026-07-24.md` — toutes les sources y sont).
Rédigé le 2026-07-24, après merge attendu de la stack #33→#36.

## 1. Objectif produit (cadrage Fabien)

Optimiser le **panier** (valeur de réservation) sans dégrader conversion ni confiance :
- **Mise en avant** = pondération entre le scoring des hôtels (qualité) et la proximité
  de leur prix au **budget déclaré** du client (décision Fabien, session audit).
- **Fallback hors budget** : quand un budget explicite donne 0 résultat, proposer les
  offres les plus proches au-dessus, avec disclosure honnête — jamais un dead-end.

Insight central : le moins cher MINIMISE le panier. Le budget déclaré est un signal de
willingness-to-pay ; l'objectif est de servir des offres de qualité proches du plafond
budgétaire du client, pas les moins chères.

## 2. Conclusions de la recherche (les 5 qui commandent le design)

1. **Quality floor d'abord** (Jannach & Adomavicius, RecSys 2017) : re-classer par le
   prix uniquement PARMI les bons hôtels capture ~50 % du gain de revenu à coût de
   pertinence quasi nul. Le profit a un **optimum intérieur** : pousser trop fort
   effondre la conversion. On réordonne les bons, on ne promeut jamais un médiocre.
2. **Ne jamais forcer le prix dans le ranking** (Airbnb KDD 2020) : deux tentatives de
   pression prix manuelle → conversion en baisse (−1,5 %, −0,67 %) → deux reverts.
   Le terme prix reste un modificateur borné, la qualité domine. Taux d'échange
   observé : ~0,2-0,3 % de bookings par 1 % de déplacement du prix moyen.
3. **Le budget déclaré = prix de référence explicite, contrainte SOUPLE** : dépasser
   pèse ~1,3-2× plus lourd que rester dessous (aversion à la perte) MAIS les budgets
   déclarés sont sous-calibrés, contiennent du slack (>75 % des acheteurs), un montant
   rond signale de la flexibilité, et une limite salillante incline vers la qualité.
   Le bon traitement (littérature contraintes + précédent produit Airbnb Flexible
   Matching) : **relaxation minimale + contrainte violée nommée**, jamais silencieuse.
4. **Ordre prix DÉCROISSANT parmi les éligibles** : +~4 % de prix moyen choisi (unique
   test terrain, Suk JMR 2012 — plafond optimiste). Bonus structurel : le moins cher
   finit en position 5 = position de bord sur-choisie → l'option budget reste visible
   (anti-« ils cachent les moins chers »).
5. **L'offline ne prédit pas le business** (Booking.com KDD 2019, 150 modèles) :
   la calibration offline borne, seul un A/B online tranche conversion vs panier.

Chiffre à retenir sur la bande hors budget : **+10-15 % est une convention triangulée**
(±5 % académique, 15 % badge « Deal » Google, 17 % plafond McKinsey) — AUCUN chiffre
primaire n'existe, ce sont nos données qui la calibreront.

## 3. Piste recommandée (v1 déterministe, code-owned)

```
Q = rating_shrunk/5                    # shrinkage bayésien (n·rating + k·prior)/(n+k), k≈20
r = prix / budget
proximity(r) = max(0.35, exp(−((r−1)/0.5)²))   si r ≤ 1        # sous budget : doux, plancher 0.35
             = exp(−((r−1)/0.25)²)             si 1 < r ≤ 1.15 # au-dessus : raide (aversion perte ×2)
             = 0                                si r > 1.15
score = Q^1 × proximity(r)^0.5                  # γ=0.5 : la qualité domine
```

Deux garde-fous anti-piège (modes d'échec documentés) :
- **Floor qualité RELATIF** : seuls les hôtels avec `Q ≥ Q_max_shortlist − 0.1` sont
  re-classables par le prix ; les autres suivent, classés par Q. (Relatif, pas absolu :
  les distributions de rating varient par marché.)
- **Cap de déplacement** : max +2 positions vs le rang qualité — coupe le biais
  « toujours le plus cher juste sous le budget en tête ».

Affichage : éligibles triés **prix décroissant**, puis les autres par Q.
Sans budget déclaré : Q seul (jamais de budget inventé) — option : référence = prix
médian de la shortlist (soutenu par la théorie du prix de référence).

## 4. Pistes alternatives (évaluées, non retenues en v1)

| Piste | Formule | Pour | Contre |
|---|---|---|---|
| **Blend linéaire** | `0.6·Q + 0.3·proximity + 0.1·(1−dist_norm)` | La plus simple à calibrer/expliquer ; grille de 2 poids | Compensation additive : un médiocre pile au budget peut battre un excellent 15 % dessous → exige le floor de toute façon |
| **Expected value** | `P̂(book)=σ(a0+a1·Q+a2·prox+a3·dist) ; score=P̂×prix` | Le SEUL dont l'objectif EST le panier ; fit logistique offline une fois, constantes figées ensuite | Biais structurel « plus cher faisable en tête » (fix = contrainte, pas poids) ; calibration fragile par marché ; paraîtra pire sur NDCG par construction |
| **Tri prix croissant** | — | « Honnêteté » apparente | Revenue-suboptimal ET pas consumer-optimal : value-for-money bat prix-croissant ET rating-seul en CTR/conversion/revenu (Ghose et al. 2014) |

La v1 recommandée (§3) = kernel multiplicatif + les 2 garde-fous ; le blend linéaire
est le fallback si la calibration du kernel s'avère instable ; l'expected value est la
v2 naturelle quand on aura des données de booking par carte.

## 5. Fallback hors budget (budget explicite → 0 résultat)

1. Re-probe feuille SANS `priceRangeMax` — précédent mécanique exact : le fallback
   timeslot A4-c (`response_bridge.py:633-642`, « closest matches instead »).
2. **1 à 3 offres** au-dessus du budget, bande ≤ +15 %, triées par **écart croissant**
   (plus l'écart est petit, plus ça convertit — Mirai).
3. Écart affiché sur le **prix tout compris** + **ce que l'écart achète** (« 12 € au-
   dessus de votre budget — piscine, à 300 m ») : la justification donne l'excuse de
   reclassification mentale, la spécificité est le driver documenté de l'upsell.
4. **Additif, jamais substitutif** : s'il existe des offres dans le budget, elles
   restent devant ; le hors-budget est une option marquée EN PLUS.
5. Valeurs (écart, prix, tri) possédées par le CODE (`over_budget_gap_eur` calculé),
   le LLM ne fait que formuler — même mécanique d'event que S-CX2.

## 6. Lignes rouges (UE + confiance — non négociables)

- Jamais d'ancre hors budget en tête quand un budget est déclaré (catégorie d'ancre qui
  échoue en réplication + steering le plus détectable).
- Jamais masquer/reléguer trompeusement une option moins chère (dark pattern nommé,
  UCPD/DSA). Prix tout compris partout. Pas de fausse rareté (UCPD Annexe I, CMA 2019).
- Pas de prix de référence inventés (règle 30 jours Omnibus) — l'écart se réfère au
  budget DU CLIENT uniquement. Pas de carte-leurre ; 5 cartes max en chat.
- Folklore interdit en business case : « anchor cher +6,8 % » (citation inexistante),
  « Cornell +27 % » (intraçable).

## 7. Mesure — le point qui conditionne tout

**⚠️ La vérité terrain d'`eval_ranking.py` est la DISTANCE** (protocole S-G9 : pool
re-fetché trié par haversine). Le blend fera BAISSER precision@5/NDCG@5 par
construction — changement d'objectif, pas régression. Plan en 3 étages :
1. **Offline** : étendre `scripts/eval_ranking.py` — NDCG@5-distance devient métrique
   de GARDE (borne, ex. −10 % max), la **valeur panier simulée du top-3** (Σ priceEuro
   pondérée par position, sur le même pool) devient la métrique de SÉLECTION.
   Grid-search (γ, σ_over, σ_under, τ, δ) sur les replays 81 cas existants.
2. Le re-rank déterministe a une latence nulle (Booking : +30 % latence ≈ −0,5 %
   conversion — ici zéro coût).
3. **Online** : A/B canary, **conversion ET panier moyen co-primaires**, ordre des
   cartes randomisable (décroissant / croissant / score seul). Métriques de confiance
   en garde : taux de retour, clics sur l'option budget en position 5.

## 8. Découpage sessions (chaque étape mergeable indépendamment)

| Étape | Contenu | Ancres code | Prérequis |
|---|---|---|---|
| **S-CX3a** | `price_eur_cents` numérique préservé sur la carte ; vérifier si un compteur d'avis existe dans le payload MCP (sinon v1 sans shrinkage, documenté) | `response_bridge.py::normalize_hotel` (:458-462, seule `price="€X.XX"` survit aujourd'hui) + miroir `inline_tools.py::_normalize_hotel_for_display` | aucun |
| **S-CX3b** | Re-ranker code-owned dans la FEUILLE (leçon s10 : les concerns de recherche vivent dans la feuille) : Q + kernel + floor + cap + tri décroissant ; flag env on/off (canary) ; tests unitaires sur les modes d'échec §3/§4 | nouveau module feuille + branchement `response_bridge.py` (post-`normalize_search_results`) ; budget dans `profile_in.budget_max` + `budget_request_source` (profile.py:77-78, 128-129) | S-CX3a |
| **S-CX3c** | Fallback hors budget : re-probe sans cap sur (budget explicite ∧ 0 résultat), DataPart offres marquées `over_budget_gap_eur`, template déterministe + règle de synthèse « additif jamais substitutif » | précédent : fallback timeslot `response_bridge.py:633-642` ; templates dans `templates.py` ; interaction à vérifier avec `maybe_auto_widen` (profile.py:262-290 — ne touche JAMAIS un budget explicite, le fallback devient le chemin explicite) et `search_exhausted` | S-CX3a (∥ 3b) |
| **S-CX3d** | Extension `eval_ranking.py` (garde distance + panier simulé), grid-search offline, protocole A/B canary | `scripts/eval_ranking.py`, `reports/RANKING-EVAL-PROTOCOL-2026-07-23.md` | S-CX3b |

Contraintes spine à respecter (héritées, non négociables) : ≤3 appels LLM/tour, guards
one-shot, le LLM ne possède jamais une valeur de filtre/prix, budget explicite jamais
écrasé silencieusement, évals `budget_change` exigent `requires_clarification == false`.

## 9. Décisions ouvertes pour Fabien

1. **GO sur la formule v1** (§3) et le découpage (§8) — ou ajustements.
2. **Bande de tolérance hors budget** : démarrer à +15 % (à calibrer sur nos données) ?
3. **Nombre d'offres hors budget** : 1 seule (prudent, evidence behavioral) vs 3
   (couverture) — la recherche penche pour 1-3 triées par écart croissant.
4. **Cadrage de l'écart** : « 12 € de plus » vs « ~10 % de plus » (extrapolation Rule
   of 100, non testée) — à trancher ou à A/B tester.
5. **Ordre décroissant** : par défaut dès la v1, ou seulement comme bras d'A/B ?

## 10. Pointeurs

- Recherche complète sourcée : `reports/RESEARCH-SCX3-PRIX-PLANCHER-2026-07-24.md`
- Audit CX (gaps G-b1/b2/b3, reco R4) : `reports/AUDIT-CX-2026-07-24.md`
- Protocole éval ranking : `reports/RANKING-EVAL-PROTOCOL-2026-07-23.md`
- HANDOFF : addenda 2026-07-24 (audit, S-CX1, S-CX2, S-CX3 recherche)
- Stack PRs : #33 (audit) ← #34 (S-CX1) ← #35 (S-CX2) ← #36 (recherche S-CX3)
