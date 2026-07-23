# Audit honnête AgentB2C — geo, multi-turn et pertinence des hôtels

**Date :** 22 juillet 2026  
**Destinataire :** Fabien  
**Périmètre :** comparaison black-box de l'agent actuel et de la refacto AgentB2C sur le même modèle, un inventaire quasi identique et le pack canonique de 249 cas.

## Verdict exécutif

AgentB2C est une **meilleure architecture cible**, mais son code actuel ne résout pas encore nos principaux problèmes de geo et de continuité multi-turn. Une bascule complète ferait gagner beaucoup en latence, mais ferait perdre trop de couverture fonctionnelle, notamment sur le mobile/GPS, les zones, les hôtels nommés, les dates, les devises et certains homonymes internationaux.

Le code AgentB2C n'a pas changé depuis le précédent audit : `origin/main` est toujours au commit `8478795`. La nouvelle branche `s-eval-pack-comparison` au commit `61c1521` ajoute uniquement deux documents (`EVAL-PACK-COMPARISON-2026-07-22.md` et `HANDOFF.md`), sans modification du runtime.

Les deux agents ont été évalués avec **GPT-5.2 explicitement forcé** :

- agent actuel : `OPENAI_MODEL=gpt-5.2` ;
- AgentB2C : `DAYUSE_MODEL=gpt-5.2` sur le concierge et ses feuilles.

Attention : les valeurs par défaut commitées dans les deux repos restent `gpt-4o-mini`. GPT-5.2 en production dépend donc d'une variable d'environnement de déploiement qu'il faut contrôler côté plateforme.

### Résultat complet, 249 cas

| Agent | Succès bruts | Taux | p50 | p95 |
|---|---:|---:|---:|---:|
| Agent actuel (`160efc1`) | 179/249 | 71,9 % | 16,0 s | 49,0 s |
| AgentB2C (`8478795`) | 141/249 | 56,6 % | 9,8 s | 26,7 s |

AgentB2C gagne **21 cas** et en perd **59** face à l'agent actuel ; 120 réussites et 49 échecs sont communs.

Dix cas AgentB2C avaient rencontré une dégradation technique pendant le run concurrent. Rejoués isolément, **6/10 récupèrent**, contre **8/10** sur le replay miroir de l'agent actuel. En remplaçant seulement ces erreurs par leur replay, le score indicatif AgentB2C passe à **147/249, soit 59,0 %**. Cela réduit le déficit, mais ne change pas le verdict.

### Résultats par suite

| Suite | Agent actuel | AgentB2C | Lecture |
|---|---:|---:|---|
| Core | 70/95 | 66/95 | écart limité, mais davantage de pertes de filtres côté B2C |
| Domaines | 8/8 | 2/8 | façade B2C n'exploite pas réellement domaine/locale/devise |
| Geo | 36/41 | 26/41 | principal déficit produit |
| International | 7/13 | 2/13 | homonymes, locales et amenities fragiles |
| Multi-turn | 16/27 | 12/27 | profil incomplet ; les deux agents restent perfectibles |
| Blessures production | 6/13 | 3/13 | GPS et origine des distances absents côté B2C |
| Worldwide | 36/52 | 30/52 | B2C retourne beaucoup plus souvent zéro hôtel |

Sur le périmètre le plus directement lié à la décision — **41 geo + 27 multi-turn + 13 blessures production** — le résultat est :

- agent actuel : **58/81, soit 71,6 %** ;
- AgentB2C brut : **41/81, soit 50,6 %** ;
- AgentB2C après remplacement des trois timeouts récupérés sur ce périmètre : **44/81, soit 54,3 %**.

GPT-5.2 améliore donc certains cas, mais ne comble pas les trous du contrat et de l'état applicatif.

## Méthodologie et limites

Les deux agents ont reçu les mêmes messages, contextes natifs et horloges de test.

- AgentB2C : snapshot local de **8 701 hôtels**, **22 177 plans** et **29 marchés**, exposé via un MCP local en lecture seule.
- Agent actuel : base locale de **8 754 hôtels actifs** sur les mêmes 29 marchés.
- Écart d'inventaire : 53 hôtels, soit environ 0,6 %.
- Trafic identifié comme synthétique ; aucune réservation ou écriture métier.
- Langfuse désactivé pour les deux agents pendant l'évaluation.

Le protocole est solide pour comparer la geo, les contraintes, le multi-turn et les shortlists. Il n'est pas totalement iso-production sur trois dimensions :

1. le MCP local ne reproduit pas tout le pricing et toutes les devises de `MCP_B2C` ;
2. il ne fournit pas tous les outils FAQ, détails, comparaison et récupération de booking ;
3. les runs complets ont utilisé trois partitions concurrentes par agent, ce qui expose les limites de timeout.

En conséquence, le score global de 249 cas est **directionnel**. Le verdict geo/multi-turn repose en plus sur l'inspection du code, les assertions structurées et les replays isolés. Les 6 échecs de domaine ne sont pas utilisés seuls pour condamner la refacto : la fixture monétaire est limitée, mais le code confirme indépendamment que la façade ignore encore `locale`, `currency` et le domaine comme entrées métier.

## Ce que la refacto améliore vraiment

### Une architecture nettement plus saine

AgentB2C sépare l'orchestrateur, la recherche hôtelière, la FAQ et les contrôles déterministes. Les feuilles sont stateless et échangent un `profile_in`/`profile_delta`. C'est plus testable, plus observable et plus simple à faire évoluer que l'agent actuel.

### Un état de session explicite

Le `SessionProfile` Redis est une bonne fondation. Il rend explicites la ville, le pays/État, le budget, les horaires, les amenities, la dernière shortlist et l'offre en attente. Cette base est meilleure qu'une mémoire reposant seulement sur l'historique LLM.

### Plus de décisions sensibles dans le code

La refacto apporte notamment des gardes déterministes sur le géocodage, les amenities, les budgets dérivés d'une durée, l'élargissement de recherche et la confirmation de réservation. Elle hallucine moins volontiers lorsqu'un service ne répond pas.

### Une latence bien meilleure

AgentB2C réduit la médiane de **16,0 s à 9,8 s** et le p95 brut de **49,0 s à 26,7 s**. C'est un vrai bénéfice produit. Il est toutefois partiellement obtenu au prix d'un timeout de feuille fixe à 10 secondes : dix cas ont renvoyé une dégradation technique, et Chester a de nouveau expiré même en replay isolé.

### Des gains ciblés

Parmi les cas où AgentB2C améliore le résultat : Bremen, Heidelberg, Cap Ferrat, la non-contradiction sur une amenity, une variante de « rooftop pool », la pagination « autres options », ainsi que certaines locales coréennes et canadiennes-françaises.

## Geo : meilleure prudence, couverture insuffisante

### Résultat

- agent actuel : **36/41** ;
- AgentB2C brut : **26/41** ;
- AgentB2C après replay de Milano et Bonn : **28/41**.

Le score officiel compte quelques succès sans hôtel. En exigeant une vraie shortlist sur les cas réussis :

- agent actuel : **33/41** ;
- AgentB2C brut : **21/41** ;
- AgentB2C après les deux replays récupérés : **23/41**.

### Cause dans le code

Le géocodeur AgentB2C demande un seul candidat à Mapbox (`limit=1`) puis l'accepte ou le rejette. Il ne classe pas plusieurs candidats avec :

- le pays ou l'État demandé ;
- la locale, le domaine et la devise ;
- la densité réelle d'inventaire Dayuse ;
- une ancre GPS ou une adresse ;
- un score de proximité avec une zone ou un POI.

Cette approche explique les échecs sur Milano, Lisboa, Genève, La Défense, Köln/München/Nürnberg et certains homonymes. Elle est prudente — mieux vaut zéro hôtel qu'un mauvais pays — mais trop souvent incapable de poursuivre avec le bon candidat.

### Contexte natif et GPS

La façade B2C ignore aujourd'hui `native_context/geolocation`. Le profil ne stocke ni coordonnées de l'ancre, ni type d'origine de distance. Les cas GPS Paris, Detroit et Orange County échouent côté B2C et réussissent côté actuel sur ce run.

C'est un **P0 mobile** : un changement de tour ne doit jamais remplacer silencieusement un GPS, une adresse ou une zone par le centroïde d'une ville.

## Multi-turn : bon pattern d'état, profil encore incomplet

### Résultat

- agent actuel : **16/27** ;
- AgentB2C : **12/27**.

Sur les 36 assertions de filtres structurés :

- agent actuel : **25 passent**, 11 échouent ;
- AgentB2C : **16 passent**, 20 échouent.

Les deux agents échouent encore les trois variantes de conservation d'horaire et les trois variantes de changement de zone. AgentB2C échoue en plus les trois suites d'hôtel nommé et les trois suivis date/disponibilité.

### Champs manquants

Le profil AgentB2C ne modélise pas encore :

- `named_hotel` ;
- `zone` et `metro` ;
- date absolue et `date_reference` ;
- devise ;
- origine GPS et coordonnées résolues ;
- origine des distances ;
- IDs déjà affichés et curseur de pagination.

Le pont vers `active_filters` force actuellement `named_hotel: null` et `date_reference: null`. GPT-5.2 ne peut pas compenser de façon fiable un état que le contrat ne sait ni stocker ni restituer.

### Horaires à la demi-heure

Le cas 07:30–13:30 réussit sur l'agent actuel et échoue côté AgentB2C, qui l'arrondit à 07:00–13:00. Le schéma de la feuille reste fondé sur des heures entières.

Le cas « une chambre pour une heure » passe formellement côté B2C parce qu'il n'invente plus un budget de 1, mais la réponse ignore tout de même le budget explicite de 100 dollars et retourne des prix en euros. Ce succès ne prouve donc pas une gestion complète de la demande.

## Pertinence des hôtels poussés

La refacto ne dégrade pas systématiquement les hôtels lorsque la destination est correcte, mais le nouveau run ne permet pas de dire que les shortlists sont équivalentes.

Lorsque les deux agents retournent des hôtels :

| Suite | Tours comparables | Recouvrement moyen des listes | Médiane |
|---|---:|---:|---:|
| Geo | 21 | 24 % | 11 % |
| Multi-turn | 40 | 34 % | 25 % |
| Worldwide | 32 | 29 % | 20 % |

Ce recouvrement est nettement plus faible que lors du précédent petit run. Il peut refléter plusieurs listes acceptables, mais il interdit de conclure à une parité de pertinence.

Surtout, AgentB2C ne possède pas de reranker hôtel propre dans `response_bridge` : il prend les cinq premiers résultats du MCP. La fixture locale les trie déjà par distance. La refacto sait donc bien transporter une shortlist fournie par le backend, mais elle ne démontre pas encore une optimisation autonome de pertinence. Le bridge supprime aussi latitude, longitude et distance, ce qui empêche le harness de vérifier précisément la proximité.

Avant canary, il faut une évaluation de ranking dédiée avec un inventaire iso-prod : destination résolue identique, mêmes candidats, vérité de distance, contraintes dures, puis métriques `precision@5`/`NDCG@5` ou jugement humain en aveugle.

## Edge cases à conserver comme gates

| Cas | Agent actuel | AgentB2C GPT-5.2 | Risque à traiter |
|---|---|---|---|
| Milano simple | 5 hôtels | timeout au run, puis 5 hôtels au replay | timeout et stabilité |
| Lisboa en portugais | échec | résout Lisbon, Arkansas | locale/pays non injectés au ranking geo |
| Chester, GB | hôtels | timeout, y compris isolé | timeout fixe de 10 s |
| Victoria, BC | pas satisfaisant | pas satisfaisant | homonyme + élargissement contrôlé |
| GPS Paris/Detroit | succès | échec | contexte natif ignoré |
| Orange County | succès sur ce run | échec | zone/metro et ancre exacte absentes |
| 07:30–13:30 | conserve les demi-heures | arrondit à 07:00–13:00 | schéma horaire entier |
| Hôtel nommé, 3 contextes | 2/3 succès | 0/3 | champ `named_hotel` absent |
| Date/disponibilité, 3 contextes | 3/3 succès | 0/3 | date absente du profil |
| Changement de zone, 3 contextes | 0/3 | 0/3 | dette commune à corriger |
| Autres options | répète sur ce run | meilleure diversité | pagination B2C prometteuse mais non garantie par état |

## Correctifs P0 avant bascule

1. **Geo multi-candidats et inventory-aware** : demander plusieurs candidats Mapbox, les classer avec pays/État, locale/domaine/devise, inventaire Dayuse et proximité, puis clarifier seulement si l'ambiguïté subsiste.
2. **Contexte natif** : consommer `native_context.geolocation`, conserver l'ancre exacte et son type, et exposer latitude/longitude/distance dans les cartes.
3. **Profil complet** : ajouter hôtel nommé, zone/metro, date, devise, coordonnées résolues, origine de distance et IDs déjà affichés.
4. **Pont déterministe profil → feuille** : ne pas demander au LLM de recopier implicitement `country_anchor`/`state_anchor` dans les arguments attendus par le géocodeur.
5. **Horaires précis** : accepter minutes et demi-heures de bout en bout.
6. **Timeouts** : remplacer le seuil fixe de 10 s par un budget cohérent avec le p95 réel, mesurer chaque phase et prévoir un retry borné/idempotent.
7. **Pricing/devise** : ne plus formatter principalement depuis `priceEuro`; propager explicitement domaine, locale et devise.
8. **Ranking vérifiable** : conserver les coordonnées et distances, puis tester la shortlist sur un pool candidat identique.

## Durcissements du harness

1. Ajouter `min_hotels >= 1` aux cas geo censés trouver une offre.
2. Séparer dans le score `safe clarification`, `successful search` et `technical degradation`.
3. Vérifier le pays et l'ancre résolus même avec une shortlist vide.
4. Vérifier date, zone, horaires, devise et hôtel nommé après chaque tour.
5. Échouer une distance invérifiable lorsque le cas impose de la proximité.
6. Pour « autres options », exiger un minimum de nouveaux IDs ou une divulgation d'épuisement.
7. Reporter séparément le score brut, le score sans outils non disponibles et le taux de timeout.
8. Rejouer les gates critiques au moins trois fois pour mesurer la stabilité LLM.

## Recommandation

Ne pas faire un remplacement “big bang”. Garder AgentB2C comme architecture cible et porter d'abord les capacités éprouvées de l'agent actuel : résolution geo multi-candidats, GPS/ancre de distance, contexte domaine/devise, horaires précis et filtres multi-turn.

Gate proposée avant canary :

- zéro mauvais pays ;
- zéro perte d'une contrainte explicite entre deux tours ;
- zéro remplacement silencieux du GPS/adresse/zone ;
- aucun succès geo vide lorsqu'une offre existe dans le rayon attendu ;
- parité sur les 81 cas geo/multi-turn/blessures production ;
- timeout technique inférieur au seuil produit convenu ;
- ranking validé séparément sur candidats identiques.

## Artefacts

Résultats détaillés du run GPT-5.2 :

- `dayuse_eval_pack/eval_pack/results/honest_20260722_full_gpt52/current_main.json` ;
- `dayuse_eval_pack/eval_pack/results/honest_20260722_full_gpt52/agentb2c.json` ;
- `dayuse_eval_pack/eval_pack/results/honest_20260722_full_gpt52/comparison.json` ;
- `dayuse_eval_pack/eval_pack/results/honest_20260722_full_gpt52/b2c_degraded_sequential.json` ;
- `dayuse_eval_pack/eval_pack/results/honest_20260722_full_gpt52/current_same10_sequential.json`.
