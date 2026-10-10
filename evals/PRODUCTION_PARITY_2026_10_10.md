# Production parity — reprise du 10 octobre 2026 (v98)

**NO GO en attente du rejeu des correctifs et du comparatif large.**

Le MCP est de nouveau accessible. Le diagnostic candidat a terminé ses **26 parcours /
65 tours**, après le même lot sur la production actuelle `3093647`. Ces parcours
mélangent historiques, suivis synthétiques et régressions tirées des tests de prod ;
ils ne représentent pas 26 clients indépendants ni un échantillon aveugle du trafic.

Le contrôle des données affichées a joint **144 cartes** à leur reçu MCP exact
(hôtel, formule, date, créneau) : aucune divergence de prix, aucun reçu manquant
pour ces cartes et aucune offre expirée au moment de la réponse. Ce contrôle ne
prouve pas la pertinence géographique ni l'exhaustivité des résultats.

Le diagnostic a identifié deux défauts du candidat :

- `New York, Texas` était correctement extrait, puis l'État était remplacé par
  New York dans la résolution géographique. La correction donne priorité à
  l'état de destination détenu par le concierge et refuse un résultat dont la
  région n'est pas vérifiée par le fournisseur.
- Un nom hôtel extrait correctement était effacé par une décision « préserver
  la zone ». Le nom littéralement demandé reste maintenant utilisable pour lire
  les détails via MCP ; une question sur l'unique hôtel affiché retrouve cette
  identité pour ses informations générales comme pour ses horaires.

Ces corrections n'ajoutent ni regex, ni dictionnaire géographique, ni appel LLM.
Les régressions ciblées sont couvertes par des tests ; leur validation réelle sur
le MCP est en cours. Ne pas confondre correction de la cause et succès déjà rejoué.

Les points encore ouverts comprennent les deux séjours avec dates et horaires
associés, le suivi après une demande de semaine flexible, et les écarts de couverture
entre l'export de production et le MCP. La FAQ/SAV reste hors de cette phase.
La comparaison conserve les différences de configuration : production GPT-5.2,
candidat triage GPT-5.2 / recherche 4o-mini / synthèse GPT-5.2 ; la configuration
B2C Railway utilise encore un triage 4o-mini. Aucun gain n'est attribué au seul modèle.

Budget : **2,9178 USD** pour les deux bras du dernier diagnostic ; cumul
**152,2733 USD** provisions incluses, plafond **200 USD**, réserve **0,50 USD**.
Le passage large est préparé sur 100 parcours / 280 tours par bras, avec plafond
propre de 20 USD et suivi comptable au fil des conversations. Pas encore exécuté.

La CI GitHub du dernier head publié n'a pas démarré pour cause de facturation du
compte. Aucun merge, déploiement ou changement Railway. La PR reste en brouillon.

---

## Archive : état avant la reconnexion MCP

# Production parity — 10 octobre 2026 (v97)

**NO GO : nouvelle référence de production exécutée, candidat encore bloqué par la connexion MCP.**
La référence actuelle est `3093647`, déployée le 9 octobre à 18:31 UTC. Les six
services/environnements Railway ont été relus avant et après le passage : aucun
changement de configuration ou de déploiement. Main B2C reste `cbe88b9`.
Le candidat testé prochainement est `869faf4`, dont les 80 fichiers runtime sont
identiques à `6a5a221`. Aucun changement fonctionnel dans cette livraison v97.

## Exécution et coût

- **Prod : 26 parcours, 65 tours, 65 traces Langfuse tarifées**, sessions isolées,
  tours séquentiels, aucun rejeu automatique. Coût supplémentaire **1.6182 USD**.
- **Candidat : 0 parcours exécuté.** Initialisation MCP en expiration de connexion
  avant authentification, avec URL et jeton identiques à la configuration Railway.
  Le contrôle préalable a arrêté le lancement avant tout appel modèle candidat.
- Budget supplémentaire autorisé : 50 EUR ; sous-plafond prudent de 50 USD ajouté.
  Plafond cumulé 200 USD ; total comptabilisé **150.9737 USD**, dont 7,10 provisionnés
  conservés. Réserve 0,50 USD ; reste disponible **48.5263 USD**.
  Ledger soldé, aucun batch payant actif à la clôture du passage.

## Résultats de la référence

Revue manuelle non aveugle des 26 conversations : **5 B, 15 C, 5 D, 1 non notée**.
A = parfait, B = mineur, C = significatif, D = majeur, F = critique. Ce lot est
volontairement concentré sur les régressions : ce n'est pas une estimation du taux
d'erreur du trafic de production. Ce n'est pas non plus un comparatif apparié terminé.
Il contient 5 régressions connues, 3 conversations récentes et 18 contrôles
synthétiques dérivés des derniers correctifs de production ; pas 26 conversations
clients historiques. Deux suivis synthétiques sont inclus dans les régressions.

| Comportement | Observation vérifiée dans le rejeu actuel |
|---|---|
| Réponse numérique à une question géographique | Le code déclare aussi un budget explicite, contrairement au sens de la réponse. Langfuse indique que cette valeur ne vient pas de l'extraction LLM. |
| Élargissement autour de Milan | Un homonyme près de Spoleto est géocodé ; le métro devient Rome. Une validation géographique négative ne bloque pas la recherche servie. |
| Élargissement depuis un GPS canadien | La recherche passe de l'Ontario à Halifax, puis se corrige après protestation. |
| Demande d'une autre option à Madrid | Le suivi est interprété comme un autre lieu ; les budgets sont inventés puis augmentés sans demande. |
| Prix pour un horaire précis | 11 annonces ciblées sont contredites par leurs propres créneaux structurés. Exemple : 160,30 USD annoncé pour une sortie à 19 h, contre 179,20 USD pour le créneau couvrant cette heure. Ce sous-échantillon a été sélectionné pour diagnostic. |
| Hôtel nommé | Un hôtel exact dans l'Ohio est joint à des cartes de New York ; une autre recherche limitée à Los Angeles renvoie Boston. Les appels outils confirment les incohérences de contexte et de filtrage. |
| Hôtel ajouté dans le texte | Le guard détecte un hôtel fantôme mais sa proposition tarifée reste dans la réponse, accompagnée d'une mention d'absence des résultats. |
| Correctifs préservés en prod | Les neuf codes aéroport restent dans la bonne zone au suivi ; le cas New York au Texas ne bascule pas vers New York City ; l'identité exacte Hilton Atlanta et les créneaux Hampton O'Hare sont récupérés. Cela ne valide pas tous leurs prix/équipements. |

Six traces complètes (111 observations) ont été lues pour diagnostiquer les causes.
Les données brutes, coordonnées, sessions, clés et transcriptions restent hors Git.
La piscine ET le spa sont bien transmis en filtres obligatoires, mais l'inclusion
des accès dans une offre chambre n'est pas établie : cas non noté, pas faux succès.
Les séjours à deux dates et la demande de semaine suivante sont non vérifiables
sur les cartes legacy non datées ; les contrôles date restent `skipped`.
Les différences export/RevOps contre MCP préproduction ne sont pas automatiquement
attribuées à l'agent. Les incohérences internes prix/créneau, ville et budget sont
évaluables indépendamment de cette différence d'inventaire.

## Suite exacte

1. Rétablir la connexion MCP, rejouer les mêmes 26 parcours sur le candidat figé,
   puis joindre les cartes aux offres MCP réelles. Ne pas relancer la prod déjà
   terminée si version, horloge utile et inventaire restent comparables.
2. Corriger les défauts réellement observés sur le candidat en lots cohérents,
   sans regex ni dictionnaire géographique ajouté ; rejouer les cas en échec.
3. Passer les 100 autres parcours / 280 tours sur les deux agents actuels.
4. Ajouter 3 conversations de ce matin / 16 tours, messages figés avant réponse
   candidat, et 6 objectifs adaptatifs / 48 tours maximum au total sur les deux
   agents. Ces objectifs sont préparés, pas exécutés ; leur runner adaptatif reste
   à implémenter. Contextes natifs absents explicitement signalés, jamais inventés.
5. Challenger 4o-mini par une ablation contrôlée si les traces candidat montrent
   une limite de compréhension. La prod GPT-5.2 échoue aussi quand les champs ou
   résultats invalides ne sont pas bloqués : le modèle seul ne tranche pas cela.

Le candidat utilise triage5.2 / recherche4o-mini / synthèse5.2 ; le B2C déployé
utilise triage4o-mini. Le gain code+configuration ne doit pas être présenté comme
un effet du modèle seul. FAQ/SAV restent en phase 2.
Dernière validation runtime inchangée : 3 110 tests passants, 1 skip ; 87 tests
d'évaluation liés passants. Aucun nouveau test runtime n'est revendiqué ici.
La CI du dernier head reste bloquée par la facturation GitHub avant exécution.
Aucun merge, déploiement, changement Railway ni opération client.
