# OBS2 — Exploiter Langfuse pour debugger et fiabiliser AgentB2C

Brief de cadrage, 2026-07-29. Suite d'OBS1 (tracing posé, cf. HANDOFF addendum 2026-07-28).
Chaque affirmation ci-dessous a été vérifiée contre la doc Langfuse de juillet 2026 **et** contre la
version réellement déployée (self-hosted **v3.205.1**, SDK Python **langfuse==4.14.1**).

---

## 0. Contraintes à connaître avant de planifier

**Licence — rien de ce qui suit ne coûte de licence.** Sur self-hosted, tout le produit est OSS/MIT
sans limite : LLM-as-a-judge, code evaluators, datasets & experiments, annotation queues, playground,
prompt management, dashboards custom, sessions, blob exports.
La clé EE ne débloque que de la gouvernance : RBAC au niveau projet, data retention policies, audit
logs, masking côté serveur, protected prompt labels, Admin/SCIM API. Vérifié dans le code du tag
`v3.205.1` (`entitlements.ts`) : le plan « self-hosted Pro » a exactement les mêmes droits qu'OSS.

**Version — v3.205.1 est sur la ligne OSS v3, dépréciée.** Ce qui est **v4-only** et donc indisponible
aujourd'hui :

| Feature | Statut sur notre instance | Repli |
|---|---|---|
| Monitors & alerts (seuils + Slack/webhook) | ❌ v4-only | cron externe sur Metrics API v1 → Slack |
| Metrics API v2 / Observations API v2 | ❌ | `langfuse.api.legacy.metrics_v1` / `observations_v1` |
| Full-text search sur input/output, Filter Search Bar, Pulse | ❌ (index texte ClickHouse ≥ 25.12) | filtres sidebar classiques |
| Blob export « enriched observations » (field group `tools`) | ❌ (layout legacy `traces/`+`observations/`) | consommateur legacy |

Le reste (observation types, agent graph, evaluators observation-level ≥ 3.153.0, scores API v3,
datasets/experiments, dashboards, playground, prompt management) **est présent en 3.205.1**.
Support sécurité de v3 : **jusqu'à fin janvier 2027** → la migration v4 est un chantier à planifier
(ClickHouse 24 → ≥ 25.12, ~½ journée, instance partagée avec d'autres producers Dayuse), pas une
urgence.

**Trois features exigent une clé LLM stockée *dans* Langfuse** (chiffrée par `ENCRYPTION_KEY`) :
Playground, LLM-as-a-judge, Prompt experiments. Un gateway OpenAI-compatible marche (provider
`OpenAI` + Base URL) **à condition qu'il supporte le tool calling** — Langfuse force un tool
`extract` pour parser `{score, reasoning}`. Décision à prendre (§5) : clé chez Langfuse, ou pipeline
d'éval externe qui garde la clé chez nous.

---

## 1. Debug profond — les 6 réglages qui changent tout (effort faible)

Aujourd'hui la trace d'un tour est une arborescence de spans corrects mais **non typés** : Langfuse
les voit tous comme `span`/`generation`. Conséquence : pas d'Agent Graph, pas de filtre par nature
d'étape, et les feuilles A2A vivent dans des **traces séparées** simplement groupées par session.

**1.1 Typer les observations → l'Agent Graph apparaît.** Condition d'affichage documentée, unique :
la trace doit contenir au moins une observation d'un type autre que `span`/`event`/`generation`.
Aucun attribut « graph » à poser, Langfuse infère le graphe de l'imbrication et des timings.

```python
from langfuse import get_client, observe
langfuse = get_client()

@observe(as_type="agent")          # spine b2c-concierge, feuilles
async def handle_turn(...): ...

with langfuse.start_as_current_observation(as_type="tool", name="search_offers") as obs:
    obs.update(input=params, output=res, metadata={"mcp": "MCP_B2C", "circuit": "closed"})
```

Mapping proposé : `agent` = concierge + `hotel-search-agent` + `faq-agent` · `tool` = les 6 tools MCP,
Mapbox, les 3 tools inline · `generation` = litellm (déjà) · **`guardrail` = les 12 guards** (le type
existe littéralement pour ça) · `chain` = `tool_loop`.
Types dispos : `event, span, generation, agent, tool, chain, retriever, evaluator, embedding, guardrail`.
Poser `as_type=` via le SDK plutôt que l'attribut OTel brut (la table de mapping OTel ne documente
encore que `span|generation|event` — probablement en retard, mais inutile de parier).

**1.2 Une seule trace par tour, traversant l'A2A.** Deux briques :

```python
# concierge, autour de l'appel de feuille
with propagate_attributes(session_id=sid, user_id=uid, environment=env, as_baggage=True):
    await call_leaf(...)

# feuille, à l'entrée
with langfuse.start_as_current_observation(
    as_type="agent", name="hotel-search-agent",
    trace_context={"trace_id": incoming_trace_id, "parent_span_id": incoming_span_id},
): ...
```

⚠️ `as_baggage=True` met le contexte dans **tous** les headers HTTP sortants → jamais de PII dedans
(ici uniquement des identifiants opaques : conforme). Recommandation Langfuse et la nôtre :
**1 trace = 1 tour, 1 session = 1 conversation** — pas de trace géante par conversation.
Pour voir aussi les requêtes ES de MCP_B2C dans la même trace : injecter le traceparent W3C dans le
champ **`_meta`** de l'appel de tool MCP et l'extraire côté serveur TS (exemple officiel
`langfuse-examples/applications/mcp-tracing`). Chantier séparé, dans le repo MCP_B2C.

**1.3 `level` + `status_message` sur les dégradations.** `DEBUG|DEFAULT|WARNING|ERROR`, filtrable.

```python
langfuse.update_current_span(level="ERROR", status_message="leaf timeout 10s — dégradation honnête")
langfuse.update_current_span(level="WARNING", status_message="guard=geocode_echo_back rejected mapbox hit")
```

Un filtre `level:ERROR` devient la file de debug quotidienne. À câbler sur : timeout feuille 10 s,
circuit-breaker MCP ouvert, retry Mapbox épuisé, guard qui corrige, shield `_shield_payload`.

**1.4 `environment` + `release` + `version`.** `LANGFUSE_TRACING_ENVIRONMENT` est déjà posé en prod ;
ajouter **`LANGFUSE_RELEASE` = sha git** sur les 3 services. Le filtre environment est global à
toutes les vues ; `release` permet de comparer un avant/après déploiement sur les mêmes métriques.

**1.5 TTFT devient une métrique native.** Poser `completion_start_time=datetime.now()` sur la
generation de synthèse → mesure `timeToFirstToken`, agrégeable en p95 dans la Metrics API et les
dashboards. C'est exactement le SLO « event `progress` < 300 ms » du CLAUDE.md, mesuré en continu
au lieu d'être vérifié au smoke.

**1.6 `metadata` utile et filtrable.** Langfuse ne filtre que sur les **clés de premier niveau**, et
`propagate_attributes(metadata=...)` tronque les valeurs > 200 caractères. À poser : route de triage,
feuille appelée, `llm_calls` du tour, état du circuit-breaker, `is_synthetic` (déjà en tag).

**Bonus disponible si besoin plus tard** : `mask_otel_spans` (hook d'export, agit sur les attributs
OTel bruts — donc couvre litellm/ADK, ce que l'ancien hook `mask` ne fait pas) si on veut un jour
réduire le contenu exporté sans désinstrumenter. Et `LANGFUSE_SAMPLE_RATE` (décision au niveau trace)
si le volume devient un sujet.

---

## 2. Scores déterministes — le meilleur ROI, zéro appel LLM

C'est le chaînon manquant entre l'audit 2026-06 et la prod : aujourd'hui on sait qu'un guard existe,
on ne sait pas **à quelle fréquence il déclenche en vrai**. Un score est une valeur attachée à une
trace/observation/session/dataset-run, ingérable même **avant** que la trace arrive.

```python
lf = get_client()
# état du tour
lf.score_current_trace(name="hotels_returned", value=float(len(hotels)), data_type="NUMERIC")
lf.score_current_trace(name="empty_shortlist", value=1 if not hotels else 0, data_type="BOOLEAN")
lf.score_current_trace(name="llm_calls", value=float(n_llm), data_type="NUMERIC")  # budget ≤ 3
# un score par guard → une série temporelle par guard
for g in GUARDS:  # 12 noms stables
    lf.score_current_trace(name=f"guard_{g}", value=1 if g in fired else 0, data_type="BOOLEAN")
```

Détails qui évitent des pièges :

- `BOOLEAN` prend **0/1**, pas `True`. Types : `NUMERIC`, `CATEGORICAL`, `BOOLEAN`, `TEXT` (`TEXT`
  est exclu des experiments, du judge et des analytics — ne pas l'utiliser pour du mesurable).
- Créer des **score configs** (UI ou API) et passer `config_id` : validation min/max/catégories, et
  c'est ce qui rend les séries propres dans les dashboards et utilisables en annotation queue.
- **Idempotence** = `id` + `name` + `toDate(timestamp)` doivent tous correspondre. Même `id` avec un
  `name` différent → doublon, pas une mise à jour. Toujours renvoyer le score complet.
- Hors contexte (job, réponse déjà streamée) : `lf.create_score(trace_id=..., score_id=f"{tid}-guard_r9", ...)`.
- **Tag vs score** : catégorie connue au moment du tracing et immuable → tag (`synthetic`). Mesure
  ajoutable a posteriori → score.
- **RGPD** : `comment` est du texte libre → identifiants de règle uniquement, jamais d'extrait de
  message (l'invariant « zéro contenu dans les métriques » s'applique aussi aux scores).

Sortie attendue : dashboard « taux de shortlist vide », « fréquence de déclenchement par guard »,
« tours à > 3 appels LLM », « boucle de clarification détectée » — les 4 chiffres que l'audit
réclamait et qu'on n'a pas aujourd'hui.

---

## 3. Feedback utilisateur 👍/👎 rattaché au tour

Exposer le `trace_id` du tour dans l'event SSE (`progress` ou `done`), le front poste un score avec
**la clé publique seule** (`@langfuse/browser`, `score()` part immédiatement, pas de flush) :

```ts
await langfuse.score({ traceId, id: `user-feedback-${traceId}`, name: "user-feedback",
                       value: 1, dataType: "BOOLEAN", comment });
```

Jamais de secret key dans le navigateur. C'est aussi la source d'alimentation de l'annotation queue (§6).
Exemple complet : `langfuse-examples/applications/user-feedback`.

---

## 4. Évals offline — datasets + experiments (à côté de `adk eval`)

L'evalset ADK (32 scénarios, 8 familles) donne un score global ; les datasets Langfuse donnent la
comparaison de runs, l'historique et le lien vers la trace prod d'origine.

```python
langfuse.create_dataset(name="b2c/geo", input_schema={...})   # le "/" fait un dossier dans l'UI
langfuse.create_dataset_item(
    dataset_name="b2c/geo",
    input={"messages": [...], "profile": {...}},      # multi-tours : historique + profil accumulé
    expected_output={"state": "CT", "min_hotels": 1},
    metadata={"guard": "state_anchored_geocoding"},
    source_trace_id=trace_id,                          # ← la boucle prod → dataset
)

result = langfuse.get_dataset("b2c/geo").run_experiment(
    name="ph2-baseline", task=task,
    evaluators=[geo_state_match], run_evaluators=[avg_geo], max_concurrency=5,
    metadata={"model": "gpt-4o-mini", "release": sha},
)
```

- **Toujours un dataset hébergé** : un dataset local ne crée pas de `DatasetRun`, donc pas de vue de
  comparaison.
- **Multi-tours** : pas de type « conversation ». Le pattern officiel est **N+1** — l'item porte
  l'historique jusqu'au tour fautif, la task rejoue et produit le tour N+1, un evaluator score la
  réponse. Nos feuilles étant stateless (profil via `DataPart`), l'item **doit** porter l'historique
  *et* le profil, sinon le tour n'est pas reproductible. `input_schema` (JSON Schema) verrouille ça.
- **Evaluators SDK (fonctions Python) plutôt que code evaluators managés** : les managés tournent
  dans un runtime sans dépendances tierces, sans réseau, timeout 2 s, et exigent
  `LANGFUSE_CODE_EVAL_DISPATCHER` — sur Railway seul `insecure-local` (TS, non sandboxé) serait
  possible. Incompatible avec notre posture zéro-lock-in : on garde les evaluators en Python, en git.
- **Gate CI** : `RegressionError` + `langfuse/experiment-action` (commente la MR avec les scores et
  le lien de comparaison), ou plus simple chez nous : `pytest` + assert sur `result.run_evaluations`,
  à côté du job `adk eval` existant.
- Rattacher une trace **déjà émise** à un dataset run : `langfuse.api.dataset_run_items.create(...)`
  (l'endpoint est marqué deprecated sur `main` mais c'est ce que `run_experiment` utilise en interne
  — utilisable, à ne pas industrialiser).

---

## 5. Évals online (LLM-as-a-judge) — utile, mais une décision à prendre

Côté serveur, à l'ingestion : filtres → file → job worker → **un score par observation par
evaluator**. Hors de notre budget « ≤ 3 appels LLM/tour » (c'est le worker Langfuse qui paie la
latence), mais ça consomme des tokens.

Trois prérequis non négociables :

1. Une **LLM Connection** dans le projet (clé stockée chez Langfuse) et un modèle qui supporte le
   **structured output / tool calling**.
2. Une **observation racine par tour portant l'input utilisateur ET la réponse finale complète** —
   un evaluator observation-level **ne voit ni les enfants ni les sœurs**. Notre span `v3.chat` fait
   déjà ça pour la façade ; à vérifier sur le chemin A2A (batterie, smoke, peers).
3. `propagate_attributes()` pour que `session_id`/`user_id`/`tags`/`version` soient **sur chaque
   span** : sans ça, un evaluator filtré sur des attributs de trace ne matchera aucune observation.
   Les evaluators **trace-level sont dépréciés** → câbler directement en observation-level.

Judges managés pertinents pour nous (11 maintenus par Langfuse + ~12 Ragas) : **`User Distress`,
`User Disagreement`, `Out-of-Scope Request`** — BOOLEAN, conversation-level : littéralement nos
boucles de clarification, nos villes non couvertes et la frustration utilisateur. Puis `Hallucination`
et `Relevance` sur l'observation racine. Sampling par evaluator (tirage indépendant : deux evaluators
à 5 % ne notent pas le même sous-ensemble — pour co-scorer, 100 % + un tag posé par notre code).
Debug : chaque exécution de judge crée sa propre trace, filtrable sur l'environnement
`langfuse-llm-as-a-judge`.

**Alternative sans clé LLM chez Langfuse** : pipeline d'éval externe — un job lit les traces via
l'API, calcule ce qu'il veut (n'importe quelle lib, notre propre clé), et réinjecte des scores.
Chemin documenté et supporté. Plus de code, mais la clé reste chez nous et on garde LiteLLM comme
unique porte de sortie modèle (invariant CLAUDE.md).

---

## 6. Annotation queues (OSS, gratuit)

File d'annotation humaine sur des dimensions définies par des score configs, raccourcis clavier,
**corrected outputs** (« ce que l'agent aurait dû répondre »). Deux usages concrets :
alimenter automatiquement la queue avec les traces `empty_shortlist=1` ou `user-feedback=0` (API
annotation-queues), puis **calibrer les judges** sur le jugement humain et convertir les corrections
en items de dataset.

---

## 7. Prompt management (optionnel, à arbitrer)

Sortir les instructions du code pour les versionner dans Langfuse donne : labels `prod`/`latest`,
A/B par label, **métriques par version de prompt** (latence, tokens, coût, scores médians).
Le lien trace ↔ version marche sans `langfuse.openai` grâce à `propagate_attributes(prompt=prompt)`
(SDK ≥ 4.14.0 — on est en 4.14.1 ✓). Cache local 60 s avec revalidation en arrière-plan (fetch
médian ~37 ms, p99 ~69 ms).
Réserves : `get_prompt()` **lève** si aucun cache et réseau HS → il faut un pré-fetch au boot ou un
`fallback=` (mais un prompt fallback **ne crée aucun lien trace↔prompt**), et un pré-fetch est un
appel réseau au boot — à arbitrer contre l'invariant « aucun appel LLM/MCP au boot ». Faible priorité
tant que les prompts bougent par MR.

---

## 8. Dashboards, métriques, alerting

- **Dashboards custom** : widgets sur `traces` / `observations` / `scores`, **exportables en JSON**
  (`{"$langfuseWidget": true, ...}`) → versionnables en git, réimportables. Dashboards curated
  Latency/Cost/Usage déjà fournis.
- **Metrics API v1** (`langfuse.api.legacy.metrics_v1`) : agrégations jusqu'à `p99`, mesures
  `latency`, `timeToFirstToken`, `totalTokens`, `totalCost`, dimensions `name`, `level`, `type`,
  `promptVersion`, `sessionId`, `environment`, `traceRelease`… + `GET /api/public/metrics/daily`.
- **Alerting** : v4-only. En attendant, un petit cron (p95 TTFT, `count` de `level:ERROR`, taux
  `empty_shortlist`) → Slack. À ne pas sur-investir : ça devient natif à la migration v4.
- **Coûts** : si un modèle n'est pas reconnu, définir un prix custom (Project Settings → Models,
  match par regex). Attention, un changement de prix ne s'applique **qu'aux nouvelles générations**.

---

## 9. Debugger depuis Claude Code

Langfuse expose un **MCP server** : `https://<instance>/api/public/mcp`, transport streamable-http,
Basic auth base64 `pk:sk` (clé project-scoped). ⚠️ tools de **lecture et d'écriture** actifs par
défaut → allowlist read-only côté client, cohérent avec notre posture HITL. Derrière le proxy
Railway, prévoir `LANGFUSE_MCP_ALLOWED_HOSTS` (sinon 403).
**Incertitude** : aucune version serveur minimale documentée, et les tools s'appuient probablement
sur les read APIs v2 (absentes en OSS v3) → sur 3.205.1, compter de façon fiable sur les tools
**prompts** uniquement. Un `POST /api/public/mcp` avec `initialize` tranche en 2 minutes.

---

## 10. Séquencement proposé

| Session | Contenu | Effort | Valeur |
|---|---|---|---|
| **OBS2** | §1 (types d'observation + `level`/`status_message` + `release` + `completion_start_time`) et §2 (scores déterministes guards/hotels/llm_calls + score configs) + 1 dashboard exporté en git | ~1 j | ⭐⭐⭐ debug immédiat, premières séries prod |
| **OBS3** | §1.2 trace distribuée A2A (baggage + `trace_context`) et §3 feedback 👍/👎 | ~½ j | ⭐⭐⭐ une trace = un tour, bout en bout |
| **OBS4** | §4 datasets depuis la prod (`source_trace_id`) + experiments + gate CI | ~1,5 j | ⭐⭐⭐ non-régression mesurée |
| **OBS5** | §5 online judges (après décision clé LLM) + §6 annotation queue | ~1 j | ⭐⭐ qualité conversationnelle |
| **OBS6** | migration serveur v4 (ClickHouse ≥ 25.12) → monitors/alerts, full-text search, Metrics v2 | ~½ j + coordination | ⭐⭐ à faire avant fin janv. 2027 |
| plus tard | §7 prompt management, traceparent dans `_meta` MCP_B2C (repo MCP_B2C) | — | ⭐ |

## 11. À vérifier dans l'UI (15 min, avant de planifier OBS4/OBS5)

1. Écran « Pick an Evaluator » : quels judges managés sont réellement embarqués dans notre build ?
2. `get_dataset(name, version=...)`, « Fast Mode », backfill « Actions → Evaluate » depuis la table
   Traces : présents ou non (features récentes, probablement absentes en 3.205.1).
3. `POST /api/public/mcp` avec `initialize` → l'endpoint existe-t-il ?
4. La barre de recherche des traces couvre-t-elle input/output, ou seulement id/name ?
5. Écran Monitors : présent (le code 3.205.1 contient la page) mais fonctionnel ? La doc dit non.
6. `ENCRYPTION_KEY` est-il posé sur l'instance ? Prérequis pour stocker une LLM Connection.

---

## 12. Faut-il mettre à jour le serveur ? (vérifié le 2026-07-29)

Instance interrogée en direct : `GET /api/public/health` → `{"status":"OK","version":"3.205.1"}`.

**Oui pour un refresh mineur v3 — non pour la v4.**

**12.1 Bump 3.205.1 → 3.224.2 (2026-07-27) : recommandé, avant OBS2.** Zéro changement de code.
Motivations, toutes dans notre plage de retard (19 releases, 22 jours) :

- **3.224.2 est une release de backport de sécurité dédiée à la branche v3** : `fix(api): stop
  logging public API request payloads` (des payloads d'API publique atterrissaient dans les logs
  serveur → directement notre invariant RGPD), `fix(llm): require fresh secrets for base URL changes`
  (même surface que CVE-2026-41487), `fix(auth): resolve API key scope from the verified key`.
  Aucun CVE publié n'affecte 3.205.1, mais Langfuse patche désormais v3 par backports sans CVE.
- **3.214.0 `fix(otel): serialize int64 fields as strings, not protobufjs Long internals`** — bug de
  corruption de données **pour tout ingesteur OTLP, donc nous**.
- **3.208.0** `gen_ai.usage.input_cached_tokens` traité comme cache-read (coûts/usage faux) et
  **3.206.0** double-facturation de spans d'agents — la suite du chantier « usage compté 3× » d'OBS1.
- **3.211.0** baggage OTel préservé à travers `startNewTrace` + prompts liés aux seules generations →
  prérequis de fait pour §1.2 (baggage A2A) et §7 (link prompt↔trace).
- **3.213.0** `stop 35s max_execution_time from killing background-migration chunk queries` →
  prérequis de fait si on visait un jour le backfill v4.

Précautions : **épingler `langfuse/langfuse:3` et `langfuse-worker:3`** (ou `3.224.2` exact) — `latest`
basculera sur v4 à la GA ; backup Postgres + ClickHouse (3.223.0 ajoute des skip indexes ClickHouse,
premier boot plus long) ; 3.208.0 fait de **Parquet le format d'export blob par défaut** (sans objet
chez nous, aucun export configuré).

**12.2 v4 : ne pas y aller maintenant.** Vérifié le 2026-07-29 : la dernière v4 publiée est
**`4.0.0-rc.3`** (2026-07-27) — les 4 tags `4.0.0*` sont tous des RC, et les tags flottants `latest`,
`3` et `3.224` résolvent le même digest, donc **`latest` pointe encore sur v3**. Position officielle :
« *the recommendation is to hold off from Langfuse v3 → v4 migrations in production environments until
a stable release is published* » ; le self-hosted v4 est « on the way, exact dates will follow ».
L'étiquette « v3 Deprecated / v4 GA » de la matrice reflète le **Cloud**, pas le self-hosted.
**v3 est patché jusqu'à fin janvier 2027** → fenêtre confortable, mais la migration doit être faite
avant.

**12.3 La seule préparation qui vaut le coup dès maintenant : ClickHouse.** v4 exige **ClickHouse
≥ 25.12 (26.4 recommandé)**, et *« Langfuse v3 releases are fully compatible with current ClickHouse
versions »* → on peut upgrader ClickHouse **en restant sur v3**, découplé, sans risque de migration.
C'est le seul prérequis bloquant. Instance partagée avec d'autres producers Dayuse → coordination.
Aucun nouveau composant d'infra en v4 (même web/worker/PG/CH/Redis/S3).
Bonus : si une **politique de rétention globale** est configurée, on peut sauter entièrement le
backfill historique (mode `dual` pendant une fenêtre de rétention) et éviter sa contrainte de **3× le
volume disque ClickHouse**.

**12.4 Est-ce que ça remet en cause l'implémentation OBS1 ? Non — et OBS3 supprime au passage la
seule surface dépréciée.** Points vérifiés :

| Élément de notre code | v3.224.2 | v4 |
|---|---|---|
| Ingestion OTLP `/api/public/otel/v1/traces` | inchangé | **inchangé** |
| `should_export_span` élargi au scope `gcp.vertex.agent` | inchangé | inchangé (100 % client-side, et le filtre par défaut du SDK v4 reste restrictif → notre élargissement reste nécessaire) |
| `propagate_attributes` dans `turn_observation` | inchangé | c'est **la** seule API restante (`update_current_trace` a déjà disparu du SDK 4.14.1) |
| `ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN=2`, `instrument_litellm=False` | inchangé | inchangé (choix client) |
| `flush()` jamais `shutdown()` dans les lifespans | inchangé | inchangé |
| **`stamp_langfuse_session` : attributs `langfuse.trace.input` / `.name`** | OK | ⚠️ **`langfuse.trace.input/output` dépréciés** (l'IO remonte sur la root observation) |
| `create_score` (OBS2) — passe par `POST /api/public/ingestion`, pas `/scores` | OK | ⚠️ **contradiction documentaire** : la matrice marque `/ingestion` « Unsupported » en v4, le guide de migration dit « score writes unaffected ». **À tester avant la migration.** |
| Lectures Metrics/Observations (cron alerting §8) | `api.legacy.metrics_v1` obligatoire | v1 → **404** en mode `events_only`, passer en v2 |
| `api.dataset_run_items.create` (rattacher une trace existante, §4) | fonctionne | **404** en `events_only`, remplacé par `/experiments` |

Trois règles de conception à appliquer dès OBS2 pour ne pas créer de dette :

1. **§1.2 (trace distribuée A2A) rend `stamp_langfuse_session` obsolète** : dès que la feuille rejoint
   la trace du concierge via `trace_context`, elle porte une observation `agent` avec son propre
   input/output et il n'y a plus de `langfuse.trace.*` à stamper. Faire OBS3 = solder la dette v4.
2. **Isoler toute lecture de métriques dans un seul module** (`metrics_v1` aujourd'hui, `v2` demain) —
   la migration devient un fichier, pas une chasse.
3. **Ne pas sur-investir l'alerting maison** (§8) : les monitors natifs arrivent avec la v4.

**Séquence retenue** : bump 3.224.2 (pin `:3`) → OBS2 → OBS3 → upgrade ClickHouse ≥ 25.12 en restant
sur v3 → v4 dès la GA stable, avant fin janvier 2027 → monitors natifs.

---

### Sources principales

Observation types · Agent Graphs · Log Levels · Metadata · MCP Tracing · Sessions · Distributed
Tracing · Environments · Releases & Versioning · Custom Dashboards · Metrics API · Monitors ·
Scores (data model, API v3) · Datasets & Experiments · Experiments via SDK · Experiments CI/CD ·
Multi-turn evaluation cookbook · LLM-as-a-judge · Annotation Queues · Prompt link-to-traces ·
Caching · Guaranteed Availability · Playground · Public API · Blob Storage Export · MCP Server ·
Sampling · Masking · Token & Cost Tracking · Best Practices · Self-hosting license-key ·
pricing-self-host · versioning matrix · upgrade v3→v4 — tous sur https://langfuse.com,
+ code `langfuse@v3.205.1` (`entitlements.ts`, `managed-evaluators.json`).
