# Dayuse B2C changements par demande client et comparaison avec la production

Cette synthèse s’adresse à l’équipe produit et technique qui doit revoir la PR et préparer le remplacement de l’agent historique. Elle explique les changements par demande client, leur raison et les preuves disponibles au 12 octobre 2026.

**Le candidat évalué progresse sur le corpus historique : 73 parcours A/B contre 48 pour la production de référence. Il conserve toutefois 27 défauts significatifs et affiche moins souvent des hôtels. Les derniers correctifs de la PR passent les tests locaux, mais attendent leur rejeu complet.** La PR est prête pour revue, pas encore validée pour une bascule générale.

[PR 134 — contexte conversationnel et offres MCP](https://github.com/Dayuse-Labs/AgentB2C/pull/134). Le comparatif porte sur la production exécutée le **10 octobre**, pas sur un nouveau test du déploiement du 12 octobre. Les exemples de demandes ci-dessous illustrent les comportements attendus ; ils ne sont pas des transcriptions client.

## Ce que donne le candidat face à la production

Les deux agents ont traité 100 parcours et 280 messages chacun. Les notes suivent la grille historique : A parfait, B défaut mineur, C significatif, D majeur, F critique.

| Mesure | Production de référence | Candidat évalué |
| --- | ---: | ---: |
| A parfait | 7 | 10 |
| B défaut mineur | 41 | 63 |
| C défaut significatif | 44 | 27 |
| D ou F | 8 | 0 |
| Total A/B | 48 sur 100 | 73 sur 100 |
| Réponses contenant des cartes hôtel | 142 sur 280 | 84 sur 280 |
| Occurrences de cartes affichées | 603 | 299 |
| Latence médiane | 10,38 s | 4,87 s |
| Latence p95 | 15,10 s | 8,07 s |
| Coût modèle observé pour les 100 parcours | 5,63 USD | 5,73 USD |

**43 parcours sont mieux notés, 14 moins bien, 43 identiques.** Le gain de 25 points de A/B est descriptif. Il ne signifie pas 25 % de conversion en plus, ni que les 14 écarts ont été résolus depuis.

Le candidat répond plus vite dans ce test, mais une clarification sans résultat peut être rapide. La baisse de fréquence des cartes est un vrai sujet de lancement ; elle peut mêler prudence, surclarification et différences de recherche/inventaire. Le test ne sépare pas leurs contributions. Le nombre de conversations exécutées en parallèle diffère aussi entre les lots.

Sur les 299 occurrences du lot candidat final, **298 offres datées sont reliées aux réponses MCP**, plus une carte d’identité hôtel sans disponibilité confirmée. Aucun écart de prix, de faits de carte ou d’expiration n’a été détecté dans cet audit ; 246 distances et 28 plafonds avec frais ont été contrôlés. Cela ne garantit pas la justesse de toute la prose ni le rappel exhaustif des hôtels. [Comparatif et mesures](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/evals/PRODUCTION_PARITY_2026_10_10.json).

## Chercher dans une ville un quartier ou près de soi

**Demande type :** « À New York, puis plutôt Newark… finalement Manhattan » ou « près de moi ».

**Pourquoi changer :** un affinage pouvait perdre sa ville parente, réutiliser une ancienne ancre ou confondre une zone demandée avec un lieu réellement confirmé. Un homonyme ne doit pas être résolu uniquement par la langue ou le GPS.

**Ce que la PR change :** demande géographique, choix en attente et identité fournisseur vérifiée sont séparés. La localisation du navigateur, la destination explicite et la proximité ont des rôles distincts. Une résolution échouée ne peut pas enregistrer les coordonnées provisoires comme vérité. Quartier, municipalité, département et proximité sont vérifiés selon leur portée ; rester dans un quartier n’équivaut pas à chercher aux alentours.

**Dernier complément :** le dernier lieu vérifié reste un indice interne pendant un changement de destination. Il peut aider à interpréter Manhattan, mais ne doit pas imposer ses coordonnées ou son pays à une nouvelle demande.

**Validation et limites :** résolution de Berlin Mitte observée dans les parcours complet et adaptatif ; contrat de changement de pays testé localement. Le dernier test isolé de triage retrouve le parent de Manhattan, sans rejouer toute la recherche. Dublin centre, certains quartiers, les homonymes et les fautes de noms restent à surveiller.

## Recherche par aéroport adresse ou points multiples

**Demandes types :** « près d’un aéroport » puis « Rome » ; « Heathrow Terminal 3 » ; « près de ces deux codes postaux » ; « à pied de cette adresse ».

**Pourquoi changer :** une ville pouvait effacer le besoin aéroport, deux lieux devenir une question générique, ou une adresse partielle déclencher une nouvelle demande des composants déjà fournis.

**Ce que la PR change :**

- Le besoin aéroport persiste dans la clarification du concierge. Une ville peut préciser son parent ; elle ne vaut pas automatiquement accord pour des hôtels du centre-ville.
- Un terminal peut être proposé à confirmer si son identité, sa catégorie et son numéro viennent du fournisseur. Aucun remplacement silencieux par un arrêt de bus ou le centre de l’aéroport.
- Deux points restent mémorisés. Sans recherche simultanée vérifiable, l’agent demande lequel privilégier ou quel repère intermédiaire précis utiliser.
- L’adresse et ses composants restent liés. Si la ville manque, la question porte sur la ville/pays plutôt que de redemander systématiquement numéro et rue.
- Un rayon est attaché à son origine vérifiée ; une distance à vol d’oiseau n’est pas présentée comme un temps de marche.

**Validation et limites :** tests de contrats et de suivi sur deux tours. Le reçu Heathrow conservé fournit deux vrais choix de terminal, sans sélection automatique. Ce dernier correctif n’a pas encore de rejeu complet MCP. Une adresse composite madrilène échouait encore dans le parcours adaptatif. Les fautes et abréviations comme Cph ne sont pas déclarées résolues.

## Modifier une date un créneau ou une durée

**Demande type :** « Mercredi de 15 h à 18 h », puis « plus tard et moins longtemps », ou « demain avec piscine ».

**Pourquoi changer :** les heures pouvaient être prises pour une date, une nouvelle contrainte effacer le jour, ou « dispo demain » devenir une période indéfinie.

**Ce que la PR change :** la date, la période non résolue, les heures et la durée sont des contraintes distinctes. Leur provenance et leur mise à jour sont contrôlées avant la recherche. Les formules doivent correspondre au jour et couvrir le séjour demandé selon le contrat du site. Une alternative au créneau exact doit être explicitement présentée comme telle, avec ses heures réelles.

**Dernier complément :** une extraction de flexibilité doit préciser qu’elle concerne les dates. Une réponse telle que « aucune » à une question composée ne doit plus ouvrir une période sans sujet.

**Validation et limites :** conservation de mercredi et 15–18 observée ; les neuf alternatives de minutes du lot complet ont toutes été annoncées. Les deux anciennes erreurs de flexibilité sont reproduites puis rejetées au niveau du contrat ; les vraies plages restent à clarifier. Le nouveau traitement dépend encore de la bonne extraction du modèle et attend son rejeu complet.

## Fixer un budget demander moins cher ou changer de devise

**Demande type :** « Moins cher que celui-ci », « 150 dollars maximum, frais compris », « 30 euros de l’heure » ou « affiche dans la devise de l’hôtel ».

**Pourquoi changer :** montant saisi, plafond de recherche MCP, devise affichée et prix de référence pouvaient être confondus. Le prix de l’hôtel consulté ne doit pas être remplacé par celui d’une autre formule.

**Ce que la PR change :** un budget conserve montant, devise et unité ; une demande relative utilise une offre précédemment affichée comme référence. Les contrôles portent sur la même formule datée et ses frais connus. Aucun taux de change n’est inventé. Les prix euro et devise hôtel viennent des champs indexés de cette offre ; les formules alternatives gardent chacune leur prix. Le contexte navigateur transporte aussi devise, locale et fuseau, sans transformer ces informations en preuve géographique.

La séparation euro/devise hôtel existait déjà dans le nouvel agent : la PR l’étend aux formules alternatives et fiabilise son articulation avec le budget. Elle n’introduit pas un service de conversion universel.

**Validation et limites :** 28 plafonds avec frais vérifiés sans violation dans le lot complet. Un total incomplet reste non confirmé. Un nombre isolé après une question de lieu ne devient pas automatiquement un budget : le dernier correctif demande son rôle.

## Affiner comparer et renouveler les résultats

**Demande type :** « Le premier », « et son offre ? », « un autre moins cher », puis « pas forcément moins cher, juste d’autres hôtels ».

**Pourquoi changer :** consulter un détail pouvait remplacer la liste de recherche utilisée pour les choix suivants. Un nouveau filtre pouvait aussi conserver une pagination devenue invalide.

**Ce que la PR change :** la liste de recherche et l’hôtel consulté sont mémorisés séparément. Les références de comparaison, l’identité de l’hôtel et l’offre datée restent explicites. « D’autres hôtels » conserve le curseur seulement si les critères n’ont pas changé ; modifier la literie, le groupe ou d’autres contraintes repart du début.

**Dernier complément :** un verdict de triage « ne veut pas d’autres options » prime sur le mot-clé lexical, afin qu’une négation ne fasse pas avancer la page.

**Validation et limites :** tests de suivi et reprises ciblées, puis comparaison complète sur la version évaluée. Le durcissement lexical final est couvert localement. Des réponses restent trop génériques après un échec et certaines continuations historiques répondent à une question que seul l’ancien agent avait posée.

## Demander une piscine un spa ou un type de chambre

**Demande type :** « Avec piscine intérieure », « jacuzzi privé inclus », « un lit double », puis « enlève le spa ».

**Pourquoi changer :** posséder une piscine ne prouve pas que l’accès est inclus dans la formule ; une caractéristique d’hôtel ne prouve pas l’équipement de la chambre réservée.

**Ce que la PR change :** préférences de chambre et besoins d’accès persistent dans le profil. La literie s’appuie sur la formule fournisseur ; présence, accès, gratuité et caractère privé sont distincts. Les retraits de filtres sont appliqués à la recherche. La réponse doit conserver l’incertitude quand la preuve d’accès manque.

**Validation et limites :** le parcours adaptatif piscine conserve date, budget et groupe et maintient l’incertitude sur l’accès. En revanche, une réponse de détail d’un autre parcours promettait encore un accès inclus après une réserve ; piscine intérieure peut encore être ramenée à piscine générique. C’est un défaut restant de fidélité à la demande, malgré l’intégrité des cartes.

## Chercher pour plusieurs adultes ou avec des enfants

**Demande type :** « Nous sommes quatre », puis « un adulte et deux enfants ».

**Pourquoi changer :** demander toute la composition avant d’explorer pouvait créer une boucle ; supposer une capacité à partir du nom de chambre pouvait afficher une offre inadaptée.

**Ce que la PR change :** total annoncé, adultes et enfants sont distingués. Une découverte conditionnelle est possible sans inventer la répartition. Les capacités viennent des champs de la formule, avec traitement explicite des informations inconnues et des changements de groupe.

**Validation et limites :** aucun dépassement de capacité détecté dans le lot complet contrôlé. Quatre cartes de détail du complément adaptatif n’exposent pas la capacité dans leur payload : elles ne sont pas validées sur ce critère. Les âges limites et tous les cas de politique enfants ne sont pas couverts exhaustivement.

## Retrouver un hôtel nommé et préparer une réservation

**Demande type :** « L’offre de cet hôtel à Miami », « confirme », ou « je ne confirme pas ».

**Pourquoi changer :** une identité d’hôtel n’est pas une disponibilité datée ; une faute dans le nom ne doit pas conduire à une identité inventée. Le mot « confirme » dans une question ou une négation ne suffit pas à autoriser un lien.

**Ce que la PR change :** les recherches et détails conservent l’identité fournisseur ; prix, date, horaires et caractéristiques restent liés à la même offre. L’identité seule peut être présentée sans promettre de disponibilité. La ville explicitement extraite d’une demande d’hôtel est conservée séparément.

Le garde de confirmation respecte d’abord questions et refus reconnus. Après triage absent ou classé « none », un verbe isolé ne suffit plus ; le « oui » court devant une offre en attente reste accepté.

**Validation et limites :** identité contre offre vérifiée dans les contrôles et le complément adaptatif. Le nom d’hôtel mal orthographié reste mal extrait dans le dernier test réel : contrat amélioré ne signifie pas récupération réussie. Les tests ne valident pas un parcours de réservation authentifié ni un achat réel. Le garde concerne la génération du lien.

## Répondre sans résultat et traiter les FAQ

**Demande type :** « Il n’y a rien ? », « est-ce inclus ? », « comment annuler ? ».

**Ce que la PR change :** un échec de résolution, une recherche bornée sans offre et une indisponibilité outil doivent conduire à une réponse adaptée. L’absence de résultats de la requête ne prouve pas l’absence totale d’hôtels ; l’origine fine et les contraintes ne doivent pas disparaître pendant la récupération.

**Limites :** récupération encore trop répétitive à Budapest, informations d’accès non vérifiables et quelques changements de langue. Aucune couverture de marché n’est inventée à partir de l’ancien export. **FAQ, annulations et SAV restent en phase 2**, conformément au périmètre retenu ; cette PR ne justifie pas leur remplacement en production.

## Ce qui est repris de la production sans remplacer la nouvelle architecture

L’expérience de production est transférée en règles explicites et en tests : conserver les préférences utiles, compléter plutôt qu’effacer le contexte, distinguer demande et preuve, n’enregistrer un lieu qu’après vérification, garder les contre-exemples historiques.

| Responsabilité | Nouvelle architecture conservée |
| --- | --- |
| Mémoire de la conversation | Un profil Redis détenu par le concierge, persistant entre les tours de la session |
| Compréhension | Triage existant avec intentions et champs structurés |
| Décisions | Code déterministe pour mises à jour, clarifications, routage et garde-fous |
| Recherche et FAQ | Feuilles A2A sans état ; elles ne deviennent pas propriétaires du profil |
| Lieux et offres | Identités géographiques fournisseur et réponses MCP liées aux requêtes |
| Réponse au client | Une synthèse à partir des faits du tour, avec contrôles de cartes et de contraintes |
| Modèles | LiteLLM conservé ; aucun appel modèle supplémentaire systématique par tour dans les derniers correctifs |

Le profil est une mémoire **de session**, pas la preuve d’un profil CRM durable entre plusieurs sessions. Le code de l’ancien orchestrateur n’est pas importé en bloc. Les appels MCP d’évaluation restent dans le périmètre de lecture ; aucune réservation ou annulation client n’a été réalisée.

Pour la revue technique : [profil](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/agents/b2c_concierge/b2c_concierge/profile.py), [état géographique](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/agents/b2c_concierge/b2c_concierge/location_state.py), [budget](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/libs/b2c_common/b2c_common/search_budget.py), [faits de formule](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/libs/b2c_common/b2c_common/offer_facts.py).

## Risques des regex et corrections apportées

Le danger principal est d’utiliser des mots-clés pour décider d’une intention ambiguë. La PR n’ajoute aucune regex et en supprime une : **81 sites d’appel direct à re.*, dont 55 compilations dans 19 fichiers**, contre 82 et 56 auparavant. Ce ne sont ni 81 motifs uniques ni un décompte d’exécution.

- Confirmation : la décision lexicale ne doit plus contredire le verdict absent/none du triage dans le garde de lien.
- Pagination : un « false » du triage prime sur les mots « other options ».
- Dernière question : remplacement d’une regex coûteuse par un parcours linéaire des caractères.
- Nombre nu : suppression des espaces extérieurs avant le motif pour éviter des essais redondants sur de longues entrées.

Les anciens chemins dépassaient une seconde sur certains stress tests à 32 001 caractères. La façade nettoie déjà les entrées numériques : il s’agit d’un durcissement de helper, pas d’un déni de service distant démontré.

Les replis de routage, accords courts, dates/heures et contrôles de prose restent sensibles aux formulations. Aucune preuve d’absence générale d’erreur sémantique n’est revendiquée. Les validations de formats restent utiles. [Audit détaillé et limites](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/evals/GROUPED_REGRESSIONS_AND_REGEX_RISKS_2026_10_10.md).

## Méthode et niveau de preuve

Le corpus rassemble des conversations historiques, du feedback lié à des traces et des régressions connues. Il est inspiré des six mois de production, **sans couvrir exhaustivement tout ce trafic**. Les exemples synthétiques et les messages réels ne sont pas assimilés. Les notes sont une revue non aveugle par l’agent de codage, pas une évaluation humaine indépendante.

| Élément | Ce qui est établi |
| --- | --- |
| Comparatif complet | 100 parcours et 280 réponses par bras ; candidat évalué au commit 3153771 |
| Conversations adaptatives séparées | 4 objectifs et 16 réponses par agent ; candidat 3B/1C contre prod 1B/3C |
| Dernier code livré | Commit 548b739 ; 3 336 tests locaux réussis, un test Langfuse live payant optionnel ignoré |
| Vérifications complémentaires | Ruff, mypy sur 86 fichiers, guardrails ; 225 tests concernés repassés après nettoyage final |
| Derniers appels réels | 18 appels de triage isolés, pas 18 conversations complètes ; ils précèdent les derniers changements de terminaux |
| Dernier coût supplémentaire | 0,297304 USD ; aucune nouvelle campagne payante pour cette synthèse |

L’ancien agent utilise un export/Qdrant ; le nouveau utilise le MCP de préproduction, décrit par l’équipe comme reflet exact de la production. Les chemins de recherche et leur fraîcheur diffèrent malgré cela. Le candidat final est comparé à une référence legacy exécutée plus tôt le même jour. Une différence d’hôtel ne suffit donc pas à prouver une régression du code.

La configuration évaluée est **triage GPT-5.2 low/2048/15 s, recherche 4o-mini, synthèse GPT-5.2**. Le B2C déployé audité utilisait encore 4o-mini au triage. Le gain ne peut pas être attribué au seul code ou au seul modèle ; la PR ne change pas les variables Railway.

Cumul de campagne enregistré : **225,17 USD sur 230 USD**, comprenant les provisions historiques ; 4,33 USD disponibles après réserve. Ce sont les coûts modèle observés, hors infrastructure et fournisseurs, pas une facture comptable.

## Ce qui reste avant la bascule

La PR est ouverte, fusionnable et prête pour revue. Aucun merge ni déploiement n’est inclus dans cette livraison. Au 12 octobre, la dernière CI est bloquée avant exécution par un paiement GitHub échoué ou un plafond à relever ; aucune revue humaine n’est enregistrée. Les anciens accès temporaires de rejeu sont indisponibles localement et le MCP n’a pas été revérifié ce jour.

1. Rétablir l’accès de test et une CI exécutable, puis fixer explicitement la configuration modèle et la source de données prévues pour le lancement.
2. Rejouer les 14 objectifs moins bien notés avec des réponses adaptées aux vraies questions, plus des contrôles de géographie, dates, budgets, créneaux et confirmation. Contrôler aussi les cartes utiles et les boucles, pas seulement les notes.
3. Faire relire les exemples et les défauts restants par l’équipe. Le dépôt prévoit la revue de Fabien avant merge.
4. Après cette validation, déployer progressivement avec suivi Langfuse et possibilité de retour à la version précédente. FAQ et annulations gardent leur phase dédiée.

**Les derniers correctifs ciblent des causes communes ; ils ne démontrent pas encore que les 14 parcours sont réparés.** Les 27 C du comparatif et les 14 cas moins bons sont deux ensembles différents : les 14 comportent 11 C et 3 B. Les prochaines décisions doivent utiliser le rejeu du code final, pas lui attribuer automatiquement les notes de la version précédente.

Références : [comparatif complet](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/evals/PRODUCTION_PARITY_2026_10_10.md), [14 écarts et causes](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/evals/REGRESSION_REMEDIATION_2026_10_10.md), [derniers correctifs et preuve](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/evals/GROUPED_REGRESSIONS_AND_REGEX_RISKS_2026_10_10.json), [protocole des parcours](https://github.com/Dayuse-Labs/AgentB2C/blob/548b739/evals/REAL_USER_JOURNEYS.md).
