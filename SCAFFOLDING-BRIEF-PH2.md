# Brief de scaffolding Phase 2 — à exécuter dans Claude Code

> 2026-07-15 · Pour la session **Claude Code** (là où vivent le plugin `dayuse-agentic-platform` et les skills `google-agents-cli-*`, absents de Cowork).
> Réfs : `PLAN-REWORK-AGENT-USA.md` (§4 amendé, décisions D1-D7), `AUDIT-REWORK-2026-07.md`, design review du 2026-07-15 (GO avec réserves — résumée ici).

## 0. Avant toute chose

- ⚠️ **Vérifier le hook `PreToolUse` du plugin** : la build Cowork matche `Write|Edit|...` et bloque les écritures locales. Si la build Claude Code a le même défaut, le scaffolding sera bloqué. Le matcher sain (repo source `DayuseAgency/dayuse-agentic-platform/hooks/hooks.json`) ne matche que `mcp__gitlab__…`/`mcp__notion__…`.
- Repo cible : ce dossier (`AgentB2C/`), à `git init` en premier — **avec `.gitignore` incluant `baseline/`** (messages utilisateurs bruts, RGPD).

## 1. Décisions qui contraignent le scaffold

| Décision | Contenu |
|---|---|
| D1 (produit) | **2 feuilles A2A** : `hotel-search-agent` + `faq-agent`. La design review recommandait une seule (faq sans critère de mutualisation plein) — décision produit assumée, en contrepartie faq applique strictement les parades latence ci-dessous |
| D7 | Identité intérimaire : réseau privé Railway (`*.railway.internal`) + bearer statique vérifié côté feuille, exception documentée avec échéance dans le README de chaque service. `oidc-mtls` (stub dans la lib) viendra plus tard. `dev-insecure` jamais déployé |
| B3 | **Feuilles stateless** : profil in/out via payload A2A (`DataPart`), le Redis de session n'appartient qu'à l'orchestrateur |
| D3 | LiteLLM, `DAYUSE_MODEL=gpt-4o-mini` au départ (comparaison iso-modèle) |

## 2. Ordre de scaffolding

1. `/scaffold-agent` → **`hotel-search-agent`** (feuille A2A)
   - Tools MCP_B2C : `search_offers`, `find_hotel_by_name` (streamable-http, env `MCP_B2C_URL` + `MCP_B2C_AUTH_TOKEN`)
   - Géocoding **Mapbox interne** (`MAPBOX_TOKEN` — secret propre à cette feuille) + portage des guards géo d'agent-usa : geocode echo-back, state anchoring, generic place words (leurs ~30 tests = la spec)
   - **Stateless** : entrée `{query_params, profile_in}`, sortie `{results, profile_delta}` ; 0-1 appel LLM interne max ; retries + circuit-breaker Mapbox/MCP possédés ICI (Mapbox timeout 1,5 s / 1 retry ; MCP timeout 5 s)
2. `/scaffold-agent` → **`faq-agent`** (feuille A2A — décision produit)
   - Tool MCP_B2C : `get_faq_conditions` ; stateless, 0-1 LLM interne, keep-alive httpx, réseau privé — aucun hop superflu au-delà de la frontière assumée
3. `/wire-a2a` sur les deux — Agent Cards signées (JWS/JCS), `securitySchemes` = bearer intérimaire (D7), servies sur `/.well-known/agent-card.json`
4. `/scaffold-orchestrator` → **`b2c-concierge`**
   - **Spine code-owned** (pattern `cs_copilot` : custom BaseAgent, PAS LlmAgent+sub_agents libre) : triage 1 appel LLM éco + fallback regex, table de routage en code, `RemoteA2aAgent` vers les 2 feuilles
   - Tools MCP inline : `get_hotel_details`, `compare_hotels`, `generate_booking_link`
   - **12 guards déterministes** en code (les 11 d'agent-usa — spec = `tests/unit/application/test_audit_fixes_2026_06.py` + fichiers dédiés, ~150 tests — **+ R9** : `generate_booking_link` inappelable sans flag de confirmation dans l'état du tour). Un guard ne relance jamais une boucle : 1 retry borné, puis correction déterministe
   - **Budget structurel ≤ 3 appels LLM/tour** typique (triage + LLM feuille éventuel + synthèse) ; UNE synthèse streamée ; mini tool-loop borné ≤ 2 itérations réservé à la synthèse ; prompt à préfixe stable (cache), ground-truth block ≤ 5 hôtels, historique tronqué
5. `/eval-agent` — brancher `evalset/evalset-v0.json` (32 scénarios, 8 familles) au format ADK + job `adk eval` en CI, avec les invariants Dayuse
6. CI GitLab : lint/typecheck/tests + `dayuse_guardrails.sh` (zéro lock-in)

## 3. Contrats & budgets (à respecter dans le scaffold)

- **A2A `DataPart`** : `{query_params, profile_in}` → `{results, profile_delta, diagnostics}` — l'Agent Card fige ce contrat
- **Timeouts, propriétaire unique par dépendance** : feuille → Mapbox 1,5 s (1 retry) et MCP 5 s (circuit-breaker) ; orchestrateur → appel feuille 10 s **sans retry** (dégradation honnête via ground-truth) ; retries LLM au seul niveau LiteLLM (jamais de couche de retry imbriquée — leçon de l'audit : ~6 tentatives × 60 s pire cas aujourd'hui)
- **SSE (façade)** : événement `progress` immédiat (< 300 ms — c'est LE TTFT mesuré), événement `hotels` dès le retour feuille, tokens de synthèse ensuite ; le contrat JSON iso-`/v3/chat` reste servi en non-streamé
- **Infra** : min-instances 1 partout (orchestrateur, 2 feuilles, MCP_B2C) ; services co-localisés réseau privé Railway ; clients httpx persistants
- **Observabilité jour 1** : `dayuse_agent_common.metrics`/`metrics_pg` → `llm_metric_events` (même Postgres Railway), `service=b2c-*` — le dashboard existant fait le before/after ; zéro contenu de message dans les métriques (verrouillé par test)

## 4. RGPD — préconditions de prod (à documenter dans les README des services)

Résidence EU du provider modèle derrière LiteLLM (à vérifier AVANT tout trafic réel) · TTL sessions Redis + politique de rétention `conversation_logs` · colonne `is_synthetic` dès le jour 1 (les batteries QA polluent la table actuelle : 49 % du volume) · secrets V1 (`MCP_B2C_AUTH_TOKEN`, `MAPBOX_TOKEN`) en exception documentée avec échéance broker · `baseline/` gitignoré.

## 5. Après le scaffolding

Revenir en session Cowork pour la Phase 3 : portage détaillé des guards (les tests d'agent-usa comme spec), intégration MCP_B2C réelle, puis shadow-run **sur ES de prod** (exigence : jamais sur staging — données et latence non représentatives).
