# faq-agent

Feuille A2A FAQ/politiques pour l'orchestrateur `b2c-concierge` (ADK Python + LiteLLM, portable). Consomme le tool **lecture seule** du serveur MCP_B2C (`get_faq_conditions`) en Streamable HTTP. Squelette S2 : `dayuse_agent_common` (metrics, budget tool-calls) arrive en S3.

## Pourquoi une feuille séparée (décision produit D1)

La design review recommandait d'inliner la FAQ dans l'orchestrateur (critères de mutualisation non pleins). La décision produit D1 maintient une feuille séparée — **en contrepartie, les parades latence sont non négociables ici** :

- **0-1 appel LLM interne** par requête, jamais de boucle de tool-calls ;
- **connexions persistantes (keep-alive)** : le `McpToolset` maintient une session Streamable HTTP unique vers MCP_B2C, les clients httpx de l'orchestrateur sont persistants ;
- **co-localisation réseau privé Railway** (aucun hop superflu au-delà de la frontière assumée), min-instances 1.

## Contrat (stateless — décision B3)

La feuille ne détient AUCUN état : pas de Redis, pas de session — le Redis de session appartient à l'orchestrateur seul. Tout transite par le `DataPart` A2A (`faq_agent/contract.py`), même enveloppe que hotel-search-agent :

- **Entrée** `FaqRequest` : `query_params` (question/sujet FAQ) + `profile_in` (instantané du profil, propriété de l'appelant).
- **Sortie** `FaqResponse` : `results` (contenu conditions/politiques renvoyé par le tool, jamais inventé) + `profile_delta` (seuls les faits NOUVEAUX appris ce tour) + `diagnostics` (appels effectués, dégradations — jamais montré à l'utilisateur).

S2 fige l'enveloppe uniquement ; les champs métier internes suivent les mêmes sessions de durcissement que la recherche (S4/S5).

⚠️ Côté MCP_B2C, `get_faq_conditions` est **en review, non mergé** (état au 2026-07-16) : tant qu'il n'est pas exposé par le serveur, l'allowlist filtre à zéro tool et la feuille répond en le disant dans `diagnostics` (jamais d'invention).

## Lancer / tester

Depuis la racine du repo (voir `CLAUDE.md` § Commandes) :

```bash
bash scripts/run_local.sh        # boote les 3 services (faq sur :8102)
.venv/bin/pytest -q              # tests offline (ni réseau ni clé API)
bash scripts/dayuse_guardrails.sh .
```

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `DAYUSE_MODEL` | `gpt-4o-mini` | Slug LiteLLM (D3 — jamais de SDK cloud direct) |
| `OPENAI_API_KEY` | — | Clé du provider LiteLLM (aucun appel au boot, connexions lazy) |
| `MCP_B2C_URL` | `http://localhost:8099/mcp` | Serveur MCP_B2C Streamable HTTP (placeholder local ; staging via `.env`) |
| `MCP_B2C_AUTH_TOKEN` | (vide) | Token MCP **brut** dans `Authorization` (le serveur refuse le schéma `Bearer` — contrat observé) ; header omis si vide, jamais dans le contexte modèle |
| `FAQ_MCP_TIMEOUT_SECONDS` | `5.0` | Budget MCP, propriété de cette feuille |
| `A2A_HOST` | `localhost` | Hôte joignable par les pairs — écrit dans l'URL de la carte servie |
| `PORT` | `8102` | Port d'écoute (plage AgentB2C : 8100 concierge / 8101 search / 8102 faq) |
| `A2A_BEARER_TOKEN` | — **(obligatoire)** | Bearer entrant D7, vérifié par `serve.py` — fail-closed au boot si absent/vide |

## ⚠️ Exception d'identité intérimaire (D7) — avec échéance

L'identité cible (oidc-mtls de `dayuse_agent_common`) est un stub `NotImplementedError`. En attendant, cette feuille applique le régime intérimaire D7, PLUS strict que la fleet (qui ne vérifie aucun bearer entrant) :

- **Réseau privé Railway** + **bearer statique vérifié côté feuille** : toutes les routes exigent `Authorization: Bearer $A2A_BEARER_TOKEN` (comparaison à temps constant), SAUF `/.well-known/agent-card.json` (découverte).
- **Fail-closed** : token absent ou vide → `RuntimeError` au démarrage. `dev-insecure` n'est jamais déployé.
- **Carte servie NON signée** (`sign_agent_card` non implémenté) — incluse dans l'exception. La carte déclare `securitySchemes.bearer-interim` pour que les appelants découvrent le schéma.

**Échéance** : bascule sur oidc-mtls dès que la lib l'implémente, **au plus tard avant le canary S11**. Cette exception est documentée ici et suivie dans `HANDOFF.md`.

## RGPD

- **Nature des données** : les questions FAQ peuvent contenir du texte libre utilisateur et un instantané de profil — données personnelles potentielles. La feuille ne persiste RIEN (stateless) : aucune base, aucun log applicatif de contenu de message ; les métriques (S3) n'embarqueront jamais de contenu de message (verrouillé par test côté socle).
- **Transit** : orchestrateur → feuille sur le réseau privé Railway (bearer D7) ; feuille → MCP_B2C en HTTPS avec bearer en header (jamais dans le contexte modèle) ; feuille → provider LLM via LiteLLM (`DAYUSE_MODEL`).
- **Résidence** : déploiements en région **EU** uniquement (zéro lock-in cloud : même image OCI pour Cloud Run / k8s / Railway).

## ⚠️ Staging ≠ shadow-run

Le MCP_B2C accessible en dev pointe sur l'Elasticsearch de **staging** : notes/avis quasi vides, inventaire partiel. **OK pour développer, INTERDIT pour le shadow-run/la parité** (exige l'ES prod, cf. plan Ph3.3).
