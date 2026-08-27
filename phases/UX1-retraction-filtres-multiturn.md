# UX1 — Rétraction d'un filtre en multi-tour (« enlève le spa »)

> Issu de la liste Fabien du 2026-08-27, item 1. **Priorité 1 des six** : c'est le seul qui casse une intention explicite de l'utilisateur.

## Symptôme rapporté

> « Quand on change un critère de recherche, celui-ci ne s'applique pas. Par exemple si je demande un hôtel à Paris avec spa et qu'il ne me retourne rien, quand je lui demande d'enlever le filtre spa, il ne le fait pas. »

## Cause racine — établie dans le code, pas supposée

Il n'y a pas de « bug multi-tour » : le multi-tour fonctionne **trop bien**. Le filtre est
re-appliqué par **deux cliquets indépendants**, chacun monotone croissant. Les deux doivent
être coupés ; couper un seul ne change rien de visible.

### Cliquet A — la feuille ré-applique le filtre depuis le profil

`agents/hotel_search_agent/hotel_search_agent/equipment_ids.py:164-166`

```python
llm_keys = _canonical_keys(args.pop("amenities", None))
profile_keys = _canonical_keys(_profile_amenities(tool_context))
requested = profile_keys + [key for key in llm_keys if key not in profile_keys]
```

`requested` est une **union avec le profil**, à chaque tour. Et le modèle n'a aucun canal
pour exprimer un retrait : le paramètre virtuel `amenities` est déclaré (`equipment_ids.py:56-67`)
comme « amenities the user explicitly asked the hotel to HAVE », et l'instruction
(`agents/hotel_search_agent/hotel_search_agent/agent.py:192-200`) lui **interdit** d'y mettre
une négation :

> « A negated or excluded amenity ("sans piscine", "no pool") is NOT a request: do not include it »

Donc « enlève le spa » → le modèle omet `amenities` → `llm_keys = []` → `requested = ["spa"]`
→ `hotelEquipmentIds = [35]` repart vers MCP. Le tour est **identique** au précédent.

### Cliquet B — le réducteur du concierge n'a pas de soustraction

`agents/b2c_concierge/b2c_concierge/profile.py:616-621`

```python
if values.get("amenities"):
    merged = list(profile.amenities)
    for amenity in values["amenities"]:
        if amenity not in merged:
            merged.append(amenity)
    profile.amenities = merged
```

`append`-only. `profile.amenities` ne peut que grandir, pour toute la durée de la session.
Noter les deux conséquences non évidentes :

- un `{"op": "set", "value": []}` correct venant de la feuille serait **avalé** par le
  `if values.get("amenities"):` (une liste vide est falsy) ;
- un `{"op": "set", "value": ["pool"]}` (spa retiré) serait **re-mergé** avec le spa du profil.

Le réducteur doit donc changer **en même temps** que la feuille.

## La règle d'accumulation n'est PAS le bug — ne pas la supprimer

`agents/hotel_search_agent/hotel_search_agent/occupancy.py:26-33` écrit noir sur blanc la
doctrine du repo, et elle est juste :

> « the model's value for THIS turn wins; otherwise carry the profile's forward. That is the
> **date** rule (a fresh statement supersedes), not the **amenities** one (`equipment_ids`
> unions profile and LLM keys, because filters accumulate). »

L'accumulation est voulue : l'utilisateur ne doit pas retaper « avec piscine » à chaque tour.
Ce qui manque, c'est **le canal de rétraction**. La correction ajoute une soustraction, elle
ne remplace pas l'union par un écrasement.

## Périmètre — 5 fichiers

| Fichier | Changement |
|---|---|
| `hotel_search_agent/equipment_ids.py` | 2e param virtuel `amenities_removed` + soustraction dans `enforce_equipment_filters` |
| `hotel_search_agent/agent.py` | 1 puce d'instruction pour le nouveau param |
| `hotel_search_agent/response_bridge.py` | `profile_delta["amenities"]` passe en `_op_set(...)`, émis même vide — **mais seulement si l'état a été écrit ce tour-ci** (voir pièges) |
| `b2c_concierge/profile.py` | `_normalize_delta` remonte les slots arrivés en `op: set` ; le bloc amenities honore le remplacement |
| `libs/b2c_common/scores.py` | +1 nom dans `GUARD_SCORE_NAMES` (append seul) |

## Ce qu'il faut faire

### 1. Le canal de rétraction (feuille)

Ajouter un paramètre virtuel `amenities_removed`, **même enum fermée** que `amenities`
(`list(EQUIPMENT_IDS)`), injecté par `inject_amenities_declaration` à côté de l'existant.
Sa description couvre les DEUX formulations, parce qu'elles produisent le même effet
métier — MCP n'a pas de filtre négatif, donc « je ne veux pas de X » == « X n'est pas dans
le filtre » :

- la rétraction d'une contrainte posée avant : « enlève le spa », « finalement sans le spa », « drop the pool filter » ;
- la négation dans une demande fraîche : « un hôtel sans piscine ».

Bénéfice collatéral à mentionner dans la MR : aujourd'hui « un hôtel sans piscine » **après**
« avec piscine » garde le filtre piscine. Ce chantier le corrige aussi.

### 2. La soustraction (feuille)

```python
removed = _canonical_keys(args.pop("amenities_removed", None))
requested = [k for k in (profile_keys + new_llm_keys) if k not in removed]
```

**Précédence quand une clé est dans les deux : l'ajout gagne.** Ce n'est pas une préférence,
c'est une protection : le piège d'inversion de négation de gpt-4o-mini (leçon S10, et le
`_AMENITIES_PROPERTY` actuel est écrit pour lui) fait que le modèle peut recopier la clé dans
les deux champs sur « je veux une piscine ». Une demande explicite ce tour-ci ne doit jamais
être annulée par un signal de retrait. Compter la collision dans une métrique
(`dayuse_metric=amenity_filter_conflict`, comptes seuls, jamais les clés — même discipline
RGPD que `equipment_ids.py:70-74`).

### 3. Le transport (feuille → concierge)

`response_bridge.py:1270-1272` devient un `_op_set` émis **même quand la liste est vide** :
c'est légitime et sans perte, parce que `requested` **contient déjà** les clés du profil —
un `set` porte donc l'état complet du tour, pas un fragment.

`_op_set` existe déjà (`response_bridge.py:1092-1098`) et sa docstring annonce précisément
cette migration : « amenities/budget/timeslot stay flat here on purpose (out of this phase's
scope) ». UX1 **est** cette phase.

### 4. Le réducteur (concierge)

`_normalize_delta` (`profile.py:472-491`) renvoie un 3e élément `explicit_sets: set[str]` —
les slots arrivés sous forme `{"op": "set"}`. Le bloc amenities devient :

```python
if "amenities" in explicit_sets:
    profile.amenities = list(values.get("amenities") or [])   # remplacement autoritaire
elif values.get("amenities"):
    ...merge append-only existant...                          # retro-compat liste plate
```

Garder la branche `elif` : la retro-compat liste plate est un contrat explicite de
`_normalize_delta` (« today's plain `{key: value}` leaf format »), et les tests existants
l'exercent.

### 5. La preuve en prod (guard)

Ajouter `filter_relaxation_honored` **à la fin** de `GUARD_SCORE_NAMES`. Le contrat
l'autorise explicitement (`libs/b2c_common/b2c_common/scores.py:7` : « add new guards, never
rename or remove one ») — donc **append**, jamais un réordonnancement.

Il tire quand `removed` retire effectivement au moins une clé de l'ensemble qui aurait été
appliqué. Passer par `record_guards_fired` (`response_bridge`), **unique écrivain** de
`temp:hotel_search_guards_fired` depuis PR #95 — ne pas créer un second chemin.

Rappel structurel vérifié le 2026-08-26 : `score_guards` n'est appelé qu'à **un seul endroit**
(`b2c_concierge/agent.py:562`). Un appel A2A direct à la feuille ne produira **jamais** de
score : toute preuve Langfuse doit traverser le concierge.

## Hors périmètre — mais découvert pendant l'analyse, à ne pas perdre

**Le budget affiché n'est pas le budget appliqué.** `query_params` part toujours vide
(`agent.py:349-351`) : tout voyage par `profile_in`. Or `budget_max` n'est **jamais**
ré-injecté dans les args de `search_offers` (contrairement à `amenities` via `equipment_ids`
et à `adults/children` via `occupancy.inject_profile_occupancy`). Ses seuls consommateurs sont
`facade.py:379` (`active_filters`, donc l'UI) et `agent.py:697`.

Conséquence : au tour 2 sans mention de prix, la recherche part **sans filtre budget** alors
que `active_filters` affiche toujours `budget_max: 80`. C'est le symptôme miroir de celui de
Fabien — le critère affiché ne s'applique pas.

**Action UX1 : mesurer et rapporter, ne rien corriger ici.** Écrire le constat dans le
HANDOFF avec la trace qui le prouve, et laisser Fabien arbitrer (porter le budget comme les
amenities, ou cesser de l'afficher). Élargir le scope en cours de phase serait exactement ce
que `SESSIONS-CLAUDE-CODE.md` interdit.

## Pièges

- 🪤 **LE piège de la phase.** Sur un tour où `search_offers` n'est pas appelé (tour de
  clarification qui s'arrête à `geocode_location`, ou `find_hotel_by_name`),
  `STATE_APPLIED_AMENITIES_KEY` n'est **jamais écrit**. Le code actuel
  (`state.get(KEY) or []`) écrase la distinction entre « absent » (→ carryover) et
  « écrit vide » (→ set à vide). Tel quel, passer en `_op_set` inconditionnel **efface les
  filtres à chaque tour de clarification**. Il faut distinguer `None` (absent) de `[]` :
  `sentinel = state.get(KEY)` puis `if sentinel is not None: profile_delta["amenities"] = _op_set(sentinel)`.
  Écrire le test de non-régression sur ce cas précis **avant** le reste.
- 🪤 Le concierge ne lit **que** `profile_delta` sur le fil : une clé sœur au niveau racine
  n'atteint jamais le profil (constat S-G9 finding 1, `response_bridge.py:1301-1304`).
- 🪤 `configId` Langfuse est plafonné à 35 caractères. `filter_relaxation_honored` fait
  25 → `guard_filter_relaxation_honored` fait 31, ça passe. Vérifier quand même : le guard
  `date_hallucinated_year_rolled_forward` a un `configId: null` définitif pour cette raison.
- 🪤 Ne pas toucher `EQUIPMENT_IDS` : la table est le **correctif** du bug d'ID halluciné
  (Miami `[1]` → 0 offres), pas un mapping à réduire. Voir UX6.

## DoD

1. Test qui **échoue sur le code actuel** avec la signature du bug : tour 1 « hôtel à Paris
   avec spa » → tour 2 « enlève le spa » → assertion que `hotelEquipmentIds` est absent des
   args du 2e `search_offers`. Vérifier l'échec par `git stash` du seul correctif, comme
   `test_client_header_outranks_an_existing_cookie` l'a fait pour PR #97.
2. Test de non-régression du piège ci-dessus : un tour de clarification ne vide pas `amenities`.
3. Test que l'accumulation normale survit : « avec piscine » puis « et un spa » → les deux.
4. Test de la précédence de collision : la clé dans les deux champs → appliquée.
5. `pytest -q` vert (**baseline 2026-08-27 : 1452 passed, 1 skipped**), `ruff`, `mypy`,
   `dayuse_guardrails.sh` verts.
6. `llm_calls ≤ 3` sur la trace de preuve — ce chantier n'ajoute **aucun** appel LLM
   (le param virtuel voyage dans l'appel existant de la feuille).
7. **Preuve prod** via le proxy widget (`x-dayuse-synthetic: 1`), session fraîche : la
   séquence spa → « enlève le spa » rend des hôtels, et
   `guard_filter_relaxation_honored = true` dans Langfuse. Filtre `value: ["true"]`
   (BOOLEAN — `["1"]` fait échouer le serveur), et **valider le filtre positivement** avant
   de conclure quoi que ce soit d'un zéro.
8. `HANDOFF.md` : bloc daté + le constat budget de la section « hors périmètre ».
