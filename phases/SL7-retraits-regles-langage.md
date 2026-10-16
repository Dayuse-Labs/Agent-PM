# S-L7a…f — Retrait des règles de langage, une MR par règle

> **Bandeau 2026-10-16 (plan QA14707, `plans/qa14707/`).** Plusieurs règles de ce tableau ont déjà été traitées par QA14707, sans leaf ni `GEO_LEAF_MODE` (DQ1) : le prérequis « S-L8 faite » ne s'applique pas à elles, le cas de couverture est resté vert sans la règle.
>
> | Règle | Statut |
> |---|---|
> | S-L7a regex de prépositions, articles, sondes | **retirée par Q09** (`3cbeba1`, `410b78e`) ; spécification « St Paul's à Londres » tenue par `TestCityNamedInMessage.test_a_landmark_with_its_city_in_the_intent_resolves` (`agents/hotel_search_agent/tests/test_geocode_tool.py`) |
> | S-L7b exception « gare de lyon » du prompt | **transformée, non retirée** (Q07, DQ6) : la règle S5 est `ambiguity.reason = city_needed` ; garde `qa14707-guard-gare-de-lyon-asks-city-fr` |
> | S-L7c règle « nom complet » | **réécrite** par Q07 en champ `canonical` du `GeoIntent` |
> | S-L7d mots génériques | **à faire** |
> | S-L7e État lu dans le texte | **à faire** |
> | S-L7f `select_us_postal_anchor` | **retirée par Q10, décision DQ7** (`b36672d`) : la « décision de Fabien avant tout retrait » demandée par la ligne ci-dessous est DQ7 ; les tests « near 11580 » restent la spécification (`agents/hotel_search_agent/tests/test_postcode_resolution.py`, `test_us_zip_removal.py`) ; le cas live est `qa14707-near-11580-en` |
>
> Q11 a de plus retiré côté concierge la regex d'extraction de question, la liste de mots oui/non de la route de clarification et le repli sur le message brut de `find_hotel_by_name` (hors tableau). Les numéros de ligne du tableau sont ceux de `cbe88b9` : chercher par symbole.


| | |
|---|---|
| **Mode** | Piloté pour S-L7a, puis **boucle possible** (critère mécanique : le cas qui couvre la règle reste vert sans elle) — protocole « Loop engineering » de `SESSIONS-CLAUDE-CODE.md` |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche** | une par règle : `sl7a-…`, `sl7b-…`, etc. |
| **Zone autorisée** | `agents/hotel_search_agent/**` · `evals/datasets/**` (cas de couverture) — NE PAS toucher `libs/b2c_common/b2c_common/scores.py` |
| **Prérequis** | S-L8 faite (`GEO_LEAF_MODE=on`) · taux de repli `fallback_geo_leaf` mesuré et jugé acceptable par Fabien : chaque retrait affaiblit le chemin de repli (leaf en panne) |
| **Durée cible** | non estimée |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · `reports/PLAN-LEAF-GEO-2026-10-08.md` (§1 L3, §7) · le code de la règle visée (tableau ci-dessous) et ses tests.

## Les règles

Numéros de ligne relevés le 2026-10-08 sur `main` (ou sur la branche #124 quand c'est indiqué) : ils bougent après chaque merge, `grep` avant d'agir.

| Session | Règle | Où | Cas qui la couvre | Devenir |
|---|---|---|---|---|
| S-L7a | Regex de 12 prépositions, liste de 22 articles, 3 sondes pour repêcher la ville | `geocode_tool.py:232-265` (#124, commit fc5cbd9) | « Saint Paul à Londres » et ses variantes dans les 7 langues | **supprimée (Q09)** |
| S-L7b | Exception « gare de lyon » dans l'instruction de la feuille | `hotel_search_agent/agent.py:172-182` | gare de Lyon (Paris) ; Part-Dieu (Lyon) | supprimée — **transformée en champ `ambiguity.reason = city_needed` (Q07, DQ6)** |
| S-L7c | Règle « nom complet » des monuments | `hotel_search_agent/agent.py:185-186` (#124, commit 8671594) | St Paul's Cathedral contre « St Paul's, Burdett Rd, E3 » | supprimée |
| S-L7d | Mots génériques (`_GENERIC_LOCATION_WORDS`, `demote_generic_city`) | `geo_guards.py:167-225` | « airport », « downtown », « terminal 2 » | réécrite en vérification du `GeoIntent` (un aéroport ou un quartier n'est jamais une ville) ; garde `generic_location_demotion` conservée sous le même nom |
| S-L7e | État américain lu dans le texte (`extract_state_hint_from_text`, `resolve_state_hint`) | `geo_guards.py:88-165` | « Milford ct » ; « AZ » qui n'est pas l'Arizona (registre) | lu dans `GeoIntent.region_named` ; garde `state_anchoring` conservée sous le même nom |
| S-L7f | Code postal américain (`select_us_postal_anchor`) | `geo_guards.py:458` | code postal à 5 chiffres | **retirée par Q10 (DQ7, 2026-10-14)** : la décision de Fabien a été prise, la règle est supprimée |

**À garder, ce ne sont pas des règles de langage** : `_LEADING_ARTICLE_WORDS` (`geo_resolver.py:321`, normalisation de l'écho), la question sans ville ni GPS (`geocode_tool.py:536-547`), l'écho `geocode_echo_back`, la garde #14 (`geocode_tool.py:141`), le palier d'inventaire (`geo_resolver.py:58`).

## Étapes (pour chaque règle)
1. Preuve : la règle est encore là (`grep`), et le cas qui la couvre passe AVEC elle.
2. Contrôle de couverture : le cas passe aussi en `GEO_LEAF_MODE=on` sans la règle (code commenté localement), sur 3 rejeux.
3. Retrait + tests mis à jour. Un test qui fige la règle elle-même est remplacé par un test du comportement (le cas de couverture), jamais simplement supprimé.
4. Jeux géo complets : aucune régression.

## DoD (exécutable)
```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```
Live : cas de couverture vert sur 3 rejeux sans la règle ; jeux géo sans régression ; `GUARD_SCORE_NAMES` inchangé.

## Fin de session
HANDOFF (règle retirée, cas de couverture, résultats) · commit + MR, une seule règle par MR.

## Prompt de lancement
```
Lis CLAUDE.md, HANDOFF.md, reports/PLAN-LEAF-GEO-2026-10-08.md (§1 et §7), puis
phases/SL7-retraits-regles-langage.md. Prends LA première règle non retirée du tableau (vérifie dans HANDOFF), et
retire-la elle seule, dans ce périmètre exactement.
Règles : prouver d'abord que le cas de couverture passe sans la règle ; un test qui fige la règle est remplacé par
un test du comportement ; jamais de nom de garde retiré ; une seule règle par session ; fin = DoD verte + HANDOFF
+ commit sur branche, jamais de merge.
```
