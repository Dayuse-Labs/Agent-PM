# HANDOFF — AgentB2C

État du chantier pour reprise en session fraîche. **Lire en entier avant d'agir ; ne pas reconstruire ce qui existe.** Mettre à jour en fin de CHAQUE session (bloc daté en tête).

## ⏱ État au 2026-07-16 (initialisation, avant toute session de dev)

**Fait (hors de ce repo)** :
- Phase 0 complète : audit + baseline prod nettoyée + evalset → `AUDIT-REWORK-2026-07.md`, `evalset/evalset-v0.json` (32 scénarios, 8 familles), `baseline/` (données brutes, NE PAS COMMITER).
- MCP_B2C : les 6 tools sont codés et verts (459 tests, 98,6 %) — **les 2 derniers (`get_faq_conditions`, `generate_booking_link`) sont en review par Fabien, non mergés**. Docker/README du MCP (5.1/5.2) volontairement en attente.
- Design review D1 : GO avec réserves, décisions actées dans `PLAN-REWORK-AGENT-USA.md` §9 (D1 : 2 feuilles A2A — décision produit ; D7 : identité intérimaire ; B3 : feuilles stateless ; spine code-owned).

**Pas fait (ce repo)** : tout le code. Aucun scaffolding lancé. Pas de `git init`.

**Prochaine étape** : lancer S1 avec le prompt de `PROMPTS-SESSIONS.md` (modèle Opus). Détail : `phases/S01-socle-feuille-search.md`. Le suivi d'avancement des items de phase se tient ICI (compteurs par session).

**Pièges connus** :
- Le hook `PreToolUse` du plugin peut bloquer les écritures locales si la build installée est divergente (matcher sain = `mcp__gitlab__…|mcp__notion__…` uniquement — vérifier avant S1).
- Le MCP_B2C accessible en dev pointe sur l'ES de **staging** : notes/avis quasi vides, inventaire partiel. OK pour développer, INTERDIT pour le shadow-run/parité (exige ES prod, cf. plan Ph3.3).
- `oidc-mtls` de `dayuse_agent_common` est un stub `NotImplementedError` — d'où D7 intérimaire.
- La fleet a évolué : `cs_copilot` (spine code-owned conversationnel) et `booking_qa` (feuille cliente MCP streamable-http) sont les précédents à imiter.
