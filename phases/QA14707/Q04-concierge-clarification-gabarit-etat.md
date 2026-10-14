# Q04 — Concierge : clarification rendue par gabarit, état persistant, anti-boucle sur l'état

| | |
|---|---|
| **Phase** | 2 |
| **Modèle** | opus — touche le cœur du concierge (`agent.py`, `profile.py`), la synthèse et une garde |
| **Effort** | high |
| **Dépend de** | Q03 |
| **Prérequis** | E2 |
| **Zone (owned_files)** | `agents/b2c_concierge/b2c_concierge/agent.py` · `agents/b2c_concierge/b2c_concierge/profile.py` · `agents/b2c_concierge/b2c_concierge/templates.py` · `agents/b2c_concierge/tests/**` |

## Contexte utile
- `DIAGNOSTIC.md` §1, retours 2 et 3. Décision **D-Q2** : la question de clarification se rend par gabarit, sans synthèse.
- État actuel sur `main` (#135) :
  - `profile.pending_search = {request, question}` est posé par `next_pending_search` (`profile.py:985`) ;
  - la `question` est extraite **par regex** de la paraphrase de la synthèse (`extract_final_question`, `profile.py:1063` ; appels `agent.py:904`, `:920`, `:926`) ;
  - la même extraction alimente `profile.last_clarifying_question` (`agent.py:928`). Ce slot est déjà posé directement par des gabarits du code ailleurs (`agent.py:1468`, `:1580`, `:1599`) : c'est le modèle à suivre ;
  - le contexte « EARLIER REQUEST / YOU ASKED / REPLY » est construit par `pending_search_context` (`profile.py:1002`, appel `agent.py:1645`) et attaché par `_attach_outgoing_datapart` (`agent.py:365`).
- Synthèse : `_SYNTHESIS_INSTRUCTION` (`agent.py:451`), appel `:691`. Garde anti-boucle : `agent.py:900-928` (`questions_equivalent`, `profile.py:1077`). Elle compare des paraphrases et n'a pas déclenché sur la trace C1.
- Gabarits en 7 langues : `templates.py` (`TEMPLATE_LANGUAGES`).

## Notes d'implémentation
1. **Rendu.** Quand la feuille remonte une `Clarification` (Q03), la réponse est le gabarit du concierge dans la langue de la conversation, construit depuis l'objet (`subject`, options numérotées). Aucun appel de synthèse sur ce tour ; le budget LLM du tour le reflète.
   - Vérifier que le chemin SSE (`/v3/chat/stream`) émet bien `progress` puis le texte quand la synthèse est sautée, comme pour les gabarits existants.
2. **État.** Nouveau slot réservé au concierge, `profile.pending_clarification = {clarification, request}`.
   - `request` est la demande non cherchée, cumulée comme `pending_search` (500 car. max).
   - Le gabarit rendu pose aussi `profile.last_clarifying_question`, comme les autres gabarits du code : c'est ce texte, écrit par le code, que le triage reçoit au tour suivant (`previous_question`, Q05).
   - Le tour suivant envoie à la feuille la demande d'origine, la clarification **structurée** (et non une paraphrase) et la réponse. La feuille réextrait date, créneau et budget depuis la demande d'origine : c'est elle qui comprend, sans regex.
   - Sur ce chemin, `pending_clarification` remplace la paire `pending_search.question` / regex. Les questions libres de la feuille restent sur `pending_search`, et leur regex est retirée en Q11.
3. **Anti-boucle sur l'état.**
   - Si la même `Clarification` (même `kind`, même `subject`) revient au tour suivant, le gabarit passe à une variante différente : soit les options du géocodeur numérotées, soit, s'il n'y en a pas, « je ne trouve pas « X » sans la ville » avec un exemple de réponse.
   - Une troisième fois, aucune question : une réponse honnête qui propose de chercher par ville.
   - La garde garde son nom `anti_clarification_loop` (`GUARD_SCORE_NAMES` est figé) ; seule sa mesure change (état au lieu du texte).
4. ⚠️ #134 (Victor) a aussi un `pending_clarification`. Ce modèle-ci fait foi (README, « Articulation »), et le nom est gardé pour que le portage de #134 s'y raccorde.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- Test : un tour où la feuille remonte une `Clarification` ne fait **aucun** appel de synthèse, et sa réponse est le gabarit dans la langue de la conversation (au moins `fr` et `en`).
- Test : le tour suivant envoie à la feuille la demande d'origine (« … demain à 14h ») et la clarification structurée ; le créneau et la date y figurent.
- Test : la même clarification deux tours de suite donne deux textes différents ; à la troisième, plus de question.
- Test : aucune option absente de la `Clarification` n'apparaît dans la réponse (rendu sans LLM).
- Contrôle négatif noté dans le rapport : sans le correctif, le test « aucun appel de synthèse » échoue.

## Hors périmètre
Le triage et la priorité de routage (Q05). Le retrait de la regex des questions libres (Q11).
