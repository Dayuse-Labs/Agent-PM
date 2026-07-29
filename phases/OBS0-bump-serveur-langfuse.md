# OBS0 — Bump serveur Langfuse 3.205.1 → 3.224.2 + checklist UI

**Projet : Railway, projet `Langfuse`** (services `langfuse-web` + `langfuse-worker`). Aucun code
AgentB2C modifié, sauf la doc/HANDOFF en fin de session.
Modèle : Sonnet · **piloté, jamais loop** (production partagée).
Décisions : D-OBS-1, D-OBS-2 (cf. `PLAN-OBS-LANGFUSE-2026-07-29.md`).

## Pourquoi (ne pas re-litiger)

3.224.2 (2026-07-27) est une **release de backport de sécurité dédiée à la branche v3** :
`fix(api): stop logging public API request payloads` (des payloads d'API publique atterrissaient dans
les logs serveur → notre invariant RGPD), `fix(llm): require fresh secrets for base URL changes`,
`fix(auth): resolve API key scope from the verified key`. S'y ajoutent, dans notre plage de retard :
`fix(otel): serialize int64 fields as strings` (3.214.0 — **corruption de données pour tout ingesteur
OTLP, donc nous**), le traitement correct de `gen_ai.usage.input_cached_tokens` (3.208.0), la fin
d'une double-facturation de spans (3.206.0), le baggage préservé à travers `startNewTrace` (3.211.0 —
prérequis de fait pour OBS4) et `stop 35s max_execution_time from killing background-migration chunk
queries` (3.213.0 — prérequis de fait pour OBS9).

## Entrées à lire

`OBS2-LANGFUSE-BRIEF.md` §0 et §12 · `PLAN-OBS-LANGFUSE-2026-07-29.md` (décisions + questions
ouvertes Q1-Q5) · HANDOFF addendum 2026-07-28 (rollout OBS1, piège CLI Railway).

## Étapes

1. **Constat avant** : `curl -s https://<instance>/api/public/health` → attendre
   `{"status":"OK","version":"3.205.1"}`. Noter la valeur dans le rapport.
2. **Backup** : Postgres **et** ClickHouse de l'instance Langfuse. 3.223.0 ajoute des skip indexes
   ClickHouse sur `observations`/`traces`/`scores` → DDL automatique au boot, **premier démarrage plus
   long**. Sans backup, pas de bump : STOP.
3. **Épingler les tags** sur les deux services : `langfuse/langfuse:3` et `langfuse/langfuse-worker:3`
   (ou `3.224.2` exact). ⚠️ **Ne jamais laisser `latest`** : il basculera sur v4 à la GA.
   Piège CLI connu : `railway variables` (**pluriel**) — le singulier sort du vide silencieux.
4. **Redeploy web puis worker**, surveiller les logs de migration au boot. Le worker est
   indispensable (evaluators, exports, background migrations).
5. **Constat après** : `/api/public/health` → `3.224.2`. Puis vérifier qu'un tour réel s'ingère
   toujours : lancer un tour synthétique (`X-Dayuse-Synthetic`) contre la prod et le retrouver dans
   l'UI, session nommée `obs0-bump-check-01`, **zéro erreur d'export** dans les logs des 3 services
   AgentB2C.
6. **Checklist UI** (§11 du brief) — répondre par écrit, chaque réponse conditionne une session :
   1. Écran « Pick an Evaluator » : **liste exacte** des judges managés embarqués. Y a-t-il
      `User Distress`, `User Disagreement`, `Out-of-Scope Request`, `Hallucination` ? → **Q1, gate OBS7**
   2. `ENCRYPTION_KEY` posée sur l'instance ? → **Q3, bloquant OBS7** (pas de LLM Connection sans elle)
   3. `POST /api/public/mcp` avec un payload `initialize` → l'endpoint répond-il ?
   4. La barre de recherche des traces couvre-t-elle input/output, ou seulement id/name ?
   5. Écran Monitors : présent ? fonctionnel ? (la doc le dit v4-only — vérifier, pas parier)
   6. Politique de rétention globale configurée sur le projet ? → **Q4, dimensionne OBS9**
   7. `get_dataset(..., version=)`, « Fast Mode », backfill « Actions → Evaluate » depuis la table
      Traces : présents ? → périmètre OBS6/OBS7
7. **Rollback** si l'ingestion casse ou si l'UI est dégradée : re-pin `3.205.1` et redeploy. Les
   updates intra-majeure sont conçues non disruptives, mais le chemin de retour doit être écrit
   **avant** l'étape 4.

## DoD

- `/api/public/health` renvoie `3.224.2` sur l'instance, tags épinglés sur la ligne `:3` (capture ou
  sortie CLI dans le rapport).
- Un tour synthétique de prod visible dans l'UI après bump, zéro erreur d'export côté AgentB2C.
- **Les 7 points de la checklist répondus par écrit** dans le bloc HANDOFF daté + réponses reportées
  dans les questions ouvertes Q1-Q5 du plan.
- Tableau de suivi du plan mis à jour (OBS0 ✅ + date).

## Hors périmètre

- **Toute migration v4** (D-OBS-2 : la dernière v4 publiée est `4.0.0-rc.3`).
- L'upgrade ClickHouse (c'est OBS8, coordination Dayuse séparée).
- Toute modification de code AgentB2C.
- Configurer une LLM Connection (c'est OBS7, et ça dépend de Q3).

## Pièges

- `latest` pointe encore sur v3 aujourd'hui — donc « ne rien épingler » marche… jusqu'à la GA v4, où
  ça deviendrait une migration accidentelle en production. Épingler est le geste de la session.
- 3.208.0 fait de **Parquet le format par défaut** des exports blob. Sans objet chez nous (aucun
  export configuré) — le vérifier, ne pas le supposer.
- L'instance est **partagée avec d'autres producers Dayuse** : prévenir avant le redeploy.
