# Évaluation recherche avant remplacement de la production — 9 octobre 2026

**Pas de GO remplacement. PR 134 en draft pour revue technique.**
Dernier runtime évalué : `27362ee5394b69bf0268908f8c6a433b16a43ec5` (v60),
base main `cbe88b9`. FAQ, annulations et actions SAV en phase 2.

## Dernier passage complet

56 conversations / 156 réponses relues : **4 A, 21 B, 21 C, aucun D/F,
10 non notées**. A = satisfaisant sur le parcours observé ; B = mineur ;
C = significatif ; D = majeur ; F = critique. Revue Codex avec preuves,
pas validation humaine indépendante ni supériorité statistique.

47 parcours référencent des messages SQL de production ; 9 contrôles sont
synthétiques. 132 tours portent un identifiant de ligne source. 52 références
à des fichiers sources ont leur empreinte revérifiée ; quatre autres cas sont
des spécifications de contrôle explicites. Les 33 conversations historiques
initiales couvrent mai–octobre. Le corpus est exposé, pas un test réservé.

151 cartes rapprochées par hôtel, offre, date et créneau aux reçus MCP du même
tour : aucun écart de prix, jointure manquante ou offre expirée à la réponse.
Aucun dépassement des plafonds vérifiables en devise native/EUR. Les capacités
adulte/enfant des 15 cartes du parcours de rétractation sont suffisantes.
Piscine extérieure Kimpton, huit créneaux Biltmore, équipements Aloft et préavis
massage de 48 heures confirmés au reçu détails.

**Limite horaire :** deux offres commencent à 10h30 pour une demande 10h–17h.
La règle site compare les heures entières et les admet ; la couverture littérale
à la minute n'est pas garantie et l'écart n'est pas annoncé. Le parcours reste C.

## Valeur du lot v60

Le catalogue MCP lu par scope confirme que douche, baignoire, climatisation et
room service sont des équipements de chambre. Le code les ignorait et supprimait
les `roomEquipmentIds`. Le lot les traduit désormais dans le bon filtre, distingue
ascenseur/rooftop bar côté hôtel, conserve une exigence supportée même si une autre
clé est inconnue, et maintient la propriété des critères au concierge après
clarification ou rétractation. Les feuilles restent stateless.

- Baignoire → Hong Kong : critère conservé, requête `roomEquipmentIds=[11]`,
  aucun jacuzzi substitué. Aucun résultat disponible sur la date du passage.
- Spa puis rooftop le soir → Rome : `hotelEquipmentIds=[35,2981]`, critères
  conservés et aucune restriction « evening » ajoutée au créneau de chambre.
  L'inclusion tarifaire et les horaires du rooftop restent non prouvés.
- Douche + lit double : le transfert du filtre de chambre fonctionne, mais le
  triage ajoute aussi baignoire sans demande. Cas toujours C ; le lit reste
  explicitement non vérifié. Élargir le vocabulaire ne corrige pas cette erreur
  d'interprétation. Pas de filtre spécifique au lit ou à l'insonorisation.
- Déjeuner : aucun filtre petit-déjeuner ajouté sur ce passage, mais un seul
  tour sans recherche repas aboutie. Ce n'est pas une validation de bout en bout.

2707 tests passent, 1 ignoré ; 87 ciblés ; ruff, mypy (70 fichiers) et guardrails
passent. Contrefactuel hors réseau sur les mêmes extractions avant/après et tests
multi-tour de conservation/rétractation. Aucune nouvelle regex, phase modèle ou
hausse de quota. Code figé pendant tout le passage.

## Défauts ouverts

- Interprétation : ajout baignoire à douche, journée entière devenue matin,
  jacuzzi hôtel présenté comme chambre avec jacuzzi privé.
- Géographie : LAX, codes postaux, rues et unions de villes ; 23rd Street perdue
  après New York sur ce passage, Halm Blvd perd San Antonio, « Milano e dintorni »
  résolu comme une association. « Près de l'aéroport » peut garder le centre-ville.
- Périmètre : alternatives Bronx/Queens annoncées comme Manhattan ; Lisbonne ou
  Porto réduit à Porto ; pont perdu après précision de région.
- Dialogue : critique/sarcasme déclenche un accueil ; pagination affichant bien
  de nouvelles cartes mais texte demandant d'élargir. Fin de formule à 23h
  présentée comme un problème pour un départ souhaité à 20h.
- Données : contextes navigateur absents, branches conditionnelles différentes,
  dates historiques et disponibilité actuelle limitent plusieurs comparaisons.

## Comparaison et modèle

| Candidat | A | B | C | D | Non notés | Réponses |
|---|---:|---:|---:|---:|---:|---:|
| v55 | 3 | 16 | 25 | 5 | 9 | 160 |
| v58 | 5 | 19 | 23 | 1 | 8 | 156 |
| v59 | 5 | 18 | 24 | 0 | 9 | 156 |
| v60 | 4 | 21 | 21 | 0 | 10 | 156 |

Ces changements de notes ne prouvent pas un gain causal global : horloge,
inventaire, variabilité des modèles et branches non comparables diffèrent.
Les corrections antérieures d'origine préparée et d'identité exacte Manhattan
restent fonctionnelles ; les suivis USD, moins cher, plafond et détails aboutissent,
ainsi que le retrait d'enfant. La qualité de tout le dialogue reste insuffisante.

La vraie prod rejouée en v55 (export/Qdrant) reste visible face au candidat via
MCP préproduction, décrit comme reflet de la prod par l'utilisateur. Fraîcheur et
retrieval diffèrent : les anciens hôtels/prix ne sont pas un attendu universel.
Le petit lot réservé v58 (cinq conversations, 28 réponses prod/candidat) n'est
pas attribué à v60 et est désormais exposé.

Modèles locaux inchangés depuis v58 : triage 4.1-mini, recherche 4o-mini,
synthèse 5.2. Des erreurs persistent même au triage 4.1-mini et dans la synthèse ;
aucune justification ici pour promettre qu'un remplacement de 4o-mini suffira.
Aucune variable Railway modifiée, aucun déploiement ni merge.

## Budget et preuves

v60 : **1,3512553 USD** ; cumul conservateur **107,8330605 / 110 USD**, dont
8,10 USD de provisions non tarifées maintenues. Réserve interne : 0,75 USD.
Toutes les générations physiques réconciliées ; aucune écriture de budget en
attente, aucun rejeu actif. Les étapes live des précédentes CI étaient ignorées :
leur succès n'est pas une mesure de qualité et leurs provisions ont été rapprochées
séparément sur preuves. La nouvelle CI doit être contrôlée sur le commit publié.

Les conversations, reçus, coordonnées, générations, revues signées par empreintes,
matrices comparatives et ledger sont privés, hors Git, dans le rapport v60.
Prochaine étape de qualité : un lot cohérent sur interprétation de contraintes,
raffinement géographique et restitution des alternatives, puis un nouveau contrôle
non réservé à ces seuls cas. Ce document n'autorise pas le basculement en production.
