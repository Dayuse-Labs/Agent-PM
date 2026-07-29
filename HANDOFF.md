# HANDOFF — AgentB2C

État du chantier pour reprise en session fraîche. **Lire en entier avant d'agir ; ne pas reconstruire ce qui existe.** Mettre à jour en fin de CHAQUE session (bloc daté en tête).

## 🚢 Addendum 2026-07-29 (12h50) — S-PERF4 DÉPLOYÉ SUR RAILWAY DEPUIS LA BRANCHE (pas mergé)

**GO explicite de Fabien (« mets cette version sur sa branche et déploie-la sur Railway que je puisse
voir »). La PR #45 n'est PAS mergée** — le gate humain reste à exercer. La démo tourne donc du code
de branche : `main` et le déployé ont divergé, à re-synchroniser après review.

**Déployé** : `concierge` **puis** `widget` — dans cet ordre, parce que le fix des picks est
côté serveur : widget-en-SSE avant concierge aurait affiché exactement le bug corrigé (cartes sans
CTA). `hotel-search` et `faq` **non redéployés** (`git diff origin/main` vide sur leurs dossiers).
`WIDGET_CHAT_TRANSPORT=sse` posée sur le service `widget` (elle n'existait pas → le défaut `json`
était actif).

**Vérifié EN PROD sur https://widget-production-3f56.up.railway.app**
- Assets : meta `du-chat-transport="sse"`, `stream.js` **200**, et dans `send.js` servi :
  `mapV3Hotels` ×3, `rating_count` ×2, `state.hotelPicks = Array.isArray(frame.hotel_picks)` ×1.
- Probe SSE brute : la frame porte `hotel_picks` **identique à `done`** (3 picks, €89 → €90 → €95),
  `response_language: fr`, `rating_count` 4 / 1 / 0.
- **Navigateur (CDP)** : cartes à **4,9-5,1 s**, fin de tour à **8,2-9,3 s** → **3,3-4,2 s d'avance**.
  À l'instant des cartes : 3 cartes, **3 `.pick-cta`**, notes `4,9/5 (4)` et `5,0/5 (1)`, rien sur le
  `rating: 0`, badges `-33/-34 %`, `dès €90 €135/nuit`, bulle thinking en dessous (`thinking: true`
  relevé dans le DOM = le tour n'était PAS fini).
  → `reports/latency/widget-sse-2026-07-29/prod-cards-midstream-with-cta.png`
- **Clic réel du CTA de la carte #2** (`hotel_id=20152`) → carte de réservation du bon hôtel
  (€89,00, 15:00-22:00, mer. 29 juil.) + lien tunnel `offerId`/`ratePlanPolicyUuid`/`checkinDate`,
  en **1,43 s**. → `prod-pick-booking-card.png`

**Rollback** (2 niveaux, indépendants)
1. Revenir au transport bloquant sans toucher au code : `railway variables --service widget --set
   "WIDGET_CHAT_TRANSPORT=json"` (ou supprimer la variable) + redeploy du widget.
2. Revenir au code de `main` : `railway up --service concierge --ci` puis `--service widget --ci`
   **depuis un checkout de `main`** (`railway up` envoie le répertoire de travail, pas le git).

**Toujours pas démontré** : le sélecteur MULTI-formules de S-CX8 (l'inventaire de l'après-midi ne
renvoyait qu'une formule — même limite de cutoff que la veille). `card.js` est **identique à main** et
la booking card n'a pas changé, donc le risque est structurellement nul, mais la preuve visuelle
manque. À reprendre tôt le matin.

## 🖥 Addendum 2026-07-29 (après-midi, branche `sperf4-widget-sse`, PR #45) — S-PERF4 rebasé sur main : le CTA S-CX9 survit au rendu hotels-first

**La PR #45 était complète et vérifiée depuis le 28/07 — mais jamais mergée, et `main` a bougé
dessous** (S-CX7 #49, S-CX8 #50, S-CX9 #51/#52, tous déployés). Le merge de `main` dans la branche
n'a levé que **4 conflits textuels** (`HANDOFF.md`, `tasks/lessons.md` = append-only ;
`facade.py` = wrapper OBS1 `turn_observation` à réindenter autour du `yield` de la frame ;
`send.js` = `mapV3Hotels()` extrait de `normalizeV3Response` **vs** `rating_count` ajouté par #52).

**Le vrai défaut n'était dans AUCUN conflit** : le CTA de réservation de S-CX9 (`.pick-cta` sur la
carte) est gaté sur `state.hotelPicks`, que le widget ne remplissait **que depuis le corps JSON
bloquant** (`send.js`, à `done`). La frame SSE `hotels` ne portait pas `hotel_picks` → en transport
`sse` **toutes les cartes se peignaient sans leur CTA principal**, et `skipCarousel` interdisant tout
redessin à `done`, le CTA n'apparaissait jamais. Pire : `state.hotelPicks` gardait les picks du tour
PRÉCÉDENT, donc un `hotel_id` commun affichait un CTA issu d'un état périmé. Et comme #49 a retiré
l'exigence de date de `build_hotel_picks`, les picks sont non-vides sur **quasi toute** recherche —
donc le défaut touchait tous les tours de recherche, pas un cas limite.

**Fait (côté serveur)**
- **`build_hotel_picks` déménage de `facade.py` vers `profile.py`** — `facade.py` importe `.agent`,
  donc `agent.py` ne peut pas importer le facade (cycle). Les deux appelants exécutent désormais **la
  même fonction sur le même profil** : la frame et le payload sont égaux **par construction**, pas
  par revue. `facade.py` la ré-importe (aucun changement d'API pour `build_chat_payload`).
- **`_hotels_event(ctx, response, language, picks)`** porte `hotel_picks` ; le facade le relaie sur
  la frame SSE (additif, à côté de `requires_clarification` / `response_language`).
- **Le `yield` de la frame passe APRÈS `apply_profile_delta` + `record_search_shortlist`** (juste
  avant la synthèse — le gain S06 est intact, tout ce qui précède est du dict en mémoire). Émis
  avant, il calculait les picks sur la ville et la shortlist du tour PRÉCÉDENT. **Vérifié en
  remettant le `yield` à sa place d'origine → le test tombe** (`[] != [101]`).
  Effet de bord assumé : les 2 sorties anticipées (`search_unavailable`, pagination épuisée)
  n'émettent plus de frame du tout — c'étaient des tours à `hotels: []`, rien à peindre, et le
  payload donne `hotels: None` dans les deux cas.
- **Chemin inline** (`details`/`compare`) : mêmes picks que le payload (ces routes ne touchent pas
  `last_results` — parité avec le POST bloquant, pas une amélioration).

**Fait (côté widget)**
- `renderHotelsEarly` pose `state.hotelPicks` depuis la frame, **inconditionnellement** (absent ⇒
  `[]`) et **avant** `createHotelCarousel` — sinon les picks du tour précédent gatent les cartes du
  tour courant.
- `mapV3Hotels` récupère **`rating_count`** : sans ça le merge annulait silencieusement le fix #52.

**Tests** : `pytest -q` → **1099 passed**, 1 failed = `test_llm_meter_usage` (**rouge sur `main`
aussi**, bug d'arrondi du test, hors zone). ruff / mypy (43 fichiers) / guardrails **OK** ;
`node --check` sur les 5 JS touchés. 2 tests neufs, **tous deux vérifiés en échec sans leur fix** :
parité picks frame↔`done` non vide, et « les picks de la frame sont ceux de CE tour, pas du
précédent » (2 tours, 2 villes).

**Vérification navigateur (Chrome headless, CDP, stack locale réelle + MCP live)**
- **À l'instant où les cartes apparaissent** (4,53 s, soit **2,87 s avant la fin du tour** à 7,40 s) :
  3 cartes, **3 `.pick-cta`** (`ids 9075 / 20152 / 7851`), libellés **« Choisir cet hôtel »** en
  français, notes **`4,9/5 (4)`** et **`5,0/5 (1)`**, aucune note sur le 3e (`rating: 0`), badges
  `-33 % / -34 %`, prix `dès €90 €135/nuit`, bulle « thinking » SOUS les cartes.
  → `reports/latency/widget-sse-2026-07-29/sse-cards-instant-with-cta.png`
- **Contrôle JSON** (proxy `:8091`, transport `json`) : cartes à **7,37 s** (lead 0,09 s), et **DOM
  final identique** (3 cartes, 3 CTA, 1 carrousel, mêmes notes, mêmes ids).
- **Clic réel du CTA de la carte #2** (pas la 1re, `hotel_id=20152`) → carte de réservation du **bon
  hôtel** (Courtyard by Marriott Lyon Eurexpo, €89,00, 15:00-22:00, mer. 29 juil.) avec lien tunnel
  portant `offerId` + `ratePlanPolicyUuid` + `checkinDate`. 1 seul carrousel, chips d'affinage
  intactes. → `sse-pick-booking-card.png`
- **Probe SSE brute** sur `:8100` : `hotel_picks` de la frame == celui de `done` (3 picks, tri
  €89 → €90 → €95), `response_language: fr`.

**⚠️ PIÈGE DE VÉRIFICATION (m'a fait mesurer le mauvais code pendant 10 min)** :
`scripts/run_local.sh` ne tue que les pids de **son propre** `.run-logs/`. Un stack lancé depuis un
AUTRE checkout tient les ports 8100-8102 → mes 3 services meurent en `[Errno 48] address already in
use`, **puis la sonde de readiness trouve l'ancien stack et annonce « ready »**. Ma première probe
lisait donc le code de `main` (`hotel_picks: []`, `response_language: None` — j'ai failli conclure à
un bug de mon fix). **Toujours vérifier quel checkout sert le port** :
`ps -p $(cat .run-logs/b2c_concierge.pid) -o command=`. Les ports sont codés en dur dans le script
(pas de surcharge par env).

**Reste / à trancher**
- **Décision produit ouverte (inchangée depuis le 28/07, jamais revue)** : en `sse` le texte de
  synthèse arrive **SOUS les cartes** (en `json` l'intro reste au-dessus). Visible sur
  `sse-pick-booking-card.png` (« J'ai trouvé 3 hôtels à Lyon… » sous le carrousel). Alternative
  écartée : injecter l'intro dans le message des cartes à `done` (DOM final identique au JSON) — ça
  déplace la vue pendant que l'utilisateur lit les cartes.
- **Déploiement (Fabien)** : merger #45, puis `WIDGET_CHAT_TRANSPORT=sse` sur le service `widget` +
  redeploy. Rollback = retirer la variable (le défaut `json` est le comportement actuel).
- Si le widget est un jour servi par l'app Dayuse via `/v3/chat/public`, le stream devient
  `/v3/chat/stream/public` et cette route doit exister côté hôte. Non concerné sur la démo Railway.
- `adk eval` non relancé (worktree installé sans `google-adk[eval]`, cf. bloc du 28/07).

## 🚀 Addendum 2026-07-29 (11h50) — S-CX8 + S-CX9 MERGÉS DANS MAIN, widget DÉPLOYÉ depuis main

**Fabien a donné le go explicite de merger (« merge le PR dans l'ordre et lance un déploiement ») —
le gate humain de CLAUDE.md a été exercé, pas contourné.**

**Ordre suivi** : PR #50 (S-CX8 → main), puis **retarget de #51 sur main AVANT toute suppression de
branche** (le piège consigné : supprimer la base ferme la PR enfant sans la réouvrir), puis #51, puis
#52 (le correctif ci-dessous). **Les branches ne sont PAS supprimées** — hygiène laissée à Fabien.
`main` = `5f1446d`. La prod est enfin reproductible depuis main : le warning de l'addendum précédent
(« le prochain `railway up` depuis main FERA DISPARAÎTRE la feature ») est **levé**.

**Déployé** : service `widget` seul (`railway up --service widget`), 2 déploiements en `SUCCESS`
(`4f979041…` puis `650bdcec…` pour le correctif). `concierge` / `hotel-search` **non redéployés** :
ils tournaient déjà le code de la branche S-CX8, désormais identique à main — aucun diff fonctionnel.

**Vérifié EN PROD sur https://widget-production-3f56.up.railway.app** :
- Assets servis : 6 marqueurs S-CX9 dans `card.js`, `class="pick-cta" data-action="pick-hotel"`
  présent, **0 occurrence de `pickButtonsHtml`** (la rangée de chips a bien disparu), `star.svg` 200,
  5 règles `.pick-cta` dans le CSS.
- **Capture navigateur, vraie recherche** (`?q=un hotel avec piscine a Lyon cet apres-midi`) : 3
  cartes, badges `-33 % / -34 % / -33 %` sur les photos, étoiles jaunes (elles étaient cassées avant
  ce déploiement), notes `4,9/5 (4)` et `5,0/5 (1)`, **aucune note sur le 3e hôtel (`rating: 0`)** —
  le garde-fou fait exactement son travail —, prix `dès €90  €135/nuit` sur une baseline, CTA bleu
  nuit + lien texte. Plus aucune chip de choix, seules restent les 3 chips d'affinage.
- **Le CTA produit bien la carte de réservation** : pick de Mercure Lyon Saxe (`hotel_id: 9075`) →
  carte au bon hôtel/date/créneau (16:00-21:00, €90) avec lien tunnel `https://` ; idem Villa Paris
  Orly et Drawing House. `hotel_picks` = 5/5 hôtels sur Paris, 3/3 sur Lyon → CTA sur toutes les
  cartes montrées.
- **Dégradation honnête observée en vrai** : une requête Orly a renvoyé `hotel_picks: []` +
  « je n'arrive pas à joindre la recherche » (hoquet MCP) → **aucun CTA nulle part**, ce qui est le
  comportement voulu du gate.

**⚠️ Non re-démontré aujourd'hui : le sélecteur MULTI-formules.** Les 3 hôtels piqués ce matin
renvoient `rate_plans` absent, et l'agent confirme lui-même « une offre » pour Drawing House → **une
seule formule bookable aujourd'hui**, ce qui EST la dégradation documentée (« une formule n'est pas un
choix »). Cohérent avec le cutoff same-day (`cutoffDeadlineUtc` Paris 05h-16h) : à 11h50 une partie
des formules du jour est déjà passée. **Zéro ligne backend ni booking-card touchée par S-CX9**, et le
chemin `rate_plans: 3` était vérifié en prod la veille (addendum S-CX8). À re-regarder tôt le matin
pour une preuve visuelle du sélecteur sous le nouveau CTA.

## 🐛 Défaut TROUVÉ ET CORRIGÉ post-deploy (PR #52) — le compte d'avis n'atteignait pas la carte

La capture navigateur a montré « **5,0/5** » sur le Courtyard Eurexpo, noté par **une** personne. Le
payload prod portait bien `rating_count: 1` : c'est **`normalizeV3Response` (`handlers/send.js`) qui
whiteliste les champs hôtel** — `rating` y était, `rating_count` non.

**Piège à ne jamais reconstruire** : mes 25 assertions jsdom passaient parce qu'elles donnaient le
dict hôtel **directement** à `createHotelCard`, contournant le mapping qui cassait tout. Le harnais
exerce maintenant le vrai chemin (payload v3 → `normalizeV3Response` → carte), d'où l'`export` de la
fonction ; **30/30**. Règle consignée dans `tasks/lessons.md` : **tout champ nouvellement lu par un
renderer doit être asserté À TRAVERS le mapping de payload réel.** Recorrigé et redéployé, vérifié à
l'écran : `4,9/5 (4)` et `5,0/5 (1)`.

## ⏱ Addendum 2026-07-29 — S-CX9 : le CTA de réservation passe sur la carte de résultat (branche `scx9-card-pick-cta`, mergée dans main par PR #51)

**Contexte** : Fabien n'était pas convaincu par la rangée de chips sous le carousel pour choisir
l'hôtel. Artefact de 5 propositions produit (`claude.ai/code/artifact/f887ae71`) ; décision =
**proposition A + la repasse des cartes**. Détail des écarts assumés dans `tasks/todo.md`.

**100 % widget vendored (`web/vendor/**`), zéro changement backend** — même périmètre que S-CX5b.

**Fait** :
1. **La rangée de chips `pick-row` est supprimée** (`pickButtonsHtml` + le paramètre
   `allowedHotelIds` d'`addFollowUpMessage`, et les règles CSS `.pick-row`/`.pick-button`).
   Le CTA vit maintenant sur chaque carte : `.pick-cta` → `data-action="pick-hotel"`, **le handler
   de `ui/messages.js:377` est inchangé** (il lit `data-hotel-id`/`data-pick-label` sur n'importe
   quel élément). Le tour, le message envoyé et la booking card sont identiques à avant.
2. **`state.hotelPicks` devient une PERMISSION, pas un rendu.** Point le plus important de la
   session : la liste vide signifie « le backend juge la demande trop vague pour réserver » (pas de
   destination résolue). La carte la lit pour décider si elle affiche le CTA ; un bouton non gaté
   aurait abrogé cette règle produit en silence. Sans pick offert, la carte garde exactement le
   bouton jaune « Voir la fiche » d'aujourd'hui.
3. **Hiérarchie de couleur enfin cohérente** : `hotels.css` avait déjà écrit la règle en S-CX5
   (« le dégradé chaud est réservé au CTA qui part vers le tunnel ») et **c'est le bouton de la
   carte qui la violait** — jaune, mais il partait sur dayuse.com. Désormais : **jaune = partir
   réserver (`.booking-card__cta` seul), bleu nuit plein = avancer dans la conversation
   (`.pick-cta`), lien texte souligné = aller consulter (`.see-hotel-link`)**. Un seul bouton jaune
   par thread, celui qui prend l'argent. Le libellé ne dit **pas** « Réserver » (`card_pick_cta`) :
   il ouvre une carte, pas un checkout — c'est le défaut que l'ancien wording évitait déjà.
4. **Repasse de la carte** : badge `-X%` promu sur la photo (`.deal-badge`, coin gauche —
   `.pool-badge` tient le droit) ; note `4,7/5 (128)` dans la ligne étoiles/quartier (`rating` était
   sur le payload depuis S-CX3a et n'était lu que par la booking card) ; prix sur **une** baseline
   (`dès €54  €98/nuit` au lieu de 3 lignes empilées) ; ligne concierge passée **sous** le créneau et
   clampée à 2 lignes (elle était le bloc le plus haut pour la donnée la plus molle) ; hairline au-
   dessus du footer.
5. **Le libellé de créneau ne disparaît QUE quand il ne revendique rien** (`available_timeslots`).
   Les niveaux `exact`/`close`/`none` sont l'information du guard S-G6 (« créneau proche », « les
   plus proches ») et restent affichés — les supprimer aurait rendu muet le garde-fou qui empêche
   une carte de montrer 07:00-13:00 pour une demande à 07:30.
6. **`formatRating` déplacé dans `utils.js`** (il était privé dans `ui/messages.js`) : la carte et la
   booking card affichent la même note sur le même écran, deux formateurs = deux occasions de ne pas
   s'accorder sur le séparateur décimal.
7. **`static/icon/star.svg` AJOUTÉ** — défaut préexistant trouvé en rendant la carte : le fichier
   manquait au manifeste vendorisé (S9), donc **toutes les étoiles de toutes les cartes étaient des
   images cassées dans la démo déployée**. 7 locales touchées pour l'i18n (`card_pick_cta` ajouté,
   `pick_prompt`/`pick_from_prefix` supprimés, `card_from_label` raccourci en `dès`/`da` sur fr/it).

**Vérifié** (pas de suite de tests JS dans le repo — deux harnais jetables dans le scratchpad de
session) :
- **25/25 assertions sur le vrai `createHotelCard` sous jsdom** : CTA présent/absent selon
  `hotelPicks` (y compris un pick pour un AUTRE hôtel → pas de CTA), `data-action`/`data-hotel-id`/
  `data-pick-label` corrects, note formatée `4,7/5 (128)` en fr, badge remise sur la photo et non
  dans le footer, prix+qualificatif+tarif nuit sur une seule ligne, ordre créneau→concierge, libellé
  de créneau dropé sans revendication mais **conservé** en `close`, repli sans pick, carte sans prix,
  et un nom d'hôtel hostile (`"><img onerror=…`) correctement échappé.
- **Rendu réel en Chrome headless** avec le CSS servi (`index.css` complet), 3 cartes côte à côte à
  320 px : hiérarchie, baseline du prix, clamp 2 lignes, pastille ambre du créneau proche, étoiles
  jaunes. ⚠️ **La zone photo n'est pas vérifiable dans cet environnement** (pas de réseau sortant :
  `static.dayuse.com` ne résout pas) — à regarder sur le démo déployé.
- `ruff` + `mypy` OK, guardrails `OK`, `pytest` **1097 passed / 1 failed**.

**⚠️ Rouge PRÉEXISTANT, non lié** : `tests/test_llm_meter_usage.py::test_usage_record_extracts_tokens_and_model`
échoue à HEAD aussi (vérifié par `git stash`) — `round(432.15, 1)` vaut `432.1` en flottant, le test
attend `432.2`. Zéro fichier Python touché par S-CX9. Laissé tel quel : décider si c'est le test ou
`meter.usage_record` qui a tort appartient au chantier OBS1, pas à celui-ci.

**Reste à faire** :
- Faire tourner l'œil sur le démo déployé (zone photo + carousel réel), puis `railway up` si OK.
  **Attention : PR #50 toujours ouverte** → cette branche est EMPILÉE dessus. Piège déjà rencontré
  (cf. addendum CI) : **retargeter la PR enfant sur main AVANT de supprimer la branche de base**,
  sinon GitHub ferme la PR enfant et ne la réouvre pas.
- Instrumentation à regarder avant d'aller plus loin dans la roadmap CX : `hotel_pick_click` **par
  rang de shortlist** dans Amplitude. Si les rangs 4→10 ne convertissent pas, la rangée de chips ne
  portait rien et A suffit ; sinon la proposition D (liste compacte sous le carousel) est le
  remplaçant à construire.
- Propositions C et E de l'artefact (formules sur la carte / créneaux cliquables) sont **bloquées sur
  un changement de contrat MCP_B2C** : le payload de recherche ne porte pas les formules du jour
  (`normalize_hotel` ne garde que `_best_offer`). C'est le seul verrou qui empêche la carte
  d'afficher les vrais prix du jour au lieu d'un « dès ».

## 🚀 Addendum 2026-07-28 (soir) — S-CX8 DÉPLOYÉ EN PROD depuis la branche (main NON mergée)

**Déployé sur Railway (projet `AgentB2C`, env production) : `hotel-search`, `concierge`, `widget`.**
`faq` non touché par le diff, non redéployé. Les 3 déploiements en `SUCCESS`,
`deploymentStopped=false`.

⚠️ **Déployé depuis la branche `scx8-rateplan-selector`, PAS depuis main.** `railway up` envoie le
répertoire de travail, donc la prod tourne du code que **la PR #50 n'a pas encore fait entrer dans
main** (règle CLAUDE.md : la review humaine de Fabien est le gate, je ne merge jamais moi-même).
**Conséquence à connaître : le prochain `railway up` fait depuis main FERA DISPARAÎTRE la feature.**
Merger la PR #50 est ce qui rend l'état de la prod reproductible.

**Vérifié EN PROD** (widget proxy `POST /v3/chat`, tours réels) :
- **Le badge de remise s'affiche enfin** — `-66 %` sur H4 Wyndham Paris Pleyel (€95 vs €280 nuit) ;
  **5/5 hôtels** portent un tarif nuit à Paris, Lyon (Pullman −33 %) et Marseille (Ibis Centre −33 %).
  C'est le correctif de la feuille (`response_bridge` → `slot.original_price` en euros) qui rend
  vivant `computeNightDiscount`, mort en prod depuis toujours.
- **Sélecteur de formules** : pick de Villa Paris Orly → `rate_plans: 3` (dayuse.day / early /
  late_break), 3 liens tunnel `https://`, remise −37 % sur chacun, `bedding`/`capacity` présents.
  Invariants vérifiés en prod : **un seul plan sélectionné**, **prix carte == prix du plan
  sélectionné**, **url carte == url du plan sélectionné**.
- Widget : 16 marqueurs S-CX8 dans le `messages.js` servi en prod.
- **Logs prod (`railway logs --service concierge`)** : `POST /v3/chat` → **200 OK** sur tous les
  tours, zéro exception, zéro `status=degraded`. Seul bruit : les UserWarning ADK expérimentaux
  (préexistants).

**Le coût du lookup ajouté est mesuré, pas supposé.** En amendant
`test_the_cheapest_is_picked_from_the_screen_never_re_searched` j'avais acté qu'un pick coûte
désormais un `get_hotel_details` + N `generate_booking_link` parallèles, sans chiffre. Les logs prod
donnent la réponse : `concierge_metric=turn family=booking route=inline:generate_booking_link
llm_calls=1 phases=triage ms=1383 status=ok` → **1,4 s pour le tour de pick entier, 1 seul appel LLM**
(le triage ; le chemin booking reste 100 % déterministe). Le compromis est donc bon marché.

**Observation de latence, expliquée — SANS lien avec S-CX8, et sans anomalie** : les tours `search`
mesurent **9,3 à 10,0 s** dans ces logs, alors que le bloc S-PERF plus bas enregistre un p50 ramené à
**~3,4 s**. Ce n'est pas une régression : les variables prod du concierge portent
**`DAYUSE_MODEL_SYNTHESIS=gpt-5.2`** (+ `DAYUSE_MODEL=gpt-5.2`, `DAYUSE_MODEL_TRIAGE=gpt-4o-mini`,
`DAYUSE_REASONING_EFFORT=low`) — la mitigation `gpt-4o-mini` sur la synthèse **a été levée**, et les
~3,4 s avaient précisément été mesurés AVEC cette mitigation. Le surcoût est donc le prix assumé
d'une synthèse 5.2. Et la synthèse fonctionne bien : les tours sortent en `status=ok`, **pas** en
`status=synthesis_fallback` — le fix de la collision `temperature × reasoning_effort` tient en prod.
Arbitrage qualité de prose ↔ latence à trancher par Fabien, pas un incident.

**E2E local exécuté AVANT le déploiement** (le trou de vérification signalé dans le bloc précédent
est comblé) : `run_local.sh` redémarré sur le nouveau code, `smoke_e2e.py` **PASS** (ack 18 ms /
search 9,5 s / faq 12,9 s), plus un scénario `search → pick` maison qui inspecte la `booking_card`
réelle : 3 formules, liens réels, invariants OK.

**Faux positif à ne pas rechercher** : `GET /` sur `concierge-production-aaa2.up.railway.app`
renvoie **502** — le service ne route pas la racine, ce n'est pas une panne. Le chemin réel est le
proxy du widget (`widget-production-3f56.up.railway.app/v3/chat`), qui répond 200. `railway status
--json` n'a pas de clé `latestDeployment` à la racine : elle est sous
`services.edges[].node.serviceInstances.edges[].node.latestDeployment.status`.

**RGPD OK** : `.railwayignore` (déjà en place) exclut `baseline/` — Railway **n'honore pas**
`.gitignore`, donc c'est ce fichier qui protège les messages utilisateurs bruts lors d'un
`railway up`.

## ✅ Addendum 2026-07-28 (suite S-CX8, même branche) — la nouvelle version de MCP est déployée, les 3 champs sont branchés

**Fabien : « la nouvelle version du mcp est déployé »** → re-probe immédiat. Les deux champs demandés
sont là, **plus un troisième sous un nom différent de celui que j'avais demandé** :

| Champ | Remplissage mesuré | Statut |
|---|---|---|
| `originalPriceEuro` | **2 084 / 2 114 = 98,6 %** | branché (nom exact déjà lu par le code) |
| `ratePlanName` | **2 114 / 2 114 = 100 %** | branché |
| `includedAmenities` | **1 674 / 2 114 = 79,2 %** | branché **au niveau CARTE**, pas par ligne (voir ci-dessous) |

**`originalPriceEuro` validé sur 760 paires réelles** : 0 % d'anomalie, ratio nuit/jour médian 1,64
(min 1,03, max 3,75), unité centimes EUR confirmée. **Le badge de remise s'affiche pour la première
fois en production** — sur les DEUX surfaces :
- booking card, par formule (`_rate_plan_view`, déjà écrit, la donnée est arrivée) ;
- **carrousel** : `response_bridge` pose désormais `slot.original_price` **en euros** — la forme que
  `computeNightDiscount` lisait depuis toujours sans que rien ne la remplisse. Vérifié en live :
  Ibis La Ciotat → `original_price: 76.7` sur un prix de €69 → −10 %.

**`includedAmenities` n'est PAS une prestation de formule — piège évité de justesse.** Probé sur
**227 journées multi-formules** : identique sur toutes les formules **128 fois**, différent **0
fois**, et seulement **4 valeurs distinctes** (Free parking, Outdoor pool, Indoor pool, Fitness
room). C'est un équipement d'hôtel. L'afficher par ligne aurait répété la même mention en
prétendant différencier. → `hotel_amenities` sur la CARTE, une seule fois (`_day_hotel_amenities`),
table i18n fermée × 7 langues, valeur non mappée **ignorée** (jamais d'anglais brut dans une carte
française). Le rendu par-ligne des « prestations » a été **supprimé** : la donnée n'existe pas à ce
niveau.

**Défaut de conception attrapé par les données réelles** : le titre de ligne ne peut pas être choisi
par ligne. Deux cas live du 2026-07-29 :
- **Ibis La Ciotat** — 3 formules toutes `dayuse.day`, **même créneau 10:00-15:00**, seule la
  chambre diffère (« …with Sea view », « …with balcony ») → un titre par type donnerait « Journée /
  Journée / Journée » ;
- **Mercure Lyon Saxe** — 3 formules toutes nommées « Standard King Room », seuls les créneaux
  diffèrent → un titre par nom donnerait trois lignes identiques.

→ La décision est désormais **au niveau de la CARTE** (`renderRatePlans`) : le nom de chambre prend
le titre uniquement si les libellés de type NE séparent PAS les lignes et que les noms LE font ;
sinon le type titre et la pastille de créneau (toujours affichée) porte la distinction. Le CTA
reçoit le titre retenu depuis le renderer (plus de recalcul divergent) et retombe sur le libellé
générique au-delà de 22 caractères — « Standard Double Room with Sea view » ne tient pas dans le
bouton.

**Vérifié** : chemin de pick live sur 3 hôtels réels (Ibis 7720, Mercure 9075, Villa 22293) →
`ok=True`, formules + liens + remises réelles (−10 % à −37 %) ; normalizer de la feuille en live ;
composant rendu et screenshoté (**27 assertions** + **11 assertions** dédiées aux deux formes
réelles, dont clics). Gates : **pytest 1 097 ok**, ruff, mypy, guardrails.

**Piège** : MCP renvoie **429 Too Many Requests** si on enchaîne les `get_hotel_details` sans pause
— tout probe d'échantillon doit espacer les appels (~1,5 s) et ouvrir une session par hôtel.

**Reste** : e2e via les 3 services jamais relancé ; format horaire AM/PM du carrousel toujours
ouvert ; enum `offerType` non exhaustif (échantillon 51 hôtels, valeur inconnue → créneau).

## 🧾 Addendum 2026-07-28 (branche `scx8-rateplan-selector`) — S-CX8 : sélecteur de rateplan + « à partir de »

**Demande Fabien** : (1) la carte résultat doit dire « à partir de » sur son prix (c'est le
rateplan le moins cher, présenté comme LE prix) ; (2) après un pick, présenter les différentes
formules avec prestations/prix et un lien tunnel par formule. Artefact de 3 propositions publié
(`claude.ai/code/artifact/cf5457e0-5da8-4bba-a774-df30e19c58a0`) → **option A retenue** (sélecteur
intégré à la booking card), 4 points client cochés : prestations, type de chambre, remise vs nuit,
annulation gratuite.

**Fait (gates verts : pytest 1091 ok / ruff / mypy / guardrails)** :
- **`inline_tools.py`** : `_rate_plan_view` + `_day_rate_plans` (toutes les formules d'UN jour,
  dédupées, prix croissant, cap `_MAX_RATE_PLANS = 6`) et `_quote_picked_rate_plans` — appelé
  UNIQUEMENT sur le tour de pick, **liens générés en parallèle** (`asyncio.gather` sur une seule
  session MCP : le SDK multiplexe par `request_id`, vérifié dans `BaseSession.send_request`).
  `_hotel_facts` extrait (partagé avec `_quote_fresh_offer`).
- **Règle centrale** : le plan **présélectionné est celui que la carte du carrousel affichait**
  (`offer_id` de `last_results`), pas le moins cher du jour — sinon le prix saute entre carrousel
  et carte, ce qui se lit comme un appât même quand c'est moins cher.
- **Dégradations, toutes vers le chemin mono-offre existant** : `get_hotel_details` en échec, aucun
  plan, ou lien du plan sélectionné en échec → `{"ok": False}` → `_quote_fresh_offer` inchangé. Un
  plan dont le lien échoue est **retiré** de la liste (une ligne sélectionnable non réservable est
  pire qu'une ligne absente). ≤ 1 plan → pas de clé `rate_plans` du tout.
- **Widget** : `renderRatePlans` dans `messages.js` (lignes radio, sélection 100 % client-side —
  les liens sont déjà générés, donc zéro tour de chat), CSS `.booking-card__plan*` dans
  `hotels.css` (lignes outlined ; le gradient warm reste réservé à l'unique CTA du tunnel),
  « à partir de » sur la carte résultat + « dès €X » sur les pastilles de pick, 20 clés i18n × 7
  langues.

**⚠️ Ce que les probes live ont changé dans la conception** (probes : `get_hotel_details` sur
4 596 offres réelles / 51 hôtels + snapshot catalogue prod 22 177 rate plans) :
- **`offerType` est le seul vrai différenciateur** — enum fermé (`dayuse.day` 72 %,
  `late_break` 13 %, `early` 11 %, `dayuse_pm` 3 %, `dayuse_am` 0,7 %), traduit côté widget
  (« Journée / Soirée / Matinée… »). **Le sélecteur fonctionne donc dès maintenant, sans MCP.**
- **`rate_plan_name` NE PEUT PAS titrer les lignes** : c'est le nom de la CHAMBRE, en langue libre
  du partenaire, et **2 829 / 5 591 hôtels multi-formules donnent le même nom à toutes leurs
  formules** (« Standard Double Room » ×3). Gardé dans le contrat, jamais en titre.
- **`room_type` est NULL sur 22 177 / 22 177 lignes** → retiré de la demande MCP ; remplacé par
  `bedding` + `capacity`, peuplés (« Lit double · 2 personnes »).
- **`addons_included` : 4,6 % de remplissage** → prestations rares. Rendu prêt, aucune dépendance.
- **`original_price` : 98,8 % en base, absent de MCP** → **seule demande du prompt MCP**
  (`reports/PROMPT-MCP-B2C-RATEPLANS.md`, réécrit après probes). Corollaire :
  `computeNightDiscount` (`card.js`) est **du code mort en prod depuis toujours** — aucun chemin
  AgentB2C ne remplit `original_price`.
- **64 % des hôtels ont 2+ formules** → concerne la majorité du parc.

**Vérifié** : chemin de pick complet **en live contre le vrai MCP** (hôtel 22293 → `ok: True`,
3 formules, 3 liens tunnel réels générés en parallèle). Composant rendu **hors navigateur puis
screenshoté** en headless Chrome, 23 assertions dont un clic réel simulé (sélection → href, label
CTA, créneau, prix, `data-booking-url`) et le passage par le sanitizer `sanitizeTrustedHtml`.
**Non vérifié** : tour e2e via les 3 services (`smoke_e2e.py` non relancé — services locaux de
Fabien laissés en place, pas redémarrés).

**Un test amendé, délibérément** : `test_spine_profile.py::test_the_cheapest_is_picked_from_the_
screen_never_re_searched` exigeait l'ABSENCE de `get_hotel_details` sur un pick (S-CX5 : réutiliser
l'offre du carrousel, zéro aller-retour). Les formules sœurs n'existent nulle part en état de
session → un lookup devient inévitable. Ce que la décision achetait est toujours asserté : aucune
2e recherche, et l'offre réservée reste celle de la carte. Alternative écartée (porter tous les
rate plans dans le payload de recherche) : taxe le tour search critique en TTFT pour une donnée
que seul un pick consomme, et le filtre de fenêtre de la feuille afficherait une liste tronquée.

**Corrigé au passage** (exposé par le rendu réel) : `formatCardDate`/`formatRating` passaient
`undefined` en locale → **locale de l'OS et non langue du chat** : carte fr affichant « Wed, Jul
29 » et « 4.6/5 ». Corrigé en `getLanguage()` (le commentaire de `formatRating` promettait déjà
« 4,7 in fr »).

**Trouvé, NON corrigé** : `renderTimeslots` (`card.js`) affiche les créneaux en **AM/PM dans les 7
langues** (« 10:30am – 4pm » sur une carte fr, alors que la booking card montre « 10:30 – 16:00 »).
Faux pour fr/es/it/de/nl. Correction = décision produit + touche tout le carrousel → session dédiée.

**Reste** : lancer le prompt MCP (`originalPriceEuro`) ; décider du format horaire ; e2e via les 3
services ; éventuellement exposer l'enum `offerType` exhaustif (mon échantillon = 51 hôtels, une
valeur inconnue dégrade vers le créneau).

## 🎫 Addendum 2026-07-28 (soir, PR #47 mergée + déployée) — SCX6 : la confirmation ÉCRITE atteint la gate R9

**Repro Fabien post-rollout OBS1** : « oui je confirme » répondu par le template d'accueil — le lien
jamais généré. Cause (pas une régression du deploy) : `is_booking_confirmation_signal` n'acceptait
qu'un affirmatif NU ; toute phrase explicite (« je confirme », « yes I confirm ») partait au triage
→ template. Fix : `_CONFIRMATION_RE` (verbes confirm/valide/réserve/book/vas-y) consulté SEULEMENT
sous `pending_booking`, gardes négation+question (un faux positif générerait le lien).
`_AFFIRMATIVE_RE`/`is_bare_affirmative` inchangés. **Vérifié en prod** (widget proxy, tours
synthétiques) : confirmation tapée → booking_card + lien ; refus → pas de lien.

**Décision produit OUVERTE** : `build_hotel_picks` (facade.py, règle S-CX5 du 27/07) n'offre les
boutons de pick que si destination ET date sont résolues — une recherche SANS date affiche le
carrousel mais zéro bouton (c'était l'autre moitié du « la feature a disparu »). Afficher les picks
quand la date est défautée à aujourd'hui = 1 ligne, à trancher par Fabien.

**Rollout OBS1 fait le même jour** : 3 services déployés (main c0a8fdc puis fcf6f96), variables
LANGFUSE posées par Fabien (env=production), tracing vérifié en prod (session `obs1-deploy-check-01`,
zéro erreur d'export). Piège CLI : `railway variables` (pluriel) — le singulier sort du vide silencieux.

## 🔭 Addendum 2026-07-28 (branche `obs1-langfuse-tracing`) — OBS1 : Langfuse (monitoring + audit des conversations)

**Contexte** : zéro canal d'observabilité actif en prod (pas de `DATABASE_URL` → `llm_metric_events`/
`conversation_logs` no-ops). Fabien veut auditer les échanges users via son Langfuse self-hosted
Railway. **Gate version vérifié AVANT d'implémenter : aucune mise à jour serveur requise** —
l'instance (projet Railway `Langfuse`) tourne en **v3.205.1, région europe-west4 (EU ✅ RGPD)**,
URL `https://langfuse-web-production-272b.up.railway.app` ; le SDK Python v4 exige serveur ≥ 3.63.0
et l'ingestion OTel existe depuis 3.22.0. Langfuse serveur v4 n'existe qu'en RC (4.0.0-rc.3) —
migration à faire dans une session dédiée quand la stable sortira (ClickHouse 24 → ≥ 25.12 requis,
instance partagée avec d'autres producers Dayuse, ~½ journée). Refresh mineur v3.224.2 possible à
l'occasion (redeploy web+worker, le tag `:3` flotte).

**Fait (offline — gates verts : pytest/mypy/ruff/guardrails)** :
- **`libs/b2c_common/b2c_common/observability.py`** (la seule couture) : `setup_langfuse(service)`
  — opt-in sur `LANGFUSE_PUBLIC_KEY`+`SECRET_KEY`, **inerte sans les clés** (aucun import langfuse,
  aucun réseau — la suite offline entière verrouille ce chemin) ; `turn_observation(...)` (span
  racine de tour, input=message user, output=texte final, session/user/tags propagés) ;
  `stamp_langfuse_session` (callback feuille : `dayuse_trace_id` A2A → `langfuse.session.id`) ;
  `shutdown_langfuse` (flush via lifespan `to_a2a`).
- Choix vérifiés dans le code installé : SDK **langfuse==4.14.1** (provider OTel GLOBAL → les spans
  ADK `gcp.vertex.agent` s'activent, filtre `should_export_span` élargi sinon le span `invocation`
  sans attributs serait droppé) + **openinference-instrumentation-litellm==0.1.34** (patch d'attribut
  module : couvre triage `litellm.acompletion`, synthèse Router ET le LiteLlm des feuilles ; le
  callback natif litellm `langfuse_otel` REJETÉ — écrase le span parent + 2e pipeline privé en
  1.90.2) + `opentelemetry-exporter-otlp-proto-http==1.42.1` (cap google-adk ≤ 1.42.1, pas de
  conflit pip). litellm reste pinné 1.90.2.
- Branchements : `serve.py` ×3 (init + lifespan flush ; **feuilles : init AVANT l'import agent** —
  lite_llm bind `acompletion` à l'import) ; `facade.py` chat + chat_stream (span racine par tour,
  TTFT intact : export batch en arrière-plan, vérifié par smoke enabled offline) ; `_get_leg`
  envoie `a2a_request_meta_provider={"dayuse_trace_id": ctx.session.id}` (bonus : remplit le
  trace_id des métriques fleet) ; callbacks feuilles + READMEs + `.env.example`.
- Tests neufs : `libs/b2c_common/tests/test_observability.py`, concierge
  `test_facade_langfuse.py`, cas leg dans `test_leaf_timeout_budgets.py`. Locks RGPD S3 inchangés
  (contenu → Langfuse EU self-hosted = canal d'audit sanctionné, miroir de conversation_logs ;
  métriques/logs `b2c_concierge.*` toujours sans contenu). Tag `synthetic` via X-Dayuse-Synthetic.

**Smoke local VALIDÉ avec les vraies clés (2026-07-28, revue Fabien)** — 3 corrections attrapées :
traces feuilles nommées + input (le span racine ADK `invocation` est sans attributs → stamps
`langfuse.trace.*` posés depuis le callback feuille) ; sessions complètes aussi en pilotage A2A
(smoke/batterie : `stamp_langfuse_turn_session` sur le spine, idempotent avec la façade) ; **usage
compté 3x corrigé → 1x** (`ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN=2` retire `call_llm` ;
`instrument_litellm=False` dans les feuilles où `generate_content` est LA génération). Vérifié :
`smoke_e2e.py` (A2A) + `smoke_e2e.py --contract` (/v3), zéro erreur d'export.

**Reste** : poser `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY`/`LANGFUSE_BASE_URL`/
`LANGFUSE_TRACING_ENVIRONMENT=production` sur les 3 services Railway → redeploy → vérifier un tour
réel. Sans les clés, le code déployé est inerte (aucun risque).

**Pièges découverts** : (1) `to_a2a` annote `lifespan` comme `-> AsyncIterator` mais le consomme en
`async with lifespan(app)` — il FAUT `@asynccontextmanager` + `type: ignore[arg-type]` (la docstring
ADK elle-même utilise le décorateur). (2) **litellm fait `load_dotenv()` à l'import** : tout secret
du `.env` racine entre dans CHAQUE process python du repo, pytest compris — avec de vraies clés la
suite exportait pour de vrai et gelait (double shutdown du client langfuse via les lifespans
TestClient). Verrou : `conftest.py` racine neutralise les clés (chaîne vide, `load_dotenv` n'écrase
pas l'existant) + les lifespans font `flush()` jamais `shutdown()` (le client langfuse possède son
shutdown atexit). (3) **Pré-existant sur main** : `tests/test_llm_meter_usage.py::
test_usage_record_extracts_tokens_and_model` échoue (round(432.15,1)=432.1 en IEEE754 vs 432.2
attendu) — WIP llm-meter balayé par erreur (cf. commit d157323) ; hors scope OBS1, à corriger ou
supprimer dans sa propre session.

## 🖥 Addendum 2026-07-28 (branche `sperf4-widget-sse`) — S-PERF4 : widget en SSE, rendu hotels-first (chantier #1 de la roadmap latence)

**Objectif atteint** : le widget ne fait plus un POST bloquant de 8-11 s. En transport `sse` il lit
`/v3/chat/stream` et **rend le carrousel dès la frame `hotels`**, le texte à `done`.
Mesuré au facade (`measure_latency_e2e.py`, 3 runs, stack locale 4o-mini) :
search `hotels=3776 ms` vs `done=8649 ms` → **4,9 s d'avance** ; refine 3266 vs 7244 → **4,0 s**.
Mesuré DANS le navigateur (Chrome headless piloté en CDP) : cartes visibles 2,3-3,8 s avant que le
tour se termine, `progress` à 1-8 ms.

**Fait**
- **`web/vendor/static/js/chat/stream.js`** (NOUVEAU, ~80 l) — transport SEUL : `openChatStream()`
  (fetch POST — EventSource ne POST pas) + `readSseFrames()` (générateur async, `getReader()` +
  `TextDecoder`, split sur ligne vide, frame illisible ignorée sans tuer le tour). Aucun rendu ici.
- **`handlers/send.js`** — `buildRequestBody()` extrait (même payload pour les 2 transports),
  `makeApiCall(requestBody)` (retry ×3 inchangé), `mapV3Hotels()` extrait de `normalizeV3Response`
  (source unique du mapping hôtel→carte, utilisée par la frame ET par `done`), `renderHotelsEarly()`
  + `runStreamedTurn()`. À `done` le payload repart dans le pipeline EXISTANT (`normalizeV3Response`
  → handlers) avec le seul flag `skipCarousel`.
- **`handlers/responses.js`** — `buildResultsBlock` / `updateMarketFromResults` exportés ;
  `handleResultsResponse(data, hasTimeslotRequest, skipCarousel=false)` : en `skipCarousel` seul le
  texte d'intro est ajouté (pas de 2e carrousel, pas de `scrollIntoView` qui remonterait les cartes
  hors écran). **Zéro changement de comportement pour le chemin JSON** (défaut `false`).
- **Flag** : meta `du-chat-transport` (`chat_clean.html`, défaut **`json`** = comportement actuel),
  substituée par `run_widget_proxy.py` via **`WIDGET_CHAT_TRANSPORT=sse`** (lu par requête → flip
  sans redeploy JS). Endpoint dérivé comme `getWelcomeEndpoint` : `/v3/chat` → `/v3/chat/stream`.
- **Fallback** : échec d'OUVERTURE du stream → POST bloquant pour CE tour. **Jamais de re-send si
  une frame a déjà été consommée** (`framesSeen > 0` → l'erreur remonte, pas de double tour).
- **Tracking ADDITIF** : `latency_ms` garde sa sémantique time-to-done ; ajout de `ttft_ms`
  (frame `progress`), `hotels_ms`, `transport` (`sse` | `json` | `json_fallback` — le fallback est
  visible sans nouvel event Amplitude). `chat_request_failed` porte aussi `transport`.
- **2 divergences réelles trouvées et corrigées (Python, additif)** — la frame `hotels` ne portait
  que `hotels`, donc un client hotels-first devait deviner :
  1. `requires_clarification` — sans ça un tour de clarification AVEC shortlist aurait peint des
     cartes que le POST bloquant retient (il `return` avant le switch). Verrouillé par test.
  2. `response_language` — **bug visuel constaté en capture** : les cartes se peignaient en anglais
     (langue de boot de la page) puis le texte arrivait en français. `setLanguage` ne tournait qu'à
     `done`. Le spine met maintenant la langue du tour sur son marqueur (`_hotels_event(ctx,
     response, language)`), le facade la relaie, le widget localise AVANT de rendre. Vérifié en
     capture avant/après.
- **`ui/thinking.js`** — `createThinkingSteps` renvoie en plus `relocalize()` : la bulle « thinking »
  reste à l'écran SOUS les cartes pendant la synthèse (ce widget n'a **pas** d'élément
  `#typing-indicator` — `showTypingIndicator()` y est un no-op, vérifié), donc son texte doit
  pouvoir se re-localiser après le switch de langue. Aucune string user-facing nouvelle (7 locales).

**Vérification (captures navigateur, leçon scx5b)** — pas d'infra de test JS : driver CDP
(`websockets` + `Page.captureScreenshot`, deep-link `?q=` qui auto-envoie, clics via
`Runtime.evaluate`), matrice **{ack, search, refine, pick→booking card, clarification, faq, empty} ×
{sse, json, json_fallback}** + 2 flux SSE scriptés (`done` dégradé mi-stream, stream tronqué sans
`done`). Résultats : exactement **1 carrousel par tour** dans les deux transports (compté en delta
DOM), chips/pick buttons/follow-up intacts, `done` dégradé après cartes ⇒ cartes conservées + message
honnête dessous, stream tronqué ⇒ `generic_error` + **aucun re-send**. 4 captures clés commitées dans
`reports/latency/widget-sse-2026-07-28/`. Tests/ruff/mypy/guardrails verts (seul rouge :
`test_llm_meter_usage`, **préexistant sur main**, bug d'arrondi du test).

**Choix assumés (à trancher en review)**
- **Le texte de synthèse arrive SOUS les cartes** en mode `sse` (JSON = intro au-dessus, inchangé).
  Séquence chat : cartes → bulle thinking → texte. Alternative écartée : injecter l'intro dans le
  message des cartes à `done` (DOM final identique au JSON) — ça déplace la vue pendant la lecture.
- Les frames `token` sont **ignorées** (pas accumulées) : rien à rendre, le texte complet est dans
  `done`. Le streaming token réel reste le chantier #9, déféré.

**Reste / pièges**
- **Déploiement (Fabien)** : après merge, poser `WIDGET_CHAT_TRANSPORT=sse` sur le service `widget`
  + redeploy. Le pré-requis `read1` est déjà en prod (probé). Rollback = retirer la var.
- **Si un jour le widget est servi par l'app Dayuse** avec un endpoint `/v3/chat/public`, le stream
  devient `/v3/chat/stream/public` : cette route doit exister côté hôte (le facade AgentB2C n'expose
  que `/v3/chat/stream`). Sur la démo Railway le proxy force `/v3/chat` → non concerné.
- Le worktree local a été installé **sans `google-adk[eval]`** (résolution uv impossible :
  `google-cloud-aiplatform[evaluation]` veut `litellm<1.83.7`, le repo pin `1.90.2`). Tests/lint/
  typecheck/run OK ; `adk eval` non lancé cette session.

## ⏱ Addendum 2026-07-28 (soir, branche `sperf3-temp-reasoning-collision`) — rollout S-PERF déployé + collision temperature×reasoning attrapée en live (mitigée, fix en PR)

**Rollout exécuté (GO Fabien)** : PRs #41/#42/#43 mergées, env posées (concierge
`DAYUSE_MODEL_TRIAGE=gpt-4o-mini` + `DAYUSE_REASONING_EFFORT=low`, feuilles `DAYUSE_MODEL=gpt-4o-mini`),
4 services redéployés. **Le fix read1 du proxy est vérifié EN PROD** : frames SSE séparées à travers
l'edge Railway (probe chunk-par-chunk : progress 149 ms, hotels 3,7 s en chunk propre, done ensuite).

**⚠️ Attrapé en live juste après le déploiement** : la réponse d'un tour search était le texte
OUTCOME de la feuille, pas de la prose — `railway logs` : **chaque synthèse échouait en
`UnsupportedParamsError` → fallback leaf-verbatim silencieux** (`status=synthesis_fallback` sur tous
les tours search/faq). Cause reproduite localement : litellm côté CLIENT rejette
**`temperature` + `reasoning_effort≠none` ENSEMBLE sur gpt-5*** (« Only temperature=1 is supported…
temperature is supported when reasoning_effort='none' ») — chaque param seul passe, et
temp+effort='none' passe. Mon probe pré-rollout n'envoyait PAS temperature → il a validé un shape
d'appel qui n'était pas celui du code (leçon ajoutée à tasks/lessons.md).

**Mitigation appliquée immédiatement (env, réversible)** : `DAYUSE_MODEL_SYNTHESIS=gpt-4o-mini` sur
concierge + redeploy — le levier prévu par le rapport. Vérifié live : vraie prose de synthèse de
retour (« J'ai trouvé 5 offres d'hôtels en journée à Paris pour demain : … »).

**Fix code (cette branche)** : `b2c_common.llm_params.temperature_kwargs_for` — temperature cède au
cap de reasoning UNIQUEMENT sur la combinaison illégale (gpt-5* + effort≠none), conservée partout
ailleurs (probé : 4o-mini, openrouter, effort='none'). Branché sur les 2 call sites ; no-op env non
posées verrouillé (temperature 0.0/0.2 inchangées). Contre-preuve live : `_generate_once` via Router
sur gpt-5.2+low → texte réel (le code déployé → None). Une fois mergé, `DAYUSE_MODEL_SYNTHESIS`
peut être retiré pour re-tester la synthèse 5.2 cappée.

**Chiffres POST-rollout mesurés (démo Railway, config mitigée, 5 runs — étalon
`reports/latency/baseline-railway-gpt52.jsonl`)** : voir bloc résultats dans la conversation de
session ; ordre de grandeur : search p50 10,6 s → ~3,4 s, faq 24,9 s → ~8,4 s, progress ~60-90 ms
sur tous les tours (les runs 1 post-deploy portent le cold start). À re-mesurer après merge du fix
si Fabien re-bascule la synthèse sur 5.2+low.

## ⏱ Addendum 2026-07-28 (branches `sperf0-latency-audit` / `sperf1-model-roles` / `sperf2-a2a-diet`) — S-PERF : audit latence complet + 3 quick wins (« l'agent est devenu plus lent »)

**Contexte** : ressenti Fabien post-merges S-CX. Audit demandé (archi async, thinking mode, toute
piste). Décisions Fabien (AskUserQuestion) : mix modèle par rôle ; bascule SSE widget incluse au
chantier (roadmap) ; livrable = quick wins + rapport. **Rapport complet :
`reports/AUDIT-LATENCE-2026-07-28.md`** (sur sperf0) — causes, mesures, roadmap 9 chantiers.

**Diagnostic (tout mesuré)** : (1) **Railway tourne en gpt-5.2 sur les 3 services** (confirmé
`railway variables`), zéro cap de reasoning, zéro max_tokens — search p50 10,6 s, faq 21-36 s ;
(2) **latence perçue = tour entier** : widget en POST bloquant ET le widget-proxy bufferisait le SSE
en un burst (read(4096) sur upstream chunké — progress=hotels=done à la ms près) alors que le facade
streame à 2-6 ms ; (3) **prompt feuille croissant par tour** : RemoteA2aAgent rejoue toute la session
(condition d'arrêt jamais satisfaite) + DataPart profil persisté dans l'event muté + shortlist S-CX5
passé à 14 clés → 4 353 → 5 813 tokens entre tour 2 et 3 ; (4) prompt triage +65 % (27/07), prompts
fixes feuille ~4,3k tokens ×2/tour.

**Fait** :
- **sperf0** : `scripts/measure_latency_e2e.py` (5 tours scriptés sur /v3/chat/stream, p50/max par
  frame, JSONL) ; **fix P0 : widget-proxy `read` → `read1`** (vérifié avant/après : progress
  9 581 ms → 2 ms) ; baselines Railway gpt-5.2 + locale 4o-mini dans `reports/latency/` ; rapport.
- **sperf1** : `b2c_common.llm_params` — `role_model` (`DAYUSE_MODEL_{ROLE}` > `DAYUSE_MODEL` >
  4o-mini), `reasoning_kwargs_for` **provider-aware** (le `reasoning_kwargs` de la fleet est shape
  OpenRouter → 400 sur slug OpenAI-direct ; **probé live sur gpt-5.2 : `low` 200, `none` 200,
  `minimal` 400** — le floor a changé depuis gpt-5.0), `max_tokens_for` (triage 200, synthèse 1000,
  0=off) ; branché sur les 2 seuls appels LLM du concierge (triage.py, `_generate_once`) + label
  `reasoning_effort=` sur les métriques. **No-op strict env non posées (verrouillé par test).**
  Feuilles : zéro code (services Railway séparés → `DAYUSE_MODEL` par service suffit au mix).
- **sperf2** : `leg.py::StatelessLeafLeg` (message A2A = SEUL l'event user du tour courant ;
  contre-preuve : 10 parts → 2 sur une session de 3 tours ; pin-guard sur la méthode privée ADK) ;
  `profile.py::leaf_profile_view` (la COPIE A2A : last_results → {hotel_id, name}, 8 clés
  concierge-only droppées dont `last_clarifying_question`/`last_suggestions` — minimisation RGPD ;
  Redis/carte/picks intouchés, verrouillé) ; `include_contents="none"` sur les 2 feuilles (sémantique
  ADK vérifiée : tour courant + paires tool call/réponse).

**Vérifié LIVE (stack locale, gpt-4o-mini, MCP staging)** : smoke défaut / `--conversation` /
`--contract` / `--booking` **PASS ×4** (lien tracké réel au confirm — R9 intact) ; **prompt_tokens
feuille PLAT** (tour refine 5 813 → 4 347, croissance supprimée) ; battery 32 scénarios ancien vs
nouveau : moyenne main 2,19 vs sperf2 **2,28** (6 scénarios en hausse, 1 flip négatif isolé = variance juge ; score absolu bas PRÉEXISTANT, juge strict — hors scope), budget ≤3 LLM/tour : 0 dépassement des deux côtés.

**DoD** : pytest **1027 passed** (+ le seul rouge préexistant `test_llm_meter_usage`, bug d'arrondi
du test, hors zone) ; ruff OK ; mypy 41 fichiers OK ; guardrails OK. Tests clés vérifiés en échec
sans leur fix (leg parent vs subclass ; to_dict vs leaf_profile_view).

**Rollout env Railway proposé (après merge, GO Fabien)** : concierge
`DAYUSE_MODEL_TRIAGE=gpt-4o-mini` + `DAYUSE_REASONING_EFFORT=low` ; hotel-search + faq
`DAYUSE_MODEL=gpt-4o-mini` ; redéployer `widget` (fix read1). Levier sans code si besoin :
`DAYUSE_MODEL_SYNTHESIS`. Attendu : search ~10,6 → ~6-7 s, faq 21-36 → ~13 s. Re-mesurer avec le
script (baselines = l'étalon).

**Pièges découverts** :
- `HTTPResponse.read(amt)` sur un upstream chunké BLOQUE jusqu'à amt octets — tout proxy de SSE doit
  lire en `read1`. Le passthrough de l'edge Railway reste à re-vérifier après redéploiement du widget.
- Le plugin mypy pydantic synthétise un `__init__` fields-only pour un subclass d'agent ADK sans
  `__init__` explicite → passthrough `*args/**kwargs` requis (leg.py).
- `reasoning_effort` : le vocabulaire OpenAI a changé entre générations (minimal → none/xhigh) — ne
  jamais mapper sans probe, passer verbatim pour échouer bruyamment.
- La battery juge à 2/5 un « quelle ville ? » sur « près de moi » SANS geo_context — calibrage juge à
  revoir (hors scope latence).

**Merge** : 3 PRs indépendantes (sperf0/sperf1/sperf2), review Fabien = gate. Rollout env = action
dashboard Fabien (ou GO explicite).

## ⏱ Addendum 2026-07-27 (branche `scx5b-widget-card-fixes`, sur `main`) — S-CX5b : 3 défauts UI de S-CX5 remontés par Fabien sur le démo déployé

**Contexte** : Fabien teste le démo Railway après le merge de S-CX5 (3 screenshots) et remonte (1) le bouton de la carte de réservation est **rogné**, et il veut une carte à **taille fixe** comme l'artefact ; note hôtel affichée `4.666666666666667/5` ; (2) sur les cartes du carrousel, le bouton dit « Réserver » alors qu'il ouvre la **fiche hôtel**, pas le tunnel ; (3) un clic sur un chip de créneau **fait disparaître les boutons de choix d'hôtel**, donc la route en 1 clic vers la carte de réservation.

**Tout est dans le widget vendored (`web/vendor/**`) — zéro changement backend.**

**Causes racines (mesurées, pas devinées)** :
1. **Bouton rogné** — `.booking-card__cta` est un `<a>`, donc il n'hérite PAS du `box-sizing: border-box` que la feuille UA donne aux `<button>` (c'est pourquoi `.book-button`, lui, n'a jamais eu le bug). Cette CSS n'a **aucun reset global** : `width: 100%` + `padding: 12px 22px` en content-box → CTA **412 px dans une boîte de contenu de 368 px**, et l'`overflow: hidden` de la carte coupait le label. Mesuré avant fix : `boxSizing: "content-box"`, `overflowPx: 44`.
2. **Label trompeur** — le `href` du bouton de carte de résultat est `hotel.url` (fiche hôtel). Seul le CTA de la carte de réservation part vers le tunnel. Même défaut sur la carte inline `[CARTE:]` de `messages.js`.
3. **Chips de choix disparus** — la branche « filtre par créneau » de `runSearchWithFilters` filtre `state.previousResults` **dans le navigateur** (aucun tour serveur) et faisait `return` **avant** `addFollowUpMessage()`. Les pick buttons partaient avec.

**Fait (4 fichiers)** :
- `hotels.css` — `box-sizing: border-box` sur `.booking-card` / `__body` / `__cta` ; `max-width: 400px` → `width: 400px; max-width: 100%` (taille fixe en desktop, rétrécit en mobile). Commentaire en place pour que le prochain ne re-tombe pas dans le piège du reset absent.
- `messages.js` — `formatRating()` : une décimale dans la locale du lecteur (`4,7` en fr). ES fait transiter la moyenne brute (`globalAverageRating`), c'est une correction d'AFFICHAGE, la valeur reste intacte en amont.
- `card.js` + `messages.js` — les 3 boutons qui ouvrent la fiche hôtel utilisent `card_see_hotel` (« Voir la fiche de l'hôtel »), déjà traduit dans les 7 locales. Clé `see_details` désormais inutilisée, laissée en place.
- `search.js` — la branche client-side dessine à nouveau la ligne de suivi, avec les picks **restreints aux hôtels encore à l'écran** (`pickButtonsHtml(allowedHotelIds)`) : un bouton pour un hôtel filtré hors carrousel réserverait quelque chose d'invisible. Les picks serveur restent valides — la shortlist en session n'est pas touchée par un filtre navigateur, donc `pickHotel(id)` résout toujours.

**Vérifié en NAVIGATEUR (Chrome headless, CSS réelle + vrais modules ES servis en HTTP, avant/après sur le même harnais)** :

| | avant | après |
|---|---|---|
| débord du CTA | **44 px** (rogné) | **0 px** |
| largeur carte | 402 px | **400 px** |
| note | `4.666666666666667/5` | `4,7/5` |
| pick buttons après chip créneau | **0** | **1** (`data-action="pick-hotel"`, restreint à l'hôtel 1/1 filtré) |
| label bouton carte | `Réserver` | `Voir la fiche de l'hôtel` |

Cas mobile vérifié aussi (colonne 330 px → carte 280,5 px, débord 0).

**DoD** : `pytest -q` → **1013 passed** (même unique échec préexistant `test_llm_meter_usage`, **confirmé rouge sur un arbre stashé** — hors zone, aucun code Python touché) ; guardrails OK ; les 3 JS touchés passent `node --check`.

**Pas fait, délibérément** : l'artefact montrait aussi un badge « Annulation gratuite » et un avis « Réservable jusqu'à 15:00 aujourd'hui ». Ces champs n'existent pas dans le payload `booking_card` (le dict d'identité de `inline_tools.py` est construit depuis l'offre, sans politique d'annulation ni heure limite) — c'est un changement backend + une demande de champ à MCP_B2C, hors scope de ce fix visuel.

## ⏱ Addendum 2026-07-27 (branche `scx5-booking-offer-identity`, **stackée sur `scx3a-price-cents` / PR #37**) — S-CX5 : 3 symptômes remontés par Fabien en session live + 1 P0 trouvé en creusant

**Contexte** : Fabien teste l'agent (2 screenshots, session Paris/fr) et remonte (1) « le moins cher » renvoie des hôtels PLUS chers, (2) le flow de réservation est trop long, (3) le lien brut au lieu d'une carte avec bouton. Design du (3) tranché par artefact + AskUserQuestion : cartes de résultat **INCHANGÉES** (pas de deep link tunnel depuis le carrousel — refus explicite de Fabien), choix par **boutons** façon chips, layout **L1**, copie **nom + prix**, tap → **directement la carte**.

**P0 trouvé en creusant, non signalé par Fabien** : la carte affichait €87 / 11:00-19:00 / **demain**, le lien réservait €90 / 17:00-23:00 / **aujourd'hui**. `_quote_fresh_offer` appelait `get_hotel_details` **sans la date de session** puis prenait `offers[0]`. **Probe live** (Paris J+3, 5 hôtels) : la date était fausse sur **5/5**, l'offre entière (prix + créneau + rate plan) sur **1/5**.

**Fait (4 commits)** :
1. **Identité de l'offre bout-en-bout** — `offer_id` (= `ratePlanUuid`, l'`offerId` du tunnel) + `offer_date` sur la carte (feuille ET inline), portés par `record_search_shortlist` avec prix/créneau/photo/rating. Le devis réutilise l'offre VUE sans round-trip MCP ; fallback (hôtel hors shortlist) = lookup **daté** + offre la moins chère **du jour** (jamais le minimum global : un `get_hotel_details` non scopé renvoie ~90 offres sur 32 jours, probé live).
2. **« le moins cher »** — 2 causes : (a) `capture_after_tool` excluait `shown_hotel_ids` sur TOUTE recherche alors que le curseur ne se réinitialisait que sur un changement de ville → la recherche censée classer par prix cachait les 5 moins chers ; (b) aucun tri prix n'existe côté MCP (`search_offers` n'a pas de param de tri ; le serveur classe availability .30/quality .25/**commission .20**/rpm .15/tier .10).
3. **Boutons de choix + carte récap** — 2 clés de contrat neuves (`hotel_picks`, `booking_card`) + frame SSE, renderer et CSS dans le widget vendored, strings dans les 7 locales.
4. **Widget** — pick buttons L1, clic → label en message + `hotel_id` dans le body.

**⚠️ Changement d'invariant à revoir : R9 / guard #12 REDÉFINI.** Un lien exige toujours un flag de confirmation explicite **code-owned** dans l'état du tour ; ce flag a maintenant 2 formes : (a) devis en attente + « oui » (inchangé), (b) une **sélection résolue** sur un tour classé booking. Rien n'est réservé dans les deux cas (le lien ouvre le tunnel, le paiement s'y fait) et la carte affiche hôtel/jour/créneau/prix à côté du bouton. Décision produit de Fabien ; restreindre (b) aux seuls clics de bouton = une condition d'une ligne.

**Correction de Fabien en cours de session (RÉCIDIVE)** : j'avais détecté « le moins cher » par **regex**. Or sa leçon du 2026-07-20 dit : le LLM déjà en place fait la COMPRÉHENSION, le code garde la DÉCISION. Refactor : le triage (1 appel LLM déjà fait chaque tour → **0 coût**) émet `pick` (enum fermée validée en code) ; `select_cheapest_hotel(last_results)` ne lit jamais le message (test verrouillant sa signature). Regex reléguée en `fallback_pick`, chemin LLM-down uniquement. **Mesuré** : sur 8 formulations, LLM 8/8, regex fausse sur 4.

**Vérifié LIVE** (stack locale, gpt-4o-mini, MCP staging) :
- Session de Fabien rejouée : tour 2 devise Villa Paris Orly €54 (la moins chère) **sans nouvelle recherche**, tour 3 lien `checkinDate=2026-07-28` + `offerId` de la carte. Avant : €90 / 17:00-23:00 / aujourd'hui.
- `hotel_picks` : 5 boutons du moins cher au plus cher ; clic sur le bouton **2** (ni le moins cher ni la position 1, avec 2 hôtels homonymes) → carte de CE hôtel.
- Un tour : « je veux réserver le moins cher » → carte complète (photo réelle, date, créneau, prix, lien tunnel), zéro « vous confirmez ? ».
- `smoke_e2e` défaut / `--contract` / `--booking` : **PASS**.

**Piège découvert (attrapé par le smoke, pas par les tests)** : j'avais retiré l'URL du texte quand une carte est émise. La carte voyage sur un **marker interne** que seule la façade lit — un consommateur **A2A** (harness d'éval, `smoke_e2e`) ne voit que le texte, et se retrouvait sans lien. Gardé dans le texte : le widget strippe déjà les URLs brutes quand une carte est présente (`handlers/send.js`).

**DoD** : **1011 passed** (+42 ; même unique échec préexistant `test_llm_meter_usage`, untracked, hors zone) ; ruff OK ; mypy 40 fichiers OK ; guardrails OK ; tout le JS touché passe `node --check`. Les 3 tests de non-régression clés ont été **vérifiés en échec sans leur fix** (un test vert des deux côtés ne prouve rien).

**Reste** : point 3 du plan (tri prix sur une recherche SANS shortlist — 1er tour) et point 4 (guard n°14 sur les superlatifs prix). Voir `tasks/todo.md`.

**Merge + déploiement (2026-07-27, sur instruction explicite de Fabien)** : tout est sur `main` (`69aa145`) et **déployé** sur le démo Railway. #36 mergée (portait scx1 + scx2, qui n'avaient aucune PR propre), #38 mergée (portait scx3a + scx5). **#37 fermée par accident** — supprimer la head de #36 a supprimé la base de #37, et GitHub refuse de rouvrir une PR dont la base n'existe plus ; ses commits sont bien dans `main` via #38 (vérifié par `merge-base --is-ancestor`), commentaire laissé sur la PR. #19 (s-d-judge-ab, 22/07, CONFLICTING) **non touchée**.

**Déployé et vérifié LIVE sur https://widget-production-3f56.up.railway.app** : 5 boutons de choix triés €54 < €58 < €60 < €70 < €72 ; clic → carte (Villa Paris Orly, 2026-07-28, 10:00-17:00, €54.00, photo) avec lien tunnel à la bonne date ; réponse **en français** sur une session française. Services redéployés : `concierge`, `hotel-search`, `widget` (`faq` inchangé, zéro diff).

**⚠️ SÉCURITÉ — à traiter** : le build Railway **imprime `FLEET_READ_TOKEN` (PAT GitHub) en clair** dans les logs (préfixe `github_pat_11BQDMTMY0hpq…`). Conséquence inhérente du build ARG (le builder Metal refuse `--mount=type=secret`, cf. addendum 2026-07-22) : Railway echo chaque ligne `RUN`. **Le PAT doit être révoqué et réémis**, et chaque build le re-fuite tant que le build ARG existe — vraie correction : vendorer `dayuse-agent-common` ou le publier sur un index privé.

**Corrigé après coup (2 erreurs de process, cf. `tasks/lessons.md`)** : mon 1er commit avait embarqué via `git add -A` 5 fichiers untracked d'une session S-B (dont le test llm-meter cassé) → `main` rouge ; `git rm --cached` les a détrackés sans les toucher sur disque (suite `main` = **1009 passed** vue d'un clone frais). Et un bug de langue trouvé sur le démo (session fr → réponse booking en anglais, parce que `profile.language` n'était jamais alimenté par le triage et qu'un clic de bouton envoie un LABEL sans marqueur de langue) corrigé + déployé.

## ⏱ Addendum 2026-07-27 (branche `scx3a-price-cents`, stackée sur `scx3-research-prix-plancher`) — S-CX3a : les signaux numériques survivent à la carte + **2 découvertes live qui changent le design de S-CX3b**

**Scope** : l'étape §8 du brief `phases/SCX3-prix-plancher-panier.md` qui ne dépend d'AUCUNE décision produit ouverte (les décisions §9 gouvernent 3b/3c, pas 3a). Aucun re-ranking, aucun changement de comportement client : uniquement des champs préservés sur la carte.

**Fait (3 fichiers source, 10 tests)** :
1. **`response_bridge.py::normalize_hotel` (feuille)** — `price_eur_cents` (int) à côté du `price` d'affichage `€X.XX` : jusqu'ici la chaîne formatée était le SEUL survivant de la normalisation (gap G-b2 de l'audit CX), donc rien en aval ne pouvait comparer un prix à un budget. Plus `rating_count` (le `totalReview` de MCP) et `relevance_score` (le `score` de MCP). Helper `_finite_float` neuf — délibérément PAS `_coord`, dont le clamp ±180 est un invariant de coordonnée qui avalerait un score légitime.
2. **`inline_tools.py::_normalize_hotel_for_display` (concierge)** — miroir `price_eur_cents` + `rating_count` (helper local `_price_eur_cents`, convention B3 déjà documentée dans ce fichier : chaque côté possède son petit helper de formatage, pas d'import cross-package). PAS de `relevance_score` ici : `score` est **search-only**, l'ajouter donnerait un None permanent.
3. **`tests/test_leaf_concierge_seam.py`** — lock de soudure réelle : `normalize_hotel` → `emit_search_datapart` → DataPart JSON → `decode_datapart` → `facade.normalize_hotels`, avec assertion `isinstance(int)` après le round-trip JSON. C'est la classe de bug exacte qui avait avalé `distance_origin` en S-G9 (chaque côté testait sa moitié).

**Vérifié LIVE (MCP staging, probe direct `search_offers`, 2026-07-27, Paris + New York)** : `totalReview` **populé 19/19 hôtels**. Le brief prévoyait « sinon v1 sans shrinkage, documenté » — pas nécessaire, le champ existe. Le probe a aussi imprimé la liste complète des clés hôtel du payload (`address`, `description`, `score`, `matchReasons`, `timezone` en plus de ce qu'on normalisait).

**⚠️ Découverte 1 — les compteurs d'avis sont MINUSCULES (2 à 10, jamais plus sur 19 hôtels)**. Conséquence directe sur la formule §3 du brief : avec `k≈20`, la shrinkage bayésienne écrase TOUT vers le prior (4.9 sur n=2 → ~4.54 ; 4.1 sur n=4 → ~4.43), la bande de `Q` se comprime à ~0,15 point, donc le **floor qualité relatif (`Q ≥ Q_max − 0.1`) admet tout le monde** et le re-rank dégénère en tri par prix pur — précisément le mode d'échec que la recherche (Airbnb KDD 2020) dit fatal à la conversion. `k=20` est à revoir (k≈3-5), ou `Q` doit s'appuyer ailleurs.

**⚠️ Découverte 2 — le « scoring hôtel » que Fabien voulait pondérer EXISTE déjà côté serveur, et il est DÉJÀ monétisé.** `search_offers` renvoie `score` par hôtel et `results` arrive **déjà trié** par ce score (`rankHotels`, même pondération que le `function_score` ES). Sa composition (`SCORING_WEIGHTS`) : availability **.30** / quality **.25** / commission **.20** / rpmV2 **.15** / tier **.10** — soit **35 % de termes commerciaux déjà dans le classement**. Deux implications pour 3b : (a) `Q = rating_shrunk/5` serait un proxy qualité bien plus faible que ce qui est disponible sur le fil ; (b) multiplier une proximité-budget sur un score qui contient déjà commission + rpmV2 **monétise le même clic deux fois** — le risque de chute de conversion documenté devient structurel, pas hypothétique. `hotel.scoringQuality` existe comme sous-score dédié côté MCP mais n'est PAS exposé : l'exposer serait une demande d'UN champ à MCP_B2C, très supérieure à une shrinkage maison sur n=3.

**DoD verte** : `pytest -q` → **957 passed** (+10 ; même unique échec préexistant `test_llm_meter_usage`, untracked, hors zone) ; `ruff` OK ; `mypy agents libs` 40 fichiers OK ; guardrails OK. Non testé en e2e LLM live (stack locale down) — le seam test couvre le chemin de la carte de bout en bout hors LLM.

**Piège découvert (unités — à lire avant d'écrire 3b/3c)** : `profile.budget_max` est en **EUR** (capté depuis l'arg `priceRangeMax` de `search_offers`, dont le schéma dit « in EUR, booking fees included ») alors que `priceEuro` / `price_eur_cents` sont en **CENTIMES**. Tout `r = prix / budget` exige un ×100 explicite ; l'oubli donne un ratio 100× faux, donc `proximity()` = 0 partout et un re-rank silencieusement neutre.

**Reste / décisions Fabien** : les 5 questions §9 du brief restent ouvertes, et les 2 découvertes ci-dessus en ajoutent une 6e, prioritaire — **sur quel signal de qualité 3b s'appuie-t-il** (score MCP composite tel quel comme baseline à modifier / demander `scoringQuality` à MCP_B2C / `starRating` + rating shrunk avec un k réaliste) — parce qu'elle décide si la formule §3 tient telle quelle.

### S-CX3c tenté dans la même session : **design réfuté en live, code retiré** (aucun mécanisme 3c sur cette branche)

**Ce qui a été essayé** : éviter le 2e appel MCP du brief (§5 item 1) en appliquant au prix la mécanique déjà bénie pour l'horaire (S-G6 : MCP reçoit le filtre GROSSIER, le code applique le vrai) — `priceRangeMax` envoyé à budget × 1,15, vrai budget stashé, split en code (in-budget d'abord, tail hors budget marqué `over_budget_gap_eur`, tri par écart croissant), disclosure fr/en, règle « additif jamais substitutif » dans le bloc ground-truth. Implémenté, 14 tests verts, ruff/mypy/guardrails OK. **Puis probé en live — et réfuté.** Le code est retiré (`git checkout`), la branche ne contient QUE S-CX3a.

**Pourquoi (mesures live, MCP staging, Paris + New York, 2026-07-27)** :
1. **Élargir le cap COÛTE des résultats dans le budget.** Paris, budget 71 € : cap dur à 71 → **10 hôtels in-budget** sur la page ; cap bandé à 81,65 → **7 seulement**, 5 in-budget perdus (55, 55, 55, 64, 64 € — exactement les options qu'un client au budget serré veut) contre 3 hors budget gagnés.
2. **Aucune taille de page atteignable ne les récupère.** `size` 10 / 12 / 15 → in-budget reste **7, 7, 7** pendant que le hors-budget monte 3 → 5 → 8. Changer `priceRangeMax` ne re-découpe pas une liste stable : ça change le POOL de candidats (521 hôtels à Paris), et les moins chers sortent de la fenêtre classée. New York (inventaire mince) récupère à `size=15` ; Paris jamais.
3. **`size` ≥ 16 = structuredContent VIDE, sans `isError`** (cliff exact : 15 OK, 16 vide). Un appelant qui monte la page lit un ZÉRO silencieux → « pas d'offres » sur un marché qui en a 521 = la fausse rareté de F2 par une autre cause. Le commentaire « max 50 » d'`inject_pagination_offset` (probe 2026-07-23) était FAUX — **corrigé dans ce commit**, seul changement de code qui survit du chantier 3c.
4. **La bande ne fait RIEN pour le cas de l'audit.** « max 10 € » : 0 résultat à 10 €, 0 à 11,50 € — le plancher marché Paris est 54 €, soit **5,4×** le budget. Une bande de +15 % ne peut structurellement pas l'atteindre ; nommer le plancher (« la moins chère est à 54 € », la phrase qui manque au dead-end de l'audit) exige un appel SANS cap.

**Leçon méthodo** : mon test unitaire `test_band_never_pushes_an_in_budget_hotel_off_the_page` PASSAIT — il partitionnait une page fixe. Il prouvait la partition, pas la page : le serveur renvoie une page différente quand le cap change, ce qu'aucun test offline ne peut voir. Tout changement d'ARGUMENT envoyé à MCP doit être vérifié en live avant d'être cru.

**Design corrigé pour la session S-CX3c dédiée** (à valider par Fabien) : garder le cap dur au vrai budget (c'est l'optimum pour les résultats in-budget, mesuré) et faire un **2e appel MCP, SANS cap, uniquement quand le premier renvoie 0** (dead-end réel, donc rare : latence là où on perdait la vente de toute façon, et c'est le seul chemin qui connaît le plancher, donc qui traite AUSSI le lowball). Obstacle technique identifié : `capture_after_tool` est **sync** (pas d'`await`) et un retour non-None court-circuite la suite de la chaîne after-tool — donc le probe plancher doit être un **nouveau callback `async` placé AVANT** `capture_after_tool` (il lit `tool_response` lui-même, stashe le plancher dans `state`), pas une modification de `capture_after_tool` (que ~40 tests appellent en synchrone). À vérifier d'abord : que l'ADK installé await bien un after_tool_callback coroutine mélangé à des callbacks sync. Le split/marquage/disclosure/règle ground-truth écrits cette session sont réutilisables tels quels une fois le producteur corrigé (perdus du working tree — les re-écrire est ~1 h, la valeur était dans la mesure).

**Merge** : PR #37 depuis `scx3a-price-cents` (stackée sur `scx3-research-prix-plancher` / PR #36 encore ouverte) — review humaine de Fabien = le gate.

## ⏱ Addendum 2026-07-24 (branche `scx3-research-prix-plancher`, stackée sur `scx2`) — S-CX3 deep dive : état de l'art « prix plancher / optimisation panier » — rapport seul, AUCUN code

**Contexte** : demande Fabien — « recherches pour savoir s'il existe déjà des méthodo, l'objectif étant d'optimiser le panier du client ». 4 recherches web parallèles (littérature ranking price-aware ; pratiques OTA + réglementaire UE ; budget comme point de référence ; effets d'ordre). **Livrables : `reports/RESEARCH-SCX3-PRIX-PLANCHER-2026-07-24.md`** (recherche complète sourcée, chiffres avec niveau de confiance, folklore débusqué — la citation menu-engineering « Parsa & Njite +6,8 % » n'existe pas dans Crossref) **+ `phases/SCX3-prix-plancher-panier.md`** (topo de cadrage autoporteur demandé par Fabien pour la session d'implémentation : conclusions, formule v1, pistes alternatives évaluées, ancres code, découpage S-CX3a..d, décisions ouvertes §9).

**Convergences clés** : (1) re-ranker par valeur SEULEMENT parmi les bons hôtels — quality floor (Jannach : ~50 % du gain revenu à coût de pertinence quasi nul, optimum intérieur) ; (2) ne jamais forcer le prix dans le ranking (Airbnb KDD 2020 : 2 tentatives, 2 reverts, −1,5 % bookings) ; (3) budget déclaré = prix de référence explicite → contrainte SOUPLE, kernel asymétrique (λ≈1,3-2), relaxation minimale EXPLIQUÉE (pattern Airbnb Flexible Matching) ; (4) ordre prix décroissant parmi les éligibles (+~4 % plafond, Suk JMR 2012, moins cher visible en position de bord) ; (5) bande hors budget +10-15 % = convention triangulée, PAS un chiffre primaire — à calibrer ; (6) lignes rouges UE (jamais masquer le moins cher, prix tout compris, pas de fausse rareté, pas de decoy).

**Formule v1 recommandée (§2 du rapport)** : `score = Q^β × proximity(r)^γ` (Q = rating shrinké dominant, kernel asymétrique σ_under=0.5/σ_over=0.25/τ=0.15, plancher 0.35 sous budget) + quality floor relatif (Q ≥ Q_max−δ) + cap de déplacement 2 positions + tri décroissant des éligibles ; fallback hors budget = re-probe sans cap → 1-3 offres triées par écart croissant, écart affiché sur prix all-in + ce qu'il achète, additif jamais substitutif.

**⚠️ Point technique critique (§3)** : la vérité terrain d'`eval_ranking.py` est la DISTANCE — le blend la fera mécaniquement baisser. Plan de mesure : NDCG@5-distance en GARDE + valeur panier simulée du top-3 en SÉLECTION (extension du script), puis A/B canary conversion+panier co-primaires (leçon Booking.com : l'offline ne prédit pas le business).

**Découpage implémentation proposé (§5)** : S-CX3a donnée (cents numériques sur carte) → S-CX3b re-ranker feuille (flag env, code-owned) ∥ S-CX3c fallback hors budget → S-CX3d mesure. Chaque étape mergeable indépendamment. **Rien n'est lancé — GO Fabien requis sur la formule et le découpage.**

**Piège découvert** : un agent de recherche a heurté la limite de dépense mensuelle de l'org en cours de route — ses 2 sous-agents avaient déjà livré ; synthèse faite sans relance. Vérifier `/usage-credits` avant les prochaines sessions à agents multiples.

**Merge** : PR depuis `scx3-research-prix-plancher`, base `scx2-mcp-truth-localized-fallbacks` (stack #33 ← #34 ← #35 ← celle-ci, merger top-down). Review Fabien = gate.

## ⏱ Addendum 2026-07-24 (branche `scx2-mcp-truth-localized-fallbacks`, stackée sur `scx1-facade-shield`) — S-CX2 : vérité MCP-down (fin de la fausse rareté) + jargon neutralisé + fallbacks localisés (fixes F2/F3/F5 de l'audit CX, GO Fabien)

**Contexte** : 2e branche du GO Fabien post-audit CX. Fixe F2 (MCP injoignable → « il n'y a pas d'offres à Marseille », mensonge reproduit 4/4), F3 (texte feuille anglais verbatim sur synthèse morte + jargon `mcp_guard` dans le contexte modèle) et F5 (localisation des textes de secours, ack anglais sur « ok » d'un client fr).

**Fait** :
1. **Vérité MCP-down, chaîne bout-en-bout (F2)** — signal déterministe côté feuille dans `emit_search_datapart` : tour SANS réponse search capturée ET (breaker déclenché ce tour [nouveau flag `_STATE_SEARCH_UNAVAILABLE_KEY`, posé par `capture_after_tool` sur `error=mcp_circuit_open`] OU anchor geocode stashé [geocode ok ⇒ l'instruction impose une recherche]) ET pas un tour clarify → DataPart `status="search_unavailable"` + texte honnête déterministe qui REMPLACE la prose du modèle (même mécanique que le clarify D3). Couvre : toolset MCP inénumérable (le cas Marseille — le breaker ne voyait RIEN passer), circuit ouvert, échec d'appel, budget tools épuisé avant la recherche. `skip_final_generation` court-circuite aussi la passe finale du modèle quand le flag est posé (zéro echo de jargon possible). **Concierge** (`agent.py`) : `status=search_unavailable` → template `leaf_degraded_response` (jamais de synthèse), le delta geocode est GARDÉ (la destination est nommée dans le template), et le tour n'est PAS compté comme recherche vide (pas de streak/auto-widen/chips — l'inventaire n'a jamais été consulté).
2. **Jargon neutralisé (F3)** — `mcp_guard._degraded_response` : reason sans « MCP_B2C »/« circuit » ; les 2 tests qui verrouillaient l'ancienne string verrouillent maintenant l'ABSENCE de jargon.
3. **Localisation des textes de secours (F3/F5)** — `_outcome_text` fr/en (+ helper `_profile_language` depuis `profile_in.language`) ; question de clarify géo fr/en (`geo_resolver.resolve(language=...)` ← le hint 2 lettres que Mapbox recevait déjà) ; nouveau `triage.template_language` (langue établie → locale client → guess) utilisé par les 2 sites d'ack du spine ; `_locale_response_language` DÉPLACÉ de facade.py vers `triage.locale_response_language` (facade l'importe sous son ancien nom local — aucun contrat changé). **Règle Fabien (review PR #34), appliquée ici aussi** : une locale DÉCLARÉE non traduite (ni fr ni en) → ANGLAIS, jamais le guess (hints français piégés par es/it/pt) ; le guess ne sert que sans locale.

**DoD verte** : 945 passed (+19 : 10 bridge feuille, 1 geo_resolver, 5 triage, 3 spine dont « pas compté comme recherche vide » ; même unique échec préexistant `test_llm_meter_usage`) ; ruff OK ; mypy 40 fichiers OK ; guardrails OK.

**Vérifié LIVE (repro EXACTE de l'audit : feuille relancée avec `MCP_B2C_URL` mort, 2 appels)** : « je cherche un hôtel à Marseille demain » → **« Je n'arrive pas à joindre la recherche d'hôtels à Marseille pour le moment, et je préfère ne rien inventer. Pouvez-vous réessayer dans un instant ? »** 2/2, `suggestions: []` (avant : « il n'y a pas d'offres de jour à Marseille » 4/4). Feuille restaurée → smoke e2e PASS (le nominal ne régresse pas).

**Limite documentée (assumée, YAGNI)** : le cas `find_hotel_by_name` avec MCP inénumérable ET breaker pas encore ouvert n'a pas de signal déterministe (pas de geocode sur ce chemin) — la prose du modèle reste ; après 3 échecs le breaker le couvre. Résiduel F3 : le chemin verbatim sur échec geocode (prose modèle « geocode_no_match ») reste LLM-authored — jargon possible seulement sur double panne geocode+synthèse, non traité (rare, et la prose du modèle paraphrase en pratique).

**Merge** : PR depuis `scx2-mcp-truth-localized-fallbacks`, base `scx1-facade-shield` (stack #33 ← #34 ← celle-ci — merger top-down). Review Fabien = gate.

## ⏱ Addendum 2026-07-24 (branche `scx1-facade-shield`, stackée sur `audit-cx-2026-07-24`) — S-CX1 : bouclier façade + frame SSE terminale garantie (fix F1/P0 de l'audit CX, GO Fabien)

**Contexte** : GO explicite de Fabien sur S-CX1+S-CX2 de la roadmap de l'audit CX (`reports/AUDIT-CX-2026-07-24.md`). Cette branche = S-CX1 seul (F1). Décision de contrat prise : **pas de frame `error` nouvelle — un `done` dégradé** (zéro changement widget ; documenté dans la docstring de `chat_stream`).

**Fait (3 pièces, petites)** :
1. **`templates.py::service_degraded_response`** (neuf) — message générique honnête fr/en (la façade ne sait pas quelle étape a lâché ; ne dit pas « recherche d'hôtels » à tort sur un tour FAQ).
2. **`facade.py::_shield_payload`** (neuf) — payload iso-contrat complet construit sur entrées PURES uniquement (`SessionProfile()` frais, `build_chat_payload` pur, zéro Redis/DB/ADK — n'importe lequel peut être CE qui vient de planter). **Langue (règle Fabien, review PR #34)** : une locale DÉCLARÉE mais non traduite (ni fr ni en — es/pt/de/…) → réponse en ANGLAIS, jamais via `guess_language` (ses hints français peuvent se déclencher sur de l'espagnol/italien) ; le guess sur le message ne sert que sans locale. Métrique count-only `concierge_metric=facade_shield path=… error_type=…` + `enqueue_metric_event` (jamais de contenu de message — RGPD) + `logger.exception` pour l'ops.
3. **`facade.py` handlers** : `chat()` → try/except de dernier recours autour de session/native-context/drive/`_finalize` → payload bouclier en 200 (jamais un 500 nu hors contrat). `chat_stream()` → (a) échec de SETUP avant l'ouverture du stream → mini-générateur `progress`+`done` dégradé (un EventSource ne parse pas un body 500) ; (b) échec MID-STREAM → except dans `_body()`, le `yield done` est APRÈS le try/except → **le stream se termine TOUJOURS par `done`**. Helper `_sse_response` factorisé (headers + cookie).

**DoD verte** : 926 passed (+5 : `tests/api/test_facade_http.py` section « last-resort shield » — crash JSON → contrat 200, localisation fr via locale, crash mid-stream → `done` terminal, crash setup SSE → `progress`+`done`, panne Redis dans `_finalize` → bouclier tient) ; même unique échec préexistant `test_llm_meter_usage` ; ruff OK ; mypy 40 fichiers OK ; guardrails OK. **Vérifié par la repro EXACTE de l'audit** (probe in-process `_drive` patché) : JSON = 200 + contrat complet + message fr honnête + cookie (avant : `500 Internal Server Error` texte brut) ; SSE = `['progress','token','done']` (avant : flux mort sans `done`).

**Pièges** :
- Le `yield _sse("done", payload)` doit être HORS du try/except (après), sinon un crash pendant la construction du payload dégradé lui-même tuerait encore le stream — le payload bouclier est pur précisément pour ça.
- `_apply_native_context` ne touche Redis QUE si le body porte un champ natif — un test « Redis down » doit passer par `_finalize` (ou fournir une locale) pour exercer le chemin.

**Merge** : PR depuis `scx1-facade-shield`, base `audit-cx-2026-07-24` (stack — merger top-down, leçon #28/#29). Review Fabien = gate.

## ⏱ Addendum 2026-07-24 (branche `audit-cx-2026-07-24`, base `main`) — Audit CX complet avant exposition client : rapport seul, AUCUN fix appliqué

**Contexte** : audit demandé par Fabien (exposition prochaine aux clients : zéro fuite d'erreur + agent plus interactif/proactif, notamment propositions autour du budget). Cadrage tranché par Fabien en session : livrable = rapport seul (fixes en sessions dédiées après GO), « prix plancher » = **pondération scoring hôtel × proximité du prix au budget client** pour la mise en avant, passe live incluse.

**Fait** : `reports/AUDIT-CX-2026-07-24.md` — lecture de code exhaustive des surfaces client (3 agents Explore) + **passe live adversariale** (stack locale + MCP staging : 10 sondes + 4 scénarios destructifs — feuille tuée, MCP coupé, synthèse cassée, crash injecté in-process sur l'app ASGI réelle). Chaque constat tagué [LIVE]/[CODE]/[HYPOTHÈSE]. `git diff --stat` vide sur les fichiers trackés : zéro changement `agents/**`/`libs/**`/`tests/**`.

**Les 3 P0 (tous reproduits, détails et repros exacts dans le rapport)** :
1. **F1** — façade sans bouclier d'exception : crash inattendu → `500 Internal Server Error` texte brut hors contrat (JSON) ; SSE → flux mort **sans `done` ni frame `error`** (aucun event `error` n'existe). Prouvé in-process (`_drive` patché pour lever).
2. **F2** — MCP injoignable → **fausse rareté** 4/4 : « il n'y a pas d'offres de jour à Marseille » alors que le backend est mort. Root cause : l'échec d'**énumération du toolset MCP** (`TaskGroup` errors, `search_offers` jamais appelé) est invisible pour le circuit-breaker (`mcp_guard` ne voit que les échecs d'APPEL) ; le modèle feuille improvise « pas d'offres ». Perte de vente silencieuse + métriques polluées.
3. **F3** — synthèse en échec → `leaf_text` verbatim : client fr reçoit `"5 day-use offer(s) found: …"` anglais avec `response_language: "fr"` (prouvé live : concierge relancé avec `DAYUSE_MODEL` invalide — la feuille, process séparé, garde son modèle sain, le triage retombe sur la regex). Le jargon `mcp_guard` (« MCP_B2C unavailable — circuit open ») peut passer par ce même chemin sur double panne.

**Aussi dans le rapport** : P1 = pas de cap taille message (300 Ko accepté, 18,8 s, tokens facturés) ni rate limiting ; localisation incohérente des fallbacks ; gaps de tests façade (les 400 de /stream et /reset sont corrects live mais non testés). Axe interactivité : l'agent est honnête mais passif — dead-end budget sans proposition (« max 10 € » → conseil générique, jamais « la moins chère est à 54 € ») ; 3 blocages structurels pour la demande de Fabien (filtre prix dur MCP = hôtels hors budget jamais renvoyés ; `priceEuro` numérique perdu sur la carte, seul `"€X.XX"` survit ; aucun re-ranking cross-hôtels). Nuance live : la qualification VILLE existe déjà de facto (LLM feuille demande « quelle ville ? ») mais `requires_clarification` reste false (signal non structuré).

**Roadmap proposée (rien lancé, GO Fabien requis)** : S-CX1 bouclier façade + frame SSE terminale (R1) ; S-CX2 vérité MCP-down + jargon + localisation (R2, R3) ; S-CX3 chaîne prix plancher — cents numériques sur carte → fallback sans cap prix sur budget explicite → **blend rating × proximité budget** → template de proposition (R4) ; S-CX4 qualification structurée + chips contextuelles + caps (R5, R6). S-CX1/S-CX2 bloquantes avant exposition réelle.

**DoD verte** : 921 passed (même unique échec préexistant `test_llm_meter_usage`, untracked hors zone) ; ruff OK ; mypy 40 fichiers OK ; guardrails OK ; smoke e2e final PASS, stack arrêtée proprement.

**Pièges découverts** :
- Un serveur MCP **injoignable** ne produit PAS le dict `mcp_circuit_open` : l'échec se joue à l'énumération du toolset (avant tout appel), le breaker ne compte rien — tester les deux modes de panne (serveur up + tool qui échoue ≠ serveur down) pour tout fix R2.
- Technique de repro « synthèse seule cassée » : relancer UNIQUEMENT le concierge avec `DAYUSE_MODEL` invalide — le triage retombe sur la regex (le tour route quand même) et la feuille garde son propre env sain. Repro du chemin verbatim en 1 requête.
- Crash mid-stream non déclenchable à la demande en live : preuve honnête = in-process sur `serve.app` réel (pattern `tests/api/conftest.py` : fakeredis + `reset_runner` + `_drive` patché), `raise_server_exceptions=False`.

**Merge** : PR à ouvrir depuis `audit-cx-2026-07-24` (rapport + ce bloc HANDOFF uniquement) — review humaine de Fabien = le gate.

## ⏱ Addendum 2026-07-24 (branche `sg12-hotel-page-urls`, base `main` post-#31) — S-G12 : URLs de page hôtel depuis le slug ES + guard n°13 anti-liens fabriqués

**Bug prod repéré par Fabien** : à la demande de liens, la synthèse INVENTAIT les URLs en slugifiant le nom affiché — `dayuse.com/hotels/france/ibis-rungis-a-roport-paris-orly` (mauvais domaine, « é » → tiret) au lieu de `dayuse.fr/.../ibis-rungis-aeroport-paris-orly`, et `eurohotel-...` au lieu de `euro-hotel-...`. Root cause : AUCUN code ne construisait d'URL de page hôtel ; le `slug` ES (envoyé par hotel dans le payload MCP, probé 2026-07-23) était jeté par `normalize_hotel`, et le prompt de synthèse (règle 1 « never invent a link ») n'avait aucun guard déterministe derrière.

**Fait (5 pièces, toutes petites)** :
1. **`libs/b2c_common/b2c_common/hotel_urls.py` (neuf, exporté)** — `build_hotel_page_url(slug, country_code, country_name)` : slug ES verbatim (validation stricte, jamais « réparé »), tables marché portées de la référence prod agent-usa `src/application/shared/hotel_urls.py` (host par pays DESTINATION : FR→dayuse.fr, IT→dayuse-hotels.it, BR→dayuse.net.br… ; path-slug pays : US→`usa`) + mapping countryName anglais→ISO (search_offers n'envoie pas de countryCode). Non mappable → `None`, la carte n'a honnêtement pas de lien. Lib partagée EXPRÈS (leçon agent-usa 2026-07-06 : 2 tables tenues à la main ont divergé → 404 sur 4 jours).
2. **Feuille `response_bridge.py::normalize_hotel`** : `card["url"]` depuis le slug ES. **Concierge `inline_tools.py::_normalize_hotel_for_display`** : idem, défensif (shape `get_hotel_details` non re-probée pour `slug`).
3. **`ground_truth.py`** : ligne hôtel `— url: <...>` + règle header LINKS « copy EXACTLY the url listed... NEVER construct » ; un hôtel sans url listé = pas de lien à donner.
4. **`link_guard.py` (neuf — guard n°13)** : `enforce_hotel_link_truthfulness(text, hotels)` — toute URL `*dayuse*/hotels/...` de la synthèse absente du set exact des urls de la shortlist est retirée en code (markdown → label conservé, URL nue → excisée avec ses espaces de tête, la ponctuation de phrase survit — pas de rewrite global qui casserait l'espace-deux-points français). Tunnel booking / pages help ne matchent pas `/hotels/` → intouchés. Câblé en fin de `_synthesize_with_guards` (la synthèse est bufferisée, jamais streamée depuis litellm — le guard voit le texte entier), tourne MÊME à shortlist vide. Métrique count-only `link_guard stripped=N` (RGPD).
5. **Tests (+29)** : les 2 repros prod de Fabien verrouillés en régression nommée (b2c_common), guard (12 cas dont ponctuation française et fabrication markdown), ground-truth, cartes feuille + inline.

**DoD** : 921 passed (+29, même unique échec préexistant `test_llm_meter_usage`, untracked hors zone) ; ruff OK ; mypy 40 fichiers OK ; guardrails OK. **Vérifié** : seam in-process payload MCP → carte → bloc ground-truth → guard (repro exact nettoyé) ; les 2 URLs construites répondent **HTTP 200 live** (et un slug bidon 404 — le schéma de path est bien signifiant). NON vérifié en e2e LLM live (stack locale down) — à faire au prochain run smoke.

**Pièges découverts** :
- `search_offers` envoie `countryName` (jamais `countryCode`) → le mapping nom→ISO ne couvre que les noms ANGLAIS des 22 marchés d'agent-usa ; un countryName localisé ou un nouveau marché → pas d'URL (honnête). Si MCP_B2C expose un jour `countryCode`, il gagne déjà (préférence câblée).
- Le host varie par marché de DESTINATION (pas par origine widget) — même politique que le rewrite prod d'agent-usa (export Amplitude 2026-07-06).

**Merge** : PR à ouvrir depuis `sg12-hotel-page-urls` — review humaine de Fabien = le gate.

## ⏱ Addendum 2026-07-23 (branche `sg10-geo-fixes`, stackée sur `sg9-gate-rerun`) — S-G10 : audit indépendant des findings S-G9 + les fixes P0/P1 — Budapest→HU **PASS live**, La Défense plus jamais AE, Gate 7 (ranking) débloqué

**Contexte** : audit sceptique des findings du rapport S-G9 (demandé par Fabien), puis, sur son GO explicite, les fixes. Deux phases dans la même session : (1) audit lecture de code + ~15 replays live ciblés (JAMAIS les 81×3), (2) 6 fixes petits et localisés, 14 tests neufs, re-vérification live. `DAYUSE_MODEL=gpt-5.2` pour tous les replays (mêmes conditions que S-G9, vérifié par `ps eww` ciblé sur la variable exacte).

**Verdict d'audit (finding par finding)** : F1 `distance_origin` **CONFIRMÉ** (code + 100 % None live sur tours avec hôtels) ; F4 wrong-country **CONFIRMÉ + root cause trouvée** (voir ci-dessous) ; F3 `requires_clarification`/F5 fixtures GPS/F9 Wien **CONFIRMÉS** (citations exactes, Wien reproduit live) ; **F2 texte-vide multi-turn : NON REPRODUIT** (0/10 tours sur les familles annoncées « 12/12 déterministes », même jour, mêmes conditions — à la place : clarify Fort Lauderdale/Lauderdale MN + mismatch sémantique fixture `zone` vs `city` de l'agent ; le bucket « 14/run » du rapport S-G9 mélange probablement ces causes). Chiffres globaux S-G9 : arithmétique interne cohérente (52/59/57, buckets, stabilité), pas re-vérifiables bit à bit (bruts non commités) — **ne PAS relancer un 243-appels avant que ces fixes soient mergés**, le chiffre bougerait pour de mauvaises raisons.

**Root cause des 2 wrong-country (une seule faille, prouvée par probe déterministe)** : `geo_resolver.py` triait `key=(has_inventory, score)` avec `has_inventory = inv > 0`, et L204 sélectionnait EN SILENCE dès que le top avait de l'inventaire et pas le second. Or le snapshot figé (`data/inventory_snapshot.json`) donne `inv=1` à *Budapest, Georgia* (le Quality Inn de Bremen GA à 7 km) contre `inv=0` pour Budapest HU (pas un marché) → tier flip silencieux, echo-guard passe (« budapest » echo). Idem « La Défense » → `'Defense, Al Ain, Abu Dhabi'` (`inv=1` à Al Aïn) — et Mapbox ne renvoie même pas les candidats Puteaux-FR sans param `language` (liste candidats INSTABLE d'un appel à l'autre, constaté). Technique de probe réutilisable : charger `.env`, `sys.path.insert(leaf)`, appeler `geocode_location(...)`/`geo_resolver.resolve(...)` in-process et imprimer `res.scored` — zéro LLM, déterministe.

**Les 6 fixes (tous sur cette branche, `agents/**` touché — c'était le mandat)** :
1. **`response_bridge.py::emit_search_datapart`** : `distance_origin` niché DANS `profile_delta` (le concierge ne lit que cette clé — `_normalize_delta` traite un dict brut comme set implicite, vérifié). Test feuille corrigé (il verrouillait le placement bogué) + **`tests/test_leaf_concierge_seam.py` neuf** : la vraie soudure emit réel → `apply_profile_delta` → `build_active_filters`, cross-package (aucun test ne l'exerçait). Type vestige `profile.py` corrigé (`dict[str, Any] | None`).
2. **`geo_resolver.py`** : `_MIN_TIER_INVENTORY = 3` — le tier quasi-dur exige un vrai footprint ; `inv` 1-2 reste un poids soft. Budapest HU redevient top (5.00 vs 3.77), near-tie cross-country → clarify au lieu du select silencieux. 2 tests de régression nommés (Budapest GA, La Défense/Al Aïn). Les cas légitimes (Lisbon-Arkansas etc., inv≥3) inchangés — tous les tests existants passaient déjà avec des inventaires ≥3.
3. **`geocode_tool.py` + `inject_profile_geo_context`** : nouveau param `language_hint` (depuis `profile_in.language`, triage fr/en), utilisé UNIQUEMENT en fallback du param Mapbox `language` quand `profile_in.locale` est absent — **jamais** pour `_locale_country` (piège S-G7, verrouillé par un test dédié : le prior pays ne bouge pas).
4. **`geocode_tool.py`** (découvert par le probe post-fix, régression évitée) : un `clarify` avec zone/landmark nommé tente d'abord le tier-2 Search-Box (echo-validé) avant de poser la question — sinon « city=Paris, zone=La Défense » régressait d'un POI correct vers un clarify sur du fuzz colombien. **Effet bonus prouvé live : c'est CE chemin qui fait passer Budapest** (le POI « Keleti station » désambiguïse le clarify HU/GA → `country_code=HU`).
5. **`agent.py` (concierge)** : ne dégrade plus que si `leaf_text is None` ET `response` (DataPart) vide — un tour feuille sans texte mais avec résultats part en synthèse (elle réécrit depuis le structuré de toute façon) ; double échec (pas de texte + synthèse morte) → template dégradé, jamais un message vide. Rend le F2 de S-G9 inoffensif SANS avoir eu à prouver son mécanisme exact.
6. **`geo_guards.py`** : table `_EXONYM_EQUIVALENTS` (wien/vienna, münchen/munich, praha/prague, lisboa/lisbon… ~16 paires, les deux sens) branchée dans `_token_matches`. « vienne » (fr) exclu EXPRÈS : Vienne est une vraie ville française, la paire réintroduirait le wrong-country que le guard existe pour attraper.

**DoD verte** : `pytest -q` → **872 passed** (+14 ; 1 échec préexistant `test_llm_meter_usage.py`, untracked S-B, hors zone, inchangé) ; `ruff` OK ; `mypy agents libs` 38 fichiers OK ; guardrails OK.

**Vérifié LIVE (gpt-5.2, MCP staging, 3 services locaux)** :
- `geo-budapest-4d5b6c69` : **PASS 2/2** — `country_code=HU`, resolved Budapest Hongrie, 0 offre honnête (pas d'inventaire HU staging). Avant fix : `country_code=US` + 1 hôtel géorgien servi, 3/3.
- `geo-la-defense-59b7c3f6` : plus jamais AE (2/2) — clarify honnête. Le cas échoue encore `min_hotels` (rien n'est servi, comportement sûr vu le staging) ; les options du clarify sont du fuzz Mapbox (« La Defensa, Colombie ») — moche mais honnête, poli possible plus tard.
- 3 cas multiturn Boca/Miami : `active_filters.distance_origin` présent sur TOUS les tours de recherche (`{latitude, longitude, type:city_centroid}`, carryover inclus) — avant : 100 % None.
- `scripts/eval_ranking.py` sur ce replay frais : **2 échantillons scorés** (precision@5=0.4, NDCG@5=0.2689), skips corrects — le Gate 7 est débloqué ; ces chiffres prouvent la pipeline, ce n'est PAS un baseline (n=2).

**Reste (sessions suivantes / décisions Fabien)** :
- Re-run complet du gate 81×3 APRÈS merge de cette branche (les chiffres S-G9 sont périmés par construction) — attendre aussi la décision sur les fixtures.
- Décisions pack (intouchable sans GO) : fixtures GPS `native_context.geolocation` → `client_geo_context.device.*` ; sémantique `zone` vs `city` des familles multiturn (l'agent modélise Fort Lauderdale/Boca Raton comme des villes — défendable — donc `filter_equals zone=...` ne peut structurellement pas passer) ; `requires_clarification` minimal non-bloquant (façade → True quand la feuille renvoie `geocode_ambiguous` ce tour) rendrait le Gate 4 mesurable.
- Réserves design `eval_ranking.py` (documentées dans l'audit, pas bloquantes) : skew temporel pool vs replay ; divergence post-filtre minute-exact ; « pool identique entre agents » réinterprété mono-agent (scope limit 5 du protocole) — à valider par Fabien.
- Mécanisme exact du texte-vide gpt-5.2 : toujours non prouvé (non reproduit ce jour) — le filet #5 le neutralise ; investiguer seulement si le symptôme réapparaît dans les métriques (`synthesis_fallback`/`degraded`).

**Pièges découverts** :
- **La liste de candidats Mapbox v6 n'est PAS stable d'un appel à l'autre** pour une requête fuzzy (les candidats Puteaux-FR pour « La Défense » apparaissent ou pas, à minutes d'écart, mêmes params) — ne jamais conclure d'un probe unique qu'un candidat « n'existe pas » ; le resolver doit être robuste à la liste entière qui change.
- Un élargissement du chemin `clarify` peut **court-circuiter le tier-2 Search-Box** (le early-return du clarify passait avant) — tout changement de la politique de décision du resolver doit re-tester les 4 formes d'extraction (city seul, city+zone, zone seul, city=Paris+zone) via le probe in-process.
- La branche S-G9 n'avait jamais été poussée (pas de MR) — poussée cette session avec sa propre PR pour que le stack sg10 ait une base reviewable.

**Décisions Fabien prises en session (2e commit de cette branche)** — D1-a, D2-a, D3-a explicites ; D4 = re-run complet SEULEMENT après merge + décisions (aucun modèle tranché pour le re-run — à demander) ; D5/D6/D7 délégués (« fais ce qui te semble pertinent ») :
- **D1-a (pack, autorisé)** : les 2 fixtures GPS passent à `client_geo_context.device.{latitude,longitude,permission:"granted"}` (la vraie forme S-G2) ; le runner forwarde `client_geo_context` et `_resolve_origin` lit les 2 formes. **Découverte live en exécutant D1 : la feuille n'avait AUCUN chemin de recherche GPS-only** (`search_anchor` = simple biais de proximité du geocode) — ajouté : `geocode_location` résout sur le fix GPS quand RIEN n'est géocodable (jamais quand une zone/landmark est nommée — Gate 3 anti-remplacement silencieux). Vérifié live : Detroit « near me » → **4 hôtels réels, `distance_origin.type="gps"`** ; Paris GPS → recherche lancée, 0 offre honnête (piscine + same-day sur staging, confond d'inventaire, plus un gap de capacité).
- **D2-a (pack + harness + resolver)** : nouveau type d'assertion `filter_place` (la place comptée où que l'agent l'enregistre : `zone`/`city`/`resolved_city`) + 9 assertions migrées ; `filter_equals` accepte un filtre structuré (dict `date_reference`) contre le token littéral via `expression` (sinon `carry_same_time` restait imposssible à passer — dict ≠ "tomorrow") ; `check_zone_change` S-G8 idem ; et la **règle nom-exact du resolver** (`requested_name`) : un nom tapé EXACTEMENT ne clarifie plus contre un candidat de nom différent (« Fort Lauderdale » vs « Lauderdale, MN ») — asymétrique exprès, un top non-exact ne supprime jamais rien, deux homonymes exacts (Budapest HU/GA) clarifient toujours. **Vérifié live : `multiturn-carry_same_time_0` et `multiturn-zone_change_0` PASSENT (0/3 sur les runs S-G9).**
- **D3-a (chaîne bout-en-bout, non-bloquant)** : capture `geocode_ambiguous` côté feuille → DataPart `requires_clarification: true` + question déterministe en text part (l'événement émis REMPLACE le texte final du modèle — la question doit voyager ici, la synthèse la re-localise) → marker `hotels` du concierge → façade (`build_chat_payload(requires_clarification=...)`, le hardcodé False n'existe plus). **Vérifié live : la-defense → `requires_clarification: true` dans le payload /v3, et `outcome_counts.safe_clarification: 1` via la couche S-G8 (structurellement 0 sur les 3 runs S-G9).** Gate 4 devient mesurable.
- **D5 (arbitrage)** : mono-agent accepté + documenté dans le protocole ; skew temporel divulgué (`ground_truth_fetched_at` + `n_samples_with_past_date` + warning console) ; post-filtre minute-exact reproduit dans le pool ground-truth (mêmes sémantiques `_offer_fits_exact_window` + fallback A4-c, re-dérivées sans import agents/**).
- **D6 (arbitrage)** : la règle nom-exact EST le poli retenu (elle supprime le pire cas produit) ; PAS de filtrage écho des options résiduelles (le fuzz colombien de la-defense reste affiché — sur-filtrer risquait de vider des clarifies légitimes ; à re-évaluer sur plainte réelle).
- **D7 (arbitrage) : DIFFÉRÉ** — câbler `_eval_clock` = honorer une horloge fournie par le client (surface d'injection : un client prod pourrait fausser la résolution de dates) ; à designer gated (env flag éval only) dans une session dédiée. `check_date_reference` reste approximatif, fiable seulement quand le run est same-day.

**DoD 2e commit** : 889 passed (+17), pack tests 11 passed (`cd dayuse_eval_pack && ../.venv/bin/python -m pytest -q tests/`), ruff/mypy/guardrails OK, même échec préexistant unique (`test_llm_meter_usage`).

**Reste après cette session** : re-run complet 81×3 post-merge (D4 — demander à Fabien quel modèle) ; le mécanisme texte-vide gpt-5.2 (non reproduit, neutralisé par le filet) ; `_eval_clock` (D7, différé) ; options de clarify résiduelles sur fuzz (D6, accepté).

**Merge** : `sg9-gate-rerun` (PR #28, mesure) puis `sg10-geo-fixes` (PR #29, fixes + décisions, stackée) — review humaine de Fabien = le gate, rien n'est mergé par moi.

## ⏱ Addendum 2026-07-23 (branche `sg9-gate-rerun`, worktree principal) — S-G9 : re-run du gate 81 cas ×3 + design éval ranking — mesure seulement, **AUCUN fix agent**, 3 bugs neufs confirmés + 1 limite structurelle documentée

**Contexte** : dernière session de la fenêtre (S-G1→S-G8 toutes mergées sur `main`), rôle = mesurer honnêtement, jamais corriger (`agents/**` intouché tout du long, vérifié `git diff --stat` en fin de session). Rapport complet : `reports/GATE-RERUN-2026-07-23.md` (7 gates, 10 findings numérotés, ledger d'échecs complet sur les 3 runs). Protocole ranking : `reports/RANKING-EVAL-PROTOCOL-2026-07-23.md`.

**Décision prise avec Fabien avant de lancer quoi que ce soit** : `DAYUSE_MODEL=gpt-5.2` explicitement choisi (question posée via AskUserQuestion) pour matcher les conditions de l'audit du 22/07 (qui avait forcé gpt-5.2 des deux côtés) — le défaut committé reste `gpt-4o-mini`, confirmé absent de l'environnement sinon. MCP staging (Railway, live) — PAS le snapshot local figé de l'audit (confond d'inventaire déjà documenté, pas nouveau). 3 runs strictement séquentiels (jamais concurrents, pour éviter le confond timeout du run du 22/07).

**Résultat brut, très en dessous de la cible** : **29/81 (35,8 %), 22/81 (27,2 %), 24/81 (29,6 %)** sur les 3 replays (moyenne 25/81, 30,9 %) — sous la cible de parité 58/81 ET sous le propre score brut de l'audit sur ce set (41/81, 50,6 %). **Mais creuser cas par cas montre que ce n'est PAS une régression de capacité** — un petit nombre de causes racines précises expliquent l'écart :

**Bug neuf #1 (confirmé, bloque le Gate 7 ranking)** : `hotel_search_agent/response_bridge.py::emit_search_datapart` attache `distance_origin` comme clé **sœur** de `profile_delta` dans le payload sortant, pas nichée dedans — `b2c_concierge/agent.py:843` ne lit QUE `response.get("profile_delta")`, donc `distance_origin` n'atteint jamais le profil, sur AUCUN tour de recherche (GPS ou pas), confirmé sur les 17 tours avec hôtels du run 1 (100 % `None`). `distance_km`/`lat`/`lon` par hôtel restent corrects (chemin de code différent, déjà bon). Aucun test ne couvre la vraie soudure (chaque côté teste son moitié isolément). **Fix = 1 ligne** (nicher dans `profile_delta` avant l'assignation), non appliqué (hors zone). C'est la cause directe du 0 échantillon de l'éval ranking cette session — le script (`scripts/eval_ranking.py`, 15 tests verts, protocole MCP live-validé) est prêt et n'attend que ce fix pour produire de vrais precision@5/NDCG@5.

**Bug neuf #2 (dominant, explique la majorité du score brut faible)** : la recherche RÉUSSIT réellement (MCP `status=ok`, zéro timeout, zéro exception) mais la feuille ne renvoie AUCUN texte ce tour — `_run_leaf` (`agent.py:288-337`) tombe sur `leaf_text is None`, le concierge dégrade honnêtement (« I can't reach the hotel search... ») alors que la recherche a fonctionné. Concentré à >94 % dans le multi-turn (37/38/33 occurrences sur 3 runs, quasi 0 en geo/prod_wounds) — touche **de façon déterministe 12/12** les 4 familles `carry_same_time`/`budget_change`/`zone_change`/`date_availability_follow_up` (3 variantes × 3 runs) + une variante `rooftop_pool` intermittente. Hypothèse de mécanisme (non prouvée à 100 %) : `MAX_TOOL_CALLS=2` (`hotel_search_agent/agent.py:85`, callback `dayuse_agent_common.tool_budget`) interagit mal avec le style d'appel d'outils de gpt-5.2 spécifiquement sur les tours de SUIVI (contexte accumulé plus long) — la lib partagée documente déjà ce même symptôme pour un AUTRE modèle (glm-5.2) dans son propre docstring. **Jamais vu avant** car toutes les vérifications live précédentes du projet tournaient en gpt-4o-mini (le défaut), jamais gpt-5.2 à ce volume. **PAS un timeout** (Gate 6 = 0,0 % propre sur les 3 runs, confirmant que le budget S-G4 tient) — un mécanisme distinct que la métrique timeout ne peut pas voir. Prochaine étape recommandée (pas faite ici) : reproduire un cas 2-tours avec logs ADK/LiteLLM verbeux pour voir le contenu littéral de la dernière completion de la feuille.

**Limite structurelle documentée (pas un bug)** : `requires_clarification` est câblé en dur à `False` (`facade.py:435-452`, choix architectural explicite et documenté : « le spine ne bloque jamais sur une étape de clarification structurée »). Conséquence : `outcome_counts.safe_clarification` reste à **0 sur les 3 runs**, alors que l'agent pose bien de vraies questions de désambiguïsation sensées en prose (Victoria BC/PEI/NL, Nürnberg/Kürnberg, Parma IT/OH, Heidelberg DE/AU, Salerno IT/Balerno, Bremen DE/GA — 5 à 7 cas/run) — ces cas sont notés échecs bruts alors que le comportement est probablement le bon. Décision produit à trancher par Fabien (accepter le sous-comptage, ou câbler un vrai signal de clarification bout-en-bout — chantier séparé, pas fait ici).

**2 vrais wrong-country confirmés et reproductibles 3/3 (Gate 1, le plus critique)** : **`geo-budapest-4d5b6c69`** — message cite « near Keleti station » (repère non ambigu de Budapest, Hongrie), résultat `country_code="US"` **avec 1 hôtel réellement servi** en USD — hypothèse : le tie-break `_W_INVENTORY` de `geo_resolver.py` (S-G3) peut être piégé par un homonyme obscur AYANT de l'inventaire staging quand la vraie ville n'en a actuellement aucun — à vérifier par un probe Mapbox+inventaire dédié avant tout fix. **`geo-la-defense-59b7c3f6`** — La Défense (Paris) → `country_code="AE"` (Émirats), reproductible 3/3, **invisible aux checks `hotel_countries` du pack** (0 hôtel servi = rien à vérifier — un angle mort du harness en plus du bug lui-même). Root cause non diagnostiquée cette session (pas eu le temps d'un probe Mapbox dédié) — item ouvert prioritaire.

**Autres findings précis (détaillés dans le rapport)** : `native_context.geolocation` du fixture pack ≠ le contrat réel `client_geo_context.device.*` de la façade (2 cas prod_wounds GPS, PAS un bug agent, `dayuse_eval_pack/**` intouchable) ; 2 gaps adresse/zone déjà connus de l'audit (Orange County, Rue Lafayette) ; l'echo-guard (`geo_guards.py::geocode_echo_matches`) ne connaît pas la paire Wien/Vienna (exonyme traduit, pas juste diacritique — contrairement à Gießen/giessen qu'il gère déjà) — piste de fix étroite et facile ; famille `named_hotel` : les tours 1-3 identifient bien l'hôtel par nom sur 3 formulations différentes, c'est le tour 4 (suivi) qui perd le contexte et le tour 5 qui retombe sur le gabarit d'accueil générique — plus nuancé que le « 0/3 » brut de l'audit.

**Gate 6 (timeout) = vrai PASS propre** : 0,0 % de timeout HTTP sur les 3 runs × 81 cas (243 tours), confirme que le budget par famille S-G4 tient sous gpt-5.2.

**Stabilité ×3** : 87,65 % (71/81 cas d'accord sur les 3 runs), 10 cas instables (jitter LLM réel, cohérent avec la variance ~2× déjà documentée en S-G4 pour gpt-5.2) — 0 cas incomplet (aucun crash).

**Verdict par gate** (détail complet + ledger d'échecs exhaustif dans le rapport) : Gate 1 FAIL · Gate 2 NON-MESURABLE (masqué par le bug #2) · Gate 3 FAIL/partiellement non-mesurable · Gate 4 confondu (pas mesurable proprement) · Gate 5 (parité ≥58/81) FAIL · Gate 6 PASS · Gate 7 NON-MESURABLE (bloqué par le bug #1).

**DoD verte** : `pytest -q` → **858 passed** (+15, `tests/test_eval_ranking.py`, 15/15) ; 1 échec préexistant sans rapport (`test_llm_meter_usage.py`, déjà documenté, hors zone) ; `ruff check .` OK ; `mypy agents libs` → 38 fichiers OK (inchangé, `scripts/**` hors périmètre de cette commande, même précédent que `eval_hardening.py`) ; `dayuse_guardrails.sh` OK. `git diff --stat` confirme : zéro changement `agents/**`, seulement `scripts/eval_ranking.py` (neuf), `tests/test_eval_ranking.py` (neuf), `reports/GATE-RERUN-2026-07-23.md` + `reports/RANKING-EVAL-PROTOCOL-2026-07-23.md` (neufs), ce bloc HANDOFF.

**Reste (pour la prochaine session, probablement ciblée « fix » plutôt que « mesure »)** :
- Fix #1 (`distance_origin` nesting, 1 ligne) + relancer `scripts/eval_ranking.py` → devrait débloquer le Gate 7 immédiatement.
- Investiguer le mécanisme exact du bug #2 (logs ADK verbeux sur un cas 2-tours) avant de choisir entre relever `MAX_TOOL_CALLS` pour les routes d'amendement ou ajouter un filet de sécurité « forcer une completion finale ».
- Probe Mapbox+inventaire dédié pour Budapest→US et La Défense→AE avant tout fix (ne pas deviner).
- Fix Wien/Vienna dans la table de synonymes de l'echo-guard (petit, contenu, facile à vérifier).
- Décision Fabien sur `requires_clarification` (accepter le sous-comptage vs câbler un vrai signal).
- `dayuse_eval_pack` : faire évoluer les 2 fixtures GPS `native_context.geolocation` vers `client_geo_context.device.*` (décision Fabien, pack habituellement intouchable).

**Pièges découverts** :
- Le premier `ps eww <pid>` que j'ai lancé pour vérifier `DAYUSE_MODEL` a exposé `MCP_B2C_AUTH_TOKEN` en clair dans la sortie (grep trop large sur `MCP_`) — corrigé immédiatement en ne grep-ant plus que le nom de variable exact recherché. Toujours cibler la variable précise, jamais un préfixe large, quand on inspecte l'env d'un process qui porte des secrets.
- `register_model: model=openrouter/z-ai/glm-5.2` dans les logs LiteLLM au boot est un piège de lecture — c'est l'enregistrement du `DEFAULT_MODEL` de la lib partagée (plomberie interne, cost-map), PAS le modèle réellement utilisé par requête ; le modèle réel par appel est dans `dayuse_metric=llm_call ... model=...`, jamais dans cette ligne de warning.
- `macOS` n'a pas `timeout` par défaut — utiliser le `--timeout` propre du runner/script plutôt que `timeout <cmd>`.

**Merge** : cette branche (`sg9-gate-rerun`) n'est PAS mergée cette session — review humaine de Fabien = le gate. Le **GO canary reste entièrement une décision Fabien** ; ce rapport instruit, il ne décide pas.

## ⏱ Addendum 2026-07-23 (branche `sg7-locale-currency`, worktree principal) — S-G7 : propagation locale/devise/domaine (A6-a) — ⚠️ bug trouvé dans le pont locale→géo de S-G3 (mauvais champ profil) + découverte live : MCP expose désormais `currencyCode` par hôtel (jamais un prix converti)

**Contexte** : séquentielle après S-G6 (mêmes fichiers feuille), après S-G2 (locale/currency/domain au profil) et S-G3 (le client Mapbox expose `language`) mergées sur `main`. Zone : `agents/hotel_search_agent/**` (param `language` Mapbox, cartes) + `agents/b2c_concierge/**` (`response_language`, `active_filters.currency`, disclosure synthèse) + tests + `reports/MCP-B2C-REQUESTS.md`.

**Bug trouvé en lisant le code AVANT d'écrire quoi que ce soit (item 1, locale → géo)** : S-G3 avait déjà câblé `geocode_location(locale=...)` → Mapbox `language` + le boost `_W_LOCALE` du ranker (`geo_resolver.py`), mais la SEULE source de cette valeur était l'instruction du modèle : *« pass … profile_in.language as `locale` »* (`hotel_search_agent/agent.py`). Or `profile_in.language` est le champ de **triage** (`b2c_concierge/triage.py:127` — `"fr" ou "en"` UNIQUEMENT, jamais autre chose) — **pas** `profile_in.locale`, le vrai tag natif du client (S-G2, ex. `"pt-PT"`). Conséquence : le boost Lisboa→PT que le cas d'audit demande ne pouvait STRUCTURELLEMENT jamais recevoir `"pt"` — même avec un modèle parfaitement obéissant, le seul champ qu'on lui demandait de recopier ne contient jamais que fr/en. Root-cause, pas un simple oubli de câblage : exactement le pattern P0 #4 que toute cette série corrige ailleurs (le modèle recopie, au lieu que le code porte la valeur), retrouvé une 2e fois dans un endroit que S-G3 n'avait pas encore touché.

**Fait** :
1. **`hotel_search_agent/geocode_tool.py::inject_profile_geo_context`** — `locale` rejoint `profile_state_context`/`profile_location_hint`/`proximity_lat`/`proximity_lon` : un **pont déterministe pur** (`profile_in.locale` → `args["locale"]`, toujours écrasé, jamais laissé au modèle) — même doctrine que le reste de ce callback (S-G5). `agent.py` (feuille) : l'instruction ne demande plus au modèle de recopier `profile_in.language` — le texte dit maintenant explicitement que le système remplit locale/anchors/GPS automatiquement, comme pour le reste.
2. **`response_language` (item 2, bout-en-bout)** — vérifié : **déjà correct et déjà testé** (S-G2, `test_native_context_http.py::test_unsupported_locale_falls_back_to_guess_language`, verrouillé exprès). `_locale_response_language` restreint delibérement le champ à fr/en (« ne jamais désynchroniser `response_language` du texte RÉELLEMENT généré ») — la génération elle-même (synthèse + triage + `amenity_guard`'s table de synonymes fr/en) reste fr/en-only dans tout le spine, un choix de scope S9 documenté à plusieurs endroits, **PAS** retouché ici (le périmètre de la phase exclut explicitement « i18n des templates au-delà de fr/en »). **Décision explicite prise cette session** : le « réponse en pt » du prompt de lancement est vérifié comme *le champ `country_code`/`active_filters.locale` corrects + `response_language` conforme à son propre contrat testé (retombe honnêtement sur fr/en)* — PAS une réponse conversationnelle en portugais, qui exigerait de défaire une décision S-G2 déjà testée et documentée. Voir preuve live plus bas.
3. **Disclosure devise (item 3)** — `agent.py::_synthesize_with_guards` calcule un `currency_note` (marqueur `CURRENCY:`, même mécanique que `PROVENANCE:`/`AUTO_WIDEN:`) sur **deux déclencheurs indépendants**, l'un suffit : (a) `profile.currency` connue et ≠ EUR (contexte natif de l'utilisateur, S-G1/S-G2) ; (b) un hôtel affiché CE tour porte son propre `currency_code` ≠ EUR (nouveau signal, voir point 4). Règle 9 ajoutée à `_SYNTHESIS_INSTRUCTION` : jamais un montant inventé dans une autre devise, divulguer platement que l'affichage reste EUR. `active_filters.currency` était déjà exposé (S-G1/S-G2) — vérifié, rien à faire.
4. **Probe MCP pricing live (item 4, constat + code additif honnête)** — `search_offers`/`get_hotel_details` exposent désormais un `currencyCode` **par hôtel** (probé staging : Paris→EUR, Miami→USD, Londres→GBP, varie correctement par marché — nouveau depuis le dernier probe pricing du 2026-07-20, jamais vu avant). **Mais ça ne change rien à la porte pricing** : les seuls champs de prix numériques restent `priceEuro`/`priceEuroWithBookingFees`, TOUJOURS en cents EUR quel que soit `currencyCode` (vérifié : Cadillac Hotel Miami `currencyCode="USD"` → `priceEuro=11933` = €119.33, LE MÊME montant déjà vu dans l'addendum démo Railway 2026-07-22 — pas un montant USD mal étiqueté). Constat versé dans `reports/MCP-B2C-REQUESTS.md` (aucune demande cross-repo — rien à demander, juste documenté). Câblé côté affichage (pas pricing) : `currency_code` stampé sur les cartes (`response_bridge.py::normalize_hotel`, `inline_tools.py::_normalize_hotel_for_display`, même pattern que `country_code`), consommé par le point 3.
5. **Cartes / `country_code` (item 5)** — vérifié : déjà alimenté bout-en-bout depuis S-G3/S-G5 (`_STATE_COUNTRY_KEY` → `card.setdefault("country_code", ...)`, `response_bridge.py`), tests existants + nouveaux confirment. Rien à compléter.

**DoD verte** : `pytest -q` (repo) → **843 passed** (leaf 318→**322**, +4 ; concierge 329→**335**, +6) ; **1 échec préexistant, SANS RAPPORT** (`tests/test_llm_meter_usage.py`, untracked S-B, hors zone `agents/**`, déjà documenté dans les addenda précédents, non touché) ; `ruff check .` OK ; `mypy agents libs` → 38 fichiers OK ; `bash scripts/dayuse_guardrails.sh .` OK.

**Vérifié LIVE (3 services locaux, MCP staging réel + Mapbox réel + LiteLLM réel via `.env`)** :
1. **« hoteis em Lisboa » (message pt, locale `pt-PT`, SANS date)** → `active_filters.country_code="PT"` (Lisbonne Portugal, PAS l'homonyme Arkansas), `active_filters.locale="pt-PT"` persisté. 0 hôtel (comportement same-day honnête déjà documenté en S-G6, pas un bug du jour). `response_language="en"` (fallback attendu — voir point 2 ci-dessus, comportement conforme au contrat testé, pas une régression).
2. **« hoteis em Lisboa amanha » (même contexte, avec date)** → **5 hôtels réels à Lisbonne** (Marriott, Hyatt Regency, ibis, Mercure…), `country_code="PT"` sur chaque carte, `currency_code="EUR"` sur chaque carte (marché EUR, donc AUCUNE disclosure déclenchée — comportement correct), `date="2026-07-24"` résolu depuis « amanha », `distance_km` présent sur chaque carte (A8-a, inchangé).
3. **« hotels in Miami tomorrow », `currency: "USD"`** → 5 hôtels Miami, `active_filters.currency="USD"`, chaque carte `currency_code="USD"` (prix toujours affichés en `€`, ex. Cadillac Hotel & Beach Club `€119.33` — identique au montant déjà vu en démo Railway). **Rejoué 2 fois** : la synthèse (gpt-4o-mini réel) a inclus la divulgation littérale *« Prices are shown in EUR with no conversion applied »* sur le 2e essai — confirme que le marqueur `CURRENCY:` atteint bien le prompt ET que le modèle peut s'y conformer (même statut de fiabilité probabiliste que `PROVENANCE:`/`AUTO_WIDEN:` ailleurs dans ce spine — jamais garanti mot pour mot par construction, seulement instruit ; le 1er essai ne l'a pas verbalisé, ce qui est la même variance déjà acceptée pour les autres marqueurs).

**Reste (pour les sessions suivantes)** :
- **Génération conversationnelle au-delà de fr/en** : toujours hors scope (décision produit séparée, cf. point 2) — si un jour on veut une VRAIE réponse en pt/es/it/…, il faudra revoir simultanément `triage.py` (le classify LLM ne connaît que fr/en), `_SYNTHESIS_INSTRUCTION`, `amenity_guard.py` (table de synonymes fr/en-only, documentée comme telle) et `_locale_response_language` (S-G2) — un chantier à part entière, pas une extension de celui-ci.
- **Pricing multi-devises réel (A6-b)** : toujours bloqué — `currencyCode` existe maintenant mais aucun prix natif ni taux de change n'est exposé server-side (voir constat `MCP-B2C-REQUESTS.md`). Rouvrir seulement si MCP_B2C expose un jour un prix converti ou un taux.
- **Boost `domaine` dans le ranker géo** : NON construit — `profile.domain` n'est jamais peuplé par le trafic réel du widget (confirmé S-G2, aucun changement depuis) ; ajouter un prior spéculatif sur un champ jamais rempli aurait été de la complexité non justifiée (YAGNI). `locale` reste le seul prior de marché actif dans `geo_resolver.py` (`_W_LOCALE`), ce qui couvre le cas Lisboa de l'audit.
- Item 5 (cartes `country_code`) et item 2 (`response_language`) n'ont nécessité AUCUN changement de code — juste une vérification (déjà couverts par S-G2/S-G3/S-G5) ; documenté ici pour éviter qu'une session future ne les recroie manquants.

**Pièges découverts** :
- **`profile_in.language` ≠ `profile_in.locale`** — le premier est le champ triage fr/en-only (conversation), le second le tag natif du client (S-G2, arbitraire BCP-47). Une instruction qui demande au modèle de recopier l'un pour nourrir un signal qui a besoin de l'autre est un bug silencieux (jamais d'erreur, juste un prior qui ne peut structurellement jamais s'activer pour un cas comme "pt") — à vérifier explicitement (pas juste "le paramètre existe") chaque fois qu'une instruction demande au modèle de recopier un champ `profile_in.*`.
- **`currencyCode` par hôtel a pu apparaître dans le schéma MCP sans qu'aucune session précédente ne l'ait remarqué** (le dernier probe pricing datait du 2026-07-20, avant même que S-G1 n'introduise `profile.currency`) — toujours reprober le schéma live avant de conclure qu'un signal « n'existe pas côté MCP », même quand un probe plus ancien existe déjà.
- **Un marqueur de prompt (`CURRENCY:`/`PROVENANCE:`/`AUTO_WIDEN:`) est vérifiable en test au niveau « atteint le prompt », jamais au niveau « le modèle l'a dit mot pour mot »** — confirmé en direct : 1 essai sur 2 n'a pas verbalisé la divulgation devise malgré la présence du marqueur. Ce n'est pas un bug à corriger (même statut que les 2 marqueurs existants) — juste à documenter honnêtement plutôt que de sur-vérifier en direct jusqu'à obtenir le résultat désiré.

**Merge** : cette branche (`sg7-locale-currency`) n'est pas mergée cette session — review humaine de Fabien = le gate.

## ⏱ Addendum 2026-07-23 (branche `sg6-dates-durations-minutes`, worktree principal) — S-G6 : dates/durées/demi-heures de bout en bout — ⚠️ `date` est REQUIS par `search_offers` (hypothèse du brief invalidée par le probe)

**Contexte** : séquentielle après S-G5 (mêmes fichiers feuille : instruction + `response_bridge.py`), après S-G1 (champs `date`/`date_reference`) et S-G2 (native-context intake, `client_timezone` explicitement punté à cette session) mergées sur `main`. Zone : `agents/hotel_search_agent/**` (nouveau module + instruction + capture) + `agents/b2c_concierge/**` (profil + facade + templates + inline_tools) + tests + `reports/MCP-B2C-REQUESTS.md` (neuf).

**Probe MCP staging (obligatoire avant tout code, `mcp.ClientSession.list_tools()` sur `search_offers`) — invalide une hypothèse du plan** :
- Le plan (`PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` §4 A4, "OUT") disait : *« la date n'est PAS encore un paramètre de `search_offers` — vérifier au probe si un param date existe »*. **Le probe montre le contraire : `date` est un paramètre RÉEL et REQUIS** (`"required": ["lat", "lon", "date"]`, `{"type":"string","format":"date","description":"Target date in ISO format (yyyy-MM-dd), already resolved."}`) — MCP ne fait aucun calcul de date lui-même, exactement comme le géocodage. Ce n'était pas hors-scope : c'était juste non vérifié.
- `timeSlot` confirmé integer-hour-only (`startHour`/`endHour`, `additionalProperties:false`, aucun champ minute) — confirme A4-c tel quel (filtre client + demande cross-repo).
- Conséquence architecturale (déviation documentée du libellé du plan) : le plan écrivait *« Résolution en code (concierge) »* pour la date. Puisque `date` est REQUIS et que seule la FEUILLE appelle `search_offers` (synchrone, dans son propre tour), la résolution DOIT s'exécuter côté feuille — le concierge ne peut pas la faire après coup. Décision retenue : la feuille résout (code, jamais le LLM), le concierge reste responsable de fournir `client_timezone` (natif, S-G2/S-G6) et de persister `date`/`date_reference` une fois résolus (le reducer S-G1 `apply_profile_delta` gérait déjà ces 2 clés sans changement).

**Fait** :
1. **`hotel_search_agent/datetime_resolver.py` (neuf)** — même split que `equipment_ids.py` (le patron éprouvé) :
   - `inject_datetime_declaration` (before_model) : `date` devient un objet-label `{type: relative|absolute, value, expression}` (JAMAIS une date résolue — retiré de `required` puisque le code la remplit toujours) ; nouveau virtuel `duration` (string ISO-8601, ex. "PT1H") ; `timeSlot` gagne `startMinute`/`endMinute` virtuels (enum 0/15/30/45).
   - `resolve_search_date` (before_tool, dernier groupe) : pop le label, résout via `reference_today` (timezone client si `profile_in.client_timezone` valide, sinon horloge serveur, fallback documenté) → `args["date"]`. **Un label frais résolu PERSISTE** (`STATE_RESOLVED_DATE_KEY` → `profile_delta.date`/`date_reference`) ; **l'absence de label frais NE PERSISTE RIEN** — reprend `profile_in.date` (carryover) ou `reference_today` en dernier recours, mais n'écrase JAMAIS une vraie date antérieure par un "aujourd'hui" de bootstrap (c'est exactement le bug audit "date perdue au tour suivant", évité par construction plutôt que corrigé après coup).
   - `resolve_search_timeslot` (before_tool) : combine `timeSlot` (minutes) + `duration` virtuel en fenêtre EXACTE (minutes-du-jour), floor/ceil vers les heures entières que MCP accepte réellement, stashe la fenêtre exacte (`STATE_EXACT_WINDOW_KEY`) pour la capture + le post-filtre. **Une durée sans AUCUNE heure de départ (ni fraîche, ni `profile_in.timeslot_start` porté) n'invente aucune fenêtre** — `timeSlot` est simplement omis (ferme `core-e2e-201` par construction).
2. **`response_bridge.py`** : post-filtre exact-minute (`_offer_fits_exact_window`, appliqué dans `normalize_hotel`/`normalize_search_results` — un hôtel dont AUCUNE offre ne tient dans la fenêtre exacte est retiré) ; si le filtre strict vide tout mais que la fenêtre heure-arrondie MCP avait des résultats → **fallback** vers ces résultats + disclosure honnête dans `_outcome_text`/`emit_search_datapart`/`skip_final_generation` (jamais un 0 silencieux) ; `capture_after_tool` recapture `timeslot_start`/`timeslot_end` EXACTS depuis `STATE_EXACT_WINDOW_KEY` (l'ancien `_budget_timeslot_from_args` force toujours `:00` — c'était le bug `core-e2e-084` — resté en fallback pur pour compat, jamais utilisé une fois `resolve_search_timeslot` câblé) ; `emit_search_datapart` mappe `STATE_RESOLVED_DATE_KEY` vers `profile_delta.date`/`date_reference`.
3. **`agent.py` (feuille)** : instruction réécrite (date = label jamais calculé, duration distinct de timeSlot, minutes explicites) ; `inject_today_before_model` reformulé — injecte TODAY pour contexte SEULEMENT, interdit explicitement au modèle de calculer quoi que ce soit (avant : le modèle convertissait lui-même "demain"→date, exactement la violation "le LLM calcule" que cette phase corrige) ; wiring des 2 nouveaux callbacks.
4. **`profile.py` (concierge)** : nouveau champ persisté `client_timezone` (tranche le punt S-G2 : dédié + recopié dans `date_reference.client_tz` à la résolution, pas SEULEMENT niché) ; `apply_profile_delta` le porte en carryover.
5. **`facade.py`** : `_parse_client_timezone` (validation IANA via `zoneinfo.ZoneInfo`, même patron que locale/currency/domain) câblé dans `_native_context_delta`. **`client_local_time` reste délibérément non consommé** — un clock d'appareil peut être faux ; l'horloge serveur + un timezone validé est l'ancre plus sûre (décision documentée en commentaire, remplace le punt S-G2).
6. **Bug trouvé en passant (S-G1, pas cette session) et corrigé ici** : `build_active_filters` exposait `date_reference` mais **jamais `date`** (le champ ISO plat) — un oubli qui aurait rendu tout check de date en observabilité (dont `scripts/eval_hardening.py::check_date_reference`, câblé en S-G8 par anticipation) structurellement impossible à vérifier. Ajouté, avec `client_timezone`.
7. **Affichage minute-exact** : `templates._format_time_slot`/`booking_offer_summary_response` prennent désormais des chaînes "HH:MM" (`start_time`/`end_time`) au lieu d'entiers d'heure forcés à `:00` ; `inline_tools._quote_fresh_offer` capture `offer.startMinute`/`endMinute` réels.
8. **`reports/MCP-B2C-REQUESTS.md` (neuf)** : demande cross-repo `startMinute`/`endMinute` sur `search_offers` (A4-a), avec la condition de retrait exacte de l'intérim client-side (A4-c) une fois honorée.

**DoD verte** : `pytest -q` (repo) → **833 passed** (leaf 270→**318**, +48 ; concierge 321→**329**, +8 ; reste des tests neufs dans `test_datetime_resolver.py`) ; **1 échec préexistant, SANS RAPPORT** (`tests/test_llm_meter_usage.py::test_usage_record_extracts_tokens_and_model` — un fichier untracked laissé par une session S-B différente, bug d'arrondi flottant `432.1 == 432.2`, confirmé préexistant et hors zone `agents/**`, non touché) ; `ruff check .` OK ; `mypy agents libs` → 38 fichiers OK (un `Any | None` sur `dict.get()` a nécessité une annotation locale explicite, cf. pièges) ; `bash scripts/dayuse_guardrails.sh .` OK.

**Vérifié LIVE (3 services locaux, MCP staging réel + LiteLLM réel via `.env`)** — les 4 vérifications de l'étape 4 + 2 extensions ciblées :
1. **« hôtel à Paris demain entre 7h30 et 13h30 »** → `active_filters`: `date="2026-07-24"` (`date_reference.resolved_from="relative"`, `expression="demain"`), `timeslot_start="07:30"`, `timeslot_end="13:30"` (EXACT, pas `:00` — `core-e2e-084` fermé) ; **3 hôtels** dont ceux dont l'offre tient réellement dans la fenêtre (confirmé par probe MCP direct : Villa Paris Orly 8h-13h, OKKO 8h-12h fits ; Novotel 7h-12h et Campanile 10h-14h correctement exclus).
   - Sans date (« hôtel à Paris entre 7h30 et 13h30 », donc AUJOURD'HUI) → 0 résultat, vérifié HONNÊTE par un probe MCP direct sur la même date/fenêtre : le serveur lui-même ne renvoie déjà plus aucune offre matinale pour une recherche same-day à l'heure courante (comportement MCP documenté : « same-day searches drop offers that already ended ») — pas un bug.
2. **« une chambre à Paris pour une heure »** → `timeslot_start`/`timeslot_end` **tous deux `null`** (AUCUNE fenêtre 00:00-01:00 inventée, `core-e2e-201` fermé), `budget_max` **`null`** (aucun budget halluciné à partir de « une heure »).
3. **« hôtel à Paris demain »** (seul) → `date="2026-07-24"`, `date_reference={"resolved_from":"relative","expression":"demain"}` — date ISO correcte en profil.
4. **Suivi vague « plus tôt »** (même session, après « hôtel à Paris demain ») → **rien d'inventé** : `timeslot_start`/`end` restent `null`, `date` reste `"2026-07-24"` (identique au tour précédent, ni changé ni effacé). Observation annexe (hors périmètre S-G6, routing pas extraction) : le modèle n'a pas rappelé les tools ce tour (aucun `tool_call` dans les logs feuille pour cette invocation) — la réponse recycle le ground-truth de `profile.last_results` ; comportement honnête (rien d'inventé) mais pas une vraie ré-recherche.
5. **Extra — fallback A4-c déclenché réellement** : « hôtel à Paris demain entre 8h15 et 12h45 » (fenêtre choisie pour qu'aucune offre échantillonnée ne tienne EXACTEMENT dedans) → réponse : *« J'ai trouvé 5 offres de jour à Paris pour demain, mais aucune ne couvre exactement la plage horaire demandée. Voici les options les plus proches »* — disclosure honnête, 5 hôtels affichés (jamais un 0 silencieux), `timeslot_start`/`end` toujours capturés exacts (`08:15`/`12:45`).

**Reste (pour les sessions suivantes)** :
- **MCP minute-level filter** : demande ouverte, `reports/MCP-B2C-REQUESTS.md` (condition de retrait de l'intérim documentée).
- **`_eval_clock`** : le harness d'éval (`dayuse_eval_pack/eval_pack/runner.py:674-677`) envoie déjà un champ `_eval_clock` test-only au payload (« adapters should use this as their notion of now », actuellement ignoré silencieusement par la façade) — **non câblé cette session** (hors DoD, aucun check live ne l'exigeait). Sans lui, `scripts/eval_hardening.py::check_date_reference` (S-G8) ne pourra donner un signal fiable qu'à condition que l'horloge réelle du serveur au moment du run corresponde à ce que la fixture attend — à trancher en S-G9 (soit câbler `_eval_clock` comme override test-only de `reference_today`, soit accepter que ce check reste approximatif hors gate figée).
- **Turn "plus tôt" sans ré-recherche** (point 4 ci-dessus) : comportement observé, pas un bug de CE périmètre (extraction date/durée/minute) — potentiellement un sujet de routing/instruction pour une session future si jugé prioritaire.
- **`client_local_time`** : toujours non consommé (décision, pas un oubli) — voir le commentaire `facade.py` mis à jour.

**Pièges découverts** :
- **Le module `INSTRUCTION` de la feuille est `.format()`-é** (`agent.py`, `.format(amenity_keys=...)`) — toute accolade littérale ajoutée dans le texte (ex. exemples JSON `{"type": "relative", ...}`) casse le format avec un `KeyError` cryptique au chargement du module. Écrit en prose au lieu d'accolades littérales — à refaire pareil pour toute future édition de ce texte.
- **`dict.get(key)` sur un `dict[str, Any]` typé strictement ne s'infère PAS toujours en `Any` pour mypy** — `int(offer.get(hour_key))` inline lève `Any | None` incompatible avec `int()` malgré le `try/except (TypeError, ValueError)` autour ; il faut d'abord affecter à une variable locale annotée `Any` explicitement.
- **Auto-correction en session** : un `git stash --include-untracked` lancé pour isoler une hypothèse a temporairement effacé tout le travail non commité de cette session (`git stash pop` immédiat a tout restauré, `pytest -q` reconfirmé vert après) — ne jamais utiliser `git stash` pour une vérification ponctuelle quand le seul besoin est de comparer un fichier isolé ; `git show HEAD:<path>` ou un worktree séparé sont sans risque.
- **Probe MCP `date=aujourd'hui` piégeux à interpréter** : un probe MCP direct avec la date du jour et une fenêtre matinale peut légitimement renvoyer 0 (comportement same-day documenté par le schéma MCP lui-même) — toujours reprobe avec une date FUTURE avant de conclure à un bug du post-filtre exact-minute.

**Merge** : cette branche (`sg6-dates-durations-minutes`) n'est pas mergée cette session — review humaine de Fabien = le gate.

## ⏱ Addendum 2026-07-23 (branche `sg8-harness-hardening`, worktree dédié) — S-G8 : durcissement du harness d'éval (8 items, zéro modif du pack)

**Contexte** : fenêtre (S-G2 ∥ S-G5 ∥ S-G8), zone stricte `scripts/**` + `tests/**` — `dayuse_eval_pack/eval_pack/**` jamais touché (byte-identique, vérifié par `git status`/`git diff --stat` avant commit), `agents/**` jamais touché. Les 8 items viennent de `REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md` § « Durcissements du harness » : une couche d'annotation/scoring PAR-DESSUS un rapport déjà produit par `eval_pack.runner` (jamais modifié), avec la règle absolue : un champ indisponible dans le schéma = `skipped: field_missing` divulgué, jamais un faux vert.

**Étape 1 (mapping item → champ, constat sur un run réel avant tout code)** — inventaire fait sur `AgentB2C/dayuse_eval_pack/eval_pack/results/candidate_staging.json` (run S-A du 2026-07-21, 249 cas, seul résultat réel disponible dans les 4 worktrees) :
1. `min_hotels` geo → `hotels` (longueur) + les types d'assertion déjà présents dans `cases/geo.jsonl` (`hotel_countries`/`min_hotels`/`max_hotels`).
2. 3-classes → `requires_clarification` (contrat top-level), `message`/`response` (phrases de dégradation honnête connues), `hotels` (vide/non-vide), `_http_status`/`_client_error`.
3. Pays+ancre à shortlist vide → `active_filters.country_code`/`active_filters.resolved_city` (exposés depuis S-G1, `agent-usa` les avait déjà).
4. Assertions par tour → `active_filters.{currency,timeslot_start,timeslot_end,date,zone,named_hotel}` (tous dé-nullés en S-G1) + le `clock`/`tags`/`request.currency` DE LA FIXTURE elle-même (jamais une valeur attendue codée en dur) pour dériver mécaniquement l'attendu.
5. Distance → `hotel.distance_km`/`hotel.latitude`/`hotel.longitude` (exposés depuis S-G3, A8-a) + `active_filters.distance_origin` (dict `{latitude,longitude,label,type}` — **attention, le typage `str | None` dans `profile.py:158` est un vestige, la vraie forme runtime est un dict, vérifié via `response_bridge.py:376-381`**).
6. « Autres options » → uniquement les cartes hôtel (id) de deux tours consécutifs + le texte du message — **ne dépend PAS de S-G5** (le mécanisme interne `shown_hotel_ids` n'est jamais lu ; le check observe le comportement externe, donc il score déjà correctement même avant que S-G5 câble l'exclusion réelle).
7. Score triple → `passed` (déjà dans le rapport) + la classification de l'item 2 + `_http_status`/`_client_error` pour le taux de timeout.
8. Replay ×3 → les 3 fichiers `cases/{geo,multiturn,prod_wounds}.jsonl` (41+27+13 = **81**, vérifié par test contre les vraies fixtures).

**Fait** :
- **`scripts/eval_hardening.py`** (items 1-2-3-4-5-6-7) — stdlib pur, aucun import de `dayuse_eval_pack/` ni `agents/` (le harness reste black-box comme le pack lui-même) : `geo_cases_missing_min_hotels`/`check_min_hotels_added`, `classify_turn_outcome`/`classify_case_outcome` (4 classes : `successful_search`/`safe_clarification`/`technical_degradation`/`no_result_honest` — le 4e bucket évite de forcer une classification fausse sur un « 0 résultat honnête » qui n'est ni une dégradation ni une clarification), `check_anchor_resolved_when_empty`, `check_currency_per_turn`/`check_timeslot_minutes`/`check_zone_change`/`check_named_hotel_present`/`check_date_reference` (item 4, chacun dérivé mécaniquement de la fixture — tag `zone_change`/`named_hotel_present`, `request.currency`, `clock`+mot-clé today/tomorrow — jamais une valeur attendue à la main), `check_distance_verifiable`, `check_other_options` (regex fr/en sur « other/different/cheaper options »/« autres options », turn>1 seulement), `build_triple_report`, `annotate_report`/`annotate_result` (orchestration).
- **`scripts/eval_replay_stability.py`** (item 8) — `critical_suite_case_ids()` (81 cas, lu depuis les fixtures) + `compute_stability()` (pure, distingue `unstable` — un cas dont le verdict change entre runs — de `incomplete` — un cas absent d'un run, jamais confondu avec un verdict) + `replay()`/`invoke_runner_subprocess()` (orchestration `python -u -m eval_pack.runner`, cwd `dayuse_eval_pack/`, style identique à `run_release_gate.py`). **Non exécuté contre un endpoint live cette session** (aucun service tournant, hors DoD de la phase qui ne demande que la démo sur un `results/*.json` existant) — la logique pure et le câblage subprocess sont testés avec un invoker injecté (aucun réseau).
- **Tests** : `tests/test_eval_hardening.py` (47 tests) + `tests/test_eval_replay_stability.py` (10 tests), tous sur fixtures synthétiques (sauf 2 tests qui lisent les VRAIES fixtures `dayuse_eval_pack/eval_pack/cases/` en lecture seule pour verrouiller l'item 1 et le compte 81 de l'item 8).

**Démo (DoD de la phase)** : `scripts/eval_hardening.py` exécuté sur le run réel `candidate_staging.json` (249 cas, S-A) → `raw 110/249 (44.2 %)` (identique au chiffre déjà publié dans `EVAL-PACK-COMPARISON-2026-07-22.md`, confirme que rien n'a été inventé) ; `excluding_technical_degradation 107/222 (48.2 %)` (27 cas exclus) ; `outcome_counts = {successful_search:119, safe_clarification:0, technical_degradation:27, no_result_honest:103}`. Ce run précède les waves S-G1/S-G3 (mergées depuis) : `zone_change`/`date_reference`/`distance_verifiable`/certains `named_hotel_present` sortent honnêtement `skipped: field_missing` (champs encore nuls à l'époque de ce run) — attendu, pas un bug du harness.
**Trouvaille concrète (preuve que la couche ajoute un vrai signal, pas juste de la plomberie)** : `timeslot_minutes` remonte **4 échecs**, dont `core-e2e-084` (le bug déjà nommé dans l'addendum S-A : « 7h30-13h30 » tronqué en « 07:00-13:00 ») **ET 3 cas jamais nommés individuellement avant** (`core-e2e-074`, `core-e2e-075`, `core-e2e-076`, même famille de bug, même signature `timeslot_start/end` arrondis à `:00`) — la couche de durcissement trouve strictement plus que le triage manuel de S-A sur ce point précis.

**DoD verte** : `pytest -q` (repo, depuis ce worktree, `.venv` du worktree principal réutilisé) → **704 passed** (+57, aucune régression) ; `ruff check .` OK ; `mypy agents libs` → 37 fichiers OK (inchangé, ce module est un script autonome hors `agents`/`libs`) ; `bash scripts/dayuse_guardrails.sh .` OK.

**Reste (pour S-G9, ou une session future si besoin de re-couvrir)** :
- Un run LIVE frais (services `run_local.sh` + `run_eval_adapter.py` up) donnerait un signal plus riche sur les items 3/4/5 puisque S-G1/S-G3/S-G4 sont mergés depuis ce run S-A — non fait cette session (hors scope/DoD, aucun service requis n'était up).
- `eval_replay_stability.py` n'a jamais tourné contre un vrai endpoint (uniquement testé avec un invoker factice) — **c'est exactement le rôle de S-G9** (qui possède le run de gate + le verdict merge/no-merge, explicitement hors périmètre S-G8).
- Item 6 (« autres options ») ne trouve aujourd'hui que 2 cas dans tout le pack (`prod-wound-auckland-nzd-sticky`, `prod-wound-more-options-not-repeat`) — mécanique mais peu de couverture ; si le pack grossit ce nombre grandira automatiquement (regex sur le texte, pas une liste figée).
- `active_filters.date_reference` (dict `{expression,resolved_from,client_tz}`) vs la fixture `filter_equals: {"date_reference": "tomorrow"}` (string) — écart de forme déjà noté au registre S-A (« 6 = gap d'exposition… »), pas re-traité ici (mon check `date_reference` cible volontairement `active_filters.date`, le champ ISO plat, pas `date_reference`).

**Pièges découverts** :
- `profile.py:158` type-hint `distance_origin: str | None` est trompeur — la valeur réelle stockée est un dict (`{latitude,longitude,label,type}`, cf. `response_bridge.py:376-381`) ; Python ne vérifie pas les type hints à l'exécution donc aucun bug réel, mais un futur mypy strict sur ce fichier le signalerait — à corriger si quelqu'un touche `profile.py` (hors périmètre scripts/tests de cette session).
- `dayuse_eval_pack/tests/test_runner.py` n'est PAS dans `testpaths` de `pytest.ini` racine (`agents libs evals tests`) — ce test existant est mort du point de vue de `pytest -q` à la racine, indépendant de cette session (jamais touché, `dayuse_eval_pack/**` intouchable).
- Ce worktree n'a pas son propre `.venv` (comme S-G1/S-G3) — `.venv` du worktree principal réutilisé depuis le cwd de `AgentB2C-sg8`, vérifié que `pytest -q` importe bien 704 tests cohérents avec ce worktree (pas de résolution croisée).

**Merge** : cette branche (`sg8-harness-hardening`) merge **EN DERNIER** de la fenêtre (après `sg2-native-context` et `sg5-bridge-pagination`, rebase requis) — pas mergée cette session, review humaine de Fabien = le gate.

## ⏱ Addendum 2026-07-23 (branche `sg5-bridge-pagination`, worktree `../AgentB2C-sg5`) — S-G5 : pont déterministe profil→outils + pagination « autres options », + BUG RACINE trouvé et corrigé (find_datapart)

**Contexte** : fenêtre S-G2 ∥ S-G5 ∥ S-G8 (après S-G1 + S-G3 mergées). Zone : `agents/hotel_search_agent/**` (callback d'injection, émission ops, `from`-offset) + `agents/b2c_concierge/**` (exclusion shown_ids, curseur, disclosure, `a2a_datapart.py`) + tests. `facade.py` et `scripts/` d'annotation non touchés (zone S-G2/S-G8). Rebasée sur `main` après le merge de `sg2-native-context` (voir addendum S-G2 juste en dessous) — zéro conflit de code (seul `HANDOFF.md` en conflit, les deux addenda touchant la même zone d'insertion).

**PROBE A7 (obligatoire avant de coder la pagination, MCP staging réel, token du repo)** :
- `search_offers` accepte bien `from` (offset, défaut 0) / `size` (page, défaut 10, max 50) et renvoie `total`/`has_more`/`next_offset`. Un `from` avancé d'une page pleine renvoie des IDs **réellement disjoints** (vérifié : Miami `from=10,size=5` → 5 IDs, zéro intersection avec `from=0`). **Aucun paramètre d'exclusion** (`excludeHotelIds` ou assimilé) n'existe — un nom de clé inconnu (`limit`/`offset`) est un **rejet dur** de validation Zod côté serveur (`additionalProperties: false`).
- **Décision A7 retenue** : le `from`-offset MCP natif est le moteur PRINCIPAL de pagination (déterministe, code-owned, jamais confié au LLM) ; `shown_hotel_ids` (déjà accumulé côté profil depuis S-G1) reste un filet de sécurité côté client, appliqué **avant** la coupe top-5 — utile si le `from` calculé et le contenu réel divergent (page-size différente d'un tour à l'autre, drift de ranking ES).

**Fait** :
1. **`hotel_search_agent/geocode_tool.py::inject_profile_geo_context`** (nouveau `before_tool_callback`, pattern exact `enforce_equipment_filters`) — comble `city`/`zone`/`metro`/`country_code` **manquants** depuis `profile_in` (une valeur fraîchement extraite par le LLM CE tour gagne toujours, jamais réécrite) ; `profile_state_context`/`profile_location_hint` sont désormais **toujours** sourcés du profil (ce sont par définition l'ancre d'un tour précédent, jamais une extraction fraîche — l'instruction de la feuille est allégée d'autant, elle ne demande plus au modèle de les recopier) ; `proximity_lat`/`proximity_lon` (2 nouveaux paramètres optionnels de `geocode_location`) sont sourcés de `profile_in.search_anchor` (champ S-G1, **peuplé par S-G2 — désormais mergée**, cf. addendum ci-dessous : le GPS device réel transite bien par ce champ dès que `permission=="granted"`). Threadé jusqu'à `mapbox_client.geocode_candidates(proximity="lon,lat")` et `geo_resolver.resolve(proximity=(lat,lon))` (les deux acceptaient déjà ce paramètre depuis S-G3, jamais sourcé jusqu'ici — la chaîne facade→profil→feuille est maintenant complète bout-en-bout).
2. **`zone`/`metro` enfin persistés au profil** (gap identifié par `code-verification-memo.md` claim 3 : acceptés par `geocode_tool`, validés par l'echo guard, **jamais** transmis en `profile_delta`) — `_ok()` dans `geocode_tool.py` les ajoute désormais (only-when-present, pas de nouvelle sémantique d'invalidation).
3. **Émission ops geo côté feuille** — `emit_search_datapart` (`response_bridge.py`) passe `city`/`state_anchor`/`country_anchor`/`zone`/`metro` au format S-G1 `{"op":"set","value":...}` (migration de forme uniquement, sémantique byte-identique — le reducer accepte les deux formats depuis S-G1). `amenities`/`budget`/`timeslot` restent au format plat (hors périmètre).
4. **Pagination** — `response_bridge.inject_pagination_offset` (avant_tool_callback sur `search_offers`) : `args["from"] = profile_in.search_cursor * MAX_RESULTS` (5), **toujours** recalculé côté code (un `from` que le modèle inventerait est écrasé — même doctrine que `hotelEquipmentIds`). `normalize_search_results` filtre désormais `exclude_ids` (le `shown_hotel_ids` du profil) **avant** la coupe top-5. `profile.py::is_more_options_signal` (nouveau détecteur, distinct de `is_search_refinement_signal` — seul lui avance le curseur) + `is_search_refinement_signal` étendu pour router "autres options"/"other options"/"show me more" vers `search` même si triage se trompe. `agent.py` : `advance_search_cursor` appelé avant l'appel feuille quand `is_more_options_signal` ; au retour, si `more_options and results_count == 0` → **exhaustion immédiate** (`profile.search_exhausted = True`, zéro appel LLM de synthèse, même tour — pas d'attente de streak comme le S12 budget-driven) — étend `templates.search_exhausted_response` avec un nouveau paramètre `reason="pagination"` (message dédié : « vous avez vu tous les hôtels… élargir le budget/la zone/retirer un filtre » — jamais le même flag/gabarit ni une machine parallèle).

**⚠️ BUG RACINE trouvé (par la preuve live de CETTE session, pas par les tests unitaires) et corrigé — `find_datapart` (2 miroirs : `hotel_search_agent/response_bridge.py` et `b2c_concierge/a2a_datapart.py`)** :
- Symptôme : la preuve live "autres options → nouveaux IDs" échouait à 100 % — les 6 premiers tours renvoyaient **exactement les 5 mêmes hôtels**, alors que `search_cursor` était correctement incrémenté et persisté côté concierge (vérifié directement en Redis : `search_cursor` montait bien 0→6).
- Cause : côté feuille, `tool_context.user_content.parts` **accumule le DataPart de CHAQUE tour sur toute la session A2A** (vérifié en direct : `n_parts` croît 2→6→10→14→18→22→26 tour après tour) — l'ADK de la feuille garde l'historique complet, contrairement à la boucle par-événement de `_run_leaf` côté concierge qui retombe naturellement sur le dernier (elle écrase `response` à chaque événement). `find_datapart` renvoyait le **PREMIER** DataPart décodable trouvé dans cette liste croissante = **celui du tour 1, pour toujours**.
- Portée réelle : ce bug touchait **silencieusement tous les ponts déterministes profil→outil** existants (`equipment_ids._profile_amenities`, et maintenant les 2 nouveaux de cette session) — masqué jusqu'ici parce que `city`/`amenities` restent SOUVENT identiques au tour 1 dans les scénarios testés (et parce que le modèle, voyant l'historique de conversation complet, peut « deviner » correctement la ville/les amenities par lui-même, masquant encore plus le problème). Seul `search_cursor` (jamais coïncidentellement égal à sa valeur du tour 1) l'a rendu visible sans ambiguïté.
- Fix : `find_datapart` renvoie désormais le **DERNIER** match décodable, jamais le premier — dans les 2 fichiers miroirs, avec un test de non-régression dédié dans chacun (`test_find_datapart_prefers_the_last_match_over_the_first`). Comportement identique dans le cas à un seul DataPart (l'immense majorité des tests existants) — changement sûr, aucune régression.
- **Pas introduit par S-G5** — bug latent depuis S-G1/S3/S10 au minimum, jamais détecté parce que jamais vérifié en LIVE multi-tours avec un signal qui ne peut PAS coïncider avec le tour 1. Corrigé ici parce qu'il bloquait la preuve live exigée par cette phase, et parce qu'il est root-cause/in-scope (les 2 fichiers touchés sont dans le périmètre autorisé).

**DoD verte** : `pytest -q` → **689 passed** (+42 vs baseline 647 : 24 feuille + 18 concierge) ; `ruff check .` OK ; `mypy agents libs` → **37 fichiers** OK ; `dayuse_guardrails.sh` OK.

**Vérifié LIVE (3 services locaux, MCP staging réel + Mapbox réel via `.env` copié du worktree principal)** :
- Session réelle multi-tours, `/v3/chat` : « hotel a Paris » → 5 hôtels (IDs `[22293, 16692, 18100, 9736, 21325]`) → **6× "autres options"** → **5 hôtels NOUVEAUX à CHAQUE page, zéro chevauchement** avec tout ce qui a été vu avant (`overlap: set()` sur les 6 tours) — `search_cursor` 0→6 confirmé en Redis, `shown_hotel_ids` plafonné à 25 (`MAX_SHOWN_HOTEL_IDS`) avec les 25 IDs les plus récents.
- **Épuisement réel** : curseur forcé à 200 (`from=1000`, très au-delà du total réel Paris = 522) via Redis → tour suivant "autres options" → réponse **exactement** le gabarit `reason="pagination"` (« Vous avez vu tous les hôtels correspondant à vos critères à Paris. Voulez-vous que j'élargisse le budget, la zone, ou que je retire un filtre ? »), `hotels: None`, `search_exhausted: True` persisté, **zéro appel LLM de synthèse** ce tour.
- Probe A7 elle-même vérifiée en direct (MCP staging, Miami + Paris) avant tout code — schéma `search_offers` capturé en clair (`from`/`size` confirmés, `limit`/`offset` rejetés).

**Reste / pièges découverts** :
- Le fix `find_datapart` corrige le principe partout où la fonction est utilisée, mais seul le chemin pagination a été vérifié en LIVE multi-tours ; si un futur audit live révèle un AUTRE champ « toujours figé au tour 1 », ce sera la même cause, déjà corrigée — pas un nouveau bug à chercher.
- Reset du curseur/`shown_hotel_ids` sur changement de contrainte **non-ville** (budget/zone/amenities) : **hors périmètre** de cette session — seul un changement de ville les réinitialise (règle S-G1, non retouchée). Simplification consciente, documentée, pas un bug.
- **Worktree sans venv propre confirmé à nouveau** (même piège que S-G3) : `bash scripts/run_local.sh` échoue avec un `uvicorn` système (Python 3.13 Homebrew, sans les packages) tant qu'aucun `.venv` n'existe ici — un symlink temporaire vers le `.venv` du worktree principal a permis de lancer les 3 services pour la preuve live, **retiré en fin de session** (même discipline que S-G3). `.env` copié depuis le worktree principal **laissé en place** (gitignored, artefact de dev normal par worktree, nécessaire pour relancer les services dans une session future sans redemander les secrets).
- Cross-repo MCP_B2C : aucune demande à ouvrir pour la pagination — `from`/`size` suffisent, pas besoin d'un `excludeHotelIds` côté serveur.
- **Merge** : cette branche merge **APRÈS `sg2-native-context`** (native context / facade), **rebasée avec succès** — prête pour MR.

## ⏱ Addendum 2026-07-23 (branche `sg2-native-context`, worktree `AgentB2C-sg2`) — S-G2 : intake contexte natif (facade → profil) — ⚠️ payload réel ≠ hypothèse du brief

**Contexte** : fenêtre S-G2 ∥ S-G5 ∥ S-G8 (S-G1/S-G3/S-G4 déjà mergées sur `main`). Zone stricte `agents/b2c_concierge/**` (`facade.py` + tests) — feuille (`agents/hotel_search_agent/**`) et `scripts/` non touchés (`git status --short` confirme : `facade.py` modifié + 2 fichiers de tests neufs, rien d'autre).

**Probe du widget vendorisé AVANT tout code (`web/vendor/static/js/chat/`) — divergence majeure avec l'hypothèse du brief S-G2, à ne jamais reconstruire sans re-probe** :
- Le payload réel `POST /v3/chat` envoie `locale`/`currency` en **top-level** (`handlers/send.js:298-362` : `state.marketContext.language`/`.currency`), **PAS** nichés sous `native_context`.
- **Le GPS transite par `client_geo_context.device.{latitude, longitude, accuracy_m, permission}`** (`handlers/send.js:266-292`), envoyé **seulement** quand le message demande explicitement la position appareil (regex `near me`/`use my location`/`près de moi`/… , `explicitlyRequestsDeviceLocation`) **ET** que `navigator.geolocation` a répondu. `permission` ∈ `{"granted","denied","unavailable"}` ; `latitude`/`longitude` présents **seulement** si `"granted"`.
- **`native_context`** (`window.__DAYUSE_NATIVE__`, injecté par la webview mobile) est un **blob opaque** : son propre commentaire (`utils.js:12-15`) dit qu'il porte « recent bookings, favourites, geolocation » mais **aucun nom de champ n'est défini nulle part dans ce snapshot vendorisé** — c'est l'objet propre de l'app native, pas documenté ici. L'hypothèse du brief (`native_context.geolocation {latitude, longitude, accuracy?}`) est donc **invérifiable** — je ne l'ai PAS codée (inventer un schéma sans preuve = exactement ce que la consigne « le payload réel = la spec » interdit). `native_context` est accepté sans jamais planter, mais reste non décodé. **Item ouvert** : quand l'équipe mobile documentera son schéma réel (probablement pas dans ce repo), un futur `native_context.geolocation` pourra être ajouté à `_parse_gps_anchor`/`_native_context_delta` en second lookup.
- `domain` n'est en réalité **jamais envoyé dans le body** par ce widget (il vit dans une balise `<meta>` HTML rendue côté serveur, jamais réémise dans le POST JSON) — parsing implémenté quand même (défensif/forward-compat pour un futur client), documenté comme non exercé par le trafic réel probé.
- `client_local_time`/`client_timezone` sont bien envoyés (confirmé, `getClientTimeContext()`), mais **délibérément pas persistés** cette session : `client_local_time` est un instant par-requête (jamais un carryover sûr), et la bonne maison de `client_timezone` (champ dédié vs `date_reference.client_tz`) est un choix de design qui appartient à S-G6 (résolution de dates), explicitement HORS périmètre ici — l'inventer aurait risqué une double implémentation contradictoire.
- Découvertes additionnelles hors liste du brief, notées mais **non câblées** (hors périmètre exact) : `entry_market_country` (top-level, dupliqué avec `currency`/`locale` à des fins de marché) et `selected_place` (toujours `null` dans ce snapshot, forme jamais observée — aucun composant ne l'alimente dans ce vendor).

**Fait (`facade.py` uniquement)** :
1. **Parsing + validation** (`_parse_locale`/`_parse_currency`/`_parse_domain`/`_parse_gps_anchor`) — tout optionnel, absent-tolérant, **jamais de 500** sur un champ invalide (type erroné, hors-plage, forme opaque) : validation stricte (`lat ∈ [-90,90]`, `lon ∈ [-180,180]`, nombre réel non-bool, locale BCP-47-ish, currency ISO4217-ish 3 lettres, domain hostname-ish) — une valeur invalide est **ignorée en silence**, jamais propagée.
2. **`_native_context_delta`** compose un delta `{locale?, currency?, domain?, search_anchor?}` — un champ absent/invalide n'apparaît PAS dans le delta (= carryover garanti par le reducer typé S-G1, `apply_profile_delta`). GPS → `search_anchor {type:"gps", lat, lon, label:None, set_at_turn}` **seulement** quand `permission=="granted"` et coordonnées valides — c'est CE mécanisme (rien dans le delta = carryover) qui implémente la règle no-silent-downgrade, **sans aucun changement au reducer S-G1** (déjà correct par construction : `search_anchor` n'est cleared que sur un changement de ville EXPLICITE, `profile.py:401-409`).
3. **`_apply_native_context`** — appelé dans `chat()` ET `chat_stream()` juste après résolution de `session_id`/`turn_index`, **avant** `_drive(...)` : charge le profil Redis, applique le delta natif (`apply_profile_delta`), sauvegarde — pour que la feuille voie déjà le contexte via `profile_in` dans CE MÊME tour (l'usage réel — Mapbox proximity S-G3/S-G5, devise d'affichage S-G7 — reste hors périmètre ici, ce n'est QUE le transport facade→profil). Zéro aller-retour Redis quand la requête ne porte aucun de ces champs optionnels.
4. **`build_active_filters`** expose désormais `locale`/`domain`/`search_anchor` (même pattern que `currency`/`zone`/etc. posé par S-G1) — observable via le contrat public, `CONTRACT_KEYS` top-level intouché (test golden `TestContractKeysUntouched` toujours vert).
5. **`response_language`** — précédence `profile.language or _locale_response_language(profile.locale) or guess_language(message)` : **`profile.language` (la langue réellement déterminée ce tour par le triage/la feuille) garde la priorité sur `locale`** — décision délibérée, PAS littéralement ce que dit le brief (« préfère locale quand présent ») : préférer `locale` EN PREMIER créerait un vrai risque de désync entre `response_language` annoncé et la langue RÉELLEMENT synthétisée (cette facade ne pilote pas la langue de génération — c'est `triage.language`, hors zone de cette session). `locale` s'insère donc comme un meilleur *fallback* que le défaut anglais silencieux de `guess_language`, jamais comme un override de ce qui a été effectivement généré. Même logique appliquée à `_empty_ack_text` (chemin zéro-LLM) qui accepte maintenant un `locale` optionnel.
6. **RGPD** : aucun nouveau point de log/métrique ajouté — le seul log touché par le chemin natif est le compteur existant `_log_profile_ops` (S-G1, noms de slots uniquement, jamais de valeur), déjà safe. Testé explicitement de bout en bout (`test_gps_coordinates_never_appear_in_logs_or_metrics`, DEBUG + `enqueue_metric_event` capturé) : les coordonnées réelles n'apparaissent nulle part.

**DoD verte** : `pytest agents/b2c_concierge -q` → **311 passed** (+18, `test_native_context.py`, unitaire pur) ; `pytest tests/api -q` → **48 passed** (+11, `test_native_context_http.py`, bout-en-bout via l'app ASGI réelle + fakeredis) ; `pytest -q` (repo) → **676 passed** ; `ruff check .` OK ; `mypy agents libs` → **37 fichiers** OK (narrowing explicite `isinstance` sur `lat`/`lon` nécessaire — `math.isfinite` seul ne suffit pas à mypy à partir d'un `Any` de dict) ; `bash scripts/dayuse_guardrails.sh .` OK. `git status --short` confirme la zone : `facade.py` modifié + 2 fichiers de tests neufs, rien dans la feuille ni `scripts/`.

**Scénario bout-en-bout vérifié (le cas DoD exact)** : tour 1 (GPS `granted`, ack) → `active_filters.search_anchor` porte `{type:"gps",...}`, profil Redis confirmé (`store.get` direct) ; tour 2 (même session, aucun signal de lieu) → ancre **conservée** ; tour 3 (nouvelle ville explicite via une feuille stubbée, delta `city` différent) → ancre **remplacée** (cleared) par la règle S-G1 déjà existante (`profile.py:401-409`) — **zéro changement au reducer nécessaire**, seul le câblage facade→delta manquait.

**Reste (pour les sessions suivantes)** :
- **S-G3/S-G5** : `search_anchor` existe et persiste correctement mais n'est **pas encore lu** par le géocodeur (`proximity` Mapbox) — c'est le prochain consommateur, explicitement hors périmètre ici (déjà noté dans le plan).
- **`native_context.geolocation` mobile** : schéma non défini dans ce repo — si le besoin devient réel (app mobile en prod), il faudra soit obtenir le schéma exact de l'équipe app, soit l'observer en direct (logs de prod anonymisés) avant de coder un second chemin GPS dans `_parse_gps_anchor`.
- **`entry_market_country`** (champ réel du widget, absent du brief) et **`selected_place`** (forme jamais observée) : notés, non mappés — candidats naturels pour S-G7 (locale/devise) si un besoin se matérialise.
- **`client_timezone`** : lu par personne encore — S-G6 devra décider de sa maison (champ dédié vs `date_reference.client_tz`) avant de le persister ; le probe ci-dessus (champ réellement envoyé, forme confirmée `Intl.DateTimeFormat().resolvedOptions().timeZone`) lui sert de spec toute prête.
- **`domain`** : parsing prêt mais non exercé par le widget réel (jamais envoyé en body) — si un jour un autre client (mobile ?) l'envoie, le mapping fonctionne déjà ; sinon, la résolution domaine/marché réelle (`X-Dayuse-Domain`/`Origin`/`Referer`, mentionnée en commentaire JS comme comportement de l'ANCIEN backend agent-usa) reste à bâtir ailleurs si besoin (S-G7 ?), PAS via ce champ de body.
- Cette branche (`sg2-native-context`) doit **merger EN PREMIER** dans la fenêtre S-G2 ∥ S-G5 ∥ S-G8 (les autres rebasent dessus, par numéro croissant) — pas encore mergée à la fin de cette session (review humaine = le gate, jamais de merge automatique).

**Pièges découverts** :
- Ce worktree (`AgentB2C-sg2`) n'a pas son propre `.venv` — utiliser celui du worktree principal (`/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/python -m pytest`) **depuis le cwd de CE worktree** fonctionne correctement (`pytest.ini` a un `pythonpath` relatif, front-inséré → résout le code de ce worktree, pas celui du repo principal — même piège/même solution que documenté pour S-G1/S-G3).
- mypy ne narrow PAS `Any` → `float` juste avec `math.isfinite(x)` seul : il faut un `isinstance(x, (int, float))` explicite juste avant pour que la vérification de plage `-90.0 <= x <= 90.0` type-check sans `float(x)` sur un `Any | None`.
- Piège évité de justesse : préférer `locale` à `profile.language` pour `response_language` (lecture littérale du brief) aurait désynchronisé le champ annoncé de la langue RÉELLEMENT synthétisée (pilotée par `triage.language`, jamais touché ici) — `profile.language` garde la priorité, `locale` n'est qu'un meilleur fallback que l'anglais par défaut de `guess_language`.

## ⏱ Addendum 2026-07-23 (branche `sg1-profile-v2`, worktree dédié) — S-G1 : profil v2 (schéma complet + reducer ops typées, concierge)

**Contexte** : première session de la fenêtre S-G1 ∥ S-G3 ∥ S-G4 de la série de remédiation geo/multi-turn. Zone stricte `agents/b2c_concierge/**` + tests (`profile.py`, `facade.py::build_active_filters`) — `agents/hotel_search_agent/**` non touché (confirmé par `git diff --stat`).

**Fait** :
1. **`SessionProfile` étendu** (`profile.py`) — 12 nouveaux champs, tous optionnels/absent-tolérants : `named_hotel {hotel_id, name, source}`, `zone`, `metro`, `date` (ISO 8601), `date_reference {expression, resolved_from, client_tz}`, `currency`, `locale`, `domain`, `search_anchor {type, lat, lon, label, set_at_turn}`, `distance_origin`, `shown_hotel_ids` (liste accumulée, cap `MAX_SHOWN_HOTEL_IDS=25`), `search_cursor` (int). `to_dict`/`from_dict` symétriques + `to_dict()` stampe `schema_version: PROFILE_SCHEMA_VERSION="2.0"` (littéral, pas un champ dataclass — toléré/ignoré en retour, ISE A2A pattern).
2. **`apply_profile_delta` v2 = reducer à ops typées** (arbitrage A3-a) — `_normalize_delta` scinde tout delta entrant en `(values, clears)` : un slot shape `{"op": "set", "value": ...}` ou `{"op": "clear"}` est reconnu ; **tout le reste (le format plat actuel de la feuille) est traité comme un `set` implicite** — retro-compat byte-for-byte, aucune régression sur les guards P1/P6/anchors existants (leur logique interne lit désormais `values` au lieu de `delta`, sémantique inchangée). Un slot absent du delta n'apparaît dans ni `values` ni `clears` = carryover garanti par construction. Les clears explicites sont appliqués en dernier, génériquement, via `_slot_default()` (valeur zéro déclarée par le dataclass field lui-même — `None`/`[]`/`0` selon le champ).
3. **Règles d'invalidation** — changement de `city` (nouvelle valeur ≠ ancienne) : clear `zone`/`metro`/`search_anchor`/`state_anchor`/`country_anchor` (comportement anchors S04 conservé, étendu aux 3 nouveaux champs) + reset `shown_hotel_ids=[]`/`search_cursor=0`. Un changement de `zone` SEUL ne touche à rien d'autre (date/timeslot/budget/amenities/shown_ids/cursor tous conservés) — le cas exact de l'audit (3 variantes eval-pack `multiturn-zone_change_*`/`multiturn-carry_same_time_*` couvertes par test).
4. **`shown_hotel_ids`** — le point d'accumulation est `record_search_shortlist` (déjà appelé à chaque recherche dans `agent.py:714`, signature inchangée donc **zéro changement d'appelant nécessaire**) : `_accumulate_shown_hotel_ids` déplace un id déjà vu en fin de liste (dédup, le plus récent gagne), cap 25 (FIFO, les plus anciens tombent). `last_results` continue de se comporter EXACTEMENT comme avant (remplacement, jamais touché par un résultat vide) — les deux mécanismes cohabitent sans interférence.
5. **`search_cursor`** — pas de détecteur de signal "autres options" ici (hors périmètre, c'est S-G5) ; seule la primitive pure `advance_search_cursor(profile)` est livrée, testée isolément, prête à être appelée par la session qui câblera la pagination.
6. **`build_active_filters` (`facade.py`) dé-nullé** — `named_hotel`/`date_reference` ne sont plus des `None` littéraux mais lisent le profil ; ajout de `zone`/`currency`/`distance_origin`. **`CONTRACT_KEYS` (le contrat top-level `/v3/chat`) intouché** — vérifié par un test golden dédié (`test_active_filters.py::TestContractKeysUntouched`) qui fige le frozenset exact.
7. **Compteur RGPD-safe** (`dayuse_metric=profile_ops set=<n> clear=<n> slots=<noms>` — jamais de valeur, jamais de ville/budget/devise) — loggé une fois par appel `apply_profile_delta` non vide, testé (`caplog`) pour l'absence de toute valeur métier dans la ligne.

**DoD verte** : `pytest agents/b2c_concierge -q` → **278 passed** (+35 : 31 dans `test_profile.py` + 4 dans le nouveau `test_active_filters.py`) ; `pytest -q` (repo entier) → **571 passed** ; `ruff check .` OK ; `mypy agents libs` → 34 fichiers OK ; `bash scripts/dayuse_guardrails.sh .` OK. Aucun échec pré-existant observé dans ce worktree (`tests/test_llm_meter_usage.py` mentionné dans un addendum antérieur n'existe pas ici — untracked ailleurs, sans rapport).

**Reste (pour les sessions qui suivent, dans l'ordre du plan)** :
- **S-G5** doit câbler : (a) le vrai déclencheur "autres options" → appeler `advance_search_cursor` ; (b) `shown_hotel_ids` → argument d'exclusion réel vers `search_offers` (aujourd'hui l'accumulateur existe mais rien ne le lit encore côté recherche) ; (c) migrer la feuille pour émettre des ops typées (`{"op": "set"/"clear"}`) au lieu du format plat — **rien ne l'y oblige aujourd'hui**, la retro-compat tient tant que ce n'est pas fait.
- **S-G3** (geo resolver, feuille) et **S-G6** (dates/durées/minutes) sont les prochains à peupler réellement `zone`/`metro`/`search_anchor`/`distance_origin` et `date`/`date_reference` — aujourd'hui ces champs existent et se comportent correctement mais restent vides en trafic réel (aucune extraction ne les émet encore).
- **`named_hotel`** : champ + reducer prêts, mais rien ne l'émet encore (pas dans le périmètre S-G1 — extraction hors scope) ; le mécanisme de résolution shortlist existant (`resolve_hotel_reference*`) reste la seule source de vérité pour l'instant.
- Cette branche (`sg1-profile-v2`) doit **merger EN PREMIER** dans la fenêtre S-G1 ∥ S-G3 ∥ S-G4 (les autres rebasent dessus) — pas encore mergée à la fin de cette session, sur demande explicite de Fabien (review humaine = le gate).

**Pièges découverts** :
- Le worktree `AgentB2C-sg1` n'a pas son propre `.venv` — utiliser celui du worktree principal (`/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest` etc.) depuis le cwd du worktree sg1 fonctionne correctement (pytest insère `agents/b2c_concierge` du **cwd courant** dans `sys.path`, donc `import b2c_concierge` résout bien vers CE worktree, pas vers le repo principal — vérifié explicitement avant de faire confiance aux résultats).
## ⏱ Addendum 2026-07-23 (branche `sg3-geo-resolver`, worktree `../AgentB2C-sg3`) — S-G3 : résolveur géo multi-candidats, inventory-aware (feuille search)

**Contexte** : Wave-1 de la série S-G, en ∥ avec S-G1 (profile v2) et S-G4 (timeouts). Zone stricte `agents/hotel_search_agent/**` + `scripts/build_inventory_snapshot.py` + snapshot data. **Zéro ligne touchée dans `agents/b2c_concierge/**`** (vérifié). Remplace le géocodage `limit=1` accept/reject par un multi-candidats + ranker 100 % déterministe (zéro appel LLM).

**PROBE LIVE d'abord (Mapbox v6 `/forward` réel, token du repo, diagnostics structurels seuls)** — a tranché A2 et le design du parser :
- **`limit=10` renvoie bien 10 candidats** ; tous les `place/district/region` portent `bbox` + `coordinates` ; **certaines `locality`/`neighborhood` n'ont PAS de bbox** (→ le compteur d'inventaire est en RAYON autour du centroïde, pas en bbox — voir plus bas).
- **`full_address` échoue à contenir le nom pour les POI mais PAS pour les places** : `Köln` → `full_address="Köln, North Rhine-Westphalia, Germany"` (contient « Köln » → l'echo guard passe) ; le parser garde `name`, `full_address` (echo), `place_formatted` (label clarify), `context` (ISO pays/région), `bbox`, lat/lon.
- **`language` agit sur le scoring ET le texte** (probé : `Lisboa`+`pt` → « Lisboa » préféré ; `Milano`+`it`).
- **v6 suffit pour toutes les villes/districts de l'audit** (Milano, Lisboa, Köln, Chester, **Orange County** = `district`, Victoria) — les homonymes se règlent par inventaire + hint, PAS par Search Box (Search Box rend des **aéroports** pour « Orange County », pire).
- **v6 échoue sur les vrais POI/landmarks** (`La Défense`, `Tour Eiffel` → junk) ; **Search Box `/forward` les résout** (`poi`, bonnes coords). ⇒ **DÉCISION A2 = A2-b confirmé : Search Box adopté en TIER-2 de repli**, déclenché UNIQUEMENT sur un miss tier-1 AVEC une zone/landmark nommée (jamais sur une recherche ville — Search Box y est pire + SKU séparé).
- **Probe MCP live** : `search_offers` **renvoie `lat`/`lon` par hôtel** (⇒ cartes vérifiables) et supporte `from`/`size`/`radiusKm` + réponse `has_more`/`next_offset`/`total` (**= la pagination S-G5, HORS périmètre — noté, non touché**) ; les offres portent `startMinute`/`endMinute` (A4/S-G6, HORS périmètre).

**Fait (feuille uniquement)** :
1. **`mapbox_client.py`** — `geocode()` (limit=1) **inchangé** (tests existants verts) ; NOUVEAU `geocode_candidates()` (défaut `limit=10`, `autocomplete=false`, `types=place,locality,neighborhood,district,region`, `language`/`proximity`/`country` optionnels) → `list[GeocodeCandidate]` (feature_type, place_formatted, ISO pays/région, bbox, rank). Cache partagé (clés 4-tuple vs 6-tuple, jamais de collision).
2. **`inventory.py` (neuf)** — `InventoryProvider` (Protocol **injectable** : A1-a statique aujourd'hui, A1-c MCP plus tard, même signature) + `SnapshotInventory` : compte les hôtels dans un **rayon** (défaut 25 km, haversine + pré-filtre bbox) autour du centroïde — le rayon (pas la bbox du candidat) mime `search_offers(lat,lon,radiusKm)` et évite qu'une bbox de région/état gonfle un candidat grossier.
3. **`scripts/build_inventory_snapshot.py` (neuf)** + **`data/inventory_snapshot.json` (neuf, committé, 172 Ko)** — compile `{coord}` de **8 701 hôtels / 29 marchés** depuis les exports `structured_hotels_*.json` (MÊME source que la fixture eval, PAS `baseline/`). Coordonnée SEULE (aucun attribut hôtel). Déterministe (points triés, arrondis 5 déc., date d'export = mtime des sources, jamais d'horloge). Refresh manuel : `python scripts/build_inventory_snapshot.py --source-dir ~/Projects/agent-usa/data`.
4. **`geo_resolver.py` (neuf, 100 % déterministe, ZÉRO LLM)** — re-rank : (1) hint pays/région = **filtre dur** (jamais un boost ; si le filtre vide tout → `none`, jamais un mauvais pays) ; (2) densité inventaire = **quasi-dur** (0-inventaire démoté SOUS tout candidat avec inventaire — tue Lisbon-AR + homonymes Victoria), magnitude = poids soft borné ; (3) prior locale = boost borné ; (4) proximité GPS = boost **borné + band-limité** (règle Pelias) ; (5) prior feature-type (`place` > `locality`/`neighborhood` > `district` > `region`) + position Mapbox. **Poids en constantes nommées** (`_TYPE_PRIOR`, `_W_RANK=0.3`, `_W_LOCALE=1.0`, `_W_INVENTORY=2.0` cap 30, `_W_PROXIMITY=0.5`, `_MARGIN_SELECT=1.5`, `_MIN_CLARIFY_SEPARATION_KM=100`). **Policy** : marge décisive → sélection silencieuse ; sinon clarify-once (question **template** depuis `place_formatted`, 2-3 options, différenciées pays/région) UNIQUEMENT si les alternatives sont **loin** (≥100 km — sinon = même zone de recherche, ex. NYC vs West New York, on sélectionne). Jamais de boucle (le guard anti-clarification-loop du concierge fait le reste).
5. **`geocode_tool.py`** — intègre : demote/ZIP-anchor/state-hint/query **inchangés** → `geocode_candidates` → `geo_resolver.resolve` → **`geocode_echo_matches` conservé en sanity-check final sur le candidat CHOISI** → tier-2 Search Box si echo/tier-1 rate ET zone présente → clarify passthrough (`error="geocode_ambiguous"`, question+options en diagnostics ; le modèle relaie, la synthèse concierge la voix, aucune modif concierge requise — vérifié par lecture de `agent.py`). Nouveau param optionnel `locale` (mappé `language` Mapbox + prior pays ; GPS/proximity du profil = S-G5). Le POI tier-2 est requêté sur le **landmark seul** (`La Défense`, pas `La Défense, Paris` qui ramenait un hôtel « Citadines La Défense »).
6. **`response_bridge.py` (A8-a, instrumentation seule — PAS de reranker)** — cartes portent `latitude`/`longitude` (du `lat`/`lon` MCP) + `distance_km` (haversine depuis l'ancre géocodée, stashée par le branch geocode) ; payload émet `distance_origin` (lat/lon/label/type) quand il y a des résultats. Additif : le concierge ignore les clés inconnues (vérifié).
7. **`agent.py`** — instruction : passer `profile_in.language` comme `locale` ; sur `error="geocode_ambiguous"`, poser la question de clarification, ne pas chercher.

**DoD verte** : `pytest -q` (repo) → **591 passed** (baseline 536, **+55** ; leaf **232**, +55). `test_geo_guards.py` **28 inchangés verts** (guards re-verts). `ruff` OK ; `mypy agents libs` → **37 fichiers** OK (34 + inventory/geo_resolver/searchbox_client) ; guardrails OK. **Chaque cas d'échec de l'audit = un test nommé** (`test_geo_resolver.py` : Milano, Lisboa-pt, Lisbon-AR-démoté, Victoria-BC-par-hint, GPS-ne-surclasse-pas-NYC, NYC-vs-West-New-York, clarify homonyme, filtres durs…).

**Vérifié LIVE (Mapbox v6 + Search Box réels + snapshot inventaire, via le VRAI `geocode_location` bout-en-bout ; diagnostics structurels seuls)** — 8 cas de l'audit, **zéro résolution mauvais-pays** :
- **Résolus** : `Milano`(it)→`Milano, Italia` (place, IT) · `Lisboa`(pt)→`Lisboa, Portugal` (place, PT) · `Köln`(de)→`Köln, Deutschland` (place, DE) · `La Défense` (zone)→**tier-2 POI** `La Défense, 92800 Puteaux, France` (poi, FR) · `New York`→`New York, US` (plus de sur-clarify grâce au gate 100 km).
- **Clarify-once (homonymes lointains, honnête, jamais un mauvais pays)** : `Chester`→GB vs PA · `Victoria`→London-Victoria vs Singapore · `Orange County`→FL/CA/NY.

**Reste / à trancher (tous notés, HORS périmètre S-G3)** :
- **Chester/Victoria clarifient** au lieu d'auto-résoudre le plus prominent : comportement honnête (0 mauvais-pays) et **conforme à la policy arbitrée**. Les constantes (`_MARGIN_SELECT`, `_MIN_CLARIFY_SEPARATION_KM`, poids) sont **à tuner sur les 41 cas geo en S-G9** — c'est là que se règle le curseur select/clarify. Chester = aussi un bug de LATENCE (S-G4), pas de résolution.
- **Surfaçage VERBATIM de la question clarify** : la décision (ambigu→demander) est 100 % code ; le TEXTE template est voix par la synthèse concierge (pas byte-verbatim) → si on veut le verbatim + boutons, c'est un consommateur concierge de `geocode_ambiguous` (Wave-2, hors S-G3).
- **`distance_origin`/`distance_km`/`lat`/`lon`** exposés sur les cartes mais **pas encore consommés** côté concierge/widget (A8 = instrument d'abord ; le reranker + l'eval de ranking = S-G9/A8).
- **Proximity GPS** : le client + le resolver l'ACCEPTENT et sont testés, mais `geocode_tool` ne source PAS encore le GPS du profil (câblage = **S-G5**).
- **Venv du worktree** : ce worktree n'a PAS de venv propre. Pendant S-G3 j'ai réutilisé celui du checkout principal (`pythonpath` du `pytest.ini` est relatif + front-inséré → les imports résolvent bien le code du worktree, vérifié) ; symlink retiré en fin de session. Lancer le `uv venv` documenté (CLAUDE.md) avant de retravailler ici.
- **Merge** : cette branche merge **APRÈS `sg1-profile-v2`** → rebase sur `main` fraîche avant la MR. Jamais de merge soi-même (gate review Fabien).

## ⏱ Addendum 2026-07-23 (branche `sg4-timeout-budgets`) — S-G4 : budgets timeout par famille + LiteLLM RetryPolicy + instrumentation par phase + root-cause Chester RÉSOLU

**Contexte** : suite de `reports/research/timeouts-latency-memo.md` + `reports/research/code-verification-memo.md` (claim 6). Zone : `agents/b2c_concierge/**` (consts timeout, config LiteLLM) + `agents/hotel_search_agent/**` (instrumentation par phase) + tests. `∥` avec S-G1 (`sg1-profile-v2`) et S-G3 (`sg3-geo-resolver`) — cette branche merge EN DERNIER (rebase après les deux autres).

**1. Constat local LiteLLM (`num_retries` × `timeout`) — les 2 flags du memo levés par des probes empiriques, pas par lecture de source seule (la lecture de source m'a d'ailleurs trompé deux fois, corrigé par les probes) :**
- `litellm.acompletion(timeout=T, num_retries=N)` (SDK direct, sans Router) : chaque tentative reçoit son PROPRE `T` complet — PAS un budget partagé sur l'ensemble des tentatives (contredit la doc Router "`timeout` is for the entire length of the call", vérifiée seulement pour Router, jamais pour le SDK direct). Mesuré : `num_retries=2` contre un endpoint qui ne répond jamais → ~5x le temps d'une tentative seule (et non ~1x).
- `num_retries=N` (SDK direct) retry **à l'identique quel que soit le type d'exception** — un stub `400`/`401` (permanent) est retry autant de fois qu'un `429` (transitoire). Contredit ma première lecture de source (qui suggérait à tort que l'`AsyncOpenAI(max_retries=…)` sous-jacent filtrerait déjà par type). **`litellm.Router` + `RetryPolicy`** est la seule construction qui retry PAR TYPE D'EXCEPTION — vérifié en direct (400/401 → 1 requête, 429 → 1+N requêtes) — et vérifié aussi que `monkeypatch.setattr(litellm, "acompletion", fake)` intercepte toujours les appels faits via `Router.acompletion` (le Router appelle `litellm.acompletion` par attribut, pas par binding figé) → aucune casse des mocks existants (`test_spine.py`/`test_spine_profile.py`/`test_tool_loop.py`/`test_triage.py`).
- **Sans `num_retries` du tout** (cas réel de `triage.py`, jamais changé) : **0 retry** — confirme empiriquement que le docstring de `triage.py` ("NO retry") était déjà vrai en pratique, contrairement à une intuition initiale (mauvaise lecture de `DEFAULT_MAX_RETRIES=2` dans `litellm/main.py` qui ne s'applique pas à ce chemin).

**2. Budgets par famille (`agents/b2c_concierge/b2c_concierge/agent.py`)** — `_LEAF_TIMEOUT` unique remplacé par `_leaf_timeout(leaf)` (lu à l'appel, pas figé à l'import — même pattern que `hotel_search_agent.agent.build_connection_params`, choisi APRÈS avoir découvert qu'une constante figée + test par `importlib.reload` polluait `tests/api/test_facade_http.py` via le singleton `root_agent` partagé importé par `serve.py`) :
- `CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS` (déf. **15 s**), `CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS` (déf. **25 s**) ; `CONCIERGE_LEAF_TIMEOUT_SECONDS` (legacy, singulier) reste prioritaire pour LES DEUX familles si posée — le `30` du démo Railway continue de marcher sans y toucher.
- Méthode/chiffres sources documentés en commentaire dans `agent.py` : ancrés sur les 2 points mesurés en direct dans l'addendum Railway 2026-07-22 (FAQ ~9 s à chaud, 1er search à froid >10 s) avec marge ~1.5x/~2.5x — PAS un fit de percentile complet (aucune métrique p95-par-famille live n'existait avant cette session ; c'est justement l'instrumentation du point 4 qui le permet maintenant, à resserrer plus tard sur constat réel).
- `_get_leg`/`_run_leaf` utilisent `_leaf_timeout(route.target)` (search vs faq résolus via `LEAF_HOTEL_SEARCH`/`LEAF_FAQ`). **0 retry orchestrateur→feuille inchangé** (invariant).
- Tests : `test_leaf_timeout_budgets.py` (7 tests, précédence env var complète, `monkeypatch.setenv` pur — aucun reload).

**3. RetryPolicy synthèse (`agent.py`)** — `litellm.Router` construit paresseusement et **caché par model_slug** (mirroir du cache `_get_leg`, fonction `_get_synthesis_router`/`_reset_synthesis_routers`) :
- `RetryPolicy(TimeoutErrorRetries=_SYNTHESIS_NUM_RETRIES, RateLimitErrorRetries=_SYNTHESIS_NUM_RETRIES, BadRequestErrorRetries=0, AuthenticationErrorRetries=0, ContentPolicyViolationErrorRetries=0)`, `num_retries=0` au niveau Router (la policy est la SEULE source de retry, jamais de double-retry empilé).
- `_generate_once` appelle `_get_synthesis_router(model_slug).acompletion(model=_SYNTHESIS_MODEL_GROUP, …)` au lieu de `litellm.acompletion(…, num_retries=…)` direct — corrige un vrai bug de gaspillage (un échec permanent consommait quand même tout le budget de retry avant de tomber sur le fallback "leaf text verbatim").
- **`triage.py` volontairement INCHANGÉ** (pas de RetryPolicy ajoutée) — décision documentée dans son docstring : son fallback (regex) est instantané et aussi fiable qu'un retry réussi ; ajouter un retry n'y gagnerait rien et ajouterait juste de la latence avant d'atterrir exactement au même endroit.
- **`stream_timeout` délibérément NON posé** — la synthèse ne stream jamais depuis litellm (génération bufferisée pour le guard anti-boucle-de-clarification, cf. docstring `_chunk_text`) : `stream_timeout` n'a aucun effet sur un appel non-streamé, le poser serait un no-op qui laisserait croire à une protection inexistante. Le SLO TTFT <300 ms est protégé structurellement par le marker `progress` émis AVANT tout travail LLM (étape 0 du docstring du module), pas par un knob LiteLLM.
- Tests : `test_synthesis_retry_policy.py` (8 tests — config du Router, cache par slug, `_generate_once` route bien via le Router).

**4. Instrumentation par phase (feuille, `agents/hotel_search_agent/hotel_search_agent/response_bridge.py`)** — 3 des 4 compteurs demandés EXISTAIENT DÉJÀ (dayuse_agent_common S3 : `tool_timing_before/after` → `dayuse_metric=tool_call tool=geocode_location|search_offers ms=…` ; `llm_timing_before/after` → `dayuse_metric=llm_call … ms=…`) ; seul le **total** manquait. Ajouté : `stamp_turn_start` (`before_agent_callback`, nouveau, stampe `temp:hotel_search_turn_t0`) + `emit_search_datapart` logge désormais `dayuse_metric=leaf_turn_total agent=b2c_hotel_search ms=…` **EN PREMIER, inconditionnellement** (avant tout early-return — couvre aussi le chemin geocode-fail/clarification, pas seulement une recherche réussie). RGPD : flag/durée seule, jamais de contenu (testé). Tests : 5 nouveaux dans `test_response_bridge.py` + 1 dans `test_agent.py` (wiring `before_agent_callback`/`after_agent_callback`).

**5. Root-cause Chester GB — RÉSOLU, verdict = pas un bug de correctness, confirmé par preuve live avec l'instrumentation ci-dessus :**
- 3 services locaux relancés (`.env` réel : Mapbox + MCP staging), Chester rejoué **8 fois en `gpt-4o-mini`** (défaut) : requête exacte de l'eval pack (`dayuse_eval_pack/eval_pack/cases/geo.jsonl#geo-chester-gb-homonym` — "Hotels in Chester England, budget 100 gbp") + une variante — **toujours 200, toujours GB (jamais d'homonyme US), leaf_call 2.1-4.5 s**, chaque phase saine (geocode 0-55 ms, search_offers 380-580 ms, 2 appels LLM 800-2000 ms chacun). Zéro reproduction en `gpt-4o-mini`.
- **Cause trouvée en changeant UNE variable** : `DAYUSE_MODEL=gpt-5.2` (le modèle que l'audit du 2026-07-22 faisait tourner — noté HANDOFF S-A "l'eval de l'audit tournait GPT-5.2", jamais vérifié jusqu'ici) → même requête Chester rejouée **8 fois** : `leaf_call` **3.1-8.2 s** (vs 2-4.5 s en gpt-4o-mini, ~2x), `concierge` turn total **6.4-14.0 s** — **directement au ras de l'ancien seuil fixe unique 10 s**, avec la variance naturelle de latence LLM suffisant à faire basculer certains tours au-dessus. Chaque phase reste saine (tool calls 0-443 ms) : **la totalité de l'écart vient des 2 appels LLM de raisonnement de la feuille**, plus lents avec GPT-5.2 (jusqu'à 5.8 s un seul appel), pas d'une boucle/retry/mismatch caché.
- **Verdict** : Chester = **cas de queue saine sous-provisionnée** (exactement le failure mode "false-timeout-rate" du memo §a.2), PAS le cas "bimodal latency" que le memo envisageait par défaut en absence de mesure — l'instrumentation de cette session permet justement de trancher entre les deux, et la mesure tranche pour la queue saine. Le nouveau budget search **15 s** (posé au point 2, AVANT ce probe) couvre déjà le pire cas observé en GPT-5.2 (8.2 s, ~45 % de marge) — **aucun code additionnel à écrire**, le fix du point 2 résout Chester par construction.
- Rien à documenter côté MCP_B2C (pas un item cross-repo) — la cause est entièrement expliquée par modèle+budget, confirmée avec le repo tel qu'il est.
- Services remis en `gpt-4o-mini` (défaut) puis arrêtés en fin de session.

**DoD verte** : `pytest -q` → **557 passed** (+21 neufs : 7 budgets timeout, 8 retry policy, 6 instrumentation) ; `ruff` OK ; `mypy agents libs` → **34 fichiers** OK ; `dayuse_guardrails.sh` OK. **Vérifié LIVE** (3 services, `.env` réel) : un tour search (`hotel a paris demain avec piscine`) → leaf_call **5.0 s** (budget 15 s) ; un tour FAQ (`puis-je payer sur place ?`) → leaf_call **9.7 s** (budget 25 s, cohérent avec le point d'ancrage "~9 s à chaud" du memo) ; les 2 sous budget avec marge confortable, 4 compteurs par phase visibles dans les logs des 2 tours.

**Reste / pièges découverts :**
- Budgets 15 s/25 s sont des points de départ ancrés sur 2 mesures Railway + validés ex-post par 8 runs GPT-5.2 — PAS un fit de percentile complet ; à resserrer une fois un vrai p95-par-famille accumulé via l'instrumentation posée ici.
- Deadline propagation bout-en-bout (A5-b) reste hors scope, comme prévu par la phase — pas commencée.
- Le contrôle plateforme de `DAYUSE_MODEL` (défaut committé = `gpt-4o-mini`) avant toute comparaison canary, déjà noté en S-G0, est renforcé par cette session : GPT-5.2 double la latence LLM de la feuille — tout run comparatif doit fixer explicitement le modèle des deux côtés.
- `_reset_synthesis_routers()`/`_reset_legs()` : hooks de test uniquement, jamais appelés en prod — si une session future ajoute un test qui change `DAYUSE_MODEL` en cours de process, il faudra les appeler explicitement (aucun test actuel n'en a besoin, le cache est par model_slug donc déjà correct par défaut).

## ⏱ Addendum 2026-07-23 (docs only, aucun code) — plan de remédiation geo/multi-turn ARBITRÉ + série S-G prête à lancer

**Contexte** : Fabien a déposé `REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md` (audit 249 cas vs agent-usa : geo 26/41 vs 36/41, multi-turn 12/27 vs 16/27) et demandé : étude + recherche web + rapport d'options + arbitrage + plan de dev.

**Fait (cette session, zéro changement de code)** :
1. **Vérification code des 10 claims de l'audit → 10/10 VRAIS** sur `main@453c77f`, preuves file:line dans `reports/research/code-verification-memo.md` (+ inventaire complet des guards existants et du flux profile_in/delta). Deux constats au-delà de l'audit : le géocodeur n'envoie JAMAIS `proximity` ni ne varie `language` ; le handling `zone` est à moitié construit (accepté par geocode_tool, validé par l'echo guard, jamais persisté au profil).
2. **3 mémos de recherche web** (sources citées, non-vérifiés flaggés) : `reports/research/geo-disambiguation-memo.md` (Mapbox v6 : limit défaut=5/max 10, AUCUN score de pertinence renvoyé pour les places → le ranking doit être à nous ; Airbnb/Expedia rankent contre leur PROPRE inventaire ; règle Pelias : la proximité ne surclasse jamais une destination explicite) · `multiturn-state-memo.md` (SOM-DST/Diable : ops par slot, carryover par défaut ; RFC 7386 ; confirmation mainteneur ADK : les sessions ne sont PAS partagées en A2A, le DataPart est le bon pattern) · `timeouts-latency-memo.md` (percentile sain + false-timeout-rate ; params LiteLLM vérifiés : RetryPolicy par exception, stream_timeout ; hedging analysé et rejeté).
3. **Plan d'options arbitrable** : `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` (+ artifact HTML publié dans la conversation). Diagnostic : UNE famille de cause racine — le contrat/l'état ne portent pas le contexte, et le pont profil→outils repose sur la recopie LLM. Zéro nouvel appel LLM dans tout le plan.
4. **ARBITRAGE (Fabien, 2026-07-23) : toutes les recommandations acceptées** — A1-a snapshot inventaire statique · A2-b Search Box tranché par probe · A3-a ops typées · A4-c · A5-a budgets par famille · A6-a contexte maintenant/pricing gated · A7 probe d'abord · A8-a instrumenter avant reranker. **⚠️ A4 : Fabien pensait les demi-heures déjà corrigées — vérifié NON corrigé sur main** (`hotel_search_agent/agent.py:144` impose des heures entières au modèle ; `response_bridge.py:202-203` force minute=0 à la capture ; seul l'AFFICHAGE des offres lit `startMinute`/`endMinute` — c'est probablement la source de la confusion, avec le « HH:MM » du profil livré en S14). `core-e2e-084` reste ouvert, A4-c reste au plan.
5. **Plan de dev prêt à passer à d'autres sessions** : `phases/SG1-…SG9-*.md` (9 fichiers autonomes : périmètre IN/OUT, étapes, DoD exécutable, prompt de lancement inclus) + vue d'ensemble/timeline/modèles dans `SESSIONS-CLAUDE-CODE.md` §S-G + checklist `tasks/todo.md`. Fenêtres : (S-G1 ∥ S-G3 ∥ S-G4) → (S-G2 ∥ S-G5 ∥ S-G8) → S-G6 → S-G7 → S-G9. S-G3 = Opus ; S-G9 = jamais loop.

**Reste** :
- Lancer la série S-G (chaque phase porte son prompt de lancement). Merge order des fenêtres parallèles : numéro le plus bas d'abord.
- Cross-repo MCP_B2C : demandes à ouvrir (minutes timeSlot, offset/exclusion pagination, pricing/devise, éventuel count_hotels_near) — matérialisées dans `reports/MCP-B2C-REQUESTS.md` en S-G6/S-G7.
- Ops : contrôle plateforme de `DAYUSE_MODEL` (défaut committé = `gpt-4o-mini`, l'eval de l'audit tournait GPT-5.2) avant toute comparaison canary.

**Pièges découverts** :
- Mapbox v6 ne renvoie AUCUN champ de pertinence numérique pour les features de type place (`match_code`/`confidence` = adresses seulement) — ne pas espérer un seuil de confiance API, le ranker est forcément à nous (position + nos signaux).
- Les claims « La Défense = neighborhood v6 » / « Orange County = district » sont inférés des docs, PAS testés live — d'où le probe obligatoire en tête de S-G3.
- LiteLLM : router `timeout` couvre l'appel entier retries compris (docs), mais l'interaction exacte `num_retries` × `timeout` est à vérifier par un test local de 10 lignes (fait en S-G4).
- Les tests de ce repo (`pytest -q`) : 1 échec pré-existant `tests/test_llm_meter_usage.py` (untracked S-B, sans rapport avec cette session).

## ⏱ Addendum 2026-07-23 (branche `s-railway-deploy-demo`) — fix sélection d'hôtel par numéro (booking) découvert sur le démo

**Bug (signalé par Fabien, capture d'écran)** : sur le démo, après une recherche Miami, « je veux booker » → « Quel hôtel ? Dites-moi son nom : 1. … 2. … » ; répondre **« 1 »/« 2 »** → « I can't reach the hotel search in Miami » (dégradation). Impossible de choisir un hôtel de la liste.

**Root cause (3 constats, tous logique applicative PRÉEXISTANTE — pas le déploiement, reproductible en local)** :
1. **Un numéro nu n'était jamais mappé à la position dans la shortlist.** « 1 » partait au name-matching → `resolve_hotel_reference_strict("1")` = rien, puis fuzzy → mauvais hôtel (a tenté « Regency » = #3).
2. **Le numéro nu était triagé `family=search`** (pas booking) → feuille → dégradation + épuisement du budget de recherche, ce qui pouvait aussi écraser la shortlist.
3. **`find_hotel_by_name(cityName=profile.city)` est un PIÈGE** (prouvé par probe MCP direct) : `cityName="Miami"` → « No hotel found » même pour un nom exact (« Cadillac… »), car les hôtels sont indexés sous Miami Beach/Doral/Aventura, pas « Miami ». Donc « passer cityName » (le fix naïf envisagé) est contre-productif — **non retenu**.

**Fix retenu (élégant, subsume tout le cluster ; zone concierge uniquement)** : résolution **shortlist-first par position**. La shortlist porte déjà le `hotelId` → aucun aller-retour MCP, aucun filtre ville.
- `profile.py::resolve_shortlist_ordinal(text, last_results)` (neuf) : « 1 », « #2 », « n°3 », « option 1 », mots ordinaux fr/en (`premier`/`first`/`deuxième`…). **Volontairement STRICT** : rejette « le 2 »/« le 28 » (raffinement de DATE fr), hors-plage, « 1 star hotel ».
- `inline_tools.py::_resolve_hotel_id` : ordinal testé EN PREMIER (avant strict/MCP/weak).
- `agent.py` override de routage : un ordinal nu avec shortlist présente → `family=booking` (plus jamais search).

**DoD verte** : `pytest -q` → **538 passed** (+13 neufs : `TestResolveShortlistOrdinal` ×7 dans test_profile, `TestOrdinalSelection` ×3 dans test_inline_tools + ajustements) ; ruff/mypy(34)/guardrails OK. (1 échec restant = `tests/test_llm_meter_usage.py`, untracked S-B, sans rapport.)

**Vérifié LIVE (URL publique du démo)** : Miami → « je veux booker » → **« 1 » → offre Cadillac Hotel & Beach Club €119.33 quotée** (R9, demande confirmation) → **« oui » → lien réel `https://www.dayuse.com/tunnel/booking?offerId=…`**. Le cluster de la capture est résolu.

**Résidus honnêtes (pré-existants, NON régressions, hors périmètre de ce fix)** :
- **« oui je confirme » (affirmatif NON nu) → template ack**, pas confirmation : `is_booking_confirmation_signal` n'accepte qu'un affirmatif NU (« oui »/« ok »). Un « oui » nu confirme bien. Gap de formulation R9, à traiter séparément si besoin.
- **Certains hôtels (ex. Wyndham #2) n'ont pas d'offre réservable** sur staging → `get_hotel_details` sans `offers` → « no bookable offer » (dégradation honnête). Manque de données staging, pas un bug de routage.
- La qualité de `find_hotel_by_name` (hôtel HORS shortlist, nommé) reste limitée par le filtre ville exact du MCP — item MCP-B2C, hors périmètre.

## ⏱ Addendum 2026-07-22 (branche `s-railway-deploy-demo`) — déploiement Railway du démo hébergé (widget + 3 services + Redis)

**Contexte** : Fabien a demandé de déployer AgentB2C sur Railway **avec le front webapp comme sur `localhost:8090`**. Décisions (Fabien) : **démo hébergée sur MCP staging** (pas la parité prod, qui reste bloquée S-C), **vendoriser le widget + proxy en 4e service**, **nouveau projet Railway `AgentB2C`**. Trafic synthétique/démo uniquement, aucun utilisateur réel.

**Le front `:8090` n'était PAS dans ce repo** : `scripts/run_widget_proxy.py` sert le widget d'`agent-usa` (`templates/chat_clean.html` + `static/js|css/chat/**`) qui vit dans le repo voisin. Il a fallu le vendoriser.

**Fait (code, branche `s-railway-deploy-demo`)** :
1. **`web/vendor/`** — manifeste widget complet vendorisé (39 fichiers, 1,2 Mo ; les 2 hero JPG + la police MaisonNeue dominent). Exhaustif vérifié : chaque `@import`/`src`/`href`/import JS résout en local (le graphe `js/chat` est 100 % relatif → dossier autonome). Seule dépendance externe = Google Fonts CDN (client-side, dégrade en police système).
2. **`scripts/run_widget_proxy.py`** (était untracked S9, committé ici) — honore `PORT`/`HOST`/`WIDGET_BACKEND` ; **bind IPv6 dual-stack** (`_WidgetProxyServer` : `http.server` bind AF_INET par défaut, **incapable de binder `::`** contrairement à uvicorn — bug réel trouvé au run conteneur) ; défaut `--agent-usa-dir` = dossier vendorisé (plus besoin du repo voisin).
3. **`web/Dockerfile`** (neuf, stdlib only, aucun token) + **3 Dockerfiles backend patchés** : ajout `apt-get install git` (**la vraie raison pour laquelle ils n'avaient jamais buildé** — `python:3.12-slim` n'a pas git, donc pip ne pouvait pas résoudre le git+ dep privé) + résolution du token fleet via **build ARG** `FLEET_READ_TOKEN` (rewrite `insteadOf` de la CI), token scrubé (`rm /root/.gitconfig`) dans la MÊME couche. **⚠️ Piège Railway** : le builder Metal **rejette** `--mount=type=secret` + la directive `# syntax=docker/dockerfile:1` (build échoue au « scheduling », zéro log Docker) — build ARG simple obligatoire (Railway passe les variables de service en build args).
4. **`.railwayignore`** (neuf) — `railway up` honore `.gitignore` par défaut MAIS pas garanti ; **`baseline/` (messages users bruts, RGPD) + `.env` + `.venv` explicitement exclus de l'upload de contexte**.

**Topologie Railway (projet `AgentB2C` = `a200e208-863d-4771-8b4d-03b5a6280904`, env `production`, workspace Inno Labs)** :
| Service | Source | Public | Rôle |
|---|---|---|---|
| `Redis` | managé | privé | session store concierge (`CONCIERGE_REDIS_URL=${{Redis.REDIS_URL}}` → `redis.railway.internal`) |
| `hotel-search` | `agents/hotel_search_agent/Dockerfile` | privé | feuille A2A (:8101) |
| `faq` | `agents/faq_agent/Dockerfile` | privé | feuille A2A (:8102) |
| `concierge` | `agents/b2c_concierge/Dockerfile` | privé | orchestrateur + façade `/v3` (:8100) |
| `widget` | `web/Dockerfile` | **PUBLIC** | proxy widget → `/v3/*` vers concierge (privé) |

**URL publique démo** : **https://widget-production-3f56.up.railway.app** (le navigateur ne parle qu'à cette origine ; le proxy forwarde `/v3/*` en privé). Concierge/feuilles jamais exposés. Câblage : cartes A2A `http://<svc>.railway.internal:<port>/.well-known/agent-card.json`, 3 bearers A2A générés (scratchpad session), MCP staging = `https://mcp-server-production-bcbe.up.railway.app/mcp` (public, joignable), `DAYUSE_MODEL=gpt-4o-mini` (miroir local ; `.env` `OPENAI_MODEL=gpt-5.2` = dead config non lu). Pas de `DATABASE_URL` (logs conversation off pour la démo), `CHAT_API_KEY` vide (façade ouverte, mais concierge privé).

**Vérifié LIVE (via l'URL publique)** :
- Page widget 200 + tous les assets 200 + `du-chat-endpoint=/v3/chat`.
- Les 5 services `Application startup complete`, bind `[::]`, zéro crash.
- **SEARCH** « hotel à Marseille avec piscine » → **5 hôtels réels** (staging ES), `active_filters.amenities=['pool']` (filtre amenity actif). Paris → Villa Paris Orly €54 etc. (mêmes données que les runs locaux).
- **FAQ** « payer sur place ? » → vraie réponse synthétisée (MCP `get_faq_conditions` : erreur-puis-retry-OK côté feuille, doc volumineuse).
- **ACK** « bonjour » → template zéro-LLM.
- Feuille prouvée joignable en privé (`GET agent-card 200` depuis IPv6 `fd12:…`), `geocode_location ok 32ms`, `search_offers ok 951ms`.

**⚠️ Déviation d'invariant assumée pour la démo** : `CONCIERGE_LEAF_TIMEOUT_SECONDS` monté **10 → 30 s** (variable Railway, zéro code). Le budget 10 s « feuille SANS retry » (invariant CLAUDE.md) est trop serré sur Railway : le **premier** appel search cold-start dépasse 10 s (le travail outil est rapide — geocode 32 ms, search 951 ms — c'est la latence LLM gpt-4o-mini à froid) et la **synthèse FAQ** (doc ~6 K tokens, ~9 s) dépasse 10 s même à chaud → dégradation honnête « je n'arrive pas à joindre… ». À 30 s tout passe. **À rediscuter** : soit assumer 30 s en démo, soit garder 10 s prod et accepter que le 1er appel dégrade (miroir de la latence documentée p95 ≈ 11,6 s/cas).

**Reste / pièges** :
- **Cold start** : le tout premier appel après un (re)déploiement/idle peut dégrader (LLM à froid). Railway ne met pas en sommeil (min 1 instance), donc une fois chaud ça reste chaud. Un warm-up post-deploy lisserait la 1re impression.
- **Rendu navigateur non vu par moi** : API + page + assets vérifiés au curl ; le rendu visuel des cartes (card.js) reste à confirmer par Fabien en ouvrant l'URL.
- Bruit ADK expérimental « original event loop is closed » au cleanup de session feuille après un timeout concierge — quirk A2A expérimental, inoffensif.
- Secrets de build/tokens A2A dans le scratchpad de session (éphémère). `FLEET_READ_TOKEN` déposé par Fabien dans `.env` (gitignored) + posé en variable Railway des 3 backends.
- MCP staging = inventaire épars (cf. addendum eval) : certaines villes « 0 offre » — fidèle au local, pas un signal qualité.



**Contexte** : suite directe de S-A (PR #18, mergée). Fabien a demandé de faire tourner le pack complet (`eval_pack.runner`/`eval_pack.compare`, code déjà existant, aucun code neuf) contre agent-usa (démarré en local, `:5002`) ET AgentB2C (via l'adapter S-A, `:8110→:8100`), et de produire un comparatif clair. **2 kills accidentels en cours de route** (l'utilisateur faisait des modifs en parallèle) ont fait perdre la première tentative (~75 %/~68 % de progression) — relancé intégralement depuis zéro sur sa confirmation.

**Fait** : 249 cas × 2 stacks (`eval_pack/results/{agent_usa,candidate}.json`) + `eval_pack.compare` (`eval_pack/results/comparison.json`). Rapport complet + triage : `EVAL-PACK-COMPARISON-2026-07-22.md`. Dashboard : artifact publié dans la conversation.

**⚠️ Constat central (à ne jamais oublier en relisant les chiffres bruts)** : les deux runs sont dominés par un confond d'inventaire local, PAS un signal qualité propre :
- **agent-usa** : 202/249 échecs, dont **197 (98 %) à 0 hôtel retourné** — y compris sur ses propres métros US phares (New York, Miami, Chicago), pourtant dans son `MarketRegistry` documenté (80+ villes US). Ses propres réponses le disent explicitement ("no listings available in the wider Miami area either"). Pointe vers des données de disponibilité locales périmées/éparses (Postgres+Qdrant figés sur l'export du 2026-07-15), pas un défaut de raisonnement.
- **AgentB2C** : 139/249 échecs, dont **91 (65 %) aussi à 0 hôtel** — cohérent avec le gap déjà documenté (ES staging partiel, `AUDIT-REWORK-2026-07.md` §5).
- **Preuve concrète** : même requête "hotel in Queens Village NY" → AgentB2C 5 hôtels réels (staging ES) vs agent-usa 0 (alors que Queens Village est dans son propre périmètre documenté).

**Chiffres bruts** : pass rate AgentB2C 110/249 (44,2 %) vs agent-usa 47/249 (18,9 %) ; diff `improvement=80 / unchanged_fail=122 / unchanged_pass=30 / regression=17` ; latence p95/cas AgentB2C 11,6 s vs agent-usa 25,4 s (**-54 %**, cohérent avec le budget ≤3 appels LLM/tour).

**2 signaux propres (non confondus par l'inventaire)** :
1. **Suite `domain`** (langue/devise par ccTLD, 8 cas, aucune dépendance à la disponibilité hôtel) : agent-usa 8/8 vs AgentB2C 2/8 — gap de capacité réel et déjà documenté (spine fr/en + EUR uniquement, décision de périmètre S9), pas un bug.
2. **Latence** — cf. ci-dessus, cohérent avec le bench Judge A/B du même jour (`JUDGE-AB-BENCH-2026-07-22.md`).

**Les 17 régressions, triées une par une** (règle du pack : jamais conclure sans relire chaque régression) :
- 7 = gap langue/devise documenté (suite domain + `prod-wound-date-not-budget`).
- 6 = gap d'exposition `active_filters.zone/date_reference/named_hotel` déjà au registre S-A.
- **2 = VRAIS bugs neufs découverts par ce run** : `core-e2e-084` (créneau "7h30-13h30" tronqué en "07:00-13:00", le schéma `timeSlot` de `search_offers` n'a que des heures entières, la demi-heure est perdue silencieusement) ; `core-e2e-201` ("for 1 hour" = une DURÉE, extraite comme une fenêtre horaire absolue "00:00-01:00" — même famille de bug que l'incident prod historique "20 minutes → budget 20 €", sur un autre champ). **À corriger, indépendamment du confond d'inventaire.**
- 1 = dégradation FAQ MCP staging déjà connue (S-A).
- 1 = probablement transitoire (Le Meridien DC, dégradation honnête complète, à revérifier).

**Reste / recommandations** :
- Ne PAS lire les gaps core/geo/international/worldwide comme "AgentB2C meilleur en recherche" — 98 % des échecs agent-usa sont 0-hôtel, pas un signal de raisonnement.
- `core-e2e-201` (durée→horloge) mérite un vrai fix côté feuille search, indépendamment de tout confond.
- S-C (accès ES prod pour MCP_B2C) reste le préalable bloquant pour une vraie mesure de parité — ce run renforce plutôt la nécessité de S-C qu'il ne s'y substitue.

## ⏱ Addendum 2026-07-21 (branche `s15-eval-adapter`) — S-A : adapter eval-pack + smoke staging (audit comparatif agent-usa vs AgentB2C)

**Contexte** : Fabien a ajouté `dayuse_eval_pack/` (249 cas black-box en 7 suites, runner stdlib POST `/v3/chat`, comparateur régression/amélioration — extrait du repo agent-usa, PII-clean par construction). Objectif global : audit comparatif qualité/perf/scalabilité agent-usa (prod) vs ce rework — plan complet validé par Fabien (sessions S-A→S-F) : baseline agent-usa **local :5002**, candidat sur **prod ES read-only** (run-of-record), load test borné, + passe LLM-judge (evalset-v0) sur les 2 agents. **Le pack n'est JAMAIS modifié** (byte-identique entre runs) ; tout le code neuf vit dans `scripts/`.

**Fait (S-A)** :
1. **`scripts/run_eval_adapter.py`** — proxy stdlib `:8110 → :8100` (pattern `run_widget_proxy.py`). Requêtes pass-through + header `X-Dayuse-Synthetic: 1` (→ `is_synthetic=true` en conversation_logs). Réponses `/v3/chat` : 3 règles de mapping, **uniquement clé absente, jamais d'écrasement, jamais d'invention** : (a) `country_code` ← table statique nom-complet→ISO2 (29 marchés du fixture + variantes ; nom inconnu = laissé visible en échec) ; (b) `currency:"EUR"` ssi `price` matche le format façade `^€\d+(\.\d{2})?$` (fait de provenance `priceEuro`) ; (c) `display_price` float parsé de la même chaîne. Chaque ajout divulgué par carte sous `eval_debug.adapter_mapped` (archivé dans les rapports). Non-buts documentés en docstring : lat/lon/distance_km, booking_card, devises non-EUR.
2. **`tests/test_eval_adapter_mapping.py`** — 15 tests offline (fonctions pures, import via importlib du script) : no-overwrite, no-invention, disclosure, formats prix non-façade rejetés, entries non-dict, eval_debug préservé.
3. **Fixture inventaire régénérée** (`eval_pack/fixtures/`) depuis les exports frais `~/Projects/agent-usa/data/structured_hotels_*.json` du 2026-07-15 (l'ancienne provenait du 2026-06-24) : 8 701 hôtels / 29 marchés (inchangé — catalogue stable), manifest + SHA à jour. `dayuse_eval_pack/data/` (exports bruts) gitignoré ; le fichier `rate-plans-export-2026-07-20.json` déposé par Fabien est un export PRICING (ratePlanId/price/availability, zéro attribut hôtel) — inutilisable pour la fixture, gardé comme cross-check prix éventuel.
4. **Smoke run complet (staging ES = plumbing only, PAS un chiffre d'audit)** : 249/249 cas exécutés via l'adapter → `eval_pack/results/candidate_staging.json` (gitignoré, debug). **110/249 passed (44,2 %)**, latence par cas p50 6,2 s / p95 15,8 s (⚠ latence pack = SOMME des tours d'un cas). Adapter prouvé sous charge : 541 cartes `currency`/`display_price`, 23 `country_code` (le reste déjà stampé géocode côté leaf — cohérent), 100 % divulgué.
5. **Triage des 139 échecs** (script d'analyse en scratchpad, à re-porter en S-C comme `annotate_inventory_confound.py`) : **90 cas = 0 hôtel retourné** (pattern inventaire staging/géocode — à rejouer sur prod ES en S-C) ; **~20 cas = hôtels hors zone** (US : NYC/Atlanta/Seattle, `allowed_geo_terms` 0/5 — candidats investigation réelle S-C) ; **20 cas gap-only** (36 assertions sur les gaps documentés : langue de/es/it/pt/zh, devises non-EUR, distance, filtres zone/metro/named_hotel/date_reference — SOUS le budget ≈45 prédit par la table des gaps du plan) ; multiturn `message_contains_any` : mix environnement (FAQ MCP dégradé sur staging → « I can't look up the Dayuse conditions ») et wording `named_hotel_absent`/`date_availability` à revérifier sur prod.

**DoD verte** : `pytest -q` → **526 passed** (+15) ; `ruff` OK ; `mypy agents libs` → 34 fichiers OK ; guardrails OK. Vérifié live : round-trip adapter (session body honorée), run 249 cas complet.

**Reste (sessions suivantes — bloquants Fabien marqués)** :
- **S-B baseline** : boot agent-usa local :5002 (procédure + backend données prod-comparable → **Fabien**) + `scripts/run_llm_meter.py` (coût old agent). Préfixe sessions runner `canonical-eval-` : PAS dans la liste d'exclusion synthétique historique — le header `X-Dayuse-Synthetic` du candidat couvre le neuf ; côté agent-usa local, hors prod, non-problème.
- **S-C run-of-record** : creds MCP_B2C **prod ES read-only** + `DATABASE_URL` (coûts) → **Fabien** ; puis `candidate.json`, `comparison.json`, `annotate_inventory_confound.py`, `measure_ab_perceived_latency.py` (TTFT SSE vs TTFB bloquant), SQL coût/tour.
- **S-D judge A/B** (`run_judge_ab.py`, evalset-v0 × 2 agents) ; **S-E load probe** (1/5/10/20) ; **S-F rapport `AUDIT-COMPARATIF-AB-2026-07.md`**.
- `scripts/run_widget_proxy.py` (S9) traîne toujours en untracked — à committer dans une session dédiée ou avec l'accord de Fabien.

**Pièges découverts** :
- **Sandbox Bash de Claude Code : les écritures fs des commandes composées/background ne persistent PAS toujours dans le repo** (le nohup initial écrivait dans un overlay ; un `cd` relatif a même créé un `dayuse_eval_pack/dayuse_eval_pack/` fantôme, nettoyé). Parade fiable utilisée : sortir les artefacts long-running vers le **scratchpad session** puis `cp` simple vers le repo. Toujours vérifier `pwd` avant un lancement détaché ; chemins absolus partout.
- Le runner du pack somme les latences des tours d'un cas (`latency_ms` par cas) — toute comparaison de latence dans le rapport final doit le divulguer.
- `python3 -u` obligatoire pour un runner nohup (sinon stdout bufferisé, log illisible en cours de run).

## ⏱ Addendum 2026-07-21 (branche `s13-drift-geo-zip`) — S13 : scoping pays du géocodage ZIP US (feuille search)

**Contexte** : `AUDIT-DRIFT-AGENT-USA-2026-07-20.md` pointait un bug prod agent-usa (`b429125`, spec `test_us_market_five_digit_postcode_never_falls_through_worldwide`) : un ZIP US 5 chiffres (« near 11580 ») partait en géocodage MONDE ENTIER faute de scope pays. Zone stricte `agents/hotel_search_agent/**` — zéro changement concierge.

**Probe AVANT code (constat, comme demandé par la phase)** :
- `mapbox_client.py` supporte déjà un paramètre `country` optionnel sur `.geocode()`, forwardé en `country=<lower>` au paramètre Mapbox v6 — déjà testé (`test_mapbox_client.py`), **aucun changement nécessaire ici**.
- `geocode_tool.py::geocode_location` reçoit déjà un paramètre `country_code` et le transmet tel quel au client Mapbox — MAIS cette valeur est **entièrement fournie par le modèle** (argument de tool-call LLM), jamais validée ni forcée par du code déterministe.
- `select_us_postal_anchor` (`geo_guards.py`, porté en S4, déjà testé dans `test_geo_guards.py`) n'était appelé **NULLE PART** en dehors des tests — code mort, zéro influence sur la requête Mapbox réelle. C'est exactement le gap du bug prod : si le LLM ne reconnaît pas que « 11580 » implique les USA, le géocodage part sans scope, à la merci du premier match mondial de Mapbox.

**Fait** :
- `geocode_tool.py::geocode_location` — appelle désormais `select_us_postal_anchor(raw_user_message, effective_city, effective_zone, effective_metro)` **avant** la construction de la query, et force `country_code = "US"` **uniquement si le modèle n'a fourni aucun `country_code`** (`not effective_country_code`) — un `country_code` explicite du modèle gagne toujours (jamais de scope inventé par-dessus un signal existant, jamais de biais locale→pays ajouté, posture reconduite de S4/S12). La valeur forcée traverse aussi `resolve_state_hint` (cohérence : `"US"` ne bloque pas la résolution d'un state-hint textuel — seul un pays non-US *truthy* le ferait).
- Aucune modification de `mapbox_client.py` (déjà correct) ni de `select_us_postal_anchor` (déjà correct/testé S4) — seul le câblage manquant a été ajouté, strictement dans le périmètre.

**Tests** (`test_geocode_tool.py`, nouvelle classe `TestUsZipCountryScoping`, 5 tests) :
- Pattern existant (`FakeMapboxClient`) : ZIP US détecté → `country="US"` passé au client ; aucun ZIP/signal pays → `country=None` inchangé ; un `country_code` explicite du modèle l'emporte même sur un nombre à 5 chiffres présent dans le message (« paris 75015 » + `country_code="FR"` → reste `"FR"`, jamais écrasé).
- Preuve renforcée demandée par la phase (« l'URL mockée porte `country=us` ») : 2 tests supplémentaires exercent le VRAI `MapboxClient` via `httpx.MockTransport`, assertion directe sur `request.url.params["country"]`.

**DoD verte** : `pytest agents/hotel_search_agent -q` → **177 passed** (+5, les 172 existants inchangés) ; `pytest -q` (repo entier) → **511 passed** ; `ruff` OK ; `mypy agents libs` → **34 fichiers** OK (inchangé) ; guardrails OK.

**Vérifié LIVE (Mapbox réel, `.env`, aucun token ni contenu de requête imprimé — uniquement des diagnostics structurels : status, feature_count, country résolu, place générique)** :
- **Reproduction ET fix du bug prod sur le VRAI endpoint Mapbox v6**, même query `"11580"` : sans scope pays → `full_address="Mexico City, 11580, Mexico"` (**le bug exact, reproduit en direct**) ; avec `country=us` (notre fix) → `full_address="Valley Stream, New York 11580, United States"` — bascule confirmée.
- **À travers le vrai `geocode_location`** (message combinant zip+ville, « near 11580 baldwin », sans state hint) : `country_param_sent="us"` (forcé par l'ancre), `ok=True`, `resolved_country_code="US"` — le scoping fonctionne de bout en bout dans la feuille réelle. (Résolu vers « Baldwin Park, California » plutôt que le Baldwin NY visé — limitation PRÉEXISTANTE et hors périmètre du guard d'écho `geocode_echo_matches` sur les homonymes multi-états, jamais durci ici — cf. audit « durcissement géo massif », explicitement OUT.)
- **Caveat honnête découvert au probe** : la feuille utilise `DEFAULT_TYPES="place,locality,neighborhood"` (`mapbox_client.py`) — **sans** le type `postcode`. Un message **ZIP SEUL, sans mot de lieu** (« near 11580 », repro le plus littéral du test agent-usa) obtient donc **0 feature** de Mapbox avec CE filtre de types, **que le pays soit scopé ou non** — dégradation honnête (`geocode_unavailable`), identique avant/après ce fix (aucune régression, mais pas non plus une résolution bout-en-bout du repro le plus nu). Élargir `types` pour couvrir ce cas est un changement de capacité géo distinct (même famille que POI/Search Box) — explicitement **hors périmètre S13** (cf. audit : « durcissement géo massif… décision produit, pas un fix »). Le scoping lui-même (l'objet exact de cette session) est prouvé correct et actif dès qu'un mot de lieu accompagne le ZIP dans le message.

**Reste / recommandations** :
- Si la couverture « ZIP seul, sans ville » doit un jour fonctionner de bout en bout : soit élargir `DEFAULT_TYPES` (ajouter `postcode`), soit injecter le ZIP littéral dans la query construite par `geocode_location` (aujourd'hui `query = zone, city, state_hint` — ne réutilise jamais le ZIP lui-même) — décision produit, hors de ce scope.
- `select_us_postal_anchor` reste un détecteur texte pur (aucune connaissance de pays déjà déclaré) : un code postal français à 5 chiffres coïncidant avec le pattern (ex. « 75015 ») pourrait en théorie être mal identifié comme ZIP US si AUCUN `country_code` n'est fourni par ailleurs — comportement hérité tel quel de la fonction déjà portée en S4 (hors périmètre de modifier la détection elle-même ici), mais un `country_code` explicite (le cas normal quand le modèle reconnaît un contexte français) le neutralise toujours (verrouillé par `test_explicit_country_code_wins_over_a_stray_five_digit_number`).

## ⏱ Addendum 2026-07-21 (branche `s14-search-leaf-budget-timeslot`) — S14 : budget/timeslot du tour → `profile_delta` (feuille search) → guards S12 ENFIN actifs en trafic réel

**Contexte** : le gap noté « Reste » depuis S9 et re-souligné en S12 est comblé. `hotel_search_agent` n'émettait toujours pas `budget_max`/`timeslot_*` dans son `profile_delta` → les 3 guards S12 (budget-vs-durée, auto-widen/exhaustion, honnêteté de provenance) étaient des machines à états correctes mais **dormantes**. Zone stricte `agents/hotel_search_agent/**` — **zéro changement concierge** (le contrat `apply_profile_delta` existe depuis S5, clés vérifiées en direct 2026-07-21).

**Fait (feuille uniquement)** :
1. **INSTRUCTION (`agent.py`)** — nouveau bullet : passer `priceRangeMax` (number, EUR) sur un budget explicite (+ `priceRangeMin` si borne basse), `timeSlot{startHour,endHour}` (int 0-23) sur des heures explicites ; **jamais** halluciner une valeur non dite, ne pas transformer un « moins cher »/« plus tôt » vague en nombre → argument omis. Brace-free (l'instruction passe par `.format(amenity_keys=...)`).
2. **`response_bridge.py::capture_after_tool`** — sur `search_offers` (jamais `find_hotel_by_name`, pas de ces params), capture des **args RÉELS** (`priceRangeMax` → `_positive_budget`, rejette 0/négatif/garbage ; `timeSlot` → `_hhmm` en `"HH:MM"`, midnight `startHour=0` non-drop) stashés sous `temp:hotel_search_budget_timeslot`. Tourne aussi sur une recherche 0-résultat (c'est là que l'auto-widen a besoin du budget) ; une recherche en échec (`isError`/`ok False`) retourne avant, rien stashé. `priceRangeMin` **non mappé** au profil (le concierge n'a pas de champ budget-min — jamais en inventer un).
3. **`response_bridge.py::emit_search_datapart`** — mappe vers les clés EXACTES du concierge : `budget_max` (float) + `budget_request_source`, `timeslot_start`/`timeslot_end` (`"HH:MM"`) + `timeslot_request_source`. **`request_source` = `"flexible_default"` TOUJOURS** (`_REQUEST_SOURCE_FLEXIBLE`, littéral local, jamais d'import concierge — B3) ; le guard P1 côté concierge fait seul l'upgrade « explicit ». Only-when-present (une source n'est jamais envoyée sans sa valeur ; une capture vide n'écrase rien).
4. **Compteur RGPD-safe** (`dayuse_metric=budget_timeslot has_budget=0/1 has_timeslot=0/1`, **flags seuls, jamais les valeurs** — même règle que `amenity_filter` S10) : rend la feuille greppable en live, y compris le piège d'hallucination (`has_budget=0` sur une recherche sans budget).

**DoD verte** : `pytest agents/hotel_search_agent -q` → **172 passed** (+18 : capture stash/absent/garbage/midnight/0-résultat/échec, emit full-map/budget-only/timeslot-only/coexistence-city+amenities/omit, 2 tests RGPD du compteur) ; `pytest -q` (repo entier) → **506 passed** ; `ruff` OK ; `mypy agents libs` → **34 fichiers** OK ; guardrails OK.

**Vérifié LIVE (3 services relancés — pas de hot-reload — `.env` réel Mapbox + MCP staging ; Redis dédié `:6380` via `CONCIERGE_REDIS_URL`, JAMAIS le 6379 de Fabien)** :
- **Preuve mandatoire** : `POST /v3/chat` « un hotel a paris demain sous 80 euros entre 14h et 20h » → `active_filters` = `{budget_max: 80.0, timeslot_start: "14:00", timeslot_end: "20:00"}` (**toujours `None` avant ce fix**), 2 offres filtrées. Compteur leaf : `has_budget=1 has_timeslot=1` (sans valeurs).
- **Piège négation/hallucination (leçon S10 #4)** : « un hotel a paris demain » (sans budget) → `budget_max: null`, `timeslot: null`, **5 offres non filtrées**, compteur `has_budget=0 has_timeslot=0` — le modèle n'invente PAS de filtre.
- **⭐ PREMIÈRE PREUVE LIVE du mécanisme auto-widen/exhaustion S12 depuis sa création (S05/S06)** — session multi-tours (Barfleur, 0 offre) : T1 budget 30 (0 offre) → **T2 auto-widen 30→45** (synthèse : « Le budget a été automatiquement augmenté à 45 € » — disclosure surfacée, règle 5) → **T3 45→67.5** (« après plusieurs recherches ») → T4 plafond atteint (widen_attempt_count=2, `search_exhausted=True` posé) → **T5 « ok » → message terminal d'exhaustion** (`route=template:search_exhausted`, **`llm_calls=1`** = triage seul, zéro leaf/synthèse). Profil Redis final : `budget_max=67.0 source=flexible_default widen_attempts=2 consec_empty=4 exhausted=True`. Budget ≤3 LLM/tour respecté partout (search = 3, exhaustion = 1).

**Reste / pièges découverts (tous côté concierge/instruction — HORS périmètre S14, à trancher plus tard)** :
- **Le modèle feuille réutilise `profile_in.budget_max` sur un refinement SANS budget dans le message** (T2/T3/T4 : `has_budget=1` alors que le message ne dit pas de budget) — c'est CE QUI FAIT que le budget élargi prend réellement effet dans les recherches suivantes (bonne nouvelle : l'auto-widen n'est pas théorique). Effet de bord mineur : gpt-4o-mini **arrondit** parfois en ré-émettant (`67.5→67`), d'où le `67.0` stocké vs le `67.5` de la synthèse T3. Provenance reste `flexible_default` (correct, jamais downgrade d'un explicit — voir point suivant).
- **Le guard P1 « bare number → explicit » du concierge est en pratique inatteignable via la feuille** : une réponse nue « 80 » route bien vers search (`family=search`) mais la feuille (stateless, ne sait pas si « 80 » = euros/invités/étoiles) **ne l'extrait PAS comme budget** → `budget_max` reste `None`, l'upgrade explicit ne se déclenche jamais. Conséquence : les budgets restent `flexible_default` (donc toujours auto-widenables) — parfait pour la démo S12, mais si on VEUT qu'un budget nu devienne « explicit » (non-widenable), c'est un travail concierge (interpréter le nombre nu en contexte de collecte, le concierge a l'état) ou d'instruction feuille — explicitement OUT en S14 (phase : « la feuille reste flexible_default toujours »).
- Ce bloc **clôt le « Reste » de l'addendum S12** (« combler le gap `budget_max`/`timeslot` en profile_delta … PRÉREQUIS pour que les guards #1/#2/#4 s'exercent ») et le « Reste » S9 (« budget/timeslot du tour ne sont pas encore réémis en profile_delta »).

## ⏱ Addendum 2026-07-20 (branche `s12-drift-guards`) — S12 : 4 guards drift orchestrateur (exhaustion, budget/durée, named-hotel, provenance)

**Contexte** : `AUDIT-DRIFT-AGENT-USA-2026-07-20.md` a trouvé 4 fixes prod agent-usa (`29fcb6e..b429125`) jamais portés (checkout figé avant S1). Session pilotée (plan mode), zone stricte `agents/b2c_concierge/**` — feuille search et `evals/**` non touchées.

**Fait** :
1. **Guard search-exhaustion terminal** (`profile.py`) — `maybe_auto_widen` était SANS plafond (bug prod agent-usa 034c97c4, Rimini, 9 tours vides) : chaque tour vide ≥2 rewidenait ×1,5 à l'infini. Ajout `widen_attempt_count`/`search_exhausted` sur `SessionProfile`, plafond `AUTO_WIDEN_MAX_ATTEMPTS=2` : après 2 widens réels, le 3e échec pose `search_exhausted=True`. `record_search_outcome` efface les deux flags sur un succès. Gate déterministe dans `agent.py` (AVANT `_run_leaf`, zéro appel LLM/MCP supplémentaire) : un affirmatif nu (`is_bare_affirmative`, nouveau wrapper public de `_AFFIRMATIVE_RE`) reste bloqué sur un message terminal (`templates.search_exhausted_response`) ; tout AUTRE message efface les flags et relance une recherche. **Semantique retenue = celle proposée par `phases/S12-drift-guards-orchestrateur.md`** (un seul cran, contrairement à agent-usa qui widen zone/budget/amenity).
2. **Budget-vs-durée** (`profile.py`) — `_looks_like_time_derived_budget` (port comportemental, proportionné : sans la liste de 15 devises ni le cas HH:MM d'agent-usa, non exercés par les 2 tests spec portés) rejette un `budget_max` qui ressemble à une mention de durée/distance (« less than 20 minutes away ») AVANT persistance dans `apply_profile_delta` — jamais de `max_distance_km` (hors périmètre, ce spine n'a pas ce concept).
3. **Précédence named-hotel** (`profile.py` + `inline_tools.py`) — `_resolve_hotel_id` faisait confiance à la shortlist même sur le tier FAIBLE (chevauchement d'un seul mot distinctif), zéro vérification MCP. **Résolution personnelle d'une ambiguïté explicitement signalée par la session** (le fix d'agent-usa suppose une architecture repo city-scoped vs global qui n'existe pas ici) : le tier substring (fort) reste inchangé (zéro appel MCP) ; le tier token-only (faible) n'est plus jamais fait confiance seul — `find_hotel_by_name` (global) est TOUJOURS appelé et son résultat gagne ; le hit faible ne sert plus que de dernier recours si MCP dégrade. Nouvelle fonction `resolve_hotel_reference_strict` (substring only) + refactor `_hotel_matches`→`_substring_match` (zéro changement de comportement de `resolve_hotel_reference`/`resolve_hotel_references`, `compare_hotels` continue d'utiliser le tier faible sans MCP, inchangé, hors périmètre).
4. **Honnêteté de provenance** (`agent.py`) — Rule 8 dans `_SYNTHESIS_INSTRUCTION` + note `PROVENANCE:` injectée (même mécanisme que `AUTO_WIDEN:`, S06) quand `budget_request_source`/`timeslot_request_source` ≠ explicit : la synthèse ne peut plus jamais dire « comme demandé » sur une valeur par défaut.
5. **README concierge** : note sur `client_local_time`/`client_timezone` (2 champs optionnels que le front agent-usa envoie désormais, PR #125) — ignorés sans casse, aucune résolution "now" à brancher dessus aujourd'hui.

**DoD verte** : `pytest agents/b2c_concierge -q` → **230 passed** (+31 neufs : `TestSearchExhaustion`, `TestIsBareAffirmative`, `TestBudgetVsDurationGuard`, `TestResolveHotelReferenceStrict` dans `test_profile.py` ; 2 tests named-hotel dans `test_inline_tools.py` ; `TestSearchExhaustionThroughTheSpine`, `TestProvenanceHonestyThroughTheSpine` dans `test_spine_profile.py`) ; `pytest -q` (repo entier) → **482 passed** ; `ruff` OK ; `mypy agents libs` → **34 fichiers** OK (une erreur de narrowing `float | None` corrigée dans `maybe_auto_widen`) ; guardrails OK ; `run_release_gate.py --quick` → **PASS**.

**Vérifié LIVE (3 services relancés, `.env` réel, MCP staging)** :
- **Item 3 (named-hotel) validé en direct contre le VRAI MCP_B2C** : shortlist périmée `{"name": "Villa Something Unrelated"}` (chevauche le mot « villa » avec la requête « Villa Paris Orly ») → `get_hotel_details` résout bien vers le VRAI hôtel (id 22293, via `find_hotel_by_name` global), jamais vers le hit faible périmé — la coïncidence d'un seul mot ne masque plus la recherche globale.
- **Items 1/2/4 (exhaustion, budget-vs-durée, provenance) : PAS vérifiables en LIVE bout-en-bout** — constat fait en session, pas une régression : la feuille `hotel_search_agent` **n'émet toujours pas `budget_max`/`budget_request_source` dans son `profile_delta`** (gap déjà documenté S9 : « budget/timeslot du tour ne sont pas encore réémis en profile_delta ») — confirmé par grep (`response_bridge.py` : zéro occurrence). Résultat : `apply_profile_delta`'s bloc budget ne s'exécute JAMAIS sur un tour réel aujourd'hui → le mécanisme de widen (et donc l'exhaustion, et donc la note PROVENANCE côté budget) ne s'est **jamais** déclenché en prod/dev réel, ni avant ni après S12 — exactement la même limite que l'auto-widen S05/S06 (jamais vérifié live non plus à l'époque, seulement testé avec un `profile_delta` FAKÉ). Les tests automatisés (qui fakent le delta, comme `TestAutoWidenThroughTheSpine` le faisait déjà avant S12) sont donc la SEULE vérification actuelle de ces 3 items — posture honnête, pas une régression introduite ici.
- Répliqué en live 6 tours (recherche normale, relances, "ok", nouvelle ville) : zéro crash, zéro 500, comportement cohérent avec l'absence de budget capturé (le "ok" a reçu la synthèse normale "no offers", jamais le message terminal, puisque `search_exhausted` n'a jamais pu se poser).

**Reste / recommandations** :
- **Combler le gap `budget_max`/`timeslot` en `profile_delta`** (feuille search, zone S13 ou une future session dédiée) est un PRÉREQUIS pour que le guard #1/#2/#4 s'exercent jamais en trafic réel — sans ça, ce sont des machines à états correctes mais dormantes.
- `empty_dead` de la batterie S8 peut désormais retourner un message terminal au lieu d'un widen infini — **ne PAS re-poser la baseline ici**, différé à S10 (shadow-run) comme prévu par la phase.
- Item 3 est ma résolution d'une ambiguïté explicitement signalée par `phases/S12-drift-guards-orchestrateur.md` (« si doute → STOP, demander ») — présentée en plan avant codage, à confirmer en review PR.

## ⏱ Addendum 2026-07-20 (branche `fix-hotel-photos`) — vraies photos hôtel (toutes les cartes montraient le placeholder par défaut)

**Bug (repro widget)** : toutes les cartes affichaient `https://images.dayuse.com/hotels/default/default.jpg` au lieu d'une vraie photo.

**Cause** : le widget (`agent-usa/static/js/chat/hotels/card.js`, `ui/messages.js`) lit `hotel.image_urls` (tableau) et retombe TOUJOURS sur ce placeholder codé en dur quand il est vide. Les deux constructeurs de carte AgentB2C (`hotel_search_agent/response_bridge.py::normalize_hotel`, `b2c_concierge/inline_tools.py::_normalize_hotel_for_display`) ne posaient jamais `image_urls` — décision documentée depuis S6/S7 : MCP ne renvoie `mainPhotoNormal` qu'en **chemin relatif** (`/hotels/22293/....png`), « base inconnue, jamais inventer de lien ».

**Ce qui a changé** : cette base est désormais résolue avec une preuve empirique, pas une supposition.
- Page hôtel réelle (`www.dayuse.com/hotels/france/villa-paris-orly`, hôtel 22293) → sa vraie photo vit à `https://static.dayuse.com/hotels/22293/c243849e1e41ef651a1dabaabe49bfd6-villa-paris-orly.png` — **exactement le même suffixe de chemin** que `mainPhotoNormal` renvoie pour ce même hôtel côté MCP.
- Aucune constante documentée trouvée ni dans MCP_B2C (`hotel-document.schema.ts` : le champ est un simple `z.string()`, aucune base assumée) ni dans un repo du site principal accessible localement — le chemin relatif est une caractéristique réelle du stockage ES, la résolution est une convention du frontend Next.js.
- L'allowlist du widget (`security.js::isDayuseHost`) accepte déjà N'IMPORTE QUEL sous-domaine de `dayuse.com` (`hostname.endsWith('.dayuse.com')`) → `static.dayuse.com` passe sans AUCUN changement widget.
- `mainPhotoNormal` est présent sur toutes les formes d'hôtel MCP utiles : `search_offers`, `get_hotel_details`, `find_hotel_by_name`, `compare_hotels`.

**Fait (zone concierge + feuille search, zéro changement facade/widget)** :
- `_PHOTO_BASE_URL = "https://static.dayuse.com"` + `_photo_url(main_photo_normal)` — dupliqué dans les deux constructeurs de carte (même convention existante que `_format_price_eur_cents`, déjà dupliqué à l'identique dans les deux fichiers — pas de module `card_utils` partagé dans ce repo). Provenance empirique documentée en commentaire dans le code.
- `normalize_hotel` (feuille, couvre `search_offers`+`find_hotel_by_name`) et `_normalize_hotel_for_display` (concierge, couvre `get_hotel_details`+`compare_hotels`) posent `card["image_urls"] = [photo]` quand `mainPhotoNormal` résout ; sinon la clé est absente (jamais un tableau vide/cassé).
- `facade.py::normalize_hotels` — **zéro changement de code** : fait déjà `card = dict(hotel)` (passthrough générique) avant le formatage prix, donc `image_urls` atteint le JSON public `/v3/chat` automatiquement. Un test de verrouillage ajouté.
- **DoD verte** : `pytest -q` → **467 passed** (+8 neufs : `test_response_bridge.py` ×4, `test_inline_tools.py` ×3, `tests/api/test_contract_mapping.py` ×1) ; ruff OK ; mypy 34 fichiers OK ; guardrails OK.
- **Vérifié LIVE** (3 services relancés, `.env` réel) : recherche Paris → 5 cartes, chacune avec un `image_urls` `static.dayuse.com` réel ; **les 5 URLs `curl -I` → `200`** (vraies images, pas des 404) ; `details sur villa paris orly` → même photo réelle sur la carte inline ; `smoke_e2e.py` PASS.

**Reste / limites** :
- La provenance de `static.dayuse.com` est empirique (reverse-engineering de la page prod), pas un contrat documenté par MCP_B2C ni le site principal — si l'un ou l'autre change un jour sa convention de stockage/CDN, cette constante devra être mise à jour ici (aucun signal automatique ne préviendrait d'une rupture, à part des photos cassées en prod).
- `mainPhotoOriginal` (haute résolution, vu sur `get_hotel_details`) n'est pas utilisé — `mainPhotoNormal` seul suffit au besoin actuel (une vignette de carousel).

## ⏱ Addendum 2026-07-20 (branche `s10-amenity-filters`) — filtres amenities réels sur la recherche (« piscine à Miami » → 0 offre corrigé)

**Bug (repro live)** : « je voudrais un hotel à miami avec une piscine » → « aucune offre » alors que Miami a 55 hôtels (44 avec piscine). Cause : `search_offers` n'a AUCUN paramètre amenity texte — uniquement `hotelEquipmentIds`/`roomEquipmentIds` (IDs équipement **entiers**, hard filters, `additionalProperties: false`) ; rien ne mappait « piscine » → ID, le LLM feuille **hallucinait un ID** (repro : `[33]` réel → total=44, `[1]` halluciné → **total=0**). Invisible aux logs (métriques scrubbed RGPD : un hard filter trop strict ressemble à un search sain `status=ok`). Défaut secondaire : cartes `amenities: []` → le guard de véracité hedgeait des claims « pool » VRAIS (« (non confirmé) »).

**Décisions (Fabien)** : tout le traitement amenities vit dans la FEUILLE (zéro code concierge) ; c'est le **LLM existant de la feuille qui extrait l'intention** (clés canoniques d'une liste FERMÉE — pas de regex déterministe) ; le référentiel équipements vient du code MCP_B2C (lecture autorisée) : `src/shared/reference/hotel-equipment.json` + `pool-equipment-ids.ts`.

**Fait (zone feuille uniquement)** :
- **`equipment_ids.py` (neuf)** — 3 briques :
  - `EQUIPMENT_IDS` : table canonique → IDs. `pool → (33, 34, 2982, 3000, 3001)` = exactement le OR-group serveur `HOTEL_POOL_EQUIPMENT_IDS` (les IDs piscine sont OR-matchés serveur ; TOUS les autres AND) ; spa 35, gym 38, jacuzzi 41, sauna 2951, restaurant 14, breakfast 2992, pet_friendly 2956, shuttle 2949. **Non mappés (dégradation honnête = pas de filtre + hedge du guard)** : parking (5 variantes, piège AND), rooftop (2981 bar vs 2982 pool, ambigu), `roomEquipmentIds` hors v1 (toujours poppé, jamais posé).
  - `inject_amenities_declaration` (`before_model_callback`) : élargit la déclaration `search_offers` VUE PAR LE MODÈLE avec un param **virtuel** `amenities` (array, `enum` = clés de la table) — mécanisme vérifié dans l'ADK installé : `McpTool._get_declaration` expose le JSON schema brut (`parameters_json_schema`), LiteLLM le forwarde verbatim (lite_llm.py:1818) → l'enum atteint n'importe quel `DAYUSE_MODEL`, modes strict satisfaits. **deepcopy obligatoire** (la déclaration RÉFÉRENCE l'inputSchema caché du McpTool) ; si un futur ADK cesse d'exposer un dict → no-op gracieux (testé).
  - `enforce_equipment_filters` (`before_tool_callback`, câblé DERNIER) : **seul écrivain des filtres équipement**. Poppe TOUJOURS `hotelEquipmentIds`/`roomEquipmentIds` écrits par le LLM (tue à lui seul le bug d'ID halluciné), poppe le param virtuel `amenities` avant que le serveur (schéma strict) ne le voie, valide chaque clé contre la table, fait l'union avec `profile_in.amenities` (décodé du DataPart entrant via `tool_context.user_content` — chaîne vérifiée part_converter→runners→readonly_context), pose `hotelEquipmentIds` déterministe, stashe les clés appliquées (`temp:hotel_search_applied_amenities`, explicitement `[]` sinon). Métrique : `dayuse_metric=amenity_filter n_keys= n_ids=` (compteurs seuls, jamais les clés — même règle RGPD que la ville).
- **`response_bridge.py`** : miroir `decode_datapart`/`find_datapart` (B3, aucun import orchestrateur) ; **estampillage cartes** : une recherche hard-filtrée stampe les clés appliquées sur chaque carte (`pet_friendly` → « pet friendly », la table de synonymes du guard ne connaît que la forme espacée) — vérités garanties serveur, le guard cesse de hedger et le ground-truth block les affiche ; **`profile_delta.amenities`** réémis (only-when-present) → le concierge ré-apprend via son merge déjà testé, `search_context_line`/`active_filters` s'allument LE MÊME TOUR (delta appliqué avant synthèse), accumulation multi-tours (« avec piscine » T1 → « moins cher » T2 toujours filtré).
- **`agent.py` feuille** : injection ajoutée en dernier de `before_model_callback` (skip_final_generation reste premier — son court-circuit saute aussi l'injection) ; enforcement dernier de `before_tool_callback` ; INSTRUCTION : bullet amenities avec la liste fermée injectée par `.format()` module-level (jamais de drift instruction↔enum, testé) + interdiction explicite d'écrire les IDs.
- **Piège découvert au probe live (gpt-4o-mini)** : sur « sans piscine », le modèle a d'abord émis les **8 autres clés** (inversion de la négation) → AND sur 8 équipements → 0 hôtel. Corrigé en durcissant l'instruction + la description du param virtuel (« ne JAMAIS compenser avec les clés restantes ; exclusion = argument omis = recherche non filtrée »). Re-testé : « sans piscine demain » → 5 hôtels non filtrés, aucune ligne `amenity_filter`. La qualité d'extraction reste LLM-dépendante (choix assumé) : échec = recherche non filtrée, jamais un mauvais hard filter (validation code de chaque clé).
- **DoD verte** : `pytest -q` → **459 passed** (+31 : 24 `test_equipment_ids.py` neufs, 11 ajoutés/adaptés `test_response_bridge.py`, wiring `test_agent.py`, 1 spine concierge `test_amenities_delta_is_persisted_and_surfaces_in_search_context`) ; ruff OK ; mypy **34 fichiers** (+1) ; guardrails OK ; `smoke_e2e.py` PASS.
- **Vérifié LIVE** (3 services relancés, `.env` réel, MCP staging, sans Redis) : « avec piscine » → **3 hôtels Miami**, cartes `amenities=['pool']`, réponse « avec piscine » SANS « (non confirmé) », log `amenity_filter n_keys=1 n_ids=5`, `llm_calls=3` inchangé ; « sans piscine demain » → 5 hôtels non filtrés, pas de ligne filtre.

**Reste / recommandations** :
- `active_filters.amenities` reste `[]` en dev local sans Redis (limitation S5 documentée — la persistance est couverte offline par fakeredis).
- Suppression d'amenity (« finalement sans piscine » après un tour piscine) = travail futur : la négation empêche seulement l'AJOUT, une clé au profil persiste.
- Approximations assumées : sauna → 2951 seul (40 legacy + 2952 Hammam AND-eraient), shuttle → 2949 seul.
- **Recos équipe MCP_B2C** : accepter des amenities canoniques string côté serveur (le mapping ID appartient au serveur) + retourner les amenities par hôtel sur `search_offers` (l'estampillage client deviendrait inutile).
- Négation/extraction = couverture eval (battery), pas unit-testable (les units verrouillent seulement que le code n'invente jamais un filtre que le modèle n'a pas émis).

## ⏱ Addendum 2026-07-20 (branche `s9-fix-market-country`, fille de `s9-facade`) — fix pays/marché du payload `/v3/chat` (bouton « hôtels en USA » + URLs cards 404)

**Bug (repro widget local, recherche Paris)** : bouton carrousel « Voir tous les hôtels en USA » + clic card → `dayuse.com/hotels/usa/<slug>` 404. Le widget résout le marché depuis `hotels[0].country_code` (ISO alpha-2 — sa table `COUNTRY_META` est indexée ISO, un nom complet ne matche pas) puis compose l'URL fallback `dayuse.<meta>/hotels/<countrySlug>/<slugify(name)>` ; non résolu → défaut USA/.com (`agent-usa/static/js/chat/markets.js:238`). Nos cards n'avaient AUCUN code pays : le geocode Mapbox retourne `country_code` ISO mais `capture_after_tool` le jetait ; le `profile_delta` feuille ne mappait que `city`/`state_anchor` → `profile.country_anchor` jamais posé → `_infer_market_country` toujours `None` → `market={}`.

**Fait** :
- **Probe live MCP `search_offers` AVANT de coder** (précédent S7) : les hôtels réels portent `countryName` (`'France'`, nom complet — inutilisable par le widget) et un **`slug` réel** (`'villa-paris-orly'`), mais NI `countryCode` NI `url`. Le `slug` est un cadeau pour un futur pass-through d'URL exacte (le widget lit `hotel.url` verbatim si host allowlisté) — non exploité ici (composer l'URL exigerait de dupliquer la table marché du widget côté feuille = hors périmètre, jamais d'URL fabriquée).
- **`response_bridge.py` (feuille)** : `_STATE_COUNTRY_KEY` (`temp:`, invocation-scoped) stash le `country_code` ISO du geocode (validé alpha-2 via `_iso_alpha2`, jamais un nom) ; les cards du chemin `search_offers` UNIQUEMENT reçoivent `card.setdefault("country_code", <stash>)` (un `countryCode` serveur gagnera toujours s'il apparaît un jour ; `find_hotel_by_name` PAS estampillé — pas exécuté aux coordonnées géocodées) ; `emit_search_datapart` ajoute `profile_delta["country_anchor"]` (only-when-present, jamais de `None` effaceur — le wipe city-change de `apply_profile_delta` gère la staleness, déjà testé côté orchestrateur, zéro changement orchestrateur).
- **`facade.py`** : `_infer_market_country` ne retourne plus que des valeurs formées ISO alpha-2 (`_iso_alpha2`) — le bug latent « `country: "France"` → pseudo-code `"FRANCE"` » est verrouillé (`None` est strictement meilleur : le widget retombe sur son marché d'entrée).
- **DoD verte** : `pytest -q` → **429 passed** (13 neufs : 9 `test_response_bridge.py`, 4 `tests/api/test_contract_mapping.py`) ; ruff OK ; mypy 33 fichiers OK ; guardrails OK. **Live** (3 services relancés — pas de hot-reload, piège S7) : `POST /v3/chat` « hotels demain à Paris » → `market={"country_code":"FR"}`, `market_country`/`entry_market_country`/`search_country`=`"FR"`, `hotels[0].country_code="FR"` (Villa Paris Orly). **Re-test visuel widget à faire par Fabien** (bouton « en France » + clic card sans 404).

**Reste / caveats** :
- `active_filters.country_code` reste `null` en dev local **sans Redis** (dégradation documentée S5, vérifiée aux logs — pas un défaut du fix : l'ancre arrive par le profil persisté ; chemin couvert offline par `test_market_falls_back_to_profile_country_anchor` + tests delta feuille). Les champs marché, eux, sont dérivés des cards du tour → OK même sans Redis.
- **Frontière** : une recherche Genève retournant des hôtels français estampille le pays de la RECHERCHE (setdefault) — dégradation = URL fallback slugifiée, même classe d'approximation que le fallback prod ; le `countryCode` MCP par hôtel gagnera dès que le serveur l'enverra.
- Coordination : les phases S12/S13 (posées ce jour, non lancées) rebaseront par-dessus — ce fix livre une partie du country-anchoring noté « jamais porté » dans `AUDIT-DRIFT-AGENT-USA-2026-07-20.md`.

## ⏱ Addendum 2026-07-20 (même branche `s9-facade`) — feuille search : 3e appel LLM (prose finale gaspillée) supprimé → 3→2 appels internes

**Contexte** : la latence feuille borderline notée depuis S2 (Fougères/Quimper timeout > 10 s puis passés) tenait pour partie à un **3e appel LLM inutile**. La feuille est un `LlmAgent` : sa boucle tool-calling fait geocode-décision (#1) → search-décision (#2) → **prose finale (#3)**. Or #3 est **doublement jeté** : `emit_search_datapart` (after_agent_callback) écrase sa prose par un `_outcome_text` construit en CODE (zéro LLM), et le concierge **re-synthétise** de toute façon la réponse utilisateur depuis les `results` structurés + le ground-truth block (la prose feuille n'est qu'un input « OUTCOME » non fiable + un fallback total-échec). Coûtait ~2–4 s gaspillées par recherche. **Purement latence** (la feuille compte comme UN slot `leaf_llm`, budget ≤3/tour intact).

**Fait (zone feuille `hotel_search_agent`, `s9-facade`)** :
- **`response_bridge.py::skip_final_generation`** (neuf) — un `before_model_callback` : si `capture_after_tool` a déjà stashé les résultats (`temp:hotel_search_results` présent), il renvoie un `LlmResponse` canné (le MÊME `_outcome_text`) → ADK **court-circuite l'appel modèle réel** (`base_llm_flow` : une réponse before_model_callback truthy est yieldée, l'appel n'a pas lieu). Garde sur `is None`, PAS falsiness : un search à **0 résultat** stashe `[]` (vrai outcome) et court-circuite quand même ; seuls geocode-fail / clarification / MCP-dégradé laissent la clé absente → le modèle génère alors le diagnostic honnête (fallback `leaf_text`).
- **`agent.py`** — `skip_final_generation` câblé **EN PREMIER** dans `before_model_callback` : le court-circuit revient avant `after_model_callback`, donc `llm_timing_after` ne tire pas ; le placer en tête évite que `llm_timing_before` stampe un timer orphelin (et `inject_today` un append inutile) sur un appel qui n'aura pas lieu.
- **DoD verte** : `pytest -q` → **417** (+4 : `test_response_bridge.py::skip_*` — non-vide court-circuite, `[]` court-circuite avec ligne « no offers », pas-de-search → None, geocode-seul → None) ; `ruff` OK ; `mypy` **33** ; guardrails OK.
- **Vérifié LIVE (3 services redémarrés — pas de hot-reload — `.env` réel Mapbox + MCP staging, sans Redis)** : compteur `dayuse_metric=llm_call` de la feuille = **exactement 2 par `inv`** (était 3 ; le 3e ex-appel avait `completion_tokens=17-20`, la prose jetée). Paris (5 offres), **Fougères** (1 offre, Campanile 47 €), **Quimper** (3 offres) → tous `status=ok`, réponses correctes/groundées, cartes peuplées. `leaf_call ms` : Paris **4592**, Fougères **2725**, Quimper **2661** (avant, même run précédent : 3403/4185/**8696** + un **degraded** 6258) — les villes qui timeoutaient passent avec marge sous les 10 s, zéro dégradation. Turn budget inchangé (`llm_calls=3` = triage+leaf_llm+synthesis).

**Reste** :
- **Tail worst-case toujours borné par l'I/O séquentiel** (Mapbox geocode 1,5 s +1 retry, MCP search ≤5 s) que ce fix ne coupe pas. Si une ville repasse > 10 s malgré les 2 appels, l'option différée = **feuille code-owned** (1 appel LLM d'extraction de params → geocode+search déterministes, 3→1) — plus gros rewrite, worst-case toujours I/O-bound. Cache géocode inutile pour les villes froides type Fougères/Quimper (1er géocodage).
- Non commité : working tree prêt sur `s9-facade`, en attente du go de Fabien (le commit + MR sont sa décision ; la review reste le gate).

## ⏱ Addendum 2026-07-20 (même branche `s9-facade`) — multi-tours souple (refinement) + réponses transparentes

**Contexte** : tests live post-search → deux manques UX. (1) « je le veux pour le 28 » / « moins cher » (changer la date/le budget d'une recherche) partaient en `booking` → cul-de-sac « Je n'arrive pas à préparer cette réservation ». (2) Quand rien ne revient, l'utilisateur est perdu : la réponse ne dit pas ce qui a été compris, ni pourquoi c'est vide.

**Fait (spine concierge + 2 lignes d'instruction feuille — `s9-facade`)** :
- **Routing refinement (déterministe, code-owned — « le LLM ne route jamais »)** : `profile.is_search_refinement_signal` étendu — déclenche aussi quand un **contexte de recherche antérieur existe** (`city`/`last_results`/streak vide) ET que le message porte un **modificateur** (date `le 28`/`demain`/mois/jour, budget `moins cher`/nombre nu/€, créneau via `_TIME_MENTION_RE`, zone) ET **ne nomme pas** un hôtel de la shortlist (`resolve_hotel_reference` → sinon ça reste booking/details). L'override dans `agent.py` s'applique désormais **quelle que soit la famille triage** (plus seulement `template`) : booking-confirmation d'abord, puis refinement→`search`, **sauf `faq`** (une question de politique avec une date reste faq). + une ligne de désambiguïsation dans le prompt de triage (defense-in-depth).
- **Feuille reuse la ville mémorisée** : instruction ajoutée — un follow-up qui ne change que date/budget/filtres réutilise `profile_in.city` comme destination (le modèle voit déjà `profile_in.city` + le message + TODAY, cf. addendum précédent). Pas de query_params ni de réécriture de message.
- **Transparence** : (a) le bloc **SEARCH CONTEXT** (city/budget/timeslot/amenities, via `profile.search_context_line`) est injecté dans le prompt de synthèse + règle 7 → la réponse **restitue** ce qui a été cherché (la date est déjà dans le MESSAGE que la synthèse voit) ; (b) les 3 cas « rien » sont distincts : **empty honnête** (0 résultat → synthèse dit « aucune offre à <ville> pour <date> + change date/zone/budget », `_EMPTY_SCREEN_NOTE` durci), **technique** (`leaf_degraded_response` nomme la ville), **booking sans sélection** (`templates.booking_needs_selection_response` **liste la shortlist** `profile.last_results` au lieu du message plat — distingue les raisons). `stub_response` (mort) supprimé.
- **DoD verte** : `pytest -q` → **413** (+14 : refinement detector, search_context_line, refinement routing spine, booking-needs-selection) ; `ruff` OK ; `mypy` 33 ; guardrails OK.
- **Vérifié LIVE** (Redis dédié **:6380** — `CONCIERGE_REDIS_URL=redis://localhost:6380/0`, jamais le 6379 de Fabien ; 3 services + proxy UI :8090 up) : session partagée → « Paris demain » (5 hôtels) → **« ok je le veux pour le 28 » → family=search** (plus booking !) → « Pour le 28, j'ai trouvé 5 offres à Paris » → « moins cher » → 3 offres moins chères. Booking sans hôtel nommé → liste les 5 hôtels à choisir. **Barfleur/Ouessant** (0 offre, status=ok) → « Il n'y a pas d'offres à Barfleur pour demain — changer la date, élargir la zone ou ajuster le budget ». Budget ≤3 LLM/tour respecté (l'override n'ajoute aucun appel).

**Reste** :
- **Multi-tours EXIGE Redis** (continuité de profil) — inhérent ; **:6380** en local, vrai Redis en déploiement. Sans Redis, l'override refinement ne détecte pas le contexte antérieur.
- ~~**Latence feuille toujours borderline** sur certaines villes (3 appels LLM internes)~~ **RÉSOLU** par l'addendum en tête (3e appel LLM gaspillé supprimé → 3→2 ; Fougères/Quimper repassent à ~2,7 s, zéro dégradation). Tail worst-case restant borné par l'I/O (Mapbox+MCP), voir « Reste » du bloc en tête.
- La date n'est pas un champ de profil (elle vit dans le message du tour) : « change encore la date » sur un tour SANS ville re-mentionnée marche via `profile_in.city`, mais une date n'est pas persistée pour un tour ultérieur — extension future si besoin.
- Sélection ordinale (« le premier ») non gérée comme refinement (pas un modificateur de param) — tombe sur booking-needs-selection (liste la shortlist), acceptable ; résolution d'ordinal = futur.

**Pièges découverts** :
- **A2A card builder rejette une `instruction` callable** (`_replace_pronouns` regex sur une fonction → `to_a2a` plante au boot) — la date TODAY (addendum précédent) DOIT passer par un `before_model_callback`, pas une instruction dynamique. (Déjà corrigé ; re-confirmé pertinent ici en ne rendant PAS l'instruction feuille dynamique.)
- **`docker rm -f --filter publish=6379`** a supprimé par erreur le `dayuse-redis-1` de Fabien (projet dayuse.com, up 10 j) — **volume `dayuse_redis-data` intact** (rm ne touche pas les volumes nommés) ; restaurable via `docker compose -f .../orchestration/docker-compose.yml -f docker-compose.dev.yml up -d redis`. **Leçon : jamais de suppression docker par filtre large ; cibler par nom, et STOP si un conteneur `Up` non-créé-par-moi apparaît.** Fabien a choisi « laisse tomber pour l'instant » ; 6379 laissé libre.

## ⏱ Addendum 2026-07-20 (même branche `s9-facade`) — feuille search : résultats STRUCTURÉS + troncature payload → « aucun résultat » RÉSOLU

**Contexte** : après S9, un test live via l'interface d'agent-usa remontait « aucun résultat de recherche ». Audit de bout en bout (3 couches) : `search_offers`/géocodage MARCHENT, mais deux gaps AMONT (feuille, déjà notés « Reste » S4/S5/S6) :
1. **Pas de DataPart structuré** — la feuille (`LlmAgent`) répondait en PROSE seule ; le concierge (`find_datapart`) ne trouvait rien → `hotels` toujours vide → carousel vide MÊME sur un succès.
2. **Payload ~24k tokens** — `search_offers` (structuredContent + miroir texte) réinjecté dans le modèle → appel LLM final ~11 s > budget feuille 10 s → `TimeoutError` → dégradation honnête (dominait : 3/3).

**Fait (zone feuille `hotel_search_agent`, sur `s9-facade` — décision explicite de Fabien : hors zone façade S9, expansion assumée de la PR S9)** :
- **`response_bridge.py` (neuf)** — deux hooks ADK natifs sur l'`LlmAgent` existant (pas de wrapper) :
  - **`capture_after_tool`** (`after_tool_callback`, placé **DERNIER** après `mcp_circuit_after_tool` — un retour non-None coupe la chaîne, ne doit jamais masquer l'observation du breaker) : normalise le top-5 (camelCase MCP → shape d'affichage, prix `priceEuro` cents → `€X.XX`, timeslots), **stashe** dans `tool_context.state["temp:…"]`, et **remplace** le payload que le modèle ingère par le compact top-5 (24k → **~2,9k tokens** vérifié). Sur échec (`isError`/`ok False`) → `None` (le modèle voit l'erreur). Géocode : stashe son `profile_delta`, pas de troncature.
  - **`emit_search_datapart`** (`after_agent_callback`) : émet UN event portant à la fois un **texte d'outcome court (construit en CODE, zéro LLM)** ET le DataPart `{results, profile_delta}` — encodage byte-compatible avec `b2c_concierge.a2a_datapart` (constantes ADK `part_converter`, aucune dépendance au package concierge, feuilles indépendantes B3).
- **`agent.py`** — `after_tool_callback += [capture_after_tool]`, `after_agent_callback=[emit_search_datapart]` ; **instruction raccourcie** (le texte du modèle est de toute façon remplacé/redondant → 1 phrase → gagne de la latence sur l'appel final).
- **3 bugs trouvés EN LIVE (pas au 1er jet, cohérent avec la leçon S7 « probe/exécute pour de vrai »)** :
  1. `hotel.get("hotelId") or hotel.get("id")` transforme un `hotelId==0` légitime en `None` (0 falsy) → helper `_first` (première valeur non-None). Attrapé par un test.
  2. **L'event du `after_agent_callback` (non-partial, dernier) REMPLACE le texte du modèle dans l'artefact A2A** (miroir inverse du piège S6 : dernier non-partial gagne) → le concierge recevait un DataPart SANS `leaf_text` → `leaf_text None` → dégradation (alors que `leaf_call status=ok` !). **Fix : émettre texte + datapart dans le MÊME `Content`** (les deux parts survivent). Diagnostiqué par un probe A2A direct de la feuille (`part kinds: ['data']`, aucun texte).
  3. **Écart de nommage S5** confirmé et corrigé ICI : géocode renvoie `last_city`/`last_state_context`, le concierge `apply_profile_delta` lit `city`/`state_anchor` → mapping fait dans `emit_search_datapart` (le concierge possède le schéma profil).
- **Vérifié LIVE (services réels, `.env`, sans Redis/DATABASE_URL)** : recherche Paris via `/v3/chat` → **5 hôtels** (Villa Paris Orly €54, OKKO €70, Eurohotel Créteil €58, Novotel €72, Campanile €60) avec stars/rating/timeslots, `ready_to_search=True`, `active_filters.city="Paris"`, message FR synthétisé listant les offres. **4/4 recherches OK**, `leaf_call` désormais **4,3–6 s** (était ~11 s timeout), `turn status=ok` (3 LLM/tour, budget respecté). `smoke_e2e.py --contract` : le tour search renvoie les vraies offres (plus le message dégradé). Relayé aussi par le proxy UI (:8090) → cartes rendues côté navigateur.
- **DoD gate verte** : `pytest -q` → **399** (+15 `test_response_bridge.py`, offline : normalize/troncature/emit vérifiés via le VRAI converter ADK `convert_genai_part_to_a2a_part`) ; `ruff` OK ; `mypy agents libs` → **33 fichiers** (+1) ; guardrails OK.

**Reste (partiels honnêtes, pas des blocages)** :
- `search_offers` ne porte PAS d'amenities (seul `get_hotel_details` en a) → `amenities: []` sur les cartes de recherche… **[PÉRIMÉ depuis S10 — voir l'addendum s10-amenity-filters : les cartes d'une recherche hard-filtrée sont estampillées avec les amenities garanties serveur.]** Pas d'`image`/`url` sur les cartes (chemin `mainPhotoNormal` relatif sans base connue / jamais inventer de lien)… **[PÉRIMÉ depuis l'addendum `fix-hotel-photos` ci-dessous — la base `static.dayuse.com` est désormais résolue, `image_urls` posé sur toutes les cartes.]** Pas d'`url` de booking sur les cartes — le carousel affiche nom/prix/étoiles/note/créneau/photo.
- Seul `city` remonte au profil (via géocode `last_city`) ; budget/timeslot du tour ne sont pas encore réémis en `profile_delta` — extension future. **[Partiellement clos en S10 : les `amenities` appliquées sont désormais réémises et ré-apprises par le concierge.]**
- `find_hotel_by_name` : stashé (une carte possible) mais non tronqué (payload déjà petit).
- Latence TOTALE du tour ~11 s (triage + feuille ~5 s + synthèse ~5 s) : sous les budgets par-dépendance (feuille 10 s), pas de budget total ; acceptable. La feuille fait 3 appels LLM (géocode-décision + search-décision + final) — structurel à l'`LlmAgent`, la troncature a supprimé le facteur bloquant (le payload).

## ⏱ État au 2026-07-20 — S9 terminée (façade publique `/v3/chat` iso-contrat + SSE + conversation_logs)

**Fait (branche `s9-facade`, séquentielle sur S8 mergée — pas de worktree, S9 pas lancée en ∥)** :
- **`facade.py` (module neuf, zone façade)** — la surface HTTP publique du concierge, montée sur le **MÊME app Starlette** que la surface A2A (`serve.py`) :
  - `POST /v3/chat` (JSON iso-contrat), `POST /v3/chat/stream` (SSE), `POST /v3/chat/session/reset` (204).
  - **Iso-contrat en FORME, pas en sémantique — décision de session assumée** (mode phase « contrat = zone à jugement »). Le contrat golden d'agent-usa est capturé en clés/types (les 18 clés toujours présentes : `message`/`response`/`context` (alias legacy), `hotels`, `suggestions`, `session_id`/`conversation_id`, `response_language`, `state`, `ready_to_search`, `requires_clarification`, `profile_status`, `active_filters`, `market`/`market_country`/`entry_market_country`/`search_country`, `turn_id`), gelées dans `facade.CONTRACT_KEYS`. Le spine B2C n'a NI intake staged, NI market engine, NI langues es/it → reproduire le *comportement* d'agent-usa (clarification espagnole, staged workflow) est structurellement impossible et hors design. Chaque champ sans équivalent est **mappé depuis l'état réel du profil** ou reçoit un **défaut honnête documenté** (`build_chat_payload`, un commentaire par champ). Les clés conditionnelles d'agent-usa (`type`/`questions`/`booking_card`/`location_candidates`) ne sont PAS émises : le spine ne pose jamais de flag de clarification structuré (il répond ou dégrade honnêtement). **L'invariant RGPD/honnêteté (ne jamais inventer hôtel/prix/politique) est intact — ces booléens de contrôle ne sont pas de la donnée hôtelière.** → **à valider par Fabien (review = le gate) : fidélité de contrat acceptable pour la bascule frontend ?**
  - **`hotels`** = liste du marker `hotels` si non-vide, sinon `None` (ack/faq/dégradé → None ; search-avec-résultats/details/compare → liste). `ready_to_search = hotels is not None`. Distingue correctement faq (marker `hotels:[]` → None → `ready_to_search=false`, vérifié live) d'une vraie recherche. **Prix** : `priceEuro` (centimes EUR) → `€X.XX` via le formateur S7 (`_format_price_eur_cents`), cohérence garantie.
  - **Session** : id résolu cookie `du_chat_sid` → header `X-Client-Session-Id` → `session_id` du body (phase `M1` legacy) → nouveau uuid ; `SESSION_ID_PATTERN` iso-agent-usa. **L'id de session de la façade EST l'id de session ADK** (Runner `InMemoryRunner` get-or-create keyé dessus) → le profil Redis (clé `ctx.session.id`) porte la continuité inter-tours HTTP sans plomberie ajoutée. La façade ajoute **ZÉRO appel LLM** (elle ne fait que consommer le flux d'événements du spine — mêmes ≤ 3/tour).
  - **SSE** : `event: progress` (marqueur TTFT, immédiat) → `hotels` → `token` (chunks) → `done` (payload contrat complet). Le JSON non-streamé sert exactement le même payload — test `test_json_and_stream_agree_on_the_same_turn` verrouille l'égalité (hors `turn_id`).
- **Auth split (serve.py)** — décision de session : **deux régimes sur un app**. Routes A2A (`/`, carte) = bearer D7 inchangé (agent↔agent, fail-closed au boot) ; routes `/v3/*` = **API key interne** (`X-Internal-Api-Key`, env `CHAT_API_KEY`, `AUTH_BYPASS`) — le minimum demandé par la phase (OUT : « auth interne complète — reprendre le minimum : API key interne »). Composé par un petit dispatcher ASGI (`/v3/*` → app brut ; tout le reste + lifespan → gate D7). La *vérification* D7 reste consolidée dans `b2c_common.auth` (invariant intact — j'y ai touché à RIEN) ; seule la *composition* (quelles routes du concierge sont ouvertes) vit dans serve.py.
- **`conversation_log.py` (module neuf)** — `conversation_logs` Postgres : mêmes colonnes qu'agent-usa **+ `is_synthetic`** (détecté du header interne `X-Dayuse-Synthetic`). Row builder PUR + détection header (testés offline) ; persistance **best-effort, no-op sans `DATABASE_URL`** (posture `metrics_pg` S3) — jamais un 500 sur un tour réussi. C'est la SEULE table qui porte du contenu de message (par design analytics/export) — distincte des métriques (content-free, verrouillé).
- **`ProfileStore.delete()`** ajouté (profile_store.py) — nécessaire au reset de session (best-effort, dégrade comme get/set).
- **`pytest.ini`** : `tests` ajouté aux testpaths (additif) — sinon `pytest -q` de la CI raterait `tests/api/`. **`scripts/smoke_e2e.py --contract`** : aller-retour /v3/chat (ack + search, continuité via `X-Client-Session-Id`) + SSE progress-first. **README concierge** : section façade `/v3`, deux régimes d'identité, env (cookie/api-key/DATABASE_URL), et **RGPD rétention** réécrite (sessions Redis TTL + conversation_logs contenu+is_synthetic+rétention DB à poser + métriques content-free).
- **DoD exécutée verte** : `pytest tests/api -q` → **32 passed** (mapping pur + HTTP ack offline + search mocké + cookie/session/reset + auth + is_synthetic + ordre SSE) ; `pytest -q` (repo entier) → **384 passed** (352 S8 + 32) ; `ruff check .` OK ; `mypy agents libs` → **32 fichiers** (+2 : facade.py, conversation_log.py) ; `dayuse_guardrails.sh` OK. **Live (3 services up, .env réel, sans Redis/DATABASE_URL)** : `smoke_e2e.py --contract` **PASS** (ack 48 ms, search dégrade honnêtement à 11 s, SSE progress à **2 ms**) ; `curl -N .../v3/chat/stream` → `event: progress` d'abord puis `event: done` (payload contrat) ; **tour FAQ nominal live via /v3/chat** → 200, chemin triage→feuille→synthèse LLM complet, `ready_to_search=false` correct.

**Reste** :
- **Fidélité de contrat à valider par Fabien** (review = gate) : les champs staged-workflow (`ready_to_search`/`state`/`profile_status`/`market*`/`requires_clarification`) sont des défauts/dérivations honnêtes, PAS la sémantique agent-usa (impossible sur ce spine). Si le frontend lit un champ autrement, l'ajuster.
- **`conversation_logs` write live Postgres jamais exercé** (pas de `DATABASE_URL` en dev/CI — no-op, comme `metrics_pg` depuis S3) : à vérifier en S10/S11 avec un Postgres. **Rétention DB à POSER** (politique de purge/anonymisation) avant tout trafic réel — la table stocke du contenu brut, aucune purge auto n'est encore en place (documenté README).
- **`is_synthetic` posé UNIQUEMENT par le trafic qui passe par la façade HTTP** : la batterie S8 drive **in-process** (pas via HTTP, zone S8, pas touchée) donc ne pose PAS le header aujourd'hui — le mécanisme est prêt pour le shadow-run S10 (trafic HTTP synthétique) et tout futur harnais HTTP.
- **Latence feuille search ~11 s en live** → la façade dégrade honnêtement (budget 10 s respecté, message « je préfère ne rien inventer ») — pré-existant (S2/S4/S6, troncature payload), pas un défaut de façade. Un vrai tour search réussi via SSE (progress→hotels→tokens) est prouvé en **mocké** (`test_sse_search_streams_progress_hotels_tokens_done`), pas en live tant que la latence feuille n'est pas sous 10 s.
- **`InMemorySessionService`** (Runner de la façade) : l'historique d'événements ADK est perdu au restart du process ; le profil Redis (vraie continuité des guards) survit. Un `SessionService` durable serait un sujet S10/S11 si l'historique ADK doit persister.

**Pièges découverts en S9** :
- **`pytest.ini testpaths` n'incluait pas `tests/`** : la CI (`pytest -q`) aurait silencieusement RATÉ `tests/api/` (le DoD `pytest tests/api` le trouve par argument explicite, pas la CI) — `tests` ajouté aux testpaths.
- **Cookie `Secure` empêche le round-trip httpx sur http** : TestClient (et le smoke) sur http local ne renvoient pas un cookie `Secure` → continuité cassée en test. Défaut `CONCIERGE_SESSION_COOKIE_SECURE=true` (prod-safe) ; les tests posent `false`, le smoke `--contract` utilise `X-Client-Session-Id` (cookie-free) pour la continuité.
- **La feuille faq émet un marker `hotels` vide** (le spine émet `_hotels_event` après TOUT retour de feuille, search comme faq) : impossible de distinguer faq d'une recherche à 0 résultat par le seul marker → règle « liste non-vide sinon None » adoptée (empty→None) ; conséquence assumée : un search à 0 résultat mappe aussi `hotels=None`/`ready_to_search=false` (indistinguable de faq — nuance sans source côté spine, sans impact frontend : il n'y a rien à afficher dans les deux cas).
- **`Response.set_cookie(samesite=...)` typé `Literal["lax","strict","none"]` par mypy** : renvoyer une str échoue le typecheck ; `_cookie_samesite` renvoie désormais le littéral explicite (lowercase — `SameSite` est insensible à la casse RFC 6265bis, bascule invisible).
- **Import-binding du profil store** : agent.py ET facade.py lient `get_profile_store` à l'import ; en test il faut patcher les DEUX noms de module (`agent.get_profile_store` et `facade.get_profile_store`) vers le MÊME fakeredis, sinon la façade lit un store différent de celui que le spine a écrit (fait dans `tests/api/conftest.py`).

## ⏱ État au 2026-07-20 — S8 terminée (batterie conversationnelle live + release gate + baselines posées)

**Fait (branche `s8-batteries`, séquentielle sur S7 mergée, pas de worktree — S9 pas lancée en ∥ cette session)** :
- **Harness d'éval neuf, zone `evals/**` + `scripts/**` uniquement** (façade S9 jamais touchée) :
  - `evals/judge.py` — LLM-as-judge **via LiteLLM** (invariant projet — le juge d'agent-usa instanciait un client OpenAI mais l'appelait avec la shape Anthropic `client.messages.create`/`response.content[0].text`, bug latent corrigé ici). Rubrique **par scénario** (le champ `expected` de `evalset-v0.json`), PAS les 5 dimensions search-only d'agent-usa (la batterie couvre 8 familles, pas que la recherche). `temperature=0`, sortie JSON `{verdict, score 1-5, reasoning, red_flags}`, dégradation honnête (`error` verdict, jamais de crash). Modèle configurable `RELEASE_GATE_JUDGE_MODEL` (déf. `DAYUSE_MODEL`→`gpt-4o-mini`).
  - `evals/battery.py` — rejoue les 32 scénarios fixes (8 familles × 4, ordre de phase) **EN-PROCESS** via `InMemoryRunner(root_agent)` (pattern `measure_ttft_local.py`), une session ADK par scénario (continuité inter-tours). **Décision de conception assumée : in-process, PAS HTTP** — (1) le HTTP `/v3/chat`+SSE est la zone S9 (OUT), l'A2A in-process teste exactement le même spine ; (2) capture du budget propre (handler sur le logger `b2c_concierge.metrics`, parsing de `concierge_metric=turn ... llm_calls=N`, pas de scraping de fichier cross-process) ; (3) continuité de profil auto-contenue via un `ProfileStore` fakeredis injecté (aucun serveur Redis requis, orchestrateur-only par construction — les feuilles restent stateless). « Live » = vrais appels LLM (triage/synthèse/juge), pas « sur le réseau ».
  - `scripts/run_dynamic_conversation_regression.py` — CLI de la batterie (filtres `--families`/`--limit`), écrit un report JSON, imprime les taux par famille + la comptabilité budget. **Report only** — le verdict merge/don't-merge est le gate.
  - `scripts/run_release_gate.py` — **le gate** (orchestrateur, pas ré-implémenteur — modèle agent-usa). `--quick` = units (pytest) + budget (offline, CI-friendly) ; complet = + batterie live jugée. **Strictness 3 niveaux** : units (tolérant, `max_failed`) / **budget (ZÉRO tolérance, ship-blocking : tout tour > 3 LLM = rouge)** / conversation (live-LLM, `passed >= min_passed - tolerance(2)` — seules les BAISSES échouent). `evals/baselines.json` committé, réécrit UNIQUEMENT via `--update-baseline` (jamais pour rendre un run rouge vert ; le budget n'est jamais relâché). Exit 1 = don't merge.
  - `evals/tests/` (3 fichiers, **26 tests OFFLINE**, litellm mické, aucun réseau/clé) : parsing juge (fences/embedded/garbage), clamp/défauts, empty-answer sans appel LLM, panne juge = `error` ; parsing de la ligne budget, capture/drain du handler, agrégation par famille + over-budget ; logique de verdict du gate (units régression, budget ship-blocking, conversation floor/tolérance, quick skip). `pytest.ini` : `evals` ajouté à testpaths + `.` au pythonpath (additif). `.gitignore` : `evals/reports/` (baselines.json EST committé).
- **Baselines posées (live, `--update-baseline`, label `s08_baseline`)** : `units.max_failed=0`, `budget={cap 3, max_over_budget_turns 0}`, `conversation={min_passed 3, total 32, tolerance 2, judge gpt-4o-mini, by_family}`.
- **DoD exécutée verte** : `python scripts/run_release_gate.py --quick` → **PASS** (352 units) ; `python scripts/run_release_gate.py` (32 scénarios LIVE) → **PASS** — 3/32 jugés OK, **budget max 3 LLM/tour, 0 tour au-dessus du cap** (invariant dur vérifié sur les ~60 tours de la batterie), aucune régression vs baseline ; `pytest -q` → **352 passed** (326 S7 + 26 neufs) ; `ruff check .` OK ; `mypy agents libs` → 30 fichiers (inchangé — `evals/`+`scripts/` hors périmètre mypy, comme les scripts existants) ; `dayuse_guardrails.sh` OK.

**⚠️ Découverte live majeure — le taux 3/32 est HONNÊTE, pas un défaut du harness** :
- **`MAPBOX_ACCESS_TOKEN` était absent de `.env`** → le `geocode_location` de la feuille search échoue fail-closed (status=error, ms=0) pour TOUTE ville, Paris incluse → « service de géocodage non disponible » partout → baseline initiale **1/32**. **Fabien a ajouté le token en cours de session** → feuille redémarrée → baseline **3/32** (le géocodage marche : Modena passe de « géocodage indisponible » à « aucune offre pour la date »).
- Le reste du plancher bas est dominé par l'**inventaire ES staging partiel** : aucune offre day-use pour Modena/Fougères/Juvisy/Noisy-le-Grand/etc. (caveat S10 déjà documenté — la parité réelle exige l'ES **prod**). Les réponses sont des dégradations/clarifications HONNÊTES ; le juge les échoue correctement contre des attentes de famille qui présupposent un vrai inventaire. `empty_dead` monte à 3/4 (géocodage OK → « non couvert » honnête reconnu).
- **Latence feuille search désormais ~2-7 s** (dans le budget 10 s) — la dégradation ~10,5 s quasi systématique documentée en S2 n'est PLUS systématique (travail payload S4 + staging réactif). Un tour a frôlé 10,9 s (borderline) mais a abouti `ok`.

**Reste** :
- **Re-poser la baseline conversation en S10** contre l'ES **prod** (+ Mapbox réel) pour un plancher qualité SIGNIFIANT — aujourd'hui `min_passed=3` rend le check conversation quasi inerte (floor=1) ; **le gate budget est le vrai garde live** jusque-là. Le mécanisme (exit 1 sur régression) est prouvé, seules les données manquent.
- **Juge = `gpt-4o-mini`** (seules creds OpenAI dispo) — faible sur les attentes de famille nuancées en français ; un juge plus fort (swap `RELEASE_GATE_JUDGE_MODEL`) affinerait les verdicts, différé (coût + creds).
- **Floors par famille enregistrés mais informatifs** (pas gating) — pourraient devenir gating quand la baseline sera significative (S10).
- **Le gate complet est un outil d'éval local/gated** (exige OPENAI + feuilles up + Mapbox + staging) — seul `--quick` tourne dans le job CI bloquant (comme agent-usa : units en CI, batterie gated).
- **Ordre de merge si ∥ avec S9** : S8 d'abord, S9 rebase (consigne de phase).

**Pièges découverts en S8** :
- **La batterie in-process joue le rôle du concierge vers les feuilles** et doit envoyer le MÊME bearer D7 sortant que `run_local.sh` donne aux feuilles : `.env` n'a pas de `A2A_BEARER_TOKEN`, donc le harness doit reproduire le défaut `local-dev-token` de `run_local.sh` (fait dans le script) — sinon CHAQUE tour search/faq 401→dégrade silencieusement (trouvé en live au premier run).
- `run_local.sh` **ne hot-reload pas** (piège S7 re-confirmé) : après l'ajout de `MAPBOX_ACCESS_TOKEN` par Fabien, il a fallu `stop` puis redémarrer la feuille pour qu'elle le lise.
- **Mapbox absent = géocode fail-closed** (status=error, ms=0) → « géocodage indisponible » pour TOUTE ville, Paris incluse — c'est le signal qui distingue un trou de TOKEN d'un trou d'INVENTAIRE (« aucune offre pour la date »).
- `InMemoryRunner` logue un warning « App name mismatch » en pilotant `root_agent` chargé depuis un chemin (cosmétique, identique à `measure_ttft`) — pas un échec.
- Les grep/awk sur `.env` sont **bloqués par la protection secrets** de la session — lister les noms de clés avec `sed -E 's/=.*/=<set>/' .env` (sûr).

## ⏱ État au 2026-07-19 — S7 terminée (tools inline réels, guard R9, amenity claim verifier, named-hotel lookup) — **12/12 guards verts**

**Fait (branche `s7-tools-inline-r9`, séquentielle sur S6 mergée, pas de worktree)** :
- **`inline_tools.py` réécrit** : `get_hotel_details`/`compare_hotels`/`generate_booking_link` appellent pour de vrai MCP_B2C (`mcp==1.28.1`, `streamable_http_client` — pas l'alias `streamablehttp_client`, déprécié dans cette version — une session HTTP par appel via un `httpx.AsyncClient(headers=..., timeout=...)` explicite, pas de session persistante cross-tour : périmètre de cette phase = le câblage + les guards, pas une parade de latence supplémentaire). Budget unique `CONCIERGE_INLINE_MCP_TIMEOUT_SECONDS` (déf. 5 s), SANS retry, dégradation honnête (`{"ok": False, "error": ...}`, jamais d'exception) — même posture que `_run_leaf`.
- **Named-hotel lookup guard (item 4)** : `profile.py` gagne `last_results` (shortlist à l'écran, ≤5, posée par `record_search_shortlist` sur toute recherche non-vide — **le `_last_results` équivalent que S6 avait noté structurellement absent**, réintroduit ici sur demande explicite de la phase) + `resolve_hotel_reference`/`resolve_hotel_references` (fuzzy match tolérant une phrase entière autour du nom, via un fallback token-based en plus du substring direct). `inline_tools._resolve_hotel_id` résout d'abord dans la shortlist (zéro appel MCP), `find_hotel_by_name` ensuite — **jamais pour `compare_hotels`** (reste shortlist-only, périmètre de phase explicite : « travaillent sur la shortlist du tour »).
- **Bugs trouvés en testant contre le VRAI MCP_B2C staging (probe direct avant câblage)** : (1) `find_hotel_by_name` renvoie l'identité sous une clé `"hotel"` (`{"hotel": {"hotelId": ..., "name": ...}}`), pas à plat comme `get_hotel_details`/`compare_hotels` — corrigé (`hotel = data.get("hotel") or data`) ; (2) `find_hotel_by_name` ne tolère PAS une phrase entière autour du nom (« Book Villa Paris Orly for me » → `HotelNotFoundError`, « Villa Paris Orly » → match) — aucune extraction d'entité LLM dans ce spine, donc `_extract_hotel_name_candidate` (regex, strip des tournures « book »/« compare »/« tell me about »/« for me »/« please »/« merci »…) précède l'appel MCP ; (3) **le plus important** : un premier jet de `generate_booking_link` résolvait l'hôtel depuis le MESSAGE COURANT même à l'étape de confirmation — cassait sur un simple « yes » (aucun nom d'hôtel à résoudre) découvert en faisant tourner `smoke_e2e.py --booking` en vrai. Corrigé : l'étape de confirmation réutilise l'identité de l'offre stockée dans `profile.pending_booking` (jamais re-résolue depuis le message de confirmation), avec un contrôle anti-mismatch en défense en profondeur (si le message nomme explicitement un AUTRE hôtel de la shortlist que celui en attente, re-cote au lieu de confirmer l'ancien). Les 3 bugs n'auraient été visibles dans AUCUN test unitaire mocké — seul le probe direct + le smoke réel les a révélés.
- **Guard R9 / #12 (`generate_booking_link`)** : câblé, **fully deterministic, ZÉRO LLM** (`agent.py::_run_booking`) — décision de session : une confirmation de réservation est un flux de contrôle sensible, jamais délégué au jugement d'un LLM (cohérent avec l'invariant « tout le contrôle vit en Python »). Le flag `confirmed` réellement envoyé à MCP est dérivé de `profile.pending_booking` (état serveur), jamais de l'argument `user_confirmed` seul — vérifié en gardant `generate_booking_link` **stateless côté serveur** (probé en direct : un premier appel `confirmed=true` renvoie un vrai lien, sans mémoire d'un `confirmed=false` antérieur). `profile.pending_booking` (nouveau champ) + `is_booking_confirmation_signal` (nouveau guard pur, symétrique à P2 recovery-ack) désactivent le fast-path ack ET forcent le re-routage `ack`→`booking` sur un « oui » nu alors qu'une offre est en attente. Testé aux deux chemins + tentative de bypass à 3 niveaux : `test_inline_tools.py::TestGenerateBookingLinkR9` (6 tests, dont le bypass explicite et l'échec MCP qui garde l'offre confirmable), `test_spine.py::TestBookingGuardR9` (3 tests, à travers triage+routing réels), et **`scripts/smoke_e2e.py --booking`** (nouveau mode, 2 tours un seul contextId) — **PASS en vrai contre MCP_B2C staging** : cote sans lien puis lien de tracking réel après confirmation.
- **`details`/`compare` grounded par la synthèse existante** : décision de session actée — PAS de câblage de `tool_loop.py` (construit+testé en S6, prêt selon le HANDOFF précédent). Raison : quel(s) hôtel(s) une phrase désigne est entièrement résoluble en code (le guard named-hotel lookup ci-dessus) — aucune décision réelle à laisser à un LLM sur QUAND/QUEL tool appeler, contrairement à ce que `tool_loop.py` a été conçu pour permettre ; l'utiliser quand même aurait réintroduit une décision de routage côté LLM (contraire à l'invariant du spine). À la place : `agent.py::_run_inline_lookup` réutilise le pattern DÉJÀ existant de `_run_leaf` (appel déterministe côté code → `response={"results": [...]}` → même `_synthesize_with_guards` que search/faq, mêmes guards ground-truth + amenity + anti-loop). `tool_loop.py` reste construit, testé, **inutilisé** — documenté explicitement dans `agent.py` (pas un oubli). Budget : 2 appels LLM (triage + synthesis) si l'hôtel résout, 1 seul (triage) sinon (dégradation honnête, symétrique au leaf).
- **Amenity claim verifier (P7, complète le ground-truth block de S6)** : `amenity_synonyms.py` (table multilingue en/fr/es/it/de/pt/nl, portée d'agent-usa — données propriétaires Dayuse, pas une lib tierce) + `amenity_guard.py` (`amenity_claim_violations`/`apply_amenity_truthfulness`, portage comportemental des méthodes `AgentOrchestrator._amenity_claim_violations`/`_hedge_amenity_claims`/`_apply_amenity_truthfulness` — fonctions pures, pas de classe, hedge fr/en seulement car ce spine ne répond jamais dans les 5 autres langues du synonym table). Hedge le token en place (« Hot tub (not confirmed) »/« jacuzzi (non confirmé) ») au lieu d'une note ⚠️ en fin de message qui expédiait la fausse affirmation ET sa contradiction dans le même souffle. Câblé dans `_synthesize_with_guards` (agent.py), APRÈS l'anti-clarification-loop, contre EXACTEMENT les hôtels qui ont grounded le ground-truth block (`ground_truth.shortlist_hotels`, nouvelle fonction publique extraite pour être partagée) — s'applique donc uniformément à search ET aux nouveaux inline lookups. Corrections persistées dans `profile.amenity_claim_corrections` (nouveau champ), jamais réémises deux fois. 10 tests portés (`test_amenity_guard.py`).
- **P3 (conversion devise)** : décision UX actée comme « simple » par la phase — `priceEuro` (centimes EUR) toujours affiché converti en EUR (`€X.XX`), jamais dans la devise locale de l'hôtel : aucun signal de devise utilisateur n'existe nulle part dans ce profil aujourd'hui, donc la branche « devise du user si connue » ne peut structurellement jamais se déclencher — extension triviale si un tel signal apparaît un jour.
- **DoD exécutée verte** : `pytest -q` (repo entier) → **326 passed** (192 dans `agents/b2c_concierge`, +46 vs S6 : 53 `test_profile.py` [+15 named-hotel/booking-signal], 17 `test_inline_tools.py` [neuf], 10 `test_amenity_guard.py` [neuf], 27 `test_spine.py` [+4], 8 `test_routing.py` [stubs retirés]) ; `ruff check .` OK ; `mypy agents libs` → 30 fichiers source (+2 : `amenity_synonyms.py`, `amenity_guard.py`) ; `dayuse_guardrails.sh` OK ; **`python scripts/smoke_e2e.py`** (3 tours indépendants) PASS ; **`--conversation`** (4 tours) PASS ; **`--booking`** (nouveau, 2 tours un contextId) PASS **avec vraies creds `.env`** — cote réelle (Villa Paris Orly, €54.00, créneau 17h-23h) puis lien de tracking réel après confirmation, prouvant le guard R9 de bout en bout contre MCP_B2C staging (pas seulement en mocké). `details` vérifié en direct aussi (hors smoke, appel manuel) : réponse synthétisée correcte sur amenities réelles (Free WiFi, Spa…). `compare` non revérifié en LIVE via HTTP (Redis absent en dev local → `last_results` ne survit jamais entre 2 appels HTTP séparés, limitation déjà documentée depuis S5 — mais `compare_hotels` passe par EXACTEMENT le même `_run_inline_lookup` que `details`, déjà prouvé live, et ses propres formes de données MCP ont été vérifiées par probe direct + tests unitaires).

**Reste** :
- **Offre de booking = la première (la plus proche) systématiquement** : `generate_booking_link` ne gère pas encore la sélection parmi plusieurs créneaux/rate-plans d'un même hôtel (aucune résolution de date n'existe nulle part dans ce spine aujourd'hui — `profile` n'a pas de champ date, seulement des bornes horaires) — simplification pragmatique documentée, pas un oubli. Une vraie UX de sélection d'offre est un futur sujet produit, pas dans le périmètre guard-only de S7.
- **`compare_hotels` jamais vérifié en LIVE via une vraie requête HTTP bout-en-bout** (Redis absent en dev local — voir ci-dessus) : à revérifier dès qu'un Redis local tourne, ou en Ph3.3/S10.
- **Connexion MCP inline = une session par appel, pas persistante cross-tour** (contrairement au `McpToolset` des feuilles) : latence légèrement plus élevée par appel (handshake Streamable HTTP à chaque fois) — décision de simplicité assumée cette session ; à revisiter si la latence des tools inline devient un sujet produit mesuré.
- **`tool_loop.py` reste non câblé, par choix** (voir « Fait » ci-dessus) — construit et testé depuis S6, aucune famille actuelle n'en a besoin.
- S8 (batteries) peut démarrer : les 12 guards sont maintenant tous câblés et testés.

**Pièges découverts en S7** :
- `mcp==1.28.1` : `mcp.client.streamable_http.streamablehttp_client` est DÉPRÉCIÉ au profit de `streamable_http_client`, qui ne prend plus `headers`/`timeout` directement — il faut construire son propre `httpx.AsyncClient(headers=..., timeout=...)` et le passer en `http_client=`.
- `find_hotel_by_name` renvoie `{"hotel": {...}}` (imbriqué), alors que `get_hotel_details`/`compare_hotels` renvoient leurs champs hôtel à plat — asymétrie de contrat NON documentée dans les descriptions de tools (repérée seulement en appelant le VRAI serveur, jamais visible en lisant juste le schema JSON d'entrée).
- `find_hotel_by_name` ne tolère PAS une phrase autour du nom malgré sa description (« partial input and typos tolerated ») — cette tolérance ne couvre que des variations DU NOM lui-même, pas des mots supplémentaires autour.
- **Un test unitaire mocké avec les BONNES formes de données peut quand même rater un bug d'intégration** : les 3 bugs de cette session (clé `"hotel"` imbriquée, phrase à stripper, confirmation qui re-résout depuis « yes ») n'ont été trouvés qu'en faisant tourner `smoke_e2e.py --booking` contre le VRAI MCP_B2C, pas en mockant du premier coup — le mock, écrit avant d'avoir vu les vraies réponses, reproduisait mes propres hypothèses erronées. Le probe live AVANT d'écrire le code (fait pour les schemas) n'a pas suffi : il aurait fallu aussi probe une vraie séquence confirmed=false → confirmed=true AVANT d'écrire `generate_booking_link`, pas seulement les schemas d'entrée.
- `run_local.sh` ne recharge PAS le code à chaud (uvicorn sans `--reload`) : un fix appliqué pendant une session de dev local nécessite `bash scripts/run_local.sh stop` puis un redémarrage, sinon le smoke re-teste l'ancien bytecode importé — piège classique, re-découvert ici en pensant qu'un fix ne marchait pas alors que le serveur tournait encore sur l'ancien code.

## ⏱ État au 2026-07-19 — S6 terminée (synthèse streamée, ground-truth, anti-loop, recovery acks)

**Fait (branche `s6-synthese-sse`, S4+S5 déjà mergées dans `main` avant de démarrer, pas de worktree — session séquentielle)** :
- **Événements internes `progress` → `hotels` → tokens** (`agent.py`) : `progress` émis EN PREMIER, avant tout travail (TTFT mesuré < 300 ms en local — `scripts/measure_ttft_local.py`, ~2 ms réel) ; `hotels` émis dès le retour de la feuille. Marqueurs encodés en JSON préfixé `\x1f` (Unit Separator, pattern cs_copilot/knowledge_router de la fleet) dans un `Event(partial=True)`. Les chunks de synthèse streamés sont aussi `partial=True`. **Piège structurel exploité intentionnellement** : le runner ADK n'append JAMAIS en session un event `partial=True` (`runners.py`) — ce qui protège l'hypothèse S5 de `_attach_outgoing_datapart` (`ctx.session.events[-1]` doit rester le tour utilisateur) même si des markers sont émis avant l'appel feuille.
- **Synthèse « streamée »** : décision de conception assumée et documentée dans le code (`agent.py::_chunk_text` docstring) — la génération reste bufferisée (litellm.acompletion classique, PAS `stream=True`) puis rejouée en chunks `partial=True` (découpage mot par mot). Raison : le guard anti-boucle doit pouvoir inspecter/regénérer AVANT tout envoi au client ; un token déjà émis en direct ne peut pas être retiré, contrairement à un texte bufferisé. Le contrat observable (chunks progressifs) est respecté à l'identique pour la façade S9 — rien à refaire côté contrat, juste noté si une vraie latence per-token devient un jour un besoin produit.
- **Ground-truth block** (`ground_truth.py`, module neuf, pur) : `shortlist_ground_truth_block(response, profile)` — ≤5 hôtels (`MAX_HOTELS`), amenities plafonnées à 8/hôtel (`MAX_AMENITIES`), phrase explicite « does NOT replace tool calls », note « ZERO results » quand `consecutive_empty_searches > 0` sans résultat au tour courant. **Adapté, pas porté verbatim** depuis `AgentOrchestrator._shortlist_ground_truth_block` d'agent-usa : ce spine n'a PAS de `last_results` persistant façon agent-usa (aucun champ équivalent dans `SessionProfile`) — donc le cas « shortlist obsolète affichée alors que l'écran est vide » qu'agent-usa doit gérer est structurellement impossible ici (chaque tour ne voit QUE ses propres résultats). 12 tests neufs (`test_ground_truth.py`).
- **Guard anti-clarification-loop (P10)** : `profile.extract_final_question`/`profile.questions_equivalent` (pures, Redis/LLM-free) détectent une question finale répétée vs le nouveau champ persisté `profile.last_clarifying_question`. Orchestration dans `agent.py::_synthesize_with_guards` : 1 retry borné avec directive « DO NOT ASK » injectée dans le system prompt ; si la 2e tentative boucle encore, strip déterministe (code, jamais LLM) de la question répétée — jamais de 3e tentative, jamais de boucle complète relancée. Le retry ne consomme PAS un slot de budget supplémentaire : `budget.charge("synthesis")` reste appelé UNE fois, le retry est un détail interne de ce slot (même principe que les 0-1 appels internes de la feuille comptés comme UN slot `leaf_llm`). Testé à la fois en pur (profile.py) et à travers le spine (`test_spine.py::TestAntiClarificationLoopGuard`, 3 tests : retry réussi, boucle persistante → strip, question neuve → pas de retry).
- **Guard recovery-ack (P2)** : `SessionProfile.last_suggestions` (champ neuf, listes localisées FR/EN code-owned posées par `record_search_outcome` quand un tour de recherche renvoie 0 résultat, effacées dès qu'un résultat revient) + `profile.is_search_refinement_signal(message, profile)` combinant (a) affirmatif nu (« ok »/« sure »/« oui »…) alors que `consecutive_empty_searches > 0` — désactive le fast-path ack ET force le re-routage `ack`→`search` même si le triage LLM classe la réponse « ack » —, (b) correspondance verbatim (insensible à la casse) avec `last_suggestions`. **Jamais de regex sur la prose** de la synthèse (celle-ci est maintenant streamée/écrite par le LLM, donc pas une cible stable) — contrairement à l'approche prose-scanning plus ancienne d'agent-usa, écartée délibérément (le texte de la spec de phase le demandait explicitement). Testé en pur (profile.py) et à travers le spine (`test_spine.py::TestRecoveryAck`, 4 tests, dont un qui vérifie qu'une simple salutation après une série vide reste un ack normal).
- **`auto_widen_disclosure` enfin surfacé** (item « Reste » laissé par S5) : `_synthesize_with_guards` lit le flag posé par `maybe_auto_widen` (S5), l'injecte dans le prompt de synthèse (`AUTO_WIDEN: …`), puis le CLEAR immédiatement — surfacé une seule fois, jamais silencieux, jamais répété sur un tour suivant. `test_spine_profile.py::TestAutoWidenThroughTheSpine` mis à jour en conséquence (l'assertion devient `auto_widen_disclosure is None` juste après le tour qui widen, puisque CE tour l'a déjà consommé) + assertion neuve que le prompt de synthèse contient bien la note « 100.0 to 150.0 ».
- **i18n de sortie** renforcé explicitement dans `_SYNTHESIS_INSTRUCTION` (« even when the OUTCOME text is in a different language ») — le comportement existait déjà depuis S2 (marqueur LANG), pas un guard neuf : juste la reconnaissance explicite du contrat MCP→EN / réponse→langue utilisateur, avec la note qui l'accompagne dans le prompt.
- **Mini tool-loop borné (≤2 itérations)** : `tool_loop.py` (module neuf, générique, `run_bounded_tool_loop`) — au-delà de 2 rounds exécutés, force un appel `tool_choice="none"` plutôt qu'un 3e round (jamais de boucle complète relancée). **Décision actée avec Fabien en session** (question posée explicitement sur le périmètre) : construit et testé en **STANDALONE uniquement** (6 tests, `test_tool_loop.py`, contre les stubs `inline_tools` actuels) — **PAS câblé** dans `routing.py`/`agent.py` cette session : les familles `details`/`compare` restent des templates instantanés zéro-LLM (S2, inchangé). Le câblage réel (vrais tools MCP + décision de QUAND l'offrir en synthèse) est le travail de S7.
- **DoD exécutée verte** : `pytest -q` (repo entier) → **280 passed** (146 dans `agents/b2c_concierge` : 21 `test_spine.py`, 7 `test_spine_profile.py`, 38 `test_profile.py`, 12 `test_ground_truth.py`, 6 `test_tool_loop.py`, + le reste inchangé) ; `python scripts/measure_ttft_local.py` → **~2 ms** (cible < 300 ms) ; `python scripts/smoke_e2e.py` (3 tours indépendants, services locaux réels démarrés) → PASS ; **`python scripts/smoke_e2e.py --conversation`** (neuf, 4 tours PARTAGEANT le même `contextId` A2A : ack/search/« ok »/faq) → PASS, `contextId` vérifié IDENTIQUE sur les 4 réponses (continuité de session prouvée, pas juste « réponse non vide ») ; `ruff check .` OK ; `mypy agents libs` → 28 fichiers source (+3 vs S5 : `ground_truth.py`, `tool_loop.py`, `agent.py` réécrit) ; `dayuse_guardrails.sh` OK.

**Reste** :
- **Mini tool-loop pas câblé** (décision de session, voir ci-dessus) : `tool_loop.py` prêt et testé, mais `details`/`compare` répondent toujours par template zéro-LLM — S7 décide QUAND l'offrir en synthèse et branche les vrais tools MCP (`get_hotel_details`/`compare_hotels`), jamais `generate_booking_link` (R9, guard n°12, aussi S7).
- **Streaming = buffer-puis-chunks, pas un vrai `stream=True` litellm** (voir « décision assumée » ci-dessus) : si une vraie latence per-token devient un besoin produit (ex. réponses de synthèse très longues), il faudra soit accepter qu'un token déjà streamé ne peut jamais être retiré (donc revoir la sémantique du guard anti-boucle), soit garder cette architecture. Sans impact sur S9 : le contrat observable (progress→hotels→tokens) ne change pas selon l'implémentation interne.
- **Amenity claim verifier** : hors périmètre S6 (assigné à S7 dans `SESSIONS-CLAUDE-CODE.md`) — `_apply_amenity_truthfulness`/`_amenity_claim_violations` d'agent-usa restent à porter.
- **Guard n°12 (R9, `generate_booking_link`)** : toujours pas câblé (S7).
- **L'event `hotels` dépend de la feuille search qui émette réellement un `results` structuré** : comme documenté depuis S4/S5, `hotel_search_agent` ne construit PAS encore de vraie `SearchResponse` DataPart (instruction texte seulement, pas de pont pydantic) — en usage réel aujourd'hui, l'event `hotels` sera souvent `{"event":"hotels","hotels":[]}` tant que ce pont n'est pas posé. Rien à faire côté S6 : item déjà connu, pas nouveau.
- Le smoke `--conversation` en local (sans creds MCP) : le tour « ok » ne déclenche PAS concrètement le guard recovery-ack car la recherche précédente a ÉCHOUÉ (dégradation honnête), pas renvoyé 0 résultat — `consecutive_empty_searches` n'est incrémenté que sur un succès à 0 résultat, jamais sur un échec de feuille. Le comportement déterministe du guard reste vérifié par pytest (`TestRecoveryAck`) ; le smoke sert la preuve de continuité de session (`contextId`), pas la couverture du guard.

**Pièges découverts en S6** :
- `Event.partial=True` n'est JAMAIS persisté en session par le runner ADK (`runners.py`, plusieurs points identiques : `if event.partial is not True: append_event(...)`) — c'est CE mécanisme qui rend les marqueurs `progress`/`hotels` sûrs à émettre avant l'appel feuille sans corrompre l'hypothèse S5 sur `ctx.session.events[-1]`. `Event.is_final_response()` s'appuie aussi sur `not self.partial`.
- Le convertisseur A2A (`google.adk.a2a.converters.from_adk_event.convert_event_to_a2a_events`) accumule les chunks `partial=True` dans un artefact A2A qui grossit (`append=True`), puis l'event final NON-partial le REMPLACE (`append=False` sur la transition partial→non-partial — un nouveau snapshot complet, pas un ajout) : le texte final complet porté par l'event terminal n'est donc PAS une duplication côté client A2A correctement écrit. Piège inverse côté TESTS : `test_spine.py`/`test_spine_profile.py` pilotent le runner ADK brut (pas la conversion A2A) — leurs helpers `_drive`/`_run_turn` concaténaient naïvement TOUS les events avant cette session ; corrigés pour ne lire QUE l'event terminal non-partial (sinon double-comptage garanti dès qu'un chunk est streamé).
- `redis` n'était plus installé dans `.venv` en tout début de session (désynchronisé de `requirements.txt`, cause inconnue) — `uv pip install …` (commande du CLAUDE.md) a resynchronisé sans drame ; a aussi fait remonter `litellm` à 1.90.2 (cohérent avec S3/S4, rien de neuf).
- Le champ A2A `contextId` (PAS `sessionId`, qui n'existe pas côté A2A) est ce que `google.adk.a2a.converters.request_converter` utilise pour dériver À LA FOIS `session_id` et `user_id` (`A2A_USER_{context_id}`) — c'est le SEUL levier pour qu'un smoke (ou un vrai client) multi-tours partage la même session/profil Redis ; à réutiliser tel quel en S9 pour la façade `/v3/chat`.

## ⏱ État au 2026-07-17 — S5 terminée (profil de session + guards profil, orchestrateur)

**Fait (branche `s5-profil-session`, worktree `../AgentB2C-s5`, ∥ avec S4 sur `s4-guards-geo`)** :
- **`profile.py`** : `SessionProfile` typé (city, state_anchor/country_anchor, budget_max/budget_request_source, timeslot/timeslot_start/timeslot_end/timeslot_request_source/timeslot_mode, amenities, language, consecutive_empty_searches, auto_widen_disclosure) + guards purs (zéro dépendance Redis, testables seuls) :
  - **budget integrity (P1)** : `apply_profile_delta` marque `budget_request_source=explicit` dès que le message du tour EST le nombre nu (« 180 », « $40 ») — **override le classement renvoyé par la feuille**, jamais l'inverse (le bug prod était une feuille/LLM qui mésétiquette une réponse explicite) ; `maybe_auto_widen` (×1,5 après 2 recherches vides consécutives, budgets non-explicites seulement) pose `auto_widen_disclosure={from,to}` — **à surfacer par la synthèse (S06)**, pas fait ici.
  - **timeslot sanitization (P6)** : `_split_one_sided_clock`/`_normalize_timeslot` salvage un horaire à borne unique corrompu (« 15:00- », « -09:00 », « 15:00_ ») en `timeslot_start`/`timeslot_end` — jamais persisté tel quel ; garde anti-inversion (`_mentions_explicit_time`) : une borne ancrée (ex. fin à 09:00) n'est jamais réécrite par une ré-extraction d'un tour SANS nouvelle mention d'heure.
  - **ancres géo** : `state_anchor`/`country_anchor` effacées sur changement de ville explicite, sauf si le même delta fournit une ancre fraîche (résolution dans le même tour).
  - Comportement **porté** depuis `agent-usa/tests/unit/application/test_audit_fixes_2026_06.py` (sections budget integrity + timeslot sanitization, ~10 tests) — PAS le code (architecture entièrement différente) ; réécrit en 23 tests neufs dans `tests/test_profile.py` contre notre propre schéma.
- **`profile_store.py`** : Redis async (`redis.asyncio`), une clé JSON par session (`b2c_concierge:profile:<session_id>`), **TTL glissant** `CONCIERGE_PROFILE_TTL_SECONDS` (déf. 1800 s), rafraîchi à chaque écriture. **Dégradation honnête si Redis est injoignable** (même posture qu'un échec de feuille : `get` renvoie un profil vierge, `set` avale l'erreur en warning — jamais de crash du tour) — testé (mock client qui raise) à la fois unitairement et à travers tout le spine (`test_spine_profile.py::TestProfileStoreOutageDegradesHonestly`).
- **`a2a_datapart.py`** : encode/decode du mécanisme identifié en S2/S3 (`inline_data` `<a2a_datapart_json>` du part converter ADK — `google.adk.a2a.converters.part_converter`) — seul point d'injection possible, `RemoteA2aAgent` construit son message sortant uniquement depuis `ctx.session.events`. Round-trip vérifié à travers les VRAIS convertisseurs ADK (`convert_genai_part_to_a2a_part`/`convert_a2a_part_to_genai_part`), pas seulement nos propres fonctions.
- **`agent.py`** : `_run_leaf` attache `{query_params: {}, profile_in: profile.to_dict()}` en DataPart sur l'événement utilisateur courant AVANT l'appel de la leg, puis décode le premier DataPart trouvé dans les événements de réponse (`profile_delta`, `results` pour la feuille search). `_run_async_impl` charge le profil (Redis) avant l'appel feuille, applique le delta + les guards + `record_search_outcome`/`maybe_auto_widen` après, persiste, PUIS synthétise. `query_params` reste `{}` par construction (son schéma métier est le contrat de S4, pas de S5).
- **Test « feuille stateless »** (`tests/test_stateless_leaves.py`) : aucune occurrence de `redis` (case-sensitive, comme le grep du DoD — les deux feuilles documentent DÉJÀ l'invariant en prose avec un « Redis » capitalisé, qui doit continuer à passer) sous `agents/hotel_search_agent` ou `agents/faq_agent`.
- **DoD exécutée verte, RE-EXÉCUTÉE post-rebase sur `main` (avec S4 mergée)** : `pytest agents/b2c_concierge -q` → **101 passed** ; grep redis statique OK ; `pytest -q` (suite complète, 3 agents + libs, avec les 63 tests géo de S4) → **235 passed** ; `dayuse_guardrails.sh` OK ; `ruff check .` OK ; `mypy agents libs` → 26 fichiers source (+3 vs S3 pour S5 : profile.py, profile_store.py, a2a_datapart.py ; +1 vs S4 pour ses nouveaux modules géo).

**⚠️ Écart de zone (noté, pas bloquant)** : `requirements-dev.txt` (racine, hors `agents/b2c_concierge/**`) a reçu UNE ligne additive (`fakeredis~=2.36`, pour `test_profile_store.py` — offline, aucun Redis réel requis pour la suite). Fichier dev-only partagé par les 3 agents (comme `pytest.ini`/`ruff.toml`/`mypy.ini`), pas de contenu S4 dedans, ajout pur (aucune ligne retirée/réordonnée) : risque de conflit quasi nul au rebase, mais signalé explicitly comme demandé par la consigne de session.

**⚠️ Écart de nommage découvert au rebase (post-merge S4, à trancher dans une session ultérieure)** : le bloc S4 ci-dessous révèle que `geocode_location` (feuille search) attend des paramètres explicites `profile_state_context`/`profile_location_hint` recopiés par le modèle depuis `profile_in` — alors que le schéma `SessionProfile` posé ici nomme ces champs `state_anchor`/`country_anchor`. Le pont propre `profile_in → ToolContext.state → paramètres du tool` n'existe ENCORE NI côté feuille NI côté orchestrateur (S4 confirme : `root_agent` lit `query_params`/`profile_in` via l'instruction texte, pas via un pont pydantic) — donc AUCUNE régression aujourd'hui, mais la convention de nommage entre les deux feuilles devra être alignée (renommer un côté, ou introduire un mapping explicite) avant que le DataPart ne serve réellement à qualifier le géocodage.

**Reste** :
- **S06 (synthèse)** doit surfacer `auto_widen_disclosure` à l'utilisateur quand il est posé (aujourd'hui le flag existe dans le profil mais rien ne le lit côté réponse) — sinon le guard est silencieux.
- **Dépendance avec S04** : `profile_delta`/`results` ne sont QUE décodés si la feuille search émet réellement un DataPart réponse dans ce même format `{query_params, profile_in} → {results, profile_delta, diagnostics}` (contrat déjà figé dans `hotel_search_agent/contract.py` depuis S1). Tant que S4 n'émet pas encore ce DataPart côté feuille, le profil reste silencieusement vide en usage réel (dégradation honnête déjà testée) — **rien à faire côté S5**, c'est le contrat qui fait le lien.
- **Alignement de schéma avec S4** (voir écart de nommage ci-dessus) : `state_anchor`/`country_anchor` (S5) vs `profile_state_context`/`profile_location_hint` (paramètres `geocode_location`, S4) — à réconcilier avant que le géocodage ne consomme réellement l'ancre du profil.
- **Local dev** : `scripts/run_local.sh`/`smoke_e2e.py` n'ont PAS été mis à jour pour exiger un Redis local — `CONCIERGE_REDIS_URL` par défaut pointe `redis://localhost:6379/0` ; sans Redis qui tourne, le profil dégrade honnêtement (get/set no-op loggé) mais AUCUNE continuité de profil n'est réellement exercée en smoke local tant qu'un Redis (ou `docker run -p 6379:6379 redis`) n'est pas lancé à côté. À faire si un smoke E2E avec continuité de profil est voulu.
- Rebasé sur `main` fraîche (post-merge PR #5 S4) le 2026-07-17 — DoD complet réexécutée post-rebase (voir en tête de ce bloc). Prêt pour la MR.

**Pièges découverts en S5** :
- `RemoteA2aAgent._construct_message_parts_from_session` construit le message A2A sortant EXCLUSIVEMENT depuis `ctx.session.events` (aucun hook d'injection dédié) : le seul moyen d'ajouter un DataPart sortant est de muter `ctx.session.events[-1].content.parts` AVANT `leg.run_async(ctx)` — c'est ce que fait `_attach_outgoing_datapart`.
- Piège de test : `ctx.session.events[-1]` change de sens PENDANT le tour — le runner ADK ajoute l'événement de réponse finale à la session APRÈS le passage dans la leg ; inspecter `ctx.session.events[-1]` une fois le tour terminé pointe sur la réponse, pas sur le tour utilisateur envoyé à la feuille. Les tests d'intégration capturent un SNAPSHOT des parts au moment de `leg.run_async(ctx)`, pas une référence tardive à `ctx`.
- Le grep `redis` du DoD (et notre test statique miroir) est délibérément **case-sensitive** : les deux feuilles documentent déjà l'invariant en prose avec « Redis » capitalisé — un grep insensible à la casse aurait de faux positifs sur leur propre documentation.
- `google-adk[eval]==2.4.0` installé seul (sans le reste des requirements) casse la résolution de dépendances avec `litellm==1.90.2` pinné (conflit `google-cloud-aiplatform[evaluation]`, versions PyPI ayant bougé depuis S3) — non lié à S5, `google-adk[a2a]==2.4.0` (sans l'extra eval) suffit pour `pytest`/DoD ; installer l'extra eval séparément si besoin de rejouer `adk eval`.

## ⏱ État au 2026-07-17 — S4 terminée (feuille search : Mapbox réel + 3 guards géo + circuit-breaker MCP)

**Fait (branche `s4-guards-geo`, worktree dédié, ∥ avec S5 sur l'orchestrateur — zone touchée : `agents/hotel_search_agent/**` UNIQUEMENT)** :
- **`geo_guards.py`** : les 3 guards portés depuis `agent-usa/tests/unit/application/test_audit_fixes_2026_06.py` (sections geocode echo-back + state hints + ZIP anchor, generic place words, state anchoring) : `extract_state_hint_from_text`, `resolve_state_hint`, `geocode_echo_matches` (endonymes ß/ø/æ, alias courts, script non-latin, folding Saint/St), `select_us_postal_anchor`, `is_generic_location_token` / `demote_generic_city`, `anchor_state_context`. **26/26 tests de spec portés** (`tests/test_geo_guards.py`, 22 verbatim + 4 adaptés) + 2 tests de couverture supplémentaires = 28 tests dans ce fichier. **Adaptation assumée (pas un affaiblissement)** : agent-usa mute un `Conversation.preferences` long-lived ; cette feuille est stateless (B3) — la démotion générique et l'ancre d'état sont re-testées sur les fonctions pures dict-in/dict-out réellement utilisées ici (`demote_generic_city`, `anchor_state_context`), même scénario/même verdict, sans `Conversation`. **Hors périmètre volontaire** (ni nommé dans la phase, ni porté) : country-anchoring (`last_country_context`), currency-prior (`_geo_country_preferences`), homonyme ambigu (`ambiguous_homonym_pending`) — même fichier de spec agent-usa, audits différents, pas les 3 guards de cette phase.
- **`mapbox_client.py`** : client Mapbox Geocoding API v6 réel (`httpx.Client`, `limit=1`), budget 1,5 s + 1 retry (single-owner rule), cache mémoire borné (`OrderedDict`, éviction FIFO). 12 tests mockés (`httpx.MockTransport`, zéro réseau réel) : parsing, timeout+retry, 5xx, cache positif/négatif, bornage.
- **`geocode_tool.py`** : tool code-owned `geocode_location` (FunctionTool ADK, schéma généré sans erreur — vérifié) composant démotion → résolution d'état → appel Mapbox → validation echo-back → mise à jour de l'ancre ; **ne raise JAMAIS** — tout rejet devient `{"ok": False, "error": ..., "diagnostics": {...}}`. Câblé dans `root_agent.tools` (2e tool, après le McpToolset) ; instruction mise à jour (geocode AVANT `search_offers`, jamais de coordonnées inventées). 8 tests avec un faux client.
- **`mcp_guard.py`** : `CircuitBreaker` de `resilience.py` (S1, jusqu'ici non branché) posé sur `search_offers`/`find_hotel_by_name` via `before_tool_callback`/`after_tool_callback`/`on_tool_error_callback` — 3 échecs consécutifs → court-circuit instantané (`mcp_circuit_open`, zéro appel réseau, zéro exception), reset après 30 s. Classifieur de réponse MCP (isError/`error`/`structuredContent.ok=False`/`ok=False`), avec exemption explicite du stop `TOOL BUDGET` (pas un échec MCP). 15 tests (horloge fake, pas de sleep).
- **Bug trouvé en cours de câblage** : `resolve_state_hint` héritait de l'agent-usa d'origine un `country_code != "US"` qui traitait `None` (aucun signal pays) comme un pays non-US *résolu* et coupait la résolution texte à tort. Corrigé (`if country_code and country_code != "US" and country_resolved`) — sans régression sur les tests portés (qui passent toujours `"US"`/`"ES"` explicitement, jamais `None`).
- **`agent.py`** : `MAX_TOOL_CALLS` inchangé (2 = geocode + search, ou find_hotel_by_name seul) ; ordre des callbacks avant-tool = timing → budget → circuit MCP (premier non-None gagne, sémantique ADK). `README.md` + `requirements.txt` (pin explicite `httpx==0.28.1`, déjà tiré transitivement) mis à jour ; `.env.example` non touché (refusé par les permission settings, comme en S1/S2).
- **DoD exécutée verte** : `pytest agents/hotel_search_agent -q` → **96 passed** (63 nouveaux : 28 guards + 12 mapbox + 8 geocode_tool + 15 mcp_guard) ; `pytest -q` (repo entier) → **192 passed** ; `ruff check .` OK ; `mypy agents libs` OK ; `bash scripts/dayuse_guardrails.sh .` OK.
- **Addendum post-review (même jour, PR #5 ouverte, question de Fabien)** : `geo_guards.py` sourçait à la main le référentiel générique — table des 50 états US et folding des ligatures d'endonymes. Recherche faite (aucune lib géo utilisée nulle part dans l'écosystème Dayuse, y compris agent-usa qui hardcode pareil) → remplacé par `us==3.2.0` (unitedstates/python-us, CC0, exclut DC/territoires par défaut — vérifié 1:1 identique à l'ancien dict à la main) et `anyascii==0.3.3` (ISC, translittération Unicode→ASCII bien plus large que les 8 ligatures hardcodées, successeur d'Unidecode). Les listes réellement Dayuse-spécifiques (`_TEXT_UNSAFE_STATE_ABBREVS`, `_GENERIC_LOCATION_WORDS`, `_ECHO_NOISE_WORDS`, `STREET_SUFFIX_TOKENS`) restent en dur — jugement produit issu des audits prod, aucune lib ne les connaît. `usaddress` (parseur d'adresse probabiliste pour l'ancre ZIP) et `pycountry` (si les guards pays sont repris) évalués mais PAS adoptés maintenant — dépendance plus lourde/moins déterministe pour le premier, rien à remplacer aujourd'hui pour le second. Les 28 tests de `test_geo_guards.py` restent verts INCHANGÉS après le swap (même DoD que ci-dessus, re-exécuté).

**Reste** :
- L'enveloppe DataPart `SearchRequest`/`SearchResponse` (contract.py) n'est toujours PAS le mécanisme qui alimente réellement `root_agent` — l'agent lit toujours `query_params`/`profile_in` via l'instruction texte, pas via un pont pydantic. `geocode_location` accepte `profile_state_context`/`profile_location_hint` en paramètres explicites que le modèle doit recopier depuis ce qu'il voit de `profile_in` dans le prompt — le pontage propre (session → `ToolContext.state` → tool) reste à faire quand le profil de session (S5) sera posé côté orchestrateur.
- **Jamais testé contre le vrai Mapbox** (uniquement mocké) : `MAPBOX_ACCESS_TOKEN` à poser par Fabien avant tout smoke réel ; posture volontairement NON fail-closed (absent/vide → dégradation honnête, pas un crash au boot, à la différence du bearer D7).
- S5 (orchestrateur, ∥) : round-trip effectif de `profile_delta` → `profile_in` du tour suivant (le Redis de session lui appartient) ; c'est lui qui devra transmettre `profile_state_context`/`profile_location_hint` à cette feuille.
- Guards non portés dans cette session (voir ci-dessus) : country-anchoring / currency-prior / homonyme ambigu — à qualifier dans une session ultérieure si le besoin business se confirme.

**Pièges découverts en S4** :
- Le job CI `checks` (celui qui bloque) installe SANS `google-adk[eval]` — seul le job `eval` séparé l'installe (litellm y est downgradé à 1.85.x pour satisfaire `google-cloud-aiplatform[evaluation]`, sans effet sur `checks`). Reproduire le setup dev en incluant `google-adk[eval]` dans la MÊME commande `uv pip install` que les autres requirements est un résolveur insatisfiable (conflit `litellm` 1.90.2 vs <1.86.0) — installer sans cet extra pour tout ce qui n'est pas `adk eval`.
- `mypy` : réutiliser une variable de boucle for-unpacking (`for name, canonical in dict.items()`) puis la réassigner à un type `X | None` plus loin dans la même fonction fait échouer le typecheck même si la valeur est correcte à l'exécution — renommer la seconde variable.
- Ordre de vérification `_is_tool_failure` : le dict de court-circuit du tool-budget (`{"ok": False, "error": "TOOL BUDGET..."}）` a `ok=False` ET un `error` — le préfixe `TOOL BUDGET` doit être vérifié EN PREMIER (return anticipé), sinon le fallback `ok is False` le classe à tort comme un échec MCP et ouvre le breaker sur du contrôle de flux, pas une vraie panne.

## ⏱ État au 2026-07-17 — S3 terminée (socle transverse : lib commune, métriques, CI, éval)

**Fait (branche `s3-socle-transverse`, PR ouverte)** :
- **`dayuse_agent_common` en dépendance git PINNÉE** (mode d'install **acté avec Fabien** — décision de session) : `dayuse-agent-common @ git+ssh://…dayuse-agent-fleet.git@8071917…#subdirectory=libs/dayuse_agent_common` dans les requirements des 3 agents. Jamais de copie du code ; bump du SHA délibéré. ⚠️ repo fleet PRIVÉ : la CI et les builds d'image ont besoin d'un accès lecture (`FLEET_READ_TOKEN`, insteadOf https) — **secret à créer par Fabien sur le repo GitHub** ; wiring build Docker complet en S10/S11.
- **`libs/b2c_common`** (nouveau package interne, layout fleet, COPY dans les 3 Dockerfiles) : identité intérimaire D7 consolidée en UN point (`require_bearer_token` fail-closed + `BearerAuthMiddleware`) — la lib fleet ne vérifie AUCUN bearer entrant, le régime AgentB2C reste plus strict ; la bascule oidc-mtls (échéance S11) se fera dans ce seul module. **Verrou `dev-insecure`** : `test_no_dev_insecure_in_deploy_configs` échoue si la chaîne atteint Dockerfiles/workflows/manifests.
- **Métriques jour 1** : feuilles = `build_model()` (défaut B2C `gpt-4o-mini` conservé — ⚠️ le défaut de la lib est un slug OpenRouter) + callbacks lib (llm/tool timing + erreurs) + `make_tool_budget_callback(2)` ; PAS de `switch_model_callback` (trafic public). Spine = `enqueue_metric_event` sur `turn`/`leaf_call`/`llm_call` (phase=triage|synthesis, tokens+coût). **Noms d'agents renommés `b2c_hotel_search`/`b2c_faq`** (le nom EST le label `service` des métriques — dashes de la spec → underscores, contrainte identifiant ADK ; cartes + tests alignés, l'orchestrateur résout par URL donc zéro impact A2A). **Verrou RGPD étendu aux événements** (`test_metric_events_never_contain_message_content`) en plus des logs.
- **CI GitHub Actions** (`.github/workflows/ci.yml` — transposition du plan GitLab au host réel du repo, décision S1) : ruff + mypy + pytest + guardrails (bloquants), job `adk eval` non bloquant (skippé sans `OPENAI_API_KEY`). Configs : `ruff.toml` (défauts, py312), `mypy.ini` (pragmatique, tests exclus — 3 packages `tests` homonymes).
- **Evalset ADK** : `scripts/convert_evalset.py` (rejouable, validé pydantic) → `evalset/evalset-v0.adk.json` (32 cas, 118 tours, multi-tours préservés ; la rubrique `expected` = référence du dernier tour) + `evalset/test_config.json` (ROUGE 0,1 — indicatif en attendant un juge LLM).
- **DoD exécutée verte** : `ruff check .` OK ; `mypy agents libs` OK (19 fichiers — `mypy src/` adapté au layout réel) ; `pytest -q` → **129 passed** ; guardrails OK ; **`adk eval` complet : 32 cas exécutés, 2 passed / 30 failed** (score libre assumé : squelette + rubrique≠verbatim) ; **Postgres jetable docker** : `SELECT service, count(*) FROM llm_metric_events GROUP BY 1` → `b2c_concierge=8, b2c_faq=3, b2c_hotel_search=3` sur un smoke (feuilles via callbacks lib, spine via enqueues) + **0 row contenant du contenu de message** (vérifié en SQL).

**Reste** :
- Fabien : review + merge PR S3 ; créer le secret **`FLEET_READ_TOKEN`** (PAT lecture fleet) et `OPENAI_API_KEY` sur le repo GitHub — sans le premier, le job CI `checks` échoue à l'install.
- S4 (feuille search) : Mapbox + guards géo/date — l'eval montre exactement pourquoi (30/32 échecs dont la latence feuille > 10 s et l'absence de géocodage/ancrage date).
- `GET /model` (serving.py de la lib) volontairement NON branché : sa résolution (`resolved_model()`) divergerait du défaut B2C `gpt-4o-mini` — à brancher quand `DAYUSE_MODEL` sera posé partout en env de déploiement.

**Pièges découverts en S3** :
- `mypy` ne tolère pas les 3 packages `tests` homonymes (importlib pytest oui) → tests exclus du typecheck, source seulement.
- `adk eval` exige l'extra **`google-adk[eval]`** (rouge-score…) — absent des requirements des agents, installé par la CI eval et le setup dev.
- L'historique d'eval s'écrit dans `agents/…/.adk/eval_history/` → gitignoré (`**/.adk/`).
- Le process `adk eval` configure le root logging → les lignes `concierge_metric=` sortent en double dans ses logs (handler dédié + propagation) — cosmétique, pas un double comptage en base.

## ⏱ État au 2026-07-17 (suite) — post-merge S2 : MCP_B2C complet + retour au Bearer standard

**Fait (branche `fix-mcp-bearer-standard`, PR ouverte)** :
- ⚠️ **La PR #2 a été mergée à `b36a2e0`, AVANT les 2 derniers commits de la branche S2** (`d6dab14` compteur LLM visible au runtime, `0137c93` contrat MCP + date smoke + drain run_local) — ils n'étaient PAS dans main. **Cherry-pickés dans cette PR.** Leçon : après un push tardif sur une PR déjà mergée, GitHub ne re-merge rien et ne prévient pas.
- Côté MCP_B2C (fix de Fabien déployé le 2026-07-17, vérifié au probe) : **`Bearer <token>` accepté** (token brut toujours toléré en rétro-compat), et **les 6 tools sont exposés** (`get_faq_conditions` et `generate_booking_link` inclus). Les 2 feuilles sont **rebasculées sur le header Bearer standard** (RFC 6750) + tests/README alignés.
- `.env` : renommage `MCP_B2C_TOKEN` → `MCP_B2C_AUTH_TOKEN` fait par Fabien — plus aucun mapping nécessaire, `run_local.sh` + `smoke_e2e.py` tournent tels quels.

**Reste** : review + merge de cette PR, puis S3 (prompt dans `PROMPTS-SESSIONS.md`).

## ⏱ État au 2026-07-17 — S2 terminée (feuille faq-agent + orchestrateur b2c-concierge)

**Fait (branche `s2-faq-orchestrateur`, **PR #2 mergée le 2026-07-17** — mais voir bloc « suite » ci-dessus : les 2 derniers commits ont raté le merge)** :
- `agents/faq_agent/` : miroir exact de la feuille S1 (allowlist `["get_faq_conditions"]`, `FAQ_MCP_TIMEOUT_SECONDS` 5 s, bearer D7 fail-closed, carte non signée, Dockerfile :8102, README = D1 + parades latence + RGPD). ⚠️ côté serveur MCP_B2C, `get_faq_conditions` est **en review non mergé** : l'allowlist filtre à zéro tool en attendant, la feuille répond en le disant dans `diagnostics`.
- `agents/b2c_concierge/` : **spine code-owned** custom `BaseAgent` (pattern `cs_copilot`, PAS de LlmAgent+sub_agents) —
  - ack fast-path regex (0 LLM) → template ; **triage** 1 appel LLM éco `{family, language}` + **fallback regex** sur tout échec (aucun retry : LiteLLM est la seule couche de retry) ;
  - **table de routage EN CODE** (`routing.py`) : search/faq → `RemoteA2aAgent` (clients httpx **persistants** avec bearer D7 sortant par feuille ; **`asyncio.timeout` 10 s SANS retry** = le vrai plafond, le timeout httpx ne borne pas un stream) ; details/compare/booking → **stubs inline** (`inline_tools.py`, réponse template honnête, 0 LLM de plus ; le stub `generate_booking_link` ne produit AUCUN lien par construction = posture R9) ; ack → template ;
  - **dégradation honnête** (`templates.py`) : feuille injoignable → message qui le dit, zéro invention, pas de synthèse ;
  - **UNE synthèse** litellm par tour (squelette S6) ; échec → texte feuille servi verbatim (grounded) ;
  - **compteur LLM/tour** (`budget.py`) : cap 3, `LlmBudgetExceededError` au-delà ; test `test_spine.py::test_simple_search_turn_stays_within_llm_budget` échoue si > 3 ; métriques logs `b2c_concierge.metrics` **sans contenu de message** (verrouillé par `test_logs_never_contain_message_content`).
- **Restructuration nécessaire** : `serve.py` déplacé DANS chaque package (`<pkg>.serve:app`, Dockerfiles mis à jour) + `pytest --import-mode=importlib` + pythonpath des 3 agents — sans ça, collision du module `serve` entre les 3 services co-testés.
- `scripts/run_local.sh` : boote les 3 services (pids + logs `.run-logs/`, readiness = carte, `stop`) ; `scripts/smoke_e2e.py` : 3 tours (ack + search + faq) via l'orchestrateur.
- **DoD exécutée** : `pytest -q` → **110 passed** ; guardrails OK ; boot des 3 services OK ; **smoke PASS** — d'abord sans clé (dégradation honnête exercée de bout en bout), puis **avec `OPENAI_API_KEY` (.env ajouté par Fabien le 2026-07-17)** : chemin nominal LLM confirmé aux métriques runtime — ack `llm_calls=0` (6 ms), search et faq `llm_calls=3 phases=triage,leaf_llm,synthesis status=ok` (~6,8 s). ⚠️ `OPENAI_MODEL` (ajouté aussi) n'est lu par RIEN — le knob modèle est `DAYUSE_MODEL`.
- **MCP_B2C staging branché le 2026-07-17** (URL + token ajoutés par Fabien) — validé par probe direct : session OK, **vraies données** (`search_offers` Paris → NH Paris Gare de l'Est, 6 offres, payload 28 Ko). Découvertes de contrat, TOUTES vérifiées empiriquement :
  - ~~**Auth = token BRUT dans `Authorization`**~~ (résolu le 2026-07-17 : fix serveur déployé, Bearer standard accepté — voir bloc « suite ») ; renommage `.env` fait.
  - ~~Le staging n'expose que **4 tools**~~ (résolu : les 6 tools sont exposés depuis le redeploy du 2026-07-17).
  - `search_offers` **exige `lat`/`lon` numériques + `date`** — aucun géocodage serveur : le Mapbox de S4 est indispensable (aujourd'hui gpt-4o-mini fournit les coords de tête — les guards géo S4 rendront ça déterministe) ; « demain » sans date explicite part n'importe où (date anchoring S4 — le smoke épingle une date absolue).
- **Latence feuille search sur payload réel : ~10,5 s** (2 passes LLM internes obligatoires avec ADK — le modèle doit INGÉRER les 28 Ko — même avec l'instruction « top 5 compact » ajoutée) → **dépasse le budget 10 s de l'orchestrateur** → le tour search via concierge dégrade honnêtement de façon quasi systématique. Le budget 10 s est un invariant, on n'y touche PAS : la correction appartient à S4/S6 (troncature code-owned du payload tool AVANT le modèle, ground-truth ≤ 5, streaming). Preuve du chemin data : appel direct feuille = offres réelles compactes en 10,5 s.
- **Dérive de grounding observée** : sans tool disponible, le LLM feuille (faq) répond du savoir générique au lieu de refuser strictement — l'instruction seule ne suffit pas, confirmé empiriquement = spec vivante des guards S4-S7.
- Piège `run_local.sh` corrigé : après `kill`, attendre la mort effective du process (un uvicorn en drain tient encore le port et répond au probe de readiness à la place de son successeur → « Connection refused » juste après « ready »).

**Reste** :
- ~~Fabien : review + merge de la PR S2 ; re-run du smoke avec un `.env` réel~~ (faits le 2026-07-17).
- S3 : `dayuse_agent_common` (`build_model()` per-phase — le triage doit rester éco quand le modèle de synthèse montera —, `metrics_pg` → `llm_metric_events` + verrou test contenu, budget tool-calls), CI complète.
- Notes S4/S5 : l'enveloppe DataPart `{query_params, profile_in}` n'est **pas encore émise par le spine** (les feuilles reçoivent le texte utilisateur transmis par `RemoteA2aAgent` ; mécanisme identifié pour S4/S5 : encodage `inline_data` `<a2a_datapart_json>` du part converter ADK) ; sessions du concierge en mémoire process (Redis + TTL = S5) ; comportement historique de `RemoteA2aAgent` en multi-tour à trancher en S5 (`full_history_when_stateless`).
- Exception D7 toujours ouverte — désormais sur **3 services** (cartes non signées + bearers statiques) ; échéance inchangée : oidc-mtls avant le canary S11.

**Pièges découverts en S2** :
- `RemoteA2aAgent` construit le message sortant à partir des **événements de session** (aucun hook « message override ») ; le spine consomme les événements du leg **sans les re-yield** → réponse A2A propre côté client, MAIS la réponse feuille n'est pas persistée en session (le multi-tour se règle en S5 avec le profil).
- Le timeout httpx ne plafonne PAS une réponse streamée (reset à chaque chunk) : le budget 10 s réel est l'`asyncio.timeout` de `_run_leaf`.
- `.env` / `.env.example` sont **refusés par les permission settings** de l'agent Claude Code — les variables sont documentées dans les README de chaque service à la place.
- Un token sortant vide n'est pas fatal au boot du concierge : la feuille fail-closed répond 401 et le tour dégrade honnêtement (jamais d'auth contournée) — comportement voulu, documenté dans le README concierge.

**Ports + env (concierge)** : port **8100**. Env : `DAYUSE_MODEL` (déf. `gpt-4o-mini`), `OPENAI_API_KEY`, `HOTEL_SEARCH_CARD_URL` / `FAQ_AGENT_CARD_URL` (déf. localhost:8101/8102), `HOTEL_SEARCH_A2A_TOKEN` / `FAQ_AGENT_A2A_TOKEN` (bearers D7 sortants, par feuille), `CONCIERGE_LEAF_TIMEOUT_SECONDS` (10), `CONCIERGE_TRIAGE_TIMEOUT_SECONDS` (5), `CONCIERGE_SYNTHESIS_TIMEOUT_SECONDS` (15), `CONCIERGE_SYNTHESIS_NUM_RETRIES` (1), `A2A_HOST`, `PORT`, `A2A_BEARER_TOKEN` (**obligatoire**, fail-closed). Feuille faq : mêmes vars que la feuille search avec `FAQ_MCP_TIMEOUT_SECONDS`, port **8102**. Détail : README de chaque service.

## ⏱ État au 2026-07-16 — S1 terminée (socle repo + feuille hotel-search-agent)

**Fait (branche `s1-socle-feuille-search`, poussée sur GitHub — merge en attente de review)** :
- Remote : `github.com/Dayuse-Labs/AgentB2C` (privé — décision du 2026-07-16, GitHub Dayuse-Labs et non GitLab). **PR #1 ouverte** (`s1-socle-feuille-search` → `main`) : la review de Fabien reste le gate, rien n'est mergé.
- `git init` (main = docs seuls), `.gitignore` (baseline/ jamais commité), branche `s1-socle-feuille-search`.
- `agents/hotel_search_agent/` complet (pattern booking_qa de la fleet + overlay Dayuse) : `agent.py` (LiteLlm `DAYUSE_MODEL`→`gpt-4o-mini`, `McpToolset` streamable-http avec allowlist `["search_offers", "find_hotel_by_name"]`, timeout 5 s), `contract.py` (enveloppe stateless `SearchRequest{query_params, profile_in}` → `SearchResponse{results, profile_delta, diagnostics}` — champs métier volontairement ouverts, spec S4/S5), `resilience.py` (CircuitBreaker réel + testé, branché nulle part — TODO S4 Mapbox), `serve.py` (carte custom via `AgentCardBuilder` avec `securitySchemes.bearer-interim` + **middleware ASGI bearer D7 fail-closed**), Dockerfile (python:3.12-slim, non-root 10001, `--host ::`), agent-card.json statique, README (exception D7 + RGPD + staging≠shadow-run), .env.example.
- Racine : `scripts/dayuse_guardrails.sh` (copié fleet), `scripts/run_local.sh`, `.githooks/pre-commit` (activé via `core.hooksPath`), `pytest.ini`, `requirements-dev.txt`, `.venv` (uv, python 3.12), section Commandes de `CLAUDE.md` remplie.
- **DoD exécutée verte** : boot réel sur :8101 ; carte servie SANS bearer (`.name == "hotel_search_agent"`, `bearer-interim` déclaré) ; `GET /` sans bearer → 401, mauvais bearer → 401, bon bearer → 405 (≠401, gate passée) ; boot sans token → RuntimeError (fail-closed) ; `pytest -q` → 30 passed ; guardrails OK.

**Reste** :
- ~~Fabien : review + merge de la PR #1~~ (mergée le 2026-07-16).
- ~~S2 : faq-agent + orchestrateur~~ (faite, voir bloc du 2026-07-17 ci-dessus).
- S3 : brancher `dayuse_agent_common` (`build_model()`, metrics, budget tool-calls), CI complète.
- Exception D7 ouverte : carte NON signée + bearer statique — bascule oidc-mtls au plus tard avant le canary S11 (documentée dans le README de la feuille).

**Pièges découverts en S1** :
- Le hook PreToolUse du plugin a été patché **dans le cache** (`~/.claude/plugins/cache/...`) — à corriger à la source du plugin, sinon toute réinstallation/mise à jour restaure le matcher divergent.
- `dayuse_guardrails.sh` : ajout obligatoire de `--exclude-dir='.venv*'` vs la version fleet — les site-packages de google-adk/litellm contiennent `import vertexai` et font échouer le check 2 quand on lance le script à la racine avec un venv local. Seule adaptation de fond.
- La fleet ne vérifie AUCUN bearer entrant ; AgentB2C oui (D7) — écart assumé, spec de la phase.
- `AgentCardBuilder.build()` tente une session MCP pour lister les tools (échec gracieux et instantané hors ligne) — l'import de `serve.py` reste offline-safe, mais ne pas s'étonner du warning.
- `to_a2a()` n'expose que POST sur `/` : un `GET /` authentifié répond 405 — c'est la preuve « ≠401 » de la DoD, pas une erreur.

**Port + env vars (feuille search)** : port **8101** (plage AgentB2C : 8100 concierge / 8101 search / 8102 faq ; la fleet occupe 8092/8093). Env : `DAYUSE_MODEL` (déf. `gpt-4o-mini`), `OPENAI_API_KEY`, `MCP_B2C_URL`, `MCP_B2C_AUTH_TOKEN` (header omis si vide), `HOTEL_SEARCH_MCP_TIMEOUT_SECONDS` (déf. `5.0`), `A2A_HOST` (écrit dans l'URL de la carte), `PORT`, `A2A_BEARER_TOKEN` (**obligatoire**, fail-closed). Détail : `agents/hotel_search_agent/README.md` + `.env.example`.

## ⏱ État au 2026-07-16 (initialisation, avant toute session de dev)

**Fait (hors de ce repo)** :
- Phase 0 complète : audit + baseline prod nettoyée + evalset → `AUDIT-REWORK-2026-07.md`, `evalset/evalset-v0.json` (32 scénarios, 8 familles), `baseline/` (données brutes, NE PAS COMMITER).
- MCP_B2C : les 6 tools sont codés et verts (459 tests, 98,6 %) — **les 2 derniers (`get_faq_conditions`, `generate_booking_link`) sont en review par Fabien, non mergés**. Docker/README du MCP (5.1/5.2) volontairement en attente.
- Design review D1 : GO avec réserves, décisions actées dans `PLAN-REWORK-AGENT-USA.md` §9 (D1 : 2 feuilles A2A — décision produit ; D7 : identité intérimaire ; B3 : feuilles stateless ; spine code-owned).

**Pas fait (ce repo)** : tout le code. Aucun scaffolding lancé. Pas de `git init`.

**Prochaine étape** : ~~lancer S1~~ (faite, voir bloc du 2026-07-16 ci-dessus) → S2 avec le prompt de `PROMPTS-SESSIONS.md`. Le suivi d'avancement des items de phase se tient ICI (compteurs par session).

**Pièges connus** :
- Le hook `PreToolUse` du plugin peut bloquer les écritures locales si la build installée est divergente (matcher sain = `mcp__gitlab__…|mcp__notion__…` uniquement — vérifier avant S1).
- Le MCP_B2C accessible en dev pointe sur l'ES de **staging** : notes/avis quasi vides, inventaire partiel. OK pour développer, INTERDIT pour le shadow-run/parité (exige ES prod, cf. plan Ph3.3).
- `oidc-mtls` de `dayuse_agent_common` est un stub `NotImplementedError` — d'où D7 intérimaire.
- La fleet a évolué : `cs_copilot` (spine code-owned conversationnel) et `booking_qa` (feuille cliente MCP streamable-http) sont les précédents à imiter.
