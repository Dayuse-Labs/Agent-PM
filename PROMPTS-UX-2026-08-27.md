# Prompts de lancement — chantiers UX1-UX6 (liste Fabien du 2026-08-27)

> Mode d'emploi : ouvrir une session Claude Code dans `~/Projects/AgentB2C` (ou le worktree
> indiqué), choisir le modèle, coller le prompt. Chaque prompt pointe vers son fichier
> `phases/UX*.md` — c'est LUI qui porte le détail et la cause racine ; le prompt ne fait
> qu'amorcer proprement.
>
> Baseline établie le 2026-08-27 sur `main` (`7208919`) : **`pytest -q` → 1452 passed,
> 1 skipped**. Toute session qui démarre sur du rouge s'arrête et le signale.

---

## Les six items, et ce que l'analyse a changé

| # | Item Fabien | Verdict de l'analyse |
|---|---|---|
| UX1 | Un critère changé ne s'applique pas | **Cause racine trouvée** : 2 cliquets monotones (union feuille + merge append-only concierge). Pas un bug multi-tour. |
| UX2 | Tester des langues plus exotiques | Le triage reconnaît **déjà** 7 langues, le widget est **déjà** traduit en 7 ; seule la production est clampée à fr/en. Scope arbitré : élargir aux 7. |
| UX3 | Devise locale de l'hôtel | **Ambigu dans le code** : `priceEuro` est-il en EUR ou déjà local ? Écart de charge ×10. Mesure obligatoire d'abord. |
| UX4 | Rate plans homonymes | Dédoublonnage sur `offer_id` seul ; le widget a déjà une heuristique pour 2 cas sur 3. Il manque le collapse des lignes vraiment identiques. |
| UX5 | Wording « c'est confirmé » | Confirmé, trivial : `templates.py:109-110`. Le tour d'avant dit déjà l'inverse. |
| UX6 | Trop de mappings en dur | Étude. 3 catégories : contrats à garder (dont `EQUIPMENT_IDS`), duplication back/front (la vraie dette), tables que MCP rend inutiles. |

## Timeline & parallélisation

```
Fenêtre 1        Fenêtre 2                    Fenêtre 3                Fenêtre 4
UX5        →     UX1  ∥  UX3-phase1     →     UX2  ∥  UX4        →     UX6
(Sonnet)         (Opus)  (Sonnet)              (Sonnet)(Sonnet)         (Opus)
                 2 worktrees                   2 worktrees              séquentiel
                         ↓
                   [gate Fabien sur le verdict devise]
```

| Fenêtre | Sessions | Parallèle ? | Condition |
|---|---|---|---|
| 1 | UX5 | Non — 30 min, ship seul | — |
| 2 | **UX1 ∥ UX3-phase1** | **Oui — 2 worktrees** (zones disjointes : feuille+profil vs mesure read-only) | UX5 mergée |
| 3 | **UX2 ∥ UX4** | **Oui — 2 worktrees** (`templates.py`+`triage.py` vs `inline_tools.py`) | **UX5 mergée impérativement** (UX2 réécrit le fichier de UX5) |
| 4 | UX6 | Non | les autres mergées (l'audit doit voir l'état final) |
| — | UX3-phase2A/2B | Non | **GO écrit de Fabien** sur le verdict de la phase 1 |

**Pourquoi cet ordre.** UX5 d'abord parce que c'est la seule des six qui trompe activement
l'utilisateur, et qu'elle prend une heure. UX1 en deuxième parce que c'est la plus haute
valeur et la plus risquée — elle mérite une fenêtre où elle est le sujet principal. UX3-phase1
en parallèle parce que c'est de la mesure read-only : zéro conflit possible. UX6 en dernier
parce qu'un audit des mappings doit auditer le code final, pas un état intermédiaire.

**Ordre de merge d'une fenêtre parallèle** : le numéro le plus bas d'abord ; le second rebase
avant MR.

## Modèles — règle et tableau

Règle du repo (inchangée depuis `PROMPTS-SESSIONS.md`) : **Opus** quand le coût d'une mauvaise
décision structurelle dépasse le coût tokens ; **Sonnet** partout où la spec est exécutable ;
**Haiku** nulle part sur ce chantier.

| Session | Modèle | Mode | Pourquoi ce modèle |
|---|---|---|---|
| **UX5** | Sonnet | piloté | Deux `return` à réécrire. La difficulté est un arbitrage de wording, qui revient à Fabien. |
| **UX1** | **Opus** | piloté, **jamais en loop** | Change un **contrat** (typed ops sur `amenities`), la sémantique du réducteur, et ajoute un guard. Le piège du tour de clarification (qui effacerait les filtres) demande de raisonner sur un invariant, pas d'itérer sur des tests. |
| **UX3-phase1** | Sonnet | piloté | Mesure et rapport. Aucune décision d'architecture — la décision vient après, avec Fabien. |
| **UX3-phase2A** | Sonnet | piloté | Si lecture B : changement d'affichage mécanique sur 2 côtés + `ground_truth.py`. |
| **UX3-phase2B** | Sonnet | piloté | Si lecture A : rédiger une demande MCP + vérifier une divulgation existante. |
| **UX2** | Sonnet | loop possible | ~93 chaînes × 5 langues : c'est du volume, et les tests paramétrés sur `LANGUAGES` sont le garde-fou. **Opus seulement si** la refonte de `_pick` en table révèle un appelant récalcitrant. |
| **UX4** | Sonnet | piloté | Une fonction, un tuple de signature, 5 tests. Les cas limites sont déjà écrits dans le fichier de phase. |
| **UX6** | **Opus** | piloté | Le livrable est un **jugement** : distinguer un contrat code-owned légitime d'une dette. Se tromper ici fait supprimer `EQUIPMENT_IDS` et réintroduire le bug d'ID halluciné. |

---

## Prompts

### UX5 (Sonnet) — le wording de confirmation

La branche `fix/booking-link-wording-not-confirmed` existe déjà et porte le commit de plan (`ad11a5a`) : cette PR portera donc les 8 fichiers de planification EN PLUS du correctif. Vérifier `git branch --show-current` avant de commencer.

```
Lis CLAUDE.md, HANDOFF.md, puis phases/UX5-wording-confirmation-booking.md et exécute cette phase, dans ce périmètre exactement.
Tu es déjà sur la branche `fix/booking-link-wording-not-confirmed`, qui porte le commit de plan du chantier — vérifie-le et travaille dessus, n'en crée pas une autre. La PR portera le plan + ce correctif.
Le wording final est un arbitrage produit : propose-moi 2 ou 3 variantes FR/EN dans la description de MR au lieu d'en imposer une.
Cherche les tests qui assertent la chaîne littérale AVANT d'éditer.
Termine par : DoD exécutée verte (pytest 1452 passed / 1 skipped en baseline, ruff, mypy, guardrails), preuve widget du texte rendu, HANDOFF.md à jour (bloc daté), commit + PR ouverte — ne merge jamais toi-même.
```

### UX1 (Opus) — la rétraction de filtre

```
Lis CLAUDE.md, HANDOFF.md, puis phases/UX1-retraction-filtres-multiturn.md et exécute cette phase, dans ce périmètre exactement.
La cause racine est déjà établie dans le fichier de phase avec les numéros de ligne : ne la re-cherche pas, vérifie-la et corrige-la.
Écris EN PREMIER le test de non-régression du piège documenté (un tour de clarification ne doit pas vider `amenities`) : c'est le seul endroit où ce correctif peut casser la prod.
Écris AUSSI le test qui échoue sur le code actuel avec la signature du bug, et prouve cet échec par `git stash` du seul correctif.
Le constat « budget affiché ≠ budget appliqué » de la section hors-périmètre : mesure-le et rapporte-le, ne le corrige pas — j'arbitrerai.
Si un choix fondateur non prévu émerge (par exemple sur la sémantique du réducteur), STOP et pose-moi la question.
Termine par : DoD exécutée verte, preuve prod avec `guard_filter_relaxation_honored = true` dans Langfuse (filtre BOOLEAN `value: ["true"]`, validé positivement avant toute conclusion d'un zéro), HANDOFF.md à jour, commit sur branche + MR — ne merge jamais toi-même.
```

### UX3 phase 1 (Sonnet) — la mesure devise

```
Lis CLAUDE.md, HANDOFF.md, puis phases/UX3-devise-locale-mesure.md et exécute LA PHASE 1 SEULEMENT.
Objectif unique : répondre par des chiffres à « `priceEuro` est-il en EUR, ou déjà dans la devise de l'hôtel ? ». Zéro ligne de code de production.
Sonde des hôtels non-euro (US, GB, CH, et surtout TH — l'ordre de grandeur du THB tranche seul), compare au prix affiché par le site de prod pour le même hôtel/jour/formule.
Espace les appels MCP (429 sur les appels chaînés) et sonde sur demain, pas aujourd'hui (cutoff même-jour ~16h Paris).
Termine par : le tableau de mesure dans reports/, le verdict écrit (lecture A ou B), HANDOFF.md à jour, et STOP — n'enchaîne PAS sur la phase 2 sans mon GO.
```

### UX2 (Sonnet) — les 7 langues

```
Lis CLAUDE.md, HANDOFF.md, puis phases/UX2-reponses-7-langues.md et exécute cette phase, dans ce périmètre exactement.
Prérequis à vérifier avant de commencer : UX5 est mergée dans main (elle réécrit `booking_link_response`, que tu vas traduire).
Utilise `web/vendor/static/js/chat/i18n.js` comme source de vérité de style pour les 5 nouvelles langues — les 7 blocs y sont déjà rédigés. N'invente pas une seconde voix.
Ne lève `TEMPLATE_LANGUAGES` qu'en DERNIER, quand toutes les tables sont complètes : sinon le fallback anglais masque les trous.
Les chaînes fr/en existantes doivent rester INCHANGÉES (contrat iso agent-usa sur les deux plus gros marchés) — teste-le.
Termine par : DoD exécutée verte, preuve prod 5 langues × 1 tour (es/it/de/pt/nl, session fraîche chacune, aucune réponse mixant deux langues), HANDOFF.md à jour, commit sur branche + MR — ne merge jamais toi-même.
```

### UX4 (Sonnet) — les rate plans indistinguables

```
Lis CLAUDE.md, HANDOFF.md, puis phases/UX4-rateplans-indistinguables.md et exécute cette phase, dans ce périmètre exactement.
La décision de design est prise et écrite dans le fichier de phase : dédoublonner sur la signature d'affichage côté backend, prix INCLUS dans la signature. Ne remets pas ça en cause, et n'ajoute pas d'heuristique frontend.
Les 3 cas limites (Ibis La Ciotat, Mercure Lyon Saxe, plans sans prix) sont déjà décrits : écris leurs tests.
Si aucun hôtel réel ne déclenche le cas pendant la vérification prod, écris-le tel quel dans le HANDOFF — n'écris jamais « prouvé en prod » sur une preuve que tu n'as pas.
Termine par : DoD exécutée verte, HANDOFF.md à jour, commit sur branche + MR — ne merge jamais toi-même.
```

### UX6 (Opus) — l'audit des mappings

```
Lis CLAUDE.md, HANDOFF.md, puis phases/UX6-audit-mappings-en-dur.md et exécute cette phase, dans ce périmètre exactement.
C'est une PHASE D'ÉTUDE : le livrable principal est reports/AUDIT-MAPPINGS-<date>.md, pas un refactor. Ne supprime que ce que la mesure prouve mort.
Le réflexe « une table en dur est une dette » est faux dans ce repo, et le démontrer fait partie du livrable : `EQUIPMENT_IDS` est le CORRECTIF d'un bug de prod (Miami `[1]` → 0 offres), pas sa cause. Si ton audit conclut qu'une table de catégorie 1 doit bouger, STOP et pose-moi la question.
Mesure `countryCode` sur au moins 4 pays dont un non-euro avant de conclure quoi que ce soit sur `_ISO_BY_COUNTRY_NAME`.
La duplication `_MARKET` / `COUNTRY_META` : chiffre-la et propose, ne l'implémente pas.
Termine par : le rapport, les suppressions prouvées avec leurs tests, DoD exécutée verte, HANDOFF.md à jour, commit sur branche + MR — ne merge jamais toi-même.
```

---

## Règles communes à toutes les sessions

- **Un seul scope** : celui de la phase. Un « pendant que j'y suis » se note dans le HANDOFF,
  il ne se code pas (`SESSIONS-CLAUDE-CODE.md`).
- **Bloqué deux fois sur la même approche → STOP.** Re-planifier ou poser une question
  précise ; ne pas décliner des variantes.
- **« Fait » est une affirmation qui exige une preuve.** Un typecheck vert ne prouve pas un
  comportement. Si ça n'a pas été lancé / testé / ouvert dans un navigateur : écrire
  « non testé ».
- **Jamais de HANDOFF « fait » sur du rouge** (CLAUDE.md, fin de session).
- **La review humaine de Fabien est le gate** : commit sur branche + MR, jamais de merge
  autonome.

---

## Nettoyage en fin de chantier — OBLIGATOIRE (décision Fabien, 2026-08-27)

Ces fichiers de planification sont **temporaires**. Ils sont commités dans la **première PR**
(UX5) pour que le plan soit relisible pendant tout le chantier, et ils doivent **disparaître**
quand les six items sont livrés. Ce qui reste, c'est le `HANDOFF.md` — c'est lui qui porte la
mémoire du projet, pas ces brouillons.

À supprimer dans la **dernière PR du chantier** (UX6, ou la dernière mergée si l'ordre change) :

```bash
git rm PROMPTS-UX-2026-08-27.md \
       tasks/todo-ux-2026-08-27.md \
       phases/UX1-retraction-filtres-multiturn.md \
       phases/UX2-reponses-7-langues.md \
       phases/UX3-devise-locale-mesure.md \
       phases/UX4-rateplans-indistinguables.md \
       phases/UX5-wording-confirmation-booking.md \
       phases/UX6-audit-mappings-en-dur.md
```

Avant de supprimer, **vérifier que rien de durable n'est perdu** — chaque phase a produit des
constats qui doivent avoir été recopiés ailleurs :

- [ ] UX1 : la cause racine des 2 cliquets et le constat « budget affiché ≠ budget appliqué » →
      dans `HANDOFF.md`
- [ ] UX2 : la variante `pt` retenue et le sort de `_ACK_RE` → dans `HANDOFF.md`
- [ ] UX3 : le verdict devise (lecture A ou B) → dans `reports/` **et** `HANDOFF.md`
- [ ] UX4 : la règle de signature d'affichage → dans la docstring de `_day_rate_plans`, pas
      seulement dans le fichier de phase
- [ ] UX6 : la justification par table → dans `reports/AUDIT-MAPPINGS-*.md` (qui reste)
- [ ] Aucun autre fichier du repo ne référence encore `phases/UX*` ou `PROMPTS-UX-2026-08-27`
      (`grep -rn "UX[1-6]-\|PROMPTS-UX" --exclude-dir=.git .`)

⚠️ Ne pas toucher `tasks/todo.md` : il porte le tracker OBS4 (577 lignes, tracké). L'index de
ce chantier est `tasks/todo-ux-2026-08-27.md`, un fichier distinct, précisément pour que sa
suppression ne détruise rien.
