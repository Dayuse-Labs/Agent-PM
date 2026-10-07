# Préservation des acquis de production — revue du 7 octobre 2026

Cette révision prolonge la [comparaison du 6 octobre](production-state-transfer-2026-10-06.md). Elle reste une proposition de migration à revoir, pas une autorisation de lancement. Les résultats du 6 octobre ne sont pas attribués au nouveau runtime.

## Ce qui a été repris et adapté

Le point de départ reste la production déployée `a08a7792ed95dedca6255b5c588a80a504dd6249`, et AgentB2C `main` à `07be07e447418c1b9b87fdd8b753b36a058a26b8`. L'inspection porte sur le câblage effectif des dépendances, les variables Railway, les traces Langfuse, les tests historiques et les retours QA, dont le ticket Dayuse [14707](https://gitlab.com/dayuse/dayuse/dayuse-com/-/work_items/14707).

Le legacy combine Postgres, Qdrant, un export de disponibilités, un profil Redis et un historique borné. Il utilise GPT‑5.2. AgentB2C conserve le concierge propriétaire du profil, les feuilles A2A sans stockage de session, les outils MCP et LiteLLM. Les tables de villes et les expressions régulières du legacy ne sont pas copiées. La reprise concerne les invariants métier et les responsabilités de l'état, pas l'import du moteur legacy.

| Acquis à préserver | Adaptation dans cette PR | Limite à vérifier dans les dialogues |
| --- | --- | --- |
| Le lieu confirmé survit aux raffinements | Identité fournisseur, pays, région, coordonnées et provenance persistés par le concierge ; invalidation lors d'un nouveau lieu ; coordonnées MCP imposées par le géocodeur | Un snapshot valide peut représenter un mauvais lieu initialement interprété. |
| Budget et horaires durables | Modifications structurées émises par le triage existant, contrôlées puis injectées dans les paramètres outils ; « moins cher » ne retire pas un plafond | La classification sémantique reste probabiliste ; conversion de devises non inventée. |
| Références à une liste réellement présentée | Une sélection sans shortlist ne déclenche pas une recherche ou réservation arbitraire ; reprise contextualisée des réponses courtes | Les longues séquences, négations et changements de but restent à noter au niveau conversation. |
| Identité d'un hôtel nommé | Identité issue du fournisseur transmise entre tours avec la ville du fournisseur | Une fiche d'identité ne devient pas une disponibilité confirmée. |
| Intention précise de recherche | Priorité prix/distance/note portée par le profil ; synthèse orientée vers la demande plutôt que la remise marketing | Tri sur la page reçue, pas optimum de l'inventaire complet ; rappel MCP non mesuré comme un défaut de raisonnement. |
| Géographie confirmée et homonymes | Catégories de POI du fournisseur, IATA, ville exacte et région ; pays du lieu vérifié prioritaire sur la locale du navigateur | Pas de catalogue ajouté ; une zone ou un lieu ambigu peut rester non résolu. |
| Produit de jour et preuves d'offre | Nuit non présentée comme satisfaite par une formule de jour ; heures et prix rattachés à la même offre ; alternatives annoncées | Éligibilité familiale, équipements, offre réservable et politiques demandent leurs propres preuves. |
| Dégradation honnête et reprise | Timeouts Redis ; coupe-circuit MCP alimenté uniquement par les résultats pertinents, sans prolongation par ses propres refus | Pas de nouveau cycle de retry ; reconnexion après redéploiement MCP à valider séparément. |

La configuration évaluée est [preservation-candidate.env.example](../../configs/preservation-candidate.env.example) : triage GPT‑4.1 mini, feuilles et synthèse GPT‑4o mini. Un essai entièrement GPT‑4.1 mini n'a pas montré un gain suffisant sur le petit lot de développement ; il n'est pas le profil retenu. Aucun appel de raisonnement supplémentaire n'a été ajouté à la structure habituelle.

## Provenance du corpus

Le snapshot frais arrêté le 6 octobre contient **30 713 lignes de logs et 186 766 événements**, avec pagination terminée et hashes conservés. Il remplace l'ancien export local de février à juillet comme source de sélection. Ces nombres ne sont pas des nombres de conversations uniques. Les 348 tours des 125 cas principaux ont tous été retrouvés dans les logs source ; ils s’étendent du **21 mars au 6 octobre 2026**. Les sessions aux préfixes de test explicites sont exclues. Le schéma exporté ne contient cependant pas de champ certifiant une origine client. Les cas sélectionnés portent encore `traffic=unclassified` : ils sont enregistrés dans le service de production, mais leur origine client versus QA n'est pas certifiée pour chaque séquence. L'échantillon ciblé ne mesure donc ni tout le trafic client, ni l'intégralité des six mois de comportements.

Les datasets Langfuse historiques du projet AgentB2C et les retours QA ont été lus séparément : leurs scores du mois d'août ne prouvent pas la qualité du runtime présent. Les exigences dérivées des réponses de l'ancien agent ne deviennent pas automatiquement une vérité métier.

## Préserver la mémoire des correctifs

La [PR du harnais #121](https://github.com/Dayuse-Labs/AgentB2C/pull/121) fournit une matrice de **32 exigences** reliées aux sources legacy, aux tickets et aux tests du candidat. Elle conserve aussi un index de **1 707 fonctions de test dans 116 fichiers** du SHA legacy. Ce recensement ne signifie pas que chaque comportement historique a déjà une équivalence validée dans AgentB2C.

La validation doit conserver ces trois niveaux séparés : tests de contrats et contre-exemples, séquences réelles complètes, puis cas réservés après sélection. Les faux positifs et les incidents ne sont pas transformés en réussite. Les nouvelles règles métier doivent d'abord devenir une attente explicite ; on ne modifie pas l'attente après avoir vu une réponse pour faire passer le test.

## Comparer malgré l'export et le MCP

La comparaison principale rejoue les messages utilisateur, dans l'ordre et avec des sessions neuves, sans réinjecter les anciennes réponses assistant. Locale, domaine et devise proviennent du contexte enregistré ; aucun GPS ni compte client n'est inventé. Les anciennes dates ne sont pas décalées silencieusement. La différence d'inventaire et de date interdit de conclure qu'un système est meilleur uniquement parce qu'il affiche davantage d'hôtels.

Un contrôle supplémentaire injecte le même instantané MCP fini dans deux adaptateurs : repository/cache pour le code legacy isolé, et serveur MCP local pour AgentB2C. Il contient 57 hôtels et 142 offres du 7 octobre, dans quatre zones. Prix EUR frais inclus, identité, coordonnées, horaires et échéances de réservation viennent du même document. Ce contrôle active l'export strict côté legacy et supprime les scores vectoriels ; il ne reproduit pas le classement Qdrant/Elasticsearch ni les équipements ou politiques non établis. Toute requête hors périmètre doit être signalée, pas interprétée comme une recherche vide valide.

Les parcours SAV sont exécutés sur un fournisseur de réservations fictif lorsque l'agent legacy pourrait appeler une action réelle. Le MCP du candidat ne possède pas la capacité d'annuler une réservation existante. Une explication FAQ correcte, une redirection vers le compte et une annulation exécutée sont trois résultats distincts.

## Protocole de revue

Le juge indépendant évalue contexte, suivi, pertinence, appui sur les faits, support et progression. Il reçoit les dialogues complets en ordre A/B masqué et doit citer les tours qui prouvent un échec ; « inconnu » reste un résultat permis. Sa calibration répète des cas dans les deux ordres, suivie d'une inspection des raisons. Ce juge aide la revue et ne donne jamais le feu vert de déploiement.

Les conversations, reçus MCP, traces et coûts détaillés restent dans le dossier privé. Seuls les agrégats et exigences sans dialogue brut sont versionnés. Les échecs de transport, itérations abandonnées et générations sans coût observable restent traçables. Une réserve explicite pour un appel non tarifé consomme le budget disponible, sans être présentée comme une dépense observée.

## Résultats du runtime final

Runtime figé **`1be89742ae3b013ef2531bfe3e3996528bfca664`**. Aucun changement applicatif depuis le début de cette passe ; les commits de publication suivants ne modifient que la documentation. Les 125 profils finaux du lot principal sont archivés avant expiration de Redis.

| Lot | Séquences exécutées | Tours par agent | Référence |
| --- | ---: | ---: | --- |
| Principal | 125 | 348 | Réponses du vrai service de production archivées le 6 octobre ; candidat rejoué le 7 |
| Cas réservés après sélection | 12 | 43 | 9 références directement en production (35 tours), 3 sur code isolé avec fournisseur SAV fictif (8 tours) |
| Inventaire commun | 4 | 14 | Code legacy isolé et serveur MCP local lisant le même instantané |
| SAV historique | 6 | 8 | Code legacy isolé et fournisseur fictif |
| Annulation synthétique | 1 | 4 | Réservation entièrement fictive |

Soit **148 exécutions de séquence / 417 tours candidats** ; les quatre séquences du contrôle commun sont reprises du lot principal, donc ce ne sont pas 148 conversations uniques. Les 12 cas réservés étaient exclus des lots antérieurs lors de leur sélection. Six ont été partiellement exécutés sur v12, invalidée par le coupe-circuit ; seules les corrections de résilience ont été ajoutées ensuite, sans adaptation aux réponses de ces cas. Le déploiement de production a été revérifié avant et après le lot frais : même SHA et même déploiement.

**Tests locaux : 1 877 passés, 1 ignoré ; Ruff, mypy (58 fichiers), garde-fous et contrôle de confidentialité verts. Harnais : 193 passés, 1 ignoré. Aucun nouvel appel regex.** Le lot principal termine techniquement 341 tours en `ok`, 7 en `degraded` ; `ok` ne signifie pas que la réponse est pertinente.

Sur les **24 critères géographiques** prédéfinis : candidat **16 conservés / 6 partiels / 2 échecs** ; référence de production archivée **17 / 5 / 2**. Il ne s'agit pas d'un score global. La Défense et Paris Bercy échouent sur le replay principal ; La Défense réussit dans le contrôle commun avec une autre structuration du lieu (Paris au lieu de Puteaux). Cette variabilité interdit de présenter le correctif comme stable sur toutes les formulations.

À inventaire commun, **107 couples prix/créneau legacy et 27 candidats** sont retrouvés dans le même instantané, sans discordance. Deux sondes au lendemain, sur le sixième tour de Milano, dépassent le périmètre d'un jour : la séquence Milano est exclue de l'agrégat du juge de ce contrôle. Le zéro EUR fournisseur reste présent dans l'instantané et sa validité commerciale n'est pas prouvée.

L'annulation synthétique ne réussit sur aucune branche : **zéro appel au fournisseur fictif, zéro `cancel_booking`**. Le legacy perd la référence initiale et la redemande ; le candidat reconnaît sa limite d'action. Ce résultat ne doit jamais être résumé comme une annulation testée avec succès.

### Le juge n'est pas validé comme classement de qualité

GPT‑4.1 a relu les 125 dialogues principaux, les 12 réservés et les 3 contrôles communs admissibles. Dix revues supplémentaires permutent A/B sur cinq cas : préférence stable 5/5, mais seulement 51/60 verdicts détaillés identiques. Trois contrôles de cohérence synthétiques et un contrôle de duplication de carte passent. Un premier contrôle de nombre de cartes était mal isolé car une carte dépassait le budget ; il reste archivé comme non interprétable.

Une contre-vérification sur un cas réservé montre surtout une erreur substantielle : le juge récompense la production lorsqu'elle transforme une faute du mot « moins cher » en lieu, malgré l'absence de ville/GPS. Il pénalise en parallèle une clarification légitime du candidat. **Ses classements et taux de critères sont donc exclus du verdict de qualité.** Les sorties restent des pistes de revue ; elles ne sont pas des annotations humaines de référence. Il faut corriger/calibrer ce juge sur des labels humains avant d'en faire une condition de mise en production, plutôt que modifier le produit pour optimiser un score trompeur.

### Bilan pour la review

Les gains démontrés incluent la reprise du coupe-circuit sous trafic continu (contre-exemple reproduit sur l'ancien runtime), le maintien du plafond à Westminster, le refus de sélectionner un hôtel absent de la shortlist, la séparation identité/disponibilité et la résolution de Gillingham. Ils ne suffisent pas à établir la parité avec la production.

Points encore bloquants pour une validation générale :

- La Défense, Paris Bercy et certains lieux composés restent non résolus ; des clarifications bouclent.
- Un hôtel nommé peut être conservé pendant deux tours puis perdu comme contrainte de recherche lors de l'ajout du budget (cas réservé Sheraton San Siro).
- Exclusions de zone, questions sur le quartier ou la capacité et priorités de proximité ne sont pas toujours correctement traitées ; des réponses restent centrées sur la promotion.
- Le garde de durée de trajet a un faux positif sur une demande italienne de séjour de trois heures. Ce risque introduit par le nouveau champ sémantique est explicite, malgré les tests de contrat verts.
- Des affirmations de respect d'un budget en dollars s'appuient encore sur des cartes EUR sans preuve de conversion ; les assertions d'adéquation familiale ou de moyen de paiement demandent une preuve spécifique.
- Le MCP FAQ renvoie des formulations divergentes sur le délai d'annulation (dernière minute / deux heures). Le dialogue doit gérer cette incertitude et le blocage client ; l'annulation d'une réservation existante reste une capacité absente du candidat.

**PR maintenue en draft : pas de recommandation de lancement, aucun merge ni déploiement.** La review humaine doit trancher les règles métier de source, puis verrouiller ces contre-exemples dans un jeu d'acceptation avant une nouvelle itération. On ne déduit pas « mieux que la prod » d'un plus grand nombre de cartes ou d'une suite technique verte.

### Coûts et traçabilité

Coût modèle observé cumulé : **37.60 USD**, plus **1.00 USD réservés** pour un appel expiré sans coût fournisseur observable. Engagement budgétaire : **38.60 / 60 USD** ; arrêt de nouveaux lots à 40 USD, réserve générale 20 USD. Itérations abandonnées, incidents et juge inclus ; hors Codex et infrastructure. Rapprochement final terminé, aucun lot en attente ; la provision d'appel non tarifé n'est ni effacée ni présentée comme une dépense certaine.

Les [agrégats versionnés](production-preservation-2026-10-07.json) ne contiennent aucun dialogue brut. Les rapports privés conservent toutes les réponses côte à côte, les identifiants de traces vérifiés, les reçus, les profils, les contrôles et les scripts de reproduction. Les passes v7–v13 restent disponibles avec leur statut, notamment v12 invalidée par le verrouillage MCP. Les résultats de ces itérations ne sont pas fusionnés avec ceux de ce runtime.

Pour reproduire : utiliser le SHA figé, le profil de modèles fourni et le harnais #121 ; restaurer les sources et scripts du checkpoint privé dans un environnement isolé ; employer des sessions neuves, conserver les dates et hashes d'entrée, vérifier le déploiement de référence, et ne jamais redémarrer automatiquement un manifeste déjà payé. L'absence de secrets dans les jobs live de CI signifie « non exécuté », même si le job technique termine vert.
