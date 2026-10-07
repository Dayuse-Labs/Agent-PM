# Mémoire et contraintes de production adaptées à AgentB2C

## Production effectivement inspectée

Le 6 octobre 2026, la configuration Railway et le déploiement actif ont été relus : service `agent-conversationnel-USA`, déploiement `2c2c30e4-2072-4e0a-b01c-8060f14b35bc`, code `a08a7792ed95dedca6255b5c588a80a504dd6249`. Aucun changement de configuration ni déploiement effectué.

La production utilise `gpt-5.2`, `VECTOR_SEARCH_TYPE=qdrant` et `LOCATION_RESOLVER_MODE=authoritative`. Railway expose aussi Postgres, Redis et `cron_maj_dispo` au même SHA applicatif. Les connexions Qdrant et Langfuse sont configurées. La présence de ces services ne prouve pas à elle seule la fraîcheur de chaque offre ; aucune parité d’inventaire avec le MCP de développement n’est présumée.

Le câblage de `SearchTool` combine le repository Postgres, Qdrant et `AvailabilityCache`, alimenté par un export S3 de rate plans. `cron_maj_dispo` déclenche `/sync-availability` ; le code prévoit aussi un rafraîchissement paresseux par worker (TTL par défaut 1 800 s). Point important vérifié dans la configuration active : **`AVAILABILITY_STRICT_EXPORT=false`**. Dans ce mode, si une formule ne possède pas de correspondance dans le cache dynamique, le moteur peut conserver la formule de base du repository. Le nombre de cartes de la prod n’est donc pas une preuve de disponibilité temps réel supérieure au MCP. Le présent audit ne déclenche pas de synchronisation manuelle. Un GET `/availability-stats` pendant le replay indique, pour le seul worker répondant, `source_date=2026-10-06`, 17 672 formules et 7 463 hôtels chargés ; ce constat ne prouve ni la fraîcheur de tous les workers ni la réservabilité de chaque formule.

Le chemin réellement câblé dans `src/api/dependencies.py` est `SyncRedisSessionStore`, avec TTL de session configuré à 3 600 secondes, 50 messages maximum conservés par défaut, connexions bornées à 2 secondes et lectures à 3 secondes. L’orchestrateur borne ensuite son historique à 10 messages. Le profil conserve séparément les préférences, les hôtels affichés et l’identité résolue du lieu : la mémoire utile ne dépend donc pas uniquement de l’historique injecté au modèle.

## Mécanismes repris

| Mécanisme de prod et source vérifiée | Adaptation dans la nouvelle architecture |
| --- | --- |
| `location_state.py:commit_resolved_location` stocke pays, région, identifiant fournisseur, coordonnées, provenance et version du lieu. `begin_location_transition` invalide les ancres d’une ancienne destination. | Snapshot géographique produit par le géocodeur, contrôlé sur son identifiant, son pays et ses coordonnées, et lié aux champs exacts de la demande. Ce contrôle de format/provenance ne prouve pas à lui seul que le fournisseur a trouvé le bon lieu. Le concierge le persiste dans son profil Redis ; une modification de ville, région ou zone l’invalide. |
| `SearchTool.committed_place_for_preserving_turn` réutilise l’identité déjà acceptée lorsqu’aucun nouveau lieu n’est demandé. | Sur `retain`, le callback du géocodeur réutilise le snapshot transmis par A2A. `search_offers` reçoit toujours les coordonnées contrôlées par le callback du tour. Aucun stockage ni accès Redis ajouté aux feuilles. |
| Le profil de production conserve les contraintes et leur provenance ; le resolver en mode authoritative est la source du lieu. | Le triage existant reçoit un résumé borné de l’état courant et produit des modifications budget/horaires avec une citation du message actuel. Ces modifications sont persistées avant l’appel distant, puis imposées aux paramètres MCP. Une extraction de la feuille ne peut pas les rétrograder en défaut flexible. |
| Les résultats de production distinguent les formules couvrantes et les alternatives ; la sélection se fait sur les offres disponibles. | Vérification du prix et des horaires de l’offre affichée, puis avertissement déterministe si une alternative ne respecte pas la demande. Les prix de deux formules ne sont pas combinés pour fabriquer une offre compatible. |
| Connexions Redis bornées dans le conteneur applicatif de production. | Timeouts de connexion et de lecture ajoutés au client Redis asynchrone du concierge, sans changer le TTL existant ni la politique de dégradation. |

Le fichier legacy `hotel_relevance_gate_v44.py` décrit un contrôle **shadow** : il n’est pas présenté ici comme un mécanisme de filtrage actif vérifié en production. Les tables de villes, regex et catalogues géographiques du legacy ne sont pas recopiés.

## Responsabilités conservées

Le concierge reste propriétaire du profil et du routage. Les feuilles sont stateless et échangent `profile_in` et les résultats vérifiés via A2A ; les outils restent accessibles via MCP. Mapbox fournit l’identité géographique. Les données MCP restent la source des offres, dates et prix. LiteLLM et les budgets de dépendances sont conservés.

Le triage est configuré séparément : `DAYUSE_MODEL_TRIAGE=gpt-4.1-mini` dans l’image du concierge. Une variable de déploiement explicite peut remplacer ce défaut ; en exécution locale hors Docker, exporter cette variable pour reproduire le profil évalué. Les feuilles et la synthèse restent sur `gpt-4o-mini` pendant le replay. Le diagnostic isolé sur 16 messages, à code et schéma identiques, a motivé ce choix : `gpt-4o-mini` perdait notamment la ville de repères connus, le budget associé à une heure et la suppression explicite du plafond. Les 16 appels `gpt-4.1-mini` mesurés restaient sous les 5 secondes du triage (le diagnostic lui-même autorisait 15 secondes pour mesurer sans masquer une éventuelle lenteur). Ce petit jeu de développement ne constitue pas une validation globale.

Aucune étape LLM supplémentaire. Le plafond du triage passe de 400 à 650 tokens pour les champs structurés supplémentaires ; le coût réel des générations est suivi dans le même ledger cumulatif plafonné à 60 USD. La limite ne garantit pas que le classifieur interprète chaque demande correctement : les replays mesurent cette limite.

## Séparer la qualité de l’agent de la qualité des données

La référence de production utilise l’export/index Qdrant. Le nouvel AgentB2C utilise le MCP dayuse-dev. Rejouer les mêmes messages ne rend **pas** ces sources identiques. Le replay live compare les deux systèmes complets ; il ne permet pas d’attribuer une différence de disponibilité, de prix ou de classement au seul code de l’agent.

| Comparaison | Données communes | Ce qu’elle mesure | Ce qu’elle ne prouve pas |
| --- | --- | --- | --- |
| Production actuelle ↔ PR en direct | Messages utilisateur et contexte locale/devise/domaine enregistrés | Comportement des systèmes complets, conservation des contraintes, contradictions avec leurs propres résultats | Rappel ou classement à inventaire égal ; parité de prix/disponibilité |
| AgentB2C main ↔ synthèse PR à faits figés | Profil, message, offres, modèle de synthèse | Effet du traitement des contraintes sur la réponse | Qualité du moteur legacy ou de la recherche MCP |
| Tests de contrats hors réseau | Identité de lieu, profil, enveloppes A2A, retours outils contrôlés | Invariants techniques et contre-exemples déterministes | Taux réel de réussite sémantique du modèle |

Trois niveaux de preuve sont distingués :

1. **Contrats et mémoire** : tests de profil persisté, DataParts A2A et callbacks MCP avec données contrôlées. Ils vérifient les modifications de lieu, les coordonnées possédées par le fournisseur et la conservation des contraintes après échec.
2. **Réponse sur faits identiques** : composant de synthèse d’AgentB2C `main` (`07be07e`) et PR alimentés par les mêmes quatre fixtures et le même modèle. Trois jeux de faits proviennent de réponses MCP archivées ; le quatrième applique explicitement un budget synthétique de 50 EUR aux mêmes offres. Le hash des entrées est identique entre variantes. Il s’agit d’une comparaison du composant `main`→PR, **pas** de l’ancien agent de production, ni de sa recherche. Les huit générations coûtent ensemble environ 0,00213 USD, inclus dans le ledger. La PR annonce le créneau non couvrant là où `main` omettait cet écart ; les deux contrôles compatibles ne déclenchent pas d’avertissement. Le dépassement de budget était déjà annoncé par `main` sur ce cas : pas de gain inventé sur ce point.
3. **Système complet** : conversations historiques contre la production actuelle et AgentB2C/MCP. Les erreurs de mémoire et les contradictions avec les propres résultats sont examinées indépendamment de la différence de stock. L’absence d’un hôtel côté MCP n’est pas une faute de l’agent à elle seule.

Exemple concret : sur Queens, la prod présente Hampton LaGuardia vers 7 km, tandis que le candidat demande un rayon de 3 km. Une sonde MCP indépendante retrouve bien cet hôtel au catalogue (`hotelId=9287`). Avec les mêmes filtres piscine/plafond 130 EUR et la date du 6 octobre, le serveur renvoie `total=0, results=[]` à 3 km puis `total=2, results=[]` à 10 km. Cela distingue présence au catalogue, rayon et offres effectivement retournées ; ni `total` ni la fiche d’identité ne prouvent une disponibilité réservable. Un second contrôle explicite au lendemain (7 octobre) renvoie zéro résultat à 3 km et deux hôtels avec offres à 10 km, dont Hampton LaGuardia. Il isole l’effet du rayon à date et filtres constants, sans établir une parité de stock historique. Ces sondes sont postérieures au replay, sans appel modèle.

Autre contrôle : une carte `ibis Milano Fiera` à 0 EUR provient bien d’une offre renvoyée par le MCP (`hotelId=8991`, `ratePlanId=33937`, 7 octobre, `priceEuro=0`, `priceEuroWithBookingFees=0`). Sa validité commerciale reste à confirmer ; ce zéro n’est pas un avantage de prix attribuable au nouvel agent.

Une mesure contrôlée de la pertinence de **l’ancien agent contre le nouveau** nécessiterait un inventaire canonique partagé et des adaptateurs validés vers les deux moteurs, avec prix, devises, offres et dates identiques. Ce dispositif n’est pas présenté comme réalisé dans cette PR. Les contrôles à faits figés ne prouvent donc aucune parité globale entre export et MCP.

## Vérification

Candidat figé **`1853c942b6de620f0a6283978b2ac5dfa9396fc6`**, comparé au code legacy **`a08a7792ed95dedca6255b5c588a80a504dd6249`**. Les 58 fichiers Python applicatifs et le Dockerfile du concierge sont identiques entre la copie de replay et la branche proposée ; les commits suivants ne contiennent que documentation/preuves. Le déploiement de référence a été vérifié avant et après le replay live.

| Lot | Conversations | Tours par agent |
| --- | ---: | ---: |
| live | 125 | 348 |
| support | 6 | 8 |
| cancellation | 1 | 4 |

`live` contient 125 conversations historiques distinctes, dont les 24 cas géographiques et les 22 conversations de validation relues intégralement. Les autres cas live ont les contrôles indépendants disponibles ; aucune affirmation que les 125 ont tous une notation humaine. `support` utilise le code legacy isolé et un fournisseur de réservations fictif ; `cancellation` est un scénario entièrement synthétique, sans possibilité d’action sur une réservation réelle. Le contrôle à faits identiques et le diagnostic triage sont des expériences séparées.

Les statuts techniques des 360 tours candidats (live + isolés) sont : `{'ok': 340, 'degraded': 20}`. `ok` signifie que le tour s’est terminé techniquement, pas que sa réponse est pertinente ; les dégradations restent dans les résultats.

**1 847 tests passent, 1 ignoré ; Ruff, mypy (58 fichiers), garde-fous et contrôle de syntaxe CI verts.** Vérification AST : aucun nouvel appel regex dans les 34 fichiers Python modifiés par rapport à `main`. La CI hébergée est relancée sur le commit publié ; un job live sans ses secrets signifie « non exécuté », même si le job technique est vert.

Coût modèle cumulé de cette campagne : **27.98 USD / 60 USD**, y compris premières versions, essais arrêtés, diagnostic triage, faits figés et erreurs. Les métriques tardives ont été rapprochées ; aucun coût en attente. Arrêt de dispatch prévu à 40 USD avec 20 USD de réserve. Hors Codex, infrastructure et campagne antérieure.

Sur les mêmes 24 critères géographiques historiques : **15 conservés / 6 partiels / 2 échecs / 1 non vérifié** pour le candidat ; **17 conservés / 5 partiels / 2 échecs** pour la production au même replay. Première version de la PR : 12 critères conservés. Il ne s’agit ni d’un taux de succès des conversations ni d’un effet causal isolé : modèles, horaires et inventaires diffèrent. Un résultat géographique conservé peut masquer un défaut métier, explicitement noté ci-dessous.

### Limites confirmées à conserver dans la review

- **Résolution sémantique du lieu** : Disneyland peut être accepté comme un commerce à Drancy ; Rennes sud comme Homebox Rennes Sud. Le snapshot évite les dérives ultérieures mais peut figer une mauvaise résolution initiale. Gillingham/Kent est correctement structuré puis échoue côté résolution fournisseur (rejet `geocode_echo_mismatch`).
- **Interprétation des corrections** : « cheaper alternatives » retire le plafond à Westminster dans la sortie du triage. La citation du message prouve son origine, pas sa sémantique. « past 5 pm » est normalisé en fin 17h. L’avertissement final ne corrige pas ces erreurs d’intention.
- **Pertinence et références de suivi** : Berkeley conserve le lieu mais répète les offres éloignées ; la synthèse privilégie souvent la remise. Annapolis puis une sélection ordinale sans shortlist valide déclenchent une proposition d’hôtel à St Louis. Des retours à l’accueil persistent sur JFK et la capacité de quatre personnes.
- **Produit et langues** : une demande de nuit à Singapour est encore présentée comme satisfaite par une offre de jour ; des chiffres seuls provoquent des réponses en français dans des conversations anglaises. Les dates historiques passées ne sont pas un test équitable de disponibilité et nécessitent une clarification dédiée.
- **FAQ / annulation** : le candidat conserve sa limite de capacité : aucune consultation ou annulation de réservation existante via les outils FAQ actuels. Les résultats du scénario synthétique et les appels réellement observés sont détaillés dans le rapport privé ; ne pas confondre bonne réponse FAQ et action métier réalisée.

Le dossier de preuves privé conserve les messages source, réponses des deux agents, traces Langfuse, appels MCP, hash des entrées, métriques et ledger. Les conversations brutes et les clés ne sont pas dans Git. [Agrégats publiables](production-state-transfer-2026-10-06.json). Les résultats de la première révision restent historiques dans [le premier rapport](search-intent-preservation-2026-10-06.md).

### Reproduire sans mélanger les preuves

1. Utiliser le runtime figé et les modèles ci-dessus ; repartir de sessions neuves et d’une base Redis isolée pour le candidat. Conserver le concierge propriétaire de Redis ; aucun état serveur ajouté aux feuilles.
2. Vérifier le SHA réellement déployé de la référence, la source MCP et le contexte enregistré. Rejouer chaque conversation en ordre, sans réinjecter les anciennes réponses assistant. Conserver les dates historiques sans prétendre reproduire le stock historique.
3. Réutiliser le harnais de la PR #121 et les scripts du checkpoint privé ; les runners refusent de relancer automatiquement un manifeste payé existant. Réserver le budget avant dispatch, rapprocher les coûts et vérifier les identifiants de session/trace.
4. Noter séparément perte d’intention, requête de recherche, couverture de source, et contradiction avec les faits reçus. Pour une comparaison causale legacy/MCP, construire ensuite l’inventaire canonique et ses adaptateurs : cette étape reste à réaliser.


Les tests ajoutés vérifient une reprise après échec, plusieurs tours après disparition du premier message de l’historique, l’invalidation sur changement de lieu, les coordonnées invalides, la preuve tirée du message actuel, les overrides de budget/horaires dans les vrais DataParts A2A et l’avertissement d’offre alternative. Les cas négatifs conservent les refus : pas de conversion de devise inventée et pas de fenêtre diurne construite à partir d’une plage nocturne inversée.

## Traces de diagnostic pour la review

Traces privées du replay candidat, accessibles avec les droits du projet Langfuse ; aucune publication publique des traces. Les identifiants de trace **et** de session ont été vérifiés avant attribution.

- [Queens : budget, rayon et résultats](https://langfuse-web-production-272b.up.railway.app/project/cms4gd0d20002nz029tuly62e/traces/0793401e83df3c398ac265bb7f24d2ff) — tour 3
- [South Plainfield : contrainte et origine](https://langfuse-web-production-272b.up.railway.app/project/cms4gd0d20002nz029tuly62e/traces/45c31ae6d53a6a1798aa8ce37f60b09b) — tour 3
- [Westminster : suppression du plafond](https://langfuse-web-production-272b.up.railway.app/project/cms4gd0d20002nz029tuly62e/traces/74aac0179ee1ba52cb72619d4b90055c) — tour 5
- [Gillingham : rejet du géocodeur](https://langfuse-web-production-272b.up.railway.app/project/cms4gd0d20002nz029tuly62e/traces/45344c3a658d815cb17f50c24cc169cf) — tour 2
- [Annapolis : sélection sans shortlist](https://langfuse-web-production-272b.up.railway.app/project/cms4gd0d20002nz029tuly62e/traces/8dd1aa94530da0e3b7482bc7ddaf03a1) — tour 5

Le scénario d’annulation isolé active explicitement `CS_MCP_ENABLED=true` et `CS_MCP_ALLOW_CANCEL=true` avec un fournisseur fictif. Résultat observé : deux consultations de réservation, deux lectures de politique, **zéro appel `cancel_booking`**. Le legacy répète la confirmation ; le candidat ne possède pas la capacité d’action. Aucun succès d’annulation de bout en bout n’est revendiqué.
