# Préservation des conversations de production — review AgentB2C

Cette branche porte des mécanismes de préservation du contexte observés dans le legacy. Elle ne remplace pas la validation produit du nouvel agent et ne donne pas de feu vert au lancement.

## Changements applicatifs

Le triage existant produit un changement de lieu structuré (`retain`, `replace`, `refine`), validé en code. La demande reste séparée de la ville et des coordonnées vérifiées. Elle est persistée avant l'appel de la feuille : une indisponibilité de recherche ne doit pas effacer le lieu demandé. Un changement de destination efface les anciens champs géographiques ; un affinement conserve les champs non modifiés.

La feuille reçoit les trois derniers messages utilisateur, bornés à 400 caractères chacun. Le géocodeur lit la demande structurée et le vrai message, puis possède les coordonnées envoyées à `search_offers`. Une recherche gérée par ce contrat exige un géocodage réussi au tour courant. Un nom de quartier doit correspondre au nom du résultat géographique, pas seulement à son adresse. Les codes d'aéroport utilisent les identifiants IATA du fournisseur ; aucun catalogue de villes ou d'aéroports n'est ajouté. Aucune nouvelle regex.

Les correctifs de suivi FAQ/SAV, de budget numérique reconnu par le triage et de couverture complète d'un séjour sont également inclus. Pour un séjour 10–17 h, une offre 09–17 h couvre la demande, une offre 10–16 h ne la couvre pas. Cela ne corrige pas encore toutes les voies de repli vers des offres alternatives, ni les offres couvrantes déjà exclues par le filtre amont du MCP. Une condition de réservation racontée par l'utilisateur reste une donnée non authentifiée ; elle ne devient pas une politique générale.

Aucun appel logique de modèle supplémentaire : le JSON de lieu enrichit le triage existant, dont la limite de sortie passe de 200 à 400 tokens. Le nombre réel de générations des feuilles et des retries reste compté séparément dans l'évaluation.

La CI ne réimporte plus automatiquement les datasets Langfuse, pour préserver les corrections humaines. Une configuration live absente produit un résumé « non exécuté », jamais une validation qualité implicite. La batterie live existante est conservée avec ses limites de mesure documentées.

## Référence et protocole

Les entrées proviennent de l’export historique vérifié (30 713 tours / 12 597 sessions), et les critères des correctifs legacy et [retours QA](https://gitlab.com/dayuse/dayuse/dayuse-com/-/work_items/14707). Les conversations sans marqueur de test restent classées « non classifiées », pas certifiées organiques. Le petit nombre de feedbacks Langfuse ne permet pas de calibrer un score général de satisfaction. La revue de cette campagne est effectuée par Codex, sans validation humaine des labels à ce stade.

- Code de départ AgentB2C : `main` à `07be07e447418c1b9b87fdd8b753b36a058a26b8`.
- Référence réelle : `https://ai.dayuse.com/v3/chat`, legacy `a08a7792ed95dedca6255b5c588a80a504dd6249`, déploiement `2c2c30e4-2072-4e0a-b01c-8060f14b35bc`, modèle `gpt-5.2`.
- Candidat figé pendant le replay : `032e9e385731236f6af2f9ed41dd4486e2e7e18e`, `gpt-4o-mini`, MCP dayuse-dev live, horloge réelle. Les changements ultérieurs de cette branche portent sur les tests, la CI et ce compte rendu ; les 54 fichiers Python applicatifs sont comparés octet par octet au runtime évalué.
- Harnais et critères indépendants : [PR #121](https://github.com/Dayuse-Labs/AgentB2C/pull/121), révision `65b74dd`. Les correctifs applicatifs qui y figuraient sont inclus ici ; éviter de les merger deux fois sans rebaser cette PR de harnais.
- 125 conversations live distinctes exécutées : les 24 cas géographiques, les 22 cas de validation live et les 80 cas initiaux, avec un doublon retiré ; 348 tours par agent.
- 6 conversations historiques SAV / 8 tours dans le code legacy isolé, avec fournisseur de réservation fictif ; 2 reproductions ciblées / 4 tours ; 1 annulation entièrement synthétique / 4 tours.
- Messages utilisateur et ordre conservés ; sessions et cookies neufs par conversation ; réponses générées par chaque agent utilisées pour son propre suivi. Aucun GPS, compte ou réponse historique inventé.
- Identités, hashes des entrées, ordre et couverture des tours contrôlés. Référence vérifiée avant et après les lots live. Les réponses sans cartes ne deviennent pas des succès automatiques ; budget et durée doivent s'appliquer à la même offre, sans conversion de devise supposée.
- Même ledger cumulatif à 60 USD, incluant les itérations et incidents de cette campagne. Arrêt des nouveaux appels à 40 USD observés avec réserve de 20 USD. Coûts réels des traces production et des générations locales, aucun juge payant. Codex, infrastructure et campagne antérieure exclus.

Les cas ont déjà été vus pendant le diagnostic : c'est une campagne de non-régression, pas un nouveau holdout. Les horaires, stocks, modèles et environnements diffèrent ; les comptes avant/après ne prouvent pas un effet causal ni une hausse de conversion. La production a elle-même des erreurs.

## Vérification locale

```sh
pytest -q
ruff check .
mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

1 828 tests passent, 1 test live ignoré. Ruff, mypy (54 fichiers) et garde-fous passent. YAML CI parsé et blocs shell validés avec `bash -n`. Aucun ajout d'appel regex dans les fichiers Python modifiés ; aucune clé ni conversation brute dans les fichiers suivis.

## Résultats du replay final

Campagne clôturée avant création de la PR : **134 exécutions de conversations appariées, 364 tours par agent**, dont 125 conversations / 348 tours contre la production réelle. Les autres lots sont distingués ci-dessous. Les coûts des générations locales tardives sont rapprochés après stabilisation ; aucun poste en attente dans le ledger.

| Lot | Conversations | Tours / agent | Coût référence | Coût candidat |
| --- | ---: | ---: | ---: | ---: |
| live | 125 | 348 | $6.601 | $0.903 |
| support | 6 | 8 | $0.072 | $0.007 |
| targeted | 2 | 4 | $0.118 | $0.012 |
| cancellation | 1 | 4 | $0.043 | $0.005 |

**Coût cumulé de la campagne : 17.10 USD / 60 USD**, incluant les itérations et incidents précédents. Le tableau ne porte que sur le replay final ; ses montants ne sont donc pas le total de campagne. Aucun juge LLM payant.

Sur les **22 cas géographiques communs déjà scorés**, le candidat précédent avait 6 critères conservés, 4 partiels, 10 échecs et 2 non vérifiés ; le candidat corrigé en a **12 conservés, 5 partiels et 5 échecs**. Sur les 24 cas finaux, le candidat obtient 12 conservés / 7 partiels / 5 échecs ; la production actuelle 15 conservés / 5 partiels / 3 échecs / 1 non vérifié. Le critère Halifax/GBP reste faible : une devise ne prouve pas une destination. Ces comptes portent sur le critère géographique de chaque ligne, pas sur la réussite intégrale des conversations.

Les 24 dialogues géographiques, les 22 de validation live et cinq parcours supplémentaires sont relus en entier, ainsi que les lots SAV, ciblés et synthétiques. Les autres dialogues live reçoivent les contrôles disponibles ; ils ne sont pas tous annotés qualitativement. Le [relevé agrégé](search-intent-preservation-2026-10-06.json) contient les contrôles indépendants sur les cartes, leurs échecs et les cas non scorables. Les pages locales privées donnent les deux dialogues côte à côte.

La clôture ne constitue **pas une parité produit**. Les défauts de quartier, suivi long, exclusion, budget, nuit et annulation ci-dessous restent ouverts. La PR est destinée à la review, sans remplacement de la production.


## Diagnostic confirmé dans Langfuse

Les traces du runtime final sont relues après contrôle de leur `id` et `sessionId` contre les sorties du replay. Les outils et le JSON de triage permettent de localiser les défauts restants :

- Queens est extrait dans `zone`, mais `kind=city` le supprime des arguments de géocodage. Le centroïde NYC remplace alors le quartier.
- Berkeley est d’abord résolu en Californie ; le budget seul est ensuite classé `replace`, ce qui efface l’ancrage avant de redemander Californie ou Illinois.
- South Plainfield conserve le lieu NJ dans le triage et les coordonnées résolues, mais un message excluant NYC fait passer le champ d’état hérité à NY. Un commerce homonyme est pris pour la zone.
- Strasbourg reste correctement transmis après « moins cher » ; la nouvelle résolution, sans identité géographique conservée, introduit un homonyme à Lille.
- Louise échoue sur la validation du nom puis épuise le budget outils. Le message d’indisponibilité masque cette cause applicative ; un contrôle de transport MCP séparé réussit.

Ces observations sont conservées comme défauts ouverts, pas présentées comme corrigées par cette branche. Les traces brutes restent dans les artefacts privés.

## Points à conserver ouverts lors de la review

Les traces montrent des gains sur Berlin-Mitte, La Défense, JFK, Milford CT et Heathrow Terminal 3. Elles montrent aussi des défauts persistants sur Queens, Manhattan après Newark, les exclusions géographiques, les équipements et les références à un hôtel déjà trouvé. Certains budgets explicites sont perdus ou élargis ; les offres alternatives ne sont pas toujours signalées comme ne couvrant pas les horaires. Des day rooms sont encore présentées à tort comme une nuit.

Le contrat de lieu reste dépendant de la bonne extraction sémantique : une zone contenant encore une préposition peut rester bloquée, et un commerce homonyme peut être pris pour un secteur (Rennes sud). Le replay Louise/Naamsepoort montre un refus du centroïde puis un message incorrectement présenté comme indisponibilité réseau, alors que le MCP est joignable. Ces cas restent bloquants pour une bascule.

Le scénario synthétique final confirme que le legacy consulte la réservation fictive et sa politique, mais redemande une confirmation après un oui explicite : aucun appel d’annulation n’a été exécuté dans ce replay. Ce parcours n’est donc validé de bout en bout pour aucun des deux agents.

La FAQ ne sait pas consulter ni annuler une réservation. Les sources MCP présentent des délais d'annulation contradictoires ; il faut les réconcilier et conserver la condition de l'offre comme référence. Le parcours transactionnel de l'ancien agent doit rester accessible ou être remplacé explicitement avant toute bascule.

Données brutes, traces, scripts d'exécution et tableaux de dialogue sont conservés dans les artefacts privés de la campagne ; ne pas les copier dans le dépôt. Les décisions de lancement nécessitent ensuite un jeu de conversations réellement tenu à l'écart, des annotations humaines sur les échecs ci-dessus et une vérification avec l'inventaire cible.
