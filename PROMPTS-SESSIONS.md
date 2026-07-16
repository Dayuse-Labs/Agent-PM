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
