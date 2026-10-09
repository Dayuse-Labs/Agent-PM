# Bilan final du 9 octobre 2026 — revue de PR, remplacement refusé

**NO GO pour fusion/déploiement en remplacement de la production.** Le candidat final présente encore des défauts de géographie et de suivi, et régresse par rapport à la version v69 publiée précédemment. Les protections et les tests ont une valeur technique, mais cette branche complète ne constitue pas une amélioration globale validée. La PR reste draft ; aucune modification Railway, fusion ni action client.

Runtime évalué : `71fdbf69ba47ac58f7ee8f19095029a2beda7a4c` ; main au gel : `cbe88b9963f28fbea932ac2a6ce23d22112f2b76`. Les **75 fichiers runtime** sont identiques sur les cinq lots. Le commit de livraison ajoute seulement ce bilan et le handoff après les évaluations.

## Évaluation effectuée

**100 conversations / 280 réponses**, toutes relues par Codex, sans juge payant supplémentaire. Les 58 trajectoires principales sont identiques à celles rejouées sur l'ancienne production le 9 octobre à partir de 05:30 UTC, déploiement `a08a7792ed95dedca6255b5c588a80a504dd6249`. Ce n'est pas une validation humaine indépendante.

| Version | A | B | C | D | F | Non notés |
|---|---:|---:|---:|---:|---:|---:|
| Production déployée | 2 | 21 | 28 | 2 | 0 | 5 |
| PR précédemment publiée v69 | 13 | 22 | 18 | 0 | 0 | 5 |
| Candidat v75 avant cette fenêtre | 8 | 26 | 21 | 0 | 0 | 3 |
| Candidat final v78 | 7 | 19 | 30 | 0 | 0 | 2 |

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
