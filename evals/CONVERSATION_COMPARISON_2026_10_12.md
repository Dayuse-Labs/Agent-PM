# Comparaison des 100 conversations Dayuse

Comparaison rétrospective des 100 conversations rejouées le 10 octobre, préparée le 12 octobre 2026. Les notes existantes sont conservées ; aucune nouvelle campagne payante ni nouvelle notation indépendante. Les derniers correctifs de la PR ne sont pas encore rejoués.

**Le candidat montre au moins un hôtel dans 48 conversations, contre 76 pour la prod.** Il y a 59 conversations avec moins d’hôtels distincts, 18 avec davantage et 23 avec autant. Un gain de note ne garantit donc pas que le parcours aboutit à une sélection.

| Mesure | Production | Candidat |
| --- | ---: | ---: |
| Conversations avec au moins une carte | 76/100 | 48/100 |
| Réponses avec cartes | 142/280 | 84/280 |
| Cartes affichées cumulées | 603 | 299 |
| Somme des hôtels distincts dans chaque conversation | 439 | 228 |

La dernière ligne déduplique les identifiants à l’intérieur de chaque conversation, pas entre conversations. Une carte peut représenter une identité sans disponibilité datée ; aucun de ces nombres n’est un nombre de réservations possibles.

## Où se produit le déficit de cartes

Sur 280 paires de réponses : 52 montrent des cartes des deux côtés, 90 seulement côté prod, 32 seulement côté candidat et 106 d’aucun côté. Les 90 contre 32 expliquent le déficit net de 58 réponses avec hôtels.

| Réponse observée du candidat quand seule la prod montre des cartes | Nombre de tours |
| --- | ---: |
| Lieu ou identité à préciser | 39 |
| Aucune offre vérifiable annoncée | 38 |
| Budget groupe ou référence à préciser | 12 |
| FAQ hors périmètre | 1 |

Ce classement décrit les réponses, pas les causes techniques prouvées. Les clarifications géographiques comprennent les questions nécessaires et celles qui bloquent à tort. Une recherche vide peut provenir des critères, du calendrier, d’une mauvaise interprétation ou du fournisseur ; elle n’est pas attribuée automatiquement à l’inventaire.

Dans **28 des 90 réponses où seule la prod affiche des hôtels**, au moins une de ses cartes signale elle-même un écart de contrainte. C’est un avertissement émis par l’ancien agent, pas une validation indépendante ; il ne prouve pas que toutes ses autres cartes sont bonnes ou mauvaises.

## Conclusions concrètes

- **Régressions utiles à traiter** : Heathrow Terminal 3 (C004), contexte NYC et Manhattan (C013), Dublin centre (C061), récupération du Biltmore (C063), deux origines (C053 et C083). La Défense (C022), Rueil et 92 (C048), Al Mankool (C080) restent aussi bloqués alors que la prod elle-même présente des défauts.
- **Moins de cartes parfois justifié** : minuit à Singapour (C033), soirée avec jacuzzi à Philadelphie (C040), baignoire à Hong Kong (C071), contraintes de formule ou budget (C073, C094, C100). Il faut encore distinguer refus correct et récupération trop pauvre.
- **Plus de cartes peut être un échec** : Rome après une demande d’aéroport (C041) affiche le centre-ville ; l’ancienne prod clarifie correctement. Le volume seul ne doit pas devenir l’objectif.
- **Comparaison gênée par les branches** : nombres nus ou références de liste après des questions différentes (C003, C015, C081, C088). Un rejeu adaptatif est nécessaire pour juger la suite.
- **Différences fournisseur non expliquées** : Melbourne (C007), Auckland (C042), entre autres. Les dates rejouées en 2027 (C008, C049, C054, C072, C094) limitent aussi l’interprétation du rappel.

## Lecture des 100 fiches

Pour chaque conversation : notes historiques prod → candidat, cartes par tour prod → candidat, hôtels distincts, diagnostic et vérification suivante. A parfait, B défaut mineur, C significatif, D majeur, F critique. Les notes portent sur le dialogue et ses contraintes ; elles ne sont pas un score de conversion ou de rappel d’inventaire.

Les 200 fichiers de trajectoire correspondent aux empreintes de leurs revues et les 280 messages utilisateur sont identiques entre les bras. Cette passe rapproche toutes les revues existantes, les cartes de tous les tours et les 90 réponses candidat sans cartes face à une réponse prod avec cartes. Elle ne prétend pas remplacer la revue par un nouveau juge indépendant. Les transcriptions complètes et identifiants de source restent dans le rapport local privé ; les fiches ci-dessous sont reformulées sans verbatim client.


## C001 Hôtel nommé à Hong Kong

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 2 → 1. Hôtels distincts dans le parcours : 1 → 1.

Cartes par tour : T1 1 → 1 ; T2 1 → 0.

L’identité est conservée des deux côtés. La prod réaffiche l’hôtel ; le candidat ne confirme aucune offre datée après la précision de ville. La disponibilité explique la réponse, mais sa cause fournisseur reste à vérifier.

**Vérification suivante :** Comparer les disponibilités datées du même hôtel.

## C002 Paddington puis meilleur avis

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 5 → 6. Hôtels distincts dans le parcours : 5 → 5.

Cartes par tour : T1 0 → 0 ; T2 5 → 5 ; T3 0 → 1.

Les deux agents proposent des hôtels près de Paddington. Le candidat répond au classement avec une carte de la liste réelle ; la prod répond sans nouvelle carte. La baisse globale de cartes ne concerne pas ce parcours.

**Vérification suivante :** Conserver la référence à la liste et vérifier les affirmations sur la salle de bain.

## C003 Piscine dans Queens puis nombre seul

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 2 → 3. Hôtels distincts dans le parcours : 1 → 3.

Cartes par tour : T1 0 → 0 ; T2 1 → 3 ; T3 1 → 0.

Le candidat montre davantage de cartes au tour de recherche, puis clarifie le nombre isolé. La question précédente diffère de celle de la prod ; le suivi numérique fixe n’est pas une comparaison équitable. La prod promet l’accès piscine sans preuve suffisante.

**Vérification suivante :** Rejouer avec une réponse de budget adaptée à la vraie question.

## C004 Heathrow Terminal 3 puis horaires

**Notes prod → candidat : B → C · Moins bien noté.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 7 → 0.

Cartes par tour : T1 5 → 0 ; T2 5 → 0.

La prod avance avec des hôtels autour de Heathrow ; le candidat redemande deux fois la ville déjà contenue dans le nom. Le suivi sur les horaires reste bloqué : perte utile de résultats côté candidat.

**Vérification suivante :** Rejouer la proposition de terminaux fournisseur du dernier correctif.

## C005 La Défense avec faute puis Courbevoie

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 10 → 5. Hôtels distincts dans le parcours : 8 → 5.

Cartes par tour : T1 0 → 0 ; T2 0 → 0 ; T3 5 → 0 ; T4 5 → 0 ; T5 0 → 5.

La prod produit des cartes mais mélange heure, plafond et prix nul. Le candidat garde mercredi et 15–18 mais reste bloqué sur la faute jusqu’à sa correction explicite, puis fournit cinq cartes.

**Vérification suivante :** Accélérer la récupération du repère sans perdre heure ni plafond.

## C006 Piscine intérieure à Milan

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 5 → 10. Hôtels distincts dans le parcours : 5 → 5.

Cartes par tour : T1 0 → 0 ; T2 5 → 5 ; T3 0 → 5.

Les deux agents affichent des hôtels, mais aucun ne prouve le sous-type intérieur demandé. Le candidat ajoute des cartes au suivi de zone ; ce volume supplémentaire ne résout pas le défaut d’équipement.

**Vérification suivante :** Conserver et vérifier le sous-type intérieur.

## C007 Séjour de trois heures à Melbourne

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 6 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0 ; T3 5 → 0.

La prod propose des hôtels aux deux tours. Le candidat maintient la durée mais ne trouve aucune offre datée vérifiable ; rien ne démontre que les offres legacy sont disponibles à cette date.

**Vérification suivante :** Comparer requêtes et disponibilités, puis proposer un compromis concret.

## C008 Escale près de JFK à date historique

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 5 → 0 ; T2 0 → 0.

La prod affiche des hôtels éloignés vers Jersey City. Le candidat conserve JFK et les horaires, mais la date historique est rejouée en 2027 et la recherche est vide. Géographie et calendrier empêchent de comparer le seul volume.

**Vérification suivante :** Rejouer à date relative avec contrôle de distance et du séjour complet.

## C009 Piscine pour enfants à Abu Dhabi

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 10 → 10. Hôtels distincts dans le parcours : 9 → 6.

Cartes par tour : T1 5 → 5 ; T2 5 → 5.

Même volume de cartes. Le candidat maintient une réserve d’accès au suivi ; la prod promet davantage sans preuve de politique enfants. La première réponse candidat reste trop affirmative.

**Vérification suivante :** Vérifier accès et politique enfants sur la formule.

## C010 Edison et East Brunswick en soirée

**Notes prod → candidat : D → C · Mieux noté.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 8 → 0.

Cartes par tour : T1 5 → 0 ; T2 5 → 0 ; T3 0 → 0 ; T4 0 → 0.

La prod affiche dix cartes cumulées puis se trompe de pays sur Metro Park. Le candidat ne résout pas complètement Edison et traite une date contradictoire comme juillet 2027 tout en disant ce soir. Les deux parcours échouent différemment.

**Vérification suivante :** Résoudre la contradiction de date avant recherche et conserver les deux zones.

## C011 Brooklyn puis budget et horaires

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 10 → 0.

Cartes par tour : T1 5 → 0 ; T2 5 → 0.

La prod montre des options dont une hors quartier et au-dessus du plafond. Le candidat demande quel Brooklyn ; les réponses historiques ne lèvent pas l’ambiguïté. La clarification peut être légitime, mais ne conduit à aucun résultat dans ce rejeu fixe.

**Vérification suivante :** Faire un rejeu adaptatif avec confirmation du Brooklyn visé.

## C012 Gillingham et séjour de quatre heures

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 5 → 2. Hôtels distincts dans le parcours : 5 → 2.

Cartes par tour : T1 0 → 0 ; T2 5 → 2 ; T3 0 → 0 ; T4 0 → 0.

Les deux proposent des hôtels après la ville. Le candidat en montre moins puis n’invente pas une offre pour des heures déjà passées localement ; la prod ne persiste pas correctement le nouvel horaire.

**Vérification suivante :** Rejouer à heure future et vérifier la qualité de literie annoncée.

## C013 NYC puis Newark puis Manhattan

**Notes prod → candidat : B → C · Moins bien noté.** Cartes cumulées : 5 → 5. Hôtels distincts dans le parcours : 5 → 5.

Cartes par tour : T1 0 → 0 ; T2 0 → 5 ; T3 0 → 0 ; T4 5 → 0.

Le candidat trouve des hôtels à NYC mais perd ce contexte après Newark et redemande quel Manhattan. La prod aboutit à Manhattan. C’est une régression de suivi, malgré les cinq cartes initiales du candidat.

**Vérification suivante :** Rejouer la conservation du précédent parent vérifié.

## C014 Singapour avec faute puis nuit

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 5 → 0 ; T2 5 → 0.

La prod récupère le nom et affiche des cartes. Le candidat demande confirmation puis répond à une question de nuit sans cartes. Le deuxième tour relève de la FAQ hors périmètre ; il ne faut pas compter toute la différence comme perte de recherche.

**Vérification suivante :** Distinguer récupération du nom et validation séparée du parcours nuit.

## C015 Jacuzzi à Milford puis nombre seul

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 8 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0 ; T3 3 → 0.

La prod propose des alternatives en signalant l’absence de jacuzzi. Le candidat garde le filtre et n’a pas d’offre vérifiable ; le nombre suivant répondait à une autre question côté legacy.

**Vérification suivante :** Tester un assouplissement consenti puis un budget explicite.

## C016 Escale à Berlin Mitte

**Notes prod → candidat : C → A · Mieux noté.** Cartes cumulées : 0 → 1. Hôtels distincts dans le parcours : 0 → 1.

Cartes par tour : T1 0 → 0 ; T2 0 → 1.

La prod répond de façon explicative sans recherche utile. Le candidat résout le quartier et affiche une offre réelle. Gain de progression et de pertinence, pas seulement gain de cartes.

**Vérification suivante :** Conserver ce parcours comme contrôle positif.

## C017 Westminster jacuzzi et climatisation

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 11 → 0. Hôtels distincts dans le parcours : 9 → 0.

Cartes par tour : T1 4 → 0 ; T2 2 → 0 ; T3 2 → 0 ; T4 0 → 0 ; T5 3 → 0.

La prod affiche des options puis relâche un filtre sans consentement. Le candidat clarifie d’abord un homonyme, mais redemande encore la ville après Westminster UK et interprète un nombre comme lieu. Les deux ont des défauts.

**Vérification suivante :** Utiliser la réponse UK pour résoudre le parent et clarifier le rôle du nombre.

## C018 Bercy puis date et créneau

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 10 → 10. Hôtels distincts dans le parcours : 7 → 9.

Cartes par tour : T1 0 → 0 ; T2 5 → 5 ; T3 5 → 5.

Même volume de cartes et origine conservée. Le candidat ne privilégie pas immédiatement le moins cher demandé, mais trouve ensuite une option à 57 EUR.

**Vérification suivante :** Vérifier que le premier classement suit la demande de prix.

## C019 East Brunswick puis plafond USD

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 8 → 10. Hôtels distincts dans le parcours : 6 → 5.

Cartes par tour : T1 5 → 5 ; T2 3 → 5.

Le candidat conserve ville et plafond et montre plus de cartes au suivi. Le rendu EUR et la sélection générique restent peu alignés avec la demande qualitative ; la prod cite aussi des hôtels absents de la liste.

**Vérification suivante :** Améliorer la présentation du prix et la justification du classement.

## C020 Disneyland sans ville

**Notes prod → candidat : D → B · Mieux noté.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0 ; T3 0 → 0 ; T4 0 → 0 ; T5 0 → 0 ; T6 0 → 0.

Aucun hôtel des deux côtés. La prod choisit un pays erroné ; le candidat clarifie un parc ambigu, mais les suites fixes ne répondent pas à sa question. Absence de cartes ici ne signifie pas régression.

**Vérification suivante :** Rejouer avec confirmation du parc réellement souhaité.

## C021 South Plainfield en excluant NYC

**Notes prod → candidat : D → B · Mieux noté.** Cartes cumulées : 15 → 2. Hôtels distincts dans le parcours : 13 → 2.

Cartes par tour : T1 5 → 2 ; T2 5 → 0 ; T3 5 → 0.

La prod continue à proposer Manhattan malgré l’exclusion. Le candidat garde le New Jersey, mais demande le rôle du nombre puis la devise. Moins de cartes et meilleure contrainte géographique, avec friction de clarification.

**Vérification suivante :** Répondre au budget dans le contexte réel puis contrôler la zone exclue.

## C022 La Défense puis arrivée à 18 h

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 9 → 0.

Cartes par tour : T1 5 → 0 ; T2 5 → 0.

La prod montre des cartes avec prix nul ou créneau inadapté. Le candidat conserve plafond et arrivée mais redemande la ville aux deux tours. Refuser de mauvaises offres ne justifie pas ce blocage géographique.

**Vérification suivante :** Résoudre La Défense puis comparer les formules couvrant 18 h.

## C023 Halifax puis absence de plafond

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 4 → 0. Hôtels distincts dans le parcours : 2 → 0.

Cartes par tour : T1 2 → 0 ; T2 2 → 0.

La prod choisit une ville et impose un plafond malgré la demande. Le candidat garde l’absence de plafond, mais répète le choix Canada ou Royaume-Uni auquel le suivi fixe ne répond pas.

**Vérification suivante :** Tester une réponse de désambiguïsation réelle.

## C024 Halton et Peel puis piscine

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 7 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0 ; T3 5 → 0.

La prod remplace les deux régions par Toronto et promet trop sur l’accès. Le candidat conserve le besoin piscine mais ne transforme pas les deux lieux en demande exploitable. Question générique sans recherche.

**Vérification suivante :** Conserver les deux régions et demander une priorité utile si nécessaire.

## C025 Île de France spa pour deux

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 15 → 6. Hôtels distincts dans le parcours : 8 → 5.

Cartes par tour : T1 5 → 5 ; T2 5 → 0 ; T3 0 → 1 ; T4 5 → 0.

Le candidat sait rechercher et détailler la première offre, puis bloque deux fois sur la composition du groupe et perd la géographie après près de moi. La prod avance mais mélange spa seul, chambre et budget.

**Vérification suivante :** Préserver la découverte conditionnelle et la référence de prix lors des suivis.

## C026 Près de moi sans GPS en anglais

**Notes prod → candidat : A → A · Même note.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0.

Les deux agents demandent une localisation sans inventer de résultat. Zéro carte est le comportement attendu à ce stade.

**Vérification suivante :** Contrôle négatif à conserver.

## C027 Près de moi puis 80 EUR et horaires

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 4 → 1. Hôtels distincts dans le parcours : 2 → 1.

Cartes par tour : T1 2 → 1 ; T2 1 → 0 ; T3 1 → 0.

La prod affiche des alternatives lointaines annoncées. Le candidat applique réellement 80 EUR mais sa prose cite l’ancien seuil de 97,50 EUR ; la recherche est vide. Défaut d’explication distinct du filtrage.

**Vérification suivante :** Aligner le texte sur le plafond actif et vérifier l’offre legacy comparable.

## C028 Jacuzzi à Milan à date explicite

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 4 → 5. Hôtels distincts dans le parcours : 4 → 5.

Cartes par tour : T1 0 → 0 ; T2 4 → 5.

Les deux recherchent et le candidat affiche légèrement plus de cartes. Il distingue présence et accès privé ou inclus, que la prod promet sans preuve suffisante.

**Vérification suivante :** Conserver l’incertitude d’accès dans les détails aussi.

## C029 Aéroport de Vienne puis 13 h à 18 h

**Notes prod → candidat : B → A · Mieux noté.** Cartes cumulées : 5 → 1. Hôtels distincts dans le parcours : 5 → 1.

Cartes par tour : T1 0 → 0 ; T2 0 → 1 ; T3 5 → 0.

Le candidat trouve d’abord une offre puis ne montre plus de formule vérifiable pour le créneau exact. La prod affiche des créneaux partiels avec réserve. Différence de stratégie d’alternative, pas preuve de perte d’inventaire.

**Vérification suivante :** Proposer une alternative explicite après accord sur les horaires.

## C030 Déjeuner inclus sans destination

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0.

Les deux demandent un lieu. Le candidat laisse l’inclusion conditionnelle à la formule ; aucune carte n’est attendue sans destination.

**Vérification suivante :** Contrôle de clarification et d’inclusion à conserver.

## C031 Navette à DFW

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 5 → 2. Hôtels distincts dans le parcours : 5 → 2.

Cartes par tour : T1 0 → 0 ; T2 5 → 2.

Les deux reconnaissent l’aéroport. Le candidat expose deux offres avec créneaux réels contre cinq côté prod ; navette et disponibilité ne sont pas comparables par nombre seul.

**Vérification suivante :** Vérifier navette incluse et pertinence des formules retournées.

## C032 Portugal puis deux villes dont une mal écrite

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 0 → 2. Hôtels distincts dans le parcours : 0 → 2.

Cartes par tour : T1 0 → 0 ; T2 0 → 0 ; T3 0 → 0 ; T4 0 → 2.

La prod perd Porto avec la faute sur Lisbonne. Le candidat recherche Porto et signale l’autre zone non résolue. Gain de récupération partielle explicite.

**Vérification suivante :** Conserver les alternatives valides sans prétendre couvrir les deux villes.

## C033 Singapour avec arrivée à minuit

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0 ; T3 0 → 0 ; T4 0 → 0 ; T5 0 → 0.

La prod présente d’abord 00 h comme compatible avec une formule commençant à 00 h 30. Le candidat ne montre aucune offre pour minuit ; les dates historiques et le suivi comparatif sans liste compliquent le rejeu.

**Vérification suivante :** Tester minuit à date future et annoncer toute alternative de 30 minutes.

## C034 Jacuzzi autour de Den Bosch

**Notes prod → candidat : D → B · Mieux noté.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 4 → 0.

Cartes par tour : T1 0 → 0 ; T2 2 → 0 ; T3 3 → 0.

La prod affiche des hôtels vers Schiphol comme s’ils répondaient à Den Bosch. Le candidat garde la ville et le jacuzzi mais répond vide puis clarifie une réaction issue de la branche legacy.

**Vérification suivante :** Vérifier le résultat fournisseur local et proposer un compromis géographique explicite.

## C035 Près de moi demain avec piscine

**Notes prod → candidat : B → C · Moins bien noté.** Cartes cumulées : 0 → 5. Hôtels distincts dans le parcours : 0 → 5.

Cartes par tour : T1 0 → 0 ; T2 0 → 5 ; T3 0 → 0 ; T4 0 → 0.

Le candidat montre cinq cartes au deuxième tour, puis transforme demain en période indéfinie et bloque. La prod ne montre aucune carte mais continue à demander le lieu. Le défaut candidat ne se voit pas dans le total de cartes.

**Vérification suivante :** Rejouer le correctif de flexibilité temporelle.

## C036 Barking tôt le matin puis moins cher

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0 ; T3 5 → 0.

La prod présente des créneaux partiels en les signalant. Le candidat garde 06–16, n’a pas d’offre vérifiable et ne peut pas établir moins cher sans référence. Les suites fixes n’acceptent aucun compromis.

**Vérification suivante :** Tester des alternatives après consentement sur le créneau.

## C037 Cph avec jacuzzi

**Notes prod → candidat : A → B · Moins bien noté.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0.

Aucune carte. La prod reconnaît le code et explique la couverture ; le candidat demande une précision. Régression mineure de compréhension et de récupération, invisible dans les compteurs de cartes.

**Vérification suivante :** Valider la normalisation avec une identité fournisseur et une couverture autoritative.

## C038 SeaWorld et paiement en espèces

**Notes prod → candidat : D → B · Mieux noté.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 5 → 0.

La prod choisit Seattle sans fondement. Le candidat demande la ville du parc et ne fournit pas de mauvaise sélection. Le paiement en espèces reste à vérifier.

**Vérification suivante :** Répondre à l’ambiguïté puis vérifier les conditions de paiement séparément.

## C039 Deux quartiers de Rio

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 0 → 4. Hôtels distincts dans le parcours : 0 → 2.

Cartes par tour : T1 0 → 2 ; T2 0 → 2.

La prod perd l’une des alternatives. Le candidat conserve les deux, puis les rattache à Rio et affiche des résultats dans les zones vérifiées.

**Vérification suivante :** Contrôle positif de zones alternatives et parent.

## C040 Philadelphie le soir avec jacuzzi privé

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 4 → 0. Hôtels distincts dans le parcours : 1 → 0.

Cartes par tour : T1 0 → 0 ; T2 1 → 0 ; T3 1 → 0 ; T4 1 → 0 ; T5 1 → 0.

La prod répète une carte diurne et avance un rayon en temps de trajet non prouvé. Le candidat conserve soirée et jacuzzi, reste sans offre et propose des compromis ; il ne vérifie pas non plus le temps de voiture.

**Vérification suivante :** Proposer un seul compromis explicite et ne pas promettre un rayon routier.

## C041 Aéroport puis Rome

**Notes prod → candidat : A → C · Moins bien noté.** Cartes cumulées : 0 → 5. Hôtels distincts dans le parcours : 0 → 5.

Cartes par tour : T1 0 → 0 ; T2 0 → 5.

Le candidat affiche cinq cartes du centre-ville alors que la prod demande quel aéroport. Ici davantage de cartes constitue un défaut : le besoin aéroport est perdu.

**Vérification suivante :** Rejouer la clarification aéroport persistante avant toute sélection.

## C042 Centre de congrès à Auckland

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0.

La prod affiche des hôtels après précision de ville. Le candidat conserve le repère mais ne trouve aucune offre datée. La cause de la différence fournisseur n’est pas établie.

**Vérification suivante :** Comparer identité du repère et offres à date identique.

## C043 Rothrist puis autre horaire

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 0 → 6. Hôtels distincts dans le parcours : 0 → 3.

Cartes par tour : T1 0 → 0 ; T2 0 → 3 ; T3 0 → 3.

La prod élargit vers Zurich et applique un contexte monétaire inadéquat. Le candidat garde la ville et expose les créneaux réels, mais change de langue sur un tour.

**Vérification suivante :** Conserver le lieu et stabiliser la langue des suivis.

## C044 Liverpool station puis Hoxton

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 5 → 0 ; T2 0 → 0.

La prod choisit Liverpool et montre notamment un prix nul ; le candidat clarifie Liverpool Street ou Lime Street. Le suivi d’hôtel nommé reste ensuite insuffisamment résolu des deux côtés.

**Vérification suivante :** Tester station confirmée puis recherche d’hôtel nommé indépendante.

## C045 Hôtel Five 6 Splendour mal écrit

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0.

Aucun hôtel des deux côtés. Le candidat pose une question générique au lieu d’une récupération ciblée du nom ; la prod répète aussi une demande de ville.

**Vérification suivante :** Proposer une identité fournisseur plausible à confirmer.

## C046 Séjour romantique à New York

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 5 → 5. Hôtels distincts dans le parcours : 5 → 5.

Cartes par tour : T1 0 → 0 ; T2 5 → 5.

Même volume de cartes. Le candidat annonce son secteur mais la sélection reste générique et ne démontre pas le caractère romantique.

**Vérification suivante :** Justifier les critères qualitatifs sans inventer de prestations.

## C047 Alghero puis retrait de piscine

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0 ; T3 0 → 0.

Aucune carte des deux côtés. La prod dit retirer la piscine mais garde le filtre ; le candidat le retire réellement. Gain d’état même sans résultat disponible.

**Vérification suivante :** Contrôle positif du retrait explicite de filtre.

## C048 Rueil puis département 92

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 3 → 0. Hôtels distincts dans le parcours : 3 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0 ; T3 3 → 0.

La prod interprète 92 comme budget et ville ; le candidat reconnaît le département mais perd Rueil et redemande la ville. Les cartes legacy ne suffisent pas à valider le parcours.

**Vérification suivante :** Associer le département au lieu déjà demandé sans créer de budget.

## C049 Hong Kong de 04 h à 17 h

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 5 → 0.

La prod propose des recouvrements partiels explicités. Le candidat ne trouve pas de formule complète ; la date d’octobre est rejouée en 2027. Disponibilité et stratégie d’alternative sont confondues.

**Vérification suivante :** Rejouer à date relative avec compromis d’horaire explicite.

## C050 Secteur est de Rome

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 5 → 0.

La prod ignore est et affiche Rome entière. Le candidat refuse de résoudre le secteur et demande un repère, en français malgré la demande italienne. Ni couverture correcte ni récupération fluide.

**Vérification suivante :** Clarifier le secteur utilement et préserver la langue.

## C051 Près de moi sans GPS en italien A

**Notes prod → candidat : A → A · Même note.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0.

Les deux demandent un lieu. Aucun hôtel n’est inventé et aucun déficit de sélection n’est établi.

**Vérification suivante :** Contrôle négatif à conserver.

## C052 Près de moi sans GPS en italien B

**Notes prod → candidat : A → A · Même note.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0.

Les deux demandent un lieu. Il s’agit d’un autre parcours conservé, pas d’une preuve indépendante sur une nouvelle famille.

**Vérification suivante :** Conserver sans surpondérer les doublons de comportement.

## C053 Deux codes postaux britanniques

**Notes prod → candidat : B → C · Moins bien noté.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 5 → 0 ; T2 0 → 0.

La prod recherche depuis une origine et demande la priorité ; la proximité aux deux points n’est pas démontrée. Le candidat perd les points dans une question générique sans sélection.

**Vérification suivante :** Rejouer la clarification structurée des deux origines.

## C054 Hong Kong de 04 h à 17 h avec répétition

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 5 → 0 ; T2 0 → 0.

La prod affiche un recouvrement partiel puis clarifie. Le candidat garde tout le séjour mais reste vide sur une date rejouée en 2027. Même objectif que C049 avec un suivi supplémentaire.

**Vérification suivante :** Contrôle complémentaire de conservation des heures, pas nouveau cas indépendant.

## C055 Paris de 22 h à 03 h

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0.

Aucune carte. Le candidat explicite le créneau non supporté ; les affirmations générales sur les nuitées relèvent du périmètre FAQ à traiter séparément.

**Vérification suivante :** Valider la frontière séjour diurne et nuit en phase dédiée.

## C056 Chambre fumeur à Mons puis Bruxelles

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 0 → 10. Hôtels distincts dans le parcours : 0 → 7.

Cartes par tour : T1 0 → 0 ; T2 0 → 2 ; T3 0 → 2 ; T4 0 → 1 ; T5 0 → 0 ; T6 0 → 5 ; T7 0 → 0.

Le candidat montre des offres dans les villes demandées et conserve la référence de détail ; la prod n’affiche aucune carte. L’autorisation de fumer reste inconnue, donc le volume ne valide pas ce critère.

**Vérification suivante :** Vérifier les conditions sans assimiler inconnu à autorisé.

## C057 Piscine enfants puis Annapolis et baignoire

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 17 → 12. Hôtels distincts dans le parcours : 8 → 7.

Cartes par tour : T1 0 → 0 ; T2 5 → 5 ; T3 0 → 1 ; T4 5 → 0 ; T5 5 → 5 ; T6 1 → 1 ; T7 1 → 0.

Le candidat perd le contexte Maryland pour Annapolis et cumule piscine, jacuzzi et baignoire au dernier tour. Les deux agents promettent parfois trop sur l’accès. Le candidat ajoute un détail mais perd des recherches utiles.

**Vérification suivante :** Réutiliser le parent et distinguer ajout de préférence et remplacement.

## C058 École Montessori à Mississauga

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0.

La prod montre cinq hôtels sans preuve que les distances partent de l’école. Le candidat demande une adresse pour vérifier le repère avant de classer par proximité.

**Vérification suivante :** Comparer l’origine réelle avant de qualifier les cartes manquantes de régression.

## C059 Gare de Lyon à Paris

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 0 → 5. Hôtels distincts dans le parcours : 0 → 5.

Cartes par tour : T1 0 → 5.

La prod redemande quelle ville malgré le repère. Le candidat géocode et montre cinq offres ; une formulation mélange minutes et distance aérienne.

**Vérification suivante :** Conserver la résolution et corriger la formulation des distances.

## C060 Heathrow avec GPS distant

**Notes prod → candidat : C → A · Mieux noté.** Cartes cumulées : 0 → 3. Hôtels distincts dans le parcours : 0 → 3.

Cartes par tour : T1 0 → 3.

La prod redemande quel aéroport. Le candidat privilégie l’aéroport explicitement nommé et montre trois offres cohérentes malgré le GPS distant.

**Vérification suivante :** Contrôle positif de priorité à la destination explicite.

## C061 Dublin centre demain puis budget et piscine

**Notes prod → candidat : B → C · Moins bien noté.** Cartes cumulées : 15 → 0. Hôtels distincts dans le parcours : 7 → 0.

Cartes par tour : T1 5 → 0 ; T2 5 → 0 ; T3 5 → 0.

La prod avance à chaque tour en signalant le manque de piscine. Le candidat bloque trois fois sur le centre de Dublin malgré les contraintes suffisantes. C’est une perte claire de progression.

**Vérification suivante :** Valider le centre fournisseur et rejouer les trois tours.

## C062 Kimpton nommé à Los Angeles

**Notes prod → candidat : D → B · Mieux noté.** Cartes cumulées : 6 → 2. Hôtels distincts dans le parcours : 6 → 1.

Cartes par tour : T1 1 → 1 ; T2 5 → 1.

La prod affiche d’abord un hôtel de Miami puis se reprend. Le candidat garde la bonne identité et ne mélange pas la propriété au suivi piscine. Moins de cartes, identité plus fiable.

**Vérification suivante :** Conserver le contrôle d’identité et éviter les précisions inutiles.

## C063 Biltmore mal orthographié à Los Angeles

**Notes prod → candidat : B → C · Moins bien noté.** Cartes cumulées : 1 → 0. Hôtels distincts dans le parcours : 1 → 0.

Cartes par tour : T1 1 → 0 ; T2 0 → 0.

La prod récupère le nom. Le candidat demande encore nom et ville déjà fournie, puis ne peut traiter les horaires. Régression de récupération du nom.

**Vérification suivante :** Tester un candidat fournisseur à confirmer sans inventer l’identité.

## C064 Rockville Centre puis horaires

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 10 → 10. Hôtels distincts dans le parcours : 6 → 5.

Cartes par tour : T1 5 → 5 ; T2 5 → 5.

Même volume. La prod coupe à tort le nom de municipalité ; le candidat conserve Rockville Centre comme un tout et les heures demandées.

**Vérification suivante :** Contrôle positif des noms composés.

## C065 Adresse à Madrid puis moins cher et plus près

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 0 → 5. Hôtels distincts dans le parcours : 0 → 5.

Cartes par tour : T1 0 → 0 ; T2 0 → 5 ; T3 0 → 0 ; T4 0 → 0.

La prod perd la rue et élargit sans résultat. Le candidat résout l’adresse simple et propose cinq hôtels ; ensuite le plafond moins cher limite la recherche sans compromis de proximité assez clair.

**Vérification suivante :** Comparer le point géocodé et expliciter le compromis prix distance.

## C066 Animaux acceptés à Glendora à 11 h

**Notes prod → candidat : B → A · Mieux noté.** Cartes cumulées : 5 → 5. Hôtels distincts dans le parcours : 5 → 5.

Cartes par tour : T1 0 → 0 ; T2 5 → 5.

Les deux affichent cinq hôtels. Le candidat conserve l’arrivée et vérifie la couverture du créneau ; la prod confond parfois heure de début de formule et heure demandée.

**Vérification suivante :** Contrôle positif de couverture de l’arrivée.

## C067 Hong Kong puis Tuen Mun et Tung Chung

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 6 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0 ; T3 5 → 0 ; T4 0 → 0 ; T5 0 → 0 ; T6 5 → 0.

La prod finit par élargir au centre sans consentement. Le candidat reste vide sur 17–23 puis perd le parent Hong Kong et ne peut produire une référence moins chère. Défaillance de suivi distincte de l’inventaire vide initial.

**Vérification suivante :** Restaurer le parent des deux zones et négocier explicitement les horaires.

## C068 Farnborough en soirée

**Notes prod → candidat : B → A · Mieux noté.** Cartes cumulées : 5 → 3. Hôtels distincts dans le parcours : 5 → 3.

Cartes par tour : T1 0 → 0 ; T2 5 → 3.

La prod propose cinq alternatives dont certaines peu adaptées au soir. Le candidat affiche trois formules 16–22 et annonce les villes voisines. Une sélection plus courte peut être plus pertinente.

**Vérification suivante :** Contrôle positif du créneau de soirée.

## C069 Sauna puis Washington et moins cher

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 2 → 10. Hôtels distincts dans le parcours : 1 → 10.

Cartes par tour : T1 0 → 0 ; T2 1 → 5 ; T3 1 → 5.

La prod transforme sauna en spa. Le candidat sait ensuite rechercher et comparer moins cher, mais la première référence à ces hôtels ne possède pas de liste source. Les cartes diffèrent fortement entre branches.

**Vérification suivante :** Séparer le critère sauna de spa et répondre aux références réellement présentes.

## C070 Downey avec faute puis incompréhension

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0.

La prod finit par rechercher Downey. Le candidat propose la bonne correction mais attend une confirmation que le suivi ne donne pas ; il prétend aussi avoir recherché avant confirmation.

**Vérification suivante :** Rejouer une confirmation adaptative et retirer la fausse annonce de recherche.

## C071 Baignoire à Hong Kong

**Notes prod → candidat : C → A · Mieux noté.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0.

La prod affiche cinq hôtels sans maintenir le filtre baignoire. Le candidat garde ce critère et ne dispose d’aucune offre datée vérifiable. Les cartes legacy ne prouvent donc pas la satisfaction de la demande.

**Vérification suivante :** Comparer les caractéristiques de chambre et les offres datées.

## C072 Venise en mai avec plafond en euros

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 11 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 5 → 0 ; T2 3 → 0 ; T3 3 → 0.

La prod mélange EUR et USD et répète des cartes non confirmées. Le candidat conserve 110 EUR et rejoue mai en 2027, mais répète sa réponse vide sans aide utile.

**Vérification suivante :** Rejouer à date proche et proposer un compromis concret en restant dans la bonne devise.

## C073 Philadelphie escale puis moins cher

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 15 → 11. Hôtels distincts dans le parcours : 10 → 10.

Cartes par tour : T1 5 → 5 ; T2 5 → 1 ; T3 5 → 0 ; T4 0 → 5.

La prod prétend parfois couvrir tout le séjour avec des créneaux incompatibles. Le candidat couvre réellement les heures, refuse un moins cher non vérifiable, puis reprend avec cinq cartes près de l’aéroport.

**Vérification suivante :** Conserver la formule de référence et améliorer la proposition de compromis.

## C074 New Jersey puis GW Bridge

**Notes prod → candidat : D → C · Mieux noté.** Cartes cumulées : 5 → 3. Hôtels distincts dans le parcours : 5 → 3.

Cartes par tour : T1 0 → 1 ; T2 5 → 0 ; T3 0 → 0 ; T4 0 → 2.

La prod affiche des hôtels de Virginie pour le pont. Le candidat demande une rive déjà contextualisée puis perd le pont après Bergen County. Les deux sélections ont des problèmes géographiques.

**Vérification suivante :** Conserver le New Jersey et le point fin du pont après affinage.

## C075 Piscine à Londres puis journée entière

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 5 → 10. Hôtels distincts dans le parcours : 5 → 5.

Cartes par tour : T1 5 → 5 ; T2 0 → 5.

Le candidat garde les cartes et indique le plus long créneau réel 10–18 ; la prod répond sans cartes au second tour. L’accès piscine reste à prouver.

**Vérification suivante :** Demander les heures exactes et vérifier l’accès de formule.

## C076 Piscine et spa à Heemskerk

**Notes prod → candidat : B → A · Mieux noté.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0 ; T3 5 → 0.

La prod affiche cinq hôtels avec une contradiction texte carte. Le candidat conserve les deux équipements mais retourne vide et propose des zones proches. Aucun écart de rappel n’est démontré sans comparaison fournisseur.

**Vérification suivante :** Comparer les requêtes puis tester un élargissement accepté.

## C077 La Quinta à San Antonio puis rue

**Notes prod → candidat : D → C · Mieux noté.** Cartes cumulées : 1 → 5. Hôtels distincts dans le parcours : 1 → 5.

Cartes par tour : T1 1 → 5 ; T2 0 → 0.

La prod propose d’abord un hôtel du Colorado. Le candidat reste dans la ville mais applique mal la préférence de chaîne et perd San Antonio au suivi de rue. Plus de cartes ne signifie pas objectif atteint.

**Vérification suivante :** Conserver chaîne et rue dans la destination demandée.

## C078 Spa puis rooftop le soir à Rome

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0.

La prod montre des alternatives en signalant les services non vérifiés. Le candidat applique soirée à la recherche de chambre et reste vide ; le besoin concernait peut-être surtout l’accès au rooftop après le séjour.

**Vérification suivante :** Séparer horaires de chambre et horaires des services.

## C079 Budapest puis 100 EUR

**Notes prod → candidat : A → B · Moins bien noté.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0.

Aucun hôtel des deux côtés. La prod explique la couverture du marché ; le candidat répète une absence d’offres et propose une autre date. Défaut de récupération sans impact sur le nombre de cartes.

**Vérification suivante :** Utiliser une preuve actuelle de couverture, pas une supposition du modèle.

## C080 Al Mankool puis Dubai

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0.

La prod se trompe d’abord de pays puis perd le quartier. Le candidat garde quartier et arrivée mais ne le résout pas après Dubai, et prétend avoir recherché. Les deux restent insatisfaisants.

**Vérification suivante :** Valider le quartier avec son parent et annoncer honnêtement l’étape bloquante.

## C081 Ascenseur sans keycard puis comparaison

**Notes prod → candidat : A → B · Moins bien noté.** Cartes cumulées : 10 → 17. Hôtels distincts dans le parcours : 10 → 5.

Cartes par tour : T1 0 → 0 ; T2 5 → 5 ; T3 5 → 0 ; T4 0 → 5 ; T5 0 → 5 ; T6 0 → 2.

La prod répond au budget et compare les deux cartes. Le candidat clarifie un nombre dans une branche différente puis réaffiche les hôtels lors de questions informatives. Davantage de cartes cumulées ne prouve pas la règle d’accès.

**Vérification suivante :** Rejouer le budget dans son contexte et comparer en gardant la réserve sur l’accès.

## C082 Préférence sans destination puis aucune

**Notes prod → candidat : B → C · Moins bien noté.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0.

Aucune carte. La prod continue à demander la ville ; le candidat transforme aucune en période temporelle. Le défaut n’apparaît pas dans les volumes.

**Vérification suivante :** Rejouer le correctif du sujet de flexibilité.

## C083 Entre deux villes avec enfants et piscine

**Notes prod → candidat : B → C · Moins bien noté.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0.

La prod avance avec une origine et des choix sous plafond sans prouver toute la compatibilité. Le candidat conserve groupe et budget, mais pose une question générique sur les deux villes.

**Vérification suivante :** Rejouer le contrat des origines multiples puis vérifier les capacités.

## C084 Deux ZIP puis San Antonio et 40 USD

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 17 → 0. Hôtels distincts dans le parcours : 10 → 0.

Cartes par tour : T1 5 → 0 ; T2 5 → 0 ; T3 5 → 0 ; T4 2 → 0.

La prod expose des alternatives hors ZIP ou budget avec réserve. Le candidat demande deux fois le parent, puis conserve le dernier ZIP et reste sans offre datée sous plafond. Les causes varient selon le tour.

**Vérification suivante :** Tester confirmation de ZIP puis élargissement et plafond séparément.

## C085 Piscine à Paris sans limite de budget

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 10 → 10. Hôtels distincts dans le parcours : 5 → 5.

Cartes par tour : T1 0 → 0 ; T2 5 → 5 ; T3 5 → 5.

Même volume. La prod fixe pourtant un plafond et promet trop sur l’accès. Le candidat respecte l’absence de limite et distingue équipement et accès, avec texte encore générique.

**Vérification suivante :** Conserver absence de plafond et preuve d’accès dans tous les suivis.

## C086 Red Deer puis demain

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 4 → 4. Hôtels distincts dans le parcours : 2 → 2.

Cartes par tour : T1 2 → 2 ; T2 2 → 2.

Même nombre de cartes et date conservée. Le candidat affirme spontanément une piscine incluse sans preuve de formule ; défaut de prose malgré les résultats.

**Vérification suivante :** Étendre les réserves d’accès aux mentions spontanées et aux détails.

## C087 Los Angeles deux personnes puis lit douche et LAX

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 15 → 7. Hôtels distincts dans le parcours : 13 → 6.

Cartes par tour : T1 5 → 4 ; T2 5 → 2 ; T3 5 → 1.

Le candidat conserve séjour, literie et transfert vers l’aéroport avec des formules vérifiées, mais réduit progressivement la liste. La prod conserve plus de cartes sans garantir tout le séjour ni les équipements de chambre.

**Vérification suivante :** Vérifier la distinction dans le terminal et près de l’aéroport.

## C088 Denver une heure puis fourchette numérique

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 9 → 5. Hôtels distincts dans le parcours : 9 → 5.

Cartes par tour : T1 0 → 0 ; T2 5 → 5 ; T3 4 → 0.

Les deux montrent cinq hôtels. La prod avait demandé un budget ; le candidat pose une autre question puis clarifie la fourchette. Le rejeu fixe crée une partie de la friction.

**Vérification suivante :** Rejouer une réponse monétaire explicite dans chaque branche.

## C089 Capodistria puis nuit

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0.

Aucune carte. Couverture du marché et demande de nuit dominent le parcours ; la partie FAQ n’est pas validée en phase 1.

**Vérification suivante :** Traiter couverture autoritative et nuit dans le périmètre dédié.

## C090 San Bruno puis 125 USD

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 10 → 9. Hôtels distincts dans le parcours : 6 → 5.

Cartes par tour : T1 5 → 5 ; T2 5 → 4.

Le candidat garde San Bruno, le plafond et les frais et affiche quatre cartes au suivi contre cinq. La prod ajoute une zone aéroport non demandée. Différence de volume mineure sans rappel mesuré.

**Vérification suivante :** Contrôler le total et éviter les ancres ajoutées implicitement.

## C091 Lower Manhattan avec faute puis 200

**Notes prod → candidat : B → C · Moins bien noté.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 6 → 0.

Cartes par tour : T1 5 → 0 ; T2 5 → 0.

La prod comprend le quartier et le budget dans sa branche. Le candidat demande confirmation du quartier puis prend le nombre pour un lieu. Régression initiale de récupération, puis effet de branche.

**Vérification suivante :** Rejouer normalisation du quartier et clarification du rôle numérique.

## C092 Strasbourg calme à 10 h puis classement

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 5 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0 ; T3 0 → 0 ; T4 0 → 0.

La prod affiche un prix nul et classe sa liste. Le candidat reste vide sur les offres datées, puis ne peut comparer deux hôtels inexistants dans sa branche. Le suivi est peu utile mais ne doit pas inventer de liste.

**Vérification suivante :** Comparer l’inventaire daté puis adapter les suivis à la liste réellement affichée.

## C093 Adresse partielle à Manhattan

**Notes prod → candidat : B → C · Moins bien noté.** Cartes cumulées : 0 → 0. Hôtels distincts dans le parcours : 0 → 0.

Cartes par tour : T1 0 → 0 ; T2 0 → 0.

Aucune carte des deux côtés. La prod propose une interprétation précise à confirmer ; le candidat redemande des composants déjà donnés au lieu de la ville. Défaut de clarification ciblée.

**Vérification suivante :** Rejouer le correctif de ville manquante.

## C094 Utrecht sous 80 EUR puis septembre

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 20 → 0. Hôtels distincts dans le parcours : 5 → 0.

Cartes par tour : T1 5 → 0 ; T2 5 → 0 ; T3 5 → 0 ; T4 5 → 0 ; T5 0 → 0.

La prod répète prix nul, offre hors plafond et disponibilité non étayée. Le candidat garde le plafond, retourne vide puis conserve la date rejouée en 2027. Il manque une récupération utile malgré le filtrage prudent.

**Vérification suivante :** Comparer à date proche et offrir un compromis sans augmenter le budget tacitement.

## C095 Chambre à thème puis Fayetteville

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 0 → 2. Hôtels distincts dans le parcours : 0 → 1.

Cartes par tour : T1 0 → 0 ; T2 0 → 0 ; T3 0 → 1 ; T4 0 → 1.

Le candidat retrouve une offre après la ville et la conserve après aucune ; la prod reste vide. Le thème adulte demandé n’est pas prouvé, donc le gain d’inventaire ne vaut pas validation du besoin.

**Vérification suivante :** Vérifier le thème ou préciser qu’il est inconnu.

## C096 Brooklyn avec faible dépôt puis budget

**Notes prod → candidat : B → B · Même note.** Cartes cumulées : 10 → 0. Hôtels distincts dans le parcours : 7 → 0.

Cartes par tour : T1 0 → 0 ; T2 5 → 0 ; T3 5 → 0.

La prod choisit NYC et affiche des options. Le candidat propose des homonymes ; le suivi budgétaire ne choisit aucun lieu. Le dépôt relève en plus de conditions non établies.

**Vérification suivante :** Faire une clarification adaptative du lieu puis vérifier les conditions de dépôt.

## C097 23rd Street Manhattan en soirée

**Notes prod → candidat : C → C · Même note.** Cartes cumulées : 10 → 5. Hôtels distincts dans le parcours : 7 → 5.

Cartes par tour : T1 5 → 0 ; T2 5 → 5.

La prod montre des cartes avec créneaux partiellement inadéquats. Le candidat clarifie NYC puis affiche Financial District en perdant 23rd Street. Le total final masque une perte du repère fin.

**Vérification suivante :** Conserver l’origine précise après confirmation de ville.

## C098 Paris famille puis retrait enfant et moins cher

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 15 → 15. Hôtels distincts dans le parcours : 10 → 15.

Cartes par tour : T1 5 → 5 ; T2 5 → 5 ; T3 5 → 5.

Même volume. Le candidat applique réellement le retrait de l’enfant et annonce les créneaux alternatifs ; la prod mélange capacité inconnue et produit spa seul. Quelques formulations tarifaires restent ambiguës.

**Vérification suivante :** Contrôle positif des mises à jour de groupe et alternatives horaires.

## C099 Paris puis autres hôtels sans exigence de baisse

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 20 → 15. Hôtels distincts dans le parcours : 11 → 15.

Cartes par tour : T1 5 → 5 ; T2 5 → 5 ; T3 10 → 5.

Les deux avancent, mais la prod dit ne pas avoir d’autres hôtels tout en montrant de nouvelles cartes et en affichant dix au dernier tour. Le candidat conserve le plafond et pagine sans répéter la première sélection.

**Vérification suivante :** Vérifier nouvelles identités plutôt que le seul nombre de cartes.

## C100 Manhattan en USD puis moins cher et nouveau plafond

**Notes prod → candidat : C → B · Mieux noté.** Cartes cumulées : 20 → 9. Hôtels distincts dans le parcours : 7 → 5.

Cartes par tour : T1 5 → 5 ; T2 5 → 0 ; T3 5 → 0 ; T4 5 → 3 ; T5 0 → 1.

La prod élargit à Queens sans accord et mélange référence de prix et créneau. Le candidat refuse le moins cher non vérifiable, conserve Manhattan, puis reprend au plafond explicite et détaille le total réel.

**Vérification suivante :** Améliorer le compromis prix tout en gardant zone et formule de référence.

## Versions et limites

Comparatif historique : candidat 3153771 contre production legacy 3093647. Le dernier code applicatif 548b739 n’est pas réévalué par ce document. Export/Qdrant côté prod et MCP préproduction côté candidat, référence legacy exécutée plus tôt le même jour ; différences de calendrier et de concurrence. Les 100 cas incluent des régressions connues, des exemples synthétiques et des doublons de famille, pas un échantillon indépendant de six mois de trafic. Aucun échec d’inventaire n’est causalement attribué au code sans preuve.

[Comparatif source](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/evals/PRODUCTION_PARITY_2026_10_10.json) · [Derniers correctifs non encore rejoués](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/evals/GROUPED_REGRESSIONS_AND_REGEX_RISKS_2026_10_10.md) · [PR 134](https://github.com/Dayuse-Labs/AgentB2C/pull/134).
