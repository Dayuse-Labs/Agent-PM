# OBS3 — Scores déterministes : les guards deviennent des séries mesurées

**Projet : AgentB2C.** Zone : `libs/b2c_common/**` + `agents/b2c_concierge/**` +
`observability/langfuse/**` (nouveau dossier). Branche `obs3-scores-deterministes`.
Modèle : Sonnet · loop possible. Référence : `OBS2-LANGFUSE-BRIEF.md` §2 et §8.
Décisions : D-OBS-6 (module unique de lecture), D-OBS-7 (pas d'alerting maison).

## Problème traité

On sait que les 12 guards existent (~150 tests). On ne sait pas **à quelle fréquence ils déclenchent
en prod**, ni combien de tours finissent avec une shortlist vide, ni combien dépassent le budget de
3 appels LLM. C'est exactement ce que l'audit 2026-06 réclamait et qu'aucun canal ne fournit
aujourd'hui. Coût de l'opération : **zéro appel LLM**.

## Entrées à lire

`OBS2-LANGFUSE-BRIEF.md` §2 et §8 · `libs/b2c_common/b2c_common/observability.py` ·
`agents/b2c_concierge/b2c_concierge/facade.py` (le span racine `v3.chat` / `v3.chat_stream`) ·
les 12 guards : `{amenity_guard,link_guard,budget,profile,ground_truth,tool_loop,routing}.py` +
leurs tests · `AUDIT-REWORK-2026-07.md` (la spec des guards).

## Étapes

1. **Figer les 12 noms de guards en UNE constante** — `GUARD_SCORE_NAMES` dans `b2c_common`, dérivée
   de la spec (tests portés + audit), en `snake_case` stable. Un nom de score est un contrat : il
   alimente des séries temporelles, le renommer casse l'historique. Les 12 doivent être exhaustifs et
   correspondre 1-pour-1 aux guards documentés, R9 (`generate_booking_link` sans flag de confirmation)
   inclus.
2. **Module d'émission** dans `observability.py` (ou un `scores.py` voisin), opt-in, jamais levant :
   - `guard_<nom>` : **BOOLEAN** (valeur `0`/`1`, **pas** `True`) — un score par guard par tour
   - `hotels_returned` : **NUMERIC** (nombre de cartes réellement rendues)
   - `empty_shortlist` : **BOOLEAN**
   - `llm_calls` : **NUMERIC** (verrou du budget ≤ 3)
   - `ttft_ms` : **NUMERIC** (le point d'émission a été posé en OBS2 si le chemin natif
     `completion_start_time` n'était pas praticable)
   - `degraded` : **BOOLEAN** ou CATEGORICAL (`leaf_timeout` / `mcp_circuit_open` / `mapbox_retry_exhausted` / `shield`)
3. **Brancher l'émission dans le span racine du tour** (`v3.chat` / `v3.chat_stream`) via
   `score_current_trace`, **après** que la réponse est connue. Un score peut être ingéré avant que la
   trace existe : ne jamais bloquer le stream pour scorer. Chemin A2A (batterie, smoke, peers) : même
   émission depuis le spine, idempotente avec la façade — comme `stamp_langfuse_turn_session`.
4. **Score configs** : créer les configs correspondantes (UI ou API) et passer `config_id`. Sans
   config, une catégorie n'a pas de mapping numérique et les séries sont inexploitables. Versionner
   les définitions dans `observability/langfuse/score-configs.json`.
5. **Module unique de lecture des métriques** (D-OBS-6) : `b2c_common/langfuse_metrics.py`, qui
   n'utilise que `langfuse.api.legacy.metrics_v1` / `observations_v1` (les défauts `api.metrics` /
   `api.observations` renvoient **404** sur serveur v3). Un seul fichier à migrer en v2 après OBS9.
   Y exposer 3-4 requêtes utiles : p95 TTFT, p95 latence par `name`, `count` par `level`, taux
   `empty_shortlist`.
6. **Un dashboard, exporté en JSON dans git** : `observability/langfuse/dashboard-b2c.json` (les
   widgets et dashboards s'exportent en `{"$langfuseWidget": true, ...}` → portable entre projets et
   instances). Contenu minimal : p95 TTFT, p95 latence par observation, `count` par `level`, taux de
   shortlist vide, 12 séries `guard_*`, tours à `llm_calls` > 3, coût par modèle.
7. **Tests** : émission no-op sans clés ; les 12 noms présents et stables (test de non-régression sur
   la constante) ; **aucun contenu de message** dans un `comment` (verrou RGPD, dans l'esprit des
   locks S3 de `test_spine.py`) ; l'émission n'élève jamais même si le client est cassé.
8. **Vérification réelle** : smoke local avec vraies clés, session `obs3-check-01`, puis dans l'UI :
   les scores apparaissent sur la trace, un guard volontairement déclenché passe à 1, le dashboard
   importé affiche les séries.

## DoD

- Gates verts : `pytest -q`, `ruff check .`, `mypy agents libs`, `dayuse_guardrails.sh`.
- 12 `guard_*` + `hotels_returned` + `empty_shortlist` + `llm_calls` visibles sur une trace réelle.
- `observability/langfuse/{score-configs.json,dashboard-b2c.json}` committés et réimportables.
- Une valeur chiffrée reportée dans le tableau « Résultats attendus » du plan (taux de shortlist vide
  et fréquence par guard sur les tours de smoke, en attendant 7 jours de prod).
- HANDOFF : bloc daté (noms figés, mécanisme d'émission, contraintes d'idempotence).

## Hors périmètre

- Tout **judge LLM** (OBS7) et tout dataset (OBS6).
- Le feedback utilisateur 👍/👎 (OBS5) — mais le nommage `user-feedback` est réservé dès maintenant.
- L'alerting (D-OBS-7 : monitors natifs en v4). Au plus, documenter la requête de métrique qu'un cron
  utiliserait — ne pas construire le cron.

## Pièges

- **`BOOLEAN` prend 0/1**, pas `True`. `TEXT` est exclu des experiments, des judges et des analytics :
  ne jamais l'utiliser pour du mesurable.
- **Idempotence** = `id` + `name` + `toDate(timestamp)` doivent **tous** correspondre. Même `id` avec
  un `name` différent → doublon, pas une mise à jour. Toujours renvoyer le score complet, jamais un
  patch partiel.
- **Tag vs score** : catégorie connue au tracing et immuable → tag (`synthetic`, déjà en place).
  Mesure ajoutable a posteriori → score. Ne pas transformer les scores en tags.
- **RGPD** : `comment` = identifiant de règle. Un extrait de message dans un commentaire de score
  violerait l'invariant « zéro contenu hors canal d'audit ».
- **v4** : `create_score` passe par `POST /api/public/ingestion`, dont le statut en v4 est
  contradictoire dans la doc (Q5 du plan). Ne pas s'en inquiéter maintenant, mais **isoler l'appel**
  dans une seule fonction pour que le test d'OBS9 soit trivial.
