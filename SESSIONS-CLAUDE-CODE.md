# Découpage en sessions Claude Code — dev AgentB2C

> **Détail par session : `phases/S10…S11.md`** (jamais lancées, cf. `CHANTIERS.md` A2). S01-S09, S12-S14 et leurs prompts (`PROMPTS-SESSIONS.md`) sont livrés : fichiers retirés au nettoyage du 2026-10-19 (historique git). Ce fichier reste la vue d'ensemble.

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

## Sessions S-G — remédiation geo/multi-turn (arbitrée 2026-07-23)

> Source : `REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md` (audit) + `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` (plan arbitré, décisions A1-A8). Sessions SG1-SG9 toutes livrées : fichiers de phase retirés au nettoyage du 2026-10-19 (historique git). Recherche à l'appui : `reports/research/*.md`.

| # | Scope (1 session) | Zone | Prérequis | Durée |
|---|---|---|---|---|
| S-G1 | Profil v2 : schéma complet (named_hotel, zone, date+référence, devise, ancre GPS, shown_ids, curseur) + reducer ops typées (set/clear, absent=carryover, rétro-compat delta plat) + `active_filters` dé-nullé | concierge | — | 1 j |
| S-G2 | Intake contexte natif : GPS/locale/domaine/devise/timezone lus du body (probe du widget vendorisé = spec), ancre taguée + règle no-silent-downgrade | facade | S-G1 | ½ j |
| S-G3 | Résolveur géo multi-candidats : probe live Mapbox D'ABORD (tranche Search Box), limit=10 + language + proximity, ranker déterministe inventory-aware (snapshot statique), clarify-once, cartes avec lat/lon/distance | feuille | token Mapbox | 1,5-2 j |
| S-G4 | Budgets timeout par famille (search/faq) + LiteLLM RetryPolicy/stream_timeout + instrumentation par phase + root-cause Chester | concierge (+instr. feuille) | — | ½-1 j |
| S-G5 | Pont déterministe profil→geocode (before_tool_callback, pattern equipment_ids) + pagination shown_ids/curseur/disclosure (probe search_offers d'abord) | feuille + concierge | S-G1+S-G3 | 1 j |
| S-G6 | Dates (LLM étiquette / code calcule, timezone client), durées ≠ fenêtres (core-e2e-201), demi-heures bout-en-bout (core-e2e-084, post-filtre intérim + demande schéma MCP) | feuille + concierge | S-G1+S-G2, après S-G5 | 1 j |
| S-G7 | Locale→Mapbox language + prior ranker, response_language, devise stockée + disclosure display EUR, probe pricing MCP | feuille + concierge | S-G2+S-G3, après S-G6 | ½ j |
| S-G8 | Durcissement harness : les 8 items de l'audit en couche d'annotation `scripts/` (pack byte-identique, assertions manquantes = skipped divulgué) | scripts/ | — | 1 j |
| S-G9 | Gate 81 cas ×3 replays + rapport 7 critères + design éval ranking (precision@5/NDCG@5) — mesure seulement, jamais de fix | scripts/ + reports/ | S-G1→S-G8 | 1 j |

### Timeline & parallélisation

```
Fenêtre 1                Fenêtre 2                Fenêtre 3        Fenêtre 4
S-G1 ∥ S-G3 ∥ S-G4  →    S-G2 ∥ S-G5 ∥ S-G8  →    S-G6 → S-G7  →   S-G9
(worktrees ; merge       (merge S-G2 d'abord)     (séquentiel :    (gate, piloté,
 S-G1 d'abord)                                     mêmes fichiers   jamais loop)
                                                   feuille)
```

Ordre de merge des fenêtres parallèles : **numéro le plus bas d'abord**, les autres rebasent. Estimation totale : ~2 semaines.

### Modèles & modes

| Session | Modèle | Mode |
|---|---|---|
| S-G3 | **Opus** | piloté (design ranker + probes = jugement) |
| S-G1, S-G5, S-G6, S-G8 | Sonnet | piloté puis **loop possible** (spec exécutable, tests d'abord) |
| S-G2, S-G4, S-G7 | Sonnet | piloté (courts) |
| S-G9 | Sonnet | piloté, **jamais loop** (mesure, données réelles) |

### Décisions arbitrées (2026-07-23, Fabien) — ne pas re-litiger en session

A1-a snapshot inventaire statique (provider swappable) · A2-b Search Box tranché par le probe S-G3 · A3-a ops typées · A4-c demi-heures : post-filtre intérim + demande schéma MCP (⚠️ vérifié NON corrigé sur main : `agent.py:144` heures entières, `response_bridge.py:202-203` minute=0 — seul l'AFFICHAGE des offres lit les minutes) · A5-a budgets statiques par famille (deadline propagation = plus tard) · A6-a contexte maintenant, pricing gated sur probe MCP · A7 probe search_offers d'abord · A8-a instrumenter avant tout reranker. Hedging : rejeté. Flag ops : contrôle plateforme de `DAYUSE_MODEL` requis avant toute comparaison canary.

## Sessions S-L — leaf de compréhension géo (arbitrée 2026-10-08)

> **Mise à jour 2026-10-16 : cette section est en grande partie remplacée par le plan QA14707** (`plans/qa14707/`, source `phases/QA14707/`). Décision DQ1 : le `GeoIntent` (contrat v1.1) est produit par la feuille de recherche, comme argument de `geocode_location`, sans leaf dédiée. S-L2 est tenue par Q06, le mapping côté feuille de S-L5 par Q07 et Q08, S-L7a et S-L7f par Q09 et Q10. S-L3, S-L4 et S-L8 sont conditionnelles (voir `CHANTIERS.md` § L) ; S-L1, S-L6, S-L7d et S-L7e restent à faire. Les statuts sont dans les bandeaux de `phases/SL2…`, `SL5…` et `SL7…`.

> Source : discovery « Leaf géo AgentB2C » (2026-10-07) + `reports/PLAN-LEAF-GEO-2026-10-08.md` (plan arbitré, revu contre le code : décisions L1-L6, écarts E1-E15, contrat `GeoIntent` v1). Détail par session : `phases/SL1…SL8-*.md` (prompt de lancement inclus dans chaque fichier).

| # | Scope (1 session) | Zone | Prérequis |
|---|---|---|---|
| S-L1 | #124 réconciliée avec le MCP mergé : `sort` → `sortBy`, cas « ancre lieu » dans le test de contrat, coordonnées de l'hôtel nommé (D-2), limites d'outils figées | feuille | MCP `main` déployé + contrat rafraîchi, D-2 |
| S-L2 | Contrat `GeoIntent` v1 (`b2c_common`, snapshot dans `contracts/`) + jeux `b2c-geo-intent` (dev/test) et `b2c-geo-preservation` (24 familles du registre) + évaluateurs | libs, contracts, evals | — |
| S-L3 | Leaf `geo_understanding_agent` : LlmAgent sans outil, `output_schema=GeoIntent`, D7, port 8103, `scripts/eval_geo_intent.py` | nouvel agent | S-L2 |
| S-L4 | Concierge : `GEO_LEAF_MODE` (off / shadow / on), leg dédié en parallèle, timeout propre, budget (D-1), mesure sur le banc de rejeu | concierge | S-L3, D-1 |
| S-L5 | Bascule : la feuille géocode en code depuis le `GeoIntent` (1 appel au modèle au lieu de 2), reprise en code, repli `fallback_geo_leaf` | feuille + concierge | S-L4, D-3, D-4 |
| S-L6 | Périmètre hybride annoncé : table de politique, partage « dedans / juste à côté » en code, libellés jusqu'à la synthèse | feuille + synthèse | S-L5, D-5 |
| S-L8 | Déploiement Railway, registre de la flotte, `shadow` puis `on` | infra | S-L5, S-L6, go de Fabien |
| S-L7a…f | Retrait des règles de langage, une MR par règle | feuille | S-L8, taux de repli mesuré |

### Timeline & parallélisation

```
Fenêtre 1        Fenêtre 2   Fenêtre 3   Fenêtre 4   Fenêtre 5   Fenêtre 6                Fenêtre 7+
S-L1 ∥ S-L2  →   S-L3   →    S-L4   →    S-L5   →    S-L6   →    S-L8 (shadow, puis on)  →  S-L7a … S-L7f
(worktrees ;                                                                                 (une règle
 merger S-L1                                                                                  par session)
 d'abord)
```

Durées : non estimées (à mesurer sur S-L1 et S-L2).

### Modèles & modes

| Session | Modèle | Mode |
|---|---|---|
| S-L2, S-L3, S-L4, S-L5 | **Opus** | piloté (contrat, prompt, invariant de budget, bascule = jugement) |
| S-L1, S-L6 | Sonnet | piloté |
| S-L7a…f | Sonnet | piloté pour la première, puis **boucle possible** (critère mécanique : le cas qui couvre la règle reste vert sans elle) |
| S-L8 | Sonnet | piloté, **jamais en boucle** (production) |

### Décisions arbitrées (2026-10-08, Fabien) — ne pas re-litiger en session

L1 leaf A2A après le triage, tours de recherche seulement · L2 comprendre d'abord, résoudre en phase 2 · L3 retrait des règles de langage une par une, chacune couverte par un cas d'éval · L4 hybride annoncé (dedans d'abord, puis « juste à côté » avec la distance) · L5 #124 d'abord · L6 budget d'outils constant, enchaînements en code. Encore ouvertes : D-1 à D-7 (plan §5) — D-1 bloque S-L4.
