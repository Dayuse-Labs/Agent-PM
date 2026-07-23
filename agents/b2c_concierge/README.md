# b2c-concierge

Orchestrateur conversationnel B2C de Dayuse (ADK Python + LiteLLM, portable) — **spine code-owned** (pattern `cs_copilot` de la fleet : custom `BaseAgent`, PAS de LlmAgent + sub_agents libre). Remplace `agent-usa`. **La façade publique `/v3/chat` + SSE (S9) est en place** (ci-dessous). **S7 câble les 3 tools MCP inline pour de vrai + guard R9 + amenity claim verifier + named-hotel lookup** ; synthèse streamée + ground-truth + anti-loop/recovery-ack (S6) et Redis de session + profil (S5) déjà en place.

## Flux d'un tour (budget structurel ≤ 3 appels LLM — n'inclut QUE les appels LLM, jamais un appel MCP)

1. **Fast-path ack** (`triage.py`) — message purement social → template, **0 LLM** — SAUF signal de reprise de recherche (P2) ou de confirmation de réservation en attente (R9), qui désactivent ce fast-path.
2. **Triage** — 1 appel LLM **éco** (`DAYUSE_MODEL`) classifiant `{family, language}`, litellm direct hors session ADK ; **fallback regex** sur tout échec (jamais de retry : LiteLLM est la seule couche de retry).
3. **Routage en code** (`routing.py`) — aucune décision de contrôle par LLM :

| Family | Action |
|---|---|
| `search` | `RemoteA2aAgent` → feuille **hotel-search-agent** (:8101) |
| `faq` | `RemoteA2aAgent` → feuille **faq-agent** (:8102) |
| `details` / `compare` | appel MCP_B2C réel (`inline_tools.py`, S7) grounded par la MÊME synthèse que search/faq (`_run_inline_lookup`) |
| `booking` | flux de confirmation **déterministe, ZÉRO LLM** (guard R9, `_run_booking`) |
| `ack` | template (`templates.py`) |

4. **Appel feuille / tool inline** — timeout **10 s** (feuille) ou **5 s** (tool MCP inline, `CONCIERGE_INLINE_MCP_TIMEOUT_SECONDS`) SANS retry, propriété de l'orchestrateur. Échec/timeout → **dégradation honnête** : un message qui le dit, zéro invention. Le profil de session part avec l'appel feuille (`{query_params, profile_in}`) et revient éventuellement enrichi (`profile_delta`) — voir « Profil de session » ci-dessous.
5. **UNE synthèse LLM** par tour pour search/faq/details/compare (streamée en chunks — S6), grounded par le ground-truth block + l'**amenity claim verifier** (S7 : hedge en place toute amenity affirmée non backée par les données). `booking` ne passe JAMAIS par la synthèse (0 LLM). Échec de synthèse → texte source servi tel quel (grounded).

Le compteur d'appels LLM par tour (`budget.py`) est instrumenté : dépasser 3 lève `LlmBudgetExceededError` (un guard ne relance jamais une boucle), et `tests/test_spine.py::test_simple_search_turn_stays_within_llm_budget` échoue si un tour simple dépasse le budget.

### Guard R9 / #12 — `generate_booking_link` (S7)

Le tool MCP `generate_booking_link` est **stateless côté serveur** (vérifié en direct contre le staging : un premier appel `confirmed=true` renvoie un vrai lien, sans mémoire d'un éventuel appel `confirmed=false` précédent) — toute la garantie de confirmation vit donc **côté code** (`inline_tools.generate_booking_link`) : le flag `confirmed` réellement envoyé à MCP est dérivé de `profile.pending_booking` (état serveur, jamais de l'argument `user_confirmed` seul). Flux : (1) pas d'offre en attente → appel `confirmed=false` systématique, résumé présenté, offre mémorisée ; (2) offre en attente **ET** confirmation de l'utilisateur → réutilise l'identité de l'offre mémorisée (jamais re-résolue depuis un simple « oui »), appelle `confirmed=true`. Une tentative de contournement (`user_confirmed=true` sans offre en attente préalable) ne produit **jamais** de lien. Testé aux deux chemins + tentative de bypass (`tests/test_inline_tools.py::TestGenerateBookingLinkR9`, `tests/test_spine.py::TestBookingGuardR9`) et par `scripts/smoke_e2e.py --booking` (flux réel en 2 tours contre MCP_B2C).

### Named-hotel lookup guard (item 4, S7)

`get_hotel_details`/`compare_hotels`/`generate_booking_link` résolvent d'abord un hôtel nommé dans la shortlist **du tour précédent** (`profile.last_results`, fuzzy match — `resolve_hotel_reference`), MCP `find_hotel_by_name` ensuite (jamais pour `compare_hotels`, qui reste shortlist-only par périmètre de phase) — un hôtel qu'on vient de recommander ne fait jamais de dead-end. `find_hotel_by_name` ne tolère pas une phrase entière autour du nom (vérifié en direct) : un strip déterministe des tournures de requête courantes (« book », « compare », « tell me about »…) précède l'appel MCP.

## Façade publique `/v3/chat` + SSE (S9)

Bascule **iso-contrat** avec `agent-usa` : même surface HTTP pour le frontend, orchestrateur remplacé de façon invisible. Servie sur le **même app Starlette** que la surface A2A (`serve.py`), mais sous une **identité séparée** (`facade.py`).

- **`POST /v3/chat`** — réponse JSON iso-contrat (mêmes clés/formes qu'agent-usa : `message`/`response`/`context` (alias legacy), `hotels`, `suggestions`, `session_id`/`conversation_id`, `response_language`, `state`, `ready_to_search`, `requires_clarification`, `profile_status`, `active_filters`, `market`/`market_country`/`entry_market_country`/`search_country`, `turn_id`). **Iso-contrat en FORME, pas en sémantique** : le spine B2C n'a ni intake staged, ni market engine, ni langues es/it — les champs sans équivalent sont mappés depuis l'état réel du profil ou reçoivent un défaut honnête documenté (`facade.build_chat_payload`). Le prix est affiché depuis `priceEuro` (centimes EUR) → `€X.XX`, cohérent avec S7.
- **`POST /v3/chat/stream`** — SSE : `event: progress` (le marqueur TTFT, immédiat) → `event: hotels` → `event: token` (chunks) → `event: done` (le payload contrat complet). Le JSON non-streamé ci-dessus sert exactement le même payload en un coup.
- **`POST /v3/chat/session/reset`** — 204, efface le cookie + la session ADK + le profil Redis.
- **Session** : id résolu cookie `du_chat_sid` → header `X-Client-Session-Id` → `session_id` du body (phase M1 legacy) → nouveau. L'id de session de la façade EST l'id de session ADK, donc le profil Redis (clé `ctx.session.id`) porte la continuité entre tours HTTP sans plomberie supplémentaire.
- **Auth (minimum, phase OUT)** : les routes `/v3/*` prennent une **API key interne** (`X-Internal-Api-Key`, env `CHAT_API_KEY`), PAS le bearer D7 des routes A2A (voir « Deux régimes d'identité » plus bas). Ouvertes quand `CHAT_API_KEY` est vide ou `AUTH_BYPASS=true` (défaut dev).
- **Budget** : la façade ajoute **ZÉRO appel LLM** — elle ne fait que consommer le flux d'événements du spine (mêmes ≤ 3 appels/tour).
- **`client_local_time`/`client_timezone`** (S12, drift audit 2026-07-20) : le front d'agent-usa envoie désormais ces deux champs optionnels dans le body `POST /v3/chat` (PR agent-usa #125, pour résoudre "now" côté agent-usa). Cette façade les ignore sans casse — ce spine n'a aucune résolution de date/"now" à brancher dessus aujourd'hui ; à consommer le jour où ce besoin existera.

### Deux régimes d'identité (serve.py)

Un seul app, deux surfaces : les routes A2A (`/`, carte) gardent le **bearer D7** (agent↔agent, réseau privé, fail-closed au boot) ; les routes `/v3/*` prennent l'**API key interne** (frontend/BFF). La composition (quelles routes sont ouvertes) vit dans `serve.py` ; la *vérification* D7 reste consolidée dans `b2c_common.auth` (invariant — bascule oidc-mtls en un seul endroit).

## Profil de session (S5)

**Orchestrateur-only** (décision B3) : les feuilles restent stateless, le Redis n'appartient qu'au concierge — enforcé statiquement par `tests/test_stateless_leaves.py` (aucune occurrence de `redis` dans `agents/hotel_search_agent` ou `agents/faq_agent`).

- **Schéma** (`profile.py::SessionProfile`) : `city`, `state_anchor`/`country_anchor` (ancres géo, complément des guards S4), `budget_max`/`budget_request_source`, `timeslot`/`timeslot_start`/`timeslot_end`/`timeslot_request_source`/`timeslot_mode`, `amenities`, `language`, `consecutive_empty_searches`, `auto_widen_disclosure`, `last_suggestions`, `last_clarifying_question`, et depuis S7 : `last_results` (shortlist à l'écran, ≤5, guard named-hotel lookup), `pending_booking` (offre en attente de confirmation, guard R9), `amenity_claim_corrections` (corrections déjà émises, jamais répétées).
- **Stockage** (`profile_store.py`) : une clé Redis JSON par session (`b2c_concierge:profile:<session_id>`), TTL glissant (rafraîchi à chaque écriture) — `CONCIERGE_PROFILE_TTL_SECONDS` (défaut 1800 s = 30 min d'inactivité).
- **Transport** (`a2a_datapart.py`) : le profil voyage en A2A `DataPart` — encodage `inline_data` `<a2a_datapart_json>` du part converter ADK (aucun autre point d'injection : `RemoteA2aAgent` construit son message sortant uniquement à partir de `ctx.session.events`). `{query_params: {}, profile_in: profile.to_dict()}` part avant l'appel feuille ; `profile_delta` (et `results` pour la feuille search) revient dans la réponse et est fusionné avec les guards.
- **Guards portés (spec agent-usa, comportement rejoué — pas le code)** :
  - **Budget integrity (P1)** : une réponse nombre nu (« 180 », « $40 ») marque `budget_request_source=explicit`, quelle que soit la classification renvoyée par la feuille — un budget explicite n'est **jamais** auto-élargi silencieusement ; l'auto-widen (×1,5 après 2 recherches vides consécutives, budgets par défaut seulement) pose `auto_widen_disclosure={from, to}` (obligatoire à surfacer par la synthèse — S06).
  - **Timeslot sanitization (P6)** : un horaire à borne unique corrompu (« 15:00- », « -09:00 ») est salvage en `timeslot_start`/`timeslot_end`, jamais persisté tel quel ; une borne ancrée (ex. fin à 09:00) n'est jamais inversée par une ré-extraction d'un tour sans nouvelle mention d'heure.
  - **Ancres géo** : `state_anchor`/`country_anchor` persistent tant que la ville ne change pas explicitement ; un changement de ville efface les ancres (sauf si le même delta en fournit une fraîche).

## Lancer / tester

```bash
bash scripts/run_local.sh          # boote les 3 services (concierge sur :8100)
python scripts/smoke_e2e.py        # 1 tour ack + 1 search + 1 faq via l'orchestrateur
python scripts/smoke_e2e.py --conversation  # 4 tours, un seul contextId (continuité de session)
python scripts/smoke_e2e.py --booking       # guard R9 : book <hôtel> puis "yes" (2 tours, un contextId)
python scripts/smoke_e2e.py --contract      # S9 : aller-retour /v3/chat (JSON) + SSE progress
.venv/bin/pytest -q                # tests offline (ni réseau ni clé API)
.venv/bin/pytest tests/api -q      # S9 : tests de contrat de la façade uniquement
bash scripts/dayuse_guardrails.sh .
```

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `DAYUSE_MODEL` | `gpt-4o-mini` | Slug LiteLLM (D3) — triage ET synthèse en S2 ; per-phase via `build_model()` en S3 |
| `OPENAI_API_KEY` | — | Clé du provider LiteLLM (aucun appel au boot) |
| `HOTEL_SEARCH_CARD_URL` | `http://localhost:8101/.well-known/agent-card.json` | Carte de la feuille search |
| `FAQ_AGENT_CARD_URL` | `http://localhost:8102/.well-known/agent-card.json` | Carte de la feuille faq |
| `HOTEL_SEARCH_A2A_TOKEN` | (vide) | Bearer D7 **sortant** vers la feuille search (secret par feuille en déploiement) |
| `FAQ_AGENT_A2A_TOKEN` | (vide) | Bearer D7 **sortant** vers la feuille faq |
| `CONCIERGE_LEAF_TIMEOUT_SEARCH_SECONDS` | `15.0` | Budget appel feuille search, propriété de l'orchestrateur — SANS retry (S-G4) |
| `CONCIERGE_LEAF_TIMEOUT_FAQ_SECONDS` | `25.0` | Budget appel feuille faq — SANS retry (S-G4 : la synthèse FAQ doc-lourde a besoin de plus de marge) |
| `CONCIERGE_LEAF_TIMEOUT_SECONDS` | — (legacy) | Si posée, gagne pour LES DEUX familles (compat démo Railway `=30`) — sinon chaque famille utilise sa variable dédiée |
| `CONCIERGE_TRIAGE_TIMEOUT_SECONDS` | `5.0` | Timeout du classify éco (échec → fallback regex) — pas de retry, décision S-G4 (voir HANDOFF) |
| `CONCIERGE_SYNTHESIS_TIMEOUT_SECONDS` | `15.0` | Timeout de la synthèse |
| `CONCIERGE_SYNTHESIS_NUM_RETRIES` | `1` | Retries PAR EXCEPTION TRANSITOIRE (Timeout/RateLimit) via `litellm.Router` + `RetryPolicy` (S-G4) — BadRequest/Auth/ContentPolicy restent à 0 retry |
| `A2A_HOST` | `localhost` | Hôte joignable par les pairs — écrit dans l'URL de la carte servie |
| `PORT` | `8100` | Port d'écoute (plage AgentB2C : 8100 concierge / 8101 search / 8102 faq) |
| `A2A_BEARER_TOKEN` | — **(obligatoire)** | Bearer **entrant** D7, vérifié par `serve.py` — fail-closed au boot |
| `CONCIERGE_REDIS_URL` | `redis://localhost:6379/0` | Redis du profil de session (orchestrateur seul — décision B3) |
| `CONCIERGE_PROFILE_TTL_SECONDS` | `1800` | TTL glissant du profil (rafraîchi à chaque écriture) — rétention RGPD |
| `MCP_B2C_URL` | `http://localhost:8099/mcp` | Serveur MCP_B2C — les 3 tools inline (S7) l'appellent directement, une session par appel (`inline_tools.py`) |
| `MCP_B2C_AUTH_TOKEN` | (vide) | Bearer RFC 6750 vers MCP_B2C (même token que les 2 feuilles) |
| `CONCIERGE_INLINE_MCP_TIMEOUT_SECONDS` | `5.0` | Budget d'un appel MCP inline (connexion + appel(s)), propriété de l'orchestrateur — SANS retry |
| `CHAT_API_KEY` | (vide) | Façade `/v3` (S9) : clé API interne attendue ; vide → façade ouverte (dev) |
| `CHAT_API_KEY_HEADER` | `X-Internal-Api-Key` | Header portant la clé API interne de la façade |
| `AUTH_BYPASS` | (vide) | `true` → désactive l'auth de la façade `/v3` (dev/tests) |
| `SESSION_MIGRATION_PHASE` | `M1` | `M1` accepte un `session_id` legacy dans le body quand aucun cookie ; `M2` l'ignore |
| `CONCIERGE_SESSION_COOKIE_NAME` | `du_chat_sid` | Nom du cookie de session de la façade |
| `CONCIERGE_SESSION_TTL_SECONDS` | `3600` | Max-Age du cookie de session |
| `CONCIERGE_SESSION_COOKIE_SECURE` | `true` | `Secure` sur le cookie (mettre `false` en dev http local) |
| `CONCIERGE_SESSION_COOKIE_SAMESITE` | `lax` | Attribut `SameSite` du cookie |
| `DATABASE_URL` | (vide) | Postgres partagé : `conversation_logs` (S9) + `llm_metric_events` (S3) ; **write no-op sans cette variable** |

Un token sortant vide n'est pas fatal au boot : la feuille fail-closed répond 401 et le tour dégrade honnêtement (jamais d'auth contournée). `scripts/run_local.sh` partage un même token local pour les 3 services.

## ⚠️ Exception d'identité intérimaire (D7) — avec échéance

Même régime que les feuilles : réseau privé Railway + bearer statique (entrant vérifié par `serve.py`, sortant porté par les clients httpx des legs), carte servie **non signée** (`sign_agent_card` non implémenté). **Échéance : bascule oidc-mtls au plus tard avant le canary S11.** Suivi dans `HANDOFF.md`.

## RGPD — données & rétention

- **Sessions (Redis, profil)** : TTL glissant `CONCIERGE_PROFILE_TTL_SECONDS` (défaut **1800 s = 30 min** d'inactivité, rafraîchi à chaque écriture), orchestrateur seul (S5). Le cookie de session HTTP (`du_chat_sid`, `CONCIERGE_SESSION_TTL_SECONDS`, défaut 3600 s) porte le même id ; `POST /v3/chat/session/reset` efface cookie + session ADK + profil Redis. La session ADK elle-même (historique d'événements) reste en mémoire du process (éphémère).
- **`conversation_logs` (Postgres, S9)** — la SEULE table qui porte du **contenu de message** (`user_message`, `assistant_message`), par design (analytics/export), à ne jamais confondre avec les métriques. Colonnes = celles d'agent-usa + **`is_synthetic`** (booléen) : le trafic synthétique (batteries, shadow-run) se marque lui-même via le header interne `X-Dayuse-Synthetic` et reste filtrable hors de toute analyse. Écriture **best-effort, no-op sans `DATABASE_URL`** (posture `metrics_pg`) — jamais un 500 sur un tour réussi. **Rétention à appliquer côté DB** (précondition de prod, S10/S11) : purge/anonymisation périodique de la table (aucune purge automatique n'est encore posée ici — la table stocke du contenu brut, sa durée de conservation doit être bornée par une politique DB avant tout trafic réel).
- **Métriques (`llm_metric_events`, Postgres)** : AUCUN contenu de message — uniquement family/route/compteurs/latences, verrouillé par test côté logs (`test_logs_never_contain_message_content`) ET côté événements (`test_metric_events_never_contain_message_content`). Mirroré via `dayuse_agent_common.metrics_pg` (`service=b2c_concierge`, no-op sans `DATABASE_URL`).
- **Résidence EU** du provider modèle derrière LiteLLM : à vérifier AVANT tout trafic réel (précondition de prod, cf. brief §4).

## ⚠️ Staging ≠ shadow-run

Les feuilles pointent en dev sur le MCP_B2C de **staging** (notes/avis quasi vides, inventaire partiel). OK pour développer, INTERDIT pour le shadow-run/la parité (exige l'ES prod, cf. plan Ph3.3).
