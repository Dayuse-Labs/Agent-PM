# Évaluation recherche avant remplacement de la production — 9 octobre 2026

**Suite locale non poussée :** préparation de l'origine détenue avant le modèle
pour éviter l'épuisement du quota par des recherches prématurées. Dix tests
ajoutés et contre-épreuve hors réseau des appels v58. Le même lot protège aussi
l'identité exacte d'un quartier contre sa ville parente : cinq tests ajoutés et
rejeu du reçu fournisseur Manhattan avec le snapshot d'inventaire. Aucun appel
payant, aucune nouvelle note live. La perte de rue lors d'une clarification de
ville reste ouverte ; le triage la classe parfois comme changement de destination.
Les résultats ci-dessous concernent toujours exclusivement `d1320bc`.

**Décision : pas de GO remplacement. PR 134 conservée en draft pour revue technique.**
La PR corrige des défauts démontrés, mais le dernier rejeu complet contient encore
23 parcours C et un D. Aucun résultat ne prouve la conservation exhaustive des
six mois de comportement en production. FAQ, annulation et actions SAV sont
reportées à la phase 2 à la demande de Victor.

## Périmètre livré

- Le concierge détient le contexte entre tours : destination confirmée,
  clarification, dates et heures, durée, moment de journée, budget avec unité et
  devise, équipements et occupation. Les feuilles restent stateless via A2A.
- Les lieux nommés sont vérifiés contre les résultats fournisseurs. Une ville
  explicite ne peut plus devenir arbitrairement un commerce ou une recherche GPS.
  Les variantes de régions, unions et périmètres sont typées ; leur extraction
  reste imparfaite et ne doit pas être assimilée à une couverture complète.
- Les cartes doivent correspondre à une même offre datée : créneau compatible,
  prix et frais, devise indexée et capacité. Les comparaisons « moins cher »
  utilisent un prix antérieur vérifié. Une rétraction d'enfant remet children à zéro.
- Le classement par distance précède la pagination ; l'origine est explicitée.
  Les détails hôtel alimentent la synthèse avec les équipements et jusqu'à vingt
  formules datées vérifiées, chacune gardant son prix et son créneau.
- Pas de nouvelle regex d'intention, ni de SDK modèle direct. LiteLLM, MCP,
  A2A et Redis détenu par le concierge sont conservés ; les outils restent bornés.
  Les changements FAQ déjà présents dans la branche ne sont pas validés par ce lot.

## Version et méthode

Runtime figé : `d1320bc2d425dbc7c8264ee464d7c507b242003e`, base main `cbe88b9`.
Les commits de documentation postérieurs ne modifient pas ce runtime.
Modèles **locaux de cet essai** : triage `gpt-4.1-mini`, recherche `gpt-4o-mini`,
synthèse `gpt-5.2`. Aucun modèle par défaut ou paramètre Railway modifié.

56 conversations complètes / 156 réponses, toutes relues avec leurs cartes,
profils et traces d'outils. Le lot comporte des régressions historiques déjà
exposées et des contrôles synthétiques ; les identifiants historiques « holdout »
ne signifient plus qu'il s'agit d'une validation réservée. Deux conversations
purement politiques ont été retirées du lot précédent de 58. Les questions
mixtes restent entières, mais les règles FAQ ne sont pas notées en phase 1.

| Passage candidat | A | B | C | D | Non notés | Réponses |
|---|---:|---:|---:|---:|---:|---:|
| v55, avant les trois lots suivants | 3 | 16 | 25 | 5 | 9 | 160 |
| v56 | 3 | 24 | 20 | 1 | 8 | 156 |
| v57 | 5 | 24 | 20 | 2 | 5 | 156 |
| v58, source finale | 5 | 19 | 23 | 1 | 8 | 156 |

A = satisfaisant sur le parcours observé ; B = défaut mineur ; C = significatif ;
D = majeur ; F = critique (aucun F dans ces passages). Revue par Codex avec
preuves, **pas une validation humaine indépendante**. Variabilité modèle,
inventaire et horloge différents : cette table n'établit ni causalité globale ni
taux de victoire contre la prod. Le dernier passage n'est pas un progrès uniforme.
Les branches conditionnelles incohérentes et contextes manquants restent non notés.

La vraie prod a été rejouée en v55 et reste visible conversation par conversation
dans le rapport privé. Elle utilise export/Qdrant ; le candidat utilise le MCP
préproduction, reflet exact de la prod selon Victor. L'identité et la fraîcheur de
ces deux inventaires ne sont pas indépendamment garanties. Les prix/hôtels
historiques ne servent donc pas de réponse attendue universelle.

Validation réservée : 5 conversations issues des messages SQL et des
traces Langfuse correspondantes, 28 réponses prod/candidat, jamais
utilisées pour concevoir ces corrections. Requêtes conservées, contexte adapté
seulement lorsqu'attesté ; GPS arrondi et autorisation de fixture distingués du
payload navigateur d'origine. Résultat détaillé dans le rapport privé ; ce petit
échantillon ne prouve aucune supériorité statistique. Revue : prod 3 C / 2 D ;
candidat 3 B / 2 C. Gains observés sur budget/devise native, arrivée à 13h,
origine nommée et alternatives moins chères à Bangkok ; défauts persistants
sur appartements et week-end non résolu. 33 cartes candidat supplémentaires
rapprochées des reçus MCP, sans écart de prix/jointure/expiration.

## Gains observés et limites

- Milan reste une ville au lieu du commerce homonyme « environs » observé en v57.
  Strasbourg et le suivi piscine de Dublin atteignent leur recherche sans le
  défaut d'origine/quota observé au passage précédent.
- Soirée avant clarification de ville, minuit à Singapour, dates numériques,
  créneaux complets et changement de formule/prix à Rockville Centre sont conservés.
- Piscine extérieure Kimpton et huit créneaux Biltmore vérifiés contre les reçus
  MCP du même tour. Aucun prix unique n'est attribué à toutes les formules.
- **Manhattan reste D** : le lieu est rejeté comme New York City, puis l'agent
  propose New York/Illinois malgré l'État initial. Arrêter les mauvais résultats
  ne suffit pas à rendre le parcours utilisable.
- LAX, codes postaux, adresse après ville et quartiers restent fragiles. Des
  précisions peuvent disparaître ; Lisboa ou Porto ne cherche que Porto.
- Baignoire → jacuzzi, déjeuner → petit-déjeuner et équipement hôtel → chambre
  privative restent des écarts de sens. Les filtres ne prouvent pas l'accès inclus.
- Une critique de distance ou un résultat vide peut boucler ou repartir en
  salutation. La synthèse peut annoncer qu'il faut élargir alors que de nouvelles
  cartes viennent d'être affichées, ou mal expliquer une fin de créneau.
- La validation réservée montre aussi une demande de week-end oubliée après
  clarification partielle : le candidat recherche vendredi en attendant samedi/dimanche.
- Un suivi « moins cher » a épuisé son quota avec deux appels avant géocodage.
  Les logs confirment un mauvais ordre d'outils, pas une panne réseau MCP.

Prochain lot cohérent : extraction/provenance des contraintes, résolution typée
borough/adresse/parent, ordre des outils détenu par le code et contrat de synthèse
incluant résultat/pagination/récupération. Ajouter des régressions de cause commune,
puis refaire un passage complet figé et une nouvelle validation réservée.
Ne pas assouplir la vérification géographique uniquement pour faire passer Manhattan.

## Vérifications et coût

- **2 686 tests passés, un ignoré**, 102 tests ciblés ; ruff, mypy (69 fichiers),
  guardrails verts sur le runtime final.
- **151 cartes** rapprochées des reçus MCP du même tour par hôtel, identifiant
  d'offre, date et minutes : zéro carte sans correspondance, écart de prix ou
  offre expirée à la réponse ; zéro dépassement des plafonds vérifiables.
  Ce contrôle ne valide pas la pertinence ni la compréhension de la demande.
- Coût v58 : **1,46111915 USD** ; validation réservée : **0.43411109 USD**.
  Cumul comptabilisé : **109.13609113 / 110 USD**, provisions incluses.
  Les provisions antérieures de 12,10 USD restent comptées ; ce n'est pas une
  facture fournisseur définitive. Aucun appel payant automatique supplémentaire.
- Le diagnostic triage antérieur (48 appels) n'établit pas de gagnant universel.
  Le test de feuille 4.1 préparé n'a pas été exécuté. Aucun changement de modèle
  de production recommandé sur la seule base de ces observations.

Messages réels, GPS, traces, reçus, scripts exacts et registre de coûts sont
conservés hors Git. Les datasets suivis dans ce dépôt sont des spécifications
synthétiques, pas l'intégralité du corpus exécuté. L'index de 256 commits / 2 088
symboles de tests historiques est une carte de couverture, pas autant de
comportements certifiés. L'expiration réelle de session et toute la phase 2
restent notamment à vérifier. Aucun merge, déploiement ou acte de réservation.
