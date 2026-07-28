# hotel-search-agent

Feuille A2A de recherche hôtelière day-use pour l'orchestrateur `b2c-concierge` (ADK Python + LiteLLM, portable). Consomme les tools **lecture seule** du serveur MCP_B2C (`search_offers`, `find_hotel_by_name`) en Streamable HTTP. `dayuse_agent_common` (metrics, budget tool-calls) branché en S3. S4 a ajouté un client Mapbox réel + 3 guards géo déterministes (`geo_guards.py`) exposés via le tool `geocode_location` (`geocode_tool.py`), et un circuit-breaker sur les 2 tools MCP (`mcp_guard.py`).

## Guards géo (S4)

MCP_B2C n'effectue aucun géocodage serveur : `search_offers` exige `lat`/`lon` numériques. Laisser le LLM deviner ces coordonnées est exactement ce qui a produit les échecs prod audités (voir `agent-usa/tests/unit/application/test_audit_fixes_2026_06.py`) — ce leaf porte donc 3 guards déterministes (`geo_guards.py`, ~30 tests portés dans `tests/test_geo_guards.py`), composés dans le tool code-owned `geocode_location` (`geocode_tool.py`) :

1. **Geocode echo-back** (`geocode_echo_matches`) : un résultat Mapbox `limit=1` doit refléter l'état US demandé et au moins un token distinctif de la ville/zone — sinon rejeté (mésolution "Colorado Springs" pour "Birmingham airport", "Atlanta" pour "Budapest", etc.). Comprend l'exemption des alias courts (NYC), le repli sur script non-latin, et la translittération Unicode→ASCII (ß, ø, æ… et au-delà — voir ci-dessous).
2. **Generic place words** (`is_generic_location_token` / `demote_generic_city`) : "airport", "downtown", "terminal 5"… ne sont jamais géocodés comme ville — démotion en indice de zone, le tool refuse la recherche (`no_geocodable_location`) plutôt que d'envoyer le mot générique à Mapbox.
3. **State anchoring** (`resolve_state_hint` / `anchor_state_context`) : un état US explicitement nommé ("Milford **ct**") qualifie le géocodage et est renvoyé dans `profile_delta` (`last_state_context`/`last_city`) pour ancrer les tours suivants — effacé si une nouvelle ville est nommée sans état. Ce leaf étant stateless (décision B3), l'ancre voyage via `profile_in`/`profile_delta`, pas une session : c'est à l'appelant (orchestrateur, S5) de la faire suivre au tour suivant.

`geocode_location` ne raise JAMAIS : tout rejet de guard ou échec Mapbox devient un diagnostic propre `{"ok": False, "error": ..., "diagnostics": {...}}` que le modèle relaie honnêtement (jamais de coordonnées inventées).

Le référentiel géographique générique (les 50 états US, la translittération Unicode→ASCII) vient des libs `us` et `anyascii` plutôt que de tables recopiées à la main — aucune autre lib géo n'était utilisée nulle part dans l'écosystème Dayuse (vérifié, y compris agent-usa qui hardcode la même donnée). Les listes réellement Dayuse-spécifiques (codes ambigus multilingues, mots génériques, bruit d'echo-back) restent en dur : ce sont des décisions produit issues des audits prod, pas du référentiel géo.

## Circuit-breaker MCP (S4)

`mcp_guard.py` branche le `CircuitBreaker` de `resilience.py` sur `search_offers`/`find_hotel_by_name` via les callbacks ADK (`before_tool_callback`/`after_tool_callback`/`on_tool_error_callback`) : après 3 échecs consécutifs, tout nouvel appel est court-circuité instantanément (aucun appel réseau, aucune exception) avec un diagnostic `{"ok": False, "error": "mcp_circuit_open", ...}` — dégradation honnête, jamais de boucle de retry contre une dépendance morte. Réinitialisation automatique après 30 s.

## Contrat (stateless — décision B3)

La feuille ne détient AUCUN état : pas de Redis, pas de session — le Redis de session appartient à l'orchestrateur seul. Tout transite par le `DataPart` A2A (`hotel_search_agent/contract.py`) :

- **Entrée** `SearchRequest` : `query_params` (intention de recherche) + `profile_in` (instantané du profil, propriété de l'appelant).
- **Sortie** `SearchResponse` : `results` (offres/hôtels renvoyés par les tools, jamais inventés) + `profile_delta` (seuls les faits NOUVEAUX appris ce tour) + `diagnostics` (appels effectués, dégradations — jamais montré à l'utilisateur).

S1 fige l'enveloppe uniquement ; les champs métier internes sont spécifiés en S4 (géo) et S5 (profil). Budget : 0-1 appel LLM interne par requête.

## Lancer / tester

Depuis la racine du repo (voir `CLAUDE.md` § Commandes) :

```bash
bash scripts/run_local.sh        # boote les 3 services (search sur :8101)
.venv/bin/pytest -q              # tests offline (ni réseau ni clé API)
bash scripts/dayuse_guardrails.sh .
```

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `DAYUSE_MODEL` | `gpt-4o-mini` | Slug LiteLLM (D3 — jamais de SDK cloud direct) |
| `OPENAI_API_KEY` | — | Clé du provider LiteLLM (aucun appel au boot, connexions lazy) |
| `MCP_B2C_URL` | `http://localhost:8099/mcp` | Serveur MCP_B2C Streamable HTTP (placeholder local ; staging via `.env`) |
| `MCP_B2C_AUTH_TOKEN` | (vide) | Bearer MCP standard (RFC 6750 — accepté côté serveur depuis le fix du 2026-07-17) ; header omis si vide, jamais dans le contexte modèle |
| `HOTEL_SEARCH_MCP_TIMEOUT_SECONDS` | `5.0` | Budget MCP, propriété de cette feuille ; protégé par le circuit-breaker `mcp_guard.py` (S4) |
| `HOTEL_SEARCH_MAX_TOOL_CALLS` | `2` | Cap dur d'appels tool réels par tour (`geocode_location` + `search_offers`, ou `find_hotel_by_name` seul) |
| `MAPBOX_ACCESS_TOKEN` | (vide) | Token Mapbox Geocoding API v6 ; absent/vide n'empêche PAS le boot (pas un secret D7) — un géocodage échoue simplement et le tool dégrade honnêtement |
| `MAPBOX_GEOCODE_TIMEOUT_SECONDS` | `1.5` | Budget Mapbox, propriété de cette feuille (single-owner rule) ; 1 retry interne avant abandon |
| `A2A_HOST` | `localhost` | Hôte joignable par les pairs — écrit dans l'URL de la carte servie |
| `PORT` | `8101` | Port d'écoute (plage AgentB2C : 8100 concierge / 8101 search / 8102 faq) |
| `A2A_BEARER_TOKEN` | — **(obligatoire)** | Bearer entrant D7, vérifié par `serve.py` — fail-closed au boot si absent/vide |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL` | (vides) | OBS1 : traces vers le Langfuse self-hosted EU — les deux clés absentes ⇒ inerte (voir le README du concierge pour le détail) |

## ⚠️ Exception d'identité intérimaire (D7) — avec échéance

L'identité cible (oidc-mtls de `dayuse_agent_common`) est un stub `NotImplementedError`. En attendant, cette feuille applique le régime intérimaire D7, PLUS strict que la fleet (qui ne vérifie aucun bearer entrant) :

- **Réseau privé Railway** + **bearer statique vérifié côté feuille** : toutes les routes exigent `Authorization: Bearer $A2A_BEARER_TOKEN` (comparaison à temps constant), SAUF `/.well-known/agent-card.json` (découverte).
- **Fail-closed** : token absent ou vide → `RuntimeError` au démarrage. `dev-insecure` n'est jamais déployé.
- **Carte servie NON signée** (`sign_agent_card` non implémenté) — incluse dans l'exception. La carte déclare `securitySchemes.bearer-interim` pour que les appelants découvrent le schéma.

**Échéance** : bascule sur oidc-mtls dès que la lib l'implémente, **au plus tard avant le canary S11**. Cette exception est documentée ici et suivie dans `HANDOFF.md`.

## RGPD

- **Nature des données** : les requêtes contiennent du contenu utilisateur (destination, dates, éventuellement texte libre) et un instantané de profil — données personnelles potentielles. La feuille ne persiste RIEN (stateless) : aucune base, aucun log applicatif de contenu de message ; les métriques (S3) n'embarqueront jamais de contenu de message (verrouillé par test côté socle).
- **Transit** : orchestrateur → feuille sur le réseau privé Railway (bearer D7) ; feuille → MCP_B2C en HTTPS avec bearer en header (jamais dans le contexte modèle) ; feuille → provider LLM via LiteLLM (`DAYUSE_MODEL`).
- **Résidence** : déploiements en région **EU** uniquement (zéro lock-in cloud : même image OCI pour Cloud Run / k8s / Railway).

## ⚠️ Staging ≠ shadow-run

Le MCP_B2C accessible en dev pointe sur l'Elasticsearch de **staging** : notes/avis quasi vides, inventaire partiel. **OK pour développer, INTERDIT pour le shadow-run/la parité** (exige l'ES prod, cf. plan Ph3.3).
