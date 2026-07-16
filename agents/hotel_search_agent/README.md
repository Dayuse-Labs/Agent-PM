# hotel-search-agent

Feuille A2A de recherche hôtelière day-use pour l'orchestrateur `b2c-concierge` (ADK Python + LiteLLM, portable). Consomme les tools **lecture seule** du serveur MCP_B2C (`search_offers`, `find_hotel_by_name`) en Streamable HTTP. Squelette S1 : les guards géo + Mapbox arrivent en S4, `dayuse_agent_common` (metrics, budget tool-calls) en S3.

## Contrat (stateless — décision B3)

La feuille ne détient AUCUN état : pas de Redis, pas de session — le Redis de session appartient à l'orchestrateur seul. Tout transite par le `DataPart` A2A (`hotel_search_agent/contract.py`) :

- **Entrée** `SearchRequest` : `query_params` (intention de recherche) + `profile_in` (instantané du profil, propriété de l'appelant).
- **Sortie** `SearchResponse` : `results` (offres/hôtels renvoyés par les tools, jamais inventés) + `profile_delta` (seuls les faits NOUVEAUX appris ce tour) + `diagnostics` (appels effectués, dégradations — jamais montré à l'utilisateur).

S1 fige l'enveloppe uniquement ; les champs métier internes sont spécifiés en S4 (géo) et S5 (profil). Budget : 0-1 appel LLM interne par requête.

## Lancer / tester

Depuis la racine du repo (voir `CLAUDE.md` § Commandes) :

```bash
bash scripts/run_local.sh        # boote sur :8101 (source .env si présent)
.venv/bin/pytest -q              # tests offline (ni réseau ni clé API)
bash scripts/dayuse_guardrails.sh .
```

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `DAYUSE_MODEL` | `gpt-4o-mini` | Slug LiteLLM (D3 — jamais de SDK cloud direct) |
| `OPENAI_API_KEY` | — | Clé du provider LiteLLM (aucun appel au boot, connexions lazy) |
| `MCP_B2C_URL` | `http://localhost:8099/mcp` | Serveur MCP_B2C Streamable HTTP (placeholder local ; staging via `.env`) |
| `MCP_B2C_AUTH_TOKEN` | (vide) | Bearer MCP ; header omis si vide, jamais dans le contexte modèle |
| `HOTEL_SEARCH_MCP_TIMEOUT_SECONDS` | `5.0` | Budget MCP, propriété de cette feuille (circuit-breaker en S4) |
| `A2A_HOST` | `localhost` | Hôte joignable par les pairs — écrit dans l'URL de la carte servie |
| `PORT` | `8101` | Port d'écoute (plage AgentB2C : 8100 concierge / 8101 search / 8102 faq) |
| `A2A_BEARER_TOKEN` | — **(obligatoire)** | Bearer entrant D7, vérifié par `serve.py` — fail-closed au boot si absent/vide |

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
