# Q07 — La feuille extrait le lieu dans un `GeoIntent`

| | |
|---|---|
| **Phase** | 3 |
| **Modèle** | opus — change l'interface de l'outil central de la feuille et son prompt ; risque de régression géo |
| **Effort** | xhigh |
| **Dépend de** | Q06 |
| **Prérequis** | E2 |
| **Zone (owned_files)** | `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py` · `agents/hotel_search_agent/hotel_search_agent/agent.py` (prompt et câblage) · `agents/hotel_search_agent/hotel_search_agent/response_bridge.py` · `agents/hotel_search_agent/tests/**` · `tests/test_mcp_contract.py` (si la chaîne before-tool l'exige) |

## Contexte utile
- `DIAGNOSTIC.md` §1, retours 2A, 2B et 3. Traces de la feuille :
  - A : `geocode_location(city="", zone="Gare du Nord", raw_user_message="Gare du nord Paris")` ;
  - B : `zone="Boulevard de la République Versailles", city=""` ;
  - C : `zone="2 boulevard Poissonnière", city=""` (code postal jeté).
- Prompt de la feuille, `hotel_search_agent/agent.py:162-202`. Il contient l'exception « lieu nommé d'après une ville où il n'est pas » (`:173-183`) et « laisse `city` vide si tu ne sais pas » (`:189-190`).
- Signature et docstring de `geocode_location` : `geocode_tool.py` vers `:400-430`. `raw_user_message` est rempli par le LLM, aucun code ne l'injecte.
- Correspondance cible (plan S-L §3) :
  - `places[0].kind = city` → `city` ;
  - un autre `kind`, sauf `hotel` → `zone`, avec `city` venant de `places[0].city` ou de `city.canonical` ;
  - `country_named` → `country_code` (filtre dur) ;
  - un pays non nommé → `country_guess` ;
  - `region_named` → ancre d'état.

## Notes d'implémentation
1. `geocode_location` prend un argument `intent: GeoIntent` à la place de `city`, `zone` et `raw_user_message`. Les autres arguments restent.
2. **Correspondance** en tête de fonction, de l'objet vers les variables internes existantes (`effective_city`, `effective_zone`, `country_code`, `country_guess`). Tout l'aval reste intact : écho, gardes, palier d'inventaire, garde #14, rayon.
3. **Vérification par le code** :
   - la `mention` doit figurer dans le message réel (comparaison sans casse ni accents) ; sinon le champ est écarté et compté en métrique. C'est un contrôle de l'affirmation du LLM, pas une compréhension du langage ;
   - `canonical` doit géocoder vers une ville avec inventaire (`_city_coordinate`) ;
   - le message réel est **injecté par le code** depuis l'invocation, plus jamais recopié par le LLM.
4. **Prompt** : la section « lieu » est réécrite pour remplir le `GeoIntent`. La ville nommée va toujours dans `city`, même écrite dans le nom d'un lieu ou d'une adresse. Les exceptions des lignes `:173-190` disparaissent ; la question sur la ville reste décidée par le code.
5. **Reprise d'un tour à l'autre** : comportement actuel conservé (remplissage depuis `profile_in`). Le champ `carryover` est lu mais pas encore appliqué : S-L5, hors périmètre.
6. Faire tourner la vraie chaîne before-tool (`tests/test_mcp_contract.py`) avec un `GeoIntent`, pour qu'aucune clé hors schéma n'atteigne le MCP.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- Tests de correspondance, Mapbox simulé : pour A, `GeoIntent(city=Paris, places=[station "Gare du Nord"])` ne donne **pas** `geocode_city_needed` et géocode la gare dans Paris. Pour B, la ville Versailles est retenue.
- Test : une `mention` absente du message est écartée et comptée en métrique.
- Test : « Gare du Nord » sans ville donne toujours `geocode_city_needed` (cas à préserver).
- Les tests géo existants (Budapest, La Défense, gare de Lyon, Saint-Paul, Manhattan) passent. Si une assertion doit changer, la justification est dans le rapport et une entrée `deviation` est ajoutée.
- Le prompt de la feuille ne contient plus l'exception « named after a city they are not in » (diff).

## Hors périmètre
L'adresse et le code postal (Q08). Le retrait de `_city_named_in_message` (Q09) : il reste en repli pendant cette phase. `carryover` (S-L5).
