# Datasets Langfuse — familles geo-poi / occupancy / language-robustness

Semés à la main le 2026-07-30 (audit `AUDIT-AGENTIQUE-2026-07-30.md`, bugs Champs-Élysées + occupancy).
Format aligné sur `phases/OBS6-datasets-experiments.md` — ces fichiers sont une **entrée** pour la
session OBS6 (qui possède les experiments, les évaluateurs et le gate CI), pas un harnais parallèle.

## Fichiers → datasets hébergés

| Fichier | Dataset Langfuse | Items |
|---|---|---|
| `b2c-geo-poi.jsonl` | `b2c/geo-poi` | 21 |
| `b2c-occupancy.jsonl` | `b2c/occupancy` | 14 |
| `b2c-language-robustness.jsonl` | `b2c/language-robustness` | 13 |
| `b2c-prod-regressions.jsonl` | `b2c/prod-regressions` | 6 — **importé** (`source_trace_id`), pas semé — voir OBS6 §5 |
| `b2c-qa-2026-09-30.jsonl` | `b2c/qa-2026-09-30` | 10 — retours QA du 30/09 (mcp-dayuse#8), attendus calculés par code |
| `b2c-dialogue-state.jsonl` | `b2c/dialogue-state` | 9 — état de dialogue multi-tours (mcp-dayuse#6) : critères conservés après une question, « oui » seul, créneau remplacé, affinage sans effet |
| `b2c-geo-class-2026-10-06.jsonl` | `b2c/geo-class-2026-10-06` | 10 — classe géographique (mcp-dayuse#7) : hôtel nommé, quartier, homonyme |
| `b2c-qa-14707-2026-10-14.jsonl` | `b2c/qa-14707-2026-10-14` | 12 — les 3 retours QA de Raphael (dayuse-com#14707) : 9 `target` (ville/adresse/code postal écrits dans le message, réponse à la question de ville en 1 tour, « je confirme » après une question) + 3 `regression_guard` (la ville est demandée, règle S5 ; `qa14707-near-11580-en` : « near 11580 » sans pays nommé reste aux États-Unis, DQ7/DQ8). Barre des rejeux live H1 (référence) et H3 (après la phase 3) |

Import (crée les datasets hébergés + upsert des items, idempotent — les `id` sont déterministes) :

La CI lit les datasets hébergés existants ; elle ne lance pas ces imports.
Un upsert évite les doublons mais peut remplacer les entrées, réponses attendues
et métadonnées corrigées dans Langfuse pour les mêmes identifiants. Ces scripts
servent à une initialisation ou une maintenance explicite : exporter la version
hébergée et réconcilier ses annotations avec les fichiers locaux avant réimport.
Un dataset absent fait échouer l'experiment ; il n'est pas recréé silencieusement.

```bash
# LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST dans l'env (ou .env sourcé)
.venv/bin/python scripts/langfuse_seed_datasets.py            # tout
.venv/bin/python scripts/langfuse_seed_datasets.py --dry-run  # validation locale seule
.venv/bin/python scripts/langfuse_seed_datasets.py --only b2c-occupancy
```

## Format d'item (OBS6 §2, pattern N+1 §4)

```json
{
  "id": "occ-basic-fr",                    // déterministe → ré-import = upsert, jamais de doublon
  "input": {
    "messages": [{"role": "user", "content": "..."}],  // historique JUSQU'AU tour à rejouer inclus
    "profile": {"city": "Paris", ...}      // le profil accumulé AVANT ce tour (feuilles stateless :
  },                                       // sans lui le tour n'est pas reproductible)
  "expected_output": { ... assertions déterministes ... },
  "metadata": {"family": "...", "locale": "...", "status": "...", "bug_ref": "...", "notes": "..."}
}
```

### Rejeu multi-tours (`evals/langfuse_experiment.py`, QA14707 DQ4)

Le runner rejoue **chaque tour `user`** de `input.messages`, dans l'ordre, sur **une seule session**
(même id de conversation), après avoir amorcé `input.profile` (une fois, avant le 1er tour rejoué).
Les tours `assistant` enregistrés ne sont **pas** rejoués : les vraies réponses les remplacent — c'est
le but (la question posée au tour 1 est celle à laquelle le tour 2 répond). Les évaluateurs notent la
réponse au **dernier** tour ; celle de l'avant-dernier est exposée comme `previous_reply` (à défaut,
pour un item à un seul tour `user`, le dernier tour `assistant` enregistré). Un échec de transport sur
un tour intermédiaire arrête le rejeu : la réponse notée est alors cet échec.

Les faits de trace (`expected_output.trace`) sont ceux de la trace du **dernier tour** : une trace par
tour depuis OBS4, donc la plus récente de la session ; tant que la session n'a pas autant de traces que
de tours rejoués, rien n'est rendu (l'export est asynchrone : on ne rend jamais les faits du tour
précédent comme s'ils étaient ceux-ci). Les items à un seul tour lisent toute la session, comme avant.
Les items multi-tours existants (`b2c-dialogue-state`, items `*-multiturn-*`) sont donc désormais
réellement multi-tours : leur référence se refait (H1).

`metadata.status` :
- `target` — échoue AUJOURD'HUI (c'est le but : baseline avant fix, la barre à faire passer au vert).
- `regression_guard` — passe aujourd'hui, ne doit jamais redescendre (guards S-G9/S-G11, R9…).

⚠️ Les items multi-tours `occ-persistence-*` portent `adults`/`children` dans `input.profile` : ces
champs n'existent pas encore dans `SessionProfile` (P0-1 de l'audit). Avant P0-1 ils échouent — attendu.

## Vocabulaire d'assertions (`expected_output`)

Pensé pour des évaluateurs Python déterministes (D-OBS-3), en deux niveaux.

**Niveau réponse** — lisible sur le retour `POST /v3/chat` `{message, hotels, active_filters, …}` :

| Clé | Sémantique |
|---|---|
| `min_hotels` / `max_hotels` | bornes sur `len(hotels)` |
| `hotels_within_km {lat, lon, km}` | CHAQUE hôtel rendu est dans le rayon (lat/lon des cartes) |
| `resolved_country_code` | `active_filters.country_code` attendu |
| `active_filters_include {…}` | sous-ensemble attendu d'`active_filters` (subset, pas égalité) |
| `offers_capacity_gte` / `offers_children_capacity_gte` | capacité de l'offre visible sur chaque carte |
| `clarify_expected` / `clarify_allowed` | question de désambiguïsation exigée / tolérée (0 hôtel + question) |
| `if_resolved_country_code` | pays exigé SEULEMENT si résolution directe (sinon clarify OK) |
| `clarify_options_include_country [..]` | pays devant figurer dans les options du clarify |
| `must_ask_city` | la réponse demande la ville (guard mots génériques) |
| `message_must_contain_any` / `message_must_not_contain_any` | garde-fous textuels (faibles, en dernier recours) |
| `party_total` | somme adultes+enfants attendue quand la répartition est libre |
| `cards_cover_window {start, end}` | chaque carte couvre le créneau selon la règle du site (`b2c_common.timeslot`, l'oracle partagé) — ou aucune ne le couvre et la réponse les annonce comme « les plus proches » |
| `offers_on_date {month, day}` / `{days_ahead}` | chaque carte est une offre du jour demandé (prochaine occurrence, Europe/Paris) |
| `no_iso_date_in_message` | aucune date ISO dans le texte (hors URL) |
| `first_hotel_name_contains` | la 1re carte est l'hôtel nommé (sous-chaîne, sans casse) |
| `reply_differs_from_previous` | la réponse au dernier tour n'est pas, mot pour mot (casse et blancs ignorés), la réponse au tour précédent (`previous_reply`) — « je confirme » ne rend pas la question du tour 1. `skipped` sans réponse précédente |

**Niveau trace** (`expected_output.trace`) — nécessite la trace Langfuse du run (args réels des tools,
route de triage). À brancher en évaluateur second temps (OBS6/OBS7) ; le réflexe consigné au HANDOFF :
*« la trace d'abord, la `date` envoyée d'abord »* — ici généralisé à `adults`/`children`/route géo.

| Clé | Sémantique |
|---|---|
| `search_offers_args_include {…}` | sous-ensemble des args réellement envoyés au MCP |
| `search_offers_args_absent [..]` | args qui ne doivent PAS être envoyés (non-invention) |
| `expected_route` | `search_refinement` / `ack` / `faq` / `booking_confirmed` / `not_booking_confirmed` |
| `expected_pick {pick, pick_position}` | slot PICKS du triage |
| `geocode_city_needed` | le résultat de `geocode_location` (observation TOOL `geocode_location`, dernier appel du tour) est — ou n'est pas — la question « quelle ville ? » sans option (`geocode_ambiguous` sans candidat, statut `geocode_city_needed`). `skipped` si l'outil n'a pas été appelé |
| `tools_not_called [..]` | aucun de ces outils inline du concierge n'a été appelé au dernier tour (`generate_booking_link`, `find_hotel_by_name`). Clé sur le nom EXACT de l'observation TOOL, `mcp-<outil>` (`inline_tools._call_tool`) : une observation sous un autre nom (le nom nu, par exemple) n'est pas un appel. `skipped` si aucune observation n'a été vue |
| `clarify_options_from_geocoder [..]` | aucune option inventée : parmi les lieux listés (ceux qu'un modèle est tenté de proposer, ex. `["Paris", "Bruxelles"]`), chacun que la réponse nomme doit être un candidat renvoyé par le géocodeur (`geocode_location`, options) ou un mot de l'utilisateur. Signal faible (la réponse n'expose pas d'options structurées : c'est une recherche de texte sur les seuls noms listés). Sans aucun candidat (`geocode_city_needed`), aucun nom n'est permis. `skipped` si `geocode_location` n'a pas été appelé |

Les faits de trace du harnais : `search_offers_args`, `geocode` (`ok`, `error`, `city_needed`, `options`,
`country_code`), `tool_calls` (noms exacts des observations TOOL `mcp-*` ; `None` = aucune observation vue,
`[]` = trace vue sans appel inline), `pick`, `family`, `route`. Ne pas asserter une route de triage pour
un comportement d'outil (`_derive_route` déduit la route de la famille de triage, ce qui cessera d'être
fidèle après Q05) : asserter sur ces faits.

## Esquisse d'évaluateurs (pour OBS6)

```python
def geo_within_km(*, output: dict, expected_output: dict, **_) -> Evaluation:
    exp = expected_output.get("hotels_within_km")
    hotels = output.get("hotels") or []
    if not exp:
        return Evaluation(name="geo_within_km", value=None, comment="n/a")
    bad = [h["name"] for h in hotels
           if haversine_km(exp["lat"], exp["lon"], h["lat"], h["lon"]) > exp["km"]]
    return Evaluation(name="geo_within_km", value=0 if bad else 1, comment=", ".join(bad) or "ok")
```

Même gabarit pour `min_hotels`/`active_filters_include`/`offers_*` ; les assertions `trace.*` lisent
la trace du run (`langfuse.api`) au lieu d'`output`. Un item ne score que les clés qu'il déclare.

## `b2c-prod-regressions.jsonl` — importé, pas semé

Ce 4e fichier n'a pas de `input.messages` : chaque ligne ne porte que `id`, `source_trace_id`,
`expected_output`, `metadata`. `scripts/langfuse_import_dataset.py` vérifie que la trace existe
encore (jamais d'import silencieux d'une référence morte) et lit le VRAI texte du tour depuis la
trace elle-même — jamais une retranscription à la main qui pourrait diverger. Les 6 cas sont des
tours de prod déjà documentés dans `HANDOFF.md` (garde de l'année hallucinée PR #57, fallback de
cutoff même-jour PR #40/#58) : `metadata.status="regression_guard"` partout, ils doivent rester
verts pour toujours.

```bash
.venv/bin/python scripts/langfuse_import_dataset.py             # vérifie + upsert
.venv/bin/python scripts/langfuse_import_dataset.py --dry-run   # vérifie seulement
```

## Boucle de vie

1. Baseline : run experiment sur les 4 datasets AVANT les fixes P0 (audit §4) — les `target` sont rouges.
2. Chaque fix (P0-1 occupancy, P0-2 géo, P1-1 triage) : re-run, comparaison des `DatasetRun` dans l'UI.
3. Les échecs prod futurs s'ajoutent en items `source_trace_id` (script OBS6 `langfuse_import_dataset.py`),
   jamais en modifiant les items existants (un id = un cas figé).
