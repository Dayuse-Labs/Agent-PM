# OBS4 — Contrat de propagation de trace (A2A + MCP)

**Décision arbitrée le 2026-07-30, session OBS4, branche `obs4-trace-distribuee-a2a`.**
Implémente **D-OBS-5** (`PLAN-OBS-LANGFUSE-2026-07-29.md`) : *1 trace = 1 tour, 1 session = 1
conversation*. Référence : `OBS2-LANGFUSE-BRIEF.md` §1.2 et §12.4.

Ce fichier est le **contrat consommé par la session OBS10** (repo MCP_B2C) : §3 dit exactement où et
sous quelle forme le traceparent W3C part dans le champ `_meta` d'un appel de tool MCP, §4 dit ce que
le serveur doit en faire.

Versions contre lesquelles tout ci-dessous a été vérifié : `langfuse==4.14.1` (client Python),
serveur Langfuse **3.224.3**, `google-adk==2.4.0`, `a2a-sdk==0.3.26`, `mcp==1.28.1`,
`opentelemetry-*==1.42.1`.

---

## 1. Le mécanisme retenu, et pourquoi l'autre est structurellement impossible

Deux voies étaient ouvertes par le brief §1.2. **Retenu : le contexte W3C dans les en-têtes HTTP,
extrait au bord ASGI de la feuille.** Pas par préférence : l'autre voie ne peut pas marcher.

### 1.1 Preuve que la voie « contexte explicite dans le `DataPart`/metadata A2A » ne peut pas donner une trace par tour

On envoie déjà `dayuse_trace_id` dans la metadata A2A (`a2a_request_meta_provider`, `agent.py`), et la
feuille la lit dans `before_agent_callback` (`callback_context.run_config.custom_metadata`). Tentant
d'y ajouter `trace_id`/`span_id` et d'ouvrir l'observation de feuille avec
`trace_context={"trace_id": …, "parent_span_id": …}`.

**Ça produit deux traces, pas une.** Le point de lecture le plus précoce de la metadata A2A est un
callback ADK, et à cet instant les spans racines d'ADK (`invoke_workflow` puis `invoke_agent`) sont
**déjà créés** : leur `trace_id` est immuable. Une observation ouverte avec un `trace_context`
explicite vivrait donc dans la trace du concierge tandis que **tout le sous-arbre ADK autour d'elle
(les 2 générations, les 3 à 5 spans de tools MCP/Mapbox) resterait dans une trace séparée**. On
passerait de 2 traces à 3.

Pour rattacher les spans ADK, il faut que le contexte OTel soit **actif avant** qu'ADK ne crée son
span d'invocation. Le seul point d'interception situé avant, c'est la couche ASGI — qui voit les
**en-têtes**, pas la metadata A2A (elle est dans le corps JSON-RPC). D'où le choix.

### 1.2 Ce qui manquait réellement sur le saut A2A (vérifié, pas supposé)

```
grep -rn "propagate|inject|traceparent" google/adk/agents/remote_a2a_agent.py \
    a2a/client/transports/*.py a2a/client/base_client.py google/adk/a2a/   →  0 occurrence
```
Ni `RemoteA2aAgent` (côté client) ni l'app A2A d'ADK / le `a2a-sdk` (côté serveur) ne touchent au
contexte de trace. **Les deux moitiés manquaient** : on injecte côté concierge, on extrait côté
feuille. Rien à désactiver, aucun doublon possible.

### 1.3 Le baggage n'est pas un bonus « attributs » : il est requis pour la correction de l'arbre

`langfuse/_client/span_processor.py::_mark_app_root_candidate` décide quel span porte
`langfuse.internal.is_app_root` (la racine applicative de la trace, celle dont l'input/output
remonte au niveau trace) :

```python
suppressed_by_parent_claim = propagated_trace_id == trace_id      # ← lu dans le BAGGAGE
mark_app_root = (expected_exported and is_app_root_eligible(span)
                 and not parent_expected_exported          # ← faux : le parent est REMOTE
                 and not suppressed_by_parent_claim)
```
Dans la feuille, le span parent est distant : il n'est pas dans la table locale
`_span_export_expectation_by_id`, donc `parent_expected_exported` est **faux**. Sans l'entrée de
baggage `langfuse_trace_id`, la feuille **revendiquerait une seconde racine applicative sur la même
trace**. Avec elle, `suppressed_by_parent_claim` est vrai et la revendication est supprimée — c'est
exactement le cas cross-service prévu par le SDK.

Le SDK pose cette entrée lui-même dès qu'un de SES spans est actif
(`client.py::_start_as_current_otel_span_with_processed_media` → `_set_langfuse_trace_id_in_baggage`
+ `attach`), donc le chemin façade `/v3` (où `turn_observation` ouvre un span Langfuse) l'a
gratuitement. On la pose **explicitement** en plus, pour couvrir le chemin **piloté en A2A**
(batterie d'éval, smoke, peers) où seuls des spans ADK existent.

**Conclusion : les deux voies ne sont pas alternatives — traceparent ET baggage voyagent ensemble,
dans le même en-tête HTTP, par une seule injection.** Le propagateur global OTel par défaut est
`CompositePropagator(fields={'traceparent', 'tracestate', 'baggage'})` (vérifié en process, aucun
`OTEL_PROPAGATORS` posé) : un seul `inject()` écrit les trois.

### 1.4 Ce que le baggage transporte en plus (attributs)

`turn_observation` passe désormais `as_baggage=True` sur `propagate_attributes` — mais **seulement
pour `session_id` et `user_id`**. `as_baggage` est un drapeau par appel, pas par champ : les `tags` et
la `metadata` du tour (`turn_index`, `locale`, `currency`, `domain`) sont donc posés par un **second
`propagate_attributes` imbriqué sans baggage**, et ne quittent jamais le process.

Côté feuille, `LangfuseSpanProcessor.on_start` lit le baggage entrant
(`_get_propagated_attributes_from_context`) et applique `session.id` / `user.id` à **chaque** span
qu'elle crée — donc les observations de feuille sont agrégables par session/user sans une ligne de
code de notre côté.

### 1.5 Règle de sécurité (D7 + RGPD)

Le baggage part dans des en-têtes HTTP en clair. Deux garde-fous :

1. **Identifiants opaques uniquement** : ids de trace/span, `session_id` (id de conversation généré
   par le client), `user_id` = `v3_<session_id>` (`facade.py::_user_id`). **Jamais de contenu de
   message, jamais de secret, jamais de PII.**
2. **Injection à deux points nommés seulement**, jamais via une instrumentation httpx globale
   (`HTTPXClientInstrumentor`) : le hook de requête du client httpx de la jambe A2A, et le client MCP
   inline. **Mapbox et tout futur tiers ne reçoivent donc rien** — c'est la raison technique de ne
   pas instrumenter globalement, pas une préférence de style.

Réseau privé Railway + bearer statique (D7) : acceptable comme aujourd'hui, avec la même échéance
(bascule oidc-mtls avant le canary S11).

---

## 2. Ce qui est implémenté côté AgentB2C (zone `libs/b2c_common/**` + `agents/**`)

| Où | Quoi |
|---|---|
| `b2c_common.observability.trace_context_carrier()` | **La forme du contrat** : rend le carrier plat `{"traceparent": …, "baggage": …}` du span actif (+ l'entrée `langfuse_trace_id`). `{}` si tracing désactivé ou aucun span actif. Ne lève jamais. |
| `b2c_concierge.agent._inject_trace_context` | `event_hooks={"request": …}` du client httpx de chaque jambe A2A → les en-têtes sortants portent le carrier. |
| `b2c_common.observability.A2aTurnObservation` | Middleware **ASGI pur** (précédent `BearerAuthMiddleware`) : `extract()` + `attach()` du contexte amont, puis ouvre l'observation **racine** du service (`a2a.<agent_name>`). POST seulement (le GET de l'agent card n'ouvre pas de trace). Toujours **sous** le gate D7 : un appel non authentifié n'ouvre pas de trace. Monté sur toute l'app des 2 feuilles, et sur la **seule surface A2A** du concierge (`/v3/*` a déjà sa racine, `turn_observation` — un 2e wrapper au-dessus lui volerait son nom et son input). |
| `b2c_common.observability.stamp_a2a_turn` | `before_agent_callback` des 2 feuilles — **remplace `stamp_langfuse_session`** : pose l'input de l'observation racine + `langfuse.session.id`. Plus aucun `langfuse.trace.input` / `langfuse.trace.name` (dette v4 soldée, verrouillée par `test_no_deprecated_trace_attributes.py`). |
| `b2c_common.observability.mark_a2a_turn_output` | Appelée depuis `agent.py::_final` (l'entonnoir unique de TOUT événement terminal du concierge) : donne son output à la trace du chemin A2A, qui n'en avait aucun avant. No-op sur le chemin façade. |
| `b2c_common.observability._should_export_span` | Élargi au scope **`a2a-python-sdk`** — voir §2.1, découverte de la vérif live. |
| `b2c_concierge.inline_tools._call_tool` | `session.call_tool(..., meta=trace_context_carrier() or None)` → §3. |

### 2.1 Une trace ≠ un arbre : le trou trouvé en vérifiant en live

Premier tour réel après le câblage : **une seule trace** (objectif atteint) mais **trois observations
racines** — `v3.chat`, `invoke_workflow b2c_hotel_search` et notre `a2a.b2c_hotel_search` côte à côte,
au lieu d'un seul arbre. Donc pas d'arête concierge → feuille dans l'Agent Graph.

Cause : le `a2a-sdk` décore ses transports et ses handlers avec `@trace_class`
(`a2a/utils/telemetry.py`, scope `a2a-python-sdk`), et ces spans sont **exactement entre** le span de
jambe du concierge et les spans ADK de la feuille, des deux côtés du saut. Le filtre d'export les
jetait → deux trous, et Langfuse remonte les orphelins au premier niveau. Le parent réel du carrier
injecté est `JsonRpcTransport._send_request` (côté client) ; celui des spans ADK de la feuille est
`DefaultRequestHandler._run_event_stream` (côté serveur) : **aucun des deux n'est atteignable depuis
notre code**, donc il fallait les exporter.

Élargir tout le scope donnait 76 observations par tour (la boucle
`EventQueue.enqueue/dequeue/task_done` tire des dizaines de fois). Retenu : exporter le scope **sauf
le préfixe de module `a2a.server.events.`** → **31 observations, un seul arbre, une seule racine**.
Exclusion par préfixe de module et pas par liste blanche des noms du chemin : ça échoue **ouvert**
(un renommage a2a-sdk = quelques spans bruyants) au lieu d'échouer **fermé** (un trou dans l'arbre,
ce qu'on vient justement de réparer). Bénéfice au passage : le coût du saut réseau A2A est maintenant
visible dans la trace, ce que veut le chantier latence.

**Appel direct d'une feuille sans contexte amont** (peer A2A, `smoke_e2e.py` en isolé, batterie
d'éval) : aucun en-tête `traceparent` → rien n'est attaché, l'observation racine démarre **sa propre
trace**, nommée `a2a.b2c_hotel_search` / `a2a.b2c_faq`, avec le texte de la requête entrante comme
input et `langfuse.session.id` = `dayuse_trace_id` (ou, à défaut, l'id de session ADK de la feuille).
Lisible, jamais une trace anonyme sans input.

---

## 3. Contrat MCP `_meta` — ce qu'OBS10 consomme

### 3.1 Forme sur le fil

Le contexte part dans `params._meta` d'une requête `tools/call` JSON-RPC, **à plat, une clé par
en-tête W3C** :

```json
{
  "jsonrpc": "2.0", "id": 3, "method": "tools/call",
  "params": {
    "name": "search_offers",
    "arguments": { "lat": 48.8566, "lon": 2.3522, "date": "2026-07-31" },
    "_meta": {
      "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
      "baggage": "langfuse_trace_id=4bf92f3577b34da6a3ce929d0e0e4736,langfuse_session_id=abc123,langfuse_user_id=v3_abc123"
    }
  }
}
```

- `traceparent` : format W3C `00-<32 hex trace-id>-<16 hex span-id>-<2 hex flags>`. Le `span-id` est
  celui de l'appel de tool côté client — c'est **le parent** des spans que MCP_B2C doit créer.
- `tracestate` : présent seulement si un amont en a posé un. À propager tel quel, jamais à inventer.
- `baggage` : format W3C Baggage (`k=v,k=v`, valeurs percent-encodées). **Identifiants opaques
  uniquement** (§1.5). `langfuse_trace_id` est l'anti-double-racine du §1.3.
- **Toutes les clés sont optionnelles** : `_meta` absent, `{}`, ou sans `traceparent` = appel sans
  contexte amont. Le serveur doit alors démarrer sa propre trace, jamais échouer.

### 3.2 Qui injecte, côté AgentB2C

| Appelant | Tools | Injection |
|---|---|---|
| `hotel_search_agent` / `faq_agent` (ADK `McpToolset`) | `search_offers`, `find_hotel_by_name`, `get_faq_conditions` | **ADK 2.4.0 le fait déjà**, sans une ligne de notre code : `google/adk/tools/mcp_tool/mcp_tool.py:408-426` — `propagate.get_global_textmap().inject(carrier=trace_carrier)` puis `session.call_tool(..., meta=meta_trace_context)`, avec le commentaire *« Propagate trace context in the _meta field as specified by MCP protocol »*. Le contrat ci-dessus **n'est donc pas inventé par nous** : c'est déjà ce qui arrive sur MCP_B2C aujourd'hui. |
| `b2c_concierge` (client `mcp.ClientSession` brut) | `get_hotel_details`, `compare_hotels`, `generate_booking_link` | Ajouté par OBS4 dans `inline_tools._call_tool` — même carrier, produit par `trace_context_carrier()`, qui est l'équivalent explicite du `inject()` d'ADK. |

`mcp==1.28.1` : `ClientSession.call_tool(name, arguments, read_timeout_seconds=None,
progress_callback=None, *, meta: dict[str, Any] | None = None)` — `meta` est **keyword-only** et
devient `params._meta` (`mcp/types.py`, `RequestParams.meta = Field(alias="_meta")`).

### 3.3 Ce que MCP_B2C doit faire (zone OBS10, hors de ce repo)

1. Lire `params._meta` de `tools/call` et **extraire** le contexte W3C (`propagation.extract` du SDK
   OTel JS sur `{traceparent, tracestate, baggage}`).
2. Créer les spans du tool (dont les requêtes ES) **dans ce contexte** → ils atterrissent dans la
   trace du tour AgentB2C.
3. **Ne pas revendiquer la racine applicative** quand `baggage.langfuse_trace_id` égale l'id de
   trace courant (§1.3). Avec le SDK Langfuse JS, extraire le baggage suffit : la logique
   `suppressed_by_parent_claim` est la même des deux côtés.
4. Aucun en-tête HTTP n'est requis : la session MCP est mutualisée entre appels de tool, donc le
   contexte doit venir **de l'appel**, pas de la connexion. C'est précisément la raison d'être de
   `_meta`.
5. `_meta` absent → trace autonome, jamais d'erreur (§3.1).

**Ordre de merge : la MR OBS4 passe avant celle d'OBS10.**

---

## 4. Ce qui n'a pas changé, et pourquoi

- **`stamp_langfuse_turn_session` est conservé.** C'est la seule chose qui pose `session`/`user` sur
  le chemin **concierge piloté en A2A** (batterie, smoke, peers), où il n'y a pas de
  `turn_observation`. Le retirer viderait la vue Sessions sur ce chemin ; il n'écrit aucun attribut
  déprécié (`langfuse.session.id`/`langfuse.user.id`, pas `langfuse.trace.*`).
- **L'observation racine de feuille est typée `span`, pas `agent`**, contrairement à la suggestion du
  fichier de phase. Raison : OBS2 a découvert et documenté qu'ADK 2.4.0 type **déjà** nativement
  `invoke_agent <leaf>` en `AGENT` (`gen_ai.operation.name=invoke_agent`). Un wrapper `agent`
  ajouterait un second nœud agent pour la même feuille dans l'Agent Graph. Le concierge a exactement
  la même forme depuis OBS1 : `v3.chat` est un `span`, le type `agent` vient d'ADK. La condition
  d'affichage de l'Agent Graph (≥ 1 observation non span/event/generation) reste remplie par les
  types natifs d'ADK.
- **Pas d'`output` sur l'observation racine de FEUILLE** (le concierge, lui, en a un, cf.
  `mark_a2a_turn_output`). Aucun seam public ne l'expose côté feuille : la chaîne
  `after_agent_callback` d'ADK s'arrête au premier retour non-`None`
  (`google/adk/agents/base_agent.py:552`) et sur la feuille search c'est `emit_search_datapart` — un
  callback ajouté après ne tournerait jamais sur un tour de recherche. Les stamps supprimés ne
  posaient de toute façon **que** `name` + `input` : aucune régression. La réponse de la feuille
  reste visible dans sa génération finale, dans le même arbre.
- **`instrument_litellm=False` dans les feuilles** : inchangé (`generate_content` d'ADK EST la
  génération ; une seconde instrumentation doublerait tokens et coût).
- **`setup_langfuse` AVANT l'import du module agent** dans les feuilles : inchangé (ADK `lite_llm`
  binde `acompletion` à l'import — piège payé en OBS1).
- **`flush()` jamais `shutdown()`** dans les lifespans : inchangé.
- **Budget et TTFT** : la propagation est un attribut + un en-tête, aucun appel réseau ajouté,
  l'export reste un batch de fond. Le frame `progress` part toujours avant tout travail LLM.

---

## 5. Mesuré en vrai (2026-07-30, sessions `obs4-check-05*`, clés réelles, MCP + LLM réels)

Instance `https://langfuse-web-production-272b.up.railway.app`, `LANGFUSE_TRACING_ENVIRONMENT=dev-obs4`.

| Chemin | Tours envoyés | Traces | Nom de trace | Racines | Obs. | input / output | Générations avec usage |
|---|---|---|---|---|---|---|---|
| Façade `/v3/chat` | 1 | **1** | `v3.chat` | **1** | 31 | ✅ / ✅ | 4 (2 concierge + 2 feuille) |
| Pilotage A2A `message/send` | 2 | **2** | `a2a.b2c_concierge` | **1** chacune | 37 / 40 | ✅ / ✅ | 4 chacune |

- **Un seul arbre** : `v3.chat` → `invoke_agent b2c_concierge` → `invoke_agent hotel_search_leg` →
  transport A2A → `a2a.b2c_hotel_search` → handler A2A → `invoke_workflow b2c_hotel_search` →
  `invoke_agent b2c_hotel_search` → `generate_content` → `search_offers` (TOOL).
- **Usage compté 1×** : les 3 spans `call_llm` restent typés `SPAN` avec usage nul (le masque
  d'export de la PR #62 tient) ; seules les 2 `acompletion` du concierge et les 2 `generate_content`
  de la feuille portent de l'usage. `total_cost` ≈ 0,00106 $ / tour de recherche.
- **Vue Sessions peuplée sur les deux chemins** (`session.id` + `user.id` sur chaque trace).
- **OBS2/OBS3 non régressés** : types `AGENT`×3 / `TOOL` / `GUARDRAIL` / `GENERATION`×4 présents, et
  **16 scores par trace** (13 `guard_*` + `hotels_returned`/`empty_shortlist`/`llm_calls`) avec
  `configId` non nul — sur les DEUX chemins (avant OBS4, les scores existaient déjà mais la feuille
  vivait sur une autre trace).
- **Latence/budget intacts** : `smoke_e2e.py` et `--contract` passent, premier frame SSE `progress`
  à **3 ms** (SLO < 300 ms), `llm_calls=3` sur un tour de recherche.
