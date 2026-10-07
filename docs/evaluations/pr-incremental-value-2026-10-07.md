# Valeur résiduelle de la PR #123 après leurs fixes — 7 octobre 2026

**Décision : conserver en draft ; ne pas fusionner le bloc en l’état.** Une partie de nos apports est déjà intégrée dans main. Le delta restant a des gains ciblés démontrés, quatre défauts ouverts et une décision d’architecture à revoir avec l’équipe. Aucun GO de lancement.

## Attribution après les extractions de l’équipe

Main **cbe88b9963f28fbea932ac2a6ce23d22112f2b76** inclut désormais :

- **#130** : budget nu transmis aux arguments MCP. Ce n’est plus un apport incrémental de #123.
- **#131** : contexte des derniers messages vers triage, FAQ et synthèse ; prudence sur la gestion des réservations. Même attribution à main.
- **#132** : socle du replay de production et batterie CI. #121 contient maintenant seulement les compléments restant à examiner.
- Les précédents fixes #122/#126/#127/#129 : dates, créneaux avec arrondi, replis, erreurs MCP, lien Voir tout, compteur et réserve parking du tour courant restent attribués à main.

L’intégration **1791432** conserve exactement le runtime applicatif évalué **2bdca9aaa4328d6f4a6cecafc5e18fa951c176b9** : diff vide sur agents/, libs/, configs/. Les extractions étant déjà présentes dans le candidat, pas de double insertion des hooks de contexte/budget.

## Comparaison réellement exécutée

**41 séquences uniques** : 40 issues des logs de production (clients/QA non distingués individuellement), 1 annulation fictive, dont les **24 parcours géographiques**. Quatre séquences ont un second passage. **155 tours par bras, 310 tours appariés**.

Le nouveau main cbe88b9 a été exécuté sur les 155 tours ; le bras PR réutilise les réponses du runtime identique 2bdca9a. Pas de deuxième facture pour ces réponses. Le premier comparatif contre fee667d (310 tours) reste historique : **465 tours payés au total dans cet audit**, pas 465 nouveaux cas.

Même triage GPT-4.1 mini, feuilles/synthèse GPT-4o mini, horloge fixe, sessions séparées, cache MCP/Mapbox par arguments exacts. Requêtes différentes = données potentiellement différentes ; pas de snapshot transactionnel de tout le catalogue. Le modèle de déploiement par défaut n’est pas comparé. Utilisateur fixe, références ordinales historiques non adaptées à de nouvelles listes ; ancien holdout déjà vu. Le cas de la cohorte historique « common » utilise ici le même cache MCP, pas son ancien inventaire fini.

Ce bras A est **AgentB2C main**, pas le legacy en production. Les anciennes comparaisons legacy restent archivées ; leur export/Qdrant diffère du MCP. Aucun classement global « mieux que la prod » n’est déduit de cet audit. Aucun juge payé : revue Codex des réponses, états et générations, pas gold humain indépendant.

## Ce qui reste utile dans la PR

**18 contrôles déterministes identiques : 5 passent sur main, 18 avec PR.** Les 13 échecs main sont des assertions, pas des erreurs d’import. Sorties de modèles/outils scénarisées ; tests extraits du candidat et complétés par des sondes géo/circuit : preuves de mécanismes, pas 13 bugs clients clos ni suite d’acceptation indépendante.

- Demande de lieu conservée après échec de feuille, contexte de recherche transmis au suivi : Milford/CT, JFK, Heathrow, Queens, Bercy.
- Identité de l’hôtel maintenue au suivi : Rambler Oasis et Sheraton Milano San Siro, sans en déduire prix/disponibilité vérifiés.
- Référence ordinale non résolue bloquée avant un appel outil ; langue maintenue sur un nombre seul.
- Commerces homonymes filtrés dans trois contrôles géographiques ; circuit MCP capable de récupérer malgré des requêtes rejetées pendant son cooldown.
- Prudence sur les nuits et temps de trajet non vérifiés. Main invente notamment une estimation de trajet dans le cas Princeton ; cette protection PR a cependant un faux positif ci-dessous.

La persistance structurée de l’intention et l’extraction du lieu dans le triage constituent une **décision d’architecture encore à valider**, même si les feuilles restent stateless, A2A/MCP conservés et l’état détenu par le concierge. Aucun nouvel appel regex ajouté dans le delta applicatif de notre PR.

## Quatre défauts du candidat, non corrigés par cet audit

| Défaut | Preuve | Reprise requise |
|---|---|---|
| Correction géographique ignorée | Courbevoie/La Défense : faute de zone conservée, édition set/clear contradictoire rejetée. Voir les deux passages dans la matrice. | Contrat set/clear non ambigu ; aucune reconduction silencieuse du lieu corrigé. |
| Ancien plafond conservé | Paramus : 10 reste après under $80 sur 2/2 passages PR ; main change le montant mais garde une sémantique EUR erronée. South Plainfield : 80 reste après 120 dans la PR. | Séparer montant/devise/unité ; clarifier si conversion non disponible. |
| Refus de trajet hors sujet | Long layover : refus terminal sur 1/2 passages PR ; demande de ville appropriée sur main. | Distinguer durée de séjour/escale et vraie question de trajet. |
| Avertissement de créneau contradictoire | 08:45–17:00 demandé, 09:00–17:00 offert : règle commune accepte l’arrondi, annotate_constraints ajoute hours. | Réutiliser slot_covers_window, définition unique du contrat. |

Les répétitions ne garantissent pas une stabilité générale. Main varie aussi ; les preuves sont conservées séparément, sans sélectionner le meilleur passage.

## Couverture encore incomplète

Le JSON adjacent détaille **32 exigences prioritaires**, leur origine, leur attribution et les cas concernés. **314 commits / 1 707 tests legacy inventoriés ne signifient pas tous les acquis portés.**

Pertinence/proximité complète (Berkeley, Atlanta), exclusions de zone/aéroport, question sur le quartier, occupants/enfants, unité tarifaire, durée→créneau (Milano : 2/3h devient 00–23h des deux côtés), GPS réel, expiration de session, cartes cadeaux, no-show, âge et base FAQ exhaustive restent ouverts ou non validés. Le budget nu réparé sur main n’assure pas sa conservation après un échec de lieu.

**Aucune gestion authentifiée de réservation, modification, annulation ou remboursement n’est ajoutée.** La FAQ peut orienter ; elle ne démontre ni éligibilité ni succès d’action. Les dialogues SAV restent parfois trop génériques.

## Vérification et budget

Python 3.13 local : main **2 135 passés / 2 ignorés**, application + PR **2 211 / 2**, harnais complet **2 236 / 2**. Suites qui se recouvrent, ne pas additionner. Ruff, mypy et guardrails verts. Les 18 contrôles comparatifs sont inclus dans le harnais ; pas de total gonflé.

Audit incrémental : **1.53517 USD**. Cumul toutes campagnes : **40.83714 USD observés + 1.00 USD provisionné / 60 USD**, aucun lot pending. Les métriques tardives sont rapprochées. Sur les mêmes 155 tours : main actuel **0.46713 USD**, PR **0.62998 USD** ; pas une prévision du coût de production.

Données brutes, profils, générations, reçus outils, caches, hashes et ledger restent privés. Ce dépôt contient seulement les conclusions et les contrôles synthétiques. Aucun merge vers main, aucun déploiement ni action sur réservation réelle. Les rapports précédents sont historiques ; cette comparaison cbe88b9 est la référence pour la valeur résiduelle de #123.
