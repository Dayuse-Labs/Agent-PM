# Contrôle de migration à inventaire commun

Le replay sur `https://ai.dayuse.com/v3/chat` conserve la valeur de la production réelle : son code, ses six mois de conversations, Postgres/Qdrant et son export de disponibilités. Il ne permet pas d’attribuer un hôtel manquant au raisonnement du nouvel agent : les données et le classement diffèrent du MCP.

`common_inventory.py` fournit donc un deuxième contrôle, volontairement borné. Un instantané réel MCP est lu par deux adaptateurs : repository + cache de disponibilités du legacy, et serveur MCP local pour AgentB2C. Les identités, coordonnées, prix EUR frais inclus, heures et échéances viennent du même document immuable. Le cache legacy indique explicitement indisponible après l’échéance, et le serveur MCP applique la même règle. Les annulations, emails, bases de production et paiements restent déconnectés.

Le contrôle couvre un catalogue fini, un jour et des conversations sans changement de date. Il ne reconstitue pas Qdrant, le tri Elasticsearch, les scores de pertinence, les équipements absents, les notes ou les règles commerciales complètes. Une requête hors périmètre produit une erreur explicite et doit être exclue d’une conclusion de parité. Aucun stock global ni parité complète de recherche n’est revendiqué.

Pour le serveur local, avec des fichiers privés récupérés depuis les preuves de campagne :

```sh
python -m evals.common_inventory_server \
  --snapshot baseline/private/snapshot.json \
  --catalog baseline/private/catalog.json \
  --receipts baseline/private/control-receipts.jsonl
```

Le serveur écoute uniquement sur `127.0.0.1`. La configuration candidate pointe `MCP_B2C_URL` sur `http://127.0.0.1:8378/mcp` et utilise un Redis isolé. Dans le conteneur de dépendances du commit legacy évalué, injecter `LegacyRepository`, `LegacyAvailability` et `NoVectorEvidence`; activer l’export strict pour ce contrôle. Ce dernier réglage et l’absence de scores vectoriels sont des différences expérimentales à mentionner, pas des paramètres du service réellement déployé.

Le juge de `conversation_judge.py` complète les vérifications programmatiques : dialogues complets, ordre A/B masqué, critères explicites, catégories inconnu/non applicable. Il ne récompense pas un nombre de cartes plus élevé et n’invente pas les offres historiques manquantes. Sa calibration compare deux ordres de présentation sur les mêmes sorties, puis nécessite une revue humaine de ses raisons. Aucun résultat du juge ne déclenche un déploiement.

`preservation_transfer_map.json` relie les 32 exigences auditées à leurs preuves et à leurs limites. `legacy_regression_index.json` conserve les noms de 1 707 tests dans 116 fichiers de la production figée. Un test indexé n’est pas automatiquement un comportement porté.

Méthode inspirée de [Automating eval design and hillclimbing](https://claude.dev/blog/automating-eval-design-and-hillclimbing/) : vrais parcours, contrôles négatifs, test séparé, vérification du juge et coûts cumulés. Nous conservons aussi les itérations abandonnées et les incidents d’infrastructure, au lieu de les compter comme des réussites.

La comptabilité peut réserver explicitement 1 USD pour une génération échouée sans coût fournisseur observable. Les clés `unpriced-reserve:` consomment le plafond de dispatch et sont rapportées séparément des dépenses observées ; un timeout ne devient jamais un coût nul. Les réserves ne sont retirées qu’après preuve de facturation.
