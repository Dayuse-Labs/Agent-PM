# S09 — Façade `POST /v3/chat` iso-contrat + SSE

Branch: `s9-facade` (S08 déjà mergée → pas de worktree). Zone: façade/API + ses tests. NE PAS toucher `evals/**`.

## Contexte / décisions de contrat (zone à jugement, mode phase)
- Le contrat golden d'agent-usa est capturé **en FORME** (clés/types), pas en sémantique :
  le spine B2C n'a NI intake staged, NI market engine, NI langues es/it — reproduire le
  comportement d'agent-usa (clarification espagnole, staged workflow) est structurellement
  impossible et hors design. On mappe l'état réel du spine → les clés du contrat, avec des
  défauts honnêtes documentés là où le spine n'a pas d'équivalent.
- **Auth split** : les routes A2A (`/`, carte) gardent le bearer D7 (réseau privé, agent↔agent) ;
  les routes `/v3/*` (frontend/BFF) prennent le **minimum** demandé par la phase : une API key
  interne (`X-Internal-Api-Key`, env `CHAT_API_KEY`, `AUTH_BYPASS`). D7 reste consolidé dans
  b2c_common (invariant) — la composition (quelles routes sont ouvertes) vit dans serve.py.
- **hotels** : liste du marker `hotels` si non-vide, sinon `None` (faq/ack/dégradé → None ;
  search-avec-résultats/details/compare → liste). `ready_to_search = hotels is not None`.
- **conversation_logs** : mêmes colonnes qu'agent-usa + `is_synthetic` (header `X-Dayuse-Synthetic`).
  Persistance Postgres best-effort, no-op sans `DATABASE_URL` (posture metrics_pg S3). Testé en
  pur (row builder + détection header) ; write live Postgres = S10/S11.

## Étapes
- [ ] 1. Golden : figer le schéma de réponse (clés/types) depuis les tests API d'agent-usa → fixtures de non-régression.
- [ ] 2. `facade.py` : mapping état spine → contrat v3, prix `priceEuro` cents → `€X.XX`, cookie/session, reset, API-key interne, Runner get-or-create keyé sur session_id.
- [ ] 3. SSE `POST /v3/chat/stream` : `progress` (<300 ms) → `hotels` → tokens → `done` ; JSON `/v3/chat` inchangé.
- [ ] 4. `conversation_log.py` : row builder pur + `is_synthetic` + persister best-effort (no-op sans DATABASE_URL).
- [ ] 5. `serve.py` : composition (D7 pour A2A + lifespan, API-key interne pour /v3).
- [ ] 6. Tests `tests/api/` (+ `tests` dans testpaths) : shape, mapping pur, HTTP (ack offline + search mocké), cookie/session/reset, auth, is_synthetic, ordre SSE.
- [ ] 7. `scripts/smoke_e2e.py --contract`.
- [ ] 8. README concierge : section rétention (TTL Redis + conversation_logs).
- [ ] 9. DoD verte + HANDOFF + commit branche (jamais de merge).

## DoD
- `pytest tests/api -q` vert ; `pytest -q` (suite complète) vert ; `ruff` + `mypy` OK ; guardrails OK.
- SSE : premier event = `progress` immédiat (TTFT).
- `scripts/smoke_e2e.py --contract` PASS (services up).

## Review (fait)
- Livré : `facade.py` (v3 JSON + SSE + reset, auth API-key, Runner keyé session_id, mapping contrat),
  `conversation_log.py` (row pur + is_synthetic + persister best-effort no-op sans DATABASE_URL),
  serve.py composé (split D7 A2A / API-key /v3), `ProfileStore.delete`, `tests/api/` (32 tests),
  `pytest.ini` (+tests), `smoke_e2e.py --contract`, README (façade + rétention).
- Décisions assumées (mode « contrat = zone à jugement ») : iso-contrat en FORME pas sémantique ;
  hotels empty→None + ready_to_search=hotels is not None ; conversation_logs best-effort ;
  auth split D7/API-key ; Runner in-process InMemory (profil Redis = vraie continuité).
- DoD verte : pytest tests/api 32, pytest -q 384, ruff, mypy 32, guardrails ; live : smoke --contract PASS
  (SSE progress 2 ms), curl SSE progress-first, tour FAQ nominal live OK.
- À valider par Fabien (review = gate) : fidélité de contrat des champs staged-workflow.
- Détail complet : bloc HANDOFF daté 2026-07-20 (S9).
