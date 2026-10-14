# Q10 — Retrait : ZIP américain par regex

| | |
|---|---|
| **Phase** | 4 |
| **Modèle** | sonnet — retrait borné, remplacé par `postal_code` et le pays du `GeoIntent` (Q06-Q08) |
| **Effort** | medium |
| **Dépend de** | Q09 (même fichier `geocode_tool.py`) |
| **Prérequis** | E2, H3 |
| **Zone (owned_files)** | `agents/hotel_search_agent/hotel_search_agent/geo_guards.py` · `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py` · `agents/hotel_search_agent/tests/**` |

## Contexte utile
- `geo_guards.py:417-514` : `select_us_postal_anchor` et `STREET_SUFFIX_TOKENS` (anglais seulement). Un nombre de 5 chiffres dans le texte est lu comme un ZIP américain.
- `geocode_tool.py:671-675` force `country_code="US"` quand le modèle ne donne pas de pays. Origine : bug prod « near 11580 » géocodé hors des États-Unis.
- Défaut latent : tout code postal français est pris pour un ZIP américain (`DIAGNOSTIC.md`).
- Le plan S-L (S-L7) avait oublié cette règle dans ses retraits ; Q12 l'y ajoute.

## Notes d'implémentation
- Le pays d'un code postal vient du `GeoIntent` : `country_named` si l'utilisateur l'a nommé, sinon le pays déduit par le LLM (`places[].country`), en indice. À défaut, le pays du marché. Le géocodage par code postal (Q08), filtré par ce pays, confirme le code ou le refuse.
- Supprimer `select_us_postal_anchor`, `STREET_SUFFIX_TOKENS` s'il n'a plus d'usage, et le forçage `US`.
- Les tests existants du bug « near 11580 » sont la spécification. Leur sens doit tenir : un utilisateur du marché US qui donne un ZIP est cherché aux États-Unis. Adapter les entrées, pas les assertions.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- `select_us_postal_anchor` n'existe plus (`git grep` vide) et le forçage `US` a disparu de `geocode_tool.py`.
- Test : « 2 boulevard Poissonnière 75009 Paris » et « hotel 13001 marseille », sans pays nommé, restent en France.
- Les assertions des tests « near 11580 » passent sans modification.
- Aucune nouvelle regex ni liste de mots dans le diff.

## Hors périmètre
Les autres règles de `geo_guards.py` (S-L7).
