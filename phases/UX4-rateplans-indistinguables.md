# UX4 — Deux rate plans que rien ne distingue à l'écran

> Issu de la liste Fabien du 2026-08-27, item 4.

## Symptôme rapporté

> « Voir comment gérer les rateplans avec le même nom pour éviter d'avoir des listes avec
> mêmes noms et mêmes timeslots. »

## Constat — le dédoublonnage backend ne regarde pas ce qui est affiché

`agents/b2c_concierge/b2c_concierge/inline_tools.py:606-624` (`_day_rate_plans`) dédoublonne
sur **`offer_id` seul** :

```python
if plan is None or plan["offer_id"] in seen:
    continue
```

Deux offres MCP d'UUID différents mais de `offerType`, `ratePlanName`, créneau et prix
identiques passent donc toutes les deux. Elles produisent deux boutons rigoureusement
identiques.

Le frontend se bat déjà contre ce problème et documente ses deux cas live
(`web/vendor/static/js/chat/ui/messages.js:638-658`) :

> *Ibis La Ciotat — 3 formules, toutes `dayuse.day`, toutes 10:00-15:00, ne différant que par
> la chambre.* → titres par type : « Journée / Journée / Journée ».
> *Mercure Lyon Saxe — 3 formules toutes nommées « Standard King Room », ne différant que par
> le créneau.* → titres par nom : trois lignes identiques.

D'où l'heuristique `nameLeads` : le nom mène **seulement** quand les types ne séparent pas et
que les noms séparent. Elle est bonne, et elle traite ces deux cas.

**Le cas résiduel de Fabien est celui qu'aucune heuristique de titre ne peut gagner** : quand
type ET nom ET créneau sont identiques, il n'y a plus aucune dimension affichée sur laquelle
départager. Le frontend ne peut pas inventer une différence qui n'est pas dans la donnée.

Chiffres du repo, à ne pas re-mesurer : 2 829 des 5 591 hôtels multi-plans (**51 %**) donnent
le même `ratePlanName` à toutes leurs formules ; `roomType` est NULL sur les 22 177 lignes du
snapshot ; `offerType` est un enum fermé à 5 valeurs dont `dayuse.day` couvre 72 %
(`inline_tools.py:536-560`). Une collision complète est donc **structurellement fréquente**,
pas un cas exotique.

## Décision de design — dédoublonner sur la signature d'affichage, côté backend

Pas une troisième heuristique frontend. La règle : **si deux lignes seraient
indiscernables pour l'utilisateur, il n'y a pas de choix à lui offrir.**

Dans `_day_rate_plans`, dédoublonner sur un tuple de signature en plus de `offer_id` :

```
(offer_type, name, start_time, end_time, price_eur_cents)
```

Le **prix reste dans la signature** : deux formules identiques à 70 € et 80 € sont un vrai
choix (le prix est affiché, l'utilisateur voit la différence). Ne s'effondrent que les lignes
identiques **jusqu'au prix**. Conserver la première rencontrée — la liste est triée
cheapest-first ensuite, et de toute façon les doublons ont le même prix par construction.

Pourquoi backend et pas frontend :

- `generate_booking_link` a déjà été appelé une fois **par plan** sur le tour de pick
  (`_quote_picked_rate_plans`, `inline_tools.py:795`, et les liens sont générés en parallèle
  sur une session MCP unique). Écarter les doublons **avant** cette étape économise des
  appels MCP — or MCP renvoie des 429 sur les appels chaînés (constat mémoire).
- La règle devient couverte par un test Python, comme `discount_pct` l'est déjà et pour la
  même raison écrite dans le fichier : « a discount is a claim, and claims need a guard ».
- `_MAX_RATE_PLANS` cesse d'être dépensé sur des doublons.

Effet de bord voulu : quand il ne reste qu'un plan après collapse, `renderRatePlans` rend
déjà `NO_PLANS` (`messages.js:639` : `plans.length < 2`) et la carte simple s'affiche. Rien à
changer côté widget.

## Périmètre

`agents/b2c_concierge/b2c_concierge/inline_tools.py` — `_day_rate_plans` seulement.
Aucun changement de contrat, aucun changement widget.

## Hors périmètre

- L'heuristique `nameLeads` du widget : elle traite les cas où une dimension **sépare**
  vraiment. Elle reste utile et ne bouge pas.
- Demander à MCP_B2C un différenciateur de formule : c'est déjà écrit dans
  `reports/PROMPT-MCP-B2C-RATEPLANS.md`, et `_rate_plan_view` est déjà construit pour gagner
  les labels « le jour où ils apparaissent ». Ne pas relancer ce sujet ici.

## Pièges

- 🪤 Ne pas dédoublonner sur le seul `name` : ce serait exactement le cas *Ibis La Ciotat*, où
  3 formules réellement différentes (vue mer / balcon) partagent le nom. On perdrait de
  l'inventaire réel.
- 🪤 Ne pas dédoublonner avant le filtrage par jour : `_offers_for_day` doit passer d'abord,
  sinon on collapse la formule de mardi avec celle de mercredi (même type, même créneau, même
  prix — et `get_hotel_details` sans date renvoie 94 offres sur 32 jours pour l'hôtel 22293).
  L'ordre actuel de la boucle est déjà bon : ne pas le réorganiser.
- 🪤 `price_eur_cents` peut être `None` (plan sans prix, « still bookable, just not
  comparable »). `None` dans la signature est légitime et ne doit pas faire collapser deux
  plans sans prix qui diffèrent par ailleurs — vérifier que les autres membres du tuple
  suffisent, et écrire ce test.

## DoD

1. Test avec 2 offres d'UUID différents et signature d'affichage identique → **1** plan rendu.
2. Test *Ibis La Ciotat* (même type, même créneau, noms différents) → **3** plans conservés.
3. Test *Mercure Lyon Saxe* (même nom, créneaux différents) → **3** plans conservés.
4. Test prix différents, tout le reste identique → **2** plans conservés.
5. Test plans sans prix (`price_eur_cents is None`) non collapsés à tort.
6. `pytest -q` vert (baseline 1452 passed, 1 skipped), `ruff`, `mypy`, guardrails verts.
7. **Preuve prod** : trouver un hôtel réel qui déclenche le cas (partir des 51 % de
   `ratePlanName` partagés) et montrer la carte avant/après. Si aucun hôtel ne le déclenche
   en live sur la période testée, **le dire** dans le HANDOFF plutôt que d'écrire « prouvé ».
8. `HANDOFF.md` : bloc daté.
