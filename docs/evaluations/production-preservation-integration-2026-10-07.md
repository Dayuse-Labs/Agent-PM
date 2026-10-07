# Préservation de production — intégration du main courant, 7 octobre 2026

**Draft pour review ; pas de validation de lancement.** Les suites techniques passent, mais des défauts métier persistent. La campagne complète est terminée sur le runtime `40dd0c626069d773f7d7b099340eafea37d28ccb`, intégrant main `9b2ec69`. Les commits ultérieurs ne changent que la documentation. PR applicative #123, puis harnais #121 empilé sur sa branche avec un code applicatif identique.

## Ce qui est proposé

Le concierge garde dans Redis les demandes géographiques, les résolutions vérifiées, le budget, les horaires, la priorité et le contexte de shortlist. Les feuilles restent stateless via A2A ; recherche/FAQ restent derrière MCP. Modifications de contraintes structurées, protection du plafond sur « moins cher », identité hôtel séparée de disponibilité, limites honnêtes sur la nuit et le trajet, reprise du coupe-circuit sans faux incident sur un refus local. Aucun nouvel appel regex dans notre diff par rapport au main intégré.

Les apports récents de l’équipe sont conservés : dates demandées/servies, règle horaire du site (arrondi à l’heure la plus proche), moments de journée souples, repli de synthèse, erreurs MCP distinguées, devise sur demande, états vides citant les filtres exécutés et « Voir tout ». Les anciens oracles minute par minute restent distincts de cette règle produit, sans être réécrits pour embellir un score.

## Validation

- Application : **2 058 tests passent, 1 ignoré** ; Ruff, mypy (65 fichiers), guardrails et contrôle de confidentialité verts.
- Branche du harnais : **2 212 tests passent, 1 ignoré**, incluant ceux de l’application ; suites à ne pas additionner. Mêmes contrôles statiques verts.
- 125 conversations enregistrées dans le service de production de mars à octobre : **348 tours candidats**. Références réelles archivées du 6 octobre.
- 12 cas complémentaires déjà vus en v14 : **43 tours** ; neuf références de prod réelle et trois de code legacy isolé. Ce n’est plus un holdout indépendant.
- 4 contrôles d’inventaire : **14 tours** ; 6 SAV historiques isolés : **8 tours** ; 1 annulation entièrement fictive : **4 tours**.
- Total : **148 exécutions de séquence / 417 tours candidats**. Les quatre contrôles communs reprennent des cas du lot principal ; ce ne sont pas 148 conversations uniques.
- Géographie : **18 critères conservés, 5 partiels, 1 échec**, sur 24 séquences/72 tours relus. Revue Codex par critère, pas score global ni annotation humaine indépendante.
- Coût cumulé : **39.30 USD observés + 1 USD provisionnés** pour appels expirés non tarifés, plafond utilisateur **60 USD**. Itérations, incidents et juge antérieur inclus. Seuil de nouveaux lots ajusté à 42 USD pour l’intégration imprévue de main, réserve 18 USD ; aucun compteur remis à zéro, aucun lot en attente. Hors Codex et infrastructure.

Les jobs CI techniques ont passé sur les commits d’intégration. Les étapes live GitHub sont explicitement non exécutées faute de secrets ; les résultats ci-dessus viennent du harnais local avec traces. Consulter les checks du dernier commit publié pour son état exact.

## Défauts encore à traiter

1. **Corrections géographiques et clarifications.** La Défense et Paris Bercy répondent dans ce passage, mais le parcours avec faute initiale puis Courbevoie/La Défense reste bloqué. Langfuse montre une zone à la fois renseignée et demandée à effacer : le validateur rejette la correction entière et l’ancienne zone persiste. Rennes sud, Halton/Peel, Disneyland et Brooklyn restent fragiles. Les différences entre passages ne prouvent pas une amélioration causale.
2. **Budget et devise.** Le triage peut comprendre le nouveau montant et l’étiqueter USD ; le parseur le refuse car le filtre MCP est EUR. L’ancien plafond reste alors actif sans explication. À Paramus, un prix horaire est aussi pris pour un plafond total. Ne jamais « corriger » cela par une conversion inventée : il faut conserver la demande et traiter explicitement l’écart de devise.
3. **Pertinence et suivi.** À Milano, Langfuse confirme une durée de quelques heures transformée par la feuille en après-demain, puis conservée ; la date n’est pas fiable dans ce parcours. Paiement en espèces répondu comme une recherche vide, recommandations promotionnelles au lieu du quartier/de la proximité demandée, exclusions de zone et questions de capacité. Les faits des cartes, la qualité de la réponse et l’exhaustivité du catalogue doivent être évalués séparément.
4. **Réservation existante.** Aucune capacité d’annulation de bout en bout démontrée ; le scénario est entièrement fictif et le candidat ne dispose pas du parcours fournisseur nécessaire. Aucun appel sur réservation réelle.

Les dialogues, profils et appels outils du passage v15 sont conservés. La revue privée détaille aussi les longs suivis et les compléments SAV ; elle ne transforme pas une réponse techniquement `ok` en succès métier.

## Comparaison équitable et limites

La référence active reste le legacy `a08a7792`, déploiement Railway `2c2c30e4-2072-4e0a-b01c-8060f14b35bc`, revérifié pendant ce passage. Modèle GPT‑5.2, Postgres/Qdrant et disponibilité via export S3, `AVAILABILITY_STRICT_EXPORT=false`. Le candidat utilise triage GPT‑4.1 mini, feuilles/synthèse GPT‑4o mini et MCP dev. Le code de production n’utilise donc pas le vrai MCP hôtelier : aucune attribution globale au seul code à partir de ces sources/modèles différents.

Le contrôle complémentaire donne aux deux architectures le même instantané fini : 57 hôtels, 142 offres, mêmes identités, EUR, créneaux et échéances. Les prix/créneaux affichés sont rapprochés du snapshot (détail dans le JSON). La référence v14 est archivée et le candidat v15 passe plus tard, sans horloge figée : certaines échéances peuvent donc avoir expiré. Ce contrôle vérifie les faits des offres, pas un gain causal de disponibilité. Il ne reproduit pas le classement Qdrant/Elasticsearch, toutes les capacités ou tous les jours. Les requêtes hors jour capturé sont non comparables, jamais assimilées à un stock réel nul.

Les tours utilisateurs sont rejoués tels qu’enregistrés, avec sessions isolées et hashes exacts ; certaines références ordinales dépendent de la liste historique et exigent de juger la cohérence du nouveau dialogue. Les préfixes de test explicites sont exclus mais l’origine client versus QA n’est pas certifiée pour chaque enregistrement. Les nouveaux résultats sont comparés aux références archivées, sans les refacturer.

Le juge GPT‑4.1 de v14 est **exclu du classement de qualité** : un contre-exemple le montre récompensant une localisation inventée par la production. Aucun nouveau juge payé en v15 ; pas de taux global annoncé comme fiable. La prod peut elle-même se tromper.

## Préserver la connaissance

Le harnais #121 conserve 32 exigences liées aux sources, un registre géographique, la couverture FAQ/SAV, et un index de 1 707 tests legacy dans 116 fichiers. L’index n’est pas une déclaration que tous sont portés. Les données brutes, reçus, traces, replays invalidés et scripts de reproduction sont sauvegardés dans le checkpoint privé ; jamais dans Git. Les résultats v14 demeurent dans leur document historique.

Ordre de review : **#123, puis #121** (base de #121 = branche de #123). Aucune fusion vers main ni déploiement effectués ; revue métier/humaine nécessaire.
