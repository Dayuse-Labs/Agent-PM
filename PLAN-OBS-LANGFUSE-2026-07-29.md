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
| **OBS6** | **Datasets + experiments** : datasets hébergés par famille, items multi-tours (`messages`+`profile`) avec `source_trace_id`, evaluators Python, gate CI | AgentB2C — `evals/**` + `scripts/**` + `.github/**` | OBS3 (∥ OBS4) | 1,5 j | Sonnet · loop possible |
| **OBS7** | **Judges online + annotation queue** : LLM Connection, 3-5 judges observation-level à sampling bas, queue alimentée par `empty_shortlist=1` / 👎 | Langfuse UI + AgentB2C (`observability/langfuse/**`) | OBS4 (observation racine stable) | 1 j | Sonnet · piloté |
| **OBS5** | Feedback utilisateur 👍/👎 : `trace_id` du tour exposé dans le SSE, score posté par le front avec la **clé publique seule** | AgentB2C (`facade.py` + `web/`) — phase à écrire au lancement | OBS4 | ½ j | Sonnet · piloté |
| **OBS8** | Prépa v4 : **ClickHouse ≥ 25.12** (26.4 recommandé) en restant sur v3 | Railway — instance partagée, coordination Dayuse | OBS0 | ½ j + coordination | Sonnet · piloté, jamais loop |
| **OBS9** | **Migration serveur v4** dès la GA stable (avant fin janv. 2027) : `legacy` → `dual` → cutover, retrait des `langfuse.trace.*` restants, lectures métriques v1 → v2, **test `create_score` via `/ingestion`** | Railway + AgentB2C | OBS8 + v4 GA publiée | 1 j | **Opus** · piloté, GO humain par étape |
| **OBS10** | Traceparent W3C dans le champ `_meta` des appels de tools MCP → les requêtes ES dans la trace du tour | **MCP_B2C** (serveur TS) + client dans AgentB2C | OBS4 | 1 j | Sonnet · piloté |

Détail par session : `phases/OBS0…OBS7.md`. OBS5, OBS8, OBS9, OBS10 : cadrés ici, fichier de phase à
écrire au moment du lancement (dépendent d'événements externes ou d'un autre repo).

### Timeline & parallélisation

```
Fenêtre 0        Fenêtre 1     Fenêtre 2     Fenêtre 3 (2 worktrees)   Fenêtre 4      Plus tard
OBS0        →    OBS2      →   OBS3      →   OBS4  ∥  OBS6         →   OBS7 → OBS5 →  OBS8 → OBS9 → OBS10
(ops)            (Sonnet)      (Sonnet)      (Opus)   (Sonnet)         (Sonnet)       (ops + v4 GA)
                                             merge OBS4 d'abord
```

| Fenêtre | Sessions | Parallèle ? | Condition d'entrée |
|---|---|---|---|
| 0 | OBS0 | Non — ops prod | backup PG + ClickHouse fait |
| 1 | OBS2 | Non — touche `observability.py` | serveur en 3.224.2, checklist UI remplie |
| 2 | OBS3 | Non — touche `observability.py` + `facade.py` | OBS2 mergée |
| 3 | **OBS4 ∥ OBS6** | **Oui — 2 worktrees**, zones disjointes (`agents/`+`libs/` vs `evals/`+`scripts/`+`.github/`) | OBS3 mergée |
| 4 | OBS7 puis OBS5 | Non | OBS4 mergée (observation racine stable pour les judges) |

Ordre de merge en fenêtre parallèle : **OBS4 avant OBS6**, OBS6 rebase sur main fraîche avant la MR.

---

## Suivi

Statuts : ⬜ à faire · 🟡 en cours · ✅ mergée · ⏸ bloquée (raison) · ❌ abandonnée.
**À tenir à jour par la session elle-même** (en même temps que le bloc HANDOFF daté).

| # | Session | Statut | Branche | Date | MR | Note / blocage |
|---|---|---|---|---|---|---|
| OBS0 | Bump serveur 3.224.2 + checklist UI | ⬜ | `obs0-bump-serveur-langfuse` | | | |
| OBS2 | Typage observations + level + release + TTFT | ⬜ | `obs2-typage-observations` | | | |
| OBS3 | Scores déterministes + dashboard | ⬜ | `obs3-scores-deterministes` | | | |
| OBS4 | Trace distribuée A2A | ⬜ | `obs4-trace-distribuee-a2a` | | | |
| OBS6 | Datasets + experiments + gate CI | ⬜ | `obs6-datasets-experiments` | | | |
| OBS7 | Judges online + annotation queue | ⬜ | `obs7-judges-online` | | | |
| OBS5 | Feedback 👍/👎 | ⬜ | `obs5-user-feedback` | | | phase à écrire |
| OBS8 | ClickHouse ≥ 25.12 | ⬜ | — (ops) | | | coordination Dayuse |
| OBS9 | Migration v4 | ⏸ | — | | | **attend la GA stable** (RC au 2026-07-29) |
| OBS10 | Traceparent `_meta` MCP | ⬜ | (repo MCP_B2C) | | | |

### Résultats attendus, mesurables (à remplir à la fin de chaque session)

| Indicateur | Avant | Après | Session |
|---|---|---|---|
| Agent Graph visible sur un tour réel | non | | OBS2 |
| Tours filtrables par `level:ERROR` | non | | OBS2 |
| p95 TTFT mesuré en continu | non (smoke seulement) | | OBS2 |
| Taux de tours à shortlist vide (prod, 7 j) | inconnu | | OBS3 |
| Fréquence de déclenchement par guard (12 séries) | inconnue | | OBS3 |
| Tours dépassant 3 appels LLM | inconnu | | OBS3 |
| 1 trace = 1 tour bout en bout (concierge + feuilles) | non (traces séparées) | | OBS4 |
| Non-régression conversationnelle mesurée en CI | non (`adk eval` seul) | | OBS6 |
| Frustration utilisateur / hors-périmètre détectés | non | | OBS7 |

### Questions ouvertes

- **Q1** — Quels judges managés sont réellement embarqués dans le build 3.224.2 ? (checklist OBS0 ;
  conditionne OBS7)
- **Q2** — Quel modèle juge, via quelle connexion ? OpenAI direct ou gateway OpenAI-compatible ; le
  tool calling est obligatoire (D-OBS-4). À trancher en OBS7 avec un budget tokens mensuel plafonné.
- **Q3** — `ENCRYPTION_KEY` est-elle posée sur l'instance ? Sans elle, pas de LLM Connection
  stockable (checklist OBS0, bloquant pour OBS7).
- **Q4** — Politique de rétention globale sur le projet Langfuse ? Si oui, OBS9 peut **sauter le
  backfill historique** et sa contrainte de 3× le disque ClickHouse.
- **Q5** — `create_score` passe par `POST /api/public/ingestion`. La matrice v4 marque cet endpoint
  « unsupported » alors que le guide de migration dit « score writes unaffected ». **À tester avant
  OBS9** : tout OBS3 repose dessus.
