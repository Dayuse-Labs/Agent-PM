# Audit de drift agent-usa — 2026-07-20

Delta analysé : `29fcb6e..b429125` (9 commits, 2026-07-16 → 2026-07-20, ~5 900 lignes). Le checkout local d'agent-usa était figé à `29fcb6e` depuis le 2026-07-15 (veille de S1) : **aucune session S1-S9 n'a vu ces commits**. Le checkout local est désormais à `b429125` — les fichiers de spec cités ci-dessous se lisent directement dedans.

## Ce qui a changé côté agent-usa

| Changement | Spec exécutable (agent-usa) | Impact AgentB2C |
|---|---|---|
| **Nouveau guard : search-exhaustion terminal** (prod Rimini `034c97c4`, 9 tours vides) — widening plafonné à 2 tentatives (`widen_attempt_count`), puis flag `search_exhausted` : plus AUCUNE recherche tant que l'utilisateur ne change pas ville/contrainte, message honnête (clé i18n `search_exhausted`) | `test_search_exhaustion_guard.py` (neuf) | **BUG LATENT CHEZ NOUS — S12.** `maybe_auto_widen` (profile.py) re-widen ×1,5 à CHAQUE tour vide dès que `consecutive_empty_searches ≥ 2` (le compteur ne reset que sur succès) : inflation composée sans plafond ni état terminal. Même boucle que le bug prod Rimini. |
| **9 fixes d'audit prod 2026-07-19** : « 20 minutes » persisté comme budget €20 ; budget devise à ne PAS jeter ; ZIP US géocodé monde entier ; « Perth, WA » → Washington ; horloge client vs serveur pour « now » ; provenance par défaut présentée comme demande utilisateur ; claims 18+ inventés | `test_prod_audit_fixes_2026_07_19.py` (neuf) | **3 items portables → S12** (budget-vs-durée, provenance par défaut dans le prompt de synthèse) **+ S13** (scoping pays du ZIP US). Les autres touchent des mécanismes que ce spine n'a pas (country anchoring, disambiguator, résolution de date) — voir « non-actions » ci-dessous. |
| **Règle additive named-hotel** : un hôtel explicitement nommé se résout d'abord au catalogue GLOBAL — une shortlist de ville périmée ne doit jamais le masquer | `test_loop_enforcement_and_name_lookup.py::test_explicit_named_hotel_outranks_inherited_city_scope` (neuf) | **À vérifier/fixer → S12.** Notre `_resolve_hotel_id` (inline_tools.py) est shortlist-FIRST avec fuzzy token : un match token faible peut capturer un nom explicite absent de la shortlist (risque après changement de ville, `last_results` Redis périmée). |
| **Guard uncovered-country REDESSINÉ** — 3 assertions INVERSÉES + 1 test supprimé dans `test_audit_fixes_2026_06.py` : l'ancien contrat « décliner puis wiper ville + ancre pays » devient « préserver l'identité, état terminal idempotent (`uncovered_country_terminal`), levée uniquement sur vraie transition de ville résolue ailleurs » | `test_audit_fixes_2026_06.py` (sections coverage gate, modifiées) | **Aucune action** : le country-anchoring n'a jamais été porté (hors périmètre S4, documenté). ⚠️ **Si un jour il est porté : implémenter le NOUVEAU contrat, pas les tests d'avant le 2026-07-16.** |
| **Durcissement géo massif** (5 commits) : clarification d'homonymes au lieu de deviner, pool de candidats 5→10, grounding POI/landmark (Search Box), ordre geo-tier des cartes (5 km > 35 km), rayon strict 5 km en sub-city | `test_resolved_location_golden.py`, `test_candidate_ranker.py`, `test_search_tool_authoritative_location.py`, `test_mapbox_v6_types.py` | **Aucune action immédiate** : couche de capacité que notre feuille n'a jamais eue (`mapbox_client.py` = `limit=1`, périmètre S4 = 3 guards). Le porter est une décision produit, pas un fix — session dédiée à qualifier si le besoin se confirme. |
| **Contrat `/v3/chat`** : la RÉPONSE est inchangée (aucune clé/valeur `state` nouvelle) — nos `CONTRACT_KEYS` S9 restent valides. La REQUÊTE gagne 2 champs optionnels envoyés par le front : `client_local_time` + `client_timezone` (IANA), lus par agent-usa pour interpréter « now ». Amplitude (#125) = frontend pur | diff `chat_workflow.py`, `static/js/chat/*` | **Note README seulement (S12, item 5)** : notre façade ignore les champs inconnus (aucune casse) et ce spine n'a AUCUNE résolution de date — signal à brancher le jour où une résolution de « now » existera. |

## Non-actions actées (pour ne pas re-analyser)

- **Country anchoring / disambiguator / homonymes** : toujours hors périmètre (décision S4 reconduite) — seule obligation : porter le contrat POST-2026-07-16 le jour venu.
- **`age_constraint` 18+** : aucun champ équivalent dans notre profil ; l'amenity guard couvre les claims d'équipements. Rien à faire.
- **Horloge client** : pas de résolution de date dans ce spine (documenté depuis S7) — les 2 champs de requête sont tolérés et documentés, pas consommés.
- **Amplitude #125** : zéro surface backend.

## Sessions de correction

- **`phases/S12-drift-guards-orchestrateur.md`** — exhaustion terminal + budget-vs-durée + précédence named-hotel + honnêteté provenance + note façade. Zone : `agents/b2c_concierge/**`.
- **`phases/S13-drift-geo-zip-feuille.md`** — scoping pays du géocodage sur ancre ZIP US. Zone : `agents/hotel_search_agent/**`.
- S12 ∥ S13 possibles en worktrees (zones disjointes, mécanique S4∥S5) ; séquentiel = zéro conflit. **Les deux avant S10** (le shadow-run comparera à un agent-usa qui a DÉJÀ ces guards).
