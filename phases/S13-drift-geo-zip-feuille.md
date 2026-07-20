# S13 — Drift agent-usa juillet : scoping pays du géocodage ZIP US (feuille search) (∥ possible avec S12)

| | |
|---|---|
| **Mode** | Piloté — trop court pour une loop |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `git worktree add ../AgentB2C-s13 -b s13-drift-geo-zip` si S12 tourne en parallèle |
| **Zone autorisée** | feuille search (`agents/hotel_search_agent/**`) + ses tests — NE PAS toucher `agents/b2c_concierge/**` (zone S12) |
| **Prérequis** | Fixes en cours de Fabien mergés (rebase sur main fraîche) · agent-usa local à `b429125` |
| **Durée cible** | ½ journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `AUDIT-DRIFT-AGENT-USA-2026-07-20.md` · spec exécutable (agent-usa, checkout à `b429125`) :
- `tests/unit/application/test_prod_audit_fixes_2026_07_19.py` : UNIQUEMENT `test_us_market_five_digit_postcode_never_falls_through_worldwide`

Bug prod visé : un ZIP US 5 chiffres (« near 11580 ») partait en géocodage MONDE ENTIER — agent-usa force désormais `country=us` sur chaque appel géocodeur quand l'ancre postale US a parlé (`provenance=market_postcode`).

## Périmètre
**IN** : quand `select_us_postal_anchor` (geo_guards.py, porté en S4) détecte un ZIP US, l'appel Mapbox réel est SCOPÉ pays (`country=us`) — vérifier le câblage actuel `geocode_tool.py` → `mapbox_client.py`, ajouter le paramètre s'il manque, verrouiller par test.
**OUT** : tout le reste du durcissement géo d'agent-usa (homonymes, pool 5→10, POI/Search Box, geo-tier ordering, rayon strict) — couche de capacité jamais portée, décision produit hors session (voir audit) · country anchoring (jamais porté) · orchestrateur (zone S12).

## Étapes
1. **Probe de l'existant** : lire `geocode_tool.py` + `mapbox_client.py` — le résultat de `select_us_postal_anchor` influence-t-il aujourd'hui la requête Mapbox (paramètre `country` de l'API v6) ? Documenter le constat dans HANDOFF avant de coder.
2. **Câblage** (si manquant) : `mapbox_client` accepte un scope pays optionnel ; `geocode_tool` le pose à `us` quand l'ancre ZIP US a parlé. Jamais de scope inventé sans signal (pas de biais locale→pays : agent-usa vient de SUPPRIMER ce fallback chez lui). Posture inchangée : jamais d'exception, dégradation `{"ok": False, ...}`.
3. **Tests** (pattern `test_geo_guards.py`/`test_geocode_tool.py` existants, `httpx.MockTransport`) : ZIP US → la requête Mapbox porte `country=us` (assertion sur l'URL mockée, miroir de l'assertion agent-usa « every geocoder call is scoped ») ; requête sans signal pays → AUCUN paramètre `country`.

## DoD (exécutable)
```bash
pytest agents/hotel_search_agent -q     # nouveaux tests scoping verts, les 96+ existants inchangés
pytest -q && bash scripts/dayuse_guardrails.sh .
```

## Fin de session
HANDOFF (constat du probe + câblage fait/déjà présent) · commit + MR. Si ∥ S12 : **merger APRÈS S12 (rebase sur main fraîche)**.

## Prompt de lancement (à coller — déplacer dans PROMPTS-SESSIONS.md à l'occasion)
```
Lis CLAUDE.md, HANDOFF.md, AUDIT-DRIFT-AGENT-USA-2026-07-20.md, puis phases/S13-drift-geo-zip-feuille.md et exécute cette phase, dans ce périmètre exactement.
Règles : un seul scope (un seul fix : le scoping pays du ZIP US) ; la spec = le test agent-usa pointé ; commence par le probe de l'existant AVANT de coder ; fin = DoD verte + HANDOFF à jour + commit branche, jamais de merge.
```
