# Q06 — Contrat `GeoIntent` v1.1 et preuve ADK hors ligne

| | |
|---|---|
| **Phase** | 2 |
| **Modèle** | opus — conception de contrat ; reprend S-L2 avec deux ajouts que les retours de Raphael imposent |
| **Effort** | high |
| **Dépend de** | — |
| **Prérequis** | E2 |
| **Zone (owned_files)** | `libs/b2c_common/b2c_common/geo_intent.py` (neuf) · `libs/b2c_common/tests/test_geo_intent.py` (neuf) · `contracts/geo_intent.schema.json` (neuf) · `tests/test_geo_intent_contract.py` (neuf) |

## Contexte utile
- `reports/PLAN-LEAF-GEO-2026-10-08.md` §3 (contrat `GeoIntent` v1, et sa correspondance vers `geocode_location`) · `phases/SL2-contrat-geointent-evals.md` (partie contrat).
- Décision **D-Q1** (README) : la feuille de recherche actuelle remplira cet objet comme argument de `geocode_location` (Q07).
- ADK 2.4 :
  - construit la déclaration d'un paramètre pydantic (`.venv/lib/python3.12/site-packages/google/adk/tools/_function_parameter_parse_util.py:169-178`, `:496-497`) ;
  - reconvertit les arguments par `model_validate` (`google/adk/tools/function_tool.py:173-182`) ;
  - passe la déclaration à LiteLLM (`google/adk/models/lite_llm.py`).
- Piège (mémoire `reference-adk-mandatory-tool-params`) : un paramètre sans défaut est rejeté avant l'exécution de la fonction.

## Notes d'implémentation
1. **Modèle** `GeoIntent` selon le plan §3 : `schema_version`, `places[]` (au plus 2), `city`, `country_named`, `region_named`, `relation`, `carryover`, `exclusions[]`, `ambiguity`. Énumérations fermées, `extra="forbid"`, **aucune coordonnée**, un défaut sur chaque champ.
2. **Deux ajouts** (version `"1.1"`), justifiés par `DIAGNOSTIC.md` :
   - `places[].postal_code` : le code postal tel qu'écrit (trace C : il était jeté) ;
   - une sémantique explicite de `mention` et `canonical`, aussi pour `city`. `mention` est le texte exact de l'utilisateur ; `canonical` est le nom normalisé par le LLM (« Pari » → « Paris », « paris » → « Paris »). Le code vérifiera l'ancrage de la `mention` et la réalité de `canonical` (Q07).
3. **Snapshot** `contracts/geo_intent.schema.json`, généré depuis le modèle. `tests/test_geo_intent_contract.py` vérifie qu'ils ne divergent pas.
4. **Preuve ADK hors ligne** : une `FunctionTool` dont le paramètre est un `GeoIntent`.
   - La déclaration se construit, avec l'objet imbriqué et les énumérations.
   - La conversion LiteLLM produit un schéma d'outil valide.
   - Un appel avec des arguments `dict` arrive en `GeoIntent` dans la fonction.
   - Un appel sans l'argument ou partiel n'est pas rejeté avant la fonction.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q tests/test_geo_intent_contract.py
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- `geo_intent.py` existe et respecte le plan §3, plus `postal_code` et `mention` / `canonical`. Aucun champ de coordonnée (test).
- `contracts/geo_intent.schema.json` est identique au schéma généré (test).
- Les 4 propriétés ADK du point 4 sont prouvées par des tests hors ligne. Si l'une échoue, le rapport s'arrête en `blocked` et décrit l'échec : D-Q1 serait à revoir.

## Hors périmètre
Brancher le contrat dans la feuille (Q07). Les jeux d'évals de S-L2 : le jeu bout en bout de ce plan est Q01. `contracts/mcp_b2c_tools.json` : seul `scripts/refresh_mcp_contract.py`, lancé par un humain, y écrit.
