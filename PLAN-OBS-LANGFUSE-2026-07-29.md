# Plan OBS — exploiter Langfuse pour debugger et fiabiliser AgentB2C

Arbitré le 2026-07-29. Référence technique : **`OBS2-LANGFUSE-BRIEF.md`** (le brief porte le détail
vérifié : features, versions, pièges, sources). Ce fichier porte **le découpage en sessions, les
dépendances et le suivi**. Prompts de lancement : **`PROMPTS-OBS-LANGFUSE.md`**.

État de départ : OBS1 livré et déployé (cf. HANDOFF addendum 2026-07-28). Instance vérifiée le
2026-07-29 : `GET /api/public/health` → `{"status":"OK","version":"3.205.1"}`.

---

## Décisions actées (ne pas re-litiger en session)

| # | Décision | Raison |
|---|---|---|
| **D-OBS-1** | **Bump serveur 3.205.1 → 3.224.2 AVANT tout code**, tags épinglés sur la ligne `:3` | 3.224.2 est un backport de sécurité v3 (dont l'arrêt du logging des payloads d'API publique = invariant RGPD) + `fix(otel)` int64 qui nous concerne comme ingesteur OTLP |
| **D-OBS-2** | **Pas de migration serveur v4 maintenant** | dernière v4 publiée = `4.0.0-rc.3`, `latest` pointe encore v3, Langfuse recommande explicitement d'attendre la stable ; v3 patché jusqu'à fin janvier 2027 |
| **D-OBS-3** | **Evaluators en Python côté nous** (SDK experiments), pas de code evaluators managés | runtime managé sans dépendances tierces / sans réseau / timeout 2 s, et sur Railway seul le dispatcher `insecure-local` (TS, non sandboxé) serait possible → incompatible zéro-lock-in |
| **D-OBS-4** | **Judges LLM-as-a-judge managés**, avec une **LLM Connection stockée dans notre Langfuse** (clé chiffrée par `ENCRYPTION_KEY`) | setup UI, sampling, backfill natifs ; pas de pipeline maison à maintenir. Contrainte : le modèle juge doit supporter le tool calling |
| **D-OBS-5** | **1 trace = 1 tour, 1 session = 1 conversation** ; les feuilles A2A **rejoignent la trace du tour** | reco Langfuse ; supprime au passage la seule surface dépréciée en v4 de notre code (`langfuse.trace.*` posés par `stamp_langfuse_session`) |
| **D-OBS-6** | **Toute lecture de métriques Langfuse dans UN seul module** (`api.legacy.metrics_v1` aujourd'hui, v2 après migration) | la migration v4 devient un fichier, pas une chasse |
| **D-OBS-7** | **Pas d'alerting maison au-delà du strict minimum** | les monitors natifs arrivent avec la v4 : ne pas construire ce qui sera jeté |

## Invariants qui s'appliquent à toutes les sessions OBS

1. **Le code reste inerte sans les clés** (`LANGFUSE_PUBLIC_KEY`+`SECRET_KEY`) : aucun import
   `langfuse`, aucun réseau. La suite offline entière verrouille ce chemin — c'est non négociable.
2. **L'observabilité ne casse jamais un tour** : tout nouveau chemin est try/except + `logger.debug`,
   comme `stamp_langfuse_session`.
3. **RGPD** : le contenu de message ne va QUE dans les traces Langfuse (canal d'audit sanctionné).
   Les **scores**, leurs `comment`, les métriques et les logs `b2c_concierge.*` restent **sans
   contenu** — identifiants de règle uniquement.
4. **Budget** : ≤ 3 appels LLM/tour inchangé. Les judges tournent côté worker Langfuse, hors chemin.
5. Fin de session : gates verts (`pytest`, `ruff`, `mypy`, `dayuse_guardrails.sh`) → `HANDOFF.md`
   (bloc daté) → commit sur branche + MR. **Jamais de merge par la session.**

---

## Sessions

| # | Scope (1 session) | Projet / zone | Prérequis | Durée | Modèle / mode |
|---|---|---|---|---|---|
| **OBS0** | Bump serveur Langfuse 3.205.1 → **3.224.2** (pin `:3`), backup PG+CH, vérif santé, puis **checklist UI** (§11 du brief) : judges embarqués, endpoint MCP, recherche, monitors, `ENCRYPTION_KEY` | **Railway (projet `Langfuse`)** + doc dans AgentB2C | — | ½ j | Sonnet · piloté, **jamais loop** |
| **OBS2** | **Typage des observations** (`agent`/`tool`/`chain`/`guardrail`) → Agent Graph · `level`+`status_message` sur les dégradations · `LANGFUSE_RELEASE` · mesure TTFT | AgentB2C — `libs/b2c_common/**` + `agents/**` | OBS0 | 1 j | Sonnet · piloté puis loop possible |
| **OBS3** | **Scores déterministes** : 12 guards + `hotels_returned` + `empty_shortlist` + `llm_calls` · score configs · module de lecture métriques · 1 dashboard exporté en JSON versionné | AgentB2C — `libs/b2c_common/**` + `agents/b2c_concierge/**` + `observability/langfuse/**` | OBS2 | 1 j | Sonnet · loop possible |
| **OBS4** | **Trace distribuée A2A** : baggage côté concierge + `trace_context` côté feuilles → une trace par tour de bout en bout ; **retrait de `stamp_langfuse_session`** | AgentB2C — `libs/b2c_common/**` + `agents/**` | OBS3 | ½-1 j | **Opus** · piloté (touche l'A2A) |
| **OBS6** | **Datasets + experiments** : datasets hébergés par famille, items multi-tours (`messages`+`profile`) avec `source_trace_id`, evaluators Python, gate CI | AgentB2C — `evals/**` + `scripts/**` + `.github/**` | **OBS0 seulement** (∥ OBS2 puis OBS3) | 1,5 j | Sonnet · loop possible |
| **OBS7** | **Judges online + annotation queue** : LLM Connection, 3-5 judges observation-level à sampling bas, queue alimentée par `empty_shortlist=1` / 👎 | Langfuse UI + AgentB2C (`observability/langfuse/**`) | OBS4 (observation racine stable) | 1 j | Sonnet · piloté |
| **OBS5** | Feedback utilisateur 👍/👎 : `trace_id` du tour exposé dans le SSE, score posté par le front avec la **clé publique seule** | AgentB2C (`facade.py` + `web/`) — phase à écrire au lancement | OBS4 | ½ j | Sonnet · piloté |
| **OBS8** | Prépa v4 : **ClickHouse ≥ 25.12** (26.4 recommandé) en restant sur v3 | Railway — instance partagée, coordination Dayuse | OBS0 | ½ j + coordination | Sonnet · piloté, jamais loop |
| **OBS9** | **Migration serveur v4** dès la GA stable (avant fin janv. 2027) : `legacy` → `dual` → cutover, retrait des `langfuse.trace.*` restants, lectures métriques v1 → v2, **test `create_score` via `/ingestion`** | Railway + AgentB2C | OBS8 + v4 GA publiée | 1 j | **Opus** · piloté, GO humain par étape |
| **OBS10** | Traceparent W3C dans le champ `_meta` des appels de tools MCP → les requêtes ES dans la trace du tour | **MCP_B2C** (serveur TS) + client dans AgentB2C | OBS4 | 1 j | Sonnet · piloté |

Détail par session : `phases/OBS0…OBS7.md`. OBS5, OBS8, OBS9, OBS10 : cadrés ici, fichier de phase à
écrire au moment du lancement (dépendent d'événements externes ou d'un autre repo).

### Timeline & parallélisation

Analyse par **collision de fichiers**, pas par intuition. Trois zones ne se croisent jamais :
**A** = `libs/b2c_common/**` + `agents/**` · **B** = `evals/**` + `scripts/**` + `.github/**` ·
**C** = ops Railway / UI Langfuse. Le repo **MCP_B2C** est une quatrième zone, physiquement séparée.

```
Fenêtre 0     Fenêtre 1              Fenêtre 2       Fenêtre 3              Fenêtre 4        Plus tard
OBS0     →    OBS2  ∥  OBS6      →   OBS3  ∥ (OBS6   OBS4  ∥  OBS10    →    OBS7 ∥ OBS5  →   OBS9
(ops)         (zone A) (zone B)      (zone A) suite)  (zone A) (MCP_B2C)     (zone C) (A+web)  (ops, v4 GA)
              ↑ coordination OBS8 (ClickHouse) lancée ICI en tâche de fond humaine — OBS8 s'exécute quand la fenêtre est accordée
```

| Fenêtre | Sessions | Parallèle ? | Pourquoi |
|---|---|---|---|
| 0 | **OBS0 seul** | Non | ops prod, court, et sa checklist conditionne OBS6 + OBS7. Le `fix(otel)` int64 de 3.214.0 corrige l'ingestion OTLP : inspecter des traces AVANT le bump, c'est inspecter des données potentiellement fausses |
| 1 | **OBS2 ∥ OBS6** | **Oui — 2 worktrees** | zones A et B strictement disjointes ; OBS6 attaque l'agent par la **façade HTTP** (contrat inchangé), il n'a pas besoin du typage d'OBS2 |
| 2 | **OBS3** (∥ fin d'OBS6) | Non pour OBS3 | OBS3 touche `observability.py`, `facade.py` **et les call sites des guards** — exactement les fichiers d'OBS2. Séquentiel obligatoire. OBS6 (1,5 j) peut déborder ici sans risque |
| 3 | **OBS4 ∥ OBS10** | **Oui — repos différents** | OBS10 vit dans MCP_B2C : zéro fichier partagé, aucune worktree à créer. Il construit l'extraction serveur contre un contrat documenté, pendant qu'OBS4 pose l'injection côté client |
| 4 | **OBS7 ∥ OBS5** | **Oui — 2 worktrees** | OBS7 = UI Langfuse + `observability/langfuse/**` + `scripts/**` ; OBS5 = `facade.py` + `web/**`. Disjoints |
| ops | **OBS8** | En tâche de fond | l'upgrade ClickHouse est découplé du code (compatible v3). Le coût réel, c'est le **délai de coordination** avec les autres producers Dayuse → lancer la demande dès la fenêtre 1 |

**Ce qui n'est PAS parallélisable, et pourquoi** : OBS2/OBS3 (même trio de fichiers) · OBS4 après
OBS3 (même zone A, et OBS4 supprime du code qu'OBS2/OBS3 viennent de toucher) · OBS7 après OBS4 (les
judges observation-level exigent l'observation racine stable) · OBS9 après OBS8 **et** après la GA v4.

Ordre de merge en fenêtre parallèle : **zone A d'abord** (OBS2 avant OBS6, OBS4 avant OBS10), le
second rebase sur main fraîche avant sa MR. OBS7/OBS5 : ordre libre, aucun fichier commun.

### Contraintes pratiques des fenêtres parallèles (vérifiées dans le repo)

1. **Ports fixes** : `scripts/run_local.sh` code en dur `8100/8101/8102`. **Deux stacks locales ne
   peuvent pas tourner en même temps.** `scripts/` est la zone d'OBS6 → **OBS6 ajoute un
   `PORT_OFFSET` à `run_local.sh`** (et utilise 8110-8112) ; `smoke_e2e.py` honore déjà
   `CONCIERGE_URL`. À défaut : une seule session lance le stack à la fois, l'autre travaille offline
   et garde sa vérif live pour la fin.
2. **`.env` n'est pas dans git** → absent d'un worktree neuf. `cp .env ../AgentB2C-obs6/.env`, sinon
   la session tourne sans clés et croit que tout est inerte.
3. **`.venv` est par worktree** : rejouer le bloc setup de `CLAUDE.md` dans chaque worktree (~5 min).
   C'est le vrai coût d'entrée d'une fenêtre parallèle.
4. **Séparer les traces des deux sessions** : `LANGFUSE_TRACING_ENVIRONMENT=dev-obs2` /
   `dev-obs6` (regex `^(?!langfuse)[a-z0-9-_]+$`, ≤ 40 car.). Sans ça les deux sessions polluent la
   même vue et chacune conclut faux sur ce qu'elle observe.
5. **Un seul terminal touche `main`** : les MR partent dans l'ordre de merge annoncé, jamais en
   simultané.

---

## Suivi

Statuts : ⬜ à faire · 🟡 en cours · ✅ mergée · ⏸ bloquée (raison) · ❌ abandonnée.
**À tenir à jour par la session elle-même** (en même temps que le bloc HANDOFF daté).

| # | Session | Statut | Branche | Date | MR | Note / blocage |
|---|---|---|---|---|---|---|
| OBS0 | Bump serveur 3.224.2 + checklist UI | ✅ | `obs0-bump-serveur-langfuse` | 2026-07-30 | | Bumpé à **3.224.3** (tag `:3` avait déjà bougé, approuvé par Fabien) au lieu de 3.224.2 — diff = deps/pricing only. Backups PG+CH pris et lockés avant redeploy. Checklist §11 répondue (cf. HANDOFF) — découverte notable : Monitors semblent actifs sur v3 (contredit l'hypothèse D-OBS-7) |
| OBS2 | Typage observations + level + release + TTFT | ✅ | `obs2-typage-observations` | 2026-07-30 | | Découverte majeure : ADK 2.4.0 type déjà `agent`/`tool` nativement (Agent Graph déjà visible avant OBS2) — le typage réel posé se limite aux 3 tools inline + 5 guards concierge (`guardrail`) + `level`/`status_message` sur les dégradations existantes. Bug trouvé ET corrigé en session : `mark_level`/`mark_metadata` dégradaient `agent`→`span` via `update_current_span` (fixé en attributs OTel bruts, cf. HANDOFF). Découverte non corrigée (hors périmètre) : usage compté 2× sur les feuilles ADK (hotel_search_agent/faq_agent), `call_llm`+`generate_content` — dashboards de coût feuille surestimés dès aujourd'hui. `LANGFUSE_RELEASE` documentée (zéro code), pose Railway en attente d'un GO Fabien |
| OBS3 | Scores déterministes + dashboard | ⬜ | `obs3-scores-deterministes` | | | |
| OBS4 | Trace distribuée A2A | ⬜ | `obs4-trace-distribuee-a2a` | | | |
| OBS6 | Datasets + experiments + gate CI | 🟡 (non mergée) | `obs6-datasets-experiments` | 2026-07-30 | | 4 datasets hébergés (48+6 items), 2 runs comparés, CI non bloquant ; attend le merge d'OBS2 puis rebase — détail HANDOFF |
| OBS7 | Judges online + annotation queue | ⬜ | `obs7-judges-online` | | | |
| OBS5 | Feedback 👍/👎 | ⬜ | `obs5-user-feedback` | | | phase à écrire |
| OBS8 | ClickHouse ≥ 25.12 | ⬜ | — (ops) | | | coordination Dayuse |
| OBS9 | Migration v4 | ⏸ | — | | | **attend la GA stable** (RC au 2026-07-29) |
| OBS10 | Traceparent `_meta` MCP | ⬜ | (repo MCP_B2C) | | | |

### Résultats attendus, mesurables (à remplir à la fin de chaque session)

| Indicateur | Avant | Après | Session |
|---|---|---|---|
| Agent Graph visible sur un tour réel | non | **déjà oui, nativement (ADK 2.4.0) — découverte OBS2, pas un livrable OBS2** | OBS2 |
| Tours filtrables par `level:ERROR` | non | oui (vérifié : timeout simulé retrouvé, type non dégradé) | OBS2 |
| p95 TTFT mesuré en continu | non (smoke seulement) | mesure posée en metadata (`ttft_ms`) ; le score/p95 agrégé arrive avec OBS3 | OBS2 |
| Taux de tours à shortlist vide (prod, 7 j) | inconnu | | OBS3 |
| Fréquence de déclenchement par guard (12 séries) | inconnue | | OBS3 |
| Tours dépassant 3 appels LLM | inconnu | | OBS3 |
| 1 trace = 1 tour bout en bout (concierge + feuilles) | non (traces séparées) | | OBS4 |
| Non-régression conversationnelle mesurée en CI | non (`adk eval` seul) | oui, non bloquant (job `langfuse-experiments`) — seuil pas encore fixé | OBS6 |
| Frustration utilisateur / hors-périmètre détectés | non | | OBS7 |

### Questions ouvertes

- **Q1** — ✅ **Répondue (OBS0, 2026-07-30)** : 23 judges managés embarqués sur 3.224.3 (vérifié par
  lecture de `worker/src/constants/managed-evaluators.json` au tag déployé), dont les 3 ciblés —
  `User Distress`, `User Disagreement`, `Out-of-Scope Request` — plus `Hallucination`/`Relevance` et
  6 autres Langfuse + 12 Ragas. OBS7 débloqué sur ce point.
- **Q2** — Quel modèle juge, via quelle connexion ? OpenAI direct ou gateway OpenAI-compatible ; le
  tool calling est obligatoire (D-OBS-4). À trancher en OBS7 avec un budget tokens mensuel plafonné.
- **Q3** — ✅ **Répondue (OBS0, 2026-07-30)** : `ENCRYPTION_KEY` est posée, MAIS c'est la valeur
  placeholder documentée par Langfuse (64 zéros hex), pas une clé générée — à régénérer
  (`openssl rand -hex 32`) avant de configurer la LLM Connection d'OBS7 (rien n'est encore chiffré
  dessus, rotation sans risque aujourd'hui). Décision de rotation à prendre par Fabien.
- **Q4** — ✅ **Répondue (OBS0, 2026-07-30)** : NON — `data-retention` n'est un entitlement que du plan
  `self-hosted:enterprise` (vérifié dans `entitlements.ts` au tag déployé), absent d'`oss`/
  `self-hosted:pro`, et aucune clé de licence EE n'est posée sur `langfuse-web`. OBS9 devra donc
  budgéter le backfill historique complet (3× le volume disque ClickHouse), pas de raccourci rétention.
- **Q5** — `create_score` passe par `POST /api/public/ingestion`. La matrice v4 marque cet endpoint
  « unsupported » alors que le guide de migration dit « score writes unaffected ». **À tester avant
  OBS9** : tout OBS3 repose dessus.

**Découverte OBS0 non prévue par le plan** — l'écran Monitors (§8, raison de D-OBS-7) semble déjà
fonctionnel sur 3.224.3 : pages/formulaires/table complets, aucun gate d'entitlement (`monitor-count`
identique sur tous les plans y compris `oss`), et `MonitorRunner`/`monitor-queue` démarrés en LIVE au
boot du worker. Le brief avait conclu « v4-only » contre 3.205.1 sans vérification de code approfondie.
**À revérifier visuellement (Fabien) avant de re-décider si D-OBS-7 (pas d'alerting maison) tient
toujours** — si les Monitors marchent déjà, une partie du chantier alerting externe devient inutile.
