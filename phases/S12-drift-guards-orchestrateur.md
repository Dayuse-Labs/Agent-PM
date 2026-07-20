# S12 — Drift agent-usa juillet : guards orchestrateur (exhaustion, budget-vs-durée, named-hotel) (∥ possible avec S13)

| | |
|---|---|
| **Mode** | **LOOP ENGINEERING recommandé** — ou piloté |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche/worktree** | `git worktree add ../AgentB2C-s12 -b s12-drift-guards` si S13 tourne en parallèle |
| **Zone autorisée** | orchestrateur (`agents/b2c_concierge/**`) + ses tests — NE PAS toucher `agents/hotel_search_agent/**` (zone S13) ni `evals/**` |
| **Prérequis** | S9 mergée · fixes en cours de Fabien mergés (rebase sur main fraîche AVANT de démarrer) · agent-usa local à `b429125` (fait le 2026-07-20) |
| **Durée cible** | 1 journée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `AUDIT-DRIFT-AGENT-USA-2026-07-20.md` · spec exécutable (agent-usa, checkout à `b429125`) :
- `tests/unit/application/test_search_exhaustion_guard.py` (entier — spec de l'item 1)
- `tests/unit/application/test_prod_audit_fixes_2026_07_19.py` : UNIQUEMENT `test_distance_minutes_are_not_persisted_as_a_budget`, `test_real_budget_with_currency_is_not_dropped`, `test_prompt_exposes_default_provenance_instead_of_calling_it_user_requested`
- `tests/unit/application/test_loop_enforcement_and_name_lookup.py` : UNIQUEMENT `test_explicit_named_hotel_outranks_inherited_city_scope`
- `src/application/i18n/messages.py` : la clé `search_exhausted` (≈ l.595) — pour le wording du message terminal, à adapter fr/en

Comme en S4/S5 : porter le COMPORTEMENT (mêmes scénarios, mêmes verdicts), jamais le code — agent-usa mute un `Conversation.preferences` long-lived, ici tout passe par `SessionProfile` (profile.py) et des fonctions pures.

## Périmètre
**IN** : guard search-exhaustion terminal (le bug boucle Rimini existe chez nous), extension P1 budget-vs-durée, précédence named-hotel explicite, honnêteté provenance dans le prompt de synthèse, note façade (2 champs de requête).
**OUT** : feuille search (zone S13) · country anchoring / uncovered-country terminal (jamais porté, décision produit — voir audit) · toute résolution de date/« now » · re-pose des baselines batterie (S10).

## Étapes (= items de boucle)

1. **Guard search-exhaustion terminal** (spec : `test_search_exhaustion_guard.py`). Bug latent vérifié : `maybe_auto_widen` re-widen ×1,5 à CHAQUE tour vide dès `consecutive_empty_searches ≥ 2` (reset uniquement sur succès) — inflation composée sans fin. À porter :
   - `SessionProfile` gagne `widen_attempt_count: int` et `search_exhausted: bool` ; `maybe_auto_widen` incrémente le compteur et refuse de widen au-delà de **2** tentatives ; quand plus rien n'est wideable (budget explicite, `None`, ou plafond atteint) ET `widen_attempt_count ≥ 2` → pose `search_exhausted=True`. Adaptation honnête : agent-usa widen sur plusieurs crans (zone/budget/amenity), ce spine ne widen QUE le budget — même machine à états, un seul cran.
   - Gate déterministe dans le spine (agent.py, AVANT `_run_leaf`) : `search_exhausted` posé + message sans signal de changement → PAS d'appel feuille, message terminal honnête (wording adapté de la clé `search_exhausted`, fr/en, dans templates.py — zéro LLM au-delà du triage). **Sémantique minimale proposée** (= le bug prod : l'utilisateur répète « Sì »/« ok ») : un affirmatif nu ne relance JAMAIS la recherche ; tout message substantif (nombre nu = budget explicite, mention horaire via `_TIME_MENTION_RE`, texte non-trivial) efface `search_exhausted` + `widen_attempt_count` et relance UNE recherche. Si cette sémantique soulève un doute → STOP, question à Fabien.
   - Succès de recherche (`record_search_outcome`, `results_count > 0`) → efface `search_exhausted` + `widen_attempt_count` (miroir du reset agent-usa).
   - Tests : la machine à états en pur (profile.py) + à travers le spine (pattern `test_spine.py::TestRecoveryAck`) : exhaustion → « oui » nu ne recherche PAS ; nouvelle ville/contrainte → recherche relancée une fois, flags effacés.

2. **Extension P1 : budget-vs-durée** (spec : les 2 tests budget de `test_prod_audit_fixes_2026_07_19.py`). Dans `apply_profile_delta` : un `budget_max` entrant dont le nombre correspond à une mention de DURÉE/DISTANCE du message du tour (« less than 20 minutes away », « à 20 min ») SANS marqueur de devise → jeté (jamais persisté) ; avec devise (« $20 », « 20 dollars », « 20€ ») → conservé tel quel. Porter le comportement de `_looks_like_time_derived_budget` en fonction pure. NE PAS ajouter de champ `max_distance_km` (ce spine n'a pas de concept distance — hors périmètre, le noter en docstring).

3. **Précédence named-hotel explicite** (spec : `test_explicit_named_hotel_outranks_inherited_city_scope`). Invariant à garantir dans `_resolve_hotel_id` (inline_tools.py) / `resolve_hotel_reference` (profile.py) : **un hôtel explicitement nommé absent de la shortlist doit atteindre MCP `find_hotel_by_name` (global) — jamais être capturé par un match token FAIBLE de la shortlist** (risque réel : `last_results` Redis périmée après changement de ville). Le match direct/substring de la shortlist reste prioritaire (zéro appel MCP, comportement S7 conservé) ; c'est le fallback token-based qu'il faut borner. Test adapté du scénario Sir Christopher Wren (nom explicite hors shortlist + shortlist contenant un homonyme partiel). `compare_hotels` reste shortlist-only (périmètre S7 inchangé).

4. **Honnêteté provenance dans la synthèse** (spec : `test_prompt_exposes_default_provenance_instead_of_calling_it_user_requested`). Le prompt de `_synthesize_with_guards` expose la SOURCE du budget/timeslot quand elle n'est pas `explicit` (défaut/feuille) + instruction « never say the user requested it ». Test : le prompt contient la source ; jamais « you asked for »/« vous avez demandé » sur un défaut. (L'auto-widen disclosure S6 reste inchangée — elle couvre déjà son cas.)

5. **Note façade (documentation seule)** : README concierge — le front d'agent-usa envoie désormais `client_local_time` + `client_timezone` (optionnels) dans le body `/v3/chat` ; notre façade les ignore sans casse (aucune résolution de date dans ce spine) ; à brancher le jour où une résolution de « now » existera. Aucun changement de comportement, aucun test.

## Règles de loop
Identiques à S04 (tests = spec intouchable, 2 rouges consécutifs = STOP, pas de push). Item 1 : si la sémantique d'effacement du flag soulève une question produit → STOP et demander.

## DoD (exécutable)
```bash
pytest agents/b2c_concierge -q          # nouveaux tests guards verts, aucun existant cassé
pytest -q && bash scripts/dayuse_guardrails.sh .
python scripts/run_release_gate.py --quick   # budget ≤3 LLM/tour intact (le gate terminal = 0 LLM après triage)
```
⚠️ La famille `empty_dead` de la batterie S8 peut changer de comportement (message terminal au lieu de re-widen) : ne PAS re-poser la baseline ici — noter dans HANDOFF pour la re-pose S10.

## Fin de session
HANDOFF (bloc daté : guards portés, sémantique d'effacement retenue, baseline à re-poser) · commit + MR. Si ∥ S13 : ordre de merge S12 d'abord, S13 rebase.

## Prompt de lancement (à coller — déplacer dans PROMPTS-SESSIONS.md à l'occasion)
```
Lis CLAUDE.md, HANDOFF.md, AUDIT-DRIFT-AGENT-USA-2026-07-20.md, puis phases/S12-drift-guards-orchestrateur.md et exécute cette phase, dans ce périmètre exactement.
Règles : un seul scope ; la spec = les tests agent-usa pointés (checkout local à b429125), porter le comportement jamais le code ; choix fondateur imprévu = STOP et question ; fin = DoD verte + HANDOFF à jour + commit branche, jamais de merge.
```
