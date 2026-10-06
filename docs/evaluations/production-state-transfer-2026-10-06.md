# Mémoire et contraintes de production adaptées à AgentB2C

## Production effectivement inspectée

Le 6 octobre 2026, la configuration Railway et le déploiement actif ont été relus : service `agent-conversationnel-USA`, déploiement `2c2c30e4-2072-4e0a-b01c-8060f14b35bc`, code `a08a7792ed95dedca6255b5c588a80a504dd6249`. Aucun changement de configuration ni déploiement effectué.

La production utilise `gpt-5.2`, `VECTOR_SEARCH_TYPE=qdrant` et `LOCATION_RESOLVER_MODE=authoritative`. Railway expose aussi Postgres, Redis et `cron_maj_dispo` au même SHA applicatif. Les connexions Qdrant et Langfuse sont configurées. La présence de ces services ne prouve pas à elle seule la fraîcheur de chaque offre ; aucune parité d’inventaire avec le MCP de développement n’est présumée.

Le chemin réellement câblé dans `src/api/dependencies.py` est `SyncRedisSessionStore`, avec TTL de session configuré à 3 600 secondes, 50 messages maximum conservés par défaut, connexions bornées à 2 secondes et lectures à 3 secondes. L’orchestrateur borne ensuite son historique à 10 messages. Le profil conserve séparément les préférences, les hôtels affichés et l’identité résolue du lieu : la mémoire utile ne dépend donc pas uniquement de l’historique injecté au modèle.

## Mécanismes repris

| Mécanisme de prod et source vérifiée | Adaptation dans la nouvelle architecture |
| --- | --- |
| `location_state.py:commit_resolved_location` stocke pays, région, identifiant fournisseur, coordonnées, provenance et version du lieu. `begin_location_transition` invalide les ancres d’une ancienne destination. | Snapshot géographique produit par le géocodeur, validé et lié aux champs exacts de la demande. Le concierge le persiste dans son profil Redis ; une modification de ville, région ou zone l’invalide. |
| `SearchTool.committed_place_for_preserving_turn` réutilise l’identité déjà acceptée lorsqu’aucun nouveau lieu n’est demandé. | Sur `retain`, le callback du géocodeur réutilise le snapshot transmis par A2A. `search_offers` reçoit toujours les coordonnées contrôlées par le callback du tour. Aucun stockage ni accès Redis ajouté aux feuilles. |
| Le profil de production conserve les contraintes et leur provenance ; le resolver en mode authoritative est la source du lieu. | Le triage existant reçoit un résumé borné de l’état courant et produit des modifications budget/horaires avec une citation du message actuel. Ces modifications sont persistées avant l’appel distant, puis imposées aux paramètres MCP. Une extraction de la feuille ne peut pas les rétrograder en défaut flexible. |
| Les résultats de production distinguent les formules couvrantes et les alternatives ; la sélection se fait sur les offres disponibles. | Vérification du prix et des horaires de l’offre affichée, puis avertissement déterministe si une alternative ne respecte pas la demande. Les prix de deux formules ne sont pas combinés pour fabriquer une offre compatible. |
| Connexions Redis bornées dans le conteneur applicatif de production. | Timeouts de connexion et de lecture ajoutés au client Redis asynchrone du concierge, sans changer le TTL existant ni la politique de dégradation. |

Le fichier legacy `hotel_relevance_gate_v44.py` décrit un contrôle **shadow** : il n’est pas présenté ici comme un mécanisme de filtrage actif vérifié en production. Les tables de villes, regex et catalogues géographiques du legacy ne sont pas recopiés.

## Responsabilités conservées

Le concierge reste propriétaire du profil et du routage. Les feuilles sont stateless et échangent `profile_in` et les résultats vérifiés via A2A ; les outils restent accessibles via MCP. Mapbox fournit l’identité géographique. Les données MCP restent la source des offres, dates et prix. LiteLLM et les budgets de dépendances sont conservés.

Aucune étape LLM supplémentaire. Le plafond du triage passe de 400 à 650 tokens pour les champs structurés supplémentaires ; le coût réel des générations est suivi dans le même ledger cumulatif plafonné à 60 USD. La limite ne garantit pas que le classifieur interprète chaque demande correctement : les replays mesurent cette limite.

## Vérification

Résultats du nouveau replay à compléter après exécution sur un commit figé. Les résultats de la première version restent disponibles dans `search-intent-preservation-2026-10-06.md` et ne sont pas attribués à cette révision.

Les tests ajoutés vérifient une reprise après échec, plusieurs tours après disparition du premier message de l’historique, l’invalidation sur changement de lieu, les coordonnées invalides, la preuve tirée du message actuel, les overrides de budget/horaires dans les vrais DataParts A2A et l’avertissement d’offre alternative. Les cas négatifs conservent les refus : pas de conversion de devise inventée et pas de fenêtre diurne construite à partir d’une plage nocturne inversée.
