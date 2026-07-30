# OBS2 — Typage des observations, niveaux d'erreur, release, TTFT

**Projet : AgentB2C.** Zone : `libs/b2c_common/**` + `agents/**` (+ variables Railway).
Branche `obs2-typage-observations`. Modèle : Sonnet · piloté, loop possible une fois le typage posé.
Référence : `OBS2-LANGFUSE-BRIEF.md` §1. Décisions : D-OBS-5 (préparée ici, exécutée en OBS4).

## Problème traité

Aujourd'hui la trace d'un tour est correcte mais **non typée** : Langfuse voit tous nos spans comme
`span`/`generation`. Conséquences : **pas d'Agent Graph**, pas de filtre par nature d'étape, et aucune
distinction visuelle entre une dégradation et un tour normal.

## Entrées à lire

`OBS2-LANGFUSE-BRIEF.md` §1 · `libs/b2c_common/b2c_common/observability.py` (l'unique couture) ·
`agents/b2c_concierge/b2c_concierge/{facade,routing,tool_loop,leg,inline_tools,triage}.py` ·
`agents/hotel_search_agent/hotel_search_agent/{agent,geocode_tool}.py` · `agents/faq_agent/faq_agent/agent.py` ·
`libs/b2c_common/tests/test_observability.py` + `agents/b2c_concierge/tests/test_facade_langfuse.py`.

## Étapes

1. **Inventorier ce qu'ADK émet déjà AVANT d'ajouter un span.** Leçon OBS1 (usage compté 3×) :
   ADK produit `generate_content` et, selon les versions, ses propres spans d'exécution de tool. Faire
   tourner un tour réel, lister les spans obtenus, et **n'ajouter que ce qui manque**. Un span en
   double = du bruit et des agrégats faux. Documenter l'inventaire dans HANDOFF.
2. **Helpers dans `observability.py`** (une seule couture, opt-in, inertes sans clés) : un
   context manager `observation(as_type, name, **kw)` et un `mark_level(level, status_message)` qui
   ne lèvent jamais et sont des no-ops quand `_client is None`.
3. **Poser les types** — condition documentée de l'Agent Graph : la trace doit contenir au moins une
   observation d'un type autre que `span`/`event`/`generation`. Aucun attribut « graph » à poser,
   Langfuse infère depuis l'imbrication et les timings.
   - `agent` : spine `b2c-concierge`, `hotel-search-agent`, `faq-agent`
   - `tool` : les tools MCP consommés, Mapbox, les 3 tools inline (`get_hotel_details`,
     `compare_hotels`, `generate_booking_link`)
   - `chain` : la boucle `tool_loop`
   - `guardrail` : **les 12 guards** (le type existe littéralement pour ça)
   - `generation` : litellm — déjà couvert par l'instrumentor, ne rien ajouter
   Utiliser `as_type=` du SDK, **pas** l'attribut OTel brut : la table de mapping OTel ne documente
   encore que `span|generation|event`.
4. **Nommage stable** (ça conditionne durablement dashboards, evaluators et saved views) : verbe en
   tête (`classify-intent`, `search-offers`, `synthesize-answer`), **jamais de valeur dynamique** dans
   le nom (pas d'id, pas de ville), **jamais le nom du modèle**.
5. **`level` + `status_message`** sur chaque dégradation, pour qu'un filtre `level:ERROR` devienne la
   file de debug quotidienne :
   - `ERROR` : timeout feuille 10 s (dégradation honnête), circuit-breaker MCP ouvert, retry Mapbox
     épuisé, passage par `_shield_payload`
   - `WARNING` : un guard qui corrige (`status_message` = **nom du guard**, jamais un extrait de
     message utilisateur)
6. **`LANGFUSE_RELEASE` = sha git court** sur les 3 services Railway + documenté dans les
   `.env.example`. Permet de comparer un avant/après déploiement sur les mêmes métriques.
7. **TTFT mesuré en continu.** Cible : `completion_start_time` sur la generation de synthèse →
   mesure native `timeToFirstToken`. ⚠️ La generation est créée par l'instrumentor litellm, pas par
   nous : **vérifier la faisabilité d'abord**. Si on ne peut pas la renseigner proprement, **repli
   assumé** : la façade mesure déjà l'instant du frame `progress` → émettre un score NUMERIC
   `ttft_ms` (le mécanisme de score arrive en OBS3 ; ici, poser la mesure et le point d'émission).
   Documenter le choix retenu.
8. **`metadata` filtrable** : Langfuse ne filtre que sur les **clés de premier niveau**, et
   `propagate_attributes(metadata=...)` tronque les valeurs > 200 caractères. Poser : route de triage,
   feuille appelée, `llm_calls` du tour, état du circuit-breaker.
9. **Tests** : étendre `test_observability.py` (types posés, no-op sans clés, `mark_level` n'élève
   jamais) et `test_facade_langfuse.py`. Le verrou « inerte sans clés » doit rester vrai pour toute la
   suite offline.
10. **Vérification avec les vraies clés** (hors suite offline, comme en OBS1) : `bash
    scripts/run_local.sh` + `python scripts/smoke_e2e.py` puis `--contract`, session
    `obs2-check-01`, et **regarder l'UI** : Agent Graph présent, types corrects, aucun span orphelin,
    usage toujours compté **1×**.

## DoD

- `.venv/bin/pytest -q` · `ruff check .` · `mypy agents libs` · `bash scripts/dayuse_guardrails.sh .`
  → tous verts.
- Suite offline **toujours inerte sans clés** (aucun import langfuse, aucun réseau).
- Smoke local avec vraies clés : **Agent Graph visible**, un `ERROR` provoqué volontairement
  (timeout simulé) retrouvé par filtre, usage compté 1× (non régressé).
- `LANGFUSE_RELEASE` posée sur les 3 services + `.env.example` à jour.
- HANDOFF : bloc daté avec l'inventaire des spans ADK, le choix TTFT retenu, la liste des noms
  d'observations. Suivi du plan mis à jour.

## Hors périmètre

- Les **scores** (OBS3) — ici on ne fait que préparer le point d'émission du TTFT.
- La **trace distribuée A2A** (OBS4) : les feuilles restent dans leurs traces, groupées par session.
  Ne pas toucher `stamp_langfuse_session`, son retrait appartient à OBS4.
- Datasets, judges, dashboards.

## Pièges

- **Ne pas doubler les spans d'ADK** (étape 1). C'est exactement l'erreur qui avait triplé l'usage
  en OBS1.
- **Filtrer un parent en gardant ses enfants crée des observations orphelines** et casse le graphe :
  notre `_should_export_span` élargi au scope `gcp.vertex.agent` est là pour ça, ne pas le restreindre.
- Le filtre par défaut du SDK v4 est restrictif (scope `langfuse-sdk`, attributs `gen_ai*`, allowlist
  d'instrumenteurs) : un span typé posé par nos helpers passe, un span maison hors SDK peut être
  silencieusement droppé — vérifier dans l'UI, pas dans le code.
- `status_message` est du texte libre → **nom de règle uniquement**, jamais de contenu utilisateur.
