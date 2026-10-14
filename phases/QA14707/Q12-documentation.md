# Q12 — Documentation : HANDOFF, CHANTIERS, plan S-L

| | |
|---|---|
| **Phase** | 5 |
| **Modèle** | sonnet — documentation qui doit dire exactement ce que le code fait ; pas mécanique |
| **Effort** | medium |
| **Dépend de** | — (phase 5 : tout le code est mergé) |
| **Prérequis** | E2 |
| **Zone (owned_files)** | `HANDOFF.md` · `CHANTIERS.md` · `reports/PLAN-LEAF-GEO-2026-10-08.md` · `SESSIONS-CLAUDE-CODE.md` |

## Contexte utile
CLAUDE.md, « Fin de session » · le README de ce dossier (décisions D-Q1 à D-Q3, « Articulation ») · les rapports des tâches Q01-Q11 · mémoire `project-chantiers-source-of-truth` : CHANTIERS.md est la liste vérifiée, et les blocs `### Reste` de HANDOFF se recopient après livraison.

## Notes d'implémentation
1. **`HANDOFF.md`** : un bloc daté en tête.
   - **Fait** : par tâche, avec les preuves.
   - **Reste** : H3 et H4 si non faits ; la question à Raphael sur la locale.
   - **Pièges découverts**.
   - Retirer les « reste » que ce plan a soldés.
2. **`CHANTIERS.md`** :
   - une entrée QA14707 (fait / reste) ;
   - la section L mise à jour selon D-Q1 : le `GeoIntent` est produit dans la feuille de recherche ; S-L3/S-L4 deviennent conditionnels ;
   - les règles retirées par Q09, Q10 et Q11 sorties de la liste S-L7.
3. **`reports/PLAN-LEAF-GEO-2026-10-08.md`** :
   - §3 : contrat v1.1 (`postal_code`, `mention` / `canonical`) ;
   - §4 : séquence modifiée par D-Q1 ;
   - liste S-L7 : `select_us_postal_anchor` ajouté puis marqué retiré ;
   - numéros de ligne périmés corrigés (ceux du plan sont ceux de `cbe88b9`).
4. **`SESSIONS-CLAUDE-CODE.md`** : la section S-L renvoie vers ce plan.

## Vérification
```
bash scripts/dayuse_guardrails.sh .
/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q
```

## Définition du fini
- `HANDOFF.md` commence par un bloc daté QA14707 (fait / reste / pièges).
- `CHANTIERS.md` a l'entrée QA14707, et sa section L reflète D-Q1.
- Le plan S-L contient `postal_code` dans son contrat et `select_us_postal_anchor` dans sa liste S-L7.
- Chaque affirmation du bloc HANDOFF cite un fichier, un test ou un commit vérifiable.

## Hors périmètre
Tout fichier de code.
