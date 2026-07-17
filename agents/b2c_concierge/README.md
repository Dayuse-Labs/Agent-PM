# b2c-concierge

Orchestrateur conversationnel B2C de Dayuse (ADK Python + LiteLLM, portable) — **spine code-owned** (pattern `cs_copilot` de la fleet : custom `BaseAgent`, PAS de LlmAgent + sub_agents libre). Remplace `agent-usa`. Squelette S2 : les 12 guards arrivent en S4-S7, la façade `/v3/chat` + SSE en S9, la synthèse riche/streamée en S6, `dayuse_agent_common` (metrics, build_model) en S3, le Redis de session + profil en S5.

## Flux d'un tour (budget structurel ≤ 3 appels LLM)

1. **Fast-path ack** (`triage.py`) — message purement social → template, **0 LLM**.
2. **Triage** — 1 appel LLM **éco** (`DAYUSE_MODEL`) classifiant `{family, language}`, litellm direct hors session ADK ; **fallback regex** sur tout échec (jamais de retry : LiteLLM est la seule couche de retry).
3. **Routage en code** (`routing.py`) — aucune décision de contrôle par LLM :

| Family | Action |
|---|---|
| `search` | `RemoteA2aAgent` → feuille **hotel-search-agent** (:8101) |
| `faq` | `RemoteA2aAgent` → feuille **faq-agent** (:8102) |
| `details` / `compare` / `booking` | tools MCP inline — **STUBS S2** (`inline_tools.py`), réponse template honnête, 0 LLM de plus |
| `ack` | template (`templates.py`) |

4. **Appel feuille** — timeout **10 s SANS retry**, propriété de l'orchestrateur (`asyncio.timeout` = le vrai plafond ; httpx keep-alive persistant + bearer D7 sortant). Échec/timeout → **dégradation honnête** : un message qui le dit, zéro invention.
5. **UNE synthèse LLM** par tour (squelette — streaming en S6). Échec de synthèse → texte de la feuille servi tel quel (grounded).

Le compteur d'appels LLM par tour (`budget.py`) est instrumenté dès maintenant : dépasser 3 lève `LlmBudgetExceededError` (un guard ne relance jamais une boucle), et le test `tests/test_spine.py::test_simple_search_turn_stays_within_llm_budget` échoue si un tour simple dépasse le budget. R9 (lien de réservation inappelable sans flag de confirmation) est porté par le stub `generate_booking_link` — il ne produit AUCUN lien par construction — et devient un guard exécutable en S4-S7.

## Lancer / tester

```bash
bash scripts/run_local.sh        # boote les 3 services (concierge sur :8100)
python scripts/smoke_e2e.py      # 1 tour ack + 1 search + 1 faq via l'orchestrateur
.venv/bin/pytest -q              # tests offline (ni réseau ni clé API)
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
| `CONCIERGE_LEAF_TIMEOUT_SECONDS` | `10.0` | Budget appel feuille, propriété de l'orchestrateur — SANS retry |
| `CONCIERGE_TRIAGE_TIMEOUT_SECONDS` | `5.0` | Timeout du classify éco (échec → fallback regex) |
| `CONCIERGE_SYNTHESIS_TIMEOUT_SECONDS` | `15.0` | Timeout de la synthèse |
| `CONCIERGE_SYNTHESIS_NUM_RETRIES` | `1` | Retries LiteLLM (seule couche de retry LLM) |
| `A2A_HOST` | `localhost` | Hôte joignable par les pairs — écrit dans l'URL de la carte servie |
| `PORT` | `8100` | Port d'écoute (plage AgentB2C : 8100 concierge / 8101 search / 8102 faq) |
| `A2A_BEARER_TOKEN` | — **(obligatoire)** | Bearer **entrant** D7, vérifié par `serve.py` — fail-closed au boot |

Un token sortant vide n'est pas fatal au boot : la feuille fail-closed répond 401 et le tour dégrade honnêtement (jamais d'auth contournée). `scripts/run_local.sh` partage un même token local pour les 3 services.

## ⚠️ Exception d'identité intérimaire (D7) — avec échéance

Même régime que les feuilles : réseau privé Railway + bearer statique (entrant vérifié par `serve.py`, sortant porté par les clients httpx des legs), carte servie **non signée** (`sign_agent_card` non implémenté). **Échéance : bascule oidc-mtls au plus tard avant le canary S11.** Suivi dans `HANDOFF.md`.

## RGPD

- **Sessions** : le Redis de session (TTL + rétention documentées) appartient à l'orchestrateur seul et arrive en **S5** — en S2 les sessions vivent en mémoire du process A2A (éphémères).
- **Logs/métriques** : AUCUN contenu de message — uniquement family/route/compteurs/latences, verrouillé par test côté logs (`test_logs_never_contain_message_content`) ET côté événements `llm_metric_events` (`test_metric_events_never_contain_message_content`). Depuis S3, chaque tour est aussi mirroré en Postgres via `dayuse_agent_common.metrics_pg` (`service=b2c_concierge`, no-op sans `DATABASE_URL`).
- **Résidence EU** du provider modèle derrière LiteLLM : à vérifier AVANT tout trafic réel (précondition de prod, cf. brief §4).

## ⚠️ Staging ≠ shadow-run

Les feuilles pointent en dev sur le MCP_B2C de **staging** (notes/avis quasi vides, inventaire partiel). OK pour développer, INTERDIT pour le shadow-run/la parité (exige l'ES prod, cf. plan Ph3.3).
