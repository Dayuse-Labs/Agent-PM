# AUDIT — les mappings en dur d'AgentB2C : lesquels sont légitimes, lesquels sont de la dette

> Phase UX6, item 6 de la liste Fabien du 2026-08-27 : « On commence à avoir plusieurs
> mappings en dur. Voir comment on pourrait s'en passer. »
> Le fichier de phase (`phases/UX6-…`) a été supprimé au nettoyage de fin de chantier —
> **ce rapport le remplace.**
> Phase d'ÉTUDE : le livrable est ce rapport ; les suppressions ne se font que là où la
> mesure les prouve mortes.
> Mesures du 2026-08-28. Branche `audit/ux6-hardcoded-mappings`, PR #109.

---

## 1. Verdict

**Il n'y a aucune table morte dans ce repo.** 98 tables inventoriées, 0 avec un compte de
références à zéro, 0 suppression exécutée. La thèse de la phase — « trois catégories, une
seule est de la dette » — est confirmée, mais **la répartition proposée était fausse sur ses
quatre candidats à la suppression**, et la mesure les a tous les quatre renvoyés en
catégorie 1.

| Ce que la phase attendait | Ce que la mesure a trouvé |
|---|---|
| `_ISO_BY_COUNTRY_NAME` = « le meilleur candidat », `countryCode` désormais présent | **0/201 hôtels** portent un `countryCode` sur `search_offers`, sur 21 pays. La table est **la seule jambe porteuse** de l'URL d'hôtel sur le chemin carte. Catégorie 1. |
| `_LOCALE_COUNTRY` = la façade fournit peut-être déjà l'info | La façade fournit la **locale**, qui est l'**entrée** de la table, pas son remplacement. Atteinte à 4 sites, dont 2 inconditionnels dans le ranking. Catégorie 1. |
| `_EXONYM_EQUIVALENTS` = « probablement irréductible » | Irréductible, et ses **omissions** encodent du jugement (`vienne` exclu volontairement). Catégorie 1. |
| `US_STATE_*` = déjà dérivées du paquet `us`, bon état final | Vrai — **et instructif** : même l'état final « propre » garde 2 correctifs manuels documentés. Voir §7. |
| ~20 tables en dur | **98**, dont **30 ne sont pas des mappings** mais la couche de traduction (§4). |

**Le constat le plus important n'était pas au programme** (§6) : la table que la phase
voulait réduire est protégée par un contrat que le widget **défait silencieusement**.
Quand le back rend honnêtement « pas de lien », le front en **fabrique un**, sur le mauvais
marché, avec un slug inventé depuis le nom d'affichage — exactement le défaut de prod que
`hotel_urls.py` existe pour fermer. Prouvé en exécutant le vrai module widget (§6.2).

Catégorie 2 (`_MARKET` / `COUNTRY_META`) : chiffrée à **85 entrées tenues à la main dans
4 tables et 2 langages**, dont **8/22 marchés déjà en désaccord sur l'hôte**. Chiffrée et
proposée, **non implémentée**, conformément au périmètre.

---

## 2. Méthode

Toutes les commandes sont rejouables. Les greps de la phase datant du 2026-08-27 ont été
relancés — et **élargis**, car ils manquaient les tables indentées, les tuples fermés et les
`frozenset` (c'est la raison de l'écart 20 → 98).

```bash
# 1) Inventaire Python — collections littérales au niveau module
grep -rnE "^ *_?[A-Z][A-Z0-9_]{2,}(: *[^=]+)? *= *(\{|\[|frozenset|dict\(|tuple\(|set\()" \
  agents libs --include='*.py' | grep -v "/tests/"          # -> 74 lignes

# 2) Inventaire Python — enums fermées en tuple (que le grep de la phase ratait)
grep -rnE "^ *_?[A-Z][A-Z0-9_]{2,}(: *[^=]+)? *= *\(" \
  agents libs --include='*.py' | grep -v "/tests/"          # -> 20 lignes, dont 6 chaînes

# 3) Inventaire JS
grep -rnE "^ *(const|let|var) [A-Z][A-Z0-9_]{2,} *= *(\{|\[)" web/vendor/static/js/
                                                            # -> 11 lignes, dont 1 sentinelle

# 4) Recherche de tables MORTES : compte d'usages hors ligne de définition
#    (boucle complète dans §8) -> minimum observé = 1, donc aucune table morte

# 5) Mesure live countryCode (réseau réel, pas un pytest)
set -a; . ./.env; set +a
.venv/bin/python scripts/probe_country_code_coverage.py             # 8 marchés + details
.venv/bin/python scripts/probe_country_code_coverage.py --coverage  # les 14 autres + 2 non mappés

# 6) Chiffrage de la duplication back/front (lecture seule, hors ligne)
.venv/bin/python scripts/measure_market_table_drift.py
```

Total : **74 − 1 doublon (`US_STATE_NAMES` réassigné l. 415 puis 416) + 14 + 10 = 98 tables.**

**Piège de la phase traité en premier** : `bash scripts/dayuse_guardrails.sh .` a été lancé
**avant** toute modification → `Dayuse guardrails: OK`. Vérifié au passage qu'il n'a **aucune
règle sur les constantes ou les hosts en dur** (seule règle proche : « SDK modèle cloud
importé en dur »), donc aucun signal du guardrail ne pouvait être confondu avec un constat
d'audit.

**Interdit de session respecté** : le code de MCP_B2C n'a pas été relu. Tout ce qui est
affirmé sur MCP vient de ses **réponses** (201 hôtels sondés), pas de son implémentation.

---

## 3. Inventaire chiffré

| Classe | Tables | Verdict |
|---|---:|---|
| **Catégorie 0** — traduction, pas mapping | 30 | Hors sujet : c'est `i18n.js` côté Python |
| **Catégorie 1** — contrats code-owned | 63 | GARDER, et défendre |
| **Catégorie 2** — duplication back/front | 4 | La vraie dette. Chiffrée, proposée, non faite |
| **Catégorie 3** — MCP a déjà la donnée | **0** | La catégorie est **vide après mesure** |
| dont dérivées d'une lib (état final visé) | 5 | Référence, §7 |
| **Tables mortes** | **0** | Aucune suppression possible |

---

## 4. Catégorie 0 — 30 « tables en dur » qui ne sont pas des mappings

La phase exclut `i18n.js` du périmètre : « ce n'est pas un mapping en dur, c'est un fichier de
traduction ». **Par symétrie, 29 tables Python sont exactement la même chose** — la couche de
traduction côté serveur, écrite ou élargie par UX2 (PR #107). Leur forme (`dict[str, str]`
clé = code langue) les fait ressortir dans un grep « mappings en dur » alors qu'elles ne
mappent aucun référentiel métier : elles portent du texte.

| Fichier | Tables | Lignes |
|---|---|---|
| `b2c_concierge/templates.py` | `_ACK_RESPONSE`, `_INLINE_UNRESOLVED`, `_OFFER_SUMMARY`, `_BOOKING_LINK`, `_NEEDS_SELECTION_LIST_INTRO`, `_NEEDS_SELECTION_NO_OFFER`, `_NEEDS_SELECTION_NO_LIST`, `_WHERE`, `_DEGRADED`, `_DEGRADED_SUFFIX`, `_SEARCH_EXHAUSTED_PAGINATION`, `_SEARCH_EXHAUSTED_BUDGET`, `_SERVICE_DEGRADED` | 28, 68, 174, 235, 262, 272, 303, 354, 371, 405, 431, 462, 516 |
| `hotel_search_agent/response_bridge.py` | `_DATE_FALLBACK_SWAPPED`, `_DATE_FALLBACK_SAME_DAY`, `_DATE_FALLBACK_PLAIN`, `_OUTCOME_EMPTY`, `_OUTCOME_FOUND`, `_OUTCOME_TIMESLOT_FALLBACK`, `_SEARCH_UNAVAILABLE` | 1127, 1158, 1189, 1221, 1231, 1241, 1301 |
| `hotel_search_agent/geo_resolver.py` | `_CLARIFY_ONE`, `_CLARIFY_MANY`, `_CLARIFY_LAST_SEP`, `_CITY_NEEDED` | 183, 193, 206, 236 |
| `b2c_concierge/profile.py` | `_RECOVERY_SUGGESTIONS`, `_DATE_SUGGESTIONS` | 103, 123 |
| `b2c_concierge/amenity_guard.py` | `_HEDGE`, `_CORRECTION_NOTE` | 167, 177 |
| `b2c_concierge/currency_guard.py` | `_DISCLOSURE_TEXT` | 29 |
| `web/.../chat/i18n.js` | `STRINGS` | 38 |

**Conséquence pour l'arbitrage** : le ressenti « on commence à avoir plusieurs mappings en
dur » porte pour presque un tiers sur la traduction. Les réduire, c'est le chantier i18n
(UX2-bis : sortir les 7 langues dans des fichiers de ressources), pas le chantier mappings.
À traiter séparément, et pas dans cette phase.

---

## 5. Catégorie 1 — 63 contrats code-owned : justification par table

Le livrable demandé : « une justification écrite par table, pour que la prochaine personne
qui lit *mappings en dur* ne les supprime pas par hygiène mal placée. »

### 5.1 Le cas à ne surtout pas toucher — `EQUIPMENT_IDS`

`hotel_search_agent/equipment_ids.py:59`. **C'est le CORRECTIF d'un bug de prod, pas sa
cause.** Les faits, tous déjà dans sa docstring (l. 1-46) et confirmés par lecture du code :

1. `search_offers` n'a **aucun** paramètre texte d'équipement — seulement
   `hotelEquipmentIds`, un tableau d'entiers, utilisé en **filtre dur**, sur un schéma
   `additionalProperties: false`.
2. Livré à lui-même le modèle hallucine un ID : « piscine » → `[1]`. Un filtre dur sur un ID
   inexistant rend **zéro offre en ayant l'air d'une recherche saine** — reproduit live le
   2026-07-20 : Miami `[33]` → 44 hôtels, `[1]` → **0**.
3. La table encode une **asymétrie serveur non déductible** : les IDs de piscine sont
   OR-groupés (`(33, 34, 2982, 3000, 3001)` = le `HOTEL_POOL_EQUIPMENT_IDS` du serveur), tous
   les autres sont AND-requis individuellement.
4. Elle encode des **non-mappings délibérés** : `parking` (22 valet / 23 gratuit / 24 payant /
   25 garage / 2948 à proximité) et `rooftop` (2981 bar / 2982 piscine) sont **absents**
   parce qu'une famille multi-variantes ne peut pas exprimer « n'importe lequel » en AND —
   la recherche part sans filtre et le guard `amenity_truthfulness` hedge, ce qui est honnête.
   `sauna` ne garde que 2951 (2952 Hammam ANDerait), `shuttle` que 2949.

**Une table dont les absences sont du raisonnement n'est pas une table générable.** Le
remplacer par un appel dynamique au référentiel de MCP_B2C ne reproduirait ni l'OR-groupe ni
les 4 non-mappings : ça réintroduirait le bug de Miami sous une forme plus difficile à voir.

Les deux schémas de params virtuels qui l'entourent — `_AMENITIES_PROPERTY:73` et
`_AMENITIES_REMOVED_PROPERTY:87` — sont le **mécanisme** de l'invariant spine (« le LLM
n'écrit jamais une valeur de filtre ») : leur `enum` est `list(EQUIPMENT_IDS)`, donc ferme le
monde de ce que le modèle peut émettre. Les rendre dynamiques rouvrirait ce monde.

### 5.2 Contrats externes — renommer casse de l'historique ou un tiers

| Table | `fichier:ligne` | Pourquoi elle est en dur |
|---|---|---|
| `GUARD_SCORE_NAMES` | `libs/b2c_common/b2c_common/scores.py:47` | Contrat de séries temporelles Langfuse. Un renommage casse l'historique des 15 guards. Immuable par construction ; CLAUDE.md la cite comme « contrat figé ». |
| `_SCORE_CONFIG_IDS` | `scores.py:105` | UUIDs des score-configs créés sur l'instance Langfuse. Générables par personne : ce sont des identifiants distants. |
| `_DEGRADED_REASONS` | `scores.py:87` | Enum fermée des raisons de dégradation, lue par les scores. |
| `ROUTES` / `LEAF_ENDPOINTS` | `b2c_concierge/routing.py:24` / `:35` | La table de routage **est** le pattern `cs_copilot` imposé par CLAUDE.md (« table de routage en code »). La supprimer = supprimer l'architecture. |
| `CONTRACT_KEYS` | `b2c_concierge/facade.py:73` | Contrat iso de `POST /v3/chat` : les clés que la façade s'engage à rendre. Verrouillée par test. |
| `ALLOWED_MCP_TOOLS` | `hotel_search_agent/agent.py:76`, `faq_agent/agent.py:45` | Liste blanche : 2 des 6 tools MCP côté feuille search, 1 côté FAQ. Une liste blanche déductible du serveur n'est plus une liste blanche. |
| `MCP_TOOL_NAMES` | `hotel_search_agent/mcp_guard.py:22` | Même rôle, côté guard. |
| `PER_TOOL_CALL_LIMITS` | `hotel_search_agent/agent.py:98` | Plafond d'appels par tool et par tour (budget structurel ≤ 3 appels LLM, CLAUDE.md). |
| `_TARGET_TOOLS` | `response_bridge.py:63` | Les 2 tools dont la sortie est pontée. |
| `_EXTRA_EXPORT_SCOPES`, `_CALL_LLM_CONTENT_KEYS` | `libs/b2c_common/b2c_common/observability.py:101`, `:132` | Noms de scopes/attributs OTel de l'ADK et du SDK a2a — contrat d'un tiers, pas notre choix. OBS4. |
| `_MAX_TOKENS_DEFAULTS`, `_DISABLE_SPELLINGS`, `_OPENAI_REASONING_PREFIXES` | `llm_params.py:47`, `:41`, `:45` | Familles de modèles et leurs paramètres : contrat LiteLLM/fournisseur. |

### 5.3 Données de guards — un guard dont les motifs sont dynamiques n'est plus un guard

| Table | `fichier:ligne` | Note |
|---|---|---|
| `_AMENITY_CLAIM_PATTERNS`, `_CLAIM_NEGATION_MARKERS` | `amenity_guard.py:25`, `:39` | Motifs du guard de vérité `amenity_truthfulness`. |
| `_AMENITY_SYNONYMS` | `amenity_synonyms.py:18` | Sa docstring tranche déjà la question : « **Dayuse's own curated content, not a third-party library** ». Table de synonymes en/fr/es/it/de/pt/nl portée depuis agent-usa, données ET comportement. Aucune API interrogée ne la contient. |
| `_GENERIC_LOCATION_WORDS`, `_ECHO_NOISE_WORDS` | `geo_guards.py:167`, `:313` | Guards `generic_location_demotion` et `geocode_echo_back`. |
| `_TEXT_UNSAFE_STATE_ABBREVS` | `geo_guards.py:61` | Abréviations d'État qui collisionnent avec des mots courants en EN/FR/ES/IT/PT (`or`, `me`, `in`, `la`…). **Jugement linguistique, pas donnée** : aucune source ne le fournit. |
| `_EXONYM_EQUIVALENTS` | `geo_guards.py:274` | Voir §5.5 — le candidat n° 3 de la phase, réfuté. |
| `STREET_SUFFIX_TOKENS`, `_LEADING_DETERMINERS`, `_LEADING_ARTICLE_WORDS` | `geo_guards.py:417`, `:206`, `geo_resolver.py:321` | Normalisation d'adresse et d'article, côté guard. |
| `_TYPE_PRIOR`, `_LANDMARK_TYPE_PRIOR` | `geo_resolver.py:49`, `:274` | **Poids** du resolver géo déterministe (place 5.0 > locality 4.0 > … > region 1.0). Ce sont des paramètres de scoring calibrés, pas un référentiel. |
| `_MONTHS`, `_ORDINAL_WORDS`, `_NAME_STOPWORDS` | `profile.py:761`, `:1181`, `:951` | Extraction déterministe (mois, ordinaux, stopwords de nom d'hôtel). |
| `_RELATIVE_WEEKDAYS` | `datetime_resolver.py:179` | Jours relatifs pour la résolution de date. |

### 5.4 Enums fermées validées côté code — le mécanisme qui empêche le LLM de décider

`b2c_concierge/triage.py`. La docstring l. 51-57 explique exactement pourquoi, et c'est la
doctrine Fabien du 2026-07-20 citée dans le fichier : *« le LLM COMPREND la formulation (c'est
une étape de compréhension — ne pas pousser du déterminisme dans la compréhension du
langage) ; le CODE possède ce à quoi ça se résout, depuis une enum fermée validée ici. »*

| Table | Ligne | Note |
|---|---|---|
| `FAMILIES` | 48 | Les 6 familles de routage + `FALLBACK_FAMILY`. |
| `PICKS` | 58 | S-CX5. « Ajouter une valeur coûte une entrée d'enum plus un resolver — la forme du contrat ne change pas. » |
| `BOOKING_CONFIRMATIONS` | 79 | P1-1. R9 re-dérive quand même `confirmed` depuis `profile.pending_booking` : **aucune valeur de cette enum ne peut autoriser un lien de réservation à elle seule.** |
| `LANGUAGES` / `TEMPLATE_LANGUAGES` | 89 / 90 | Depuis UX2 les deux sont égales. Gardées comme deux noms : `response_language()` est le point d'étranglement unique qui les garde synchronisées. |
| `_ACK_WORDS` | 101 | Fallback regex du triage. |
| `_SUPPORTED_LANGUAGES` | `response_bridge.py:1113` | La copie locale côté feuille — la feuille est stateless et n'importe pas `b2c_concierge` (invariant A2A, CLAUDE.md). Duplication **assumée et commentée**, pas une dérive. |
| `_CONCIERGE_ONLY_KEYS` | `profile.py:315` | Clés de profil qui ne partent jamais vers la feuille (RGPD + surface A2A). |
| `_FEEDBACK_VALUES` | `facade.py:981` | OBS5 : `{0.0, 1.0}`, l'enum du feedback utilisateur. |
| `_TRUTHY` | `conversation_log.py:39` | Orthographes acceptées de l'en-tête `x-dayuse-synthetic` (colonne `is_synthetic`, RGPD). |
| `_ARG_TO_SLOT` | `occupancy.py:55` | 2 entrées, `adults`/`children`. |
| `_MINUTE_ENUM`, `_DATE_LABEL_PROPERTY`, `_DURATION_PROPERTY`, `_START_MINUTE_PROPERTY`, `_END_MINUTE_PROPERTY` | `datetime_resolver.py:112`, `70`, `100`, `113`, `118` | Mêmes params virtuels à enum fermée qu'`EQUIPMENT_IDS`, pour les dates/créneaux (S-G6). Même raison de vivre. |

### 5.5 Les 3 candidats de la phase, réfutés un par un

#### `_ISO_BY_COUNTRY_NAME` — `libs/b2c_common/b2c_common/hotel_urls.py:57`

La phase la donnait pour « le meilleur candidat » : « depuis, `countryCode` est bien présent
dans le payload et les deux appelants le passent déjà en premier argument ». **La première
moitié est fausse, la seconde est vraie et sans effet.**

Les deux appelants passent bien `countryCode` en premier argument (`inline_tools.py:318-320`,
`response_bridge.py:574-576`) — mais **la valeur passée est `None`** sur le chemin carte.
Mesure du 2026-08-28, `scripts/probe_country_code_coverage.py`, réseau réel :

| Chemin | Hôtels | `countryCode` résout un marché | `countryName` résout un marché | **Jambe NOM porteuse** |
|---|---:|---:|---:|---:|
| `search_offers` (carte de la feuille) | **201** | **0** (0 %) | **201** (100 %) | **201 (100 %)** |
| `get_hotel_details` (inline concierge) | 24 | 24 (100 %) | 24 (100 %) | 0 (0 %) |

21 pays avec inventaire, dont **12 non-euro** (GB, US, CH, TH, SE, SG, HK, AE, BR, AU, CA, NZ
— bien au-delà des « ≥ 4 pays dont un non-euro » demandés) et 9 euro (FR, ES, IT, DE, NL, BE,
AT, IE, PT). Détail : FR, ES, IT, DE, GB, US, CH, TH à 10 hôtels chacun (80), puis NL 10,
BE 10, AT 10, IE 10, PT 10, SE 4, SG 9, HK 10, AE 10, BR 8, AU 10, CA 10, NZ 10 (121) = 201.
MY, JP et MX n'avaient aucune offre à la date sondée (`total=0`). `countryCode` est
absent sur **la totalité** des 201 hôtels de `search_offers`, sur **tous** les marchés — ce
n'était donc pas un artefact FR (le piège explicite de la phase).

**Verdict : catégorie 1.** La table n'est pas un fallback mort, c'est **la seule chose qui
produit une URL d'hôtel sur le chemin carte**, c'est-à-dire tout ce que S-G12 garde. Zéro
divergence entre les deux jambes quand les deux répondent (`legs_disagree = 0`), et zéro
hôtel sans marché du tout (`no_market_at_all = 0`) : la table couvre **100 % des
`countryName` que MCP émet réellement** sur les 21 marchés observés — aucun trou de
couverture trouvé.

Deux commentaires du code sont ainsi **confirmés exacts**, pas périmés : `hotel_urls.py:54-56`
(« search_offers sends `countryName`, never an ISO code ») et `response_bridge.py:562-565`
(« search_offers doesn't send one today »). **C'était le fichier de phase qui portait
l'information périmée**, pas le code. Les deux commentaires ont été re-datés (§9).

> Nuance mesurée, à ne pas surinterpréter : `get_hotel_details` **envoie** bien un
> `countryCode` (24/24). Ça ne rend pas la table réductible — le chemin details a de toute
> façon la jambe nom en second, et le chemin carte, lui, n'a que la jambe nom.

#### `_LOCALE_COUNTRY` — `hotel_search_agent/geocode_tool.py:50`

La phase demandait : « la locale native arrive maintenant par la façade (S-G2), vérifier si la
table est encore sur le chemin chaud ». **La prémisse est inversée** : la façade fournit la
**locale** (`facade.py:666-668` → `profile.locale` `facade.py:388` → `geocode_tool.py:926-927`
`args["locale"]`), et cette table est précisément **ce qui transforme `"pt"` en `"PT"`**.
La façade est son alimentation, pas son remplacement. Aucune API interrogée (Mapbox v6,
Search Box, MCP) ne mappe langue → pays.

Atteinte à 4 sites, dont 2 **inconditionnels** sur le chemin de résolution géo :
`geocode_tool.py:649` et `:793` (`locale_country=guess_iso or _locale_country(locale)`, le
prior borné `_W_LOCALE` du resolver), plus `:569` et `:812` via `_soft_country`.

Et comme `EQUIPMENT_IDS`, **ses absences sont du raisonnement** : l'anglais est
volontairement absent (l. 48-49 : « en spans US/GB/CA/AU/… , a prior would mislead more than
it helps »). 6 entrées, toutes les paires langue→pays non ambiguës parmi les 29 marchés.
**Catégorie 1.**

#### `_EXONYM_EQUIVALENTS` — `hotel_search_agent/geo_guards.py:274`

La phase disait « probablement irréductible, mais le dire après avoir regardé ». Regardé :
irréductible, et pour une raison plus forte qu'attendu. 18 paires (`wien`/`vienna`,
`firenze`/`florence`, `londres`/`london`…), dans les deux sens, en ASCII plié des deux côtés.
Elle existe parce que le pliage de translittération ne peut pas franchir un exonyme :
`Gießen`/`giessen` est une variante diacritique, `Wien`/`Vienna` est **un autre mot**
(finding 9 de S-G9 : « Wien » → « Vienna, Austria » était rejeté en echo mismatch).

Le guard compare **le mot de l'utilisateur** au nom du candidat — donc même si Mapbox rend le
nom dans la langue demandée, il faut toujours ponter deux langues à la fois. Et là encore
l'omission porte le jugement, explicitement (l. 271-273) : le français `vienne` est **exclu
volontairement**, parce que Vienne est aussi une vraie ville française et que le mapper
ferait accepter au guard exactement l'échange de pays qu'il existe pour attraper.
**Catégorie 1.**

### 5.6 Tables JS de catégorie 1

| Table | `fichier:ligne` | Justification |
|---|---|---|
| `PLAN_TYPE_KEYS`, `BEDDING_KEYS`, `AMENITY_KEYS` | `chat/ui/messages.js:564`, `572`, `587` | Enums **fermées de MCP_B2C**, live-sondées sur 4 596 offres réelles (S-CX8), traduites côté widget. Leur commentaire dit la raison du choix : une valeur non mappée est **omise**, pas rendue brute — « `dayuse.late_break` devant un client est une pire réponse qu'une ligne en moins ». |
| `CURRENCY_SYMBOLS` | `chat/hotels/card.js:56` | Symbole d'affichage par code ISO, espacement compris. Voir §9 : son commentaire renvoyait à un symbole backend inexistant dans ce repo. |
| `DAYUSE_HOSTS` | `chat/security.js:10` | Allowlist d'hôtes du sanitizer. Voir §6 — elle est en catégorie 1 par sa fonction, mais son **contenu** est de la catégorie 2. |
| `MIME_CANDIDATES` | `chat/ui/voice-input.js:29` | Ordre de préférence des codecs `MediaRecorder` — contrat navigateur. |
| `EXTRA_IMAGE_HOSTS` | `chat/security.js:28` | 2 hôtes CDN images. |

---

## 6. Catégorie 2 — la vraie dette, chiffrée

### 6.1 Les chiffres

`scripts/measure_market_table_drift.py` (lecture seule, hors ligne, rejouable) :

```
=== table sizes ===
_MARKET (py)              : 22 countries
COUNTRY_META (js)         : 23 keys (22 distinct codes)
COUNTRY_SLUG_TO_CODE (js) : 24 slugs
DAYUSE_HOSTS (js)         : 16 host roots

1. country SET agreement           : aucun écart dans les deux sens
2. hotel country-path SLUG         : 0/22 marchés en désaccord
3. market HOST (booking vs widget) : 8/22 marchés en désaccord  ← 36 %
4. DAYUSE_HOSTS admet-il _MARKET ? : 0/22 rejetés aujourd'hui
5. slugs en trop côté JS           : ['uk', 'united-states']
6. total entrées tenues à la main  : 85 dans 4 tables, 2 langages
```

Le désaccord n° 3, marché par marché — hôte de réservation réel (`_MARKET`) contre hôte du
`browseUrl` du widget (`COUNTRY_META`) :

| | AE | AU | BR | CA | HK | MY | NZ | TH |
|---|---|---|---|---|---|---|---|---|
| back | `www.dayuse.ae` | `au.dayuse.com` | `www.dayuse.net.br` | `ca.dayuse.com` | `www.dayuse.com.hk` | `my.dayuse.com` | `nz.dayuse.com` | `th.dayuse.com` |
| front | `www.dayuse.com` | `www.dayuse.com` | `www.dayuse.com` | `www.dayuse.com` | `www.dayuse.com` | `www.dayuse.com` | `www.dayuse.com` | `www.dayuse.com` |

**Ce qui va bien, et qu'il faut dire** : l'ensemble des pays et les slugs de chemin sont
**exactement d'accord** aujourd'hui (0/22 d'écart), et `DAYUSE_HOSTS` admet encore les
22 hôtes de `_MARKET` (0 rejeté) grâce à la règle sous-domaine d'`isHostMatch`. La panne
n'est pas en cours. Elle est à **un marché de distance** : ajouter à `_MARKET` un pays avec un
eTLD réellement nouveau (`dayuse.pl`) sans toucher `security.js` fait rejeter l'URL par le
sanitizer, ce qui déclenche le chemin de §6.2. C'est le scénario exact de la panne de 404 de
4 jours du 2026-07-06 que `hotel_urls.py:8-10` raconte.

Deux commentaires de ces tables **renvoient à un repo qui n'est pas celui-ci** — signe que le
lien back/front n'a jamais été re-tissé après le portage : `security.js:5-9` cite
`_BOOKING_HOST_BY_COUNTRY in src/application/shared/hotel_urls.py` (chemin agent-usa ; ici le
symbole s'appelle `_MARKET` dans `libs/b2c_common/`), et `card.js:54-55` dit « Mirrors the
backend `_CURRENCY_DISPLAY` » alors que **`_CURRENCY_DISPLAY` n'existe pas dans ce repo**
(`grep -rn "_CURRENCY_DISPLAY" agents libs` → 0). Les deux pointeurs ont été corrigés (§9).

### 6.2 🔴 Le constat non prévu : la « None honnête » du back est défaite par le front

`hotel_urls.py:1-18` pose un contrat explicite : *« nothing in this repo may ever slugify a
display name into a URL — that is exactly the prod defect this module closes (LLM-invented
`a-roport`/`eurohotel` slugs on the wrong domain) »*, et *« An unmapped country or a malformed
slug yields None — the card honestly has no link rather than a guessed one »*.

**Le widget ne respecte pas ce contrat.** `markets.js:232-245::buildHotelFallbackUrl`
slugifie le nom d'affichage, et `card.js:149-151` l'utilise dès que `hotel.url` est absent :

```js
const fallbackUrl = buildHotelFallbackUrl(hotel);
const sanitizedUrl = sanitizeDayuseUrl(appendAmplitudeIdToUrl(hotel.url || fallbackUrl));
```

Exécuté sur les **vrais modules** du widget (aucun mock, `node` sur `markets.js` +
`security.js`) :

```
Poland    | fallback=https://dayuse.com/hotels/usa/h-tel-m-tropole-spa
          | passes host allowlist -> rendered=https://dayuse.com/hotels/usa/h-tel-m-tropole-spa
Japan     | fallback=https://dayuse.com/hotels/usa/grand-hyatt-tokyo
          | passes host allowlist -> rendered=https://dayuse.com/hotels/usa/grand-hyatt-tokyo
Thailand  | fallback=https://www.dayuse.com/hotels/thailand/bangkok-riverside
          | passes host allowlist -> rendered=https://www.dayuse.com/hotels/thailand/bangkok-riverside
```

Trois faits dans ces 3 lignes :

1. Un hôtel **polonais** est rendu comme une page **`/hotels/usa/`** — `inferCountryCodeFromHotel`
   ne sait rien faire d'un `country: "Poland"` (il exige 2 lettres), donc `getMarketMeta`
   retombe sur son défaut `'US'`. **Tout hôtel d'un pays absent de `_ISO_BY_COUNTRY_NAME`
   devient un hôtel américain.**
2. Le slug est **inventé et abîmé** : `Hôtel Métropole & Spa` → `h-tel-m-tropole-spa`. C'est
   littéralement le défaut `a-roport` cité par la docstring du back.
3. Ça **passe l'allowlist** et s'affiche comme un lien de réservation vivant. Et
   `trackEvent('booking_url_fallback')` (`card.js:152`) ne se déclenche **que** si
   `hotel.url` existait et a été rejeté — donc le cas « pas d'url du tout → url fabriquée »
   est **totalement non tracké**.

**Conséquence directe pour la question de la phase** : réduire `_ISO_BY_COUNTRY_NAME` ne
produit pas « pas de lien » (la dégradation honnête que le module documente), ça produit
**un lien fabriqué sur le mauvais marché**. Chaque entrée retirée de la table est un marché
qui se met à afficher des liens américains inventés. C'est la raison la plus forte de la
garder, et elle n'était dans aucun des deux fichiers.

Portée de la preuve, à ne pas surinterpréter : c'est une exécution **déterministe hors
ligne** du vrai code widget, pas une observation en prod. Je n'ai **pas** observé d'hôtel réel
dans un pays absent de la table — les 21 marchés à inventaire sont tous couverts, et MY/JP/MX
n'avaient aucune offre à la date sondée (`total=0`). Le chemin est donc **prouvé atteignable
et prouvé fabricant**, mais son **taux d'occurrence en prod n'est pas mesuré**.

### 6.3 Proposition — chiffrée, non implémentée

Conformément au périmètre (« on chiffre, on propose, Fabien tranche »), rien de ce qui suit
n'a été codé.

**Option A — une source unique servie par la façade** (la piste du fichier de phase).
Un JSON du référentiel exposé par la façade, le widget le charge au boot.
*Coût* : 1 endpoint + cache/ETag côté façade, suppression de `COUNTRY_META` et
`COUNTRY_SLUG_TO_CODE`, `DAYUSE_HOSTS` dérivé au chargement. *Ce que ça casse* : le widget
gagne une dépendance réseau au boot pour rendre une carte — un échec de fetch doit avoir un
défaut figé, donc **on ne supprime pas vraiment la table JS, on la transforme en cache**.
Le sanitizer d'hôtes se met à dépendre d'une réponse réseau : mauvaise direction pour un
composant de sécurité.

**Option B — génération au build du widget.** `_MARKET` reste la source ; un script émet
`markets.generated.js` et la liste d'hôtes ; CI échoue si le généré diverge du committé.
*Coût* : 1 script + 1 job CI. *Ce que ça casse* : rien au runtime, le widget reste statique
et le sanitizer garde une table figée. **Recommandation : B.** Elle applique la leçon de
`hotel_urls.py:8-10` (UNE table) sans mettre la sécurité au bout du réseau.

**Option C — le garde-fou seul, sans unification** (le moins cher de très loin).
Un test qui échoue si `DAYUSE_HOSTS` cesse d'admettre un hôte de `_MARKET`, et si un
`hotelCountrySlug` de `COUNTRY_META` diverge de `_MARKET`. Les deux parseurs existent déjà
dans `scripts/measure_market_table_drift.py` : le convertir en test coûte ~30 lignes.
Ça ne supprime aucune duplication mais **ça supprime la panne silencieuse**, qui est le seul
vrai risque chiffré ici. Non fait dans cette phase parce que l'unification de ces tables est
explicitement hors périmètre — mais si une seule chose doit être faite, c'est celle-là, et
elle est indépendante du choix A/B.

**Question annexe à trancher avec** : faut-il aligner `buildHotelFallbackUrl` sur le contrat
du back (rendre `null` et ne pas afficher de lien) ? C'est un changement de comportement
visible client, donc une décision produit, pas un sous-produit d'audit. Chiffrage : ~10 lignes
dans `markets.js` + `card.js`. Mon avis : oui, et c'est plus urgent que l'unification.

---

## 7. `US_STATE_*` — la référence, et sa nuance

La phase demandait de citer ces tables comme exemple du bon état final. Elles le sont —
`geo_guards.py:49-56` dérive tout du paquet `us` :

```python
US_STATE_ABBREV_TO_NAME = {state.abbr.lower(): state.name for state in us.STATES}
US_STATE_NAME_TO_CANONICAL = {name.lower(): name for name in US_STATE_ABBREV_TO_NAME.values()}
```

**Mais l'exemple est plus instructif que « dérivez d'une lib »** : juste après la dérivation,
le code garde **deux correctifs manuels, chacun commenté avec sa raison** —
`US_STATE_NAME_TO_CANONICAL["mass"] = "Massachusetts"` (raccourci vu en prod, session
5d7c8813) et `.pop("washington")` (ambigu DC/État en texte libre, ne jamais inférer).

C'est la vraie leçon de la phase : **même le bon état final garde un delta possédé à la main,
parce que le jugement métier n'est pas dans la bibliothèque.** Le progrès n'est pas
« zéro table en dur », c'est « la partie mécanique vient d'une source, la partie jugement est
en dur et commentée ». `EQUIPMENT_IDS`, `_LOCALE_COUNTRY` et `_EXONYM_EQUIVALENTS` sont
exactement dans cet état : ils sont **entièrement** de la partie jugement.

---

## 8. Suppressions : aucune, et la mesure qui le prouve

Le repo a été balayé pour des tables mortes — pour chaque nom de table, compte des références
**hors** ligne de définition :

```bash
grep -rnE "^ *_?[A-Z][A-Z0-9_]{2,}(: *[^=]+)? *= *(\{|\[|frozenset|dict\(|tuple\(|set\()" \
  agents libs --include='*.py' | grep -v "/tests/" | while IFS=: read -r f l rest; do
  name=$(echo "$rest" | grep -oE "^ *_?[A-Z][A-Z0-9_]{2,}" | tr -d ' ')
  uses=$(grep -rn "\b$name\b" agents libs --include='*.py' | grep -v "^$f:$l:" | wc -l)
  echo "$uses|$name|$f:$l"
done | sort -n
```

**Minimum observé : 1.** Aucune table Python n'a 0 usage. Combiné aux §5 et §6, il n'y a
**aucune suppression prouvée à exécuter dans cette phase** — et c'est le résultat, pas un
échec : la phase demandait de ne supprimer que ce que la mesure prouve mort, et la mesure ne
prouve rien de mort.

### La seule entrée provablement morte du repo — et pourquoi elle n'est pas supprimée ici

`COUNTRY_META.UK` (`web/vendor/static/js/chat/markets.js:46-51`, 6 lignes) est
**inatteignable**. `COUNTRY_META` n'est lu qu'en un point, `getMarketMeta:219`, et cette
fonction passe systématiquement la clé par `normalizeCountryCode`, qui convertit `'UK'` → `'GB'`
avant la recherche (`markets.js:177-182`). Donc `COUNTRY_META['UK']` ne peut jamais être
adressé. (À ne pas confondre avec `COUNTRY_SLUG_TO_CODE['uk']`, qui **est** atteignable via un
chemin d'URL `/s/uk`.)

Non supprimée dans cette phase, pour deux raisons de périmètre :
1. Le DoD exige « chaque suppression avec son test ». **Il n'existe aucun harnais de test JS
   dans ce repo** (aucun `package.json`, aucun `*.test.js`, aucun test Python ne charge
   `markets.js`) — en créer un pour 6 lignes mortes serait un chantier bien plus gros que le
   gain.
2. C'est `markets.js`, le fichier dont la refonte est **explicitement hors périmètre**
   (« Unifier `_MARKET` / `COUNTRY_META` dans cette phase »). L'option B ou C de §6.3 devra
   toucher ce fichier de toute façon : la suppression y est gratuite, et testée par le
   générateur.

**Proposé pour la phase d'unification, pas fait ici.**

---

## 9. Ce qui a été modifié : 4 commentaires, zéro comportement

Aucune ligne exécutable n'a changé. La mesure a établi que 4 commentaires induisent le
prochain lecteur en erreur — dont les deux qui auraient conduit à supprimer
`_ISO_BY_COUNTRY_NAME`. Corrigés :

| `fichier:ligne` | Avant | Après |
|---|---|---|
| `libs/b2c_common/b2c_common/hotel_urls.py:54-56` | « probed 2026-07-20 », lu comme un fallback | Re-sondé 2026-08-28 : 0/201 hôtels sur 21 marchés portent un `countryCode` ; **jambe porteuse à 100 %**, pas un fallback. Renvoi à ce rapport. |
| `hotel_search_agent/response_bridge.py:562-565` | « probed live 2026-07-20 » | Confirmé encore vrai le 2026-08-28 (0/201), avec le compte. |
| `web/.../chat/security.js:5-9` | `_BOOKING_HOST_BY_COUNTRY in src/application/shared/hotel_urls.py` (chemin agent-usa) | Le vrai symbole de ce repo : `_MARKET` dans `libs/b2c_common/b2c_common/hotel_urls.py`, + le chiffre 0/22 rejetés du 2026-08-28. |
| `web/.../chat/hotels/card.js:54-55` | « Mirrors the backend `_CURRENCY_DISPLAY` » — symbole absent de ce repo | Dit d'où vient réellement la valeur (`currency_code` de MCP via la carte) et que le miroir backend n'existe pas ici. |

Deux scripts de mesure ajoutés, tous deux hors du chemin de production et **volontairement
pas des pytest** (appels réseau réels / lecture de fichiers du widget), même posture que
`probe_currency_priceeuro.py` :

- `scripts/probe_country_code_coverage.py` — la mesure `countryCode` (§5.5).
- `scripts/measure_market_table_drift.py` — le chiffrage de la catégorie 2 (§6.1).

---

## 10. Ce qui reste ouvert — arbitrages pour Fabien

1. **Catégorie 2** : option A / B / C de §6.3. Recommandation : **C tout de suite**
   (~30 lignes, supprime la panne silencieuse), **B ensuite** si l'unification est voulue.
2. **`buildHotelFallbackUrl`** (§6.2) : aligner le widget sur le contrat « pas de lien plutôt
   qu'un lien inventé » ? Changement visible client. Mon avis : oui, avant l'unification.
3. **Le trou de tracking** : `booking_url_fallback` ne se déclenche pas quand `hotel.url` est
   absent. Une ligne, et ça rendrait le taux d'occurrence de §6.2 mesurable en prod — ce que
   cette phase n'a pas pu faire.
4. **Catégorie 0** (30 tables de traduction, §4) : chantier i18n séparé (UX2-bis), pas un
   chantier mappings. Rien à faire ici.
5. **`COUNTRY_META.UK`** : 6 lignes mortes prouvées, à supprimer dans la phase qui touchera
   `markets.js`.

Aucun de ces 5 points n'est une suppression de catégorie 1, et **aucune table de catégorie 1
n'a été touchée** — donc le STOP prévu par la phase (« si l'audit conclut qu'une table de
catégorie 1 doit bouger, il s'arrête et pose la question ») n'a pas eu à être déclenché.
La phase a en réalité fait l'inverse : elle a **promu** 2 tables (`_ISO_BY_COUNTRY_NAME`,
`_LOCALE_COUNTRY`) de la catégorie 3 vers la catégorie 1.

---

## 11. État des vérifications

| Contrôle | Résultat |
|---|---|
| `bash scripts/dayuse_guardrails.sh .` **avant** la phase | `Dayuse guardrails: OK` |
| Aucune règle guardrail sur constantes/hosts en dur | Vérifié (`grep` sur le script) |
| `pytest -q` | **1691 passed, 1 skipped** — identique à la baseline post-#107, aucun test ajouté ni modifié (rien d'exécutable n'a changé). ⚠️ Le DoD de la phase annonçait « baseline 1452 » : chiffre périmé, la baseline réelle est 1691 depuis UX2/#107. |
| `ruff check .` | `All checks passed!` |
| `mypy agents libs` | `Success: no issues found in 48 source files` |
| `bash scripts/dayuse_guardrails.sh .` **après** | `Dayuse guardrails: OK` |
| 3 fichiers JS édités | `node --check` OK ×3, + import réel de `markets.js` / `security.js` |
| Code de MCP_B2C relu | **Non** — mesures sur ses réponses uniquement |
| 429 MCP | Espacement 1,5-2 s entre appels ; aucun 429 rencontré sur les 2 runs |

> Les chiffres du tableau ci-dessus sont ceux de **l'audit seul**. Les suites arbitrées (§12)
> ajoutent 11 tests : `pytest -q` finit à **1702 passed, 1 skipped**.

---

## 12. Suites arbitrées par Fabien le 2026-08-28

Les 4 arbitrages de §10 ont été tranchés le jour même : **« 1. C now and B later · 2. yes, and
ahead of unification · 3. ok · 4. ok »**. Ils sont livrés sur la même branche/PR. Ce qui suit
n'est donc plus de l'audit : c'est du code, et §9 (« 4 commentaires, zéro comportement ») ne
décrit plus que la première moitié de la PR.

### 12.1 Option C — le garde-fou de dérive (sans unification)

`tests/test_market_table_drift.py`, 11 tests. Il **n'unifie rien** — il rend la panne
silencieuse impossible, ce qui était le seul risque réellement chiffré de §6.1 :

- tout hôte de `_MARKET` est admis par `DAYUSE_HOSTS` (le test qui compte) ;
- les slugs de chemin `_MARKET` ↔ `COUNTRY_META` concordent ; les ensembles de pays aussi ;
- tout slug émis par le back est relisible par `COUNTRY_SLUG_TO_CODE` ;
- la divergence connue des 8 hôtes de browse est **plafonnée, pas interdite** (`<= 8`) : c'est
  une question produit, pas une panne, et la verrouiller aurait été la trancher — mais un 9e
  marché divergent réveille le test.

**Les parseurs sont importés de `scripts/measure_market_table_drift.py`, pas réécrits** — les
réécrire aurait fait de ce test une **cinquième** copie tenue à la main de la table qu'il
surveille.

Deux protections contre le faux vert : une classe `TestTheParsersActuallyParsed` (un parseur
qui rend `{}` se lit exactement comme « aucune dérive » — même piège que le faux positif de
`_old_dedup_count` dans `probe_rateplan_dedup.py`), et un test qui vérifie que le contrôle
d'allowlist **peut** échouer (`www.dayuse.pl` refusé, `th.dayuse.com` accepté).

**Preuve que le garde tire, avec la signature de la panne** — en retirant temporairement
`'dayuse.fr'` de `DAYUSE_HOSTS` :

```
AssertionError: 1 market host(s) would be REJECTED by DAYUSE_HOSTS in
  web/vendor/static/js/chat/security.js: {'FR': 'www.dayuse.fr'}. Every hotel card in
  those markets renders with no hotel-page link. Add the host root there.
```

Restauré ensuite (`git diff` vérifié : seul le commentaire volontaire subsiste).

### 12.2 Décision 2 — le widget ne fabrique plus d'URL

`buildHotelFallbackUrl` est **supprimée** de `markets.js`, avec ses 2 appelants
(`utils.js::buildHotelMap`, `hotels/card.js::createHotelCard`). Pas de remplacement : pas
d'URL serveur = pas de lien. Le commentaire laissé à sa place garde la trace de ce qu'elle
émettait et pourquoi c'était grave, pour qu'elle ne soit pas réintroduite par commodité.

Conséquence de rendu, assumée : `renderFooter` **n'affiche plus le lien hôtel** quand il n'y a
pas d'URL, au lieu de rendre un `href="#"`. La carte garde son prix et, s'il y en a un, son
bouton de sélection — elle cesse simplement de promettre une page qu'elle ne peut pas
atteindre. C'était la formulation explicite de l'arbitrage (« rendre `null`, ne pas afficher
de lien »).

### 12.3 Décision 3 — le cas non tracké devient visible

Le garde passe de `if (hotel.url && !sanitizedUrl)` à `if (!sanitizedUrl)`, avec une propriété
`reason` : `'rejected_by_allowlist'` (le cas déjà suivi) ou `'missing_from_payload'` (le cas
invisible, §6.2). **Le nom d'événement `booking_url_fallback` est conservé** : le renommer
casserait la série Amplitude, exactement le raisonnement qui rend `GUARD_SCORE_NAMES`
immuable (§5.2). Le taux d'occurrence que cet audit n'a pas pu mesurer devient mesurable dès
le déploiement.

### 12.4 Décision 4 — `COUNTRY_META.UK` supprimée, et l'objection de §8 levée

§8 donnait deux raisons de ne pas la supprimer. Les deux sont tombées : `markets.js` est
maintenant dans le périmètre (décisions 2 et 3 y touchent), et **le harnais de test JS qui
manquait existe**.

`tests/widget/widget_url_contract.test.mjs` — 9 tests, `node:test`, zéro dépendance, sur les
**vrais** modules widget. Câblé dans `pytest -q` via
`test_market_table_drift.py::TestWidgetUrlContract`, donc **il tourne en CI sans modifier le
workflow** (node est présent sur `ubuntu-latest`) ; skip propre si `node` manque en local.
Il vérifie notamment que la suppression de l'alias est **sûre** (`getMarketMeta('UK')` →
`GB`, slug et host inclus) et que `COUNTRY_SLUG_TO_CODE['uk']`, lui, **reste atteignable** —
pour qu'un futur « nettoyage » ne l'emporte pas avec l'alias mort.

🪤 **La subtilité qui rend ce harnais possible** : `card.js` ne peut pas être ÉVALUÉ en node nu
(il importe des modules qui touchent le DOM). Mais ESM **parse et lie tout le graphe avant
d'évaluer**, donc un import resté sur une exportation disparue ressort en
`SyntaxError: does not provide an export named`, que le test attrape, tandis qu'une
`ReferenceError` sur `document` signifie que le linkage a réussi — le seul point testé.
Vérifié en réintroduisant l'import mort : le test tombe avec ce message exact.

### 12.5 Ce qui n'a PAS été fait

- **L'unification (option B)** reste à faire : c'est sa propre phase. Les 85 entrées sont
  toujours tenues à la main dans 4 tables et 2 langages — le garde-fou empêche seulement que
  leur dérive soit silencieuse.
- **La divergence des 8 hôtes de browse** n'est pas corrigée (question produit, §6.1).
- **Le taux d'occurrence du cas `missing_from_payload`** n'est toujours pas chiffré, et ne peut
  pas l'être par une sonde : il demande un hôtel dans un pays absent de
  `_ISO_BY_COUNTRY_NAME`, et les 21 marchés à inventaire sont tous couverts. C'est
  l'événement ajouté en 12.3 qui répondra dans la durée.

### 12.6 Déployé et vérifié en prod (2026-08-28)

`widget` seul — les modifications Python de la PR sont prouvées commentaires-seuls, donc les
3 autres services gardent une estampille honnête. `LANGFUSE_RELEASE=48c399f` posé avec
`--skip-deploys` (`latestDeployment.createdAt` inchangé après le stamp, vérifié), puis
`railway up --service widget --detach` → `SUCCESS 2026-08-28T07:56:17Z`.

Quatre preuves, détaillées dans le bloc `HANDOFF.md` du 2026-08-28 :

1. **Le code servi a changé** : `buildHotelFallbackUrl` et `UK:` étaient servis en prod avant,
   0 occurrence après ; les 4 fichiers JS servis sont byte-identiques à HEAD.
2. **Le rendu, sur le module déployé, dans un vrai Chrome** : avec `url` → lien réel
   `dayuse.fr/hotels/france/…` ; **sans `url` → aucun href, aucun `/hotels/usa/` fabriqué**,
   carte et prix intacts. La même fixture rendait `dayuse.com/hotels/usa/h-tel-m-tropole-spa`
   avant le déploiement.
3. **Le trou de tracking est fermé** (`sendBeacon`/`amplitude.track` interceptés) : url valide
   → aucun événement ; pas d'url → `reason: "missing_from_payload"` ; url rejetée →
   `reason: "rejected_by_allowlist"`. Même nom d'événement, série Amplitude continue.
4. **Un vrai tour** (`?q=`, payloads MCP réels, `x-dayuse-synthetic: 1`) : 5 cartes, 5 liens,
   tous sur `www.dayuse.fr`, 0 `href="#"`, 0 lien fabriqué, slug serveur réel.
