# Bilan final du 9 octobre 2026 — revue de PR, remplacement refusé

## État actuel — v94 : NO GO maintenu

Runtime `47f13ad` : **2 conversations / 11 tours, 1 B / 1 D**. Le type de
clarification géographique est désormais conservé par le concierge et lié à sa
dernière question. Une réponse numérique ambiguë reste une demande de lieu,
sans devenir un budget ou une sélection d'ancien hôtel. Aucun regex ni phase
modèle ajouté ; les feuilles restent stateless.

Le parcours numérique reçoit une clarification géographique et aboutit à une
région nommée avec une offre vérifiée. Il contient **2 messages historiques et
2 réponses synthétiques fixes** choisies lors d'un suivi précédent. Note B sur
ce parcours seulement ; aucune stabilité générale démontrée.

Le nouveau parcours GPS contient **7 messages historiques**. L'ancre native
reste dans la province initiale sur cinq recherches, alors que les traces de
production attestent un saut vers une province homonyme après élargissement.
Mais le nouveau parcours reste **D** :

- Une demande pour la semaine suivante est étiquetée « demain » par la feuille
  de recherche et sert une date hors de la période demandée.
- Une recherche sans offre strictement moins chère est présentée comme une
  absence totale d'offres, malgré un contexte de comparaison transmis correctement.
- Quatre villes alternatives correctement extraites sont rejetées par la limite
  de trois destinations ; la clarification résultante n'exploite pas les lieux donnés.
- Une sélection ordinale revient à l'ancienne liste après le changement de lieu
  non résolu. Référent ambigu ; clarification requise, pas intention supposée.
- Le point GPS est conservé, mais aucun élargissement de rayon n'a été exécuté.

**15 cartes** correspondent aux reçus MCP exacts, sans écart de prix, jointure
ou expiration. Ce contrôle ne valide pas la pertinence de leur date. Aucun
plafond utilisateur demandé : **0 carte évaluée sur un budget explicite**.

**3 086 tests passent, 1 gate Langfuse payante ignorée** ; ruff, mypy
(79 fichiers), guardrails et diff-check passent. 79 empreintes runtime stables.
34 nouveaux échanges de production issus de 9 sessions relus ; 7 traces
Langfuse / 141 observations analysées. Statut organique non vérifié. Le contexte
GPS du rejeu est reconstitué depuis les coordonnées natives des traces servies,
avec permission accordée reconstituée ; le body navigateur original manque.
Aucune locale, devise ou timezone absente inventée. Sources privées hors Git.

Rejeu fixe et exposé, revue manuelle non indépendante. Modèles locaux : triage
GPT-5.2, recherche GPT-4o-mini, synthèse GPT-5.2 ; le triage diffère de Railway
GPT-4o-mini. Le défaut de date est observé dans une sortie 4o-mini ; celui de
fausse indisponibilité dans une sortie 5.2. Ce passage ne compare pas les modèles
et ne justifie pas à lui seul une montée en gamme.

Dernier passage complet : **v78, 100 conversations / 280 tours**. Les notes du
petit lot courant ne prouvent aucune supériorité globale. Restent les corrections
ci-dessus, un passage complet sur le code final et un jeu adaptatif séparé.
FAQ/SAV restent en phase 2.

Coût v94 **0.2363 USD** ; cumul **149.3555 / 150 USD**, dont
7,10 provisionnés. Disponible après réserve : **0.1445 USD**.
Services possédés arrêtés, aucune dépense en attente. Extension de 10 USD demandée,
non autorisée. CI GitHub bloquée avant toute étape par facturation/plafond Actions
sur le précédent head, run 37975668283. Aucun merge ni déploiement.

## Dernier rejeu groupé — v91, 9 octobre

Runtime `e9fd132` : **4 conversations / 14 tours, 2 B / 2 C contre 4 C**
sur les mêmes messages en v90. **NO GO maintenu** : aucun nouveau passage
complet historique ni preuve de supériorité globale.

- Code postal : résolution fournisseur typée, parent conservé, même point
  recherché après la réponse de ville. Plus de confusion entre pays. Reçus
  MCP vides pour la date du jour : le classement « moins cher » n'est pas évalué.
- Distance : permission de30km effectivement envoyée à MCP. Fin24:00 gardée ;
  cinq offres jusqu'à23:00/23:30 affichées comme alternatives non conformes
  à la borne exacte. Rayon à vol d'oiseau et horaires différents explicités.
- Repères alternatifs : recherchés ensemble dès la première destination
  explicite, sans obligation de choisir un seul. Les relances restent peu
  utiles sur huit tours sans offre ; inventaire vide et recovery à distinguer.
- Nombre géographique : question du lieu mieux priorisée, mais le garde-fou
  numérique oublie encore une destination typée pourtant reconnue au triage.
  Aucun budget inventé ; parcours toujours C et correctif complémentaire requis.

5 cartes reliées aux reçus MCP exacts,0écart prix/jointure/expiration.
Aucun plafond demandé :0carte budget évaluée.78empreintes runtime stables.
3070tests passent/2ignorés ; contrôle Node ensuite relancé :16tests du fichier
passent, incluant le contrat JS. Gate Langfuse payante non exécutée. Ruff,
mypy78,guardrails verts. Services possédés arrêtés, aucune dépense en attente.

Coût **0,2917USD**, cumul **148,9859/150USD**, dont7,10provisionnés ; disponible
après réserve0,50 :0,5141USD. Extension10USD demandée, pas encore autorisée.
Revue Codex non indépendante, cas exposés et trajectoires fixes ; contexte natif
identique, inventaire frais susceptible de changer. GPS absent non inventé.
Configuration locale triage5.2/recherche4o-mini/synthèse5.2, distincte du triage
Railway4o-mini. Dernier passage complet100/280toujoursv78. Aucun merge/déploiement.

Les sections suivantes sont des campagnes historiques sur leurs propres runtimes.

## Dernier complément — v90, conversations fraîches

Commit `2f3c9d4`, runtime identique à `9991aa1` : **4 conversations /14 tours,
4C**, contre4C sur les réponses de production d'origine, avec défauts différents.
Pas de supériorité ni d'équivalence globale démontrée. Clarification sur le groupe
avant le lieu, résolution de code postal, élargissement30km non appliqué et
ville parente traitée comme destination supplémentaire restent insuffisants.
Les générations enregistrées soutiennent ces diagnostics ; correctifs à faire.

4cartes jointes aux reçusMCP exacts sans écart de prix/jointure/expiration.
Aucun budget explicite : aucune carte évaluée pour ce critère.77hashes runtime
inchangés. Trajectoires fixes, non adaptatives ; contexte navigateur absent non
inventé ; premier tour GPS non comparable. Revue Codex non indépendante.

Coût **0,2812USD** ; cumul **148,6942/150USD**, dont7,10provisionnés.
Services possédés arrêtés, ledger sans pending. CI du commit2f3c9d4 réussie
(run37969333761), checks offline exécutés et étapes live ignorées.
Les8conversations/23tours des lotsv89+v90 ont coûté0,4488USD. **NO GO maintenu.**
Le passage complet historique100/280 demeure requis après corrections.


## État courant — v89, 9 octobre à 17:51 UTC

Runtime `9991aa1` : **4 conversations / 9 tours, 2 B / 2 C**, contre 1 B / 3 C
sur les mêmes parcours en v88. Un contrôle synthétique adresse → budget → horaires
passe de C à B ; Voorhees et la contestation JFK restent C, Biltmore reste B.
Revue Codex non indépendante, corpus exposé ; aucune supériorité globale prouvée.
Le dernier passage complet 100/280 reste v78, décrit plus bas comme historique.

Depuis le précédent head publié : vérification d'identité commune/aéroport,
alternatives de repères conservées avec recherches bornées indépendantes,
clarification du total de voyageurs, adresses typées vérifiées composant par
composant, minutes exactes affichées, contexte combiné budget/horaires dans les
réponses vides et alignement MCP sur le filtre horaire partagé. Pas de nouvelle
regex, de dictionnaire géographique ou de phase modèle ajoutée.

Le point adresse est conservé sur trois recherches. Le dernier tour vide cite
les critères, mais a emprunté la synthèse habituelle : son amélioration ne prouve
pas causalement la nouvelle branche déterministe budget_no_verified_offer,
couverte par tests hors ligne. Les recherches MCP utilisent 11–19 pour la
fenêtre 10:30–19 selon la règle arrondie du site ; cela n'autorise pas à présenter
une arrivée11h comme une correspondance littérale10h30. Les décalages restent à
signaler. Le nombre d'offres peut varier avec le modèle et l'inventaire frais.

**3029 tests passent / 1 gate live optionnelle ignorée**, ruff/mypy77/guardrails
verts.77empreintes runtime identiques pendant le lot.12cartes reliées aux reçus
MCP exacts sans anomalie de prix/jointure/expiration ;5cartes budget conformes
frais compris. Ces contrôles ne prouvent ni rappel inventaire ni pertinence globale.

Coût du lot **0,1676USD** ; cumul **148,4130/150USD**, dont7,10provisionnés,
réserve0,50USD. Services locaux possédés arrêtés, aucun coût en attente.
43nouveaux échanges de production/19sessions relus ; deux traces Langfuse
(31observations) inspectées. Une relance espagnole conserve la ville dans le
profil mais le guard recherche la refuse ; une réponse numérique de localisation
ajoute à tort un budget alors que l'extraction monétaire est nulle. Ces cas ne
sont pas des attentes à reproduire et n'ont pas encore été rejoués sur v89.
Statut organique des sessions non vérifié ; aucun contenu brut ajouté au dépôt.

**NO GO maintenu.** Restent la récupération après clarification, les contestations,
les alternatives hôtel/ville, les zones après relance et un nouveau passage
historique complet. Configuration locale inchangée (triage5.2/recherche4o-mini/
synthèse5.2), différente du triage Railway4o-mini. Aucun merge/déploiement.
Les sections suivantes documentent les passages antérieurs avec leurs propres
runtimes ; leurs chiffres ne sont pas les résultats du head actuel.


## Complément final — correctifs localisés, NO GO maintenu

Runtime `e4b5c37` : les noms de ville explicitement demandés ne sont plus perdus
si la preuve globale suffit ou si une région optionnelle non mentionnée a été
ajoutée. Les preuves de cible explicitement invalides restent refusées. Sur les
280 sorties triage enregistrées du passage complet, six transactions changent,
274 restent identiques. Ce contrôle offline n'est pas un nouveau rejeu utilisateur.

Une question sur les offres reprend l'unique hôtel affiché si aucun autre nom,
changement de lieu ni clarification géographique en attente ne contredit cette
référence. Le suivi Biltmore donne maintenant les huit créneaux du bon hôtel et
de la bonne date, vérifiés contre MCP. Cette référence sert uniquement aux
faits : aucune sélection ou confirmation de réservation n'est créée.
Aucun champ, regex, prompt, modèle ou appel LLM supplémentaire ajouté.

**7 conversations /21 tours rejoués intégralement : 4B/3C**, revue Codex non
indépendante. Ce sous-ensemble exposé ne remplace pas les scores du dernier
rejeu complet v78 ci-dessous. Budapest/San Bruno/Red Deer et le suivi horaires
Biltmore fonctionnent sur ce passage ; Edison reste partiel, Annapolis ambigu,
le parcours enfants/jacuzzi insuffisant et le suivi Rambler instable. Les essais
intermédiaires sont conservés : v79 cinq parcours3B/2C, v80 sept parcours2B/5C.
Une réussite isolée n'est pas une preuve de stabilité ni de supériorité sur la prod.

**2932 tests passent /1 gate live ignoré**, ruff/mypy75/guardrails/diff-check verts.
32 cartes exactes MCP,0 anomalie de jointure/prix/expiration ;4 cartes sous
plafond conformes frais compris. Ces contrôles ne certifient pas la pertinence.
Les75 fichiers runtime sont restés figés pendant le dernier passage.

Trois rejeux complémentaires : **1.1074USD**, dernier passage
**0.3934USD**. Fenêtre totale **10.0276USD** ; cumul
**145.2605/150USD**, dont7,10provisionnés, ledger sans pending. Aucun service
Railway modifié, aucun merge/déploiement ; services d'évaluation possédés arrêtés.
Le rapport HTML privé présente toutes les réponses avant/après. Aucun transcript
client ajouté au dépôt. Main revérifié : `cbe88b9`.

**NO GO pour fusion/déploiement en remplacement de la production.** Le candidat du dernier rejeu complet présente encore des défauts de géographie et de suivi, et régresse par rapport à la version v69 publiée précédemment. Les protections et les tests ont une valeur technique, mais cette branche complète ne constitue pas une amélioration globale validée. La PR reste draft ; aucune modification Railway, fusion ni action client.

Runtime évalué : `71fdbf69ba47ac58f7ee8f19095029a2beda7a4c` ; main au gel : `cbe88b9963f28fbea932ac2a6ce23d22112f2b76`. Les **75 fichiers runtime** sont identiques sur les cinq lots. Ce runtime désigne le passage complet v78 ; les correctifs ultérieurs et leur validation ciblée sont décrits ci-dessus.

## Évaluation effectuée

**100 conversations / 280 réponses**, toutes relues par Codex, sans juge payant supplémentaire. Les 58 trajectoires principales sont identiques à celles rejouées sur l'ancienne production le 9 octobre à partir de 05:30 UTC, déploiement `a08a7792ed95dedca6255b5c588a80a504dd6249`. Ce n'est pas une validation humaine indépendante.

| Version | A | B | C | D | F | Non notés |
|---|---:|---:|---:|---:|---:|---:|
| Production déployée | 2 | 21 | 28 | 2 | 0 | 5 |
| PR précédemment publiée v69 | 13 | 22 | 18 | 0 | 0 | 5 |
| Candidat v75 avant cette fenêtre | 8 | 26 | 21 | 0 | 0 | 3 |
| Dernier rejeu complet v78 | 7 | 19 | 30 | 0 | 0 | 2 |

A = parfait, B = défaut mineur, C = significatif, D = majeur, F = critique. Les notes portent sur la conversation complète ; absence d'offre n'est pas à elle seule un échec. Les tours devenus non comparables après une branche différente sont signalés dans les preuves privées.

Compléments :

- Géographie historique : **24 conversations / 72 tours**, 12 préservées, 8 partielles, 4 échecs. Ces verdicts évaluent uniquement l'attendu géographique, pas toute la qualité de la conversation.
- Trois conversations supplémentaires / 7 tours : 1 B, 2 C.
- Dix autres historiques / 18 tours : 3 B, 5 C, 2 non notées.
- Cinq parcours du dernier export / 20 tours : 3 B, 2 C.

## Changements et résultat concret

Le concierge conserve son profil Redis ; les feuilles A2A restent stateless et l'inventaire passe par MCP. Les contraintes typées, les preuves d'offre et les coordonnées fournisseur appartiennent à des champs distincts. LiteLLM et le budget de phases existants sont conservés. Aucun regex, dictionnaire de villes ou appel LLM supplémentaire ajouté dans ce dernier lot ; des fallbacks historiques du projet subsistent.

- Horaires précis prioritaires sur un simple moment de journée ; durée explicite mémorisée, demande traversant minuit conservée jusqu'à remplacement explicite.
- Identité de l'hôtel nommé conservée pour les suivis ; une carte d'identité sans offre ne prouve pas une disponibilité.
- Prix nul sans preuve commerciale de gratuité exclu des cartes et comparaisons.
- Une transaction géographique structurée distingue changement, précision, correction et conservation, avec ville/État, quartier et repère. Les coordonnées et appartenances restent vérifiées via le fournisseur.
- Clarification géographique non masquée par une question de devise après le retour du leaf. Cela corrige le diagnostic antérieur trop large « devise avant géocodage » : le problème observé était aussi un masquage après résolution échouée.

Le rejeu confirme des progrès sur l'heure de fin 18 h, une heure de séjour, Milan et ses alentours, l'union de quartiers après précision de Rio, et l'hôtel Rambler après précision de Hong Kong. Mais des cas auparavant satisfaits régressent : premiers tours de villes, Heathrow/Vienne, Dublin centre, détail des horaires d'un hôtel nommé. **Ne pas fusionner la refonte géographique simplement parce que les tests offline passent.**

## Blocages de recherche encore présents

- Repères et parents : LAX/Halm Boulevard perdent leur ville parente ; JFK/Heathrow/Vienne peuvent demander une ville déjà identifiable. Philadelphia airport reste parfois du texte avec distances calculées depuis le centre-ville.
- Quartiers, régions et corridors : Brooklyn/Manhattan/Dublin centre/Berlin Mitte/Al Mankool peuvent rester bloqués ; codes postaux et corridors non aboutis ; rejet géographique trop générique.
- Identité fournisseur : convention centre d'Auckland accepté sous une autre identité de centre de convention. Une réponse fournisseur ne suffit pas à prouver le bon établissement.
- Suivi : hôtel reconnu puis perdu à la question horaires ; objections brèves et prix moins cher sans shortlist mal récupérés.
- Contraintes fines : offres débutant à 10 h 30 encore mises en avant pour 10 h malgré avertissement ; jacuzzi privé, accès inclus, durée de route et certains débuts en langage naturel non garantis. Les corrections structurées ne prouvent pas que chaque extraction est correcte.
- Pays ambigu : une interprétation automatique de Halifax comme Canada reste possible sans confirmation ; la devise du client ne constitue pas à elle seule la destination.

FAQ, annulations et SAV sont phase 2. Les anciens fichiers FAQ du diff cumulé ne sont pas certifiés par cette campagne ; un mauvais routage d'une recherche vers FAQ reste toutefois un défaut de phase 1.

## Vérifications et budget

**2 892 tests passent, 1 gate Langfuse live ignoré** ; ruff, mypy (75 fichiers), guardrails et diff-check passent.

- 300 cartes jointes aux reçus MCP exacts hôtel/UUID/date/créneau : 0 sans correspondance, 0 écarts de prix, 0 expirées.
- 34 cartes avec plafond enregistré contrôlées frais compris : 0 dépassements et 0 invérifiables. Un budget perdu avant enregistrement n'entre pas dans ce contrôle.
- 254 distances recalculées, 0 écarts arithmétiques. Ce n'est pas une preuve du bon point d'origine ni d'un temps de trajet.
- 2 écarts de minutes signalés ; les cartes incompatibles restent un défaut produit. Aucun score global de sécurité n'est déduit de ces audits.

Les métriques comptent 832 complétions modèle réussies et 1 à 3 phases logiques par tour : le leaf peut appeler plusieurs fois le modèle à l'intérieur d'une phase. Médiane locale 6,69 s, p95 11,56 s ; pas de comparaison de latence valable avec la prod séquentielle. 103 événements outil marqués erreur (91 géocodage, 10 recherche, 2 FAQ) incluent les refus de résolution/validation ; ce ne sont pas 103 pannes réseau. Aucune erreur d'appel modèle enregistrée sur le passage final. Une capacité manque sur une carte de détail ; aucune capacité insuffisante parmi les cartes vérifiables, sans certifier les demandes enfants non structurées.

Passage complet final : **5.3015 USD**. Fenêtre de livraison : **8.9202 USD**, diagnostics et provisions compris. Cumul suivi : **144.1531 / 150 USD**, dont **7.10 USD provisionnés**, réserve opérationnelle 0,50 USD. Ledger sans pending. Télémétrie, pas facture ; hors Codex, infrastructure et éventuelle CI. Les tentatives antérieures ne sont pas effacées : v77 a été arrêté après 54 réponses sur une régression ville/État, coûts réconciliés ; seul v78 est le passage complet final.

## Configuration et limites d'interprétation

Candidat testé : triage **gpt-5.2 / low / 2048 tokens / timeout 15 s**, recherche **gpt-4o-mini**, synthèse **gpt-5.2**. Railway B2C observé le 9 octobre conserve **triage 4o-mini**, recherche 4o-mini, synthèse 5.2. Ancienne prod : **gpt-5.2**. Aucun modèle Railway changé. Fusionner le code seul ne reproduirait donc pas la configuration évaluée. Le contrôle de modèle v76 était mixte ; **pas de justification d'un upgrade global**, le candidat final combine changement de code et configuration.

Les trajectoires sont fixes, les tours séquentiels, deux sessions indépendantes en parallèle. Ce n'est pas un utilisateur adaptatif ni un A/B simultané. Tous les 100 parcours sont maintenant exposés : régression, aucun holdout aveugle. Le corpus ne couvre pas exhaustivement six mois de données ni chaque ancien correctif. Expiration de session, injections de pannes de transport, ownership et confirmation réelle des actions ne sont pas validés en live dans ce passage.

Production export/Qdrant versus MCP préproduction, déclaré reflet exact de production par l'équipe : fraîcheur/récupération/heure diffèrent. Cache des réponses fournisseur de géocodage dans le harnais ; inventaire MCP relu sans cache du proxy. Les champs GPS/devise/fuseau absents des exports ne sont pas inventés ; quelques fixtures GPS et scénarios synthétiques sont explicitement identifiés. Dernier export applicatif à 11:48 UTC : 34 363 lignes au total, 2 000 retournées ; ce n'est pas un nouveau dump SQL exhaustif.

Les traces Langfuse historiques ont servi à contextualiser les sources. Le lanceur local désactive leur export pour ces replays ; métriques, réponses, profils, reçus et hashes locaux constituent les preuves. Les sorties brutes du triage final ne sont pas archivées dans Langfuse : ne pas attribuer avec certitude toute panne à un champ modèle sans diagnostic supplémentaire.

Les transcriptions et preuves détaillées restent privées, hors Git. Le rapport local `production_parity_v18/current_evaluation.html` montre les 100 conversations ; sur les 58 principales, production et candidat figurent côte à côte. HTML analysé en source, sans rendu visuel navigateur.

## Registre des défauts significatifs du lot principal

Les identifiants ci-dessous permettent de retrouver les preuves privées sans publier les conversations clientes.

| Cas | Défaut observé |
|---|---|
| 2 · `holdout-74b956ea3e1a7fc8` | Budapest déclenche une clarification générique de destination injustifiée; budget ensuite conservé mais parcours peu utile. |
| 3 · `holdout-b1ce7fbdf24e645b` | Fin 18h, douche et deux adultes conservés; le suivi LAX perd la ville et impose une clarification évitable au lieu de rechercher autour de l'aéroport. |
| 4 · `holdout-93277644d97e4852` | San Antonio/Texas résolu comme une ville et budget 40 USD appliqué; les deux codes postaux successifs ne sont pas intégrés à la zone. |
| 5 · `holdout-2809855ca5548fd9` | Date et budget EUR préservés sans fausse disponibilité; réponse identique à l'objection de disponibilité, sans solution de suivi. |
| 6 · `holdout-92d1d0dcb10d8d41` | Piscine, budget et occupation préservés; corridor Smyrna–Acworth non traité et clarification générique peu exploitable. |
| 8 · `holdout-efeb0cdc930d7f2d` | Fayetteville NC finalement résolu correctement; deux clarifications génériques successives sur le corridor et besoin initial de chambre thématique non résolu. |
| 9 · `holdout-f2f1622848dd80a2` | Brooklyn identifié mais recherche bloquée comme zone trop large; budget dollar non résolu et aucune option après trois tours. |
| 10 · `holdout-d4a34235ab399d8d` | Faute Lower Manhatten non résolue; nombre 200 clarifié prudemment mais aucun aboutissement géographique. |
| 13 · `holdout-0b29daa0abbc6cd7` | Créneau 17–23 conservé; alternatives Tuen Mun/Tung Chung non résolues malgré parent Hong Kong, recherche moins chère bloquée. |
| 15 · `holdout-7619238f09035b85` | Al Mankool conservé comme sous-zone de Dubai et 13h demain préservé, mais résolution toujours bloquée après clarification explicite. |
| 21 · `holdout-ca85ca81818ed73f` | Clarification générique injustifiée au premier tour San Bruno; second tour récupère ville et budget USD avec total incluant frais. |
| 22 · `holdout-e7ebdc270a65b19b` | Budget 80 EUR et date conservés; demande répétée de montant/devise déjà connus puis boucle de réponses sans alternatives. |
| 23 · `holdout-a79808b0ca0babe4` | Red Deer déclenche une clarification générique injustifiée; demain récupère correctement ville et date. |
| 25 · `holdout-39a54953510f835c` | New Jersey et Bergen County correctement reconnus comme régions; suivi vers GW Bridge perd la contrainte de proximité et reste bloqué deux tours. |
| 26 · `holdout-c4e9b80bc86b2dbc` | Hôtel de Trieste annoncé comme alternative distante; après demande nocturne, carte 11–18 reste affichée malgré incompatibilité reconnue dans le texte. |
| 29 · `holdout-0048c180dc610be4` | Adresse conservée après Madrid mais fournisseur résout un autre lieu; rejet prudent sans hôtel erroné, parcours bloqué jusqu'au quatrième tour. |
| 30 · `holdout-1f69121a2a1a58f5` | Washington DC retrouvé mais sauna initial non enregistré comme contrainte; propose piscines comme alternatives sans répondre au besoin sauna/spa, tout en signalant l'absence de preuve. |
| 31 · `holdout-650a7ee342f64a4c` | La Quinta San Antonio présent mais pas sélectionné exclusivement; suivi Halm Blvd perd le parent San Antonio et redemande la ville. |
| 33 · `holdout-2cd9246e21cb9917` | Dates et remplacement 09h30–19h par 09–18 conservés; airport ne déplace pas l'origine, distances et tri restent centrés sur Philadelphia malgré demande de proximité aéroport. |
| 36 · `fresh-v50-bf9ee2ff35f5b7fb` | Jacuzzi et Den Bosch conservés, aucune offre inventée; phrase d'alternative tronquée et objection de proximité mal comprise. |
| 37 · `fresh-v50-7e9def1de19c668e` | Deux adultes et alternative de villes conservés; Lisbonne mal orthographiée non résolue, résultats limités à Porto avec couverture partielle annoncée. |
| 42 · `fresh-v49-c3030b5436d76d57` | Vienne-Schwechat explicitement nommé mais clarification répétée ville/aéroport au lieu de rechercher; 13–18 correctement conservé sans aboutissement. |
| 43 · `fresh-v39-0c597d7ce05c9c5e` | Fin20h, date et deux adultes conservés; passage GPS puis détails ancienne shortlist fonctionne, mais moins cher réintroduit verbalement Île-de-France et propose élargissement hors région malgré origine GPS active. |
| 46 · `geo-v43-named-heathrow` | Heathrow explicitement nommé non résolu; demande terminal ou autre ville et ne présente aucune offre, recul face au précédent ancrage aéroport. |
| 48 · `synthetic-usd-cheaper-explicit-city-v47c` | Manhattan New York explicitement donné reste non résolu après cinq tours; date, heures et plafond USD mémorisés mais recherche et affichage USD bloqués faute de shortlist. |
| 50 · `synthetic-children-capacity-retraction` | Rétraction enfant1→0 conservée au suivi moins cher. Deux cartes commencent10h30 pour demande10h; écart signalé mais offre incompatible57EUR mise en avant comme meilleure économie. |
| 51 · `fresh-v53-8ee27e5a0b03c2a4` | Jacuzzi conservé mais Cph non résolu malgré suggestion Copenhagen; pas d'offre ni ancrage utilisable. |
| 53 · `global55-dublin-centre` | Dublin centre reste un sous-périmètre non résolu malgré ville explicite; plafond150EUR et piscine conservés mais trois tours bloqués sans offres. |
| 56 · `global55-hotel-typo` | Biltmor corrigé en Biltmore au premier tour, puis question sur les horaires perd la sélection et demande le nom déjà connu. |
| 58 · `fresh-v61-e424532e56` | Amélioration:18h reste conservé après evening sur cinq tours. Jacuzzi privé non distingué et rayon35minutes proposé sans calcul de trajet; boucle de réponses sans alternatives vérifiées. |
