# Plan de développement & migration — agent-usa → AgentB2C

> **Statut : DRAFT à valider par Fabien** · 2026-07-15
> Rework de l'agent de recherche hôtelière B2C (POC vibecodé en prod) vers une architecture modulaire industrialisée : orchestrateur ADK + agents-feuilles A2A + outils MCP, données temps réel via MCP_B2C.

---

## 1. Décisions actées (2026-07-15)

| # | Décision | Choix |
|---|----------|-------|
| A1 | Repo cible | **Nouveau repo greenfield dans `AgentB2C`** — agent-usa reste intouché en prod (pattern strangler) |
| A2 | Contrat front | **Façade iso-contrat `POST /v3/chat`** (bascule invisible, canary possible) **+ endpoint streaming SSE** optionnel, adopté par le front quand prêt |
| A3 | Données | **Cible = remplacement complet** par MCP_B2C/Elasticsearch (offres datées temps réel), **via shadow-run** : dual-run mesuré avant bascule, puis décommissionnement Postgres hotels + Qdrant + JSON |
| A4 | Accès prod (audit) | **Connecteur/CLI Railway à installer** (n'existe ni en skill ni dans le registre de connecteurs — installation manuelle, voir §7) |

Les décisions encore ouvertes sont listées en §9 — **aucune ne sera prise sans ton accord**.

---

## 2. Contexte & objectifs

**Existant** : `agent-usa` — Flask, ~53 500 lignes (120 fichiers `src/`, 117 fichiers de tests), boucle OpenAI function-calling monolithique (gpt-4o-mini), 6 tools, 12 garde-fous conversationnels issus de l'audit prod 2026-06, données statiques (`structured_hotels_*.json` → Postgres + Qdrant), déployé sur Railway.

**Objectifs mesurables du rework** :

1. **Architecture** : modulaire ADK / A2A / MCP conforme aux invariants plateforme Dayuse (LiteLLM, zéro lock-in cloud, identité enfichable, RGPD).
2. **Données** : disponibilité et prix **réels et datés** via MCP_B2C (la faiblesse « CRITIQUE » déjà identifiée dans `AUDIT_MCP_ARCHITECTURE.md`).
3. **Fluidité client** : streaming SSE, réduction de la latence par tour, moins d'appels LLM séquentiels.
4. **Industrialisation** : observabilité (métriques par appel), harnais d'éval en CI, release gate, docs/runbook.

Chaque objectif est chiffré en §6 — la baseline Phase 0 sert de point de comparaison avant/après.

---

## 3. État des lieux — ce qu'on garde, remplace, jette

**On garde (actifs précieux — ce sont des specs, pas du legacy)** :
- Les **12 conversation quality guards** (geocode echo-back, budget integrity, anti-clarification-loop, amenity claim verifier, state anchoring…) : chacun corrige un échec prod vérifié. Ils sont portés tels quels en logique déterministe (§4) et verrouillés par tests.
- Le **harnais d'éval** : `evals/` (baselines, judge LLM), `run_intent_battery.py`, `run_dynamic_conversation_regression.py`, `run_release_gate.py`, tests audit 2026-06.
- La **connaissance géo** : pipeline Mapbox, `disambiguation.json`, détection aéroports, ancrage d'état US.
- Le **contrat front** `/v3/chat` et les sessions Redis (profil accumulé multi-tours).
- Les **logs prod** (`conversation_logs` Postgres) comme matière première de l'evalset.

**On remplace** :
- Boucle agent monolithique → orchestrateur ADK + sous-agents (§4).
- SDK OpenAI direct → **LiteLLM** (`DAYUSE_MODEL`).
- JSON statiques + Postgres hotels + Qdrant → **MCP_B2C** (Elasticsearch prod, lecture seule, offres datées).
- FAQ hardcodée (13 entrées) → tool `get_faq_conditions` (réponses par marché/hôtel/rate plan).

**On décommissionne à terme** (Phase 6) : scripts de seed, dumps JSON, tables hotels Postgres, Qdrant. Postgres reste pour `conversation_logs` ; Redis reste pour les sessions.

---

## 4. Architecture cible (proposition — à valider, cf. D1)

Application des règles du plugin `dayuse-agentic-platform` : A2A = agent↔agent, MCP = agent↔outil ; une feuille A2A seulement si ≥ 2 critères de mutualisation (réutilisation ≥ 2 orchestrateurs, contrat stable, cycle de vie/secrets propres) ; **ne pas sur-fragmenter** — chaque frontière A2A est un hop réseau, or la latence est LA contrainte B2C.

```
Front (web / widget / chatgpt-app futur)
  │  POST /v3/chat (iso-contrat)  +  GET /v3/chat/stream (SSE)
  ▼
Façade API (contrat, sessions Redis, i18n, canary)
  ▼
Orchestrateur conversationnel `b2c-concierge` (ADK)
  ├─ routing de tour + guards déterministes EN CODE (callbacks ADK,
  │  pas en prompt) : anti-loop, budget integrity, amenity verifier,
  │  ground-truth block, recovery acks…
  ├─ [A2A] hotel-search-agent ──── MCP_B2C: search_offers, find_hotel_by_name
  │        (+ géocoding Mapbox interne, guards géo, profil de recherche)
  ├─ [A2A] faq-agent ───────────── MCP_B2C: get_faq_conditions
  ├─ [inline] content/compare ──── MCP_B2C: get_hotel_details, compare_hotels
  │           (travaille sur _last_results injectés — pas de contrat réutilisable)
  └─ [inline] booking-link ─────── MCP_B2C: generate_booking_link
              (confirmation explicite utilisateur — R9)
Services code (pas des agents) : profil/session Redis, i18n, télémétrie
```

**Frontières V1 (D1 tranchée)** : `hotel-search-agent` et `faq-agent` en feuilles A2A déployées (décision produit — cf. tableau D1) ; `content/compare` et `booking-link` in-process « A2A-ready ».

**Amendements issus de la design review (2026-07-15, GO avec réserves — verdict complet tracé dans le brief de scaffolding)** :
- **Orchestrateur = spine code-owned** (pattern `cs_copilot`/`knowledge_router` de la fleet) : triage de tour par 1 appel LLM éco + fallback regex, table de routage en code, **budget structurel ≤ 3 appels LLM/tour typique**, UNE synthèse LLM streamée par tour, mini tool-loop borné (≤ 2 itérations) réservé à la synthèse. Un guard qui intercepte ne relance jamais une boucle complète (1 retry borné avec directive, puis correction déterministe).
- **Feuilles stateless (B3)** : le profil de session appartient exclusivement à l'orchestrateur (service code + Redis) ; les feuilles reçoivent le contexte dans le payload A2A (`DataPart` structuré) et renvoient des deltas de profil — jamais de Redis partagé entre feuille et orchestrateur. 0-1 appel LLM interne par feuille (l'extraction de paramètres est faite en amont, la rédaction en aval).
- **R9 devient le guard n°12** : `generate_booking_link` n'est appelable que si le flag de confirmation explicite est présent dans l'état du tour courant — en code, verrouillé par test, comme les 11 autres.
- **Contrat SSE/TTFT** défini dans la spec de façade : événement de progression immédiat (= le TTFT mesuré), événement hotels dès le retour de la feuille, tokens de synthèse ensuite. Prompt à préfixe stable (cache), min-instances 1 sur toute la chaîne (orchestrateur, feuilles, MCP_B2C) — à ~58 sessions/j, le scale-to-zero ferait payer un cold start par hop.
- **Un propriétaire unique par dépendance** pour timeouts/retries : la feuille possède Mapbox/MCP (retry + circuit-breaker), l'orchestrateur possède le timeout d'appel feuille (sans retry, dégradation honnête via ground-truth), les retries LLM vivent au seul niveau LiteLLM.
- **RGPD (préconditions de prod)** : résidence EU du provider modèle à vérifier derrière LiteLLM, TTL Redis + politique de rétention `conversation_logs`, colonne `is_synthetic` dès le jour 1, zéro contenu de message dans les métriques (verrouillé par test), secrets V1 (token MCP_B2C, Mapbox) en exception documentée avec échéance broker.

**Conformité invariants plateforme** :
- **Modèle** : LiteLLM uniquement (iso-modèle gpt-4o-mini au départ pour comparer à périmètre constant — cf. D3).
- **Exécution** : conteneurs OCI, cible Railway (déjà le cas), manifestes k8s/Knative générés par `deploy-anywhere`.
- **Coordination** : A2A (Agent Cards signées via `wire-a2a`) + MCP (MCP_B2C en streamable-http avec auth token).
- **Identité** : `AgentIdentityProvider` (`oidc-mtls` défaut, `dev-insecure` en local) via `dayuse_agent_common`.
- **RGPD/HITL** : flux 100 % lecture (le booking link est une génération d'URL, pas une écriture externe) → pas de HITL bloquant, mais confirmation utilisateur R9 sur le lien, **aucun contenu de message dans les métriques** (convention fleet), résidence EU Railway, logs sans PII.

**Réutilisation fleet** : `libs/dayuse_agent_common` (identity, `metrics`/`metrics_pg`, `model_switch`, `costs`) consommé comme dépendance — pas de copie. Les événements partent dans `llm_metric_events` (Postgres Railway existant) → le **dayuse-metrics-dashboard existant affiche le before/after gratuitement** (colonne `service`).

---

## 5. Phasage

Durées indicatives à affiner après Phase 0. Phase 1 est parallélisable avec Phase 0.

### Phase 0 — Audit & baseline métriques ✅ **TERMINÉE le 2026-07-15** (livrable : `AUDIT-REWORK-2026-07.md`)
| # | Tâche | Livrable |
|---|-------|----------|
| 0.1 | **Audit de code** structuré d'agent-usa (grille `engineering:tech-debt` : hotspots, duplication, complexité, couplage ; cartographie des appels LLM par tour, points de latence séquentiels, taille des prompts) | `AUDIT-REWORK-2026-07.md` chiffré |
| 0.2 | **Baseline prod** via Railway (à installer) + `conversation_logs` : latence p50/p95 par tour, tours/session, taux de recherches vides, boucles de clarification, taux d'erreur, coût/tour estimé, CPU/RAM. ⚠️ agent-usa n'instrumente pas la latence par requête — un micro-patch d'observabilité (access-log gunicorn avec durée) sera peut-être proposé : **soumis à ton accord avant tout déploiement** | Tableau baseline (§6 rempli) |
| 0.3 | **Evalset de référence** : scénarios réels extraits des logs prod (anonymisés) + reprise de `evals/baselines.json` et des batteries existantes | `evalset` v0 rejouable |
| 0.4 | **Probe MCP_B2C** (déjà branché dans ma session Cowork) : parité fonctionnelle sur un échantillon de requêtes types vs pipeline actuel | Rapport de probe |
| | **Gate** : validation par Fabien des KPIs baseline et des cibles chiffrées (D4) | GO Phase 2 |

### Phase 1 — Terminer MCP_B2C (prérequis, ~1 sem, parallélisable)
- 1.1 Tools manquants : `get_faq_conditions` (4.5) et `generate_booking_link` (4.6) — suivi existant `docs/suivi-implementation.md`, méthode `mcp-builder` + `dayuse-vibes`.
- 1.2 Dockerisation & livraison (phase 5 du suivi MCP_B2C) + déploiement accessible depuis AgentB2C.
- 1.3 Décision D2 (résolution POI) : défaut proposé = Mapbox reste côté agent, câblage de l'index `poi` ES plus tard si besoin.

### Phase 2 — Fondations AgentB2C (~2 sem)
- 2.1 **Design review avant scaffolding** : passage de l'architecture §4 par l'agent `agent-design-reviewer` du plugin, puis `/scaffold-orchestrator` + `/scaffold-agent` (+ `wire-a2a` pour les 2 feuilles).
- 2.2 Socle : LiteLLM, `dayuse_agent_common` en dépendance, conteneurs OCI, CI GitLab (lint, typecheck, `dayuse_guardrails.sh`), identité `oidc-mtls`/`dev-insecure`.
- 2.3 **Instrumentation jour 1** : `metrics_pg` → `llm_metric_events` → dashboard (le after se mesure dès le premier commit).
- 2.4 Harnais d'éval ADK (`/eval-agent`) branché sur l'evalset Phase 0 + CI.

### Phase 3 — Feuille search + intégration MCP_B2C (~2-3 sem)
- 3.1 `hotel-search-agent` : tools MCP_B2C + géocoding Mapbox + **portage des guards géo** (echo-back, state anchoring, generic place words) + timeouts/retry/circuit-breaker vers le MCP.
- 3.2 Portage du profil de session (SearchProfileBuilder → service Redis).
- 3.3 **Shadow-run (A3)** : harness dual-run — mêmes requêtes vers pipeline actuel et MCP_B2C ; rapport de parité (recouvrement top-N, pertinence jugée par le judge existant, latence, fraîcheur/réservabilité des offres). **Gate** : parité suffisante ou activation du fallback hybride (§8).

### Phase 4 — Orchestrateur conversationnel complet (~2-3 sem)
- 4.1 Orchestrateur : routing de tour, **portage systématique des 12 guards** en callbacks déterministes, i18n, gestion multi-tours.
- 4.2 FAQ, content/compare, booking-link (confirmation R9).
- 4.3 Portage des batteries : conversation regression live + release gate équivalent (`--quick` inclus) ; **la baseline qualité ne doit pas régresser**.

### Phase 5 — Façade API & migration front (~1-2 sem)
- 5.1 Façade `/v3/chat` iso-contrat (mêmes champs : `message, hotels, suggestions, session_id, active_filters…`) + endpoint SSE. Cutover **par nouvelles sessions** (les sessions Redis en cours restent sur agent-usa).
- 5.2 **Canary Railway** : % de trafic progressif, critères de rollback écrits AVANT la bascule (latence p95, taux d'erreur, score judge), comparaison A/B sur le dashboard.
- 5.3 Bascule 100 %, agent-usa gelé en standby (rollback à froid possible).

### Phase 6 — Mesure, décommissionnement, docs (~1 sem)
- 6.1 **Rapport avant/après** sur les KPIs §6 — le livrable qui matérialise l'apport du rework.
- 6.2 Décommissionnement : Qdrant, tables hotels, seeds, JSON (après période d'observation à définir).
- 6.3 Runbook, HANDOFF.md, ADRs consolidés.

**Total indicatif : ~10-12 semaines**, parallélisation possible (Ph0 ∥ Ph1 ; 3.3 ∥ 4.1).

---

## 6. Métriques — mesurer l'apport du rework

Baseline remplie en Phase 0, re-mesure identique en Phase 6. Cibles = **propositions à valider (D4)**.

| KPI | Source de mesure | Baseline | Cible proposée |
|-----|------------------|----------|----------------|
| Latence serveur p50/p95 par tour | Railway + access logs / `llm_metric_events` | Ph0 | −30 % p95 |
| Time-to-first-token perçu (SSE) | front / synthétique | N/A (pas de streaming) | < 1,5 s |
| Appels LLM séquentiels par tour | instrumentation | Ph0 (≥ 2 : classif + boucle + vérifs) | réduit à périmètre égal |
| Coût tokens / tour | `costs.py` (fleet) | Ph0 (estimé) | −20 % |
| Taux de recherches à résultat vide | `conversation_logs` | Ph0 | ↓ (dispo réelle) |
| Boucles de clarification répétées | logs + guard | Ph0 | 0 (guard porté) |
| **Fraîcheur des offres** : % d'offres affichées réellement réservables à la date | shadow-run puis prod | ~statique (aucune dispo datée) | 100 % offres datées ES |
| Qualité conversationnelle (score judge) | `evals/judge` | baseline existante | ≥ baseline (non-régression) |
| Taux d'erreur (LLM + tools) | `llm_metric_events.status` | Ph0 | ↓ |

---

## 7. Tooling — skills, plugins, connecteurs

### Déjà en place
| Outil | Usage dans ce rework |
|-------|----------------------|
| **Plugin `dayuse-agentic-platform`** (DayuseAgency) | `agent-architecture` (design §4) · `scaffold-orchestrator`/`scaffold-agent` (Ph2.1) · `wire-a2a` (Ph2/3) · `agent-identity` (Ph2.2) · `rgpd-guardrails` (Ph2/4) · `eval-agent` (Ph2.4) · `deploy-anywhere` (Ph5) · sous-agent `agent-design-reviewer` (revue avant scaffolding) |
| Skills génériques | `mcp-builder` + `dayuse-vibes` (finir MCP_B2C, Ph1) · `engineering:tech-debt` (grille d'audit Ph0) · `engineering:architecture` (un mini-ADR par décision D*) · `engineering:code-review`, `engineering:testing-strategy` (continu) |
| MCP connectés (session) | `gitlab_dayuse` (issues/MR/CI) · `dayuse-mcp-b2c` (probe Ph0.4 + shadow Ph3.3) · `context7` (docs ADK/A2A à jour) |
| Fleet (réutilisation lib) | `dayuse_agent_common` (identity, metrics, metrics_pg, model_switch, costs) · `dayuse-metrics-dashboard` (before/after) |

### À installer / vérifier
| Besoin | Détail | Quand |
|--------|--------|-------|
| **Connecteur Railway** (A4) | Pas de skill ni de connecteur registre → installer le MCP officiel Railway ou la CLI + token (je te guide au kickoff Ph0) | Ph0.2, puis Ph5 (canary) |
| **Skills Google `agents-cli`** | Le plugin délègue le scaffolding ADK générique à ces skills — présents dans ton env Claude Code, absents de cette session Cowork : le scaffolding Ph2 se fera là où ils sont installés | Ph2 |
| Clé interne agent-usa | `X-Internal-Api-Key` + URL prod pour `GET /v3/chat/logs` (complément/secours du connecteur Railway) | Ph0.2 |

### À créer (optionnel, si récurrence avérée)
- Skill `conversation-analytics` (via `skill-creator`) : requêtes types sur `conversation_logs` / `llm_metric_events` pour rejouer l'audit à chaque jalon sans repartir de zéro.

---

## 8. Risques & garde-fous

| Risque | Garde-fou |
|--------|-----------|
| **Régression de qualité conversationnelle** (les 12 guards encodent des mois de corrections prod) | Portage systématique en code + tests de régression repris, evalset Ph0, shadow-run, canary avec critères de rollback écrits |
| **Latence multi-agents** (hops A2A) | D1 : frontières A2A minimales en V1 (2 feuilles), sous-agents in-process ailleurs, SSE pour la latence perçue, budget latence suivi dès Ph2 via dashboard |
| **Parité recherche sémantique** (Qdrant vectoriel → ES keyword/function_score) | Le shadow-run Ph3.3 tranche sur données réelles ; fallback : mode hybride temporaire (Qdrant conservé pour les requêtes sémantiques) si parité insuffisante — gate explicite |
| MCP_B2C dépend d'un **ES prod partagé** (lecture seule) | Timeouts, retry, circuit-breaker côté feuille ; rate-limit déjà côté MCP ; dégradation gracieuse (message honnête, pas d'invention — guard ground-truth) |
| MCP_B2C **incomplet** (2 tools + docker manquants) | Phase 1 dédiée, en parallèle de Ph0 — bloquant pour Ph3, pas pour Ph2 |
| **Dérive de périmètre** (widget, chatgpt-app, WhatsApp…) | Hors scope V1 ; les Agent Cards A2A préparent ces réutilisations sans les implémenter (D5) |
| RGPD | Conventions fleet : aucun contenu de message dans les métriques, `error_type` sans message, résidence EU, logs sans PII |

---

## 9. Décisions ouvertes — soumises à ton approbation

| # | Décision | Proposition par défaut | Échéance |
|---|----------|------------------------|----------|
| D1 | Frontières A2A V1 | ✅ **Tranchée le 2026-07-15 (décision produit Fabien)** : `hotel-search` + `faq` en feuilles A2A ; `content/compare` + `booking-link` in-process A2A-ready. ⚠️ La design review recommandait UNE seule feuille (faq ne remplit aucun critère de mutualisation plein) — décision produit assumée : pari sur la réutilisation multi-fronts ; en contrepartie, la feuille faq applique les parades latence (0-1 LLM interne, contrat structuré, keep-alive, réseau privé) | Close |
| D2 | Résolution localisation → lat/lon | Mapbox côté agent (guards géo conservés) ; index `poi` ES plus tard | Ph1.3 |
| D3 | Modèle via LiteLLM | Iso-modèle gpt-4o-mini d'abord (comparaison à périmètre constant), essais via `DAYUSE_MODEL_ALLOWLIST` ensuite | Ph2.2 |
| D4 | Cibles chiffrées des KPIs | ✅ **Validées le 2026-07-15** (gate Ph0 passé) — cf. `AUDIT-REWORK-2026-07.md` §6 | Close |
| D5 | Sort de `chatgpt-app/` et du widget | Hors scope V1, contrats A2A prêts pour eux | Ph2 |
| D7 | Identité inter-agents V1 (`oidc-mtls` de la lib = stub, découvert en design review) | ✅ **Tranchée le 2026-07-15** : contrôle intérimaire documenté — réseau privé Railway + bearer statique vérifié côté feuille, exception avec échéance (pattern booking_qa) ; `oidc-mtls` implémenté dans `dayuse_agent_common` quand il servira toute la fleet ; `dev-insecure` jamais déployé | Close |
| D6 | Micro-patch observabilité sur agent-usa prod | ❌ **Annulée le 2026-07-15** (pas de patch prod) — latence mesurée en A/B synthétique en Ph5 + instrumentation native AgentB2C dès Ph2 | Close |

---

## 10. Prochaines étapes immédiates

1. **Toi** : valider/amender ce plan — en priorité §4 (architecture) et D1.
2. **Toi** : installer le connecteur Railway (je te guide), ou me fournir URL prod + `X-Internal-Api-Key` en attendant.
3. **Moi** : lancer Phase 0 — l'audit de code (0.1) peut démarrer immédiatement, sans accès prod.
