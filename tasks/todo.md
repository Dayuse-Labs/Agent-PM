# S-CX6 — « aucun résultat » l'après-midi = cutoff de réservation du jour (2026-07-27)

**Symptôme Fabien** : « aucun résultat qui remonte alors que je devrais en avoir »
(screenshot Gare de Lyon → 0 offre, chips budget/zone/filtre).

**Diagnostic mesuré (live, MCP staging + démo Railway déployée)** : ce n'est PAS un
bug de plomberie. Chaque offre porte un `cutoffDeadlineUtc` **le jour du séjour**
lui-même : sur 63 offres D+1 Gare de Lyon, cutoffs 05h(3) 06h(7) 08h(16) 09h(18)
10h(1) 12h(2) 14h(8) 15h(7) 16h(1) Paris — **le plus tardif = 16h**. Fabien testait
à 17h20 → `date = today` (le défaut quand l'utilisateur ne dit pas de date) est
structurellement mort. Vérifié en marchant les **11 pages** du pool de 518 hôtels à
17h50 : `n=0` sur chaque page jusqu'à `has_more=False`. Contre-épreuve même seconde :
New York 3 résultats, Los Angeles 5, Paris 0 (ils sont encore le matin).
Rejoué sur le démo déployé, une session : « today » → 0 hôtel ; « et demain ? » →
**5 hôtels, 54 € → 72 €**, mêmes coordonnées.

**3 défauts réels** : (1) la réponse ne nomme JAMAIS la date cherchée ; (2) les chips
de récupération sont en dur (`profile.py:100`) et aucune ne traite la cause ;
(3) `total=518, results=[]` est la signature lisible « pool existant, tout passé
cutoff » (vs `total=0` = zéro inventaire, cf. Tokyo) et la feuille ne lit que
`results`, jamais `total`.

**Décision Fabien (AskUserQuestion)** : sonder J+1 sur un 0 réel + réponse datée.
Le landmark « gare de lyon » non résolu (La Garde / Gary / Rueil) = **session à part**.

- [x] 1. Feuille — `probe_next_day_after_tool`, nouveau `after_tool_callback`
      **async** placé AVANT `capture_after_tool` (jamais une modif de ce dernier :
      ~40 tests l'appellent en synchrone, et un retour truthy casse la chaîne).
      Blocker du HANDOFF levé : ADK `functions.py:625` fait
      `if inspect.isawaitable(...): await ...` sur une liste mixte — vérifié sur
      l'ADK installé. Ne tire QUE sur la signature exacte (same-day + `total>0` +
      `results` vide) ; `tool.run_async` ne re-déclenche pas les callbacks (zéro
      récursion) ; try/except total (un probe ne casse jamais un tour).
- [x] 2. Feuille — `capture_after_tool` consomme le payload J+1 stashé quand sa
      propre normalisation donne 0, et bascule la date portée (provenance
      `cutoff_fallback`) pour qu'un tour suivant ne re-meure pas sur aujourd'hui.
- [x] 3. Feuille — `search_date` sur le DataPart (`date` / `same_day` /
      `cutoff_fallback_from`) : c'est ce qui permet de NOMMER la date, de choisir
      les chips et de rendre la divulgation obligatoire. Texte d'outcome + 
      `skip_final_generation` alignés (même ligne code-owned).
- [x] 4. Concierge — bloc ground-truth : divulgation OBLIGATOIRE « ces offres sont
      pour <date>, PAS aujourd'hui » ; note écran-vide qui nomme la date.
- [x] 5. Concierge — chips date-first sur un dead-end same-day
      (`voir demain` / `après-demain` / `élargir la zone`). Les labels retombent
      sur `_DATE_MENTION_RE` déjà en place → un clic relance la recherche datée,
      zéro plomberie neuve.
- [x] 6. Tests — probe (tire / ne tire pas), consommation, texte, DataPart, chips,
      ground-truth + un test de soudure feuille→DataPart→façade.
- [x] 7. Vérif LIVE sur la stack locale (il est >16h Paris : la condition du
      dead-end est réunie pour de vrai) + `smoke_e2e`.

## Review S-CX6 (fin de session)

**7/7 fait.** Vérifié LIVE sur la stack locale à 18h20 Paris (la condition du
dead-end était réunie pour de vrai, pas simulée) :

| tour | avant | après |
|---|---|---|
| « hotel à la gare de lyon à Paris » | 0 hôtel, chips budget/zone/filtre | **5 hôtels 54→72 €**, « Les réservations pour aujourd'hui (2026-07-27) sont closes, voici les offres pour demain » |
| « le moins cher, je veux réserver » | — | carte + lien `checkinDate=2026-07-28` avec l'`offerId` de l'offre vue |
| « un hôtel à Paris le 5 août » | 5 hôtels | **inchangé** (5 hôtels, provenance `absolute`, aucun probe) |

Coût mesuré : `cutoff_fallback_probe status=ok ms=569 found=1` — UN appel MCP en
plus, uniquement sur le dead-end ; tour feuille total 6,2 s (budget orchestrateur
10 s). `smoke_e2e` défaut / `--contract` / `--booking` : **PASS**.

**Défaut d'honnêteté attrapé en cours de route (avant commit)** : la première
version déduisait « les réservations d'aujourd'hui sont closes » de `same_day`
seul. Or un 0 same-day sur un pool VIDE (Tokyo, `total=0`) n'est pas une fenêtre
fermée, c'est un marché sans inventaire — le message aurait affirmé une cause que
la donnée n'établit pas. La feuille ne pose donc `cutoff_closed` que quand des
hôtels ont matché ET qu'aucun n'était réservable ; sinon la récupération générique
reste en place. Verrouillé par 2 tests (feuille + bloc ground-truth).

**Non couvert en live, couvert par tests seulement** : le cas « aujourd'hui fermé
ET demain vide aussi » (→ chips date). Paris a de l'inventaire demain, donc le cas
n'était pas reproductible live sans fabriquer un marché.

**Reste (hors scope, décidé avec Fabien)** : « gare de lyon » n'est pas résolu
comme landmark parisien — sur mon replay du démo déployé, le tour 1 a proposé
*La Garde (Lyon)* / *Gary (Illinois)* / *Gare (Rueil-Malmaison)* au lieu de Paris.
Session à part (famille du bug inventory-tier du resolver).

# S-CX5 — panier & remise du lien (session live de Fabien, 2026-07-27) — 10/12 FAIT

Trois symptômes rapportés (2 screenshots, session Paris/fr). Diagnostic par lecture
de code + contrat MCP_B2C (repo sœur). Design du point 3 : artefact publié
(3 propositions de carte + comparaison de flow + décisions).

## Constat 1 — « le moins cher » remonte des hôtels PLUS chers

Écran 1 : €54 / €58 / €70. Message « ok je veux booké le moins cher ».
Écran 2 : €81 / €87 / €112, texte « La moins chère est : ». Trois causes
indépendantes, chacune suffisante :

- **RC1 — l'exclusion de pagination s'applique à TOUTES les recherches.**
  `response_bridge.capture_after_tool` passe `shown_hotel_ids` en `exclude_ids`
  dès qu'il est non vide (L614-620), alors que sa propre docstring le décrit
  comme le filet de sécurité du « other options ». Les 5 hôtels les moins chers
  venaient d'être affichés → retirés de la 2e recherche → l'utilisateur reçoit
  les rangs 6-10 du même classement, mécaniquement plus chers.
- **RC2 — aucun tri prix n'existe.** `search_offers` n'a aucun paramètre de tri
  et le classement serveur est `availability .30 / quality .25 / commission .20 /
  rpmV2 .15 / tier .10` (`relevance-scorer.ts`) — le prix n'y entre pas. « Le moins
  cher » n'est pas une capacité aujourd'hui, juste une recherche de plus.
- **RC3 — rien ne vérifie le superlatif.** La synthèse écrit « la moins chère est »
  sans qu'aucun guard ne confronte l'affirmation aux prix des cartes du tour
  (contrairement à `amenity_guard` et `link_guard`).

- [x] 1. `capture_after_tool` : n'exclure `shown_hotel_ids` **que** sur un tour de
      pagination (`search_cursor > 0`) + `reset_search_cursor` sur toute
      recherche non-pagination (le curseur ne se remettait à 0 que sur un
      changement de ville). Le test qui verrouillait le comportement bogué a été
      corrigé, 2 tests de non-régression ajoutés.
- [x] 2. Intention prix : **le triage LLM comprend** (champ `pick`, enum fermée
      validée en code, 0 appel LLM en plus — le triage tourne déjà), **le code
      décide** (`select_cheapest_hotel`, ne lit jamais le message). Regex
      reléguée en `fallback_pick` (chemin LLM-down uniquement, comme
      `fallback_family`). Correction d'une récidive — cf. `lessons.md`.
      Vérifié live : LLM 8/8 sur des formulations où la regex se trompait 4 fois.
- [ ] 3. **NON FAIT (reste)** — vraie recherche « les moins chers » SANS shortlist
      (1er tour) : trier la page par prix côté code avant la coupe top-5, avec
      une formulation honnête (« les moins chers parmi les N trouvés », jamais
      « le moins cher de Paris » — le pool est une fenêtre de pertinence, pas le
      marché). `size` : re-probe live obligatoire (falaise à 16, scx3c).
- [ ] 4. **NON FAIT (reste)** — guard n°14 (prix) : un superlatif prix dans la
      synthèse vérifié contre les cartes du tour. Risque réduit maintenant que
      l'ordre est correct, mais pas nul : le modèle peut encore dire « le moins
      cher de Paris » là où la vérité est « le moins cher des 5 trouvés ».

## Constat 2 — le lien réserve la MAUVAISE offre (P0, non signalé par Fabien)

Carte affichée : €87, 11:00–19:00, **demain**. Lien généré : €90, 17:00–23:00,
`checkinDate=2026-07-27` (**aujourd'hui**). Cause : `inline_tools._quote_fresh_offer`
appelle `get_hotel_details` **sans la date de session** (le paramètre `date` existe
pourtant, cf. `get-hotel-details-tool.ts`) puis prend `offers[0]` — pas l'offre vue.

- [x] 5. Passer `profile.date` à `get_hotel_details` dans le chemin booking
      (branche `scx5-booking-offer-identity`). **Vérifié live** : `date=` scope
      bien au jour demandé (3 offres au lieu de 94 sur 32 jours).
- [x] 6. Identité de l'offre sur la carte (`offer_id` = `ratePlanUuid`,
      `offer_date`) côté feuille ET inline, portée par `record_search_shortlist`
      avec prix + créneau affichés. Le devis réutilise l'offre vue **sans
      round-trip** ; fallback (hôtel hors shortlist) = lookup daté + offre la
      moins chère **du jour** (jamais le minimum global : un `get_hotel_details`
      non scopé renvoie ~90 offres sur un mois, probé live).
- [x] 7. Seam test bout-en-bout `tests/test_leaf_concierge_seam.py` : carte
      affichée == arguments du lien. **Vérifié qu'il échoue sans le fix**
      (`2026-07-27 != 2026-07-28`).

## Constat 3 — flow de réservation trop long + lien brut

4 tours pour un hôtel déjà désigné, puis une URL de 250 caractères en texte.

- [x] 8. Ordinal dans une phrase : c'est le triage qui comprend
      (`pick: "position"` + `pick_position`), le code qui résout
      (`select_hotel_by_position`). « ok pour la première » ne dead-end plus.
- [x] 9. `booking_card` émis dans `/v3/chat` (+ frame SSE `booking_card`),
      construit depuis l'offre dont le lien est issu (carte et lien ne peuvent
      pas diverger). Nouvelle clé `hotel_picks` pour les boutons.
- [x] 10. Carte récap (design B) : renderer + CSS dans
      `web/vendor/static/js/chat`, strings dans les 7 locales `i18n.js`.
      **Seul endroit d'où part un lien tunnel** côté widget.
- [x] 11. **Boutons de choix d'hôtel** (remplace l'ancien design C, écarté par
      Fabien : pas de deep link tunnel depuis le carrousel, cartes de résultat
      INCHANGÉES). Pills famille `.chip` avec traitement renforcé (13px/700,
      bordure 1,5px, prix en pastille tabulaire), copie = **nom + prix**,
      triées du moins cher au plus cher. Affichées quand **ville + date résolues
      OU intention de réservation** détectée. Layout **L1 choisi par Fabien**.
      Clic → label en message + `hotel_id` dans le body (résolution par id,
      jamais par le texte).
- [x] 12. Tap sur un bouton → **directement la carte B**, aucun tour
      « vous confirmez ? » (décidé). R9 conservé : le clic sur le CTA de la
      carte EST la confirmation explicite. Résolution par `hotel_id`, jamais
      par parsing du label envoyé dans la conversation.

## Vérification (non négociable)

- Probe live AVANT/APRÈS sur le même marché pour tout changement d'argument envoyé
  à MCP (leçon scx3c : un test offline ne voit pas le serveur renvoyer une autre page).
- Rejouer la session exacte de Fabien (Paris, demain, « le moins cher »,
  « ok pour la première ») et comparer.
- `pytest -q` + ruff + mypy + guardrails verts, smoke e2e.

## Décisions prises par Fabien (2026-07-27)

1. Le clic vaut la confirmation R9 → **oui**, plus de tour « vous confirmez ? ».
2. Directement la carte B (pas d'étape A).
3. Layout **L1** (boutons de choix d'abord, chips d'affinage en dessous, muets).
4. Copie des boutons = **nom + prix**, triés du moins cher au plus cher, **sans
   badge « le moins cher »** (ce serait une affirmation, donc un guard à écrire).
5. Déclencheur des boutons = ville + date résolues **OU** intention de réservation.
6. Clic → message = le label, résolution = `hotel_id`.

## À REVOIR en review (changement d'invariant)

**R9 / guard #12 redéfini** : un lien exige toujours un flag de confirmation
explicite et code-owned dans l'état du tour, mais ce flag a maintenant 2 formes :
(a) devis en attente + « oui » (inchangé), (b) une SÉLECTION résolue sur un tour
classé booking. Rien n'est réservé dans les deux cas — le lien ouvre le tunnel,
le paiement s'y fait. Docstrings + tests mis à jour ; si tu veux restreindre (b)
aux seuls clics de bouton (et pas au texte « réserve le moins cher »), c'est une
condition d'une ligne.

---

# S-G12 — hotel page URLs depuis le slug ES (branche `sg12-hotel-page-urls`, 2026-07-24)

Root cause (diagnostiqué avec Fabien) : AUCUN code ne construit d'URL de page
hôtel — le LLM de synthèse les invente en slugifiant le nom affiché (mauvais
domaine `.com`, « aéroport » → `a-roport`, « Eurohotel » sans tiret). Le vrai
slug ES arrive dans le payload MCP (`slug`, probé live 2026-07-23) et est jeté
par `normalize_hotel`.

- [x] 1. `libs/b2c_common/b2c_common/hotel_urls.py` — `build_hotel_page_url(slug, country_code, country_name)` :
      tables marché (host par pays destination + country path-slug) portées
      d'agent-usa `hotel_urls.py`, mapping countryName→ISO, validation stricte
      du slug, `None` si non mappable (omission honnête, jamais d'URL devinée)
- [x] 2. Feuille `normalize_hotel` (`response_bridge.py`) : garder `url`
      construite depuis le slug ES sur la carte
- [x] 3. Concierge `_normalize_hotel_for_display` (`inline_tools.py`) : idem,
      défensif (shape `get_hotel_details`/`find_hotel_by_name` non re-probée)
- [x] 4. `ground_truth.py` : `url` sur chaque ligne hôtel + règle header
      « copy EXACTLY the url listed, never construct »
- [x] 5. Guard n°13 `link_guard.py` (déterministe, 0 retry) : toute URL
      `dayuse*/hotels/...` de la synthèse absente du set autorisé est retirée
      (lien markdown → label conservé) ; câblé en fin de
      `_synthesize_with_guards` ; métrique count-only (RGPD)
- [x] 6. Tests : builder b2c_common (repros prod verrouillés), `url`
      response_bridge, ligne ground_truth, link_guard (12 cas), display inline
- [x] 7. ruff + mypy + pytest verts ; HANDOFF.md ; commit + MR (review Fabien)

## Review S-G12

5 changements, tous localisés : 1 module partagé neuf (`hotel_urls.py`, ~120
lignes dont ~60 de tables), 2 insertions de 8 lignes (carte feuille + carte
inline), 2 lignes ground_truth + règle header, 1 guard neuf (~85 lignes) câblé
en 12 lignes dans `agent.py`. +29 tests (921 passed). Évidence : seam
in-process payload→carte→ground-truth→guard OK ; les 2 URLs des repros de
Fabien répondent HTTP 200 live, un slug bidon 404. Piège documenté : pas de
`countryCode` dans search_offers → mapping countryName anglais→ISO, marché non
mappé = pas d'URL. E2E LLM live non couru (stack down) — à vérifier au
prochain smoke.

---

# S-G10 — fixes issus de l'audit S-G9 (branche `sg10-geo-fixes`, 2026-07-23)

Périmètre approuvé par Fabien : 4 fixes + tests + re-vérification live.

- [x] **Fix 1 (P0) — `distance_origin` niché dans `profile_delta`** (`response_bridge.py::emit_search_datapart`)
  - [x] Nester le dict dans `profile_delta` ; corriger le test feuille (assertion top-level → nichée)
  - [x] Test de soudure côté concierge (`tests/test_leaf_concierge_seam.py` — emit réel → `apply_profile_delta` → `build_active_filters`)
  - [x] Corriger le type vestige `profile.py` (`str | None` → `dict[str, Any] | None`) + tests concierge qui passaient une string
- [x] **Fix 2 (P0) — Gate 1 : tier inventaire gamé par micro-homonymes** (`geo_resolver.py`)
  - [x] Le tier quasi-dur exige `inventory >= 3` (`_MIN_TIER_INVENTORY`) ; en dessous, inventaire = poids soft seulement
  - [x] Tests nommés : Budapest HU vs GA (inv=1) → clarify ; La Défense/Al Aïn ; gros marchés (inv≥3) inchangés
- [x] **Fix 3 (P0-bis) — fallback `language` Mapbox** (`geocode_tool.py` + injection `language_hint`)
  - [x] Injecté depuis `profile_in.language`, utilisé SEULEMENT pour le param Mapbox `language` — test verrouille que le prior pays (`_locale_country`) n'est jamais nourri par le triage
- [x] **Fix 4 (P1) — filet concierge** (`agent.py`) : dégrade seulement si `leaf_text is None` ET `response` vide ; double échec → template dégradé, jamais de message vide
- [x] **Fix 5 (P1) — exonymes echo-guard** (`geo_guards.py`) : table Wien/Vienna + 15 paires (« vienne » exclu exprès — vraie ville FR)
- [x] **Fix 6 (découvert au probe) — clarify → tier-2 Search-Box** (`geocode_tool.py`) : un clarify avec zone nommée tente d'abord le POI Search-Box (echo-validé) avant de poser la question
- [x] **DoD** : 872 passed (+14) · ruff OK · mypy 38 fichiers OK · guardrails OK (1 échec préexistant `test_llm_meter_usage`, hors zone, documenté)
- [x] **Live (gpt-5.2)** : geo-budapest → **PASS 2/2** (`country_code=HU`, le POI « Keleti station » désambiguïse) ; geo-la-defense → plus jamais AE 2/2 (clarify honnête) ; `distance_origin` présent sur tous les tours de recherche ; `eval_ranking.py` → **2 échantillons scorés** (precision@5=0.4, NDCG@5=0.27 — pipeline débloquée, pas un baseline)
- [x] HANDOFF.md (bloc daté) + commit + MR (review Fabien = gate, pas de merge)

## Review S-G10 (commit 1 — fixes audit)
6 changements, tous petits et localisés : 2 fichiers feuille cœur (`geo_resolver.py` ~10 lignes, `geocode_tool.py` ~30), 2 guards (`geo_guards.py` table + 3 lignes, `response_bridge.py` 4 lignes), concierge (`agent.py` 10 lignes, `profile.py` 1 ligne de type). 14 tests neufs, dont 2 cas d'échec S-G9 nommés en régression et 1 test de soudure cross-package qui manquait structurellement.

# S-G10 bis — décisions Fabien D1-a/D2-a/D3-a + arbitrages D5/D6/D7 (même branche, commit 2)

- [x] **D1-a — fixtures GPS** : `native_context.geolocation` → `client_geo_context.device.{latitude,longitude,permission:"granted"}` (2 cas prod_wounds) ; runner forwarde `client_geo_context` + `_resolve_origin` lit les 2 formes
- [x] **D1 follow-up (découvert live)** : la feuille n'avait AUCUN chemin de recherche GPS-only — `geocode_location` résout désormais sur le fix GPS du profil quand rien n'est géocodable (jamais quand une zone/landmark est nommée — Gate 3) ; vérifié live : Detroit « near me » → 4 hôtels, `distance_origin.type="gps"`
- [x] **D2-a — zone vs city** : nouveau type d'assertion `filter_place` (zone OU city OU resolved_city) dans le runner + 9 assertions migrées ; `filter_equals` accepte un dict structuré (`date_reference`) contre le token littéral via `expression` ; `check_zone_change` S-G8 accepte le déplacement en `city` ; + règle nom-exact du resolver (« Fort Lauderdale » tapé exactement ne clarifie plus contre « Lauderdale, MN ») — vérifié live : `carry_same_time_0` et `zone_change_0` **PASSENT** (0/3 avant)
- [x] **D3-a — `requires_clarification` minimal non-bloquant** : chaîne feuille (capture geocode_ambiguous → DataPart flag + question déterministe) → marker concierge → façade ; vérifié live : la-defense → `requires_clarification: true`, `outcome_counts.safe_clarification: 1` (structurellement 0 avant)
- [x] **D5 (mon arbitrage)** : limite mono-agent acceptée + documentée ; skew temporel divulgué (`ground_truth_fetched_at`, `n_samples_with_past_date` + warning) ; post-filtre minute-exact reproduit dans le pool (mêmes sémantiques + fallback A4-c)
- [x] **D6 (mon arbitrage)** : la règle nom-exact du resolver EST le poli principal (supprime le pire cas) ; le filtrage écho des options résiduelles (fuzz colombien de la-defense) volontairement non fait — risque de sur-filtrage > gain
- [x] **D7 (mon arbitrage) : DIFFÉRÉ** — honorer `_eval_clock` (horloge fournie par le client) = surface d'injection ; à designer gated (env flag éval) dans une session dédiée ; `check_date_reference` reste approximatif tant que les runs sont same-day
- [x] DoD : 889 passed (+17), pack tests 11 passed, ruff/mypy/guardrails OK
- [x] Live (gpt-5.2) : budapest PASS, carry_same_time_0 PASS, zone_change_0 PASS, detroit GPS tour 1 = 4 hôtels ancrés GPS, la-defense = clarify honnête flaggé, ranking eval 1 échantillon (precision@5=1.0, NDCG@5=0.83)

---

# Audit comparatif agent-usa vs AgentB2C — suivi

Plan complet : `~/.claude/plans/dans-le-repo-j-ai-serene-wreath.md`
(session précédente S09 : voir bloc HANDOFF 2026-07-20 + git history de ce fichier)

## S-A — Adapter + smoke staging (branche s15-eval-adapter)
- [x] `scripts/run_eval_adapter.py` (proxy :8110→:8100, 3 règles de mapping, disclosure `eval_debug.adapter_mapped`)
- [x] `tests/test_eval_adapter_mapping.py` (15 tests offline, fonctions pures) — verts
- [x] Gates verts (526 pytest, ruff, mypy, guardrails)
- [x] Smoke run : 249 cas via l'adapter sur staging ES → 110/249 (44,2 %) — plumbing validé, PAS un chiffre d'audit
- [x] Triage : 90 cas zéro-hôtel (staging), ~20 hors-zone US à investiguer sur prod, 20 gap-only (36 assertions < budget ≈45), adapter 541+23 mappings divulgués
- [x] Fixture inventaire régénérée (exports agent-usa 2026-07-15, 8 701 hôtels / 29 marchés)
- [x] HANDOFF.md + commit + MR (PR #18 — review Fabien = gate)

## S-B — Baseline agent-usa local (BLOQUÉ : procédure de boot :5002 + inventaire prod → Fabien)
- [ ] `scripts/run_llm_meter.py` (comptage tokens old agent) + baseline `local_5002.json`

## S-C — Run-of-record prod ES + compare (BLOQUÉ : creds MCP_B2C prod read-only + DATABASE_URL → Fabien)
- [ ] `candidate.json`, `comparison.json`, `annotate_inventory_confound.py`, `measure_ab_perceived_latency.py`, coût SQL

## S-D — Judge A/B — `scripts/run_judge_ab.py` (evalset-v0, 32 scénarios × 2 agents)
## S-E — Load probe — `scripts/load_probe.py` (1/5/10/20 concurrents, les 2 stacks locales)
## S-F — Rapport `AUDIT-COMPARATIF-AB-2026-07.md` + HANDOFF final

---

# TODO — Railway deploy: AgentB2C hosted demo (widget front + 3 services)

**Goal**: reproduce `localhost:8090` (agent-usa chat widget → AgentB2C `/v3` facade → 2 A2A leaves → **staging** MCP) as a hosted Railway demo in a **new project "AgentB2C"**. Synthetic/demo traffic only — no prod-ES, no real users.

**Decisions (Fabien, 2026-07-22)**: hosted demo on staging MCP · vendor widget + proxy as 4th service · new Railway project.

## Target topology (project `AgentB2C`, env `production`)

| Service | Source | Public? | Role |
|---|---|---|---|
| `redis` | Railway managed Redis | private | concierge session store |
| `hotel-search` | `agents/hotel_search_agent/Dockerfile` | private | A2A leaf (Mapbox + MCP) |
| `faq` | `agents/faq_agent/Dockerfile` | private | A2A leaf (MCP) |
| `concierge` | `agents/b2c_concierge/Dockerfile` | private | orchestrator + `/v3` facade |
| `widget` | new `web/Dockerfile` (`run_widget_proxy.py`) | **PUBLIC** | serves widget, forwards `/v3/*` → concierge (private) |

Only `widget` gets a public domain. Browser talks to one origin (proxy); proxy forwards server-side over the private net. Concierge stays private.

## Phase 0 — Prerequisite (BLOCKING, needs Fabien)
- [ ] `FLEET_READ_TOKEN` (fine-grained read PAT on `Dayuse-Labs/dayuse-agent-fleet`) — needed at **build time** for the pinned private `dayuse-agent-common` dep. Same secret CI uses. Without it, no image builds.

## Phase 1 — Code changes on branch `s-railway-deploy-demo` (reviewable, testable locally) ✅ DONE
- [x] Branch `s-railway-deploy-demo`.
- [x] Vendored full widget manifest into `web/vendor/` (39 files, 1.2 MB — hero JPGs + font dominate). Complete: every `@import`/`src`/`href`/JS-module ref is local (js/chat imports are all relative → dir is self-contained). Only external dep = Google Fonts CDN (client-side, degrades gracefully).
- [x] Patched `scripts/run_widget_proxy.py`: honors `PORT`/`HOST`/`WIDGET_BACKEND` env; **dual-stack IPv6 bind** (`_WidgetProxyServer` — http.server defaults AF_INET, can't bind `::`); auto-prefers vendored dir (no longer needs sibling repo).
- [x] New `web/Dockerfile` (stdlib only, no token). **Built + ran + smoke-tested in container**: binds `:::8090` dual-stack, all assets 200, chat meta `/v3/chat`, `/v3/*` forwards (502 when upstream down = forward path proven).
- [x] Patched 3 backend Dockerfiles: `# syntax=docker/dockerfile:1`, `apt-get install git` (the real reason they never built), fleet token via BuildKit secret-mount OR build ARG + CI's `insteadOf`, token scrubbed same-layer.
- [x] Gates: ruff ✅, mypy (34 files) ✅, guardrails ✅, `pytest -q` → 528 pass / 1 fail (pre-existing, untracked S-B `test_llm_meter_usage.py`, unrelated to this branch).
- [ ] **NOT YET**: build the 3 backend images (needs `FLEET_READ_TOKEN`) — will do locally with `--secret` to prove them BEFORE deploying.

## Phase 2 — Railway provisioning ✅ DONE
- [x] Project `AgentB2C` (a200e208-863d-4771-8b4d-03b5a6280904, workspace Inno Labs); Redis + 4 Dockerfile services (RAILWAY_DOCKERFILE_PATH per service, context = repo root); public domain on `widget` only → https://widget-production-3f56.up.railway.app

## Phase 3 — Env wiring ✅ DONE
- [x] 3 generated A2A bearers, cross-service card URLs, `CONCIERGE_REDIS_URL=${{Redis.REDIS_URL}}`, staging MCP + Mapbox + OpenAI from `.env`, `FLEET_READ_TOKEN` as build ARG on the 3 backends, `DAYUSE_MODEL=gpt-4o-mini`. Demo deviation: `CONCIERGE_LEAF_TIMEOUT_SECONDS=30` (see HANDOFF).

## Phase 4 — Deploy + verify ✅ DONE (evidence in HANDOFF)
- [x] All 5 services up (`Application startup complete`, bind `[::]`). Live via public URL: SEARCH (5 real hotels + pool filter), FAQ (real answer), ACK (template). Fixed en route: git-in-slim, Railway rejects BuildKit secret mount → build ARG, http.server IPv6 `::` bind.

## Phase 5 — Close out
- [x] `HANDOFF.md` dated block (topology, URL, env matrix, gotchas, timeout deviation).
- [ ] Commit on branch + push + MR (Fabien's review = gate, never self-merge) — pending Fabien's go on push/MR.
- [ ] Fabien to open the URL and confirm the widget renders cards visually (I verified API+page+assets via curl only).

## Caveats
- Staging MCP = sparse inventory → some "0 offres" cities, faithful to local not a quality signal.
- `DAYUSE_MODEL=gpt-4o-mini` mirrors local (`.env` `OPENAI_MODEL=gpt-5.2` is dead config, not read).
- 4 always-on services + Redis = small non-zero cost.

# Remédiation geo/multi-turn (S-G series, arbitrée 2026-07-23)

Plan : `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` · phases : `phases/SG1…SG9.md` · vue d'ensemble : `SESSIONS-CLAUDE-CODE.md` §S-G.

- [ ] S-G1 profil v2 + ops reducer (concierge)
- [ ] S-G2 intake contexte natif (facade) — après S-G1
- [ ] S-G3 résolveur géo multi-candidats (feuille, Opus, probe live d'abord)
- [x] S-G4 budgets timeout + RetryPolicy + Chester — branche `sg4-timeout-budgets`, Chester résolu (GPT-5.2 latency + ancien budget 10s, pas un bug), voir HANDOFF
- [ ] S-G5 pont déterministe + pagination — après S-G1+S-G3
- [ ] S-G6 dates/durées/demi-heures — après S-G5
- [ ] S-G7 locale/devise propagation — après S-G6
- [ ] S-G8 durcissement harness (∥ possible)
- [ ] S-G9 gate 81 cas ×3 + éval ranking — dernier
- [ ] Cross-repo MCP_B2C : ouvrir les demandes (minutes timeSlot, offset/exclusion, pricing) — `reports/MCP-B2C-REQUESTS.md` créé en S-G6/S-G7
- [ ] Ops : contrôle plateforme `DAYUSE_MODEL` (défaut committé = gpt-4o-mini, eval = gpt-5.2)
