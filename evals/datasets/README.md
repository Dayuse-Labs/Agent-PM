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

**Niveau trace** (`expected_output.trace`) — nécessite la trace Langfuse du run (args réels des tools,
route de triage). À brancher en évaluateur second temps (OBS6/OBS7) ; le réflexe consigné au HANDOFF :
*« la trace d'abord, la `date` envoyée d'abord »* — ici généralisé à `adults`/`children`/route géo.

| Clé | Sémantique |
|---|---|
| `search_offers_args_include {…}` | sous-ensemble des args réellement envoyés au MCP |
| `search_offers_args_absent [..]` | args qui ne doivent PAS être envoyés (non-invention) |
| `expected_route` | `search_refinement` / `ack` / `faq` / `booking_confirmed` / `not_booking_confirmed` |
| `expected_pick {pick, pick_position}` | slot PICKS du triage |

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
