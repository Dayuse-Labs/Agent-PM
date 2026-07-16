# S05 — Profil de session + guards profil (orchestrateur) (∥ possible avec S04)

| | |
|---|---|
| **Mode** | **LOOP ENGINEERING recommandé** — ou piloté |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `git worktree add ../AgentB2C-s5 -b s5-profil-session` si S04 tourne en parallèle |
| **Zone autorisée** | orchestrateur (`agents/b2c_concierge/**` : service profil, mapping DataPart) + ses tests — NE PAS toucher `agents/hotel_search_agent/**` (zone S04) |
| **Prérequis** | S3 mergée |
| **Durée cible** | 1-2 journées |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · spec exécutable (agent-usa) : `test_audit_fixes_2026_06.py` (sections budget integrity, timeslot sanitization) ; source au besoin : `search_profile.py` (UNIQUEMENT les fonctions pointées par les tests)

## Périmètre
**IN** : service profil Redis côté orchestrateur (TTL documenté), construction/consommation `DataPart` `{query_params, profile_in}` / `{profile_delta}`, guards profil.
**OUT** : la feuille search (zone S04), synthèse (S06).

## Étapes (= items de boucle)
1. Service profil : Redis sync/async selon le squelette, TTL + clé par session, schéma typé (ville, état ancré, budget+source, timeslot start/end, amenities, langue).
2. Mapping DataPart : l'orchestrateur envoie le contexte, applique les deltas retournés. Test « feuille stateless » : **aucun import redis dans agents/*_agent** (assertion statique).
3. Guard **budget integrity** : réponse nombre nu (« 180 ») = `budget_request_source=explicit`, jamais auto-élargi ; auto-widen (défauts seulement) → disclosure obligatoire injectée.
4. Guard **timeslot sanitization** : « 15:00- » salvagé en borne, jamais persisté corrompu ; borne end-only non inversée par re-extraction.
5. Ancres état/pays côté profil (complément S04) + effacement sur changement de ville explicite.

## Règles de loop
Identiques à S04 (tests = spec intouchable, 2 rouges = STOP, pas de push).

## DoD (exécutable)
```bash
pytest agents/b2c_concierge -q          # tests profil portés verts
grep -rn "redis" agents/hotel_search_agent agents/faq_agent && exit 1 || true
pytest -q && bash scripts/dayuse_guardrails.sh .
```

## Fin de session
HANDOFF · commit + MR. **Merger APRÈS S04 (rebase sur main fraîche).**
