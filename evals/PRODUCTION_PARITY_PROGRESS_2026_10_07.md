# Audit historique et correctifs v18 — 7 octobre 2026

**Pas de GO remplacement production.** Le VPN fonctionne et les comparaisons live
ont repris. Des gains ciblés sont établis, mais plusieurs défauts importants
restent ouverts. Aucun merge, déploiement ou changement des modèles Railway.

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
sous50USD puis aucune offre vérifiable sur09h–17h ; San Diego ne trouve pas de
formule vérifiable sous60USD. Le candidat ne réintroduit pas une offre hors
budget. Sa phrase « only one matches » reste trop générale pour une page de
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
