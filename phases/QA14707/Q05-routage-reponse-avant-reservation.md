# Q05 — Routage : la réponse à la question passe avant la réservation

| | |
|---|---|
| **Phase** | 2 |
| **Modèle** | opus — triage (prompt et schéma fermé) et priorité de routage, avec l'invariant R9 en jeu |
| **Effort** | high |
| **Dépend de** | Q04 |
| **Prérequis** | E2 |
| **Zone (owned_files)** | `agents/b2c_concierge/b2c_concierge/triage.py` · `agents/b2c_concierge/b2c_concierge/agent.py` · `agents/b2c_concierge/b2c_concierge/profile.py` · `agents/b2c_concierge/b2c_concierge/inline_tools.py` · `agents/b2c_concierge/b2c_concierge/dialogue_context.py` · `agents/b2c_concierge/tests/**` |

## Contexte utile
- Trace C2 (session `8a79b460…`, tour `a53c0b1b…`). Après une question sur la ville, « Je confirme » est trié `{"family":"booking","booking_confirmation":"confirm"}`, ce qui mène à `generate_booking_link`, puis à `find_hotel_by_name("Je confirme")` en erreur, puis au gabarit `_NEEDS_SELECTION_NO_LIST` (`templates.py:364-367`).
- En prod (`cbe88b9`), le triage ne voyait pas la question posée. **Depuis PORT1 (#137)**, il reçoit `LAST ASSISTANT QUESTION` = `profile.last_clarifying_question` (`triage.py:487-519`, appel `agent.py:1226`). Seul le budget s'en sert, par `answer_to` : le triage recopie la question, et le code vérifie la citation (`triage.py:268-278`, consigne `:416-428`). Ses exemples poussent toujours « je confirme » vers `booking` (`triage.py:392` et suivantes).
- Priorité actuelle (`agent.py:1328-1362`) : signal de réservation (`:1328`) > choix nommé > pick > ordinal > affinage (`:1350`) > demande en attente vers la recherche, **seulement si `family == "ack"`** (`:1353-1360`). `pending_search` est vidée quelle que soit la route (`:1362`).
- Chemin rapide avant le triage (`agent.py:1200-1212`) : un `answers_pending` local, calculé **par regex** (`is_bare_affirmative`), décide si un « oui » court-circuite le triage.
- Le triage a déjà des champs fermés validés (`Triage`, `triage.py:149`) : `family`, `affirmative`, `booking_confirmation`, `hotel_name`, `requested_budget`… Il n'a aucun champ de réponse à une question de clarification.

## Notes d'implémentation
1. **Entrée du triage : aucun canal nouveau.** La question en attente lui arrive par le `previous_question` de PORT1. Depuis Q04, c'est le texte du gabarit, écrit par le code et plus extrait par regex. S'il y a des options, leurs libellés numérotés font partie de ce texte. Jamais le profil (minimisation RGPD).
2. **Sortie du triage.** Un champ fermé `answers_pending ∈ {yes, no}`, défaut `no`, validé comme les autres énumérations, plus l'index d'option choisi s'il y a des options.
   - Pas de copie `answer_to` pour ce champ : le code sait déjà, par l'état, qu'une clarification est en attente, et une citation à vérifier n'ajouterait qu'un faux négatif possible au routage. `answer_to` reste au budget.
   - Le triage route ; il n'extrait pas le lieu (décision L1/D-6). Pas de nouvel appel LLM.
   - Le `answers_pending` local par regex (`agent.py:1206`) cède la place à l'état : avec une clarification en attente, le chemin rapide d'accusé de réception ne s'applique jamais, et le tour passe par le triage.
3. **Priorité en code.** Clarification en attente et `answers_pending=yes` → route recherche, avec le contexte de Q04, **avant** la route réservation déduite du triage. Seul un vrai signal de réservation, c'est-à-dire une offre en attente (`pending_booking`), passe devant. La condition `family == "ack"` disparaît de ce chemin.
4. **Option choisie.** Un index d'option résout en code la ville de l'option, puis lance la recherche.
5. **Invariant R9 renforcé.**
   - La route réservation exige une offre en attente ou une liste à l'écran. Sinon : si une clarification est en attente, c'est une réponse ; sinon, le gabarit « pas de liste » actuel, inchangé.
   - `find_hotel_by_name` n'est appelé qu'avec un `hotel_name` venu du triage, jamais avec le message brut (`_extract_hotel_name_candidate`, `inline_tools.py:146`).
6. Ajuster les exemples du prompt du triage : « je confirme » n'est une confirmation de réservation que s'il répond à une demande de confirmation de réservation.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- Test (faux triage `{"family":"booking","booking_confirmation":"confirm","answers_pending":"yes"}`, clarification en attente) : route recherche, aucun appel à `generate_booking_link` ni à `find_hotel_by_name`.
- Test : le même triage **sans** clarification en attente, sans offre ni liste, renvoie le gabarit « pas de liste », comme aujourd'hui.
- Test : avec une offre en attente, « je confirme » reste une confirmation de réservation (R9 inchangé, `guard_booking_confirmation`).
- Test : l'index d'option 2 lance la recherche sur la ville de l'option 2.
- Test : le triage rejette une valeur de `answers_pending` hors énumération et retombe sur `no`.
- Contrôle négatif noté dans le rapport : sans la nouvelle priorité, le premier test emprunte la route réservation.

## Hors périmètre
L'extraction du lieu dans la réponse (Q07, par la feuille). Retirer `_AFFIRMATIVE_RE` (Q11).
