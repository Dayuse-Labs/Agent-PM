# Évaluation recherche avant remplacement de la production — 9 octobre 2026

**Pas de GO remplacement. PR 134 en draft pour revue technique.**
Dernier runtime évalué : `f05be5676fa1685f2f0bfecf495b33ee655027bf` (v59),
base main `cbe88b9`. FAQ, annulations et actions SAV restent en phase 2.

## Dernier passage complet

56 conversations / 156 réponses relues : **5 A, 18 B, 24 C, aucun D/F,
9 non notées**. A = satisfaisant sur le parcours observé ; B = mineur ;
C = significatif ; D = majeur ; F = critique. Revue Codex avec preuves,
pas une validation humaine indépendante ni une supériorité statistique.

47 parcours référencent des messages SQL de production, 9 sont des contrôles
synthétiques. 132 tours portent un identifiant de ligne source. Les 52 fichiers
sources référencés par cas ont leur empreinte vérifiée ; les quatre autres cas
sont définis explicitement comme contrôles synthétiques. Les 33 conversations
historiques initiales couvrent mai–octobre. Les cas déjà exposés ne sont plus un
jeu de validation réservé, quels que soient leurs anciens identifiants.

151 cartes rapprochées par hôtel, offre, date et créneau aux reçus MCP du même
tour : aucun écart de prix, aucune jointure manquante, aucune offre expirée à
la réponse. Aucun dépassement des plafonds vérifiables en devise native/EUR.
15 offres du parcours enfants vérifiées avec leur capacité adulte/enfant.
Piscine extérieure Kimpton, huit créneaux Biltmore et préavis massage48h
confirmés dans les reçus détails du même tour.

**Limite horaire explicite :** deux offres commencent à10h30 pour une demande
10h–17h. La règle site adoptée par main compare les heures entières et les admet ;
elle ne garantit pas la couverture littérale à la minute. Le parcours reste C,
car la réponse ne signale pas cet écart. Ne pas annoncer zéro erreur de créneau.

## Valeur des deux dernières corrections

- Origine vérifiée préparée avant les appels de recherche via les mêmes gardes.
  Le suivi moins cher après rétraction d'enfant atteint désormais le MCP, sans
  épuiser le quota avec deux recherches émises avant le géocodage. Deux adultes,
  absence d'enfant, date, fenêtre et plafond comparatif sont conservés.
- Le classement conserve le quartier exact fourni par le géocodeur au lieu de
  préférer sa ville parente. Manhattan est résolu comme Manhattan et les cinq
  tours fonctionnent : horaires, USD, moins cher, plafond200USD, détail hôtel.
  Le D de géocodage devient C : des alternatives hors Manhattan et une synthèse
  de pagination contradictoire empêchent encore de valider tout le parcours.
- Ces deux mécanismes ont aussi des contre-épreuves hors réseau avant/après.
  Pas de regex ajoutée, de phase modèle supplémentaire ou de quota élargi.

## Défauts ouverts

- Attributs sémantiques perdus entre triage et feuille : douche/baignoire
  correctement étiquetées par le triage, mais absentes du vocabulaire accepté,
  puis remplacées par jacuzzi. Déjeuner devient petit-déjeuner ; jacuzzi hôtel
  ne prouve pas un jacuzzi dans la chambre ou son inclusion dans l'offre.
- Toute la journée devient matin ; soirée rooftop devient créneau de chambre.
- LAX, codes postaux et adresses restent fragiles. La rue23rdSt est conservée
  cette fois, mais sa perte précédente n'est pas démontrée éradiquée. HalmBlvd
  et aéroportPhiladelphie peuvent garder une origine centre-ville incorrecte.
- UnionLisbonne/Porto réduite à Porto ; région donnée après un pont peut faire
  perdre ce repère. Alternatives hors quartier insuffisamment divulguées.
- Critique de distance ou incompréhension peut repartir en salutation.
  Pagination produit de nouvelles cartes mais la synthèse demande d'élargir.
- Contextes navigateur absents, branches conditionnelles devenues incohérentes
  et disponibilités actuelles vides limitent plusieurs comparaisons.

## Comparaison et méthode

| Candidat | A | B | C | D | Non notés | Réponses |
|---|---:|---:|---:|---:|---:|---:|
| v55 | 3 | 16 | 25 | 5 | 9 | 160 |
| v56 | 3 | 24 | 20 | 1 | 8 | 156 |
| v57 | 5 | 24 | 20 | 2 | 5 | 156 |
| v58 | 5 | 19 | 23 | 1 | 8 | 156 |
| v59 | 5 | 18 | 24 | 0 | 9 | 156 |

Le dernier passage n'est pas un progrès global uniforme. Horloge, inventaire,
variabilité modèle et branches non comparables interdisent un taux de victoire
causal calculé à partir de cette table. Les fenêtres sont évaluées à la fois
selon le contrat du site et selon la demande littérale, sans cacher leur écart.

La vraie prod a été rejouée en v55 ; ses conversations restent visibles en face
du candidat dans le rapport privé. Elle utilise export/Qdrant, contre MCP
préproduction pour le candidat (reflet exact de la prod selon Victor). Leur
fraîcheur et leur retrieval diffèrent : ni prix ni hôtels historiques ne sont
une réponse attendue universelle. Géocodage fournisseur enregistré en cache,
inventaire MCP lu en direct, application figée pendant le passage.

Validation réservée précédente v58 : cinq conversations SQL/Langfuse,
28 réponses prod/candidat ; prod3C/2D contre candidat3B/2C, 33 cartes contrôlées.
Ce petit lot n'a pas été rejoué en v59 ; ses résultats ne sont pas attribués au
nouveau runtime. Il est maintenant exposé pour toute correction ultérieure.

Modèles locaux v59 inchangés depuis v58 : triage4.1-mini, recherche4o-mini,
synthèse5.2. Aucun défaut ni modèle Railway modifié. Plusieurs pertes observées
se produisent après un triage correct : un changement de modèle seul ne suffit
pas à corriger ces transferts d'information.

## Validation, coût et traçabilité

2701 tests passent / 1 ignoré ; 177 ciblés, ruff, mypy70fichiers et guardrails
verts sur le code applicatif du lot. Aucun merge ni déploiement.

Passage v59 : **1,34571410USD**. Cumul conservateur après rapprochement :
**106,48180523/110USD**, dont8,10USD de provisions non tarifées, réserve0,75USD.
Les deux provisions CI de2USD couvraient la même PR134 : les41exécutions et tous
leurs essais montrent les étapes payantes ignorées. Leur retrait est documenté,
pas une baisse de dépenses réellement observées. Plafond utilisateur inchangé.

Le passage s'est arrêté au contrôle comptable après le neuvième parcours : une
clarification code-only comptait encore comme phase logique de feuille.
Contre-épreuve hors réseau liée à l'empreinte du reçu, puis observation explicite
du contournement du premier appel modèle ; tous les coûts physiques conservés.
Reprise au dixième parcours, sans rejouer les neuf premiers ni changer le code
applicatif. Instrumentation et reprise consignées dans le manifeste privé.

Preuves privées hors Git : `production_parity_v18/batch-v59/`,
`remote-batch-search-v59/`, `offline-v59/ci-budget-audit/` et comparaison v55.
Le rapport local courant relie conversations, cartes et notes. Aucun message
client, GPS, secret ou reçu brut n'est ajouté au dépôt.
