# OBS6 — Datasets Langfuse + experiments + gate CI

**Projet : AgentB2C.** Zone : `evals/**` + `scripts/**` + `.github/**` + `evalset/**` (lecture).
Branche `obs6-datasets-experiments`. Modèle : Sonnet · loop possible.
Référence : `OBS2-LANGFUSE-BRIEF.md` §4. Décision : **D-OBS-3** (evaluators Python, pas de code
evaluators managés).
⚠️ Session **parallèle d'OBS2** (fenêtre 1) dans un worktree dédié. Zone interdite : `agents/**`,
`libs/**`. **OBS2 merge en premier** → rebase sur main fraîche avant la MR.
⚠️ **Contention de ports à régler en premier item** : `scripts/run_local.sh` code `8100-8102` en dur
et OBS2 occupe ce triplet. `scripts/` est ta zone → ajouter un `PORT_OFFSET` (défaut 0, comportement
inchangé sans la variable) et travailler sur `8110-8112` avec `CONCIERGE_URL=http://localhost:8110/`.
Prérequis réel : **OBS0 seulement** (l'agent est attaqué par la façade `/v3`, dont le contrat est
stable — le typage d'OBS2 n'est pas nécessaire).

## Problème traité

`adk eval` (32 scénarios, 8 familles) donne un score global à un instant donné. Il ne donne ni
comparaison de runs, ni historique, ni lien vers la trace de prod qui a motivé le cas. Les datasets
Langfuse ajoutent exactement ces trois choses, **à côté** du harnais existant — on ne remplace rien.

## Entrées à lire

`OBS2-LANGFUSE-BRIEF.md` §4 · `evalset/evalset-v0.adk.json` + `evalset/test_config.json` ·
`scripts/run_eval_adapter.py` et le pack `dayuse_eval_pack/` (**intouchable, byte-identique**) ·
`EVAL-PACK-COMPARISON-2026-07-22.md` · `.github/workflows/ci.yml` (job eval non bloquant).

## Étapes

1. **Un dataset hébergé par famille** (le `/` crée un dossier dans l'UI) : `b2c/geo`, `b2c/budget`,
   `b2c/multiturn`, … alignés sur les 8 familles de l'evalset. **Toujours un dataset hébergé** : un
   dataset local ne crée pas de `DatasetRun`, donc pas de vue de comparaison — c'est tout l'intérêt.
2. **Format d'item, verrouillé par `input_schema`** (JSON Schema côté Langfuse) :
   `input = {"messages": [...], "profile": {...}}`. Nos feuilles sont **stateless** (profil via
   `DataPart`) → sans le profil accumulé, le tour n'est pas reproductible. `expected_output` =
   assertions déterministes (ville/état attendus, `min_hotels`, guard attendu).
3. **`source_trace_id` sur chaque item importé depuis la prod** : c'est la boucle
   « échec observé → cas de régression ». Un script `scripts/langfuse_import_dataset.py` qui prend
   un `session_id` ou un filtre et fabrique les items.
4. **Pattern multi-tours = N+1** (approche officielle) : l'item porte l'historique **jusqu'au tour
   fautif**, la task rejoue et produit le tour N+1, un evaluator score cette réponse. Pas de type
   « conversation » dans Langfuse : c'est du JSON libre, la discipline est dans le schéma.
5. **`run_experiment` + evaluators Python** (D-OBS-3) : evaluators item-level (`geo_state_match`,
   `min_hotels_met`, `guard_expected_fired`) et run-level (moyennes). Concurrence bornée
   (`max_concurrency`), `metadata` du run = modèle + release (sha) pour retrouver le contexte.
6. **Gate CI** : job à côté du job `adk eval` existant. Deux voies, trancher et documenter :
   `pytest` + assert sur `result.run_evaluations` (le plus simple, cohérent avec nos gates), ou
   `RegressionError` + l'action `langfuse/experiment-action` (commente la MR avec les scores et le
   lien de comparaison). **Le job reste non bloquant au premier tour** — on pose la mesure avant de
   poser le seuil ; le seuil se fixe sur 2-3 runs de référence.
7. **`flush()` obligatoire** en fin de script : les runs d'eval sont des process courts, sans flush les
   données sont perdues.
8. **Rattacher des traces déjà émises** à un run (facultatif) : `api.dataset_run_items.create`.
   Fonctionne sur v3, **marqué deprecated en amont** → usage ponctuel, ne rien industrialiser dessus.

## DoD

- Gates verts : `pytest -q`, `ruff check .`, `mypy agents libs`, `dayuse_guardrails.sh`.
- ≥ 3 datasets hébergés peuplés (dont ≥ 5 items importés depuis de vraies traces avec
  `source_trace_id`), `input_schema` posé.
- **Deux runs comparés dans l'UI** (baseline + un run après changement volontaire), captures ou liens
  dans le rapport.
- Job CI présent, exécutable, **non bloquant**, avec les seuils écrits mais commentés + la méthode de
  fixation du seuil documentée.
- HANDOFF : bloc daté (familles couvertes, format d'item retenu, voie CI choisie).

## Hors périmètre

- **Le pack `dayuse_eval_pack/` reste byte-identique** (leçon S-G8 : toute annotation vit dans
  `scripts/`).
- `agents/**` et `libs/**` : zone OBS4, worktree parallèle. Un besoin dans le code applicatif →
  HANDOFF + STOP sur ce point.
- Judges LLM (OBS7) : ici, **evaluators déterministes uniquement**.

## Pièges

- **Dataset local ≠ dataset hébergé** : sans dataset hébergé, pas de `DatasetRun`, pas de comparaison.
  C'est l'erreur qui rendrait la session inutile.
- Un item multi-tours **sans le profil** ne reproduit pas le tour → faux échecs, et pire, faux succès.
- Ne pas dupliquer le harnais existant : les 12 guards restent couverts par `pytest` (spec exécutable).
  Les experiments mesurent la **qualité conversationnelle**, ce que les tests unitaires ne savent pas
  dire.
- Features récentes probablement absentes en 3.224.2 : `get_dataset(..., version=)`, « Fast Mode »,
  API `experiment-items`. **Vérifier avant de s'appuyer dessus** (checklist OBS0, point 7).
