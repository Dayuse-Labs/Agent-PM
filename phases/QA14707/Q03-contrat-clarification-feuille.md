# Q03 — Contrat `Clarification` et émission structurée par la feuille

| | |
|---|---|
| **Phase** | 2 |
| **Modèle** | opus — conception d'un contrat partagé entre la feuille et le concierge, sur un chemin géo sensible |
| **Effort** | high |
| **Dépend de** | — |
| **Prérequis** | E2 |
| **Zone (owned_files)** | `libs/b2c_common/b2c_common/clarification.py` (neuf) · `libs/b2c_common/tests/test_clarification.py` (neuf) · `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py` · `agents/hotel_search_agent/hotel_search_agent/response_bridge.py` · `agents/hotel_search_agent/hotel_search_agent/contract.py` · `agents/hotel_search_agent/tests/**` |

## Contexte utile
- `DIAGNOSTIC.md` §1 : la question `city_needed` est produite par le code sans option. La synthèse la réécrit et invente des options (« Bruxelles », « Versailles (78) », « plusieurs communes »). Le tour suivant n'en garde qu'une paraphrase.
- Sources de la question :
  - `geocode_tool.py:595-610` (`geocode_city_needed`, gabarit `geo_resolver.city_needed_question`, `options: []`) ;
  - `geocode_tool.py:750-780` et `:910` (homonyme, `geo_resolver.py:486-525`, gabarit `_CLARIFY_MANY`).
- La feuille transmet déjà au concierge des faits structurés hors texte, par le même canal : `search_context` (HANDOFF 2026-10-06, mcp-dayuse#5). C'est le modèle à suivre.

## Notes d'implémentation
1. `clarification.py` : un modèle pydantic `Clarification`.
   - Champs : `schema_version="1"`, `kind ∈ {city_needed, homonym}`, `subject` (la mention de lieu à préciser), `options[]`.
   - Chaque option : libellé, ville, région, `country_code`, au plus 5 options.
   - `extra="forbid"`, aucune coordonnée.
2. La feuille joint cet objet à `geocode_ambiguous` et le remonte au concierge dans son DataPart, par le même canal que `search_context`.
   - Les `options` viennent **uniquement** des candidats du géocodeur retenus par le palier d'inventaire, jamais du LLM.
   - `city_needed` garde `options: []` : la question part avant tout géocodage, et c'est voulu (cas à préserver, PRESERVATION.md).
3. Le texte de la feuille ne change pas : le concierge actuel, qui ignore le nouvel objet, continue de marcher. C'est Q04 qui le consomme.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- Un test montre qu'un `geocode_city_needed` remonte une `Clarification(kind="city_needed", subject="Gare du Nord", options=[])` dans le DataPart de la feuille.
- Un test montre qu'un homonyme remonte des options qui sont exactement les candidats du géocodeur au palier d'inventaire, et aucune autre.
- Le modèle refuse un champ inconnu et ne contient aucune coordonnée (test).
- Les tests existants de la feuille passent sans modification de leurs assertions.

## Hors périmètre
Le rendu et la persistance côté concierge (Q04). Le routage (Q05). Changer le moment où `city_needed` se déclenche.
