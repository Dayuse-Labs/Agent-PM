# Q13 — Revue globale (lecture seule)

| | |
|---|---|
| **Phase** | 5 |
| **Modèle** | opus — revue sceptique de l'ensemble, lecture seule |
| **Effort** | high |
| **Dépend de** | Q12 |
| **Prérequis** | E2 |
| **Zone (owned_files)** | aucune (lecture seule) |

## Points à vérifier
1. **Principe** : aucune nouvelle regex ni liste de mots pour comprendre le langage dans le diff total (`git diff main...plan/<name>`). Chaque règle retirée (Q09, Q10, Q11) l'est vraiment (`git grep`).
2. **Budget** : `MAX_LLM_CALLS_PER_TURN` est inchangé. Un tour de clarification ne fait plus d'appel de synthèse. Aucun nouvel appel LLM ailleurs.
3. **Contrats figés** : `GUARD_SCORE_NAMES` et `FALLBACK_SCORE_NAMES` n'ont perdu aucun nom ; `contracts/geo_intent.schema.json` est identique au modèle ; `contracts/mcp_b2c_tools.json` n'a pas été touché.
4. **R9** : `generate_booking_link` reste inappelable sans confirmation, et sans offre en attente ni liste à l'écran.
5. **RGPD** : le triage reçoit la question en attente, jamais le profil. Aucun contenu de message dans les métriques (test existant vert). Aucun fichier de `baseline/` dans le diff.
6. **Cas à préserver** : « Gare du Nord » sans ville, gare de Lyon, Budapest, La Défense, « near 11580 », Saint-Paul, Manhattan. Chacun a un test vert.
7. **Vérité des documents** : HANDOFF, CHANTIERS, le plan S-L et les commentaires du code disent ce que le code fait.
8. **Gates** : les 4 commandes vertes, garde calendrier +400 j comprise.

## Vérification
```
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs
bash scripts/dayuse_guardrails.sh .
```

## Définition du fini
- Rapport de revue : chacun des 8 points marqué OK, ou KO avec sa preuve (fichier:ligne, commande).
- Chaque KO devient une entrée `review` ou `debt` dans le HANDOFF du plan.

## Hors périmètre
Toute modification de fichier.
