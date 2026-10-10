# B2C / production : bilan de validation du 10 octobre 2026

**NO GO pour remplacer la production. La PR #134 apporte des corrections vérifiées, mais la parité fonctionnelle n'est pas atteinte.** Les correctifs stabilisent le contexte et les offres MCP ; des blocages de pertinence et de suivi restent reproductibles. Ce document remplace les bilans intermédiaires v97-v103. Les rapports datés précédents sont historiques.

## Versions et architecture

- Candidat execute : `9e85fe9f79f1a31a477c4e36857b8065a3693190`. Les 81 fichiers runtime sont figes et verifies apres execution. Le commit de livraison peut ajouter uniquement ce bilan et le handoff.
- Production effectivement deployee : `3093647403ec167a0f4ddc2e0bace05f9669d88f`; main B2C refetch avant/apres : `cbe88b9963f28fbea932ac2a6ce23d22112f2b76`.
- Les configurations et deploiements des six services/environnements Railway sont identiques avant/apres. Les images B2C deployees n'exposent pas de SHA applicatif : ne pas les assimiler au candidat local.
- Architecture conservee : profil Redis detenu par le concierge, feuilles A2A sans session, MCP pour les donnees, LiteLLM pour les modeles. Aucun nouvel appel regex dans le diff agents/libs de la PR. Pas de dictionnaire geographique ajoute ni de boucle LLM de reparation.

Configuration **testee**, differente du B2C deploye : triage GPT-5.2, raisonnement low, 2048 tokens et timeout15s; recherche4o-mini; synthese GPT-5.2. Le triage Railway B2C reste4o-mini. La production legacy utilise GPT-5.2. Les gains ne peuvent pas etre attribues au code seul ni au modele seul. La PR ne modifie pas Railway.

## Ce qui a été exécuté

| Lot candidat | Parcours | Reponses | Reference legacy |
|---|---:|---:|---|
| Corpus principal historique + controles | 100 | 280 | 100 / 280 |
| Suivis adaptes aux vraies reponses | 6 | 24 | 6 / 24 |
| Prefixes recents de production | 7 | 26 | 7 / 26 |
| Reprises explicites apres clarification | 4 | 14 | 4 / 14 |
| Controles critiques complementaires | 17 | 36 | Hors comparatif final appaire |
| Identite / nom d'hotel | 5 | 11 | Hors comparatif final appaire |
| Retour sur une ancienne carte / creneau | 1 | 4 | Rejeu cible du defaut |
| **Total** | **140 executions** | **395** | **117 / 344** |

Les reponses legacy proviennent des passages du meme jour v101 (corpus principal) et v102 (autres lots), avec leurs dates et hashes d'origine. Elles ne sont pas refacturees. Les inventaires sont **non simultanes et differents** : export/Qdrant legacy, MCP preproduction (reflet de la prod selon l'equipe). Un hotel absent ou un prix different ne prouve pas une erreur d'agent. Les tours sont sequentiels par session; quatre conversations independantes en parallele sur le corpus principal. Latence locale versus Railway non comparable directement.

Les 140 executions ne sont ni140 clients uniques ni les six mois complets. Le corpus melange messages historiques, prefixes recents et controles synthetiques issus des corrections. Tous sont exposes; les sept prefixes recents ont notamment servi au correctif NYC. **Aucun holdout independant final.** Les anciens messages utilisateur sont fixes et peuvent ne pas repondre aux nouvelles clarifications. Les six objectifs adaptatifs compensent partiellement cette limite en reagissant aux cartes reellement recues. GPS, devise UI, fuseau et autres contextes natifs manquants ne sont pas inventes. FAQ/SAV en phase2.

## Ce que les preuves permettent de conclure

**514 occurrences de cartes datees** sont reliees a un recu MCP exact par hotel, formule, date et creneau : zero recu manquant, zero divergence detectee de prix ou de faits de formule, aucune offre expiree detectee lors de sa reponse. Trois autres occurrences sont des fiches d'identite sans offre/prix; elles sont comptees a part. Ces controles ne prouvent ni l'exhaustivite ni la pertinence des hotels, ni la veracite de chaque phrase generee.

Sur le corpus principal :301 cartes datees,262 calculs de distance sans ecart arithmetique,25 controles de capacite et21 plafonds frais inclus sans violation detectee. Quatre ecarts a la minute litterale relevent de la regle horaire du site et sont annonces comme alternatives. Une distance mathematiquement correcte n'empeche pas une recherche dans une mauvaise zone. Le candidat affiche des cartes sur84/280 reponses, contre146/280 pour le legacy : clarifications, inventaires et parcours conditionnels interdisent d'y lire seuls un taux de succes.

**Corrections confirmees par le rejeu :** NYC n'est plus perdu a cause de la normalisation du nom; consulter une carte ne transforme plus la zone en recherche d'un seul hotel; un rayon explicite30km repart du GPS verifie; les details d'un ancien hotel choisissent une formule compatible avec l'horaire memorise. Le parcours Herald Square conserve date/18h, propose d'autres hotels, puis retrouve le bon prix/creneau. Les controles Texas, Hilton Atlanta, Maritime, BNA/HNL/PDX et devise USD conservent leur contexte. Les prix sont rattaches a une formule/date, au lieu de reconstituer une offre depuis un prix d'appel.

**Blocages encore ouverts :**

| Priorite | Defaut verifie | Consequence / correction attendue |
|---|---|---|
| Majeur | Apres «toujours en Seine-et-Marne», une option moins chere a Saint-Germain-les-Corbeil (adresse MCP91250) est presentee sans signaler la sortie du departement | La region est memorisee mais le filtrage final utilise le point de Melun. Distinguer contexte de geocodage et contrainte geographique obligatoire jusqu'aux cartes. |
| Significatif | La Defense, Manhattan, Heathrow Terminal3, WestminsterUK et BNE peuvent rester bloques | Ameliorer la resolution par preuves fournisseur et la clarification ciblee; ne pas revenir aux substitutions de ville non verifiees. |
| Significatif | W4 conserve dans2/3 repetitions; SW19 peut devenir Londres-centre | Une precision sur la ville parente ne doit pas effacer silencieusement le district. |
| Significatif | «its offer», «c'est dans quelle zone?», «autre horaire», choix d'un lieu propose ou faute sur un hotel visible | Unifier les referents de cartes/lieux et les operations de suivi; ne pas confondre autres hotels et autres creneaux. |
| Significatif | «15 18h» devient date15 +18-20 au lieu d'une clarification | Resoudre l'ambiguite sans remplacer silencieusement la date memorisee. Deux sejours restent traites un a un, sans comparaison automatique. |
| Significatif | Question sur le calendrier a North Little Rock annonce une panne | A2A et LLM ont repondu; la feuille a produit du texte sans outil. Distinguer clarification, absence d'offre et panne dans le contrat de retour. |

La prod a aussi des defauts confirmes : derive GW Bridge vers Virginia Beach/Washington, Metro Park/Princeton vers l'Inde, GPS Ontario vers Halifax, et prix d'appel associes a un mauvais creneau ou a un passe piscine. Les traces Langfuse completes ont servi a verifier le cas LAX, notamment. Cela ne rend pas automatiquement le candidat meilleur sur l'ensemble des parcours.

## Notation et fiabilité du juge

A parfait, B mineur, C significatif, D majeur, F critique; NN pour une affirmation non evaluable. Note de conversation entiere, pas moyenne des tours. **120 revues de conversations-bras par l'agent de codage**, incluant les24 regressions geo des deux bras, tous les suivis adaptatifs et controles complementaires. Ce n'est pas une validation humaine independante.

GPT-4.1 a evalue117 paires, plus4 repetitions avec ordre inverse. Calibration :7/16 notes identiques a la revue prealable; inversion de l'ordre :4/8 notes de bras changent. Il a rate des erreurs de prix/creneau, penalise a tort des ecarts d'inventaire et une FAQ hors scope. Ses9 signalements majeurs ont tous ete revus; une sortie invalide a ete remplacee par une revue des deux bras sans nouvel appel payant. **Les notes automatiques restantes sont provisoires; aucun taux global de reussite ni victoire globale n'est valide.** Le rapport prive indique la provenance de chaque note. La conclusion NO GO repose sur des defauts observes, pas sur la moyenne du juge.

Les six suivis adaptatifs entierement revus donnent candidat3A/2B/1D, legacy2B/1C/3D. C'est un petit lot cible, pas une estimation du trafic. La matrice ci-dessous utilise uniquement les revues de conversations entieres; une noteC peut provenir du suivi, meme si le pays est correct.

| Regression historique | Prod | Candidat |
|---|---|---|
| East Brunswick, NJ | B | B |
| Halton / Peel, Canada | C | A |
| Berlin-Mitte | B | A |
| Abu Dhabi et piscine enfants | C | B |
| Milano et question sur le quartier | B | C |
| La Defense / Courbevoie | C | C |
| Disneyland et clarification du pays | D | C |
| JFK et horaires | C | B |
| Heathrow Terminal 3 | C | C |
| Milford, Connecticut | B | B |
| Queens et piscine | C | B |
| South Plainfield, NJ | B | B |
| Melbourne, Australie | B | B |
| Rambler Oasis / Hong Kong | C | A |
| Singapore avec faute de frappe | B | B |
| Correction Courbevoie / La Defense | C | C |
| Newark puis Manhattan | C | C |
| Halifax ambigu | C | B |
| Westminster UK | B | C |
| Kent / Gillingham | B | B |
| Brooklyn et budget | B | B |
| Paris Bercy / demain | C | B |
| Metro Park Edison vers Hampton Princeton | D | C |
| Nice adjectif / Paddington / meilleure note | B | A |

## Modèle et coût

Micro-controle isole :4 decisions capturees, deux modeles, trois repetitions, entree/outils identiques, aucun outil execute. Sur la question North Little Rock,4o-mini affirme une indisponibilite sans outil3/3; GPT-4.1 demande une recherche3/3. Les deux appellent des outils sur les trois autres controles. Cout **0.1196 USD**. Cela justifie un futur challenger4.1 de bout en bout, **pas un remplacement valide**. Les gardes de contexte/prix et le contrat de clarification restent necessaires.

- Derniere validation v104 : **11.8294 USD**, dont8.0587 de rejeux,3.6511 de notation et0.1196 de micro-controle.
- Derniere enveloppe supplementaire : **41.1252 USD consommes**, sous-plafond operationnel ajoute50USD.
- Cumul comptabilise : **190.4807 USD**, dont7,10USD de provisions anterieures non tarifables conservees; plafond200USD, reserve0,50USD, disponible **9.0193 USD**. Aucun batch payant en attente.
- Corpus principal : candidat5,6691USD /280 reponses, legacy5,7628USD /280. Pas de baisse de cout robuste demontree. Tarification issue de la telemetrie, pas verification de facture; couts MCP/Mapbox/infrastructure exclus.

Le corpus principal compte812 appels modele :280 tours, au plus3 phases logiques, mais jusqu'a6 appels physiques a cause des boucles d'outils. Ne pas presenter l'architecture comme «3 appels maximum».

## Revue / livraison

3185 tests hors reseau passent,1 test Langfuse live optionnel saute; ruff, mypy81 fichiers, guardrails et verification de diff passent. Aucun merge, deploiement, changement Railway ou operation client. La CI GitHub est a verifier sur le head livre; le head precedent etait bloque avant execution par la facturation du compte.

Ordre de revue conseille : contrats `libs/b2c_common`, profil/triage et operations du concierge, ancrage/filtrage et offres de la feuille recherche, details/comparaison/devise, puis tests et harnais. La PR est large (136 fichiers avant ajout du bilan JSON); les donnees brutes privees et les cles restent hors Git. Le fichier JSON adjacent contient les compteurs et hashes de preuve sans conversations.

Avant remplacement : fermer les blocages ci-dessus, rejouer leurs controles sur un meme runtime, puis figer un nouveau lot reel non expose et faire calibrer les jugements par la team. La PR reste en brouillon pour cette revue.
