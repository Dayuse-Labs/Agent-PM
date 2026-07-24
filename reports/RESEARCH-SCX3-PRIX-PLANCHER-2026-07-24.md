# S-CX3 — Prix plancher & optimisation du panier : état de l'art et recommandation (2026-07-24)

Recherche demandée par Fabien avant l'implémentation S-CX3 : « existe-t-il déjà des
méthodologies ? L'objectif est d'optimiser le panier du client. » Cadrage déjà acté
(session audit CX) : mise en avant = **pondération entre le scoring des hôtels et la
proximité de leur prix au budget du client**.

**Méthode** : 4 recherches parallèles (littérature académique ranking price-aware ;
pratiques industrie OTA/hospitalité + cadre réglementaire UE ; budget comme point de
référence comportemental ; effets d'ordre de présentation). Toutes les affirmations
ci-dessous sont sourcées (URL). Les chiffres non fiables sont explicitement flagués —
deux « chiffres » célèbres du menu-engineering se sont révélés être du folklore non
sourçable (citation Parsa & Njite 2014 introuvable dans Crossref, « Cornell +27 % »
intraçable) : ils ne doivent jamais entrer dans un business case Dayuse.

---

## 1. Réponse courte : oui, des méthodologies existent, et elles convergent

Quatre résultats structurants, indépendants et convergents :

1. **Le re-ranking par valeur ne paie que parmi les bons hôtels** (« quality floor »).
   Jannach & Adomavicius (RecSys 2017) : en ne laissant le prix/profit re-classer que
   les items au-dessus d'un seuil de qualité, on capture **~50 % du gain de revenu
   disponible à coût de pertinence quasi nul** (seuil 4.5/5), >80 % avec <10 % de perte
   de précision (seuil 4.0) — et le profit a un **optimum intérieur** : pousser trop
   fort fait s'effondrer la conversion et le total.
   [arXiv:1707.08029](https://arxiv.org/abs/1707.08029)
2. **Forcer le prix dans le ranking est le piège documenté n°1.** Airbnb (KDD 2020) a
   tenté deux fois d'injecter une pression prix manuelle dans son ranker : les deux
   tentatives ont dégradé les réservations (−1,5 % puis −0,67 %) et ont été **revertées**.
   Le terme prix doit rester un modificateur borné d'un score dominé par la qualité.
   [arXiv:2002.05515](https://arxiv.org/abs/2002.05515)
3. **Le budget déclaré est un prix de référence explicite, à traiter en contrainte
   SOUPLE avec relaxation minimale expliquée.** Littérature reference-price : dépasser
   le budget « coûte » perceptuellement ~1,3-2× l'équivalent sous le budget (aversion à
   la perte — fourchette honnête post-méta-analyses, pas le 2,25 folklorique)
   ([Kalyanaram & Winer 1995](https://pubsonline.informs.org/doi/pdf/10.1287/mksc.14.3.G161),
   [Brown et al. JEL 2024](https://www.aeaweb.org/articles?id=10.1257%2Fjel.20221698),
   [Walasek et al. 2024](https://www.sciencedirect.com/science/article/pii/S0167487024000485)) ;
   MAIS les budgets déclarés sont systématiquement sous-calibrés (
   [Ülkümen et al. 2008](https://academic.oup.com/jcr/article-abstract/35/2/245/1806120)),
   contiennent du slack délibéré (>75 % des acheteurs,
   [Stilley et al. 2010](https://academic.oup.com/jcr/article-abstract/37/2/264/1815154)),
   et une limite de prix salillante **ancre près de la limite et incline vers la
   qualité** — les acheteurs contraints dépensent jusqu'à ~50 % de plus
   ([Larson & Hamilton, JMR 2012](https://journals.sagepub.com/doi/10.1509/jmr.10.0508)).
   Un « max 120 € » rond signale en outre statistiquement de la flexibilité
   ([Backus et al., JPE 2019](https://www.journals.uchicago.edu/doi/abs/10.1086/701699)).
   La littérature des systèmes à contraintes formalise le bon comportement : **relaxation
   minimale + explication de la contrainte relâchée**, jamais de dead-end ni d'ignorance
   silencieuse ([Felfernig et al.](https://web-ainf.aau.at/pub/jannach/files/BookChapter_Constraint-BasedRS_2015.pdf)).
4. **Le précédent produit conforme existe : Airbnb « Flexible Matching »** (2021) —
   quand les filtres sur-contraignent, montrer les quasi-correspondances avec la
   contrainte violée NOMMÉE et barrée sur la carte
   ([Rental Scale-Up](https://www.rentalscaleup.com/airbnb-flexible-destinations-dates-matching/)).
   Et le dead-end actuel est un coût mesuré : ~la moitié des sites e-commerce
   dead-endent sur 0 résultat, l'abandon de recherche coûte >300 G$/an aux retailers US
   ([Baymard](https://baymard.com/blog/no-results-page),
   [Google Cloud/Harris](https://cloud.google.com/blog/topics/retail/search-abandonment-impacts-retail-sales-brand-loyalty)).

## 2. La formule recommandée (v1 déterministe, code-owned)

Composite des patterns les mieux étayés — c'est l'implémentation directe de la décision
de Fabien (blend scoring × proximité budget), durcie par la littérature.

### 2.1 Score qualité (Q) — dominant

```
rating_shrunk = (n·rating + k·prior) / (n + k)        # shrinkage bayésien, k≈20
Q = rating_shrunk / 5                                  # option : 0.8·rating + 0.2·stars
```
Le shrinkage empêche un 5.0-avec-3-avis de battre un 4.6-avec-900-avis. Nécessite le
nombre d'avis sur la carte (à vérifier dans le payload MCP ; sinon v1 sans shrinkage,
documenté).

### 2.2 Proximité budget — kernel asymétrique (r = prix/budget)

```
proximity(r) = max(0.35, exp(−((r−1)/σ_under)²))   si r ≤ 1        # sous le budget : doux, plancher 0.35
             = exp(−((r−1)/σ_over)²)               si 1 < r ≤ 1+τ  # au-dessus : raide (aversion à la perte)
             = 0                                    si r > 1+τ      # hors bande de tolérance
départ : σ_under = 0.5, σ_over = 0.25 (asymétrie ≈ λ), τ = 0.15
```
- L'asymétrie encode l'aversion à la perte (dépasser pénalise ~2× plus fort).
- Le plancher 0.35 sous budget évite d'écraser un excellent hôtel à 40 % du budget
  (mode d'échec documenté du kernel multiplicatif).
- **Pas de budget déclaré → pas de kernel** : Q seul (± distance), ou référence = prix
  médian de la shortlist (soutenu par la théorie du prix de référence). Jamais de
  budget inventé.

### 2.3 Score final + les 2 garde-fous anti-piège

```
score = Q^β × proximity(r)^γ          # départ : β = 1, γ = 0.5 (la qualité domine)
```
1. **Quality floor relatif** (pattern Jannach) : seuls les hôtels avec
   `Q ≥ Q_max_shortlist − δ` (départ δ = 0.1) peuvent être re-classés par le prix ;
   les autres suivent, classés par Q. Relatif et non absolu (les distributions de
   rating varient par marché — Paris ≠ NYC).
2. **Cap de déplacement** : un hôtel ne peut pas monter de plus de 2 positions par
   rapport à son rang qualité — coupe structurellement le biais « le plus cher juste
   sous le budget toujours en tête » (mode d'échec documenté du scoring expected-value).

### 2.4 Ordre d'affichage des éligibles : prix DÉCROISSANT

Meilleure preuve terrain disponible : ordre décroissant → prix moyen choisi **+~4 %**
(bar, 8 semaines, N≈1195, [Suk, Lee & Lichtenstein, JMR 2012](https://www.researchgate.net/publication/262087911_The_Influence_of_Price_Presentation_Order_on_Consumer_Choice) ;
répliqué conceptuellement [Mukherjee 2022](https://onlinelibrary.wiley.com/doi/10.1111/ijcs.12775)).
Mécanisme (prospect theory) : premier prix vu = référence ; en descendant, descendre la
liste = perte de qualité perçue. Conditions favorables réunies chez Dayuse : lien
prix-qualité cru fort (hôtels), utilisateurs non experts. Deux compléments :
- La position 1 gouverne l'ATTENTION, pas la persuasion ([Ursu, Marketing Science
  2018](https://pubsonline.informs.org/doi/10.1287/mksc.2017.1072) sur rankings Expedia
  randomisés : la position n'affecte pas l'achat conditionnel à l'examen) — l'effet
  panier vient du mécanisme de référence, les deux leviers s'additionnent.
- L'ordre décroissant place le moins cher en position 5 = position de BORD, elle-même
  sur-choisie ([Dayan & Bar-Hillel 2011](https://www.cambridge.org/core/journals/judgment-and-decision-making/article/nudge-to-nobesity-ii-menu-positions-influence-food-orders/8CBE6FB7505ECCD31C09157A74007EC9))
  — l'option budget reste visible et trouvable, ce qui neutralise le soupçon « ils
  cachent les moins chers ».
- Attention chat : +4 % est le PLAFOND optimiste (unique test terrain) ; et le ranking
  « value-for-money d'abord » bat à la fois le tri prix croissant et le tri rating seul
  en CTR/conversion/revenu ([Ghose, Ipeirotis & Li, Management Science 2014](https://pubsonline.informs.org/doi/10.1287/mnsc.2013.1828)) —
  notre score composite EST un tri value-for-money, l'ordre décroissant ne s'applique
  qu'à l'intérieur du set éligible au floor qualité.

### 2.5 Fallback hors budget (budget explicite → 0 résultat)

Pattern Airbnb Flexible Matching + relaxation minimale expliquée :
1. Re-probe feuille SANS `priceRangeMax` (précédent mécanique exact dans le code : le
   fallback timeslot A4-c de `response_bridge.py`).
2. Proposer **1 à 3 offres** les plus proches AU-DESSUS du budget, **bande τ ≤ +15 %**
   (triangulation : zone d'insensibilité ±5 % académique, seuil « Deal » Google 15 %,
   plafond catégorie McKinsey 17 % — AUCUN chiffre primaire n'existe pour « +X % », à
   calibrer sur nos données), triées par écart croissant (Mirai : plus l'écart est
   petit, plus ça convertit).
3. **Écart affiché explicitement sur le prix tout compris** (« 12 € au-dessus de votre
   budget ») + ce que l'écart ACHÈTE (« piscine, à 300 m ») — la justification donne
   l'excuse de reclassification mentale ([Cheema & Soman 2006](https://myscp.onlinelibrary.wiley.com/doi/abs/10.1207/s15327663jcp1601_6))
   et la spécificité est le driver documenté de l'upsell hôtelier.
4. **Additif, jamais substitutif** : s'il existe des offres dans le budget, elles
   restent en tête et le hors-budget est une option marquée en plus. La recherche sur
   la persuasion knowledge est nette : une reco perçue comme motivée par le profit
   détruit la confiance dans tout l'assistant.
5. Cadrage optionnel « ~10 % de plus » plutôt que « 12 € de plus » (extrapolation Rule
   of 100, flaguée comme telle — à A/B tester, pas à affirmer).

### 2.6 Ce qu'on ne fera PAS (lignes rouges, UE + trust)

- **Jamais d'ancre hors budget en tête de liste** quand un budget est déclaré : c'est
  la catégorie d'ancre (incidente/non pertinente) qui a ÉCHOUÉ en réplication à forte
  puissance ([Shanks et al. 2020](https://online.ucpress.edu/collabra/article/6/1/19/113066/Do-Incidental-Environmental-Anchors-Bias-Consumers),
  [Fudenberg et al. 2012](https://economics.mit.edu/sites/default/files/2022-09/On%20the%20Robustness%20of%20Anchoring%20Effects%20in%20WTP%20and%20WTA%20Experiments.pdf)),
  et la forme de steering la plus détectable ([Werner et al.](https://arxiv.org/abs/2409.12143)).
- Jamais masquer/reléguer trompeusement une option moins chère (dark pattern nommé,
  UCPD Commission Notice 2021 + DSA art. 25).
- Prix TOUT COMPRIS partout ; l'écart budget se calcule dessus (Omnibus/PID).
- Pas de fausse rareté/urgence (UCPD Annexe I ; engagements CMA 2019 de Booking/Expedia).
- Pas de « prix barrés » vs références inventées (règle des 30 jours, PID art. 6a) —
  nos écarts se réfèrent au BUDGET DU CLIENT, jamais à un prix de référence fabriqué.
- Pas de carte-leurre (decoy) ajoutée juste pour ancrer : 5 cartes est déjà la borne
  haute en chat (plus d'options → plus de clics mais MOINS d'achats,
  [Ghose et al. 2014](https://pubsonline.informs.org/doi/10.1287/mnsc.2013.1828)).
- Transparence de ranking : les paramètres principaux de la mise en avant doivent être
  explicables (Omnibus) — un score déterministe code-owned l'est par construction ;
  horizon Digital Fairness Act (consultation 2025) : concevoir à la lecture stricte.

## 3. Calibration et mesure — le point technique critique

**⚠️ La vérité terrain de l'éval ranking actuelle est la DISTANCE** (`scripts/
eval_ranking.py`, protocole S-G9 : ground truth = pool re-fetché trié par haversine
depuis l'anchor ; precision@5/NDCG@5 dessus). Un blend qualité × prix fera BAISSER ces
métriques par construction — ce n'est pas une régression, c'est un changement
d'objectif. Plan de mesure en 3 étages :

1. **Offline — étendre `eval_ranking.py`** : garder NDCG@5-distance comme MÉTRIQUE DE
   GARDE (borne de régression de pertinence géo acceptable, ex. −10 % max), ajouter
   comme métrique de SÉLECTION la **valeur panier simulée du top-3**
   (Σ priceEuro pondérée par position) calculée sur le même pool re-fetché. Grid-search
   des paramètres (γ, σ_over, σ_under, τ, δ) sur les replays existants (81 cas).
2. **Leçon Booking.com (KDD 2019, 150 modèles)** : les gains offline ne prédisent PAS
   la valeur business — l'offline borne, seul l'online tranche
   ([ACM](https://dl.acm.org/doi/10.1145/3292500.3330744)). Un re-rank déterministe a
   par ailleurs une latence nulle (Booking : +30 % latence ≈ −0,5 % conversion — ici
   zéro coût).
3. **Online — A/B canary** avec **conversion ET panier moyen co-primaires** (l'échange
   documenté chez Airbnb : ~0,2-0,3 % de réservations par 1 % de déplacement du prix
   moyen — l'optimum est intérieur, pas maximal). Ordre des cartes randomisable
   (décroissant vs croissant vs score seul) — tous les effets de terrain publiés
   viennent d'exactement ce type d'expérience. Métriques de confiance en garde :
   taux de retour, clic sur l'option budget en position 5.

## 4. Chiffres de référence (avec niveau de confiance)

| Chiffre | Valeur | Source | Confiance |
|---|---|---|---|
| Gain revenu capturable avec quality floor | ~50 % à coût nul ; >80 % pour <10 % précision | Jannach & Adomavicius (simulation) | Haute (peer-reviewed) mais simulation |
| Coût conversion d'une pression prix forcée | ~0,2-0,3 % bookings / 1 % prix moyen | Airbnb KDD 2020 (2 RCT, revertés) | Haute — terrain, grande échelle |
| Ordre décroissant → prix moyen choisi | +~4 % | Suk et al. JMR 2012 (terrain, N≈1195) | Moyenne-haute — unique test terrain, plafond |
| Aversion à la perte (budget dépassé) | λ ≈ 1,3-2,0 (pas 2,25) ; atténuée à petits enjeux | Méta-analyses JEL 2024 / JEP 2024 | Haute, fourchette honnête |
| Conversion upsell canal direct hôtel | 6 % des résas ; +14 % de valeur/transaction | Mirai (données transactionnelles) | Moyenne-haute — mono-vendeur |
| Bande de tolérance hors budget | +10-15 % (triangulé) — aucun chiffre primaire | ±5 % académique / 15 % Google / 17 % McKinsey | Basse — convention à calibrer sur nos données |
| Acheteurs incluant du slack budgétaire | >75 % | Stilley et al. JCR 2010 | Haute (peer-reviewed, contexte grocery) |
| Dead-end 0-résultat | ~50 % des sites ; abandon >300 G$/an US | Baymard / Google Cloud-Harris | Moyenne (études commerciales, gros N) |
| « Anchor cher d'abord = +6,8 % ticket » / « Cornell +27 % » | — | citations INTROUVABLES | **Folklore — ne jamais citer** |

## 5. Découpage proposé pour la session d'implémentation S-CX3

Prérequis mécaniques déjà spécifiés dans l'audit CX (R4a/R4b) + ce rapport :

1. **S-CX3a — la donnée** : `price_eur_cents` numérique préservé sur la carte
   (`normalize_hotel` + miroir `inline_tools`) ; vérifier si un compteur d'avis existe
   dans le payload MCP (sinon v1 sans shrinkage). Petit, sans risque.
2. **S-CX3b — le re-ranker** : module code-owned dans la feuille (les concerns de
   recherche vivent dans la feuille — leçon s10) : Q + kernel + floor + cap +
   ordre décroissant des éligibles ; flag env pour activer/désactiver (canary) ;
   `AUCUNE` valeur possédée par le LLM. Tests unitaires sur les modes d'échec
   documentés (§2.3).
3. **S-CX3c — le fallback hors budget** : re-probe sans cap sur budget explicite → 0,
   DataPart avec offres marquées `over_budget_gap_eur` (code-computed), template/note
   de synthèse déterministe (écart + ce que ça achète), règle de synthèse « additif
   jamais substitutif ». Même mécanique d'event que S-CX2.
4. **S-CX3d — la mesure** : extension `eval_ranking.py` (garde distance + valeur panier
   simulée), grid-search offline, protocole A/B canary (co-primaires conversion/panier,
   métriques de confiance en garde).

Chaque étape est indépendamment mergeable ; 3b et 3c peuvent être parallélisées après 3a.
