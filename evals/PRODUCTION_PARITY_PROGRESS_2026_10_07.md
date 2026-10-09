# Évaluation recherche avant remplacement de la production — 9 octobre 2026

**Pas de GO remplacement. PR 134 en draft pour revue technique.**
Un lot v62 est préparé localement, sans push ni rejeu réel : conservation des
quartiers après précision de ville, pagination, horaires partiels et restitution
des prix avec frais. 2726 tests / 1 ignoré et quatre contre-factuels sur traces
v61 passent hors réseau ; ils ne changent aucune note du bilan ci-dessous.
Coût additionnel nul, budget inchangé. Rejeu complet requis avant publication.

Runtime évalué : `f90e3681e0a7fd7f92b92b5c793e5267e53c2698` (v61),
base main `cbe88b9`, fetchée à nouveau et inchangée. FAQ, annulations et SAV
restent en phase 2 ; aucune correction FAQ ajoutée dans le lot v61.
Des modifications FAQ antérieures existent dans le diff cumulé : ce verdict
recherche ne les valide pas pour lancement.

## Passage complet et méthode

**58 conversations, 163 réponses**, relues en entier avec cartes, profils,
appels d'outils et générations. Modèles/code/entrées figés durant tout le passage.
Aucun rejeu automatique payant, aucune modification Railway ou trafic client.

| Cohorte | A | B | C | D/F | Non notés |
|---|---:|---:|---:|---:|---:|
| 56 historiques exposés | 7 | 20 | 23 | 0 | 6 |
| 2 sessions récentes | 0 | 0 | 1 | 0 | 1 |
| Total | 7 | 20 | 24 | 0 | 7 |

A = satisfaisant sur le parcours observé ; B = mineur ; C = significatif ;
D = majeur ; F = critique. Revue Codex, pas validation humaine indépendante.
Une branche conditionnelle devenue incohérente est non notée, jamais comptée
comme un succès. La grille reste historique A/B/C/D/F.

Les 56 cas précédents sont identiques à v60 : 47 parcours avec références SQL,
9 contrôles synthétiques. Les conversations initiales couvrent mai–octobre.
Deux sessions du dernier export SQL sont ajoutées séparément : quartiers de Rio
puis précision de ville, et jacuzzi privé/soirée à Philadelphie. Leurs 7 messages
et domaines sont vérifiés octet pour octet contre la source, avec empreinte.
Les traces Langfuse des sessions ont été lues ; le contexte navigateur manquant
n'a pas été inventé. Ce sont des observations récentes déjà lues, pas un holdout
aveugle. L'API SQL ne fournit pas le drapeau synthétique ; les sessions de test
identifiables ont été exclues, sans prétendre certifier tous les visiteurs.

## Valeur et limites du lot géographique

Le provider renvoie un parent ville avec identifiant ; ce parent était perdu
pour les POI. Le lot le conserve dans les adaptateurs et le profil du concierge,
puis autorise un raffinement de rue depuis cette preuve. Le texte de requête
n'est pas accepté comme parent vérifié. Un contrefactuel hors réseau, sur la
même identité et le même reçu réel v60, montre le rejet de San Antonio avant
et sa conservation après. Cela ne prouve pas la réussite de toute conversation.

Le type municipalité décidé par le concierge persiste au fallback fournisseur :
un commerce homonyme ne peut pas devenir cette destination. Le triage sépare
nom propre et préférence de proximité, et précise les règles de raffinement.
Aucune nouvelle regex ou phase modèle. LiteLLM, A2A, feuilles stateless et Redis
au concierge sont conservés.

- **23rd Street → New York :** rue conservée et résolue, cinq offres à
  0,5–1,3 km couvrent 18h30–21h. B, avec clarification initiale encore évitable.
- **La Quinta → Halm Blvd :** reste C. Le premier tour ne résout cette fois
  aucune identité ; la correction du parent fournisseur n'a donc pas de parent
  vérifié à transporter. Halm est mal extrait comme municipalité. Pas «corrigé».
- **Milano e dintorni :** plus de commerce/association homonyme, mais une
  clarification redondante bloque encore la recherche. C, pas un succès global.
- **Quartiers de Rio → Rio :** nouvelle observation C ; union reconnue puis
  perdue après précision de la ville. Les hôtels effectivement à Barra ne
  prouvent pas que les deux quartiers restent correctement recherchés.

2714 tests passent, 1 ignoré ; ruff, mypy (70 fichiers), guardrails verts.
Les tests couvrent parent réel vs texte de recherche, stockage et retour A2A,
refus du parent sans identifiant et fallback ville/commerces/POI légitimes.

## Vérification factuelle indépendante des notes

269 cartes rapprochées à l'offre exacte du même tour (hôtel, UUID, date,
créneau) : **0 jointure manquante, 0 écart de prix carte/reçu, 0 expiration**.
Aucun dépassement de plafond vérifiable en devise native/EUR. Ce contrôle ne
valide ni la prose de prix ni la pertinence géographique.

245 distances affichées correspondent à la distance à vol d'oiseau depuis
l'origine enregistrée. Cela ne valide pas le choix de cette origine, ni un
trajet à pied/voiture. Les 15 capacités du parcours enfant/rétractation sont
confirmées sur les offres sources. Sur 54 cartes avec occupation demandée,
53 portent une capacité suffisante ; une carte détails n'expose pas ce champ,
donc ce contrôle local est indéterminé, pas une insuffisance prouvée.

Les cinq offres de Londres mentionnent explicitement la piscine incluse ;
le parcours journée entière est A sur ce passage. Hong Kong conserve baignoire
avec `roomEquipmentIds=[11]`. Piscine extérieure Kimpton et huit créneaux
Biltmore vérifiés au reçu détails. Les cartes n'affichent toutefois qu'un créneau,
contrairement à certaines phrases de synthèse. Spa/rooftop Rome conserve les
équipements, mais applique cette fois la soirée à la chambre : C.

**Deux offres commencent 10h30 pour 10h demandé**, sans annonce claire.
La règle site en heures les admet ; la couverture littérale à la minute n'est
pas garantie. Ce parcours reste C.

## Défauts à traiter avant remplacement

1. **État géographique et clarifications :** ZIP numériques, LAX, correction
   de rue/numéro, pont après précision de comté, unions de villes/quartiers,
   aéroport remplacé par une origine centre-ville. Bronx/Queens mal annoncés
   comme Manhattan. La disponibilité de stock ne valide pas le périmètre.
2. **Portée des contraintes :** chambre vs hôtel/jacuzzi privé, chambre en
   journée vs rooftop le soir, montants nus et devise, alternatives «ou».
   Le bon filtre ne suffit pas si la contrainte a été mal interprétée.
3. **Restitution :** nouvelles pages annoncées comme une absence d'autres
   choix, sarcasme/objection déclenchant un accueil, départ 20h opposé à une
   formule finissant 23h, prix avec frais comparé à une carte hors frais sans
   explication, détails source présentés comme déjà visibles sur la carte.

Philadelphie récente finit par annoncer honnêtement qu'aucune offre ne couvre
la soirée et que le jacuzzi privé n'est pas confirmé. Pas de faux match garanti,
mais le tour «another one» n'a pas de carte de référence dans la branche obtenue :
non noté globalement. Limite 35 minutes en voiture non vérifiée.

## Comparaison avec la prod et coût

v60 avait 4 A / 21 B / 21 C / 10 non notés sur les mêmes 56 entrées.
Les notes v61 ne prouvent pas un gain causal global : changement de date,
inventaire et tirages modèle rendent davantage de suites comparables.
La vraie prod rejouée en v55 reste visible dans la matrice, ainsi que les réponses
SQL des deux nouvelles sessions. Legacy export/Qdrant contre MCP préproduction
(reflet de la prod selon l'utilisateur) : comparer les obligations utilisateur
et les reçus, pas exiger la même liste d'hôtels ou le même prix à des dates différentes.

Modèles locaux inchangés : triage 4.1-mini, recherche 4o-mini, synthèse 5.2.
523 générations physiques comptabilisées : triage 0,4558 USD ; 4o-mini
0,3142 USD ; synthèse 0,7930 USD. Les erreurs traversent ces trois rôles :
aucune preuve qu'un remplacement de 4o-mini suffise.

**Rejeu v61 : 1,5629836 USD**, plus 0,0082392 USD pour le diagnostic préalable.
**Cumul conservateur : 109,4042833 / 110 USD**, dont 8,10 USD de provisions
non tarifées conservées. Réserve de dispatch interne passée de 0,75 à 0,50 USD,
sans hausse du plafond ni suppression de dette inconnue. Aucun coût tardif,
aucune écriture en attente ; trois services de rejeu arrêtés.

Pas de nouvelle campagne payante automatique. La CI distante doit être vérifiée
sur le commit publié ; les prérequis live sont actuellement absents selon les
métadonnées de secrets, donc un succès des contrôles ne vaut pas une évaluation
conversationnelle. Messages, reçus, traces, GPS, matrices et ledger restent privés,
hors Git, dans `production_parity_v18/batch-v61`.
