# Évaluation recherche avant remplacement de la production — 9 octobre 2026

**Pas de GO remplacement. PR 134 en draft pour revue technique.**
Runtime évalué `68324266a50cbd6f8c1c39e868f337d856ed59a1` (v62), main
`cbe88b9` fetchée et inchangée. FAQ, annulations et SAV restent en phase 2.
Des modifications FAQ antérieures existent dans le diff cumulé : le verdict
recherche ne les valide pas. Aucun ajout FAQ, regex ou phase modèle dans v62.

## Rejeu complet

58 conversations, 163 réponses, toutes relues avec cartes, état et traces.
Les entrées sont identiques à v61 ; 70 empreintes source vérifiées avant/après.

| Cohorte | A | B | C | D/F | Non notés |
|---|---:|---:|---:|---:|---:|
| 56 historiques v61 | 7 | 20 | 23 | 0 | 6 |
| Les mêmes 56 en v62 | 10 | 19 | 21 | 0 | 6 |
| 2 sessions SQL récentes v62 | 0 | 0 | 2 | 0 | 0 |
| Total v62 | 10 | 19 | 23 | 0 | 6 |

A = satisfaisant ; B = mineur ; C = significatif ; D = majeur ; F = critique.
Revue Codex, pas revue humaine indépendante. Les 56 historiques comprennent
47 parcours référencés SQL (mai–octobre) et 9 contrôles synthétiques. Les deux
sessions récentes ont été rapprochées de SQL et Langfuse avant v61 ; elles sont
exposées, pas un holdout aveugle. Aucun contexte navigateur manquant inventé.
Les suites conditionnelles incohérentes ne sont pas des succès. Philadelphie
récente est C sur une dernière demande autonome et une affirmation de jacuzzi
privé non prouvée ; le suivi « another one » reste non comparable.

## Ce que le lot améliore, et ce qu'il ne résout pas

Le concierge conserve les sous-zones non résolues lorsque le triage fournit
explicitement une précision de ville. Le fournisseur doit encore prouver
l'appartenance. L'orchestrateur indique les nouvelles cartes de pagination ;
la synthèse reçoit la couverture des bornes horaires partielles, le prix carte
et le total avec frais, et distingue les autres formules de la carte choisie.
LiteLLM, A2A, feuilles stateless et profil Redis restent l'architecture utilisée.

Gains observés : trois pages Paris = 15 hôtels distincts correctement annoncés ;
une offre finissant 23h n'oblige plus le client à rester après son départ 20h ;
USD 126 hors frais / 131 avec frais et détail Aloft 139 / 148 sont expliqués ;
Kimpton et Biltmore distinguent formule affichée et autres créneaux vérifiés.

Recul observé : 23rd Street est perdu après New York, alors que v61 le conservait.
Rio reste C : le triage omet location_intent au deuxième tour et la conservation
ne s'active pas. Le contre-factuel hors réseau avec action refine ne prouvait
pas son émission par le modèle. Milano traite encore « dintorni » comme sous-zone.
La Quinta devient une ville, Halm reste perdu, LAX/ZIP et plusieurs périmètres
restent fragiles. Bronx/Queens apparaissent avant accord sous demande Manhattan.
Budgets nus, critiques ironiques et équipements privés ne sont pas fiabilisés.
Le total avec frais peut encore manquer d'explication sur les recherches vides.

## Contrôles factuels et limites

260 cartes rapprochées de l'identité hôtel, UUID d'offre, date et créneau du
même reçu MCP : zéro jointure manquante, prix carte divergent, carte expirée
ou dépassement de plafond vérifiable. 236 distances correspondent à l'origine
stockée : ceci ne prouve ni le bon point géographique ni un trajet à pied/voiture.
Les capacités renseignées satisfont les demandes ; une carte détail n'en fournit
pas. Deux offres 10h30 pour une demande 10h restent admises par la règle site
en heures entières, sans explication précise. Pas de garantie à la minute.
Piscine Londres incluse dans les cinq offres, baignoire HK filtrée au scope
chambre, huit créneaux Biltmore et piscine extérieure Kimpton vérifiés dans les
reçus. Red Roof Classic King Room ne prouve pas un jacuzzi privé : la description
mentionne seulement un hot tub dans les installations de l'hôtel.

2726 tests passent, 1 ignoré ; ruff, mypy (70 fichiers), guardrails verts.
Les tests et quatre contre-factuels locaux n'ont pas remplacé le rejeu réel.
522 appels modèle physiques : triage 4.1-mini (163), recherche/FAQ 4o-mini (221),
synthèse 5.2 (138), aucune erreur. Ce n'est pas un comparatif causal de modèles.
Changer seulement 4o-mini ne résout pas les omissions du triage ou la restitution.

Comparaison descriptive avec la prod legacy enregistrée v55 (export/Qdrant),
les réponses SQL récentes et v61. MCP préproduction, reflet de prod selon l'équipe,
mais dates/inventaire et mécanismes de recherche diffèrent. Pas de nouveau
rejeu simultané de toute la prod, ni supériorité statistique revendiquée.

## Coût et publication

Rejeu v62 : **1,56882295 USD**. Cumul conservateur **108,97310628 / 110 USD**,
dont **6,10 USD de provisions inconnues**, réserve interne 0,50 USD.
Deux provisions startup (2 USD) levées seulement après preuve de refus de
connexion à la fiche A2A avant toute invocation feuille ; cinq triages déjà
comptés conservés. Les timeouts et autres coûts inconnus restent provisionnés.
Aucun coût tardif ni lot en attente après réconciliation ; services locaux arrêtés.
Le solde ne finance pas une nouvelle campagne complète ; aucune autorisation
supplémentaire déduite. Aucun merge, déploiement, réservation ou écriture Railway.

Preuves privées hors Git : batch-v62 et remote-batch-search-v62, rapport HTML
comparant prod/v61/v62, chaque revue liée à l'empreinte du résultat brut.
PR à actualiser après ce rejeu ; CI du commit publié à contrôler séparément.
