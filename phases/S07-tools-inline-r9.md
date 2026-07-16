# S07 — Tools inline (details/compare/booking), guard R9, amenity verifier

| | |
|---|---|
| **Mode** | **LOOP ENGINEERING recommandé** |
| **Modèle** | Sonnet (`claude-sonnet-5`) |
| **Branche** | `s7-tools-inline-r9` |
| **Prérequis** | S06 mergée · tools MCP_B2C `get_faq_conditions`/`generate_booking_link` mergés |
| **Durée cible** | 1-2 journées |

## Entrées à lire
`CLAUDE.md` · `HANDOFF.md` · spec (agent-usa) : `test_named_hotel_card.py`, sections amenity verifier de `test_audit_fixes_2026_06.py` · contrat MCP : descriptions des tools `get_hotel_details`, `compare_hotels`, `generate_booking_link` (flag `confirmed`)

## Périmètre
**IN** : câblage réel des 3 tools MCP inline, guard n°12 (R9), amenity claim verifier, named-hotel lookup (shortlist d'abord).
**OUT** : batteries (S8), façade (S9).

## Étapes (= items de boucle)
1. `get_hotel_details` + `compare_hotels` inline : travaillent sur la shortlist du tour (`_last_results` équivalent dans l'état), prix affichés convertis depuis `priceEuro` centimes (P3 — décision UX simple : devise du user si connue, sinon EUR, à confirmer avec Fabien si doute).
2. **Guard R9 (n°12)** : `generate_booking_link` inappelable sans flag de confirmation dans l'état du tour courant — le flux force `confirmed=false` d'abord, la confirmation utilisateur pose le flag, alors seulement `confirmed=true`. Tests des deux chemins + tentative de bypass.
3. Guard **amenity claim verifier** : vérification programmatique post-LLM des claims d'amenities vs la fiche hôtel ; hedge in-place (« non confirmé ») ; corrections dédupliquées et réinjectées au ground-truth.
4. Guard **named-hotel lookup** : un hôtel nommé se résout d'abord dans la shortlist (fuzzy), MCP `find_hotel_by_name` ensuite — jamais de dead-end sur un hôtel qu'on vient de recommander.

## Règles de loop
Identiques à S04. Item 2 (R9) : si le flux de confirmation soulève une question UX → STOP et demander.

## DoD (exécutable)
```bash
pytest -q            # 12/12 guards verts — compteur total ~150 tests portés atteint
python scripts/smoke_e2e.py --booking   # flow booking avec confirmation en 2 temps
```

## Fin de session
HANDOFF (12/12, liste des ~150 tests portés) · commit + MR.
