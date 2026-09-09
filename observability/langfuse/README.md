# observability/langfuse — définitions versionnées

Export **réel** (lu depuis l'instance, pas supposé) des objets Langfuse du projet
`b2c-concierge` : score configs, widgets + dashboard, evaluators, règles d'évaluation,
file d'annotation. Instance self-hosted **v3.224.3** (`langfuse-web-production-272b`).

> 📘 **Pour un PM ou un QA** (pas pour un dev) : `guide-langfuse-pm-qa.html` — page autonome,
> à ouvrir directement dans un navigateur (aucun serveur, aucune dépendance réseau). Elle explique
> l'outil à partir d'un **vrai tour** de l'instance : arbre des 34 étapes cliquable, les 15 guards
> avec leurs taux réels, les 7 vignettes du dashboard décodées, playbooks d'enquête, boucle
> annotation → dataset → rejeu, RGPD, quiz. Données figées au 2026-09-09 ; les requêtes de
> rafraîchissement sont en annexe de la page.

## ⚠️ Ne pas recréer les widgets via le serveur MCP Langfuse (tant qu'on est en v3)

`createDashboardWidget` (MCP) estampille **`dashboard_widgets.min_version = 2`** sans
possibilité de le paramétrer. Le query builder lit ce champ : `(minVersion ?? 1) >= 2`
⇒ il utilise les *view declarations* v2, qui lisent `events_core` / `events_full`,
**tables qui n'existent qu'en Langfuse v4**. Sur cette instance v3, tout widget de la
vue `observations` renvoie alors une 500 (`dashboard.executeQuery` → toast
« Internal Server Error » ; en logs : `Unknown table expression identifier 'events_core'`).
Les widgets `scores-*` survivent — d'où un dashboard **partiellement** vivant, qui est
la signature du problème.

**`dashboard-b2c.json` ci-contre ne porte PAS `min_version`** : le réimporter via MCP
réintroduit donc la panne.

Deux options jusqu'à OBS9 (montée en v4) :

1. créer les widgets **dans l'UI** (ils naissent en `min_version = 1`) ;
2. ou, après une création via MCP, remettre le stamp à 1 côté Postgres Langfuse :

```sql
UPDATE dashboard_widgets SET min_version = 1 WHERE min_version = 2;
```

Historique complet du diagnostic (et les hypothèses réfutées, à ne pas ressusciter) :
addendum **2026-08-26 bis** de `HANDOFF.md`.
