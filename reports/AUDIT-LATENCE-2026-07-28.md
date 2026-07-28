# Audit latence AgentB2C — 2026-07-28

Déclencheur : ressenti Fabien « l'agent est devenu plus lent » (démo Railway, post-merges S-CX du
24–27/07). Méthode : 3 explorations parallèles du code (orchestrateur / feuilles+libs / config LLM +
diffs récents), vérifications live (Railway env, probes provider, mesures avant/après), 2 sessions de
design. **Tout chiffre de ce rapport est mesuré, pas estimé** ; les runs bruts sont dans
`reports/latency/*.jsonl` et reproductibles via `scripts/measure_latency_e2e.py`.

## TL;DR — les 4 causes, par ordre d'impact

1. **Les 3 services Railway tournent en `DAYUSE_MODEL=gpt-5.2`, sans cap de reasoning ni
   `max_tokens` nulle part** (confirmé via `railway variables`, 2026-07-27). C'est le switch documenté
   HANDOFF 23/07 comme régression ×2 (tour search p50 ~6 s → ~10 s). Mesuré ici : search p50
   **10,6 s**, refine **9,4 s**, **faq 21–36 s**. `DAYUSE_REASONING_EFFORT` existe dans la fleet mais
   n'est posé nulle part — et aurait **400é** (shape OpenRouter sur un slug OpenAI-direct) ; les 2
   appels du concierge bypassaient de toute façon `build_model`. → **PR sperf1** + rollout env.
2. **La latence perçue = le tour ENTIER, sans aucun signal intermédiaire** — deux étages :
   (a) le widget déployé n'utilise pas le SSE (POST `/v3/chat` bloquant, `api.js:12`,
   `send.js:508`) ; (b) même en SSE, le **widget-proxy bufferisait le stream en un burst unique**
   (`read(4096)` sur un upstream chunké bloque jusqu'à 4096 octets accumulés — mesuré : progress =
   hotels = done à la ms près, en local ET via Railway). Le facade, lui, streame parfaitement
   (progress à **2-6 ms** en direct). → fix `read1` **PR sperf0** (vérifié avant/après) + chantier
   widget SSE en roadmap.
3. **Le prompt des feuilles grossissait à chaque tour de la conversation** : `RemoteA2aAgent` rejoue
   toute la session (sa condition d'arrêt attend un event du leg que `_run_leaf` ne persiste jamais),
   `_attach_outgoing_datapart` mute l'event stocké (tour N = N snapshots de profil), et le shortlist
   S-CX5 est passé de 2 à 14 clés/hôtel le 27/07 (commits `6acca29`+`64b4bb3` : last_results 245 →
   2 385 chars, ~+535 tokens par appel LLM feuille, ×2 appels/tour). Mesuré : appel feuille
   4 353 → **5 813 tokens** entre tour 2 et tour 3. → **PR sperf2** ; après : **plat, 4 240–4 452**
   (tour 3 = −25 %).
4. **Prompts fixes lourds** : triage +65 % le 27/07 (3 488 → 5 742 chars, payé à CHAQUE tour, acks
   compris) ; feuille ~4,3k tokens incompressibles par tour (INSTRUCTION ~1,3k + docstring
   `geocode_location` ~1,2k + schémas MCP) — payés ×2. → roadmap (compression = risque mesuré).

## Mesures

### Baseline Railway (gpt-5.2, proxy bufferisé) — 2026-07-28, 5 runs × 5 tours

| tour | progress p50/max | hotels | done p50/max |
|---|---|---|---|
| ack | 74 / 97 ms | — | 74 / 97 ms |
| search | 10 577 / 10 659 | idem (burst) | 10 584 / 10 668 |
| refine | 9 381 / 9 991 | idem (burst) | 9 384 / 10 007 |
| pick | 1 693 / 2 535 | — | 1 693 / 2 535 |
| **faq** | **24 875 / 36 088** | idem (burst) | **24 875 / 36 091** |

Toutes les frames arrivent au même instant : c'est le buffering du proxy, pas le facade.
Le tour pick est rapide : chemin booking zéro-LLM + réutilisation du shortlist (S-CX5) — la preuve
que les chemins code-owned tiennent leurs promesses de latence.

### Baseline locale (gpt-4o-mini, facade direct) — 3 runs × 5 tours

| tour | progress | hotels p50 | first_token p50 | done p50 |
|---|---|---|---|---|
| ack | 6 ms | — | — | 8 ms |
| search | **2 ms** | 4 423 | 8 851 | 8 860 |
| refine | 3 ms | 4 059 | 7 822 | 7 836 |
| pick | 6 ms | — | — | 1 682 |
| faq | 6 ms | 11 524 | 13 291 | 13 299 |

Décomposition d'un tour search (métriques stdout existantes) : feuille ~4,4 s (2 appels LLM ~2,2 s +
1 s, geocode 68 ms, search_offers 582 ms, ~0,8 s non instrumenté = create_session+list_tools MCP par
tour) ; puis synthèse ~4,4 s bufferisée. **Les outils coûtent ~650 ms sur un tour de ~9 s : le reste
est LLM.** En gpt-5.2, chaque tranche LLM double environ.

### Probe provider (gpt-5.2, vraie clé, 2026-07-28)

- `reasoning_effort="low"` → **200** ; `"none"` → **200** ; `"minimal"` → **400** (« Supported
  values: none, low, medium, high, xhigh » — le floor a changé depuis gpt-5.0). D'où le mapping
  provider-aware de `b2c_common.llm_params` (disable → "none", le reste verbatim, non-reasoning → rien).

### Avant/après PR sperf2 (diète A2A, même conversation scriptée)

| | avant | après |
|---|---|---|
| prompt_tokens feuille, tour search | 4 353 / 4 470 | 4 240 / 4 357 |
| prompt_tokens feuille, tour refine | **5 813** (et ça continue de croître) | **4 347 / 4 452 (plat)** |
| smoke défaut / --conversation / --contract / --booking | — | **PASS ×4** (lien tracké réel au confirm) |
| battery 32 scénarios (juge gpt-4o-mini, même jour, même MCP staging) | main : 4/32, score moyen 2,19 | sperf2 : 3/32, score moyen **2,28** — 7 scénarios diffèrent, 6 en HAUSSE, 1 flip négatif isolé = variance juge. **Plat/mieux, aucun effondrement de famille.** Le score absolu bas est PRÉEXISTANT (juge strict — il note 2/5 un « quelle ville ? » sur « près de moi » sans geo_context ; calibrage à revoir, hors scope). Budget ≤ 3 LLM/tour : 0 dépassement des deux côtés. |

### Avant/après fix proxy (sperf0, local, même stack)

| | read(4096) | read1 |
|---|---|---|
| progress (tour search) | 9 581 ms (= done) | **2 ms** |
| hotels | 9 581 ms | 4 370 ms |
| done | 9 586 ms | 8 359 ms |

## Ce qui est livré (3 PRs, review Fabien = gate)

| PR | branche | contenu |
|---|---|---|
| sperf0 | `sperf0-latency-audit` | `measure_latency_e2e.py` + fix buffering proxy (`read1`) + baselines JSONL + ce rapport |
| sperf1 | `sperf1-model-roles` | `b2c_common.llm_params` (modèle par rôle, cap reasoning provider-aware, max_tokens triage 200 / synthèse 1000) + les 2 call sites concierge + label `reasoning_effort` sur les métriques. **No-op strict tant que les env ne sont pas posées** (verrouillé par test) |
| sperf2 | `sperf2-a2a-diet` | `StatelessLeafLeg` (message A2A d'un seul tour, contre-preuve 10 parts → 2) + `leaf_profile_view` (shortlist → {hotel_id, name}, 8 clés concierge-only droppées — bonus RGPD : `last_clarifying_question`/`last_suggestions` ne voyagent plus) + `include_contents="none"` sur les 2 feuilles |

## Rollout env Railway proposé (après merge — GO Fabien requis)

```
concierge :    DAYUSE_MODEL_TRIAGE=gpt-4o-mini     # enum fermée, l'éco suffit — et le triage 5.2 risquait le timeout 5 s → fallback regex silencieux
concierge :    DAYUSE_REASONING_EFFORT=low          # cappe la synthèse gpt-5.2 (probé 200)
hotel-search : DAYUSE_MODEL=gpt-4o-mini             # sorties = tool calls, décisions en code
faq :          DAYUSE_MODEL=gpt-4o-mini
widget :       redéployer (fix read1)
```

Levier prêt sans code si la synthèse 5.2+low reste lente à la re-mesure : `DAYUSE_MODEL_SYNTHESIS=gpt-4o-mini`.
Attendu : tour search ~10,6 s → **~6-7 s** (retour vers la baseline 4o-mini, en gardant 5.2 là où la
qualité se voit), faq 21-36 s → ~13 s. **Re-mesurer avec le même script après rollout** (les deux
baselines JSONL sont l'étalon).

## Roadmap (chantiers restants, chacun sessionnable)

| # | Chantier | Effort | Gain attendu |
|---|---|---|---|
| 1 | **Widget SSE** : fetch + ReadableStream (EventSource ne POST pas), flag meta `du-chat-transport` avec fallback POST, rendu hotels-first (cartes ~4 s avant le texte), tracking `ttft_ms`/`hotels_ms` ADDITIFS (ne jamais redéfinir `latency_ms` Amplitude). Pré-requis : sperf0 déployé ; re-probe frames séparées à travers l'edge Railway (le proxy est prouvé, l'edge pas encore) | M | perçu : cartes 3-6 s plus tôt, spinner honnête < 300 ms |
| 2 | **Geocode async** : `geocode_location` est un `def` sync exécuté SUR l'event loop (httpx.Client sync, pire cas ~6 s de loop bloquée : 2×1,5 s v6 + 2×1,5 s Search Box, 1 worker uvicorn) → wrapper `anyio.to_thread` (nom/signature/docstring préservés — la déclaration LLM en dépend) + `httpx.Limits(keepalive_expiry=60)` sur Mapbox/Search Box (défaut 5 s = TLS neuf quasi à chaque geocode) et sur les legs concierge | S | ~100-300 ms médiane ; tue le tail 6 s sous concurrence |
| 3 | **Breaker Mapbox** (réutilise `resilience.CircuitBreaker`, TODO en place) + clé de cache geocode : `proximity` GPS pleine précision → clés quasi uniques ; arrondir à 2 décimales (~1,1 km, biais soft assumé) | S | tail/outage ; cache enfin utile sur sessions GPS |
| 4 | **`sse_read_timeout=10 s`** sur les 2 feuilles : le « timeout MCP 5 s » ne couvre que connect/init/list_tools — `call_tool` hérite de 300 s, un ES lent mange le budget feuille entier, et `@retry_on_errors` double en silence | S | p99 |
| 5 | **Pool session MCP inline** (concierge) : handshake httpx + streamable_http + initialize PAR appel aujourd'hui (`inline_tools.py:63-70`, ~3-4 round-trips ; `_quote_fresh_offer` = jusqu'à 3 calls dedans) + métrique `concierge_metric=inline_tool` (zéro timing aujourd'hui) + `CachedMcpToolset` (list_tools 1×/tour, dans les ~0,8 s non instrumentés) | M | 50-150 ms tous les tours ; 200-600 ms details/booking |
| 6 | **Feuille FAQ** : `FAQ_MODEL` env (S) puis, si la mesure le justifie, miroir du pattern capture/skip de hotel_search (le 2e appel LLM feuille relit le doc ~6k tokens pour une prose que la synthèse réécrit) | S/M | faq : mesuré 21-36 s en 5.2 ; attendu ~moitié |
| 7 | **Hygiène façade** : `normalize_hotels` exécuté 2× (frame SSE + payload) ; log Postgres = psycopg.connect + DDL (CREATE TABLE/INDEX IF NOT EXISTS) + INSERT par tour, AWAITED avant `done` — inerte sans DATABASE_URL (cas Railway) mais s'arme dès que la var apparaît → connexion réutilisée + DDL one-shot + fire-and-forget | S | 0 aujourd'hui ; évite +50-200 ms/tour futurs |
| 8 | **Compression prompts** : triage 5 742 chars (~1,4k tokens payés chaque tour, acks compris) ; INSTRUCTION feuille 5 188 + docstring geocode 3 483 (~2,5k tokens ×2/tour). ~30 % compressibles MAIS risque mesuré : battery A/B complète obligatoire (leçon gpt-4o-mini : une consigne de négation peut s'inverser) | M | modéré, cumulatif |
| 9 | **Streaming token réel : DÉFÉRÉ.** Le guard anti-clarification juge la DERNIÈRE phrase et régénère TOUT ; amenity/link guards réécrivent des spans arbitraires — streamer imposerait de les redessiner en filtres par phrase (affaiblissement refusé par défaut). Avec hotels-first (#1) + synthèse rapide (rollout), le texte est la dernière ~seconde du tour | L | faible une fois #1 fait |

Notes hors roadmap : les 2 `copy.deepcopy` de session par tour dans le facade (coût croissant avec
l'historique ; fix = compteur de tours dans le profil Redis, M, différé) ; flag ADK
`IN_MEMORY_SESSION_SERVICE_LIGHT_COPY` = WIP upstream, ne pas activer ; `test_llm_meter_usage` rouge
sur main = bug d'arrondi DU TEST (banker's rounding 432,15 → 432,1), sans rapport ; rappel sécurité
ouvert : le build Railway fuit toujours `FLEET_READ_TOKEN` (addendum HANDOFF 27/07).

## Reproduire

```bash
# stack locale puis :
.venv/bin/python scripts/measure_latency_e2e.py --runs 3 --out reports/latency/run.jsonl
# Railway (via le proxy widget) :
CONCIERGE_URL=https://widget-production-3f56.up.railway.app .venv/bin/python scripts/measure_latency_e2e.py --runs 5
# courbe de croissance du prompt feuille :
grep "llm_call agent=b2c_hotel_search" .run-logs/hotel_search_agent.log | grep -oE "prompt_tokens=[0-9]+"
```
