# Triage : gpt-4o-mini contre gpt-6-luna, l'appel seul (2026-10-19)

> gpt-4o-mini s'arrête le 2027-01-14 ; le triage du concierge tourne dessus en prod. Mesure faite
> **avant** toute bascule, sur l'appel de triage seul (la vraie `triage.classify()`, pas toute la pile).
> Instrument : `scripts/measure_triage_models.py`. Entrées figées : `evals/triage_inputs.jsonl`.

> **Mise à jour du 2026-10-26** : le verdict ci-dessous est celui du prompt d'origine. Après 2
> itérations du prompt, luna tient la barre. Fabien a décidé la bascule, atomique (§5).

## Verdict (prompt d'origine, 2026-10-19)

**gpt-6-luna ne tient pas tel quel. Le triage reste sur gpt-4o-mini en prod.**

- La latence et `answers_pending` ne sont pas en cause.
- Ce qui bloque : trois champs régressent avec un effet visible pour l'utilisateur (§3).
- luna gagne sur 5 champs, coûte 35 % de moins, et sort un JSON compact avec de la marge sous le
  plafond.
- Les trois régressions relèvent du prompt. Prochaine étape proposée : resserrer ces trois règles,
  puis remesurer les deux modèles avec le même instrument (le prompt est partagé).

## 1. Montage

**114 entrées, dédoublonnées sur (message, messages récents, dernière question) :**

- **62 tracées** : la GENERATION de triage des runs H3' `h3p-2026-10-19-plan-r1..3` (qa-14707,
  dialogue-state, geo-poi). On y lit les `recent_messages` et la `previous_question` exactement
  comme la pile les a passés. Le prompt n'a pas changé depuis (seulement des commentaires).
- **52 reconstruites** (approximation, signalée par ligne) : geo-class, language-robustness,
  occupancy, qa-0930.
  - `recent` vient de `dialogue_context.recent_user_messages()`.
  - La question vient de `profile.turn_question()` appliqué au tour assistant enregistré.
- Jamais `baseline/`. `prod-regressions` est exclu (son jsonl ne porte aucun message).

**Bras, entrelacés par entrée et exécutés en séquence :**

| Bras | Modèle, effort | Appels |
|---|---|---|
| `mini` | gpt-4o-mini, sans effort, comme en prod | 3 tirages × 114 + 20 « froids » |
| `luna` | gpt-6-luna, effort `none` | 3 tirages × 114 + 20 « froids » |
| `luna-low` | gpt-6-luna, effort `low`, ce qu'enverrait la seule variable Railway | 20 |

Un appel « froid » porte un préfixe aléatoire en tête du prompt système, pour casser le cache de prompt.

**Incident pendant le run.** Le réseau de sortie a changé en cours de session : l'IP
`45.156.191.77` (celle de H3') est devenue `86.218.8.120`. La bascule a produit 256 appels contigus en
« Connection error », sans un seul succès dans la fenêtre. Ces lignes ont été retirées et rejouées.

- Les bras restent entrelacés : chaque modèle a vu le même réseau, et la comparaison tient.
- Les latences absolues mêlent les deux réseaux.

- Les appels rejoués tournent sur le code avec `max_retries=0` (commit `9358b68`).
- Les premiers tournaient encore avec les relances SDK : un timeout y vaut environ 16 s.
- Lignes brutes : `evals/reports/triage_ab_2026-10-19.jsonl`, gitignoré. La copie avec la coupure est
  conservée à côté.

## 2. Opérationnel

| bras | appels | erreurs | JSON inexploitable | `length` | tokens de complétion p50/p95/max | chaud p50/p95/max | froid p50/p95/max | coût / appel |
|---|---|---|---|---|---|---|---|---|
| mini | 362 | 2 timeouts | 2 (les timeouts) | 0 | 114 / 150 / **183** | 1,74 / 2,89 / 13,3 s | 1,84 / 2,48 / 2,50 s | 0,000504 $ |
| luna | 362 | 3 timeouts (tous froids) | 3 (les timeouts) | 0 | **75 / 97 / 110** | 1,71 / 2,89 / 8,2 s | 1,97 / 4,31 / 4,36 s | **0,000326 $** |
| luna-low | 20 | 0 | 2 | **2** | 143 / 200 / 200 | 3,18 / 4,45 / 5,0 s | — | 0,000363 $ |

- **Prémisse « la variable Railway seule suffit » : réfutée en vrai.** À effort `low`, luna dépense
  64 à 101 tokens de raisonnement. 2 appels sur 20 butent sur le plafond de 200 : JSON tronqué, donc
  repli regex silencieux. D'où l'effort par rôle (commit `ccfdc2b`).
- **Marge sous le plafond.** mini sort du JSON indenté : p95 à 150 tokens, max à 183 sur un plafond de
  200. luna sort du JSON compact : max à 110 tokens.
- **Coût** (prix catalogue, remise de cache non comptée) : 0,50 $ contre 0,33 $ pour 1 000 triages,
  soit −35 %.

**Latence non tronquée** (sonde à part : 15 s de timeout, sans relance, 30 appels par case,
`evals/reports/triage_cold_probe_2026-10-19.json`) :

| | p50 | p95 | max | > 5 s | erreurs |
|---|---|---|---|---|---|
| mini froid | 1,9 s | 5,0 s | **15,4 s** (timeout) | 2 | timeout, 500 |
| mini chaud | 1,6 s | 3,7 s | **15,0 s** (timeout) | 1 | timeout |
| luna froid | 2,5 s | 6,8 s | 7,9 s | 2 | 0 |
| luna chaud | 2,2 s | 3,8 s | 6,8 s | 1 | 0 |

**Calage prod** (Langfuse, `/api/public/metrics`) :

- triage gpt-4o-mini, 1 152 appels du 09/01 au 10/19 : p50 1,36 s, p95 2,55 s, p99 4,43 s,
  **max 16,4 s** ;
- feuilles gpt-6-luna depuis le 10/15 (62 générations, prompts constants, trafic faible) : p50 1,9 s,
  p95 3,6 s, max 4,3 s.

**Lecture.**

- OpenAI était lent cet après-midi.
- Les deux modèles dépassent 5 s environ 5 % du temps, et seul mini a calé au-delà de 15 s.
- luna ajoute environ 0,5 s au p50. Ce n'est pas un motif de blocage.
- La barre fixée avant la mesure (« 0 timeout, p95 froid nettement sous 5 s ») n'est tenue par
  **aucun** des deux modèles aujourd'hui : elle ne départage rien.

**Trouvé au passage** (commit `9358b68`) : le max prod à 16,4 s, c'est la relance SDK.

- litellm passe `max_retries=2` au SDK OpenAI, qui relance les timeouts.
- Le budget de 5 s du triage valait donc environ 17 s, en prod, sur mini.
- Corrigé par `max_retries=0`.

## 3. Champ par champ (vote majoritaire sur 3 tirages, 114 entrées)

| champ | accord | arbitrage des désaccords | verdict |
|---|---|---|---|
| `family` | 110/114 | 4/4 pour luna : « vale », « va bene » sont classés `faq` par mini (attendu `search_refinement`) ; « on vient avec ma fille de 8 ans », « finalement on sera 3 adultes » aussi `faq` chez mini | **luna meilleur** |
| `language` | 113/114 | « hotel con piscina a milano oggi » : mini `es`, luna `it` ✓ | luna meilleur |
| `pick` (+ position) | 111/114 | luna rate 2 ordinaux dans une phrase : « ok pour la deuxième » (cas étiqueté `lang-ordinal-pick`) et « montre-moi plutôt le deuxième ». mini invente une position 1 pour « celui de St Pauls ». Le code ne rattrape que l'ordinal nu (`resolve_shortlist_ordinal`) | **luna pire** |
| `affirmative` | 109/114 | luna rate « passt, mach das » : le repli regex est fr/en seulement, donc `lang-affirm-de` perd son raffinement. Il rate aussi « c'est parfait vas-y », sans effet (`booking_confirmation=confirm` décide). mini dit `true` sur « ok pour la deuxième » et « yes, Paris », qui portent une demande. « 👍 » : ambigu | **luna pire** (1 cas étiqueté) |
| `booking_confirmation` | **114/114** | aucun désaccord, les 2 cas étiquetés justes des deux côtés | égal |
| `answers_pending` | 108/114 | 5/6 pour luna. Le prompt impose « no » sans LAST ASSISTANT QUESTION ; mini répond « yes » quand même (« Je confirme », « yes, Paris », « plutôt vers les champs élysées » : tours 1 qui avaient cherché sans rien demander, DQ12). Sans effet aujourd'hui, car `pending_clarification` est vide dans ces cas. 1 cas ambigu, en contexte reconstruit | luna meilleur |
| `answer_option` | 114/114 | — | égal |
| `hotel_name` | 113/114 | « celui de St Pauls » : luna « Leonardo Royal London St Paul's », mini « Leonardo Royal » | luna ≥ |
| `wants_more_options` | 114/114 | — | égal |
| `requested_budget` | 111/114 | 3/3 pour luna, dont « 150 » après la question de budget (cas étiqueté `priceRangeMax 150`), que mini laisse à `null` | luna meilleur |
| `price_comparison` | **107/114** | **7/7 contre luna** : `clear` sur « actually make it paris », « et samedi plutôt ? », « élargir la zone », « passt, mach das », « non attends… » ; `lower` sur « plutôt vers les champs élysées » (2 tirages sur 3) et « pas trop cher » au tour 1, alors qu'aucune offre n'est affichée. Les preuves citées sont dans le message, donc l'ancrage du code les laisse passer | **luna pire, bloquant** |
| `requested_occupancy` | 105/114 | luna juste sur « ma fille de 8 ans » (enfants 1, étiqueté) et « 3 adultes » (adultes 3, étiqueté), que mini laisse à `null`. Sur « bébé », mini invente un adulte. luna omet `total` quand adultes et enfants sont donnés (équivalent). « pour deux » : luna `total=2`, ce que dit la règle du prompt ; mini `adults=2` | luna meilleur |
| `requested_room`, `display_currency` | 114/114 | — | égal |

**Cas étiquetés du jeu language-robustness** :

- mini 6/8 : échoue sur « vale » et « va bene » ;
- luna 6/8 : échoue sur « passt, mach das » et « ok pour la deuxième ».

Langue = locale de l'item : mini 110/114, luna 111/114.

## 4. Suite proposée (pas faite ici)

1. **Resserrer trois règles du prompt de triage** :
   - `price_comparison` : omettre la clé hors demande explicite de prix ; `clear` seulement sur un
     abandon de prix nommé ;
   - un ordinal dans une phrase est une `position` ;
   - `affirmative` dans les 7 langues, avec un exemple allemand.

   Le prompt est partagé : mini change aussi. Il faut donc remesurer les deux bras sur la même
   fixture (`measure_triage_models.py run`), plus un contrôle sur les 3 cas étiquetés.
2. Si luna tient la barre champ par champ, faire le rejeu live au montage H3 (qa-14707,
   dialogue-state, geo-poi ×3, concurrence 1, Redis :6390, IP `45.156.191.77`), comparé à
   `h3p-2026-10-19-plan-r1..3`.
   - Ce rejeu n'a pas été lancé le 2026-10-19, pour deux raisons : la barre n'est pas tenue, et
     MCP_B2C staging était injoignable depuis la nouvelle IP.
3. Puis la bascule humaine : déployer `concierge` (effort par rôle), puis
   `DAYUSE_MODEL_TRIAGE=openai/gpt-6-luna` posé avec `--skip-deploys` avant `railway up`. Retour
   arrière : remettre la variable avant ou avec le code.

Échéance : 2027-01-14.

## 5. Les 2 itérations du prompt (2026-10-26)

**Montage** : le même que le §1, sans les bras `luna-low` ni « froid » (`--low 0 --cold 0`). Soit 114
entrées × 3 tirages × 2 modèles, sur le code avec l'effort par rôle et `max_retries=0`.
- Lignes brutes : `evals/reports/triage_ab_2026-10-26-iter{1,2}.jsonl`, gitignorées.
- Aucun exemple du prompt n'est tiré de la fixture : celle-ci est aussi le jeu de mesure.

**Barre, fixée avant la mesure :**
- au plus 1 désaccord `price_comparison` contre luna ;
- les 3 cas étiquetés justes sur luna ;
- aucun champ où luna perd l'arbitrage ;
- mini ne régresse pas ;
- 0 `length` sur luna.

**Itération 1** (`price_comparison` seulement quand le message parle de prix, ordinal dans une
phrase, accord familier dans les 7 langues) : barre ratée.
- Corrigés :
  - les `clear` parasites (zone, date, « élargir la zone ») ;
  - le `lower` sur « plutôt vers les champs élysées », qui plafonnait le prix sur un changement de
    zone ;
  - « passt, mach das » ;
  - « montre-moi plutôt le deuxième ».
- Encore faux, ou nouveau :
  - `lower` au **premier message** (« moins de 150€ », « pas trop cher ») : rien n'est à l'écran,
    donc le code pose « moins cher que quoi ? » au lieu de chercher ;
  - « ok pour la deuxième », 1 tirage sur 3 ;
  - mini tronqué 3 fois sur 3 sur « moins cher ? » (JSON indenté, plafond de 200 tokens) ;
  - une dérive de la langue vers `es`.

**Itération 2** (JSON compact sur une ligne ; ni premier message ni montant pour `price_comparison` ;
le triage classe les mots, il ne voit jamais la liste ; moins d'exemples étrangers) :

| bras | erreurs | JSON KO | `length` | tok. compl. p50/p95/max | latence p50/p95 | coût / appel |
|---|---|---|---|---|---|---|
| mini | 1 timeout | 1 | 0 | 79 / 104 / 106 | 1,69 / 2,43 s | 0,000531 $ |
| luna | 0 | 0 | 0 | 81 / 99 / 116 | **1,49 / 2,49 s** | **0,000364 $** |

**Côté luna, la barre est tenue :**
- `price_comparison` : **1** désaccord (7, puis 6). Reste « non attends ne confirme pas, montre-moi
  plutôt le deuxième » : `lower` en majorité, sur un message qui choisit aussi une position.
- Plus aucun `lower` au premier message.
- Cas étiquetés : « ok pour la deuxième » 2 tirages sur 3 en `position` ; « passt, mach das »
  juste ; « 150 » (réponse à la question de budget) juste. mini rate encore ce dernier.
- `family` 4 sur 4 pour luna. `language` : luna juste sur les 2 désaccords avec mini.
- 0 `length`, 0 erreur.

**luna, prompt d'origine → itération 2** (vote majoritaire, champ par champ) :
- Gains :
  - 2 ordinaux ;
  - « passt, mach das » ;
  - `answers_pending` juste sur « vale », « va bene » et « c'est parfait vas-y », qui répondent à
    la question posée ;
  - 6 `price_comparison` parasites retirés.
- **1 régression** : « hotel con piscina a milano oggi », `it` → `es`, sur les deux modèles (langue
  = locale de l'item : 111 → 110 sur 114).
- **3 changements à juger en live** (jeux entre parenthèses) :
  - « non attends ne confirme pas, montre-moi plutôt le deuxième » : `price_comparison` passe de
    `clear` à `lower`, alors que le message choisit aussi la 2e position (`language-robustness`) ;
  - « celui de St Pauls » : `hotel_name` passe du nom complet composé à `null` (`geo-class`). La
    ligne de fixture est reconstruite sans la question d'origine (« quel Leonardo Royal ? »), qui
    est justement ce qui permet de la trancher ;
  - « oui » en réponse à « dans quelle ville ? » : `answers_pending` passe de `yes` à `no`, avec
    `affirmative` vrai (`dialogue-state`).

**Côté mini, la barre est ratée.** En JSON compact, mini omet les clés à leur valeur par défaut (57
`affirmative`, 57 `booking_confirmation`, 55 `wants_more_options`). Pour le code, `None` veut dire
« le LLM n'a rien dit », et ces 3 champs repassent par les regex fr/en (`is_bare_affirmative`,
`is_more_options_signal`, la confirmation). mini dérive aussi vers `es` sur 2 messages français.

**Décision (Fabien, 2026-10-26)** : luna accepté, bascule **atomique**. Le code et la variable
partent ensemble, et un retour arrière ramène les deux. Ainsi mini ne tourne jamais avec ce prompt.
Avant la bascule : le rejeu live H3 (`qa-14707`, `dialogue-state`, `geo-poi`) + `geo-class` +
`language-robustness`, qui couvrent les 4 cas ci-dessus.

## 6. Rejeu live, 2 bras (2026-10-27) : luna au niveau de la prod, bascule

**Montage.**
- IP `45.156.191.77`, Redis :6390, concurrence 1, 3 tirages par bras.
- 5 jeux, 67 items : `qa-14707` (12), `dialogue-state` (11), `geo-poi` (21), `geo-class` (10),
  `language-robustness` (13).
- **A** = main `54c6a09` (la prod), triage gpt-4o-mini ; **B** = `feat/triage-gpt-6-luna`, triage
  luna.
- Réglages communs : feuilles luna, synthèse `gpt-5.2` (`DAYUSE_REASONING_EFFORT_SYNTHESIS=low`,
  comme la démo), `DISABLE_AIOHTTP_TRANSPORT=True` (voir plus bas).
- Runs `m1-2026-10-27-httpx-{mini,luna}-r{1,2,3}`.
- Pas de comparaison à `h3p-2026-10-19` : `dialogue-state` et `geo-poi` ont changé le 2026-10-20
  (`b3e2318`).
- Ces 2 jeux étaient restés à leur version d'avant `b3e2318` dans Langfuse (7 items différents, 2
  manquants). Tous les items hébergés étaient identiques au repo d'avant `b3e2318`, donc aucune
  correction faite dans Langfuse n'a été perdue. Ils ont été ré-amorcés.

**Premier essai invalide** (`m1-2026-10-27-{mini,luna}-r*`, à ignorer) :
- Sur les 2 bras, ~42 % des triages sont passés en repli regex.
- Ces « Timeout » échouaient en **0,02-0,06 s** : le transport aiohttp de litellm réutilise une
  connexion que le réseau local a coupée.
- Reproduit hors service sur le même appel : échec après 8 s et 30 s d'inactivité, 7 sur 7 bons
  avec `DISABLE_AIOHTTP_TRANSPORT=True`.
- Depuis #157 (`max_retries=0`), plus rien ne masque ce défaut.
- Prod non touchée : 2 timeouts sur 273 triages depuis le déploiement de `54c6a09`.

**Résultats** (replis du triage : luna 0 sur 276 tours, mini 4 sur 268) :
- Total des évaluateurs : **mini 575/631 (91,1 %), luna 574/631 (91,0 %)**.
- 45 lignes (jeu × évaluateur) sur 50 sont identiques ; les 5 autres diffèrent d'un seul item.
- 2 gains pour luna : `ds-oui-to-clarify-keeps-request` et `qa14707-gare-du-nord-en`, tous deux
  sur `active_filters_include`, 3 sur 3 contre 2 sur 3.
- 3 pertes, aucune due au triage :
  - `geo-poi-generic-gare-no-city`, `must_ask_city` 0/3 contre 1/3 : les 6 réponses des 2 bras
    **demandent bien la ville**. C'est l'heuristique de mots-clés qui la rate, comme le
    2026-10-19.
  - `geo-poi-notre-dame`, `clarify_options_include_country` 2/3 contre 3/3 : aucune
    clarification dans les 6 runs, tous trouvent des hôtels. L'évaluateur bascule quand la réponse
    ne nomme pas Paris.
  - `qa14707-poissonniere-75009-no-country-en`, `resolved_country_code` 2/3 : un tour dégradé
    (« I can't reach the hotel search »), un incident ponctuel.

**Les 4 cas que la mesure hors ligne ne tranchait pas :**
- « celui de St Pauls » : 3/3 sur les 2 bras. En contexte réel, la question d'origine est
  présente.
- « oui » à « quelle ville ? » : luna 3/3, mini 2/3.
- « non attends… montre-moi plutôt le deuxième » : `expected_route` échoue 3/3 **sur les 2 bras**.
  C'est un défaut existant, que le `lower` de luna ne change pas.
- Milano : la prod (mini) répond **en espagnol 3 fois sur 3** ; luna 2 fois en espagnol, 1 en
  italien. La dérive `es` est celle du modèle en prod, pas une régression de luna.

**Verdict** : luna tient le niveau de la prod de bout en bout. La bascule peut se faire.

## Reproduire

```bash
.venv/bin/python scripts/measure_triage_models.py extract      # reconstruit la fixture (Langfuse)
.venv/bin/python scripts/measure_triage_models.py run --out evals/reports/triage_ab.jsonl
.venv/bin/python scripts/measure_triage_models.py report evals/reports/triage_ab.jsonl
```
