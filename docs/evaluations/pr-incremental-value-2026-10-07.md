# Valeur incrémentale de la PR #123 — 7 octobre 2026

**Décision : conserver la PR en draft et la reprendre avant fusion.** Elle apporte des mécanismes utiles, mais ne corrige pas tous les défauts et introduit des régressions. Les tests verts ne donnent pas un GO produit.

## Comparaison réellement exécutée

- Leur main **fee667d3b2b43c91064b58b5186b87ad140cda4f** (incluant #129 parking/compteur) contre le même main avec notre PR, runtime **2bdca9aaa4328d6f4a6cecafc5e18fa951c176b9**.
- Même triage GPT-4.1 mini, mêmes feuilles/synthèse GPT-4o mini, même horloge applicative. Le modèle par défaut d'un déploiement n'est pas comparé : on isole ici le delta de code/prompt.
- Cache partagé des réponses MCP et Mapbox par arguments exacts. Des arguments différents peuvent retourner des données différentes : pas de snapshot transactionnel global ni de parité inventée.
- **41 séquences / 278 tours** (40 issues des logs de production, clients/QA non distingués individuellement, et 1 annulation entièrement fictive). Parmi elles, les 24 dialogues géographiques. **4 séquences répétées / 32 tours**, soit **310 tours** et toujours 41 séquences uniques. Utilisateur fixe, pas de simulation adaptative ; références ordinales à des listes historiques à interpréter avec prudence.
- Aucun juge LLM. Lecture des réponses et états conservés, diagnostics des sorties structurées capturées. Revue Codex, pas gold humain indépendant.

## Apport qui reste utile après leurs fixes

18 contrôles d'intégration identiques, sorties de modèles/outils scénarisées : **18 passent avec PR, 3 sur main**, 15 échecs d'assertion sur main, aucun échec d'import. Ce sont des preuves de mécanismes, pas 15 bugs clients tous clos.

- Budget numérique isolé transmis jusqu'aux arguments de recherche ; langue maintenue sur un nombre seul.
- Demande de lieu conservée après timeout et contexte utilisateur transmis au triage, à la FAQ et à la synthèse, sans contamination entre sessions.
- Hôtel nommé conservé (Rambler Oasis, Sheraton Milano San Siro dans le replay) et identité séparée de prix/disponibilité vérifiés.
- Référence ordinale non résolue bloquée avant un appel de réservation ; précision utile sur les limites de nuit et de trajet.
- Commerces homonymes exclus des lieux demandés dans trois contrôles de géographie ; cooldown du circuit réparé.

Les dialogues montrent notamment un gain sur Milford/Connecticut + 110 (**2/2 avec PR, 0/2 main**), Queens, JFK, Heathrow, Paris Bercy. Cela ne démontre ni un classement optimal ni une réussite complète de tous ces parcours.

## Quatre reprises avant fusion

| Problème | Preuve avant/après | Action requise |
|---|---|---|
| Correction de lieu bloquée | Courbevoie/La Défense : résolution utile main 1/2, PR 0/2. L'ancien texte fautif demeure. Premier passage : une zone renseignée également dans clear_fields fait rejeter toute l'édition. | Rendre le contrat set/clear non ambigu ; ne pas réutiliser silencieusement un ancien lieu après correction. Rejouer correction et nouvelle destination. |
| Ancien budget conservé en silence | Paramus : 10 USD/h devient 10 EUR total dans les deux. Après under $80, main change le montant sur 2/2 (devise toujours incorrecte), PR reste à 10 sur 2/2. South Plainfield reste aussi à 80 après 120. | Séparer montant, devise, unité horaire/total. Sans conversion fiable, expliquer/clarifier au lieu de garder un plafond périmé. |
| Faux refus de calcul de trajet | Une escale longue reçoit la nouvelle réponse terminale travel_time_unverified sur 1/2 passages PR, 0/2 main. Le précédent faux positif Pompei ne se reproduit pas dans ce passage. | Éviter de court-circuiter une recherche pour une durée de séjour/escale ; contre-test avec une vraie question de trajet. |
| Avertissement de créneau contradictoire | Hors LLM, 08:45–17:00 demandé et 09:00–17:00 offert : leur règle d'arrondi accepte ; notre annotate_constraints émet hours. | Réutiliser la règle commune timeslot au lieu de comparer une seconde fois à la minute. |

**Ces quatre défauts ne sont pas corrigés dans le candidat de ce rapport.** Le main varie aussi : son succès Courbevoie n'est pas stable. Le second passage PR hésite ensuite entre Manhattan NY et Illinois ; aucune garantie géographique générale.

## Ce qui est déjà livré par l'équipe

Dates explicites, règle de contenance/arrondi et moments souples, synthèse de repli, erreurs MCP typées, note de devise, état vide, contrat searchPage et lien Voir tout : fixes de main #122/#126/#127. Le compteur de taille de page et la réserve parking du tour courant viennent de #129. Notre PR n'en revendique pas le mérite. Le rappel parking aux suivis et le total réservable restent ouverts.

## Ce qui demeure absent ou non validé

Pertinence complète/proximité (Berkeley, Atlanta), question sur le quartier, exclusion d'aéroport, unité tarifaire, durée → créneau (Milano reste erroné des deux côtés), capacité/enfants (Orange County), et couverture FAQ. La PR améliore la prudence sur annulation/remboursement, mais **n'ajoute pas de consultation authentifiée, modification, annulation ou remboursement de réservation**. Le renvoi Marriott après échec de check-in reste trop générique. Aucune action sur une vraie réservation n'a été effectuée.

Le JSON adjacent détaille **32 exigences prioritaires**, avec attribution, source historique et numéros de cas. **314 commits et 1 707 tests legacy sont inventoriés, pas tous portés ni reliés à une preuve de succès.** GPS réel, expiration de session, cartes cadeaux, no-show, âge et base FAQ exhaustive restent explicitement non validés ou absents. Ce rapport ne prétend pas couvrir tous les problèmes des six mois.

## Validation et coût

Suites locales Python 3.13 : main **1 975 tests passent / 2 ignorés**, PR intégrée **2 064 / 2**. Contrôles comparatifs : **18/18** côté PR. Ces suites se recouvrent, ne pas additionner les comptes.

Nouvelle comparaison : **1,06805 USD**. Cumul de toutes les campagnes : **40,37001 USD observés + 1 USD provisionné / 60 USD**, aucun appel en attente ; deux métriques tardives réintégrées. Sur les mêmes 155 tours par version : main **0,43807 USD**, PR **0,62998 USD**, soit environ +44 % sur cet échantillon (pas une prévision de facture de production). Les statuts techniques 139/155 ok sur main, 151/155 sur PR ne sont pas des scores métier.

Preuves privées locales : inputs hashés, réponses complètes, profils par tour, générations, reçus outils, caches, métriques et ledger rapproché. Aucun dialogue brut ni secret dans ce dépôt. Pas de fusion vers main, pas de déploiement. Ordre de revue : #123 puis harnais #121.
