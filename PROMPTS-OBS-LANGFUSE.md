# Prompts de lancement — série OBS (Langfuse)

> Mode d'emploi : une session = un scope. Ouvrir Claude Code **dans le projet indiqué**, choisir le
> modèle, coller le prompt. Le détail est porté par le fichier de phase — le prompt ne fait
> qu'amorcer proprement. `/clear` entre deux sessions.
> Plan + suivi : `PLAN-OBS-LANGFUSE-2026-07-29.md` · Référence technique : `OBS2-LANGFUSE-BRIEF.md`.

## Ordre et projets — vue d'ensemble

| Fen. | # | Projet / dossier | Branche | Modèle | Mode |
|---|---|---|---|---|---|
| 0 | OBS0 | `~/Projects/AgentB2C` + **Railway (projet `Langfuse`)** | `obs0-bump-serveur-langfuse` | Sonnet | piloté, jamais loop |
| 1 | OBS2 | `~/Projects/AgentB2C` (checkout principal) | `obs2-typage-observations` | Sonnet | piloté puis loop |
| 1 | OBS6 | `~/Projects/AgentB2C-obs6` (**worktree**) | `obs6-datasets-experiments` | Sonnet | piloté puis loop |
| 2 | OBS3 | `~/Projects/AgentB2C` | `obs3-scores-deterministes` | Sonnet | piloté puis loop |
| 3 | OBS4 | `~/Projects/AgentB2C` | `obs4-trace-distribuee-a2a` | **Opus** | piloté |
| 3 | OBS10 | **`~/Projects/MCP_B2C`** (autre repo) | `obs10-mcp-tracing` | Sonnet | piloté |
| 4 | OBS7 | `~/Projects/AgentB2C` + **Langfuse UI** | `obs7-judges-online` | Sonnet | piloté |
| 4 | OBS5 | `~/Projects/AgentB2C-obs5` (**worktree**) | `obs5-user-feedback` | Sonnet | piloté |
| ops | OBS8 | **Railway** (ClickHouse, instance partagée) | — (ops) | Sonnet | piloté, jamais loop |
| — | OBS9 | **Railway** + `~/Projects/AgentB2C` | — | **Opus** | piloté, GO par étape |

Parallèle : **OBS2 ∥ OBS6** (2 worktrees) · **OBS4 ∥ OBS10** (repos différents, pas de worktree) ·
**OBS7 ∥ OBS5** (2 worktrees). Merge : **zone `agents/`+`libs/` d'abord**, l'autre rebase.

---

## Marche à suivre

**Avant de commencer (une fois)**

1. Backup Postgres + ClickHouse de l'instance Langfuse — sinon OBS0 s'arrête là.
2. Envoyer la demande de fenêtre pour **l'upgrade ClickHouse ≥ 25.12** (OBS8) aux autres producers
   Dayuse. C'est du délai de coordination : lancé maintenant, il ne bloquera rien plus tard.

**Fenêtre 0 — OBS0, seul (½ j).** Bump 3.205.1 → 3.224.2, tags épinglés `:3`, puis la checklist UI en
7 points. **Ne pas enchaîner avant d'avoir les réponses** : elles conditionnent OBS6 (point 7) et
OBS7 (points 1 et 2). Reporter dans Q1-Q5 du plan.

**Fenêtre 1 — OBS2 ∥ OBS6 (2 terminaux, ~1,5 j).**

```bash
# préparer le worktree d'OBS6 AVANT de lancer les sessions
cd ~/Projects/AgentB2C && git worktree add ../AgentB2C-obs6 -b obs6-datasets-experiments
cp .env ../AgentB2C-obs6/.env          # .env n'est pas dans git : sans ça, session sans clés
cd ../AgentB2C-obs6 && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python \
  -r agents/hotel_search_agent/requirements.txt -r agents/faq_agent/requirements.txt \
  -r agents/b2c_concierge/requirements.txt -r requirements-dev.txt -e libs/b2c_common
.venv/bin/pytest -q                    # contrôle d'install
```

⚠️ **Ne pas ajouter `"google-adk[eval]==2.4.0"`** à cette commande : l'extra tire
`google-cloud-aiplatform[evaluation]` qui exige `litellm<1.86`, contre notre pin `litellm==1.90.2`
→ **résolution uv insatisfiable** (piège déjà rencontré en S5 et le 28/07, cf. HANDOFF). `google-adk[a2a]`
des requirements suffit pour pytest, `run_local.sh` et le smoke. OBS6 n'en a pas besoin : son livrable
ce sont les experiments Langfuse, et `adk eval` tourne dans son propre job CI.

Terminal A = OBS2 dans le checkout principal (ports 8100-8102, `LANGFUSE_TRACING_ENVIRONMENT=dev-obs2`).
Terminal B = OBS6 dans le worktree (`PORT_OFFSET=10` → 8110-8112 après qu'OBS6 l'a implémenté,
`CONCIERGE_URL=http://localhost:8110/`, `LANGFUSE_TRACING_ENVIRONMENT=dev-obs6`).
**Merge OBS2 d'abord**, puis OBS6 rebase sur main fraîche.

**Fenêtre 2 — OBS3, seul (1 j).** Sur main fraîche après OBS2. Non parallélisable avec OBS2 : mêmes
fichiers (`observability.py`, `facade.py`, call sites des guards). Si OBS6 tourne encore, aucun
problème — zones disjointes.

**Fenêtre 3 — OBS4 ∥ OBS10 (~1 j).** OBS4 dans AgentB2C sur main fraîche (Opus). OBS10 dans
`~/Projects/MCP_B2C` : repo différent, aucun worktree, aucune contention. OBS4 définit le contrat
d'injection du traceparent, OBS10 implémente l'extraction — **OBS4 merge d'abord**, OBS10 fait sa
propre MR dans son repo.

**Fenêtre 4 — OBS7 ∥ OBS5 (~1,5 j).** OBS7 sur main fraîche (UI Langfuse + config versionnée),
OBS5 dans un worktree (`git worktree add ../AgentB2C-obs5 -b obs5-user-feedback` + `cp .env`).
Ordre de merge libre : aucun fichier commun.

**Ensuite** : OBS8 quand la fenêtre ClickHouse est accordée · OBS9 **uniquement** quand une v4
self-hosted stable est publiée (au 2026-07-29 : `4.0.0-rc.3`).

**Règles de fenêtre parallèle** (elles évitent les trois pannes classiques)

- Une seule stack locale à la fois **ou** ports décalés — `run_local.sh` code 8100-8102 en dur.
- `LANGFUSE_TRACING_ENVIRONMENT` distinct par session, sinon les deux terminaux lisent les traces de
  l'autre et concluent faux.
- Un seul terminal touche `main` ; les MR partent dans l'ordre annoncé, jamais en simultané.
- À la fin : `git worktree remove ../AgentB2C-obs6` (et `-obs5`), après merge.

---

## OBS0 — Bump serveur 3.205.1 → 3.224.2 (ops, jamais loop)

```bash
cd ~/Projects/AgentB2C && git checkout main && git pull && git checkout -b obs0-bump-serveur-langfuse && claude --model claude-sonnet-5
```

```
Lis CLAUDE.md, HANDOFF.md, OBS2-LANGFUSE-BRIEF.md (§0 et §12), PLAN-OBS-LANGFUSE-2026-07-29.md,
puis phases/OBS0-bump-serveur-langfuse.md et exécute cette phase, dans ce périmètre exactement.
C'est une opération sur une instance Langfuse de PRODUCTION partagée avec d'autres producers Dayuse.
Règles absolues : aucun redeploy sans que le backup Postgres + ClickHouse soit fait et confirmé ;
aucune action de migration v4 (la décision D-OBS-2 est prise : la v4 n'est qu'en RC) ; les tags
d'image sont épinglés sur la ligne :3, jamais latest ; les critères de rollback sont écrits AVANT
le premier redeploy et soumis à moi. Piège CLI : `railway variables` au PLURIEL.
Tu termines par : version constatée avant/après, un tour synthétique retrouvé dans l'UI, et les
7 points de la checklist §11 répondus PAR ÉCRIT (ils conditionnent OBS6 et OBS7 — Q1 à Q5 du plan).
Fin = HANDOFF.md à jour (bloc daté) + tableau de suivi du plan mis à jour + commit sur la branche.
Ne merge jamais toi-même.
```

## OBS2 — Typage des observations, level, release, TTFT

```bash
cd ~/Projects/AgentB2C && git checkout main && git pull && git checkout -b obs2-typage-observations && claude --model claude-sonnet-5
```

```
Lis CLAUDE.md, HANDOFF.md, OBS2-LANGFUSE-BRIEF.md (§1), PLAN-OBS-LANGFUSE-2026-07-29.md (décisions
et invariants), puis phases/OBS2-typage-observations.md et exécute cette phase, dans ce périmètre
exactement.
Règles : commence par INVENTORIER les spans qu'ADK émet déjà sur un tour réel avant d'ajouter le
moindre span — un span en double est l'erreur qui avait triplé l'usage en OBS1 ; le code doit rester
totalement inerte sans les clés LANGFUSE_* (la suite offline verrouille ce chemin) ; l'observabilité
n'élève jamais une exception dans un tour ; aucun contenu de message dans un status_message.
Ne touche pas stamp_langfuse_session (son retrait appartient à OBS4) et n'implémente aucun score
(OBS3) — au plus, pose le point d'émission du TTFT.
Fin = gates verts (pytest, ruff, mypy, dayuse_guardrails.sh) + vérification manuelle avec les vraies
clés via run_local.sh et smoke_e2e.py (Agent Graph visible, usage compté 1×) + HANDOFF à jour +
commit branche. Jamais de merge.
```

## OBS6 — Datasets + experiments + gate CI (fenêtre 1, **en parallèle d'OBS2**, worktree)

Préparation du worktree : voir la marche à suivre ci-dessus (`git worktree add` + `cp .env` + venv).

```bash
cd ~/Projects/AgentB2C-obs6 && LANGFUSE_TRACING_ENVIRONMENT=dev-obs6 claude --model claude-sonnet-5
```

```
Lis CLAUDE.md, HANDOFF.md, OBS2-LANGFUSE-BRIEF.md (§4), PLAN-OBS-LANGFUSE-2026-07-29.md,
EVAL-PACK-COMPARISON-2026-07-22.md, puis phases/OBS6-datasets-experiments.md et exécute cette phase,
dans ce périmètre exactement.
Tu es dans un worktree dédié (branche obs6-datasets-experiments) : une session OBS2 travaille EN
PARALLÈLE sur libs/ et agents/. INTERDICTION de toucher libs/** et agents/** ; ta zone = evals/**,
scripts/**, .github/** (+ evalset/** en lecture). Le pack dayuse_eval_pack/** est INTOUCHABLE
(byte-identique — leçon S-G8 : toute annotation vit dans scripts/). Besoin hors zone → HANDOFF + STOP
sur ce point.
Contention à régler EN PREMIER : scripts/run_local.sh code les ports 8100-8102 en dur et la session
OBS2 occupe déjà ce triplet. scripts/ est TA zone → ajoute un PORT_OFFSET à run_local.sh (documenté,
défaut 0, comportement inchangé sans la variable) et travaille sur 8110-8112 avec
CONCIERGE_URL=http://localhost:8110/. Ne lance jamais une stack sur les ports par défaut.
Règles : datasets HÉBERGÉS obligatoirement (un dataset local ne crée pas de DatasetRun, donc pas de
comparaison de runs) ; un item multi-tours porte l'historique ET le profil accumulé, sinon le tour
n'est pas reproductible ; evaluators en Python chez nous, jamais de code evaluators managés
(D-OBS-3) ; aucun judge LLM ici ; flush() en fin de script d'eval ; le job CI reste NON BLOQUANT ce
tour-ci (on pose la mesure avant le seuil) ; tu attaques l'agent par la façade HTTP — le contrat /v3
est stable, tu n'as pas besoin du travail d'OBS2.
Preuve de fin : deux runs comparés dans l'UI + ≥ 5 items importés de vraies traces avec
source_trace_id.
Ta branche merge APRÈS obs2-typage-observations : rebase sur main fraîche avant la MR.
Fin = gates verts + HANDOFF à jour + commit branche. Jamais de merge toi-même.
```

## OBS3 — Scores déterministes + dashboard versionné

```bash
cd ~/Projects/AgentB2C && git checkout main && git pull && git checkout -b obs3-scores-deterministes && claude --model claude-sonnet-5
```

```
Lis CLAUDE.md, HANDOFF.md, OBS2-LANGFUSE-BRIEF.md (§2 et §8), PLAN-OBS-LANGFUSE-2026-07-29.md,
puis phases/OBS3-scores-deterministes.md et exécute cette phase, dans ce périmètre exactement.
Règles : les 12 noms de guards sont un CONTRAT — une seule constante, dérivée de la spec existante
(tests portés + AUDIT-REWORK-2026-07.md), snake_case stable, jamais renommée ensuite ; BOOLEAN vaut
0/1 et jamais True ; RGPD — un comment de score contient un identifiant de règle, jamais un extrait
de message (ajoute le test qui le verrouille) ; toute lecture de métriques passe par UN seul module
utilisant api.legacy.metrics_v1 (décision D-OBS-6) ; ne construis PAS d'alerting maison (D-OBS-7).
Zéro appel LLM ajouté.
Fin = gates verts + scores visibles sur une trace réelle (smoke avec vraies clés) + score-configs.json
et dashboard-b2c.json committés dans observability/langfuse/ + HANDOFF à jour + commit branche.
Jamais de merge.
```

## OBS4 — Trace distribuée A2A (fenêtre 3, **en parallèle d'OBS10** qui vit dans MCP_B2C)

```bash
cd ~/Projects/AgentB2C && git checkout main && git pull && git checkout -b obs4-trace-distribuee-a2a && claude --model claude-opus-5
```

```
Lis CLAUDE.md, HANDOFF.md, OBS2-LANGFUSE-BRIEF.md (§1.2 et §12.4), PLAN-OBS-LANGFUSE-2026-07-29.md,
puis phases/OBS4-trace-distribuee-a2a.md et exécute cette phase, dans ce périmètre exactement.
Une session OBS10 travaille EN PARALLÈLE dans un AUTRE repo (MCP_B2C) sur l'extraction du traceparent
côté serveur MCP : tu ne touches pas ce repo, mais tu DOIS produire et écrire le contrat d'injection
qu'elle consomme (où et sous quelle forme le traceparent W3C part dans le champ `_meta` de l'appel de
tool). Ta zone = libs/b2c_common/** + agents/**.
Règles : décide et DOCUMENTE le mécanisme de propagation (baggage vs contexte explicite dans le
DataPart A2A) avant de coder, avec une preuve, pas une intuition ; le baggage part dans tous les
headers sortants → identifiants opaques uniquement, jamais de PII ni de secret ; 1 trace = 1 tour et
1 session = 1 conversation (D-OBS-5) — pas de trace géante par conversation ; une feuille appelée
sans contexte amont doit rester lisible ; setup_langfuse AVANT l'import du module agent dans les
feuilles ; instrument_litellm=False dans les feuilles ; flush() jamais shutdown() dans les lifespans.
Preuve de fin : une seule trace par tour sur les DEUX chemins (façade /v3 et pilotage A2A), plus
aucune occurrence de langfuse.trace.input / langfuse.trace.name dans le code (grep = la preuve),
usage toujours compté 1×, vue Sessions toujours peuplée.
Fin = gates verts + HANDOFF à jour + commit branche. **Ta MR passe avant celle d'OBS10.** Jamais de
merge toi-même.
```

## OBS7 — Judges online + annotation queue (fenêtre 4, **en parallèle d'OBS5**)

```bash
cd ~/Projects/AgentB2C && git checkout main && git pull && git checkout -b obs7-judges-online && claude --model claude-sonnet-5
```

```
Lis CLAUDE.md, HANDOFF.md, OBS2-LANGFUSE-BRIEF.md (§5 et §6), PLAN-OBS-LANGFUSE-2026-07-29.md,
puis phases/OBS7-judges-online-annotation.md et exécute cette phase, dans ce périmètre exactement.
VÉRIFIE D'ABORD les 3 prérequis bloquants (ENCRYPTION_KEY posée, liste réelle des judges embarqués
dans le build, OBS4 mergée) : si l'un manque, STOP et rapport — ne contourne pas.
La décision D-OBS-4 est prise : judges managés avec une LLM Connection stockée dans notre Langfuse.
Ne rouvre pas le débat du pipeline externe.
Règles : le modèle juge DOIT supporter le tool calling ; sampling bas au départ (5-10 %) et coût
mesuré sur 24 h avant toute montée ; les tours taggés `synthetic` sont exclus ; observation-level
uniquement (les evaluators trace-level sont dépréciés) ; AUCUN appel LLM ajouté dans le chemin du
tour — le budget ≤ 3 appels/tour est intouchable ; valide le variable mapping sur la preview live
avant d'activer une règle.
Écris explicitement dans le HANDOFF que la clé du modèle juge envoie du contenu de message au
provider = extension du périmètre de traitement RGPD, à valider par moi avant activation en prod.
Fin = judges actifs sans erreur sur 24 h + queue alimentée + ≥ 10 traces annotées à la main + config
versionnée dans observability/langfuse/ + HANDOFF à jour + commit branche. Jamais de merge.
```

---

## Sessions à cadrer au lancement (fichier de phase à écrire)

**OBS5 — feedback 👍/👎** — fenêtre 4, **en parallèle d'OBS7**, dans un worktree
(`git worktree add ../AgentB2C-obs5 -b obs5-user-feedback` + `cp .env ../AgentB2C-obs5/.env` + venv),
Sonnet. Zone = `facade.py` + `web/**` ; interdit : `observability/langfuse/**` et `scripts/**` (zone
OBS7). Ordre de merge libre, aucun fichier commun.

```
Lis CLAUDE.md, HANDOFF.md, OBS2-LANGFUSE-BRIEF.md (§3), PLAN-OBS-LANGFUSE-2026-07-29.md.
Écris D'ABORD phases/OBS5-user-feedback.md (périmètre, étapes, DoD, pièges) et soumets-le moi avant
d'implémenter. Scope : exposer le trace_id du tour dans le SSE (progress ou done), puis un score
`user-feedback` BOOLEAN posté par le front avec la CLÉ PUBLIQUE SEULE — jamais de secret key dans le
navigateur. Le nom de score `user-feedback` a été réservé en OBS3.
```

**OBS8 — ClickHouse ≥ 25.12** (Railway, ops, jamais loop) :

```
Lis OBS2-LANGFUSE-BRIEF.md (§12.3) et PLAN-OBS-LANGFUSE-2026-07-29.md.
Objectif : upgrader ClickHouse de l'instance Langfuse à ≥ 25.12 (26.4 recommandé) EN RESTANT sur le
serveur v3 — c'est le seul prérequis bloquant de la v4, et il est découplable.
Instance PARTAGÉE avec d'autres producers Dayuse : tu écris le plan (backup, fenêtre, rollback,
communication) et tu me le soumets AVANT toute action. Aucune migration serveur v4 dans cette session.
```

**OBS9 — migration v4** (Railway + AgentB2C, Opus, GO par étape) — **ne lancer qu'une fois la v4
stable publiée** (au 2026-07-29 : `4.0.0-rc.3`, donc bloquée) :

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

**OBS10 — traceparent dans `_meta` des tools MCP** — fenêtre 3, **en parallèle d'OBS4** (repo
différent : aucune contention, aucun worktree). **Projet MCP_B2C**, Sonnet. Sa MR passe après celle
d'OBS4, qui produit le contrat d'injection côté client :

```bash
cd ~/Projects/MCP_B2C && git checkout main && git pull && git checkout -b obs10-mcp-tracing && claude --model claude-sonnet-5
```

```
Lis CLAUDE.md (MCP_B2C), docs/suivi-implementation.md, puis la référence Langfuse « MCP tracing »
(propagation du traceparent W3C via le champ `_meta` de l'appel de tool, exemple officiel
langfuse-examples/applications/mcp-tracing).
Objectif : le serveur MCP extrait le contexte OTel du champ `_meta` et rattache ses spans (dont les
requêtes Elasticsearch) à la trace du tour émise par AgentB2C. Écris d'abord le plan et soumets-le moi.
Contraintes du repo : TypeScript strict, aucun `any`, Zod sur toute entrée externe, Elasticsearch en
LECTURE SEULE, pas de PII ni de token dans les logs, couverture ≥ 80 %, et
`npm run lint:fix && npm run format && npm test` vert avant de conclure.
Le côté client (injection du traceparent dans `_meta`) appartient à AgentB2C : documente le contrat
attendu, ne le code pas ici.
```

---

## Mode LOOP — OBS2, OBS3, OBS6 (après la partie design faite en piloté)

Même mécanique que la série S-G (budget 15 itérations, tests = spec intouchable, jamais de push).
Prompt d'itération type (`prompts/loop-obs3.txt`, adapter le fichier de phase et la commande DoD) :

```
Lis CLAUDE.md, HANDOFF.md, puis phases/OBS3-scores-deterministes.md.
Prends LE PREMIER item de la phase non encore fait d'après HANDOFF.md. Implémente-le, LUI SEUL.
Interdictions : modifier un test existant (les tests sont la spec — un test qui te semble faux →
HANDOFF + stop) ; toucher hors zone autorisée ; git push. Les décisions D-OBS-1 à D-OBS-7 sont
arbitrées : ne les rouvre pas.
Fin d'itération : tests de la zone ; HANDOFF à jour (item fait/rouge + compteur) ; commit local
descriptif. Même test rouge 2 itérations de suite → n'insiste pas, documente et termine.
```

```bash
for i in $(seq 1 15); do
  claude -p "$(cat prompts/loop-obs3.txt)" --model claude-sonnet-5 --permission-mode acceptEdits
  bash -c '.venv/bin/pytest -q && bash scripts/dayuse_guardrails.sh .' && echo "DoD VERTE en $i itérations" && break
done
```

⚠️ **Jamais en loop** : OBS0, OBS8, OBS9 (production), OBS4 (design du contrat A2A), OBS7 (UI +
budget tokens réel), OBS5 (contrat front).
