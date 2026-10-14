# Q11 — Retrait : question extraite par regex et oui/non par liste de mots, sur la route de clarification

| | |
|---|---|
| **Phase** | 4 |
| **Modèle** | sonnet — retrait borné côté concierge, remplacé par l'état structuré de Q04 et le champ fermé de Q05 |
| **Effort** | medium |
| **Dépend de** | — (phase 4 : Q04 et Q05 sont mergées) |
| **Prérequis** | E2, H3 |
| **Zone (owned_files)** | `agents/b2c_concierge/b2c_concierge/profile.py` · `agents/b2c_concierge/b2c_concierge/agent.py` · `agents/b2c_concierge/tests/**` |

## Contexte utile
- `extract_final_question` (`profile.py:1063`) extrait **par regex** la dernière question de la réponse de la synthèse, et `questions_equivalent` (`:1077`) compare deux questions. Ces deux fonctions remplissent « YOU ASKED » de `pending_search`, `profile.last_clarifying_question`, que le triage reçoit depuis PORT1, et l'anti-boucle (`agent.py:900-928`).
- `_AFFIRMATIVE_RE` (`profile.py:136`) et `is_bare_affirmative` (`:143`) : une liste fermée de oui/ok. Usages : `agent.py:1160`, `:1206`, `:1355`, `:1505`. « Je confirme » n'y figure pas.
- Remplaçants :
  - `pending_clarification` structurée (Q04) pour les questions du code ;
  - pour une question libre de la feuille, son **propre** texte, pris avant la synthèse, au lieu d'une phrase extraite de la paraphrase ;
  - `answers_pending` et `affirmative` du triage (Q05).

## Notes d'implémentation
- « YOU ASKED » de `pending_search` reçoit le texte de la feuille tel qu'elle l'a écrit, que le concierge reçoit déjà avant la synthèse (aucun changement côté feuille), et non une phrase extraite par regex de la paraphrase.
- L'anti-boucle se fait sur l'état (Q04). Si `questions_equivalent` et l'extraction n'ont plus d'appelant, les supprimer.
- `pending_place` : une fois Q09 mergée, la feuille ne lit plus ce slot. Le retirer du profil et du concierge (`_CONCIERGE_ONLY_KEYS`, `profile.py:365` ; `agent.py:1714-1715`) s'il n'a plus de lecteur. Q09 et Q11 tournent en parallèle : vérifier sur la branche d'intégration, après le merge de Q09, qu'aucun lecteur ne reste.
- Le chemin « réponse à une question en attente » ne lit plus `_AFFIRMATIVE_RE` : il lit `answers_pending` et `triage.affirmative`. Si `_AFFIRMATIVE_RE` sert encore ailleurs (accueil, relance courte), le laisser et noter l'usage restant en `debt` (S-L7).

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- Plus aucune regex n'alimente « YOU ASKED » ni la décision « réponse à la question en attente » (diff).
- Les tests de mcp-dayuse#6 (« piscine < 150 € demain 14h-18h » puis « Lyon » garde tout ; « oui » répond à la question) passent sans modification de leurs assertions.
- Aucune nouvelle regex ni liste de mots dans le diff.

## Hors périmètre
`_AFFIRMATIVE_RE` hors de la route de clarification. Les règles de langage du triage (`triage.py:102-108`, `:171-179`).
