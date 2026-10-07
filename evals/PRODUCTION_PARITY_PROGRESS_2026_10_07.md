# Audit historique et correctifs v18 — 7 octobre 2026

## 2026-10-08 — v21 : revue des 108 notes terminée, nombres et contexte corrigés

**Toujours pas de GO remplacement.** Les 108 annotations du lot historique v19
ont été revues séparément des suggestions du juge ; les 216 empreintes des
rejeux/notations ont été vérifiées. 70 notes ont changé. C'est une classification
sémantique limitée aux preuves disponibles, pas une validation exhaustive des
sources, de l'inventaire ou des 6 mois de comportement. Le lot reste sur d1eb29e.

Le triage ne crée plus un budget à partir d'un nombre seul sans contexte : une
réponse budgétaire doit citer la question précédente réelle. Les codes postaux ne
sont pas distingués des montants par un seuil arbitraire. Le modèle interprète le
rôle, le code vérifie la présence de la preuve ; cela ne certifie pas la sémantique
de toute question. Aucun regex ni appel LLM supplémentaire. Les nombres seuls
conservent la langue établie ; les contraintes de recherche restent transmises à
la synthèse même lorsque l'inventaire est vide.

**Quatre itérations, 54 réponses ; dernière version 17 réponses.** Le premier
correctif rejetait aussi une réponse budgétaire valide faute de citation par le
modèle. Ce défaut a été conservé dans les rapports, puis corrigé avec un rappel
ciblé dans le même appel de triage. Dernier lot : 6 contrôles d'état ciblés passent
(codes postaux sans budget, précision ville/État/pays, montant USD, deux plafonds
JPY successifs avec langue stable). **20 cartes** jointes aux reçus MCP par
hôtel/formule/date/minute : zéro écart de prix, expiration ou carte non jointe.
Aucune carte avec plafond vérifiable dans ce lot : ne pas en déduire une preuve
supplémentaire sur les budgets frais compris.

**Défauts encore présents** : une synthèse traite parfois un nombre non validé
comme un plafond ; des clarifications ville/devise tournent en boucle. Géographie
pays/comté/POI, preuves par borne horaire, accès aux équipements, FAQ et widget
restent à valider/corriger. Aucun taux global ni supériorité sur prod démontré.

Comparatif de triage isolé : 12 cas × 2 tirages × 2 modèles. Rôle des nombres :
4o-mini 24/24, 4.1-mini 23/24. Le prompt de ce test précède le dernier rappel
numérique ; le test ne mesure ni le prompt final ni le parcours complet. Le rejeu
complet a précisément révélé un défaut absent du test isolé. Aucune configuration
Railway changée et aucun changement de modèle préconisé sur cette seule preuve.

Nouveau contrôle SQL : 33 216 lignes, 2 000 dernières exportées. Les 9 nouvelles
lignes forment 3 sessions hors identifiants de nos rejeux connus ; l'API n'expose
pas is_synthetic, donc provenance organique non certifiée. 9/9 messages associés
exactement aux extractions Langfuse. Devises/locales attestées dans les diagnostics,
fuseaux appareil retrouvés. Entrées préparées pour Waterloo/Wimbledon,
Brescia/province et East London/Bromley, **pas encore rejouées**. GPS/favoris présents
dans une session mais valeurs exactes non retrouvées : aucune donnée inventée.

Validation code final : **2 276 tests passés, 1 ignoré** ; 206 tests ciblés ;
ruff, mypy (60 fichiers), guardrails et diff propres. Deux anciens tests traitaient
un nombre initial comme budget sans contexte : leurs scénarios ont été précisés
(question budgétaire préalable ou devise explicite), sans retirer les assertions
sur le caractère explicite et l'absence d'élargissement du plafond. Les nouveaux
tests ont échoué avant correction (8 échecs, 5 succès).

CI92dd1d5 précédente réussie (étapes live ignorées). Main re-fetché, toujours cbe88b9.
Coût de cette étape **0,3037 USD**, dont 0,0202 de comparatif modèles ; cumul
**83,6990/110 USD**, dont 11,10 de provisions, réserve 10. Aucun runner payant actif.
Données, conversations et rapports détaillés privés hors Git. PR134 reste brouillon,
sans merge ni déploiement. Suite : reprendre les nouveaux parcours géographiques
avec leur contexte attesté, puis contrôles horaires, FAQ/annulation informative et
widget ; préserver les échecs et rejouer après chaque correction.


**Pas de GO remplacement production.** Le VPN fonctionne et les comparaisons live
ont repris. Des gains ciblés sont établis, mais plusieurs défauts importants
restent ouverts. Aucun merge, déploiement ou changement des modèles Railway.

## 2026-10-08 — v20 : créneau conservé entre les tours, rejeux correctifs terminés

**Toujours pas de GO remplacement.** Le concierge conserve maintenant les bornes
horaires validées dans un champ persistant distinct des déclarations de la feuille.
La feuille ne peut ni le réécrire ni le supprimer, y compris via une opération
`clear`. Le même champ contrôle les arguments horaires MCP et le profil après
une recherche ou une interruption FAQ. Aucun nouveau regex ni appel LLM ajouté.

Les changements explicites restent possibles : retrait du filtre, nouvelle durée,
ou préférence non numérique interprétée par la feuille. Quand le triage transforme
« le matin » en heures sans preuve numérique, les heures sont rejetées et la
nouvelle préférence est déléguée, plutôt que de conserver l'ancien soir. Les heures
marquées explicites uniquement par une ancienne feuille ne sont pas promues en
preuve du concierge. La règle produit d'arrondi des offres reste inchangée.

Trois lots correctifs : **33 réponses au total, coût 0,2620 USD**. Premier lot :
Manhattan garde 18:30–21 après précision géographique ; Philadelphia garde 09:30
après « moins cher ». Il révèle une durée d'une heure omise par le triage. Deuxième
lot : durée corrigée, mais changement au matin ignoré après rejet de 6–12 inventé.
Après correction de ce chemin, dernier lot **2 parcours / 9 tours : tous les 9
contrôles d'état horaire passent**, avec mode overlap pour matin et aucun filtre
horaire après retrait. **26 cartes** jointes par hôtel/formule/date/minute au MCP,
0 écart de prix/expiration/non jointe. Aucun budget plafonné testé dans ce lot.
Les 33 réponses ne sont pas toutes issues du code final ; chaque version est figée.

La qualité conversationnelle n'est pas entièrement corrigée : la synthèse redemande
parfois une durée/fenêtre connue. Le cas combinant matin + heure de départ nécessite
encore un meilleur contrôle de preuve par borne. Ces résultats ne prouvent ni le
rappel de l'inventaire, ni une supériorité globale, ni la stabilité du modèle.

Validation code final : **2 261 tests passés, 1 ignoré** ; 191 tests ciblés,
ruff, mypy (60 fichiers), guardrails et diff propres. Les tests ont reproduit les
pertes de minutes avant correction. La nouvelle CI reste à vérifier après push.

Revue manuelle historique : **57/108 annotations**, dont les 36 du candidat ;
51 restent à revoir côté legacy/B2C. Notes originales conservées séparément.
Contrôle récent SQL : 33 207 lignes incluant nos tests, 2 000 dernières exportées ; ce chiffre ne compte pas des conversations organiques distinctes.
Coût cumulé comptabilisé **83,3954/110 USD**, dont 11,10 de provisions ; réserve 10.
Aucun runner payant actif à ce checkpoint. Traces et messages bruts hors Git.

Suite : compléter les 51 revues ; corriger les rôles des nombres, la granularité
et le suivi géographiques, le grounding horaire restant et les répétitions ;
challenger les modèles par composant sur ces défauts ; compléter les rejeux avec
contexte natif retrouvé/dates futures, FAQ/annulation informative et widget.
PR134 reste brouillon, sans merge, déploiement ni modification Railway.

## 2026-10-07 — validation historique v19 collectée, revue des notes incomplète

**Pas de GO.** La version runtime `d1eb29e` est restée identique pendant les
36 conversations historiques réservées : **104 messages originaux par bras,
312 réponses** legacy production / B2C déployé / candidat. Inventaire MCP frais,
aucune action de réservation ou annulation. Le lot coûte **3,1526 USD**.

Les 47 cartes du candidat sont jointes aux reçus MCP par hôtel, UUID de formule,
date et créneau à la minute : **0 écart de prix, 0 offre expirée, 0 non jointe**.
Seulement 3 cartes ont un budget total vérifiable ; toutes respectent ce plafond,
frais de réservation inclus. Cela ne prouve ni le rappel ni les droits d'accès
aux équipements. Les heures/dates historiques rejouées aujourd'hui limitent la
comparaison de disponibilité, particulièrement après fermeture des créneaux.

Langfuse historique retrouvé pour 23 sessions ; 22 couvrent les messages SQL
via leurs appels d'extraction, une n'est attestée que partiellement. Une trace
supplémentaire répète le premier message d'une session, sans message client
manquant identifié. Un fuseau de l'appareil apparaît dans 22 sessions, absent
de l'export SQL ; il n'a pas été ajouté rétroactivement aux entrées figées.

**108 notes assistées reçues, mais pas de taux de réussite utilisable.** Le juge
commet notamment des faux A (pays explicite ignoré), des reproches fondés sur un
budget fourni plus tard et des erreurs de containment horaire. 14 annotations
ont été revues manuellement, avec corrections séparées et notes originales
conservées. La revue complète doit précéder toute affirmation de supériorité.
Notation : A parfait / B mineur / C significatif / D majeur / F critique.

Défauts observés à traiter : rôle des nombres (code postal devenu budget),
matin transformé en minuit, minutes perdues au tour suivant une clarification
géographique, pays/homonymes et comté confondu avec quartier, critères d'accès
ascenseur/baignoire mal interprétés. Le contrôle du delta v19 protège seulement
les minutes du message courant, pas encore celles des tours antérieurs.

Coût notation **1,3107 USD** ; cumul comptabilisé **83,1334 USD / 110 USD**, dont
11,10 USD de provisions, réserve 10 USD. Aucun runner payant actif à ce point.
Code inchangé : **2 232 tests passés, 1 ignoré**, CI37687522548 réussie, étapes
live ignorées par configuration. Les fichiers privés restent hors Git.

Suite : terminer la revue des 108 parcours notés, corriger les causes sans
nouveau regex, comparer les modèles étape par étape, rejouer les défauts avec
contexte natif retrouvé et dates futures dans un lot distinct. Les 36 sessions
sont désormais exposées : leurs rejeux futurs ne sont plus un holdout inédit.
FAQ/annulation informative, widget et preuve complète des correctifs restent
à terminer. Ni merge, ni déploiement, ni changement Railway.

> Les sections suivantes sont des checkpoints historiques ; le dernier état ci-dessus prévaut.

## Rejeu adaptatif terminé et corrections v19

9 objectifs synthétiques historiques × 3 agents = **135 réponses**, coût
supplémentaire **2,0701 USD**. Exclusions manuelles des objectifs non respectés
par le client simulé ; pas de moyenne de succès. Les annotations A/B/C/D/F sont
limitées aux critères réellement exercés. Pescara reste sur l'Adriatique dans
le préfixe candidat ; legacy dérive vers Vérone et B2C vers Pérouse. Heathrow
est résolu côté candidat alors que B2C redemande Londres sur cinq tours.
Ces gains ne compensent pas les autres parcours majeurs en échec.

Le code v19 transmet maintenant à la synthèse les **créneaux et la date de la
carte**, recherche avant de sélectionner « le moins cher » lorsque les heures
changent, complète les bornes explicitement demandées et protège les minutes
du tour contre un delta feuille arrondi. Aucun regex/appel LLM supplémentaire.
**2 232 tests passés, 1 ignoré**, ruff/mypy/guardrails verts. Un test préexistant
avait détecté un report abusif d'horaire implicite : corrigé dans le code,
assertion conservée.

Rejeu `live-followup-v19` : **5 parcours / 15 réponses**, candidat seul, inventaire
frais. Brooklyn cite la formule11–15:30 et conserve15:30 au tour suivant ; Orlando
recherche11–16 avant le choix. **9 cartes sous plafond frais inclus,0dépassement,
0non vérifiée**. Audit brut général :25cartes de recherche jointes,0écart de prix,
0expiration ;6cartes de détails non jointes par cet audit limité aux recherches.
Ces contrôles ne prouvent pas le rappel ou l'ensemble des conversations.

Défauts encore constatés dans cette version : questions de quartier après
indifférence (Orlando), début10h ajouté sans demande (SanDiego), échec Birmingham,
quote at11am modifiée par le modèle et rejetée ; la variante avec espace conserve
11–17 mais échoue aussi sur la recherche. La note du dernier parcours est B
pour Brooklyn, C pour Orlando/SanDiego, D pour les deux variantes cinéma.
Pas de score global ni de GO. Les montants en lettres, FAQ/conditions exactes,
adults-only/bains privés/spa inclus, exhausted-list et validation36 restent
incomplets. Coût cumulé **78,6701 USD**, dont11,10 de provisions, plafond110.

## Mise à jour v17 : total avec frais et limites conversationnelles

Les mentions « sous plafond » ci-dessous dans v15 décrivent le **prix affiché**.
L'audit indépendant ultérieur du lot `live-budget-answers-v15` trouve une offre
Arlington45USD +6USD de booking fees, soit51USD pour un plafond50USD.
`live-context-v16` confirme4cartes en dépassement frais inclus. Ces lots ne sont
pas une preuve de respect des budgets totaux, malgré leurs prix affichés valides.

Le correctif local v17 vérifie `*WithBookingFees` sur la même offre ; pas de
repli sur un prix hors frais manquants. `live-context-v17`,9séquences27tours,
présente18cartes plafonnées toutes vérifiées par hôtel/UUID/date/créneau :
**0dépassement frais inclus,0non vérifiée**. Aucun appel ni regex ajouté.
2 226 tests passent,1ignoré. Ces corrections sont incluses dans le checkpoint v19 de PR134.

La synthèse ne doit plus prendre une carte pour tout l'inventaire, une distance
au POI pour une distance au centre ou une grosse remise pour le prix le plus bas.
La FAQ utilise désormais payment pour les cartes cadeaux. Reste un défaut
significatif : malgré ce meilleur contexte,4o-mini extrapole les règles Dayuse
aux cartes cadeaux propres aux hôtels. Les articles eux-mêmes divergent sur
les pays éligibles (France seule versus5pays) : pas de règle universelle établie.

Le lot adaptatif historique v17 est en cours. Premiers résultats : Pescara
reste sur l'Adriatique côté candidat, mais des demandes de nouveaux créneaux avec
« cheapest » sont détournées vers details ; la synthèse n'a pas les horaires des
cartes et demande des dates déjà connues. Des disponibilités sont mal triées en
booking. Les montants en lettres ne sont pas conservés. Ce sont des défauts
bloquants pour le remplacement. Certains clients simulés changent leur objectif :
ces segments sont exclus de la notation des exigences concernées, sans effacer
les traces ni les coûts. Aucun taux de succès global n'est calculé à ce stade.

## Correction du protocole de devise — candidat v15 rejoué

La revue du code effectivement déployé (`a08a7792`) et du champ historique
`detected_market` a révélé une omission du banc : les 14 séquences fraîches
précédentes ne transmettaient pas la devise enregistrée. **Les lots v3 à v6 ne
prouvent donc pas une parité avec le contexte natif du widget.** Ils restent des
diagnostics avec contexte de devise retiré ; leurs coûts et contre-exemples sont
conservés. Les constats ci-dessous décrivent les entrées de ces lots, pas tous les
parcours de production.

Le nouveau lot `fresh-native-v15` compare les trois bras. Pour 11 séquences / 32
tours, une devise explicite est attestée dans les diagnostics URL historiques et
restaurée. Pour 3 séquences / 12 tours (Arlington, San Diego, Paris tardif), seule
la devise du marché résolu est attestée : elle **n'est pas transformée en choix
explicite**. Le domaine et la locale initiaux sont conservés ; ces cas restent
limités par l'absence de la requête widget brute. Le legacy peut remplacer un
faible défaut USD par la devise du pays de l'hôtel, contrairement à un choix
explicite. Cette distinction est nécessaire pour interpréter les résultats.

Le candidat v15 ajoute un budget montant/devise/unité, persistant et validé sur
une citation du message courant. La devise native fournit l'unité d'un montant
nu sans changer le mode d'affichage du nouveau B2C. Le filtre MCP en EUR est
réservé aux budgets EUR ; les autres unités sont vérifiées sur le prix de la
même offre. Aucune conversion de change inventée, aucun appel LLM ni regex ajouté.
Une réponse composée uniquement d'une devise peut compléter un budget en attente.
Les limites de rappel sur la page récupérée et les suppléments restent explicites.

**Limite supplémentaire vérifiée pendant le lot :** le cache MCP journalier peut
contenir des offres dont la limite de réservation est passée. Une lecture directe
sans cache le 7 octobre à 20:00 UTC à Arlington a renvoyé des offres différentes.
Les résultats de `fresh-native-v15` restent donc des diagnostics de contraintes
sur instantanés ; ils ne valident pas la disponibilité actuelle. Le contrôle
suivant utilise un transport MCP lecture seule sans cache d'inventaire ni décalage
de date. Les anciennes sorties restent conservées et facturées.

Validation locale v15 : **2 224 tests passés, 1 ignoré**. Ruff, mypy et guardrails
passent. La comparaison live et le rejeu des réponses courtes sont terminés ;
aucun succès global n'est déduit des tests locaux. Les résultats v11/v12/v13 sont
des diagnostics intermédiaires, pas des résultats rétroactifs du candidat v15.

## Résultats v15 avec inventaire frais

`live-native-v15` : **14 séquences / 132 réponses**, trois bras terminés avec
sessions séparées. MCP candidat sans cache d'inventaire ni décalage de date,
Mapbox en cache statique. **27 cartes** jointes par hôtel + UUID de formule +
date à la réponse MCP brute : aucun écart de prix, aucune limite de réservation
passée à l'heure de la réponse. **12 cartes avec plafond vérifiable**, toutes
sous ce plafond dans la bonne unité ; aucun filtre MCP EUR pour ces budgets
étrangers. Ces contrôles ne mesurent ni le rappel de l'inventaire ni les
suppléments facultatifs ni la qualité complète d'une conversation.

`live-budget-answers-v15` : **2 parcours adaptés / 7 tours**, sans cache également.
« USD » et « US dollars » complètent bien les plafonds50/60, conservés ensuite.
La fenêtre09h–17h et la borne de départ20h persistent. Arlington trouve une offre
affichée sous50USD mais à51USD frais inclus, puis aucune offre vérifiable sur09h–17h ; San Diego ne trouve pas de
formule vérifiable sous60USD. Le contrôle du prix affiché seul était insuffisant pour ce lot. Sa phrase « only one matches » reste trop générale pour une page de
résultats : ne pas la considérer comme une preuve d'exhaustivité.

Les traces fraîches déployées montrent priceRangeMax100EUR pour le clientUSD100.
Le candidat le corrige. Les défauts sémantiques établis restent **C** sur les
segments concernés : Orlando redemande la zone après indifférence ; Paris perd
la clarification22h ; carte cadeau est classée ack et reçoit un accueil ;
Ripley confond le filtre d'occupation2adultes avec une demande adults-only sans
vérification de politique. **Les autres cas partiels ne deviennent pas A/B.**
Brooklyn/Davenport nécessitent des réponses adaptées aux clarifications ; trois
séquences restent limitées par la devise native non explicitement attestée.

Pescara est vérifiée sur la côte adriatique (42.47194,14.206623), Tours conserve
starRatings5, Rome/Milan conservent leurs équipements. Les résultats vides du MCP
frais en fin de journée ne prouvent pas une régression face à l'export legacy.
L'absence de fuseau natif à Singapour empêche un verdict de disponibilité.
La normalisation des montants écrits en lettres reste une limite à évaluer :
le nouveau validateur exige actuellement une représentation numérique citée.

Coût après ces deux lots : **75.5730USD engagés**, **64.4730USD observés** et
**11.10USD de provisions**, aucun lot modèle pending. La provisionCI existante
est réutilisée pour le prochain push ; les étapes live du précédent run avaient
été ignorées par leurs gardes de configuration. Aucun changement de modèle.

## Données et fiabilité de la mesure

- Export frais via l’API SQL en lecture : **32 822 tours / 13 340 sessions**, du
  20 février au 7 octobre. Ce n’est pas un backup SQL complet.
- Échantillon figé avant lecture : 72 conversations de développement et **36 de
  validation encore non lues**. Filtres de longueur, identifiant et domaine ; ils
  ne prouvent pas que chaque session est organique. Échantillon mensuel équilibré,
  pas pondéré par le trafic ; pas de session d’avril éligible.
- Langfuse historique : 48/72 sessions avec traces, 24 sans. Une session possède
  un tour de destination dans Langfuse absent de l’export ; elle est écartée du
  rejeu exact. Des nombres égaux de tours ne prouvent pas un contexte complet.
- Grille A/B/C/D/F historique conservée. Les juges économiques et GPT-4.1 ont été
  calibrés, mais la revue des A/B a encore trouvé un changement de pays répété,
  un prix horaire traité comme total et des affirmations de services/politique
  insuffisamment étayées. **Les distributions automatiques sont retirées du
  verdict qualité**. Les corrections manuelles et sorties originales restent
  conservées ; aucun taux global de réussite validé n’est annoncé.

## Comparaison fraîche

14 séquences réelles de développement, 44 messages chacune des trois versions :
**132 réponses** legacy production / B2C déployé / candidat v18-v3, toutes terminées
et revues qualitativement (texte, cartes et profil ; traces ciblées pour les causes).
Ce lot a été choisi pour diagnostiquer des défauts ; ce n’est pas un échantillon
aléatoire de satisfaction. Il complète les 41 séquences et 24 objectifs de v17,
sans leur attribuer rétrospectivement le code v18.

Les sessions/cookies sont indépendants. Les deux déployés sont appelés par leur
vrai endpoint ; le candidat utilise la configuration de modèles Railway et des
services locaux isolés, avec cache MCP/Mapbox par arguments exacts. Date courante
par cas, contexte natif manquant signalé. Legacy export/Qdrant et MCP préprod
(reflet exact de la prod selon Victor) ont des chemins et fraîcheurs différents.
Une différence d’hôtel ou un résultat vide ne suffit pas à conclure à un défaut.

Douze traces fraîches ciblées ont été lues (Arlington legacy, Orlando et Londres
B2C), sans ERROR/WARNING observé : les défauts décrits ci-dessous sont sémantiques,
pas expliqués par une panne MCP. Les anciens 429/quota et 400/extract_claims sont
consignés comme incidents historiques distincts.

| Parcours | Constat de la comparaison fraîche |
|---|---|
| Arlington Texas → budget → 9h–17h | Legacy change vers Virginie/DC après « Arlington ». Candidat conserve Texas et les heures ; devise encore à traiter. |
| Orlando, 100 USD, quartier indifférent | Les nouveaux agents traitent USD100 comme EUR100. B2C déployé et candidat v3 répondent par un accueil générique à l’indifférence. |
| San Diego, budget contextuel, jusqu’à 20h | Legacy conserve60 ; candidat v3 annonce le montant sans le persister. Les réponses suivantes dépassent le budget. |
| Jacuzzi puis Londres ; spa puis Rome | Candidat conserve mieux l’équipement après clarification ; le déployé le perd. Une installation d’hôtel ne prouve pas un accès inclus ou privé. |
| Pescara | Les deux nouveaux agents choisissent un hameau près de Pérouse. Mapbox avait bien renvoyé la ville adriatique ; le classement par inventaire la remplaçait. |
| Ripley MS, baignoire, adultes seulement | Ville/État mal extraits ; une clarification géo peut être remplacée par une fausse panne. Deux occupants adultes ne prouvent pas un hôtel réservé aux adultes. |
| Cinq étoiles → Tours | Déployé propose trois étoiles sans réserve ; candidat conserve le filtre et retourne vide. |
| Milan → spa → jacuzzi | Candidat poursuit la recherche ; déployé redemande la ville. Vérification de l’accès privé/inclus toujours nécessaire. |
| Cinéma sans ville ; Davenport ambigu | Une clarification nécessaire n’est pas un échec. Ne pas récompenser une destination inventée. |
| Brooklyn → « le premier » | Après clarification non répondue, aucune liste n’existe : sélection non comparable. Rejeu adaptatif nécessaire. |
| Paris « ferme vers22h » | Il faut distinguer réception, arrivée et départ. Réponse Paris ne résout pas cette ambiguïté ; la question initiale se perd. |
| Carte cadeau puis Singapour | Politique legacy à vérifier ; manque de fuseau natif et date locale déjà au lendemain empêchent un verdict de disponibilité. |

## Changements du candidat

- Géo : destination demandée prioritaire sur GPS ; pays vérifié prioritaire sur
  locale ; ville résolue indépendamment ; identité IATA/terminal contrôlée ; repli
  administratif borné pour un quartier après échec SearchBox, avec pays/nom/distance
  vérifiés. Aucun nom de ville ajouté à une liste d’exceptions.
- Triage existant : fenêtre horaire optionnelle avec citation du message courant,
  persistée avant la feuille. Un après-midi vague n’est pas une preuve de 12h.
- Relances : dernière réponse du concierge bornée transmise comme contexte non
  fiable au triage uniquement. La feuille ne reçoit pas les suggestions de l’agent
  comme nouvelle source de préférences. Pas de nouvel appel LLM, pas de regex ajouté,
  pas de données de politique ni de consentement déduites de cette réponse.
- Fiches collectives : identifiants de la sélection, dédupliqués, maximum 5 ; même
  date et même formule quand connues. Prix et horaires de la même offre ; si la
  formule a disparu, pas de remplacement silencieux par un prix différent.
- MCP timeSlotMode choisi par code : contain pour heures, overlap pour daypart,
  retiré sans fenêtre. Évite l’envoi de l’enum invalide start_only.
- Diagnostic géo : un DataPart de télémétrie conserve le texte de la feuille pour
  l’invocation courante ; aucun ancien tour, résultat outil ou raisonnement repris.
- Homonymes : une municipalité exacte mieux classée par Mapbox ne doit pas être
  remplacée par une subdivision du même pays au seul motif de l’inventaire. Une
  subdivision mieux classée reste candidate (contre-exemple Brooklyn NY).

Concierge propriétaire de l’état, feuilles stateless A2A, LiteLLM conservé.

## Rejeux des corrections et limites

Les variantes sont figées et identifiées par empreintes. Les erreurs intermédiaires
restent dans les artefacts et dans les coûts.

- Pilotes JFK : conservation11h–16h et lecture collective des fiches. Le premier
  pilote avait exposé une formule125 USD remplacée par156 USD ; le rejeu d’une vraie
  réponse MCP vérifie maintenant la conservation125 USD (preuve adaptateur, pas à
  elle seule validation du parcours complet).
- Triage sur24 diagnostics : objet horaire atomique, 4o-mini 10/12, 4.1-mini 12/12.
  Pilote conversationnel à cinq cas encore mixte : **aucun remplacement global
  de modèle justifié**. Le précédent essai search 5.2 coûtait environ 4,8× sans gain
  global établi.
- Candidat v4 : 14 séquences / 44 tours terminés. L’indifférence poursuit Orlando,
  budget contextuel 60 persiste à San Diego ; devises et questions répétées restent
  incorrectes. Pescara résout la bonne ville mais retourne vide à la date courante.
- Ce rejeu révèle une régression de la préférence municipale : Brooklyn NY est
  écarté pour Maryland. Test négatif ajouté et règle resserrée pour conserver les
  subdivisions mieux classées. **Les tests locaux seuls n’avaient pas détecté ce
  défaut** (2 197 passaient avant l’ajout du contre-exemple).
- Candidat v5 : 14 séquences / 44 tours terminés, 2 198 tests locaux passent.
  Brooklyn redevient une clarification ; le texte de l’assistant transmis à la
  feuille a cependant contaminé une recherche Arlington avec « downtown », jamais
  demandé par le client. Cette transmission est retirée : la réponse précédente
  sert uniquement au triage.
- Candidat v6 : 14 séquences / 44 tours terminés et revus. Pescara résout la bonne
  ville ; Brooklyn reste une clarification. Orlando poursuit la recherche après
  indifférence mais redemande un quartier ; les devises restent incorrectes. Tours
  redemande inutilement un quartier ; Rome peut traiter spa comme un lieu. Ces
  variations empêchent tout gain global affirmé. Huit séquences ont un défaut
  significatif constaté (C) ; six restent partiellement/non évaluables, **pas A/B**.
- Ce lot expose aussi children=0 rejeté par MCP. Adaptateur corrigé pour omettre
  zéro sur le fil et conserver le retrait dans le profil. La déclaration virtuelle
  autorise ce retrait au modèle sans modifier le schéma du serveur.
- Candidat v8 final de ce checkpoint : Arlington réel (5 tours) et retrait d’un
  enfant synthétique (3 tours), tous terminés, aucun rejet MCP. Profil enfants
  1 → 0 → 0 ; appels MCP enfants1 → absent → absent ; date et fenêtre10h–17h
  conservées. Ce dernier parcours conserve une autre faiblesse : budget100EUR
  supposé au raffinement « moins cher ». **Seul le retrait d’occupant est validé**.
  Le lot complet à14 conversations est v6, pas rétroactivement v8.
- Validation du code v8 : **2 201 tests passent, 1 ignoré**, ruff, mypy, guardrails
  et diff-check verts localement (Python3.13 ; CI utilise3.12). Le contrôle de
  duplication exacte entre72 développement et36 validation trouve0 recoupement,
  sans lecture humaine des conversations de validation ; quasi-doublons non exclus.

## Travail encore nécessaire

1. Revue de la PR brouillon : correctifs ciblés, pas une autorisation de bascule.
2. Étendre la validation du budget typé livré en v15 : montants écrits en lettres,
   autres devises, portée du rappel et formulation non exhaustive des résultats.
3. Lever les pertes restantes de ville explicite, les relances redondantes, les
   fenêtres ambiguës et les affirmations adultes-only / accès spa privé ou inclus.
4. Repasser suites historiques, FAQ/annulations informatives et objectifs adaptatifs
   avec référents valides. Les neuf nouveaux objectifs synthétiques de
   `datasets/b2c-history-v18-regressions.json` sont des spécifications non encore
   exécutées comme fichier adaptatif ; pas des conversations organiques.
5. Candidat figé puis 36 sessions de validation tenues à l’écart, matrice de
   préservation complète, widget/See-all/expiration/âge et revue équipe. Le code ne
   permet pas encore d’affirmer que tous les six mois de correctifs sont préservés.

Artefacts privés : campagne `production_parity_v18` du workspace legacy, manifests,
entrées/sorties, outils, traces, factures et adjudications. Aucune donnée client ou
clé dans Git. Ledger commun v17, plafond 110 USD et réserve d’arrêt 10 USD. Les timeouts
et pilotes invalides restent facturés/provisionnés. Coût au checkpoint v8 (historique, remplacé par le coût v15 plus haut) :
**70.4099 USD**, dont **9.10 USD de provisions** et **61.3099 USD
observés**. Les provisions incluent 2 USD pour la CI de cette mise à jour ; cette
somme n’est pas une consommation observée. Aucun lot modèle pending à ce checkpoint.
Aucun GO ni déploiement implicite.
