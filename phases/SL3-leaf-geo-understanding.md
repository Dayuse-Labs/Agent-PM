# S-L3 — Leaf `geo_understanding_agent` (nouvel agent A2A)

| | |
|---|---|
| **Mode** | Piloté — scaffolding interactif (skills du plugin) + réglage du prompt = jugement |
| **Modèle** | **Opus** (`claude-opus-4-8`) |
| **Branche/worktree** | `git worktree add ../AgentB2C-sl3 -b sl3-geo-leaf` (après le merge de S-L2) |
| **Zone autorisée** | `agents/geo_understanding_agent/**` (neuf) · `scripts/run_local.sh` · `scripts/eval_geo_intent.py` (neuf) · `CLAUDE.md` (commandes d'installation, ports) — NE PAS toucher `agents/b2c_concierge/**` ni `agents/hotel_search_agent/**` |
| **Prérequis** | S-L2 mergée (contrat `GeoIntent`, jeu `b2c-geo-intent`, seuil proposé) |
| **Durée cible** | non estimée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-LEAF-GEO-2026-10-08.md` (§1-3, E7 et E15) · `agents/faq_agent/**` (le patron de feuille le plus court : `agent.py`, `contract.py`, `serve.py`, `Dockerfile`, `agent-card.json`, `requirements.txt`, `tests/`) · `agents/hotel_search_agent/hotel_search_agent/agent.py:148-198` (règles géo actuelles, à reprendre) · skills du plugin `dayuse-agentic-platform` : `scaffold-agent`, `wire-a2a` (checklists).

## Périmètre
**IN** :
1. **Revue de conception** : sous-agent `agent-design-reviewer` sur le design (leaf, contrat, D7). La réserve D7 est attendue et documentée (CHANTIERS A1).
2. **Package calqué sur `faq_agent`** :
   - `agent.py` : `LlmAgent` avec le modèle via LiteLLM — `build_model(role_model("GEO"))`, donc `DAYUSE_MODEL_GEO` puis `DAYUSE_MODEL` (`libs/b2c_common/b2c_common/llm_params.py:58`) ; `output_schema=GeoIntent` ; aucun outil ; `include_contents="none"` ; les callbacks de métriques et d'observabilité des autres feuilles (jamais de contenu de message dans les métriques) ; un `after_agent_callback` qui renvoie `{geo_intent, diagnostics}` en DataPart (patron `emit_search_datapart`, `response_bridge.py:1503`).
   - `contract.py` : enveloppe d'entrée (message + contexte minimal du plan §3) et de sortie.
   - `serve.py` : copie du patron D7 de `faq_agent/serve.py` — bearer obligatoire, démarrage refusé sans jeton, carte non signée, `A2aTurnObservation` ; port 8103.
   - `Dockerfile`, `agent-card.json`, `requirements.txt` (mêmes épinglages que `faq_agent`, sans `mcp`), `README.md`.
3. **Instruction** : les règles géo de la feuille (`agent.py:148-198`) réécrites en extraction de types fermés ; exemples tirés du seul split `dev`.
4. **`scripts/run_local.sh`** : 4e service `geo_understanding_agent:geo_understanding_agent.serve:8103`, et surcharge `GEO_UNDERSTANDING_CARD_URL` avec `PORT_OFFSET` (patron des lignes 42-44 et 52-54).
5. **`scripts/eval_geo_intent.py`** : exactitude champ par champ sur `b2c-geo-intent` (`--split dev|test`), appels réels donc payants.
6. **Audit** : sous-agent `portability-compliance-auditor` sur le package produit.
7. **Choix du modèle** : le plus petit qui passe le seuil sur `test` ; noter latence et coût par appel.

**OUT** : tout appel depuis le concierge (S-L4) · tout outil dans la leaf (géocodage = phase 2) · signature de la carte (attend oidc-mtls).

## Étapes
1. Revue de conception → verdict dans HANDOFF.
2. Squelette + tests hors ligne (modèle simulé) : sortie valide, sortie invalide refusée proprement, bearer exigé.
3. Instruction réglée sur `dev`, puis un seul passage sur `test`.
4. Stack locale à 4 services, appel A2A direct de la leaf (carte servie, 401 sans bearer).
5. Audit de portabilité.

## DoD (exécutable)
```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
.venv/bin/python scripts/eval_geo_intent.py --split test     # live, payant : seuil fixé en S-L2
```

## Fin de session
HANDOFF (verdicts du reviewer et de l'auditeur, modèle retenu, scores dev/test, latence et coût par appel) · commit + MR. La leaf n'est appelée par personne à la fin de cette session.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-LEAF-GEO-2026-10-08.md (§1 à §3), agents/faq_agent/ (en entier),
puis phases/SL3-leaf-geo-understanding.md, et exécute cette phase dans ce périmètre exactement.
Règles : revue de conception (agent-design-reviewer) avant tout code ; la leaf n'a aucun outil et ne produit
jamais de coordonnées ; D7 comme les autres feuilles ; prompt réglé sur le split dev uniquement ; audit de
portabilité à la fin ; fin = DoD verte + HANDOFF + commit sur branche, jamais de merge.
```
