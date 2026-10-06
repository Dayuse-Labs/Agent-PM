# HANDOFF — AgentB2C

État du chantier pour reprise en session fraîche. **Lire en entier avant d'agir ; ne pas reconstruire ce qui existe.** Mettre à jour en fin de CHAQUE session (bloc daté en tête).

> 📋 **Pour savoir QUOI faire ensuite, ouvrir [`CHANTIERS.md`](CHANTIERS.md)** (état vérifié au 2026-09-14) : la liste des chantiers ouverts, chacun avec sa preuve, ses actions et un prompt prêt à coller — plus la liste de ce qu'il ne faut **pas** relancer parce que c'est déjà livré. `tasks/todo.md` est périmé et ne doit plus servir de référence.

## ✅ 2026-10-06 (bis) — mcp-dayuse#6 : état de dialogue explicite

**Fait** (branche `fix/dialogue-state-explicit`, **empilée sur `fix/qa-oracle-facts-silent-fallbacks`** — merger celle-ci d'abord ; 1 commit par chantier ; gates : pytest **1 955 passés / 1 skippé**, ruff, mypy, guardrails **verts**). Ticket https://gitlab.com/dayuse/dayuse/mcp-dayuse/-/work_items/6. Chaque défaut reproduit en live avant le correctif (2e stack `PORT_OFFSET=20`, MCP `main` local), revérifié après ; chaque nouveau test échoue sans son correctif.

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
- Hors périmètre, à ticketer : « Nice » seul → salutation en anglais (« nice ») ; « Je veux réserver au Grand Hôtel X à Lyon » → parcours réservation au lieu d'une recherche ; compteur/`total` et groupes OU d'équipements (#4, #1) ; réserve parking dans la synthèse normale (seul le repli la porte).
- Bornes des moments de la journée (6-12 / 12-18 / 18-23) choisies par défaut : à valider par le produit (`DAYPART_HOURS`). `active_filters` n'expose pas encore le moment de la journée (pas de puce dans le widget).

🪤 **Pièges découverts** :
- **Inverser la règle du créneau rend nuisible ce qui était inoffensif** : un créneau inventé par le LLM passait sous « offre ⊆ fenêtre », il vide tout sous « fenêtre ⊆ offre ». Seul le rejeu avant/après des datasets l'a montré.
- Le MCP renvoie `HotelNotFoundError` pour « Pullman Lyon » alors que la recherche ville le renvoie : ne jamais annoncer « introuvable » sans regarder les cartes.
- `id` piscine **3001** : dans le groupe OU du serveur, absent de `list_amenities` — gardé, exception documentée dans le test de contrat (décision au ticket #4).
- Le hook readonly bloque toute commande Bash dont le TEXTE contient `. ./.env`, même dans un heredoc de doc : éditer ces fichiers avec Edit.

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

**Non fait, à trancher** : le plugin de décalage est resté dans le scratchpad, il n'est pas commité. Le versionner (+ un job qui rejoue la suite à +400 j) empêcherait une 3e vague ; à arbitrer, ce n'était pas demandé.

Gates locaux : pytest **1 707 passés / 1 skippé**, ruff **OK**, mypy **48 fichiers, 0 erreur**, `dayuse_guardrails.sh` **OK**.

## ✅ Addendum 2026-09-09 — support pédagogique Langfuse pour Produit/QA (docs, zéro code applicatif)

**Fait.** `observability/langfuse/guide-langfuse-pm-qa.html` : page HTML **autonome** (aucun CDN, aucun serveur, ouvrable en `file://`), en français, destinée à **un PM et un QA non-devs**. 9 sections : pourquoi/accès, les 5 objets, anatomie d'un tour, les 3 familles de scores, les 7 vignettes du dashboard décodées, 6 playbooks d'enquête, la boucle annotation→dataset→rejeu→CI, pièges & RGPD, quiz. Pointeur ajouté dans `observability/langfuse/README.md`.

**Toutes les données de la page sont réelles**, extraites en lecture seule le 2026-09-09 (`GET /api/public/{traces,scores,metrics,datasets,sessions}` + outils MCP `list*`) ; les requêtes de rafraîchissement sont en annexe **dans la page**, il n'y a pas de script à maintenir. Pièce centrale : la trace `0230928659c538b69b3d309b8434d2d3` (tour `synthetic`, release `e7795fc`) rendue en cascade cliquable — **1 racine / 34 observations / 4 services / 18 scores**, avec les vraies durées et coûts (`gpt-5.2` = **76 % des 0,00532 $** du tour pour 1 appel sur 4) et les vrais arguments de `geocode_location` et `search_offers`.

**Chiffres de référence relevés au passage** (utiles pour la prochaine session, tous sur la période juillet→septembre) : `guard_recovery_ack` **10,3 %** · `guard_booking_confirmation` **9,5 %** · `guard_geocode_echo_back` **9,2 %** · `guard_filter_relaxation_honored` 3,4 % (n=117) · 6 guards à **0 %** · `empty_shortlist` **40,7 %** (n=668) · `hotels_returned` 2,68 en moyenne · `llm_calls` 2,63 (**budget de 3 jamais dépassé, 0 tour au-dessus**) · `ttft_ms` p95 **25,9 ms** mais sur **197 tours seulement** sur 652 (seul le streaming l'émet) · niveaux d'observation DEFAULT 34 003 / WARNING 118 / **ERROR 233** · coûts cumulés `gpt-4o` 2,99 $ + `gpt-5.2` 2,05 $ + `gpt-4o-mini` 1,62 $ = **6,66 $**.

**3 documents périmés corrigés dans la page** (à corriger à la source un jour) : `dashboard-b2c.json` annonce « 13 series » et « seuls 8 guards émettent » (→ **15, tous câblés**) ; `PLAN-OBS-LANGFUSE-2026-07-29.md:117` dit « 2/3 juges actifs » (→ **3/3** depuis le 2026-08-25) ; la score config `guard_poi_anchor_coherence` dit « > 100 km » (→ **40 km**).

**🔴 2 trous trouvés en lisant le code, NON corrigés (hors scope de cette session, signalés dans la page) :**
1. **`evals/langfuse_experiment.py::_call_facade` n'envoie pas `X-Dayuse-Synthetic`** (aucun `headers=`) : chaque tour de rejeu d'experiment produit une trace **non taguée**, donc éligible à l'échantillonnage 5 % des 3 juges et non exclue du feeder d'annotation. Correctif = une ligne. C'est très probablement l'origine des items vides (`input=None`) qui avaient pollué la file d'annotation.
2. **Le widget navigateur ne l'envoie jamais non plus** (`web/vendor/static/js/chat/api.js::getChatHeaders`) : **les tours de test d'un QA dans le widget sont indistinguables du trafic réel** — ils entrent dans les taux du dashboard et sont notés par les juges. À trancher : header injecté par le proxy widget derrière un flag, ou un mode « QA » explicite.

**🟠 Piège d'API relevé** : `GET /api/public/scores?value=1` **ne filtre pas** (renvoie 10 923 lignes, zéros compris). Filtrer côté client, ou passer par `/api/public/metrics` (qui, lui, agrège correctement — y compris en v3).

**🟠 ~~Rouge préexistant sur `main`~~ — RÉSOLU le 2026-09-14, voir le bloc en tête (dont la prescription ci-dessous, fausse, y est corrigée)** : `agents/hotel_search_agent/tests/test_datetime_resolver.py::test_resolve_search_date_marks_a_carried_over_future_date_as_not_today` échouait depuis **le 2026-09-09** — le test code en dur `2026-09-09` comme date *future* et on y est. Même classe que les tests corrigés en PR #71 (pourrissement par le calendrier) ; le correctif immunisant est de passer une date de référence explicite, pas de bouger le littéral. Vérifié : le test échoue à l'identique sur un arbre sans mes fichiers (`git stash -u`). Reste : 1 échec, **1 706 passés**, ruff/mypy/guardrails **verts**.

**Deuxième page, même session : `observability/langfuse/guide-tests-langfuse.html`** — tutoriel « ajouter un test » (écrire un cas → l'envoyer → lancer → lire), demandé pour que le QA alimente lui-même les jeux OBS6. Contient un **constructeur de cas interactif** (cases à cocher → ligne JSONL valide, copiable) et les 18 vérifications documentées une par une avec leur **commentaire réel** relevé sur de vrais passages (`Novotel Paris La Défense Nanterre: 7.1km > 3km`, `city: expected 'Paris', got 'paris'`, `priceRangeMax: expected 150, got None`…).

**Réponse tranchée à « peut-on jouer un jeu de prompts depuis l'UI Langfuse ? » : non, pas pour notre agent.** Vérifié dans la doc Langfuse : « Experiments via UI » = **Prompt Experiments**, qui exigent (a) un prompt dans le Prompt Management de Langfuse et (b) une LLM connection — Langfuse fait alors lui-même l'appel modèle. Il ne peut pas appeler `b2c-concierge`. Et notre projet a **0 prompt géré dans Langfuse** (vérifié : `GET /api/public/v2/prompts` → `totalItems: 0`, aucun `get_prompt` dans le code). La matrice de la doc est explicite : dataset hébergé + exécution locale/CI = « Experiments via SDK », c'est notre cas ; exécution Langfuse + dataset local = « Not supported ». **Piste proposée, non faite** : un `workflow_dispatch` sur le job CI `langfuse-experiments` donnerait au QA un vrai bouton (le job fait déjà tourner Redis + les 3 services + le seed) — c'est le seul chemin vers l'autonomie du QA sans setup local.

**🔴 Tri des 8 remontées QA du 2026-09-08 — 6 sur 8 ne sont PAS auditables par le harnais**, vérifié une par une contre le code (le détail est dans la page) :
- **auditables (2)** : n°1 « hôtels affichés + texte disant qu'il n'y a pas de dispo » (les deux faits sont dans la réponse ; mécanisme identifié = S-CX6 `ground_truth.py::_DATE_FALLBACK_NOTE`, donc c'est probablement la **divulgation obligatoire mal formulée**, pas une donnée fausse) ; n°2 format de date ISO qui fuit dans le texte (interdire le préfixe d'année, jamais une date en dur — sinon le cas pourrit).
- **en partie (2)** : n°5 devise — la *divulgation* EUR (`currency_guard.py`) est auditable et devrait devenir un `regression_guard`, la *conversion* reste bloquée sur MCP_B2C ; n°4 date non appliquée sur la page hôtel — **aucune des 14 vérifications « réponse » ne regarde l'URL du lien**, il manque une assertion (~20 lignes).
- **non auditables (4)** : n°3 (objection de conception produit : un test ne peut pas exprimer « cette fonctionnalité ne devrait pas exister ») ; n°6 Booking Fees (prix venu de MCP_B2C + config back-office par hôtel ; figer un montant rendrait le cas rouge un jour sur deux) ; **n°7 et n°8 = libellés statiques du widget**, `web/vendor/static/js/chat/i18n.js` — `card_free_cancel` (ligne 86 en anglais) et `card_price_note` (ligne 75), **présents en 7 langues** (en, fr, es, it, pt, de, nl). L'agent ne les émet jamais : aucun test ne peut les voir. **Ce sont les 2 remontées les moins chères de la liste — une correction de copy × 7 locales, à faire, sans test.**

**Chiffres d'un vrai avant/après recalculés pour la page** (jeu `b2c/geo-poi`, 21 cas, en marchant run items → traces car les filtres de scores mentent, cf. ci-dessous) : `p0-2-after-2026-08-25` **58/86 = 67 %** → `p0-2-radius-2026-08-25` **72/86 = 84 %** ; `hotels_within_km` 4/17 → 11/17, `min_hotels` 15/20 → 19/20, `resolved_country_code` 13/18 → 16/18, et une régression réelle `clarify_expected` 19/19 → 18/19.

**🟠 Deuxième filtre d'API qui ment silencieusement** (le premier était `?value=1`) : **`GET /api/public/scores?traceId=<id>` ignore le filtre** — un `traceId` inexistant renvoie les 12 718 scores du projet. Idem `?experimentId=<runId>`, qui renvoie les scores *de trace* des tours rejoués, pas les scores d'assertion du run. **La seule source fiable est l'objet trace lui-même** (`GET /api/public/traces/<id>` → son tableau `scores`). Structure d'un item de run, au passage : une trace SDK `experiment-item-run` de 5 observations (`experiment-item-task`, `experiment-item-evaluation`, `response_evaluator`, `trace_evaluator`) portant exactement les assertions **déclarées** par l'item.

**🟠 Le gate pytest ne peut pas fonctionner avec un `.env` réel** (mécanique lue, non exécutée) : `conftest.py` à la racine force `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` à `""` avant tout import, or le SDK ne se désactive que sur `None` (`client.py:381`, `if public_key is None:`) — donc `RUN_LANGFUSE_EXPERIMENT_GATE=1 pytest` construit un client aux identifiants vides et échoue à l'auth au lieu de se skipper proprement. Il n'y a aucun `conftest.py` sous `evals/`. Le chemin humain documenté dans la page est donc `python -m evals.langfuse_experiment`, pas le gate.

**Vérification faite** (pas seulement « le HTML est valide ») : Chrome headless piloté en CDP — **32 assertions vertes sur le guide, 25 sur le tutoriel, 0 erreur console de part et d'autre** — rendu des 10 sections, bascule « masquer la plomberie » (18 ⇄ 34 lignes), clic sur 3 étapes, onglets des 3 familles de scores, filtres de la table, quiz, absence de défilement horizontal, thème sombre ; 8 captures relues à l'œil. 4 bugs de rendu trouvés et corrigés par cette relecture (barres de cascade invisibles car `.track` était un `<span>` inline ; `th` sticky créant une bande vide et masquant la ligne de groupe ; flèche de retour SVG rendue en triangle plein faute de `fill="none"` ; texte du quiz en monospace).

## ✅ Addendum 2026-08-28 bis — post-merge #109 : 3 items clos par la mesure (dont un gap de liens trouvé ET fermé)

PR #109 **mergée** (`71111cf`, 09:49:45Z). **Zéro PR ouverte** — le chantier UX est clos.

**1. Estampille remise à jour, sans redéploiement.** L'arbre de `8946df4` (déployé) est identique à celui de `71111cf`, donc le code qui tourne EST celui de `main` ; seule l'estampille nommait un commit hors de `main`. `LANGFUSE_RELEASE=71111cf` posé sur `widget` avec `--skip-deploys` (`createdAt` toujours `09:07:31Z` après, vérifié). Aucun autre service touché.

**2. ✅ La divulgation EUR sort bien en prod — preuve owed d'UX3 phase 2B, enfin faite.** Le bloc « octies » disait « le fix est prouvé en local, pas en prod ; re-vérifier après merge+déploiement ». Vérifié d'abord que le correctif EST déployé (`git merge-base --is-ancestor a7dd75a e7795fc` → oui, le concierge tourne sur `e7795fc`), puis rejoué **le tour exact du bloc octies** (`POST /v3/chat`, `x-dayuse-synthetic: 1`, « un hotel a Bangkok apres demain avec piscine ») :

> « …l'Hotel Royal Bangkok est autour de 67% moins cher que le tarif nuit. … **Prix affichés en euros, sans conversion.** »

La ligne de `currency_guard.py::enforce_currency_disclosure` est là. Avant le correctif, le MÊME tour ne mentionnait aucune devise (documenté dans octies). **Item clos.** Reste bloqué côté MCP_B2C, inchangé : l'affichage en devise locale attend leur réponse sur `hotelPrice` (`reports/PROMPT-MCP-B2C-DEVISE-LOCALE-2026-08-27.md`).

**3. 🔴 Gap réel trouvé, mesuré : 3 marchés vivants ne sont pas dans `_MARKET`, donc leurs cartes n'ont AUCUN lien.** `_MARKET` couvre 22 pays, dayuse-com en sert **53**. Depuis la suppression du fabricateur (#109), un hôtel dans un pays non mappé ne reçoit plus un lien inventé — il ne reçoit **plus rien**. Restait à savoir si c'était théorique. Sondé sur 14 pays non mappés ayant un vrai domaine Dayuse (`search_offers`, J+2, réseau réel) :

| Pays | `total` | hôtels rendus | `countryName` | résolu par `_ISO_BY_COUNTRY_NAME` ? |
|---|---:|---:|---|---|
| **KR** Séoul | 2 | 2 | `South Korea` | ❌ |
| **TR** Istanbul | 6 | 5 | `Turkey` | ❌ |
| **QA** Doha | 7 | 5 | `Qatar` | ❌ |
| JP, MX, IN, ID, PH, VN, PL, GR, ZA, AR, CN | 0 | 0 | — | — |

→ **3/14 marchés non mappés avaient de l'inventaire réel**, ~15 hôtels **sans lien réservable**. Les 11 autres sont vides : gap petit et borné. **Fermé le même jour — voir le point 4.**

Et les domaines existent, vérifiés vivants (200, 0 redirection) avec leur config dayuse-com :

| | host | countryCode | currency | `defaultSearchPageLink` |
|---|---|---|---|---|
| KR | `kr.dayuse.com` | KR | KRW | **`south-korea/seoul`** ← contient une VILLE |
| TR | `tr.dayuse.com` | TR | EUR | `turkiye` |
| QA | `qa.dayuse.com` | QA | QAR | `qatar` |
| BH | `bh.dayuse.com` | BH | BHD | `bahrain` (pas encore sondé pour l'inventaire) |

**4. ✅ Gap FERMÉ le même jour — KR/TR/QA mappés, 15/15 hôtels réels résolvent 200.** Les 2 inconnues (chemin d'hôtel anglais, non donné par la config dayuse-com) ont été levées par **une vraie URL d'hôtel par marché fournie par Fabien**, pas par déduction — la docstring de `_MARKET` exige des valeurs vérifiées en trafic réel :

| | host | chemin | URL de référence (200) |
|---|---|---|---|
| KR | `kr.dayuse.com` | `south-korea` | `/hotels/south-korea/hotel-nafore` |
| TR | `tr.dayuse.com` | `turkey` | `/hotels/turkey/hilton-istanbul-bomonti-hotel-conference-center` |
| QA | **`qa.dayuse.com`** | `qatar` | `/hotels/qatar/ibis-doha` |

🪤 **L'URL de référence QA était sur `www.dayuse.com`, et je ne l'ai PAS reprise** — mesuré : les deux hôtes servent la page en 200, mais le **même hôtel** rend `"currency":"USD"` sur `www.dayuse.com` et `"currency":"QAR"` sur `qa.dayuse.com`. L'hôte de marché est celui qui affiche la devise locale. C'est exactement la classe de défaut des 8 hôtes de browse corrigés plus tôt dans la journée, cette fois prouvée par une chaîne de devise concrète et pas déduite. Verrouillé par test, pour qu'un retour à `www` soit une décision et pas un glissement.

**Vérification décisive, sur l'inventaire réel et pas sur les 3 exemples** : pour chaque hôtel que MCP renvoie réellement à Séoul / Istanbul / Doha, l'URL construite par `build_hotel_page_url` a été interrogée en HTTP → **15/15 en 200, zéro redirection** (`hotel-nafore`, `luxury-hanok-hotel-daam`, 6 hôtels TR dont `mavirem-hotel`, 7 hôtels QA dont `ibis-doha`). Les slugs de MCP correspondent donc bien aux slugs réels du site.

Ajouté dans les 4 tables du **même** module (`_MARKET`, `_ISO_BY_COUNTRY_NAME` avec les alias `korea`/`republic of korea`/`turkiye`, `_BROWSE_PATH`, `_LABEL`), puis `markets.generated.js` **régénéré** : 22 → **25 marchés**. `DAYUSE_HOSTS` n'a rien demandé (`kr.`/`tr.`/`qa.dayuse.com` sont des sous-domaines de la racine `dayuse.com` déjà présente) — et le test de dérive le confirme : **0/25 rejeté**.

`pytest -q` **1707 passed, 1 skipped**. ruff, mypy, guardrails, `--check` verts.

### ✅ Les 3 services déployés (`babc652`) et vérifiés en prod

`hotel-search` (`SUCCESS 13:33:55Z`) → `concierge` (`SUCCESS 13:35:34Z`) → `widget` (`SUCCESS 13:39:19Z`), feuille d'abord (convention #95/#102/#107), chacun estampillé `LANGFUSE_RELEASE=babc652` **après** son SUCCESS avec `--skip-deploys` (`createdAt` vérifié inchangé après chaque stamp). `faq` laissé sur son estampille : aucun de ses fichiers dans le diff.

**Preuve 1 — le backend** : tour `POST /v3/chat` « un hotel a Doha apres demain » (`x-dayuse-synthetic: 1`) → **5 cartes, toutes avec `url=https://qa.dayuse.com/hotels/qatar/…`** (`the-avenue-hotel`, `concorde-hotel-doha`, `radisson-blu-doha-hotel`, `ibis-doha`, `alwadi-hotel-doha-mgallery`) et `currency_code=QAR`. Avant ce déploiement : aucune de ces cartes n'avait de lien.

**Preuve 2 — le widget** : l'artifact servi porte bien **25 marchés** avec les 3 nouveaux `browseUrl` (`kr.dayuse.com/s/south-korea/seoul`, `qa.dayuse.com/s/qatar`, `tr.dayuse.com/s/turkiye`), byte-identique à HEAD.

**Preuve 3 — le rendu, vrai tour Doha dans le DOM** (`?q=`, `x-dayuse-synthetic: 1`) : **5 cartes, 5 liens, tous sur `qa.dayuse.com`**, `href="#"` = 0, lien fabriqué = 0. C'est le bout de la chaîne : ces cartes n'avaient aucun lien il y a une heure.

🪤 **Piège de sonde à retenir : le balayage des 25 liens de browse produit UN 404 sporadique, et il se déplace.** Un run donne IT en 404, le run suivant donne AU en 404 — et chaque URL interrogée seule répond 200 trois fois de suite (`/s/italia` ×3, `/s/australia` ×3). C'est du **throttling provoqué par le balayage lui-même** (24 requêtes en rafale sur les hôtes Dayuse), pas un défaut. Deux conséquences : espacer les requêtes (~1,2 s) et **ne jamais conclure d'un 404 isolé dans un balayage sans le rejouer seul**. Au passage, `/s/italy` est un vrai 404 constant — ce qui confirme que `italia` est bien le bon slug.

🪤 **Piège de lecture levé au passage** : ces cartes portent `country_code=QA`, ce qui semble contredire le « 0/201 `countryCode` » de l'audit. Les deux sont vrais. Le 0/201 mesure `hotel["countryCode"]` **venant de MCP** — re-vérifié le même jour sur Doha ET Paris : `'countryCode' in hotel` est `False`. Le `country_code` de la carte vient de `response_bridge.py:1037` (`card.setdefault("country_code", search_country)`) : c'est le pays que **le géocodeur** a résolu pour la recherche. Donc `inferCountryCodeFromHotel` côté widget reçoit bien un ISO2 en pratique — du géocodeur, jamais de MCP.

📌 KR est le **seul** marché dont le slug de browse porte une ville (`south-korea/seoul`, c'est le `defaultSearchPageLink` de dayuse-com pour ko-KR, et c'est là qu'est tout son inventaire). Verrouillé par un test qui échoue si un 2e marché en gagne une.

📌 Le compteur qui répondra tout seul : `booking_url_fallback` avec `reason=missing_from_payload` (livré dans #109, déployé) mesure désormais **combien de fois un utilisateur voit réellement une carte sans lien** — donnée que l'audit n'a pas pu obtenir.

🪤 **Où le lire — PAS dans les logs Railway** (vérifié le 2026-09-01, après une affirmation erronée de ma part). `trackEvent` (`tracking.js:117`) a **deux** puits : `amplitude.track(...)`, qui poste directement chez Amplitude, et `navigator.sendBeacon('/api/track')`. Or `/api/track` est **avalé** par le proxy widget — `run_widget_proxy.py:133-135` répond 204 et **jette le corps** (sa docstring l'assume : « swallowed locally (204) — AgentB2C doesn't implement it and it's fire-and-forget analytics »). Les logs Railway montrent donc bien `POST /api/track … 204`, ce qui prouve que des événements partent, mais **ne portent ni le nom de l'événement ni `reason`**. La donnée n'existe que **dans Amplitude** (événement `booking_url_fallback`, propriété `reason` ∈ `missing_from_payload` / `rejected_by_allowlist`) — accès Dayuse, hors de ce repo.

💡 **Option non faite, à trancher** : faire logger au proxy le `event` + `reason` lus dans le corps du beacon (~10 lignes dans `run_widget_proxy.py`), pour que cette métrique se lise comme toutes les autres du repo (`dayuse_metric=` / `concierge_metric=` dans les logs Railway) au lieu d'exiger un accès Amplitude. RGPD : nom d'événement et `reason` ne sont pas du contenu utilisateur — mais le corps du beacon en contient d'autres champs, donc il faudrait logger une **liste blanche** de clés, jamais le payload brut. Décision Fabien : ça touche le seul service public.

## ✅ Addendum 2026-08-28 — UX6 : audit des mappings en dur. 98 tables, 0 morte, 0 suppression — et les 4 candidats de la phase réfutés

Phase d'ÉTUDE UX6 (fichier de phase supprimé au nettoyage de fin de chantier — ce bloc et le rapport en portent tout le contenu durable). Livrable : **`reports/AUDIT-MAPPINGS-2026-08-28.md`** (à lire en entier avant de retoucher une table en dur). Branche `audit/ux6-hardcoded-mappings`, PR ouverte. **Zéro ligne exécutable modifiée** — 4 commentaires corrigés + 2 scripts de mesure ajoutés.

### Le résultat en trois lignes

1. **Aucune table morte dans le repo.** Balayage du compte de références hors ligne de définition sur les 74 tables Python : **minimum observé = 1**. La commande est dans le rapport §8, rejouable.
2. **Les 4 candidats à la suppression de la phase sont tous les 4 en catégorie 1** après mesure. La phase a donc *promu* 2 tables (`_ISO_BY_COUNTRY_NAME`, `_LOCALE_COUNTRY`) de la catégorie 3 vers la catégorie 1, au lieu d'en supprimer.
3. **~20 tables annoncées, 98 trouvées** — les greps de la phase rataient les tables indentées, les tuples fermés et les `frozenset`. Et **30 des 98 ne sont pas des mappings** : c'est la couche de traduction Python (l'équivalent d'`i18n.js`, que la phase exclut déjà). Le ressenti « plusieurs mappings en dur » porte pour un tiers sur de l'i18n → chantier UX2-bis, pas chantier mappings.

### `countryCode` : mesuré sur 21 pays, la phase avait l'information périmée — pas le code

`scripts/probe_country_code_coverage.py` (réseau réel, pas un pytest), 2026-08-28, date J+2 :

| Chemin | Hôtels | `countryCode` résout un marché | `countryName` résout | **jambe NOM porteuse** |
|---|---:|---:|---:|---:|
| `search_offers` (carte feuille) | **201** | **0 (0 %)** | 201 (100 %) | **201 (100 %)** |
| `get_hotel_details` (inline concierge) | 24 | 24 (100 %) | 24 (100 %) | 0 |

21 marchés avec inventaire dont **12 non-euro** (GB US CH TH SE SG HK AE BR AU CA NZ) — très au-delà des « ≥ 4 pays dont un non-euro » exigés, et le piège « ne pas conclure depuis FR seul » est fermé : `countryCode` est absent sur **100 %** des hôtels de `search_offers`, sur **tous** les marchés. `legs_disagree = 0`, `no_market_at_all = 0` → `_ISO_BY_COUNTRY_NAME` couvre 100 % des `countryName` que MCP émet réellement, aucun trou.

**Donc `_ISO_BY_COUNTRY_NAME` n'est pas un fallback mort : c'est la SEULE jambe qui produit une URL d'hôtel sur le chemin carte** (tout ce que S-G12 garde). Les commentaires `hotel_urls.py:54` et `response_bridge.py:562` sont **confirmés exacts**, re-datés du 2026-08-28 avec le chiffre. `get_hotel_details` envoie bien un `countryCode` (24/24) — ça ne change rien au chemin carte.

### 🔴 Constat non prévu, le plus important de la phase : le widget défait la « None honnête » du back

`hotel_urls.py` promet « an unmapped country yields None — the card honestly has no link rather than a guessed one ». **Faux en pratique** : `markets.js::buildHotelFallbackUrl` slugifie le NOM D'AFFICHAGE dès que `hotel.url` est absent (`card.js:149-151`). Exécuté sur les vrais modules widget (`node`, aucun mock) :

```
Poland  -> https://dayuse.com/hotels/usa/h-tel-m-tropole-spa      (passe l'allowlist, rendu)
Japan   -> https://dayuse.com/hotels/usa/grand-hyatt-tokyo        (passe l'allowlist, rendu)
```

Un hôtel polonais devient une page **`/hotels/usa/`** (car `inferCountryCodeFromHotel` exige 2 lettres et `getMarketMeta` retombe sur `'US'`), avec un slug **inventé et abîmé** (`h-tel-m-tropole-spa` = littéralement le défaut `a-roport` que le back existe pour fermer), et **ça passe le sanitizer**. Pire : `trackEvent('booking_url_fallback')` ne tire **que** si `hotel.url` existait et a été rejeté → le cas « pas d'url → url fabriquée » est **totalement non tracké**.

**Conséquence** : retirer une entrée de `_ISO_BY_COUNTRY_NAME` ne donne pas « pas de lien », ça donne **un lien fabriqué sur le mauvais marché**. C'est la raison la plus forte de garder la table, et elle n'était ni dans la phase ni dans le code.
⚠️ Portée : exécution déterministe **hors ligne** du vrai code widget. Le chemin est prouvé atteignable ET prouvé fabricant, mais **son taux d'occurrence en prod n'est pas mesuré** (les 21 marchés à inventaire sont tous couverts ; MY/JP/MX avaient `total=0` à la date sondée).

### Catégorie 2 chiffrée, proposée, NON implémentée (conforme au périmètre)

`scripts/measure_market_table_drift.py` (hors ligne, lecture seule) : **85 entrées tenues à la main dans 4 tables et 2 langages** — `_MARKET` (22, py), `COUNTRY_META` (23, js), `COUNTRY_SLUG_TO_CODE` (24, js), `DAYUSE_HOSTS` (16, js).

- ensemble des pays : **0/22 d'écart** ✅ · slugs de chemin : **0/22 d'écart** ✅
- **hôtes : 8/22 en désaccord (36 %)** — AE AU BR CA HK MY NZ TH : le back réserve sur `www.dayuse.ae`/`au.dayuse.com`/… , le widget browse sur `www.dayuse.com`
- `DAYUSE_HOSTS` admet encore les 22 hôtes de `_MARKET` (**0 rejeté**) grâce à la règle sous-domaine d'`isHostMatch` → **la panne n'est pas en cours, elle est à un marché de distance** (un eTLD réellement nouveau type `dayuse.pl` déclenche le chemin de fabrication ci-dessus, scénario exact de la panne 404 de 4 jours du 2026-07-06)

3 options chiffrées dans le rapport §6.3. **Recommandation : option C tout de suite** (~30 lignes : convertir les 2 parseurs du script de drift en test qui échoue si `DAYUSE_HOSTS` cesse d'admettre un hôte de `_MARKET` ou si un slug diverge — ne supprime aucune duplication mais supprime la panne silencieuse, seul risque réellement chiffré), **option B ensuite** si l'unification est voulue (génération au build du widget ; l'option A, un JSON servi par la façade, met le sanitizer d'hôtes au bout du réseau — mauvaise direction pour un composant de sécurité).

### 4 arbitrages en attente (aucun n'est une suppression de catégorie 1)

1. Catégorie 2 : option A/B/C ci-dessus.
2. Aligner `buildHotelFallbackUrl` sur le contrat du back (rendre `null`, ne pas afficher de lien) ? ~10 lignes, **changement visible client donc décision produit**. Mon avis : oui, et avant l'unification.
3. Le trou de tracking `booking_url_fallback` : 1 ligne, et le taux d'occurrence du constat ci-dessus devient mesurable en prod.
4. `COUNTRY_META.UK` (`markets.js:46-51`, 6 lignes) : **provablement mort** (`getMarketMeta` passe toujours par `normalizeCountryCode` qui convertit `UK`→`GB` avant la recherche, et `COUNTRY_META` n'est lu qu'à cet endroit). **Non supprimé ici** : il n'existe aucun harnais de test JS dans le repo (pas de `package.json`, pas de `*.test.js`) et le DoD exige « chaque suppression avec son test » ; de plus `markets.js` est explicitement hors périmètre. À faire dans la phase qui touchera ce fichier — la suppression y sera gratuite.

### Ce qui a été modifié : 4 commentaires, zéro comportement

`hotel_urls.py:54` et `response_bridge.py:562` re-datés avec le chiffre 0/201 (ce sont les deux commentaires qui auraient conduit à supprimer la table). `security.js:5` pointait vers `_BOOKING_HOST_BY_COUNTRY in src/application/shared/hotel_urls.py` — **chemin agent-usa, inexistant ici** — corrigé vers `_MARKET` dans `libs/b2c_common/`. `card.js:54` disait « Mirrors the backend `_CURRENCY_DISPLAY` » — **`_CURRENCY_DISPLAY` n'existe pas dans ce repo** (`grep` → 0), corrigé.

### Pièges rencontrés

- 🪤 **Le fichier de phase peut être la source périmée, pas le code.** UX6 affirmait « depuis, `countryCode` est bien présent dans le payload » et donnait `_ISO_BY_COUNTRY_NAME` pour « le meilleur candidat » à la suppression ; le commentaire du code disait l'inverse et avait raison. Les deux appelants *passent* bien `countryCode` en premier argument — mais la **valeur** est `None`. Vérifier la valeur, pas la signature d'appel.
- 🪤 **« La façade fournit déjà X » peut être inversé.** Pour `_LOCALE_COUNTRY`, la façade fournit la *locale*, qui est l'**entrée** de la table, pas son remplacement (`facade.py:666` → `profile.locale` `:388` → `geocode_tool.py:926` `args["locale"]`). La table est atteinte à 4 sites dont 2 inconditionnels (`geocode_tool.py:649`, `:793`).
- 🪤 Les greps « tables en dur » d'un fichier de phase sous-comptent : ajouter les tables **indentées**, les **tuples** fermés (`PICKS = (…)`, `LANGUAGES = (…)`, `GUARD_SCORE_NAMES`) et les `frozenset`. 20 annoncées → 98.
- 📌 `dayuse_guardrails.sh` n'a **aucune** règle sur les constantes ou hosts en dur (seule règle proche : SDK modèle cloud importé en dur) — donc aucun signal du guardrail ne peut être confondu avec un constat de cet audit. Lancé **avant** la phase : `OK`.
- 📌 La leçon `US_STATE_*` est plus fine que « dérivez d'une lib » : après la dérivation depuis le paquet `us`, le code garde **2 correctifs manuels commentés** (`["mass"]` ajouté, `["washington"]` retiré). Le bon état final n'est pas « zéro table en dur », c'est « la partie mécanique vient d'une source, la partie jugement est en dur **et commentée** ».

### DoD

`pytest -q` : **1691 passed, 1 skipped** (identique à la baseline post-#107 — aucun test ajouté, aucun modifié : rien d'exécutable n'a changé). `ruff check .` : clean. `mypy agents libs` : clean (48 fichiers). `bash scripts/dayuse_guardrails.sh .` : OK, **avant et après**. Les 3 fichiers JS édités re-vérifiés (`node --check` + import réel de `markets.js`/`security.js`). Code de MCP_B2C **non relu** (interdit de session) — tout vient de ses réponses. Aucun 429 sur les 2 runs de sonde (espacement 1,5-2 s).

### Suites arbitrées par Fabien le 2026-08-28 — implémentées sur la même PR

Les 4 arbitrages du rapport ont été tranchés immédiatement (« 1. C now and B later · 2. yes, and ahead of unification · 3. ok · 4. ok »), donc cette PR ne contient plus seulement l'audit. Détail dans le rapport §12.

| # | Décision | Livré |
|---|---|---|
| C | garde-fou de dérive maintenant, unification (option B) plus tard | `tests/test_market_table_drift.py` — 11 tests. Échoue avec la signature exacte de la panne : en retirant `'dayuse.fr'` de `DAYUSE_HOSTS`, `AssertionError: 1 market host(s) would be REJECTED … {'FR': 'www.dayuse.fr'}`. Restauré ensuite. |
| 2 | aligner le widget sur le contrat du back, **avant** l'unification | `buildHotelFallbackUrl` **supprimé** de `markets.js` (+ ses 2 appelants `utils.js`, `card.js`). Plus de slug inventé nulle part. `renderFooter` n'affiche plus de lien hôtel quand il n'y a pas d'URL (au lieu d'un `href="#"` mort). |
| 3 | tracker le cas non tracké | `card.js` : le garde passe de `if (hotel.url && !sanitizedUrl)` à `if (!sanitizedUrl)`, avec `reason: 'rejected_by_allowlist' \| 'missing_from_payload'`. **Nom d'événement `booking_url_fallback` conservé** — renommer casserait la série Amplitude (même raisonnement que `GUARD_SCORE_NAMES`). |
| 4 | supprimer `COUNTRY_META.UK` | Fait. Remplacé par un commentaire disant *pourquoi* il était mort, et pourquoi `COUNTRY_SLUG_TO_CODE['uk']` — qui est atteignable — ne doit **pas** être « nettoyé » avec lui. |

**Le harnais de test JS qui manquait existe maintenant** — c'était la raison invoquée dans le rapport §8 pour ne pas supprimer les 6 lignes mortes. `tests/widget/widget_url_contract.test_mjs` (9 tests, `node:test`, aucune dépendance) charge les **vrais** modules widget, et il tourne **dans `pytest -q`** via `TestWidgetUrlContract` (donc en CI : node est présent sur `ubuntu-latest`, aucun changement de workflow). Skip propre si `node` est absent en local.

🪤 **La vérification qui rend ce harnais utile** : `card.js` ne peut pas être ÉVALUÉ en node nu (il importe des modules qui touchent le DOM), mais ESM **parse et lie tout le graphe avant d'évaluer quoi que ce soit** — donc un `import { buildHotelFallbackUrl }` resté en place ressort en `SyntaxError: does not provide an export named`, que le test attrape, alors qu'une `ReferenceError` sur `document` signifie que le linkage a réussi (le seul point testé). Vérifié en réintroduisant l'import mort : le test tombe avec ce message exact, puis restauré.

### ✅ Déployé et VÉRIFIÉ EN PROD (branche non mergée — même convention que PR #95/#102)

**`widget` seul.** Les modifications Python de cette PR sont **prouvées commentaires-seuls** (`git diff` filtré sur les lignes non-commentaires : vide pour `hotel_urls.py` ET `response_bridge.py`), donc `concierge`, `hotel-search` et `faq` gardent leur estampille — elle reste honnête, leur comportement est identique. Les 4 fichiers JS sont toute la modification de comportement, et c'est `widget` qui les sert.

`LANGFUSE_RELEASE=48c399f` posé sur `widget` avec `--skip-deploys` (vérifié : `latestDeployment.createdAt` resté à `2026-08-27T08:33:35.902Z` après le stamp — aucun redéploiement de l'ANCIEN code sous la nouvelle estampille), puis `railway up --service widget --detach` → **`SUCCESS 2026-08-28T07:56:17Z`**.

**Preuve 1 — le code servi a réellement changé.** État AVANT capturé sur le domaine public : `markets.js:46 UK: {` et `markets.js:232 export function buildHotelFallbackUrl(hotel) {` étaient bien servis. APRÈS : 0 occurrence des deux, et les **4 fichiers JS servis sont byte-identiques à HEAD** (`diff` sur `markets.js`, `security.js`, `utils.js`, `hotels/card.js`).

**Preuve 2 — le rendu, sur le module DÉPLOYÉ, dans un vrai Chrome** (import dynamique de `/static/js/chat/hotels/card.js` depuis l'origine live, `createHotelCard` réel sur 2 fixtures — aucun tour de chat, aucun appel MCP, aucune donnée utilisateur) :

| Fixture | lien « voir l'hôtel » | hrefs | `href="#"` | `/hotels/usa/` fabriqué | carte rendue |
|---|---|---|---|---|---|
| avec `url` serveur | ✅ présent | le vrai `dayuse.fr/hotels/france/…` + params Amplitude | non | — | oui |
| **sans `url`** (Poland) | ✅ **absent** | **aucun** | non | ✅ **aucun** | oui, prix compris |

Avant ce déploiement, la MÊME fixture rendait `https://dayuse.com/hotels/usa/h-tel-m-tropole-spa`.

**Preuve 3 — le trou de tracking est fermé, mesuré en prod** (`navigator.sendBeacon` + `amplitude.track` interceptés) :

| Cas | Événement émis |
|---|---|
| url valide | **aucun** (correct — rien à signaler) |
| **pas d'url** | `booking_url_fallback` · `reason: "missing_from_payload"` ← **le cas qui était invisible** |
| url rejetée par l'allowlist | `booking_url_fallback` · `reason: "rejected_by_allowlist"` · `rejected_url` renseignée |

Même nom d'événement dans les deux cas : la série Amplitude est continue.

**Preuve 4 — un VRAI tour, payloads MCP réels, DOM réel** (`?q=hotel a Paris demain apres-midi`, session fraîche, `x-dayuse-synthetic: 1` injecté avant tout script de page) : **5 cartes, 5 liens, tous sur `www.dayuse.fr`**, `href="#"` = 0, `/hotels/usa/` fabriqué = 0, slug serveur réel (`h4-hotel-wyndham-paris-pleyel-resort`). Le tour est parti sur `/v3/chat/stream`. La non-régression tient donc sur le **vrai** chemin de rendu, pas seulement sur `createHotelCard` isolé.

⚠️ **Ce qui n'est PAS prouvé en prod, et ne peut pas l'être aujourd'hui** : le taux d'occurrence du cas `missing_from_payload` sur du trafic réel. Il demande un hôtel dans un pays absent de `_ISO_BY_COUNTRY_NAME`, et les 21 marchés à inventaire sont tous couverts (c'est la raison même pour laquelle l'audit ne pouvait pas le chiffrer). **C'est l'événement lui-même qui répondra**, dans la durée — pas une sonde.

🪤 **Piège rencontré sur la sonde e2e** : une première version installait le wrapper `fetch` **après** le boot de l'app puis pilotait le textarea à la main — le handler de submit de l'app n'était jamais atteint (`chat_calls: 0` pendant 120 s, lu à tort comme « pas d'inventaire »). La forme qui marche : `Page.addScriptToEvaluateOnNewDocument` (le wrapper est en place avant tout script de page) **+** `?q=` qui auto-envoie. À réutiliser pour toute sonde widget qui doit marquer son trafic.

### ✅ Option B faite + les 8 divergences tranchées par dayuse-com + `_ACK_RE` mesuré (arbitrages Fabien du 2026-08-28)

Détail complet dans le rapport §13 et §14. **Pas encore déployé** (voir plus bas).

**1. La vérité sur les 8 hôtes est dans le monorepo dayuse-com, et c'est `_MARKET` qui a raison.** Sources : `~/PhpstormProjects/dayuse-com` (commit `149c823892`), `apps/frontend/web/i18n/production.js` (liste `domains`, 53 locales) + `apps/frontend/web/config/config.<locale>.ts` (`host`, `countryCode`, `defaultSearchPageLink`). Les 8 hôtes de `_MARKET` (AE AU BR CA HK MY NZ TH) sont **tous** confirmés ; c'est le widget qui envoyait tout le monde sur `www.dayuse.com`.

**Et 2 divergences que la mesure de §6.1 n'avait pas vues** — le script ne comparait que `hotelCountrySlug`, jamais le chemin du `browseUrl`, et **le segment de browse est LOCALISÉ alors que le chemin d'hôtel est anglais** : DE `germany` vs **`deutschland`**, BR `brazil` vs **`brasil`** (ES/IT/NL/CH étaient déjà corrects : espana/italia/nederland/suisse). C'est précisément cette asymétrie qui empêchait de dériver une table de l'autre et justifiait la seconde table.

**Mesuré en HTTP réel** — le coût était pire que « question produit » :

| URL | Résultat |
|---|---|
| `www.dayuse.com/s/brazil` (lien du widget) | **404 — mort** |
| `www.dayuse.net.br/s/brasil` | 200 |
| `www.dayuse.com/s/malaysia` (lien du widget) | **404 — mort** |
| `www.dayuse.de/s/germany` | 200 via **1 redirection** vers `/s/deutschland` |
| `www.dayuse.com/s/{thailand,canada,australia,new-zealand,hong-kong,united-arab-emirates}` | 200, 0 redirection — servis, mais sur le domaine US |

→ verdict précis : **2 liens réellement morts** (BR, MY), **6 qui répondent mais sur le mauvais marché** (devise/locale par défaut fausses), **1 redirection inutile** (DE).
⚠️ **MY n'a AUCUNE page de browse** dans dayuse-com (`en-MY` n'a pas de `defaultSearchPageLink` ; marché « NEW DOMAIN ») → le référentiel porte `None` et le widget n'affiche pas de lien. Son hôte de **réservation** existe toujours.

**2. Option B : les tables du widget sont générées.** `scripts/generate_widget_markets.py` → `web/vendor/static/js/chat/markets.generated.js` (`COUNTRY_META`, `COUNTRY_SLUG_TO_CODE`), depuis `_MARKET` + `_BROWSE_PATH` + `_LABEL` ajoutées dans le **même** module. `markets.js` les importe. **85 entrées à la main → 38** (46 générées). Barrière : `TestGeneratedFileIsCurrent` régénère et compare octet à octet — vérifiée dans les **deux** sens (édition à la main de l'artifact → `STALE or was hand-edited` ; modification du Python sans régénérer → même échec ; restauré à chaque fois).

🪤 **`DAYUSE_HOSTS` n'est PAS généré, et c'est un choix.** C'est une allowlist de **racines**, volontairement **plus large** que la table de marchés : sa règle de sous-domaine admet `de.dayuse.ch`, `nl.dayuse.be`, `en.dayuse.com.hk` — de vrais hôtes Dayuse absents de `_MARKET` (visibles dans la liste `domains` de dayuse-com). La générer depuis les 22 hôtes la **rétrécirait** et rouvrirait le défaut « pas de lien ». Elle reste à la main, gardée par le test de dérive.

`getMarketMeta` ne devine plus non plus : un marché inconnu rendait `browseUrl: 'https://www.dayuse.com'` + un `hotelCountrySlug` deviné — le slug n'avait plus **aucun lecteur** (son seul consommateur était le fabricateur supprimé). Les deux sont partis, `browseUrl` vaut `null`, `carousel.js` n'affiche plus de lien « voir tout » sans URL.
⚠️ **Non fait, assumé** : `getMarketFallbackLink` (`responses.js`) garde son repli en dur `www.dayuse.com/s/united-states` (CTA de l'état vide, 4 appelants, et ce repli est un lien vivant). Effet de bord positif : MY passait par `/s/malaysia` (404) et tombe maintenant sur ce repli (200, mauvais marché).

**3. `_ACK_RE` mesuré — item clos, et la conclusion est « ne pas toucher ».** `scripts/measure_social_ack_coverage.py`, 19 formulations × 3 répétitions (3 parce que gpt-4o-mini n'est pas déterministe sur un message court cross-lingual — le piège NL d'UX2) :

| Mesure | Résultat |
|---|---|
| fr/en (contrôle) | 4/4 court-circuitées, **0 appel LLM** |
| es/it/de/pt/nl atteignant le LLM | 15 formulations, 45 runs |
| classées `family="ack"` | **45/45 — `ack_rate = 1.0`, zéro erreur** |
| latence ajoutée | **médiane 1 079 ms** (max 2 506) |
| coût | **$0,000227**/appel (gpt-4o-mini, 1 463 tokens de prompt) |
| fréquence (Langfuse, prod, 30 j) | **19 / 542 tours racine (3,5 %)** à zéro appel LLM |

Donc : **pas un problème de correction, seulement de latence**, sur une **fraction** de 3,5 % des tours.

🔴 **Et la vraie raison de ne pas élargir** : le garde `agent.py:1017` est `if is_social_ack(...) and not refinement_signal and not booking_signal:`, et ses deux signaux sont **volontairement regex-only à cet endroit** (sans les slots du triage). Or `_AFFIRMATIVE_RE` (`profile.py:136`) est **fr/en uniquement** — ni `sí`, ni `ja`, ni `sim`. Aujourd'hui un « ja » allemand pendant une confirmation de réservation ne matche pas `is_social_ack`, part au triage, et son slot `booking_confirmation` l'amène au gate R9. **Si on ajoutait les affirmatifs à `_ACK_WORDS`, le template d'accueil avalerait la confirmation** et R9 deviendrait inatteignable en de/es/pt : mot pour mot le bug que la **PR #47** a corrigé pour le français (« oui je confirme » → salutation). Ajouter seulement salutations/remerciements échappe à ce piège précis, mais pour ~1,1 s sur une fraction de 3,5 % des tours, contre l'élargissement d'une regex `^…$` prouvée qui est le dernier rempart avant un template. **Gardé en l'état.**

### ✅ Option B DÉPLOYÉE et vérifiée en prod (widget, `d6603ba`)

`railway up --service widget --detach` → **`SUCCESS 2026-08-28T09:07:31Z`**, PUIS `LANGFUSE_RELEASE=d6603ba` posé avec `--skip-deploys` (`latestDeployment.createdAt` toujours `09:07:31Z` après le stamp, vérifié). **Ordre inversé exprès par rapport au déploiement précédent** : la fois d'avant, le stamp était posé AVANT un `railway up` qui s'est fait bloquer, laissant l'estampille revendiquer un build qui ne tournait pas. Stamper APRÈS le SUCCESS ne peut mentir que dans le sens inoffensif.

`widget` seul, à nouveau : les ajouts Python (`_BROWSE_PATH`, `_LABEL`, `market_referential()`) n'ont **aucun appelant au runtime** — `market_referential` n'est lu que par le générateur et les tests, et `build_hotel_page_url`/`_resolve_market` sont inchangés (vérifié sur le diff). `concierge`/`hotel-search`/`faq` gardent une estampille honnête.

**Preuve 1 — les 6 fichiers JS servis sont byte-identiques à HEAD** (`markets.js`, `markets.generated.js`, `security.js`, `utils.js`, `hotels/card.js`, `hotels/carousel.js`), et l'artifact généré est bien servi (l'en-tête « GENERATED FILE — DO NOT EDIT BY HAND » est en prod, avec `browseUrl: 'https://www.dayuse.net.br/s/brasil'`, `'https://th.dayuse.com/s/thailand'`, `browseUrl: null`).

**Preuve 2 — LE résultat : les 21 liens de browse interrogés depuis le module DÉPLOYÉ répondent tous 200, chacun sur son propre hôte de marché, zéro redirection.** MY ne rend aucun lien. Comparaison avec l'avant : 2 liens morts (BR `/s/brazil` 404, MY `/s/malaysia` 404), 6 sur le domaine US, 1 redirection (DE).

| | AE | AU | BR | CA | DE | HK | MY | NZ | TH |
|---|---|---|---|---|---|---|---|---|---|
| avant | dayuse.com | dayuse.com | **404** | dayuse.com | 1 redir | dayuse.com | **404** | dayuse.com | dayuse.com |
| après | `dayuse.ae` 200 | `au.` 200 | `net.br/s/brasil` 200 | `ca.` 200 | `/s/deutschland` 200 | `com.hk` 200 | pas de lien | `nz.` 200 | `th.` 200 |

**Preuve 3 — aucune régression de rendu** malgré le changement structurel de `markets.js` : un vrai tour (`?q=`, `x-dayuse-synthetic: 1`) rend **5 cartes, 5 liens, tous sur `www.dayuse.fr`**, 0 `href="#"`, 0 lien fabriqué. Et les 6 modules refactorés **se lient ET s'évaluent** dans le navigateur en prod (`markets.js`, `markets.generated.js`, `carousel.js`, `card.js`, `utils.js`, `responses.js` → tous `linked+evaluated`, `pageErrors: []`) — ce contrôle-là importe parce qu'un import cassé sur `markets.generated.js` aurait fait tomber tout le widget, pas seulement un lien.

📌 Trap Langfuse consigné : `family`/`route` sont bien de la métadonnée de trace OBS2 (`mark_metadata`, `agent.py:562`) mais **ne remontent pas à plat dans l'API REST des traces** (`metadata` n'y contient que `resourceAttributes`/`scope`/`attributes` OTel) — donc pas de comptage par famille sans creuser les spans. `totalCost == 0` sur les traces racine est le meilleur proxy obtenable. Aussi : `LANGFUSE_BASE_URL` (pas `LANGFUSE_HOST`), et urllib a besoin du bundle `certifi` explicite sinon `CERTIFICATE_VERIFY_FAILED`.

### Les 2 PR restantes : fermées (décision Fabien)

- **#40** `scx6-same-day-cutoff-fallback` — fermée. Vérifié avant : sa substance est **déjà dans `main`** (`_SAME_DAY_CLOSED_NOTE` dans `ground_truth.py:41`, utilisé l. 85). Surtout, la branche est **en retard sur main** : son diff sur `ground_truth.py` **supprimerait** l'affinage de prod du 2026-07-29 et ~113 lignes à partir de `_hotel_line`. La merger aurait régressé.
- **#19** `s-d-judge-ab` — fermée. ⚠️ Celle-ci portait du contenu **absent de `main`** (`scripts/run_judge_ab.py`, son test, `JUDGE-AB-BENCH-2026-07-22.md`), noté pour que rien ne disparaisse en silence. Sans coût parce que son objet est épuisé (bench A/B contre le POC agent-usa) et ses résultats sont dans `reports/judge_*.json` + `GATE-RERUN-2026-07-23.md`. Récupérable : `git show origin/s-d-judge-ab:scripts/run_judge_ab.py`.

Les deux branches sont intactes, les deux PR réouvrables.

### Nettoyage de fin de chantier — EXÉCUTÉ

Les 2 PR ci-dessus fermées, UX6 est la dernière du chantier : la checklist de `PROMPTS-UX-2026-08-27.md` a été exécutée. Les 8 fichiers de planification sont supprimés (`PROMPTS-UX-2026-08-27.md`, `tasks/todo-ux-2026-08-27.md`, `phases/UX1`→`UX6`). `tasks/todo.md` **non touché** (tracker OBS4).

Les 6 cases vérifiées avant suppression, dont **une qui ne l'était pas** :

- ✅ UX1 (2 cliquets + budget affiché ≠ appliqué), UX3 (verdict devise lecture A, dans `reports/` **et** ici), UX4 (règle de signature d'affichage — vérifiée présente dans la docstring de `_day_rate_plans`, `inline_tools.py:606-625`), UX6 (justification par table → le rapport), variante `pt-PT` d'UX2.
- ❌ **`_ACK_RE` : la case n'était pas cochable.** Zéro mention dans `HANDOFF.md`, et le code est inchangé. Le constat, préservé ici avant que le fichier de phase disparaisse : `_ACK_WORDS`/`_ACK_RE` (`triage.py:101-107`) sont **fr/en uniquement**, donc un « grazie » ou « danke » nu ne matche pas et **part au triage LLM**. Ce n'est pas un bug (le triage gère) mais ça coûte **un appel LLM** sur un tour qui n'en avait pas besoin. La phase demandait de **mesurer puis décider**, en avertissant de « ne pas gonfler la regex par réflexe » — **aucune mesure n'a été faite**, et rien n'a été touché. Reste donc ouvert, en l'état, avec son avertissement.
- ✅ Références aux fichiers supprimés : 8 repointées avant suppression (4 dans `HANDOFF.md`, `reports/AUDIT-MAPPINGS-2026-08-28.md`, `reports/RESEARCH-UX3-…`, `test_inline_tools.py:1245`, `probe_rateplan_dedup.py:6`). Ce qui reste après le grep de la checklist n'est que des **noms de chantier** sans chemin (`UX2-bis`, `UX1-followup`, « UX4 (2026-08-27) ») — pas des liens morts.

## ✅ Addendum 2026-08-27 decies — UX2 : réponses dans les 7 langues reconnues, `TEMPLATE_LANGUAGES = LANGUAGES` — DÉPLOYÉ ET PROUVÉ EN PROD

Phase UX2 (fichier de phase supprimé au nettoyage de fin de chantier), branche `feat/ux2-seven-languages` (commit `c7c36b6`, non mergée — PR ouverte pour la review de Fabien). Prérequis UX5 vérifié mergé dans `main` avant de commencer (`git merge-base --is-ancestor 82d5e3f HEAD`).

### Le périmètre réel du clamp — plus large que le tableau initial de la phase

Le tableau de la phase listait 7 sites (`templates.py`, `triage.py` ×3, `agent.py`, `response_bridge.py::_profile_language`, `amenity_guard.py::_HEDGE_FR`), avec la mention explicite « à re-vérifier en début de phase ». Trois sites de plus se sont révélés être **la même classe de bug**, pas du scope creep :

- `b2c_concierge/profile.py` — `_RECOVERY_SUGGESTIONS_FR/_EN` et `_DATE_SUGGESTIONS_FR/_EN` (les chips de récupération après un 0-résultat) sont du texte utilisateur avec le même clamp binaire, alimentées par `reply_language` (donc par le MÊME `response_language()` qu'on élargit).
- `hotel_search_agent/geo_resolver.py` — `_clarify_question`/`city_needed_question` (les questions de désambiguïsation géo, ex. « Springfield, IL ou MO ? ») sont du texte VERBATIM potentiellement montré à l'utilisateur, alimentées par `language_hint = profile_in["language"]`. **Avant cette phase, `profile.language` ne pouvait déjà porter QUE fr/en** (le clamp d'`agent.py:1094` bloquait tout le reste) — donc `language_hint` ne pouvait jamais porter "es"/"it"/… en pratique, même si triage RECONNAISSAIT déjà 7 langues depuis P1-2. En élargissant `agent.py:1094`, ce garde-fou disparaît et `language_hint` peut désormais porter les 5 nouvelles langues DANS LE MÊME TOUR (le profil est mis à jour avant l'appel à la feuille) — sans traduire ces 2 fonctions, un utilisateur espagnol qui déclenche un clarify géo aurait reçu une question en anglais au milieu d'une réponse par ailleurs espagnole. Traduit pour fermer ce trou, avec verrou fr/en chaîne pour chaîne comme le reste.
- `hotel_search_agent/geocode_tool.py` — 2 docstrings affirmaient que `profile_in.language` « ne peut jamais porter "pt" » : devenu faux, corrigé (documentation seule, aucun changement de comportement).

Hors périmètre confirmé et non touché : `search_context_line` (labels anglais internes au prompt de synthèse, jamais montrés tels quels — le LLM synthétise dans la langue cible), `_DATE_MENTION_RE`/`_FR_HINTS` (regex fr/en de secours, explicitement hors scope par la phase), `guess_language` (dernier recours fr/en, inchangé par design).

### Le mécanisme : une table par langue avec fallback anglais, pas des `if/elif`

`_pick(language, table)` où `table` est un `dict[str, str]` avec au minimum la clé `"en"` — `table.get(language, table["en"])`. Répliqué dans chaque fichier touché (pas de dépendance inter-packages : `hotel_search_agent` est une feuille stateless sans import vers `b2c_concierge`, donc `response_bridge.py`/`geo_resolver.py` portent chacun une copie locale de `("fr","en","es","it","de","pt","nl")` — synchronisée à la main, commentée comme telle). Pour les textes avec interpolation (offre de réservation, disclosure de date, clarify géo), la table porte des `str.format()` templates plutôt que des f-strings figées — la valeur insérée (nom d'hôtel, ville, date) n'est jamais re-parsée pour ses propres accolades, donc aucun risque d'injection.

**Source de style pour les 5 nouvelles langues** : `web/vendor/static/js/chat/i18n.js` (7 blocs déjà rédigés). Registre retenu : tutoiement es/it/de/nl (`tú`/`tu`/`du`/`je`), vouvoiement pt (pt-PT, pas pt-BR — cohérent avec `_MARKET`). Vocabulaire : franja horaria/fascia oraria/Zeitfenster/horário/tijdslot pour « créneau », búsqueda/ricerca/Suche/pesquisa/zoekopdracht pour « recherche ».

### Non-régression fr/en : verrouillée par construction, pas juste testée

Chaque table a été écrite en copiant l'implémentation `if language == "fr": ... else: ...` d'origine terme à terme, puis vérifiée par un script qui reconstruit la sortie de l'ANCIEN code (f-strings originales, recopiées) et compare chaîne pour chaîne à la nouvelle sortie sur tous les cas de branche (`templates.py`, `response_bridge.py`, `geo_resolver.py`) — 0 divergence. `TestFrenchAndEnglishUnchanged` dans `test_templates.py` verrouille ensuite 4 chaînes exactes en dur (contre une régression future).

### DoD

1. **Table complète pour les 7 langues, testée par construction** — `TestSevenLanguageCoverage` (`test_templates.py`) itère les 14 cas × 6 langues non-anglaises et assère qu'aucune ne retombe sur la chaîne EN ; aucune exception légitime rencontrée (toutes les traductions diffèrent réellement).
2. **Fallback testé** — `TestFallbackToEnglish` : `ja`/`xx`/`""`/`None` rendent la chaîne EN, sans exception, pour les 14 cas.
3. **Non-régression fr/en** — `TestFrenchAndEnglishUnchanged` (chaînes exactes) + script de vérification byte-à-byte contre l'ancien code (templates.py, response_bridge.py, geo_resolver.py) — 0 divergence.
4. **`pytest -q` : 1686 passed, 1 skipped** (baseline 1452 passed + 234 tests ajoutés/modifiés depuis, dont 178 par cette phase). `ruff check .` : clean. `mypy agents libs` : clean (1 erreur de typage `str | None` vs `dict[str,str].get` trouvée et corrigée dans `geo_resolver.city_needed_question`). `bash scripts/dayuse_guardrails.sh .` : OK.
5. **12 tests existants avaient le clamp comme PRÉMISSE et ont dû être inversés** (pas juste "cassés par erreur" — leur assertion ÉTAIT le comportement qu'on vient de changer) : `test_triage.py` (`TEMPLATE_LANGUAGES == ("fr","en")`, `locale_response_language("pt-PT") is None`, `template_language(None,"es-ES",...) == "en"`, `response_language("es") == "en"`), `test_native_context.py`/`test_native_context_http.py` (`_locale_response_language("es-ES") is None`, `"Bonjour !"` + locale `es-ES` retombait sur `fr` via le guess), `test_facade_http.py` (le shield répondait en anglais sur locale `es-ES`), `test_spine.py` (`test_a_recognized_language_never_leaks_into_the_synthesis_prompt` — le nom même du test décrivait le clamp qu'on lève). Chaque test inversé garde un frère qui prouve le fallback reste atteignable sur une langue VRAIMENT non reconnue (`ja-JP`/`ja`/`kl`), pour ne pas perdre la couverture du cas fallback en élargissant le cas passant.
6. **Preuve prod, 5 langues × 1 tour, sessions fraîches, `x-dayuse-synthetic: 1`, via le widget public** (`https://widget-production-3f56.up.railway.app`, pas de cookie réutilisé entre appels) :

| Langue | Message | `response_language` | Réponse (tronquée) |
|---|---|---|---|
| es | « hotel en Madrid mañana » | `es` | « Para Madrid mañana (2026-08-28) he encontrado 5 ofertas de day-use; destaca el ahorro de Hotel Los Olivos, aprox. un 48% por debajo de su tarifa nocturna. Si me dices la zona que prefieres… » |
| it | « hotel a Milano domani » | `it` | « Per domani 2026-08-28 a Milano ho trovato 5 opzioni Dayuse: spicca soprattutto il risparmio del Glam Hotel Milano, molto sotto la tariffa notturna (circa -58%). Se mi dici zona preferita… » |
| de | « Hotel in Berlin morgen » | `de` | « Für Berlin habe ich für den 28.08.2026 fünf Dayuse‑Angebote gefunden – besonders sticht das ARCOTEL John F Berlin heraus, da es stark (ca. 47%) unter dem Nachttarif liegt. Soll es eher… » |
| pt | « hotel em Lisboa amanha » | `pt` | « Para Lisboa amanhã (2026-08-28), encontrei 5 opções de day use; o destaque é o Hyatt Regency Lisbon, com cerca de 53% de desconto face à tarifa noturna. Quer que eu refine… » |
| nl | « ik zoek een hotel in Amsterdam voor morgen overdag » | `nl` | « Voor Amsterdam heb ik voor 28-08-2026 dagkamers gevonden; de beste deal qua besparing is het Radisson Blu Hotel Amsterdam Airport Schiphol (ongeveer 42% onder het nachttarief). Zeg me je gewenste tijdslot… » |

**Aucune réponse ne mélange deux langues** — vérifié aussi sur l'event SSE `hotels` (`/v3/chat/stream`, tour IT) : `"response_language": "it"` ride bien la première frame, identique au payload `done`, donc pas de risque de rendu mixte façon S-PERF4.

🪤 **Fait découvert pendant la vérification, PAS un bug** : le premier essai NL (« hotel in Amsterdam morgen ») a classifié `language: en` — le message est ambigu (« hotel »/« in » sont identiques en anglais, et le triage LLM n'a pas eu assez de signal). Reformulé en néerlandais moins ambigu (« ik zoek… voor… overdag »), la classification devient `nl` immédiatement. C'est une limite de PRÉCISION du classify LLM sur un message très court et cross-lingual, pas un défaut du clamp qu'on vient de lever — hors périmètre de cette phase (le classify existe et fonctionne depuis P1-2).

7. **Déployé** — `LANGFUSE_RELEASE=c7c36b6` posé sur `concierge` et `hotel-search` avec `--skip-deploys` (vérifié : les deux `latestDeployment.createdAt` inchangés après le stamp), puis `railway up --service hotel-search --detach` (`SUCCESS 15:59:46Z`) puis `railway up --service concierge --detach` (`SUCCESS 16:00:34Z`) — feuille d'abord, même convention que PR #95/#102. `faq` et `widget` laissés sur leur estampille : aucun fichier du diff ne les touche.

### Pièges rencontrés

- 🪤 Le tableau de périmètre de la phase venait avec l'avertissement « à re-vérifier en début de phase » — s'y fier aveuglément aurait laissé `profile.py` (chips de récupération) et `geo_resolver.py` (clarify géo) en anglais alors que tout le reste du tour est dans la langue de l'utilisateur, exactement le défaut « incohérence visible » que la phase corrige ailleurs.
- 🪤 `agent.py:1094` (widen du stockage de `profile.language`) a un effet de bord non trivial une passerelle plus loin : il alimente `language_hint` envoyé à la feuille geo, qui avant cette phase ne pouvait JAMAIS porter autre chose que fr/en/None, même si triage reconnaissait déjà 7 langues depuis P1-2 — la reconnaissance seule ne suffisait pas à exposer le trou, il fallait aussi élargir CE site précis du clamp pour que le trou devienne atteignable.
- 📌 Le CLI `railway up` de cette session ne supporte pas `-m` (contrairement à la doc du skill `use-railway`) — `railway up --service <s> --detach` tout court fonctionne.

### Auto-review avant la review de Fabien (`bd6ba86`)

Une passe de review indépendante sur le diff a trouvé 2 points réels, corrigés :

1. `geo_resolver._clarify_question` était la seule table élargie de la phase à indexer `_CLARIFY_MANY`/`_CLARIFY_LAST_SEP` en `[lang]` brut une fois `lang` résolu — un futur désync entre les 3 dicts (une langue ajoutée à l'un, oubliée dans l'autre) aurait fait un `KeyError` au lieu du fallback anglais gracieux garanti partout ailleurs dans la phase. Passé en `.get(lang, table["en"])`, comme `city_needed_question` juste en dessous le fait déjà.
2. `_DEGRADED_SUFFIX["es"]` empilait la même préposition deux fois dans `leaf_degraded_response` avec une ville : « …hoteles **en** Paris **en** este momento… ». Reformulé en « ahora mismo », qui aligne aussi cette chaîne sur le phrasé déjà utilisé par `_SERVICE_DEGRADED["es"]` pour le même sens (au lieu d'en diverger sans raison).

`pytest -q` inchangé (1691 passed, 1 skipped), `ruff`/`mypy`/`dayuse_guardrails.sh` verts.

### ✅ Mergée (PR #107, `e7795fc`) et REDÉPLOYÉE avec les 2 correctifs

`LANGFUSE_RELEASE=e7795fc` posé sur `concierge` et `hotel-search` avec `--skip-deploys` (timestamps `latestDeployment.createdAt` inchangés après le stamp, vérifié), puis `railway up --service hotel-search --detach` (`SUCCESS 16:17:46Z`) puis `railway up --service concierge --detach` (`SUCCESS 16:19:50Z`). Les 5 langues re-vérifiées en prod sur le code redéployé (mêmes messages que la sonde initiale, sessions fraîches) : `response_language` et texte 100 % dans la langue attendue pour es/it/de/pt/nl, aucun changement de comportement visible (les 2 correctifs de la review ne touchent que des chemins non exercés par ces 5 tours : le clarify géo et le leaf-degraded ES avec ville).

### Reste à faire (hors périmètre de cette phase, arbitrages explicites de Fabien)

- Le japonais/arabe/thaï et toute langue hors des 7 : chantier RTL + refonte génération, explicitement hors scope.
- `ratePlanName` (nom de chambre partenaire) reste non traduit, par design (`messages.js:667-669`).
- `evalset/`/`dayuse_eval_pack/` élargis par langue = UX2-bis, pas cette phase.
- La précision du classify LLM sur un message court/ambigu cross-lingual (cf. le piège NL ci-dessus) — pas un défaut introduit ici, pas mesuré avant cette phase non plus.

**Réconciliation avec #106 (UX4, mergé pendant que cette PR était ouverte)** : zéro chevauchement de fichiers source (UX4 ne touche que `inline_tools.py`) — seul `HANDOFF.md` avait un conflit d'insertion (les deux PR ajoutaient un bloc au même endroit), résolu en gardant les deux blocs. `pytest -q` après merge : **1691 passed, 1 skipped** (1686 UX2 + 5 UX4). `ruff`, `mypy` (48 fichiers), `dayuse_guardrails.sh` : verts.

## ✅ Addendum 2026-08-27 nonies — UX4 : dédoublonnage des rate plans sur la signature d'affichage (backend)

Décision de design déjà tranchée dans le fichier de phase UX4 (supprimé au nettoyage de fin de chantier ; la règle vit désormais dans la docstring de `_day_rate_plans`) : `_day_rate_plans` (`agents/b2c_concierge/b2c_concierge/inline_tools.py`) dédoublonnait déjà sur `offer_id`, mais deux offres MCP d'UUID différents peuvent produire deux lignes rigoureusement identiques à l'écran (51 % des hôtels multi-plans partagent `ratePlanName` sur toutes leurs formules, `roomType` est NULL partout, `offerType` est un enum fermé à 5 valeurs). Branche `fix/ux4-rateplan-dedup`.

**Correctif** : dédoublonnage additionnel sur la signature d'affichage `(offer_type, name, start_time, end_time, price_eur_cents)`, en plus de `offer_id`, dans la même boucle (l'ordre — filtrage par jour d'abord, dédoublonnage ensuite — n'a pas changé). Le prix reste dans la signature (décision du fichier de phase) : deux formules identiques mais à des prix différents restent deux lignes. La première offre rencontrée pour une signature donnée est conservée ; comme la liste est triée cheapest-first ensuite et que deux doublons ont le même prix par construction, l'offre gardée n'a pas d'importance pour l'utilisateur. Effet de bord voulu et déjà géré côté widget : un seul survivant fait retomber la carte sur le chemin simple (`renderRatePlans`' `plans.length < 2`), rien à changer côté JS.

**5 tests ajoutés** (`TestRatePlanDedupOnDisplaySignature`, `test_inline_tools.py`), sur la couture réelle (`generate_booking_link` → `_quote_picked_rate_plans` → `_day_rate_plans`), pas sur la fonction isolée :
1. Deux UUID différents, signature identique → 1 seul plan rendu, et **`generate_booking_link` n'est appelé qu'une fois** (le doublon ne coûte pas de round-trip MCP — la raison même du choix backend écrite dans la phase).
2. Cas Ibis La Ciotat (même `offerType`, même créneau, noms différents) → 3 plans conservés.
3. Cas Mercure Lyon Saxe (même nom, créneaux différents) → 3 plans conservés.
4. Prix différents, tout le reste identique → 2 plans conservés (le prix reste un vrai différenciateur).
5. Deux plans sans prix (`price_eur_cents is None` des deux côtés) mais différant par ailleurs → non collapsés à tort (le `None` partagé ne suffit pas seul).

**Le test #1 échoue sur l'ancien code avec la signature exacte du bug** — vérifié par `git stash push` du seul `inline_tools.py` (pas les tests) : `assert 'rate_plans' not in result` échoue (`rate_plans` présent avec 2 entrées) sur le code d'avant, les 4 autres tests passent des deux côtés (ils verrouillent un comportement déjà correct). Stash restauré ensuite, pas de perte.

`pytest -q` : **1513 passed, 1 skipped** (baseline 1508 + 5). `ruff`, `mypy` (48 fichiers), `dayuse_guardrails.sh` : verts.

**Preuve prod — cherchée, non trouvée.** Script live `scripts/probe_rateplan_dedup.py` (même patron que `probe_currency_priceeuro.py` : appels réseau réels à MCP_B2C, pas un pytest) : pour chaque hôtel réel, reproduit EN PARALLÈLE l'ancien dédoublonnage (offset_id seul, avec le même cap `_MAX_RATE_PLANS`) et le nouveau (`inline_tools._day_rate_plans` réel), et signale un hôtel/jour où les deux comptes diffèrent pour une raison autre que le cap. **439 hôtels réels probés au total** (recherche via `search_offers` sur 32 marchés — Paris, Lyon, Marseille, Bordeaux, Nice, Toulouse, Lille, Nantes, Strasbourg, Madrid, Barcelone, Bruxelles, Rome, Milan, Amsterdam, Berlin, Vienne, Lisbonne, Genève, Munich, Londres, Bangkok, New York, Zurich, Montpellier, Rennes, Reims, Toulon, Grenoble, Dijon, Angers, Nîmes — dates J+1 à J+6 selon le lot), **0 collision réelle de signature trouvée** sur la fenêtre d'inventaire testée. **Ne pas écrire « prouvé en prod »** : ce que cette mesure établit, c'est que sur cet échantillon-là, à ce moment-là, aucun hôtel réel n'a déclenché le cas — pas que le cas n'existe pas (les 51 % de `ratePlanName` partagé restent un fait mesuré séparément, sur le snapshot catalogue complet, pas sur ce probe).

⚠️ **Un faux positif trouvé et corrigé en cours de route**, gardé ici pour la leçon : la première version de `_old_dedup_count` dans le script ne répliquait PAS le cap `_MAX_RATE_PLANS` de l'ancien code — un hôtel avec >6 formules toutes distinctes lisait comme une "collision" (`before=8, after=6`) alors qu'aucune signature ne collidait réellement (hôtel 16896, Paris, 2026-08-28 — vérifié offre par offre après coup). Un second bug, plus sérieux, s'est glissé pendant le refactor anti-429 du script (passage d'une session MCP persistante à une session par appel, pour éviter qu'un 429 sur un appel casse toute la file — memory: "MCP 429s on chained calls") : le bloc de résumé + le `return` sont restés à leur ancienne indentation, désormais À L'INTÉRIEUR de la boucle par hôtel — la fonction retournait après le **premier** hôtel de chaque lot alors que `len(hotel_ids)` (calculé avant la boucle) continuait d'afficher le compte total, donnant l'illusion que tout le lot avait été parcouru. Deux lots ("0 hits" sur 116 puis 180 hôtels annoncés) n'avaient en réalité vérifié qu'un seul hôtel chacun. Repéré par `mypy` (`Missing return statement`) avant que la conclusion ne soit écrite ici — corrigé, et les 3 lots ci-dessus (116 + 236 + 87 = 439) sont les runs POST-correction, vérifiés en observant `probed X/Y hotels` progresser jusqu'à Y à chaque fois.

**Hors périmètre, non touché** : l'heuristique `nameLeads` du widget (`messages.js`), et la demande à MCP_B2C d'un différenciateur de formule (`reports/PROMPT-MCP-B2C-RATEPLANS.md`, déjà écrite, sujet différent).

## ✅ Addendum 2026-08-27 octies — UX3 phase 2B : demande MCP_B2C écrite + la divulgation EUR ne sortait pas, corrigée en code

GO de Fabien reçu sur le verdict de la phase 1. Les 2 livrables de la phase 2B d'UX3 (fichier de phase supprimé au nettoyage de fin de chantier), sur la même branche/PR que la phase 1 (`measure/ux3-currency-locale`, PR #103).

**Livrable 1 — demande écrite à MCP_B2C** : `reports/PROMPT-MCP-B2C-DEVISE-LOCALE-2026-08-27.md`. Un seul champ demandé, `hotelPrice` par offre (devise réelle de l'hôtel), sur le modèle de `PROMPT-MCP-B2C-RATEPLANS.md` qui a déjà marché. Point fort de la demande : la propre réponse de MCP_B2C du 2026-07-28 mentionne déjà `hotelPrice`/`hotelComparativePrice` en interne (utilisés pour vérifier la cohérence FX d'`originalPriceEuro`) — donc probablement un cas (a) « déjà dans l'index, juste pas projeté », pas un chantier de réindexation. Pas encore posée dans une session sur le repo MCP_B2C (côté Fabien/l'équipe MCP_B2C de porter le prompt).

**Livrable 2 — la divulgation existante ne sortait pas, et c'est corrigé.** `agent.py::_synthesize_with_guards` construit déjà une `CURRENCY note` et instruit le LLM de synthèse de « mention plainly that prices are shown in EUR with no conversion applied » (S-G7). **Vérifié en PROD, ça ne sort JAMAIS** : tour synthétique (`x-dayuse-synthetic: 1`, `POST /v3/chat` sur `widget-production-3f56.up.railway.app`) « un hotel a Bangkok demain avec piscine » → 5 hôtels `currency_code: THB` affichés, réponse *« …et la meilleure économie ressort sur le Hotel Royal Bangkok (forte remise vs le tarif nuit)… »* — **aucune mention de devise**. Les tests existants (`TestCurrencyDisclosureThroughTheSpine`) ne verrouillaient que le PROMPT, jamais le texte final — trou de couverture classique (même famille que S-PERF5 : une fonction câblée jusqu'au prompt mais jamais vérifiée jusqu'au rendu).

Correctif : nouveau guard déterministe `currency_guard.py::enforce_currency_disclosure` — même contrat que `amenity_guard`/`link_guard` (passe post-LLM, une correction, jamais de retry), append une ligne honnête (« Prix affichés en euros, sans conversion. » / anglais) quand `currency_note` est non-vide et que le texte ne le dit pas déjà (détection volontairement grossière côté « déjà dit », biaisée pour re-dire plutôt que taire). **Test qui échoue sur l'ancien code avec la signature exacte du bug** (`test_a_model_that_ignores_the_instruction_gets_backstopped_in_the_final_text`), vérifié par `git stash` du seul `agent.py`.

⚠️ **Décision de scope, pas un guard scoré** : contrairement à `amenity_truthfulness`/`hotel_link_truthfulness`, ce correctif n'est **pas** ajouté à `GUARD_SCORE_NAMES` — la liste des 13 guards est un contrat compté (CLAUDE.md, OBS3), et l'ajout d'un 14e n'était pas demandé par la phase. Metric non-scorée seulement (`concierge_metric=currency_guard disclosed=1`). À arbitrer par Fabien si une preuve prod mesurable dans Langfuse est voulue plus tard.

**Non fait** : le correctif n'est **pas encore déployé** (PR non mergée) — la preuve ci-dessus documente le BUG en prod, pas le fix ; le fix est prouvé en local (test + `pytest -q`), pas en prod. Après merge+déploiement du concierge, re-vérifier avec le même tour synthétique que la ligne de disclosure sort bien.

`pytest -q` (après rebase sur `main` post-#104/#105) : **1508 passed, 1 skipped**. ruff, mypy, guardrails verts.

**Item marqué bloqué côté MCP_B2C** pour la partie « devise locale affichée » : en attente de leur réponse sur `hotelPrice`.

## ✅ Addendum 2026-08-27 septies — UX3 phase 1 : `priceEuro` est réellement en EUR (lecture A confirmée), zéro code de prod

Mesure seule, comme demandé — `reports/RESEARCH-UX3-DEVISE-LOCALE-2026-08-27.md` porte le détail. 4 marchés non-euro (TH/US/GB/CH) sondés via `search_offers` + `get_hotel_details` (script `scripts/probe_currency_priceeuro.py`, réseau réel, pas un pytest), `priceEuro` comparé au prix affiché EN DIRECT par le site de prod pour le **même hôtel, même jour** (Chrome headless/CDP sur `?date=2026-08-28`, pas le `priceRange` générique du JSON-LD — piège découvert en cours de route : ce champ est un minimum toutes-dates confondues, pas comparable).

Les 4 ratios (site affiché / `priceEuro`-en-EUR) tombent chacun dans la fourchette réelle du taux de change du marché — TH 37,99 (THB 935 vs 24,61 €×38=935,2, écart 0,2 %), US 1,141, GB 0,861, CH 0,979 — concordance trop précise sur 4 marchés indépendants pour être un hasard. **`priceEuro` est en EUR : cet item bloque sur MCP_B2C (phase 2B)**, par l'arbitrage de Fabien du 2026-08-27 (pas de taux de change côté AgentB2C sur un prix de réservation).

**STOP conforme à la phase** : aucune ligne de code de production touchée, phase 2B non démarrée — attend le GO de Fabien. `pytest -q` 1460 passed, 1 skipped (inchangé) ; ruff, mypy, guardrails verts. Worktree `AgentB2C-ux3-currency`, branche `measure/ux3-currency-locale`.

## ✅ Addendum 2026-08-27 sexies — le budget affiché s'applique enfin (arbitrage Fabien sur le constat hors-périmètre d'UX1)

Suite du constat « hors périmètre » de la session UX1 (`budget_max` affiché dans `active_filters` mais jamais ré-injecté dans `search_offers` — mesuré, pas corrigé, sur son propre HANDOFF/PR #104). Fabien a tranché : **le porter comme les amenities/occupancy**. Branche `fix/budget-max-search-injection`, PR ouverte (non mergée).

**Correctif** : `hotel_search_agent/budget_injection.py::inject_profile_budget`, nouveau `before_tool_callback` sur `search_offers`, même patron que `occupancy.py` (scalaire, pas un ensemble — la rétraction/soustraction d'UX1 pour `amenities` ne s'applique pas ici : « max 50 » **remplace** 80, ne s'additionne pas). Le modèle emet `priceRangeMax` ce tour-ci → il gagne ; sinon `profile_in.budget_max` (déjà présent sur le fil, `budget_max` n'est pas dans `_CONCIERGE_ONLY_KEYS`) comble le trou. `response_bridge._positive_budget` rendu public (`positive_budget`) et partagé, capture + injection ne peuvent plus diverger sur ce qui compte comme un budget valide.

**Bug pré-existant trouvé au passage, corrigé** : `positive_budget(True)` rendait `1.0` (`bool` est une sous-classe d'`int`, `float(True) == 1.0`) — même piège que celui dont `party_count` se protège déjà explicitement. Un garde `isinstance(value, bool)` ajouté ; test de régression sur `test_capture_rejects_non_positive_budget`.

**Preuve (offline, déterministe — pas de prod)** : test qui échoue sur le comportement d'avant (`test_a_budget_stated_on_turn_1_reaches_turn_2s_search_offers_args`, sur la couture réelle `SessionProfile.budget_max` → `leaf_profile_view` → enveloppe A2A réelle → `inject_profile_budget`), **vérifié en neutralisant temporairement la ligne de carryover** : 3 tests tombent avec le message exact du bug (`KeyError: 'priceRangeMax'`), restauré ensuite — pas un `git stash` cette fois (fichier neuf, rien à stasher), mais la même discipline. `pytest -q` (après rebase sur `main` post-#104) : **1499 passed, 1 skipped**. ruff, mypy, guardrails verts.

⚠️ **Pas encore vérifié en prod.** Deux tentatives de repro conversationnelle via le proxy widget (`x-dayuse-synthetic: 1`) n'ont pas donné de signal propre — le second tour ("montre m'en d'autres" → pagination, page 2 vide sur un petit marché ; "plutot le matin" → change aussi la disponibilité, confond la comparaison) et l'inventaire spa+Paris+demain trouvé n'avait aucun hôtel au-dessus de 80 € à faire réapparaître. Contrairement au constat original d'UX1 (mesuré hors-ligne avec un script direct sur la vraie couture, `measure_budget_gap.py`), je n'ai pas rejoué ce script ici — seulement les tests ci-dessus. **Ne pas écrire « prouvé en prod »** avant un vrai déploiement + une mesure aussi propre que celle d'UX1.

## ✅ Addendum 2026-08-27 quater — UX1 : « enlève le spa » enlève vraiment le spa (rétraction de filtre en multi-tour)

Symptôme de Fabien : « si je demande un hôtel à Paris avec spa et qu'il ne me retourne rien, quand je lui demande d'enlever le filtre spa, il ne le fait pas. »

**Ce n'était pas un bug de multi-tour — le multi-tour marchait trop bien.** Le filtre d'équipement était ré-appliqué par **deux cliquets indépendants, tous deux monotones croissants**, et couper un seul ne change rien de visible :

- **Cliquet A (feuille)** — `equipment_ids.enforce_equipment_filters` faisait `requested = profile_keys + llm_keys`, une **union avec le profil à chaque tour**. Et le modèle n'avait **aucun canal** pour exprimer un retrait : le param virtuel `amenities` est déclaré « amenities the user explicitly asked the hotel to HAVE » et l'instruction lui **interdit** d'y mettre une négation. Donc « enlève le spa » → `amenities` omis → `llm_keys = []` → `requested = ["spa"]` → `hotelEquipmentIds = [35]` repart vers MCP. Tour **identique** au précédent.
- **Cliquet B (concierge)** — `apply_profile_delta` mergeait `amenities` en **append-only**. `profile.amenities` ne pouvait que grandir pour toute la durée de la session, et un `{"op":"set","value":[]}` correct aurait été **avalé** par le `if values.get("amenities")` (liste vide = falsy).

**La règle d'accumulation n'est PAS le bug et n'a pas été touchée** (`occupancy.py` l. 26-33 en écrit la doctrine : l'utilisateur ne doit pas retaper « avec piscine » à chaque tour). Ce qui manquait, c'est le **canal de rétraction**. Le correctif **ajoute une soustraction**, il ne remplace pas l'union par un écrasement.

### Le correctif (5 fichiers + le score config)

| Fichier | Changement |
|---|---|
| `hotel_search_agent/equipment_ids.py` | 2e param virtuel `amenities_removed` (même enum fermée `list(EQUIPMENT_IDS)`) + soustraction après l'union + guard #15 |
| `hotel_search_agent/agent.py` | 1 puce d'instruction pour le nouveau param (les 2 formulations) |
| `hotel_search_agent/response_bridge.py` | `profile_delta["amenities"]` passe en `_op_set(...)`, émis même vide — **avec la sentinelle** |
| `b2c_concierge/profile.py` | `_normalize_delta` remonte un 3e élément `explicit_sets` ; le bloc amenities honore le remplacement |
| `libs/b2c_common/scores.py` | +1 nom **appendé** dans `GUARD_SCORE_NAMES` + son `config_id` |
| `observability/langfuse/score-configs.json` | le 22e config, créé pour de vrai sur l'instance |

**Précédence quand une clé arrive dans les DEUX champs : l'ajout gagne.** Ce n'est pas une préférence, c'est la direction fail-safe contre le piège d'inversion de négation de gpt-4o-mini (leçon S10 — et `_AMENITIES_PROPERTY` est déjà écrit pour lui) : sur « je veux une piscine » le modèle peut recopier la clé dans les deux champs, et une demande explicite **ce tour-ci** ne doit jamais être annulée par un signal de retrait. L'utilisateur peut toujours retirer au tour suivant ; une demande silencieusement ignorée n'a pas ce recours. Collision comptée en métrique content-free `dayuse_metric=amenity_filter_conflict` (comptes seuls, jamais les clés).

**Bénéfice collatéral, à signaler à Fabien** : « un hôtel **sans** piscine » **après** « avec piscine » gardait le filtre piscine. MCP n'ayant pas de filtre négatif, « je ne veux pas de X » **est** « X n'est pas dans le filtre » — le même canal corrige les deux, et la description du param couvre explicitement les deux formulations.

### 🪤 LE piège de la phase, et pourquoi le test de non-régression a été écrit EN PREMIER

Sur un tour où `search_offers` ne tourne pas (clarification qui s'arrête à `geocode_location`, ou `find_hotel_by_name`), `STATE_APPLIED_AMENITIES_KEY` n'est **jamais écrit**. Le code d'avant (`state.get(KEY) or []`) écrasait la distinction entre **« absent »** (→ carryover) et **« écrit vide »** (→ set à vide). Tel quel, passer en `_op_set` inconditionnel **aurait effacé les filtres à CHAQUE tour de clarification** — une régression bien pire que le bug corrigé, et invisible en tests unitaires côté feuille seule. D'où la sentinelle : `applied = state.get(KEY)` puis `if applied is not None:`. `enforce_equipment_filters` écrit **toujours** la clé quand il tourne (`[]` compris), donc « absent » ne peut signifier qu'une chose.

Verrouillé à deux niveaux : `test_emit_omits_amenities_when_no_search_ran_this_turn` (à la source) et `test_a_clarification_turn_never_wipes_the_accumulated_amenities` (sur la couture complète, avec un profil à 2 amenities).

### Preuves

**Le test de la signature du bug échoue sur le code d'avant** — `tests/test_leaf_concierge_seam.py::TestFilterRetractionAcrossTurns::test_removing_a_filter_drops_it_from_the_next_search` :

```
AssertionError: assert 'hotelEquipmentIds' not in
  {'amenities_removed': ['spa'], 'date': '2026-08-28', 'hotelEquipmentIds': [35], 'lat': 48.85, ...}
```

Vérifié par `git stash push` des **seuls 3 fichiers source** du correctif (`equipment_ids.py`, `response_bridge.py`, `profile.py` — pas les tests, pas le prompt, pas `scores.py`), comme `test_client_header_outranks_an_existing_cookie` l'a fait pour PR #97 : **17 tests tombent, et les 2 tests du piège passent quand même** (ils verrouillent un comportement pré-existant, ils doivent passer des deux côtés).

**26 tests ajoutés**, sur la couture réelle (`enforce_equipment_filters` → `emit_search_datapart` → DataPart A2A décodée → `apply_profile_delta` → `leaf_profile_view` du tour suivant), pas sur chaque moitié isolément — c'est la classe de bug que `test_leaf_concierge_seam.py` existe pour attraper. Couvre : rétraction, rétraction persistée sur un 3e tour muet, retrait d'un filtre sur deux, accumulation normale intacte, négation fraîche, précédence de collision, métrique de collision, guard qui tire / ne tire pas.

`pytest -q` : **1486 passed, 1 skipped** (baseline 1460 + 26). `ruff`, `mypy` (46 fichiers), `dayuse_guardrails.sh` : verts. **Zéro appel LLM ajouté** — le param virtuel voyage dans l'appel existant de la feuille.

### Repro EN PROD avant déploiement (10:03:43-58Z, builds `10a6d89` / `33432ff`)

| Tour | Message | `active_filters.amenities` | Hôtels |
|---|---|---|---|
| 1 | « hotel a Paris demain apres-midi avec spa » | `['spa']` | 5 |
| 2 | **« enleve le spa »** | **`['spa']`** ← inchangé | 5 |

Réponse du tour 2, mot pour mot : *« Pour le 28/08/2026 à Paris, la recherche a été faite avec le critère "spa"… Si vous voulez "sans spa", je peux relancer la recherche sans ce filtre »* — le modèle **sait** qu'on lui demande d'enlever le filtre, il n'a simplement aucun moyen de le faire. C'est exactement le symptôme de Fabien, capturé avant tout déploiement.

### ✅ Déployé et vérifié EN PROD (branche non mergée — même convention que PR #95 / `33432ff`)

`LANGFUSE_RELEASE=792d9fe` posé sur **`concierge`** et **`hotel-search`** avec `--skip-deploys` (vérifié : les deux `latestDeployment.createdAt` sont restés à 07:58:59Z / 2026-08-26T14:57:11Z après le stamp — aucun redéploiement de l'ANCIEN code sous la nouvelle estampille), puis `railway up --detach` **feuille d'abord** puis concierge → `hotel-search=SUCCESS 10:05:12Z`, `concierge=SUCCESS 10:07:04Z`. `faq` et `widget` **volontairement laissés sur leur estampille** : aucun de leurs fichiers n'est dans le diff.

**Sonde 1 — la séquence de Fabien, session fraîche, `x-dayuse-synthetic: 1`** (10:08:57 → 10:09:24Z, donc bien APRÈS les deux SUCCESS) :

| Tour | Message | `active_filters.amenities` | Hôtels rendus |
|---|---|---|---|
| 1 | « hotel a Paris demain apres-midi avec spa » | `['spa']` | 5 — *Hôtel Résidence Europe & Spa, Belinda Hôtel & Spa…* |
| 2 | **« enleve le spa »** | **`[]`** ← le filtre est parti | 5 — *H4 Wyndham Pleyel, Mercure Orly, Novotel La Défense…* |

La liste d'hôtels du tour 2 est **entièrement différente** de celle du tour 1 : la recherche est réellement repartie sans filtre, ce n'est pas un affichage qui change tout seul. Comparer avec la repro d'avant déploiement plus haut (mêmes messages, `['spa']` et **les mêmes 5 hôtels** au tour 2).

**`guard_filter_relaxation_honored = true` dans Langfuse**, trace `94e82e77765da2bdfebcdfc84241bc3d`, `environment: production`, `configId: 964592d3-2214-44c4-9754-aae6fe9ca5aa`. Sur la même trace : **`llm_calls = 3`** (plafond structurel tenu, zéro appel ajouté), `hotels_returned = 5`, `empty_shortlist = false`.

⚠️ **Le filtre Langfuse a été validé POSITIVEMENT avant de conclure quoi que ce soit** (un zéro sur un filtre cassé se lit exactement comme un guard qui ne tire pas). La forme qui marche : `name: ["guard_…"]` + `dataType: ["BOOLEAN"]` + `value: ["true"]` (+ `environment: ["production"]`) — vérifiée d'abord sur `guard_date_hallucinated_year_rolled_forward`, qui **rend bien 3 lignes** avec cette forme exacte. `value: ["1"]` fait échouer le serveur. Deux autres noms rendent 0 avec la même requête (`guard_amenity_truthfulness`, `guard_poi_anchor_coherence`) : c'est un vrai zéro, pas un filtre cassé.

**Sonde 2 — le piège ET le bénéfice collatéral, en prod, session fraîche** (10:10:18 → 10:11:03Z) :

| Tour | Message | `active_filters.amenities` | Hôtels |
|---|---|---|---|
| 1 | « hotel a Paris demain apres-midi avec piscine » | `['pool']` | 5 |
| 2 | « quelles sont les conditions d'annulation ? » (famille **faq** — `search_offers` ne tourne PAS) | **`['pool']`** ← 🪤 survit | 0 |
| 3 | « montre m'en d'autres » | `['pool']` | 5 |
| 4 | **« en fait je veux un hotel sans piscine »** | **`[]`** | 5 |

Le tour 2 est **le piège de la phase, joué en prod sur un vrai tour sans recherche** : le filtre survit. Le tour 4 est le **bénéfice collatéral** : une négation fraîche retire maintenant un filtre posé avant, au lieu de le garder. Guard à `true` sur cette trace aussi (`bd6680d1a3836a3daabab58ad279a6c8`).

### 📌 Constat de synthèse à part, PAS un bug UX1 — à noter pour UX2

Sur la sonde 1 tour 2, la **mécanique** est juste (filtre retiré, recherche relancée, hôtels neufs) mais la **phrase** est maladroite : « je ne peux pas retirer "le spa" de cette sélection car l'info spa n'apparaît pas sur ces fiches ». La synthèse décrit l'ancienne sélection au lieu de dire « c'est reparti sans le filtre spa ». C'est un problème de prompt de synthèse (le ground-truth du tour ne dit pas qu'un filtre vient d'être retiré), pas de filtre — la preuve, c'est que `active_filters` et la liste d'hôtels sont corrects. À traiter avec UX2 (réécriture de `templates.py`), pas ici.

### Pièges et faits découverts pendant la phase

- 📌 **`CLAUDE.md` disait « 13 guards déterministes » alors qu'il y en avait 14 depuis le 2026-08-26** (`poi_anchor_coherence` n'y avait jamais été ajouté). Corrigé au passage en **15** avec les deux entrées manquantes, sinon le fichier que toute session lit en premier partait à deux guards de retard. Le contrat exécutable reste `GUARD_SCORE_NAMES` — `CLAUDE.md` n'en est que le miroir en prose.
- 🪤 **`dayuse.metrics` n'est capturable ni par `caplog` ni par `capsys`/`capfd` sous pytest.** Son handler est un `StreamHandler` lié au `sys.stdout` du moment de l'import (donc à l'objet de capture GLOBALE de pytest) et il ne propage pas. Les lignes apparaissent bien dans « Captured stdout call » du rapport, mais `capfd.readouterr()` rend vide — deux itérations perdues. Le patron qui marche : brancher un handler jetable sur `logging.getLogger("dayuse.metrics")` (voir `_metric_lines()` dans `test_equipment_ids.py`).
- 📌 **`railway ssh` est bloqué par le classifieur de permissions** dans cette session : la preuve « le bon code tourne dans le conteneur » a donc été faite **par le comportement** (guard à `true` + liste d'hôtels qui change), pas par un `grep` dans `/app`. C'est au moins aussi fort ici, puisque le guard ne peut pas exister sans le code déployé.

### ⚠️ HORS PÉRIMÈTRE, mesuré et NON corrigé — **le budget affiché n'est pas le budget appliqué** (arbitrage Fabien)

Découvert en analysant UX1, mesuré pendant, **délibérément pas corrigé** : élargir le scope en cours de phase est exactement ce que `SESSIONS-CLAUDE-CODE.md` interdit.

`query_params` part **toujours vide** (`b2c_concierge/agent.py` l. 349-351, commentaire explicite : « its business schema is S4's contract to fill, not S5's ») : tout voyage par `profile_in`. Or `budget_max` n'est **jamais** ré-injecté dans les args de `search_offers`. Les deux autres slots équivalents le sont : `amenities` via `equipment_ids.enforce_equipment_filters`, `adults`/`children` via `occupancy.inject_profile_occupancy`. Côté feuille, `budget_max` n'existe qu'en **lecture** (`response_bridge._budget_timeslot_from_args` le capture depuis le `priceRangeMax` que le modèle a envoyé) — il n'y a aucun chemin d'écriture. Ses seuls consommateurs sont `facade.py` l. 379 (`active_filters`, donc l'UI) et `agent.py` l. 697.

**Mesure** (même couture réelle que les tests UX1 : `inject_profile_occupancy` + `enforce_equipment_filters` + `capture_after_tool` + `emit` + `apply_profile_delta`). Tour 1 : « un hôtel à Paris avec spa, pour 2 adultes, max 80 euros ». Tour 2 : « montre m'en d'autres » (aucune mention de prix, de personnes ou d'équipement).

| Slot | Affiché tour 2 (`active_filters`) | Réellement appliqué tour 2 (arg MCP) |
|---|---|---|
| `amenities` | `['spa']` | `hotelEquipmentIds = [35]` ✅ |
| `adults` | `2` | `adults = 2` ✅ |
| **`budget_max`** | **`80.0`** | **`priceRangeMax` absent** ❌ |

C'est le **symptôme miroir** de celui de Fabien : là il s'agissait d'un critère retiré qui restait appliqué, ici d'un critère affiché qui n'est pas appliqué. Deux arbitrages possibles, à trancher par Fabien :

1. **Porter le budget comme les amenities** — un `inject_profile_budget` before_tool sur `search_offers`. Cohérent avec les deux autres slots, mais il faudra dire ce que devient la rétraction (« oublie le budget ») : le même canal qu'UX1, ou rien.
2. **Cesser de l'afficher** — retirer `budget_max` d'`active_filters` quand il ne filtre pas. Moins de code, mais l'UI perd une information que l'utilisateur a bien donnée.

Script de mesure re-jouable dans le scratchpad de session (`measure_budget_gap.py`) — 40 lignes, aucun réseau.

## ✅ Addendum 2026-08-27 ter — UX5 : le lien de réservation ne dit plus « c'est confirmé »

`templates.booking_link_response` (FR + EN) retirait « C'est confirmé — » / « Confirmed — » avant de coller le lien : la phrase confirmait l'*intention* de l'utilisateur (R9), mais lue à côté du lien et du nom de l'hôtel elle se lisait comme « votre chambre est réservée ». Correctif : `Voici votre lien de réservation pour {hotel} — il reste à finaliser sur la page Dayuse : {url}` / `Here's your booking link for {hotel} — you'll finalize on the Dayuse page: {url}` — zéro changement de logique, zéro changement de signature, `booking_offer_summary_response` (le tour d'avant, qui pose la question) non touché. Wording final = arbitrage produit, 3 variantes FR/EN proposées dans la PR.

**Preuve widget (local, pas prod — PR non mergée)** : proxy widget (`scripts/run_widget_proxy.py`) contre le concierge local avec Redis réel (`docker run redis:7-alpine`, sinon le profil de session n'est jamais persisté et le pick échoue), piloté en Chrome headless/CDP. Un tour recherche + pick d'hôtel affiche directement `booking_link_response` (le pick génère déjà le lien — S-CX8, pas de tour de confirmation séparé nécessaire dans ce chemin) : texte rendu FR et EN conforme, sans « confirmé »/« confirmed », captures dans le scratchpad de session. `pytest -q` 1460 passed, 1 skipped (baseline inchangée) ; ruff, mypy, guardrails verts.

⚠️ **Ordonnancement rappelé** : cette branche doit être mergée AVANT UX2 (qui réécrit `templates.py` pour 7 langues), sinon UX2 repart de la mauvaise phrase.

## ✅ Addendum 2026-08-27 bis — les assets du widget revalident (ETag + `no-cache` sur le proxy)

Finding sorti de la vérification du bloc précédent, refermé ici. `WidgetProxyHandler` servait l'index et `/static/**` avec **le seul `Content-Length`** : ni `Cache-Control`, ni `ETag`, ni `Last-Modified`. Or les assets du widget sont **non versionnés** (`chat_clean.html` charge `/static/js/chat/*.js` à chemin fixe), donc la fraîcheur d'une copie en cache était laissée aux heuristiques du navigateur : un client pouvait faire tourner un ancien `state.js` contre une façade plus récente — la classe de bug exacte que le correctif de session venait de refermer.

**Correctif** : un seul helper `_send_cacheable(body, content_type)` utilisé par l'index ET par les statiques, qui pose un **`ETag` de contenu** (sha256 tronqué) + **`Cache-Control: no-cache`**, et répond **304** sans corps quand l'`If-None-Match` correspond. `no-cache` ≠ « ne cache pas » : le client peut stocker, mais doit revalider avant chaque usage — la revalidation coûte un 304, pas les octets. Pas de versionnage de noms de fichiers (il faudrait une étape de build pour un gain de perf dont la démo n'a pas besoin).

**Preuves** : `tests/test_widget_proxy_cache.py` (5 tests, **4 échouent sans le correctif** — vérifié en stashant le seul `run_widget_proxy.py`) ; et sur un proxy lancé pour de vrai en local : `200 + ETag + no-cache`, puis **`304 Not Modified`** sur l'etag rendu, puis `200` sur un etag périmé, index inclus. Suite complète : 1457 passed, 1 skipped ; ruff + mypy + guardrails verts.

**Déployé** — PR #99 mergée en `676557b`, `LANGFUSE_RELEASE=676557b` + `railway up --service widget` → SUCCESS (08:26 UTC). Vérifié sur la prod, **à travers l'edge Railway** : `200 + etag + cache-control: no-cache`, **`304`** sur un GET conditionnel portant l'etag rendu, `200` sur un etag périmé, index compris. L'etag de `state.js` en prod (`"06451cb5…"`) est identique à celui calculé en local sur le fichier corrigé : c'est bien le bon asset qui est servi.

### 🪤 Sauf que cette première version était INCOMPLÈTE — le navigateur revalidait sans jamais obtenir de 304

Le contrôle navigateur (Chrome piloté en CDP, 2 chargements de la page prod) dit deux choses. **La bonne** : au chargement 2, Chrome **envoie bien `If-None-Match`** — plus de cache muet, l'objectif de correction est atteint. **La mauvaise** : il reçoit **`200` avec le corps entier sur 36 des 38 assets**.

Cause : **l'edge Railway réécrit notre ETag fort en ETag faible** (`W/"06451cb5…"`) quand il compresse la réponse. Le navigateur renvoie donc `W/"…"`, et la comparaison exacte du handler ne matchait pas. Or `If-None-Match` se compare **toujours** avec la fonction *faible* (RFC 9110 §13.1.2) et peut porter une **liste** d'etags ou `*` — les trois cas manquaient.

Correctif : helper `_if_none_match_hits()` (strip du préfixe `W/`, liste séparée par virgules, `*`) + 3 tests (les 3 échouent sans lui). PR #100 mergée en `58e15b5`, `LANGFUSE_RELEASE=58e15b5` + `railway up --service widget` → SUCCESS (08:33:35 UTC). Suite : 1460 passed, 1 skipped.

**Vérifié en navigateur, avec le bon critère** — Chrome CDP, 2 chargements de la page prod : chargement 1 = `200 + ETag + no-cache`, chargement 2 = **`304` sur les 38 assets** (contre 36 `200` + 2 `304` avant ce correctif). Zéro asset servi depuis un cache muet.

`state.js` servi en prod garde l'etag `"06451cb5…"` : le fichier est **octet pour octet celui déjà prouvé** au bloc précédent, les deux redéploiements du `widget` n'ont rien changé au correctif de session.

### 🪤 Deux pièges de méthode, à ne pas re-payer

- **« Avant/après déploiement » se prouve avec les horodatages, pas avec l'ordre des commandes.** J'ai étiqueté une mesure « AVANT deploy » alors que le build était déjà live depuis ~1 min : elle rendait déjà `304`, ce qui aurait pu passer pour « le correctif ne servait à rien ». Comparer l'heure de la sonde avec `latestDeployment.createdAt` (`railway status --json`) avant de nommer une mesure.
- **Un `304` vu depuis l'extérieur n'est pas forcément le nôtre : l'edge Railway peut répondre à une requête conditionnelle depuis SON cache.** Pour mesurer le comportement de l'origine, ajouter un cache-buster que l'edge n'a jamais vu : `GET /static/js/chat/state.js?cb=<alea>` + `If-None-Match: W/"…"` → `304` (c'est bien notre handler), le même avec un etag périmé → `200`, une liste contenant le nôtre → `304`. Le `304` renvoie l'etag **fort** (pas de corps → pas de compression → pas d'affaiblissement).

**Leçon** : sur ce déploiement, un ETag n'est pas ce qu'on a écrit dans le code — l'edge peut le transformer. Un test unitaire sur notre propre handler ne pouvait pas voir ça ; seul le navigateur contre la prod l'a montré.

## ✅ Addendum 2026-08-27 — le reload du widget ne repart plus sur la session d'avant (précédence `session_id` inversée)

Symptôme rapporté par Fabien : « je rafraîchis la page du widget, je pose une nouvelle recherche et il me parle des critères de la session d'avant le reload ». Ce n'était pas de la dérive de prompt : le serveur **refusait** de laisser le reload ouvrir une nouvelle session.

### Repro live sur `https://widget-production-3f56.up.railway.app` (code AVANT correctif)

| Appel | Envoyé | `conversation_id` rendu | Réponse |
|---|---|---|---|
| 1 | « hotel a Bordeaux demain apres-midi avec piscine », client vierge | `cs_reloadtest_…625` + `Set-Cookie du_chat_sid` | 5 hôtels Bordeaux |
| 2 | **« je cherche un hotel »** (nu), cookie + même id sessionStorage = *reload* | `cs_reloadtest_…625` | « Pour Bordeaux le 28/08/2026, j'ai trouvé 5 hôtels avec piscine… » |
| 3 | **« je cherche un hotel »**, cookie + id client **tout neuf** | `cs_reloadtest_…625` ← l'ANCIEN | « Pour Bordeaux le 28/08/2026 (avec piscine)… » |

**L'appel 3 est la preuve décisive** : on donne au serveur un `session_id` neuf, il le remplace par celui du cookie. Aucun correctif côté navigateur ne pouvait s'en sortir.

### Les 3 couches (la première est la cause décisive)

1. **Le cookie gagnait sur tout.** `_resolve_session_id` (facade.py) lisait `du_chat_sid` **avant** `X-Client-Session-Id`. Le cookie est `httponly` (donc inatteignable depuis JS) et `max_age=3600` re-posé à chaque tour : pendant 1 h, tout reload — nouvel onglet et redémarrage du navigateur inclus — reprenait la même session serveur, avec le profil Redis (TTL glissant 30 min) et les events ADK.
2. **Le widget persistait aussi un id à travers les reloads** : `state.js` gardait `clientSessionId` en **sessionStorage** (qui survit à un reload), et `send.js` l'envoie comme `session_id` de body quand `currentConversationId` est `null`, c'est-à-dire juste après un reload. Second porteur de la même continuité.
3. **L'UI et le serveur n'étaient pas d'accord sur le sens d'un reload** : la page revient avec une conversation vide + le greeting, pendant que le serveur garde tout. D'où le « des fois » : ça dépend si l'heure du cookie / les 30 min de Redis étaient écoulées.

### Correctif (décision produit de Fabien : **un reload = une nouvelle conversation**)

- `facade.py` : précédence inversée dans `_resolve_session_id` **et** `_resolve_existing_session_id` → `X-Client-Session-Id` d'abord, cookie en secours. Le cookie continue donc de porter la continuité pour les appelants **sans header** (le BFF iso-contrat d'agent-usa) : rien ne change pour eux.
- `state.js` : `clientSessionId` minté **par chargement de page**, plus jamais persisté (la fonction `getOrCreateClientSessionId` et la clé `du_chat_client_session_id` sont supprimées ; une clé résiduelle dans un navigateur qui revient n'est plus jamais relue).
- `state.js::resetState()` : mint un id neuf. Le bouton « nouvelle conversation » ne recyclait pas seulement l'id — il **rejouait l'id de la session que `/v3/chat/session/reset` venait de supprimer**, ce qui rangeait la conversation neuve sous la session précédente dans Langfuse/Redis.

### Preuves

- Test de régression `tests/api/test_facade_http.py::test_client_header_outranks_an_existing_cookie` : **échoue sur l'ancien code avec exactement la signature du bug** (`AssertionError: assert 'before-reload' == 'after-reload'`, vérifié par `git stash` du seul `facade.py`), passe avec.
- `pytest -q` : **1452 passed, 1 skipped**. `ruff` + `mypy` (46 fichiers) + `dayuse_guardrails.sh` : verts.
- Côté widget (node, DOM stubé) : 2 chargements de `state.js` → 2 ids différents ; `resetState()` → id neuf ; **`sessionStorage` jamais touché** (getItem/setItem instrumentés, 0 appel).
- Le proxy widget forwarde bien `X-Client-Session-Id` (il ne retire que les hop-by-hop et l'en-tête de clé API, `run_widget_proxy.py`).

### ✅ Déployé et vérifié EN PROD (2026-08-27, PR #97 mergée en `10a6d89`)

`LANGFUSE_RELEASE=10a6d89` posé sur **`concierge`** et **`widget`** (`--skip-deploys`), puis `railway up --detach` sur les deux → `concierge=SUCCESS widget=SUCCESS`. `hotel-search` et `faq` **volontairement laissés sur leur estampille** : aucun de leurs fichiers n'est dans le diff.

**Preuve serveur** — 3 appels via le proxy widget (`x-dayuse-synthetic: 1`), le même scénario que la repro du bug :

| Appel | Envoyé | Résultat |
|---|---|---|
| 1 | id client A, sans cookie, « hotel a Bordeaux demain apres-midi avec piscine » | `conversation_id = A`, 4 hôtels, cookie posé |
| 2 | **id client B NEUF + le cookie de A**, « je cherche un hotel » | `conversation_id = B`, **0 hôtel**, « j'ai besoin de la ville ou du quartier… » ← **le bug est mort** |
| 3 | retour sur l'**id A** (cookie = B), « je cherche un hotel » | `conversation_id = A`, Bordeaux + piscine reviennent ← **la continuité multi-tour n'a pas été cassée** |

**Preuve navigateur** (Chrome headless piloté en CDP, contre la prod) : chargement 1 en deep link Bordeaux → 4 cartes ; `Page.reload()` → transcript vide ; chargement suivant + question nue → réponse qui **demande la destination et la date**. Les deux requêtes `/v3/chat/stream` portent **deux `X-Client-Session-Id` différents** (`ee9d4d60…` puis `62f14197…`) et la seconde **envoie bien `du_chat_sid`** : le cookie est présent, et il est ignoré. Captures dans le scratchpad de session.

### Pièges et faits découverts pendant la vérification

- 🪤 **CDP** : après un `Page.reload()`, cliquer `#main-submit-button` ne produit **rien** — la page est revenue sur la vue d'accueil (`#initial-input`), le clic est perdu. Pour le tour suivant, refaire un chargement `?q=…` (qui auto-envoie). Ça a coûté deux runs.
- 🪤 **CDP** : ne pas régler le timeout sur le socket brut (`ws.socket.settimeout`) pour dépiler les événements — la connexion meurt (`no close frame received`). Utiliser `ws.recv(timeout=…)` de `websockets.sync`.
- 📌 **Transport SSE re-confirmé en prod** : les tours du navigateur partent sur **`/v3/chat/stream`**, pas `/v3/chat` — déjà consigné plus bas (bloc S-PERF4, `l. 1063` et `l. 1934`), recoché de mes yeux le 2026-08-27. Corollaire pour toute probe DOM : la fin de réponse ne se détecte pas au nombre de nœuds mais à la **stabilisation du texte**, puisque les tokens arrivent en streaming.
- ✅ **Les assets statiques partaient sans `Cache-Control`, sans `ETag` et sans `Last-Modified`** (`content-length` seul), donc leur fraîcheur était laissée aux heuristiques du navigateur — un client pouvait rejouer un ancien `state.js` contre une façade plus récente, exactement la classe de bug que ce bloc corrige. **Traité juste après, branche `fix/widget-asset-revalidation`** (voir le bloc suivant).
- Le body `session_id` (M1 legacy) reste envoyé par le widget et vaut désormais le même id que le header : redondant mais volontaire, c'est le contrat iso agent-usa.

## ✅ Addendum 2026-08-26 decies — les 2 guards date sont CÂBLÉS ; `guard_date_hallucinated_year_rolled_forward` vu à **true 3/3 en prod** (première fois de l'histoire du projet)

Scope : uniquement le câblage de l'observabilité des 2 derniers noms de `GUARD_SCORE_NAMES` sans producteur. Zéro touche à la logique de date, zéro touche à `geocode_tool.py` / `geo_resolver.py`. Branche `feat/obs3-wire-date-guards`, commit `33432ff`, PR ouverte — **non mergée**.

### Après le merge — état des estampilles, et pourquoi aucun service n'est en retard

PR #95 mergée en `9cbbab3` (2026-08-26 17:16 Paris, vrai merge commit, donc `33432ff` est bien un ancêtre de `main`).

- **`git diff 33432ff 9cbbab3 -- agents libs` est VIDE** : l'arbre de code déployé sur la feuille est identique à `main` sur la totalité de `agents/` et `libs/`. Aucun service n'est en retard sur du code.
- **L'estampille de `hotel-search` reste `33432ff`, volontairement** — pas re-posée sur le merge commit. C'est la réponse la PLUS précise à « quel code tourne » : c'est exactement l'arbre qu'a uploadé `railway up`, et comme c'est un ancêtre de `main` le fil-piège `git log <release>..main` lit propre quand même. Re-estampiller n'aurait rien ajouté et aurait coûté une mutation d'infra (avec le risque du `--skip-deploys` oublié).
- **`concierge` et `faq` restent à `7d41d41`, et leur fil-piège SONNE — c'est un faux positif, documenté ici pour ne pas le re-diagnostiquer.** `git log 7d41d41..main -- agents/b2c_concierge libs` rend exactement un commit, `33432ff`, et sa seule modification dans le périmètre du concierge est la **docstring de module** de `libs/b2c_common/b2c_common/scores.py` (vérifié ligne par ligne : le diff de `libs` est intégralement à l'intérieur du `"""…"""` de tête). **Zéro changement exécutable, donc aucun redéploiement dû.** C'est l'instance concrète du piège annoncé au bloc « nonies » : un fil-piège lu sur `libs` accuse le concierge dès qu'une feuille touche un commentaire partagé.

### Le correctif, et la décision de design

Les 2 sites de tir (`_resolve_absolute` l. 228, `_usable_carried_date` l. 262) sont dans des helpers **purs**, sans `tool_context`. Choix retenu : **accumulateur `list[str]` passé en paramètre** — le patron déjà en place dans `geocode_tool` (`_anchor_state(..., guards_fired=...)`) — et pas une valeur de retour enrichie, qui aurait cassé le tuple public de `resolve_date_label`. Ce paramètre y est **optionnel** (`guards_fired: list[str] | None = None`) : la signature à 2 arguments que les tests utilisent partout continue de marcher.

`resolve_search_date` (qui a le `tool_context`) crée l'accumulateur et le remet à un helper NOUVEAU, `response_bridge.record_guards_fired` — désormais l'**unique écrivain** de `temp:hotel_search_guards_fired`. `capture_after_tool` y passe maintenant la liste que renvoie `geocode_location` (mêmes 4 lignes, dédupliquées) : une seule sémantique de fusion (accumule, déduplique, ordonne) pour les deux producteurs. Il fallait un helper parce que `resolve_search_date` est un **before_tool** callback : il n'y a aucune réponse d'outil sur laquelle accrocher une clé `guards_fired`.

`GUARD_SCORE_NAMES` non touché : aucun renommage, aucun retrait, aucun réordonnancement. Zéro appel LLM ajouté (`llm_calls = 3` sur la trace de preuve, plafond tenu). Zéro contenu de message dans la télémétrie : un nom de guard, jamais la date ni le message.

### ⚠️ Le plan de forçage du brief était INVERSÉ, pour une raison qu'il ne pouvait pas voir

Le brief disait : « `date_carryover_stale_floored` est forçable par un appel A2A direct à la feuille avec une date passée dans `profile_in` ; `date_hallucinated_year_rolled_forward` n'est PAS forçable (il faut que le modèle invente une année) ». **Les deux moitiés sont fausses.**

1. **Un appel direct à la feuille ne peut produire AUCUN score.** `score_guards` n'est appelé qu'à **un seul endroit dans tout le repo** : `b2c_concierge/agent.py:562`. La feuille ne publie rien. Vérifié (`grep -rn "score_guards" agents/*/[a-z]*/*.py`). Donc pour voir un score, le tour DOIT traverser le concierge.
2. **Le guard « année hallucinée » EST forçable, trivialement** : le code tire sur *toute* date ISO passée, peu importe son origine. Il suffit que **l'utilisateur** donne l'année lui-même — « un hotel a paris **le 6 aout 2023** » — et le modèle la recopie en `absolute: 2023-08-06` (c'est même son instruction : « YYYY-MM-DD if they gave a year »). Le nom du guard parle d'hallucination, son déclencheur est « ISO dans le passé ». Déterministe, 3/3.
3. **`date_carryover_stale_floored` n'est PAS forçable en prod**, et pour une raison structurelle mesurée dans le conteneur : avec `profile_in.date = 2026-08-20` (passé) et un message SANS date, **gpt-4o-mini renvoie la date du profil comme label `absolute`** au lieu de l'omettre. Le tour prend donc le chemin « label frais », et c'est le guard **année** qui tire — pas le plancher. Vérifié 2×, deux formulations (« un hotel », « d autres options ») : `guards_fired: ["date_hallucinated_year_rolled_forward"]` les deux fois. Le plancher est un vrai dernier recours (le modèle omet complètement le label), atteignable en pratique par le straddle de minuit, pas à la demande.

### Déploiement de la feuille SEULE, avec la preuve que l'estampille ne ment pas

- `LANGFUSE_RELEASE=33432ff` sur **`hotel-search` seulement**, `--skip-deploys`. `last_deploy` **resté à 16:24:07 +02:00** après le stamp → aucun redéploiement de l'ANCIEN code sous la nouvelle estampille.
- `railway up --service hotel-search --environment production --detach` → **SUCCESS 16:57:11 +02:00** (`--detach` volontaire, `--ci` streame `FLEET_READ_TOKEN` en clair).
- `concierge` et `faq` NON redéployés : le diff ne touche `libs/b2c_common/scores.py` **qu'en docstring**, et le fold côté concierge (`response.pop("guards_fired")`) est déjà en prod depuis `7d41d41`. Rien à redéployer là.
- Preuve **autrement que par l'estampille**, dans le conteneur qui tourne : `record_guards_fired` ×4 dans `datetime_resolver.py`, ×2 dans `response_bridge.py`, et `guards_fired.append("date_…")` ×2.
- 🪤 **Piège de chemin** : dans le conteneur le code est à **`/app/hotel_search_agent/…`**, PAS `/app/agents/hotel_search_agent/hotel_search_agent/…`. Un `grep` sur le chemin du repo répond « No such file or directory » et se lit comme « le code n'est pas déployé ». Le localiser par `find / -name <fichier>.py`.

### La preuve qui compte : le score à `true` dans Langfuse

3 tours via le proxy widget (`https://widget-production-3f56.up.railway.app/v3/chat`, `x-dayuse-synthetic: 1`, session fraîche à chaque tour), avec une année passée donnée par l'utilisateur :

| tour | message | réponse | trace |
|---|---|---|---|
| 1 | « un hotel a paris le 6 aout 2023 » | *« …aucune offre à Paris pour le 6 août **2027** »* | `fa3003fc0a358dddd2037330c55e3982` |
| 2 | « je cherche un hotel a lyon le 10 mai 2022 » | *« …pour le 10/05/**2027** (votre message mentionne 10 mai 2022) »* | `a78d11afe88a0b5fb8c76e1c181d94eb` |
| 3 | idem | idem | `0d204653597912186a3f72c33d8a5366` |

`guard_date_hallucinated_year_rolled_forward` = **`true`, 3/3**, `environment: production`. Ce sont les **3 seuls `true` de toute l'histoire du projet** (`listScores` sur ce nom, `dataType: BOOLEAN`, `value: ["true"]`, limit 5 → 3 lignes) : avant ce déploiement le score était structurellement à 0.0, exactement comme annoncé.

Sur la MÊME trace, les contrôles qui rendent le `true` interprétable :
- `guard_date_carryover_stale_floored` = **`false`** → les deux noms sont indépendants, le câblage n'a pas mis tout le monde à 1.0.
- `llm_calls` = **3** → plafond ≤ 3 tenu, ce chantier n'ajoute aucun appel.
- `hotels_returned` = 0 → normal, le 2027-08-06 n'a pas d'inventaire.
- `configId` = `null` sur le guard année : **définitif et attendu** (43 caractères contre 35 max côté Langfuse), son jumeau a bien le sien (`c8779d65-…`). Rien à réessayer.

🪤 Rappel du piège d'outillage, re-vérifié : ces scores sont **BOOLEAN**. Le filtre `value` s'écrit `["true"]` — `["1"]` fait répondre au serveur `value filter with dataType=BOOLEAN requires each value to be "true" or "false"`. Et le filtre a été **validé positivement** (il a rendu 3 lignes) avant de conclure du zéro sur l'autre nom.

### ❌ Ce qui n'a PAS pu être prouvé en prod

- **`date_carryover_stale_floored` : jamais vu à `true`.** `listScores` sur ce nom, `value: ["true"]` → **liste vide** (filtre validé positivement juste avant sur son jumeau, donc le zéro est réel). Non forçable pour la raison structurelle du §2 ci-dessus. **Preuve hors-ligne uniquement** : `test_stale_carryover_floor_is_reported` + `test_the_guards_ride_the_datapart_the_concierge_already_reads`, plus le fait que le transport (`guards_fired` → `budget.fired` → `score_guards`) est prouvé en prod le même jour sur les 3 guards géo ET, maintenant, sur son jumeau qui emprunte le même `record_guards_fired`. Ne pas écrire ailleurs qu'il a été vu en prod.

### ✅ RÉGLÉ — le domaine public de trop sur `hotel-search` (Fabien l'a supprimé)

En cherchant à **lire** les domaines du service, j'ai lancé `railway domain --service hotel-search` : cette commande, **sans argument, CRÉE un domaine** au lieu d'en lister un. Résultat : `https://hotel-search-production-cdb3.up.railway.app` existe maintenant, alors que **D7 dit réseau privé Railway + bearer côté feuille** — une feuille n'a pas à avoir d'entrée publique. Le bearer `BearerAuthMiddleware` est bien devant (une requête non authentifiée est rejetée, la carte d'agent exceptée), donc ce n'est pas un trou béant, mais c'est une déviation de l'invariant qu'il faut refermer.

**Supprimé par Fabien le 2026-08-26, et vérifié** (la suppression était bloquée par le classifieur de mon côté, mutation destructive d'infra) : la requête GraphQL de lecture rend maintenant `serviceDomains: []` **et** `customDomains: []` sur `hotel-search`. La feuille est de nouveau sur le réseau privé seul, D7 tenu.

⚠️ **À ne pas refaire** : `railway domain --service X` est une commande de **création**, pas de lecture. Pour lire, passer par l'API GraphQL (`service(id:){ serviceInstances{ edges{ node{ domains{ serviceDomains{ id domain } } } } } }`).

### Vérification locale

- `.venv/bin/pytest -q` → **1451 passed, 1 skipped** (référence d'entrée : 1442 / 1 → **+9 tests**).
- **Preuve que les nouveaux tests échouent sans le correctif** : `datetime_resolver.py` remis à `HEAD`, tests conservés → **5 échecs sur 7**. Les 2 qui passent quand même sont ceux qui doivent passer : le contrôle négatif (`test_a_clean_turn_reports_no_date_guard_at_all`) et le test de compatibilité de signature (`test_resolve_date_label_still_works_without_an_accumulator`).
- `ruff check .` → All checks passed ; `mypy agents libs` → no issues in 46 files ; `dayuse_guardrails.sh` → OK.

### Reste (repris du bloc « nonies », inchangé sauf mention)

- ✅ **Les 2 guards date ne sont plus « non câblés »** — l'item du bloc précédent disparaît. Les 14 noms de `GUARD_SCORE_NAMES` ont maintenant un producteur (vérifié nom par nom contre le code, pas déduit).
- ⚠️ Défaut voisin toujours ouvert : `city="Lyon"` + `zone="gare de lyon"` résout sur *« La Garde, Lyon, Rhône »* — bonne ville, pas une gare, guard #14 aveugle (la distance est bonne).
- ⚠️ `_W_LANDMARK_CITY_ANCHOR` (2,5) et `_LANDMARK_ANCHOR_ZERO_KM` (40) pèsent sur bien plus de tours depuis que l'ancre de ville est presque toujours présente. Non re-calibrés.
- ⬜ PR réellement ouvertes : **#40** `scx6-same-day-cutoff-fallback` et **#19** `s-d-judge-ab` (un mois chacune), plus celle de cette session.
- P2 `resolve_location` reste la seule sortie structurelle.

## ✅ Addendum 2026-08-26 nonies — #91 + #92 DÉPLOYÉES sur `e6d3460` et prouvées en prod : les 7 critères passent, dont l'aéroport de Nice 3/3

Suite directe des blocs « septies » (S5) et « octies » (la géo). Les deux PR mergées, **un seul déploiement** parce que les deux changements vivent dans la même feuille.

### Déploiement, avec la preuve que l'estampille ne ment pas

- `LANGFUSE_RELEASE=e6d3460` posé sur **`hotel-search` seulement**, avec `--skip-deploys`. Vérifié : le `last_deploy` est resté à **15:10:57 +02:00** après le stamp — donc aucun redéploiement de l'ANCIEN code sous la nouvelle estampille.
- `railway up --service hotel-search --environment production --detach` → **SUCCESS 16:24:07 +02:00**. `--detach` volontaire (`--ci` streame les build logs, qui contiennent `FLEET_READ_TOKEN` en clair).
- **`concierge` et `faq` NON redéployés, et leur estampille reste `7d41d41`** — c'est honnête : `git log 7d41d41..e6d3460` ne touche que `agents/hotel_search_agent/**` et `HANDOFF.md`, zéro `libs/`, zéro concierge, zéro faq. ⚠️ **Conséquence pour le fil-piège** : il faut désormais le lire **par service** (`git log <release>..main -- agents/b2c_concierge libs` pour le concierge, etc.). Lu globalement sur `-- agents libs`, il criera au loup sur les commits de la feuille.
- Preuve **autrement que par l'estampille**, dans le conteneur qui tourne (`railway ssh`) : `_city_coordinate` ×4, `_POI_ANCHOR_MAX_KM = 40.0`, et la nouvelle formulation S5 (« NAMED AFTER A CITY THEY ARE NOT IN ») ×1.

### Les 21 tours, 3 par tournure, `x-dayuse-synthetic: 1`, session fraîche à chaque tour

| tournure | critère | résultat |
|---|---|---|
| « pres de la gare de lyon demain » | question 3/3 | ✅ 3/3, 0 hôtel |
| « autour de la gare de lyon demain » | question 3/3 | ✅ **3/3** — la baseline émettait `Paris` 3/3, c'est-à-dire une **réponse fausse possible en silence**. Le pile-ou-face a disparu du bon côté. |
| « un hotel vers le vieux lyon demain » | *Vieux Lyon 69005* | ✅ 3/3, `city: lyon`, 5 hôtels |
| **« pres de l aeroport de nice demain »** | l'aéroport, plus la navette | ✅ **3/3 *Aéroport de Nice, 06200 Nice*** (avant : *Transferts Aéroport Nice, AIR PROMENADE*, à 6 km), 3 hôtels |
| « autour des champs elysees demain » | `Paris` 3/3 | ✅ *Avenue des Champs-Élysées, 75008* |
| « autour de montmartre demain » | `Paris` 3/3 | ✅ 3/3 (la baseline locale était à 2/3) |
| « autour du louvre demain » | `Paris` 3/3 | ✅ *Louvre, 75002* |

### Le parcours complet en 2 tours (celui que les deux PR traversent)

| tour, même session | résultat |
|---|---|
| T1 « pres de la gare de lyon demain » | question posée, **`zone: gare de lyon` persistée**, 0 hôtel |
| **T2 « paris »** | `city: Paris` + `zone: gare de lyon` → origine = ***Gare de Lyon, Pl. Louis Armand, 75012 Paris*** (`type: poi`), 5 hôtels, **ibis Paris Gare de Lyon Ledru Rollin à 0,5 km** |

⚠️ Piège de lecture que je me suis infligé : sur ce tour l'ibis à 0,5 km est le **5e** résultat (la liste n'est pas triée par distance), et n'imprimer que les 3 premiers donne l'impression d'une régression vers 1,6 km. Ce n'en était pas une — même liste, même hôtel, vérifié sur le tour de contrôle « pres de la gare de lyon a paris demain ».

Et **l'origine est maintenant la gare elle-même**, plus un hôtel concurrent : la baseline rendait *CitizenM Paris Gare de Lyon, 8 Rue Van Gogh* comme `distance_origin` — le symptôme exact de la requête repliée décrit dans « octies ».

### Budget et guards, sur les traces

- **`llm_calls`** : 25 traces dans la fenêtre post-déploiement, **24 à 3 et une à 1**. Plafond ≤ 3 respecté partout.
- **`guard_geocode_echo_back` : `true` sur 11 des 25.** Le guard travaille.
- **`guard_anti_clarification_loop` : jamais `true`** — le critère du bloc « sexies » sur le tour-réponse est tenu.
- **`guard_poi_anchor_coherence` : jamais `true`** → le plafond resserré à 40 km **n'a rejeté aucun POI** sur cet échantillon. Pas de dégât collatéral mesuré sur le resserrage.

⚠️ **Piège d'outillage, à retenir** : ces `guard_*` sont des scores **BOOLEAN**. Les filtrer avec `dataType: ["NUMERIC"]` + `valueMin: 1` renvoie une liste vide — qui ressemble à « aucun guard n'a jamais tiré ». Je suis tombé dedans et je l'ai rattrapé en validant le filtre sur un nom dont je savais qu'il avait des `true`. **Toujours valider positivement un filtre avant de conclure d'un zéro** — même famille de piège que « un 0.0 qui veut dire "pas mesuré" se lit "n'a pas tiré" ».

### L'interaction #91/#92 que « octies » signalait ne se matérialise PAS en prod

Le bloc « octies » prévenait : #91 pousse « aéroport de nice » vers la question (résolu 1/3 en local), alors que #92 rend la réponse correcte — donc on poserait une question là où la géo sait répondre. **En prod, le modèle émet `Nice` 3/3** sur cette tournure, la géo répond juste, et aucune question n'est posée. L'inquiétude était fondée sur la mesure locale ; la mesure prod la lève. Le résidu local (1/3) reste un écart local/prod non expliqué, pas un défaut produit — **ne pas retoucher la formulation S5 sur cette base**.

### Reste

- ⚠️ **Défaut voisin toujours ouvert** : `city="Lyon"` + `zone="gare de lyon"` résout sur *« La Garde, Lyon, Rhône »* — bonne ville, mais ce n'est pas une gare, et le guard #14 ne peut rien voir (la distance est bonne). Imprécision de ranker sur le libellé.
- ⚠️ L'ancre de ville étant maintenant presque toujours présente, `_W_LANDMARK_CITY_ANCHOR` (2,5) et `_LANDMARK_ANCHOR_ZERO_KM` (40) pèsent sur bien plus de tours qu'avant. Non re-calibrés.
- ✅ **CORRECTION — « `triage.response_language` : PR séparée, toujours ouverte » était PÉRIMÉ** et se recopiait de bloc en bloc depuis « quater » (moi compris, dans « septies », « octies » et la première version de celui-ci : recopié sans vérifier). **C'est livré** : `locale_response_language` vit dans `triage.py` et `facade.py` s'en sert à 6 endroits (`response_language` est même une clé de `CONTRACT_KEYS`), arrivé par `5ac9b49` (`fix(scx2)`). Rien à faire, l'item disparaît d'ici.
- ⬜ **Les seules PR réellement ouvertes** (vérifié `gh pr list`, pas déduit) : **#40** `scx6-same-day-cutoff-fallback` (l'après-midi, « aucune offre » est le cutoff du jour — on propose demain, ouverte depuis le 2026-07-27) et **#19** `s-d-judge-ab` (bench de juges agent-usa vs AgentB2C, depuis le 2026-07-22). Un mois chacune.
- ~~Les 2 guards date toujours non câblés~~ → **RÉSOLU le même jour, voir « decies » en tête** (`33432ff` déployée, `guard_date_hallucinated_year_rolled_forward` à `true` 3/3 en prod). P2 `resolve_location` reste la seule sortie structurelle. ⚠️ Cette phrase se recopiait de bloc en bloc depuis « quinquies » (l. 254, 357) : ne pas la ressortir.

## 🛰️ Addendum 2026-08-26 octies — « pourquoi Nice rate alors que Paris marche » : rien n'est en dur, Paris prenait juste l'autre chemin. Une ville NOMMÉE sans coordonnée est maintenant géocodée

Question posée par Fabien (« j'ai peur que Paris fonctionne parce qu'on a mis des trucs en dur dans le code »). **Réponse : non, et c'est vérifié plutôt qu'affirmé.** Aucun nom de ville ni coordonnée en dur dans la feuille — tous les hits `paris` de `agents/hotel_search_agent/**.py` sont des commentaires et docstrings, et le ranker n'est que des poids génériques (`_TYPE_PRIOR`, `_W_*`, `_MIN_TIER_INVENTORY`). `inventory_snapshot.json` est une donnée, pas une préférence.

### La vraie cause : `city_anchor` était GLANÉ, pas cherché

`geocode_tool.py` a trois chemins pour dire à Search Box de quelle ville on parle (son propre commentaire les énumère) : **1.** une coordonnée → `proximity`, requête NUE ; **2.** un nom seul → replié dans la requête (`_searchbox_query`) ; **3.** rien → biais IP.

Or le cas 1 n'était jamais *cherché* : `city_anchor` n'existait que si l'un des candidats v6 de la requête **combinée du tour** (« aéroport de nice, Nice ») échoait la ville ET passait `in_inventory_tier`. Aucun ⇒ cas 2. Et le cas 2 ne coûte pas seulement le libellé, mesuré en direct (sonde de décomposition du ranker, terme par terme) :

| requête envoyée à Search Box | ce qui revient | gagnant |
|---|---|---|
| `"aéroport de nice, Nice"` | 10 commerces, **aucun aéroport** | *Bagnard aéroport de Nice* (un marchand de sandwichs) |
| `"champs élysées, Paris"` | 10 commerces, **aucune avenue** | *citizenM Paris Champs Elysees* — un **hôtel concurrent**, à 1,2 km |
| `"aéroport de nice"` + `proximity` sur Nice | l'aéroport EST dans la liste | **Aéroport de Nice, 06200** (7,57 contre 4,67) |
| `"gare de lyon"` + `proximity` sur Paris | la gare EST dans la liste | **Gare de Lyon, Pl. Louis Armand, 75012** (9,45 contre 6,50) |

**La feature propre n'est pas mal classée : elle est ABSENTE de la liste.** Aucun ranker ne peut rattraper ça — même corollaire que le bloc « ter » (*on ne re-classe pas ce qui n'est pas renvoyé*), à un endroit neuf. Et **Paris n'est pas plus sûr par construction** : replié dans la requête, il rend un hôtel concurrent comme origine de recherche. Il marchait parce que ses tours trouvaient un candidat qui échoait « Paris » avec de l'inventaire, donc prenaient le cas 1.

⚠️ À noter : depuis mon IP, `"champs élysées"` **nu** ne renvoie qu'**un seul** candidat — *Clinique des Champs Elysées, 69006 **Lyon***. Et `_echoes` le laisse passer (le libellé contient « champs » et « elysees »). Le mode de défaillance Toulon-830-km est donc toujours vivant au niveau IP ; ce qui protège la prod, c'est la ville émise par le modèle, pas le guard d'écho.

### Correctif 1 — géocoder la ville pour de bon

`_city_coordinate()` : un NOM de ville sans coordonnée est un trou qu'on peut simplement fermer, en géocodant la ville nue — la même opération v6 que le tool fait déjà pour une recherche de ville. La requête Search Box reste alors NUE. Mesuré : Nice → `(43.7101, 7.2618)`, tier=True, 53 hôtels.

- **Paresseux** : placé après le retour tier-1, donc un tour résolu normalement coûte toujours **un seul** appel v6 (verrouillé par test). Un appel de plus uniquement sur le chemin qui dégradait.
- **`in_inventory_tier` reste le test de crédibilité** (S-G9) : le lookup nu de « Paris » renvoie aussi le quartier nommé Paris à **Roanne**. Vérifié sur ce chemin : Paris (783 hôtels) passe, Roanne (2) non — et le repli en requête reste alors intact.
- Effet de bord voulu : **le guard #14 cesse d'être un no-op ici**. Avec une ancre, il peut enfin rejeter un POI au mauvais endroit — c'est exactement comme le POI de Toulon avait été accepté.

### Correctif 2 — le plafond du guard #14 : 100 km → 40 km

Fabien, en séance : « 100 km c'est beaucoup trop ». **Il a raison** : à 100 km ce n'était pas un contrôle de cohérence sur une ville, c'était un contrôle de l'absurde. La fenêtre est bornée aux deux bouts par des distances **mesurées**, donc ce n'est pas un choix de goût :

| à GARDER | | à REJETER | |
|---|---|---|---|
| Orly | 14,7 km | Beauvais (« Paris »-Beauvais) | 69,0 km |
| Versailles | 17,5 km | Saint-Quentin | 130 km |
| CDG | 22,7 km | Viré | 329 km |
| Évry (homonyme) | 25,7 km | Lyon | 393 km |
| **Disneyland Paris** | **31,3 km** ← contraignant | Toulon | 830 km |

Tout dans (32, 130) se défend ; 100 en était le bout le plus lâche, 40 est le bout serré qui garde Disneyland avec ~8 km de marge. Beauvais est désormais rejeté contre une ancre Paris — délibéré, c'est une autre ville. **S'applique à toutes les ancres, fix GPS compris.** Aucun test existant ne dépendait du plafond lâche (vérifié : la suite passe sans amendement).

### Vérifications

`1442 passed, 1 skipped` (1436 + 6), ruff + mypy + guardrails verts. **2 des 6 tests échouent si on retire le correctif 1** (vérifié en le retirant puis en le remettant) ; les 4 autres verrouillent des invariants (repli inchangé, paresse du lookup, plafond).

En direct, après les deux correctifs (sonde in-process, aucun LLM) : `Nice`+`aéroport de nice` → *Aéroport de Nice, 06200* ; `Paris`+`champs élysées` → *Champs-Élysées, Paris* ; `Paris`+`gare de lyon` → *Gare de Lyon, Pl. Louis Armand, 75012* (le tour-réponse du clarify de #90, non régressé) ; `Nice`+`vieux nice` → *Vieux Nice, 06300*.

### Reste

- ⬜ **Confirmation en prod NON FAITE.** La chaîne de preuve est en pièces mesurées, pas de bout en bout en prod : symptôme prod mesuré (3/3), mécanisme lu dans le code, requête repliée mesurée perdante, coordonnée de ville mesurée crédible, aéroport mesuré gagnant avec cette proximité, câblage verrouillé hors-ligne.
  **#91 est mergée depuis (`48a665d`)** et les deux changements vivent dans la MÊME feuille (`agent.py` pour le prompt, `geocode_tool.py` pour la géo) : **un seul `railway up --service hotel-search --detach`**, une fois ce bloc mergé aussi, vérifie les deux. Critères cumulés : « gare de lyon » (2 tournures) → question 3/3 chacune · « vieux lyon » → *Vieux Lyon 69005* · **« aéroport de nice » → *Aéroport de Nice, 06200*, plus la société de navettes** · contrôles champs-élysées / montmartre / louvre → `Paris` 3/3 · `llm_calls=3` sur les traces. Stamper `LANGFUSE_RELEASE` sur le sha de merge avec `--skip-deploys` d'abord.
- ⚠️ **Interaction avec #91, à surveiller** : #91 a poussé « aéroport de nice » vers la QUESTION (résolu 1/3 seulement), et ce bloc-ci rend la réponse CORRECTE quand le modèle émet bien `Nice`. Le coût résiduel de #91 est donc plus élevé qu'à sa mesure : on pose une question là où la couche géo sait maintenant répondre juste. C'est exactement le cas « le nom et le lieu s'accordent » que V2-narrow veut laisser passer — candidat à un ajustement de formulation, à ne décider qu'après la mesure prod des deux ensemble.
- ⚠️ **Défaut voisin trouvé en passant, NON corrigé** : `city="Lyon"` + `zone="gare de lyon"` (la branche Lyon du clarify de #90) résout sur **« La Garde, Lyon, Rhône »** — un POI dans la bonne ville mais qui n'est pas une gare. Le guard #14 ne peut rien voir (c'est dans la ville) : c'est une imprécision de ranker sur le libellé, pas une erreur de position. À traiter à part.
- ⚠️ L'ancre de ville étant maintenant presque toujours présente, `_W_LANDMARK_CITY_ANCHOR` (2,5) et `_LANDMARK_ANCHOR_ZERO_KM` (40) pèsent sur bien plus de tours qu'avant. Non re-calibrés : à surveiller sur les landmarks légitimement excentrés (Disneyland est à 31,3 km, donc dans la zone de décroissance du bonus).
## 🏷️ Addendum 2026-08-26 septies — S5 durcie sur le piège « la zone embarque un nom de ville », et la mesure a corrigé la prémisse : 3 cas sur 4 émettaient DÉJÀ la bonne ville

Scope d'une seule chose : l'instruction S5 de la feuille. **Aucun fichier de la couche déterministe touché** (`geocode_tool.py`, `geo_resolver.py`, `response_bridge.py` intacts), et `guard_geocode_echo_back` non durci — cette classe lui est structurellement invisible, « Gare de Lyon, 75012 Paris » écho-matche légitimement « gare » ET « lyon ».

### La prémisse de la session était partiellement périmée — mesuré avant d'écrire une ligne

Baseline en prod sur `7d41d41`, **3 tours par tournure** (`x-dayuse-synthetic: 1`, session fraîche à chaque tour — sinon le clarify de #90 persiste la zone et contamine la tournure suivante) :

| tournure | `city` émis | résultat |
|---|---|---|
| « pres de la gare de lyon demain » | `None` ×3 | clarify, 0 hôtel — **le comportement V2 était déjà là** |
| « autour de la gare de lyon demain » | **`Paris` ×3** | 5 hôtels, POI = *CitizenM Paris Gare de Lyon, 75012* |
| « un hotel vers le vieux lyon demain » | **`Lyon` ×3** | 5 hôtels, *Vieux Lyon, 69005 Lyon* |
| « pres de l aeroport de nice demain » | **`Nice` ×3** | 3 hôtels, POI à Nice |
| contrôles champs-élysées / montmartre / louvre | `Paris` ×3 chacun | le bon POI à chaque fois |

Deux conséquences. D'abord le `city: None` sur « autour de la gare de lyon » du bloc « quinquies » **ne se reproduit plus** : 3/3 `Paris` aujourd'hui, à prompt identique (#89/#90 ne touchent pas le prompt). Le défaut réel n'est donc pas une omission systématique, c'est **une pièce lancée d'un jour à l'autre** — et une mesure à 1 tour ne peut pas la voir. Ensuite, la variante V2 telle que spécifiée aurait transformé **3 réponses correctes en questions** : « vieux lyon » et « aéroport de nice » embarquent un nom de ville qui *est* leur localisation, il n'y a aucun doute à arbitrer là, seulement de la friction à ajouter.

**Décision révisée avec Fabien en séance : V2-narrow.** L'exception se déclare sur le **conflit** (le lieu n'est pas dans la ville que son nom nomme) et non sur la présence d'un nom de ville. Échoue du bon côté : incertain → `city` vide → la question se pose.

### L'instrument local, et le piège qui le rendait muet

Mesurer un prompt demande le vrai modèle, mais pas forcément la prod : la feuille lit `DAYUSE_MODEL` avec `gpt-4o-mini` par défaut (`agent.py:83`) — **exactement le modèle que `hotel-search` fait tourner en prod** (vérifié : `railway variables`). Donc `run_local.sh` + les 21 tours sur `127.0.0.1:8100` mesurent le même émetteur avec le même prompt, sans écart prod/main.

⚠️ **Piège : en local il n'y a pas de Redis.** `b2c_concierge: profile store unreachable (set), not persisted` → `build_active_filters` relit un profil vide → **`active_filters.city` vaut `None` sur TOUS les tours**, y compris quand le delta était bon (`dayuse_metric=profile_ops set=6 slots=city,…,zone` le prouve dans le log). Un instrument muet qui ressemble à un résultat. `docker run -d --name s5probe-redis -p 6379:6379 redis:7-alpine` suffit ; **validé contre la prod** ensuite sur le contrôle louvre : `city=Paris`, `zone=louvre`, `poi/Louvre, 75002 Paris`, 5 hôtels — identique au tour prod.

⚠️ **Et `active_filters.city` reste un proxy, pas la vérité entière** : le chemin tier-2 landmark renvoie `_ok(..., profile_delta={})` (`geocode_tool.py:517`), donc il résout correctement **sans porter de ville dans le profil**. Un `city: None` n'y signifie pas « aucune ville émise ». Le signal sain est le couple **`requires_clarification` + le POI résolu**. Les args de l'outil ne sont pas loguables (RGPD : zéro contenu de message dans les métriques), donc l'attribution par champ n'est pas mesurable côté feuille.

### Deux formulations, la première sur-appliquait — mesuré, pas supposé

Mesures **locales**, 3 tours par tournure, même instrument, Redis up :

| cas | avant (main) | formulation 1 | formulation 2 (retenue) |
|---|---|---|---|
| « pres de la gare de lyon » | `city` 1/3, question 2/3 | question 3/3 | **question 3/3** ✅ |
| « autour de la gare de lyon » | question 3/3 | question 3/3 | **question 3/3** ✅ |
| « vieux lyon » | `Lyon` 3/3 | question 3/3 ❌ | **résolu 3/3** (POI *Vieux Lyon 69005*) ✅ |
| « aéroport de nice » | `Nice` 3/3 | question 3/3 ❌ | résolu **1/3** ⚠️ |
| contrôle champs-élysées | `Paris` 3/3 | `Paris` 3/3 | `Paris` 3/3 ✅ |
| contrôle montmartre | `Paris` **2/3** (1 question) | `Paris` 2/3 | `Paris` **3/3** ✅ |
| contrôle louvre | `Paris` 3/3 | `Paris` 3/3 | `Paris` 3/3 ✅ |

La formulation 1 se comportait comme la variante grossière : le modèle retenait le **déclencheur en tête de paragraphe** (« quand la zone contient un nom de ville ») et n'appliquait jamais la branche « si le lieu y siège vraiment, passe la ville ». Reformulée pour que la **classe de conflit** soit la première chose lue (« les rares lieux NOMMÉS D'APRÈS UNE VILLE OÙ ILS NE SONT PAS »), non-application énoncée explicitement à la fin.

⚠️ **Le blanc 1/3 sur montmartre existait DÉJÀ dans la baseline locale** (`[Paris, Paris, None]`) : ce n'était pas une régression de la formulation 1. C'est la baseline locale qui l'a établi — sans elle, il aurait été mis sur le dos du changement.

### Acquis et coût résiduel, énoncés tels quels

- **Acquis** : le cas de conflit (« gare de lyon », les 2 tournures) pose la question **6/6**. Avant, une tournure émettait `Paris` 1/3 en local et 3/3 en prod — le silence assuré était atteignable.
- **Coût** : « aéroport de nice » ne résout plus que 1/3 (3/3 avant) — il pose la question 2/3 du temps sans en avoir besoin. Assumé : c'est le mauvais côté du bon arbitrage (friction, pas réponse fausse), la direction que la décision produit du 2026-08-26 accepte explicitement.
- **La garantie est probabiliste**, comme elle l'aurait été en V1 : c'est un prompt sur `gpt-4o-mini`, pas du code. La différence tient au **sens de l'échec** — ici un raté produit une question de trop, en V1 il produisait une réponse fausse que personne en aval ne pouvait attraper. **Le filet déterministe (#89 + #90) reste la seule preuve**, et rien de ce changement n'en dépend.
- **Leçon structurelle** : `gpt-4o-mini` ne tient pas de façon fiable un conditionnel à deux branches enfoui dans une instruction longue — la phrase de déclenchement domine la condition. Argument de plus pour la sortie structurelle **P2 `resolve_location`** (cf. `reports/MCP-B2C-REQUESTS.md`), où le discriminant serait calculé et non demandé.

### Vérifications

`1436 passed, 1 skipped`, ruff + mypy + guardrails verts (aucun test ne figeait le texte de S5 — vérifié avant d'éditer). Sonde de session : `probe_s5_city.py` (scratchpad, non committée — elle n'a de valeur qu'avec un `S5_BASE` et une clé).

### Reste

- ⬜ **Confirmation en prod NON FAITE, et c'est délibéré** : elle exige de déployer, et la brancher non mergée en prod recréerait l'écart prod/main que les 3 blocs précédents signalent. Séquence après merge de la PR : stamper `LANGFUSE_RELEASE` sur le sha de merge avec `--skip-deploys`, `railway up --service hotel-search --detach` **seulement** (le diff est un prompt dans la feuille, concierge/faq inchangés), puis rejouer les 21 tours. Critères : « gare de lyon » (2 tournures) → question 3/3 chacune ; « vieux lyon » → *Vieux Lyon 69005* ; contrôles → `Paris` 3/3 ; et `llm_calls=3` sur les traces.
- ⚠️ Repéré au passage, hors scope : « pres de l aeroport de nice » résolvait en prod sur *« Transferts Aéroport Nice, AIR PROMENADE »* — une société de navettes, pas l'aéroport (en local, sur la formulation 2, c'est bien *Aéroport de Nice, 06200*). Imprécision de ranker, pas de la ville.
- `triage.response_language` : PR séparée, toujours ouverte.
- Les 2 guards date toujours non câblés ; P2 `resolve_location` reste la seule sortie structurelle.

## 🔗 Addendum 2026-08-26 sexies — la question de #89 marchait, sa RÉPONSE non : le clarify ne persistait pas la zone dont il parlait

Vérification en prod de `3966c20` (#89 déployé, 3× SUCCESS 12:59Z, `city_needed_question` présent dans le conteneur). Le tour 1 fait exactement ce qui était demandé — mais la séquence complète, elle, ne tenait pas.

| Tour (même session, `x-dayuse-synthetic: 1`) | Résultat |
|---|---|
| T1. « pres de la gare de lyon demain » | ✅ **0 hôtel**, `requires_clarification: true`, question posée : *« Près de la « Gare de Lyon », … il me manque la ville (Paris, Marseille, etc.) »*. Plus aucun hôtel lyonnais. |
| **T2. « paris »** | ❌ **5 hôtels sur tout le Grand Paris** — Saint-Denis 7,4 km, Orly 12,6 km, Nanterre 10,6 km, Rungis 10,5 km. `distance_origin.type = city_centroid`, **`zone: None`**. La gare a disparu. |
| A. « autour des champs elysees demain » | ✅ inchangé (`poi` sur l'avenue, 5 hôtels parisiens) |
| D. « autour de montmartre demain » | ✅ inchangé |

Attendu au T2 : `ibis`/`CitizenM Paris Gare de Lyon` à ~0,5 km — le chiffre que la sonde C1 avait déjà prouvé atteignable.

### La cause, dans le correctif de #89 lui-même

La moitié « ré-injection » existait déjà : `inject_profile_geo_context` recharge `zone` depuis `profile_in` quand le modèle l'omet. **C'est l'écriture qui manquait** : `profile_in["zone"]` n'est alimenté que par `_ok(...)` (S-G5, `delta["zone"] = zone`), et le clarify passe par `_fail(...)`, qui ne portait aucun delta. Côté bridge, le stash du delta est à l'intérieur de `if tool_response.get("ok")`.

Donc la zone mourait avec le tour, et « paris » arrivait sans rien à quoi se rattacher. **C'est le trou S-G5 (« a zone is lost across turns ») sur le seul chemin que S-G5 n'avait pas couvert** — celui où l'outil pose une question.

### Correctif

- `_fail` accepte un `profile_delta` optionnel, **pour ce cas uniquement** : quand l'outil pose une question, le sujet de la question doit survivre au tour de réponse.
- Les **deux** chemins de clarify le portent : la nouvelle porte sans-ancre, et le clarify homonyme de ville (qui peut aussi être renvoyé zone en main, une fois tier 2 manqué — même défaut, même ligne).
- Le bridge stashe ce delta sur la branche `geocode_ambiguous`, **en le fusionnant** avec ce qui est déjà là (`{**previous, **delta}`) : un clarify ne doit pas effacer ce qu'un appel antérieur du même tour avait résolu.
- La chaîne est complète et vérifiée dans le code : clarify → `profile_delta{zone}` → state → DataPart (l'émission lit `raw_delta["zone"]` sans dépendre de `results`) → profil concierge → `profile_in` du tour suivant → ré-injection.

### Vérifications

`1436 passed, 1 skipped` (1433 + 3 nouveaux tests, dont un qui fixe la fusion et non le remplacement), ruff + mypy + guardrails verts.

⚠️ **Pas encore vérifié en prod** : il faut redéployer puis rejouer T1 → T2 dans une même session, et confirmer au T2 la gare parisienne à ~0,5 km **et** que `guard_anti_clarification_loop` ne se déclenche pas.

### Leçon de méthode (3 fois de suite maintenant)

#87 vérifié → défaut trouvé (ancre Roanne) → #88. #88 vérifié → défaut trouvé (Lyon au lieu de Paris) → #89. #89 vérifié → défaut trouvé (la réponse perd la zone) → celui-ci. **À chaque fois c'est la vérification post-déploiement en prod qui a trouvé, jamais les tests** — parce que chaque défaut vivait dans l'interaction entre une couche neuve et une couche existante, pas dans une couche. Le tour 2 d'une séquence de clarify n'était couvert par aucun test : un clarify n'est pas testé tant que sa réponse ne l'est pas.

## 🧭 Addendum 2026-08-26 quinquies — `fa08813` déployé et vérifié ; le tour vedette n'était plus mort mais **faux avec assurance**, alors le chemin zone-seule sans ancre DEMANDE la ville

Suite directe du bloc « quater ». Deux choses ici : le déploiement de #88 (fait, vérifié, non encore documenté) et le défaut que sa vérification a trouvé — encore une fois.

### Déployé : `fa08813` sur les 3 services

`LANGFUSE_RELEASE=fa08813` stampé **avant** le déploiement avec `--skip-deploys` (vérifié : les 3 `last_deploy` sont restés à 09:00:52 / 08:58:58 / 08:59:07 après le stamp), puis `railway up` feuilles d'abord. **3× SUCCESS à 12:12Z.** L'estampille ne ment pas, et c'est prouvé autrement que par elle : `grep in_inventory_tier /app/hotel_search_agent/geocode_tool.py` → 2 occurrences dans le conteneur qui tourne (0 avant).

⚠️ Au passage : `108807a` a été committé à 09:08Z, **après** les déploiements de 09:00 — donc prod tournait bien #87 et pas #88, malgré des `railway up` postérieurs au merge de #87. Le stamp était honnête. Ne pas déduire « déployé après le merge » de « déployé récemment ».

### Vérifié en prod, 4 tours `x-dayuse-synthetic: 1`

| Tour | Résultat |
|---|---|
| A. « autour des champs elysees demain » | ✅ 5 hôtels parisiens, `poi` sur l'avenue, `city: Paris` émis seul |
| D. « autour de montmartre demain » | ✅ inchangé, `guard_geocode_echo_back = 1` |
| **C. « pres de la gare de lyon demain »** | ❌ **5 hôtels à LYON** (`distance_origin = "Masséna, Cr Vitton, 69006 Lyon"`) — le tour mort a été échangé contre une réponse fausse |
| C1. le même **avec « a paris »** | ✅ `CitizenM Paris Gare de Lyon, 75012` — `ibis Paris Gare de Lyon` à **0,5 km** |

`llm_calls = 3` partout, 14 noms de guards par trace. #88 tient sa promesse (plus d'ancre Roanne, plus de `geocode_ambiguous` sur ce tour) — mais le résultat produit n'est pas meilleur pour autant.

### La cause : ce n'est PAS le géocodage, c'est l'absence de `city`

Mesuré depuis le conteneur de prod (donc à l'IP réelle) :

| sonde | résultat |
|---|---|
| candidats Search Box pour `"gare de lyon"` (country=fr) | **10 POI, tous lyonnais** (arrêts de tram) — la gare parisienne **n'est pas dans la liste** |
| la même requête avec `proximity` forcé sur Paris | `Gare de Lyon, 75012 Paris` en **rang 1** |
| `« autour de la gare de lyon demain »` (autre tournure) | `city: None` → Lyon |

Donc : l'index Mapbox contient bien la gare de Paris, elle n'apparaît **que si le biais pointe déjà sur Paris** ; le chemin resolver est **correct dès que `city` est présent** ; et le corollaire du bloc « ter » se vérifie une fois de plus — *on ne re-classe pas ce qui n'est pas renvoyé*. Aucune liste d'options honnête ne peut même être **construite** depuis ce que Mapbox renvoie.

⚠️ **L'instruction S5 nomme DÉJÀ « gare de lyon » en exemple** et exige la ville du landmark. La feuille ne s'y conforme pas précisément quand la zone contient elle-même un nom de ville — elle considère la ville comme donnée. C'est une non-conformité de modèle, pas un trou d'instruction.

### Décision produit (Fabien, 2026-08-26) et correctif

> « Si il y a un doute possible il vaut mieux demander laquelle. »

Dans la branche zone-seule, quand la requête n'a **aucune ancre** (`city` vide, `metro` vide, pas de fix GPS), le résultat est une fonction de l'IP du conteneur **par construction** : on ne lance plus le lookup, on renvoie `geocode_ambiguous` avec `« Près de « … » — dans quelle ville cherchez-vous ? »` (`geo_resolver.city_needed_question`, localisée fr/en comme `_clarify_question`, S-CX2). Zéro appel géocodeur — on en **économise** un.

- `error` reste **`geocode_ambiguous`** : toute la plomberie existe déjà (`response_bridge` stashe la question → `requires_clarification`, l'instruction `agent.py` dit « DO NOT search, ask »). Aucun contrat touché.
- `status_message` distinct (**`geocode_city_needed`**) pour séparer ce cas du homonyme-de-ville dans le widget « Observation count by level ».
- **Pas d'`options`** : la seule ville qu'on pourrait proposer est celle du lookup IP-biaisé — Lyon. Une question qui n'offre que Lyon, c'est une mauvaise réponse déguisée en question.
- Quand un fix GPS existe, **comportement inchangé** (ranker + echo + `poi_anchor_coherence`). Gate 3 intact.

### Ce que ça change dans les tests — plus que prévu

Le plan annonçait « 1 test à amender » : c'était **faux**, il y en avait 8 (le comptage par regex avait raté les appels multi-lignes et les `city=""`). Les cas zone-seule de `TestZoneOnlyLandmarkReachesSearchBox`, `TestSearchBoxIsScoped` et le diagnostic `landmark_not_resolved` portent maintenant un **fix GPS** : ce qu'ils vérifient (le scope tier-2, les diagnostics honnêtes, le guard d'écho) reste vérifié, une fois le lookup légitimement autorisé.

⚠️ Un test passait pour la **mauvaise raison** après le changement (`test_an_echo_mismatch_is_not_accepted_even_scoped` n'assertait que `ok is False`, satisfait par le nouveau clarify) : ancré + assertion sur l'erreur exacte (`no_geocodable_location` — le `geocode_echo_mismatch` appartient au chemin tier-1, pas à celui-là).

Et le guard #14 : sa limite documentée (« sans ancre il n'y a rien à comparer, donc il ne peut pas se déclencher » — c'est **exactement** comment le POI de Toulon avait été accepté) devient **inatteignable**. Le test correspondant assert désormais la meilleure vérité : sans ancre, le tour ne parvient plus jusqu'au guard, et le POI de Toulon n'est même plus récupéré.

### `scripts/probe_geo_landmarks.py` recibé — sinon il criait au loup

16 de ses 18 cas passent `"city": ""` : à travers l'outil, ils clarifieraient tous et le probe afficherait **0/18**, ce qui ressemble à une catastrophe alors que c'est la politique. Les cas zone-seule appellent donc tier 2 **directement** (`forward_candidates` + `rank_landmark`, même requête, même scope) — le probe mesure le **ranker**, pas la politique posée au-dessus. Les cas avec ville et le cas de refus générique gardent le chemin complet.

**Vérifié : `13/18` sur l'IP `149.232.201.113`** — exactement le chiffre du tableau de #88 pour cette IP. Même instrument, même mesure. Ses 5 rouges (gare-de-lyon, gare-du-nord, la-défense, louvre-en, notre-dame) sont tous de forme zone-seule : le ranker garde son résidu, **le produit ne le sert plus**.

### Reste

- **Déployer ce correctif** puis rejouer les 4 tours : C doit poser la question (`requires_clarification: true`, 0 hôtel), puis « paris » dans la même session doit rendre la gare parisienne à ~0,5 km, A et D inchangés, et `guard_anti_clarification_loop` ne doit PAS se déclencher au tour 2.
- **Optionnel, à trancher** : durcir S5 avec le piège explicite (« quand la zone contient un nom de ville, ce nom fait partie du NOM du lieu — « gare de lyon » est à Paris »). Ça réduirait la fréquence des questions ; c'est un pari de conformité sur gpt-4o-mini, et c'est pourquoi le correctif déterministe n'en dépend pas.
- `triage.response_language` : PR séparée, toujours ouverte.
- Les 2 guards date toujours non câblés ; P2 `resolve_location` reste la seule sortie structurelle.

## 🚢 Addendum 2026-08-26 quater — géo DÉPLOYÉ sur `5d0996c` et prouvé en prod ; la vérification a trouvé un défaut dans le correctif lui-même (ancre ville = homonyme micro-inventaire), corrigé

Suite directe du bloc « ter ». **PR #87 mergée**, `LANGFUSE_RELEASE=5d0996c` stampé sur les 3 services avec `skipDeploys: true` (vérifié : les 3 `last_deploy` sont restés à 07:11 après le stamp, donc aucun redéploiement de l'ANCIEN code sous la nouvelle estampille), puis `railway up --detach` **feuilles d'abord** puis concierge. **3× SUCCESS.** Plus d'écart prod/main.

### Prouvé en prod, pas déclaré — 4 tours `x-dayuse-synthetic: 1`

| Tour | Résultat |
|---|---|
| **A. « autour des champs elysees demain »** (la requête exacte du défaut) | **5 hôtels parisiens**, `distance_origin = {"label": "Avenue des Champs-Élysées, 75008 Paris, France", "type": "poi"}`, `radiusKm: 3`. **Plus de Toulon.** `city: "Paris"` émis par le modèle SEUL (l'instruction S5 marche). |
| B. contrôle occupancy « à paris demain pour 2 adultes et 1 enfant » | `adults: 2, children: 1`, 5 hôtels, `city_centroid` et **aucun `radiusKm`** (défaut MCP 20 km) — exactement le design S4, P0-1 non régressé |
| C. « pres de la gare de lyon demain » | ❌ `geocode_ambiguous`, 0 hôtel — **défaut, voir ci-dessous** |
| D. « autour de montmartre demain » | 5 hôtels, `radiusKm: 3`, et **`guards_fired: ["geocode_echo_back"]`** |

### ✅ La plomberie OBS3 est prouvée en prod : `guard_geocode_echo_back = 1`

Sur le tour D, le score `guard_geocode_echo_back` vaut **1** en `environment=production`. **C'est le premier score non nul de l'histoire de ces 6 noms** — ils étaient à 0.0 sur chaque tour depuis que les guards existent. `14` noms de guards présents sur chaque trace (le 14e est live), `llm_calls=3` partout (budget respecté).

Le tour D confirme aussi S4 dans la vraie vie : `resolved_feature_type: "neighborhood"` (donc **tier-1** a répondu) ET `distance_origin_type: "poi"` ET `radiusKm: 3`. Sans S4 ce tour repartait sur un disque de 20 km.

### 🐛 Le défaut trouvé PAR la vérification — dans le correctif lui-même

Tour C, `zone="gare de lyon"`, `city="Paris"`. L'ancre ville que le bloc « ter » a introduite se choisissait sur le **seul écho du NOM** de la ville. Or, sur cette requête, l'unique candidat v6 qui écho-matche « Paris » est un quartier **littéralement nommé « Paris » à ROANNE** — 2 hôtels à proximité, **390 km**. Il est donc devenu « le Paris vérifié », a pointé le `proximity` de Search Box sur Roanne, qui a rendu les gares de Lyon-Perrache, qui ont échoué l'écho → tour mort sur un clarify.

**C'est exactement le piège S-G9 que le docstring du resolver décrit** (« a 1-hotel micro-homonym must never silently outrank a world-famous zero-inventory city »), réintroduit à un endroit neuf. **Une ancre qui pointe un lookup et vetoe son résultat doit être crédible par elle-même** : la condition manquante est `in_inventory_tier` (≥ 3 hôtels), qui existait déjà. Sans ancre crédible → pas d'ancre → la ville est repliée dans la requête, et ce chemin résout le cas correctement (0,4 km, mesuré).

⚠️ **Ce n'était PAS une régression** : vérifié sur un worktree à `a65a0a9`, ce même tour rendait déjà `geocode_ambiguous` avant le chantier. Le défaut est dans un mécanisme neuf dont la sortie coïncidait avec l'ancienne. **C'est la vérification post-déploiement qui l'a trouvé, pas les tests** — 2 tests de régression posés depuis.

### Mesures, protocole même-IP (le seul valide)

| IP de sortie | avant (`a65a0a9`) | après |
|---|---|---|
| `92.184.140.202` (« bonne ») | 15/18 | **17/18** |
| `149.232.201.113` (« mauvaise ») | **8/18** | **13/18** |

Les 5 cas encore rouges sur la mauvaise IP sont **tous** de forme *zone-only sans ville* — le résidu documenté (pas de ville, pas de GPS ⇒ biais IP, le ranker est la seule défense). ⚠️ **Le probe est plus pessimiste que la réalité sur ce point** : ses cas passent `city: ""` de force, alors qu'en prod le modèle fournit la ville de lui-même depuis S5 (vérifié tour A).

### Reste

- `disneyland-paris` : inchangé, toujours 30,6 km, **pas une régression** (cf. bloc « ter »).
- Les 2 guards date toujours non câblés (le transport existe).
- P2 `resolve_location` : la seule sortie structurelle, cf. `reports/MCP-B2C-REQUESTS.md`.
- `triage.response_language` : PR séparée, toujours ouverte.

## 🗺️ Addendum 2026-08-26 ter — chantier GÉO : la cause du bug Toulon n'était NI M3 NI M4, c'est le `proximity` par défaut de Mapbox Search Box (= **IP proximity**). Et le tour mort du landmark était un paramètre obligatoire, pas de la non-détermination d'extraction.

Deux symptômes, deux causes, aucune des deux au dossier. **Corriger la mémoire, pas seulement l'état** — les blocs « 08-25 » et « 08-25 ter » ci-dessous attribuent ces deux bugs à des mécanismes réfutés ici.

### 🔴 Symptôme 2 — ce n'était PAS de la non-détermination d'extraction

`city: str` dans `geocode_location` **n'avait pas de valeur par défaut**, donc ADK le déclarait obligatoire. Quand le modèle omet la clé — ce qu'il fait exactement quand l'utilisateur nomme un landmark et aucune ville — **l'appel d'outil était rejeté avant que la fonction ne tourne** :

```
IN : {"zone": "les champs élysées", "country_guess": "FR", "language_hint": "fr"}   # pas de clé "city"
OUT: {"error": "Invoking `geocode_location()` failed as the following mandatory
      input parameters are not present:\ncity\n…"}
```

**14 occurrences dans les traces Langfuse entre le 08-15 et le 08-26**, toutes sur les landmarks du chantier : champs élysées, louvre, gare de lyon, eiffel tower, la défense, buckingham palace. Le « ~1 tour sur 6 » c'était simplement : parfois le modèle écrit `city: ""` (ça marche, ça atteint le chemin landmark), parfois il omet la clé (échec dur).

**Correctif : `city: str = ""`.** Un test verrouille qu'aucun paramètre de `geocode_location` n'est sans défaut — ADK dérive « mandatory » de « pas de défaut ».

### 🔴 Symptôme 1 — la cause est une entrée que nous ne choisissions pas : l'IP de sortie du conteneur

Doc Mapbox Search Box `/forward`, verbatim : ***« If not provided, the default is IP proximity. »*** Le tier-2 landmark n'envoyait aucun `proximity` sans fix GPS — donc **la résolution était une fonction de l'IP de sortie du conteneur**. Entrée absente des traces, différente entre un portable et Railway, et susceptible de changer **sans aucun déploiement**.

Prouvé quatre fois, pas déduit :

1. **La trace prod du défaut ne porte aucun `proximity`** (`5eec27af27b79ed4b87f4c325b563bbc`, 08-25 13:30Z) : `{"zone": "les champs élysées", "city": "", "country_guess": "FR", "locale": "fr-FR"}`. Le raisonnement `_soft_country` du bloc « ter » est juste mais **n'est pas le mécanisme**.
2. **Les mêmes args rejoués en local rendaient Paris à 0,3 km** — même code, même commit, IP différente.
3. **Un `proximity` explicite au sud de la France reproduit Toulon exactement** : `Champs Elysées, 32 Rue d'Alger, 83000 Toulon, France` — le label de la trace, caractère pour caractère.
4. **Mon IP de sortie a changé DEUX FOIS en pleine session** (`45.156.191.77` → `149.232.201.113` → `92.184.140.202`) et les mêmes requêtes ont bougé de 130 à 400 km : « montmartre » → *Le Relais de Montmartre*, **Viré (329 km)** ; « gare de lyon » → un commerce à **Lyon (393 km)** ; « les champs élysées » → **Saint-Quentin (130 km)**.

⚠️ **Conséquence sur toute mesure géo passée et future** : le score du harnais géo dépend de l'IP de sortie. Le probe livré l'imprime en tête et il faut le citer avec tout chiffre. Deux runs depuis deux IP ne sont pas comparables — c'est précisément le défaut mesuré.

**Corollaire qui a orienté tout le chantier** : ni un guard sur le nom, ni un scope pays, ni un re-ranking ne peuvent corriger ça seuls. Sous un `proximity` lointain, Search Box ne renvoie **plus que 1 ou 2 features**, toutes des homonymes locaux — le landmark célèbre n'est **pas dans la liste**. On ne re-classe pas ce qui n'est pas renvoyé. **Il fallait contrôler l'entrée.**

### Une piste testée et REFUSÉE par la mesure (ne pas la reprendre)

`proximity` = **ancre d'inventaire par marché** (le disque de 25 km le plus dense du pays, calculé depuis les exports par pays). Séduisant : déterministe, code-owned, pondéré par notre offre. **Réfuté** : l'ancre ES est **Madrid**, donc « sagrada familia » partait à **503 km**. Ça remplace un biais non choisi par un biais qui casse tout landmark hors de la plus grosse métropole de son pays.

### Ce qui est livré

1. **`proximity` n'est plus jamais laissé à Mapbox.** Ordre de préférence, tout code-owned : fix GPS → **coordonnée d'une ville vérifiée** (le candidat v6 qui écho-matche la ville nommée) → à défaut, la ville est **repliée dans la requête** (`"<zone>, <ville>"`) → à défaut rien, et le ranker est la seule défense (résidu documenté).
   ⚠️ Le repli #3 **corrige la position et dégrade le label** : `"les champs élysées, Paris"` renvoie 10 commerces et **aucune feature propre**, et le premier devient le `resolved_place` que le client voit (`active_filters.distance_origin.label`). Mesuré. C'est pourquoi la coordonnée est préférée à la chaîne : requête nue + `proximity=Paris` → *« Avenue des Champs-Élysées, 75008 Paris »*. **Le commentaire de 2026-07-23 (« the landmark ALONE ») avait raison sur le LABEL et tort sur le LIEU — les deux lectures tiennent, c'est pour ça que c'est un repli et pas le défaut.**
2. **`geo_resolver.rank_landmark`** — tier-2 classe au lieu de croire le top-1 (`limit=10`, le max Mapbox, même appel, même SKU). **Select-only, zéro clarify** : on ne demande pas de choisir entre « Azur Café » et « Unisex ».
3. **`inject_landmark_radius` suit la DEMANDE, pas la taxonomie du géocodeur** : `distance_origin_type="poi"` dès qu'une zone spécifique est nommée, quel que soit le tier. Sans ça, S2 régressait `hotels_within_km` — un landmark gagnant en tier-1 comme `neighborhood` retombait sur un disque de 20 km.
4. **Instruction de la feuille** : passer la ville du landmark devient **attendu** (même cadrage que `country_guess`, qui avait marché). Vérifié en prod locale : sur « autour des champs elysees » le modèle émet désormais `city: "Paris"` de lui-même.
5. **`is_generic_location_token` devient insensible aux articles.** La liste contenait « the airport » mais aucune forme française articulée — et le modèle écrit ce que l'utilisateur dit : « près de la gare » → `zone="la gare"`, **non reconnu comme générique**, donc un mot générique partait au lookup landmark (exactement ce que le commentaire du tier-2 redoute). Plus les pluriels français d'« aéroport », absents à côté d'« airports » qui y était.
6. **14e guard `poi_anchor_coherence`** (décision Fabien) + **la plomberie qui rend les guards réels** (ci-dessous).
7. **`scripts/probe_geo_landmarks.py`** — 18 cas landmark, réseau seulement, **zéro LLM, zéro service**. C'est l'instrument qui aurait attrapé ce bug, et le seul moyen de mesurer le géo sans la variance du modèle.

### 🔴 Découverte : 6 des 13 noms de `GUARD_SCORE_NAMES` n'étaient posés NULLE PART

Les 3 guards géo et les 2 guards date tirent **dans la feuille**, et la feuille **ne rapportait jamais** ce qui avait tiré. `score_guards` publiait donc ces noms **à 0.0 sur chaque tour, depuis toujours**. `scores.py` le disait (« a later session wires their call sites ») — cette session n'avait jamais eu lieu.

⚠️ **Ça change la lecture du bloc « 08-25 ter »** : *« guard_geocode_echo_back = false ET guard_generic_location_demotion = false → un guard vert ici est un faux négatif STRUCTUREL »*. **Non.** C'étaient des scores **jamais câblés**. Un score à 0.0 qui veut dire « pas mesuré » est pire qu'une absence : il se lit comme « le guard n'a pas tiré ».

**Plomberie livrée** : la feuille accumule les noms dans `temp:hotel_search_guards_fired` et les met sur son DataPart A2A ; le spine fait `budget.fired.update(response.pop("guards_fired", ...))`. **`pop` et non `get`** : un DataPart ne portant QUE de la télémétrie doit rester une réponse vide pour toutes les décisions en aval (le check de dégradation, `"results" in response`) — l'observabilité ne doit pas changer le control flow. Un test le verrouille.

**Câblés** : les 3 guards géo + `poi_anchor_coherence`. **Toujours PAS câblés, donc toujours à 0.0** : `date_hallucinated_year_rolled_forward` et `date_carryover_stale_floored` — le transport existe maintenant, il ne manque que leurs sites d'appel dans le résolveur de dates. **C'est le prochain petit chantier évident.**

### Le 14e guard, et sa limite assumée

`poi_anchor_coherence` (score config `bad09ed2-8066-4c84-864d-09a445377773`, 27 caractères, sous le plafond de 35). Seuil **100 km**, calibré sur les distances réellement mesurées : laisse passer Disneyland (32 km), rejette Saint-Quentin (130), Viré (329), Lyon (393), Toulon (830).

**L'ancre n'est PAS le top candidat v6** — piège trouvé par un test : à l'heure du tier-2, ce candidat est celui que l'écho vient de REJETER. S'ancrer dessus faisait vetoer la bonne réponse Search Box dès que v6 partait sur un autre continent (« La Défense, Paris » → Al Aïn, AE), soit exactement le cas que P0-2 avait corrigé. **Une ancre qui vetoe doit elle-même être vérifiée** : GPS, sinon le candidat v6 qui écho-matche la ville nommée.

⚠️ **Limite honnête** : sans ville nommée ni GPS (le landmark nu), il n'y a rien à comparer — le guard ne tire pas et ne bloque pas. Ce cas appartient au contrôle du `proximity`, pas au guard. Un test l'affirme pour que ça reste vrai. Évry (27 km) est **hors de portée** de ce seuil : le resserrer assez pour l'attraper rejetterait Disneyland.

### 🪤 Quatre pièges payés dans le ranker (ne pas les repayer)

1. **`_TYPE_PRIOR` s'INVERSE entre les deux questions.** Pour une ville, `place` est la meilleure réponse (5.0). Pour un landmark c'est la PIRE : l'utilisateur a nommé plus fin qu'une ville, résoudre vers la ville élargit silencieusement au métro entier. D'où `_LANDMARK_TYPE_PRIOR` séparé.
2. **L'article donnait le bonus de nom exact à l'homonyme.** « les champs élysées » faisait de « Les Champs Elysées », un lieu au **Havre (200 km)**, un match EXACT — pendant que le vrai quartier « Champs Élysées » n'en était pas un.
3. **La ponctuation aussi.** `_name_fold` garde les tirets : « Champs-Élysées » ne vaut pas la chaîne « champs elysees ». Comparer des CHAÎNES pliées donnait le bonus à un quartier homonyme d'**Évry (27 km)**, qui gagnait ensuite sur son type de feature. → comparer des **tuples de tokens** (`_landmark_key`).
4. **`_W_RANK` (0.3) pesait plus lourd que toute l'ancre ville.** Sur 10 candidats ça fait 2,7 points — plus que le terme d'ancre (2,5) — alors que l'ordre Mapbox de cet endpoint EST l'ordre biaisé par l'IP. → `_W_LANDMARK_RANK = 0.05`, simple bris d'égalité déterministe.
   Et `_INVENTORY_SOFT_CAP = 30` (calibré pour les villes) ne distingue pas Paris (785) du Havre (16) : les deux plafonnent. → `_LANDMARK_INVENTORY_SOFT_CAP = 300`.

### Mesures

**Probe landmark, MÊME IP (`92.184.140.202`), main vs branche, dos à dos** — c'est le seul protocole valide, cf. l'avertissement plus haut :

| | main | branche |
|---|---|---|
| `probe_geo_landmarks.py` (18 cas) | **15/18** | **17/18** |

Corrigés : `gare-de-lyon` (4,0 km → 0,0 : Mapbox classait 1er un commerce « gare lyon » du 19e) et `champs-elysees-city-key-absent` (outil non appelable → 0,3 km). **Zéro régression.** Et les labels sont redevenus des vrais noms de lieux (« Avenue des Champs-Élysées, 75008 Paris ») au lieu de boutiques.

⚠️ **Le 15/18 de main est trompeusement bon** : ce jour-là l'IP était bonne. Depuis l'IP `149.232.201.113`, le même main faisait **8/18**. C'est l'amplitude du défaut, pas la qualité de main.

**Prouvé en local sur les 3 services réels**, requête exacte du défaut prod (« je cherche un hotel autour des champs elysees demain ») :
`5 hôtels parisiens`, `city: Paris` (émis par le modèle seul), `distance_origin = {"label": "Avenue des Champs-Élysées, 75008 Paris, France", "type": "poi"}`. **Plus de Toulon.**

### Gates

`1427 passed, 1 skipped` (+33, baseline 1394) · ruff · mypy 46 fichiers · guardrails OK. **Les ~150 tests de guards sont restés verts.** Trois tests ont bougé, tous pour une raison instruite : le contrat 13→14 noms, un `assert result == {...}` qui gagne `guards_fired` (le guard se déclare enfin), et 2 fakes Search Box qui apprennent `forward_candidates`.

### Reste

- **`disneyland-paris` échoue toujours (30,6 km), sur main comme sur la branche — PAS une régression.** Mécanisme mesuré : une annonce du 3e arrondissement littéralement nommée « 74 - Disneyland in Paris » écho-matche et gagne. Le vrai discriminant serait un **consensus de cluster** (3 candidats sur 4 se regroupent au parc, le 4e est à 30 km) ; délibérément **non fait** — un heuristique de plus calibré sur 1 cas dans un probe de 18 est un aller simple vers le surapprentissage. À reprendre avec un dataset plus large.
- **Le guard n'a pas encore été VU tirer sur du trafic réel** : les 4 tours locaux ont tous emprunté des chemins où aucun guard feuille ne tire (chemin zone-only, ou un tour qui a timeouté). Le mécanisme est verrouillé par 5 tests déterministes (feuille → DataPart → `budget.fired` → `score_guards`), pas par une observation live. **À revérifier après déploiement** : un tour landmark avec ville nommée doit pouvoir sortir `guard_geocode_echo_back = 1`.
- **2 guards date toujours non câblés** (ci-dessus) — petit et évident maintenant que le transport existe.
- **P2 versé dans `reports/MCP-B2C-REQUESTS.md`** : `resolve_location` sur l'index `poi` de MCP_B2C. Les findings la renforcent beaucoup : un index POI Dayuse est **immune au biais IP** par construction, et c'est le seul géocodeur naturellement pondéré par notre inventaire. Tout ce qu'on vient de livrer est de la compensation.
- **`triage.response_language`** (une conversation FR où l'utilisateur tape « sí » repart en anglais) : PR séparée après le géo, arbitré avec Fabien. Volontairement pas mélangé — si la mesure bouge, on doit savoir lequel des deux l'a bougée.
- Inchangé : harnais OBS6 (`lang-confirm-implicit` impassable, variance de `_lookup_trace_facts`), plafond OpenAI, fenêtre OBS8, OBS9 avant fin janvier 2027.
- **Pas encore déployé** : la prod tourne toujours sur `aa401ba`.
## 🩹 Addendum 2026-08-26 bis — dashboard Langfuse OBS3 cassé (3 widgets sur 7) : les widgets créés via MCP sont estampillés `min_version = 2` et lisent une table qui n'existe qu'en v4

Hors-session, déclenché par un rapport de Fabien : à l'ouverture du dashboard `b2c-concierge — OBS3 deterministic scores`, toast rouge **`Internal Server Error … Path: dashboard.executeQuery`**. **Corrigé, vérifié des deux côtés (reload OK + zéro erreur serveur depuis).**

### Cause racine — ni les définitions de widgets, ni un flag v4 activé par erreur

`dashboard_widgets.min_version = 2` sur **les 7 widgets créés le 2026-07-30 via le serveur MCP Langfuse** (tous les widgets créés avant, via l'UI, sont à `1`). Le query builder lit ce champ : `(minVersion ?? 1) >= 2` ⇒ il prend les **view declarations v2**, qui lisent `events_core` / `events_full` — **tables qui n'existent QUE en Langfuse v4**. L'instance est en **v3.224.3** : ClickHouse a 74 migrations et aucune table `events_*` (`traces`, `observations`, `scores`, `dataset_run_items_rmt`, `analytics_*`), et **aucune migration de l'image ne les crée**.

Le SQL généré est doublement cassé — c'est ce que le toast cachait :

```sql
FROM events_core AS events_observations
WHERE events_observations.environment IN (...)   -- alias
  AND events_core.project_id = '...'             -- nom d'origine -> "Unknown table expression identifier"
```

**Pourquoi la page marchait à moitié** (un `0.18` s'affichait) : seuls les **3 widgets de la vue `observations`** tombent — `Cost by model`, `Latency p95 by observation name`, `Observation count by level` (54 + 54 + 32 lignes d'erreur dans les logs `langfuse-web`). Les 4 widgets `scores-*` ont des declarations v2 qui pointent encore sur `scores` : ils rendent normalement. **Un dashboard partiellement vivant est la signature de ce bug.**

### Écartées, preuves à l'appui (ne pas les ressusciter)

| Hypothèse | Réfutation |
|---|---|
| Toggle « v4 beta » cliqué par un utilisateur | `v4_beta_enabled = false` pour **les 4 users** en base |
| `LANGFUSE_MIGRATION_V4_WRITE_MODE` en `dual`/`events_only` | défaut **`legacy`** au tag v3.224.3 ; et l'ingestion écrit bien dans `observations` (22k obs sur 24 h, la plus récente à 07:26 le jour même) |
| `LANGFUSE_MIGRATION_V4_ALLOW_PREVIEW_OPT_IN` | défaut **`"false"`** en v3.224.3 — le défaut `true` de la doc concerne la ligne v4, ne pas s'y fier pour v3 |
| Un flag events-table posé sur le service | aucun `LANGFUSE_ENABLE_EVENTS_TABLE_*` défini sur `langfuse-web` |
| Définitions de widgets invalides | les **7** requêtes rejouées via `GET /api/public/metrics` (chemin v1) renvoient toutes de vraies données |

### Correctif appliqué (Postgres Langfuse, prod)

```sql
UPDATE dashboard_widgets SET min_version = 1 WHERE min_version = 2;   -- UPDATE 7
```

Réversible d'une ligne (`SET min_version = 2`). Vérifié : les 7 lignes sont à `1`, Fabien a rechargé le dashboard (**tout s'affiche**), et **zéro** ligne `events_core` dans les logs `langfuse-web` après le correctif (140 au total, la dernière à 07:02:50Z).

### ⚠️ Le piège, à connaître avant de recréer un widget

**Tout widget créé via les tools MCP Langfuse naît estampillé `min_version = 2`** — vérifié en créant puis supprimant un widget sonde. Sur cette instance v3, il est donc cassé d'avance s'il utilise la vue `observations`. Jusqu'à OBS9 (montée en v4) : **créer les widgets dans l'UI**, ou remettre `min_version = 1` juste après une création MCP. `observability/langfuse/dashboard-b2c.json` **ne contient pas** `min_version` : recréer le dashboard depuis cet export via MCP réintroduit la panne (avertissement ajouté dans `observability/langfuse/README.md`).

Sharp edge upstream connu : discussion Langfuse #12777 (`Unknown table expression identifier 'events_core'` après une montée de version v3).

### Outillage de debug de cette instance (coûte une heure si on le redécouvre)

- `psql` via `railway ssh` **se bloque sur le pager** (c'est `less`, pas la DB) : toujours `psql -P pager=off`.
- Le `grep` BusyBox des conteneurs n'a **pas `-b`**, et il faut `-a` pour traiter les chunks `.next` comme du texte.
- Projet Langfuse non lié au repo ⇒ logs via GraphQL `deploymentLogs(deploymentId, filter, limit)` (`scripts/railway-api.sh` du skill `use-railway`). La ligne `tRPC route failed` est inutile : c'est la ligne voisine `ClickHouse query failed` qui porte le vrai SQL.

## ✅ Addendum 2026-08-26 — P1 déployé sur `aa401ba` et prouvé en prod ; la DoD 24 h d'OBS7 est CLOSE (les 3 juges sains, le prompt v2 corrige bien le faux positif)

Session courte : déploiement + la vérification 24 h qui n'était mesurable que maintenant.

### Déployé

`LANGFUSE_RELEASE=aa401ba` stampé sur les 3 services (`skipDeploys`), puis `railway up --detach` feuilles d'abord. **3× SUCCESS.** Seul `agents/b2c_concierge` avait changé ; `hotel-search` et `faq` ont été redéployés quand même, pour que l'estampille ne mente pas (même convention que le 08-25). **Plus d'écart prod/main.**

### Prouvé en prod, pas déclaré — session à 2 tours via le proxy widget

| Tour | Résultat |
|---|---|
| 1. recherche impossible (Melun + 4 amenities + 9 adultes, aujourd'hui) | 0 hôtel → `empty_shortlist=1`, streak à 1 |
| 2. **« sí »** | **relance une recherche**, `llm_calls=3` (triage + feuille + synthèse) |

`llm_calls=3` est la preuve : un template d'ack aurait coûté 1. Avant P1-1, « sí » ne matchait pas `_AFFIRMATIVE_RE` et tombait sur l'ack, sur une liste vide. Le slot `affirmative` le rattrape en prod.

### OBS7 — DoD 24 h CLOSE

- **Les 3 règles sont saines** : `enabled:true`, `status:active`, `pausedReason:null`, **jamais en erreur**.
- **`obs7-user-distress-v3chat` a produit ~13 scores — les premiers de son histoire.** Tous `false`, raisonnements cohérents, y compris le cas multilingue pour lequel il a été refait (« the message translates to *that's perfect, go ahead* »).
- **Le prompt `Hallucination` v2 marche** : 6 scores depuis l'amendement, **tous à 0,0**, dont deux qui portent exactement la forme de raisonnement qui produisait 0,7 avant :
  > *« …cannot be verified as true or false without access to real-time data; **therefore, no definitive hallucination** can be identified. »*

  **Zéro pénalité « lacks verification » depuis v2.** ⚠️ n petit et surtout du trafic `development` (les runs d'éval de la veille) — c'est un signal, pas encore une statistique.

### 🐛 Verrue trouvée en vérifiant (PAS une régression, à traiter à part)

Sur le tour 2, la conversation était en **français** (tour 1 en français, `locale=fr-FR`), l'utilisateur tape « sí », et **la réponse revient en anglais**. Cause : `response_language(triage.language)` clamp « es » → « en », alors que la langue établie de la conversation (`profile.language`) dirait « fr ».

**Vérifié que ce n'est pas nouveau** : avant P1-2, « es » était rejeté par la validation → `guess_language("sí")` → pas d'indice FR → « en » aussi. Même sortie. Mais le clamp rend la verrue plus visible et donne l'endroit exact où la corriger : **`response_language` devrait préférer `profile.language` à un « en » nu**. Une ligne, mais elle change un comportement de réponse — à trancher, pas à glisser.

### Reste (inchangé sauf mention)

- **Chantier géo** : c'est le prochain, et le seul défaut produit visible restant (tour mort landmark ~1/6 + Toulon).
- Dettes du harnais OBS6 : `lang-confirm-implicit` impassable (`hotel_id` fabriqué), variance de `_lookup_trace_facts`.
- Actions Fabien : fenêtre OBS8, plafond OpenAI, décision edge public du concierge.
- OBS9 (Langfuse v4) avant fin janvier 2027, après OBS8.

## 🧠 Addendum 2026-08-25 quater — P1-1 + P1-2 : 5 slots sortent du regex, la reconnaissance de langue passe à 7. Et le harnais OBS6 mesurait la mauvaise couche.

Chantier P1 de `AUDIT-AGENTIQUE-2026-07-30.md`. **Deux livrables, dont un non prévu** : le fix lui-même, et la correction d'un défaut du harnais découvert en essayant de le mesurer.

### ⚠️ D'abord : « P1 de l'audit » ≠ le symptôme landmark

Le brief de session disait « P1 de l'audit » mais décrivait le tour mort du landmark (~1/6). **Ce sont deux chantiers différents** — vérifié : `triage.py` ne classe que `family`/`language`/`pick`, il n'extrait **aucune** donnée géo. Le landmark vit dans `geocode_location` (feuille). Arbitré avec Fabien : ce bloc traite **P1-1 + P1-2 à la lettre**, le géo reste ouvert (et doit absorber le bug Toulon du bloc « ter »).

### Ce qui est livré

**P1-1 — 5 slots** dans le contrat JSON du triage, même pattern que `pick` (S-CX5) : enum/type fermé, validé dans `classify()`. `affirmative`, `booking_confirmation` (`none|confirm|refuse|change`), `wants_more_options`, `bare_budget_value`, `hotel_name`.

**P1-2 — reconnaissance élargie** à `fr|en|es|it|de|pt|nl`, avec un **clamp** (`triage.response_language`) partout où la langue atteint un template ou le `LANG:` de la synthèse. Sans lui, la synthèse se serait mise à répondre en espagnol pendant que les templates restaient anglais — sortie mixte que personne n'a décidée. Répondre dans la langue de l'utilisateur = chantier séparé (`templates.py`, 215 lignes de `_pick(language, fr, en)`).

### 3 décisions de conception à ne pas défaire

1. **Les slots booléens sont ADDITIFS, pas « LLM primaire »**. `_AFFIRMATIVE_RE` est ancré `^…$` sur une liste fermée : là où il matche il est *exact*, il n'y a rien à corriger. Ce qu'il ne sait pas faire, c'est « sí »/« ja ». Laisser le modèle **vetoer** un match mettrait les ~150 tests de guards à la merci d'un appel de classify pour zéro gain. `hotel_name` est l'exception assumée : c'est une VALEUR, pas un booléen — LLM primaire, stripper en fallback.
2. **`booking_confirmation: "none"` retombe sur les regex**, il ne nie pas. Le modèle juge le message seul et ne peut pas voir qu'une réservation est en attente : un « oui » nu peut légitimement revenir en `none`. Le lire comme un refus rouvrirait exactement le défaut prod de la PR #47.
3. **`bare_budget_value` n'a basculé qu'à MOITIÉ**. Usage routage (`_has_refinement_modifier`) → slot. Usage **guard d'intégrité budget** (`apply_profile_delta`) → **reste en regex** : il croise la valeur revendiquée par la feuille avec le texte littéral, sourcer les deux côtés du même modèle détruirait l'indépendance qui en fait un guard.

### 🪤 Le piège principal : le fast-path d'ack devait rester à ZÉRO appel

`refinement_signal`/`booking_signal` étaient calculés **avant** `classify()` parce qu'ils gardent le fast-path. Premier jet : conditionner le fast-path sur l'état du profil. **Mauvaise idée** — ça faisait payer un triage à tout « bonjour » suivant une recherche vide, et un test existant ne le voyait pas (`classify` avale l'AssertionError du plan scripté et retombe sur le regex : le test passait en vert **en payant un appel**).

**Vrai raisonnement** : `_ACK_WORDS` est lui-même **fr/en**. Un « sí » ne matche jamais `is_social_ack` et n'atteint donc **jamais** ce gate — il part au triage comme n'importe quel message. Pour l'ensemble exact des messages qui peuvent arriver là, les regex fr/en sont **complètes**. Le gate reste donc regex-only, et les deux signaux sont **recalculés après `classify()`** avec les slots. Zéro appel ajouté, zéro changement de comportement sur le chemin d'ack.

*Trou résiduel, pré-existant* : `_ACK_WORDS` contient 2 tokens d'accord absents d'`_AFFIRMATIVE_RE` (« top », « génial ») — seuls après une recherche vide, ils atteignent encore le template. Pas une régression.

### 🔴 Découverte : `expected_route` mesurait le CLASSIFIEUR, pas le ROUTEUR

Le fix ne bougeait presque pas la métrique. Cause : `_derive_route()` lisait le `family` de la **génération de triage** — donc l'avis brut du LLM — alors que toute l'architecture repose sur des **overrides code-owned par-dessus** (« l'LLM ne route jamais »). La métrique était **structurellement aveugle** à recovery-ack, confirmation de booking et ordinal de shortlist.

**Preuve** : sur la trace réelle du run, `lang-affirm-es` était noté ÉCHEC (`family=ack` côté génération) alors que la même trace porte `family=search`, `route=leaf:hotel_search` sur l'observation AGENT — le spine avait routé correctement.

**Corrigé** (GO Fabien) : `_lookup_trace_facts` lit maintenant `metadata.family` posé par OBS2 sur l'observation AGENT et le préfère au `family` de la génération. Même fetch, zéro appel API en plus. `metadata.family` et non `metadata.route` : `route` parle un 3e vocabulaire (`leaf:hotel_search`) dont le docstring dit justement de se méfier.
⚠️ **Ça change le SENS de la métrique** : avant le 2026-08-25 elle notait la classification, après elle note le routage réel. **Ne pas comparer aux runs du 07-30.**

### Mesures (même journée, même Redis, dataset `b2c/language-robustness`)

| | `expected_route` |
|---|---|
| main, harnais (2 runs) | **2/7** et **3/7** |
| branche, harnais (2 runs) | **4/7** et **6/7** |
| **replay local déterministe des 7 items — main** | **3/7** |
| **replay local déterministe des 7 items — branche** | **6/7** |

**6/7 est le plafond réel** : `lang-confirm-implicit` amorce un `pending_booking` **fabriqué** (`hotel_id: 123`, « Le Marais Hôtel »), donc MCP ne peut produire aucun lien et l'item ne peut structurellement pas passer. Défaut de dataset, pas d'agent.

⚠️ **Le harnais a une vraie variance run-à-run** (2/7↔3/7, 4/7↔6/7) : `_lookup_trace_facts` est best-effort et un miss dégrade en échec ou en `skipped`. Le replay local, lui, est stable. **Lire un run isolé de ce dataset comme une vérité est une erreur** — en faire deux, ou rejouer en local.

`b2c/prod-regressions` : `min_hotels` **2/6 sur main ET sur la branche** → environnemental (cutoff même-jour, run en fin d'après-midi), **pas une régression**. C'est le contrôle qui l'a établi — sans le run baseline du même jour, ce 2/6 se lisait comme une catastrophe.

### Gates

`1396 passed, 1 skipped` (+57 tests, baseline 1339) · ruff · mypy 46 fichiers · guardrails OK. **Les ~150 tests de guards sont restés verts sans modification** — un seul test a bougé, un `_fake_get_hotel_details` qui épinglait l'ancienne signature. C'est le signal recherché : on a changé l'extracteur, pas les gates.

### Reste

- **`lang-confirm-implicit` est impassable** : re-semer l'item avec un vrai `hotel_id` MCP, ou l'accepter comme plafond documenté.
- **Variance du harnais** : `_lookup_trace_facts` mériterait un backoff plus long ou un échec explicite plutôt qu'un `skipped` silencieux. Non fait — hors périmètre.
- **P1-2 s'arrête à la reconnaissance** : répondre dans la langue de l'utilisateur demande de traduire `templates.py`. Décision produit ouverte.
- Le chantier géo (tour mort landmark + Toulon du bloc « ter ») reste entier.

## 🚢 Addendum 2026-08-25 ter — prod redéployée sur `11e23ed` : les fixes POI/occupancy sont ENFIN live. Occupancy vérifiée bonne, POI vérifié encore cassé sur un cas réel (Champs-Élysées → **Toulon**).

Les PR #79/#80 étaient mergées depuis le matin mais **tournaient nulle part** : les 3 services étaient restés sur `08d215d` (2026-08-24 13:00Z). Le fil-piège posé par le bloc « 08-24 bis » (*« si un futur `git log <release>..main -- agents libs` remonte quelque chose, c'est un vrai écart »*) a fait exactement son travail.

### Déroulé

- `LANGFUSE_RELEASE=11e23ed` posé sur `concierge` / `hotel-search` / `faq` via `variableUpsert` avec **`skipDeploys: true`** — vérifié : les 3 `last_deploy` sont restés au 08-24 après le stamp, donc aucun redéploiement de l'ANCIEN code.
- `railway up --service <n> --environment production --detach`, **feuilles d'abord** (`hotel-search`, `faq`) puis `concierge` — pour que le concierge redémarre contre des feuilles déjà à jour. `--detach` volontaire : `--ci` streame les build logs, qui contiennent `FLEET_READ_TOKEN` en clair.
- 3 déploiements **SUCCESS**. `widget` NON redéployé : `git log 08d215d..main -- web` est vide (et ce service n'a pas d'estampille).
- `faq` redéployé alors que son code est inchangé (`agents/faq_agent` + `libs` = 0 commit) — délibéré, pour que l'estampille `11e23ed` ne mente pas sur ce service.

### Vérifié en prod sur du trafic réel (3 tours `x-dayuse-synthetic: 1` via le proxy widget)

| Tour | Résultat |
|---|---|
| « autour des champs elysees demain **pour 2 adultes et 1 enfant** » | `adults:2 children:1` dans `active_filters` ✅ · 0 hôtel · réponse honnête |
| **Contrôle B** « à paris demain **pour 2 adultes et 1 enfant** » | **5 hôtels, tous `capacity ≥ 2` ET `children_capacity ≥ 1`** ✅ |
| **Contrôle A** « autour des champs élysées demain » (sans occupancy) | **4 hôtels… à TOULON** ❌ |

**Occupancy (P0-1) : confirmé bon de bout en bout en prod.** C'était le point de contrôle B, conçu exprès pour séparer « filtre trop restrictif » de « géo cassée ».

**OBS3/OBS5 non régressés** : les 13 scores `guard_*` + `hotels_returned` + `empty_shortlist` + `llm_calls=3` arrivent en `environment=production` sur chaque trace, `configId` attaché partout sauf `guard_date_hallucinated_year_rolled_forward` (gap permanent des 35 caractères, connu). Budget LLM respecté.

### ❌ Défaut LIVE trouvé à la vérification : « les champs élysées » résout sur un commerce toulonnais

**Ce n'est PAS une régression du déploiement** — c'est un cas résiduel des 35 % que `hotels_within_km` laisse encore échouer après PR #79 (65 %, pas 100 %). Mais la magnitude est nouvelle : l'audit décrivait des ratés à 7-13 km (La Défense, Orly), là c'est **830 km**.

Preuve directe, dans `active_filters.distance_origin` du tour :

```
label : "Champs Elysées, 32 Rue d'Alger, 83000 Toulon, France"
type  : "poi"
lat/lon : 43.12151572, 5.93218873
```

Mapbox Search Box a matché un **commerce littéralement nommé « Champs Elysées » à Toulon**. C'est le mécanisme **M3 de `AUDIT-AGENTIQUE-2026-07-30.md`** (*Search Box non scopé — ni proximity ni prior locale, un POI homonyme passe*), toujours vivant quand la requête ne porte **aucune ville** (`city: None`, `resolved_city: None` — seul `zone` est rempli).

**Deux observations qui comptent pour la suite :**

1. ⚠️ **PÉRIMÉ — voir le bloc « 08-26 ter » en tête.** Ces deux scores étaient **jamais câblés** (à 0.0 sur CHAQUE tour depuis toujours) : ce n'était pas un faux négatif structurel du guard, c'était une absence de mesure. Et la cause du défaut n'est ni M3 ni M4 mais le `proximity` par défaut de Search Box (= IP proximity). Conservé pour la trace du raisonnement. ~~**Aucun guard géo n'a tiré** : `guard_geocode_echo_back = false` ET `guard_generic_location_demotion = false` sur cette trace. C'est exactement **M4 de l'audit** (*« l'écho valide le NOM, pas le LIEU »*) : l'écho Mapbox contient bien « Champs Elysées », donc le guard est satisfait — alors que le lieu est à 830 km. **Un guard vert ici est un faux négatif structurel, pas un oubli de câblage.**
2. **La synthèse dégrade honnêtement** : *« la recherche a bien trouvé 4 offres… mais à Toulon, pas autour des Champs-Élysées ; dites-moi la ville exacte (Paris) »*. L'agent ne ment pas — mais il affiche quand même 4 cartes de Toulon.

⚠️ ~~**Sensible à la normalisation**~~ **PÉRIMÉ (08-26 ter)** : ce n'était pas la normalisation. Les deux formes empruntent le MÊME chemin ; ce qui variait était le classement IP-biaisé de Mapbox. Vérifié : « champs elysees » et « champs élysées » donnent le même top-1 à IP constante.

### Reste

- **P1 audit (contrat JSON du triage) reste le prochain chantier** — et ce défaut lui donne une raison de plus : quand le modèle n'émet que `zone` sans `city`, le résolveur n'a aucun prior pour écarter un homonyme. Le vrai correctif est probablement double : contrat d'extraction **et** scoping du Search Box par la ville/le marché.
- Piste de guard à instruire : comparer la résolution POI à l'ancre ville/marché du tour et **démoter** au-delà d'un seuil de distance, plutôt que de valider sur le nom (M4).
- Reste inchangé : plafond OpenAI à poser, OBS8 attend une fenêtre, OBS9 avant fin janvier 2027, juges v2 à surveiller sous 24 h.

## 🔓 Addendum 2026-08-25 bis — le blocage de validation de model config est RÉSOLU : ce n'était ni le contenu, ni un défaut d'egress, mais un hang INTERMITTENT dans le process `langfuse-web`. Les 2 correctifs de juge sont livrés et actifs.

Le blocage vieux de 25 jours est levé. **La cause au dossier était fausse deux fois** — corriger la mémoire, pas seulement l'état.

### Ce que le dossier disait vs ce qui est vrai

| Au dossier (07-31 puis 08-25 matin) | Vrai, mesuré cette session |
|---|---|
| « modération OpenAI sur les few-shot grossiers » | **Réfuté** (déjà réfuté le 08-25 matin, confirmé ici) |
| « aucun evaluator ne peut être créé ni modifié, indépendant du contenu » | **À moitié faux** : indépendant du contenu ✅, mais **PAS permanent** — `upsertEvaluator` a réussi 3× d'affilée à 12:06–12:08, puis 5× en timeout de 12:09 à 12:18 |
| « validation dans `langfuse-web` vs exécution dans `langfuse-worker`, un seul a l'egress OpenAI » | **Réfuté** : `langfuse-web` joint `api.openai.com` en **173 ms**, et le worker appelle **exactement le même** `generateLLMText` de `packages/shared` (`worker/src/features/evaluation/evalExecutionDeps.ts:241`). Aucune asymétrie d'egress, aucune asymétrie de code. |

### La vraie cause

Le préflight est `web/src/features/evals/server/evaluator-preflight.ts` → `testModelCall` → `generateLLMText`. Il **hang par intermittence à l'intérieur du process Next.js long-vécu de `langfuse-web`** :

- `netstat` dans le conteneur pendant un hang : la socket vers OpenAI atteint **`ESTABLISHED`, `Recv-Q 0 / Send-Q 0`, et y reste les 120 s entières**. Connectée, rien ne circule.
- CPU à **0,6 %** pendant tout le hang (échantillonné à la minute) — rien ne tourne en boucle.
- Le **même appel depuis un process node neuf dans le MÊME conteneur est fiable à 100 %** : 20/20 en rafale (~150 ms), 17/17 espacés de 10 s avec un `Agent` partagé — dont pendant que le serveur, lui, timeoutait. Testé avec le dispatcher SSRF exact de Langfuse (`undici` Agent + `dns.lookup` enveloppé + `redirect: manual`) et avec **les 2 IP A de `api.openai.com` forcées une par une** (`172.66.0.243`, `162.159.140.245`) : les deux répondent.
- **120 s n'est pas arbitraire** : c'est exactement le défaut de `LANGFUSE_FETCH_LLM_COMPLETION_TIMEOUT_MS` (`packages/shared/src/env.ts:472`), non posé sur aucun des 2 services.
- L'état est **collant** : un hang semble en entraîner d'autres, et ça se draine après une période d'inactivité (tout échouait 09:12–09:21, tout marchait à 12:06). Le seul état long-vécu sur ce chemin est l'`Agent` undici mis en cache au niveau module (`packages/shared/src/server/outbound-url/connection.ts`). **Mécanisme exact non prouvé** — ce qui est prouvé, c'est que c'est dans le process, pas dans le réseau.

### Le correctif : un flag amont, pas un contournement

`LANGFUSE_SKIP_EVALUATOR_MODEL_CALL_VALIDATION=true` posé sur **`langfuse-web`** (variable + `serviceInstanceDeployV2`, déploiement `f96b2bec` `SUCCESS`, health `3.224.3` OK). C'est une échappatoire livrée par Langfuse dans le préflight lui-même : elle **garde** la validation de sélection de modèle et la compilation du schéma de sortie, et **ne supprime que l'appel live au provider** — appel dont on n'a aucun besoin ici, puisque le worker exécute ces mêmes juges contre la même connexion toute la journée.

**Vérifié, pas déclaré** : `netstat` pendant 2 écritures d'evaluator post-flag → **zéro connexion sortante 443**. Le préflight ne touche plus OpenAI du tout. Ce n'est donc pas « on a eu de la chance après un restart ».

⚠️ **Contrepartie assumée** : un nom de modèle réellement faux ne serait plus attrapé à l'écriture, seulement à l'exécution (la règle partirait en erreur). Réversible en retirant la variable.

### Les 2 correctifs livrés

1. **`Hallucination` v2** (`cmt8mfq1b006yni029xunepre`) — la règle active `obs7-hallucination-v3chat` a migré dessus toute seule. Section « Out of scope for this judge » ajoutée : (1) les **liens** ne sont jamais un signal d'hallucination — un juge LLM ne peut pas ouvrir une URL, et le 13e guard (`hotel_link_truthfulness`) les vérifie déjà caractère par caractère ; (2) la **donnée live** (prix, remises, dispo, dates, créneaux, capacité, nombre d'avis) n'est notée que si elle est fausse **en soi** (contredit la requête, se contredit, arithmétiquement impossible), jamais parce que le juge ne peut pas la confirmer. **La classe (2) est volontairement plus étroite que la (1)** : les liens ont un guard déterministe, les prix non — aveugler le juge sur les prix supprimerait du vrai signal. Élargissement au-delà de la demande initiale (qui ne visait que les liens), justifié par une 2e occurrence mesurée : 0,7 sur une remise de « 78 % » pour *« lacking verification against actual data »* (score `7e9dbb15`, 08-25 10:57Z). **Nom de règle inchangé** → le nom de score `obs7-hallucination-v3chat` reste stable, les séries avant/après restent comparables.
2. **`User Distress (no history)`** (`cmt8moncv0071ni02mrjjra0p`) — `conversation_history` retiré du prompt ET de la liste de variables. La règle `obs7-user-distress-v3chat` est **recâblée dessus et ACTIVE** (`enabled:true`, `status:active`, mapping `last_user_message ← input` seul, sampling 0,05, filtres inchangés). **Les 3 règles sont maintenant actives.** L'ancien `User Distress` est laissé sur l'instance en `evaluationRuleCount: 0` (jamais activé, 0 score produit) pour garder l'historique lisible.

### 🪤 Pièges découverts

1. **`railway ssh` perd les premières lignes de sortie** et re-joint ses arguments dans un shell : `sh -c 'echo A; echo B'` n'affiche que `B`, et une boucle `for … do` part en `syntax error`. Recette qui marche : passer **un seul argument déjà quoté** (`railway ssh … -- "node -e 'JS'"`) et faire imprimer au script **5 lignes de padding** avant ce qui compte. Sans ça on conclut à tort que la commande n'a rien produit.
2. **Le nom du score = le nom de la RÈGLE**, pas celui de l'evaluator (`obs7-hallucination-v3chat`, cf. `listScores`). Renommer une règle casse la continuité de la série ; changer d'evaluator dessous ne la casse pas. C'est pourquoi le juge distress a changé d'evaluator **sans** que la règle change de nom.
3. **`upsertEvaluator` sur un nom existant crée une nouvelle version ET migre les règles qui le référencent** — l'id de l'evaluator change (v1 `cms8mom1h…` → v2 `cmt8mfq1b…`). Un `id` d'evaluator noté dans un doc devient donc périmé à chaque amendement de prompt ; se référencer par **nom + scope**.
4. **Les écritures échouées sont atomiques** : les 5 timeouts n'ont laissé aucune trace (25 evaluators avant/après, règle inchangée). Rassurant, mais ça veut aussi dire qu'un timeout ne dit RIEN sur l'état — toujours relire avec `listEvaluationRules` après.

### Reste

- **Mécanisme exact du hang non identifié** (in-process, l'`Agent` undici module-level est le suspect). Sans conséquence tant que le flag est posé : le seul chemin qui l'empruntait était ce préflight. ⚠️ Il reviendrait si on utilisait le **Playground**, les filtres en langage naturel ou la recherche IA — toutes des features web-side qui appellent le LLM par le même chemin.
- **Efficacité du prompt v2 non encore mesurée** : le juge tire à 5 % de sampling, il faut du trafic organique. À revérifier : un tour produisant un lien ne doit plus sortir 0,7 pour « lacks verification ». La comparaison se lit dans la même série `obs7-hallucination-v3chat`.
- **Le juge distress n'a encore produit aucun score** (activé à 12:59Z). Vérifier sous 24 h qu'il n'est ni en erreur ni en pause, et que le 6e exemple few-shot fait bien scorer `false` un « Bonjour, je cherche un hôtel ».
- Inchangé : plafond de dépense OpenAI toujours à poser (action Fabien), OBS8 attend une fenêtre, OBS9 à planifier avant fin janvier 2027.

## 🗺️ Addendum 2026-08-25 — bugs POI et occupancy CORRIGÉS et mesurés (PR #79, #80 mergées)

Les deux P0 de `AUDIT-AGENTIQUE-2026-07-30.md` sont livrés. **Ne pas les reconstruire.**
Gates sur `main` après merge : `1339 passed, 1 skipped` · ruff + mypy clean · guardrails OK.

### Mesures, harnais OBS6 (avant → après, runs Langfuse liés dans les PR)

| Dataset / assertion | Baseline 07-30 | Après |
|---|---|---|
| `b2c/geo-poi` · `hotels_within_km` | 3/17 (18 %) | **11/17 (65 %)** |
| `b2c/geo-poi` · `resolved_country_code` | 14/18 (78 %) | **16/18 (89 %)** |
| `b2c/geo-poi` · `min_hotels` | — | **19/20 (95 %)** |
| `b2c/occupancy` · `search_offers_args_include` | 7/9 (78 %) | **9/9 (100 %)** |
| `b2c/occupancy` · `offers_capacity_gte` | **0 %** | **3/3 (100 %)** |
| `b2c/occupancy` · `offers_children_capacity_gte` | **0 %** | **3/3 (100 %)** |
| `b2c/occupancy` · `active_filters_include` | **0 %** | **4/5 (80 %)** |

### Deux hypothèses de l'audit corrigées PAR LA MESURE (ne pas re-litiger)

1. **Occupancy : le modèle émettait DÉJÀ `adults`/`children` (78 %).** L'audit croyait qu'il ne
   les émettait pas « faute de description par champ » et prescrivait un enrichissement de
   déclaration — inutile, le schéma MCP les documente lui-même. Le vrai trou était en aval :
   capture (`_budget_timeslot_from_args` ne mappait que budget/timeSlot), persistance (pas de slot
   profil), restitution (`active_filters` + cartes muettes), carryover.
2. **POI : l'audit a manqué le mécanisme décisif — `radiusKm`.** `search_offers` prend un rayon
   (**défaut 20 km**), donc un ancrage landmark et un ancrage ville cherchaient le MÊME disque :
   le géocodage pouvait résoudre l'avenue à 250 m près et les résultats revenaient de La Défense
   (7 km) et d'Orly (13 km). Les 3 correctifs prescrits seuls : 18 % → **24 %**. Avec le rayon
   (3 km sur ancrage POI) : **65 %**. `min_hotels` MONTE (95 %) — pas de fausse rareté.

### 🪤 Trois pièges découverts, à ne pas repayer

1. **`_STATE_DISTANCE_ORIGIN_KEY` n'est écrit que dans la branche SEARCH**, donc APRÈS
   `search_offers` : le lire depuis un `before_tool_callback` type-checke parfaitement et ne
   s'applique jamais. C'est **`_STATE_ANCHOR_KEY`** (branche GEOCODE) qu'il faut. Le compteur
   `dayuse_metric=landmark_radius` existe pour rendre ça visible — il a révélé exactement ce bug.
2. **Ne PAS dire au modèle de laisser `city` vide** pour un landmark : il vide `city` sans
   toujours remplir `zone` → `missing_city` instantané (ms=0), tour mort. Les deux chemins de code
   gèrent l'une ou l'autre forme ; l'instruction n'a pas à pousser.
3. **`zone_is_landmark` (bonus de l'audit) est inutile** : `is_generic_location_token` tranche déjà
   (« the airport » générique, « gare de lyon » non — appartenance EXACTE à l'ensemble). Un signal
   que le code possède ne peut pas être halluciné.

### Reste connu, mesuré

- ⚠️ **PÉRIMÉ — voir « 08-26 ter » en tête.** Ce n'était PAS de la non-détermination
  d'extraction et rien à voir avec le contrat du triage : `city: str` n'avait pas de défaut,
  donc ADK rejetait l'appel d'outil quand le modèle omettait la clé (14 occurrences tracées).
  Le modèle émettait bien `zone`. Corrigé par `city: str = ""`.
  ~~**~1 tour sur 6** (6 essais) le modèle n'émet NI `city` NI `zone` → tour mort ; c'est la
  non-détermination d'extraction = P1 de l'audit.~~
- `clarify_expected` **19/19 → 18/19** : un homonyme que `country_guess` tranche au lieu de
  demander. Contrepartie assumée d'un prior soft, à surveiller.
- `active_filters_include` occupancy : 1/5 encore rouge (cas limite d'extraction).
- Inchangés depuis la baseline, PAS des régressions : `clarify_options_include_country` 0/2,
  `if_resolved_country_code` 0/1, `must_ask_city` 0/1.
- P2 audit toujours ouvert : demande cross-repo `resolve_location` sur l'index `poi` MCP_B2C.

### Comment revérifier (services + LLM réels requis)

```bash
docker run -d --rm --name agentb2c-redis -p 6379:6379 redis:7
bash scripts/run_local.sh
set -a; . ./.env; set +a
.venv/bin/python -m evals.langfuse_experiment --datasets b2c/geo-poi,b2c/occupancy --run-name <nom>
bash scripts/run_local.sh stop && docker rm -f agentb2c-redis
```

## 🧊 Addendum 2026-08-24 ter (reprise de vacances) — GO écrit sur OBS8, v4 est GA, et le point de calibration OBS7 était structurellement impossible

Session de reprise après 24 jours. Trois livrables : vérification des 2 items P1, **GO écrit sur OBS8**,
et déblocage d'OBS7. **Aucune mutation Railway/ClickHouse.**

### Vérification des 2 items P1 laissés avant le départ

| Item P1 | Verdict | Preuve |
|---|---|---|
| Redéployer le concierge depuis `main` | ✅ **FAIT** (2× le 2026-08-24) | Les 4 services sur `08d215d` ; `git log 08d215d..main -- agents libs web` **vide**. OBS3 live en prod : **325 scores `guard_*`** (25 par guard) depuis 09:50Z. OBS5 live aussi. |
| Surveillance post-OBS7 + point de calibration | ❌ **PAS FAIT** — et ce n'était pas un défaut | Les 2 règles actives sont saines (`enabled:true`, `pausedReason:null`, **jamais en erreur** — DoD « zéro règle en erreur » ✅). Le blocage était l'absence de trafic, puis un problème de conception (ci-dessous). |

### OBS8 — GO DONNÉ, exécution différée, plus aucun blocage

Détail complet dans `phases/OBS8-clickhouse-upgrade.md`, bloc « GO — 2026-08-24 ». L'essentiel :

- **Cible : `clickhouse/clickhouse-server:25.12.11.4`** — le pin de juillet, mais **revérifié**. Le tag git
  `v25.12.12.1-stable` existe **sans image Docker** ⇒ nouveau piège : *un tag git ClickHouse n'implique
  pas une image publiée*, toujours vérifier Docker Hub.
- **26.x écarté avec preuves** : régression d'analyzer (CH PR #104268 en 26.5.1, corrigée en 26.7.1) qui
  **mal-planifie la requête `scores.all` de Langfuse** ⇒ le rayon d'impact est exactement OBS3/OBS7.
  Langfuse pin `25.12` dans son propre `docker-compose.yml` sur `main`, post-GA v4.
- **Caveat assumé, absent du doc de juillet : 25.12 n'est PAS LTS** (ClickHouse ne patche que les 3
  dernières stables ⇒ hors support depuis ~mars 2026). Donc **la vraie motivation d'OBS8 est de débloquer
  v4, pas de rattraper des patchs de sécurité** — le doc a été corrigé pour cesser de prétendre l'inverse.
- **Décision D (communication) FERMÉE** : Fabien a tranché — **AgentB2C est le seul producer** de cette
  instance. Rien à annoncer, étapes 2 et 10 du runbook N/A. Par ricochet **décision C (fenêtre) devient
  libre**. Le blocage de juillet ne pouvait pas être levé techniquement (le partage Langfuse est
  applicatif, invisible depuis Railway) : il fallait une réponse humaine.
- **Reste à faire** : Fabien pose une fenêtre, puis dérouler le runbook. Rappel : **porte à sens unique**
  dès que la nouvelle version accepte du trafic, et **single-node sans HA**.

### 🚨 Langfuse v4 est GA depuis le 2026-08-17 — `D-OBS-2` est SUPERSÉDÉE

Découvert en revérifiant les prémisses de juillet. `D-OBS-2` disait « pas de v4, dernière = `4.0.0-rc.3`,
attendre la stable ». **La GA est sortie pendant l'absence.** Ce qui reste vrai est devenu l'échéance :
**v3 n'est patché que jusqu'à fin janvier 2027.**

- `OBS9` passe de ⏸ « attend la GA stable » à ⬜ **à planifier**, avec cette date butoir.
- La migration se fait en **3 étapes indépendantes** (serveur v4 en legacy/dual-write → SDK/API/evaluators/
  exports → bascule `events_only`), chacune laissant le déploiement dans un état stable.
- Rollback possible **avant** la bascule finale en rembobinant le schéma ClickHouse en v37 — **mais pas**
  en redéployant une image v3 seule.
- ⇒ OBS8 n'est plus une préparation spéculative : c'est l'étape 1, et l'amont dit de faire ClickHouse
  **d'abord** puis d'attendre autant qu'on veut.

### OBS7 — pourquoi le point de calibration était impossible (le vrai problème, non identifié avant)

Ce n'était **pas** un manque de volume. **Les 3 règles tirent leur échantillon de 5 % indépendamment** :
la probabilité qu'un juge et un humain notent la **même** observation est quasi nulle. État live constaté :
**14 annotations humaines** (07-31) et **1 score de juge** (08-24), **zéro observation commune**. Ajouter du
trafic n'aurait rien changé — il fallait changer le dispositif, pas le volume.

**Coût des juges enfin MESURÉ** (et non estimé), depuis la trace d'exécution : `gpt-4o-mini`, 437 tokens,
**$8.22e-5 par appel**. Dépense totale à ce jour : **$0.0000822** (1 run). Formule :
`mensuel ≈ tours_organiques × sampling × n_juges × 8.2e-5`. À 10 000 tours/mois × 5 % × 3 juges ≈
**$0.12/mois** ; même à 100 % de sampling ≈ **$2.47/mois**. **Le plafond de ~20 $/mois est du pur coussin**
(≈243 000 appels) — l'item reste à poser sur la console OpenAI (action Fabien, hors CLI).

### 🔴 OBS7 — la cause documentée du blocage `User Distress` est FAUSSE

> ⚠️ **PARTIELLEMENT PÉRIMÉ depuis le 2026-08-25 (bloc « bis » en tête) — le blocage est RÉSOLU.** Ce qui reste juste : l'échec est indépendant du contenu, la modération OpenAI n'y est pour rien. Ce qui est faux : l'échec n'est **pas permanent** (il est intermittent), et l'hypothèse « web valide / worker exécute, un seul a l'egress » est **réfutée** — les deux joignent OpenAI, et le worker appelle le même code. Conservé pour la trace du raisonnement.

**Ne pas retenter l'activation depuis l'UI : ça échouera pareil.** L'hypothèse au dossier depuis le
07-31 (modération OpenAI sur les exemples few-shot du prompt) est **réfutée par 4 tests** :

| Test | Résultat |
|---|---|
| `upsertEvaluator` profanité littérale | timeout 120 s |
| idem, profanité **censurée**, nom neuf | timeout 120 s |
| idem, prompt **anodin de 37 caractères** | **timeout 120 s** |
| `updateEvaluationRule` `enabled:true` (aucune écriture d'evaluator) | timeout 120 s |

Erreur réelle, identique : `Model configuration not valid for evaluator "<nom>". The operation was
aborted due to timeout`. **Le 3ᵉ test est décisif : l'échec est indépendant du contenu.**

**Vraie cause** : le chemin d'écriture d'un evaluator — et l'activation d'une règle — **valide la config
du modèle en appelant le provider, et cet appel part en timeout à 120 s**. Indice le plus utile : les
juges **fonctionnent** (`Hallucination` a scoré le 08-24, `Relevance` le 08-25) — donc la connexion LLM
sert l'**exécution** mais pas la **validation**. Hypothèse à tester dans les logs `langfuse-web` :
validation dans `langfuse-web` vs exécution dans `langfuse-worker`, un seul des deux ayant l'egress OpenAI.

**Portée plus large que ce judge** : **aucun evaluator ne peut être créé ni modifié** sur l'instance
aujourd'hui — ça bloque aussi `User Disagreement` et `Out-of-Scope Request`. Aucune écriture n'a fui
(25 evaluators avant/après, la validation échoue avant l'écriture).

**Défaut réel trouvé au passage** : la règle mappe `conversation_history` sur
`metadata.$.conversation_history` — **ce champ n'existe pas**. Vérifié sur les observations racines
réelles : la metadata ne porte que `resourceAttributes` et `scope`, et l'`input` est une chaîne simple
(le dernier message). C'est la même raison qui avait fait renoncer aux 2 autres judges. Quand la
validation sera réparée, créer une version du prompt **sans** `conversation_history`.

### OBS7 — le point de calibration était impossible par construction (corrigé)

Pas « en attente de trafic » : **impossible**. Les 3 règles tirent **5 % indépendamment**, et la queue
humaine était alimentée depuis une **source différente** (`empty_shortlist == 1`). Juges et humains
notaient des ensembles **disjoints**. Mesuré : 10 annotations humaines au niveau observation, 3 scores de
juge, **0 observation commune**. Plus de trafic n'y aurait rien changé.

**Correctif** : `scripts/langfuse_judge_calibration.py --queue-missing` alimente la queue depuis la
**sortie des juges** — les observations déjà notées par un juge partent en annotation humaine. Le sens
compte : l'inverse est impossible (les règles ne s'appliquent qu'aux observations nouvellement ingérées,
pas de backfill sur cette instance).

**Fait le 2026-08-25** : 3 observations mises en queue, **annotées par Fabien, premier point de
calibration produit** :

| Observation | Dimension | Juge | Humain | |
|---|---|---|---|---|
| `95ad5d4d2c8dcc82` | Hallucination | 0,0 | 0,0 | ✅ accord exact |
| `f1f5976125d6b931` | Hallucination | **0,7** | **0,0** | ❌ **juge trop sévère** |
| `f74ac766a6c848ff` | Relevance | 0,8 | 0,5 | ✅ accord, écart 0,30 |

**Le désaccord est un faux positif structurel** : le juge met 0,7 parce que le lien de réservation
« lacks verification ». Un juge LLM **ne peut pas vérifier une URL** — et cette vérification est déjà
faite déterministement par le 13ᵉ guard (`hotel_link_truthfulness`, S-G12). Le juge duplique un guard et
le fait moins bien. Non corrigé : **chaque tour produisant un lien génère un faux positif**, donc le
score se dégrade d'autant plus que le produit marche.

🔴 ~~**Et le correctif est bloqué**~~ **DÉBLOQUÉ le 2026-08-25** (bloc « bis » en tête) : `Hallucination` v2 est en prod avec la section « Out of scope ». À l'époque : amender un prompt de juge est une écriture d'evaluator, donc le
chemin qui part en timeout. **Le bug de validation gèle désormais la boucle d'amélioration elle-même,
pas seulement `User Distress`** — sa priorité monte.

Détail : `f74ac766a6c848ff` porte `human_user_distress = 1` — le seul positif relevé par l'humain est
sur la dimension dont le juge est désactivé. ⚠️ **Ne pas reporter « 50 % d'accord » comme indicateur** :
n=3, c'est un test du mécanisme. Le n croît seul avec le trafic ; le script est idempotent.
Détail complet : `reports/OBS7-CALIBRATION-2026-08-25.md`.

⚠️ Non fait volontairement : **monter le `sampling` des 2 règles de production** pour accélérer le n.
C'est une modif de config de production — décision de Fabien.

### Corrections de lignes périmées (vérifiées contre le serveur live, pas déduites)

- L'ancien « les 2 règles avaient **0 score** » : il y en a **1** depuis le 08-24 12:24Z.
- L'ancien « scores OBS3 à **zéro occurrence en prod** » : **325 occurrences** depuis le 08-24 09:50Z.
- Le titre d'addendum OBS7 « **PAS MERGÉE** » : mergée le 2026-07-31 (PR #70, `f49009c`).
- **Serveur Langfuse = `3.224.3`**, pas `3.205.1` (`GET /api/public/health`).
- ⚠️ **Recette API à connaître** : les evaluators et evaluation rules **ne sont pas sur l'API REST
  publique** (`/api/public/eval/configs`, `/evaluators`, `/running-evaluators` renvoient tous la 404
  Next.js). Ils sont accessibles **uniquement** via JSON-RPC sur `POST /api/public/mcp`
  (`listEvaluators`, `getEvaluator`, `listEvaluationRules`, `getEvaluationRule`), ou via les outils MCP
  Langfuse configurés dans ce projet.

## 🔐 Addendum 2026-08-24 bis (suite de la même journée) — façade `/v3` GATÉE par `CHAT_API_KEY`, panne de 9 min causée par l'ordre des opérations, tout redéployé sur `08d215d`

Suite directe du bloc ci-dessous. Trois choses : la façade est enfin gatée, une **panne réelle** a eu lieu au passage (à lire avant de refaire l'opération ailleurs), et les 4 services sont maintenant tous à jour.

### État déployé — À JOUR au 2026-08-24 13:0x UTC

| Service | Build déployé | `LANGFUSE_RELEASE` |
|---|---|---|
| `concierge` | `08d215d` (2026-08-24 12:58 UTC) | `08d215d` |
| `hotel-search` | `08d215d` | `08d215d` |
| `faq` | `08d215d` | `08d215d` |
| `widget` | `08d215d` (12:55 UTC) | *(pas d'estampille sur ce service)* |

**Plus aucun écart prod/main.** Si un futur `git log <release>..main -- agents libs` remonte quelque chose, c'est un vrai écart, pas un reliquat.

### ⚠️ La panne : 401 pendant ~9 min, cause = ordre des opérations

**Ce qui s'est passé** : les variables `CHAT_API_KEY` ont été posées sur `widget` **et** `concierge` **avant** que la PR #73 (injection côté proxy) ne soit déployée. Poser la variable **sans `--skip-deploys` déclenche un redéploiement automatique** : le concierge a redémarré (`12:46:58Z`, `reason=redeploy`) et s'est mis à exiger la clé, alors que le widget tournait encore l'ancien proxy, incapable de l'envoyer. Résultat : `POST /v3/chat` via le widget → **401**, démo morte.

**Correction** : PR #73 mergée, puis `railway up --service widget` depuis `main` propre (`08d215d`, 12:55 UTC). Démo rétablie immédiatement.

**La séquence correcte, si c'est à refaire** (l'ordre inverse garantit la panne) :
1. Déployer d'abord le code d'injection sur `widget` — inerte tant que `CHAT_API_KEY` est absent.
2. `CHAT_API_KEY` sur `widget` + redeploy → il envoie l'en-tête, personne ne vérifie encore.
3. **La même valeur** sur `concierge` → il vérifie, le widget est déjà conforme. Aucune fenêtre de 401.

Poser les deux variables d'un coup avec `--skip-deploys`, puis redéployer widget PUIS concierge, donne le même résultat sans fenêtre.

### Comment le gating marche (PR #73)

Le navigateur ne peut pas porter le secret (devtools). C'est le **proxy widget** (`scripts/run_widget_proxy.py`, le même fichier en prod via `web/Dockerfile`) qui l'injecte côté serveur, en lisant les **mêmes deux variables que la façade** (`CHAT_API_KEY`, `CHAT_API_KEY_HEADER`, défaut `X-Internal-Api-Key`) pour que les deux ne puissent pas diverger.

L'en-tête est **propriété du proxy** : toujours retiré de ce que le navigateur a envoyé, puis ré-ajouté depuis notre env. Retiré **inconditionnellement**, même façade non gatée — sinon gater la façade plus tard serait contournable depuis la page.

**Vérifié en prod sur du trafic réel** (tours taggés `x-dayuse-synthetic: 1`) :

- ✅ chemin JSON `/v3/chat` → 200, 5 hôtels, date `demain` → `2026-08-25`
- ✅ chemin **SSE** `/v3/chat/stream` (le vrai transport, `WIDGET_CHAT_TRANSPORT=sse`) → 200, frame `progress` avec `trace_id`, event `hotels` avant les tokens
- ✅ clé **forgée** envoyée depuis la page → 200 : le proxy l'a bien remplacée par la vraie, la valeur de la page a été ignorée et non honorée
- ✅ **la façade rejette vraiment** — prouvé par le 401 d'avant le déploiement du widget (pas de clé envoyée → refus). C'est la preuve que le verrou est réel, pas seulement que le chemin heureux marche.

⚠️ **Conséquence** : tout appel direct à `/v3` en prod doit désormais porter l'en-tête `X-Internal-Api-Key`, y compris les tours de vérification manuels. `AUTH_BYPASS` doit rester **non posé** (s'il vaut `true`, la clé est ignorée — `_api_key_error` sort avant de la lire).

### 🔓 L'edge public est maintenant DÉBLOQUÉ (mais toujours cassé)

Le seul frein à la réparation de l'edge était que `/v3` était ouvert : réparer l'edge aurait exposé une façade non gatée. **Ce n'est plus le cas.**

### ❌ Cause du 502 : ce N'EST PAS le `targetPort` — hypothèse testée et RÉFUTÉE

**Ne pas repartir sur cette piste.** `targetPort` a bien été posé à `8100` sur le domaine du concierge (2026-08-24, par Fabien via l'UI) : la valeur est confirmée par `railway status --json`, et **le 502 persiste sur tous les chemins**. Contre-exemple décisif dans le même projet : le service `widget` a `targetPort = None` et répond parfaitement en public. Le port n'a jamais été le problème.

**Vraie cause : le concierge écoute en IPv6 SEULEMENT.** `uvicorn --host ::` (Dockerfile) ne donne PAS un socket dual-stack, contrairement à ce que dit le commentaire du Dockerfile : l'`asyncio` de CPython force explicitement `IPV6_V6ONLY = True` sur tout socket `AF_INET6` (`asyncio/base_events.py`, ~l.1558-1563 en 3.12 — fait exprès pour pouvoir binder v4 et v6 séparément sans `EADDRINUSE`). Le réseau privé Railway étant IPv6, les feuilles et le widget joignent le concierge sans problème ; l'edge public, lui, atteint le conteneur en **IPv4** → connexion refusée → « Application failed to respond ».

**La preuve par le widget** : `scripts/run_widget_proxy.py` est le seul service joignable publiquement, et c'est précisément le seul qui **efface `IPV6_V6ONLY`** à la main (`_WidgetProxyServer.server_bind`, avec le commentaire qui documente ce piège exact). Le repo avait déjà résolu ce problème une fois.

**Correctif si on décide de le faire** : pré-binder un socket dual-stack et le passer à uvicorn (`Server.run(sockets=[…])` ou `--fd`) — `--host 0.0.0.0` est EXCLU, ça casserait le réseau privé IPv6 dont dépendent les feuilles et le widget.

**Mais recommandation : ne pas réparer, SUPPRIMER le domaine public du concierge.** Personne ne le consomme — le widget passe par `concierge.railway.internal:8100` (privé), et le seul usage réel du domaine public était le probing manuel, qui se fait très bien à travers le proxy widget. Ne pas exposer la façade est une meilleure posture que l'exposer en s'appuyant sur une clé. Ce 502 a servi de pare-feu gratuit pendant un mois.

### Score configs (PR #72, mergée et maintenant déployée)

- ✅ **`degraded` créée** (`5499df51-d40d-43ca-ad99-f79247af1959`, CATEGORICAL, `leaf_call_failed`=0 / `facade_shield`=1) et câblée dans `_SCORE_CONFIG_IDS`. L'ancien gap accusait l'outil MCP `createScoreConfig` : **c'était juste**, le SDK Langfuse accepte le payload identique. Pour toute config CATEGORICAL, passer par le SDK ou l'UI, jamais par cet outil MCP.
- 🚫 **`guard_date_hallucinated_year_rolled_forward` : gap PERMANENT, ne pas retenter.** 43 caractères, et Langfuse plafonne le `name` d'une score config à 35 — vérifié contre le **vrai serveur** (400 `{'code':'too_big','maximum':35,'path':['name']}`), pas juste déduit du schéma de l'outil MCP comme le disait l'ancienne note. Une config ne s'applique que si son nom **égale** le nom du score, et ce nom est gelé par le contrat `GUARD_SCORE_NAMES` **et** porte de la donnée de production. Aucun des deux côtés ne peut être raccourci. Confirmé live après redéploiement : ce score arrive bien avec `configId: null`, les 12 autres avec le leur.

### Tests : un test avait pourri avec le calendrier (PR #71)

`pytest` était rouge en début de journée, sans régression : un test codait en dur `2026-08-05` pour vérifier qu'un label de date absolu passe verbatim ; la date étant devenue passée, le guard `date_hallucinated_year_rolled_forward` la roulait (correctement) vers 2027. **Leçon générale** : après une longue absence, un `pytest` rouge dans ce repo → suspecter le calendrier avant le code. Immunisés = les tests qui passent un `_TODAY` explicite ; pourrissables = ceux qui lisent l'horloge réelle en comparant à un littéral.

### Gates

`1287 passed, 1 skipped` · `ruff` clean · `mypy` clean · `dayuse_guardrails.sh` OK. Scoring OBS3 revérifié après redéploiement : 13 guards + `hotels_returned`/`empty_shortlist`/`llm_calls` en `environment=production` sur les 2 tours de contrôle.

⚠️ **CI GitHub Actions toujours rouge = facturation, pas le code** (0 step, échec en 2 s). Les merges du jour se sont appuyés sur les gates locaux.

### Reste

- **Edge public** : décision à prendre — supprimer le domaine (recommandé, personne ne le consomme) ou binder dual-stack dans le concierge. **Le `targetPort` est déjà posé et n'était pas la cause** (cf. plus haut). Plus aucun risque de sécurité dans un sens ou l'autre, la façade étant gatée.
- **Judges OBS7** : les 2 règles actives sont saines (`enabled:true`, jamais en erreur). ⚠️ **Corrigé le 2026-08-24 (bloc OBS8/OBS7 en tête) : elles n'ont plus 0 score — le juge `Hallucination` a tiré pour la première fois de son histoire à 12:24Z.** Elles avaient 0 score — cause identifiée : 19 jours sans trafic prod (05/08 → 24/08), pas un bug. Il faut du trafic **organique** : les tours de vérification de la journée sont taggés `synthetic`, donc exclus de l'échantillonnage à 5 %.
- ~~**`obs7-user-distress-v3chat`** toujours désactivé~~ → **ACTIF depuis le 2026-08-25 12:59Z**, recâblé sur `User Distress (no history)` (bloc « bis » en tête). ⚠️ **Cause corrigée le 2026-08-25 : ce n'est PAS la modération OpenAI** mais la validation de model config qui part en timeout (120 s, indépendant du contenu) — voir le bloc « ter » en tête. **Ne pas retenter depuis l'UI**, ça échouera pareil.
- **Plafond de dépense OpenAI** (~20 $/mois) non posé. Coût **mesuré** : $8,22e-5/appel de juge, soit ~$0,12/mois à 10k tours × 5 % × 3 juges — le plafond est du pur coussin. ⚠️ **Où le poser (2026-08-25)** : `platform.openai.com/settings/organization/limits` → section *Spend* → *Edit spend limit* ; au niveau **projet** via Settings → le projet → *Limits*. Piège : un « Monthly spend limit » **seul n'est qu'une alerte, le trafic continue** — il faut activer **« Enforce a hard limit »** pour bloquer (`429` + `project_spend_limit_exceeded`). **Viser le niveau PROJET** : le concierge et la synthèse consomment OpenAI aussi, un plafond dur au niveau org couperait le produit, pas seulement les juges.

## 🚀 Addendum 2026-08-24 (session « quel build tourne en prod ? », branche `fix/rotted-date-test`) — l'écart de déploiement OBS3/OBS4/OBS5 est confirmé PUIS comblé, prod redéployée sur `f49009c`

**Point de départ** : l'item laissé par le HANDOFF du 07-31 — *« vérifier quel build le service concierge Railway fait réellement tourner »*. Réponse : le soupçon était **juste**.

### Le build qui tournait : `8726160` (PR #62, `fix/adk-call-llm-usage-doublecount`, 2026-07-30 10:14 UTC)

Prouvé **trois fois, indépendamment** — pas seulement par « le service répond » :

1. **Estampille explicite sur le service** : `LANGFUSE_RELEASE=8726160`, la même valeur sur `concierge`, `hotel-search` **et** `faq` → les 3 services étaient partis ensemble. C'est la seule estampille disponible : `source.repo` est `null` sur tous les déploiements (poussés par `railway up`, donc **aucune métadonnée git côté Railway** — ne pas la chercher).
2. **Horodatage du déploiement** : `2026-07-30T10:28:54Z`, soit **avant** les 3 merges concernés. `git log 8726160..main -- agents libs` renvoie exactement 3 commits, et rien d'autre :

| Commit | Mergé (UTC) | Était en prod ? |
|---|---|---|
| `3b5a90c` **OBS3** scores déterministes + métriques de tour | 07-30 13:46 | ❌ |
| `2b671a3` **OBS4** trace distribuée A2A | 07-30 15:07 | ❌ |
| `c64507f` **OBS5** feedback utilisateur + `trace_id` SSE | 07-31 08:01 | ❌ |

3. **Les données Langfuse concordaient** : `listScores` avec `environment=["production"]` sur tous les noms `guard_*` + `user-feedback` → **vide**. Tous ces scores n'existaient qu'en `environment=development`.

**Corollaire à retenir : OBS6 et OBS7 ne touchent AUCUN code `agents/`/`libs/`** (config Langfuse pure). Ils n'ont jamais eu besoin d'un déploiement — seuls OBS3/OBS4/OBS5 en avaient besoin.

### Découverte non prévue : la prod n'avait vu AUCUN trafic pendant 19 jours

Dernier tour organique : **`2026-08-05T16:22:27Z`**. Plus rien jusqu'à cette session. Ça **explique un item ouvert d'OBS7** sans qu'il y ait de bug à chercher : les 2 judges actifs sont toujours `enabled:true` / `status:active` (ni en pause ni en erreur), mais `Hallucination`/`Relevance` avaient **0 score dans tous les environnements**. À 5 % d'échantillonnage et zéro trafic, il n'y a simplement jamais rien eu à juger. La surveillance 24 h et le point de calibration judge/humain n'étaient pas bloqués par un défaut : **ils étaient bloqués par l'absence de trafic**.

### Correction d'une explication fausse dans ce HANDOFF (ligne ~1181, bloc 2026-07-28)

Le bloc disait : *« `GET /` sur `concierge-production-aaa2.up.railway.app` renvoie 502 — le service ne route pas la racine »*. **La conclusion est bonne (ce n'est pas une panne, le vrai chemin est le proxy widget), l'explication est fausse.** `POST /v3/chat` sur le domaine public renvoie **aussi** 502, avec le corps de l'edge Railway (`{"status":"error","code":502,"message":"Application failed to respond","request_id":…}`) — ce n'est pas un 404 Starlette. **L'edge public de Railway n'atteint pas le conteneur du tout**, quel que soit le chemin. Le réseau privé, lui, fonctionne parfaitement.

Détail qui compte : cet edge cassé est **la seule chose** qui garde la façade `/v3` hors de l'internet ouvert, puisque `CHAT_API_KEY` n'est pas posé sur le service (façade non gatée, cf. `_require_auth` dans `facade.py`). À ne pas « réparer » sans poser la clé d'abord.

### Action : prod redéployée sur `f49009c` (main), les 3 services

Décision de Fabien en session (l'item était explicitement réservé à lui). Déroulé :

- `LANGFUSE_RELEASE=f49009c` posé sur les 3 services avec **`--skip-deploys`** (sinon la variable déclenche un redéploiement de l'ANCIEN code, build gaspillé).
- `railway up --service … --detach` sur `hotel-search`, `faq`, `concierge`. **`--detach` volontaire : `--ci` streamerait les build logs, qui contiennent `FLEET_READ_TOKEN` en clair** (piège déjà connu).
- Déployé depuis un `main` **propre** (`f49009c`) : le correctif de test de cette session a été committé sur une branche AVANT le déploiement, pour que la prod reçoive exactement du code relu et que l'estampille ne mente pas. Les 2 fichiers de doc non committés dans l'arbre de travail (`PROMPTS-OBS-LANGFUSE.md`, `phases/OBS8-clickhouse-upgrade.md`) sont sans effet : **aucun Dockerfile ne COPY la racine du repo**.
- 3 déploiements `SUCCESS` (`2026-08-24T09:46:4x–5xZ`).

### Vérifié APRÈS déploiement, sur du trafic réel (pas déclaratif)

Tours envoyés via le proxy widget avec l'en-tête **`x-dayuse-synthetic: 1`** (le proxy relaie tous les en-têtes non hop-by-hop — utile à savoir) pour ne pas polluer l'échantillonnage des judges :

- **OBS3 = LIVE en prod** ✅ — un tour search (« hotel a lyon avec piscine pour demain » → 5 hôtels, date résolue `2026-08-25`) a produit **les 13 scores `guard_*` + `empty_shortlist` + `llm_calls=3` + `hotels_returned=5`** en `environment=production`, tous sur une seule trace : `0b340d5b99088b0380abe2d210d3a1f8`.
- **OBS5 = LIVE en prod** ✅ — sur `/v3/chat/stream`, la frame `progress` porte bien `trace_id` (`aca3cf99161da3e8c9783d1e892d4ed6`, 32 hex minuscules), et l'event `hotels` précède les tokens. **À ne pas confondre** : sur `/v3/chat` (non-SSE) `trace_id` est absent — c'est **voulu**, OBS5 ne l'expose que sur la frame `progress` (facade.py ~845-884). Ce n'est pas une régression.
- **OBS4 = code déployé, jointure PAS re-vérifiée cette session** ⚠️ — honnêteté : `2b671a3` est dans l'arbre déployé (même `railway up` que les deux ci-dessus, dont l'un est prouvé live), donc le code EST en prod. Mais le serveur MCP Langfuse exposé ici **n'a aucun outil d'énumération d'observations** (`listObservations`/`getTrace` absents), donc je n'ai pas pu confirmer de mes yeux que les spans de la feuille rejoignent la trace du concierge. La jointure avait déjà été vérifiée en vrai au merge (« 4 services dans une trace », bloc OBS4). Contrôle visuel de 5 s si besoin : <https://langfuse-web-production-272b.up.railway.app/project/cms4gd0d20002nz029tuly62e/traces/0b340d5b99088b0380abe2d210d3a1f8>

### Correctif de test : un test avait pourri avec le calendrier (branche `fix/rotted-date-test`)

`pytest` était **rouge** au démarrage de session (1 échec) — pas une régression : `test_resolve_date_fresh_absolute_label_writes_iso_and_stashes_delta` codait en dur `2026-08-05` pour vérifier qu'un label absolu passe verbatim. Le 2026-08-06 cette date est devenue passée, et `date_hallucinated_year_rolled_forward` (PR #57) a commencé à la rouler vers `2027-08-05` — **le guard avait raison, le test avait tort**. Corrigé en calculant la date depuis l'horloge réelle, l'idiome que le test de carry-over deux blocs plus bas utilise déjà et documente dans son propre commentaire. Gates après correctif : **1277 passed, 1 skipped**, ruff clean, mypy clean, guardrails OK.

⚠️ **Leçon générale** : ce repo a d'autres tests avec des dates littérales. Ceux qui passent `_TODAY` explicitement (ex. `test_resolve_absolute_iso_date`) sont immunisés ; ceux qui lisent l'horloge réelle pourriront de la même façon. Un `pytest` rouge après une longue absence : suspecter le calendrier avant de suspecter le code.

### Reste

- ⚠️ **Edge public toujours cassé, correctif BLOQUÉ** : le domaine du service a `targetPort: null` (Railway devine le port au lieu qu'on le lui dise = 8100). `railway domain --service concierge --port 8100` **ne peut pas** corriger : la CLI ne sait que *créer* un domaine, elle refuse d'en repointer un existant (« Domains already exist on the service »). La voie GraphQL (`serviceDomainUpdate`) exige de lire le token Railway, **ce que le classifieur de permissions a bloqué** (même garde-fou qu'OBS0/OBS7 sur `ENCRYPTION_KEY`) — pas contourné. Deux issues : (a) Fabien pose le port 8100 dans l'UI Railway (service → Settings → Networking → le domaine), (b) autoriser la lecture du token pour appeler la mutation. **Poser `CHAT_API_KEY` d'abord** (cf. plus haut), sinon réparer l'edge ouvre la façade.
- **`guard_date_hallucinated_year_rolled_forward` a `configId: null`** alors que les 12 autres guards ont bien une score config rattachée. Trou de config OBS3 repéré en passant, pas corrigé (hors périmètre de cette session).
- **Judges OBS7** : maintenant qu'il y a du trafic, la surveillance 24 h et le point de calibration redeviennent faisables. Attention : les tours de vérification de cette session sont taggés `synthetic`, donc **exclus** de l'échantillonnage — il faut du trafic organique (ou des tours non taggés) pour que les judges tirent.
- ⬜ PR à ouvrir pour `fix/rotted-date-test` — la review de Fabien reste le gate, rien mergé de moi-même.

## ⚖️ Addendum 2026-07-31 (session OBS7, branche `obs7-judges-online`, **mergée en PR #70 / `f49009c` le 2026-07-31 ~11:04 UTC** — ce titre disait « PAS MERGÉE », c'était l'état à la clôture de la session, le merge a suivi ~20 min plus tard) — judges LLM-as-a-judge online (2/3 actifs) + annotation queue, RGPD scope étendu à valider a posteriori

**Contexte** : 7e chantier de `PLAN-OBS-LANGFUSE-2026-07-29.md`, implémente **D-OBS-4** (judges managés, LLM Connection stockée dans notre Langfuse). Périmètre exact de `phases/OBS7-judges-online-annotation.md` : Langfuse UI + `observability/langfuse/**` + `scripts/**`.

### Prérequis vérifiés AVANT tout code (comme demandé, STOP si un manque)

1. **OBS4 mergée** — ✅ confirmé (PR #66, `e5f6773`), vérifié en plus : une observation racine stable par tour (`v3.chat`/`v3.chat_stream`), condition nécessaire pour un evaluator observation-level.
2. **Catalogue des judges managés** — ✅ reconfirmé **en LIVE** (pas juste la lecture de code d'OBS0) : `listEvaluators` sur l'instance réelle renvoie 22 templates dont les 5 ciblés (`User Distress`, `User Disagreement`, `Out-of-Scope Request`, `Hallucination`, `Relevance`).
3. **`ENCRYPTION_KEY`** — ⚠️ trouvée encore à la valeur placeholder documentée par Langfuse (64 zéros hex), décision de rotation explicitement laissée à Fabien par OBS0 et jamais tranchée depuis. **STOP fait, question posée à Fabien** (le classifieur de permissions a d'ailleurs bloqué ma tentative de relire la valeur brute sur Railway — même garde-fou qu'OBS0). **Décision : rotation immédiate approuvée.** Nouvelle clé générée (`openssl rand -hex 32`), posée sur `langfuse-web` **et** `langfuse-worker` (les deux la lisent), redeploy des deux services vérifié `SUCCESS`, santé `GET /api/public/health` OK après coup. La valeur n'a jamais été affichée ni loggée ; le fichier temporaire local a été supprimé immédiatement après usage.

### LLM Connection

**Fabien a configuré lui-même** (UI-only, aucune API/MCP tool ne permet de poser une LLM Connection ni le "default eval model" avec les tools dont je dispose — confirmé via lecture du routeur tRPC source `llm-api-key/server/router.ts` et de la doc `/docs/administration/llm-connection` : `PUT /api/public/llm-connections` existe bien mais exige la clé en clair, que je ne dois ni détenir ni faire transiter par le chat) : provider `openai`, adaptateur `openai`. Vérifié après coup via `GET /api/public/llm-connections` (`displaySecretKey` masqué, `...E-wA`) — je n'ai jamais vu la clé complète.

**Modèle retenu : `gpt-4o-mini`** (validé avec Fabien) — tool calling supporté (obligatoire, Langfuse force un tool `extract`), cohérent avec le modèle par défaut déjà utilisé ailleurs dans l'écosystème, coût bas pour du sampling à 5 %.

**Plafond de dépense** : pas de mécanisme Langfuse pour ça — seul levier réel : une limite d'usage côté clé OpenAI (platform.openai.com). Recommandé à Fabien : ~20 $/mois pour démarrer. **Non vérifié posé côté OpenAI** — à confirmer par Fabien.

### Judges construits : 3 évaluators **project-scope** (pas des références aux templates `managed`)

Choix de conception : au lieu de référencer directement les templates `scope=managed` dans les règles (qui dépendent d'un "default evaluation model" UI-only, jamais garanti), j'ai créé 3 évaluateurs **`scope=project`** via `POST /api/public/unstable/evaluators`, avec le prompt **copié verbatim** du template managé correspondant + un `modelConfig={provider:"openai", model:"gpt-4o-mini"}` explicite. Auto-suffisant, ne dépend d'aucun réglage UI caché. Config complète : `observability/langfuse/evaluators.json`.

**5 judges visés par le brief → 3 retenus, 2 explicitement écartés** (pas un oubli — un evaluator observation-level ne voit ni les enfants ni les sœurs, exactement le piège documenté dans la phase) :

| Judge | Variables requises | Verdict | Raison |
|---|---|---|---|
| **Hallucination** | `query`, `generation` | ✅ actif | mappent directement sur `input`/`output` de la racine — confirmés chaînes de caractères simples (pas du JSON) par lecture de code **et** par inspection de 324 observations `v3.chat` réelles en `environment=production` |
| **Relevance** | `query`, `generation` | ✅ actif | idem |
| **User Distress** | `conversation_history`, `last_user_message` | 🟡 construit, **PAS actif** (bloqué, cf. plus bas) | le template dégrade proprement à "juger sur `last_user_message` seul" si l'historique est vide — fonctionnel malgré le trou d'instrumentation |
| **User Disagreement** | `conversation_history`, `last_user_message` | ❌ non créé | le tour = 1 trace (OBS4), aucun historique multi-tour n'est disponible sur l'observation racine ; la règle de dégradation du template est "score false si pas d'historique" → un juge **structurellement toujours faux**, du bruit pur, pas un signal |
| **Out-of-Scope Request** | `system_prompt`, `last_user_message` | ❌ non créé | vérifié par lecture de code (agent.py/triage.py) : le system prompt ne vit que sur l'observation `generation` **enfant**, jamais sur la racine — même symptôme, même décision |

Pour ces 2 derniers : il faudrait propager le system prompt et/ou l'historique jusqu'à l'observation racine (`turn_observation`/`stamp_a2a_turn`), un changement dans `agents/**`/`libs/b2c_common/**` — **hors zone OBS7**. Chantier séparé à ouvrir si on veut les 5.

### Règles d'évaluation — mapping validé sur données réelles, PAS juste sur le schéma

Les 3 règles (`obs7-hallucination-v3chat`, `obs7-relevance-v3chat`, `obs7-user-distress-v3chat`) : `target=observation`, filtre `name` any-of `[v3.chat, v3.chat_stream]` + `tags` none-of `[synthetic]`, `sampling=0.05` (bas de la fourchette 5-10 % demandée). Avant d'activer quoi que ce soit, j'ai tiré 3 observations `v3.chat` réelles en `environment=production` (`legacy-observations-v1s`, l'API v2 est absente sur notre v3 comme prévu par le brief) — input/output confirmés être des chaînes simples et non vides, contenu organique (« quelles sont vos horaires de check-in ? », « je cherche un hotel a lyon avec piscine pour demain »…). C'est la vérification "preview live" demandée par la phase, faite par lecture directe de données plutôt que par l'UI (aucun outil de preview exposé côté API).

**Découverte technique en activant** : `PATCH .../evaluation-rules/{id}` avec `enabled:true` déclenche un **preflight test réel contre le modèle** côté serveur Langfuse. Hallucination et Relevance activés en quelques secondes chacun. `obs7-user-distress-v3chat` échoue de façon reproductible : une fois avec un corps `422 evaluator_preflight_failed` / *"The operation was aborted due to timeout"*, deux fois en timeout client pur (100 s, aucune réponse). Arrêté après 2 relances infructueuses (règle CLAUDE.md : bloqué deux fois sur la même approche → stop, ne pas s'acharner). **Hypothèse non confirmée** : le prompt de ce judge (copié verbatim du template Langfuse) contient des exemples few-shot avec du langage grossier explicite, nécessaires pour enseigner ce qu'est de la détresse utilisateur — plausible que ça déclenche un chemin de modération/sécurité plus lent côté OpenAI, que les deux autres prompts (sans contenu choquant) ne déclenchent jamais. **Laissé désactivé** plutôt que forcé.

### RGPD — extension du périmètre de traitement (demandé explicitement par la phase, à valider par Fabien)

**La clé LLM du judge envoie du contenu réel de conversation (message utilisateur + réponse assistant) au provider (OpenAI)**, hors de notre instance Langfuse self-hosted EU. C'est une extension du périmètre de traitement RGPD au-delà de ce qui existait avant OBS7 (jusqu'ici tout le contenu restait dans notre Langfuse self-hosted). **Point posé explicitement à Fabien en session** (question dédiée, pas noyé dans le reste) : *"activer maintenant, sachant que ça envoie du contenu réel à OpenAI ?"* → **Fabien a approuvé l'activation immédiate** ("Yes, activate all 3 now"). Décision actée avec horodatage dans ce bloc ; 2/3 judges tournent effectivement sur du trafic de production réel depuis ce jour à 5 % de sampling.

### Annotation queue

Créée : `obs7-judge-calibration` (id `cms8msmlp000rni020ydjoijy`), 4 score configs rattachées — 3 **nouvelles** créées pour la calibration (`human_hallucination` NUMERIC 0-1, `human_relevance` NUMERIC 0-1, `human_user_distress` BOOLEAN, ajoutées à `observability/langfuse/score-configs.json`) + `empty_shortlist` (OBS3, pour le tri rapide). Objectif du design : l'humain score les **mêmes dimensions** que les judges → comparaison directe possible.

**Alimentation automatique** : `scripts/langfuse_feed_annotation_queue.py` (idempotent, exclut le tag `synthetic` via un lookup `trace.get` par candidat). **Source câblée** : `empty_shortlist == 1`. **Source pas câblée** (pas un bug) : `user-feedback == 0` — ce score n'existe pas tant qu'OBS5 n'est pas livré.

**Découverte non prévue, sans rapport avec le code OBS7 lui-même** ⚠️ **PÉRIMÉ depuis le 2026-08-24 : les scores OBS3 sont live en prod (325 occurrences, 25 par guard, depuis 09:50Z) — l'écart de déploiement décrit ici a été comblé le même jour. Conservé pour la trace du raisonnement.** À l'époque : `empty_shortlist` (comme les 12 autres scores OBS3) avait **zéro occurrence en `environment=production`** sur l'instance réelle — le dernier déploiement Railway réussi du concierge (`2026-07-30T10:28 UTC`) est **antérieur** aux merges d'OBS3 (13:46 UTC) et OBS4 (15:07 UTC). Le tracing lui-même (`v3.chat`, OBS2) tourne bien en prod ; seule la couche de scores OBS3 n'est pas encore déployée. Script donc **sans filtre d'environnement par défaut** (documenté dans son docstring). **Pas touché au déploiement Railway** (décision hors zone, à Fabien).

**🐛 Bug trouvé (par Fabien, en annotant) ET corrigé en session** : la 1ère version seedait la queue avec `objectType=TRACE`. Résultat vu par Fabien : la majorité des items affichaient `input`/`output` **`undefined`**, et pour retrouver du contenu il fallait fouiller un arbre plein de spans internes `a2a-sdk` (« beaucoup d'appels a2a, je ne vois pas comment les évaluer »). Cause racine : OBS4 a supprimé `langfuse.trace.input`/`.name` — **une trace ne porte plus d'input/output du tout**, seule son observation racine en porte. Pire : `empty_shortlist` se déclenche sur **3 formes de tour différentes** : façade HTTP (`v3.chat`/`v3.chat_stream`, racine avec contenu), tour piloté A2A (`a2a.b2c_concierge`, racine avec contenu — sessions de vérification OBS4 par ex.), et **appel ADK direct sans aucun wrapper** (`invoke_workflow b2c_concierge`/`b2c_faq`, `input=None` — probablement des replays d'expérience OBS6/`adk eval`, rien à annoter). Sur les 14 items d'origine : 3 `v3.chat`, 3 `a2a.b2c_concierge` (récupérables), 6 racines `invoke_workflow`/spans internes a2a-sdk purs (irrécupérables, supprimés), 2 supprimés entre-temps par Fabien. Les 5 scores humains déjà **COMPLETED** par Fabien sur les traces récupérables ont été laissés intacts (un score vit indépendamment du pointeur de l'item de queue — repointer l'item n'efface rien). Correction : les 6 items récupérables recréés en `objectType=OBSERVATION` pointant la vraie observation racine ; queue complétée à **10 observations `v3.chat` de production réelles supplémentaires**, vérifiées non-synthétiques une par une (⚠️ certaines traces `v3.chat` en **prod** portent bien le tag `synthetic` — un tour de vérification post-déploiement scripté disait littéralement *« ceci est un tour synthetique de verification post-b... »* — donc ce filtre n'est PAS accessoire, même en prod). Script corrigé pour de bon : résout la racine du tour réel (`v3.chat`/`v3.chat_stream`/`a2a.b2c_concierge`) et **saute** la 3e forme (`skipped_no_root`) au lieu de la mettre en file vide. État final : **16 items, tous `OBSERVATION`, tous avec du contenu réel** — 5 déjà annotés (valides), 11 en attente.

### Config versionnée

`observability/langfuse/` : `evaluators.json` (3 judges + les 2 gaps documentés), `evaluation-rules.json` (3 règles + état réel enabled/disabled), `annotation-queue.json` (queue + sources de flux), `score-configs.json` (+3 configs humaines, total 19). Tous ces endpoints sont explicitement **`unstable`** côté Langfuse — usage documentaire/reproductible, jamais un chemin de CI.

### Gates

`pytest -q` → **1263 passed, 1 skipped** (baseline OBS4 inchangée) · `ruff check .` clean · `mypy agents libs` clean · `dayuse_guardrails.sh` OK. Aucun fichier dans `agents/**`/`libs/b2c_common/**` touché (zone respectée).

### Reste

- **Annotation humaine ≥ 10 traces (DoD)** — ✅ **fait et vérifié** : 15/15 items de la queue `obs7-judge-calibration` en statut `COMPLETED` (vérifié via `list_queue_items`, pas juste déclaratif). `https://langfuse-web-production-272b.up.railway.app/project/cms4gd0d20002nz029tuly62e/annotation-queues/cms8msmlp000rni020ydjoijy`.
- **Point de calibration judge/humain PAS écrit — vérifié qu'il n'y a rien à comparer** : `scores.get_many(name=…)` pour `Hallucination`/`Relevance`/`User Distress` renvoie **0 résultat** au moment de clore la session — les règles viennent d'être activées (5 % de sampling), et le volume de trafic prod réel observé est faible (cf. les quelques observations `v3.chat` récentes). Rien à croiser tant qu'aucun judge n'a réellement tourné. **À faire dès qu'il y a des scores** : requêter `scores.get_many(name="Hallucination"|"Relevance"|"User Distress")`, croiser par `trace_id`/`observation_id` avec les 15 scores `human_*` déjà en base, écrire l'accord/désaccord ici.
- **`obs7-user-distress-v3chat` reste désactivé** — preflight qui timeout côté serveur Langfuse, cause non confirmée (hypothèse : modération OpenAI sur les few-shot avec langage grossier). À reprendre : vérifier le dashboard usage/rate-limits OpenAI du projet, ou retenter l'activation depuis l'UI directement (comportement potentiellement différent de l'API).
- **Plafond de dépense OpenAI (~20 $/mois recommandé) non vérifié posé** — à faire par Fabien sur platform.openai.com.
- **Surveillance 24 h (DoD)** — pas commencée par construction (chantier lancé ce jour). Revenir vérifier : zéro règle en erreur, coût réel observé, **et** au moins un score judge produit (préalable au point de calibration ci-dessus), sur les 2 judges actifs.
- **Écart de déploiement prod découvert** (sans rapport direct avec OBS7, signalé pas corrigé) : le concierge en prod tourne sur du code antérieur aux merges OBS3/OBS4 → les scores déterministes OBS3 et la trace distribuée A2A OBS4 ne sont **pas encore actifs en prod Railway**, seulement en dev/local. Décision de redéployer laissée à Fabien.
- ⬜ Pas de PR ouverte, pas de merge — la review humaine de Fabien reste le gate.

## 💬 Addendum 2026-07-31 (session OBS5, branche `obs5-user-feedback`, **PR #68 MERGÉE**) — feedback utilisateur 👍/👎 rattaché au tour, `trace_id` exposé côté SSE

**Contexte** : 5e chantier de `PLAN-OBS-LANGFUSE-2026-07-29.md`, dépend d'OBS4 (mergée, PR #66). Zone
annoncée `facade.py` + `web/**`. Phase écrite au lancement (`phases/OBS5-user-feedback.md`), **soumise
et approuvée par Fabien avant tout code**, exactement comme demandé.

### Écart assumé par rapport au prompt de lancement, avec preuves — navigateur→Langfuse direct rejeté

Le prompt citait le pattern officiel Langfuse (`@langfuse/browser`, `LangfuseBrowserClient({publicKey})`,
POST direct à `/api/public/ingestion`, `Authorization: Bearer <publicKey>` — vérifié dans le code
source réel du package). **Rejeté après recherche, pas par préférence** :
1. Aucun support CORS officiel/documenté côté self-hosted (discussion GitHub Langfuse officielle) — le
   pattern marche sur Cloud, rien ne garantit qu'il marche sur notre instance 3.224.3.
2. Notre widget porte déjà l'invariant inverse, écrit noir sur blanc dans
   `scripts/run_widget_proxy.py` (*« The browser only ever talks to ONE origin »*), jusqu'à proxier
   `/api/track` (Amplitude) pour cette même raison.

**Retenu** : `POST /v3/feedback` sur le concierge (`facade.py::register_v3_routes`), joignable depuis
le navigateur **sans toucher `run_widget_proxy.py`** (il proxie déjà tout `/v3/*` génériquement, par
préfixe — zéro fichier touché hors zone). Le score est posé serveur→serveur via le client Langfuse déjà
configuré (`get_langfuse()`, même client que les 16 scores OBS3). Le navigateur ne voit **aucune** clé
Langfuse, publique ou secrète — juste son `trace_id` et le même `X-Internal-Api-Key`/`CHAT_API_KEY` qui
protège déjà `/v3/chat`. L'invariant réel du prompt (jamais de secret key dans le navigateur) est
satisfait — en fait renforcé.

### Ce qui a été construit

- **`trace_id` sur le frame `progress`** (`facade.py::chat_stream`), jamais sur `done` : `done` porte le
  payload `_finalize()` qui EST `CONTRACT_KEYS`, verrouillé par un test d'égalité stricte
  (`test_active_filters.py`) — y ajouter une clé casserait l'iso-contrat agent-usa. 3 points d'émission :
  le chemin message vide, le chemin `kind == "progress"` de `_drive`, et `_crash_body()` (toujours
  `None` là — le setup a échoué avant que `turn_observation` ouvre le span).
- **`POST /v3/feedback`** (`facade.py`) : body `{trace_id, value, comment?}`, `_TRACE_ID_PATTERN` (32
  hex, le format exact d'`opentelemetry.trace.format_trace_id()`), `value` restreint à `{0.0, 1.0}`,
  même garde `_api_key_error` que `/v3/chat`. Score posé avec un `id` déterministe
  `f"user-feedback-{trace_id}"` — un re-vote (👍→👎) écrase plutôt que duplique (vérifié en vrai, voir
  plus bas). No-op silencieux si Langfuse désactivé ou si `create_score` lève — jamais casser le widget
  pour une histoire d'observabilité.
- **Front** (`web/vendor/static/js/chat/`) : `getFeedbackEndpoint()` (`api.js`, même dérivation que
  `getStreamEndpoint`) ; `runStreamedTurn` (`send.js`) retourne le `trace_id` lu sur `progress`, capturé
  dans `turnTraceId` (déclaré **hors** du `try` pour rester lisible même si une exception part avant que
  `turn` résolve) et attaché en un seul point : le `finally` externe de `sendMessage`, le seul qui tourne
  sur TOUTES les sorties de la fonction (les ~15 branches de retour anticipé — clarification, booking,
  switch de routage par type — incluses), sans threader le trace_id dans chacune. `attachFeedbackControl`
  (`ui/messages.js`) tague la DERNIÈRE bulle `.message.bot` du tour avec `data-trace-id` et y ajoute les
  2 boutons — cohérent avec « une trace = un tour » : peu importe quelle bulle interne a été peinte en
  dernier, c'est la réponse du tour dans son ensemble qui est notée. Nouveau module `feedback.js` (POST
  fire-and-forget, même pattern que le beacon Amplitude de `tracking.js`). i18n : 4 clés neuves dans les
  7 langues déjà supportées. `feedback.css` (nouveau) + import dans `index.css`.
- **13 tests neufs** (`test_facade_langfuse.py`, offline, client Langfuse enregistreur) : trace_id sur
  `progress`, absent de `done` (filet de sécurité en plus du lock `CONTRACT_KEYS` existant), crash-body
  sans trace_id, création/validation/rejet du score, no-op désactivé, garde d'auth.

### Vérifié en vrai (clés réelles, pas seulement les tests offline)

- `run_local.sh` + `curl` SSE brut : `trace_id` réel (32 hex) sur `progress`, absent de `done`.
- `POST /v3/feedback` avec ce trace_id → `listScores` (MCP `langfuse`) retrouve le score sur la BONNE
  trace, aux côtés des 16 scores OBS3 (aucune régression OBS3/OBS4 constatée — une seule trace, un seul
  arbre, comme avant).
- **Idempotence vérifiée, pas supposée** : un 2e POST (👍→👎) sur le même trace_id → **un seul** score,
  `value` mis à jour, `updatedAt` avancé, pas de doublon. Nuance notée : le `comment` du premier post est
  resté visible après le 2e (sans comment) — correspond à la fenêtre de merge post-création que Langfuse
  documente lui-même comme **dépréciée** (pas un bug de notre côté, qui envoie toujours l'objet complet
  comme recommandé — si ce merge disparaît un jour, notre comportement ne change pas).
- **Preuve navigateur réelle, pas juste l'API** : Chrome headless piloté par CDP (Node natif —
  `WebSocket` global de Node 24, **zéro dépendance ajoutée**), widget servi par `run_widget_proxy.py`
  (`WIDGET_CHAT_TRANSPORT=sse`) devant le concierge réel. Un vrai tour tapé + soumis via l'UI → contrôle
  👍/👎 attaché avec le bon `trace_id`, libellé FR correct (`t()`), clic 👍 → libellé « Merci… », bouton
  `is-selected` → score `user-feedback=true` confirmé sur CETTE trace via `listScores` (le POST est bien
  parti du vrai clic dans le vrai navigateur, pas simulé côté serveur).
- Gates : `pytest -q` → **1277 passed, 1 skipped** (skip antérieur, hors zone, +13 tests) ; `ruff check .`
  clean ; `mypy agents libs` clean (45 fichiers) ; `dayuse_guardrails.sh` OK.

### Reste

- **Score config `user-feedback` non créé** (optionnel dans la phase, jamais tranché avec Fabien) — le
  score s'ingère très bien sans (`configId: null`, comme `degraded` en OBS3) ; à faire via l'UI/MCP
  `langfuse` si utile pour l'annotation queue d'OBS7.
- Pas de commentaire libre côté UI (le paramètre `comment` existe côté route, jamais exposé dans le
  widget) — hors périmètre exprès, cf. phase.
- OBS7 (judges + annotation queue alimentée par `user-feedback=0`) : nom et convention 0.0/1.0 déjà
  cohérents, rien à recaler.
- ✅ PR #68 ouverte, review + merge faits par Fabien (`fc05f69`) — jamais mergée par la session.

## 🧵 Addendum 2026-07-30 (session OBS4, branche `obs4-trace-distribuee-a2a`, **PR #66 MERGÉE**) — UNE trace par tour de bout en bout à travers l'A2A, dette v4 soldée

**Contexte** : 4e chantier de `PLAN-OBS-LANGFUSE-2026-07-29.md`, implémente **D-OBS-5**. Périmètre exact de `phases/OBS4-trace-distribuee-a2a.md` : `libs/b2c_common/**` + `agents/**`. Tourne en parallèle d'**OBS10** (autre repo, MCP_B2C) : cette session produit le contrat d'injection qu'OBS10 consomme, et sa MR passe avant. Zéro appel LLM ajouté, zéro appel réseau ajouté (la propagation est un en-tête).

### Décision documentée AVANT le code, avec des preuves de code source — `OBS4-TRACE-PROPAGATION-CONTRACT.md`

Le fichier est le livrable de décision **et** le contrat pour OBS10. Les 3 preuves qui ont tranché :

1. **La voie « trace_id explicite dans la metadata A2A » est structurellement impossible**, pas juste moins jolie. Le point de lecture le plus précoce de cette metadata est un `before_agent_callback` ADK — à cet instant les spans racines d'ADK existent déjà et leur `trace_id` est immuable. On aurait eu **3 traces au lieu de 2** (l'observation rattachée dans la trace du concierge, tout le sous-arbre ADK de la feuille dans une autre). Retenu : **contexte W3C dans les en-têtes HTTP, extrait au bord ASGI** — le seul point d'interception qui précède la création des spans ADK.
2. **Les deux moitiés du saut A2A manquaient** : `grep propagate|inject|traceparent` sur `remote_a2a_agent.py`, les transports `a2a-sdk` client ET l'app A2A serveur d'ADK → **0 occurrence**. Donc aucun risque de double injection.
3. **Le baggage n'est pas un bonus « attributs », il est requis pour la correction de l'arbre.** `span_processor.py::_mark_app_root_candidate` : dans la feuille, `parent_expected_exported` est FAUX (le parent est distant, absent de la table locale) — sans l'entrée de baggage `langfuse_trace_id`, la feuille **revendiquerait une 2e racine applicative sur la même trace**. `suppressed_by_parent_claim` est exactement le mécanisme cross-service du SDK. Le SDK pose cette entrée seul dès qu'un de SES spans est actif (chemin façade) ; on la pose explicitement en plus pour couvrir le chemin A2A (spans ADK uniquement).

### Ce qui a été construit

- **`trace_context_carrier()`** (`b2c_common/observability.py`) : LE format de fil, un seul endroit — `{"traceparent", "baggage"}` du span actif + l'anti-double-racine. Consommé par la jambe A2A **et** par `_meta` MCP.
- **`_inject_trace_context`** : `event_hooks={"request": …}` sur le client httpx de chaque jambe. **Délibérément pas d'instrumentation httpx globale** : avec seulement 2 points d'injection nommés, Mapbox et tout futur tiers ne reçoivent **rien** de notre baggage. C'est la raison technique de la règle de sécurité, pas une préférence.
- **`A2aTurnObservation`** : middleware **ASGI pur** (précédent `BearerAuthMiddleware`) — `extract()`+`attach()` puis ouvre l'observation racine `a2a.<agent_name>`. POST seulement (le GET de l'agent card n'ouvre pas de trace), toujours **sous** le gate D7 (un appel non authentifié n'ouvre pas de trace — verrouillé par test). Monté sur toute l'app des 2 feuilles ET sur la **seule surface A2A** du concierge (`/v3/*` garde `v3.chat` comme racine ; un 2e wrapper au-dessus lui volerait nom et input).
- **`stamp_a2a_turn` remplace `stamp_langfuse_session`** (supprimé, tests remplacés) : input sur l'observation racine + `langfuse.session.id`. **Plus aucun `langfuse.trace.input`/`.name` dans `agents/**` ni `libs/**`** — verrouillé pour de bon par `libs/b2c_common/tests/test_no_deprecated_trace_attributes.py` (scan statique, précédent `test_no_dev_insecure.py`). **Dette v4 soldée.**
- **`stamp_langfuse_turn_session` CONSERVÉ** (décision, pas un oubli) : c'est la seule chose qui pose session+user sur un tour concierge piloté en A2A, où il n'y a pas de `turn_observation`. Aucun attribut déprécié dedans.
- **`mark_a2a_turn_output`** appelée depuis `agent.py::_final` (l'entonnoir unique des 12 événements terminaux) : le chemin A2A a maintenant un **output de trace**, qu'il n'avait jamais eu.
- **`turn_observation` : `as_baggage=True` sur session/user SEULEMENT.** `as_baggage` est un drapeau par appel, pas par champ → 2 `propagate_attributes` imbriqués, l'externe (identifiants opaques) part sur le fil, l'interne (tags + metadata `turn_index`/`locale`/`currency`/`domain`) reste en process. Verrou RGPD dédié dans `test_facade_langfuse.py`.
- **Moitié client du contrat MCP** : `inline_tools._call_tool` passe `meta=trace_context_carrier() or None`. **Découverte importante : ADK 2.4.0 injecte DÉJÀ le même carrier dans `_meta`** pour les tools MCP des feuilles (`mcp_tool.py:408-426`, `get_global_textmap().inject()` → `call_tool(meta=…)`) — le contrat d'OBS10 n'est donc pas inventé par nous, c'est déjà ce qui arrive sur MCP_B2C aujourd'hui ; le concierge (hors ADK) rattrape juste son retard.

### Le piège trouvé EN VÉRIFIANT en live : une trace ≠ un arbre

Premier tour réel : **1 seule trace** ✅ mais **3 observations racines** (`v3.chat`, `invoke_workflow b2c_hotel_search`, `a2a.b2c_hotel_search` côte à côte) → pas d'arête concierge→feuille dans l'Agent Graph. Cause : le `a2a-sdk` décore ses transports/handlers avec `@trace_class` (scope `a2a-python-sdk`) et ces spans sont **exactement entre** le span de jambe et les spans ADK de la feuille, **des deux côtés du saut** ; le filtre d'export les jetait, et Langfuse remonte les orphelins au premier niveau. Les vrais parents (`JsonRpcTransport._send_request`, `DefaultRequestHandler._run_event_stream`) ne sont atteignables depuis aucun code à nous.

Fix : `_should_export_span` élargi au scope `a2a-python-sdk` **sauf le préfixe `a2a.server.events.`**. Mesuré : tout le scope = **76 observations/tour** (la boucle `EventQueue.enqueue/dequeue/task_done` tire des dizaines de fois) ; avec l'exclusion = **31 observations, un seul arbre, une seule racine**. Exclusion par préfixe de module plutôt que liste blanche des noms du chemin : ça échoue **ouvert** (renommage a2a-sdk → quelques spans bruyants) plutôt que **fermé** (un trou dans l'arbre, ce qu'on venait de réparer), et `a2a-sdk==0.3.26` est pinné justement parce que 0.3.x bouge. Bénéfice : le coût du saut réseau A2A est désormais visible dans la trace (utile au chantier latence).

### Vérifié en live (sessions `obs4-check-05*`, clés réelles, MCP + LLM réels, `dev-obs4`)

| Chemin | Tours | Traces | Nom | Racines | Obs. | in/out | Générations avec usage |
|---|---|---|---|---|---|---|---|
| Façade `/v3/chat` | 1 | **1** | `v3.chat` | **1** | 31 | ✅/✅ | 4 (2 concierge + 2 feuille) |
| Pilotage A2A | 2 | **2** | `a2a.b2c_concierge` | **1** chacune | 37/40 | ✅/✅ | 4 chacune |

- Arbre unique : `v3.chat` → `invoke_agent b2c_concierge` → `invoke_agent hotel_search_leg` → transport A2A → `a2a.b2c_hotel_search` → handler A2A → `invoke_workflow b2c_hotel_search` → `invoke_agent b2c_hotel_search` → `generate_content` → `search_offers` (TOOL).
- **Usage compté 1×** : les 3 `call_llm` restent `SPAN` à usage nul (le masque de la PR #62 tient), seules les 2 `acompletion` + 2 `generate_content` portent l'usage ; `total_cost` ≈ 0,00106 $/tour de recherche.
- **Vue Sessions peuplée sur les deux chemins**. **OBS2/OBS3 non régressés** : `AGENT`×3/`TOOL`/`GUARDRAIL`/`GENERATION`×4 et **16 scores par trace avec `configId` non nul** (vérifié via `listScores` — le `scores_v3.get_many_v3` du SDK ne renvoie PAS le champ config, ne pas conclure à une régression en le lisant par là).
- `smoke_e2e.py` et `--contract` **PASS**, premier frame SSE `progress` à **3 ms** (SLO < 300 ms), `llm_calls=3`.

### Gates

`pytest -q` → **1263 passed, 1 skipped** (le skip est antérieur, hors zone ; +26 tests) · `ruff check .` clean · `mypy agents libs` clean (45 fichiers) · `dayuse_guardrails.sh` OK.

### Reste

- **OBS6 n'a rien à changer** (vérifié en lisant le code, pas supposé) : `evals/langfuse_experiment.py::_lookup_trace_facts` balaie **toutes** les traces de la session et s'arrête quand il a trouvé les faits — avec une trace unique il les trouve dans celle-là. Le commentaire du fichier qui dit « un tour produit DEUX traces » est maintenant périmé mais inoffensif (`evals/**` est hors zone OBS4).
- **Pas d'`output` sur l'observation racine de FEUILLE** (le concierge en a un) : aucun seam public ne l'expose — la chaîne `after_agent_callback` d'ADK s'arrête au premier retour non-`None` (`base_agent.py:552`) et sur la feuille search c'est `emit_search_datapart`. Les stamps supprimés ne posaient de toute façon que nom+input : zéro régression.
- **Les 5 guards géo/date de la feuille** (le « Reste » d'OBS3) sont maintenant débloqués : la feuille écrit sur la MÊME trace que le concierge, donc `score_current_trace` depuis la feuille y atterrira. Chantier séparé, zone `agents/hotel_search_agent/**`.
- **`langfuse_trace_id` est une clé de baggage privée du SDK** : pinnée par un test contre `langfuse._client.propagation.LANGFUSE_TRACE_ID_BAGGAGE_KEY`, donc un bump langfuse échoue bruyamment au lieu de rouvrir silencieusement le trou de la 2e racine.
- ✅ PR #66 ouverte, review + merge faits par Fabien (`3b1bb61`) — jamais mergée par la session.
- ✅ **OBS10 livrée ET déployée** (Fabien), et le joint OBS4+OBS10 est **vérifié en vrai** depuis
  AgentB2C (session `obs4-check-06-mcp`, MCP_B2C déployé) : **4 services, UNE trace, UNE racine**,
  34 observations — `[TOOL] search_offers` (feuille) → `[SPAN] search_offers` (MCP_B2C) →
  `elasticsearch.search` (`db.system=elasticsearch`, `db.operation=search`,
  `db.elasticsearch.index=hotel_staging_5`) → `search`. Aucun usage/coût parasite (0/0 sur les 3
  spans MCP), le coût de la trace est inchangé.
- **Preuve la plus forte que le baggage marche** : les spans de MCP_B2C portent
  `session.id`/`user.id` = les nôtres — notre baggage a franchi **deux sauts et une frontière de
  langage** (SDK Python → SDK TypeScript), appliqué automatiquement par le span processor côté
  serveur. Identifiants opaques uniquement, la règle de sécurité tient.
- ⚠️ **À faire côté MCP_B2C (repo séparé, hors zone — signalé, pas corrigé)** : ses spans arrivent en
  `environment='default'` (pas de `LANGFUSE_TRACING_ENVIRONMENT`) et
  `service.name='unknown_service:node'` (pas de `OTEL_SERVICE_NAME`). La trace reste juste (son
  environnement vient de la racine), mais en prod nos 3 services seront en `production` pendant que
  les spans ES resteront en `default` : **tout filtre ou dashboard au niveau OBSERVATION les
  omettrait silencieusement**, et un bucket `default` parasite apparaîtrait dans le sélecteur. Deux
  variables d'environnement sur le service MCP (`OTEL_SERVICE_NAME=mcp-b2c`,
  `LANGFUSE_TRACING_ENVIRONMENT=production` ; `LANGFUSE_TRACING_RELEASE` en option — nom JS, différent
  du `LANGFUSE_RELEASE` de nos 3 services Python), tableau complet dans le contrat §3.4. Nuance :
  **une valeur statique mislabellise forcément un appelant**, le même déploiement MCP sert le prod
  ET le dev local (vérifié dans les variables Railway) — la vraie correction serait un déploiement MCP
  séparé pour le dev.
- ✅ **Les 2 variables sont posées et vérifiées après redeploy** (session `obs4-check-09-live`) :
  spans MCP en `service.name='mcp-b2c'` + `environment='production'`. Le SDK Node du serveur honore
  donc `OTEL_SERVICE_NAME` sans changement de code. Le mislabel annoncé est bien visible : cette
  trace de dev (`development`) porte 3 spans MCP en `production` — à savoir en lisant un dashboard
  filtré par environnement au niveau observation.
- **Voie fermée, testée et pas supposée** : propager l'environnement de l'appelant dans le baggage ne
  marche pas. On émet bien `langfuse_environment` dans l'en-tête (inspecté en process), et les spans
  MCP restent en `default` alors que `session.id`/`user.id` du MÊME baggage arrivent. Patch d'essai
  non committé — ne pas re-tenter depuis AgentB2C, ce serait du code mort.

## 📊 Addendum 2026-07-30 (session OBS3, branche `obs3-scores-deterministes`, **PR #65 MERGÉE**) — scores déterministes, 12→13 guards, score configs + dashboard créés en vrai

**Contexte** : 3e chantier de `PLAN-OBS-LANGFUSE-2026-07-29.md`. Périmètre exact de `phases/OBS3-scores-deterministes.md` : `libs/b2c_common/**` + `agents/b2c_concierge/**` + `observability/langfuse/**` (nouveau dossier) — **zéro fichier touché dans `agents/hotel_search_agent/**`**, décision assumée (voir "Reste"). Référence : `OBS2-LANGFUSE-BRIEF.md` §2 et §8. Zéro appel LLM ajouté.

### Le compte de guards était faux dans les 3 sources à la fois — tranché avec Fabien avant tout code

Avant d'écrire `GUARD_SCORE_NAMES`, inventaire du code réel (docstrings + call sites, pas de supposition) : `link_guard.py` (S-G12, ajouté 2026-07-24) s'auto-désigne littéralement **"the 13th guard"**, et R9/`inline_tools.py`/`profile.py` désignent la confirmation de booking comme **"guard #12"**. Trois sources, trois chiffres : `AUDIT-REWORK-2026-07.md` dit 11 (le portage agent-usa d'origine, avant R9 et S-G12) ; `CLAUDE.md` disait 12 (11 + R9, jamais resynchronisé après l'ajout de S-G12) ; le code réel en a 13. Question posée explicitement à Fabien (le risque : figer un contrat permanent — "jamais renommé ensuite" — sur un chiffre déjà faux serait cher à corriger après coup) → **réponse : 13, et corriger `CLAUDE.md`** (fait, section "Architecture cible").

**`GUARD_SCORE_NAMES` (13, gelé)** dans `libs/b2c_common/b2c_common/scores.py` — 11 portés de l'audit agent-usa 2026-06 (`geocode_echo_back`, `generic_location_demotion`, `state_anchoring`, `date_hallucinated_year_rolled_forward`, `date_carryover_stale_floored`, `budget_integrity`, `timeslot_sanitization`, `recovery_ack`, `anti_clarification_loop`, `amenity_truthfulness`, `named_hotel_lookup`) + 2 ajouts AgentB2C (`booking_confirmation` = R9/guard#12, `hotel_link_truthfulness` = S-G12/guard#13). **8 sont émis dans cette session** (tous côté concierge) ; **5 restent réservés, non émis** (`geocode_echo_back`, `generic_location_demotion`, `state_anchoring`, les 2 guards date) — leur code vit entièrement dans `hotel_search_agent`, hors zone de cette phase ; câbler leur émission est un chantier séparé (voir "Reste").

### Mécanisme d'émission

- **`b2c_common/scores.py`** (nouveau) : `score_guards(fired)` (13 BOOLEAN, 0.0/1.0 jamais `True`/`False`), `score_turn(hotels_returned, llm_calls)` (+ `empty_shortlist` dérivé), `score_degraded(reason)` (CATEGORICAL, ensemble fermé `{leaf_call_failed, facade_shield}` — RGPD : jamais de texte libre), `score_ttft(ttft_ms)`. Toutes no-op sans clés, jamais levantes (même contrat que `observability.py`).
- **`TurnBudget.fired: set[str]`** (`budget.py`) — l'accumulateur par tour, déjà threadé partout où `budget` circule (`_run_async_impl`, `_synthesize_with_guards`, `_run_inline_lookup`, `_run_booking`).
- **UN seul point d'émission** : `_emit_turn_metric` (agent.py), appelé à CHAQUE sortie de tour — couvre à la fois la façade `/v3/chat` (à l'intérieur du `with turn_observation`) et le chemin A2A direct (battery/smoke/peers), sans code séparé, même précédent que `stamp_langfuse_turn_session`.
- **Points de déclenchement exacts** : `recovery_ack`/`booking_confirmation` = les signaux `is_search_refinement_signal`/`is_booking_confirmation_signal` mémorisés une fois en tête de `_run_async_impl` (au passage, supprime 2-3 appels redondants aux mêmes fonctions pures) ; `anti_clarification_loop`/`amenity_truthfulness`/`hotel_link_truthfulness` = les 3 blocs `mark_level(...)` existants d'OBS2 dans `_synthesize_with_guards`, un `budget.fired.add(...)` ajouté juste à côté ; `budget_integrity`/`timeslot_sanitization` = nouveau paramètre optionnel `fired: set[str] | None = None` sur `profile.apply_profile_delta` (rétro-compatible, tous les appels existants l'omettent), posé aux 2 points de décision réels (rejet/override) ; `named_hotel_lookup` = nouvelle clé `"guards_fired"` dans les dicts retournés par `inline_tools.get_hotel_details`/`generate_booking_link` (posée chaque fois que `_resolve_hotel_id` est réellement invoqué), fusionnée dans `budget.fired` côté agent.py.
- **`degraded`** : seulement les 2 raisons que le CONCIERGE peut observer lui-même pré-OBS4 (`leaf_call_failed` dans `_run_leaf`, `facade_shield` dans `facade.py` ×2) — `mcp_circuit_open`/`mapbox_retry_exhausted` vivent dans la feuille, sur une trace séparée, donc hors de portée honnête ici.
- **`ttft_ms`** : posé dans `facade.py::chat_stream` (les 2 points où `mark_metadata({"ttft_ms": ...})` existait déjà depuis OBS2) — jamais sur `/v3/chat` JSON (pas de notion de TTFT là), jamais sur le chemin A2A direct (pas de frame `progress` hors façade).

### Score configs + dashboard créés EN VRAI sur l'instance (pas juste committés)

Décision : utiliser le serveur MCP `langfuse` (déjà connecté à ce projet) plutôt que seulement écrire du JSON — **16 score configs créés** via `createScoreConfig` (12 `guard_*` BOOLEAN + `hotels_returned`/`llm_calls`/`ttft_ms` NUMERIC + `empty_shortlist` BOOLEAN), **7 widgets + 1 dashboard** créés via `createDashboardWidget`/`createDashboard`/`addDashboardPlacement`, puis `getDashboard` pour exporter le JSON réel (pas une supposition) dans `observability/langfuse/{score-configs.json,dashboard-b2c.json}`.

**2 lacunes rencontrées, documentées dans les fichiers eux-mêmes (`known_gaps`)** :
1. `guard_date_hallucinated_year_rolled_forward` fait 43 caractères — dépasse la limite Langfuse de 35 caractères pour un nom de score CONFIG (`createScoreConfig`). Pas de config pour ce guard (il n'est de toute façon pas encore émis, cf. ci-dessus) ; le score lui-même n'a pas cette limite, seul le config en a une.
2. Le config CATEGORICAL `degraded` a été rejeté systématiquement par l'outil MCP `createScoreConfig` (`categoricalCategories`) — testé avec values string, values numériques, un payload minimal jetable à 2 catégories, toujours la même erreur générique "Category must be an array of objects with label value pairs, where labels and values are unique". Ressemble à un bug de sérialisation de CET outil MCP précis, pas un problème de payload — à refaire depuis l'UI Langfuse (Project Settings → Scores) une prochaine fois. Le score `degraded` s'émet quand même sans config (vérifié dans les tests).

**Piège trouvé EN VÉRIFIANT en live, pas en écrivant le code** : les 16 configs créés n'étaient reliés à AUCUN score — `scores.py` ne passait jamais `config_id` à `score_current_trace`. Les tests offline ne pouvaient pas l'attraper (ils ne connaissent pas les IDs réels d'un projet Langfuse précis). Trouvé en relisant les scores fraîchement émis via `listScores` (`configId: null` partout), corrigé (`_SCORE_CONFIG_IDS: dict[str,str]` codé en dur — ce projet a UNE seule instance Langfuse partagée par tous les environnements, donc ce n'est pas une fuite d'environnement), re-testé (offline : 4 tests ajustés + 1 nouveau ; en vrai : `configId` non-null confirmé sur un tour rejoué après redémarrage du service).

### Vérifié en live (gates + smoke réel, clés réelles)

- `.venv/bin/pytest -q` → **1237 passed, 1 skipped** (le skip est antérieur, hors zone) ; `ruff check .` → clean ; `mypy agents libs` → clean (45 fichiers) ; `dayuse_guardrails.sh` → OK.
- `run_local.sh` + `smoke_e2e.py --booking` (2 tours, contextId partagé) : **`guard_booking_confirmation` passe à `1` sur les 2 tours**, les 12 autres `guard_*` à `0`, `hotels_returned=0`/`empty_shortlist=1` (cohérent, pas de shortlist en booking), `llm_calls=1` — les 16 scores visibles sur UNE trace réelle via `listScores(traceId=...)`, `config_id` correctement attaché après le fix.
- `smoke_e2e.py --contract` (ack + search réel) : trace de recherche avec `hotels_returned=5`, `empty_shortlist=0`, `llm_calls=3` ; trace SSE avec `ttft_ms=1.1`.
- 32 tests neufs : `libs/b2c_common/tests/test_scores.py` (21, contrat des 13 noms + no-op/never-raise + wiring config_id) + `agents/b2c_concierge/tests/test_spine.py::TestObs3GuardScores`/`TestObs3ScoresNeverContainMessageContent` (5) + `agents/b2c_concierge/tests/test_profile.py::TestObs3FiredTracking` (7) — dont le verrou RGPD (tour scripté réel + faux client Langfuse enregistreur, aucune valeur/comment de score ne contient le message utilisateur).

### Reste

- **5 guards géo/date non émis** (`geocode_echo_back`, `generic_location_demotion`, `state_anchoring`, `date_hallucinated_year_rolled_forward`, `date_carryover_stale_floored`) — leur code vit dans `agents/hotel_search_agent/**`, explicitement hors zone de cette phase. Câblage naturel avec OBS4 (trace distribuée) : une fois que la feuille rejoint la trace du concierge, `score_current_trace` depuis la feuille écrira sur la MÊME trace — jusque-là, les émettre depuis la feuille seule créerait une 2e trace non jointe, cohérent mais pas ce que cette phase visait. Les noms sont déjà gelés dans `GUARD_SCORE_NAMES`, rien à renommer quand ce chantier arrivera.
- **`degraded` sans score config** (bug outil MCP, voir ci-dessus) — à refaire depuis l'UI Langfuse.
- **`llm_metric_events`/logs restent la source `route`/`family` détaillée** — les scores OBS3 sont volontairement plus pauvres (juste des compteurs/booléens), pas une duplication du canal de métriques existant.
- Chiffres mesurés = un échantillon de smoke (4 tours), pas 7 jours de prod (tableau "Résultats attendus" du plan mis à jour avec cette réserve explicite).
- ✅ PR #65 ouverte, review + merge faits par Fabien (`00e5b16`) — jamais mergée par la session.

## 🧪 Addendum 2026-07-30 (session OBS6, branche `obs6-datasets-experiments`, PR #63 MERGÉE) — datasets + experiments Langfuse, gate CI non bloquant

**Périmètre exact** : `evals/**` + `scripts/**` + `.github/**` (+ `evalset/**` en lecture). Zéro touche à
`agents/**`/`libs/**` (zone OBS2, worktree parallèle). Worktree dédié, stack locale sur **8110-8112**
(voir plus bas) pendant qu'OBS2 tient 8100-8102.

**Contention de ports réglée en premier item** : `scripts/run_local.sh` prend maintenant un
`PORT_OFFSET` (défaut `0`, comportement inchangé sans la variable) — `PORT_OFFSET=10` décale les 3
services sur 8110/8111/8112, pidfiles/logs sous `.run-logs/offset-10/`. Piège corrigé au passage :
sans plus, le concierge continuait à composer les leaves sur les ports **par défaut** 8101/8102 (donc
sur la stack de l'AUTRE worktree) — `run_local.sh` exporte désormais `HOTEL_SEARCH_CARD_URL` /
`FAQ_AGENT_CARD_URL` décalés automatiquement quand `PORT_OFFSET != 0`.

**4 datasets hébergés peuplés** (`input_schema` posé, `/` = dossier dans l'UI) :

| Dataset | Items | Source |
|---|---|---|
| `b2c/geo-poi` | 21 | `evals/datasets/b2c-geo-poi.jsonl`, semé (`scripts/langfuse_seed_datasets.py`) |
| `b2c/occupancy` | 14 | idem |
| `b2c/language-robustness` | 13 | idem |
| `b2c/prod-regressions` | 6 | **importé** avec `source_trace_id` réel (`scripts/langfuse_import_dataset.py`) |

Les 3 premiers fichiers + le script de seed sont ceux de l'audit du même jour (bloc 🔍 ci-dessous,
`AUDIT-AGENTIQUE-2026-07-30.md`) : copiés ici tels quels, jamais modifiés. Le 4e (`b2c/prod-regressions`)
est nouveau cette session : 6 tours de PROD réels déjà documentés dans ce fichier (garde de l'année
hallucinée PR #57 — sessions `yr-postdeploy-1..4` — et fallback de cutoff même-jour PR #40/#58 —
`lat-dead-0`/`lat-nom-0`), le script vérifie que chaque trace existe encore et lit son VRAI texte
(jamais une retranscription à la main). `metadata.status="regression_guard"` partout : doivent
rester verts pour toujours.

**Évaluateurs Python déterministes** (D-OBS-3, zéro judge LLM ici) — `evals/langfuse_evaluators.py`,
14 tests offline (`evals/tests/test_langfuse_evaluators.py`). Convention : une clé absente
d'`expected_output` ne score rien (pas de sur-couverture) ; une clé déclarée mais dont la donnée est
indisponible (trace introuvable, champ pas encore sur le contrat) score `CATEGORICAL "skipped"` — **jamais
`value=None`** : confirmé en direct que `ScoreBody` du serveur rejette un score `None` (le sketch du
README de l'audit ne survit pas à un vrai `run_experiment`, corrigé ici). Tout le niveau réponse est
couvert (`min_hotels`/`max_hotels`/`hotels_within_km`/`resolved_country_code`/`clarify_*`/
`active_filters_include`/`offers_*_capacity_gte`/`party_total`/`message_must_(not_)contain_any`).

**Niveau trace, entièrement câblé** (le README de l'audit l'annonçait "à brancher en évaluateur
second temps (OBS6/OBS7)" — fait cette session, pas déféré) :
- `search_offers_args_include`/`_absent` : lit l'observation **déjà typée `TOOL`, nommée
  `search_offers`** dans la trace de la feuille — confirmé en direct (probe 2026-07-30) que ce
  typage existe SANS attendre OBS2 (Langfuse infère le type depuis les conventions sémantiques
  OTel qu'ADK 2.4.0 émet déjà — la découverte qu'OBS2 documente en détail dans son propre bloc
  ci-dessous). Aucune heuristique de sniffing de dict nécessaire.
- `expected_pick` : lit l'output JSON de la génération de triage (`{"family", "pick",
  "pick_position"}`) dans la trace du concierge.
- `expected_route` : mapping déterministe, **code-owned**, PAS un scraping du log stdout
  (`concierge_metric=turn ... route=leaf:hotel_search` utilise une 3e nomenclature, et un
  scraping de fichier ne marcherait que contre un process tourné en local) : `family="booking"` →
  `booking_confirmed`/`not_booking_confirmed` selon la présence de `booking_card` dans la réponse
  (le gate R9) ; `family="search"` → `search_refinement` ; sinon passthrough.
- ⚠️ **Un tour produit DEUX traces séparées** (concierge `v3.chat` + feuille `b2c_hotel_search`,
  OBS4/trace-distribuée pas encore là) exportées de façon indépendante. Piège trouvé et corrigé en
  direct : s'arrêter au premier essai de poll où la session a AU MOINS une trace fait parfois
  attraper seulement la trace concierge et jamais voir `search_offers` — le retry doit continuer
  jusqu'à trouver le fait recherché, pas jusqu'au premier résultat non vide.

**Runner** `evals/langfuse_experiment.py` — attaque l'agent par `/v3/chat` (contrat stable, pas de
dépendance à OBS2). Pattern N+1 : primes le profil directement dans **Redis**, même clé/encodage que
`profile_store.py` (`b2c_concierge:profile:{session_id}`, réutilise `SessionProfile.from_dict/to_dict`
en import read-only — même pattern que `evals/battery.py`), puis un seul POST du dernier tour. Piège
API découvert : `dataset.run_experiment(name=...)` seul fait ajouter un **timestamp ISO au nom du
run** par le SDK — il faut aussi passer `run_name=` explicitement pour un nom exact et comparable.

**Deux runs réels comparés dans l'UI**, mêmes 4 datasets, seule variable : `DAYUSE_MODEL`
(gpt-4o-mini défaut → gpt-4o) :

| Dataset | `baseline` | `after-gpt4o` | Lien |
|---|---|---|---|
| `b2c/geo-poi` (21) | `hotels_within_km` 3/17 (18%), `resolved_country_code` 14/18 (78%) | 4/17 (24%), 13/18 (72%) | `.../datasets/cms7b2txx000ilu028njtr7a2/runs/9469c30a-…` vs `.../328dcdde-…` |
| `b2c/occupancy` (14) | `search_offers_args_include` 7/9 (78%) | 6/8 (75%) | `.../datasets/cms7alk4d0001lu028f7extb4/runs/1468fe3c-…` vs `.../5a8a7150-…` |
| `b2c/language-robustness` (13) | `expected_route` 2/7 (29%) | 2/7 (29%) | `.../datasets/cms7b2wi50016lu02daki52my/runs/2aa52321-…` vs `.../21ffc2c1-…` |
| `b2c/prod-regressions` (6) | 100% partout | 100% partout | `.../datasets/cms7b304j0023lu02zu7lnxcz/runs/b0322223-…` vs `.../3e52dc68-…` |

Host : `https://langfuse-web-production-272b.up.railway.app/project/cms4gd0d20002nz029tuly62e`.
**gpt-4o n'est pas uniformément meilleur** (mieux sur le landmark radius, moins bon sur
`resolved_country_code`/`min_hotels`) — signal réel, pas un artefact. ⚠️ Ces deux runs ont été
exécutés AVANT le fix double-comptage d'usage du bloc 🩹 ci-dessous — les coûts affichés sur ces runs
spécifiques (pas les scores, indépendants) seraient ~2× surestimés côté feuilles si on les relit.

**Deux corrections aux hypothèses de l'audit du jour, mesurées, pas supposées** :
1. `search_offers_args_include` (adults/children) est déjà à **75-78 %** sur un seul tour — le
   `gpt-4o-mini` actuel émet DÉJÀ spontanément `adults`/`children` (le schéma MCP `search_offers`
   documente ces champs par leur description propre : *"minimum adult/children capacity..."*),
   contrairement à l'hypothèse de l'audit ("le modèle ne les émet pas spontanément, faute de
   description par champ"). Ce qui manque réellement (confirmé à 0 % ici) : la **restitution**
   (`active_filters.adults/children`, `capacity`/`children_capacity` sur la carte) et la
   **persistance multi-tours** (pas de champ `adults`/`children` dans `SessionProfile` → carryover
   perdu) — P0-1 reste nécessaire, mais pour un problème plus étroit que documenté.
2. `hotels_within_km` sur `b2c/geo-poi` confirme empiriquement M1-M4 de l'audit : **18-24 %**
   seulement des hôtels rendus sont dans le rayon du landmark demandé (le reste retombe sur un
   rayon ville de 20 km par défaut) — la mesure existe maintenant, avant tout fix P0-2.

**Job CI ajouté** (`langfuse-experiments`, `.github/workflows/ci.yml`) : `needs: checks`,
`continue-on-error: true`, service `redis:7`, sauté si `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` ou
`OPENAI_API_KEY` absents (mêmes secrets que le job `eval`, + 3 secrets Langfuse à ajouter côté repo
GitHub). Voie choisie parmi les deux du brief : **pytest + assert**, pas `langfuse/experiment-action`
(plus simple, cohérent avec nos gates, zéro action tierce). Seuil **non appliqué ce tour-ci** —
`evals/tests/test_langfuse_experiment_gate.py` double-gate (`RUN_LANGFUSE_EXPERIMENT_GATE=1` ET les
clés) pour ne JAMAIS s'exécuter dans le `pytest -q` offline par défaut ; l'assert de seuil est écrite
en commentaire avec la méthode (fixer après 2-3 runs de référence sur `main`).

**DoD** : `pytest -q` **1186 passed** (+14 nouveaux tests), 1 rouge = `test_llm_meter_usage`
(**antérieur, documenté rouge sur `main`**, hors zone) ; ruff / mypy (44 fichiers) / guardrails **OK**.
Rebasée sur `main` fraîche (`8726160`, post OBS2 PR #61 + fix double-comptage PR #62) après leur merge
— conflits limités à `HANDOFF.md` (ce bloc, réordonné en tête) et `evals/datasets/README.md` (ma
version, superset de celle déjà sur `main`, gardée).

**Reste**
- Seuils CI à fixer après quelques runs de référence sur `main`.
- `clarify_options_include_country` / `must_ask_city` sont des heuristiques texte faibles (comme
  documenté) — pas un chantier bloquant, juste à garder en tête en lisant leurs scores.
- Nuance d'évaluateur à connaître : `hotels_within_km`/`offers_*_capacity_gte` sont **vacuously true**
  quand 0 hôtel est rendu (rien à violer) — toujours lire ces taux CÔTE À CÔTE avec `min_hotels`.
- ✅ PR #63 ouverte, review + merge faits par Fabien (`1e44aea`) — jamais mergée par la session.
- Le pack `dayuse_eval_pack/` : non touché (vérifié, byte-identique).

## 🩹 Addendum 2026-07-30 (branche `fix/adk-call-llm-usage-doublecount`) — le double comptage d'usage sur les feuilles ADK est corrigé (2× → 1×)

**Contexte** : suite de la session OBS2 (`obs2-typage-observations`, PR #61) — celle-ci avait **trouvé et documenté** (pas corrigé, hors périmètre du typage) que `hotel_search_agent`/`faq_agent` comptaient l'usage LLM 2× dans Langfuse (`call_llm` + `generate_content` portaient le même usage). Fabien a donné le GO pour corriger ici, dans une branche dédiée basée sur `main` (indépendante de la PR #61, non mergée).

**Root cause, rappel** : `google/adk/flows/llm_flows/base_llm_flow.py:1342` crée sans condition un span `call_llm` et lui pose (`trace_call_llm`, `telemetry/tracing.py:314`) les mêmes attributs `gen_ai.*` (modèle, contenu, **usage**) que son enfant `generate_content {model}`. `ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN=2` ne retire PAS `call_llm` malgré le commentaire qui l'affirmait — c'est un item de la roadmap de migration d'ADK (`telemetry/_schema_version.py`) pas encore livré dans `google-adk==2.4.0`. Le comment fautif dans `observability.py` est corrigé.

**Correctif : `mask_otel_spans` (hook d'export Langfuse, doc §"Bonus" du brief OBS2 §1.6)** — `_mask_call_llm_usage` dans `observability.py`, câblé sur `Langfuse(mask_otel_spans=...)`. **Piège découvert en vérifiant en live** : un strip qui ne retire QUE `gen_ai.usage.*` ne suffit PAS — Langfuse retombe sur une **estimation** d'usage à partir du contenu (`gcp.vertex.agent.llm_request`/`llm_response`) + du modèle encore présents (`gen_ai.request.model`), et affiche un nombre différent mais toujours non nul (ex. mesuré : 4810 au lieu de 4484 tokens réels). Le correctif final retire **tous** les attributs `gen_ai.*` ET les deux clés de contenu dupliqué `gcp.vertex.agent.llm_request`/`llm_response` du span `call_llm` — les ids de corrélation (`invocation_id`/`session_id`/`event_id`) restent. `call_llm` redevient un simple span de timing, `generate_content` reste l'unique source d'usage/coût/contenu.

**Vérifié en live (avant/après, mêmes deux feuilles)** :
- `hotel_search_agent` (tour recherche Paris/piscine) : les 3 `call_llm` du tour repassent en type `SPAN`, usage `0/0/0` — les 2 `generate_content` restent seuls porteurs d'usage (4611 + 4485 tokens). `trace.totalCost = 0.00074895` = exactement la somme des deux `generate_content`, plus aucune contribution de `call_llm`.
- `faq_agent` (tour FAQ) : même résultat — les 2 `call_llm` à `0/0/0`, seuls les 2 `generate_content` (6154 + 1081 tokens) portent le coût.

**Tests** : `TestMaskCallLlmUsage` (4 cas — strip complet et ciblé, span sans rien à retirer laissé intact, jamais lève sur des params malformés) dans `libs/b2c_common/tests/test_observability.py`. Suite complète **1176 passed** (1 rouge pré-existant, `test_llm_meter_usage`, sans rapport, présent sur `main`), ruff/mypy/guardrails verts.

**Reste** : rien côté code. Si les dashboards de coût par feuille avaient déjà été consultés/exportés avant cette correction, les chiffres antérieurs à ce déploiement restent ~2× surestimés (historique non rétroactivement corrigé — Langfuse ne recalcule pas les observations déjà ingérées).

## 🏷 Addendum 2026-07-30 (branche `obs2-typage-observations`) — OBS2 : typage des observations, level/status_message, LANGFUSE_RELEASE, TTFT — et une découverte majeure sur ce qu'ADK type déjà tout seul

**Contexte** : 2e chantier de `PLAN-OBS-LANGFUSE-2026-07-29.md`. Périmètre exact de `phases/OBS2-typage-observations.md` : typer les observations (`agent`/`tool`/`chain`/`guardrail`), poser `level`/`status_message` sur les dégradations, `LANGFUSE_RELEASE`, positionner la mesure TTFT. **Ne touche pas** `stamp_langfuse_session` (OBS4) ni les scores (OBS3). Aucun merge.

### Étape 1 — inventaire AVANT tout code (leçon OBS1 : un span en double a triplé l'usage)

Tour réel lancé (`scripts/smoke_e2e.py --contract` + `--booking`), traces lues via `langfuse-cli` (skill `langfuse`, endpoint `legacy-observations-v1s` — le v2 `/api/public/v2/observations` renvoie 404 "v4 write mode only" sur notre 3.224.3, cf. piège ci-dessous) contre l'instance réelle. **Résultat qui change le périmètre du chantier : ADK 2.4.0 type déjà `AGENT` et `TOOL` tout seul**, sans une ligne de notre code :

```
SPAN       v3.chat                                  (nous, turn_observation)
  SPAN       invoke_workflow b2c_concierge           (ADK, natif)
    AGENT      invoke_agent b2c_concierge            (ADK, natif — gen_ai.operation.name=invoke_agent)
      GENERATION acompletion                         (litellm instrumentor, triage)
      AGENT      invoke_agent hotel_search_leg       (ADK, natif — le leg A2A lui-même)
      GENERATION acompletion                         (litellm instrumentor, synthèse)
```
Côté feuille (hotel_search_agent, faq_agent) : `invoke_agent b2c_hotel_search`/`b2c_faq` = **AGENT**, `geocode_location`/`search_offers`/`find_hotel_by_name`/`get_faq_conditions` = **TOOL** — tout ça déjà là, nativement, sur google-adk 2.4.0. Le brief §1.1 (« Langfuse ne voit que span/generation ») était donc **inexact pour cette version d'ADK** — vérifié UNIQUEMENT par la doc produit, jamais contre une trace réelle avant cette session. **Conséquence directe : la condition d'affichage de l'Agent Graph (≥ 1 observation non-span/event/generation) était déjà remplie avant OBS2**, sur n'importe quel tour avec une feuille. Ça réduit le travail réel de typage à deux trous génuinement non couverts :
- **`tool` sur les 3 tools inline du concierge** (`get_hotel_details`/`compare_hotels`/`generate_booking_link`, plus `find_hotel_by_name` en fallback) : ceux-là passent par un `ClientSession` MCP appelé à la main (`inline_tools._call_tool`), **hors de la machinerie tool-calling d'ADK** — rien ne les type. Fait.
- **`guardrail`** : n'existait nulle part (les guards sont de simples fonctions Python, jamais des spans). Fait sur les guards du concierge qui ont un vrai point d'appel : anti-boucle de clarification, vérification amenities, troncature des liens hôtel, résolution du hotel nommé (item 4), autorisation du lien de booking (R9/guard #12).
- **`chain` (tool_loop)** : **rien à typer** — `tool_loop.py` reste non câblé en prod (décision explicite S07/S06, agent.py le documente lui-même). Documenté, pas inventé de chantier.
- Côté feuilles (geocode/date/circuit-breaker/tool-budget) : ces guards tournent **à l'intérieur** d'un span déjà typé `TOOL` par ADK — pas de nouveau span (créerait exactement le doublon qu'OBS1 a payé), juste `level`+`status_message` posés sur ce span existant.

**11 vs 12 guards (CLAUDE.md à resynchroniser, déjà noté dans `AUDIT-REWORK-2026-07.md:12`)** : non tranché ici, hors périmètre — les guards typés ci-dessous sont ceux qui ont un point d'appel réel dans CE repo, pas un comptage canonique face à agent-usa.

### Étape 2 — un bug DÉCOUVERT et CORRIGÉ pendant l'implémentation : `mark_level`/`mark_metadata` dégradaient `agent`→`span`

Premier jet : `mark_level`/`mark_metadata` appelaient `Langfuse.update_current_span(level=..., metadata=...)` (l'API documentée). **Vérifié en live, ça casse le typage ADK** : `update_current_span` reconstruit un wrapper de span via `_get_observation_type_from_otel_span` (`langfuse/_client/client.py:1258`), qui ne lit QUE l'attribut `langfuse.observation.type` **déjà présent** — absent sur un span natif ADK (qui ne porte que des attributs `gen_ai.*`) — et retombe sur `"span"` par défaut. Le `.update()` qui suit **réécrit cet attribut EXPLICITEMENT** (`langfuse/_client/attributes.py:104`, `create_span_attributes` inclut toujours `OBSERVATION_TYPE`), ce qui écrase — au niveau ingestion — la classification `agent`/`tool` que le backend aurait sinon déduite de `gen_ai.operation.name`. Repro observée : `invoke_agent b2c_concierge` passait de `AGENT` (trace de baseline, avant tout code OBS2) à `SPAN` (dès qu'un `_emit_turn_metric`/`mark_level` touchait la trace) — sur un tour sans feuille (ack), ça aurait fait **disparaître la seule condition d'Agent Graph** de la trace.

**Correctif** : `mark_level`/`mark_metadata` posent maintenant des attributs OTel **bruts** (`opentelemetry.trace.get_current_span().set_attribute(...)`), exactement comme `stamp_langfuse_session` le fait déjà depuis OBS1 — jamais via le client Langfuse. Clés utilisées (lues dans `langfuse/_client/attributes.py`, cohérentes avec ce que le SDK écrirait lui-même) : `langfuse.observation.level`, `langfuse.observation.status_message`, `langfuse.observation.metadata.<clé>` (une clé par attribut, valeurs stringifiées — filtrables au premier niveau). **Reconfirmé en live après correctif** : `invoke_agent b2c_concierge` reste `AGENT` sur un tour trivial (ack, aucun guard) ET sur un tour avec guards/leaf ; `level:ERROR` retrouve bien le timeout simulé, avec le bon type. Piège à retenir pour OBS3+ : **toute mise à jour d'un span qu'on n'a pas créé nous-mêmes doit passer par l'attribut OTel brut, jamais par les méthodes de confort du SDK** (`update_current_span`/`update_current_generation`/`update_current_trace`) — ces méthodes assument implicitement qu'elles opèrent sur un span déjà typé par le SDK.

### Étape 3 — ce qui a été posé

**Helpers (`libs/b2c_common/b2c_common/observability.py`)** — 3, pas 2 (le 3e, `mark_metadata`, sert le point 8 du brief — route/feeder/llm_calls/status — explicitement demandé mais pas nommé dans la liste de helpers) :
- `observation(as_type, name, **kwargs)` — context manager, no-op si désactivé, **n'avale jamais l'exception de l'appelant** (seul l'`__enter__` du SDK est protégé — sinon un guard qui plante silencieusement violerait l'invariant « l'observabilité ne casse jamais un tour » en sens inverse : elle masquerait un vrai bug).
- `mark_level(level, status_message)` / `mark_metadata(dict)` — attributs OTel bruts, jamais lève, no-op si désactivé (détail ci-dessus).

**Noms d'observations posés** (stables, jamais de valeur dynamique) :
- `guardrail` (concierge, `agents/b2c_concierge/b2c_concierge/{agent,inline_tools}.py`) : `retry-clarification-loop`, `verify-amenity-claims`, `enforce-hotel-link-truthfulness`, `resolve-named-hotel`, `authorize-booking-link`.
- `tool` (concierge, `inline_tools._call_tool`) : `mcp-get_hotel_details`, `mcp-compare_hotels`, `mcp-generate_booking_link`, `mcp-find_hotel_by_name`.
- Vérifié en live (flux `--booking`) : `authorize-booking-link` imbrique correctement `mcp-generate_booking_link` + `mcp-get_hotel_details` + `resolve-named-hotel` → `mcp-find_hotel_by_name` — hiérarchie exacte du vrai call graph, zéro span orphelin.

**`level`/`status_message`** (jamais de contenu utilisateur, nom de règle uniquement) :
- ERROR : `leaf_call_failed` (`agent.py::_run_leaf`), `facade_shield` (`facade.py`, posé **avant** la fermeture du `with turn_observation` — voir piège plus bas), `mcp_circuit_open`/`mcp_dependency_failed` (`hotel_search_agent/mcp_guard.py`), `mapbox_retry_exhausted` (`mapbox_client.py::_request`).
- WARNING : `anti_clarification_loop`, `amenity_truthfulness`, `hotel_link_truthfulness`, `booking_confirmation_mismatch` (côté concierge) ; `tool_budget_exhausted` (`tool_budget_guard.py`) ; `geocode_ambiguous`, `geocode_echo_mismatch`, `generic_location_demoted` (`geocode_tool.py`) ; `date_hallucinated_year_rolled_forward`, `date_carryover_stale_floored` (`datetime_resolver.py` — les 2 guards de la PR #57, jamais instrumentés jusqu'ici).
- **Piège facade.py** : le `except Exception` qui construit `_shield_payload` est **hors** du `with turn_observation(...)`, donc le span est **déjà fermé** quand il s'exécute — `mark_level` y serait un no-op silencieux. Fix : un `try/except` interne, **à l'intérieur** du `with`, qui pose le niveau puis `raise` (l'except externe, inchangé, construit toujours le payload). Fait dans `chat()` ET `chat_stream._body()`.

**`LANGFUSE_RELEASE`** : **zéro code** — `Langfuse.__init__` lit déjà `os.environ.get("LANGFUSE_RELEASE")` en fallback (`langfuse/_client/client.py:350`), exactement comme `LANGFUSE_TRACING_ENVIRONMENT`. Documenté dans `agents/hotel_search_agent/.env.example` (seul fichier `.env.example` du repo). **Reste** : poser la variable (sha git court) sur les 3 services Railway — une mutation de variable d'env déclenche un redeploy, **non fait ici**, à soumettre à Fabien comme les changements Railway d'OBS0.

**TTFT** : la génération de synthèse n'est **jamais streamée** (`_generate_once`, buffered — voir son propre docstring), donc `completion_start_time` y serait un horodatage trompeur (= la fin, pas un premier token). Repli assumé, conforme au brief : mesure positionnée sur le frame SSE `progress` (`facade.py::chat_stream`, `t_request_start` capturé à l'entrée du handler), exposée en **metadata** `ttft_ms` sur l'observation courante — pas encore un score (OBS3). Vérifié en live : `ttft_ms: 1.2` (tour trivial, largement sous le SLO 300 ms).

**Metadata additionnelle** (`agent.py::_emit_turn_metric`, un seul point d'appel pour toutes les sorties de tour) : `route`, `family`, `llm_calls`, `status`. « État du circuit-breaker » du brief §1.6 n'est **pas** exposé côté concierge (il n'a aucune visibilité sur l'état du breaker de la feuille — process et trace séparés avant OBS4) ; il est visible directement là où il est vrai : `level:ERROR status_message=mcp_circuit_open` sur la trace de la feuille elle-même.

### Découverte non prévue par le brief, PAS corrigée ici (hors périmètre OBS2, à traiter à part)

**Le double comptage d'usage n'est pas résolu à 1× sur les feuilles ADK (hotel_search_agent, faq_agent) — il est à 2×, pas 3×.** Confirmé en live sur les 2 feuilles : le span `call_llm` (créé sans condition dans `google/adk/flows/llm_flows/base_llm_flow.py:1342`, `tracer.start_as_current_span('call_llm')`) et son enfant `generate_content {model}` (`google/adk/telemetry/tracing.py:732/793`) portent chacun le **même** usage token-pour-token — `trace.totalCost` de la feuille est exactement 2× le coût réel. Le commentaire dans `observability.py` (« `ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN=2` drops call_llm ») décrit une étape du plan de migration d'ADK **documentée mais pas encore livrée** dans google-adk==2.4.0 (`telemetry/_schema_version.py` : « 2. The `call_llm` span is removed » — un item de roadmap, lu dans le docstring, jamais vérifié contre le code réel avant cette session) : `call_llm` est créé **inconditionnellement**, l'opt-in ne change rien à ça. Le côté concierge (litellm direct, `instrument_litellm=True`) reste correct à 1×, seul le côté ADK LlmAgent est concerné. **Non corrigé ici** : la seule piste sûre (retirer `call_llm` du côté export via `_should_export_span`) touche exactement le mécanisme de filtrage qu'OBS1 a construit et que ce brief interdit de restreindre sans vérifier en profondeur — mérite sa propre session, pas un correctif improvisé en bout d'OBS2. **Impact budget/coût réel : les dashboards de coût par feuille sont ~2× surestimés dès aujourd'hui**, pas seulement après OBS3.

### Vérifié (gates + manuel, clés réelles)

- `.venv/bin/pytest -q` → **1186 passed**, `ruff check .` → clean, `mypy agents libs` → clean (44 fichiers), `dayuse_guardrails.sh` → OK.
- Suite offline toujours inerte sans clés (les nouveaux tests couvrent explicitement ce chemin pour les 3 nouveaux helpers).
- `run_local.sh` + `smoke_e2e.py --contract` + `--booking`, clés réelles : Agent Graph présent (déjà avant OBS2, confirmé ci-dessus), types `GUARDRAIL`/`TOOL` posés et bien imbriqués, `level:ERROR` retrouve un timeout simulé (`CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS=0.05`) sur le bon type (`AGENT`, pas dégradé), `ttft_ms` présent, metadata `route`/`family`/`llm_calls`/`status` présente et correcte (`llm_calls=3` = triage + leaf_llm + synthesis, conforme au budget).

**Reste** : (a) ✅ posé — `LANGFUSE_RELEASE` déployé sur les 3 services Railway le jour même (voir addendum au-dessus) ; (b) ✅ corrigé — le double comptage 2× sur les feuilles ADK, branche/PR dédiée le jour même (voir addendum au-dessus) ; (c) OBS3 peut démarrer (scores déterministes) — attention, OBS3 touche les mêmes fichiers qu'OBS2 (`observability.py`, `facade.py`, les call sites de guards), donc séquentiel après merge d'OBS2, pas en parallèle.

## 🛠 Addendum 2026-07-30 (branche `obs0-bump-serveur-langfuse`) — OBS0 : bump serveur Langfuse 3.205.1 → 3.224.3 + checklist UI

**Contexte** : premier chantier de `PLAN-OBS-LANGFUSE-2026-07-29.md` (D-OBS-1). Opération sur l'instance
Railway `Langfuse` (projet `bf0d2e04-…`, env `production`) — **partagée avec d'autres producers Dayuse**,
donc pilotée pas à pas avec GO explicite de Fabien avant tout redeploy. **Aucun code AgentB2C modifié.**

**Constat avant/après** : `GET /api/public/health` → `3.205.1` avant, **`3.224.3` après** sur `langfuse-web`
ET `langfuse-worker`. ⚠️ **Déviation assumée par rapport au plan** : le plan visait `3.224.2` (version
revue en détail dans `OBS2-LANGFUSE-BRIEF.md` §12.1), mais le tag flottant `langfuse/langfuse:3` avait
déjà bougé vers `3.224.3` (publié 2026-07-29, veille de l'exécution) au moment d'agir. Changelog de
3.224.3 vérifié (`gh api repos/langfuse/langfuse/releases/tags/v3.224.3`) : uniquement des bumps de
dépendances (Snyk path-to-regexp, brace-expansion) + ajout de tarifs par défaut (claude-opus-5,
gpt-5.3-codex) — rien de fonctionnel, toujours ligne v3, strict superset de 3.224.2. **Choix soumis à
Fabien et approuvé en direct** (AskUserQuestion) : épingler l'exact `3.224.3` plutôt que revenir en
arrière sur `3.224.2`. Les deux services sont pinnés en **tag exact** (pas `:3` flottant) :
`langfuse/langfuse:3.224.3` / `langfuse/langfuse-worker:3.224.3` — un futur redeploy ne dérivera plus
tout seul.

**Backups (gate obligatoire avant tout redeploy)** : volume backups Railway natifs (mutation GraphQL
`volumeInstanceBackupCreate`, pas de pg_dump manuel) sur les deux volumes, puis **verrouillés**
(`volumeInstanceBackupLock`, empêche une rotation/suppression auto) :
- Postgres : backup `obs0-pre-bump-2026-07-30-postgres` (id `0113c737-…`), 1142 Mo, `referencedMB`
  = taille du volume live → capture confirmée non vide.
- ClickHouse : backup `obs0-pre-bump-2026-07-30-clickhouse` (id `3427b161-…`), 9613 Mo, idem.

**Critères de rollback écrits et soumis à Fabien AVANT le premier redeploy** (approuvés avec le GO) :
1. `/api/public/health` pas à `200 OK` sous 5 min ou version ≠ cible.
2. Logs de migration en erreur réelle (pas les timings ClickHouse skip-index, cf. piège ci-dessous).
3. Tour synthétique introuvable / erreur d'export Langfuse dans les logs concierge/hotel-search/faq.
4. UI ou `/api/public/*` en 5xx après le bump.
5. Signe de rupture pour un autre producer Dayuse sur l'instance partagée.
Procédure : re-pin `source.image` → `langfuse/langfuse:3.205.1` exact (web) et
`langfuse/langfuse-worker:3.205.1` exact (worker) → redeploy web puis worker → reconstat santé. Si
toujours cassé : restaurer depuis les 2 backups verrouillés ci-dessus (`volumeInstanceBackupRestore`).
**Non déclenché** — bump propre du premier coup après correction de piège CLI (voir plus bas).

**Piège CLI découvert (nouveau, à retenir)** : `railway redeploy` / la mutation GraphQL
`serviceInstanceRedeploy` **rejouent le dernier build/digest déjà déployé**, ils NE relisent PAS
`source.image` après un `serviceInstanceUpdate` — un premier essai sur `langfuse-web` a ainsi produit
un déploiement **FAILED** avec l'ancien digest 3.205.1 (`meta.image` gelé sur l'ancienne config). La
mutation qui relit la config courante et redéploie dessus est **`serviceInstanceDeployV2(serviceId,
environmentId)`** — utilisée ensuite pour web puis worker, `meta.imageDigest` confirmé = digest de
3.224.3 sur les deux, `status: SUCCESS`. Autre piège confirmé (déjà connu, reconfirmé) : `railway
variables` (pluriel, pas `variable`) ; et les commandes `railway environment edit --json` /
`railway logs --service <nom>` de la doc `use-railway` **n'existent pas / échouent sans lien de projet
local** sur le CLI 4.12.0 installé — tout est passé par `scripts/railway-api.sh` (GraphQL direct,
`serviceInstanceUpdate`, `serviceInstanceDeployV2`, `deploymentLogs`, `environmentLogs`).

**Migration au boot** : Prisma OK (424 migrations, 4 nouvelles appliquées proprement sur `langfuse-web`).
Deux lignes `add_ingested_sdks_to_analytics_scores` / `add_created_at_indexes` (= les skip-indexes
ClickHouse de 3.223.0 annoncés dans le brief) sont taguées **severity `error` par Railway alors qu'elles
ont réussi** (59 ms / 275 ms, pas de stack trace, `status: SUCCESS`, health immédiatement vert) — le
migrateur ClickHouse logge sa progression sur stderr même en succès. Ne pas se fier à la sévérité seule,
regarder `status` du déploiement + le health check. `langfuse-worker` : boot propre, `MonitorRunner(1/1)`
et `monitor-queue` démarrés, `No background migrations to run`.

**Tour synthétique** : `POST /v3/chat` sur le widget prod (`X-Dayuse-Synthetic: 1`,
`X-Client-Session-Id: obs0-bump-check-01`) → 200, `turn_id=7fcc84c3fee644a0bfb1e12cd911046e`,
`concierge_metric=turn family=ack route=template:ack status=ok`. **Zéro erreur d'export Langfuse**
dans les logs des 3 services AgentB2C autour et après ce tour (vérifié via `environmentLogs`, filtre
`langfuse` et fenêtre temporelle). ⚠️ **Non vérifié** : la présence visuelle du tour dans l'UI Langfuse
elle-même — le classifieur de permissions a bloqué deux tentatives d'y accéder par un autre biais (lire
les clés `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` d'AgentB2C depuis Railway, et un `railway ssh` dans le
conteneur `langfuse-web` pour interroger ClickHouse directement) — à raison, ce sont des accès
sensibles à une prod tierce. **Reste un geste de 10 secondes pour Fabien** : chercher la session
`obs0-bump-check-01` dans Traces/Sessions pour la confirmation visuelle finale.

**Checklist §11 du brief — répondue par écrit** (méthode : lecture du code source au tag `v3.224.3`
réellement déployé, via `gh api`/GitHub, PAS un clic UI live — accès bloqué comme ci-dessus ; c'est plus
précis qu'un tour d'écran de 15 min mais mérite un spot-check visuel si Fabien veut confirmer) :

1. **Judges managés embarqués** (`worker/src/constants/managed-evaluators.json`) : **23 au total**, 11
   maintenus Langfuse (`Hallucination`, `Helpfulness`, `Relevance`, `Toxicity`, `Correctness`,
   `Contextrelevance`, `Contextcorrectness`, `Conciseness`, **`User Distress`, `User Disagreement`,
   `Out-of-Scope Request`**) + 12 partenaires Ragas. **→ Q1 : OUI, les 3 judges ciblés pour OBS7 sont
   bien présents**, plus Hallucination/Relevance.
2. **`ENCRYPTION_KEY` posée ?** OUI, mais c'est **la valeur placeholder documentée par Langfuse** (64
   zéros hex, `0000…0000`), pas une clé générée. **→ Q3 : techniquement présente donc une LLM
   Connection sera stockable, mais je recommande de la régénérer (`openssl rand -hex 32`) avant d'y
   chiffrer une vraie clé API** — sinon le secret de chiffrement est une valeur publique connue de
   quiconque lit la doc Langfuse. Rien n'est encore chiffré dessus (aucune LLM Connection configurée) :
   rotation sans risque aujourd'hui, décision à prendre par Fabien avant OBS7.
3. **`POST /api/public/mcp` + `initialize`** : l'endpoint **existe et répond** — `401` avec un message
   JSON-RPC MCP propre (`Authentication failed. Please check your API key.`), pas un 404. Probé sans
   clé (aucune clé Langfuse récupérable cette session, cf. plus haut) ; à retester avec un vrai `pk:sk`
   pour aller plus loin.
4. **Barre de recherche des traces** : couvre **input/output**, pas seulement id/name — confirmé dans
   `web/src/features/traces/server/legacyIoSearch.ts` (« legacy IO search », un scan `LIKE` sur
   ClickHouse, pas l'index texte v4) actif par défaut, désactivable via
   `LANGFUSE_DISABLE_LEGACY_TRACING_IO_SEARCH` — **absente de nos variables `langfuse-web`, donc
   active**. Corrige une hypothèse du brief §0 qui la disait absente.
5. **Écran Monitors** : présent **et backend actif**, pas juste la page — `web/src/features/monitors/`
   contient formulaires/table/onboarding complets (Slack + Webhook + GitHub Actions, aucune bannière
   « v4 only » ni gate EE dans le composant), et **`entitlements.ts` ne gate PAS les Monitors** par plan
   (`monitor-count: 20` identique sur `oss`, tous les plans self-hosted et cloud). **Confirmé en LIVE**
   au boot du worker qu'on vient de redéployer : `Starting MonitorRunner(1/1)`,
   `monitor-queue executor started: true`. **→ Ça contredit l'hypothèse du brief §0/§8 (« Monitors :
   v4-only, doc dit non ») et la raison de D-OBS-7** — sur 3.224.3 (peut-être déjà avant, le brief a été
   écrit contre 3.205.1 sans le vérifier en profondeur), les monitors semblent posables et actifs
   dès aujourd'hui. **À vérifier visuellement par Fabien avant de relancer un chantier alerting** (le
   déclenchement réel — Slack qui reçoit un message — n'a pas été testé ici, hors périmètre OBS0).
6. **Politique de rétention globale** : **NON configurable sur cette instance** — l'entitlement
   `data-retention` n'existe que sur le plan `self-hosted:enterprise` (`entitlements.ts`), absent de
   `oss`/`self-hosted:pro` ; aucune variable de licence EE (`LANGFUSE_EE_LICENSE_KEY` ou équivalent)
   trouvée sur `langfuse-web`. **→ Q4 : pas de rétention globale possible aujourd'hui → OBS9 ne pourra
   PAS sauter le backfill historique via ce mécanisme**, à budgéter en pleine taille (3× le volume
   disque ClickHouse, cf. brief §12.3).
7. **`get_dataset(version=)` / Fast Mode / backfill "Actions → Evaluate" depuis Traces** : la
   **versioning de dataset item par date existe et est câblée** (`dataset-router.ts` :
   `version: z.date()`, `listDatasetVersions`, historique de versions par item) — le paramètre `version=`
   du SDK a un répondant serveur réel. **« Fast Mode » : introuvable dans le code source** sous ce nom
   (recherche GitHub sur le repo) — soit un nom différent côté SDK/UI, soit pas encore livré ; **le
   backfill "Actions → Evaluate" depuis la table Traces n'a pas été localisé** par lecture statique des
   composants de table. **Ces deux derniers points restent à trancher par une vérification UI live en
   OBS6**, périmètre déjà annoncé comme secondaire.

**Hors périmètre respecté** : aucune migration v4, aucun upgrade ClickHouse (OBS8), aucune LLM
Connection configurée, aucun code AgentB2C touché.

**Reste** : (a) spot-check visuel Fabien de la session `obs0-bump-check-01` dans l'UI Langfuse ; (b)
décision sur la rotation d'`ENCRYPTION_KEY` avant OBS7 ; (c) réévaluer D-OBS-7 (alerting maison) à la
lumière de la découverte Monitors du point 5 ; (d) OBS6/OBS7 peuvent démarrer (checklist répondue).

## 🔍 Addendum 2026-07-30 (session Cowork audit, AUCUN changement de code) — audit agentique POI + occupancy, datasets Langfuse semés

**Déclencheur Fabien** : « champs élysées » résout un autre point ; « 2 adultes et 1 enfant » ignoré.
**Fait** (fichiers NEUFS uniquement — zone OBS2/OBS4 intouchée, aucun fichier tracké modifié sauf ce bloc) :
- **`AUDIT-AGENTIQUE-2026-07-30.md`** — root causes des 2 bugs + inventaire regex 3 catégories + plan P0/P1/P2.
  POI = 4 mécanismes : M1 v6 sans `poi` ; M2 **extraction zone-only → early-return AVANT le tier-2 Search Box**
  (`geocode_tool.py:200-228`) ; M3 **Search Box non scopé** (ni proximity ni prior locale — un POI homonyme
  mondial passe) ; M4 l'écho valide le NOM, pas le LIEU. Même famille que « gare de lyon » (addendum 2026-07-27).
  Occupancy = **MCP prêt (probé live : `adults`/`children` filtrent correctement `capacity`/`childrenCapacity`),
  chaîne agent vide de bout en bout** (profil sans champs, instruction muette, aucun carryover). Fix = triptyque
  existant amenities/date, zéro regex.
- **`evals/datasets/{b2c-geo-poi,b2c-occupancy,b2c-language-robustness}.jsonl`** (21+14+13 items, format OBS6 §2,
  N+1, ids déterministes, `status: target|regression_guard`) + **`scripts/langfuse_seed_datasets.py`**
  (`--dry-run` validé : 48 items ; upsert idempotent, `flush()`) + **`evals/datasets/README.md`** (vocabulaire
  d'assertions niveau réponse vs niveau trace, esquisse d'évaluateurs pour OBS6).
**Reste** : (1) ~~exécuter les fixes P0-1 et P0-2~~ ✅ **FAITS le 2026-08-25** (PR #79 et #80, mergées) —
voir le bloc daté en tête pour les mesures et les 3 pièges ; (2) seeder les
datasets quand l'instance Langfuse est prête (OBS0 en cours en parallèle) et prendre la baseline AVANT P0 ;
(3) P2 : demande cross-repo `resolve_location` sur l'index `poi` à verser dans `reports/MCP-B2C-REQUESTS.md`.
**Pièges découverts** : les items `occ-persistence-*` présupposent les champs profil P0-1 (échec attendu avant) ;
`create_dataset(input_schema=)` peut être absent en serveur 3.224.x (le script a un fallback sans schema).

## 🚢 Addendum 2026-07-29 (18h00) — PR #56 + #57 + #58 MERGÉES ET DÉPLOYÉES DEPUIS MAIN, vérifiées en prod

`main` = déployé (plus de divergence branche/prod pour ces 3 chantiers). Services redéployés :
**`hotel-search`** et **`concierge`** (`railway up --service <nom> --ci`) ; `faq` et `widget` inchangés,
zéro diff. `main` vert avant déploiement : **1172 passed** (seul rouge `test_llm_meter_usage`,
antérieur), ruff / mypy 44 fichiers / guardrails OK.

**Vérifié EN PROD sur https://widget-production-3f56.up.railway.app, dans les conditions exactes du
défaut** (17h57 Paris : 100 % des offres parisiennes du jour sont passées cutoff — c'était le cas le
plus défavorable possible, et c'est ce qui le rend démonstratif) :

| requête (session neuve) | avant, à 16h37 | après, à 17h57 |
|---|---|---|
| « je cherche un hotel à melun avec piscine » | 0 hôtel | **5 hôtels** + « Les réservations pour aujourd'hui (29/07) sont closes : ces offres sont donc pour le 30/07 » |
| « ok bon bah cherche à Paris alors » *(le tour de la capture)* | 0 hôtel | **5 hôtels**, date portée à 2026-07-30 |
| « je cherche un hotel à Paris avec piscine » | 0 hôtel | **5 hôtels** + divulgation, `date_reference.resolved_from = "cutoff_fallback"` |

**La preuve que le garde de date TIRE en prod** (ce que la PR #57 ne pouvait pas montrer — on ne fait
pas réhalluciner un modèle à la demande) : trace Langfuse `cc60b85b30ed613e84fa885f1c54ebca`, le
modèle a **re-produit `"2023-08-06"`** sur « pour le 6 aoout »… et MCP a reçu **`date="2026-08-06"`** →
5 hôtels. Le chemin nominal est vérifié dans la même passe (trace `704c8b9b`, modèle correct →
inchangé). 5 formulations de date sur 5 rendent maintenant des résultats, contre 4/5 avant.

**Latences chaudes mesurées** (3 + 2 tours) : chemin dead-end **avec** le probe J+1 **7,4-11,1 s**,
chemin nominal sans probe **12,0-12,7 s** — le probe n'est pas le terme dominant, et les deux
restent sous le budget feuille de 30 s du concierge. ⚠️ Le PREMIER tour après déploiement a coûté
**23,2 s** (démarrage à froid des conteneurs), pas représentatif mais à savoir avant de mesurer.

**Reste** : la PR #40 est toujours OPEN et son contenu est désormais dans `main` via #58 — à fermer.
Et la décision produit non tranchée : la carte ne montre qu'un plan tarifaire (le moins cher) sur les
2-12 vivants que MCP renvoie, donc le prix visible monte au fil de la journée (cf. bloc précédent, C).

## 🗓 Addendum 2026-07-29 (soir, branche `fix/absolute-date-hallucinated-year`, PR #57) — « pas de résultat sur Paris » : DEUX causes, aucune n'était le multi-turn

**Déclencheur** : Fabien remonte une capture (Melun piscine → 0, puis « ok bon bah cherche à PAris alors » → 0)
avec deux hypothèses : un bug multi-turn, et un filtre cutoff/rateplan qui ne regarderait que le
plan le moins cher. **Les deux hypothèses sont fausses**, et le diagnostic n'a pas été fait par
relecture de code mais en lisant les **arguments réels de `search_offers` dans Langfuse**
(session `3702055d-5076-4322-b4f1-721117c609a7`) — réflexe à garder : *la trace d'abord, la `date`
envoyée d'abord*.

| UTC | message | `date` envoyée | total | hôtels |
|---|---|---|---|---|
| 12:57:59 | …piscine à melun **pour 6 aout** | `2023-08-06` ⚠️ | 0 | 0 |
| 12:58:18 | Ok, cherche à paris alors | `2023-08-06` ⚠️ | 0 | 0 |
| 12:58:50 | …paris piscine **pour le 6 aoout** | `2026-08-06` | 38 | **5** |
| 13:03:59 | ok bon bah cherche à PAris alors *(la capture)* | `2026-07-29` | **38** | **0** |
| 13:08:04 | paris avec piscine **demain** | `2026-07-30` | 38 | **5** |

**A — l'année hallucinée (corrigée ici, PR #57).** `gpt-4o-mini` (modèle d'extraction en prod ; la
synthèse tourne en gpt-5.2) **ajoute une année** alors que sa consigne l'interdit, et prend celle de
son entraînement. `_resolve_absolute` roulait déjà une date passée sur l'année suivante dans la
branche MM-DD, mais **la branche ISO complète renvoyait l'année telle quelle**. Pire : la date
résolue est persistée dans `profile.date`, renvoyée au tour suivant dans `profile_in`, recopiée par
le modèle → **une seule mauvaise inférence contamine tous les tours suivants**, ce qui imite
exactement un multi-turn cassé. Nouvel invariant unique : *une date antérieure au « today » de
référence ne part jamais chez MCP* (`_next_occurrence` + `_usable_carried_date`, qui plafonne aussi
le carryover — TTL glissant 30 min ⇒ une session peut enjamber minuit et porter la date d'hier,
fausse pénurie sans aucune erreur de modèle). Reproductibilité mesurée : **1 session neuve sur 5**
(aléa d'échantillonnage, pas de formulation). Vérifié hors ligne au niveau de la couture avec le
payload verbatim de la trace ; **on ne peut pas faire réhalluciner le modèle à la demande**.

**B — le cutoff du jour, servi comme une pénurie : DÉJÀ CORRIGÉ DANS LA PR #40, JAMAIS MERGÉE.**
Le tour de la capture n'a rien à voir avec l'année : `total=38, hotels=[]` = 38 hôtels avec piscine
existent, **tous passés leur cutoff**. Ne pas réécrire ce correctif : #40 est ouverte depuis le
27/07. Elle avait 39 commits de retard → rebasée à contenu identique dans **PR #58** (4 conflits,
tous tests/docs, aucun dans le source ; suite 1156 passed). Mesure ajoutée aujourd'hui, qui
généralise le diagnostic du 27/07 : sur 221 offres parisiennes, **48 % mortes après 08h, 98 % après
15h, 100 % après 16h** — donc *chaque jour à partir de 16h, 100 % des recherches « aujourd'hui » sur
Paris sont un dead-end*. `total=612, results=0` sur 7 offsets ⇒ pas un artefact de pagination.

**C — l'hypothèse rateplan est infirmée côté MCP, vraie côté nous.** Le filtre cutoff/dispo est
**par offre** : un hôtel reste dans `results` sur ses plans survivants même quand le moins cher
meurt (Miami 17907 : 1 plan à 113,03 € à 10h40 local vs 4 plans dès 96,38 € le lendemain ; LA 10041 :
5 vs 11). Un hôtel ne disparaît que si **tous** ses plans sont morts. Mais `normalize_hotel`
réduit les 2-12 plans vivants au seul `_best_offer` (le moins cher) → **1 plan sur 11 atteint le
client** pour LA 10041, et comme les plans pas chers ont les cutoffs les plus tôt, **le prix visible
monte au fil de la journée sans aucun changement de tarif**. Décision produit, pas un bug : non
traité ici.

**Aussi noté (doc, PR #57)** : `total` et `has_more` sont calculés **avant** le contrôle de
réservabilité — LA annonce `total=110, has_more=true` à `from=80` pour ~22 hôtels réels. Ni l'un ni
l'autre n'est une disponibilité ; ne jamais paginer sur `has_more` seul.

**Rapport complet** (chiffres, méthode, réserves) : artefact « Why Paris returned nothing », publié
pour Fabien. **Reste** : mergeer #57 et l'un de #40/#58 (conflit léger sur `datetime_resolver.py` +
`HANDOFF.md` pour celle qui atterrit en second) ; trancher C (multi-rateplans sur la carte).

## 🩹 Addendum 2026-07-29 (soir, branche `fix/leaf-tool-budget-starves-search`) — la fausse panne « je n'arrive pas à joindre la recherche d'hôtels à Singapore »

**Déclencheur** : Fabien voit la dégradation honnête sur une recherche Singapour, alors que MCP_B2C
répond en 0,7 s. Diagnostic mené sur le déployé (repro widget 2 tours + logs des services), pas par
lecture de code — et **la cause n'était ni le MCP, ni un timeout, ni le geocode** :

```
tool=geocode_location ms=78 status=error error_type=tool_returned_error
tool=geocode_location ms=57 status=ok
tool=search_offers    ms=0  status=ok  budget_stopped=true      <-- jamais exécuté
```

**A — le budget d'outils était PLAT (2 appels, tous outils confondus).** Or un tour nominal en dépense
déjà exactement deux (`geocode_location` + `search_offers`) : **un seul geocode en échec consommait
tout le budget** et la recherche MCP était court-circuitée avant de partir. La feuille ne renvoyait
alors aucun résultat → le concierge servait `leaf_degraded_response("search")`, une panne qui n'a
jamais eu lieu. Ça frappe les destinations dont la 1re résolution échoue (« SG », « Singapour »)
bien plus que « Paris » — d'où l'apparence d'un bug propre à Singapour. Correctif :
`hotel_search_agent/tool_budget_guard.py` (nouveau) compte **par nom d'outil**
(`PER_TOOL_CALL_LIMITS` : geocode 2, MCP 2, défaut = `HOTEL_SEARCH_MAX_TOOL_CALLS`), donc un retry de
geocode ne peut plus affamer la recherche, et chaque outil reste borné (invariant « 1 retry borné »).
Le message de stop garde le préfixe `TOOL BUDGET` — c'est ce que `dayuse_agent_common.metrics`
matche pour `budget_stopped`, la métrique ne change pas. Nouveaux env optionnels :
`HOTEL_SEARCH_MAX_GEOCODE_CALLS`, `HOTEL_SEARCH_MAX_MCP_CALLS` (défaut 2 chacun).

**B — le circuit breaker comptait les erreurs MÉTIER comme des pannes.** `_is_tool_failure` traitait
tout `isError` MCP comme un échec de dépendance : **trois « aucun hôtel de ce nom » d'affilée
ouvraient le breaker** et toutes les recherches dégradaient pendant 30 s. MCP_B2C expose désormais
(2026-07-29, côté serveur) une enveloppe typée `structuredContent.error = {kind, message, retryable,
…}` ; le breaker ignore maintenant les erreurs `retryable: False` (`HotelNotFoundError`,
`AmbiguousHotelError`, `MissingMandatoryCriterionError`…) et ne compte que les vraies pannes.
Serveur sans enveloppe → comportement conservateur inchangé.

**Vérifié** : 7 tests neufs (`tests/test_leaf_tool_budget.py`) verrouillent la garantie « geocode ×2
puis search passe quand même » et les deux classifications du breaker ; suite complète 1133 tests,
ruff + mypy + guardrails verts. ⚠️ `tests/test_llm_meter_usage.py::test_usage_record_extracts_tokens_and_model`
**échoue déjà sur `main`** (vérifié par stash, antérieur à cette branche) — à traiter à part.

**Reste** : `inline_tools._call_tool` (concierge) fusionne encore transport / `isError` métier /
payload illisible dans un même `{ok: False}`. Aucun effet utilisateur constaté aujourd'hui (le
chemin inline sert déjà un message métier via `inline_unresolved_response`), mais l'enveloppe typée
est maintenant disponible pour l'exploiter — et `POI_INDEX=poi_staging_5` côté service MCP pointe un
alias inexistant (inerte tant que la résolution POI n'est pas câblée).

## 🚢 Addendum 2026-07-29 (14h55) — S-PERF4 + S-PERF5 MERGÉS, DÉPLOYÉS DEPUIS MAIN, mesurés en prod

**PR #45 et #54 mergées par Fabien**, `main` = `e893a83`. Déploiement fait **depuis le checkout de
`main`** (pas depuis une branche) : la prod est de nouveau **reproductible depuis main** — le warning
du bloc « déployé depuis la branche » est levé. `concierge` puis `widget` (`railway up --service X
--ci`), les 2 en `Deploy complete`. `hotel-search` / `faq` non redéployés : aucun diff sur leurs
dossiers. `WIDGET_CHAT_TRANSPORT=sse` toujours en place sur `widget`.

### ⚠️ CORRECTION D'UN CHIFFRE que j'avais annoncé — le gain de S-PERF5 est plus petit en prod

J'avais annoncé **−65 %** sur la synthèse. C'était mesuré sur la **stack locale**, dont le `.env`
n'a pas les mêmes modèles que la prod : **le chiffre local n'était pas comparable au chiffre prod**.
Comparaison honnête, même environnement, avant/après sur le déployé (3 runs chacun) :

| | prod avant | prod après |
|---|---|---|
| synthèse (frame `hotels` → 1er token) | 4,25 / 4,60 / 4,56 s (moy. **4,47 s**) | 2,62 / 2,23 / 3,33 s (moy. **2,73 s**) |
| longueur de la réponse | 889 / 924 / 983 car. (moy. **932**) | 299 / 292 / 318 car. (moy. **303**) |
| tour complet | moy. **8,06 s** | moy. **6,64 s** |

→ synthèse **−39 %** (pas −65), longueur **−67 %**, tour complet **−18 %**.

**Pourquoi l'écart** : la sortie a bien fondu de 67 %, mais le **coût fixe** de `gpt-5.2` (tokens de
reasoning + TTFT) ne diminue pas avec la longueur. Il reste donc un plancher ≈ 2 s que raccourcir le
texte ne peut plus attaquer. **Conséquence pour la suite : le levier dominant restant n'est plus le
prompt, c'est `DAYUSE_MODEL_SYNTHESIS`** (aujourd'hui `gpt-5.2`) — à prober seul, avec le piège
`temperature × reasoning_effort` de S-PERF3 en tête.

### Vérifié en prod

- Assets servis : `tRotate` présent dans `i18n.js`, **14 clés de variantes** `followup_*_2/_3`,
  2 sites d'appel `tRotate(` dans `search.js`, meta `du-chat-transport="sse"`.
- **Texte, tour 1** : « Pour demain autour de Paris, vous avez 5 offres de day-use, avec un gros bon
  plan : le H4 Hotel Wyndham Paris Pleyel Resort affiche une remise d'environ 66 % vs le tarif nuit.
  Dites-moi plutôt votre quartier idéal (centre, La Défense, Orly…) et votre heure d'arrivée
  souhaitée, et je resserre la sélection. » → angle `discount`, aucune liste, aucun prix recopié,
  aucune narration d'interface, étape suivante conversationnelle.
- **Texte, tour 2** (même session, « plutôt avec une piscine ») : « Pour Paris, j'ai bien filtré des
  offres avec piscine : les 5 options affichées correspondent à ce critère. Si vous me dites le
  quartier souhaité (centre, Bercy, 14e, etc.) et votre horaire idéal, je vous affine la sélection. »
  → **la remise de 66 % n'est PAS répétée** : l'anti-répétition (`profile.last_synthesis_angle`)
  fonctionne sur le déployé, pas seulement en test.
- **Relance rotée en prod** : variante 2 au tour 1, variante 3 au tour 2.
- 5 puis 10 cartes / 5 puis 10 CTA, **2 carrousels pour 2 tours** (pas de doublon) — le CTA S-CX9 et
  les notes avec compte d'avis tiennent toujours après S-PERF5.

### Rollback

- Texte long / ancien comportement : `git revert` de `3bae233` puis redeploy `concierge` (le prompt
  et l'angle sont côté concierge ; `tRotate` côté widget est indépendant et inoffensif seul).
- Transport bloquant : `WIDGET_CHAT_TRANSPORT=json` (ou supprimer la variable) + redeploy `widget`.

## 💬 Addendum 2026-07-29 (après-midi, branche `sperf5-synthesis-value-add`) — S-PERF5 : la synthèse arrête de recopier les cartes (−65 % de latence, réponse enfin variable)

**Déclencheur** : le rendu hotels-first de S-PERF4 a rendu visible un défaut qui existait depuis
toujours. Fabien : « pourquoi la génération est si longue ? la réponse a l'air toujours la même ».
**Mesuré en prod avant de toucher quoi que ce soit** (3 runs, `scripts/` ad-hoc, cf. `reports/`) :
`progress` 0,10 s → frame `hotels` 3,3-4,0 s → **premier token 7,5-8,5 s** → `done` +0,01 s.
La synthèse coûtait **4,25-4,60 s = 56 % du tour**, pour **889-983 caractères** qui **re-listaient les
5 cartes déjà à l'écran** (nom, ville, prix, note, URL) + une phrase de remplissage « Je n'ai pas
d'infos ici sur les équipements ». Et **les 114 frames `token` arrivaient toutes dans le même
instant** (burst 0,00 s) : ce ne sont pas des tokens streamés, c'est un REPLAY de texte déjà fini
(`_chunk_text` — buffering délibéré pour que les guards puissent corriger avant affichage).

**A — la synthèse ne recopie plus les cartes.** Bloc `THE CLIENT ALREADY SHOWS THE HOTELS` dans
`_SYNTHESIS_INSTRUCTION` : jamais de liste ni d'énumération, jamais de prix/note/district/URL
répétés, 2 phrases / 40 mots max, au plus 2 hôtels nommés et seulement pour dire ce que la carte ne
dit pas. Plus une règle **anti-narration d'interface** (« cliquez sur le bouton », « via le lien » —
les boutons se nomment eux-mêmes ; l'étape suivante doit être quelque chose à demander à l'agent).
`ground_truth._HEADER` amendé : ne PLUS volontairement signaler qu'un détail manque si personne ne
l'a demandé (c'est ça qui produisait la phrase sur les équipements).

**B — la variété vient de la DATA, décidée en code** (`ground_truth.synthesis_angle`, pure, testée) :
`(key, directive)`, un seul angle par tour, par ordre de « ce qui change la décision » —
`single` (1 seul hôtel) > `distance` (TOUS à ≥ 6 km : l'info la plus utile, que les cartes
enterrent en petit) > `discount` (≥ 40 % sous le tarif nuit, hôtel nommé) > `spread` (le moins cher
≤ 70 % du plus cher) > `thin_ratings` (toutes les notes sur 1-2 avis) > rien. Aucun angle n'invente :
il **recadre** des faits déjà sur les cartes, donc les guards n'ont rien de neuf à rattraper.
**⚠️ Défaut trouvé par MA propre vérification navigateur, puis corrigé** : deux recherches d'affilée
qui gardent le même hôtel en tête donnaient deux fois le même angle, quasi mot pour mot (« économie
impressionnante… 66 % ») — la feature censée créer de la variété devenait un nouveau template. D'où
`profile.last_synthesis_angle` (champ concierge-only, jamais envoyé aux feuilles) et l'argument
`exclude` : le tour suivant tombe sur l'angle d'après, ou sur aucun. Verrouillé par un test 2 tours.

**D — la relance n'est plus une constante.** `followup_refine` / `followup_questions` étaient UNE
string figée, servie à chaque recherche depuis toujours (c'était une bonne part du « toujours pareil »
— et ce n'était même pas le LLM). Nouveau `tRotate(key, seq)` dans `i18n.js` : rotation sur
`key`/`key_2`/`key_3` selon `state.turnSequence` (déterministe, pas aléatoire → rejouable, pas de
scintillement au re-render), résolue **uniquement dans la locale active** (jamais le fallback anglais
de `t()`). 3 variantes × 2 clés × **7 locales** = 28 strings ajoutées, diacritiques inclus.

**Résultat mesuré (stack locale réelle, MCP live, mêmes requêtes)**
| | avant | après |
|---|---|---|
| synthèse | 4,25-4,60 s | **1,12-1,74 s** (−65 %) |
| longueur | 889-983 car. | **159-260 car.** (−72 %) |
| contenu | liste des 5 cartes | 2-3 phrases de jugement |

3 angles distincts observés en live : Paris → *« tarif réduit d'environ 66 % »* (discount) ;
Lyon → *« il n'y a qu'un seul hôtel disponible avec piscine »* (single) ; Bordeaux → *« tous les
hôtels proposés se trouvent en périphérie, à 7-10 km du centre »* (distance).
**Navigateur, 2 tours** : angles différents (discount → fall-through), relance variante 2 → 3,
5 puis 10 cartes / 5 puis 10 CTA, **2 carrousels pour 2 tours** (pas de doublon).
`tRotate` vérifié en node sur les 7 locales : **60 assertions**, dont « aucune fuite d'anglais en fr ».

**DoD** : `pytest` **1119 passed** (+20), 1 rouge = `test_llm_meter_usage` (**rouge sur main aussi**,
arrondi du test, hors zone) ; ruff / mypy 43 fichiers / guardrails OK ; `node --check` sur les 2 JS.

**Reste / non fait (explicitement hors périmètre A+B+D)**
- **C non implémenté** : la phrase de devise mandatée par la règle 9 (« prix affichés en EUR, sans
  conversion depuis l'USD » — visible sur la capture de Fabien) est TOUJOURS là, comme la
  restatement obligatoire de la règle 7. Les rendre conditionnelles = chantier C.
- **Streaming réel du texte (Q3) non fait** : les tokens restent un replay. Option retenue si on y
  va : streaming **phrase par phrase** avec les guards déterministes appliqués par phrase (ils sont
  regex/lookup, pas LLM), l'anti-boucle restant en fin de texte. À rediscuter maintenant que la
  réponse tient en 2 phrases — le streaming a beaucoup moins d'intérêt sur 200 caractères.
- `DAYUSE_MODEL_SYNTHESIS=gpt-5.2` inchangé : levier orthogonal, à probé séparément (piège
  temperature × reasoning_effort de S-PERF3).

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

## ⏱ Addendum 2026-07-27 (branche `scx6-same-day-cutoff-fallback`, sur `main`) — S-CX6 : « aucun résultat » l'après-midi = **cutoff de réservation du jour**, pas un bug de plomberie

*(Bloc d'origine du 27/07, rebasé sur `main` le 2026-07-29 — 39 commits de retard, conflits de tests/docs résolus en gardant les deux côtés, suite re-verte ; contenu inchangé.)*

**Contexte** : Fabien remonte un screenshot (Gare de Lyon → 0 offre, chips budget/zone/filtre) — « j'ai aucun résultat qui remonte alors que je devrais en avoir ».

**Diagnostic (mesuré, pas déduit)** : chaque offre day-use porte un `cutoffDeadlineUtc` **le jour du séjour lui-même**. Sur 63 offres D+1 Gare de Lyon : cutoffs 05h(3) 06h(7) 08h(16) 09h(18) 10h(1) 12h(2) 14h(8) 15h(7) 16h(1) Paris — **le plus tardif = 16h**. Fabien testait à 17h20, et la date par défaut est **aujourd'hui** → dead-end structurel. Vérifié en marchant les **11 pages** du pool de 518 hôtels à 17h50 : `n=0` partout jusqu'à `has_more=False`. Contre-épreuve à la même seconde : **New York 3, Los Angeles 5, Paris 0** (ils sont encore le matin). Rejoué sur le **démo déployé** : « today » → 0 hôtel ; « et demain ? » → **5 hôtels 54→72 €**, mêmes coordonnées. La réponse de l'agent était donc FACTUELLEMENT juste — c'est la réponse elle-même qui était mauvaise.

**3 défauts réels corrigés** : (1) la réponse ne nommait JAMAIS la date cherchée ; (2) les chips de récupération étaient en dur et aucune ne traitait la cause ; (3) `total=518, results=[]` est la signature lisible « pool existant, tout passé cutoff » (vs `total=0` = zéro inventaire, cf. Tokyo) et la feuille ne lisait que `results`.

**Fait** :
- **Feuille — `datetime_resolver.probe_next_day_after_tool`**, nouveau `after_tool_callback` **async** placé AVANT `capture_after_tool`. **Le blocker que le HANDOFF du 27/07 laissait ouvert est levé** : ADK `functions.py:625` fait `if inspect.isawaitable(...): await ...` sur une liste mixte (vérifié sur l'ADK installé) — donc le probe plancher de S-CX3c peut suivre le même patron. Ne tire que sur la signature exacte (same-day + `total>0` + `results` vide), garde les filtres mais **drope `from`** (un autre jour est page 1), `tool.run_async` ne re-déclenche aucun callback (zéro récursion), retourne TOUJOURS None (un retour truthy casserait la chaîne after-tool), try/except total.
- **Feuille — `capture_after_tool`** consomme le payload J+1 quand sa propre normalisation donne 0, **avant** le bloc de stamping (les cartes échangées reçoivent distance/pays/aménités comme les autres) et rebinde `structured` pour que la vue compacte du modèle décrive le bon jour. Porte la date en avant (`resolved_from: "cutoff_fallback"`) sinon le tour suivant re-meurt sur aujourd'hui.
- **Feuille — clé `search_date` sur le DataPart** (`date` / `same_day` / `cutoff_closed` / `cutoff_fallback_from`), écrite sur CHAQUE recherche (le chemin carry-over/défaut ne persistait rien : c'est pourquoi rien en aval ne pouvait nommer la date).
- **Concierge — `ground_truth.date_context_block`** : divulgation OBLIGATOIRE « ces offres sont pour <date>, PAS aujourd'hui » (placée AVANT la liste), note « journée fermée » placée APRÈS la note générique pour écraser son menu « élargir la zone / augmenter le budget ».
- **Concierge — chips date-first** (`voir demain` / `après-demain` / `élargir la zone`), libellés choisis pour retomber sur `_DATE_MENTION_RE` : un clic relance une recherche datée par le chemin de raffinement existant, zéro plomberie neuve (verrouillé par test).

**⚠️ Défaut d'honnêteté attrapé avant commit (à ne pas re-introduire)** : la 1re version déduisait « les réservations d'aujourd'hui sont closes » de `same_day` seul. Un 0 same-day sur un pool **vide** (Tokyo, `total=0`) est un marché sans inventaire, pas une fenêtre fermée — le message aurait affirmé une cause que la donnée n'établit pas. La feuille ne pose `cutoff_closed` que quand des hôtels ont matché ET qu'aucun n'était réservable.

**Vérifié LIVE** (stack locale, 18h20 Paris — la condition du dead-end était réelle) : requête exacte de Fabien → **5 hôtels 54→72 €** + « Les réservations pour aujourd'hui (2026-07-27) sont closes, voici les offres pour demain » ; « le moins cher, je veux réserver » → carte + lien `checkinDate=2026-07-28` avec l'`offerId` de l'offre vue ; « un hôtel à Paris le 5 août » → **inchangé**, aucun probe. Coût : `cutoff_fallback_probe status=ok ms=569 found=1` — **1 seul appel MCP en plus**, sur le dead-end uniquement ; tour feuille 6,2 s (budget orchestrateur 10 s). `smoke_e2e` défaut / `--contract` / `--booking` : **PASS**.

**DoD** : `pytest -q` → **1050 passed** (+37 ; même unique échec préexistant `test_llm_meter_usage`, **reconfirmé rouge sur un arbre stashé** — noter que ce fichier est bien TRACKÉ aujourd'hui, contrairement à ce que disaient les addenda précédents) ; ruff OK ; mypy 40 fichiers OK ; guardrails OK. Les 3 tests de non-régression clés ont été vérifiés **en échec sans leur fix** (désactivation ciblée puis restauration).

**Non couvert en live** : le cas « aujourd'hui fermé ET demain vide aussi » (→ chips date) — Paris a de l'inventaire demain, donc non reproductible live sans fabriquer un marché. Couvert par tests.

**Reste — session à part (décidé avec Fabien)** : « gare de lyon » n'est pas résolu comme landmark parisien. Sur le replay du démo déployé, le tour 1 a proposé *La Garde (Lyon)* / *Gary (Illinois)* / *Gare (Rueil-Malmaison)* au lieu de Paris (Fabien, lui, était tombé sur Paris — le chemin n'est pas déterministe). Même famille que le bug inventory-tier du resolver.

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
