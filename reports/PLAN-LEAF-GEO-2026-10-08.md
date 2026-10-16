# PLAN — leaf de compréhension géo (série S-L) — arbitré le 2026-10-08

> Revu contre le code le 2026-10-08 : AgentB2C `main` cbe88b9 (dernier fetch : 2026-10-07 14:28) et branche `fix/geo-location-class` (PR #124, 2f457f8) ; MCP_B2C `main` 08f3764d (vérifié sur GitLab).
> Détail par session : `phases/SL1…SL8-*.md`, prompt de lancement inclus. Vue d'ensemble : `SESSIONS-CLAUDE-CODE.md` § S-L.
> Origine : discovery « Leaf géo AgentB2C » du 7 octobre (v2) et arbitrages de Fabien du 8 octobre.
> **Mise à jour 2026-10-16 (plan QA14707, `plans/qa14707/`, `phases/QA14707/`).** Décision DQ1 : le `GeoIntent` est produit par la feuille de recherche existante, comme argument structuré de `geocode_location`, sans leaf dédiée ni 4e appel au modèle. S-L2 est tenue par Q06 (contrat v1.1), S-L5 en son lieu par Q07 (le mapping côté feuille) et Q08, S-L3, S-L4, S-L6 et S-L8 ne sont pas construites. Le §3 décrit désormais le contrat v1.1 et le mapping tels que le code les applique. **Les numéros de ligne cités plus bas (E1-E15, §7) sont ceux de `cbe88b9` (2026-10-08) : ils ont bougé, chercher par symbole.** Plusieurs symboles cités ont changé : `geocode_location` n'accepte plus que `intent` et `metro` côté modèle (le cœur plat est `geocode_core`, `geocode_tool.py:518`), la question sans ville ni GPS est dans la branche `geocode_city_needed` de `geocode_core` (`geocode_tool.py:919`), la garde #14 est `_poi_anchor_incoherent` (`geocode_tool.py:280`), le report de destination est `_fill_place_from_profile` (`geocode_tool.py:1273`).

## 1. Décisions arbitrées (2026-10-08, Fabien) — ne pas re-litiger en session

| # | Sujet | Décision |
|---|---|---|
| L1 | Emplacement | ~~Leaf A2A `geo_understanding_agent`, appelée par le concierge après le triage, sur les tours de recherche seulement~~ **Remplacée par DQ1 (2026-10-14)** : le `GeoIntent` est produit par la feuille de recherche, comme argument de `geocode_location` |
| L2 | Périmètre | Comprendre d'abord (phase 1 : la leaf rend un `GeoIntent`, la feuille de recherche garde le géocodage), résoudre ensuite (phase 2) |
| L3 | Règles de langage existantes | Retrait une par une, chaque retrait couvert par un cas d'éval, jamais en bloc (phase 4 de QA14707 : S-L7a et S-L7f retirées, voir §4) |
| L4 | « Dans le quartier » | Hybride annoncé : dedans d'abord, puis « juste à côté » avec la distance |
| L5 | Ordre | #124 réconciliée avec le MCP mergé, puis mergée, avant tout le reste |
| L6 | Budget d'outils de la feuille | Constant (2 appels par outil). Dedans puis à côté, hôtel puis voisins, plusieurs lieux : enchaînés par le code, jamais par un appel d'outil de plus côté LLM |

Principe : le LLM comprend, le code vérifie. La leaf ne produit jamais de coordonnées. Le code garde le géocodage, l'écho, les gardes de distance et d'inventaire, le pays nommé comme filtre dur, la politique de périmètre et les gabarits de questions.

## 2. Écarts entre le plan de la discovery et le code

| # | Le plan disait | Le code dit | Conséquence |
|---|---|---|---|
| E1 | Reformuler l'invariant « ≤ 3 appels LLM » | Appliqué en code : `agents/b2c_concierge/b2c_concierge/budget.py:18` (`MAX_LLM_CALLS_PER_TURN = 3`), une 4e charge lève `LlmBudgetExceededError` ; figé par `agents/b2c_concierge/tests/test_budget.py:9` et `test_spine.py:246`, recopié dans `evals/battery.py:47` | Décision D-1 avant S-L4 ; S-L4 modifie ces 4 endroits et le CLAUDE.md |
| E2 | Écrire un test « toute clé envoyée existe dans le schéma » | Il existe : `tests/test_mcp_contract.py:117` rejoue la vraie chaîne before-tool. Son contexte (`:52`) a un état vide, donc `inject_landmark_radius` n'ajoute rien : c'est pour ça que `sort` est passé | S-L1 ajoute un cas « ancre lieu » au test existant |
| E3 | Un seul écart #124 ↔ MCP (`sort`) | Deuxième écart : `find_hotel_by_name` du MCP `main` ne renvoie aucune coordonnée (description de l'outil, `hotel-summary.dto.ts`), alors que `named_hotel.py:196` (#124) en a besoin pour chercher les voisins | Décision D-2 ; sans correctif MCP, l'hôtel nommé reste une carte seule |
| E4 | Vérifier que le MCP déployé expose `sortBy` | `contracts/mcp_b2c_tools.json` (pris le 2026-10-06) n'a ni `sortBy` ni `timeSlotMode` ; l'instance MCP connectée à la session de revue non plus | Déployer `main` 08f3764d puis rafraîchir le contrat avant S-L1 |
| E5 | Créer un compteur des dépassements de limite | Il existe : `tool_budget_guard.py:37` (préfixe `TOOL BUDGET` → métrique `budget_stopped=true`) et `:69` (niveau Langfuse `tool_budget_exhausted`) | Lire la donnée, rien à construire |
| E6 | Figer les limites par outil | 2 par outil (`agents/hotel_search_agent/hotel_search_agent/agent.py:91-103`), surchargeables par `HOTEL_SEARCH_MAX_*_CALLS` ; `tests/test_leaf_tool_budget.py:85` vérifie la marge, pas les valeurs | S-L1 fige les valeurs par défaut ; vérifier les variables Railway |
| E7 | Agent Card signée | Cartes non signées, bearer statique (exception D7, docstring de `serve.py` ; CHANTIERS A1) ; aucune primitive de signature disponible | La leaf suit D7 ; l'étape de signature de `wire-a2a` attend oidc-mtls |
| E8 | Appel de feuille : 10 s | 15 s pour la recherche, 25 s pour la FAQ (`b2c_concierge/agent.py:205-211`) ; `CONCIERGE_LEAF_TIMEOUT_SECONDS` écrase les deux | Timeout propre à la leaf, à l'abri de la variable héritée |
| E9 | La leaf reçoit son DataPart comme les autres | `_attach_outgoing_datapart` (`b2c_concierge/agent.py:343`) l'ajoute à l'événement utilisateur courant. En séquence, la feuille lit le plus récent (`response_bridge.py:265`) ; deux legs en parallèle se croiseraient | Leg dédié pour la leaf en mode ombre (S-L4) |
| E10 | Mode ombre sur le trafic réel | Plus de trafic réel sur AgentB2C depuis le 11 septembre (CHANTIERS §3). Le banc de rejeu de production est mergé (#132, `evals/production_replay.py`) | L'ombre tourne sur le banc de rejeu |
| E11 | Gates en CI | Plus de CI (CHANTIERS §1) ; jobs `eval` et `langfuse-experiments` inertes ; rejeu de jeux en 6 commandes (CHANTIERS E1 ouvert) | DoD = commandes locales |
| E12 | Jeu d'évals à construire | `evals/geo_preservation_registry.json` décrit 24 conversations géo ciblées (séquences historiques, gardées privées) avec leur attendu ; sur les 22 rejoués après la coupure VPN : 6 préservés, 4 partiels, 10 en échec, 2 non vérifiés (`evals/PRESERVATION.md`) | S-L2 part de ces 24 familles |
| E13 | Contrat : `country` et `city_inferred` | Le géocodeur distingue le pays nommé (filtre dur `country_code`) de l'indice (`country_guess`) (`geocode_tool.py:372-393`) et lit l'état dans le texte (`geo_guards.py:88`) ; le registre a une famille « Exclusion géographique » | Le contrat gagne `country_named`, `region_named` et `exclusions` |
| E14 | Une garde n°18 de périmètre | #124 apporte déjà la garde #18 `refinement_unchanged`. `GUARD_SCORE_NAMES` et `FALLBACK_SCORE_NAMES` s'allongent sans jamais retirer (`libs/b2c_common/b2c_common/scores.py:5-8`) | Une garde de périmètre serait la #19 ; une règle retirée garde son nom de garde |
| E15 | Sortie structurée de la leaf | Aucun `output_schema` dans le repo. ADK 2.4.0 l'accepte (pydantic) et le traduit en `response_format` pour LiteLLM (`google/adk/models/lite_llm.py`, `_to_litellm_response_format`). Modèle par rôle : `DAYUSE_MODEL_{ROLE}` (`libs/b2c_common/b2c_common/llm_params.py:58`) | `output_schema=GeoIntent`, `DAYUSE_MODEL_GEO` ; à valider en live en S-L3 |

## 3. Contrat `GeoIntent` v1.1 (S-L2, tenu par QA14707 Q06 et Q07)

> **v1.1 (2026-10-14, décisions DQ1, DQ5, DQ6, DQ8).** Le modèle est `libs/b2c_common/b2c_common/geo_intent.py` (`SCHEMA_VERSION = "1.1"`), son snapshot est `contracts/geo_intent.schema.json`. Écarts avec le v1 de ce plan :
> - `places[].postal_code` : le code postal tel qu'écrit. Sans lui, « 2 boulevard Poissonnière 75009 » le perdait (trace C du diagnostic).
> - `mention` / `canonical` : `mention` = les mots exacts de l'utilisateur, `canonical` = le nom normalisé par le LLM (« Pari » → « Paris »), pour `places[]` et pour `city`. Le code vérifie que la mention est ancrée dans le message et que le nom normalisé est réel.
> - `ambiguity` = `{reason ∈ homonym | city_needed | too_vague}` **sans `options`** (DQ5) : aucune option de question n'est jamais écrite par un LLM, elles viennent du seul géocodeur, par `Clarification` (`libs/b2c_common/b2c_common/clarification.py`).
> - **La règle S5 (gare de Lyon, PR #91) est portée par `ambiguity.reason = "city_needed"`** (DQ6) : le LLM pose le drapeau et ne donne aucune ville ; le code décide la question (`geocode_city_needed`). `homonym` et `too_vague` sont lus et journalisés, jamais appliqués : le géocodeur garde la décision sur les homonymes.
> - Le `GeoIntent` est produit par la **feuille de recherche** elle-même, comme argument structuré de `geocode_location` (DQ1) : pas de leaf dédiée, pas de 4e appel au modèle, pas de décision D-1.
> - L'ordre des champs de `Place` et sa liste `required` (`PLACE_REQUIRED`) font partie du prompt (Q23) : réglés pour gpt-6-luna, pas pour gpt-4o-mini.

```text
GeoIntent v1.1 — aucune coordonnée, extra="forbid", tous les champs ont un défaut
schema_version  "1.1"
places[]        0 à 2 × { mention, kind, canonical, city, country, postal_code, region, city_inferred }
                kind ∈ city | admin_district | neighborhood | landmark | street
                       | station | airport | address | hotel | region
city            null | { mention, canonical, region, country }   nommée dans le message ou reprise du contexte
country_named   null | ISO-3166-1 alpha-2   pays que l'utilisateur a NOMMÉ → filtre dur
region_named    null | code d'état ou de province nommé (« Milford ct » → "CT")
relation        in | near | whole_city
carryover       new | keep | replace_place_keep_city | refine
exclusions[]    { mention, canonical, kind }   lieux exclus (« pas à NYC ») — réservé
ambiguity       null | { reason ∈ homonym | city_needed | too_vague }
```

`relation`, `carryover` et `exclusions` sont lus mais **non appliqués** (S-L5, hors périmètre de QA14707).

Circulation (QA14707, DQ1) : le LLM de la feuille remplit `geocode_location(intent=GeoIntent, metro=…)`. Le code déduit tout le reste du `GeoIntent` et du profil (`country_code` et `country_guess` ne sont plus des arguments du modèle). La conversion de l'argument et ses limites (un argument invalide arrive en dict brut, validé par l'outil) sont décrites dans la docstring de `geo_intent.py`. Le circuit prévu au v1 (leaf A2A, `query_params.geo_intent`) n'est pas construit : S-L3 et S-L4 ne reviennent que si des rejeux montrent que le modèle de la feuille ne tient pas le schéma.

Correspondance vers `geocode_core`, telle que l'implémente `_place_args` (`agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`) :

| GeoIntent | Argument | Règle |
|---|---|---|
| un lieu de `kind = city` | `city` | compte à **n'importe quel rang** de `places` |
| le **premier** lieu qui n'est ni `city` ni `hotel` | `zone = canonical` (sinon `mention`) | le rang dans `places` ne décide rien |
| ville de la recherche | `city` | dans l'ordre : la ville propre du lieu de zone, puis un lieu de kind city, puis le champ `city` |
| `kind = hotel` | chemin `find_hotel_by_name` (`named_hotel.py`) | jamais une zone |
| `country_named` | `country_code` (filtre dur Mapbox) | seul pays qui filtre ; passe par `_iso2`, une valeur mal formée est écartée |
| pays d'un lieu ou d'une ville, non nommé | `country_guess` (indice) | suit l'ordre de la ville gagnante ; jamais un filtre |
| `region_named` | ancre d'état | passe par `resolve_state_hint` |
| `ambiguity.reason = city_needed` | aucune ville | le code pose la question (S5) |
| `places[].postal_code` | `postal_code` et `zone_kind` | lu du lieu de zone, sinon d'un lieu de ville, vérifié contre le message |

Exception à la précédence de la ville : une ville **écrite par l'utilisateur dans ses propres mots de ce tour** (`read_user_words`) et vérifiée par `_verified_city` l'emporte sur la ville propre du lieu de zone (« Gare du Nord à Bruxelles » ne cherche plus à Paris). L'estimation du pays vient alors d'abord de la ville gagnante. Une ville portée seulement par le préfixe EARLIER REQUEST du concierge garde la ville propre du lieu de zone en premier. Le désaccord est compté (`city_conflicts`, sans texte) sur la ligne `dayuse_metric=geo_intent`. Un lieu dont ni la mention ni le nom normalisé ne sont ancrés dans le message est écarté d'abord.

**Règle de pays d'un code postal (DQ8).** Quand l'utilisateur ne nomme aucun pays :
- seul un pays **nommé** est un filtre dur ;
- sinon le géocodage cherche partout et ne garde que les candidats dont `context.postcode` est égal au `postal_code` extrait (`_postcode_match`) ;
- parmi eux, l'ordre de départage est : la ville nommée du tour (`context.place` égal à la ville du tour), puis la supposition du LLM (`places[].country`), puis le pays du marché, puis l'ordre de Mapbox. La supposition et le marché ne départagent jamais plus : ce ne sont pas des filtres.
- Le pays du marché vient d'abord du `entry_market_country` de la requête, stocké dans le profil par la façade (Q16), puis de la région du locale, puis du préjugé de langue (`_market_country`). Le widget envoie un locale `en` nu : sans la première source, « near 11580 » en en/USD suivrait l'ordre de Mapbox (Mexico d'abord).
- La règle d'origine de ce plan (« la supposition comme filtre ») est remplacée : 75009 est aussi un code postal américain (Celina, TX).

| GeoIntent | Argument | Ce qui est remplacé |
|---|---|---|
| `carryover` | remplissage depuis `profile_in` | toute case vide est remplie aujourd'hui (`_fill_place_from_profile`) ; `new` : rien, `replace_place_keep_city` : la ville seule — **non appliqué** |
| `ambiguity` | question | le gabarit `Clarification` rendu par le concierge sans synthèse (DQ2) ; la question « ville nécessaire » est `geo_resolver.city_needed_question` |

## 4. Sessions

| # | Scope | Zone | Modèle · mode | Prérequis |
|---|---|---|---|---|
| S-L1 | #124 réconciliée avec le MCP mergé : `sortBy`, test de contrat, limites figées | feuille | Sonnet · piloté | MCP `main` déployé, contrat rafraîchi, D-2 |
| S-L2 | Contrat `GeoIntent` v1 et jeux d'évals | libs, contracts, evals | Opus · piloté | — (∥ S-L1) |
| S-L3 | Leaf `geo_understanding_agent` (A2A, D7, :8103) | nouvel agent | Opus · piloté | S-L2 |
| S-L4 | Concierge : appel en mode ombre, budget, timeout | concierge | Opus · piloté | S-L3, D-1 |
| S-L5 | Bascule : la feuille consomme le `GeoIntent` | feuille + concierge | Opus · piloté | S-L4, D-3, résultats d'ombre validés (D-4) |
| S-L6 | Périmètre hybride annoncé | feuille + synthèse | Sonnet · piloté | S-L5, D-5 |
| S-L8 | Déploiement Railway, registre de la flotte, bascule `on` | infra | Sonnet · piloté, validation Fabien | S-L5, S-L6 |
| S-L7a…f | Retrait des règles de langage, une MR par règle | feuille | Sonnet · piloté, puis boucle possible | S-L8, taux de repli mesuré — **a et f faites par QA14707** (Q09, Q10) |

```text
S-L1 ∥ S-L2  →  S-L3  →  S-L4  →  S-L5  →  S-L6  →  S-L8 (déploiement, bascule on)  →  S-L7a … S-L7f
```

**Séquence réellement suivie (QA14707, DQ1)** : la feuille de recherche produit le `GeoIntent` (S-L2 = Q06, S-L5 côté feuille = Q07 et Q08) → déploiement (#140) → retraits de phase 4. S-L3 et S-L4 (leaf dédiée, mode ombre) deviennent **conditionnels** : elles ne reviennent que si les rejeux H3 montrent que le modèle de la feuille ne tient pas le schéma (taux de `valid=0`), et ne changeraient alors que l'endroit où l'objet est produit. D-1 (budget d'appels) tombe : `MAX_LLM_CALLS_PER_TURN = 3` est inchangé (`agents/b2c_concierge/b2c_concierge/budget.py:18`).

**Retraits S-L7 faits par QA14707** (une règle, un cas de couverture, aucun nom de garde retiré) :

| Règle | Statut | Où |
|---|---|---|
| S-L7a regex de prépositions, articles, sondes | **retirée par Q09** (`3cbeba1`), avec l'appariement de texte sur `pending_place` | `git grep -n _city_named_in_message -- agents libs` ne renvoie rien |
| S-L7f `select_us_postal_anchor` | **retirée par Q10, décision DQ7** (`b36672d`). Le plan source affirmait que S-L7 l'avait « oubliée » : c'est faux, elle y figure comme S-L7f, « décision de Fabien avant tout retrait », et DQ7 est cette décision | `git grep -n select_us_postal_anchor -- agents libs` ne renvoie rien ; les tests « near 11580 » restent la spécification |
| S-L7b exception « gare de lyon » du prompt | **non retirée, transformée** par Q07 : la règle S5 devient `ambiguity.reason = city_needed` (DQ6), le mot « laisser `city` vide » du prompt est retiré, pas la règle | `hotel_search_agent/agent.py`, `libs/b2c_common/b2c_common/geo_intent.py` |
| S-L7c règle « nom complet » | **réécrite** par Q07 en champ `canonical` du `GeoIntent` | idem |
| S-L7d mots génériques | ouverte (`_GENERIC_LOCATION_WORDS`, `demote_generic_city`, `geo_guards.py`) | |
| S-L7e État lu dans le texte | ouverte (`extract_state_hint_from_text`, `resolve_state_hint`, `geo_guards.py`) ; `region_named` du `GeoIntent` existe, la lecture du texte reste le repli | |

Chaque retrait de S-L7 affaiblit le chemin de repli (leaf en panne → extraction actuelle). D'où l'ordre : retirer après la bascule, une fois le taux de repli `fallback_geo_leaf` mesuré.

## 5. Décisions encore ouvertes (Fabien)

- **D-1 · Budget d'appels au modèle (bloque S-L4).** (a) Plafond par famille : 4 pour un tour de recherche (triage, leaf géo, feuille, synthèse), 3 sinon — recommandé. (b) Compter la leaf dans le créneau de la feuille — déconseillé : ce créneau compte déjà 1 pour 2 appels réels de la feuille de recherche (commentaire de `skip_final_generation`, `hotel_search_agent/agent.py:327`). En appels réels, un tour de recherche reste à 4 après S-L5 : la feuille passe de 2 à 1. Pendant l'ombre (S-L4), les tours rejoués en font 5.
- **D-2 · Coordonnées de l'hôtel nommé (bloque la partie hôtel nommé de S-L1).** (a) Le MCP expose `lat`/`lon` dans `find_hotel_by_name` (petite MR MCP_B2C, demande écrite dans `reports/MCP-B2C-REQUESTS.md`) — recommandé. (b) Assumer la carte seule, et le dire.
- **D-3 · Contrats figés.** Ajouter `geo_leaf` à `FALLBACK_SCORE_NAMES` (repli quand la leaf échoue) ; une garde #19 de périmètre ou non ; configs de score Langfuse à créer.
- **D-4 · Latence de la bascule.** Référence : p50 d'une recherche ≈ 3,4 s (HANDOFF, audit latence). Dégradation acceptée et timeout de la leaf à fixer sur les mesures de S-L4.
- **D-5 · Seuil « juste à côté »** pour un lieu sans frontière (monument, gare, rue, adresse).
- **D-6 · #123 de Victor.** L'extraction du lieu dans le triage est écartée par L1 ; à fermer avec Victor. L'état géo d'un tour à l'autre vit déjà dans le profil du concierge (`profile.py:189-226`).
- **D-7 · Porteurs** par session.

## 6. Données à collecter

- La trace Langfuse du test « Saint Paul à Londres ».
- La fréquence de `budget_stopped=true` et de `tool_budget_exhausted` sur la feuille de recherche.
- Les variables `HOTEL_SEARCH_MAX_*_CALLS` éventuellement posées sur Railway.
- L'instance MCP appelée par AgentB2C (preprod, prod) et le build qu'elle sert.
- La latence p50 et p95 de la leaf et du saut A2A (S-L4), le coût d'un service Railway de plus avec min-instances 1.
- Les seuils de passage des jeux, après le passage de référence de S-L2.
- Le taux de repli `fallback_geo_leaf` avant les retraits.

## 7. Hors périmètre de la phase 1

- Résolution dans la leaf (phase 2) : `geocode_tool`, `geo_resolver`, `geo_guards`, clients Mapbox et Search Box. Lien avec la demande X1 (`resolve_location` côté MCP, `reports/MCP-B2C-REQUESTS.md`), le correctif structurel du biais IP de Search Box.
- Frontières de quartier (polygones) : source à choisir (OSM sous ODbL, bbox Mapbox).
- Option A′ (leaf en parallèle du triage) : seulement si la latence l'exige (S-L8).
- À garder quoi qu'il arrive : la question sans ville ni GPS (branche `geocode_city_needed` de `geocode_core`, `geocode_tool.py:919` ; PRESERVATION.md : ne pas la retirer à l'aveugle), l'écho `geocode_echo_back`, la garde #14 (`_poi_anchor_incoherent`, `geocode_tool.py:280`), le palier d'inventaire (`in_inventory_tier`, `geo_resolver.py:85`).
