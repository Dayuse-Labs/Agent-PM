# Audit rework agent-usa — DRAFT Phase 0 (0.1 + 0.2 + 0.4)

> 2026-07-15 · Statut : **v4 — Phase 0 terminée** (audit code, probe MCP_B2C, baseline prod nettoyée du trafic QA, evalset v0). D6 annulé (décision Fabien 2026-07-15) : la latence sera mesurée en **A/B synthétique à la Ph5** (mêmes scénarios contre les deux stacks) + instrumentation native d'AgentB2C dès la Ph2.
> Réfs : `AgentB2C/PLAN-REWORK-AGENT-USA.md` (phasage), audits internes existants (`AUDIT_MCP_ARCHITECTURE.md`, `AUDIT-SEARCH-FOR-MERGE.md`). Données : `AgentB2C/baseline/` (conversation_logs.csv 26,5k lignes / 82 Mo, baseline-summary.json).

---

## 1. Résumé exécutif

1. **Aucun streaming, tout est séquentiel** : le TTFB perçu = latence totale du tour. Un tour « recherche » enchaîne de ~3 à **20+ appels LLM** (tous sur gpt-4o-mini, y compris le routage) avant le premier octet de réponse.
2. **4 fichiers concentrent 41 % des 53 581 lignes** de `src/` ; `SearchTool.execute` fait à elle seule **3 859 lignes**. La Clean Architecture déclarée est contournée (7 fichiers application→infrastructure, double système de ports, un cycle d'imports).
3. **Les 11 guards conversationnels** (et non 12 — CLAUDE.md à resynchroniser) sont tous couverts par des tests → **spec exécutable du portage** vers les callbacks ADK. Et ils marchent : 0,4 % de sessions avec question répétée en prod.
4. **Baseline prod nettoyée** : 49 % des sessions loggées étaient du trafic QA synthétique (`intl-`, `qa-`, `claude-`…) — sur les **1 508 vraies sessions** (~58/j) : **34,6 % ne voient jamais un hôtel**, **68,6 % passent par ≥1 recherche vide** (récupérée dans 68,5 % des cas). Le gisement de valeur n°1 du rework (dispo réelle + géo) est encore plus gros qu'estimé.
5. **MCP_B2C est fonctionnel et apporte la vraie valeur** : offres datées réelles avec cutoff, 122 hôtels à NYC J+1. Probe réalisé sur l'**ES de staging** → les flags data (P1 notes, P4 couverture) sont à revalider sur prod ; les flags design (P2 géocoding, P3 centimes EUR, P5 bestBy, P6 erreurs structurées) restent valables. Exigence : shadow-run sur données iso-prod.

## 2. Performance & fluidité (chaîne d'un tour `POST /v3/chat`)

### Appels LLM par tour (tous gpt-4o-mini, aucun modèle léger dédié au routage)

| Tour | Min | Max pathologique |
|---|---|---|
| Social ack | 0 (templaté) | 0 |
| Follow-up | 2 | ~6 |
| Recherche | ~3 (+1 embed, +1 pitch) | **20+** |

Le max se construit ainsi : langue (1) + intake (`_classify_location_turn` + `_extract_with_llm`, 2) + router (1) + boucle agent jusqu'à 5 itérations avec retry par itération et appel final forcé (~11) + pitch et embed par recherche + réécriture langue (2) + **guards `_enforce_*` qui relancent une boucle agent complète** (`chat_workflow.py:2374/2506`).

### Points de latence majeurs (fichier:ligne)

1. **Pitch LLM redondant dans `search_hotels`** (`search_tool.py:8053`) : chaque recherche paie un appel LLM séquentiel, puis la boucle en fait un autre pour rédiger sur les mêmes hôtels. ~1-3 s/recherche. Fusionnable.
2. **Zéro streaming** (`chat.py:1142`, `OpenAIAdapter.stream()` existe mais jamais utilisé) : 4-8 allers-retours OpenAI séquentiels avant le moindre octet.
3. **Retries imbriqués** : adaptateur ×3 (`openai_adapter.py:457`) × orchestrateur +1 (`orchestrator.py:758`), timeout OpenAI 60 s (`openai_adapter.py:110`) → latence de queue catastrophique (~6 tentatives × 60 s pire cas).
4. **Prompt géant sans cache** : system prompt ~6 500 tokens (`orchestrator.py:146-610`) reconstruit et renvoyé à chaque itération, + ground-truth block (5 hôtels, amenities non plafonnées) + résultats tool ré-injectés (7 000 chars/appel). Pas de préfixe stable pour le prompt caching.
5. **2 appels LLM d'intake fusionnables** (`intake_stage.py:1252/1314`).
6. **Chemin critique pollué** : 3 INSERT Postgres analytics awaited avant le `jsonify` (`chat.py:1064/1099/1119`) ; geocode Mapbox et embedding séquentiels alors qu'indépendants ; tool-calls exécutés en boucle `for` sans `gather` (`orchestrator.py:832`).

Timeouts : Mapbox 1,5-3,5 s sans retry, cache géo en mémoire par worker (pas partagé Redis). Historique conversation tronqué à 10 messages.

## 3. Dette & structure

- **Répartition** : application 72,7 % (38 963 l.), infrastructure 13,3 %, api 7,9 %, domain 6,1 % — le « domaine pur » est marginal, la logique vit dans application/.
- **Hotspots** : `search_tool.py` 8 567 l. (~12 responsabilités), `search_profile.py` 6 626 l. (NLU regex maison, `apply_request_data` 2 001 l.), `orchestrator.py` 4 037 l., `chat_workflow.py` 2 973 l. 40 fonctions > 100 lignes, 12 > 200.
- **Frontières** : 7 fichiers application→infrastructure en direct ; ports du domaine doublés par des Protocols locaux ; cycle chat_workflow → orchestrator → search_tool ⇄ search_profile ; `src/api` importe `scripts/`.
- **Config éparpillée** : 22 lectures d'env hors `config.py` (8 fichiers).
- **Hygiène repo** : 451 MB de résultats d'éval commités, 124 MB de dumps dupliqués, pptx/zip à la racine, 39 scripts dont ~20 orphelins, `chatgpt-app/` (second serveur qui importe les internes de src — à remplacer par MCP_B2C, cf. plan D5).
- **Duplication** : `_currency_symbol` ×3, `_slugify` ×3, `_parse_json_payload` ×3, `_normalize_clock_time` ×3. Préoccupation « langue » répartie sur 8 fichiers, prompts construits dans 5.
- **Mort/désync doc** : `IntentDetector` documenté mais disparu ; `clarification_tool` et `DestinationTool.complete` non câblés ; 7 tools câblés (pas 6).

## 4. Tests & guards

Ratio tests/src 0,64 (34 070 l., 1 668 tests). Faiblesses : infrastructure 0,27, 1 seul fichier d'intégration, `geo_reference.py` sans test. **Guards : 11 documentés, 11 couverts** (~150 tests d'audit) = la spec de non-régression du portage (plan Ph4.1).

## 5. Probe MCP_B2C (0.4) — verdict et flags

**Fonctionne** : `search_offers` (offres datées, cutoff dynamique, pagination, 122 hôtels NYC J+1), `get_hotel_details`, `compare_hotels` (bestBy, distance), désambiguïsation `find_hotel_by_name`.

⚠️ **Probe réalisé contre l'Elasticsearch de STAGING** (précision Fabien, 2026-07-15). Les constats de *données* (P1, P4) sont des artefacts probables du staging, à revalider sur prod ; les constats de *design* (P2, P3, P5, P6) restent valables quel que soit l'environnement. **Exigence Ph3.3 : le shadow-run et toute mesure de parité doivent tourner contre l'ES de prod (lecture seule) ou un snapshot iso-prod** — données ET latence du staging ne sont pas représentatives.

| # | Constat | Impact rework | Action proposée |
|---|---------|---------------|-----------------|
| P1 | Notes/avis à 0 (US) ou quasi vides (Paris : 2-5 avis) — **artefact du staging ES** (probe hors prod) | Si la prod est dense, non-sujet ; sinon régression vs JSON enrichis du POC | Revalider P1 sur l'ES prod au kickoff Ph3 ; si la prod est aussi pauvre → source d'enrichissement notes côté feuille search |
| P2 | `search_offers` : `location` texte documenté mais absent du schéma (lat/lon requis) | Confirme D2 : géocoding côté agent | Corriger la description du tool |
| P3 | `priceEuro` en centimes EUR, devise hôtel USD | Affichage devise locale à gérer côté agent | Convertisseur d'affichage côté feuille search + décision UX |
| P4 | « Kimpton South Beach » absent de l'ES actif/bookable — **probablement le staging** | Couverture inventaire à confirmer sur prod | Métrique de recouvrement dans le shadow-run Ph3.3, sur ES prod |
| P5 | `bestBy` désigne bestRated/mostReviewed avec données à 0 | Réponses trompeuses possibles | Omettre les axes sans données |
| P6 | Erreur d'ambiguïté : candidats en texte, pas de structure visible | L'agent re-demande au lieu d'enchaîner | Vérifier/enrichir `structuredContent` |

## 6. Baseline prod — vraies sessions uniquement (2026-06-15 → 2026-07-12)

⚠️ **Découverte : 49 % du contenu de `conversation_logs` est synthétique** — 1 471 sessions sur 2 979 portent des ids préfixés (`intl-` 889, `qa-` 222, `claude-` 53, `prodlike-` 28, `codex-` 9…) : les batteries de QA tournent contre la prod et polluent la table. Tous les chiffres ci-dessous sont calculés sur les **1 508 sessions réelles** (ids hex 32). Recos : (1) exclure ces préfixes de toute analytics sur cette table ; (2) dans le rework, taguer le trafic synthétique à l'écriture (colonne `is_synthetic` via header interne) ; (3) idéalement, pointer les batteries sur staging.
🔎 **À vérifier (Fabien)** : les vraies sessions s'arrêtent au **12/07** alors que le trafic QA continue jusqu'au 15/07 — vrai creux de trafic, ou changement de format des ids de session côté front ?

Source : 4 291 tours / 1 508 sessions réelles sur 26 j. Résumé machine : `baseline/baseline-summary.json` (recalculé, trafic QA exclu).

### Volume & engagement
| Métrique | Valeur |
|---|---|
| Sessions/jour · tours/jour (réels) | ~58 · ~165 (pic 256 tours le 07/07) |
| Tours par session | méd. **2** · moy. 2,85 · p90 6 · max 24 |
| Sessions à 1 seul tour | 32,2 % |
| Langues | EN 64,2 % · FR 18,9 % · IT 7,2 % · DE 4,1 % · ES 2,4 % · NL 2,0 % |
| Top villes | Paris (270+46*), London (157), New York (86), Singapore (79), Los Angeles (47), Milano (41) — *« paris » vs « Paris » : normalisation de la ville défaillante dans `active_filters` |

### Efficacité de la recherche (le gisement du rework)
| Métrique | Valeur | Cible proposée (D4) |
|---|---|---|
| Sessions qui ne voient **jamais** un hôtel | **34,6 %** | **< 20 %** |
| Sessions passant par ≥1 recherche vide | **68,6 %** | ↓↓ (dispo réelle + géo) |
| Récupération après recherche vide | 68,5 % | > 80 % |
| Tours affichant des hôtels | 41,2 % (shortlist moy. 4,2) | ↑ |
| Sessions avec question répétée (boucle) | 0,5 % | 0 (guard porté) |
| Tours avec message d'erreur visible | 0,3 % | ≤ 0,3 % |
| Tours avec lien de booking détecté* | 0,5 %* | à instrumenter proprement |

*Proxy texte (URL dans le message) — le lien part probablement via les cartes/suggestions : à instrumenter dans le rework (event dédié).

### Comportement
Filtres remplis : timeslot 66,4 % des tours, budget 61,6 %, hôtel nommé 3,4 %. Réponses assistant : méd. 390 caractères (p90 838). Délai inter-tours méd. 33,4 s (p90 120 s) — inclut la réflexion utilisateur, **ne mesure pas la latence serveur**.

### Evalset v0 (0.3 — fait)
`AgentB2C/evalset/evalset-v0.json` : **32 scénarios anonymisés** (emails/téléphones masqués) extraits des vraies sessions, répartis sur 8 familles avec comportement attendu par famille — named_hotel (81 sessions dispo), compare (22), empty_recovered (708), empty_dead (326), budget_search (851), timeslot_search (986), multi_turn_long (213), simple_search (382). Langues sur-échantillonnées hors EN (fr 8, it 7, de 7, es 7, en 3) — les batteries EN existantes d'agent-usa complètent. À faire en Ph2.4 : convertir au format ADK evalset + brancher le judge existant.

### Ce que la baseline ne couvre PAS encore
- **Latence serveur par tour** : **D6 annulé** (décision Fabien — pas de patch prod). Stratégie de remplacement : le différentiel avant/après sera mesuré en **A/B synthétique en Ph5** (le même jeu de scénarios rejoué contre agent-usa et AgentB2C, mêmes conditions, p50/p95 comparés) ; AgentB2C est de toute façon instrumenté par requête dès la Ph2 (`metrics_pg`). Pas de baseline historique absolue — acceptable, c'est la comparaison qui prouve l'apport.
- **Coût tokens/tour** : non loggé — estimation via audit statique (~6,5k tokens system × itérations), instrumentation propre dès Ph2 (metrics_pg).

⚠️ **RGPD** : `baseline/` contient des messages utilisateurs bruts. À exclure du versioning (`.gitignore` dès le `git init` d'AgentB2C) ; l'evalset est anonymisé (scrub emails/téléphones) mais à relire avant tout commit.

## 7. Quick wins candidats sur agent-usa (chacun soumis à GO explicite)

1. 3 INSERTs analytics → fire-and-forget (`chat.py`).
2. `LLM_PITCH_ENABLED=false` ou fusion pitch/rédaction (~1-3 s/recherche).
3. Timeout OpenAI 60 s → 15-20 s + dédoublonnage retries.
4. `asyncio.gather` geocode+embed.
À séquencer consciemment : mesurer la baseline latence AVANT tout patch, sinon on se prive du différentiel démontrable.

## 8. Prochaines étapes Phase 0

1. ~~D6~~ **annulé** — latence mesurée en A/B synthétique à la Ph5 (`entrypoint.sh` restauré, aucun changement à déployer).
2. **Evalset v0 livré** — conversion au format ADK + branchement du judge en Ph2.4.
3. Vérifier l'arrêt du trafic réel au 12/07 (creux réel vs changement d'ids de session).
4. **Gate de fin de Phase 0** : valider les cibles D4 (§6) → GO Phase 1 (finir MCP_B2C) et Phase 2 (fondations AgentB2C, design review puis scaffolding côté Claude Code).
