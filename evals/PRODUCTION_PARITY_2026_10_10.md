# B2C — Rejeu après correction du 10 octobre 2026

**NO GO pour remplacer la production.** Les corrections de contexte et de mémoire sont utiles et vérifiées, mais des défauts de recherche et de suivi restent ouverts. Ce bilan v107 remplace les conclusions v104 pour le code courant.

## Changements depuis la précédente livraison

- Une contrainte de département reste obligatoire après précision de la ville. L'appartenance des résultats est vérifiée avec les identités du fournisseur géographique.
- Un code postal reste actif quand le client précise sa ville parente déjà vérifiée. Le choix d'un lieu proposé transmet sa position.
- Le profil Redis du concierge distingue la liste de recherche et l'hôtel consulté. Les questions sur son offre et les comparaisons de prix utilisent le bon hôtel, sans perdre les premières options de recherche.
- Une recherche résolue qui ne produit que du texte sans avoir tenté de lire l'inventaire déclenche un appel MCP borné. Pas de boucle LLM de réparation.
- Le triage distingue mieux les autres horaires, la pagination, les comparatifs et les réponses horaires courtes. Ces instructions ne garantissent pas à elles seules la réussite de tous les cas.

Aucune nouvelle regex ni dictionnaire géographique. Concierge propriétaire du profil, feuilles A2A sans session, LiteLLM et MCP en lecture seule conservés.

## Versions et méthode

Runtime exécuté : `0e32cc0d3ec4ecbf17e0c5113c7cf646e182af28`. Les 81 fichiers sources sont restés inchangés pendant le rejeu. Main B2C refetch après exécution : `cbe88b9`. Production legacy déployée : `3093647`. Les configurations et déploiements des six services/environnements Railway sont identiques avant et après la campagne.

Configuration testée : triage **GPT-5.2**, raisonnement low, 2048 tokens, timeout 15 s; recherche **4o-mini**; synthèse **GPT-5.2**. Le triage B2C déployé reste 4o-mini. La PR ne modifie pas Railway. Aucun gain ne peut être attribué au code seul ou au modèle seul; aucune nouvelle ablation de modèle n'a été lancée.

| Lot du runtime final | Conversations | Réponses | Coût modèle USD |
|---|---:|---:|---:|
| Contrôles détail, prix et comparaison | 3 | 12 | 0,2672 |
| Corpus historique et contrôles | 100 | 280 | 5,7671 |
| Total candidat | **103** | **292** | **6,0343** |

Les mêmes entrées du corpus principal sont comparées aux **280 réponses legacy déjà mesurées le même jour**, avec leurs timestamps d'origine. Inventaires non simultanés : export/Qdrant en production, MCP préproduction décrit comme reflet de production par l'équipe. Une absence d'hôtel ou un prix différent ne suffit pas à attribuer une erreur à l'agent.

Les dates historiques littérales sont rejouées au calendrier actuel. Le GPS, la devise et les autres champs natifs absents des sources ne sont pas inventés. Ce corpus mêle historique réel et contrôles synthétiques déjà exposés : il ne mesure pas de manière aveugle et exhaustive six mois de trafic. FAQ/SAV restent en phase 2.

## Résultats relus

Les **103 parcours candidats complets**, dont les **24 régressions géographiques**, ont été relus : **18 A, 42 B, 43 C** dans le périmètre évalué. A = parfait, B = mineur, C = significatif, D = majeur, F = critique. Une clarification appropriée peut recevoir A sans avoir produit de carte; les limites du préfixe et les questions hors périmètre sont signalées dans la revue.

Revue par l'agent qui a modifié le code, **pas une validation humaine indépendante**. Les 38 revues legacy réutilisées portent sur les fichiers inchangés, vérifiés par hash. Aucun juge payant n'a été relancé; sa calibration précédente était insuffisante. Aucun taux global de victoire contre la production n'est validé.

| Correction ou contrôle | Résultat observé |
|---|---|
| Département obligatoire après précision de Melun | Alternatives conservées en Seine-et-Marne |
| Détails puis demande moins chère | Référence 85 EUR conservée; minimum 63 EUR, économie 22 EUR |
| Mieux noté puis comparaison des deux premières options | Liste initiale conservée, confirmé dans le contrôle ciblé et le corpus principal |
| Nom complet corrigé puis question sur son offre | Bon hôtel, date, créneau 08–14 et prix 154,51 EUR; faute initiale toujours rejetée |
| Réponse courte «15 18h» | Mercredi conservé et créneau 15–18 compris; résolution de La Défense encore lente |
| Autre horaire en portugais | Créneaux présentés sans pagination dans ce rejeu |
| Retrait d'un enfant, puis moins cher | Composition et fenêtre conservées; alternatives horaires partielles annoncées |

W4 a été conservé dans **3/3 répétitions sur v106**, avant la séparation de mémoire v107. Ce ne sont pas trois nouvelles mesures sur v107. La suite finale conserve les tests de rétention de la ville parente vérifiée. Le code postal non résolu 78239 suivi de San Antonio reste un cas distinct défaillant.

## Intégrité des offres

**327 occurrences de cartes datées** sont reliées à un reçu MCP exact par hôtel, formule, date et créneau : aucun reçu manquant, écart détecté de prix ou de faits de formule, ni offre expirée lors de sa réponse. Les fiches d'identité sans offre sont comptées séparément dans le JSON.

Sur le corpus principal : 262 distances recalculées sans écart arithmétique, 30 contrôles de capacité sans insuffisance détectée, 19 plafonds frais inclus vérifiés sans violation. Quatre écarts à la minute exacte — début 09h au lieu de 08h30, ou 10h30 au lieu de 10h — sont annoncés comme alternatives. Le lot ciblé ajoute 10 distances; une fiche informative n'expose pas sa capacité dans la carte.

Ces contrôles ne prouvent ni l'exhaustivité de l'inventaire, ni la pertinence du lieu, ni l'exactitude de chaque phrase. Par exemple, une comparaison qualifie à tort 10–18 de plus long que 09–18 alors que les cartes sont exactes.

## Blocages avant remplacement

| Défaut observé | Conséquence |
|---|---|
| Quartiers/aéroports trop souvent non résolus | Heathrow Terminal 3, Manhattan après NYC/Newark, Westminster UK, La Défense et Brooklyn restent bloqués ou demandent trop de précisions |
| Parent d'un code postal non vérifié | La ville peut remplacer la zone demandée sans annoncer l'élargissement |
| «Demain» traité comme une période imprécise | L'agent redemande une date exacte au lieu de rechercher |
| Composition adultes/enfants | La même question revient malgré les autres précisions du client |
| Équipements de l'hôtel et de la formule mal distingués | Jacuzzi privé ou accès piscine insuffisamment vérifié/qualifié |
| Faute sur un nom d'hôtel | Recherche sûre mais rappel insuffisant; correction complète nécessaire |
| Synthèse et suivi complexe | Comparatifs de durée parfois faux, demandes de deux séjours non comparées automatiquement |

Les traces locales comprennent requêtes/réponses modèle, profils successifs et reçus MCP; les preuves historiques Langfuse restent conservées. Le rapport local permet à la team de relire chaque conversation et sa justification. Fermer ces défauts, puis mesurer un nouveau lot réel non exposé avec une revue humaine calibrée avant remplacement.

## Budget et livraison

- Cette reprise depuis v104 : **8,3630 USD**, diagnostics et arrêt intermédiaire compris.
- Diagnostics v105 et v106 : 9 parcours / 24 réponses chacun, respectivement 0,5172 et 0,5190 USD.
- Core v106 interrompu : 20 conversations complètes et 4 partielles, 63 réponses, 1,2925 USD. Arrêt sur erreur de transport MCP; sa revue a également découvert la régression détail → comparaison corrigée en v107. Ce lot ne vaut pas validation complète.
- Cumul comptabilisé : **198,8437 USD**, dont 7,10 USD de provisions anciennes conservées. Plafond 200 USD, réserve 0,50 USD, disponible après réserve **0,6563 USD**. Aucun coût en attente ni nouvelle autorisation ajoutée.
- Dernière enveloppe supplémentaire : 49,4882 USD consommés sous son plafond opérationnel ajouté de 50 USD. Tarification de télémétrie, pas facture; infrastructure, MCP et Mapbox exclus.

Le corpus principal compte 801 appels modèle physiques pour 280 tours : au plus trois phases logiques, mais jusqu'à cinq appels physiques liés aux échanges avec les outils. Ne pas annoncer «trois appels maximum».

**3 202 tests hors réseau passent**, un test Langfuse live optionnel est ignoré. Ruff, mypy sur 81 fichiers, guardrails et diff passent. Les services candidats de test sont arrêtés. PR #134 en brouillon, aucun merge, déploiement, changement Railway ou opération client. Conversations, GPS et secrets restent hors Git. Le JSON adjacent contient les compteurs sans conversations.

La CI sera vérifiée sur le head de livraison; le head précédent était bloqué avant les jobs par la facturation GitHub.
