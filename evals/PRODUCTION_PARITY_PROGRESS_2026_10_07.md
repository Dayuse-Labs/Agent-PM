# Évaluation recherche avant remplacement de la production — 9 octobre 2026

**La PR corrige des problèmes vérifiés ; le remplacement de la production reste NO GO.**
Runtime évalué `a02b2e0a61613931ca888523986da6e2c5bfaccb` (v69), main
`cbe88b9` fetchée et inchangée. Témoin de production réellement appelé sur
`ai.dayuse.com`, déploiement `a08a7792`. FAQ, annulations et SAV restent phase 2 ;
les anciens changements FAQ du diff cumulé ne sont pas certifiés par ce bilan.

## Comparaison avec la production actuelle

58 conversations / 163 réponses par agent, toutes relues. Témoin production v65
conservé, candidat v69 rejoué : entrées identiques, adaptateurs GPS propres à chaque
API, sessions synthétiques distinctes. 48 conversations historiques, une mixte et
neuf scénarios synthétiques : 139 tours reliés aux sources et 24 tours de test.
Corpus ciblé issu de mai–octobre, exposé pendant le développement : ni exhaustif
ni holdout aveugle. Les réponses divergentes peuvent rendre un suivi incomparable.

| Agent | A | B | C | D | F | Non notés |
|---|---:|---:|---:|---:|---:|---:|
| Production actuelle | 2 | 21 | 28 | 2 | 0 | 5 |
| Candidat v69 | 13 | 22 | 18 | 0 | 0 | 5 |

A = satisfaisant, B = défaut mineur, C = significatif, D = majeur, F = critique.
**26 parcours mieux notés, 5 moins bons, 19 identiques, 8 non comparables**
(au moins un agent non noté). Revue Codex, pas validation humaine indépendante
ni supériorité statistique revendiquée. Une clarification sans réponse n'est pas
un succès. Le bilan v68 reste archivé ; ses échecs ne sont pas effacés par un rejeu.

Production : export/Qdrant. Candidat : MCP préproduction, reflet de production
selon l'équipe. Passages successifs, dates et récupération différentes : une
variation de disponibilité ou de liste n'est pas automatiquement une erreur agent.

## Correction v69 et architecture conservée

Le fournisseur géographique renvoyait San Bruno comme `place` avec une zone.
Son identité n'était pas persistée, puis la feuille tentait une origine GPS au
suivi budget ; les gardes refusaient et la synthèse annonçait une fausse panne.
Le contexte de recherche est désormais validé et conservé aussi pour les types
fournisseur `place` et `locality`, sans les transformer en POI. Il traverse A2A,
Redis et le tour suivant ; une zone différente invalide la réutilisation.

**Rejeu réel : San Bruno → plafond 125 USD conserve le même point fournisseur,
et quatre offres compatibles sont proposées.** Un test contrefactuel utilise
également le reçu Mapbox original, réseau bloqué. Sept tests supplémentaires
couvrent la transmission réelle du contrat et les contextes invalides/changés.
Aucune nouvelle regex, liste de villes ou phase modèle.

Les corrections cumulées conservent budget/devise, dates/heures, participants,
pagination/moins cher, coordonnées fournisseur et faits de formule liés à
hôtel/UUID/date. Concierge propriétaire du contexte Redis, feuilles A2A stateless,
modèles via LiteLLM. Les chemins historiques de compatibilité restent présents.
Leur présence ne garantit pas une extraction sémantique juste.

## Préservation de l'historique et données récentes

**24 parcours géographiques supplémentaires / 72 tours historiques**, sans
recouvrement des lignes SQL avec le lot principal, reliés aux tests legacy dans
`geo_preservation_registry.json` : **9 préservés, 7 partiels, 5 échecs, 3 non évaluables**.
Critères géographiques ciblés, pas notes produit globales ni nouveau témoin prod.
East Brunswick, Abu Dhabi, Milford CT, Melbourne Australie, Gillingham UK,
Heathrow terminal 3, Paris Bercy et Paddington sont notamment conservés.
Halton/Peel, Berlin Mitte, JFK, correction de La Défense après faute et trajet
Metropark–Princeton restent en échec. Queens garde son origine mais présente
une alternative hors quartier sans avertissement suffisant.

Lecture fraîche des logs production : 2 000 lignes parmi 34 321, dont 124 nouvelles
lignes / 51 sessions sans préfixe de notre harnais depuis le précédent export.
C'est l'API des logs de production, pas un nouvel export SQL intégral ; l'origine
organique de ces sessions n'est pas certifiée. Trois parcours / sept tours ont été
figés avant leur exécution ; leurs sept traces Langfuse ont été relues. Les champs
natifs absents n'ont pas été inventés. Comparaison aux réponses sources enregistrées,
pas nouveau témoin production rejoué, ni ajout aux 58 notes principales :

- Rothrist : B. Identité suisse conservée malgré le domaine brésilien ; pas de
  plafond 100 CHF inventé. Autres horaires déclenche une clarification pertinente.
- Auckland : C. Centre de congrès conservé mais ville non validée au suivi ;
  l'agent demande une date au lieu d'aboutir sur la destination.
- Rome : C. L'aéroport devient le centre de Rome ; la distinction FCO/CIA est
  demandée après affichage de cartes de ville, même si la limite est annoncée.

Les cinq diagnostics adaptatifs v68 restent historiques, non rejoués en v69.

## Blocages avant remplacement

Cinq reculs face au témoin prod : ZIP San Antonio, Lower Manhattan ancré sur
un commerce, correction 547 West 47th conservant l'ancien point 257–259,
rooftop du soir non vérifié, déjeuner transformé en petit-déjeuner.
Autres défauts : Philadelphia aéroport conserve l'origine centre-ville ; matinée
jusqu'à 18 h mal filtrée ; courtes protestations renvoyées à un accueil ; correction
de zone bloquée ; équipement hôtel présenté comme accès inclus ou jacuzzi privé.
Une réponse texte de la feuille sans résultat structuré peut encore être rendue
comme indisponibilité technique (Milano).

La formule William Vale à **0 EUR/0 USD** réapparaît dans le reçu MCP et les cartes.
Jointure exacte ne signifie pas prix commercial valide. Ce traitement reste à
corriger ; aucun séjour gratuit n'est certifié.

Prochaine correction par familles : mise à jour/remplacement explicite du lieu,
réponse à une clarification, horaires mixtes, sémantique équipements et prix
exploitables, puis nouveau rejeu complet. Pas d'exceptions propres aux villes.

## Vérification et modèles

**2799 tests passent, 1 ignoré** ; ruff, mypy (71 fichiers), guardrails verts.
71 empreintes runtime identiques avant/après les trois campagnes v69. Deux
conversations indépendantes à la fois, tours séquentiels. Une erreur MCP HTTP 502
après neuf réponses a interrompu le lot principal ; recherche réelle de contrôle,
coûts et profils Redis vérifiés avant reprise des seuls tours manquants, mêmes
sessions/processus/horloge. Aucune réponse payée rejouée ou supprimée.

Lot principal : **278 cartes** jointes au reçu exact hôtel/UUID/date/créneau,
zéro jointure manquante, erreur de prix, expiration ou dépassement vérifiable.
253 distances concordent avec l'origine stockée : cela ne valide ni le choix de
l'origine ni un trajet. Deux créneaux 10 h 30 pour 10 h restent admis par la règle
site à l'heure entière, écart évoqué en prose ; pas de garantie à la minute.
56 cartes avec occupation demandée, zéro capacité connue insuffisante, une absente.
Geo : 119 cartes, 112 distances ; récents : 15 cartes, 15 distances, sans écart.

Local évalué : **triage 4.1-mini / recherche 4o-mini / synthèse 5.2**.
Railway B2C garde triage 4o-mini ; verdict non transposable automatiquement.
Production legacy : GPT-5.2. Appels physiques : 507 principal, 222 geo, 21 récents,
tous statut modèle ok ; ceci ne prouve pas la réussite des outils/résultats.
Le diagnostic antérieur de 108 appels sur 18 contextes de triage ne démontrait
pas de gain universel de 5.2. Aucun changement Railway ni upgrade global.

## Coût et livraison

| Campagne | USD télémétriques |
|---|---:|
| Reprise v65–v68, témoin prod et diagnostics compris | 10,766096 |
| Candidat v69, 58/163 | 1,574751 |
| Géographie v69, 24/72 | 0,713671 |
| Conversations récentes v69, 3/7 | 0,066259 |
| **Depuis l'autorisation +40 EUR** | **13,120778** |

Dernier lot : **2,354681 USD**. Cumul conservateur **122,093884 / 150 USD**,
dont 6,10 de provisions inconnues maintenues ; réserve 0,50. +40 EUR traité
conservativement comme +40 USD. Télémétrie modèle, pas facture fournisseur ni
coût Codex/infrastructure. Réconciliation finale sans incrément tardif local ;
ledger sans lot en attente et trois services agents locaux arrêtés.

Preuves privées hors Git : manifestes, reçus et revues liés aux empreintes.
Rapport local `production_parity_v18/current_evaluation.html` : 58 comparaisons et
27 compléments. Source HTML vérifiée, pas inspection visuelle. PR134 demeure draft ;
aucun merge ni déploiement. La CI du nouveau head publié est vérifiée séparément.
