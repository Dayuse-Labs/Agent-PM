# PLAN — leaf de compréhension géo (série S-L) — arbitré le 2026-10-08

> Revu contre le code le 2026-10-08 : AgentB2C `main` cbe88b9 (dernier fetch : 2026-10-07 14:28) et branche `fix/geo-location-class` (PR #124, 2f457f8) ; MCP_B2C `main` 08f3764d (vérifié sur GitLab).
> Détail par session : `phases/SL1…SL8-*.md`, prompt de lancement inclus. Vue d'ensemble : `SESSIONS-CLAUDE-CODE.md` § S-L.
> Origine : discovery « Leaf géo AgentB2C » du 7 octobre (v2) et arbitrages de Fabien du 8 octobre.

## 1. Décisions arbitrées (2026-10-08, Fabien) — ne pas re-litiger en session

| # | Sujet | Décision |
|---|---|---|
| L1 | Emplacement | Leaf A2A `geo_understanding_agent`, appelée par le concierge après le triage, sur les tours de recherche seulement |
| L2 | Périmètre | Comprendre d'abord (phase 1 : la leaf rend un `GeoIntent`, la feuille de recherche garde le géocodage), résoudre ensuite (phase 2) |
| L3 | Règles de langage existantes | Retrait une par une, chaque retrait couvert par un cas d'éval, jamais en bloc |
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

## 3. Contrat `GeoIntent` v1 (S-L2)

```text
GeoIntent v1 — aucune coordonnée, extra="forbid"
schema_version  "1"
places[]        0 à 2 × { mention, kind, canonical, city, region, country, city_inferred }
                kind ∈ city | admin_district | neighborhood | landmark | street
                       | station | airport | address | hotel | region
city            null | { mention, canonical, region, country }   nommée dans le message ou reprise du contexte
country_named   null | ISO-3166-1 alpha-2   pays que l'utilisateur a NOMMÉ → filtre dur
region_named    null | code d'état ou de province nommé (« Milford ct » → "CT")
relation        in | near | whole_city
carryover       new | keep | replace_place_keep_city | refine
exclusions[]    { mention, canonical, kind }   lieux exclus (« pas à NYC ») — réservé en v1
ambiguity       null | { reason ∈ homonym | city_needed | too_vague, options[] }
```

Circulation :
- Entrée de la leaf (DataPart) : le message du tour et un contexte minimal tiré du profil : ville, zone, ancre d'état, ancre pays, hôtel nommé, locale, langue, devise. Jamais le profil entier (minimisation RGPD).
- Sortie de la leaf : `{geo_intent, diagnostics}`.
- Concierge → feuille de recherche : `query_params.geo_intent` (dict ouvert de `agents/hotel_search_agent/hotel_search_agent/contract.py`, réservé aux indications validées par le code).

Correspondance vers `geocode_location` (S-L5) :

| GeoIntent | Argument | Aujourd'hui |
|---|---|---|
| `places[0].kind = city` | `city = canonical` | écrit par le LLM de la feuille |
| autre type, sauf `hotel` | `zone = canonical`, `city = places[0].city` ou `city.canonical` | écrit par le LLM de la feuille |
| `kind = hotel` | chemin `find_hotel_by_name` (`named_hotel.py`, #124) | décidé par le LLM |
| `country_named` | `country_code` (filtre dur) | inchangé |
| `places[0].country` non nommé | `country_guess` (indice) | inchangé |
| `region_named` | ancre d'état | lue dans le texte (`geo_guards.py:88-165`), retirée en S-L7e |
| `carryover` | remplissage depuis `profile_in` | toute case vide est remplie (`geocode_tool.py:913-936`) ; `new` : rien, `replace_place_keep_city` : la ville seule |
| `ambiguity` | question | gabarits `geo_resolver.py:193` (`_CLARIFY_MANY`) et `:236` (`_CITY_NEEDED`) |

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
| S-L7a…f | Retrait des règles de langage, une MR par règle | feuille | Sonnet · piloté, puis boucle possible | S-L8, taux de repli mesuré |

```text
S-L1 ∥ S-L2  →  S-L3  →  S-L4  →  S-L5  →  S-L6  →  S-L8 (déploiement, bascule on)  →  S-L7a … S-L7f
```

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
- À garder quoi qu'il arrive : la question sans ville ni GPS (`geocode_tool.py:536-547` ; PRESERVATION.md : ne pas la retirer à l'aveugle), l'écho `geocode_echo_back`, la garde #14 (`geocode_tool.py:141`), le palier d'inventaire (`geo_resolver.py:58`).
