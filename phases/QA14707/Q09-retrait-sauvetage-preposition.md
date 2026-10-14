# Q09 — Retrait : sauvetage de ville par préposition, correspondance de texte `pending_place`

| | |
|---|---|
| **Phase** | 4 |
| **Modèle** | sonnet — retrait borné, remplacé par du code déjà livré en phases 2 et 3 |
| **Effort** | medium |
| **Dépend de** | Q08 |
| **Prérequis** | E2, H3 (rejeu live après la phase 3) |
| **Zone (owned_files)** | `agents/hotel_search_agent/hotel_search_agent/geocode_tool.py` · `agents/hotel_search_agent/tests/**` |

## Contexte utile
- `geocode_tool.py:230-270` (`fc5cbd9`, sur `main`) : `_CITY_AFTER_PREPOSITION_RE`, `_ARTICLES`, `_city_named_in_message`, jusqu'à 3 sondages. Exécuté sur les cas de Raphael, il échoue sur les trois :
  - A : « room in » est avalé, « paris » n'est jamais essayé ;
  - B : seuls « Boulevard de » et « Boulevard » sont essayés ;
  - C : rien n'est capturé.
- `geocode_tool.py:944-968` : `_complete_pending_place` fait une correspondance de mots exacte entre la réponse et les options d'homonyme. « Pari » échoue.
- Remplaçants :
  - `city.mention` / `city.canonical` du `GeoIntent` (Q07) ;
  - la réponse à une `Clarification` par index d'option (Q05) ;
  - la ville extraite par la feuille depuis la réponse (Q04 + Q07).

## Notes d'implémentation
- Supprimer `_CITY_AFTER_PREPOSITION_RE`, `_ARTICLES`, `_city_named_in_message` et son appel.
- Supprimer la correspondance de texte de `_complete_pending_place` : une option d'homonyme se choisit par index (Q05) ou par la ville que la feuille extrait de la réponse. Côté feuille seulement : les lectures de `pending_place` dans le concierge (`_CONCIERGE_ONLY_KEYS`, `profile.py:365` ; `agent.py:1714-1715`) sont retirées en Q11, qui possède ces fichiers et tourne en parallèle.
- Les tests de `fc5cbd9` (« près de St Paul's à Londres », « autour des champs élysées ») et ceux de `pending_place` (Manhattan → « New York ») restent la **spécification**. Ils doivent passer par le nouveau chemin. Adapter leurs entrées (un `GeoIntent` au lieu de chaînes), jamais leurs assertions.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- `_CITY_AFTER_PREPOSITION_RE`, `_ARTICLES` et `_city_named_in_message` n'existent plus (diff, `git grep` vide).
- Les assertions des tests « St Paul's à Londres », « champs élysées » et Manhattan passent sans modification.
- Aucune nouvelle regex ni liste de mots dans le diff.

## Hors périmètre
Les autres règles de langage de `geo_guards.py` (mots génériques, état lu dans le texte, exonymes) : S-L7.
