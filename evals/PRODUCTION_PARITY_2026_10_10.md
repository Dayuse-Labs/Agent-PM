# Comparatif production / B2C — 10 octobre 2026

**NO GO pour remplacer la production.** Cette livraison corrige des défauts concrets et fournit un comparatif frais; elle ne prouve pas encore une supériorité globale ni une parité suffisante pour basculer le trafic.

## Changements depuis v109

Le concierge conserve les préférences de lit, d’accès aux équipements et de groupe dans son profil Redis et les transmet aux feuilles A2A. Le filtrage utilise les formules MCP. Les demandes d’accès aux équipements déclenchent une réserve lorsque l’accès inclus ou privatif n’est pas confirmé. La prose spontanée sur un équipement non demandé reste parfois trop affirmative ; cette limite est conservée dans les notes. Une demande de groupe permet la découverte conditionnelle sans inventer sa composition.

Le géocodeur peut examiner un quartier nommé sans pays et présente les homonymes réels lorsqu’il doit clarifier. Une adresse courte n’est plus rejetée uniquement pour un score agrégé faible lorsque tous ses mots, le numéro, la rue et la ville parente correspondent aux composants du fournisseur. Les autres cas, les numéros interpolés et les identités multiples restent bloqués. Les noms de quartiers préfixés par leur ville sont reconnus uniquement avec le lien parental du fournisseur. Le parent explicite est conservé qu’il soit transmis au niveau de la transaction ou de chaque quartier; plusieurs alternatives gardent chacune leur ville. La synthèse ne reçoit plus l’ancienne demande de code postal lorsque la recherche courante a effectivement résolu le point, mais conserve les restrictions écrites par le client.

« Pas forcément moins cher, juste d’autres hôtels » conserve la pagination lorsque la recherche ne change réellement pas. Un changement de literie ou de taille de groupe relance au contraire la recherche au début, même si le client demande « d’autres hôtels ». Les réponses conditionnelles sur les équipements indiquent aussi le plus long créneau des offres affichées, à partir du format réel des cartes. La synthèse reçoit la confirmation de résolution du lieu uniquement lorsque le point fournisseur correspond à l’origine effective de la recherche et au contexte courant; cela réduit les clarifications inutiles sans garantir à lui seul la qualité de la reformulation.

Pas de nouvelle regex ni dictionnaire géographique. Architecture conservée : concierge propriétaire de l’état, feuilles sans état, LiteLLM, MCP en lecture seule. Le contrôle des composants d’adresse suit les définitions de [Mapbox](https://docs.mapbox.com/api/search/geocoding/).

## Évaluation

Runtime final `315377106070e11390a84c3236993ce0d5177026`, 85 sources vérifiées inchangées pendant les rejeux. Production legacy `3093647`, main B2C `cbe88b9`. Six configurations et déploiements Railway vérifiés identiques avant/après.

| Lot | Parcours candidat | Réponses candidat | Réponses legacy | Coût modèle USD |
|---|---:|---:|---:|---:|
| core-paired-v112 | 100 | 280 | 280 | 11.3969 |
| diagnostic-candidate-v113 | 7 | 19 | 0 | 0.3482 |
| diagnostic-candidate-v114 | 7 | 19 | 0 | 0.3506 |
| diagnostic-candidate-v115 | 8 | 22 | 0 | 0.4138 |
| diagnostic-candidate-v116 | 2 | 6 | 0 | 0.1154 |
| core-candidate-v116 | 100 | 280 | 0 | 5.7325 |
| adaptive-paired-v116 | 4 | 16 | 16 | 0.7244 |

Le premier lot rejoue les deux agents dans les mêmes fenêtres. Après les corrections, les 100 parcours candidat sont tous rejoués avec 4 conversations concurrentes (premier lot : 2 candidat + 2 legacy); leur référence legacy est celle du premier lot du même jour. Les parcours adaptatifs répondent aux clarifications effectivement posées, contrairement aux continuations historiques fixes. Ils évaluent un objectif commun, pas des entrées identiques.

Grille historique A parfait / B mineur / C significatif / D majeur / F critique. Revue complète par l’agent de codage, non aveugle et non indépendante. Les comptes ci-dessous décrivent cet échantillon exposé; ils ne sont pas un taux de victoire en production.

| Agent | A | B | C | D | F | Latence médiane / p95 | Médiane réponses avec cartes |
|---|---:|---:|---:|---:|---:|---:|---:|
| Production actuelle | 7 | 41 | 44 | 8 | 0 | 10.38 / 15.1 s | 13.0 s |
| Candidat final | 10 | 63 | 27 | 0 | 0 | 4.87 / 8.07 s | 5.78 s |

### Complément adaptatif : quatre objectifs, quatre tours par agent

Ces 32 réponses sont séparées du tableau des 100 parcours. Les suites répondent aux questions réelles de chaque agent et peuvent donc différer entre bras.

| Objectif | Candidat | Production | Observation candidat |
|---|---|---|---|
| brooklyn | B | C | La clarification est suivie d’une recherche avec les contraintes complètes, puis le plafond est porté à 150 USD avec consentement. Aucun forfait au total vérifiable n’est retourné ; le détail nommé distingue correctement l’identité de l’hôtel et l’absence d’offre datée. Cette absence n’établit pas à elle seule un défaut de rappel. La récupération pourrait proposer un compromis plus concret. |
| madrid | C | B | L’adresse courte réussit dans le cas historique simple mais échoue ici après une réponse complète comprenant Madrid et Espagne. La reformulation est enregistrée comme « Calle de la Palma y el número es 43 » et persiste malgré la correction explicite au tour suivant. Quatre tours sans résolution ; défaut de récupération du contexte et des composants d’adresse. |
| berlin | B | C | Berlin Mitte est résolu et le créneau Maritim 09–17 couvre bien 10–17. Le détail relève la taxe de séjour de 7,5 % et distingue finalement prix affiché et total non confirmé. Le premier tour répond en anglais malgré le message et le contexte allemands ; ensuite langue correcte. |
| paris-pool | B | C | Le budget de 150 EUR, deux adultes et le créneau 12–22 de demain sont conservés. H4 est proposé avec accès non confirmé ; les détails citent gratuité, réservation d’un créneau à la réception et un avis de fermeture ancien, sans garantir la réouverture. Au dernier tour, l’incertitude est maintenue, mais la réponse générique répète la durée au lieu d’expliquer directement l’absence de confirmation actuelle. |

## Défauts significatifs du candidat final

Ces cas restent des obstacles à la bascule. Les motifs ci-dessous proviennent du rejeu final complet, pas du seul lot ciblé.

| Parcours | Note | Observation |
|---|---|---|
| 0d079383afa07f70848756a8 | C | Le nom London Heathrow Terminal 3 contient déjà la ville, mais l’agent la redemande deux fois. Cela empêche de traiter le suivi demandant un créneau plus tard et plus court. |
| 115feab9f6871061cf090f93 | C | Les heures 15–18 et mercredi sont conservées. La précision Courbevoie laisse le repère mal orthographié bloquer deux tours ; la correction explicite finale « La Défense » finit cette fois par résoudre la zone et afficher des offres. Récupération réelle mais trop tardive. |
| 129597a4c6fbc73b1da6a887 | C | La piscine intérieure est réduite au filtre générique piscine. La réserve sur l’accès ne conserve pas le sous-type requis. Le suivi donne une zone de manière générale, sans confirmer le critère intérieur. |
| 242824991304d2617f2181d7 | C | La résolution partielle d’Edison est signalée. La date historique contradictoire « tonight July 7 » devient juillet 2027 mais le texte dit toujours ce soir. La demande de distance entre hôtel et gare reste bloquée malgré les noms et villes fournis ; aucun temps de trajet n’est inventé. |
| 38d6a346fc6f99fbb922552e | C | La clarification sur Newark perd le contexte NYC établi. Le suivi Manhattan propose ensuite des homonymes d’autres États au lieu de réutiliser ce contexte ; la recherche est bloquée. |
| 79c582c6f2d5f826704b2233 | C | Westminster est d’abord correctement présenté comme ambigu entre Royaume-Uni et États-Unis. Après « Westminster UK », l’agent redemande encore la ville et ne lance pas de recherche. Le nombre isolé 60 répondait à une autre question dans la branche historique : ne pas lui attribuer seul l’échec. |
| a4ded214b420767da49db48c | C | La Défense reste non résolue : demandes répétées de ville alors que le budget et l’arrivée à 18h sont conservés. |
| dd788becaecdeec0a39e6fe4 | C | Halton/Peel n’est pas résolu ; la clarification « même destination ou différente » est peu utile sans destination préalable. Le besoin piscine est conservé mais la recherche géographique reste bloquée. |
| fresh-v39-0c597d7ce05c9c5e | C | La découverte conditionnelle et le détail de la première offre fonctionnent. Après « près de moi », le contexte géographique disparaît ; la demande moins chère déclenche une clarification bloquante de composition du groupe malgré une offre de référence. Aucun accès spa n’est promis, mais le suivi n’aboutit pas. |
| fresh-v51-850df97d901415d7 | C | Le créneau 12–22 et la piscine persistent, mais « dispo demain » est enregistré comme période nécessitant une date précise. Deux demandes de clarification bloquent une date pourtant exploitable. La géolocalisation fournie n’est utilisée qu’au deuxième tour. |
| fresh-v69-ac3101cd6e | C | Le besoin près d’un aéroport n’est pas conservé dans l’état de recherche lorsque Rome arrive. Des cartes du centre-ville sont affichées avant la clarification FCO/CIA ; la prose reconnaît ce décalage mais la sélection ne répond pas au besoin. |
| fresh-v72-640d4c8302 | C | Le nom Five 6 Splendour mal orthographié n’est pas reconnu. Une clarification générique sur la même destination ou une autre est peu utile sans lieu confirmé préalable. |
| fresh-v72-b67bda12db | C | Après avoir proposé Rueil-Malmaison, la réponse 92 efface Rueil et redemande une ville complète. Le département donné pour préciser la destination n’est pas associé au lieu déjà fourni ; le suivi spa reste bloqué. |
| fresh-v73-360de9bb8c | C | Rome est désormais reconnu, mais le secteur est reste non résolu et la réponse demande une adresse ou un repère supplémentaire. L’agent répond en français à la demande italienne. Aucun résultat pour le secteur demandé. |
| fresh-v73-e28a165f47 | C | Les deux codes postaux explicites ne sont pas retenus comme origines structurées ; la première clarification générique même destination ou différente est inadéquate. Au suivi carte, les deux codes sont enfin mentionnés pour choisir une origine, mais aucune recherche n’a encore abouti. |
| fresh-v75-7ebba791b128 | C | Le contexte Maryland n’aide pas à résoudre Annapolis. Le détail de la première offre affirme l’accès piscine inclus alors qu’une réserve avait été donnée au tour précédent ; c’est un défaut de prose significatif malgré des cartes exactes. Les recherches suivantes qualifient bien l’accès privé non confirmé, mais grande baignoire s’ajoute à piscine et jacuzzi au lieu de clarifier un remplacement. |
| global55-dublin-centre | C | Dublin City Centre n’est pas résolu malgré la ville, demain, le budget et la piscine. L’agent propose un repère plus précis sans résultats sur trois tours ; la première affirmation de recherche d’hôtels n’est pas étayée. |
| global55-hotel-typo | C | Une faute d’une lettre dans le nom d’hôtel bloque la résolution. L’agent redemande nom complet et ville déjà fournie, sans proposer de candidat plausible à confirmer. |
| holdout-0b29daa0abbc6cd7 | C | Le créneau 17–23 persiste, mais l’affinage Tuen Mun/Tung Chung perd Hong Kong et bloque les demandes suivantes. L’inventaire vide à l’heure du rejeu n’est pas noté comme régression. Le tour FAQ paiement est hors évaluation. |
| holdout-39a54953510f835c | C | Le contexte New Jersey se perd au suivi GW Bridge, puis Bergen County permet enfin une recherche mais sans conserver la proximité du pont. La sélection locale demandée reste non résolue. |
| holdout-650a7ee342f64a4c | C | La préférence La Quinta n’est pas suffisamment appliquée. Le suivi Halm Blvd perd San Antonio déjà confirmé et redemande l’adresse. La langue bascule aussi en espagnol. |
| holdout-7619238f09035b85 | C | La date et l’arrivée à 13h persistent après Dubai, mais Al Mankool n’est pas vérifié et bloque la recherche. La prose prétend avoir recherché des hôtels malgré l’échec de résolution de zone. |
| holdout-81bf0277ba4c7c05 | C | Aucun hôtel arbitraire inventé, mais « aucune » est interprété comme une période de dates et provoque une demande de date exacte. Clarification sans rapport avec la préférence ou l’absence de destination ; erreur de triage restante. |
| holdout-92d1d0dcb10d8d41 | C | Un adulte, deux enfants et le budget de 80 dollars sont conservés. Après sa propre demande de lieu, l’agent ne sait pas traiter les deux lieux nommés et pose une question générique « même destination ou différente », sans recherche. |
| holdout-d4a34235ab399d8d | C | La faute Lower Manhatten bloque la résolution. Le nombre 200 est ensuite interprété comme un lieu plutôt qu’une intention à préciser, sans recherche. Cette réponse numérique suivait une question de budget différente dans la branche legacy. |
| holdout-e55c851daadf30d1 | C | Le numéro et la rue sont conservés, mais l’agent demande de revérifier numéro, nom ou code postal au lieu de demander clairement la ville manquante. La recherche à distance de marche n’aboutit pas. |
| holdout-f92d2367af1c65f8 | C | 18:30–21 est conservé, mais 23rd Street disparaît derrière Manhattan. Après la précision NYC, l’agent affiche des hôtels du Financial District et redemande si la proximité de 23rd est souhaitée. Le repère fin est perdu malgré des créneaux corrects. |

Comparaison descriptive des notes : {'candidate_better': 43, 'legacy_better': 14, 'equal_grade': 43}. Une réponse de clarification rapide peut être moins utile : latence et qualité restent séparées. La concurrence candidate passe de 2 à 4 entre les lots; les latences sont descriptives, pas une mesure causale du seul correctif. Les différences d’inventaire seules ne justifient pas une mauvaise note.

Configuration candidate : triage GPT-5.2 low/2048, recherche 4o-mini, synthèse GPT-5.2. Le B2C déployé utilise 4o-mini au triage : la PR ne modifie pas Railway et le candidat testé n’est pas ce déploiement. Aucun gain ne peut être attribué au code seul ou à un changement de modèle seul.

## Données et limites

Les compteurs d’intégrité des cartes, prix, dates, créneaux, capacités, distances et budgets avec frais figurent dans le JSON adjacent. Sur le corpus final : 298 cartes jointes aux reçus MCP exacts, aucune erreur détectée de prix ou de faits dans les cartes, 246 distances recalculées sans écart et 28 budgets avec frais vérifiés. Les 9 écarts littéraux de créneau sont tous explicitement annoncés comme des alternatives. Ces contrôles ne prouvent ni le rappel exhaustif ni la qualité de chaque phrase.

Dans le complément adaptatif, 12 cartes datées sont reliées aux reçus ; une carte présente uniquement l’identité de La Quinta, explicitement sans offre disponible ni prix confirmé. Elle explique l’unique total non vérifié dans cet audit, sans fausse promesse de prix. Quatre cartes de détail n’exposent pas de capacité dans leur payload, ce qui limite le contrôle structurel de ces cartes.

Le corpus s’appuie sur les conversations historiques et les régressions déjà identifiées, sans couvrir exhaustivement six mois de trafic. Export/Qdrant en legacy, MCP préproduction présenté par l’équipe comme reflet de la production. Dates historiques littérales rejouées au calendrier actuel, contexte natif manquant non inventé. Certains messages suivants répondent seulement à la question legacy : les conclusions concernées sont nuancées et complétées par les parcours adaptatifs. FAQ/SAV restent en phase 2.

## Conditions restant à remplir avant une bascule

1. Résoudre les clarifications excessives et la perte de contexte parent : La Défense, Dublin City Centre, London Heathrow Terminal 3, NYC puis Newark/Manhattan, Rueil puis 92. Préserver l’origine fine lors d’un affinage de ville.
2. Réconcilier les sorties du triage avec l’état déjà connu : « dispo demain » ne doit pas devenir une période indéfinie, et une réponse à une clarification doit compléter la contrainte concernée.
3. Appliquer la preuve d’accès aussi aux réponses de détail, et conserver les sous-types demandés comme piscine intérieure. Le parcours familial montre encore une promesse d’accès piscine incluse dans un détail après une réserve au tour précédent.
4. Faire valider par l’équipe un échantillon indépendant avec la configuration et la source de données prévues pour le déploiement. Les notes ci-dessus ne remplacent pas cette validation. FAQ et annulations nécessitent leur phase dédiée avant une bascule qui inclurait ces usages.

Ces portes de sortie sont proposées pour décider du lancement, pas présentées comme déjà franchies. Entre le premier candidat v112 et le candidat final, les notes s’améliorent sur 9 parcours, baissent sur 7 et restent égales sur 84. Ce résultat inclut variabilité du modèle, inventaire et horaire ; il ne mesure pas l’effet causal du seul code. Les 280 entrées du candidat final sont identiques à celles du premier candidat hors identifiants de session/tour. Dans le premier comparatif, 267 paires de corps de requête étaient identiques et 13 adaptaient uniquement le transport des mêmes coordonnées GPS au contrat natif de chaque agent.

## Livraison et coût

Tests locaux : **3305 passent**, un test Langfuse live payant optionnel ignoré. Ruff, mypy sur 85 fichiers, guardrails et vérification du diff passent. CI GitHub à vérifier sur le head livré ; le head précédent ne lançait pas les jobs à cause de la facturation/plafond GitHub.

Un second lot v115 a été arrêté après 79 parcours complets et 1 partiel (225 réponses), pour corriger la perte du parent de quartier observée dans les sorties modèle. Coût **4.5767 USD** conservé; ces résultats ne valident pas le runtime final.

Lot intermédiaire v114 arrêté après **16 parcours / 45 réponses**, coût **0.8953 USD** inclus ci-dessous, pour corriger la pagination des critères de chambre/groupe. Ce lot interrompu ne vaut pas validation du runtime final; les 100 parcours sont ensuite rejoués entièrement.

Le complément adaptatif a d’abord été interrompu par un défaut de sérialisation des cookies dans le harnais : 8 réponses reçues, dont 4 non sauvegardées. Coût **0.1552 USD** rapproché des traces et conservé. Le harnais a été corrigé pour préserver domaine et chemin des cookies, puis les parcours ont repris dans de nouvelles sessions. Ce lot interrompu n’est pas compté comme validation.

Les diagnostics préparatoires v110–v112 sont également inclus dans le cumul; aucune dépense intermédiaire n’est supprimée.

Ce travail : **25.9548 USD**. Cumul **224.8714 / 230 USD**, dont 7,10 USD de provisions antérieures conservées; disponible après réserve : **4.6286 USD**. Aucun coût en attente. Télémétrie modèle, pas facture fournisseur; infrastructure/MCP/Mapbox exclus. L’extension de 30 USD n’a été appliquée qu’une fois.

PR 134 en brouillon pour revue de l’équipe, sans merge ni déploiement. Le rapport HTML local contient les parcours complets, notes et motifs. Les conversations, GPS, reçus bruts et secrets restent hors Git.
