# HANDOFF — AgentB2C

État du chantier pour reprise en session fraîche. **Lire en entier avant d'agir ; ne pas reconstruire ce qui existe.** Mettre à jour en fin de CHAQUE session (bloc daté en tête).

> 🗄️ Les blocs du 2026-07-16 au 2026-09-09 sont dans [`HANDOFF-ARCHIVE.md`](HANDOFF-ARCHIVE.md) (historique, non réécrit) : un renvoi « HANDOFF <date> » antérieur au 2026-09-14 s'y cherche par date.

> 📋 **Pour savoir QUOI faire ensuite, ouvrir [`CHANTIERS.md`](CHANTIERS.md)** (état vérifié au 2026-09-14) : la liste des chantiers ouverts, chacun avec sa preuve, ses actions et un prompt prêt à coller — plus la liste de ce qu'il ne faut **pas** relancer parce que c'est déjà livré. `tasks/todo.md` est périmé et ne doit plus servir de référence.

## 🚀 2026-10-28 — `faq`, `hotel-search` et `concierge` déployés sur `b6f9402` (#168, #169, #170)

**Déployé** (`DEPLOY.md`, par Claude à la demande de Fabien), depuis `../AgentB2C-deploy` détaché
sur `b6f9402`, arbre propre. Pré-vol : pytest 3 367 passés / 1 skippé, sur l'arbre de `83b9a47`
(identique à `b6f9402`). Estampilles posées avec `--skip-deploys` (`faq` `8d1579b`, `hotel-search`
`a407144`, `concierge` `b446a65` → `b6f9402`), puis `up` dans l'ordre faq → hotel-search →
concierge : les 3 en SUCCESS à 14:03Z. `widget` (`cb361c0`) inchangé.

**`CONCIERGE_LEAF_TIMEOUT_SECONDS` supprimée par Fabien** (UI) juste avant. 🪤 La suppression a mis
en file un redéploiement de l'**ancien** code (14:01Z), qui sans la variable coupe la recherche
à 15 s et la FAQ à 25 s. Il a été remplacé par le `up` deux minutes plus tard (statut REMOVED).
Supprimer une variable redéploie comme en poser une : la retirer juste APRÈS le `up` (le
redéploiement repart alors du nouveau code). Piège ajouté à `DEPLOY.md`.

**Preuve** (widget, synthétique, sessions `synthetic-47c28036-*`, traces en release `b6f9402`
sur les 3 services) :
- #170 : « i need a room with a hot tub » → « Where and for which day would you like to book? »,
  sans chips, `clarification_reason=location` (5,8 s, 2 appels luna) ; puis « tomorrow in new
  york city or long island » → 5 hôtels pour le 29/10 autour de New York (pas de bar).
  « a hot tub room in Paris » → question du jour seule, avec ses 3 chips.
- #168 (route FAQ en SSE) : `progress` à 0,1 s, second `progress` juste après la feuille, puis
  `hotels`, `token`, `done`. Le 1er tour FAQ après le déploiement a pris 23,8 s : 13 s **avant**
  le premier appel LLM de la feuille (démarrage à froid), puis 2 appels de 4,1 et 2,7 s, sans
  relance. À chaud : 8,4 s et 10,3 s.
- Un timeout ne se provoque pas à la demande : la relance et le budget de 45 s ne sont prouvés que
  par les tests et le run local.

**Reste** :
- Dans quelques jours : la part de `template:date_place_question` parmi les questions du jour, et
  la latence des feuilles au-delà de 15 s / 20 s (des `generate_content` en ERROR = timeouts).
- Semer l'item `geo-poi-nyc-or-long-island` dans Langfuse (Fabien).

## 📅 2026-10-28 — Demander le jour ET le lieu ensemble (branche `feat/ask-day-and-place`)

**Constat** (session prod `7e296e4b`, 2026-10-27) :
- **T1** « i nedd room with hot tub in it » → question du jour (règle `date_checked`).
- **T2** « The day after tomorrow » → feuille sans lieu → `missing_city` → la synthèse demande la
  ville (3 appels LLM, 8,2 s).
- Deux tours avant la moindre recherche.

**Fait** :
- **`place_check.py`**, `names_a_place(request)` : un appel LLM aux paramètres du rôle TRIAGE
  (luna, effort `none`, timeout 5 s, `max_retries=0`, une seule tentative), un booléen fermé, une
  métrique `llm_call phase=place_check` sans contenu. Toute panne ou réponse hors contrat → `None`.
  Le prompt du triage n'est pas touché.
- **`agent.py`**, quand la question du jour part :
  - si le profil connaît déjà un lieu (`city`, `zone`, `metro`, `region_anchor`, `named_hotel`, le
    GPS `search_anchor`), aucun appel ;
  - sinon `budget.charge("place_check")` (2e créneau, avant la feuille ; `MAX_LLM_CALLS_PER_TURN`
    inchangé, inutile de le relever), sur la demande que la réponse remettra à la feuille.
  - `False` → « Où et pour quel jour souhaitez-vous réserver ? » (7 langues), **sans chips** : une
    puce de jour répondrait à la moitié et ramènerait la question de ville.
    `clarification_reason="location"`, route `template:date_place_question`.
  - `True` ou `None` → la question du jour actuelle, avec ses chips.
  - `pending_search.date_question` est inchangé : la réponse part vers la feuille avec la demande
    seule, sans étiquettes.

**Preuves** :
- **Tests** : sans lieu → jour+lieu (`phases=triage,place_check`, feuille non appelée) ; « hot tub
  room in Paris » → jour seul ; lieu connu par GPS → 0 appel ; timeout / JSON hors contrat / texte
  libre → jour seul, sans relance ; réponse « tomorrow in Paris » → la feuille reçoit demande puis
  réponse ; 7 langues ; aucun contenu de la demande dans la métrique ni les logs ; les 2 transports
  HTTP (`suggestions: []`).
- **Scripts de test** : les tests existants qui passent par la question rejouent désormais l'appel
  explicitement. Avant, l'appel mangeait la réponse scriptée du tour suivant et ils passaient par
  accident ; le test HTTP, lui, partait sur le réseau (1,46 s → 0,01 s une fois l'appel stubbé).
- **Contrôles négatifs** : décision désactivée → 7 rouges ; lieu connu ignoré → rouge.
- **Local réel** (Redis :6390) :
  - « i nedd room with hot tub in it » → « Where and for which day would you like to book? » en
    2,9 s (2 appels) ;
  - puis « tomorrow in Paris » → 5 hôtels, `search_offers` sur Paris, `date` de demain,
    `hotelEquipmentIds: [41]` (le hot tub du premier tour a tenu) ;
  - « hot tub room in Paris » → question du jour avec ses 3 chips ;
  - « une chambre avec jacuzzi » → « Où et pour quel jour souhaitez-vous réserver ? ».
- **Gates** : pytest 3 341 passés / 1 skippé ; ruff, mypy, guardrails OK.

**Reste** :
- Mergé (#170) et déployé : voir le bloc 🚀 du 2026-10-28.
- Quelques jours après, en prod : la part des `template:date_place_question` parmi les questions du
  jour, et combien de leurs tours suivants cherchent du premier coup.

## 🏝️ 2026-10-28 — Une zone n'est jamais un commerce qui porte son nom (branche `fix/area-never-a-business-poi`)

**Constat** (session prod `7e296e4b`, T3, release `cb361c0`) : « new york city or long island »
→ la feuille a reçu Long Island en `kind=region` avec la ville NYC. Search Box a rendu « The Long
Island Bar » (Brooklyn, `poi`) → `search_offers` à 2 km avec le filtre hot tub → 0 hôtel.
`geocode_echo_back` et `state_anchoring` ont tiré sans rien rattraper.

**Déjà corrigé sur `main` pour ce cas exact** : `d20af35` (#162, déployé à 16:38Z le 10-27, deux
heures après la session) cherche la ville quand une région est nommée avec elle. Vérifié hors
ligne, puis en direct (3/3 tours locaux : Long Island lu `region`, recherche sur New York entière,
pas de `radiusKm`).

**Le même défaut restait ouvert** :
- **Hors ligne sur `main`** : le même lieu étiqueté `admin_district` ou `neighborhood`, ou nommé
  sans ville, rendait toujours le bar.
- **En prod, 2026-10-15/28** (654 `geocode_location`), 11 lieux de type zone résolus en `poi`.
  - Les faux sont des commerces qui portent le nom du lieu : « metro Detroit » → *Metropolitan
    Detroit Area Hospital Services* (`a407144`, le code actuel), « centro » → *Centro Lampo Roma*
    (`a407144`), « Bergen County » → *… Islamic Center*, « the sea » → *China Sea Milton*
    (Brisbane).
  - Les justes gardent le nom du lieu : *Châtelet*, *Basovizza*, *Manhattan*.

**Fait** (`geocode_tool.py`) : `_business_named_after_the_area`.
- **La règle** : pour une zone `region` / `admin_district` / `neighborhood`, un `poi` de Search Box
  dont le nom porte un mot absent du nom demandé et de la ville est un commerce.
  - « Lago como » pour Lago di Como reste accepté.
  - Les landmarks / gares / aéroports / adresses ne sont jamais jugés ainsi.
- **Où elle s'applique** : aux 3 endroits où un poi de Search Box est accepté (tier 2 avec ville,
  repli `natural` sans ville, zone avec GPS sans ville).
- **Ce qu'elle fait sur un rejet** : `geocode_echo_back` (score existant) et le statut
  `area_resolved_to_a_business` dans la trace.
  - Avec une ville : la ville entière (un appel récursif de `geocode_core` sans zone, l'issue même
    de la région nommée avec sa ville).
  - Sans ville : l'issue honnête existante.
- Item d'éval `geo-poi-nyc-or-long-island` (`b2c-geo-poi.jsonl`, `regression_guard` : 1 hôtel au
  moins, pas de `radiusKm`).

**Preuves** :
- **Tests** : l'intention exacte de la prod ; Long Island en `admin_district` / `neighborhood` ;
  « metro Detroit » sans ville ; Châtelet gardé ; la table des 11 cas de prod.
- **Contrôles négatifs** :
  - règle désactivée → 8 rouges ;
  - le cas exact reste vert sans la règle (la région nommée avec sa ville le couvre) et sans
    `d20af35` (la règle le couvre) ; il ne tombe qu'avec les deux désactivés : 2 protections.
- **Sonde réelle, en process** (vrais clients Mapbox, sans LLM, IP locale) :
  - Long Island `admin_district` / `neighborhood` + NYC : Search Box rend bien le bar, rejeté →
    New York entière ;
  - « metro Detroit » → non résolu (au lieu de l'hôpital) ;
  - Châtelet gardé.
- **Gates** : pytest 3 345 passés / 1 skippé ; ruff, mypy, guardrails OK.

**Résidus notés** :
- Long Island étiqueté `landmark` rend toujours le bar : un landmark EST un poi, la règle n'y
  touche pas exprès. Seul le modèle peut le voir.
- « X ou Y » n'existe pas dans `GeoIntent` (`CHANTIERS.md` G15).
- **Trouvé à la sonde, hors périmètre** : « centro » + Roma → « Centro, Turin ». C'est le tier 1 de
  v6, à 520 km : l'écho passe sur le seul mot de la zone, et le guard #14 ne contrôle que le tier 2
  (`CHANTIERS.md` G16).
- **IP de sortie** : Search Box dépend de l'IP, donc la sonde locale ne reproduit pas forcément la
  prod (en prod, « centro » a donné le commerce de Rome, que la règle rejette).

**Reste** :
- Mergé (#169) et déployé : voir le bloc 🚀 du 2026-10-28.
- Semer l'item d'éval dans Langfuse (`scripts/langfuse_seed_datasets.py --only b2c-geo-poi`) :
  c'est à Fabien, car l'upsert écrase les corrections faites dans Langfuse.

## ⏱️ 2026-10-28 — Budgets de temps des feuilles (branche `fix/leaf-llm-timeouts`)

**Constat** (session prod `7e296e4b`, 2026-10-27, release `cb361c0`, lue par l'API REST
Langfuse) : T3 « new york city or long island » a répondu « I can't reach the hotel search right
now » après 32 s. Le 1er appel LLM de la feuille recherche a duré 34,7 s, et le concierge coupe à
30 s. Les LLM des deux feuilles n'avaient **aucun timeout** (SDK OpenAI : 600 s) : deux appels de
prod ont duré 604 s le 2026-10-27 (16:28 et 20:31 UTC).

**Mesuré avant de choisir** :
- **Feuille recherche, prod luna depuis le 2026-10-15** (`generate_content`, ~1 350 appels) :
  p50 2,1 s, p95 5,1 s, p99 11,3 s. Au-delà de 10 s, deux familles :
  - des **épisodes lents**, de 12,4 à 17,6 s (02-03h et 08h UTC le 10-28, médiane de l'heure 4-5 s) ;
  - des **blocages** : 22,1 / 34,7 / 604 / 604 s.
- **Feuille FAQ** : 84 appels, p95 14,5 s, p99 16,3 s, un emballement de 50 s (4 970 tokens de
  sortie).
- **litellm 1.90.2 contre un socket local muet** : `num_retries=1, max_retries=0` (le brief) envoie
  **3** requêtes. litellm passe aussi `num_retries` au SDK comme `max_retries`
  (`main.py` : `max_retries = num_retries`). `retry_policy` + `max_retries=0` en envoie 2 sur un
  blocage, et 1 sur un 400.
- **T = 10 s essayé d'abord** : en local, pendant l'épisode de 08h, une recherche qui aurait abouti
  a échoué (ses 2 appels dépassaient 10 s). Une relance n'aide pas dans un épisode lent, elle donne
  une seconde chance d'expirer. D'où **T = 15 s** : il coupe les blocages, pas la masse des épisodes.

**Fait** :
- **Feuilles** : `LLM_CALL_KWARGS` passé à `LiteLlm` :
  - timeout recherche 15 s (`HOTEL_SEARCH_LLM_TIMEOUT_SECONDS`), FAQ 20 s (`FAQ_LLM_TIMEOUT_SECONDS`) ;
  - `max_retries=0` ;
  - `retry_policy` : 1 relance LiteLLM, sur timeout et 429 seulement.
- **Concierge** :
  - appel feuille à 45 s / 45 s par défaut (un appel bloqué + sa relance, tous deux à T, + les
    outils) ;
  - un frame `progress` suit chaque appel feuille. Le proxy du widget coupe un flux muet 60 s. Sur la
    route FAQ, sans frame `hotels` et avec une synthèse bufferisée, le silence pouvait déjà
    atteindre 8 + 30 + 30 = 68 s ;
  - la façade ne mesure plus le TTFT que sur le premier `progress`.
- **Commentaire S-G4 de la synthèse corrigé** : le « ~5× » mesuré venait des relances du SDK.
- `CLAUDE.md` (budgets).

**Preuves** :
- **`tests/test_leaf_llm_call_budget.py`**, sur le vrai chemin ADK → litellm → SDK, socket local :
  - 2 POST à T d'écart puis `Timeout` ; un 400 → 1 POST ;
  - l'arithmétique budget feuille / triage / proxy.
- **Contrôles négatifs** :
  - sans `retry_policy` → 1 POST ; avec `num_retries=1` → 3 ; sans `max_retries=0` → 3+ ;
  - le TTFT mesuré une seule fois : rouge sans la garde ;
  - le frame `progress` après la feuille : rouge sans le `yield`.
- **Local réel** (feuille recherche seule pointée sur un socket muet) :
  - 2 requêtes à 15,05 s d'écart, `timeout value=15.0 … LiteLLM Retried: 1 times` ;
  - réponse dégradée honnête à +33,4 s (avant : coupure à 30 s ; prod : 32 s).
- **Gates** : pytest 3 339 passés / 1 skippé ; ruff, mypy, guardrails OK ; `smoke_e2e` PASS.

**Trouvé, non corrigé** : une feuille dont le LLM échoue est comptée
`concierge_metric=leaf_call status=ok` (c'est la tâche A2A qui échoue, pas le transport). Seul
`turn … status=degraded` le dit (`CHANTIERS.md` O7).

**Reste** : mergé (#168) et déployé, `CONCIERGE_LEAF_TIMEOUT_SECONDS` supprimée : voir le bloc 🚀
du 2026-10-28.

## 📌 2026-10-27 (undecies) — La pile Railway EST la prod client

Rectification (Fabien) : depuis la bascule d'ai.dayuse.com (2026-10-26), la pile Railway sert les
vrais utilisateurs, sur **MCP_B2C prod** (vérifié : ai.dayuse.com répond `server: railway-hikari`
et `<meta name="agent-version">`). `CLAUDE.md`, `DEPLOY.md` et `CHANTIERS.md` (A2, M1) le
disaient encore « démo », « pas de vrais utilisateurs », « MCP de staging » : corrigés. Les
déploiements du 2026-10-27 (blocs sexies, octies, decies) ont donc touché la prod, et les
sessions 8a6576a4 / 1eb2430a étaient de vrais utilisateurs. Les blocs antérieurs à la bascule
gardent le mot « démo » pour la même pile.

## 🚀 2026-10-27 (decies) — `concierge` déployé sur `b446a65` (#165)

**Déployé** (`DEPLOY.md`, par Claude à la demande de Fabien) : pré-vol sur `b446a65`, pytest
3 329 passés / 1 skippé ; estampille `2c7dd2a` → `b446a65` posée avec `--skip-deploys` ;
`concierge` SUCCESS (déploiement de 17:22:02Z). `hotel-search` (`a407144`), `widget` (`cb361c0`)
et `faq` (`8d1579b`) inchangés : seul le code du concierge a changé.

**Preuve** (widget, synthétique, session `synthetic-deploy-triage-f7836dc7`) : trace en release
`b446a65` ; l'appel de triage part avec `timeout: 4` (avant : 5) et répond en 1,7 s ; réponse en
français, 5 hôtels. Un timeout ne se provoque pas à la demande : la relance et la langue de
session ne sont prouvées que par les tests.

**Reste** : dans quelques jours, mesurer en prod la part de triages en repli (`used_llm` faux :
observations `acompletion` de niveau ERROR sur luna, 2 par tour en échec désormais) ; attendu :
de 4,5 % de tours vers ~0,2 % si les blocages sont indépendants.

## 🔁 2026-10-27 (nonies) — Triage : une relance fraîche, et la langue de la session sur repli (branche `fix/triage-retry-language`)

**Constat** (bloc octies) : le triage a expiré, et le repli par regex a répondu en anglais à une
session française (« élargir la zone »). Demande de Fabien : éviter les regex au maximum, régler
par le LLM, peut-être en allongeant le timeout.

**Mesuré avant de choisir** :
- Prod, triages luna (156 depuis la bascule) : 4,5 % de timeouts à 5,0 s (mini : 0,6 % sur 514).
  En `development`, les « timeouts » durent 0,02 s : c'est le transport aiohttp local, pas ce cas.
- Ces timeouts tombent par rafales (15:00-15:07, 17:06-17:08), et ne suivent pas une inactivité.
  Dans les mêmes minutes, les appels luna de la feuille, sans coupure à 5 s, répondaient en 1,3 à
  4,6 s : ce sont des requêtes bloquées, pas un modèle lent.
- Le vrai `classify()` sur la fixture (228 appels, sans timeout effectif) : p99 2,8 s, max 3,9 s.
- Donc un timeout plus long ferait seulement attendre une requête qui ne revient pas.

**Fait** :
- `triage.py` : 2 tentatives de 4 s, la 2e sur `litellm.Timeout` ou `APIConnectionError`
  seulement, dans le même créneau du budget (8 s au pire, contre 5 s puis la regex).
- `agent.py` : sur un triage que le LLM n'a pas lu, la langue de la réponse est celle de la
  session (fixée par un triage LLM antérieur), puis celle de la locale ; la devinette regex
  seulement à défaut des deux.
- `CLAUDE.md` (budgets), `CHANTIERS.md` M1 (item 7, décision de relance prise).

**Preuves** : pytest vert ; contrôle négatif : sur le code de `main`, les 5 nouveaux
comportements échouent (relance, repli après 2 échecs, langue de session, langue de locale,
timeout 4 s).

**Reste** : mergé (#165) et déployé, voir le bloc decies (la mesure du taux de repli y est).

## 🚀 2026-10-27 (octies) — `hotel-search` déployé sur `a407144` (#164)

**Déployé** (`DEPLOY.md`, par Claude à la demande de Fabien) : pré-vol sur `a407144`, pytest
3 324 passés / 1 skippé ; estampille `2c7dd2a` → `a407144` posée avec `--skip-deploys` ;
`hotel-search` SUCCESS à 16:50:14Z. `concierge` (`2c7dd2a`), `widget` (`cb361c0`) et `faq`
(`8d1579b`) inchangés : seul le code de la feuille a changé.

**Preuve** (widget, synthétique, session `synthetic-deploy-widen-4641f0a9`) : les spans de la
feuille portent `a407144`. Paris avec piscine intérieure + spa < 300 € → page pleine ;
« élargir la zone » tapé → `search_offers` avec `radiusKm: 30` sans `sortBy` (pertinence), et
Océania Roissy CDG à 25,3 km entre dans les 5 hôtels (avant : les 5 plus centraux, 0,9 à 2,1 km).

**Trouvé (concierge, antérieur ; corrigé au bloc nonies)** : au même tour, le triage a expiré (OpenAI, 5 s,
une seule tentative) ; dans le repli par regex, la langue est sortie `en` pour « élargir la
zone » alors que la session est en français (locale `fr`, T0 trié `fr`) : la réponse est partie
en anglais. Le repli devrait garder la langue de la session (`profile.language`, puis la locale)
avant de deviner sur le message.

## ↔️ 2026-10-27 (septies) — « Élargir la zone » : le tri au plus proche seulement en secours (branche `fix/widen-sort-after-full-page`)

**Constat** (rejeu en prod du bloc sexies) : « élargir la zone » après une page PLEINE à Paris
passait à 30 km au plus proche, donc montrait les 5 hôtels les plus centraux (0,9 à 2,1 km),
l'inverse d'un élargissement.

**Fait** : un élargissement de ville n'est trié au plus proche que s'il porte secours, soit
quand la recherche précédente est revenue vide (`profile_in.consecutive_empty_searches`, le cas
de la puce), soit quand la ville était déjà clairsemée (Galveston). Sinon l'ordre de pertinence
de MCP reste.

**Preuve** :
- Snapshot réel : Paris page pleine → 30 km par pertinence ; Paris après une recherche vide →
  30 km au plus proche ; Galveston → 100 km au plus proche.
- MCP en direct, filtres de la session 1eb2430a : Paris 20 km = 16 hôtels ; 30 km par pertinence
  = 18, dont Océania Roissy à 24,9 km dans les 5 affichés (un vrai élargissement).
- pytest 3 324 passés / 1 skippé ; ruff, mypy, guardrails OK. Sur le code de `main`, le test
  « ville dense après une page pleine » échoue.

**Reste** : mergé (#164) et déployé, voir le bloc octies.

## 🚀 2026-10-27 (sexies) — `hotel-search` et `concierge` déployés sur `2c7dd2a` (#162)

**Déployé** (`DEPLOY.md`, par Claude à la demande de Fabien, depuis `../AgentB2C-deploy`) :
- Pré-vol : `origin/main` = `2c7dd2a` (merge de #162), worktree propre, pytest 3 322 passés /
  1 skippé.
- Estampilles posées avec `--skip-deploys` sur `hotel-search` et `concierge` (`cb361c0` →
  `2c7dd2a`). `widget` (`cb361c0`) et `faq` (`8d1579b`) inchangés : rien dans `web/`, `libs/`
  ni `agents/faq_agent` depuis.
- `hotel-search` SUCCESS à 16:38:40Z, `concierge` SUCCESS à 16:38:51Z.

**Preuve** : rejeu des 2 sessions de prod via le widget, en synthétique ; les 12 tours portent la
release `2c7dd2a` dans Langfuse.
- `1eb2430a` : 5 hôtels à chaque tour après la date (prod : 0, 0, 1), plus de question homonyme
  à T2, T3 cherche Paris, piscine intérieure et spa sur chaque carte.
- `8a6576a4` : Galveston T4 → 5 hôtels (prod : 0) ; T5 « try a nearby area » → Crystal Palace
  21,5 km et Hotel Bliss Kemah 33,2 km, les hôtels du site.

**Trouvé au rejeu, non corrigé** :
- (Corrigé, bloc septies) « élargir la zone » TAPÉ après une page PLEINE dans une ville dense : l'anneau passe à 30 km au
  plus proche, donc les 5 hôtels les plus centraux (1-2 km de Paris), l'inverse d'un
  élargissement. Après une recherche vide (le cas de la puce), le plus proche est le bon ordre.
  Piste : ne trier au plus proche que si la ville était déjà élargie (ville clairsemée), ou si la
  recherche précédente était vide.
- Galveston T4 : le modèle de la feuille n'a pas gardé le départ à 23 h ce coup-ci (« closest
  offers ») ; fenêtre horaire portée par le modèle, pas par le code (déjà noté).

## 📏 2026-10-27 (quinquies) — Recherche : rayon, fil géo, complétion, standing (branche `fix/city-radius-sparse-20261027`)

Deux sessions de prod du jour (release `cb361c0`), lues par l'API REST Langfuse (le serveur MCP
Langfuse répondait 401), ont rendu 0 ou 1 hôtel quand MCP en avait 18 à 31.

**Constat, session `8a6576a4` (Galveston, « 11pm check out »)** : une ville n'envoyait jamais
`radiusKm`, donc le défaut MCP de 20 km, et le snapshot compte 0 hôtel à 20 km de Galveston. Le
site élargit jusqu'à 50 km (`SearchHotelQueryProcessor::processConcentricNumberOfHotels`).

**Constat, session `1eb2430a` (Île-de-France)**, compté en direct sur MCP (même date, budget, filtres) :
- T2 « une chambre très classe » : la région, portée en `last_city`, a été relue comme une VILLE,
  d'où la question homonyme (Les Ulis / île de Ré). Régression de #160 (`4a24d00`).
- T3 « toute IDF autour de Paris » : région + ville → la région est partie en lieu précis
  (« Parcs, Romainville », 5 km) → 0 (18 autour de Paris).
- T4 puce « élargir la zone » : la feuille a envoyé `{}`, même recherche, 0.
- T5 « autour de Saint-Ouen » : la zone « Île-de-France » portée a survécu à la nouvelle ville
  → 2 km → 1 (19 autour de la ville).
- L'anneau d'un lieu précis se dimensionne sur l'inventaire brut, pas sur les hôtels qui
  passent les filtres ; « idéalement un massage » devenait un filtre dur (18 contre 31) ;
  « piscine intérieure » prenait tout le groupe piscine ; « très classe » ne mappait rien.
- Cause commune géo : le garde d'écho ne vérifie que le plus long mot de 4 lettres ou plus ; pour
  « Île-de-France », c'est « france », que tout lieu français contient.

**Fait** (décisions de Fabien : tout dans la même PR ; « très classe » = 4-5 étoiles par le
prompt, jamais une regex ; « idéalement » n'est pas un filtre dur ; piscine intérieure stricte) :
- Rayon des villes : défaut MCP tant que le snapshot compte au moins 7 hôtels à 20 km ; sinon 30
  puis 50 km. Galveston → 50 km ; Houston, Paris → défaut.
- « Élargir la zone » : la puce (cliquée ou tapée, 7 langues) envoie `query_params.widen_area` ;
  le `relation: "near"` de la feuille reste l'autre voie. Un anneau plus loin (ville 20 → 30 → 50
  → 100 km, au plus proche d'abord).
- Géo : une région portée l'est comme région (`city_is_area`, profil du concierge) ; région +
  ville → la ville ; une nouvelle ville ne reprend pas la zone portée.
- Complétion (`completion.py`) : une première page de moins de 5 hôtels est complétée par UN
  appel MCP de plus (50 km, ou 100 km si élargi, au plus proche), sans les souhaits optionnels ;
  ses cartes viennent après celles de la première page, et un bloc COMPLETED le dit à la synthèse
  (règle 10 amendée). Jamais sur l'impasse du jour même (sonde J+1).
- `sort` → `sortBy` (G13 fermé) : le tri par distance d'un lieu précis atteint enfin MCP, et les
  `sortBy` / `starRatings` écrits par le modèle sont jetés.
- `indoor_pool` (34) strict ; `amenities_preferred` (« idéalement ») cherché d'abord puis
  relâché ; `standing: "upscale"` → `starRatings: [4, 5]` (`standing.py`), porté par le profil,
  cité dans la phrase « aucune offre » (7 langues).
- Prompt du triage inchangé : son `price_comparison: clear` sur « très classe » est sans effet
  (`clear` se comporte comme `None`), et un changement de ce prompt exige une mesure avant/après.

**Preuves** :
- pytest 3 322 passés / 1 skippé ; ruff, mypy, guardrails OK. Contrôle négatif dans un worktree
  de `origin/main` : les nouveaux tests échouent (dont les 4 tests géo tirés de la trace).
- MCP en direct, vrais callbacks : T5 Saint-Ouen 1 → 5 hôtels ; piscine intérieure + spa
  souhaité + 4-5 étoiles à 2 km : 0 → 5.
- Rejeu local des 2 sessions (Redis :6390, luna sur tous les rôles, pas le mélange de la prod) :
  1eb2430a → 5 hôtels à chaque tour après la date, `starRatings [4, 5]` et `[34, 35]` envoyés
  dès T1 ; Galveston T4 → 4 hôtels avec départ 23 h (0 en prod).

**Pièges** :
- Le site cache des créneaux derrière la flèche du carrousel (Hotel Bliss Kemah a un 18-23 h) :
  sonder `search_offers`, ne pas conclure d'une capture.
- `search_offers` répond `results` ; le `hotels` des traces est la charge compacte de la feuille.
- Le Python système n'a pas de certificats : `urllib` échoue en TLS vers Langfuse, `httpx` passe.
- zsh ne découpe pas une variable non citée en mots : `tar cf x.tar $FICHIERS` reçoit UN nom.

**Reste** :
- Non corrigé : la feuille ne réinjecte pas une fenêtre horaire portée, c'est le modèle qui la
  recopie depuis `profile_in` ; il l'a perdue au rejeu Galveston T5 (23 h oublié).
- Non corrigé : le garde d'écho et les noms d'aire courts (« france »).
- `contracts/mcp_b2c_tools.json` est antérieur à `sortBy` / `timeSlotMode` : à rafraîchir (humain).
- Mergé (#162) et déployé : voir le bloc sexies.

## ⚖️ 2026-10-27 (quater) — Les 3 juges Langfuse passés sur gpt-6-luna : plus aucun appel gpt-4o-mini

**Fait** (UI, par Fabien, 14:08-14:15Z ; vérifié par Claude via l'API) :
- Nouvelles versions : Hallucination v4, Relevance v2, User Distress (no history) v2.
  - Modèle `gpt-6-luna`, « Output token limit » coupé, « Additional options » =
    `{"reasoning_effort": "none"}`.
  - Prompt, variables et score identiques à la version d'avant ; les 3 règles pointent les
    nouvelles versions.
- 4 exécutions réelles sur luna, de 14:16 à 14:33Z, 0 erreur, 27 à 53 jetons de sortie. Scores
  écrits : relevance 1.0 et 0.95, hallucination 0.0, user-distress 0.0.
- 0 génération gpt-4o-mini, tous environnements, de 14:15:28Z à 14:36Z.
- Mis à jour : `observability/langfuse/evaluators.json` (`judge_model_change`, anciens ids),
  `reports/JUDGE-GPT6-DRIFT-2026-10.md` §3, `CHANTIERS.md` M1, `CLAUDE.md`.

**Pièges** :
- Le réglage du modèle est derrière l'icône à droite de « Custom model configuration ». Un réglage
  grisé est un réglage coupé, ce qu'on veut pour « Output token limit ».
- La bibliothèque d'évaluateurs montre « User Distress » (ancien, sans règle) à côté de « User
  Distress (no history) » (le seul actif). Pour les distinguer, regarder les variables sous le
  prompt : l'actif n'a que `last_user_message`.
  - L'ancien a été édité 2 fois par erreur (v2, v3 sur luna). Sans effet : il n'a aucune règle.
- Le défaut « default evaluation model » du projet est `openai/gpt-6-luna`. Nos évaluateurs ne
  l'utilisent pas : ils fixent leur propre modèle.
- **La série Relevance change de niveau à partir de ce jour**, sans changement produit (−0,09 sur
  les relances courtes, rapport de dérive).

**Reste (M1)** :
- la baseline du gate avec le juge luna (`evals/baselines.json` enregistrée avec mini), depuis un
  réseau qui joint MCP_B2C ;
- 1 décision de Fabien : le montant explicite prioritaire sur `lower` (la relance unique du
  triage est faite, bloc nonies).

## 🚀 2026-10-27 (ter) — `hotel-search`, `concierge`, `widget` déployés sur `cb361c0` (#160)

**Déployé** (`DEPLOY.md`, par Claude à la demande de Fabien, depuis `../AgentB2C-deploy`) :
- Pré-vol : main = `cb361c0` (merge de #160), worktree propre. pytest **3 237 passés / 1 skippé**,
  ruff et guardrails OK.
- Ordre feuille d'abord, chaque service estampillé `cb361c0` avec `--skip-deploys` avant son `up` :
  - `hotel-search` : déploiement `2f6d8753`, `SUCCESS` à 13:32:11Z ;
  - `concierge` : `323c0d20`, `SUCCESS` à 13:34:35Z ;
  - `widget` : `a72f7bcc`, `SUCCESS` à 13:34:57Z.
- `faq` reste sur `8d1579b` : rien sous `agents/faq_agent`, et elle n'importe pas `clarification.py`.
- Compatibilité de la fenêtre feuille neuve / concierge ancien : un `kind="unresolved"` y lève une
  `ValidationError` que le concierge rattrape (`agent.py:403`). C'est la réponse d'avant #160 pendant
  ~2 min, pas une nouvelle panne.
- `DAYUSE_MODEL_TRIAGE=openai/gpt-6-luna` inchangée (bascule M1).

**Preuves sur le widget public** (tours synthétiques) :
- `<meta name="agent-version">` = `cb361c0`.
- **E** : `POST /v3/chat/welcome` rend 200 et `{"is_personalized": false, …, "market": {"language":
  "fr", "currency": "EUR"}}`. C'était 404 avant.
- **A** : « a day room in Galveston tomorrow afternoon » (marché US). La réponse ne parle plus d'une
  panne de la recherche : c'est une question d'homonymes, Galveston (Texas) ou Galveston (Indiana),
  sans repli.
- **B** : « un day use dans le Var demain après-midi » rend 4 hôtels autour de Toulon (Toulon,
  La Seyne, Six-Fours), avec `resolved_city=Var`.
- Langfuse : les 2 traces portent `release=cb361c0`, triage sur `openai/gpt-6-luna`, aucune
  observation en erreur.

**Non prouvé en ligne** : C (seulement par les tests de la PR) et D (il faut un client qui coupe le
flux).

## 🩹 2026-10-27 — Branche `fix/geo-named-hotel-prod-20261027` : les échecs des premières conversations réelles sur ai.dayuse.com (#160, mergée et déployée sur `cb361c0` le jour même, bloc ter ci-dessus)

Source : 128 conversations réelles de la nuit du 26 au 27/10 (traces Langfuse), « avec résultats » 68 % contre 75 % pour agent-usa. Un commit par point :
- **A `2463ee2`** (hotel-search + concierge) : un lieu refusé par l'écho (Galveston -> Alveston, Ojai -> Oost, Cuneo -> Luneo, Malines…) finissait sur « I can't reach the hotel search » : la feuille n'envoyait qu'un DataPart `guards_fired`, lu comme un tour vide. Le pays de `places[].country` scope la recherche v6 (retry mondial si rien ne fait écho : biais IP du conteneur, cf. agent-usa #157) ; seuls les candidats qui font écho sont classés ; l'écho accepte l'autre nom de la demande (mention/canonical) ; un quartier à ≤ 40 km de la ville nommée est accepté ; UNE nouvelle recherche sans le lieu reporté du profil ou sous l'autre nom ; sinon `Clarification(kind="unresolved")` par gabarit (nouveau kind, sans option).
- **B `4a24d00`** (hotel-search) : `kind` `admin_district`/`region` sans ville -> couche `region,district` de Mapbox, point = ville principale de la zone (mesuré : Nice, Montpellier, Toulon, Bari), rayon ville ; sinon Search Box ; la ville d'un tour précédent n'est plus accolée à une zone nommée.
- **C `b778d94`** (concierge + hotel-search) : details sans hôtel résolu -> recherche ; `hotel_name` comparé aux noms à l'écran (« Double Tree ») ; un nom introuvable sans ville qui géocode en un lieu de ce nom exact est cherché comme lieu (« Big Sur ») ; `le moins cher` dont les détails échouent répond sur la carte.
- **D `9f1eac7`** (concierge) : les 6 `output: null` = client parti pendant les trames `token` (logs : `socket.send() raised exception.`), pas un délai. Le générateur SSE draine désormais le spine, journalise le tour et marque la trace `client_disconnected`.
- **E `b596b5a`** (concierge + widget) : `POST /v3/chat/welcome` (404 sur chaque ouverture dans l'app) servi à nouveau, contrat agent-usa, sans LLM ; le proxy le relaie ; le widget envoie la langue/devise.
- Évals `669c065` : `evals/datasets/b2c-prod-2026-10-27.jsonl` (9 items `target`, non semés).

**Preuve** : pytest 3 236 passés / 2 skippés, ruff, mypy, guardrails, 96 tests JS. Contre-épreuve : les nouveaux tests rejoués sur `54c6a09` -> 29 rouges, seuls les 9 contrôles négatifs verts. Rejeu local (pile locale, clés des services Railway injectées par `railway run`, Langfuse coupé, jamais ai.dayuse.com) des conversations réelles, main puis branche : lot 1 (24 conversations en échec) erreurs visibles 11 -> 1, tours « panne » 8 -> 0, avec résultats 10 -> 12 ; lot 2 (34 conversations qui marchaient) 33/34 avec résultats des deux côtés. Rapport hors dépôt : `dayuse_aisearchagent_USA-worldwide/dashboard_bascule/data/investigation/replay_report.md`.

**Reste** : ~~revue + déploiement `hotel-search` puis `concierge` puis `widget`~~ faits (bloc ter) ; ressemer `b2c/prod-2026-10-27` ; KPI « réponse vide » à recalculer en excluant `client_disconnected` ; D n'est prouvé que par test (le rejeu lit tout le flux).

**Pièges** : le rejeu local part d'une IP française, pas du datacenter de prod — le biais IP de Mapbox n'est pas reproduit à l'identique (il l'a été 7 fois sur 8 pour A malgré tout). Le triage (gpt-4o-mini) n'est pas déterministe d'un rejeu à l'autre (« Layover in JFK » : question de date sur main, accueil sur la branche).

## 🚀 2026-10-27 (bis) — Bascule M1 : triage du `concierge` sur gpt-6-luna (`d4f4fb1`, #158)

**Déployé** (`DEPLOY.md`, par Claude à la demande de Fabien, depuis `../AgentB2C-deploy`) :
- Pré-vol : main = `d4f4fb1` (merge de #158, même arbre que la branche testée), worktree propre,
  pytest **3 186 passés / 1 skippé**.
- **`concierge` seul** : son seul changement depuis `54c6a09` est `triage.py`. `widget` reste sur
  `54c6a09`, `hotel-search` et `faq` sur `8d1579b` (raison dans le bloc sexies ci-dessous).
- 10:56:35Z, avec `--skip-deploys` : `LANGFUSE_RELEASE=d4f4fb1` et
  `DAYUSE_MODEL_TRIAGE=openai/gpt-6-luna`. Puis `railway up --service concierge --detach` ;
  déploiement `4c12003d` en `SUCCESS` à 10:58:14Z.

**Preuves (Langfuse)** :
- Les 4 traces après 10:58:14Z portent `release=d4f4fb1`. Leur génération de triage tourne sur
  `openai/gpt-6-luna` : 2 tours synthétiques (`synthetic-33c4c187`) et un visiteur réel, sur
  `/v3/chat` comme sur `/v3/chat/stream`. Le « Bonjour » sans LLM rend ses `turn_facts`.
- La règle resserrée tient en ligne : « un hôtel pas trop cher à Lyon demain après-midi » (premier
  message), puis « et plutôt à Villeurbanne ? ». Aucun `price_comparison` n'est posé. Triage en
  1,68 s et 1,54 s.
- 0 génération gpt-4o-mini de 10:58:14Z à 11:02:37Z (13 générations : luna et gpt-5.2).
- Vu en passant, sans lien avec la bascule : « plutôt à Villeurbanne » rend les mêmes offres que
  Lyon, car Villeurbanne est dans le rayon de Lyon. `refinement_unchanged` le dit.

**Retour arrière (code ET variable)** :
1. `LANGFUSE_RELEASE=54c6a09` et `DAYUSE_MODEL_TRIAGE=gpt-4o-mini`, avec `--skip-deploys` ;
2. `railway up --service concierge --detach` depuis un worktree sur `54c6a09`.

mini avec le nouveau prompt régresse.

**Piège découvert** : les 3 évaluateurs Langfuse tournent toujours sur gpt-4o-mini, et ils sont
actifs. Environnement `langfuse-llm-as-a-judge` : 228 générations en 7 jours, toutes sur mini.
- 172 viennent des experiments du rejeu (08h-09h) ;
- environ 50 viennent du trafic de la démo depuis le 2026-10-26 14h ;
- 1 seule les 6 jours d'avant.

Tant qu'ils ne sont pas passés sur luna, M1 n'est pas fini, et chaque experiment les appelle.

**Reste** (M1) :
- les 3 évaluateurs sur luna (UI, Fabien), puis `observability/langfuse/evaluators.json` ;
- la baseline du gate, une seule fois, dans le montage final ;
- 2 décisions ouvertes pour Fabien : une relance unique du triage sur échec en moins d'une seconde ;
  un montant explicite prioritaire sur `lower` (`agent.py`, branche `lower`).

## ✅ 2026-10-27 — Rejeu live du triage luna : au niveau de la prod, prêt pour la bascule (#158)

**Fait** (rapport `reports/TRIAGE-GPT6-AB-2026-10.md` §6) :
- 2 bras le même jour, depuis l'IP `45.156.191.77` : A = main `54c6a09` + triage gpt-4o-mini (la
  prod), B = `feat/triage-gpt-6-luna` + luna.
- 5 jeux (67 items), 3 tirages, concurrence 1, Redis :6390.
- **mini 575/631 (91,1 %), luna 574/631 (91,0 %).** Les 5 écarts d'un item sont expliqués et ne
  tiennent pas au triage.
- Les 4 cas ouverts sont tranchés. « celui de St Pauls » : 3/3 sur les 2 bras. Milano : la prod
  répond déjà en espagnol 3 fois sur 3.
- Runs `m1-2026-10-27-httpx-{mini,luna}-r{1,2,3}`.

**Pièges découverts :**
- **Réseau local + transport aiohttp de litellm + `max_retries=0` (#157)** : le premier appel LLM
  après ~8 s d'inactivité échoue en 0,04 s, avec « Timeout ». Résultat : 42 % des triages en repli
  regex sur les 2 bras.
  - Les runs `m1-2026-10-27-{mini,luna}-r*` sont invalides.
  - Contournement : `DISABLE_AIOHTTP_TRANSPORT=True`, consigné dans `CLAUDE.md`.
  - Prod non touchée (2/273). Une relance unique sur échec instantané protégerait la prod :
    proposé à Fabien, non fait.
- Les jeux `geo-poi` et `dialogue-state` étaient restés à leur version d'avant le 2026-10-20 dans
  Langfuse. Ils ont été ré-amorcés après vérification : hébergé = repo d'avant `b3e2318`.
- Le `.env` local avait un jeton MCP et des clés Langfuse périmés (401). Fabien les a remplacés.

**Reste** (M1, `CHANTIERS.md`) :
- ~~Fabien merge #158 ; bascule atomique~~ : faits le jour même (bloc bis ci-dessus) ;
- 3 évaluateurs Langfuse (UI) ;
- baseline du gate après bascule.

## 🚀 2026-10-26 (sexies) — `concierge` + `widget` déployés sur `54c6a09` (#155, #156, #157) ; triage luna mesuré, pas encore basculé

**Déployé** (`DEPLOY.md`, par Claude à la demande de Fabien, depuis le worktree propre
`../AgentB2C-deploy`, lié au projet Railway) :
- Pré-vol : pytest **3 186 passés / 1 skippé**.
- Estampilles lues avant : `concierge`, `hotel-search`, `faq` = `8d1579b`, `widget` = `0095a41`.
- `concierge` et `widget` estampillés `54c6a09` avec `--skip-deploys`, puis `railway up --detach` ;
  les deux en `SUCCESS` à 16:28:46Z (déploiements `7183fbbc` et `208aa175`).
- **`hotel-search` et `faq` non redéployés** (restent sur `8d1579b`) : `serve.py` n'y change qu'un
  commentaire, et `llm_params` (#157) ne change rien sur leur chemin (`reasoning_kwargs_for(slug)`
  sans rôle = l'effort global, comme avant ; seule la branche `openrouter/` est réécrite).
- Le triage reste sur `gpt-4o-mini` (variable inchangée). #157 ne lui envoie aucun paramètre (modèle
  non raisonnant), mais coupe la relance SDK sur timeout.

**Preuves sur le widget public** (tours synthétiques) :
- `<meta name="agent-version">` = `54c6a09` ; `tokens.css` sert le jaune `#FFAF36`.
- « Bonjour ! » rend ses `turn_facts`.
- Visiteur US (`currency=USD`, `entry_market_country=US`), « a day room in New York tomorrow » :
  5 cartes sur 5 en `USD` (`USD 85.00`…, `display_currency=USD`). C'est la règle de #155 ; l'ancien
  concierge affichait `€`.
- **Non tranché** : « le texte de la synthèse doit citer `$` ». Sur 2 tours, le texte ne cite aucun
  prix (« about 72% off its usual night rate ») : ni `$` ni `€`.

**Triage gpt-6-luna** (branche `feat/triage-gpt-6-luna`, M1 partie 2, pas encore de PR) :
- 2 itérations du prompt, mesurées avec `scripts/measure_triage_models.py`.
- Lignes brutes : `evals/reports/triage_ab_2026-10-26-iter{1,2}.jsonl`, gitignorées.
- Itération 2, côté luna : `price_comparison` 1 désaccord (7 au départ) ; plus aucun `lower` au
  premier message ; « ok pour la deuxième » 2 tirages sur 3 ; « passt, mach das » et « 150 » justes ;
  0 erreur, 0 `length`.
- Côté mini, avec le prompt compact : mini omet les clés à leur valeur par défaut, et `null` renvoie
  `affirmative` / `booking_confirmation` / `wants_more_options` aux regex fr/en. Sans effet si la
  bascule est atomique (variable + code ensemble, retour arrière des deux).
- Côté luna, entre le prompt d'origine et l'itération 2 :
  - 1 régression : « hotel con piscina a milano oggi », `it` → `es` ;
  - 3 changements à juger au rejeu live : « non attends… montre-moi plutôt le deuxième » `lower`,
    « celui de St Pauls » sans `hotel_name` (la ligne de fixture n'a pas la question d'origine), et
    « oui » à « quelle ville ? » `answers_pending=no`.
  - Le rejeu live ajoute donc `geo-class` et `language-robustness` aux jeux H3 (rapport §5).
- **Décision de Fabien** : luna accepté, bascule atomique.

**Outillage** : `../AgentB2C-deploy` (worktree détaché, lié à Railway) sert aux prochains
déploiements : `git -C ../AgentB2C-deploy checkout --detach origin/main` avant chaque usage, et ne
jamais y éditer.

## 🟡 2026-10-26 (quinquies) — Branche `fix/widget-dayuse-brand` : widget aux couleurs Dayuse + prix dans la devise et la locale du marché (#155, mergée et déployée sur `54c6a09` : bloc sexies)

**Widget** (retours PO) : boutons d'action en jaune Dayuse (rôle `--action-primary-*` de `tokens.css` : dégradé 62° `#FFAF36` → `#FFC536`, survol `#FF9F26` → `#FFB526`, texte `#292935`, comme le bouton primaire de dayuse.com) ; `.pick-cta` passe du sombre au jaune ; badge « -X% » en Shadow Black (`--bg-invert`) au lieu du rouge pastèque ; prix formatés par `Intl.NumberFormat` dans la locale langue-pays du marché (`web/vendor/static/js/chat/price_format.js`) sur la carte, la carte simplifiée et la booking card (fr « 165,10 € », en-US « $187.00 », en-GB « £120.00 »). `mapV3Hotels` transmet désormais `price_eur_cents` / `display_currency` / `display_price_minor`.

**Concierge** : règle d'affichage renversée (décision Victor du 2026-10-26, **go de Fabien attendu avant merge**) : par défaut, une carte dont l'hôtel facture dans la devise du marché du visiteur (`profile.currency`, envoyée par le widget) s'affiche dans cette devise ; sinon EUR ; une demande explicite (« en euros » / devise de l'hôtel) garde la priorité pour la conversation. `display_currency.market_currency` / `apply_display_currency` / `shows_hotel_currency` / `comparison_mode`, branchés sur la recherche, les détails/comparaison, la booking card (formules et prix cité) et la référence « moins cher ».

**Preuve** : pytest 3 159 passés / 2 skippés, 94 tests JS, ruff, mypy, guardrails verts ; contre-épreuves rouges (tests du widget contre `main`, tests concierge sans le correctif). Captures avant/après 1440 et 390 px sur widget local + backend simulé (pas de tour réel).

**Reste** : capture sur le widget public. Le go (merge) et le déploiement sont faits, les cartes US
sont en `USD` (bloc sexies). « La synthèse cite `$` » n'est pas tranché : sur 2 tours, le texte ne
cite aucun prix.

## ⏸️ 2026-10-26 (quater) — `widget` sur `0095a41` (sondes de santé, #152) ; bascule DNS reportée (latence Railway)

**Déployé** : `widget` seul sur `0095a41` (servi à 13:36:07Z, build ~11 min au lieu de ~2). Preuve en ligne : `/healthz` 200 `healthy` ; `/readyz` 200 `ready` (le widget joint le concierge par le réseau privé) ; `/health` 200 `status: ok`, `version: 0095a41`, `env: production` ; CSP toujours appliquée. Backends inchangés sur `8d1579b`.

**`HEALTH_TOKEN`** : copié sans affichage depuis le service `agent-conversationnel-USA` (48 car. ; le service lié au dossier `~/Projects/agent-usa` n'est pas celui-là). Posé avec `--skip-deploys` après le lancement du build, donc activé par `railway redeploy --service widget --yes` : depuis 13:41:56Z, `/health` sans jeton → **401** + `WWW-Authenticate: Bearer`, comme chez agent-usa ; `/healthz`, `/readyz`, la page (`0095a41`) et la CSP inchangés.

**Bascule DNS reportée** : Railway en latence (signalé par Fabien) ; vérification du domaine, certificat et retour arrière passent tous par Railway. État sûr : `ai.dayuse.com` sert toujours agent-usa.

**Reprise de la bascule** (tout est prêt côté AgentB2C ; le redéploiement du jeton est fait) :
1. ~~`railway redeploy --service widget --yes`~~ fait à 13:41Z.
2. Surveiller qui sert `ai.dayuse.com` toutes les 5 s (AgentB2C = `X-Frame-Options: DENY` + `<meta name="agent-version">` ; agent-usa = `SAMEORIGIN`).
3. Sonde, depuis ce clone : `railway domain ai.dayuse.com --service widget --json`. Acceptée → le domaine reste en attente (le TXT pointe encore sur agent-usa) : appliquer son CNAME + TXT dans Route 53. Refusée (« in use ») → `(cd ~/Projects/agent-usa && railway domain delete ai.dayuse.com --yes)` puis relancer l'ajout, puis Route 53. Quelques minutes de coupure probables.
4. Route 53 : zone `Z37YEHJ2ZH2A80`, UPSERT de `ai.dayuse.com.` CNAME et `_railway-verify.ai.dayuse.com.` TXT, TTL 60.
5. Preuves sur `ai.dayuse.com` : marché fr/EUR/FR, en-têtes, 403 cross-site, 404 GET `/v3`, tour réel ; `X-Forwarded-Host`, clé Amplitude Production, `/health`, logs (`refused`, `rate_limit_hit ip=`). Puis Fabien ouvre l'assistant dans l'app mobile (MOB1 phase C).
6. **Critère de retour arrière** : 10 min après la bascule, pas d'AgentB2C avec certificat valide sur `ai.dayuse.com`, ou un tour réel qui échoue.

**Retour arrière, valeurs d'avant bascule** (publiques) : CNAME `ai.dayuse.com.` → `tit3qvdo.up.railway.app` ; TXT `_railway-verify.ai.dayuse.com.` → `"railway-verify=06e2524ef128e3cc7953f9c47eaeb6e1653ffa19bdf606be79f53a6d34a6ee90"`. Si Railway refusait le double rattachement : retirer le domaine de `widget`, le rattacher au service web d'agent-usa (`agent-conversationnel-USA`), qui peut donner un nouveau CNAME/TXT à reporter dans Route 53.

## 🛡️ 2026-10-26 (ter) — CSP appliquée (`68e0f75`, #151), TTL DNS à 60 s, D7 prolongée

**CSP** : #151 — en `enforce`, la politique partait sans `report-uri` (un blocage n'aurait laissé aucune trace) ; même chaîne dans les deux modes, test durci, contre-épreuve rouge. `widget` déployé sur `68e0f75` avec `WIDGET_CSP_MODE=enforce` (servi à 11:28:52Z). Preuve : en-tête `Content-Security-Policy` … `report-uri /csp-report`, plus de report-only ; audit Chrome headless sous la politique appliquée — un tour SSE, 26/26 images (`static.dayuse.com` pour les photos de prod), polices, Amplitude via `alitude`, feedback, **Session Replay** (10 envois `api-sr.eu.amplitude.com`) : 0 violation, 0 échec de chargement. Piège : Session Replay est coupé sur `?du_synthetic=1` (`addSessionReplay`) ; pour l'auditer, tour sans le paramètre + `x-dayuse-synthetic` injecté par un wrapper `fetch`.

**DNS, préparation** : `ai.dayuse.com` (CNAME `tit3qvdo.up.railway.app`, agent-usa, projet Railway `Agent_conversationnel_USA`) et `_railway-verify.ai.dayuse.com` (TXT `railway-verify=06e2524e…`) passés de TTL 300 à **60 s**, valeurs inchangées (change Route 53 `C0580618A8JYGZ0Y7JFY`, zone `Z37YEHJ2ZH2A80`, INSYNC à ~11:35Z). Un domaine personnalisé Railway n'appartient qu'à un service : la bascule = déplacer le domaine d'agent-usa vers `widget` + CNAME/TXT donnés par Railway ; quelques minutes de coupure probables, retour arrière symétrique. agent-usa reste déployé et intact.

**Décision A1 (Fabien)** : exception D7 prolongée jusqu'au **2027-01-31** (l'échéance « avant le canary S11 » tombait avec la bascule franche) ; P5 avant la bascule ; rotation des bearers semaine du 2026-11-02 — prérequis : `BearerAuthMiddleware` n'accepte qu'un jeton. Consigné dans `CHANTIERS.md` A1/P5, `PLAN-REWORK-AGENT-USA.md` D7, `CLAUDE.md`.

**P5 fait** : `railway domain delete concierge-production-aaa2.up.railway.app --service concierge` (seul autre domaine public du projet avec celui du widget ; aucune référence dans le dépôt ; il répondait 502). Après : 404 « Application not found » ; un « Bonjour » synthétique via le widget → 200 avec `turn_facts` (concierge joint par le réseau privé). Le widget est la seule surface publique du projet.

## 🚀 2026-10-26 (bis) — `widget` déployé sur `e2b0c99` (#149 : marché au rendu + protection de l'edge)

**Déployé** : `widget` seul — `WIDGET_ALLOWED_ORIGINS=https://ai.dayuse.com,https://widget-production-3f56.up.railway.app` et `LANGFUSE_RELEASE=e2b0c99` posées avec `--skip-deploys`, puis `railway up --service widget --detach` ; page servie en `e2b0c99` à 11:02Z. `concierge`, `hotel-search`, `faq` restent sur `8d1579b` : `git log 8d1579b..e2b0c99 -- agents libs` est vide, et #148 y tourne déjà (tour synthétique « un hôtel avec piscine à Nice » → question de date + 3 puces + `turn_facts: clarification`). Gates sur `e2b0c99` : pytest 3 130 passés / 1 skippé, ruff, mypy, 78 tests JS.

**Preuves sur le widget public** (sondes synthétiques, un seul appel LLM) :
- `/?locale=fr&currency=EUR` + Referer dayuse.fr → métas `fr / EUR / FR / dayuse.fr` (avant : en/USD/US).
- En-têtes : `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy-Report-Only` (pas d'enforce).
- POST `Origin: https://evil.example` → 403 ; `Origin: https://ai.dayuse.com` + message de 501 car. → 413 (l'origine passe, donc `WIDGET_ALLOWED_ORIGINS` est lue, sans appel au concierge).
- GET `/v3/chat` → 404 (avant : 405).
- Tour réel same-origin (Londres, demain après-midi) → 200, 5 hôtels.
- `railway logs --service widget` : 3 tours navigateur de Fabien en `POST /v3/chat/stream 200`, aucun `refused cross-site POST` hors la sonde evil.example.

**Tentative précédente** : le widget servait `8d1579b` parce que rien n'avait été déployé dans AgentB2C depuis le 23/10 (4 services `SUCCESS` ce jour-là, même estampille). Le seul dossier sur `feat/contrat-cadre-p3` est `agent-sales-am`, dont `sales-ai-pipeline/` est lié au projet Railway **Sales IA Agent** : un `sales-ai-preprod` y était en `DEPLOYING` à 10:48Z, seul déploiement du créneau (à vérifier côté agent-sales-am).

**Pièges** :
- `railway up` déploie dans le projet lié au **dossier** courant (`~/.railway/config.json`), quelle que soit la branche : lancé depuis un autre repo, il part ailleurs sans erreur. Toujours depuis ce clone, toujours avec `--service`.
- Le proxy voit l'edge, pas le visiteur : pairs `::ffff:100.64.0.x`, une IP différente par requête. Sans `X-Real-IP`, la limite par IP s'étalerait sur ~20 clés. Railway documente `X-Real-IP` comme l'IP du client (docs « Specs & Limits ») et c'est prouvé en ligne : 31 `POST /v3/chat/session/reset` (zéro appel LLM, 11:10Z) → 30 × 204 puis 429 (`Retry-After: 59`), et le log écrit `rate_limit_hit … ip=45.156.191.77`, l'IP de sortie du poste. Le défaut de `WIDGET_CLIENT_IP_HEADER` est le bon. Les 30 requêtes ont rempli un seul compteur : un seul réplica sert le widget, ou toutes sont tombées sur le même.
- `.claude/` ajouté à `.railwayignore` : les worktrees de Claude Code y vivent, `railway up` les aurait envoyés.

**Reste** (hors de cette session) : DNS `ai.dayuse.com` (Route 53 + domaine custom Railway sur `widget`) et plan de retour arrière — à la bascule, vérifier que `X-Forwarded-Host` vaut `ai.dayuse.com` et qu'aucun CDN ne s'intercale devant Railway (sinon `X-Real-IP` serait l'IP du CDN) ; MCP de prod ; CSP `enforce` après quelques jours de `csp-report` ; P5 et rotation des bearers (A1) ; plafond OpenAI (O3), purge Langfuse (DPIA), cron `/sync-availability` d'agent-usa ; merges dayuse-com!15273 et dayuse-product-analytics#112.

## 🔀 2026-10-26 — Préparer la bascule franche d'ai.dayuse.com (branches `feat/widget-market-at-render` puis `feat/widget-protection`, empilées)

**Décision (Fabien, 2026-10-26)** : bascule franche d'agent-usa vers AgentB2C sur `ai.dayuse.com` (Railway + Route 53) ; MCP de prod branché par Fabien ; Langfuse remplace `conversation_logs`.

**Contrat d'entrée lu dans dayuse-com** : `AiConciergeSection` (home, Kameleoon `ai_agent_section_home`) et `AiAgentBanner` (home, recherche) ouvrent un nouvel onglet sur `https://ai.dayuse.com/?amp_device_id&amp_session_id&dayuse_session_id&locale&currency&q` — un seul hôte pour tous les TLD. !15273 (ouverte) ajoute `du_entry_source` + `market_country`.

**Fait** :
- `f053bb7` : la page est rendue dans le marché du visiteur. Résolveur d'agent-usa copié tel quel dans `web/market_context.py` (stdlib, test de synchro si `../agent-usa` est présent) ; `?market_country` épingle le pays par-dessus ; lien « Voir tout » laissé à `markets.generated.js`. Avant : en/USD/US pour tout le monde.
- `ee36fa2` : protection de l'edge public (détail et variables dans `DEPLOY.md` § Protection) : 20 tours/min et 200/h par IP, origine croisée refusée, 4 routes du concierge seulement, message ≤ 500 car., en-têtes de sécurité, CSP en report-only (`/csp-report` journalisé).
- Tests : `test_widget_proxy_market.py` (19), `test_widget_proxy_protection.py` (29), contre-épreuves rouges. pytest 3 130 passés / 1 skippé, ruff, mypy, 78 tests JS. Sonde locale du proxy : page FR/EUR/FR depuis le Referer dayuse.fr, 403 cross-site, 413, 429 au 21e tour, GET /v3 en 404.

**Reste avant bascule** : déployé le jour même, voir le bloc 2026-10-26 (bis) ci-dessus ; son « Reste » remplace celui-ci. Le cron `/sync-availability` d'agent-usa ne sert qu'au cache d'agent-usa : à arrêter quand agent-usa s'éteint. Rétention Langfuse : pas d'entitlement `data-retention` en OSS, purge à organiser.

**Écarté volontairement** : `dayuse_session_id` n'est pas repris (décision AM1 : liens sortants = `amp_*` seulement, ce que lit ab-tests ; dayuse-com ne lit aucun `du_dayuse_session_id` entrant).

## 📅 2026-10-20 — La première recherche sans jour demande la date (branche `feat/ask-search-date`)

**Décision (Fabien, 2026-10-20)** : renverse « A date is NOT required » (2026-07-28). Retour QA, trace `d327c03d` : « Rooftop pool in Los Angeles » cherché aujourd'hui sans rien demander.

**Fait** (concierge seul) :
- `agent.py` : avant la feuille, si la première recherche de la session ne nomme aucun jour (`expected_search_date`, `mentions_a_date`, slot de triage `day_stated`), réponse par gabarit `templates.date_question` + 3 puces (`date_chips` : aujourd'hui / demain / après-demain, lues par `parse_requested_date` dans les 7 langues). 1 seul appel LLM (le triage). `SessionProfile.date_checked` : une seule fois par session ; une réponse sans jour cherche aujourd'hui. Pas de question pour un hôtel nommé (le nom ne passe qu'à ce tour, mcp-dayuse#7), ni quand Redis ne répond pas (`store.exists` → None : sinon la question reviendrait à chaque tour).
- `pending_search` garde la demande (`date_question: true`) ; la réponse repart vers la feuille avec la demande SEULE, sans étiquettes (`pending_search_context`) : avec « EARLIER REQUEST / YOU ASKED », la feuille stockait « Rooftop pool » en `zone` 3 fois sur 7 (0 sur 5 en message daté direct) et le tour suivant (« and in San Diego? ») tombait en dégradé ; après correctif 0 sur 8. Les puces sont effacées au tour qui répond.
- Triage : slot `day_stated` (additif, ne peut qu'épargner la question). Une heure ou une plage sans jour (« de 14h à 18h ») compte comme aujourd'hui : gpt-4o-mini l'a lu ainsi 6 fois sur 6 sous deux formulations contraires, l'échec est sûr (comportement d'avant) — à renverser si tu préfères demander dans ce cas.
- Tests : `test_search_date_question.py` (21) + `tests/api/test_search_date_http.py` (puces dans le JSON et dans la trame SSE `done`) + triage ; 3 contre-épreuves (porte coupée, puces non effacées, sonde Redis coupée) → rouge. Les ~85 tests antérieurs qui passent par une première recherche sans jour démarrent sur une session au jour réglé (fixture `_search_date_already_settled` du `conftest.py` racine ; marqueur `date_unsettled` pour en sortir).
- Évals : « demain »/« tomorrow » ajouté aux 7 items `geo-poi` sans jour (ils testent la géographie) ; 2 items `b2c-dialogue-state` (`ds-date-asked-when-none-fr`, `ds-date-answer-keeps-request-fr`). Seed `--dry-run` : 91 items valides.

**Preuve** :
- Sonde triage réelle, 16 formulations × 3, fr/en/es : **48/48** sur gpt-4o-mini (triage prod) et 48/48 sur gpt-6-luna (défaut du code, migration M1).
- Live local (3 services + Redis :6390, feuilles luna, en-tête synthétique) : API LA (question + puces → « Tomorrow » → 5 hôtels au 2026-10-21) ; FR 3 tours (question → « demain à partir de 14h » : Nice, J+1, 14h, piscine → « et à Cannes ? » : pas de question, jour/heure/piscine reportés) ; widget SSE dans Chrome à 390 px (puces affichées, clic « Tomorrow » → cartes, « and in San Diego? » → recherche sans nouvelle question, statut `ok`).
- pytest 3 017 passés / 1 skippé, ruff, mypy, guardrails OK.

**Reste** :
- ~~Déployer `concierge` seul~~ : fait (`8d1579b`), vu en ligne le 2026-10-26 (question de date + puces sur le widget public).
- Ressemer `b2c/geo-poi` et `b2c/dialogue-state` (`scripts/langfuse_seed_datasets.py --only …`, humain).
- **À trancher** : `prod-lat-dead-0-same-day-cutoff-fallback` (`b2c/prod-regressions`, importé depuis la trace `e03688e0`, message « je cherche un hotel à Paris avec piscine ») reçoit désormais la question de date, par construction : son `min_hotels: 1` échouera. Le retirer, ou le garder comme garde « question de date » (attendus à réécrire).
- Limites connues, voulues : sans ville NI jour, deux questions (le jour, puis la ville) ; une question de budget avant recherche est suivie de la question de date.
- La batterie 32 scénarios et les rejeux Langfuse sont payants : non lancés.
- Analytics (AM1, #146) : le tour de question part en `response_type: clarification`, `clarification_reason: other` — le contrat `contracts/amplitude_events.json` (convenu avec Ali) n'a pas de valeur `date`. L'ajouter = changer le contrat partagé, à voir avec lui.

## 🧩 2026-10-20 — Retours QA widget : flèches coupées + carrousel mobile (branche `fix/widget-results-overflow`)

**Constat mesuré** (widget local servi par `run_widget_proxy.py`, `/v3/chat` routé vers un payload construit par `facade.build_chat_payload` avec les hôtels de la trace QA `d327c03d…`, Chrome headless) :
- Desktop : `.message-content.with-hotels` (item flex sans `min-width: 0`) faisait 760 px dans 724 px disponibles → 16 px au-delà du panneau. À 1440 : flèche « suivant » `r=1124` et « See all hotels in USA → » `r=1123` pour un panneau à 1120 ; à 800 la flèche était coupée en deux. C'est la « flèche en bas à droite hors cadre » et la « flèche du carrousel cassée ».
- Mobile 390 : rangée de x=52 à x=374 (colonne de l'avatar + padding du chat + `overflow:hidden`), cartes à 246 px au lieu de 330, aperçu de la suivante coupé net, liseré de 4 px de la carte précédente après un swipe.

**Fait** (CSS seul) :
- `hotels.css` : `min-width: 0` sur `.message-content.with-hotels` (toutes tailles) ; retrait des `padding-right: 20px` de `.results-intro`/`.results-meta` qui masquaient ce débordement.
- `responsive.css` (≤768) : la rangée de cartes sort du padding du chat et de la colonne de l'avatar (`margin: 12px -16px 12px calc(-16px - 28px - var(--space-2))`), carte `calc(100% - 28px)` = viewport − 16 − 12 − 32 ; doublon mobile de la règle `with-hotels` réduit à `width: 100%`.
- `tests/widget/widget_cards.test.mjs` : géométrie mobile, sortie de la colonne, `min-width: 0` (contre-épreuve : le test tombe sans la règle). 45 tests JS verts.

**Preuve** (mesures après correctif) : 1440/900/800 → bloc, flèche et « See all » ≤ bord de contenu (1100/830/780) ; 390/360 → rangée de 0 à la largeur de l'écran, carte 1 à x=16, aperçu 32 px, carte calée à x=16 après swipe, `scrollWidth === innerWidth`. pytest 2 988 passés / 1 skippé, ruff, mypy, guardrails OK.

**Reste** : déploiement du seul service `widget` (`DEPLOY.md`) puis capture sur le widget public à 1440 et 390. Les captures de la QA n'ont pas été vues (non transmises) : l'appariement retour ↔ défaut repose sur les mesures. Non touchés : flèches de la galerie photo (correctes, n'apparaissent qu'avec plus d'une photo, jamais en résultats de recherche), compteur « 1 / 5 ».

## 📈 2026-10-20 — Tracking Amplitude de l'agent (AM1, branche `feat/amplitude-tracking`)

**Décidé avec Ali** (session « grill », réponses Q1-Q28) : l'analytics produit part dans Amplitude **depuis le widget seul** ; les `chat_*` d'agent-usa sont retirés, pas repris ; préfixe `ai_agent__*` + `pageview` copié de dayuse.com (6 propriétés de page, `page_type = 'ai_agent'`) ; le `prompt` est envoyé (tronqué à 500, accès restreint), jamais la réponse ; pas d'A/B test, bascule franche ; Production seulement sur `ai.dayuse.{tld}`, Staging/Dev partout ailleurs (local, évals, démo) ; Session Replay à 5 %, non modifiable depuis Amplitude.

**Fait** :
- `contracts/amplitude_events.json` : 9 événements, 10 propriétés communes, enums, `session_replay.sample_rate`. Verrouillé par `tests/test_amplitude_contract.py` (serveur) et `tests/widget/widget_amplitude_contract.test.mjs` (widget). Ajouter, jamais renommer ni retirer.
- Serveur : bloc `turn_facts` dans la réponse JSON et le `done` SSE (`trace_id`, `family`, `route`, `status`, `response_type`, `results_count`, `empty_reason`, `clarification_reason`, `guards_fired`, `fallbacks`, `resolved_city`), construit par `turn_facts.py`, transmis par un marqueur `turn_facts` émis par le seul enrobage de `_run_async_impl` (le final reste le dernier événement). `CONTRACT_KEYS` gagne `turn_facts`. Le `turn_id` du widget est repris s'il est valide. Aucun appel LLM en plus, aucun envoi Amplitude côté serveur.
- Widget : `tracking.js` réécrit, seul émetteur ; `amplitude-bootstrap.js` supprimé ; balise `/api/track` et sa route proxy supprimées ; `?du_synthetic=1` → `is_synthetic` + `X-Dayuse-Synthetic` (volet widget de E2) ; `?market_country=` et `__DAYUSE_NATIVE__` fixent le marché suivi (`"unknown"` avant) ; liens sortants estampillés `amp_device_id`/`amp_session_id` seulement ; autocapture d'attribution coupée ; feedback 👍/👎 aussi en JSON (trace lue dans `turn_facts`) ; code mort des boutons « pick » retiré.
- Proxy : `<meta name="agent-version">` depuis `LANGFUSE_RELEASE` ; `GET /sr-config` sert la config Session Replay figée (le plugin 1.13.2 la lit à chaque session et l'écraserait sinon).
- `CLAUDE.md` : invariant RGPD amendé (exception `prompt`) + invariant Analytics. `CHANTIERS.md` : AM1 ouvert, E2 volet widget fait.

**Reste** (détail dans `CHANTIERS.md` AM1) : revues des MR sœurs déjà ouvertes, dayuse-product-analytics #112 (`ai-agent.md`, `events.yaml`, `tools/langfuse_fetch.py`) et dayuse.com !15273 (ticket #15883, `du_entry_source` + `market_country` sur les 2 bannières) ; lire la rétention Langfuse ; vérifier un tour réel dans chaque projet Amplitude et un enregistrement Session Replay ; faire confirmer par l'équipe mobile que `__DAYUSE_NATIVE__` est injecté au début du document.

**Pièges** :
- `empty_reason` n'a pas `geocode_failed` : la feuille ne le signale pas (il faudrait une clé de `DataPart`, autre chantier). `filters_too_strict` ne sort que pour le filtre « moins cher que ».
- Plugin Session Replay 1.13.2 = la dernière version compatible avec le SDK 2.11.2 ; ses envois partent directement vers `api-sr.eu.amplitude.com` (le proxy `alitude` ne sert que `/2/httpapi`) : un bloqueur de pub empêche l'enregistrement. Si `/sr-config` ne répond pas, rien n'est enregistré.
- `agent_version` = estampille du **widget** ; celle du concierge se lit dans la trace Langfuse (`langfuse_trace_id`).
- Les propriétés communes sont lues à l'envoi vers le SDK, pas à la mise en file : un `pageview` parti avant que l'app injecte `__DAYUSE_NATIVE__` est bien étiqueté `mobile_app`. Seule limite : si l'app injecte **après** l'init du SDK (chargement SDK + plugin, ou 3 s), les événements déjà partis gardent l'étiquette web et l'identifiant d'appareil du navigateur. À confirmer côté mobile : l'injection a lieu au début du document.
- `status: "unknown"` = le spine n'a pas émis de marqueur `turn_facts` (avertissement `b2c_concierge.facade` dans les logs) ; `error_type: "client"` = exception du widget après la réponse du serveur, pas une panne réseau.
- Les puces de créneau (Matin/Journée/Soir) d'une ancienne bulle peuvent rappeler `/v3/chat` (`filters/search.js`, `runSearchWithFilters`) : ce chemin a maintenant le même suivi de tour que `sendMessage` et affiche `search_error` sur une réponse non-2xx.
- Les liens sortants ne portent plus `amplitude_id` ni les `du_*` d'agent-usa, seulement `amp_device_id`/`amp_session_id` (ce que lit ab-tests).
- `.venv` absent de ce poste : gates passés avec un venv Python 3.13 reconstruit hors dépôt ; la suite y prend ~3 min 45 (dont ~110 s pour `test_calendar_rot`). `node --test tests/widget/` échoue sur Node 26 (dossier refusé) : passer le glob.

## 🧪 2026-10-19 (ter) — Sortie de gpt-4o-mini : mesures faites, triage pas encore prêt (branche `chore/off-gpt-4o-mini`, chantier `M1`)

**Fait** (code ; rien de déployé, rien d'écrit sur Langfuse) :
- **Effort de raisonnement par rôle** (`llm_params._REASONING_EFFORT_DEFAULTS`). Le triage et le juge
  sont fixés à `none` ; la synthèse a sa propre variable. Avant ce correctif, poser seulement
  `DAYUSE_MODEL_TRIAGE=openai/gpt-6-luna` aurait envoyé le triage à effort `low`, le `low` global du
  concierge de la démo. Mesuré : 2 triages sur 20 butent sur le plafond de 200, JSON tronqué, repli
  regex silencieux.
- **Triage `max_retries=0`.** litellm passe `max_retries=2` au SDK OpenAI, qui relance les timeouts.
  Le budget « 5 s » valait donc environ 17 s, et un max de 16,4 s est mesuré en prod sur mini. Le
  docstring affirmait le contraire.
- **Juge du gate** (`evals/judge.py`) : `RELEASE_GATE_JUDGE_MODEL` > `DEFAULT_MODEL`, kwargs passés par
  `llm_params`. Il ne suit plus `DAYUSE_MODEL`, donc il ne juge plus la pile avec son propre modèle.
  Avec l'ancien appel, gpt-6 aurait renvoyé un 400, avalé en `error`.
- **Gate** : il compte les erreurs du juge et les tours dégradés. `--update-baseline` refuse dans les
  deux cas, et un avertissement sort si la baseline a été jugée par un autre modèle.
- `ci.yml` suit le montage de la démo.
- **Instrument** `scripts/measure_triage_models.py` (vraie `classify()`), avec la fixture
  `evals/triage_inputs.jsonl` : 114 entrées, dont 62 tracées depuis les runs h3p.

**Mesures** (rapports `reports/TRIAGE-GPT6-AB-2026-10.md` et `reports/JUDGE-GPT6-DRIFT-2026-10.md`) :
- **Triage, luna ne tient pas tel quel.**
  - Meilleur sur `family` (mini classe « vale » / « va bene » en `faq`), `language`, budget
    (« 150 »), occupancy (2 cas étiquetés) et `answers_pending`. Égal sur `booking_confirmation`
    (114/114). −35 % de coût, JSON de 97 tokens au p95 contre 150.
  - Pire sur `price_comparison` (7 émissions à tort, dont un `lower` sur un changement de zone), sur
    l'ordinal dans une phrase (« ok pour la deuxième », non rattrapé par le code) et sur
    `affirmative` hors fr/en (« passt, mach das »).
  - Latence : la queue au-delà de 5 s est la même pour les deux modèles (environ 5 % cet
    après-midi ; seul mini a calé à 15 s). luna ajoute environ 0,5 s au p50.
- **Juges Langfuse, dérive faible, barre tenue.** Sur 53 observations, dont 13 annotées humain :
  Hallucination 98 % d'accord, Relevance 91 %, Distress 100 % ; luna aussi proche de l'humain que
  mini. Relevance baisse de 0,09 en moyenne (les relances courtes, jugées hors contexte).
  - **Sonde** : gpt-6-luna n'accepte la requête du juge Langfuse qu'avec `max_completion_tokens` et
    `reasoning_effort:"none"`, deux réglages accessibles dans l'UI seulement.

**Reste** (détail dans `CHANTIERS.md` M1) :
1. Resserrer 3 règles du prompt de triage, puis remesurer les deux modèles (le prompt est partagé).
2. Rejeu live au montage H3, puis bascule Railway (humaine) : déployer `concierge`, puis la variable.
   En cas de retour arrière, remettre la variable avant ou avec le code.
3. Baseline du gate avec le juge luna, depuis un réseau qui joint MCP_B2C.
4. Évaluateurs Langfuse après l'OK de Fabien (UI). Repli : couper les règles jusqu'à la v4.
5. agent-usa : même piège, signalé seulement.

**Pièges découverts** :
- **L'IP de sortie a changé en pleine session** : `45.156.191.77` est devenue `86.218.8.120`, et
  MCP_B2C staging est alors injoignable (`ConnectTimeout`).
  - Effets : 256 appels « Connection error » contigus dans l'A/B (rejoués), et une batterie à 0/32
    avec 112 tours dégradés sur 118, que `--update-baseline` a d'abord écrite (revert, puis garde
    ajouté).
  - **Avant tout run live : `curl -4 ifconfig.me`, puis vérifier MCP.**
- **Un écart n'est pas une régression avant d'avoir lu l'entrée exacte.** « Je confirme » / « yes,
  Paris » ressemblaient à une erreur de luna, mais la trace montre `LAST ASSISTANT QUESTION`
  absente : luna applique la règle, et c'est mini qui la viole.
- **Le juge Langfuse ne passe pas par litellm**, donc `allowed_openai_params` ne le concerne pas : ce
  sont les paramètres de modèle de l'évaluateur qui comptent.
- **La suite à 6 min 42 s (contre 29 s le matin même) vient du réseau, pas du code.**
  - `--durations` : les setups de `test_serve_auth.py` / `test_faq_serve_auth.py` prennent 10 à 20 s
    chacun, par multiples de 5 s. `test_calendar_rot` (207 s) les rejoue.
  - Ce sont des timeouts réseau, alors que MCP_B2C est injoignable. C'est très probablement la cause
    « non trouvée » de la suite à 5-6 min du 2026-10-16.
  - Ces tests se disent « No network ». Quelque chose y contacte quand même un hôte (probablement le
    `McpToolset` à l'import ou au démarrage). Non diagnostiqué plus loin.

## 🚀 2026-10-19 (bis) — QA14707 phases 4-5 déployées : `hotel-search` + `concierge` sur `130caed` (#143)

**Fait** (procédure `DEPLOY.md`) : pré-vol sur `main` propre `130caed` (#143 mergée), pytest **2 991 passés / 1 skippé**. Estampilles avant : `hotel-search`, `concierge` = `0b65159`, `faq` = `28c485a`, `widget` = `124cd43`. Seuls `hotel-search` (Q09, Q10) et `concierge` (Q11, Q27, Q28) ont changé : estampillés `130caed` avec `--skip-deploys`, puis `railway up --detach`, feuille d'abord ; les deux en `SUCCESS` à 13:54Z. `faq` et `widget` n'ont pas changé et gardent leur estampille, qui reste vraie.

**Avant le déploiement, rejeu live H3'** (sur `plan/qa14707` `34a215c`, même montage que H3 : feuilles gpt-6-luna, triage gpt-4o-mini, synthèse gpt-5.2, concurrence 1, Redis :6390, IP `45.156.191.77`, 0 MCP 429 ; runs `h3p-2026-10-19-plan-r1..3`) : au niveau de H3 ou mieux partout. Deux lignes plus basses, expliquées : `geo-poi-generic-gare-no-city` (`must_ask_city` 0/3 contre 1/3 ; la réponse demande bien la ville, l'heuristique de mots-clés la rate) et le nouvel item `qa14707-near-11580-en` (MX 3/3). Ce dernier passe avec le marché : rejoué en direct, « a hotel near 11580 tomorrow » donne **US · Valley Stream, 5 hôtels, 3/3 avec `entry_market_country=US`** (ce qu'envoie le widget) et MX · Mexico City, 0 hôtel, 3/3 sans marché (ce que fait le harnais). Détail : commentaire de #143.

**Preuve** (widget public, tours synthétiques) :
- Les 3 traces des sessions de preuve portent la release **`130caed`** : c'est bien le nouveau build qui sert.
- « a hotel near 11580 tomorrow » avec le marché US → US, Valley Stream, 5 hôtels.
- « un hôtel près de la gare de Lyon demain » → question par gabarit « Près de « Gare de Lyon », dans quelle ville cherchez-vous ? » ; la réponse « Paris » relance la recherche à Gare de Lyon, Paris, avec la date du 2026-10-20 conservée, 5 hôtels (chemin Q11 sans regex).

**Reste** :
- H4 : retest par Raphael, puis réponse point par point sur dayuse-com#14707.
- À décider (ne bloque pas la démo) : un ZIP US nu envoyé SANS marché part maintenant au Mexique (avant Q10, la regex supprimée forçait les États-Unis). Soit l'item live porte le marché pour mesurer le cas du widget (le harnais ne poste que `{session_id, message}`), soit c'est une décision produit au-delà de DQ8.

**Piège** : le snippet de statut de `DEPLOY.md` (étape 5) cassait sur la CLI Railway actuelle (`KeyError: 'serviceInstances'`) ; remplacé par une version qui parcourt tout le JSON.

## 🧹 2026-10-19 — Nettoyage du dépôt + `CLAUDE.md` remis d'équerre (branche `chore/cleanup`, sur `plan/qa14707`)

**Fait** (branche `chore/cleanup`, créée depuis `plan/qa14707`) :
- `CLAUDE.md` réécrit contre le code : lire `CHANTIERS.md` puis les blocs datés de ce fichier ; modèles par rôle, défaut `openai/gpt-6-luna` et son piège litellm ; Agent Cards NON signées (D7) ; budget de 3 créneaux en plafond dur ; timeouts réels (15/25 s, 30 s sur la démo) ; 7 guards propres à AgentB2C et anti-boucle lue sur l'état ; chemin d'éval Langfuse et ses pièges (l'`adk eval` est retiré) ; CI morte ; `agent-usa` et MCP_B2C sont des repos voisins ; contrats de `contracts/`.
- Ce fichier est coupé : les blocs du 2026-07-16 au 2026-09-09 sont déplacés tels quels dans `HANDOFF-ARCHIVE.md` (768 Ko → 88 Ko).
- 46 documents finis supprimés : phases livrées (OBS0-4, S01-09, S12-14, SG1-9, PR134, QA14707/Q01-13), `AUDIT-DRIFT-AGENT-USA-2026-07-20.md`, `EVAL-PACK-COMPARISON-2026-07-22.md`, `PROMPTS-OBS-LANGFUSE.md` (le prompt OBS9 est recopié dans `CHANTIERS.md` O4), `PROMPTS-SESSIONS.md`, `reports/judge_*.json`.
- Code mort supprimé : 4 sondes d'items clos (UX3/UX4/UX6), `scripts/run_llm_meter.py` et son test (recommités par erreur dans 69aa145), le chemin `adk eval` (`evalset/evalset-v0.adk.json`, `evalset/test_config.json`, `scripts/convert_evalset.py` ; `evalset/evalset-v0.json` reste, la batterie le lit), `reset_profile_store` (aucun appelant).
- Commentaires périmés corrigés (triage, agent, scores « 18 guards / 7 ajouts », resilience, inventory, calendar_rot) et 4 descriptions de `observability/langfuse/score-configs.json` (export versionné).
- `CHANTIERS.md` : Q1 (déjà réglé par #114/#115) et Q3 (ce nettoyage) fermés, Q13 notée faite ; `tasks/todo.md` archivé dans `tasks/archive/todo-2026-09.md` et remplacé par un pointeur.
- Local : 128 branches contenues dans `main` ou `plan/qa14707` supprimées, worktree `../AgentB2C-card-truth` (mergé) retiré, sorties ignorées périmées effacées, `.worktreeinclude` commité.
- Gates : pytest **2 988 passés / 1 skippé en 27 s**, ruff OK, mypy 68 fichiers OK, `dayuse_guardrails.sh` OK.

**Reste** :
- La seconde PR (#143) est mergée et déployée (bloc ci-dessus) ; `chore/cleanup` contient `main` et part en PR vers `main`.
- Instance Langfuse live : reporter les 4 descriptions corrigées (`guard_geocode_echo_back`, `guard_date_carryover_stale_floored`, `guard_anti_clarification_loop`, `guard_poi_anchor_coherence`).
- Gardés volontairement : `agents/b2c_concierge/b2c_concierge/tool_loop.py` (inutilisé depuis S07), `dayuse_eval_pack/` et les scripts `eval_*` (seuls leurs tests les lisent), les branches de juillet non mergées (`s-d-judge-ab`, `s2-faq-orchestrateur`, `scx6-same-day-cutoff-fallback`), les 106 branches distantes déjà mergées.

**Pièges découverts** :
- **La suite ne dure pas 5 min** : les 5-6 min du 2026-10-16 venaient de l'environnement ; le même code (`plan/qa14707`) tourne en 21 s le 2026-10-19 (`--durations` : `test_calendar_rot` ~10 s, rien d'autre au-dessus de 2 s).
- **#136 « Merged » n'est pas sur `main`** : `fix/pr134-blockers` a été mergée dans `codex/production-context-and-proximity` (#134, jamais mergée), soit 144 commits hors de `main`. Garder ces branches tant que le portage de #134 par familles n'est pas fini.
- Un renvoi « HANDOFF <date> » antérieur au 2026-09-14 (code, documents) se cherche dans `HANDOFF-ARCHIVE.md`.

## 🚀 2026-10-19 — Widget redéployé sur `124cd43` (#142, refonte design)

**Fait** (procédure `DEPLOY.md`) : pré-vol sur `main` propre `124cd43`, pytest **2 935 passés / 1 skippé** (25 s). Estampilles lues avant : `widget`, `concierge`, `hotel-search` = `0b65159`, `faq` = `28c485a`. Depuis `0b65159`, seul `web/` a changé (les 7 commits de #142) : **seul `widget` est redéployé** (`LANGFUSE_RELEASE=124cd43` posé avec `--skip-deploys`, puis `railway up --service widget --detach`). Les 3 backends gardent leur estampille, qui reste vraie : `faq` n'a pas bougé depuis `28c485a` (les seuls changements de `libs/` depuis sont `clarification.py` et `geo_intent.py`, que `faq` n'importe pas et que `__init__` n'exporte pas, plus `pydantic`, déjà transitif).

**Preuve** :
- Les 4 fichiers vérifiés sont servis à l'octet près comme dans `124cd43` (sha256 : `tokens.css` `bf339a5…`, `hotels.css` `3e8dfa7…`, `hotels/card.js` `1613ed8…`, `motion.js` `a8f81f7…`). Avant le déploiement : `tokens.css` à l'ancien hash, `motion.js` en 404.
- La page servie porte le seul changement de gabarit de #142 (viewport sans `user-scalable=no`).
- Un tour synthétique via le widget public (`x-dayuse-synthetic: 1`, « un day use à Londres, Royaume-Uni, demain après-midi ») : 200 en 7,3 s, 5 hôtels, réponse cohérente en français — le relais widget → concierge tient.

**Reste** : le rendu visuel de la refonte n'a pas été regardé dans un navigateur après déploiement. Les phases 4-5 de QA14707 (`plan/qa14707`) et le nettoyage (`chore/cleanup`) ne sont ni sur `main` ni poussés : ce déploiement ne les contient pas.

## 🏔️ 2026-10-19 — Refonte design du widget, lot 5 « hero + chat » (branche `design/widget-design-foundations`)

**Fait (CSS seul)** :
- Titre du hero en Display : 56 / 64 / −2 px desktop, 32 / 40 / −1,1 px mobile, Maison Neue Extended 700. `@font-face` recalé en 700 (le fichier est un Bold : plus de gras synthétique).
- Photo du hero : titre et sous-titre en blanc pur, plus d'ombre portée ni de dégradé coloré dans `.gradient-text` (loi 5). Voile plat noir 50 % (plancher « Veil / Top of content »).
- Thinking : texte `--fg-secondary` qui respire en opacité (`thinkingPulse`), plus de dégradé animé ni de #F55F30 ; point de chargement en `--fg-secondary`. `gradientShift` n'est plus utilisé.
- Avatar IA, pastille du header et `.ai-glyph` : `--universe-sunny-default` à la place de `--dy-gradient-primary` (plus aucun usage hors `tokens.css`).
- Test `tests/widget/widget_hero.test.mjs` ; 43 tests JS verts, guardrail OK. Captures Playwright sur mock : hero desktop 1440 et mobile 390 conformes.

**Décisions à valider par Stéphane** : titre du hero entièrement blanc (le dégradé de marque est retiré) ; voile du hero plat 50 % (la spec décrit un dégradé depuis le bord du contenu, le hero est centré, pas de dérivation officielle) ; thinking en texte secondaire pulsé (mouvement « Custom », non documenté) ; avatar IA en Universe Sunny.

**Pas fait / reste** :
- Bulles de message, composer et feedback : boutons et focus déjà couverts (lots 2 et 3), pas de nouvelle règle de forme appliquée.
- Dans `tokens.css`, les alias `--dy-*`, `--shadow-*` et `--dur-*` hérités sont à supprimer après relecture (plus utilisés, à confirmer par grep avant).
- Rendu vérifié sur mock seulement ; le passage clavier réel reste à faire.

## 🃏 2026-10-19 — Refonte design du widget, lot 4 « cartes + carrousel » (branche `design/widget-design-foundations`)

**Fait (CSS seul, aucun JS)** :
- Photo de carte hôtel et galerie en 3:2 (`aspect-ratio`), fini les 160 px fixes (`hotels.css`, `carousel.css`).
- Swipe mobile (règle 13) : carte = largeur de la rangée − 44 px (gutter 12 + peek 32), marge et fin de rangée 16, snap 16 ; la carte suivante dépasse donc de 32 px (avant : 100 %, aucun indice de swipe). Gutter desktop 24.
- Image depth volontairement NON appliqué : la photo est une galerie avec flèches au survol, la spec l'exclut dans ce cas. Veils (protection de texte, state layer) non applicables : le contenu de la carte est sous la photo, pas dessus.
- Test `tests/widget/widget_cards.test.mjs` ; 34 tests JS verts, guardrail OK.

**Pièges / à valider** :
- Non vérifié visuellement : le mock ne rend pas le carrousel de cartes (à regarder en local, desktop 1440 et mobile 390).
- Le hack `zoom: 0.8` desktop sur `.hotel-card` (responsive.css) est conservé : il contredit « la carte se déduit du viewport » ; à traiter avec Stéphane (desktop = grille, flèches en confort).
- Desktop : la rangée défile toujours (cartes 320 px fixes), pas encore posée sur la grille.
- Cartes `.simplified` (120 px, hors 3:2) non touchées.
- Retouche après relecture de Fabien : flèches du carrousel desktop recentrées sur la photo 3:2 (elles tombaient sur le titre) ; `.hotel-name` réserve 2 lignes (`min-height: 2lh`) pour aligner créneaux et pied de carte. Valeurs de `top` calculées pour une carte de 320 px (zoom 0.8 desktop) : à recalculer si le zoom saute.
- Quartier : le payload envoie la zone en slug (« marina-del-rey ») ; `humanizeZone()` dans `hotels/card.js` l'affiche « Marina Del Rey » (test `widget_zone.test.mjs`). Correctif côté widget ; la vraie correction serait d'envoyer un nom lisible depuis le backend (`response_bridge.py` / zone du profil), non touché.
- Prix en € pour Los Angeles : voulu (règle produit du 2026-09-25, EUR par défaut, devise de l'hôtel sur demande). Décision de Fabien 2026-10-19 : on ne touche pas au backend, chantier = front uniquement. Le MCP interrogé n'expose pas encore `hotelCurrency`/`hotelPrice` (vérifié sur une recherche Los Angeles) ; `cityName` y arrive en slug, d'où `humanizeZone()` côté widget.
- Reste : `--shadow-*`, dégradés/teintes `--dy-*` des cartes → lot 5 ou nettoyage.

## 🔘 2026-10-19 — Refonte design du widget, lot 3 « physique des boutons + Universe Sunny » (branche `design/widget-design-foundations`)

**Fait** :
- `tokens.css` : tokens Universe Sunny (dégradé radial ellipse 300 % × 200 %, centres 150 / 50 / −50 %, stops 13 / 50 / 75 / 87 %), ombres hover / press, ombre inset du press Default, Translucent Light 50 / 75 / 87 %, Hoverlay 3 / 6 %, `--press-offset: 2px`.
- Nouveau `buttons.css` (importé avant `hero.css`) : familles Universe, Default, Selected, Translucent. Hover = lumière seule, aucun mouvement ; press = +2 px dans l'empreinte avec ombres inset ; boutons flottants en `translateY(calc(-50% + var(--press-offset)))`.
- Plus aucun `translateY`/`scale` au hover, plus de `transition: all` ; durées Physical 300 ms ease-out.
- Test `tests/widget/widget_buttons.test.mjs` ; 31 tests JS verts, guardrail OK.
- Captures Playwright sur mock (hero, résultats, hover/press du CTA, mobile 390) : états conformes.

**Décisions à valider par Stéphane** : l'univers du widget est Sunny (supposé) ; `.book-button` traité en Universe ; `.response-card__link` passe en Default ; `.search-example` en Translucent Light, texte sombre ; Glass approximé par un flou ; `--ease-out` (valeur Figma à confirmer).

**Pièges / à vérifier** :
- Rendu vérifié sur un mock, pas sur le vrai backend ; pas de passage clavier réel.
- Le mock n'affiche pas le carrousel de cartes (seule la booking card) : cartes = lot 4.
- Le titre du hero garde son dégradé (lot 5).
- `.claude/preview/web.tgz` (non suivi) laissé dans le dépôt : à supprimer.
- Verrous git renommés (`.git/stale-*`, `.git/objects/stale-*`) : à supprimer à la main.

## ♿ 2026-10-19 — Refonte design du widget, lot 2 « accessibilité » (branche `design/widget-design-foundations`)

**Fait** :
- Saisie à 16 px / 500 / interligne 1,5 partout (`input[type=text]` du hero, textarea du composer) : règle Input des fondations, plus de dépendance au correctif mobile.
- `templates/chat_clean.html` : `maximum-scale=1.0, user-scalable=no` retirés du viewport, le zoom utilisateur n'est plus bloqué.
- Focus clavier global dans `base.css` : anneau `--focus-ring` #005FCC sur couche blanche, `:focus-visible`, via `:where()` (spécificité 0). Les deux règles ad hoc de `hotels.css` (`.pick-cta`, `.booking-card__plan`) sont supprimées. Pour la capsule du hero et la bulle du composer, l'anneau se dessine sur le conteneur (`:has(...:focus-visible)`), le champ nu n'a plus d'outline.
- `prefers-reduced-motion: reduce` dans `animations.css` (animations et transitions coupées) ; nouveau `static/js/chat/motion.js` (`scrollBehavior()`) branché sur les 6 `scrollTo/scrollBy/scrollIntoView` lissés ; plus aucun `behavior: 'smooth'` en dur.
- Test `tests/widget/widget_motion.test.mjs` (5 cas) : 26 tests JS verts, guardrail OK.

**Pièges / à vérifier** :
- Les champs texte déclenchent `:focus-visible` même à la souris (heuristique navigateur) : l'anneau du composer apparaît donc aussi au clic. Écart avec la loi 3 (« anneau = clavier seulement »), non contournable en CSS pur.
- Le champ à 16 px agrandit un peu le hero et le composer sur desktop : à regarder en captures (1440 et 390).
- La navigation clavier réelle (puces, envoi, flèches du carrousel, feedback) n'a pas été parcourue : aucun navigateur côté session.
- Un seul jeu de commits sur la branche, un par lot.

## 🎨 2026-10-19 — Refonte design du widget, lot 1 « tokens » (branche `design/widget-design-foundations`, créée depuis `main`)

Source : audit « Audit design du widget AgentB2C » (doc Claude) contre les fondations Dayuse de Stéphane (Figma, export du 2026-09-25). Plan en 5 lots, un par session : 1 tokens, 2 accessibilité, 3 physique des boutons, 4 cartes et carrousel, 5 hero et chat.

**Fait (lot 1, CSS uniquement, aucune mise en page ni JS touchés)** :
- `web/vendor/static/css/chat/tokens.css` réécrit : palette Neutral, rôles (fg/bg/solid/inline/indicator/border/divider/feedback/focus/veil), radius 4/8/16/32/999, échelle de texte. Les anciens alias (`--fg-default`, `--bg-surface`, `--border-focus`…) restent en section LEGACY, remappés sur les nouvelles valeurs.
- Sweep des 9 autres CSS : hex en dur → tokens (hors dégradés), `--radius-*` et `--fs-*` anciens → nouveaux noms, tailles hors échelle recalées (9,5 à 11,5 et 12,5 → 12 ; 13, 13,5, 15 → 14 ; 22 → 20 ; 25, 26 → 24 ; 30 → 32), `100px` → `--radius-action`, encre #120223 → #292935, prix en Manrope (loi 9), prix barrés en `--fg-secondary`, focus en `--focus-ring`, radio du plan de réservation en `--indicator-default`.
- Gris et bordures plus soutenus qu'avant (`--border-default` #C9C9CC au lieu de #EAEAEB) : c'est la valeur du système.

**Décisions prises, à valider par Stéphane** : badges « meilleur prix / populaire / mieux noté » tous en `--bg-accent` ; `.timeslot-pill--near` en Feedback/Warning ; `.response-card--*` en Feedback info/warning/success ; bulle utilisateur en Neutral 6 % (dérivation D1) ; `.deal-badge` reste en `--dy-watermelon` (rôle du badge promo non documenté) ; `--ease-out` inchangé (valeur Figma à confirmer, lot 3).

**Reste / pièges** :
- Dégradés, ombres (`--shadow-*`), durées (`--dur-*`) et `transition: all` : lot 3. `.initial-state h1` (46 px, 800, dégradé), thinking en dégradé, puces de suggestion en dégradé, `#FFB800` du loading-dot : lot 5.
- `@font-face` Maison Neue déclaré en 800 sur un fichier Bold et titre hero en 800 : volontairement laissés ensemble, à corriger avec le hero (lot 5), sinon gras synthétique.
- Non vérifié : aucune capture du rendu (pas de navigateur sur la machine locale de la session). Passer desktop 1440 et mobile 390 sur hero, carte hôtel, carrousel, booking card, composer avant de merger. Tests exécutés : `node --test tests/widget/*.test.mjs` (21 verts) et `scripts/dayuse_guardrails.sh` (OK) ; pytest non lancé (le `.venv` du dépôt est un venv macOS, inutilisable depuis la session).
- Aucun push ni PR : relecture de Fabien d'abord.

## 🧭 2026-10-16 — QA14707 phases 4-5 sur `plan/qa14707` : retraits des règles de langage, mémoire de question, anti-boucles, documentation (seconde PR)

Plan : `plans/qa14707/` (décisions DQ1-DQ13 dans `plans/qa14707/HANDOFF.md`), source `phases/QA14707/`. Cette seconde PR ne déploie rien : la production est sur `0b65159` (phases 1-3, #140). **La revue globale Q13 est faite (29/29 tâches, 2026-10-16) : reste à ouvrir la PR.**

**Fait (phase 4 : retraits, chacun sous test, aucun nom de garde retiré)** :
- **Q09, `3cbeba1` + `410b78e`** : plus de regex de prépositions ni de liste d'articles pour repêcher la ville, plus d'appariement de texte sur `pending_place`.
  - `git grep -n "_city_named_in_message\|_complete_pending_place\|_CITY_AFTER_PREPOSITION_RE" -- agents libs` ne renvoie plus de code (trois mentions de `pending_place` subsistent, toutes dans des tests : un nom de test et un commentaire, `agents/hotel_search_agent/tests/test_geocode_tool.py:424` et `:432`, et une docstring, `agents/b2c_concierge/tests/test_clarification_state.py:10`).
  - La spécification « St Paul's à Londres » passe par un `GeoIntent` : `TestCityNamedInMessage.test_a_landmark_with_its_city_in_the_intent_resolves` (`agents/hotel_search_agent/tests/test_geocode_tool.py`).
- **Q10, `b36672d` (S-L7f, DQ7)** : `select_us_postal_anchor` est retiré, avec `PostalAnchor` et les tables d'États du module.
  - Contrôle : `git grep -n select_us_postal_anchor -- agents libs` ne renvoie rien.
  - Tests : `agents/hotel_search_agent/tests/test_us_zip_removal.py` (8 tests sur des enregistrements Mapbox v6 réels, DQ9).
- **Q11, `41b0d29` + `9914d43`** : la question attendue et le oui/non ne sont plus extraits par regex ni par liste de mots sur la route de clarification, et `find_hotel_by_name` ne reçoit plus jamais le message brut (routes réservation et détails).
- **Q27, `df2451b`** : voir « Question que le tour suivant reprend » plus bas.
- **Q28, `8ec450c`** : voir « Les deux anti-boucles » plus bas.
- **Q29, `c2b9ac6`** : item live `qa14707-near-11580-en` (`evals/datasets/b2c-qa-14707-2026-10-14.jsonl`).

**Fait (phases 1-3, rappel avec preuve)** :
- **Q01, `c90a9b0`** : banc de preuve. `evals/langfuse_experiment.py` rejoue maintenant **chaque tour utilisateur d'un cas, dans l'ordre, sur une seule session** (avant : seul le dernier message partait). Les jeux multi-tours existants (`b2c-dialogue-state`, `geo-poi-multiturn-*`, certains jeux occupation et langues) sont donc devenus réellement multi-tours : **leurs anciens résultats live ne sont plus comparables**, H1 fixe la nouvelle référence. Tests : `evals/tests/test_langfuse_experiment.py`.
- **Q02, `f0b9a1e`** : créneau dans la langue de la conversation, `web/vendor/static/js/chat/slot_time.js`, test `tests/widget/widget_slot_time.test.mjs`.
- **Q03 `b3ecb1a`, Q04 `4a8fc52`, Q05 `6763465`** : `Clarification` (`libs/b2c_common/b2c_common/clarification.py`), rendue par gabarit sans synthèse (DQ2), la réponse à une question de lieu passe avant la réservation.
- **Q06 `e315fff`, Q07 `2d9b56d` + `da7f1a7`** : `GeoIntent` v1.1 (`libs/b2c_common/b2c_common/geo_intent.py`, snapshot `contracts/geo_intent.schema.json`), produit par la feuille de recherche (DQ1). Détail du mapping dans `reports/PLAN-LEAF-GEO-2026-10-08.md` §3.
- **Q08 `038ffd1`, Q14 `38060e5`, Q16 `b29a9ed`, Q17-Q26** : codes postaux et adresses, option d'homonyme choisie, marché, et les correctifs du diagnostic H3 (liste dans `plans/qa14707/HANDOFF.md`, sections Q17 à Q26).

**Preuve exacte et preuve approximative de « aucune option inventée »** :
- L'évaluateur live `clarify_options_from_geocoder` (`evals/langfuse_evaluators.py`) est un **signal live faible** : il compare seulement les noms de lieux que chaque item liste (Paris, Bruxelles…) aux candidats du géocodeur. Un lieu inventé que l'item ne liste pas passe inaperçu. Il est gardé tel quel pour que H1 et H3 restent comparables.
- La **garantie exacte** est hors ligne, en pytest : `TestRendering::test_no_word_of_a_reply_comes_from_outside_the_object` et `test_every_option_line_is_one_label_of_the_object` dans `agents/b2c_concierge/tests/test_clarification_template.py` (rendu par gabarit depuis l'objet `Clarification`, sans LLM), plus les deux tests de couture de `tests/test_leaf_concierge_seam.py`.

**Modèle de l'état de session que le port de #134 doit respecter** (décision #134 : c'est #134 qui s'aligne, pas l'inverse) — `agents/b2c_concierge/b2c_concierge/profile.py` :
- `profile.pending_clarification` = `{clarification, request, asked}` (`profile.py:301`, `next_pending_clarification` `:1085`).
  - `clarification` : l'objet `Clarification` (kind, sujet, options venues du seul géocodeur).
  - `request` : la demande d'origine, cumulée (date, créneau) pour que la réponse relance la recherche avec elle.
  - `asked` : combien de tours de suite ont posé **la même** question (même kind, sujet comparé sans casse ni espaces) ; revient à 1 sur toute autre question. C'est l'état que lit l'anti-boucle de lieu. Un `asked` absent ou non entier positif est lu comme 1.
- `profile.pending_search` = `{request, question, asked}` (`profile.py:292`, `free_question_streak` `:1013`, `next_pending_search` `:1026`). Ici `asked` compte les tours de suite qui ont fini sur une question libre sans recherche ; il ne porte aucun texte de message, il est propre au concierge (`_CONCIERGE_ONLY_KEYS`) et vit sous le TTL Redis existant. Un `asked` absent, booléen, chaîne ou < 1 compte pour « pas de série » : la question libre suivante compte 1 (`free_question_streak`). C'est l'inverse de `pending_clarification.asked`, qui lit un compte invalide comme 1. Un appelant qui ne veut que la demande (`next_pending_search` sans `ended_on_question`) écrit le slot sans clé `asked`. Tests : `TestStoredCount` dans `agents/b2c_concierge/tests/test_free_question_anti_loop.py`.
- `profile.region_anchor` (str | None, `profile.py:199`), champ **propriété du concierge** (Q14, `38060e5`).
  - Écrit uniquement depuis l'option choisie du `Clarification` stocké, jamais depuis le message.
  - Envoyé à la feuille dans `profile_in`, stocké dans Redis sous le TTL existant, effacé par un changement de ville (`profile.py:673`).
  - La feuille ne s'en sert que pour restreindre les candidats homonymes tant que la ville n'a pas changé (`_fill_place_from_profile`, `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py:1273`) : un État nommé ce tour-ci ou ancré l'emporte, une région sans correspondance ne restreint rien, et il n'est pas appliqué sur un tour de code postal.
  - **Raffinement Q21 (`773cbad`)** : tant qu'une région choisie s'applique, la requête v6 de l'option choisie ne porte aucun terme d'État. Un État nommé ce tour-ci, ancré ou lu dans le texte oriente toujours le résolveur (`region_hint`) et la garde d'écho ; la restriction ne garde que les candidats de la région choisie que l'écho de cet État accepte, et seulement s'il en reste au moins un. Un État qui contredit le choix ne restreint donc rien et le résolveur suit l'État. Tests : `agents/hotel_search_agent/tests/test_picked_option_query.py` ; code : `geocode_core` dans `geocode_tool.py`.
- `profile.entry_market_country` (str | None, `profile.py:240`, Q16, `b29a9ed`), champ **propriété du concierge**.
  - Écrivain unique : la façade, depuis le corps de la requête, vérifié ISO2 (`agents/b2c_concierge/b2c_concierge/facade.py:702-731`) ; une valeur invalide est abandonnée et la valeur stockée est conservée.
  - Stocké dans Redis sous le TTL existant, **non effacé** par un changement de ville, envoyé à la feuille de recherche dans `profile_in`.
  - Il sert uniquement de départage du marché (DQ8), jamais de filtre Mapbox.
  - **Ce n'est pas** le `entry_market_country` / `market_country` de la charge utile de réponse, que `_infer_market_country` déduit des résultats.

**Question que le tour suivant reprend (Q11 + Q27)** : un texte de question de lieu est le texte du gabarit tiré de `pending_clarification`. Sinon c'est la dernière ligne de la feuille quand elle finit par un point d'interrogation, sinon la dernière ligne de la synthèse par la même règle (`leaf_question` / `turn_question`, `profile.py:1174` et `:1193`, branchés dans `agent.py`). Aucune regex : la ponctuation de la dernière ligne non vide, plafonnée à 300 caractères. Tests : `agents/b2c_concierge/tests/test_synthesis_question_memory.py`.

**Les deux anti-boucles (Q04 + Q28)** :
- Questions de lieu : lues sur `pending_clarification.asked` (Q04). À partir du troisième envoi (`CLARIFICATION_MAX_ASKS = 2`), la réponse ne demande rien.
- Questions libres : lues sur `pending_search.asked` (Q28, `8ec450c`). Au-delà de `CLARIFICATION_MAX_ASKS`, la **même** synthèse reçoit l'instruction de ne rien demander, puis le code retire la ligne de question qui resterait (`without_final_question`), sans relance ni appel LLM de plus. La garde `anti_clarification_loop` se déclenche pour les deux. Tests : `agents/b2c_concierge/tests/test_free_question_anti_loop.py` et `test_clarification_template.py`.

**Postcode et adresse : ce que le tour persiste (Q08, Q26, `543e8aa`)** — `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py` :
- Code postal seul : seule sa ville (`context.place`) est persistée, pas de `zone`, rayon `poi` (disque serré) autour de son centroïde (Q26, `543e8aa`).
- Adresse : `zone` = le nom de l'adresse donné par Mapbox **sans** son code postal, rayon `poi`.
- Une adresse dont le `match_code.confidence` est `low` est refusée, et le code retombe sur la recherche du code postal.
- Sur un tour qui porte un `postal_code`, rien n'est repris du profil (ni ville, zone, métro, ancre pays, option choisie).

**Reste** :
- **H3' live sur gpt-6-luna (Fabien)**, une fois le build de la seconde PR lancé en local ; lire les lignes `dayuse_metric=geo_intent` (`.run-logs/`) produites par `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py` (`:1717`) :
  - **Taux** de `valid=0`, `mentions_discarded` et `canonicals_rejected`. `valid=0` élevé = le modèle ne tient pas le schéma imbriqué (DQ1 à revoir).
  - **`repaired=N`** : nombre de réparations portées par l'intention que l'outil a utilisée (une `city` chaîne devenue `CityRef`, une place de `kind` chaîne inconnu retirée ; `_repaired` / `_valid_intent`). Lecture : `valid=0` avec `repaired>0` = intention récupérée ; `valid=0` avec `repaired=0` = écartée en entier.
  - **`city_conflicts`** : une ville écrite par l'utilisateur CE tour-ci qui diffère, après pliage, de toute ville non vide portée par la place de zone (pas seulement une ville inférée) ; rien n'est compté sous `city_needed`. Un taux non nul = le modèle infère pour un lieu une autre ville que celle écrite.
  - **Traces A et B** : A = « Gare du Nord » + Paris, B = « Boulevard de la République Versailles » remplissent `city`.
  - **Drapeau S5** : `ambiguity.reason=city_needed` sur « gare de Lyon ».
- **Items à tenir 3/3 sur gpt-6-luna** :
  - `qa14707-versailles-address-fr` et `qa14707-poissonniere-75009-no-country-en` (Q20). Un tour de rue ou d'adresse sans code postal fait maintenant **un appel Mapbox v6 de plus** (types `address,street`) avant le chemin générique (`_street_match`, `geocode_tool.py:210`) : lire la latence (timeout 1,5 s, 1 retry).
  - `geo7-manhattan-answer` (Q21) : au tour de réponse il doit résoudre « Manhattan, État de New York » (localité) ; un passage par un POI commercial nommé Manhattan **ne compte pas**. Preuve hors ligne : `TestTheManhattanAnswer` dans `agents/hotel_search_agent/tests/test_picked_option_query.py`.
  - `geo7-named-not-found` (Q22, DQ10), « Bidule Imaginaire à Lyon » : la trace de la feuille montre `find_hotel_by_name` deux fois (avec `cityName`, puis sans), aucun `geocode_location` ni `search_offers` fait par le modèle, une ligne `named_hotel_city_search` en `status=ok`, des hôtels de Lyon après l'avis de non-trouvé. Preuve hors ligne : `TestNotFoundInANamedCity` dans `agents/hotel_search_agent/tests/test_named_hotel_city_fallback.py`.
  - Barre de Q23 sur gpt-6-luna : ville d'un monument remplie sans ville tapée, « gare de Lyon » `city_needed` 3/3, la réponse « Pari » 3/3, « dans le 75009 » extrait `postal_code` 3/3, et aucune intention écartée (`valid=0` avec `repaired=0`) sur les lignes `geo_intent`. Preuve hors ligne : `agents/hotel_search_agent/tests/test_geo_intent_field_order.py`. L'ordre des champs de `Place` et la liste `required` (`PLACE_REQUIRED`, `libs/b2c_common/b2c_common/geo_intent.py`) sont **réglés pour gpt-6-luna**, pas pour gpt-4o-mini.
  - `qa14707-guard-gare-du-nord-asks-city-fr` et `geo-poi-gare-du-nord` : 3/3 requis sur gpt-6-luna, recherche près de la gare du Nord à Paris, `clarify_expected` faux (DQ12). `qa14707-guard-gare-de-lyon-asks-city-fr` : 3/3 qui demandent toujours la ville (S5, DQ6). Un monument que le modèle laisse sans ville, sans correction d'appareil, reçoit quand même la question de ville en code (`agents/hotel_search_agent/tests/test_gare_du_nord_city_from_model.py` ne prouve que ce que le modèle lit ; le repli est testé dans `test_geo_intent_mapping.py`).
  - `qa14707-near-11580-en` (Q29) : 3/3 requis, `active_filters.country_code` US (`evals/datasets/b2c-qa-14707-2026-10-14.jsonl`), avec la configuration de H1/H3 (concurrence 1, Redis :6390, même IP de sortie). Sans marché, l'item échoue par construction (MX) : voir le bloc du 2026-10-19 bis.
- **Lignes de métrique de la feuille** (aucune ne porte de texte) :
  - `dayuse_metric=named_hotel_city_search agent=b2c_hotel_search status=ok|no_place|blocked|unbound|error ms=N` (`agents/hotel_search_agent/hotel_search_agent/named_hotel.py`) : `ok` = la ville a été géocodée et la recherche a tourné ; `no_place` = la ville n'a pas été géocodée, rien n'est cherché ; `blocked` = un before-tool a refusé la recherche ; `unbound` = aucun toolset MCP n'est lié ; `error` = exception avalée.
  - La ligne `named_hotel_search` rend maintenant `status=unbound` (avant `ok`) quand aucun toolset MCP n'est lié, ce qui n'arrive jamais en production.
- **Tickets restants** : aligner `geo-poi-gare-de-lyon` sur S5 et `geo7-gare-du-nord-no-city` sur DQ12 (seconde PR, décision du 2026-10-16) ; mesurer « je confirme » avec une offre en attente ; demander à Raphael quelle URL et quel marché il a testés (toutes ses traces portent `locale:"en"` et `currency:"USD"`) ; migrer le triage et le juge de gpt-4o-mini avant le 14/01/2027.
- **H4** après le merge : déploiement final, retest par Raphael, réponse point par point sur dayuse-com#14707.

**Pièges découverts** :
- **« near 11580 » sans pays nommé** : depuis Q10 (DQ7), un tour « near 11580 » reste aux États-Unis **seulement si la feuille extrait `postal_code`** ; la supposition DQ8 du modèle ou le marché garde alors le candidat US (`TestNear11580` dans `agents/hotel_search_agent/tests/test_postcode_resolution.py` et `agents/hotel_search_agent/tests/test_us_zip_removal.py`). Un tour où le modèle oublie le code postal n'est **plus rattaché à un pays**. Les trois tests qui nomment « USA » ne prouvent que le filtre dur du pays nommé. Le seul item live, `qa14707-near-11580-en`, est plus strict que la prod : le harnais n'envoie pas de marché et mesure la seule supposition du modèle (MX 3/3 au H3' du 2026-10-19), alors que le widget envoie `entry_market_country` (US 3/3, bloc du 2026-10-19 bis).
- **Source du pays du marché (DQ8)** : le `entry_market_country` de la requête (stocké dans le profil par Q16), puis la région du locale, puis le préjugé de langue (`_market_country`, `geocode_tool.py:155`). Le widget envoie un locale `en` nu, d'où la première source. Sans elle, « near 11580 » en en/USD suit l'ordre de Mapbox (Mexico d'abord), ce que fige `test_without_the_market_a_bare_en_follows_mapbox_order`.
- **Transition au déploiement de l'anti-boucle libre (Q28)** : les sessions stockées dans Redis avant le déploiement n'ont pas de `pending_search.asked` et comptent donc « pas de série » ; elles ne sont corrigées qu'à leur 4e question libre de suite au lieu de la 3e, jusqu'à l'expiration de leur TTL (`free_question_streak`, `agents/b2c_concierge/b2c_concierge/profile.py:1013` ; `TestStoredCount` dans `agents/b2c_concierge/tests/test_free_question_anti_loop.py`).
- **Un test rouge fait aussi tomber le garde calendaire** : `tests/test_calendar_rot.py` rejoue toute la suite, donc tout test rouge le fait tomber aussi. La suite complète dure ~25 s ; le 2026-10-16 elle a pris 5-6 min sur cette machine, sur un code qui tourne en 21 s le 2026-10-19 (cause d'environnement non trouvée, Langfuse était aussi injoignable ce jour-là) : une suite lente se diagnostique avec `pytest -q --durations=15`, elle ne prouve rien sur le code.
- **Imports de tests** : avec `--import-mode=importlib` (`pytest.ini:4`, commit 1bbdc4b), deux modules de test ne peuvent pas s'importer, et deux fichiers de même nom dans `agents/*/tests` font échouer la collecte complète.
- **Contexte du concierge et mots de l'utilisateur** : la feuille lit le texte du concierge (EARLIER REQUEST / YOU ASKED) dans une partie texte séparée placée **avant** les mots de l'utilisateur ; `read_user_words` ne lit que la dernière partie. Le test de couture `tests/test_leaf_concierge_seam.py` verrouille cette convention.
- **Dette notée** : le chemin détails/comparaison inline peut garder une question périmée dans `last_clarifying_question` quand sa synthèse est inutilisable (Q27, `agent.py` après le retour anticipé `candidate is None`) ; `is_bare_affirmative` sert encore `_ack_text` (`agents/b2c_concierge/b2c_concierge/agent.py:1167`), `search_exhausted` (`agent.py:1550`) et `is_search_refinement_signal` (`agents/b2c_concierge/b2c_concierge/profile.py:989`), et `_AFFIRMATIVE_RE` sert encore la confirmation de réservation (`is_booking_confirmation_signal`, `profile.py:1632`) (S-L7, hors périmètre) ; le commentaire de `agents/b2c_concierge/b2c_concierge/triage.py:79` cite encore `_extract_hotel_name_candidate`.

## 🚀 2026-10-15/16 — QA14707 phases 1-3 livrées sur `plan/qa14707` + feuilles en gpt-6-luna en prod

**Fait** :
- **Prod (15/10, release `28c485a`)** : `main` est déployé (#135 + #139).
  - Les feuilles recherche et FAQ tournent en `openai/gpt-6-luna` : gpt-4o-mini s'arrête le 14/01/2027.
  - Le triage reste en gpt-4o-mini, la synthèse en gpt-5.2 (effort `low`).
  - Traces vérifiées : 0 erreur, recherche en 6-7 s contre 22 s avant.
- **Piège gpt-6 levé par #139** : LiteLLM 1.90.2 ne connaît pas gpt-6.
  - Il faut `allowed_openai_params`, `max_completion_tokens`, et `reasoning_effort="none"`, sans quoi tout appel d'outil sur chat completions renvoie 400.
  - Un simple changement d'env aurait cassé la feuille de recherche.
- **Plan `plans/qa14707`, phases 1-3 sur `plan/qa14707`** : 21 tâches, dont Q14-Q26 ajoutées en cours de route.
  - Q01-Q08 : `GeoIntent` produit par la feuille, `Clarification` rendue par gabarit sans synthèse, routage réponse avant réservation, adresses et codes postaux, créneau dans la langue de la conversation.
  - Q14-Q26 : correctifs issus du diagnostic H3.
  - Tout est testé hors ligne, avec un contrôle négatif à chaque fois.
- **H1/H3 (preuves dans `plans/qa14707/PREREQUISITES.md`)** :
  - Premier H3 sur gpt-4o-mini : **échec**. gpt-4o-mini ne donne pas sa ville à un monument sous le schéma imbriqué (0/25).
  - H3 rejoué sur **gpt-6-luna** (DQ11) : **réussi**.
    - Le plan est au moins au niveau de `main` sur chaque évaluateur des 5 jeux.
    - Garde-fous 3/3, cas de Raphael 3/3 sur 8 items sur 9.
    - GeoIntent invalide sur 0,5 % des tours.
  - La seule exception (« dans le 75009 », rayon) est corrigée par Q26.

**Déployé (16/10, release `0b65159` = merge de #140)** :
- **Services** : `hotel-search`, `concierge` et `widget`. La `faq` garde `28c485a` : elle n'importe aucun des deux nouveaux modules de `libs/`.
- **Preuve** : tours synthétiques sur le widget de prod.
  - Gare du Nord : recherche à Paris, cartes à 0,2-0,3 km.
  - gare de Lyon : question par gabarit, sans appel à la synthèse.
  - « dans le 75009 » : anneau serré, cartes à 0,4-1,1 km.
  - Versailles : hôtels à 1,2-1,4 km.
  - « Je confirme » après une question : aucune réservation, la question revient reformulée.
- **Langfuse** : release `0b65159` sur les 6 traces, rôles conformes (feuilles gpt-6-luna, triage gpt-4o-mini, synthèse gpt-5.2).
  - Une seule erreur : un 520 Cloudflare d'OpenAI sur la synthèse, couvert par le repli honnête (`fallback_synthesis`).
  - Sur 7 jours, 2 replis pour 1 706 tours.
- **Widget** : le `utils.js` servi est identique à celui de `main` (plus de `formatTimeAMPM`).

**Reste** :
- Seconde PR : la phase 4 (Q09-Q11, Q27) et Q28, Q29, Q12 sont faites, voir le bloc du 2026-10-16 en tête ; Q13 (revue globale) faite le 2026-10-16.
- Tickets :
  - aligner `geo-poi-gare-de-lyon` sur S5 et `geo7-gare-du-nord-no-city` sur DQ12 ;
  - mesurer « je confirme » avec une offre en attente ;
  - migrer le triage (effort de raisonnement par rôle) et le juge de gpt-4o-mini avant le 14/01/2027 ;
  - agent-usa : même piège gpt-6 (`openai_adapter.py:57`).

**Pièges découverts** :
- `evals/langfuse_experiment.py` doit tourner avec **`--max-concurrency 1`**. À 5, MCP_B2C renvoie des 429 à la création de session et fausse tous les résultats.
- Redis local : `dayuse-redis-1` occupe le port 6379. Utiliser un Redis dédié sur :6390.
- Le `.env` local ne fixe aucun `DAYUSE_MODEL*` : le local tourne sur le modèle par défaut du code, pas sur le mélange de la prod.
- Un merge sur `main` ne déploie rien. Toujours déployer depuis un worktree propre de `main`.
- Les variables de modèle ne se posent qu'avec `--skip-deploys`.

## 📐 2026-10-14 — Retours QA de Raphael sur dayuse-com#14707 : diagnostic + plan orchestre (zéro code)

**Fait** : diagnostic prouvé sur 14 traces Langfuse, et plan source `phases/QA14707/` (README, DIAGNOSTIC, tâches Q01-Q13), prêt pour `/orchestre:prepare phases/QA14707`.

**Constats** (détail dans `phases/QA14707/DIAGNOSTIC.md`) :
- 🔴 **La prod sert `cbe88b9`** (release de toutes les traces de Raphael). #135 (= #124 + #125) n'est **pas déployée**, et la QA du 14/10 a testé un build sans les correctifs du 30/09.
- Créneau `10am - 4pm` en conversation FR : `formatTimeAMPM` (`web/vendor/static/js/chat/utils.js:46`) ignore la langue. Le « cut-off » de Raphael désigne bien le créneau (confirmé par Fabien).
- Ville, adresse ou code postal ignorés :
  - le 4o-mini de la feuille met `city=""` (« paris Gare du nord »), enfouit la ville dans `zone` (Versailles) ou jette le code postal (75009) ;
  - le code pose alors `city_needed` sans option ;
  - **la synthèse gpt-5.2 invente les options** (« Bruxelles », « Versailles (78) »).
- Boucle :
  - la feuille ne voit pas la question posée et ne comprend pas « Pari » ;
  - la garde anti-boucle compare des paraphrases ;
  - « Je confirme » est trié `booking`, et le routage ne renvoie une demande en attente vers la recherche que si `family == "ack"`. **`main` ne corrige pas ce cas** (lu dans le code).
- Défaut latent, prouvé hors ligne : `select_us_postal_anchor` lit 75009 et 13001 comme des ZIP américains et force `country_code=US`.
- `fc5cbd9` (sur `main`) répare le cas A par une regex de prépositions, qui n'attrape ni « a room in paris », ni Versailles, ni le code postal.

**Décisions (Fabien, 14/10, recommandations retenues)** :
- **D-Q1** : le `GeoIntent` est d'abord produit par la feuille de recherche actuelle, comme argument de `geocode_location` (contrat S-L §3, plus `postal_code` et `mention` / `canonical`). S-L3/S-L4 deviennent conditionnels.
- **D-Q2** : une clarification est rendue par gabarit, sans synthèse.
- **D-Q3** : déployer `main` après le rejeu de référence.

**Reste** :
- merger cette PR de docs, `git pull`, puis `/orchestre:prepare phases/QA14707` dans une nouvelle session ;
- H1 (rejeu de référence, `cbe88b9` contre `main`) puis H2 (déploiement de `main`), à faire par Fabien ;
- demander à Raphael l'URL et le marché de test : `locale:"en"` et `USD` sur toutes ses traces.

🪤 `/orchestre:prepare` prend un dossier contenant `tasks/` ou `taches/` pour un plan déjà converti et s'arrête : le plan source garde ses tâches à plat.

## 🟡 2026-10-12 (bis) — PORT1 « vérité des cartes » : #134 portée sur `main` en 5 tranches (PR à revoir, prompt de triage non mesuré)

Périmètre : `phases/PORT1-verite-des-cartes.md`. Branche `port/card-truth` (worktree `../AgentB2C-card-truth`), base `main` @ `49d5bd3`, source `origin/codex/production-context-and-proximity` @ `d8832b6` (#134 + #136), lue par `git show`, jamais mergée. Modèle d'état de #135 gardé ; hôtel nommé côté concierge (`named_hotel_id`) **non porté**. Hors ligne uniquement : aucun appel LLM, MCP ni réseau.

**Fait — un commit par tranche** (chacune : tests rouges d'abord, contrôle négatif, gates vertes avant la suivante) :

| Tranche | Commit | Tests | Contrôle négatif |
|---|---|---|---|
| 1 Preuves d'offre et frais | `cadf859` | `tests/test_offer_evidence.py`, `test_ground_truth::test_total_with_fees_…` | 8 retombent |
| 2 Revalidation datée détails/comparaison | `418ce0e` | `agents/b2c_concierge/tests/test_dated_details.py`, `test_ground_truth::test_verified_alternative_formulas_…` | 15 retombent |
| 3 Budget typé + B3 de #136 | `726c8bd` | `tests/test_requested_budget.py`, `tests/test_numeric_budget_context.py`, `test_typed_budget_spine.py`, `test_budget_injection::TestTypedRequest`, `test_response_bridge` (2), `test_display_currency` (2) | 40 retombent |
| 4 « Moins cher » | `aaa721b` | `tests/test_price_comparison.py`, `test_typed_budget_spine.py` (6) | 13 retombent |
| 5 Capacité chambre et groupe | `9f13ef3` | `tests/test_party_update.py`, `tests/test_room_requirements.py`, `test_party_discovery.py`, `test_occupancy` (4), `test_dated_details` (2), `test_inline_tools::…owned_bedding…` | 19 + 1 erreur de collecte |

Gates **à chaque commit** (rejouées commit par commit après la revue) : pytest 2 271 → 2 289 → 2 334 → 2 359 → **2 416 passés / 1 skippé**, garde calendrier comprise · ruff · mypy `agents libs` · `dayuse_guardrails.sh` : verts.

**Revue indépendante (agent de revue, puis vérifiée) : 8 défauts corrigés**, chacun avec un test rouge d'abord, replié dans le commit de sa tranche (fixup + autosquash, arbre final identique) :
- T2 — une carte affichée « la plus proche » du créneau était déclarée « non revalidée » par la comparaison : `preserve_shown_offer` ne revérifie plus que l'identité, le jour, le créneau, le cutoff et le prix.
- T3 — « $100 » à Paris vidait la page puis posait la question seule (contraire à B3) : un budget dont la devise n'est pas résolue ne filtre plus les cartes, la question s'ajoute aux résultats.
- T3 — « vos offres respectent votre budget » était dit sur des cartes non filtrées (hôtel nommé) : `cards_fit_budget` exige un total vérifié ≤ plafond sur chaque carte, sinon « BUDGET NOT VERIFIED ».
- T3 — les questions de budget du code n'étaient pas mémorisées (`last_clarifying_question`), donc un « 80 » en réponse était jeté ; et une question non répondue bloquait toutes les recherches suivantes : elle est posée une fois, puis abandonnée (`requested_budget = {}`).
- T3 — la devise non supportée différée se répétait à chaque recherche : le différé ne vaut que pour le tour qui répond à la demande non cherchée (`pending_search` de #135).
- T4 — la référence « moins cher » restait active après un changement de ville ou de critère : elle ne survit qu'à la page suivante de la même recherche ; la question de référence est mémorisée.
- T5 — une composition donnée dans un tour de réservation (« 2 adultes et 1 enfant, je réserve ») était perdue et la réservation refusée : la route réservation l'enregistre aussi.

Non corrigé (signalé par la revue, à arbitrer) : montants avec séparateur de milliers (« 1 000 € », « $1,000 ») rejetés par `_amounts` puis budget = `{}` ; comparaison datée = 5 sessions MCP concurrentes, un seul échec fait échouer la comparaison (MCP renvoie des 429 sur appels enchaînés — à vérifier en live).

**Réponses aux 2 questions ouvertes du fichier de phase (par test, avant le code)** :
1. `budget_integrity` ne contredit pas `offer_within_budget` : la garde décide seulement si un montant devient `budget_max`, elle ne lit aucune offre ; MCP applique `priceRangeMax` au prix frais compris, le même total que le filtre typé. Le prix sans frais d'une carte ne décide d'aucun côté. Test : `test_requested_budget.py::test_budget_integrity_and_offer_within_budget_agree_on_a_hotel_hiding_its_fees`.
2. La réécriture de `test_display_currency` (devise inconnue sans résultat → différée) ne casse **aucun** test de #135 (suite complète verte avec le seul différé) et compose avec sa question en attente (`pending_search`) : la devise demandée au tour 1 est décidée sur les hôtels du tour de réponse. Test : `test_display_currency.py::test_deferred_currency_is_resolved_by_the_answer_to_the_pending_question`. Le différé est porté (tranche 3).

**Tranche 2, vérification demandée** : le `compare_hotels` de `main` **ne suffit pas**. Il n'envoie jamais `date` (ni à `compare_hotels` ni à `get_hotel_details`) et lit le `bestOffer` du MCP. Le contrat publie bien `date` sur les deux outils, mais `compare_hotels` ne rend qu'**un** `bestOffer` par hôtel : même daté, il peut citer une autre formule que celle de la carte. Porté tel quel : shortlist datée → ≤ 5 `get_hotel_details` datés concurrents (`best_by` vide), shortlist non datée → 1 `compare_hotels`. (Le commentaire de #134 « compare_hotels has no date parameter » était faux et n'est pas repris.)

**Écarts voulus avec #134** :
- **Pas de listes de mots** (règle PORT1) : `_literal_currency` et `currency_answer` de `search_budget.py` (noms de devises en 6 langues) ne sont pas portés. Le triage pose un enum fermé `currency_basis: "dollar"` pour « $100 » sans pays ; le code résout par le pays géocodé (`_DOLLAR_MARKETS`). Un code ISO nommé est **cru sur parole** du LLM (format seulement vérifié).
- `bare_budget_value` et `apply_recognized_bare_budget` **supprimés** : un seul slot, `requested_budget` (requis). La dernière question posée (`last_clarifying_question`) est passée au triage pour `answer_to`.
- `offer_totals` vit dans `pricing.py` (pas dans `price_comparison.py`).
- Pas de template « est-ce votre budget ? » : un nombre nu non prouvé n'est simplement pas un budget, la recherche part.
- Page vide avec budget typé : la ligne « aucune offre » de `main` (#126) cite le plafond, la synthèse ajoute la piste (pas de template sans synthèse comme dans #134).

**Reste** :
- ⚠️ **Prompt de triage non mesuré** (tranches 3, 4, 5 : `requested_budget`, `currency_basis`, `answer_to`, `price_comparison`, `requested_occupancy`, `requested_room`, + bloc `LAST ASSISTANT QUESTION`). Aucune mesure LLM faite (pas d'accord de coût). À faire avant merge : rejeu `evals/production_replay.py` sur la config prod (triage gpt-4o-mini), en surveillant : nombre nu (« 75008 », « 60 » après « quel budget ? »), « $100 » à Toronto vs New York, « moins cher » sans/avec cartes, « nous sommes 3 », « sans les enfants », longueur/latence du prompt (timeout triage 5 s).
- **Non porté** : `budget_pages` (attend `reserve_mcp_read`, B1/R6b de #136, absent de `main`) → un budget hors EUR ne filtre que la 1re page MCP ; accès privatif/inclus aux équipements et avertissement B2 (famille Équipements) ; `displayed_slot_fact`, `requested_window`, `arrival_daypart` (famille Dates) ; `area_scope`/`confirmed_location`/`destination_request` (Géographie) ; `comparison_positions`, `hotel_scope`, `get_shown_hotel_details` (prompt) ; `pagination_search_key`, `detail_results` ; élargissement du schéma `children` côté feuille.
- Tests de `main` réécrits (VOULU, décision B3 de Fabien) : `test_explicit_budget_is_never_auto_widened` (remplacé par la version `answer_to`), `test_bare_number_reply_overrides…`, `test_recognized_bare_budget_reaches…`, 2 tests d'`apply_recognized_bare_budget` (supprimés), slots P1 de `test_triage`. Signatures des faux `classify` : `+previous_question`.

**Pièges** :
- Dans les heredocs Python de session, `$S:t…` est un modificateur zsh : `git show $S:tests/x` lit `…ests/x`. Écrire `"${S}:tests/x"`.
- `echo =====` échoue en zsh (expansion `=`) : utiliser `echo '#####'`.
- Contrôle négatif quand un test importe un module neuf : la collecte s'arrête ; ajouter `--continue-on-collection-errors` pour compter les échecs.


## ✅ 2026-10-12 — Ménage des PR + #124/#125 enfin ramenées sur `main`

**Fait** : #115 (garde calendrier +400 j), #133 (« Voir tout » sans les heures) et #120 (`DEPLOY.md`) mergées dans cet ordre, chacune testée sur le `main` qui la recevait. #123 fermée (delta repris par #134), **branche conservée** : #121 est empilée dessus.

🪤 **#124 et #125 affichées « Merged » n'étaient pas sur `main`** : #124 a été mergée dans `fix/qa-oracle-facts-silent-fallbacks` (base de #122, déjà mergée), #125 dans `fix/geo-location-class` une minute après le départ de #124. Cette branche les ramène : merge de `fix/geo-location-class` (`2f457f8`) sur `main`, 6 fichiers en conflit, tous des ajouts concurrents au même endroit (paramètres `no_offers`/`recent_messages` de main + `unchanged` de la garde #18 ; route FAQ + route hôtel nommé dans `leaf_kwargs`). `no_offers` (0 résultat) et `unchanged` (>0 résultat) sont exclusifs. Gates : pytest **2 245 passés / 1 skippé** (= 2 142 de main + 104 de la branche, compte exact), ruff, mypy, guardrails verts, garde calendrier comprise.

**Reste** : #134 (Victor) doit se rebaser sur ce `main` — ~14 fichiers en conflit avec cette branche, plus un littéral « 12 novembre 2026 » (`test_location_confirmation.py`) que la garde +400 j fait tomber. Décision ouverte : le `location_intent` du triage de #134 contre la feuille géo (L1, `reports/PLAN-LEAF-GEO-2026-10-08.md`, dont la prémisse « #124 ouverte » est fausse).

## 📐 2026-10-08 — Plan de la leaf de compréhension géo (série S-L) : documents seulement, zéro code

**Fait** (session Cowork de revue, rien de commité) : plan arbitré `reports/PLAN-LEAF-GEO-2026-10-08.md` (décisions L1-L6 de Fabien, écarts E1-E15 entre le plan de la discovery et le code, contrat `GeoIntent` v1) ; phases `phases/SL1…SL8-*.md`, prompt de lancement inclus ; section S-L de `SESSIONS-CLAUDE-CODE.md` ; chantier L de `CHANTIERS.md` ; demande « coordonnées dans `find_hotel_by_name` » dans `reports/MCP-B2C-REQUESTS.md`.

**Constats vérifiés dans le code** (détail au plan §2) :
- Le plafond de 3 appels LLM par tour est appliqué en code (`agents/b2c_concierge/b2c_concierge/budget.py:18`, exception à la 4e charge) : une leaf de plus impose la décision D-1 avant S-L4.
- #124 envoie `sort` ; le MCP `main` 08f3764d attend `sortBy`. Le MCP `main` ne renvoie pas non plus les coordonnées dans `find_hotel_by_name`, dont `named_hotel.py:196` (#124) a besoin pour montrer les voisins.
- `contracts/mcp_b2c_tools.json` n'a ni `sortBy` ni `timeSlotMode` : déployer le MCP puis rafraîchir le contrat avant S-L1.
- Le test de contrat (`tests/test_mcp_contract.py`) n'exerce pas l'ancre de type lieu, ce qui explique que `sort` soit passé.

**Reste** : décisions D-1 à D-7 (plan §5) ; S-L1 et S-L2 peuvent démarrer.

## ✅ 2026-10-07 (quater) — « Voir tout » sans les heures quand aucune carte ne couvre le créneau

**Fait** (branche `fix/see-all-drops-window-when-closest`, sur `main` à `cbe88b9` ; gates : pytest **2 140 passés / 1 skippé**, ruff, mypy, guardrails **verts**). QA Mathias : « Je veux un hotel a miami de 6h a 23h » → cartes « les plus proches », mais « Voir tout » ouvrait le site filtré `checkinTime=6am&checkoutTime=11pm` → « No hotel available ».
1. `b2c_common.search_page.without_hours()` retire `checkinTime`/`checkoutTime` de l'URL (lieu + date gardés).
2. Concierge (`agent.py`, juste après la lecture de `search_context.search_page`) : appliqué quand `window_fallback` est posé — repli signalé par la feuille OU filet `enforce_window_match`. Des cartes qui couvrent le créneau → le lien garde les heures (décision Mathias).
3. `conftest.py` neutralise aussi `DAYUSE_MODEL_TRIAGE`/`_SYNTHESIS`, `DAYUSE_REASONING_EFFORT`, `CONCIERGE_LEAF_TIMEOUT_SECONDS` : `import litellm` charge le `.env` local, et un `.env` aligné sur la prod faisait tomber `test_synthesis_retry_policy`.

Contrôle négatif : avec `agent.py` de `main`, les 2 cas « aucune carte ne couvre » de `TestSeeAllLink` tombent.

**Parité locale / prod (vérifiée ce jour contre Railway)** — prod sur `cbe88b9` pour les 4 services. Concierge : `DAYUSE_MODEL_TRIAGE=gpt-4o-mini`, `DAYUSE_MODEL_SYNTHESIS=gpt-5.2`, `DAYUSE_REASONING_EFFORT=low`, `CONCIERGE_LEAF_TIMEOUT_SECONDS=30` ; feuilles : `DAYUSE_MODEL=gpt-4o-mini` ; tous : `MCP_B2C_URL=https://dayuse.mcp-servers.dayuse-dev.com/mcp`.

**Pièges** :
- 🪤 `DAYUSE_REASONING_EFFORT` ne va **pas** dans le `.env` local : `run_local.sh` le donne aux 3 services, et `build_model` (fleet) envoie alors `extra_body.reasoning` à `gpt-4o-mini` → `Unrecognized request argument supplied: reasoning`, feuilles en « je n'arrive pas à joindre ». Parité exacte = une surcharge par service dans `run_local.sh` (non faite).
- 🪤 `run_local.sh` lance uvicorn sans `--reload` : relancer après chaque modif, sinon on teste l'ancien code (services locaux trouvés sur le code de la veille).

## ✅ 2026-10-07 (ter) — #121 de Victor découpée en 3 PR rebasées sur `main` (référence = main post-#126)

**Fait** (comparaison #121/#123 vs MR de Mathias, puis extraction de ce qui n'est pas déjà sur `main`) :
1. `fix/bare-budget-reaches-mcp` — un budget nu (« 60 ») reconnu par le triage atteint enfin `priceRangeMax` (sur `main`, `inject_profile_budget` réappliquait l'ancien 150). pytest 1 986 ✅.
2. `fix/faq-followup-context` — suivis SAV : 3 derniers messages utilisateur → triage, feuille FAQ, synthèse (tours faq) ; règles « pas de recherche/annulation de réservation ». pytest 1 979 ✅.
3. `evals/production-replay-harness` (cette PR) — banc de rejeu apparié legacy-prod vs AgentB2C ; job CI `eval` = batterie 32 scénarios au lieu de `adk eval` (plus d'extra `google-adk[eval]`). pytest 2 123 ✅.

**Écarté de #121** (déjà sur `main`, ou en conflit avec) : la règle créneau à la minute (`main` = règle site de #122, `slot_covers_window`) ; la divulgation devise sur FAQ (#126).

**Reste** :
- #123 (contexte géo multi-tour) **non porté** : il déplace l'extraction du lieu de la feuille vers le triage (schéma JSON strict + `gpt-4.1-mini` figé dans le Dockerfile) — décision d'architecture à trancher avant tout portage. Seul le budget nu en a été repris (identique à #121).
- `scripts/eval_ranking.py` : miroir du filtre créneau, cite encore `_offer_fits_exact_window` (renommé `_offer_covers_window` sur `main`) et ne fait pas l'arrondi à l'heure de `slot_covers_window`.
- #121 et #123 restent ouvertes côté Victor : à fermer en renvoyant vers ces PR.

## ✅ 2026-10-07 (bis) — mcp-dayuse#4 : compteur et réserve parking (le reste du ticket était déjà livré)

**Fait** (branche `fix/mcp-4-parking-reserve-page-count`, sur `main` à `d973775` ; gates : pytest **1 976 passés / 1 skippé**, ruff, mypy, guardrails **verts**). Ticket https://gitlab.com/dayuse/dayuse/mcp-dayuse/-/work_items/4. Points 1, 2, 3, 5 du correctif immédiat déjà sur `main` (#122, mcp-dayuse#8) — vérifiés dans le code et en live (Lyon 12h–13h : plus de « exactement » ; Lyon 6h–16h : « aucune offre ne couvre tout le créneau ; voici les plus proches »).

1. **Compteur (point 4)** — la ligne de la feuille disait « 5 offre(s) de jour trouvée(s) » = taille de page (`MAX_RESULTS`). Elle ne porte plus de nombre (« Offres de jour affichées : … », 7 langues) et la synthèse a la consigne de ne jamais annoncer un nombre trouvé. Un vrai décompte (offres couvrantes sur toutes les pages, `total` réservable) dépend du MCP #1.
2. **Réserve parking (point 6)** — reproduite en live : « parking et piscine » → « toutes avec piscine », rien sur le parking. `fallback_text.enforce_parking_reserve` est maintenant appliquée à toute réponse de recherche avec cartes (plus seulement au repli), jamais en double. Revérifiée en live après correctif. Métrique `concierge_metric=parking_reserve`.

Contrôle négatif : les nouveaux tests tombent avec `agent.py` / `response_bridge.py` de `main` (9 échecs).

**Reste** :
- La réserve parking lit le message du tour : un parking demandé au tour 1 n'est pas rappelé au tour 2 (« moins cher »).
- Côté MCP (#1) : `timeSlot` par contenance, `total` réservable, groupes OU (parking, rooftop, navette, sauna).
- Id piscine 3001 absent de `list_amenities` : laissé tel quel (sans effet en OU, exception documentée dans `tests/test_mcp_contract.py`).

🪤 **Pièges découverts** :
- Dans le shell de session, `cat` est un alias vers `bat` (non installé) : un `cat >> fichier <<EOF` n'écrit RIEN et ne renvoie qu'un message sur stderr. Ajouter du texte avec Edit/Write.
- zsh ne découpe pas une variable non quotée (`pytest $T` = un seul argument) : écrire les chemins en clair.
- `main` a été pull dans le worktree principal pendant la session (autre session) : vérifier `git log` avant de brancher.

## ✅ 2026-10-07 — « Voir tout » branché sur le `searchPage` du MCP mergé

**Fait** (branche `fix/see-all-search-page-contract`). Le #2 côté MCP a été mergé par une autre branche (!32) avec un autre contrat que celui de #126 : `search_offers` renvoie un **`searchPage` unique** `{slug, label, countryCode}` (élu parmi les hôtels actifs proches, indépendant de la date et des filtres, `null` sinon), pas des `searchPages` par hôtel. Avec #126 seul, « Voir tout » retombait toujours, sans erreur, sur la page pays (reproduit en live contre mcp-dayuse `main`). `b2c_common.search_page.search_page_from` lit ce champ (slug validé, sinon rien) ; le choix par nom de lieu (`pick_search_page`) est supprimé ; l'URL garde date, heures et `selectedAddress`, hôte du marché de `countryCode`. Live : Lyon, Lyon 6h–16h (0 offre : la page existe quand même), San Francisco 10h–14h, Gare du Nord, Londres → 5 URLs en 200 ; widget vérifié en SSE. Ma branche MCP `feature/14707-search-page-breadcrumb` est **abandonnée** (jamais proposée en MR).

**Reste** : le MCP choisit la page la plus proche du point cherché, donc « un hôtel à Lyon » ouvre « Lyon 2eme arrondissement » et « Gare du Nord » ouvre « Paris 10eme » (choix documenté côté MCP, à arbitrer par le produit si on veut la ville). L'état vide du widget n'affiche aucun lien (pas de CTA de repli sur ce chemin, avant comme après) : en ajouter un est une décision produit.

## ✅ 2026-10-06 (bis) — mcp-dayuse#5 : périphérie de la réponse dérivée de la recherche exécutée

**Fait** (branche `fix/search-context-see-all`, PR #126 mergée ; « Voir tout » corrigé le 2026-10-07, voir au-dessus ; 1 commit par chantier ; gates : pytest **1 969 passés / 1 skippé**, ruff, mypy, guardrails **verts**). Ticket https://gitlab.com/dayuse/dayuse/mcp-dayuse/-/work_items/5 (+ #2 pour le MCP). Chaque défaut reproduit en live avant correctif, revérifié après, contrôle négatif fait (les nouveaux tests tombent sans le correctif). Décisions Mathias du jour : options recommandées sur les 4 questions.

1. **Provenance** — la feuille envoie toujours `flexible_default` : « de 6h à 16h » / « moins de 120 euros » tapés par l'utilisateur partaient en PROVENANCE « valeur par défaut ». `apply_profile_delta` les passe `explicit` quand le message les énonce (`_mentions_explicit_time`, `_states_amount`) et ne les rétrograde plus quand la même valeur est reportée. ⚠️ Effet voulu : un budget tapé n'est plus auto-élargi (`maybe_auto_widen` l'interdisait déjà pour un budget explicite) ; 2 tests qui élargissaient « a hotel under 100 » réécrits avec « a cheap hotel ».
2. **Note devise** — « Prix affichés en euros, sans conversion » seulement si l'utilisateur a demandé une devise (`profile.requested_currency`, dernier slot `display_currency` du triage). La devise du widget (`profile.currency`) et la devise propre d'un hôtel ne déclenchent plus rien seules (22 traces sur 29 le 30/09).
3. **États vides** — la feuille émet `search_context` (lieu, jour servi, créneau ou moment, budget, équipements appliqués, occupation, rayon, page de recherche) depuis les vrais arguments de `search_offers`. À 0 résultat, `b2c_concierge/no_offers.py` écrit la phrase en code (7 langues, « Aucune offre autour de Gare du Nord, Paris le … de 7h à 9h, à moins de 30 €, avec sauna. »), la synthèse n'ajoute que la piste ; une phrase du LLM qui la recopie est retirée (`drop_restated`, vu en live).
4. **« Voir tout »** — MCP (branche `feature/14707-search-page-breadcrumb` de mcp-dayuse, commit `82c4204`) : `searchPages` sur chaque hôtel de `search_offers` = items `/s/…` du `breadcrumb` indexé. `b2c_common/search_page.py` choisit la page du lieu (nom = zone puis ville, sinon page la plus précise commune à tous les hôtels, jamais le seul pays) et construit l'URL du site (`selectedAddress`, `checkinDate`, `checkinTime=6am`, `checkoutTime=4pm`). Transport : `search_context.search_page` → `profile.search_page` → marqueur `hotels` (SSE) et `market.search_page` (JSON). Widget : « Voir tout » et « Voir tous les hôtels à Lyon → » l'utilisent, page pays en repli. Vérifié en Chrome headless (POST et SSE) et 4 URLs générées en 200 sur le vrai site (Lyon, San Francisco, Paris/Gare du Nord, Londres).

**Non-régression** : pytest/ruff/mypy/guardrails verts ; le rejeu des datasets `evals/datasets/*.jsonl` main vs branche a été **lancé puis interrompu à la demande de Mathias — non fait**, à relancer avant merge.

**Reste** :
- **Déployer le MCP d'abord** (sinon pas de `searchPages` → repli page pays, sans erreur).
- Londres → page « Greater London » (aucun nœud « London » dans le fil d'Ariane des hôtels rendus) ; Monaco → pas de lien (marché absent de `_MARKET`).
- Un moment de la journée (« l'après-midi ») n'envoie pas d'heures au site.
- ~~Compteur (taille de page présentée comme nombre d'offres) : hors périmètre, tickets #4 / MCP #1.~~ Fait côté agent le 2026-10-07 (bis) ; le `total` réservable reste au MCP #1.
- État vide sans hôtel : « Voir tout » reste la page pays (pas d'hôtel → pas de fil d'Ariane).

🪤 **Pièges découverts** :
- **`/s/san-francisco` seul répond 404** sans `placeId` ; le chemin du fil d'Ariane (`/s/united-states/california/san-francisco-county/san-francisco`) marche, et les chemins sont identiques sur tous les domaines.
- **Plusieurs sessions en parallèle** : la session #6 a lancé sa stack sur 8120-8122 pendant que la mienne redémarrait (ma stack : `PORT_OFFSET=40`, MCP :8083). Et `git stash` est partagé entre worktrees : un de mes stash a été dépilé dans le worktree principal. Contrôle négatif par copie de fichier uniquement.
- Le LLM recopie une phrase qu'on lui montre même quand on lui dit de ne pas le faire : dédoublonner en code.

## ✅ 2026-10-06 (bis) — mcp-dayuse#6 : état de dialogue explicite

**Fait** (branche `fix/dialogue-state-explicit`, **empilée sur `fix/geo-location-class` (PR #124, mcp-dayuse#7)**, fusionnée dedans le 2026-10-07 après le merge de #122 — merger #124 d'abord ; le test #7 `test_a_named_hotel_without_offers_that_day_is_said_first` codait « demain » = 7 octobre en dur, rendu relatif à l'horloge dans la fusion ; 1 commit par chantier ; gates : pytest **1 955 passés / 1 skippé**, ruff, mypy, guardrails **verts**). Ticket https://gitlab.com/dayuse/dayuse/mcp-dayuse/-/work_items/6. Chaque défaut reproduit en live avant le correctif (2e stack `PORT_OFFSET=20`, MCP `main` local), revérifié après ; chaque nouveau test échoue sans son correctif.

Audit initial : la date perdue après une question (« samedi 3 octobre » → « Monaco ») était **déjà corrigée par #8** (`requested_date`). Tout le reste a été reproduit.

1. **Créneau sans report implicite** (décision Mathias : « 9h, fin libre ») — `datetime_resolver._drop_unstated_bounds` : dès que le message énonce une heure, une borne dont l'heure n'y figure pas est retirée, qu'elle vienne du tour précédent (« à 9h00 » après 13h-15h → 9h-15h) ou du LLM (« demain matin 7h » → 7h-8h) ; une fin qui n'est pas après le début (9h-9h, vu en live) aussi. La feuille envoie l'autre borne en `{"op": "clear"}` ; `apply_profile_delta` l'applique avant de recalculer `timeslot_mode`.
2. **Demande en attente** — nouveau slot concierge-only `profile.pending_search = {request, question}` : un tour de recherche qui pose une question au lieu de chercher laisse la demande non cherchée (cumulée, 500 car. max) et la question posée. Le tour suivant l'envoie à la feuille AVANT la réponse (`EARLIER REQUEST… / YOU ASKED… / REPLY:`, part texte préfixée dans `_attach_outgoing_datapart`), une seule fois. Live : « piscine < 150 € demain 14h-18h » → « Lyon » garde piscine, budget, créneau (avant : tout perdu sauf la date). Un « oui »/« ok » qui répond à la question va à la recherche, plus à l'accueil.
3. **« oui » sans question** (décision Mathias : relance courte) — `templates.affirmative_relaunch_response` : « Dites-moi la ville et la date… », ou après une recherche « Très bien ! Je peux aussi chercher à une autre date… ». « bonjour » garde l'accueil. Deux anciens tests figeaient « ok » → accueil : mis à jour.
4. **Guard #18 `refinement_unchanged`** (décision Mathias : honnêteté seule, le rayon reste au #7) — un tour de recherche qui remet à l'écran exactement les mêmes offres (`shortlist_signature` : hôtel, offre, prix, créneau, jour) commence par « Ce changement ne modifie pas les résultats… » et la synthèse reçoit `UNCHANGED:` (interdit de prétendre avoir élargi). Exclus : pagination, repaint devise. Live : « élargir la zone » et « rayon de 10 km » (avant : « J'ai élargi la zone »). Quand la feuille renvoie d'autres cartes, le guard ne s'applique pas : règle 10 de la synthèse, « ne jamais prétendre avoir élargi la zone » (le concierge ne contrôle pas le rayon — **à lever si #7 fait varier le rayon**). Live 4/4 sans « élargi ».
5. **Expiration visible** (décision Mathias : bandeau + phrase) — la façade lit `ProfileStore.exists` AVANT l'intake native-context : ADK session avec des tours + clé Redis absente = expirée. Nouveau champ de contrat **`session_expired`** (CONTRACT_KEYS), réponse préfixée « Notre conversation a expiré après 30 minutes d'inactivité : je repars de zéro. ». Chaque tour fait `ProfileStore.touch` (sinon un tour « bonjour », qui n'écrit rien, ferait passer le suivant pour expiré). Panne Redis ≠ expiration (`exists` → None). Widget : séparateur `.chat-notice` (`addNotice`, clé i18n `session_expired` × 7 langues), vérifié dans Chrome headless sur le vrai widget.
6. **Dataset** `evals/datasets/b2c-dialogue-state.jsonl` (9 items multi-tours, enregistré dans `langfuse_seed_datasets.py`). Le test node `tests/widget/widget_session_expired.test.mjs` passe par le runner pytest existant (qui lance désormais tous les `*.test.mjs` du dossier).

**Non-régression** : rejeu des 67 items des 5 datasets à messages (geo-poi, occupancy, language-robustness, qa-2026-09-30, dialogue-state) contre la stack de Mathias (`main`, :8100) et la branche (:8120), mêmes évaluateurs (`evals.langfuse_evaluators.response_evaluator`) : **111 → 120 / 171** vérifications vertes (2e rejeu, avant les 2 derniers correctifs créneau/synthèse). dialogue-state : 3/13 → 11/13 (les 2 restants — 9h-9h et « J'ai élargi » sur cartes différentes — sont corrigés par les 2 derniers commits, vérifiés en live, non rejoués) ; les gains qa-2026-09-30 viennent de #8 (la stack de Mathias tourne sur `main`). Les bascules inverses geo-poi / occupancy / code-switching sont celles déjà notées aléatoires sur les deux stacks (#8).
- 🔴 **Régression de la branche de base #8, pas de #6** : « busco un hotel con piscina en madrid mañana por la tarde » → la feuille met Madrid en `zone`, ville vide, geocode en erreur, aucune recherche (~2 fois sur 3 sur la branche, 0 fois sur 6 sur `main`). Chaque moitié seule passe. Reproduit en retirant ma seule modification du prompt de la feuille : c'est la base. **À regarder avant de merger la MR #8.**

**Reste** :
- Score config Langfuse `guard_refinement_unchanged` (Fabien), comme les 5 de #8. Seed : `scripts/langfuse_seed_datasets.py --only b2c-dialogue-state`.
- **Libellés d'expiration à valider avec le produit** (ticket « À confirmer ») : phrase de l'agent (`templates._SESSION_EXPIRED`) et bandeau (`i18n.js session_expired`).
- Un « oui » à une question d'un tour détails/comparaison (pas de recherche) reçoit la relance courte : `pending_search` ne couvre que la recherche.
- Hors périmètre, vus en live : « New york » seul après un tour français → réponse en anglais (le triage lit la langue du seul mot) ; rayon / tri distance / « 10th » / « Gare du Nord » sans ville → ticket #7.

🪤 **Pièges découverts** :
- **La pile `git stash` est commune aux worktrees** (`AgentB2C-mcp5`, `AgentB2C-mcp7` travaillés en parallèle) : un `stash pop` a appliqué le stash de la session #5 ici. Contrôle négatif = copier le fichier corrigé, `git show HEAD:<f> > <f>`, tester, recopier. Une entrée de stash de cette session reste dans la pile (contenu déjà commité, suppression refusée en mode auto) : `git stash drop` à faire à la main après vérification.
- `cat` est aliasé sur `bat` dans le shell de session : un `cat >> fichier <<EOF` n'écrit rien, utiliser `command cat`.
- Les fixtures de test dont le texte contredit les args (« 14h » dans le message, 9h dans `timeSlot`) cassent dès qu'un guard lit le texte : 2 alignées.

## ✅ 2026-10-06 (soir) — mcp-dayuse#7 : classe géographique (hôtel nommé, quartier, homonyme)

**Fait** (branche `fix/geo-location-class`, **empilée sur `fix/qa-oracle-facts-silent-fallbacks`** (MR #8) — merger celle-ci d'abord ; 1 commit par chantier ; gates : pytest **2 005 passés / 1 skippé**, ruff, mypy, guardrails **verts**). Ticket https://gitlab.com/dayuse/dayuse/mcp-dayuse/-/work_items/7. Chaque défaut a été reproduit en local avant le correctif (stack `main` :8100), puis revérifié sur une 2e stack (`PORT_OFFSET=30`, :8130-8132) branchée sur le MCP de branche (:8180). Décisions Mathias (2026-10-06) : MR MCP incluse ; rayon = règle du site ; hôtel ambigu → question ; introuvable → le dire + montrer la ville ; hôtel trouvé → l'hôtel + ses voisins, avec prix.

1. **MCP (mcp-dayuse, branche `feature/14707-distance-sort-tolerant-city`, ticket #3)** : `search_offers` accepte `sort: "distance"` (défaut `relevance` inchangé) ; `find_hotel_by_name` : `cityName` libellé ou slug, sans casse ni accents (`London` → `london`, `Paris` couvre `paris-10`), un seul candidat au nom exact n'est plus ambigu, `lat`/`lon` exposés. 777 tests verts.
2. **Rayon et tri du site** (`response_bridge.inject_landmark_radius`) : autour d'un quartier, d'un POI ou d'une adresse, le plus petit cercle parmi 2/5/10/20/30/50 km contenant 10 hôtels (compté sur le snapshot d'inventaire), puis tri par distance (`sort` envoyé au MCP, et cartes retriées côté feuille si le MCP ne le connaît pas encore). Les villes gardent 20 km et la pertinence. Live : Marais 0,4-0,6 km (avant 1,5-2,2 km, aucune carte dans le Marais), Gare du Nord 0,2-0,3 km.
3. **Hôtel nommé** (`hotel_search_agent/named_hotel.py`) : le `hotel_name` du triage part à la feuille (`query_params`) ; `cityName` envoyé en slug, une seule nouvelle tentative sans ville si introuvable (« Londres » ≠ `london`) ; un hôtel trouvé déclenche en code une recherche datée centrée sur lui, triée par distance : il est la 1re carte avec ses prix, ses voisins suivent, la synthèse commence par lui (angle `named`) ; sans offre ce jour-là, la réponse le dit d'abord. Plusieurs correspondances → question listant les candidats (le LLM ne peut plus en choisir un : 2e recherche sans ville nouvelle court-circuitée) ; la réponse (« celui de St Pauls », « le deuxième ») est résolue en code (`profile.named_candidates`, un tour). Live : « St Paul's Hotel à Londres demain » FR et EN → l'hôtel en 1re carte, 0,0 km, 130,62 €.
4. **Homonyme et langue** : la réponse à « quel Manhattan ? » complète le lieu au lieu de le remplacer (`profile.pending_place`, un tour : le message doit nommer exactement une des options) ; un quartier résolu par le géocodeur (`locality`/`neighborhood`) suit la règle du site ; un message fait de noms propres (« New York ») garde la langue de la conversation. Live : Manhattan → « New York » → Lower Manhattan 0,4-0,9 km, en français (avant : Fort Lee / Flushing 7-17 km, en anglais).
5. **Pagination** : jamais de page 2 sur une première recherche ni sur un hôtel nommé ; triage : nommer une destination n'est pas « d'autres options ». ⚠️ Non reproduit en live (3 essais), garde ajoutée sur la trace 550ddc54.
6. **Lieu célèbre en forme courte** : l'instruction demande le nom complet (« St Paul's » → « St Paul's Cathedral ») ; avant, le classement des POI prenait « St Paul's, Burdett Rd, E3 » (même ancre sur `main`). Live 3/3 sur la cathédrale, cartes à 0,2-0,7 km.
7. **Évalset** `evals/datasets/b2c-geo-class-2026-10-06.jsonl` (10 items) + évaluateur `first_hotel_name_contains`. Outillage : `MCP_B2C_URL_OVERRIDE` dans `run_local.sh` (stack annexe sur un autre MCP sans toucher `.env`).

**Non-régression** : pytest, ruff, mypy, guardrails verts. Rejeu des 58 items (geo-poi / occupancy / language-robustness / qa) fait UNE fois, **avant les 2 derniers correctifs**, contre la stack de Mathias (:8100, lancée à 10:38 donc SANS les commits de #8) : 107 → 102 vérifications vertes. Analyse des écarts, chaque item rejoué 3× sur les deux stacks : Champs-Élysées sans ville = vraie régression (la consigne « nom complet » faisait perdre « Paris » au modèle), corrigée par `fc5cbd9`, puis 3/3 ; Sagrada Família instable sur `main` (1/3), 3/3 sur la branche ; `lang-es-search-full` instable sur les deux stacks, et « por la tarde » relève du moment de la journée de #8, pas de #7 ; en faveur de la branche : `qa0930-lyon-*` (créneau, #8), `named-hotel-unknown`, `lang-typos-heavy`. **Le rejeu complet après les derniers correctifs (branche :8130 vs base `325faba` :8150) a été arrêté à la demande de Mathias** : il n'est pas local (OpenAI, Mapbox, Langfuse), c'est un coût. À refaire avant le merge, via `evals/datasets/*.jsonl`, avec l'en-tête `x-dayuse-synthetic: 1`.

**Reste** :
- **Déployer le MCP d'abord** : sans lui, `sort` est retiré par `schema_guard` (cartes triées sur la seule page reçue), `cityName` doit être le slug exact, et un hôtel trouvé reste une carte seule sans prix (pas de `lat`/`lon`). Puis rafraîchir `contracts/mcp_b2c_tools.json` (`scripts/refresh_mcp_contract.py`, l'humain le lance).
- Seed Langfuse : `scripts/langfuse_seed_datasets.py --only b2c-geo-class-2026-10-06`.
- Hors périmètre, à ticketer : une **ville** garde la pertinence sur 20 km (« Monaco » → Nice aéroport à 18 km en tête ; « New York » → banlieue 7-17 km) — le site a une page pour ces villes, son tri est à vérifier avant d'y toucher ; le résolveur choisit parfois seul un homonyme sans demander (« Springfield » → Virginie) ; un lieu célèbre inconnu du LLM sous forme courte reste exposé au POI homonyme (le classement Search Box prime le nom exact).

🪤 **Pièges découverts** :
- Le hook pre-commit refuse le type `test(...)` : utiliser `chore(evals)`.
- `cat` est un alias de `bat` (absent) dans le shell : `cat >> fichier` échoue en silence.
- Une stack `PORT_OFFSET=20` peut déjà tourner depuis le dépôt principal : vérifier `lsof -iTCP:8121` avant de lancer la sienne.
- Le triage lit « celui de … » comme une position (1) : les mots distinctifs doivent primer.
- **Rejouer les datasets n'est pas gratuit ni neutre** : chaque tour appelle OpenAI et Mapbox, et la stack locale exporte ses traces vers Langfuse (`langfuse tracing enabled`). Le script de rejeu repris de #8 n'envoyait PAS `x-dayuse-synthetic: 1` : les rejeux du 2026-10-06 (sessions `rg-*` / `fl-*`, ~16h30-17h40) sont dans Langfuse sans le tag synthétique. À exclure ou supprimer côté Langfuse (Fabien).
- Une consigne ajoutée au milieu d'un paragraphe de l'instruction de la feuille change l'extraction voisine : l'exemple « St Paul's » placé avant la règle « passe la ville » a fait perdre la ville sur un autre cas. Toujours rejouer les items geo-poi après une modification de l'instruction.
- « St Paul's » sous forme courte : le modèle donne le nom complet 4 fois sur 5 ; la 5e, le classement des POI prend encore « St Paul's, Burdett Rd » (le nom exact l'emporte). Résidu connu.

## ✅ 2026-10-06 — mcp-dayuse#8 : oracle sur les faits, replis observables, contrat MCP

**Fait** (branche `fix/qa-oracle-facts-silent-fallbacks`, 1 commit par chantier ; gates : pytest **1 928 passés / 1 skippé**, ruff, mypy, guardrails **verts**). Ticket https://gitlab.com/dayuse/dayuse/mcp-dayuse/-/work_items/8 (parent dayuse-com#14707). Chaque défaut a été **reproduit en local avant le correctif**, puis revérifié après, sur une 2e stack (`PORT_OFFSET=20`) face au MCP mcp-dayuse `main` local.

1. **Synthèse vide ou coupée** (trace 62207822) — `finish_reason=length` ou contenu vide = synthèse inutilisable (métrique `llm_call status=truncated|empty`, jamais servie, même à moitié). Le repli est la ligne de la feuille rendue présentable en code (`b2c_concierge/fallback_text.py`) : date en toutes lettres, réserves auto-widen / parking non filtrable / devise. `max_tokens` synthèse 1000 → 2000. Nouveau contrat `FALLBACK_SCORE_NAMES` → scores BOOLEAN `fallback_synthesis|mcp_error|named_hotel_not_found` à chaque tour.
2. **Date servie ≠ date demandée** (Côte d'Azur) — `b2c_concierge/requested_date.py` lit une date non ambiguë du message (7 langues ; jours de semaine, plages, « le 3 » → None) et la pose dans le profil AVANT la feuille : elle survit à une clarification. Guard **#16 `date_served`** : jour cherché ≠ jour demandé → la réponse le dit, le profil garde le jour demandé (bascule cutoff déjà annoncée exclue). Live : « Côte d'Azur le 10 octobre » → 2 clarifications → offres du 10 (avant : du 6).
3. **Replis silencieux** — `mcp_guard.classify_mcp_error` (not_found / rejected / failed) ; un argument refusé par le schéma (`-32602`) n'alimente plus le disjoncteur et répond « reformulez » au lieu de « réessayez » ; hôtel nommé introuvable puis recherche ville → annoncé en tête (sauf si l'hôtel est quand même dans les cartes : la recherche par nom est plus stricte que la recherche, cf. mcp-dayuse#3) ; introuvable sans texte de la feuille → réponse en code.
4. **Créneau** — règle du site (décision Mathias 2026-10-06, ticket #4) : l'offre CONTIENT la fenêtre, heures entières, minutes à l'heure la plus proche. Unique définition `b2c_common/timeslot.py` (`slot_covers_window`), utilisée par le filtre de la feuille (fenêtres à un seul bord comprises) et par le guard **#17 `window_match`** du concierge (carte non couvrante retirée ; aucune → toutes annoncées « les plus proches », phrase imposée en code). Plus jamais « exactement ». Le guard exige que les cartes soient annoncées « les plus proches » ; dire « aucune ne couvre » ne suffit pas (cas vu en live).
   **Moments de la journée (option B, décision Mathias 2026-10-06)** : « le matin / l'après-midi / en soirée » (7 langues, `b2c_common.timeslot.daypart_in`) sont lus en code et filtrent en SOUPLE. Une offre passe dès qu'une partie tombe dans la période (`slot_overlaps_daypart` : matin 6h–12h, après-midi 12h–18h, soirée 18h–23h ; une offre qui touche seulement la borne ne compte pas). C'est aussi la sémantique native du `timeSlot` MCP. Nouveau slot de profil `daypart`, exclusif avec un créneau horaire : l'un efface l'autre, et il est repris aux tours suivants. Une heure explicite dans le message l'emporte toujours (règle du site). Un `timeSlot` inventé par le LLM sans heure ni moment (« un hôtel demain » → 12h-23h) est retiré (`timeslot_sanitization`).
5. **Contrat MCP** — `contracts/mcp_b2c_tools.json` (8 inputSchema + catalogue `list_amenities`, pris le 2026-10-06), `scripts/refresh_mcp_contract.py`, `tests/test_mcp_contract.py` (args réels de la chaîne before-tool de la feuille validés contre le schéma ; ids d'équipement vs catalogue) ; la fausse session de `test_inline_tools.py` valide les 69 tests du concierge. En production : `schema_guard` (dernier before-tool) retire tout argument hors schéma publié — live : `currency` injecté → retiré, 5 hôtels au lieu d'une erreur.
6. **Évalset** `evals/datasets/b2c-qa-2026-09-30.jsonl` (10 items OBS6, cas tirés des tickets — choix Mathias, pas des traces) + évaluateurs déterministes `cards_cover_window` / `offers_on_date` / `no_iso_date_in_message`. Rejeu live : 16/19 sur `main`, 22/22 sur la branche.

**Non-régression** : rejeu des 58 items des datasets geo-poi / occupancy / language-robustness / qa contre `main` et la branche, mêmes évaluateurs : **108 → 116** vérifications vertes. Les cas qui basculent dans l'autre sens (Tour Eiffel, JFK, Sagrada Família, code-switching) échouent aléatoirement sur les DEUX stacks (rejoués 3× chacun) : géocodage, ticket mcp-dayuse#7.

**Reste** :
- **Score configs Langfuse** (Fabien) : `guard_date_served`, `guard_window_match`, `fallback_synthesis`, `fallback_mcp_error`, `fallback_named_hotel_not_found` émettent sans `config_id` tant que les configs n'existent pas dans l'instance (puis les ajouter à `_SCORE_CONFIG_IDS` et `score-configs.json`). Le score `degraded` CATÉGORIEL n'a pas été étendu exprès : sa config fige la liste des catégories.
- Seed Langfuse du nouveau dataset : `scripts/langfuse_seed_datasets.py --only b2c-qa-2026-09-30`.
- Hors périmètre, à ticketer : « Nice » seul → salutation en anglais (« nice ») ; « Je veux réserver au Grand Hôtel X à Lyon » → parcours réservation au lieu d'une recherche ; `total` et groupes OU d'équipements (MCP #1). Compteur et réserve parking dans la synthèse normale : faits le 2026-10-07 (bis).
- Bornes des moments de la journée (6-12 / 12-18 / 18-23) choisies par défaut : à valider par le produit (`DAYPART_HOURS`). `active_filters` n'expose pas encore le moment de la journée (pas de puce dans le widget).

🪤 **Pièges découverts** :
- **Inverser la règle du créneau rend nuisible ce qui était inoffensif** : un créneau inventé par le LLM passait sous « offre ⊆ fenêtre », il vide tout sous « fenêtre ⊆ offre ». Seul le rejeu avant/après des datasets l'a montré.
- Le MCP renvoie `HotelNotFoundError` pour « Pullman Lyon » alors que la recherche ville le renvoie : ne jamais annoncer « introuvable » sans regarder les cartes.
- `id` piscine **3001** : dans le groupe OU du serveur, absent de `list_amenities` — gardé, exception documentée dans le test de contrat (décision au ticket #4).
- Le hook readonly bloque toute commande Bash dont le TEXTE contient `. ./.env`, même dans un heredoc de doc : éditer ces fichiers avec Edit.

## ✅ 2026-09-29 — Redéploiement Railway de `07be07e` + procédure écrite dans `DEPLOY.md`

**Fait** : les 4 services redéployés depuis `main` propre (`07be07e`, pytest **1 786 passés / 1 skippé**) — `widget`/`concierge`/`hotel-search` étaient sur `451c7e6`, `faq` sur `7d41d41` (en retard via `libs/b2c_common`). Estampille `LANGFUSE_RELEASE=07be07e` posée avec `--skip-deploys` puis `railway up --detach` feuilles d'abord → 4 × `SUCCESS` (~10:04Z).

**Preuve prod** (widget `/v3/chat`, `x-dayuse-synthetic: 1`) : « affiche les prix dans la devise de l'hôtel » → acquitté comme devise, plus routé FAQ (#119) ; puis « Londres, Royaume-Uni, demain après-midi » dans la même session → 5 cartes `display_currency=GBP` (`GBP 90.00`…, liens `dayuse.co.uk` avec `?checkinDate=`). Contrôle : même recherche en session fraîche → « prix affichés en € sans conversion » (EUR par défaut, #118). Non prouvé en prod : la règle Booking Fees (#117).

**`DEPLOY.md` (neuf)** : la procédure n'existait qu'éparpillée dans ~10 blocs de ce fichier. Les deux snippets (preuve Python, statut `railway status --json`) ont été exécutés tels qu'écrits. **Convention d'estampille tranchée : AVANT `railway up`** (Railway fige les variables au déploiement, c'est ce qui fait porter le SHA aux traces du nouveau conteneur) ; le bloc du 2026-08-28 recommandait APRÈS — ça rend la variable juste mais le conteneur garde l'ancienne valeur jusqu'au déploiement suivant. En cas d'échec d'un `up`, remettre l'ancienne estampille.

🪤 **Observé, non investigué** : « un hôtel en day use à Londres demain après-midi » (sans pays) → clarification « plusieurs lieux portent ce nom » en 20,5 s au lieu d'une recherche. Même famille que Budapest→US ; pas vérifié si c'est nouveau.

## ✅ 2026-09-29 — Demande de devise classée `faq` : les cartes sont quand même repeintes

**Fait** (branche `fix/currency-request-routed-to-faq`, gates : pytest **1 786 passés / 1 skippé**, ruff, mypy, guardrails **verts**).

Constat en local (vrai LLM de triage) : « donne le prix en sgd », « je veux dans la monnaie de l'hotel », « affiche les prix en devise locale » sont classés `faq`. Le repaint n'acceptait que `details`/`ack` : le tour partait à la FAQ, qui répondait à tort « les prix sont déjà en SGD », cartes inchangées. Deux couches : (1) prompt de triage — voir les prix dans une devise = `details`, seule une question de PAIEMENT = `faq` ; (2) filet déterministe dans `agent.py` — une demande de devise classée `faq` repeint aussi, sauf si `triage.asks_policy(message)` (`_FAQ_RE` + `_PAYMENT_RE` : payer/pay/paie/accept, « pays » exclu). « je peux payer en HKD ? » garde sa route FAQ. Contrôle négatif fait (les 3 tests de repaint tombent sans le filet). Rejoué en local avec le vrai LLM : les deux formulations repeignent en SGD.

**Vérifié le même jour en local (MCP mcp-dayuse `main` sur :8080), remontées QA déjà corrigées le 2026-09-23** : « Voir tout » (lien du pays des hôtels, FR → `dayuse.fr/s/france`) ; « réservations closes » absente sur 6 recherches du jour avec résultats ; date jamais en ISO (format US gardé, décision Mathias, pas le format britannique demandé par la QA) ; `?checkinDate=` sur les liens des cartes ; Booking Fees — 20 hôtels réglés à `true` (NY, Miami, Singapour, Hong Kong) affichent `priceEuro`, les hôtels Paris réglés à `false` affichent `priceEuroWithBookingFees`.

🪤 **Pièges découverts** :
- **La préprod MCP est antérieure au 2026-09-25** : sans `hotelCurrency`/`hotelPrice`, les cartes restent en EUR sans erreur. Tester en local contre mcp-dayuse `main` (`npm run dev`, lit `.env.local`, port 8080, token = `MCP_AUTH_TOKEN` de `.env.local` à reporter dans `MCP_B2C_AUTH_TOKEN`).
- **Un redémarrage du MCP casse la feuille search** jusqu'au redémarrage des services (`search_offers` → `mcp_tool_error` en ~5 ms, session MCP périmée gardée par le `McpToolset`). Arrivera aussi à chaque redéploiement MCP en prod. **Non corrigé** (décision Mathias : plus tard).

**Reste** : lien tunnel direct quand l'utilisateur ÉCRIT son choix (« je prends le premier ») — la QA le conteste, décision produit à prendre ; synthèse « à 18-18 km du centre » quand toutes les distances sont égales (défaut mineur, non corrigé).

## ✅ 2026-09-25 — Devise d'affichage : EUR par défaut, devise de l'hôtel sur demande

**Fait** (branche `feat/hotel-currency-display`, **empilée sur `fix/booking-fees-display-price`** — merger celle-ci d'abord ; gates : pytest **1 738 passés / 1 skippé**, ruff, mypy, guardrails **verts**).

Règle produit (Mathias, 2026-09-25) : prix en EUR par défaut ; sur demande (« dans la devise de l'hôtel », ou le code de cette devise), cartes, panneau de formule, texte et prix barré passent dans la devise de l'hôtel, **pour toute la conversation** jusqu'au retour à l'euro, et les cartes déjà affichées sont **ré-affichées** (relance de la même recherche, `query_params.repeat_previous_search`). Toute autre devise → réponse déterministe 7 langues (« pas encore disponible, voici les 2 choix »), sans recherche. **Aucune conversion** : le vrai sujet multi-devises (taux MySQL `tbl_currency_rate`) est en pause, branche MCP supprimée.

Mécanique : la feuille pose sur chaque carte le prix de la MÊME offre en devise hôtel (`hotel_price`, `hotel_price_minor`, `hotel_currency_code`, `slot.hotel_original_price`) via `b2c_common.hotel_currency_price` (même règle Booking Fees que l'euro, décimales ISO) ; nouveau slot de triage `display_currency` (`EUR`/`HOTEL`/code ISO, pas d'appel LLM en plus) ; `profile.display_currency` (concierge-only, hors `leaf_profile_view`) ; `b2c_concierge/display_currency.py` décide et bascule (`apply_hotel_currency`) ; `price_eur_cents` reste en EUR pour le budget et le tri ; angles `discount`/`spread` calculés dans la devise affichée ; disclosure « EUR sans conversion » coupée en mode hôtel ; widget : `formatBackendPrice` (« HKD 805.00 » → « HK$805.00 ») dans le panneau de formule.

**Dépendance** : MR 28 de `mcp-dayuse` (champs `hotelCurrency`/`hotelPrice`/`hotelPriceWithBookingFees`/`originalHotelPrice`) déployée. Sans elle, les cartes n'ont pas de prix devise hôtel et restent en EUR, sans erreur.

**Non vérifié** : la reconnaissance réelle par le LLM de triage (« devise locale », « en dollars de Hong Kong »…) dans les 7 langues — les tests scriptent sa réponse. Rendu carte vérifié en Chrome headless (« dès HK$805 · HK$1600/nuit »).

**Code review `/code-review` (PR #118) — 7 constats, tous corrigés sauf un arbitré** : prix barré et % du panneau de formule en devise hôtel ; code ISO d'une NOUVELLE recherche comparé aux hôtels reçus (« Tokyo en yens » → devise hôtel, sinon message avec la devise des nouveaux hôtels) ; repaint seulement pour un message « devise seule » (détails nommés / comparaison / FAQ gardent leur route ; même devise demandée → « déjà affichés en … », sans recherche) ; widget : code ISO inconnu de la table affiché tel quel (« PLN 250 », plus jamais « €250 ») ; mention EUR gardée pour une carte restée en EUR ; puce budget triée sur `price_eur_cents`. 🪤 **Arbitré par Mathias (option a)** : un repaint après « autres options » repart de la page 1 (garder le curseur ne marche pas — la feuille masquerait les hôtels affichés ; ré-afficher sans recherche exigerait de stocker les cartes complètes en Redis).

**2e review (sur les corrections seules) — 3 effets de bord corrigés** : « déjà affichés » décidé sur les cartes À L'ÉCRAN (`shortlist_display_mode`), pas sur la préférence sauvegardée (qu'un tour détails ou une recherche indisponible peut poser sans repeindre) ; en mode hôtel, la phrase générique « prix en euros » n'est ajoutée que si AUCUNE carte n'a basculé (liste mixte : le € de la carte suffit) ; une devise non disponible demandée dans une recherche sans résultats (« un hôtel en zlotys », la feuille demande la ville) reçoit quand même la réponse. Contrôle négatif fait (les 3 tests tombent sans les correctifs). Commentaires redondants retirés. Gates : pytest **1 747 passés / 1 skippé**.

## ✅ 2026-09-23 — Booking Fees : le prix affiché suit `showPricesWithoutBookingFees` (QA n°6)

**Fait** (branche `fix/booking-fees-display-price`, gates : pytest **1 715 passés / 1 skippé**, ruff, mypy, guardrails **verts**). La QA n°6 avait été classée « pas un chantier agent » : **faux**, c'est l'agent qui affichait `priceEuro` (sans frais) en dur, alors que MCP filtre le budget et trie sur `priceEuroWithBookingFees`.

Règle produit (Mathias, 2026-09-23) : `showPricesWithoutBookingFees` (booléen, racine du document hôtel ES) `true` → `priceEuro`, sinon → `priceEuroWithBookingFees`. Nouveau `b2c_common.display_price_euro(offer, hotel)` — repli `priceEuro` si le prix avec frais manque, seul un vrai `True` compte. Appliqué partout où un prix est choisi ou affiché : carte + choix de l'offre la moins chère (`response_bridge.normalize_hotel`/`_best_offer`), fiche détails/compare (`inline_tools._normalize_hotel_for_display`), offre la moins chère et prix cité à la réservation (`_best_offer`, `generate_booking_link`), lignes du panneau de formule (`_rate_plan_view`/`_day_rate_plans`). Le moins cher est désormais calculé sur le prix AFFICHÉ (test : 104 € avec frais bat 106 €, même si l'autre offre est moins chère sans frais). Non touché : le repli de formatage `facade.normalize_hotels` (chemin théorique, les cartes arrivent déjà avec `price`) et le tarif nuit barré.

**Dépendance MCP** : le drapeau n'arrive que si MCP l'expose — branche `fix/show-prices-without-booking-fees` sur `mcp-dayuse` (4 couches : schéma zod, `hotelProps`, entité `Hotel`, `mapHotelIdentity` → présent dans les 6 sorties de tools). **Déployer MCP d'abord** : sans lui, l'agent affiche le prix avec frais pour tous les hôtels, y compris ceux réglés à `true` (erreur dans le sens prudent, jamais un prix trop bas).

## ✅ 2026-09-23 — 5 remontées QA corrigées (date, « closes », « Voir tout », CTA carte, checkinDate)

**Fait** (branche `fix/qa-widget-2026-09-23`, gates locaux : pytest **1 736 passés / 1 skippé**, ruff, mypy, guardrails **verts**) :

1. **Date ISO dans le texte** (QA n°2 du 2026-09-08, « Pour demain (2026-09-24) ») — cause : `ground_truth.date_context_block` collait l'ISO dans le prompt avec « State that date », le modèle le recopiait. Nouveau `b2c_concierge/date_format.py` (7 langues, tables fixes, zéro dépendance locale) : le prompt reçoit « jeudi 24 septembre 2026 », et `humanize_iso_dates` réécrit en code toute date ISO restante après le LLM (URLs intactes). Anglais au format US, année toujours affichée (choix validés par Mathias).
2. **« Les réservations du jour sont closes » avec 4 cartes réservables à l'écran** (prod, Singapour 18 h locale) — cause : `response_bridge._date_fallback_line` ajoutait la ligne « closes » à TOUTE recherche du jour, résultats ou pas ; le LLM la reprenait fidèlement. Désormais exige résultat vide **et** `cutoff_closed` (même règle que `date_context_block` côté concierge). Effet voulu : un pool vide (Tokyo) ne prétend plus non plus à une fenêtre fermée. Contrôle négatif fait (les 2 tests tombent sur l'ancien code). **Très probablement l'explication de la QA n°1** du 2026-09-08.
3. **« Voir tout » → `/s/united-states` sur une recherche Singapour** — cause : `getMarketFallbackLink` faisait primer le marché d'entrée (`marketContext`, US par défaut sur `widget-production`) sur celui des résultats, alors que le lien du bas du carrousel était déjà basé sur les hôtels. Nouveau `markets.getResultsMarketMeta(hotels)` + `responses.resultsSeeAllLinkHtml`, câblés aux 4 constructeurs du bandeau (dont le streaming). Marché sans page de browse → pas de lien. **Provisoire assumé** : le bon produit serait que « Voir tout » ouvre la RECHERCHE (ville + date) — bloqué faute du format d'URL réel de recherche Dayuse (jamais vérifié, interdit de le deviner). Mathias a arbitré : garder ce correctif seul pour l'instant.
4. **Carte : un seul bouton** (décision produit) — « Choisir cet hôtel » est désormais un `<a>` vers la fiche hôtel (même tracking `data-track-hotel-click`), le lien « Voir la fiche de l'hôtel » et son CSS `.see-hotel-link` sont supprimés, plus de booking card au clic. Pas d'URL → pas de bouton (règle UX6). La booking card reste servie quand l'utilisateur ÉCRIT son choix (« je prends le H4 ») — voulu. 🪤 Le handler `pick-hotel` de `ui/messages.js` n'a plus d'émetteur : laissé en place pour ne pas élargir le diff.
5. **Date non appliquée sur la fiche hôtel** (QA n°4) — `?checkinDate=YYYY-MM-DD` (format fourni par le produit) via `b2c_common.with_checkin_date`, appliqué dans `emit_search_datapart` (cartes de la feuille) et `inline_tools.get_hotel_details`. Seulement une date donnée par l'utilisateur (label frais ou `profile_in.date` reporté), plus le swap cutoff J+1 (validé par Mathias : la carte montre le prix de demain). Tour silencieux ou date reportée planchée à aujourd'hui → lien nu. `sanitizeDayuseUrl` et `appendAmplitudeIdToUrl` conservent le paramètre (vérifié).

**Non vérifié** : aucun rejeu avec le vrai LLM ni sur le vrai site (le rendu de la carte a été vérifié en Chrome headless sur les vrais modules du widget, pas dans un tour complet).

**Laissé de côté par décision de Mathias** : changement de devise à la demande (bloqué par l'arbitrage Fabien « pas de FX côté AgentB2C » ; `hotelPrice` ne couvrirait de toute façon que la devise de l'hôtel, pas une devise choisie) ; message « Je n'arrive pas à joindre la recherche » sur « refais la requête en changeant la currency » (cause non établie, trace Langfuse non consultée).

**Suite immédiate (autre branche)** — ✅ livrée, voir le bloc Booking Fees ci-dessus : Booking Fees (QA n°6, reclassée — c'est bien un défaut agent). L'agent affiche `priceEuro` en dur à 7 endroits alors que MCP filtre et trie sur `priceEuroWithBookingFees`. Règle produit : `showPricesWithoutBookingFees` (booléen racine du document hôtel ES, déjà indexé, au même niveau que `globalAverageRating`) `true` → `priceEuro`, sinon → `priceEuroWithBookingFees` (repli `priceEuro` si absent). Côté MCP : le champ est jeté par `HotelDocumentSchema` (zod strip) — 4 ajouts à faire, exposé via `mapHotelIdentity`.

## ✅ 2026-09-14 — 2e vague de pourrissement calendaire : 1 test immunisé, et la preuve qu'il n'en reste aucun autre

**Fait.** `test_resolve_search_date_marks_a_carried_over_future_date_as_not_today` (`agents/hotel_search_agent/tests/test_datetime_resolver.py`) codait en dur `2026-09-09` comme date *future* : passée cette date, `_usable_carried_date` plancher correctement la date périmée sur aujourd'hui et `same_day` bascule à `True` — le test cessait de tester le carry-over. Rendu **relatif à l'horloge** (`date.today() + timedelta(days=7)`), comme ses 3 voisins de la PR #71 (lignes 290, 311, 381) qui appliquaient déjà ce motif ; ce test avait été oublié dans cette vague.

**⚠️ Correction d'une consigne fausse laissée le 2026-09-09 ci-dessous** : « le correctif immunisant est de passer une date de référence explicite ». **Ça ne marche pas ici.** Le motif `_TODAY = date(...)` (ligne 175) ne vaut que pour `resolve_date_label(label, today)`, un helper pur qui *prend* `today` en argument. `resolve_search_date` n'a pas ce paramètre : il dérive today en interne via `reference_today(profile_in)`. Le seul motif immunisant pour cette fonction est donc le calcul relatif à l'horloge. Les deux motifs coexistent dans le fichier, choisir selon que la fonction testée accepte ou non un `today` injecté.

**Balayage de TOUTE la suite, empirique et non par grep.** 327 littéraux de date sur 41 fichiers de test : les lire un par un ne dit pas lesquels pourrissent (l'immense majorité sont des *fixtures* — payloads MCP, dumps de trace — jamais comparées à l'horloge). Méthode retenue : un plugin pytest chargé en `-p` **décale l'horloge de N jours pour la source ET pour les tests**, si bien qu'un test relatif à l'horloge reste vert et que seul un test épinglé à un littéral tombe. Suite complète rejouée à **+1, +3, +7, +30, +111, +180, +365, +500, +1000 et +2000 jours** : **1 707 passés, 1 skippé à chaque décalage**. Contrôle négatif exécuté (sinon le vert ne prouve rien) : en réintroduisant un littéral `2026-12-01` — encore futur aujourd'hui — le test **passe à +0 et tombe à +400 j**, donc le harnais détecte bien cette classe. **Conclusion : après ce correctif, plus aucun test de la suite ne pourrit par le calendrier.**

**Pourquoi les autres littéraux ne pourrissent pas** : `tests/test_eval_hardening.py` injecte une horloge explicite (`clock="2026-07-10T10:00:00Z"`) ; `test_market_table_drift.py` et consorts n'ont que des dates en commentaire/provenance ; les payloads de `test_inline_tools.py` (78 littéraux) ne sont jamais confrontés à today. Côté non-pytest : `evalset/` ne contient **qu'une** date (`"generated": "2026-07-15"`, métadonnée de provenance) et **aucun** scénario ne formule de date — rien à immuniser. Il n'existe que **2 lectures d'horloge** dans le code applicatif : `datetime_resolver.reference_today` et `agent.py:283` (`inject_today_before_model`).

**Suite (même jour, PR #115) — le garde est commité, une 3e vague est désormais impossible en silence.** `tests/timeshift_plugin.py` (le plugin) + `tests/test_calendar_rot.py` (UN test qui rejoue toute la suite dans un sous-processus à +400 j et échoue en nommant le test fautif). **Pas de nouveau job CI** : la CI est morte depuis le 2026-07-23 (facturation Actions — tous les runs échouent en 4-5 s sans exécuter la moindre étape, cf. [`CHANTIERS.md`]), un job y serait du poids mort ; le garde étant DANS la suite, le job `pytest` existant le récupérera tout seul le jour où la facturation repart. Contrôle négatif rejoué sur le garde commité : littéral `2026-12-01` réintroduit → `pytest -q` reste vert sur le fichier concerné (le pourrissement est invisible aujourd'hui) mais `test_calendar_rot` tombe en citant `test_resolve_search_date_marks_a_carried_over_future_date_as_not_today`. **Coût : la suite passe de ~12 s à ~23 s** (documenté dans `CLAUDE.md`). Recursion évitée par `CALENDAR_ROT_CHILD=1`, que le fils voit et sur lequel il se skippe.

Gates locaux : pytest **1 707 passés / 1 skippé**, ruff **OK**, mypy **48 fichiers, 0 erreur**, `dayuse_guardrails.sh` **OK**.
