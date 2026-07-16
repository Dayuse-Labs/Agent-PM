# Découpage en sessions Claude Code — dev AgentB2C

> **Détail par session : `phases/S01…S11.md`** (un MD autonome par phase : périmètre, étapes, DoD, modèle). **Prompts de lancement, timeline, parallélisation worktrees et modèles : `PROMPTS-SESSIONS.md`.** Ce fichier reste la vue d'ensemble.

> Objectif : chaque session tient largement dans une context window et se termine sur un état commité + `HANDOFF.md` à jour. Une session = UN scope. `/clear` entre deux sessions ; ne jamais enchaîner deux scopes dans la même fenêtre.

## Règles de session (toutes les sessions)

1. Démarrer : lire `CLAUDE.md` (auto) puis `HANDOFF.md`, puis UNIQUEMENT les entrées listées pour la session.
2. Ne jamais lire agent-usa en entier — les tests pointés servent de spec, c'est tout.
3. Finir : DoD exécutée verte → `HANDOFF.md` mis à jour → commit branche + MR (review Fabien = gate).
4. Si un choix fondateur émerge en cours de session : STOP, le noter dans HANDOFF, demander à Fabien — pas de décision solo.

## Sessions

| # | Scope (1 session) | Entrées à lire | DoD exécutable | Prérequis externes |
|---|---|---|---|---|
| S1 | `git init` (+`.gitignore` : `baseline/`, `.env`) · scaffold `hotel-search-agent` (`/scaffold-agent` + `/wire-a2a`) : squelette, client MCP staging, bearer D7, Agent Card | BRIEF §1-3 | agent boote, card servie sur `/.well-known/agent-card.json`, `dayuse_guardrails.sh` vert | Hook plugin vérifié |
| S2 | Scaffold `faq-agent` (+wire-a2a) · scaffold `b2c-concierge` (`/scaffold-orchestrator`) : spine code-owned, triage éco+regex, table de routage, RemoteA2aAgent ×2, tools MCP inline stubs | BRIEF §2-3, fleet `cs_copilot/agent.py` (pattern) | ping E2E local : orchestrateur → 2 feuilles → réponse ; ≤3 LLM/tour vérifié par compteur | S1 mergée |
| S3 | Socle transverse : `dayuse_agent_common` en dépendance (metrics_pg service=`b2c-*`, identité intérimaire), CI GitLab (lint/typecheck/tests/guardrails), harnais `/eval-agent` branché sur `evalset/evalset-v0.json` converti au format ADK | BRIEF §3, evalset | CI verte en local ; `adk eval` tourne (échecs fonctionnels OK à ce stade) ; lignes dans `llm_metric_events` | S2 mergée |
| S4 | Feuille search RÉELLE : géocoding Mapbox + portage des 3 guards géo (echo-back, state anchoring, generic place words) avec leurs tests, budgets/circuit-breaker | agent-usa : `test_audit_fixes_2026_06.py` (sections géo) + `search_tool.py:_geocode_echo_matches` seul | tests géo portés verts (~30) | Tools MCP_B2C mergés (review Fabien) |
| S5 | Profil de session : service Redis côté orchestrateur, `DataPart` in/out, guards profil (budget integrity, timeslot sanitization, ancres état/pays) + tests | agent-usa : tests budget/timeslot/state | tests portés verts ; feuille prouvée stateless (aucun accès Redis) | S4 |
| S6 | Synthèse & SSE : UNE synthèse streamée, ground-truth block (≤5 hôtels), anti-clarification-loop, recovery acks, i18n de sortie + tests | agent-usa : tests loop/acks/ground-truth | tests portés verts ; SSE : event progress <300 ms mesuré en local | S5 |
| S7 | Tools inline + R9 : details/compare/booking-link, guard n°12 (confirmation en code), amenity claim verifier + tests | agent-usa : tests amenity/named-hotel ; MCP `generate_booking_link` (flag confirmed) | 12/12 guards verts (~150 tests portés) | S6 |
| S8 | Batteries : portage conversation-regression (familles evalset), release gate (`--quick` inclus), assertions budget LLM/tour, `adk eval` complet | agent-usa : `run_dynamic_conversation_regression.py`, `run_release_gate.py` (structure seulement) | gate verte sur les 32 scénarios + baselines posées | S7 |
| S9 | Façade : `POST /v3/chat` iso-contrat (champs identiques, sessions Redis) + endpoint SSE + `is_synthetic` + logs conversation | agent-usa : `chat.py` (contrat de sortie SEULEMENT — schéma JSON) | contrat validé par tests golden (mêmes clés/formes qu'agent-usa) | S8 |
| S10 | Shadow-run (Ph3.3) : harness dual-run vs agent-usa, rapport parité (recouvrement top-N, judge, latence, fraîcheur) | plan §5 Ph3.3 | rapport chiffré généré | **ES prod** (URL lecture seule) + MCP_B2C déployé (5.1) |
| S11 | Déploiement & canary (Ph5) : Railway (min-instances 1, réseau privé), canary %, critères rollback écrits, A/B synthétique latence | BRIEF §3-4, plan Ph5 | stack déployée, canary actif, dashboard A/B | Validation Fabien explicite avant tout trafic |

Estimation : S1-S3 = fondations (~1 sem), S4-S8 = le cœur portage (~2-3 sem), S9-S11 = migration (~1-2 sem). S4-S8 sont parallélisables par paires prudentes (S4/S5 touchent des zones disjointes) via worktrees, mais séquentiel = zéro conflit.

## Loop engineering — où ça s'applique (et où non)

Principe retenu : sessions fraîches bornées + état durable dans les fichiers (`HANDOFF.md` = mémoire, DoD exécutable = critère d'arrêt objectif). C'est déjà la pratique de la fleet (HANDOFF + « do not rebuild »).

**Bon terrain (S4-S8)** — le portage des guards est test-driven : la boucle a un critère d'arrêt mécanique (« tests portés verts »), des itérations petites (1 guard = 1 itération), zéro décision fondatrice. Protocole :
- `PROMPT-LOOP.md` fixe : « lis HANDOFF.md, prends LE premier item non fait de la session courante, implémente, fais tourner les tests, mets à jour HANDOFF, commit. Un seul item. »
- Boucle externe : relancer la session tant que la DoD n'est pas verte, **budget d'itérations plafonné** (ex. 15), et **stop conditions** : même test rouge 2 itérations de suite → STOP et question à Fabien ; toute envie de modifier la spec (les tests) → STOP.
- Jamais de `git push`/merge dans la boucle : elle commit en local sur branche, l'humain pousse et merge.

**Mauvais terrain** : S1-S3 (scaffolding = skills interactifs + choix de structure — à faire en session pilotée), S9 (contrat front = zone à jugement), S10-S11 (prod, données réelles — jamais en boucle autonome).

**Risques à garder en tête** : une boucle « verte » peut le devenir en affaiblissant les tests (d'où : tests = spec intouchable, le diff de tests est un signal de STOP) ; et le coût tokens croît vite — la boucle ne vaut que sur les scopes répétitifs où elle bat une session pilotée.
