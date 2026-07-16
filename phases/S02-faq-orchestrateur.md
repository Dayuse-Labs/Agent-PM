# S02 — Feuille `faq-agent` + orchestrateur `b2c-concierge` (spine)

| | |
|---|---|
| **Mode** | Session pilotée (PAS de loop — cœur architectural) |
| **Modèle** | Opus (`claude-opus-4-8`) |
| **Branche** | `s2-faq-orchestrateur` |
| **Prérequis** | S1 mergée |
| **Durée cible** | 1 journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `SCAFFOLDING-BRIEF-PH2.md` §2-3 · **pattern de référence : `~/Projects/DayuseAgency/dayuse-agent-fleet/agents/cs_copilot/cs_copilot/agent.py`** (spine code-owned conversationnel : triage regex+LLM éco, table de routage, événements de progression)

## Périmètre
**IN** : feuille faq (squelette), orchestrateur spine complet (routage, budget, compteur), câblage A2A des 2 feuilles, tools MCP inline en stubs.
**OUT** : guards (S4-S7), SSE façade (S9), synthèse riche (S6).

## Étapes
1. `/scaffold-agent` → `faq-agent` : tool MCP `get_faq_conditions`, stateless, 0-1 LLM interne, keep-alive httpx. Feuille VOLONTAIREMENT minimale (décision produit D1 : feuille séparée malgré la review — les parades latence sont non négociables).
2. `/wire-a2a` sur faq-agent (bearer D7, card signée).
3. `/scaffold-orchestrator` → `b2c-concierge` en **custom BaseAgent** (PAS LlmAgent+sub_agents libre) :
   - triage de tour : 1 appel LLM éco + fallback regex (social ack templaté = 0 LLM) ;
   - table de routage EN CODE : search → RemoteA2aAgent(hotel-search), faq → RemoteA2aAgent(faq), details/compare/booking → tools MCP inline (stubs), ack → template ;
   - **compteur d'appels LLM par tour instrumenté dès maintenant** + test qui échoue si > 3 sur un tour simple ;
   - timeout appel feuille 10 s SANS retry, dégradation honnête (message + pas d'invention) ;
   - une synthèse LLM unique par tour (squelette — le streaming arrive en S6).
4. Script `run_local.sh` étendu : orchestrateur + 2 feuilles + pids + logs.

## DoD (exécutable)
```bash
bash scripts/run_local.sh
python scripts/smoke_e2e.py   # 1 tour search + 1 tour faq via l'orchestrateur → réponses non vides
pytest -q                     # dont test budget ≤3 LLM/tour
bash scripts/dayuse_guardrails.sh .
```

## Fin de session
HANDOFF (ports, routage, TODO stubs) · commit + MR.
