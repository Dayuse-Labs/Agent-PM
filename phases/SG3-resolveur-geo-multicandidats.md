# S-G3 — Résolveur géo multi-candidats, inventory-aware (feuille search) (∥ possible avec S-G1, S-G4)

| | |
|---|---|
| **Mode** | Piloté — design du ranker + probes live = jugement |
| **Modèle** | **Opus** (`claude-opus-4-8`) — décisions de policy (poids, seuil de marge, clarify-once) |
| **Branche/worktree** | `git worktree add ../AgentB2C-sg3 -b sg3-geo-resolver` si ∥ S-G1 |
| **Zone autorisée** | `agents/hotel_search_agent/**` + `scripts/build_inventory_snapshot.py` (neuf) + fichier data snapshot — NE PAS toucher `agents/b2c_concierge/**` |
| **Prérequis** | Token Mapbox dans `.env` · Arbitrage : **A1-a** (snapshot statique, provider swappable), **A2-b** (Search Box tranché par le probe), **A8-a** (pas de reranker hôtel — instrumentation seulement) |
| **Durée cible** | 1,5–2 journées |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` (§2 axe G) · `reports/research/geo-disambiguation-memo.md` (EN ENTIER — params v6, ranking Pelias/Airbnb, policy clarify-once, caveats §E) · `reports/research/code-verification-memo.md` (claim 1, 7, 8 + guards existants).

## Périmètre
**IN** :
1. **PROBE LIVE d'abord (≤30 min, AVANT tout code)** — curl Mapbox v6 `/forward` avec le token du repo sur les cas réels de l'audit : `Milano`, `Lisboa` (avec/sans `language=pt`), `La Défense`, `Orange County`, `Victoria`, `Köln`, `Chester` (⚠️ croiser le résultat Chester avec S-G4 — timeout même isolé). Vérifier : nombre de candidats à `limit=10`, `feature_type` réel des zones/POI, effet de `language` et `proximity`. **Tranche A2** : Search Box `/forward` testé UNIQUEMENT si v6 échoue sur les zones/POI. Diagnostics structurels seuls dans HANDOFF (status, feature_count, types) — jamais de token ni d'URL complète.
2. **`mapbox_client.py`** : `limit` paramétrable (défaut 10), `language`, `proximity` optionnels ; retourne la **liste** de candidats parsés (plus jamais `features[0]` seul) avec `feature_type`, `place_formatted`, `context` (ISO pays/région), `bbox`, lat/lon.
3. **`geo_resolver.py` (neuf, 100 % déterministe — AUCUN appel LLM)** : re-rank des candidats — hint pays/état explicite = **filtre dur** ; densité d'inventaire = quasi-dur (candidat 0-inventaire démoté sous tout candidat avec inventaire) ; prior locale/domaine = boost borné ; proximité GPS = boost borné **par bande de prominence** (règle Pelias : ne surclasse jamais une destination explicite lointaine) ; position Mapbox + prior de type (`place` > `locality`/`neighborhood` > `district` > `region`). Poids en constantes nommées, provider inventaire **injectable** (interface : `count_hotels(bbox|city_key) -> int`).
4. **Snapshot inventaire** : `scripts/build_inventory_snapshot.py` génère `agents/hotel_search_agent/hotel_search_agent/data/inventory_snapshot.json` (`{city_key/bbox: count}`) depuis les exports `structured_hotels_*.json` (même source que la fixture eval, 8 701 hôtels/29 marchés — provenance + date dans le fichier). Refresh manuel documenté. ⚠️ `baseline/` reste interdit.
5. **`geocode_tool.py`** : intègre le resolver ; **`geocode_echo_matches` conservé** en sanity-check final sur le candidat CHOISI ; tous les guards existants (ZIP US, generic-location, state anchoring) inchangés et re-verts.
6. **Policy de décision** : marge top-1 vs top-2 ≥ seuil → sélection silencieuse ; sinon UNE question de clarification **construite en template** depuis les `place_formatted` (2–3 options max, différenciées par pays) — zéro LLM supplémentaire, jamais de boucle (doctrine 1-retry existante).
7. **Cartes vérifiables (A8-a)** : `normalize_hotel` conserve `latitude`/`longitude` (si le MCP les renvoie — probe), `distance_km` (calcul haversine en code depuis l'ancre résolue si le MCP ne la donne pas) et `distance_origin`.

**OUT** : reranker de la shortlist hôtels (A8 — instrumentation seulement) · consommation de l'ancre GPS du profil dans les args (S-G5 — ici le client ACCEPTE `proximity`, le câblage profil viendra) · pagination (S-G5) · Search Box en production si le probe dit que v6 suffit.

## Étapes
1. Probe live → constat HANDOFF → décision A2 actée.
2. `mapbox_client` multi-candidats (tests `httpx.MockTransport`, assertions sur les params d'URL — pattern S13).
3. Snapshot + script (test : le fichier se régénère, format stable).
4. `geo_resolver` + tests table-driven : chaque cas d'échec de l'audit (Milano, Lisboa-pt, Victoria-BC, Lisbon-AR démoté par inventaire 0, GPS-ne-surclasse-pas-NYC-depuis-Paris) = un test nommé.
5. Intégration `geocode_tool` + clarify-once + cartes.
6. Vérif LIVE (3 services, .env réel) sur 5 cas de l'audit minimum — résultats structurels dans HANDOFF.

## DoD (exécutable)
```bash
pytest agents/hotel_search_agent -q     # +~35 tests, les ~180 existants inchangés (guards re-verts)
pytest -q && .venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Fin de session
HANDOFF (constats probe + poids retenus + cas live vérifiés + décision A2) · commit + MR. Si ∥ S-G1 : merger après S-G1 (rebase).

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§2),
reports/research/geo-disambiguation-memo.md (en entier), reports/research/code-verification-memo.md (claims 1/7/8),
puis phases/SG3-resolveur-geo-multicandidats.md et exécute cette phase, dans ce périmètre exactement.
Règles : PROBE LIVE Mapbox avant tout code (documenter, trancher Search Box) ; le ranker est 100 % déterministe,
zéro appel LLM ; tous les guards géo existants restent verts ; chaque cas d'échec de l'audit devient un test nommé ;
fin = DoD verte + vérif live + HANDOFF + commit branche, jamais de merge.
```
