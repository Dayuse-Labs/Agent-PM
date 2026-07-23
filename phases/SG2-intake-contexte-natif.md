# S-G2 — Intake contexte natif : GPS, locale, domaine, devise, timezone (facade) (après S-G1)

| | |
|---|---|
| **Mode** | Piloté |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `sg2-native-context` (∥ S-G5 possible : facade vs feuille — merger S-G2 d'abord) |
| **Zone autorisée** | `agents/b2c_concierge/**` (surtout `facade.py` ; mapping vers les champs profil S-G1) + tests — NE PAS toucher la feuille |
| **Prérequis** | **S-G1 mergée** (les champs `search_anchor`/`locale`/`currency`/… existent) · Arbitrage A6-a |
| **Durée cible** | ½ journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md` (§3 axe N) · `reports/research/code-verification-memo.md` (claim 2 — la facade ne lit que `message`/`session_id`).

## Périmètre
**IN** :
1. **Probe du contrat réel AVANT de coder** : le widget vendorisé est dans ce repo — `grep -rn "native_context\|geolocation\|locale\|currency" web/vendor/static/js/chat/` pour voir EXACTEMENT ce que le front envoie (champs, nesting, types). C'est LA spec du payload ; ne rien inventer au-delà. Documenter le constat dans HANDOFF avant de coder.
2. **Facade** : lire du body (tous OPTIONNELS, absent-tolérant, iso-contrat : aucun champ requis en plus) — `native_context.geolocation {latitude, longitude, accuracy?}`, `locale`, `domain`, `currency`, `client_local_time`, `client_timezone` (les 2 derniers déjà envoyés par le front agent-usa PR #125, note README S12). Validation stricte en code (lat ∈ [-90,90], lon ∈ [-180,180], locale IETF plausible) — une valeur invalide est IGNORÉE, jamais une 500.
3. **Mapping profil** : GPS → `search_anchor {type: "gps", …}` ; locale/domain/currency/timezone → champs S-G1. `response_language` préfère `locale` de la requête quand présent (fallback actuel `guess_language` conservé).
4. **Règle no-silent-downgrade (l'invariant P0 mobile, testable)** : un tour search SANS nouveau lieu explicite conserve l'ancre GPS/adresse/zone existante ; seul un nouveau lieu explicite du user la remplace ; rien ne la remplace jamais silencieusement par un centroïde de ville. Implémentée dans le reducer S-G1 (ici : le câblage + les tests bout-en-bout facade→profil).
5. **RGPD** : coordonnées GPS = donnée personnelle — jamais dans les métriques ni les logs (le test métriques existant doit couvrir les nouveaux champs) ; TTL Redis existant suffit, le documenter.

**OUT** : usage du GPS dans Mapbox `proximity` (S-G3/S-G5) · résolution de dates avec la timezone (S-G6) · affichage devise (S-G7) · tout changement de `CONTRACT_KEYS` en sortie.

## Étapes
1. Probe widget (constat → HANDOFF).
2. Parsing + validation + mapping (tests unitaires facade).
3. Tests bout-en-bout : POST /v3/chat avec `native_context` → profil Redis porte l'ancre ; tour suivant sans lieu → ancre conservée ; tour avec nouvelle ville → ancre remplacée explicitement.
4. Test RGPD : aucun champ GPS dans `llm_metric_events` / logs.

## DoD (exécutable)
```bash
pytest agents/b2c_concierge -q
pytest -q && .venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Fin de session
HANDOFF (schéma réel du payload front constaté + mapping) · commit + MR.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md (§3),
reports/research/code-verification-memo.md (claim 2), puis phases/SG2-intake-contexte-natif.md
et exécute cette phase, dans ce périmètre exactement.
Règles : un seul scope (intake facade → profil) ; probe du widget vendorisé AVANT de coder (le payload réel = la spec) ;
tout optionnel, jamais de 500 sur un champ invalide ; GPS jamais dans les métriques ;
fin = DoD verte + HANDOFF + commit branche, jamais de merge.
```
