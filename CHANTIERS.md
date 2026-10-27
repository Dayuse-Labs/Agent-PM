# Chantiers AgentB2C — état vérifié au 2026-09-14 (sections L et QA14707 : 2026-10-16 ; Q1 et Q3 fermés, M1 ouvert le 2026-10-19)

> **Ce fichier remplace `tasks/todo.md`**, dont les cases sont fausses (les sessions S-G1→S-G9 y
> sont décochées alors que toutes sont mergées). Il est destiné à être ouvert au début d'une
> session fraîche, avant `HANDOFF.md`.

## Comment s'en servir

Chaque chantier porte :

| Champ | Ce que c'est |
|---|---|
| **Contexte** | pourquoi ce chantier existe, en 2-4 phrases |
| **Preuve** | ce qui prouve qu'il est *encore ouvert* — fichier:ligne, commande, ou « documentaire seulement » |
| **Actions** | les étapes concrètes |
| **Prompt** | à copier-coller tel quel dans une session Claude Code fraîche |
| **Terminé quand** | le critère d'acceptation, vérifiable |
| **Taille** | S = moins d'une session · M = une session · L = plusieurs |

Les prompts supposent que la session a lu `CLAUDE.md` (elle le fait automatiquement) et
appliquent ses règles : vérifier avant de construire, gates locaux verts, branche + MR,
jamais de merge en autonomie.

---

## Vue d'ensemble

**Ordre suggéré pour repartir :** `W1` (visible par
l'équipe, dès que tu donnes la copy) → `E2` puis `E1` puis `E4` (la boucle QA devient utilisable)
→ `O1` (lever le risque v4 pendant qu'il reste 4 mois) → `Q2`/`Q3` (hygiène) → le reste.

| # | Chantier | Taille | Bloqué par |
|---|---|---|---|
| ~~**Q1**~~ | ✅ Fait : test pourri par le calendrier réparé (PR #114/#115, garde `tests/test_calendar_rot.py`) | S | — |
| **W1** | Les 2 libellés de réassurance du widget (QA 7 et 8) | S | **Fabien** (copy) |
| **Q2** | Corriger les 3 documents qui enseignent du faux | S | — |
| **Q3** | Hygiène : `todo.md` périmé + 78 branches mergées | S | — |
| **E1** | Une seule commande pour lancer un jeu de cas | S/M | — |
| **E2** | Marquer les tours de test (`X-Dayuse-Synthetic`) — volet widget fait avec AM1 (`?du_synthetic=1`) ; reste le harnais | S | — |
| **E3** | Une vérification sur l'URL du lien (QA 4) | S/M | — |
| **E4** | Ouvrir le jeu `b2c/qa-reports` + y verser 3 cas | S | — |
| **E5** | Que devient le seuil de qualité sans CI ? | S | **Fabien** (décision) |
| **O1** | Lever le risque `ingestion` avant v4 | S | — |
| **O2** | OBS8 — ClickHouse 24.10 → 25.12.11.4 | L | **Fabien** (fenêtre) |
| **O3** | Plafond de dépense OpenAI | S | **Fabien** (console) |
| **O4** | OBS9 — migration Langfuse v4 | L | O1, O2 · ⏰ **fin janv. 2027** |
| **O5** | 2 variables d'env sur le service MCP | S | **MCP_B2C** |
| **O6** | Vignette `degraded` manquante | S | — |
| **P1→P6** | 6 décisions produit en attente | — | **Fabien** |
| **A1** | Identité D7 → oidc-mtls ; rotation des bearers semaine du 2026-11-02 | L | repo fleet · ⏰ **2027-01-31** |
| **A2** | S10 shadow-run / S11 canary | L | accès ES prod |
| **A3** | `conversation_logs` + `InMemorySessionService` | M | S10/S11 |
| **G1→G12** | Backlog produit / géo | — | — |
| **L** | Compréhension géo — série S-L (ajouté le 2026-10-08) ; `GeoIntent` produit par la feuille (DQ1) : S-L3/S-L4 conditionnelles, S-L7a et S-L7f faites, S-L7d et S-L7e restent | L | MCP déployé (S-L1) |
| **QA14707** | Retours QA de Raphael du 14/10 : créneau localisé, lieu compris (`GeoIntent` dans la feuille), clarification tenue par le code. Phases 1-3 déployées (`0b65159`) ; phases 4-5 sur `plan/qa14707`. Plan : `plans/qa14707/`, source : `phases/QA14707/` | L | **Fabien** (revue de la seconde PR, H3' live, H4 retest) |
| **X1→X3** | 3 demandes chez MCP_B2C | — | **MCP_B2C** |
| **M1** | Sortir de gpt-4o-mini (arrêt 2027-01-14) : juge du gate passé (baseline à refaire) ; triage : prompt resserré, rejeu live au niveau de la prod (2026-10-27), reste la bascule atomique (#158) ; 3 évaluateurs Langfuse (réglages UI) | M | **Fabien** (OK Langfuse, merge #158) · ⏰ **2027-01-14** |
| **AM1** | Tracking Amplitude : AgentB2C #146 et dayuse-product-analytics #112 mergées (vu le 2026-10-26) ; restent dayuse.com !15273 et 3 vérifications humaines | S | **Fabien** (!15273) |
| **MOB1** | Le widget dans l'app mobile (`__DAYUSE_NATIVE__`, pont de navigation, `native_context` opaque côté concierge) : plan de test + prompt | M | phase C : **Fabien** (app de prod) |

**Deux échéances datées** :
- **2027-01-14** : arrêt de gpt-4o-mini, qui fait encore tourner le triage et les juges Langfuse
  (`M1`) ;
- **fin janvier 2027** : fin des patchs de sécurité Langfuse v3 (chaîne `O1 → O2 → O4`).

Tout le reste est arbitrable.

---

## ⚠️ Contraintes permanentes — à lire avant de planifier quoi que ce soit

### 1. Il n'y a plus de CI. Les gates sont locaux.

La facturation GitHub Actions ne sera pas réactivée (décision Fabien, 2026-09-14). Les jobs
ne démarrent pas du tout : `checks` échoue en 3 s avec **0 étape**, message GitHub
*« The job was not started because recent account payments have failed or your spending limit
needs to be increased »*.

**Conséquences à intégrer, pas à contourner :**

- Toute PR affichera un rouge qui ne veut rien dire. **Ne jamais lire ce rouge comme un signal.**
- Les jobs `eval` et `langfuse-experiments` de `.github/workflows/ci.yml` sont **inertes**. Ils
  restent en place au cas où la facturation reviendrait, mais aucun chantier ne doit en dépendre.
- **Le gate de qualité, c'est la commande locale.** Avant toute MR :

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

  Le hook pre-commit (`git config core.hooksPath .githooks`) exécute déjà les guardrails.

### 2. Ne jamais planifier sur du texte de doc seul

Les blocs `### Reste` de `HANDOFF.md` **se recopient de bloc en bloc** : trois items y ont
survécu plusieurs semaines après leur livraison. `tasks/todo.md` est faux.
**Règle : prouver qu'un item est ouvert par une commande avant de planifier dessus.**

### 3. Le produit ne reçoit presque plus de trafic

51 tours le 07/09, puis 4 / 14 / 0 / 4 / 0 / 0 / 0. Dernier tour réel le **11 septembre**.
Les 3 juges LLM n'ont produit que **3 scores depuis le 09/09**. Toute mesure d'observabilité
est donc statistiquement faible aujourd'hui : c'est une limite réelle, pas un bug à chercher.

---

## ⛔️ Ne relance PAS ces items — ils sont écrits comme ouverts mais sont livrés

C'est la section qui économise le plus de temps.

| Item écrit comme ouvert | Réalité |
|---|---|
| « Le budget affiché n'est pas le budget appliqué » | **Livré** — `budget_injection.py::inject_profile_budget`, câblé `agents/hotel_search_agent/hotel_search_agent/agent.py:58` + `:356`, PR #105 |
| « Les 2 guards date non câblés » | **Livré** — `libs/b2c_common/b2c_common/scores.py:29` « Every name in `GUARD_SCORE_NAMES` is now wired », 15 entrées |
| « `triage.response_language` : PR séparée toujours ouverte » | **Livré** (ne pas confondre avec le chantier P4 plus bas, qui est un *autre* sujet) |
| S-G1, S-G2, S-G3, S-G5…S-G9 décochés dans `todo.md` | **Toutes livrées**, blocs HANDOFF datés du 2026-07-23 |
| `FLEET_READ_TOKEN` « BLOCKING » + « build the 3 images » + « pending Fabien's go » | **Périmés** — la stack Railway tourne depuis le 2026-07-22 |
| PR #40 et #19 « seules PR ouvertes » | **Fermées** le 2026-08-28. Aujourd'hui : **0 PR ouverte** |
| « Confirmation prod géo #91/#92 non faite » | **Faite** — 7 critères passent |
| « Le correctif currency n'est pas déployé » | **Déployé**, preuve rejouée en prod |
| Les 4 arbitrages UX6 (`buildHotelFallbackUrl`, `COUNTRY_META.UK`…) | **Tranchés et implémentés** le même jour |
| OBS7 « 2/3 juges actifs », « annoter les 3 items » | **3/3 actifs** depuis le 2026-08-25, items annotés. Reste seulement le plafond OpenAI (chantier O3) |
| OBS2 « usage compté 2× » | **Corrigé** (branche `fix/adk-call-llm-usage-doublecount`) |

---

# 1 · À faire maintenant (rien ne les bloque)

## Q1 — Réparer le test pourri par le calendrier

> ✅ **Fait** (vérifié le 2026-10-19) : `test_resolve_search_date_marks_a_carried_over_future_date_as_not_today` est relatif à l'horloge (`date.today() + timedelta(days=7)`, `agents/hotel_search_agent/tests/test_datetime_resolver.py`), et `tests/test_calendar_rot.py` garde toute la suite à +400 j (PR #114/#115). Ne pas relancer.

**Taille : S** · aucune dépendance

**Contexte.** Un test code une date en dur comme étant « dans le futur ». Cette date est
maintenant dans le passé, donc le guard de report de date la ramène correctement à aujourd'hui
et le test échoue. **Ce n'est pas une régression du produit** : c'est le test qui a pourri. C'est
la deuxième fois (PR #71 avait traité une première vague), et le motif immunisant existe déjà
dans le même fichier.

**Preuve (exécutée) :** `.venv/bin/pytest -q` → `1 failed, 1706 passed`.
`agents/hotel_search_agent/tests/test_datetime_resolver.py:762` contient `{"date": "2026-09-09"}`,
l'assertion ligne 765 attend `same_day: False`. Le motif immunisé est ligne 175 du même fichier :
`_TODAY = date(2026, 7, 23)` passé **explicitement** à la fonction.

**Actions**
1. Rendre le test indépendant du jour : soit passer une date de référence explicite comme le font
   les tests des lignes 175+, soit dériver la date du profil depuis cette référence
   (`_TODAY + timedelta(days=1)`), jamais un littéral.
2. Chercher les autres littéraux de date du même fichier et du reste de la suite — s'il en reste,
   ils pourriront au même titre.
3. Gates locaux verts, branche + MR.

**Prompt**
```
Le test agents/hotel_search_agent/tests/test_datetime_resolver.py:762
(test_resolve_search_date_marks_a_carried_over_future_date_as_not_today) échoue parce qu'il code
en dur la date "2026-09-09" comme une date future, et nous sommes après. C'est la 2e fois que ce
type de test pourrit (PR #71 a traité une première vague).

Rends-le immunisé contre le calendrier en suivant le motif déjà utilisé dans le MÊME fichier
ligne 175 (`_TODAY = date(...)` passé explicitement), plutôt qu'en déplaçant le littéral.
Puis balaye le reste de la suite à la recherche d'autres littéraux de date qui pourriront de la
même façon, et dis-moi ce que tu trouves AVANT de les corriger en masse.

Gates locaux verts (pytest -q, ruff, mypy, dayuse_guardrails.sh) puis branche + MR.
Rappel : il n'y a plus de CI, le rouge GitHub sur la PR ne veut rien dire.
```

**Terminé quand** `.venv/bin/pytest -q` affiche 0 échec, et le test passerait encore dans 6 mois.

---

## W1 — Corriger les 2 libellés de réassurance du widget (remontées QA 7 et 8)

**Taille : S** · ⚠️ **bloqué sur une décision de copy (Fabien)**

**Contexte.** Deux remontées du testeur portent sur des phrases fausses affichées sous les cartes
d'hôtel. Elles ne sont **jamais produites par l'agent** : ce sont des étiquettes statiques de
l'interface. Aucun test ne peut les attraper, et aucun n'est nécessaire — c'est une correction de
texte. Ce sont les deux remontées les moins chères de toute la liste.

**Preuve (vérifiée)** dans `web/vendor/static/js/chat/i18n.js`, **7 locales** (en, fr, es, it, pt,
de, nl) :

| Clé | Lignes | Problème remonté |
|---|---|---|
| `card_free_cancel` | 86, 194, 302, 410, 518, 626, 734 | « Free cancellation until arrival » → il s'agit du *last minute free booking*, pas d'une annulation jusqu'à l'arrivée |
| `card_price_note` | 75, 183, 291, 399, 507, 615, 723 | « for the day, taxes included » → les taxes sont incluses **à l'entrée du tunnel**, pas au moment de l'affichage |

Il existe aussi `reassurance_free_cancel` (« Free cancellation », l. 51 et suivantes) — à trancher
en même temps pour rester cohérent.

**Actions**
1. **Fabien fournit la formulation juste** pour les 2 clés (c'est le seul vrai blocage).
2. Traduire dans les 7 locales — attention, ce sont des phrases commerciales, pas de traduction
   littérale automatique.
3. Vérifier le rendu dans le widget (les guides décrivent la recette de vérification navigateur).

**Prompt**
```
Deux libellés du widget sont faux (remontées QA du 2026-09-08). Ce sont des chaînes statiques,
pas des sorties de l'agent — aucun test n'est possible ni nécessaire.

Dans web/vendor/static/js/chat/i18n.js, 7 locales (en, fr, es, it, pt, de, nl) :
- `card_free_cancel` : "Free cancellation until arrival" est faux, il s'agit du last minute
  "free booking". Nouvelle formulation : <À REMPLIR PAR FABIEN>
- `card_price_note` : "for the day, taxes included" est faux, les taxes sont incluses à l'entrée
  du tunnel, pas au moment de l'affichage du prix. Nouvelle formulation : <À REMPLIR PAR FABIEN>

Regarde aussi `reassurance_free_cancel` et dis-moi s'il doit changer pour rester cohérent.
Applique dans les 7 locales, vérifie le rendu réel dans le widget (pas seulement le diff),
gates locaux verts, branche + MR.
```

**Terminé quand** les 7 locales portent la formulation validée et le rendu est vérifié à l'écran.

---

## Q2 — Corriger les 3 documents qui enseignent du faux

**Taille : S** · aucune dépendance

**Contexte.** Trois fichiers versionnés décrivent un état dépassé. Ils ont déjà induit en erreur :
les deux guides Produit/QA ont dû les corriger au lieu de les citer. Tant qu'ils ne sont pas
corrigés à la source, chaque nouveau lecteur réapprend du faux.

**Preuve (vérifiée, encore périmés aujourd'hui)**

| Fichier | Ce qui est écrit | La réalité |
|---|---|---|
| `observability/langfuse/dashboard-b2c.json:49` | « Guard firing rate (**13 series**) » | **15 guards**, tous câblés |
| `observability/langfuse/dashboard-b2c.json:93` | « only … the **8 guards** … not wired for emission yet » | faux depuis le 2026-08-26/27 |
| `PLAN-OBS-LANGFUSE-2026-07-29.md:117` | « **2/3 judges** actifs » | **3/3** depuis le 2026-08-25 |
| `observability/langfuse/score-configs.json:146` | POI à « **>100 km** » de l'ancre | seuil abaissé à **40 km** |
| `reports/MCP-B2C-REQUESTS.md:67` | idem « more than 100 km » | idem |

⚠️ Le titre du widget vit **aussi dans l'instance Langfuse**, pas seulement dans le JSON : le
corriger dans le fichier ne change pas l'écran. Le renommer dans l'UI est le geste utile — et
**ne jamais recréer un widget via le MCP** (il naîtrait en `min_version = 2` et casserait les
3 graphiques « observations »).

**Prompt**
```
Trois documents versionnés décrivent un état dépassé et ont déjà induit en erreur :
1. observability/langfuse/dashboard-b2c.json:49 dit "Guard firing rate (13 series)" et :93 dit
   que seuls 8 guards émettent — c'est 15, tous câblés (cf. GUARD_SCORE_NAMES dans
   libs/b2c_common/b2c_common/scores.py).
2. PLAN-OBS-LANGFUSE-2026-07-29.md:117 dit "2/3 judges actifs" — c'est 3/3 depuis le 2026-08-25.
3. observability/langfuse/score-configs.json:146 et reports/MCP-B2C-REQUESTS.md:66 disent qu'un
   POI est jeté au-delà de 100 km — le seuil est à 40 km.

Corrige-les à la source. Vérifie chaque affirmation contre le code avant d'écrire (ne me crois
pas sur parole). Signale-moi si tu en trouves d'autres du même genre.

Attention : le titre du widget vit AUSSI dans l'instance Langfuse. Dis-moi ce qu'il faut y
renommer à la main — mais ne recrée jamais un widget via le serveur MCP (min_version=2 casse
les vues "observations" sur notre v3).
```

**Terminé quand** les 5 emplacements disent vrai, et le titre du widget est renommé dans l'UI.

---

## Q3 — Hygiène du dépôt

> ✅ **Fait le 2026-10-19** (branche `chore/cleanup`) : `tasks/todo.md` archivé dans `tasks/archive/todo-2026-09.md` et remplacé par un pointeur ; branches locales mergées supprimées. Ne pas relancer.

**Taille : S** · aucune dépendance

**Contexte.** `tasks/todo.md` est activement nuisible : ses cases décochées font replanifier du
travail déjà livré. 78 branches locales déjà mergées encombrent `git branch`.

**Preuve (vérifiée).** `git branch --merged origin/main` → **78 branches**.
`tasks/todo.md:567-576` liste S-G1→S-G7 comme non faits alors que les branches `sg1-profile-v2`,
`sg2-native-context`, `sg3-geo-resolver`, `sg5-bridge-pagination`, `sg6-dates-durations-minutes`,
`sg7-locale-currency` sont toutes dans la liste des mergées.

**Prompt**
```
Deux nettoyages, sans toucher au code applicatif :

1. tasks/todo.md est faux et fait replanifier du travail déjà livré (ses items S-G1→S-G9 et
   Railway sont périmés). Archive-le (par exemple tasks/archive/todo-2026-09.md) avec un en-tête
   disant qu'il n'est plus tenu à jour, et remplace-le par un pointeur vers CHANTIERS.md.
   Ne supprime rien : c'est de l'historique.

2. Supprime les branches locales déjà mergées dans origin/main (git branch --merged origin/main,
   ~78). Garde main et la branche courante. Montre-moi la liste AVANT de supprimer.

Gates locaux verts, branche + MR.
```

**Terminé quand** `git branch --merged origin/main` ne liste plus que `main`, et `tasks/todo.md`
ne peut plus tromper un lecteur.

---

# 2 · La boucle QA — transformer les remontées en tests

> **Re-planifié le 2026-09-14.** Le plan initial était un bouton « Run workflow » dans GitHub.
> Sans CI, il tombe. Le remplacement honnête est ci-dessous : **une commande unique en local**.
> Il faut le dire clairement à l'équipe — un QA sans le dépôt, sans Docker et sans `.env` ne
> sera pas autonome ; dans ce cas le fonctionnement reste « le QA écrit les cas, un dev les lance
> et renvoie le lien du passage ».

## E1 — Une seule commande pour lancer un jeu de cas

**Taille : S/M** · remplace le chantier « bouton GitHub », désormais impossible

**Contexte.** Lancer un jeu demande aujourd'hui 6 commandes dans le bon ordre (Redis, 3 services,
sourcer `.env`, semer, lancer, tout arrêter) et chacune a un mode d'échec silencieux — le pire
étant qu'**une stack éteinte ressemble à un passage à moitié réussi** (une réponse vide fait
passer au vert `message_must_not_contain_any` et `hotels_within_km`). Un script unique supprime
cette classe d'erreur.

**Actions**
1. `scripts/qa_experiment.sh <jeu> <nom-du-passage>` qui enchaîne : Redis → `run_local.sh` →
   attente de disponibilité → `langfuse_seed_datasets.py` → `python -m evals.langfuse_experiment`
   → arrêt propre, **même en cas d'échec** (`trap`).
2. **Garde-fou anti-faux-vert** : après le passage, si `min_hotels` est à 0 % sur l'ensemble du
   jeu, afficher un avertissement explicite « la stack ne répondait probablement pas » plutôt que
   de laisser lire un résultat.
3. Afficher en fin de course l'URL du passage, à coller dans un ticket.
4. Documenter la commande dans les deux guides et dans `CLAUDE.md`.

**Prompt**
```
Objectif : rendre le lancement d'un jeu de cas OBS6 faisable en UNE commande, parce qu'il n'y a
plus de CI pour le faire (facturation GitHub coupée définitivement).

Aujourd'hui il faut 6 commandes dans l'ordre : docker run redis / bash scripts/run_local.sh /
set -a; . ./.env; set +a / scripts/langfuse_seed_datasets.py / python -m evals.langfuse_experiment
--datasets X --run-name Y / run_local.sh stop. Chacune a un mode d'échec silencieux.

Écris scripts/qa_experiment.sh <jeu> <nom-du-passage> qui enchaîne tout, arrête proprement même
en cas d'échec (trap), et affiche l'URL du passage à la fin.

Ajoute un garde-fou important : si min_hotels ressort à 0 % sur tout le jeu, c'est presque
toujours que la stack ne répondait pas (une réponse vide fait passer au vert
message_must_not_contain_any et hotels_within_km). Dans ce cas, affiche un avertissement explicite
au lieu de laisser lire le résultat comme un verdict produit.

Teste-le vraiment en le lançant sur b2c/geo-poi (cela consomme de vrais appels de modèle, quelques
centimes — c'est attendu). Puis documente la commande dans observability/langfuse/guide-tests-langfuse.html
et dans CLAUDE.md. Gates locaux verts, branche + MR.
```

**Terminé quand** `bash scripts/qa_experiment.sh b2c/geo-poi essai-1` suffit, de bout en bout, et
qu'une stack éteinte produit un avertissement au lieu d'un faux vert.

---

## E2 — Marquer les tours de test (`X-Dayuse-Synthetic`)

**Taille : S** (le harnais)

> **Volet widget fait (2026-10-20, avec AM1)** : option « drapeau explicite » retenue. Ouvrir le
> widget avec `?du_synthetic=1` pose `X-Dayuse-Synthetic: 1` sur chaque appel `/v3/*` et
> `is_synthetic: true` sur chaque événement Amplitude ; sans le paramètre, le vrai chemin
> utilisateur reste non tagué. **Reste l'action 1** (le harnais `_call_facade`).

**Contexte.** Le tag `synthetic` est le **seul** mécanisme qui exclut un tour des 3 juges LLM et
de la file d'annotation. Deux producteurs de trafic de test ne le posent pas : les rejeux
d'experiment, et le widget. Conséquence : **les tours de test d'un QA sont comptés comme du
trafic réel** dans les taux du dashboard et sont notés par les juges.

**Preuve (vérifiée).** `evals/langfuse_experiment.py:104-113` — le `client.post(...)` n'a
**aucun** `headers=`. `web/vendor/static/js/chat/api.js:45-60` (`getChatHeaders`) ne le pose pas
non plus, et `grep -rn Synthetic web/ scripts/run_widget_proxy.py` → **0 occurrence**.
C'est vraisemblablement l'origine des items vides qui avaient pollué la file d'annotation.

**Actions**
1. Harnais : ajouter `headers={"X-Dayuse-Synthetic": "1"}` dans `_call_facade`. Une ligne.
2. Widget : **décision produit** — soit le proxy l'injecte derrière un drapeau, soit un mode
   « QA » explicite dans l'interface. Ne pas le poser en dur : on perdrait la capacité de tester
   le vrai chemin utilisateur.

**Prompt**
```
Le tag `synthetic` est le seul mécanisme qui exclut un tour des 3 juges LLM et de la file
d'annotation. Deux producteurs de trafic de test ne le posent pas :

1. evals/langfuse_experiment.py::_call_facade (l. 104-113) fait un client.post sans aucun
   headers= : chaque rejeu d'experiment crée une trace non taguée, éligible à l'échantillonnage
   5 % des juges. Corrige-le (une ligne) et vérifie sur une vraie trace que le tag apparaît bien.

2. Le widget navigateur ne l'envoie jamais (getChatHeaders dans
   web/vendor/static/js/chat/api.js). Là c'est une décision produit, pas un correctif : propose-moi
   2 options (injection par le proxy derrière un flag, ou mode "QA" explicite) avec leurs
   inconvénients, et n'implémente rien avant mon arbitrage — on doit garder la capacité de tester
   le vrai chemin utilisateur non tagué.

Gates locaux verts, branche + MR pour le point 1.
```

**Terminé quand** un rejeu d'experiment produit une trace portant le tag `synthetic` (vérifié sur
l'instance), et que l'option widget est tranchée.

---

## AM1 — Tracking Amplitude de l'agent (ouvert le 2026-10-20)

**Taille : S** par MR restante · décisions prises avec Ali le 2026-10-20 (session « grill »)

**Contexte.** L'agent est suivi dans Amplitude depuis le widget seul, selon le contrat figé
`contracts/amplitude_events.json` (9 événements `ai_agent__*` + `pageview`, Session Replay à 5 %).
Les faits que seul le serveur connaît arrivent par le bloc `turn_facts` de la réponse `/v3`. Les
`chat_*` d'agent-usa sont retirés, pas repris. Trois livrables, dans cet ordre : (1) la PR
AgentB2C, faite ; (2) une MR `dayuse-product-analytics` ; (3) une MR dayuse.com.

**Preuve (encore ouvert).** Au 2026-10-26, #146 et #112 sont mergées, reste !15273. MR d'origine : AgentB2C
[#146](https://github.com/Dayuse-Labs/AgentB2C/pull/146), dayuse-product-analytics
[#112](https://github.com/Dayuse-Labs/dayuse-product-analytics/pull/112) (`ai-agent.md`,
`events.yaml`, `tools/langfuse_fetch.py`), dayuse.com
[!15273](https://gitlab.com/dayuse/dayuse/dayuse-com/-/merge_requests/15273) (ticket #15883 ;
`du_entry_source` + `market_country` depuis `useDomainConfig().countryCode`, sans test commité :
`apps/frontend/web` n'a pas de lanceur de tests). Les actions 1 et 2 ci-dessous sont ces MR.

**Actions**
1. MR `dayuse-product-analytics` : `tracking/ai-agent.md` (frontmatter des nouveaux événements ;
   attribution d'un `purchase` = même `amplitude_id`, clic `ai_agent__hotel_click` ou
   `__booking_card_click` sur le même `hotel_id` dans les 7 jours ; les 4 KPI avant/après face à
   agent-usa ; `pageview` partagé avec le site, filtrer `page_type = 'ai_agent'` ;
   `agent_version` = release du widget, celle du concierge se lit dans la trace Langfuse ;
   `chat_*` retirés à la date de bascule) + `tools/langfuse_fetch.py` (API REST Langfuse, clé
   lecture seule, `trace_id` ou `conversation_id` → JSON dans le `data/` ignoré d'un bundle).
2. MR dayuse.com : les 2 bannières ajoutent `du_entry_source=banner_home|banner_search|section_home`
   et `market_country=<ISO2>` à l'URL de l'agent. Ticket séparé dans l'itération B2C.
3. Vérifications à faire par un humain : la rétention des traces Langfuse (borne de la
   réconciliation, à écrire dans `ai-agent.md`) ; un tour réel sur `ai.dayuse.{tld}` arrive dans
   le projet Production et un tour sur la démo dans Staging/Dev ; Session Replay enregistre bien
   (la config est servie par `/sr-config` du proxy, les réglages d'échantillonnage de l'UI
   Amplitude sont sans effet par décision).

**Terminé quand** les deux MR sont mergées et qu'un tour réel de chaque environnement est visible
dans son projet Amplitude avec ses `turn_facts`.

---

## MOB1 — Le widget dans l'app mobile (`window.__DAYUSE_NATIVE__`) : plan de test (ouvert le 2026-10-26)

**Taille : M** · phase A sans appareil ; phase B demande un build mobile ; phase C = Fabien sur la vraie app

**Contexte.** L'app mobile (dayuse-com, `apps/frontend/mobile/src/screens/aiAssistant/`) ouvre
`https://ai.dayuse.com/?source=mobile_app&locale=<lang>&currency=<cur>` dans une WebView. Elle injecte
`window.__DAYUSE_NATIVE__ = {amp_device_id, amp_session_id, favoriteHotelIds, geolocation{lat,lon},
lastBookings[≤3]{hotelName, hotelCity, price, timeslot}}` **avant** les scripts de la page
(`aiAssistantBridge.ts::buildContextScript`), puis `NAVIGATION_BRIDGE_SCRIPT` après chargement : il
détourne `window.open` et les `<a target="_blank">` vers `ReactNativeWebView.postMessage({type:
'navigate', url})`, que l'app route par `resolveDayuseUrl`. Depuis la bascule d'ai.dayuse.com, c'est
le widget AgentB2C qui est chargé : `utils.js::getNativeContext` lit le global, `state.js` /
`index.js` passent en mode `mobile_app` (chat ouvert d'emblée), `tracking.js` relie l'identité
Amplitude, et `send.js` envoie le bloc en `native_context` dans le corps `/v3`. Le concierge le
traite en **bloc opaque** (`facade.py`, commentaire « native context intake » : le schéma n'était
pas connu en juillet) — il l'est désormais, dans `aiAssistantBridge.ts`.

**Preuve (encore ouvert).** Rien n'a été vérifié dans une WebView ni contre le script de pont réel
(AM1 action 3 : « faire confirmer par l'équipe mobile que `__DAYUSE_NATIVE__` est injecté au début du
document ») ; `facade.py` dit « Open item for whenever the mobile schema is specified ».

**Actions**
- **Phase A — simulation fidèle dans Chrome headless (CDP), sur la démo** (`https://widget-production-3f56.up.railway.app`,
  clé Amplitude de dev ; recette CDP : mémoire `reference-widget-browser-verification-cdp`). Lire
  `aiAssistantBridge.ts` et `AIAssistantScreen.tsx` sur la **branche par défaut** de dayuse-com (le
  clone local peut être sur une autre branche : `git fetch` puis `git show origin/<défaut>:<chemin>`).
  Viewport + user-agent iPhone, `window.ReactNativeWebView.postMessage` bouchonné pour capturer.
  1. **Ouverture** : contexte injecté par `Page.addScriptToEvaluateOnNewDocument` (= `injectedJavaScriptBeforeContentLoaded`),
     URL de l'app. Attendu : chat ouvert sans le hero, langue/devise de l'URL, `entry_source` /
     `tracking_surface` = `mobile_app`. Refaire avec une injection **tardive** (après chargement) :
     le widget se dit robuste à ce cas (`index.js`, `tracking.js`).
  2. **Identité Amplitude** : `amplitude.track` et `navigator.sendBeacon` bouchonnés ; `device_id` /
     `session_id` = ceux injectés.
  3. **Pont de navigation** : injecter `NAVIGATION_BRIDGE_SCRIPT` **tel quel** (copié du fichier), faire
     un tour de recherche, puis cliquer chaque sortie : lien de carte (`card.js` `target=_blank`),
     bouton `window.open` (`card.js`, `messages.js`), CTA de la carte de réservation, « Voir tout »
     (`carousel.js`). Attendu : **un** `{type:'navigate'}` par clic, et chaque URL acceptée par
     `resolveDayuseUrl` (exécuter sa logique ou ses tests `resolveDayuseUrl.test.ts` sur ces URLs).
  4. **`native_context` côté serveur** : le capturer dans le corps `/v3` (Network), vérifier que le tour
     réussit, et **RGPD** : `lastBookings` (noms d'hôtels, prix) et `geolocation` ne doivent apparaître
     ni dans les logs, ni dans `turn_facts`, ni dans la trace Langfuse du tour (lire la trace par l'API).
  5. **Parité avec agent-usa** : ce qu'agent-usa faisait de `native_context` (grep ciblé dans
     `../agent-usa/src`, jamais tout le repo). S'il exploitait géoloc, favoris ou réservations, c'est
     une régression de la bascule à lister.
  Tours synthétiques (`x-dayuse-synthetic: 1` par wrapper `fetch`, pas `?du_synthetic=1` qui coupe
  Session Replay), 3 à 4 tours au total.
- **Phase B — vraie WebView (option)** : simulateur iOS avec un build de dev de l'app dont
  `AI_ASSISTANT_BASE_URL` pointe sur la démo (modification locale, jamais commitée). Rejoue 1 et 3.
- **Phase C — après la bascule DNS, Fabien** : ouvrir l'assistant dans l'app de prod, connecté
  (réservations) puis déconnecté ; un tour, un clic sur un hôtel, retour à la conversation.

**Prompt**
```
Lis CLAUDE.md, puis CHANTIERS.md § MOB1 en entier : c'est ton plan. Exécute la phase A
(cas 1 à 5) dans l'ordre, sans modifier de code. Pour chaque cas : attendu, observé, preuve
(sortie, capture ou extrait de trace). Tours synthétiques uniquement, 4 au plus.
À la fin : tableau des cas OK/KO, liste des écarts (régressions vs agent-usa, fuites RGPD,
URLs refusées par resolveDayuseUrl), et pour chaque écart une proposition de correctif
chiffrée — sans l'implémenter. Consigne le résultat en tête de HANDOFF.md sur une branche
docs/mob1-<date> et ouvre la PR. Réponds en français.
```

**Terminé quand** les cas 1 à 5 sont prouvés dans la simulation, les écarts sont listés avec leur
correctif proposé, et Fabien a validé la phase C dans l'app de prod.

---

## E3 — Une vérification sur l'URL du lien hôtel (remontée QA n°4)

**Taille : S/M** · débloque une remontée aujourd'hui non testable

**Contexte.** Le testeur signale qu'une date sélectionnée ne s'applique pas sur la page hôtel. La
date voyage dans les paramètres de l'URL générée — or **aucune des 18 vérifications ne regarde
une URL**. La remontée est donc non testable en l'état.

**Preuve (vérifiée).** `evals/langfuse_evaluators.py` : 14 vérifications « réponse » qui lisent
`hotels` / `active_filters` / `message` / `requires_clarification`, 4 « trace » qui lisent les
arguments MCP. `grep -c "booking_url\|hotel_url"` → **0**.

⚠️ **La seconde moitié du problème est hors périmètre** : « la page dayuse.com applique-t-elle la
date reçue ? » ne sera jamais testable par ce harnais.

**Prompt**
```
Remontée QA : une date sélectionnée ne s'applique pas sur la page hôtel. La date voyage dans les
paramètres de l'URL générée, mais aucune de nos 18 vérifications ne regarde une URL
(evals/langfuse_evaluators.py : 0 occurrence de booking_url/hotel_url).

Ajoute une vérification au niveau réponse, dans le style des 14 existantes — par exemple
`hotel_url_must_include: {"date": ...}` ou une forme plus générale si tu la juges meilleure
(propose avant d'écrire). Contraintes :
- même convention que les autres : une clé absente d'expected_output ne produit aucun score, et
  une donnée indisponible produit un "skipped" CATEGORICAL, jamais un faux succès ;
- un test unitaire offline pour chaque branche (succès, échec, skip), comme
  evals/tests/test_langfuse_evaluators.py le fait déjà ;
- documente la nouvelle clé dans observability/langfuse/guide-tests-langfuse.html (section 4,
  le tableau des vérifications) — sinon personne ne saura qu'elle existe.

Note : « la page dayuse.com applique-t-elle la date » est hors de notre système et le restera.
Gates locaux verts, branche + MR.
```

**Terminé quand** un cas peut affirmer qu'un paramètre est présent dans l'URL d'une carte, et que
la clé est documentée dans le tutoriel.

---

## E4 — Ouvrir un jeu `b2c/qa-reports` et y verser les 3 cas déjà écrits

**Taille : S** · dépend de rien (mais plus utile après E1)

**Contexte.** Le tutoriel livre 3 cas prêts à copier, écrits depuis les remontées 1, 2 et 5 et
**déjà validés** contre le vrai validateur du dépôt. Ils n'ont pas de jeu où atterrir : la
correspondance fichier → jeu Langfuse est codée en dur, donc créer un jeu demande une ligne de dev.

**Preuve (vérifiée).** `scripts/langfuse_seed_datasets.py:33-37` (`DATASET_NAMES`) ;
`grep -rln "currency\|euro" evals/datasets/` → **0 fichier**.

**Prompt**
```
Ouvre un 5e jeu de cas `b2c/qa-reports` pour les remontées des testeurs :
1. une ligne dans DATASET_NAMES (scripts/langfuse_seed_datasets.py:33-37) + le fichier
   evals/datasets/b2c-qa-reports.jsonl ;
2. verse-y les 3 cas écrits dans observability/langfuse/guide-tests-langfuse.html (section 5,
   cas A, B et C) — ils sont déjà validés contre load_items() et n'utilisent que des clés
   reconnues ;
3. sème et lance un passage pour établir la baseline : les cas A et B sont `target` (ils doivent
   échouer aujourd'hui, c'est leur rôle), le cas C est `regression_guard` (il doit passer).
   Dis-moi si la réalité diffère de cette attente — ce serait une information en soi.

Rappel : un id = un cas figé, on n'édite jamais un cas existant. Gates locaux verts, branche + MR.
```

**Terminé quand** le jeu existe, contient les 3 cas, et un premier passage a établi la baseline.

---

## E5 — Décider ce que devient le seuil de qualité, sans CI

**Taille : S** · ⚠️ **décision produit**

**Contexte.** Le seuil `assert rate >= 0.60` est écrit puis mis en commentaire, et le job est
`continue-on-error: true` — choix assumé « on pose la mesure avant le seuil ». **Sans CI, la
question change** : un seuil automatique n'a plus d'exécuteur. Il faut décider si la mesure
devient un rituel humain avant merge, ou si on l'abandonne jusqu'au retour d'une CI.

**Preuve (vérifiée).** `evals/tests/test_langfuse_experiment_gate.py:56` (`# assert rate >= 0.60`),
`.github/workflows/ci.yml:50` et `:89` (`continue-on-error: true`).

**Question à trancher :** lance-t-on un passage avant chaque MR qui touche l'agent (et qui le
fait), ou accepte-t-on de ne mesurer qu'au coup par coup ?

---

# 2 bis · M1 — Sortir de gpt-4o-mini (ouvert le 2026-10-19)

**Taille : M** · ⏰ **2027-01-14** · **bloqué par : Fabien** (OK Langfuse, bascule Railway)

**Contexte.** OpenAI arrête gpt-4o-mini le 2027-01-14. Les feuilles sont passées à
`openai/gpt-6-luna` (#139).

**Fait** (PR du 2026-10-19, branche `chore/off-gpt-4o-mini`) :
- **Effort de raisonnement par rôle.** Le triage et le juge sont fixés à `none`, et le `low` de la
  démo ne les atteint plus. Avant ce correctif, poser la seule variable Railway aurait tronqué 2
  triages luna sur 20.
- **Triage `max_retries=0`.** Le SDK OpenAI relançait les timeouts : jusqu'à 16,4 s mesurées en prod
  pour un budget annoncé de 5 s.
- **Juge du gate.** Il passe sur luna, via `llm_params`, et ne suit plus `DAYUSE_MODEL`. Les erreurs
  du juge et les tours dégradés sont comptés, et `--update-baseline` refuse de les enregistrer.
  `baselines.json` **n'est pas refait** : MCP_B2C staging était injoignable depuis l'IP de sortie du
  soir (voir Reste).
- **Instrument de triage** `scripts/measure_triage_models.py`, avec sa fixture figée.

**Preuves** : `reports/TRIAGE-GPT6-AB-2026-10.md` et `reports/JUDGE-GPT6-DRIFT-2026-10.md`.

**Fait le 2026-10-26** : #157 (partie 1) mergée et déployée sur le `concierge` (`54c6a09`), triage
encore sur gpt-4o-mini. Branche `feat/triage-gpt-6-luna` (partie 2) : le prompt de triage resserré
en 2 itérations mesurées. luna tient la barre, voir `reports/TRIAGE-GPT6-AB-2026-10.md` §5.
**Décision de Fabien** : luna accepté, bascule **atomique**. mini régresse avec le nouveau prompt
(clés omises, donc renvoyées aux regex) ; il ne doit donc jamais tourner avec ce code.

**Reste.**
1. ~~**Rejeu live**~~ **fait le 2026-10-27** (rapport §6) : 2 bras le même jour, mini 91,1 % contre
   luna 91,0 %. Les 5 écarts d'un item sont expliqués et ne tiennent pas au triage, et les 4 cas
   sont tranchés. Verdict : bascule.
2. **Bascule triage (humaine), atomique** :
   - merger la partie 2, déployer `concierge` depuis un worktree propre de main ;
   - poser `DAYUSE_MODEL_TRIAGE=openai/gpt-6-luna` avec `--skip-deploys` **avant** `railway up`. La
     **poser, jamais la supprimer** : le concierge porte `DAYUSE_MODEL=gpt-5.2`, sur lequel
     retomberait le triage ;
   - **retour arrière = variable ET code ensemble** : l'estampille et le déploiement précédents,
     plus `DAYUSE_MODEL_TRIAGE=gpt-4o-mini`. Le nouveau prompt sur mini renvoie 3 champs aux regex.
3. **Évaluateurs Langfuse** (Hallucination, Relevance, User Distress (no history)).
   - La dérive mesurée est faible, la barre est tenue. Relevance baisse de 0,09 en moyenne sur les
     relances courtes : noter la date du changement de juge.
   - gpt-6-luna exige `max_completion_tokens` (pas `max_tokens`) et `reasoning_effort: "none"`.
     Ces réglages se font dans l'UI de chaque évaluateur, pas par le MCP.
   - Ensuite : relire les règles, faire un contrôle live sur une règle temporaire à 100 %, puis
     mettre à jour `observability/langfuse/evaluators.json`.
   - **Repli** : couper les 3 règles jusqu'à la v4. Elles ont produit 3 scores depuis le 09/09.
4. **Baseline du gate à refaire avec le juge luna.** Elle doit tourner depuis un réseau qui joint
   MCP_B2C staging (IP `45.156.191.77`).
   - Montage : celui de la démo après bascule, `DAYUSE_MODEL_SYNTHESIS=gpt-5.2`, le reste sur
     luna (défaut du code), une seule fois.
   - Commande : `run_release_gate.py --update-baseline`.
   - L'effet du seul juge est déjà chiffré (`reports/JUDGE-GPT6-DRIFT-2026-10.md`) : pas de
     re-jugement sur mini.
   - Le premier essai, le 2026-10-19 : 112 tours dégradés sur 118, 0/32, refusé et non commité.
   - Ne lancer aucune autre suite pytest en même temps depuis la même IP : jusqu'à #156, une suite
     coûtait 52 requêtes MCP. Le limiteur de staging est à 300 req/min par IP, compté avant l'auth.
5. **agent-usa (repo voisin, prod client), hors périmètre ici** : `src/api/config.py:92` met
   gpt-4o-mini par défaut (`OPENAI_MODEL`), et `openai_adapter.py:57` ne détecte les modèles de
   raisonnement que par `startswith("gpt-5")` : c'est le même piège gpt-6. Seule la variable
   **déployée** dit si l'arrêt le touche ; la revue du 2026-07-22 l'a fait tourner sur gpt-5.2. À
   vérifier côté plateforme, puis à porter par son équipe.
6. Non bloquant : `cost_usd` vaut `None` sur luna, parce que litellm 1.90.2 n'a pas son prix.
   `DAYUSE_MODEL_PRICES` enregistre sous `openrouter` : à vérifier pour `openai/gpt-6-luna`.

**Terminé quand** plus aucun appel de prod ni d'éval ne part sur gpt-4o-mini. À vérifier par une
requête `/api/public/metrics` (`providedModelName=gpt-4o-mini`, 0 depuis la bascule) et par
`grep -rn 4o-mini` sur la config.

---

# 3 · Observabilité — l'échéance Langfuse v3 (fin janvier 2027)

> **Fin janvier 2027 : Langfuse v3 n'est plus patché en sécurité.** Il reste ~4 mois.
> La chaîne est : **O1 (lever le risque) → O2 (ClickHouse) → O4 (migration v4)**. O2 est un
> prérequis dur de O4. Commencer par O1, qui peut invalider tout le plan.

## O1 — Lever le risque bloquant avant de planifier v4

**Taille : S** · ⚠️ **à faire en premier de la chaîne**

**Contexte.** `POST /api/public/ingestion` est marqué « unsupported » en v4. **C'est l'endpoint sur
lequel repose tout OBS3** (les 15 guards, les scores de tour, le TTFT). Si la bascule v4 le
supprime réellement, une grande partie de l'observabilité doit être réécrite — et ça change
l'ampleur d'OBS9. Le découvrir en janvier serait très coûteux.

**Preuve :** `PLAN-OBS-LANGFUSE-2026-07-29.md:154-157` (Q5). **Documentaire** — non testé.

**Prompt**
```
Avant de planifier la migration Langfuse v4 (échéance dure : fin janvier 2027, fin des patchs
sécurité v3), il faut lever un risque identifié mais jamais testé, noté Q5 dans
PLAN-OBS-LANGFUSE-2026-07-29.md:154-157 : POST /api/public/ingestion est marqué "unsupported" en
v4, or TOUT OBS3 repose dessus (les 15 scores guard_*, hotels_returned, empty_shortlist,
llm_calls, ttft_ms).

Recherche dans la documentation Langfuse v4 (serveur MCP langfuse-docs) ce qui remplace cet
endpoint, et ce que "unsupported" signifie exactement : supprimé, déprécié mais fonctionnel, ou
remplacé par un autre chemin. Puis dis-moi précisément ce que la migration impliquerait pour
libs/b2c_common/b2c_common/scores.py.

Ne migre rien. Je veux une note de risque : impact, ampleur, et si ça change l'ordre OBS8 → OBS9.
```

**Terminé quand** on sait si OBS9 est une migration d'infrastructure ou aussi une réécriture des
scores.

## O2 — OBS8 : ClickHouse 24.10 → 25.12.11.4

**Taille : L** · ⚠️ **Fabien doit poser une fenêtre**

**Contexte.** GO écrit le 2026-08-24, **rien n'a encore été muté sur Railway**. 13 mois d'écart de
version, au-delà de la fenêtre de compatibilité officielle : **porte à sens unique**, d'où le
besoin d'un créneau calme et d'une sauvegarde. Motivation **fonctionnelle** (débloquer v4), pas
sécuritaire — 25.12 n'est plus patché non plus, et c'est assumé par écrit.

**Preuve :** `phases/OBS8-clickhouse-upgrade.md:10-13` « exécution volontairement différée. Rien
n'a encore été muté sur Railway. » Le runbook est déjà écrit dans ce fichier.

**Prompt**
```
Exécuter OBS8 : montée ClickHouse 24.10 → 25.12.11.4 sur l'instance Langfuse self-hosted.
Le runbook est déjà écrit dans phases/OBS8-clickhouse-upgrade.md, le GO date du 2026-08-24 et
rien n'a encore été muté.

Avant de toucher quoi que ce soit :
1. relis le runbook et dis-moi s'il est encore valide (versions, étapes, points de non-retour) ;
2. confirme la sauvegarde et le plan de retour arrière — c'est une porte à sens unique, 13 mois
   d'écart de version ;
3. vérifie que la fenêtre est bien calme (trafic prod quasi nul ces jours-ci, c'est plutôt
   favorable).
Puis déroule étape par étape en me montrant chaque résultat. Ne pas enchaîner sans validation.
```

## O3 — Poser le plafond de dépense OpenAI

**Taille : S** · **Fabien, console OpenAI** — hors dépôt

Coût mesuré des juges : **$8,22e-5 par appel**, soit ~$0,12/mois. Le plafond est un coussin, pas
une urgence — mais il n'existe pas. **Deux pièges** : un « Monthly spend limit » seul n'est qu'une
*alerte*, il faut activer **« Enforce a hard limit »** ; et il faut viser le niveau **projet**, pas
l'organisation — un plafond dur au niveau org couperait le produit, pas seulement les juges.
Chemin : `platform.openai.com/settings/organization/limits` → *Spend*, puis Settings → le projet
→ *Limits*.

## O4 — OBS9 : migration Langfuse v4

**Taille : L** · dépend de O1 et O2 · **échéance fin janvier 2027**

Jamais démarrée. 3 étapes prévues (serveur v4 en legacy/dual-write → SDK/API/evaluators → bascule
`events_only`). À planifier une fois O1 répondu et O2 exécutée.

Prompt de lancement (repris de l'ancien `PROMPTS-OBS-LANGFUSE.md`, retiré au nettoyage du 2026-10-19 ; la v4 est GA depuis le 2026-08-17, l'étape 0 reste à rejouer) :

```
Lis CLAUDE.md, HANDOFF.md, OBS2-LANGFUSE-BRIEF.md (§12), PLAN-OBS-LANGFUSE-2026-07-29.md.
ÉTAPE 0 obligatoire : vérifie que la v4 self-hosted est publiée en STABLE (tags Docker : un 4.x.y
sans suffixe -rc, et où pointe `latest`). Si ce n'est pas le cas, STOP immédiat et rapport.
Ensuite, écris phases/OBS9-migration-v4.md et soumets-le moi. Points obligatoires du plan : ClickHouse
≥ 25.12 déjà fait (OBS8) ; séquence legacy → dual → cutover events_only ; le backfill historique ne
tourne QU'UNE FOIS (tout ce qui est ingéré avant l'activation du dual write est définitivement absent
des nouvelles tables) ; si une politique de rétention globale existe, sauter le backfill (option B)
évite la contrainte de 3× le disque ClickHouse ; TEST PRÉALABLE de create_score via
POST /api/public/ingestion (question Q5 — tout OBS3 en dépend) ; passage des lectures métriques v1 → v2
dans le module unique ; le cutover events_only est le point de non-retour.
Règle absolue : aucune action sur l'instance sans mon GO écrit, étape par étape.
```

## O5 — Deux variables d'env sur le service MCP (OBS10)

**Taille : S** · **hors dépôt** (service MCP_B2C)

`OTEL_SERVICE_NAME=mcp-b2c` et `LANGFUSE_TRACING_ENVIRONMENT=production`. Sans elles, les spans
de l'inventaire sont mal étiquetés — c'est ce qui fait qu'un tour de développement affiche ses
3 spans en `production`.

## O6 — Le widget `degraded` manquant sur le dashboard

**Taille : S**

Le score `degraded` existe et est renseigné (4 occurrences, toutes `leaf_call_failed`), mais
aucune vignette ne le suit. **À créer dans l'interface**, jamais via le serveur MCP (il naîtrait
en `min_version = 2` et casserait les vues « observations » sur notre v3).

---

# 4 · Décisions produit en attente (rien n'avance sans toi)

| # | Sujet | La question exacte à trancher |
|---|---|---|
| **P1** | Remontée QA n°1 | La divulgation S-CX6 (« ces offres sont pour demain, pas pour aujourd'hui ») est **volontaire** — le testeur l'a lue comme une contradiction. Quelle formulation ? Le mécanisme est dans `agents/b2c_concierge/b2c_concierge/ground_truth.py::_DATE_FALLBACK_NOTE`. Une fois tranché, un test la verrouille. Depuis le 2026-10-20, la première recherche sans jour demande la date : la bascule vers demain n'arrive plus que si l'utilisateur choisit « aujourd'hui » (ou répond sans jour) après l'heure limite. |
| **P2** | Remontée QA n°3 | Doit-on pouvoir sélectionner un hôtel et entrer dans le tunnel depuis l'agent ? Et que se passe-t-il si l'utilisateur veut payer en ligne ? **Aucun test possible avant l'arbitrage.** |
| **P3** | Remontée QA n°6 | Les Booking Fees ne sont pas respectées à l'affichage. Prix venu de MCP_B2C + config back-office par hôtel → à router vers l'équipe inventaire, ce n'est pas un chantier agent. |
| **P4** | `response_language` | Le triage ne lit que `language`, jamais `profile.language` (`agents/b2c_concierge/b2c_concierge/triage.py:199-216`). ⚠️ **Le symptôme aurait changé depuis UX2** : un « sí » isolé dans une conversation française répondrait maintenant **en espagnol** (avant : en anglais). **À re-tester avant de décider** — c'est une ligne, mais elle change un comportement de réponse. |
| **P5** | Edge public du concierge | ✅ **Fait le 2026-10-26** : `concierge-production-aaa2.up.railway.app` supprimé avant la bascule d'ai.dayuse.com (compensation de la prolongation D7, voir A1) ; il répond désormais 404 « Application not found », le widget sert toujours les tours par le réseau privé. La cause du 502 était `IPV6_V6ONLY` forcé par asyncio. |
| **P6** | Seuil de qualité sans CI | cf. **E5** ci-dessus. |

---

# 5 · Dette d'architecture

## A1 — Identité intérimaire D7 → oidc-mtls

**Taille : L** · **bloqué sur le repo fleet (`dayuse_agent_common`)**

**Contexte.** Les 3 services tournent sur des **bearers statiques** et des **Agent Cards non
signées**. C'est une exception documentée avec échéance : **au plus tard avant le canary S11**.
Le provider cible est un stub.

**Preuve (vérifiée) :** `libs/b2c_common/b2c_common/auth.py:4-8` — « its oidc-mtls provider is a
**NotImplementedError stub** ». Rappelé dans les 3 README de services et dans `CLAUDE.md:15`.

**Décision (Fabien, 2026-10-26) : exception prolongée jusqu'au 2027-01-31.** L'échéance d'origine
était « avant le canary S11 » ; la bascule franche d'ai.dayuse.com amène du trafic réel sans
canary, donc elle tombait. Bloquer la bascule jusqu'à oidc-mtls était irréaliste (taille L, autre
repo, pas de date) ; prolonger sans date aurait fait de l'exception un trou permanent.
Compensations :
- **P5 avant la bascule** : le domaine public du concierge est supprimé, le widget reste la seule
  surface publique du projet.
- **Rotation des bearers, semaine du 2026-11-02.** Prérequis : `BearerAuthMiddleware`
  (`libs/b2c_common/b2c_common/auth.py`) ne compare qu'**un** jeton ; sans un second jeton
  accepté pendant la transition, la rotation ouvre une fenêtre de 401 (cf. 2026-08-24).

## A2 — S10 (shadow-run) et S11 (canary) n'ont jamais eu lieu

**Taille : L** · **bloqué : accès ES prod lecture seule, contrôle plateforme de `DAYUSE_MODEL`**

Planifiées dans `SESSIONS-CLAUDE-CODE.md:27-28`, aucune n'a de bloc de clôture dans `HANDOFF.md`.
Le déploiement Railway existant est une **démo**, pas le canary du plan. Prérequis explicite :
validation de Fabien avant tout trafic.

## A3 — Deux angles morts de persistance

`conversation_logs` (l'export RGPD) n'a **jamais été exercé** en écriture : pas de `DATABASE_URL`
en dev/CI, donc no-op silencieux. Et `InMemorySessionService` perd l'historique d'événements ADK
au redémarrage du process (le profil Redis, lui, survit). À traiter avec S10/S11.

---

# 6 · Backlog produit / géo

| # | Sujet | Note |
|---|---|---|
| G1 | Recherche « les moins chers » sans shortlist | Trier par prix avant la coupe top-5, avec formulation honnête. `size` : re-sonder en direct (falaise à 16). |
| G2 | Guard prix | Un superlatif de prix dans la synthèse n'est vérifié contre rien. Aucun des 15 guards ne couvre le prix. |
| G3 | `city=Lyon` + `zone=gare de lyon` → « La Garde, Lyon » | Le ranking se fait sur le **libellé** ; le guard #14 est aveugle car la distance est bonne. |
| G4 | `disneyland-paris` à 30,6 km | **Délibérément non fait** (surapprentissage sur 1 cas / 18). À reprendre avec un dataset plus large. Pas une régression. |
| G5 | 2 poids géo non recalibrés | `_W_LANDMARK_CITY_ANCHOR` (2,5) et `_LANDMARK_ANCHOR_ZERO_KM` (40) pèsent désormais sur bien plus de tours. |
| G6 | Repli en dur `dayuse.com/s/united-states` | `web/vendor/static/js/chat/handlers/responses.js:300`, 4 appelants. Assumé (CTA d'état vide), mais c'est un lien en dur. |
| G7 | Phrase maladroite sur rétraction de filtre | La synthèse décrit l'ancienne sélection au lieu de dire « c'est reparti sans le spa ». Devait suivre UX2, ne l'a pas fait. |
| G8 | UX2 — reste hors périmètre | Japonais/arabe/thaï (chantier RTL), `evalset`/`dayuse_eval_pack` par langue, précision du classify cross-lingual jamais mesurée. |
| G9 | Marché BH (`bh.dayuse.com`) | 26ᵉ marché candidat, jamais sondé pour l'inventaire. |
| G10 | Variance de `_lookup_trace_facts` | Un miss dégrade en `skipped` silencieux. Backoff plus long ou échec explicite. |
| G11 | Cas `lang-confirm-implicit` impassable | `pending_booking.hotel_id = 123` fabriqué → aucun lien possible, plafond 6/7 définitif. Le re-semer avec un vrai id, ou l'acter. |
| G12 | `booking_url_fallback` illisible | Le proxy jette le corps (`scripts/run_widget_proxy.py:133-135`). ~10 lignes pour logger `event` + `reason` (liste blanche, jamais le payload). |

---

# 6 bis · Leaf de compréhension géo — série S-L (ajouté le 2026-10-08)

## L — Le lieu est compris par le LLM de la feuille, le code vérifie les faits

**Taille : L** · **séquence revue par QA14707 (DQ1, 2026-10-14)** · bloqué par : MCP `main` déployé pour S-L1

**Contexte.** La compréhension du lieu reposait sur le prompt de la feuille et sur des règles de langage en code (regex de prépositions, mots génériques, état lu dans le texte, exceptions écrites dans le prompt) : chaque incident ajoutait une condition. Décision du 2026-10-08 : un `GeoIntent` fermé, sans coordonnées ; le code garde la vérification des faits. **Décision DQ1 du 2026-10-14 : ce `GeoIntent` est produit par la feuille de recherche existante, comme argument structuré de `geocode_location`** (contrat v1.1, `libs/b2c_common/b2c_common/geo_intent.py`), sans leaf dédiée ni 4e appel au modèle. Plan : `reports/PLAN-LEAF-GEO-2026-10-08.md` (§3 à jour) ; sessions : `SESSIONS-CLAUDE-CODE.md` § S-L ; exécution : `plans/qa14707/`.

**Fait (QA14707).** S-L2 (contrat) = Q06 ; mapping côté feuille de S-L5 = Q07 et Q08 ; retraits S-L7a (regex de prépositions, articles, sondes ; Q09) et S-L7f (`select_us_postal_anchor` ; Q10, DQ7). S-L7b et S-L7c ne sont pas des retraits : la règle S5 est devenue `ambiguity.reason = city_needed` (DQ6) et la règle « nom complet » est le champ `canonical`.

**Reste.**
- **S-L3 et S-L4 sont conditionnelles** : une leaf dédiée (mode ombre, `GEO_LEAF_MODE`) ne se justifie que si les rejeux H3 montrent que gpt-6-luna ne tient pas le schéma dans la feuille (taux de `valid=0` sur les lignes `dayuse_metric=geo_intent`). Elles ne changeraient alors que l'endroit où l'objet est produit. D-1 (budget d'appels) tombe : le plafond reste 3.
- **S-L1** (#124 réconciliée avec le MCP, `sortBy`) et **S-L6** (périmètre hybride) sont inchangées ; S-L8 (déploiement d'une leaf) sans objet tant que S-L3 n'est pas faite.
- **Règles S-L7 encore en place** : S-L7d (mots génériques, `_GENERIC_LOCATION_WORDS` / `demote_generic_city`, `geo_guards.py`) et S-L7e (État américain lu dans le texte, `extract_state_hint_from_text` / `resolve_state_hint`, `geo_guards.py`). S-L7b et S-L7c sont transformées, pas à retirer. S-L7a et S-L7f sont retirées.
- `relation`, `carryover` et `exclusions` du `GeoIntent` sont lus mais non appliqués (S-L5 complète).

**Preuve (vérifiée le 2026-10-16).** `git grep -n "_city_named_in_message\|select_us_postal_anchor" -- agents libs` ne renvoie rien ; `grep -n "_GENERIC_LOCATION_WORDS\|def extract_state_hint_from_text" agents/hotel_search_agent/hotel_search_agent/geo_guards.py` renvoie les deux règles restantes ; `agents/b2c_concierge/b2c_concierge/budget.py:18` (`MAX_LLM_CALLS_PER_TURN = 3`).

**Prompt.** Celui de `phases/SL1-pr124-contrat-mcp.md` pour S-L1 ; `phases/SL7-retraits-regles-langage.md` (bandeau QA14707 en tête) pour S-L7d et S-L7e.

**Terminé quand.** Jeux géo sans régression par rapport à la référence H1, règles S-L7d et S-L7e retirées (S-L3/S-L4 seulement si H3 l'exige).

---

## QA14707 — Retours QA de Raphael du 14/10 (dayuse-com#14707)

**Taille : L** · **bloqué par : Fabien** (H3' live, puis H4 retest) · plan : `plans/qa14707/`, source : `phases/QA14707/`

**Contexte.** Trois remontées : un créneau de carte dans la langue de la conversation ; une ville, une adresse ou un code postal écrits dans le message ne déclenchent jamais une question de ville ; quand une question est légitime, une seule réponse relance la recherche avec la date et le créneau d'origine, sans jamais reposer la même question ni inventer d'option.

**Fait.**
- Phases 1-3, déployées le 2026-10-16 (release `0b65159`, #140) : créneau localisé (`web/vendor/static/js/chat/slot_time.js`), `GeoIntent` dans la feuille, `Clarification` rendue par gabarit sans synthèse (`agents/b2c_concierge/tests/test_clarification_template.py`), routage de la réponse avant la réservation, adresses et codes postaux, correctifs H3 (Q14-Q26). H3 rejoué sur gpt-6-luna : réussi (`plans/qa14707/PREREQUISITES.md`).
- Phases 4-5, sur `plan/qa14707`, seconde PR : retraits S-L7a et S-L7f (Q09, Q10), plus de regex ni de liste de mots pour la question attendue et le oui/non (Q11, Q27 : `leaf_question` dans `agents/b2c_concierge/b2c_concierge/profile.py`), anti-boucle des questions libres lu sur l'état (Q28 : `agents/b2c_concierge/tests/test_free_question_anti_loop.py`), item live `qa14707-near-11580-en` (Q29), documentation (Q12). Détail et preuves : bloc daté du 2026-10-16 de `HANDOFF.md`.

**Reste.**
- La seconde PR (`plan/qa14707` → `main`) : Q13, la revue globale, est faite (29/29 tâches) ; reste à l'ouvrir et à la revoir.
- H3' live (liste des items 3/3 et des taux à lire sur les lignes `geo_intent` dans le bloc daté de `HANDOFF.md`) ; H4 : déploiement final, retest par Raphael, réponse point par point sur dayuse-com#14707.
- Tickets : aligner `geo-poi-gare-de-lyon` sur S5 et `geo7-gare-du-nord-no-city` sur DQ12 ; mesurer « je confirme » avec une offre en attente ; demander à Raphael l'URL et le marché testés ; sortie de gpt-4o-mini : voir `M1`.
- Le port de #134 (famille géo) doit respecter le modèle d'état de session décrit dans le bloc daté de `HANDOFF.md` (`pending_clarification`, `pending_search.asked`, `region_anchor`, `entry_market_country`).

**Terminé quand.** Raphael retest sans retrouver les trois remontées, et H3' à la barre indiquée dans `HANDOFF.md`.

---

# 7 · Bloqué chez MCP_B2C — à relancer

| # | Demande | État |
|---|---|---|
| X1 | **`resolve_location`** — géocodeur POI sur leur index `poi` | **Ouverte.** C'est le **fix structurel géo** : tout ce qui est livré côté client compense le biais IP de Mapbox Search Box. |
| X2 | **`hotelPrice`** — prix en devise réelle de l'hôtel | Demande **écrite** (`reports/PROMPT-MCP-B2C-DEVISE-LOCALE-2026-08-27.md`) mais **jamais portée** dans une session sur leur repo. Sans elle, l'affichage en devise locale est impossible (pas de FX côté AgentB2C sur un prix de réservation). **C'est la remontée QA n°5.** |
| X3 | **`search_offers`** — `startMinute`/`endMinute` | **Ouverte.** Intérim livré (post-filtre exact + repli honnête). |

---

## Ce que je n'ai pas pu vérifier

Par honnêteté, ces points reposent sur la documentation seule : l'état réel de Railway (quels
commits tournent, si le domaine public du concierge a été supprimé), l'état du repo MCP_B2C
(O5, X1-X3), si le plafond OpenAI a été posé depuis, et la progression de la calibration des
juges depuis le 2026-08-25.
