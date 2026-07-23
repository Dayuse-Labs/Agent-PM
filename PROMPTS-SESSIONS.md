# Prompts de lancement des sessions Claude Code — AgentB2C

> Mode d'emploi : ouvrir une session Claude Code dans `~/Projects/AgentB2C` (ou le worktree indiqué), choisir le modèle (`claude --model …` ou `/model`), coller le prompt. Chaque prompt pointe vers son fichier de phase — c'est LUI qui porte le détail, le prompt ne fait qu'amorcer proprement.

---

## Timeline & parallélisation

```
Semaine 1        Semaine 2              Semaine 3               Semaine 4
S1 → S2 → S3 →   S4 ∥ S5  → S6 →        S7 →  S8 ∥ S9  →        S10 → [gate Fabien] → S11
(Opus)(Opus)(Son) (Sonnet, worktrees)   (Son)  (Sonnet, wt)      (Son)                (Opus)
                  merge S4 puis S5             merge S8 puis S9
```

| Fenêtre | Sessions | Parallèle ? | Condition |
|---|---|---|---|
| 1 | S1 → S2 → S3 | Non (fondations séquentielles) | Hook plugin vérifié avant S1 |
| 2 | **S4 ∥ S5** | **Oui — 2 worktrees** (zones disjointes : feuille vs orchestrateur) | S3 mergée ; S4 exige les tools MCP_B2C mergés |
| 3 | S6 → S7 | Non (cœur orchestrateur) | S4+S5 mergées |
| 4 | **S8 ∥ S9** | **Oui — 2 worktrees** (evals/ vs façade) | S7 mergée |
| 5 | S10 puis S11 | Non — gates humaines | ES prod + MCP déployé (S10) ; GO Fabien écrit (S11) |

Ordre de merge des fenêtres parallèles : **le numéro le plus bas d'abord** (S4 avant S5, S8 avant S9), le second rebase avant MR.

## Modèles — règle et tableau

Règle : **Opus** quand le coût d'une mauvaise décision structurelle dépasse le coût tokens (fondations, prod) ; **Sonnet** partout où la spec est exécutable (le gros du volume, et TOUJOURS dans les boucles — le garde-fou, ce sont les tests, pas le modèle) ; **Haiku** nulle part sur ce chantier (code métier subtil).

| Session | Modèle | Mode |
|---|---|---|
| S1, S2 | **Opus** | piloté |
| S3 | Sonnet | piloté |
| S4, S5 | Sonnet | **loop conseillé** (∥ worktrees) |
| S6 | Sonnet | piloté puis loop possible |
| S7 | Sonnet | **loop conseillé** |
| S8 | Sonnet | loop possible (∥ S9) |
| S9 | Sonnet (Opus si arbitrage contrat) | piloté |
| S10 | Sonnet | piloté, jamais loop |
| S11 | **Opus** | piloté, GO humain par étape |

---

## Prompts — sessions pilotées

### S1 (Opus)
```
Lis CLAUDE.md, HANDOFF.md, puis phases/S01-socle-feuille-search.md et exécute cette phase, dans ce périmètre exactement.
Règles : un seul scope (celui de la phase) ; si un choix fondateur non prévu émerge, STOP et pose-moi la question ; termine par la DoD exécutée verte, HANDOFF.md mis à jour (bloc daté), commit sur la branche indiquée — ne merge jamais toi-même.
```

### S2 (Opus) · S3 (Sonnet) · S6 (Sonnet) · S9 (Sonnet)
Même gabarit — remplacer le fichier de phase :
```
Lis CLAUDE.md, HANDOFF.md, puis phases/<FICHIER>.md et exécute cette phase, dans ce périmètre exactement.
Règles : un seul scope ; choix fondateur imprévu = STOP et question ; fin = DoD verte + HANDOFF à jour + commit branche, jamais de merge.
```
Fichiers : `S02-faq-orchestrateur.md`, `S03-socle-transverse.md`, `S06-synthese-sse.md`, `S09-facade-v3-chat.md`.
⚠️ S9 en parallèle de S8 : lancer DEPUIS le worktree (voir section worktrees).

### S10 (Sonnet) — données prod, vigilance
```
Lis CLAUDE.md, HANDOFF.md, puis phases/S10-shadow-run.md.
AVANT TOUT : revalide P1/P4 sur l'ES de prod (étape 1 de la phase) — si les notes/avis sont vides sur prod aussi, STOP immédiat et rapport.
Exécute ensuite le shadow-run. Tu produis un rapport chiffré : la décision GO/hybride ne t'appartient pas. Lecture seule partout ; aucun trafic réel.
```

### S11 (Opus) — prod, GO humain par étape
```
Lis CLAUDE.md, HANDOFF.md, puis phases/S11-deploiement-canary.md.
Règle absolue : AUCUNE action sur la prod (création de service, variable, bascule de trafic, palier canary) sans mon GO écrit explicite dans cette conversation, étape par étape. Commence par rédiger les critères de rollback et me les soumettre.
```

---

## Prompts — sessions parallèles (worktrees)

### Lancement de la fenêtre S4 ∥ S5 (deux terminaux)

Terminal A :
```bash
cd ~/Projects/AgentB2C && git worktree add ../AgentB2C-s4 -b s4-guards-geo && cd ../AgentB2C-s4 && claude --model claude-sonnet-5
```
Prompt A (S4) :
```
Lis CLAUDE.md, HANDOFF.md, puis phases/S04-guards-geo-feuille-search.md.
Tu es dans un git worktree dédié (branche s4-guards-geo) : une session S5 travaille EN PARALLÈLE sur l'orchestrateur. INTERDICTION de toucher un fichier hors de ta zone autorisée (agents/hotel_search_agent/** et ses tests). Si un besoin hors zone apparaît, note-le dans HANDOFF et STOP sur ce point.
Exécute la phase. Fin = DoD verte + HANDOFF + commit sur la branche. S4 merge AVANT S5.
```

Terminal B :
```bash
cd ~/Projects/AgentB2C && git worktree add ../AgentB2C-s5 -b s5-profil-session && cd ../AgentB2C-s5 && claude --model claude-sonnet-5
```
Prompt B (S5) : même gabarit avec `phases/S05-profil-session.md`, zone `agents/b2c_concierge/**`, et : « Ta branche merge APRÈS s4-guards-geo : avant la MR, rebase sur main fraîche. »

Nettoyage après merge des deux : `git worktree remove ../AgentB2C-s4 ../AgentB2C-s5`.

### Fenêtre S8 ∥ S9 — même mécanique
Worktrees `../AgentB2C-s8` (branche `s8-batteries`, zone `evals/**`+`scripts/**`) et `../AgentB2C-s9` (branche `s9-facade`, zone façade/API). S8 merge d'abord.

---

## Prompts — mode LOOP (S4, S5, S7, S8 ; S6 en fin de phase)

Principe : boucle externe qui relance une session fraîche tant que la DoD n'est pas verte, un item par itération, état porté par HANDOFF.md. Le garde-fou est triple : tests = spec intouchable, stop-conditions, pas de push.

1. Sauver le prompt d'itération (adapter le fichier de phase) dans `prompts/loop-s4.txt` :
```
Lis CLAUDE.md, HANDOFF.md, puis phases/S04-guards-geo-feuille-search.md.
Prends LE PREMIER item de la phase non encore fait d'après HANDOFF.md. Implémente-le, LUI SEUL.
Interdictions : modifier un test porté (les tests sont la spec — si un test te semble faux, écris-le dans HANDOFF et arrête-toi) ; toucher hors zone autorisée ; git push.
Fin d'itération : lance les tests de la zone ; mets à jour HANDOFF.md (item fait/rouge + compteur) ; commit local descriptif. Si le même test est rouge pour la 2e itération consécutive d'après HANDOFF : n'insiste pas, documente et termine.
```
2. Boucle externe (depuis le worktree) :
```bash
for i in $(seq 1 15); do
  claude -p "$(cat prompts/loop-s4.txt)" --model claude-sonnet-5 --permission-mode acceptEdits
  bash -c 'pytest agents/hotel_search_agent -q && bash scripts/dayuse_guardrails.sh .' && echo "DoD VERTE en $i itérations" && break
done
```
3. À la sortie (verte ou budget épuisé) : relire le diff **humainement** (`git log --oneline`, `git diff main`), vérifier qu'aucun test n'a été modifié (`git diff main -- '**/test_*.py'` doit être vide sur les tests portés), puis MR.

Adapter pour S5/S7/S8 : remplacer le fichier de phase, la commande DoD et la zone. Budget 15 itérations par défaut ; si 2 sorties consécutives sans progrès (compteur HANDOFF stable), arrêter la boucle et repasser en session pilotée.

---

# Série S-G — remédiation geo/multi-turn (arbitrée 2026-07-23)

> Détail par session : `phases/SG1…SG9.md`. Plan arbitré : `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md`. Décisions A1-A8 tranchées — ne pas re-litiger en session.

## Timeline & parallélisation

```
Fenêtre 1 (3 worktrees)      Fenêtre 2 (3 worktrees)      Fenêtre 3 (séquentiel)   Fenêtre 4
S-G1 ∥ S-G3 ∥ S-G4      →    S-G2 ∥ S-G5 ∥ S-G8      →    S-G6 → S-G7          →   S-G9
(Son)  (Opus)  (Son)         (Son)  (Son)  (Son)          (Sonnet)                 (Sonnet)
merge : G1 → G3 → G4         merge : G2 → G5 → G8         sur main fraîche         jamais loop
```

| Fenêtre | Sessions | Parallèle ? | Condition d'entrée |
|---|---|---|---|
| 1 | S-G1 ∥ S-G3 ∥ S-G4 | **Oui — 3 worktrees** (zones : profil concierge / feuille geo / timeouts) | branche `sg0-plan-remediation-geo-multiturn` mergée |
| 2 | S-G2 ∥ S-G5 ∥ S-G8 | **Oui — 3 worktrees** (facade / feuille+concierge / scripts) | fenêtre 1 mergée (S-G5 exige S-G1+S-G3) |
| 3 | S-G6 puis S-G7 | Non (mêmes fichiers feuille : instruction + response_bridge) | fenêtre 2 mergée |
| 4 | S-G9 | Non — mesure, jamais loop | S-G1→S-G8 mergées + 3 services up |

Ordre de merge des fenêtres parallèles : **numéro le plus bas d'abord**, les autres rebasent avant MR.

## Modèles

| Session | Modèle | Mode |
|---|---|---|
| S-G3 | **Opus** (`claude-opus-4-8`) | piloté — design du ranker + probes live = jugement |
| S-G1, S-G5, S-G6, S-G8 | Sonnet (`claude-sonnet-5`) | piloté, **loop possible** une fois les probes faits |
| S-G2, S-G4, S-G7 | Sonnet (`claude-sonnet-5`) | piloté (sessions courtes) |
| S-G9 | Sonnet (`claude-sonnet-5`) | piloté, **jamais loop** (données réelles) |

## Fenêtre 1 — S-G1 ∥ S-G3 ∥ S-G4 (3 terminaux)

Terminal A :
```bash
cd ~/Projects/AgentB2C && git worktree add ../AgentB2C-sg1 -b sg1-profile-v2 && cd ../AgentB2C-sg1 && claude --model claude-sonnet-5
```
Prompt A (S-G1) :
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§4),
reports/research/multiturn-state-memo.md, reports/research/code-verification-memo.md (claims 3/4/9),
puis phases/SG1-profil-v2-patch-ops.md et exécute cette phase, dans ce périmètre exactement.
Tu es dans un worktree dédié (branche sg1-profile-v2) : S-G3 et S-G4 travaillent EN PARALLÈLE.
INTERDICTION de toucher un fichier hors de ta zone (agents/b2c_concierge/** + tests). Besoin hors zone → HANDOFF + STOP sur ce point.
Règles : tests de transitions AVANT le code ; rétro-compat du delta plat obligatoire ; CONTRACT_KEYS intouché ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge. Ta branche merge EN PREMIER dans cette fenêtre.
```

Terminal B :
```bash
cd ~/Projects/AgentB2C && git worktree add ../AgentB2C-sg3 -b sg3-geo-resolver && cd ../AgentB2C-sg3 && claude --model claude-opus-4-8
```
Prompt B (S-G3) :
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§2),
reports/research/geo-disambiguation-memo.md (en entier), reports/research/code-verification-memo.md (claims 1/7/8),
puis phases/SG3-resolveur-geo-multicandidats.md et exécute cette phase, dans ce périmètre exactement.
Tu es dans un worktree dédié (branche sg3-geo-resolver) : S-G1 et S-G4 travaillent EN PARALLÈLE.
INTERDICTION de toucher agents/b2c_concierge/** ; ta zone = agents/hotel_search_agent/** + scripts/build_inventory_snapshot.py.
Règles : PROBE LIVE Mapbox avant tout code (documenter, trancher Search Box / décision A2) ; le ranker est
100 % déterministe, zéro appel LLM ; tous les guards géo existants restent verts ; chaque cas d'échec de
l'audit devient un test nommé ; fin = DoD verte + vérif live + HANDOFF + commit branche, jamais de merge.
Ta branche merge APRÈS sg1-profile-v2 : rebase sur main fraîche avant la MR.
```

Terminal C :
```bash
cd ~/Projects/AgentB2C && git worktree add ../AgentB2C-sg4 -b sg4-timeout-budgets && cd ../AgentB2C-sg4 && claude --model claude-sonnet-5
```
Prompt C (S-G4) :
```
Lis CLAUDE.md, HANDOFF.md, reports/research/timeouts-latency-memo.md (en entier),
reports/research/code-verification-memo.md (claim 6), puis phases/SG4-budgets-timeout-litellm.md
et exécute cette phase, dans ce périmètre exactement.
Tu es dans un worktree dédié (branche sg4-timeout-budgets) : S-G1 et S-G3 travaillent EN PARALLÈLE.
Ta zone = consts timeout/config LiteLLM du concierge + instrumentation par phase de la feuille — ne touche PAS
profile.py (zone S-G1) ni geocode_tool/mapbox_client (zone S-G3).
Règles : 0 retry orchestrateur→feuille (invariant) ; budgets posés depuis des mesures, méthode documentée ;
Chester = bug de correctness à tracer par l'instrumentation, pas un timeout à élargir ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge. Ta branche merge EN DERNIER (rebase après G1 et G3).
```

Nettoyage après merge des trois : `git worktree remove ../AgentB2C-sg1 ../AgentB2C-sg3 ../AgentB2C-sg4`.

## Fenêtre 2 — S-G2 ∥ S-G5 ∥ S-G8 (3 terminaux)

Terminal A :
```bash
cd ~/Projects/AgentB2C && git worktree add ../AgentB2C-sg2 -b sg2-native-context && cd ../AgentB2C-sg2 && claude --model claude-sonnet-5
```
Prompt A (S-G2) :
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§3),
reports/research/code-verification-memo.md (claim 2), puis phases/SG2-intake-contexte-natif.md
et exécute cette phase, dans ce périmètre exactement.
Tu es dans un worktree dédié (branche sg2-native-context) : S-G5 et S-G8 travaillent EN PARALLÈLE.
Ta zone = facade.py + mapping profil + tests — ne touche PAS la feuille (zone S-G5) ni scripts/ (zone S-G8).
Règles : probe du widget vendorisé AVANT de coder (web/vendor/ — le payload réel = la spec) ;
tout optionnel, jamais de 500 sur un champ invalide ; GPS jamais dans les métriques ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge. Ta branche merge EN PREMIER dans cette fenêtre.
```

Terminal B :
```bash
cd ~/Projects/AgentB2C && git worktree add ../AgentB2C-sg5 -b sg5-bridge-pagination && cd ../AgentB2C-sg5 && claude --model claude-sonnet-5
```
Prompt B (S-G5) :
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§4),
reports/research/code-verification-memo.md (claims 9/10), le pattern equipment_ids.py,
puis phases/SG5-pont-deterministe-pagination.md et exécute cette phase, dans ce périmètre exactement.
Tu es dans un worktree dédié (branche sg5-bridge-pagination) : S-G2 et S-G8 travaillent EN PARALLÈLE.
Ne touche PAS facade.py (zone S-G2) ni scripts/ d'annotation (zone S-G8).
Règles : probe search_offers AVANT la pagination (décision A7) ; le callback comble, ne réécrit jamais une
extraction fraîche ; étendre l'exhaustion S12, pas de machine parallèle ; preuve live « autres options » =
nouveaux IDs obligatoire ; fin = DoD verte + HANDOFF + commit branche, jamais de merge.
Ta branche merge APRÈS sg2-native-context : rebase avant MR.
```

Terminal C :
```bash
cd ~/Projects/AgentB2C && git worktree add ../AgentB2C-sg8 -b sg8-harness-hardening && cd ../AgentB2C-sg8 && claude --model claude-sonnet-5
```
Prompt C (S-G8) :
```
Lis CLAUDE.md, HANDOFF.md (addendum S-A), REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md (§ Durcissements),
scripts/run_eval_adapter.py, puis phases/SG8-durcissement-harness.md et exécute cette phase,
dans ce périmètre exactement.
Tu es dans un worktree dédié (branche sg8-harness-hardening) : S-G2 et S-G5 travaillent EN PARALLÈLE.
Ta zone = scripts/** + tests/** UNIQUEMENT — le pack dayuse_eval_pack/eval_pack/** est INTOUCHABLE, agents/** interdit.
Règles : une assertion sans champ disponible = skipped divulgué, jamais un faux vert ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge. Ta branche merge EN DERNIER (rebase après G2 et G5).
```

Nettoyage : `git worktree remove ../AgentB2C-sg2 ../AgentB2C-sg5 ../AgentB2C-sg8`.

## Fenêtre 3 — S-G6 puis S-G7 (séquentiel, checkout principal)

S-G6 :
```bash
cd ~/Projects/AgentB2C && git checkout main && git pull && git checkout -b sg6-dates-durations-minutes && claude --model claude-sonnet-5
```
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§4 A4),
reports/research/multiturn-state-memo.md (§e), tasks/lessons.md, puis phases/SG6-dates-durees-demiheures.md
et exécute cette phase, dans ce périmètre exactement.
Règles : le LLM étiquette (date/durée/fenêtre), le code calcule — jamais l'inverse ; une durée n'est jamais
une fenêtre absolue ; vérifs live des formulations pièges obligatoires (leçon S10 #4) ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```

S-G7 (après merge S-G6) :
```bash
cd ~/Projects/AgentB2C && git checkout main && git pull && git checkout -b sg7-locale-currency && claude --model claude-sonnet-5
```
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§5 axe C),
reports/research/code-verification-memo.md (claims 2/7), puis phases/SG7-locale-devise-propagation.md
et exécute cette phase, dans ce périmètre exactement.
Règles : display EUR conservé, disclosure honnête, jamais de conversion inventée ; le pricing réel est
gated sur le probe MCP (constat, pas de code) ; preuve live Lisboa-pt obligatoire ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```

## Fenêtre 4 — S-G9 (piloté, jamais loop)

```bash
cd ~/Projects/AgentB2C && git checkout main && git pull && git checkout -b sg9-gate-rerun && bash scripts/run_local.sh && claude --model claude-sonnet-5
```
```
Lis CLAUDE.md, HANDOFF.md, REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md (§ gates),
reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§8), puis phases/SG9-gate-rerun-eval-ranking.md
et exécute cette phase, dans ce périmètre exactement.
Règles : mesure seulement, zéro fix agent (documenter les bugs trouvés) ; chaque échec trié un par un ;
conditions du run loggées (modèle, inventaire, séquentiel) ; le GO canary appartient à Fabien ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```

## Mode LOOP — S-G1, S-G5, S-G6, S-G8 (après la partie probe/design faite en piloté)

Même mécanique que la section loop S4-S8 ci-dessus (budget 15 itérations, stop-conditions, tests = spec intouchable). Prompt d'itération type (`prompts/loop-sg1.txt`, adapter le fichier de phase et la commande DoD) :
```
Lis CLAUDE.md, HANDOFF.md, puis phases/SG1-profil-v2-patch-ops.md.
Prends LE PREMIER item de la phase non encore fait d'après HANDOFF.md. Implémente-le, LUI SEUL.
Interdictions : modifier un test existant (les tests sont la spec — un test qui te semble faux → HANDOFF + stop) ;
toucher hors zone autorisée ; git push. Les décisions A1-A8 sont arbitrées : ne les rouvre pas.
Fin d'itération : tests de la zone ; HANDOFF à jour (item fait/rouge + compteur) ; commit local descriptif.
Même test rouge 2 itérations de suite → n'insiste pas, documente et termine.
```
Boucle externe :
```bash
for i in $(seq 1 15); do
  claude -p "$(cat prompts/loop-sg1.txt)" --model claude-sonnet-5 --permission-mode acceptEdits
  bash -c 'pytest agents/b2c_concierge -q && bash scripts/dayuse_guardrails.sh .' && echo "DoD VERTE en $i itérations" && break
done
```
DoD par session : S-G1 `pytest agents/b2c_concierge -q` · S-G5/S-G6 `pytest -q` · S-G8 `pytest tests/ -q`. ⚠️ S-G3, S-G4 (probes live), S-G2, S-G7 (courts) et S-G9 (mesure) : piloté uniquement.
