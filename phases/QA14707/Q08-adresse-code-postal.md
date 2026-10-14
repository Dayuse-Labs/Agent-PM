# Q08 — Adresse et code postal résolus par le géocodeur

| | |
|---|---|
| **Phase** | 3 |
| **Modèle** | opus — politique géo, avec des cas à préserver (ZIP américain, homonymes) |
| **Effort** | high |
| **Dépend de** | Q07 |
| **Prérequis** | E2 |
| **Zone (owned_files)** | `agents/hotel_search_agent/hotel_search_agent/mapbox_client.py` · `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py` · `agents/hotel_search_agent/hotel_search_agent/geo_resolver.py` · `agents/hotel_search_agent/tests/**` |

## Contexte utile
- Trace C : « Un hôtel près du 2 boulevard Poissonnière 75009 demain » donne `zone="2 boulevard Poissonnière"`, code postal jeté, `geocode_city_needed`.
- Défaut latent, prouvé hors ligne : `select_us_postal_anchor` (`geo_guards.py:458`) lit `75009` et `13001` comme des ZIP américains. `geocode_tool.py:671-675` force alors `country_code="US"` quand aucun pays n'est donné.
- `mapbox_client.py` utilise Geocoding v6 (`GEOCODE_URL`, `:29`). Il lit `context.country` et `context.region` (`:229-264`), pas `context.postcode` ni `context.place`. `match_code` et `confidence` n'existent que pour une adresse (`:15-17`).

## Notes d'implémentation
1. `mapbox_client` lit en plus `context.postcode`, `context.place` (et `match_code` pour une adresse) sur les candidats.
2. **Adresse ou rue avec `postal_code`** : géocoder la mention complète avec son code postal, en filtrant par pays (`country_named`, sinon le pays du marché en indice), types adresse et rue.
   - Le résultat est accepté **seulement si** `context.postcode` est égal au `postal_code` extrait : une égalité de champs structurés, aucune regex.
   - La ville est alors `context.place`, la zone est l'adresse, et il n'y a pas de question.
3. **Code postal seul** (« dans le 75009 ») : géocodage de type code postal, filtré par pays ; la ville est `context.place`.
4. Une ville obtenue ainsi compte comme ville pour le déclenchement de `city_needed` : le code postal suffit. Aucun autre changement à la règle `city_needed` : « Gare du Nord » seul pose toujours la question.
5. `select_us_postal_anchor` reste en place pendant cette phase ; son retrait vient en Q10. Ne pas aggraver : quand le `GeoIntent` porte un `postal_code` et un pays, c'est lui qui gagne.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- Test (réponse Mapbox v6 enregistrée en fixture, avec `context.postcode = "75009"` et `context.place = "Paris"`) : `GeoIntent(places=[address "2 boulevard Poissonnière", postal_code "75009"])` → ville Paris, aucune question.
- Test : un résultat dont `context.postcode` diffère du code extrait est refusé.
- Test : « 2 boulevard Poissonnière 75009 Paris » sans pays nommé n'est jamais cherché aux États-Unis.
- Test : « Gare du Nord » sans ville ni code postal donne toujours `geocode_city_needed`.
- Test : le cas existant « near 11580 » (bug prod de ZIP américain) garde son comportement.

## Hors périmètre
Retirer `select_us_postal_anchor` (Q10). Changer la règle `city_needed` au-delà du code postal.
