# AUDIT AGENTIQUE — 2026-07-30

**Demande (Fabien)** : deux défauts observés sur AgentB2C en local — (1) « hôtels autour des Champs-Élysées » résout un autre point que le POI parisien ; (2) « 2 adultes et 1 enfant » n'est pas pris en compte dans les résultats. Auditer le code des agents, inventorier les regex/matchings en dur, proposer une expérience plus agentique (sans correspondances en dur), et livrer des datasets Langfuse pour tester ces cas.

**Livrables de cette session** : ce document + `evals/datasets/*.jsonl` (3 nouvelles familles) + `scripts/langfuse_seed_datasets.py` + `evals/datasets/README.md`. Aucun changement de code agent (zone OBS2/OBS4 en parallèle).

---

## 1. Bug POI — « Champs-Élysées » résout ailleurs

### La chaîne telle qu'elle est

Le concierge envoie `query_params={}` (`b2c_concierge/agent.py:323`) : **toute l'extraction est faite par le LLM de la feuille** via les déclarations d'outils. Le modèle extrait `{city, zone, metro, country_code}` « from THIS message » (instruction, `hotel_search_agent/agent.py:143-151`) et appelle `geocode_location`, 100 % code ensuite :

```
demote_generic_city → [early return si ni city ni metro] → state/ZIP hints
  → Mapbox v6 geocode_candidates (types SANS poi) → geo_resolver (tier inventaire + scores)
  → echo guard → [fallback Search Box si zone nommée OU zéro candidat v6] → echo guard
```

### Les 4 mécanismes de l'échec

**M1 — Un landmark est invisible au tier-1.** v6 est interrogé avec `types=place,locality,neighborhood,district,region` (`mapbox_client.py:35`) — **pas de `poi`** (v6 ne les supporte plus, probé 2026-07-23). « Champs-Élysées » n'est donc au mieux que du fuzz v6 (homonymes partiels : le précédent consigné HANDOFF L960 — « gare de lyon » → *La Garde (Lyon)*, *Gary (Illinois)*, *Gare (Rueil-Malmaison)*).

**M2 — L'extraction `zone`-only est un dead-end.** Si le modèle classe correctement « champs élysées » en `zone` avec `city` vide, `geocode_tool.py:200-228` retourne `no_geocodable_location` **avant** le tier-2 Search Box (le bloc Search Box, `:343-371`, est en aval du early-return). Le seul chemin qui atteint Search Box sur ce message est `city="champs élysées"` + zéro candidat v6 (`:344-345`). L'issue dépend donc de **où le modèle a rangé la string** — c'est le non-déterminisme observé (HANDOFF : Fabien tombe sur Paris, le replay sur La Garde).

**M3 — Le tier-2 Search Box n'est pas scopé.** `forward(searchbox_query, country=effective_country_code, language=lang)` (`geocode_tool.py:350-352`) : `country` n'est rempli que si l'utilisateur a nommé un pays ou tapé un ZIP US ; **ni `proximity` (le client GPS/`search_anchor` n'est pas transmis à Search Box, alors que le client l'accepte, `searchbox_client.py:45-53`), ni le prior locale (`_LOCALE_COUNTRY`, appliqué uniquement au resolver tier-1 `geo_resolver.py:137-138`)**. Un POI homonyme mondial (commerce nommé « Champs Elysées » n'importe où) est renvoyé limit=1…

**M4 — …et l'écho ne peut pas l'attraper.** `geocode_echo_matches` valide que le NOM demandé est écho­yé (`geo_guards.py:317-389`, règle du token le plus long). Un business « Champs Elysées » à Abidjan ou Montréal écho­ye parfaitement « champs élysées » : **le nom est bon, le lieu est faux**. L'écho a été conçu pour le mis-resolve de nom, pas pour l'homonymie géographique — seul un signal pays/proximité la lève.

### Le paradoxe agentique

Le modèle SAIT que « champs élysées » ⇒ Paris/FR (connaissance du monde), mais l'instruction le lui interdit : `country_code` doit être « extracted from THIS message » et « never geocode a destination yourself ». La doctrine anti-hallucination (juste : ne jamais laisser le LLM émettre des **coordonnées**) a été étendue jusqu'à interdire au LLM d'émettre un **indice** vérifiable. Résultat : le pipeline se prive du seul signal qui désambiguïse à coup sûr, puis tente de le reconstituer en code (tier inventaire, exonymes, écho…) — c'est exactement la mécanique « regex en dur qui court après les cas ».

La littérature converge sur le partage inverse : le LLM fournit le **contexte** (pays probable, type de lieu, référence indirecte — il excelle sur « the Austrian capital », « Beantown »), le géocodeur fournit les **coordonnées**, le code **vérifie** (l'écho, l'inventaire). LLM-géocodeur seul = hallucinations (GDELT) ; géocodeur seul = désambiguïsation aveugle. Voir sources §6.

---

## 2. Bug occupancy — « 2 adultes, 1 enfant » ignoré

**Le MCP est prêt, la chaîne agent est vide.** Vérifié live 2026-07-30 sur le MCP connecté : `search_offers` accepte `adults`/`children` (« minimum adult/children capacity the offer must accommodate ») et filtre correctement (probe lat 48.8698 / lon 2.3078, `adults=2, children=1` → 3 hôtels, toutes les offres `capacity ≥ 2` et `childrenCapacity ≥ 1`, champs présents par offre).

Côté agents, `adults`/`children` n'apparaissent **nulle part** :

| Maillon | État | Référence |
|---|---|---|
| Instruction feuille | Muette sur l'occupancy (budget, timeSlot, date, amenities : tous cadrés ; occupancy : rien) | `hotel_search_agent/agent.py:135-210` |
| Déclaration `search_offers` | Les params existent dans le schéma MCP mais sans description par champ ni consigne — le modèle ne les émet pas spontanément (gpt-4o-mini) | schéma MCP + `equipment_ids.py:116-141` (le pattern d'enrichissement existe pour `amenities`) |
| Profil session | Aucun champ (v2.0) → même émis une fois, perdu au tour suivant (feuille stateless, `include_contents="none"`) | `profile.py:152-213` |
| Carryover before_tool | `inject_profile_geo_context` réinjecte city/zone/GPS/locale ; rien pour l'occupancy | `geocode_tool.py:401-456` |
| Restitution | `capacity` affiché sur la carte seulement ; `active_filters`, ground-truth block et synthèse ignorent l'occupancy → aucune divulgation ni vérification | `inline_tools.py:519-521` |

C'est le cas d'école du fix « agentique » à pattern constant : la maison sait déjà faire exactement ça pour `amenities` (déclaration virtuelle enrichie + enforcement code) et pour `date` (label LLM + résolution code + carryover profil). L'occupancy demande le même triptyque — **aucune regex nécessaire**.

---

## 3. Inventaire regex / matching en dur

Grep complet `agents/ + libs/` (hors tests). Trois catégories — **le problème n'est pas « il y a des regex », c'est « des regex font de la compréhension de langage sur le chemin primaire »**.

### A. Légitimes (validation de formats / guards de sortie) — à garder

| Où | Rôle |
|---|---|
| `facade.py:58,562-564` | Formats session_id / locale / devise / domaine (validation d'entrée) |
| `link_guard.py:33-34,81-82` | Guard n°13 : URLs de la synthèse vs shortlist (vérification de FAITS post-LLM) |
| `datetime_resolver.py:182-183,439,466` | Parse de **labels structurés** émis par le LLM (ISO, MM-DD, PT1H, HH:MM) — pas du langage |
| `hotel_urls.py:88`, `agent.py:255` (concierge) | Slug d'URL ; découpage de tokens pour le streaming |
| `amenity_guard.py` | Guard n°7 : vérifie les CLAIMS de la synthèse contre la fiche hôtel (post-LLM, garder) |

### B. Fallbacks de secours (design assumé, OK) — à garder mais à mesurer

`triage.py:65-103` : `_ACK_RE` (fast-path zéro LLM), `_FR_HINTS`, `_FAQ/_COMPARE/_DETAILS/_BOOKING/_PICK_CHEAPEST_RE` — **uniquement** quand le classify LLM échoue (timeout/JSON invalide). C'est le bon pattern (LLM primaire, regex = chemin de secours instantané). Action : exposer le taux `used_llm=False` dans Langfuse — si > quelques %, c'est le LLM qu'on répare, pas la regex qu'on enrichit.

### C. Compréhension de langage sur le chemin PRIMAIRE — la dette à résorber

| Où | Ce que la regex « comprend » | Fragilité |
|---|---|---|
| `profile.py:116-120` `_AFFIRMATIVE_RE` | « oui, fais ça » (relance après 0 résultat) | fr/en only — « vale », « va bene », « passt », « claro » ne matchent pas (29 marchés) |
| `profile.py:137-148` `_CONFIRMATION_RE`+`_NEGATION_RE` | Confirmation de réservation (gate R9, guard n°12) | verbes fr/en durs ; la négation par liste de mots est un piège sans fin (« finalement non… enfin si ») |
| `profile.py:321-347` `_BARE_NUMBER_RE` + devise/unité | « 180 » = budget | ne sait pas distinguer « 180 » budget de « 180 » autre chose hors contexte étroit |
| `profile.py:383-696` `_CLOCK/_TIME/_DATE_MENTION`, `_REFINEMENT_KEYWORDS`, `_MORE_OPTIONS_RE` | « ce message est-il un raffinement / demande d'autres options / mention de date-heure » | listes de mots-clés fr/en ; chaque nouveau phrasé = un patch |
| `profile.py:794-1094` `_FINAL_QUESTION_RE`, `_NAME_STOPWORDS`, `_BARE_ORDINAL_RE` | question finale, référence ordinale (« la deuxième ») | le pick par position existe DÉJÀ dans le contrat triage LLM (`PICKS`) — doublon regex |
| `inline_tools.py:100-112` | Extraction du nom d'hôtel en pelant les tournures (« book », « tell me more about ») | anglais/français figés ; « je veux le Hilton » vs « peux-tu me dire si le Hilton… » |
| `geo_guards.py:61-85,167-191,254-314` | États US texte-unsafe, mots génériques (« gare » y est, « gare de lyon » n'y est pas — matching token exact `:194-202`), **30 paires d'exonymes à la main** (Wien/Vienna…), mots de bruit d'écho | le gazetteer maison : chaque incident prod ajoute une entrée ; ne couvrira jamais 29 marchés × locales |
| `geo_guards.py:438-494` ZIP scoring | « ce nombre est-il un ZIP ? » (+30/+60/−70…) | heuristique US-only à poids magiques |
| `amenity_synonyms.py` | Table de synonymes amenities 7 langues | acceptable en guard post-LLM (cat. A), mais même logique : table à entretenir |

**La doctrine maison dit déjà la solution** — `triage.py:53-57` : « The LLM UNDERSTANDS the phrasing (…) — Fabien, 2026-07-20 : don't push determinism into language understanding ; the CODE owns what it resolves to, from a closed enum validated here ». Le pattern `PICKS` (enum fermé + resolver code) est la cible : il n'a simplement pas encore été appliqué aux slots de la table C.

---

## 4. Recommandations

Invariants respectés : ≤ 3 appels LLM/tour (rien ci-dessous n'ajoute d'appel : on enrichit des appels existants), guards déterministes conservés (on remplace la **compréhension** regex, jamais la **vérification** code), LiteLLM only, feuilles stateless.

### P0 — Quick wins (pattern existant, zéro nouvelle archi)

**P0-1. Occupancy de bout en bout** (bug 2, fix complet) :
- Profil : `adults: int | None`, `children: int | None` (`SessionProfile` + `to_dict` + `leaf_profile_view`).
- Feuille : 2 lignes d'instruction (« pass adults/children ONLY when the user states party size ; a child's age is not a count ») + enrichir la déclaration `search_offers` avec descriptions par champ (même mécanique que `inject_amenities_declaration`) + carryover before_tool depuis `profile_in` quand le modèle omet (même mécanique que la date).
- Restitution : `active_filters.adults/children`, divulgation dans la synthèse (« pour 2 adultes et 1 enfant »), ground-truth block.
- Tests : régression sur émission, carryover multi-tours, et non-invention (jamais d'occupancy non déclarée).

**P0-2. Géo — trois corrections chirurgicales** (bug 1) :
- **Zone-only atteint le tier-2** : quand `city` est vide mais `zone` nommée, tenter Search Box AVANT le `no_geocodable_location` (`geocode_tool.py:200-228`) — Gate 3 (jamais remplacer un landmark nommé par le GPS) inchangée.
- **Scoper Search Box** : passer `proximity` (le `search_anchor` déjà injecté) et un `country` de repli = `country_guess` LLM (ci-dessous) sinon prior locale (`_LOCALE_COUNTRY`) — aujourd'hui le fallback POI est mondial et aveugle (M3).
- **`country_guess` : autoriser l'indice de connaissance du monde du modèle**, en SOFT. Nouveau param de `geocode_location` distinct de `country_code` (qui reste le pays NOMMÉ, filtre dur) : « the ISO country this place is world-famously in, if you know it ». Consommé comme le prior locale (poids borné dans `geo_resolver`, jamais un filtre) + comme scope du fallback Search Box. L'écho + l'inventaire restent les vérificateurs. C'est le renversement clef : *le LLM propose, le code dispose* — au lieu d'interdire l'info et de la réinventer en tables d'exonymes.
- Bonus : `zone_is_landmark: bool` extrait par le modèle (« autour de X » où X est un lieu, pas une ville) pour router directement vers le bon tier au lieu de le déduire de quel champ est vide.

**P0-3. Mesure** : compter dans Langfuse le chemin géo emprunté (tier1/tier2/clarify/no_match + echo_reject) et le taux de fallback regex triage — les datasets livrés (§5) donnent la baseline.

### P1 — Consolider la compréhension dans les appels LLM existants

**P1-1. Étendre le contrat JSON du triage** (1 appel éco déjà payé) avec les slots aujourd'hui regex-primaires de `profile.py` : `affirmative: bool`, `booking_confirmation: "confirm"|"refuse"|"change"|"none"` (le gate R9 et l'exigence de flag restent en CODE — seule la SOURCE du signal change), `wants_more_options: bool`, `bare_budget_value: number|null`, `hotel_name: string|null` (remplace les phrase-strippers d'`inline_tools`). Chaque slot : enum/type fermé, validé, avec la regex actuelle **rétrogradée en fallback** (statut identique à `fallback_family`). Les ~150 tests de guards restent verts : on change l'extracteur, pas le gate.

**P1-2. Langues au-delà de fr/en** : le classify détecte déjà la langue ; élargir l'enum (es/it/de/pt/nl) au moins pour les templates et `_AFFIRMATIVE`-équivalents supprime la classe entière « le regex fr/en ne matche pas » — décision produit à trancher (HANDOFF S-G7 la liste déjà comme chantier à part).

### P2 — Structurel : le géocodage inventory-aware Dayuse

**`resolve_location` comme tool MCP_B2C backé par l'index `poi` existant** (alias `POI_INDEX`, aujourd'hui non câblé — HANDOFF L134). L'index porte `name_<locale>` + analyzers autocomplete : il connaît « champs élysées », « gare de lyon », « sagrada familia » dans les locales des 29 marchés, ET il est le seul géocodeur naturellement pondéré par NOTRE inventaire (le tier `_MIN_TIER_INVENTORY` du resolver approxime ça à coups de `count_near`). Cible : tier-1 = POI Dayuse, Mapbox = repli pour le hors-inventaire, guards écho inchangés. C'est une demande cross-repo (à verser dans `reports/MCP-B2C-REQUESTS.md`) et la suite logique de « durcissement géo massif = décision produit » (HANDOFF S13).

### Ce qu'on ne fait PAS

Supprimer les guards déterministes (écho, budget explicit-never-widen, link guard, R9, anti-boucle) : ils vérifient des faits, pas du langage, chacun est adossé à un incident prod, et la recherche comme l'expérience maison (année hallucinée du 29/07 !) confirment qu'un LLM non vérifié re-produira ces fautes. « Plus agentique » = déplacer la compréhension vers le LLM avec des contrats structurés — pas retirer les ceintures.

---

## 5. Datasets Langfuse livrés

3 nouvelles familles (les 8 familles evalset n'ont ni geo-POI ni occupancy), format aligné sur `phases/OBS6-datasets-experiments.md` : `input = {"messages": [...], "profile": {...}}` (pattern N+1 : historique jusqu'au tour à rejouer), `expected_output` = assertions déterministes, `metadata.family/locale/bug_ref`. Items à id déterministe (ré-import = upsert, jamais de doublon).

| Fichier | Dataset hébergé | Contenu |
|---|---|---|
| `evals/datasets/b2c-geo-poi.jsonl` | `b2c/geo-poi` | POI parisiens (champs élysées ×3 formes, tour eiffel, gare de lyon…), POI internationaux, homonymes → clarify attendu, génériques (« près de la gare »), zone-only, multi-tours avec carryover |
| `evals/datasets/b2c-occupancy.jsonl` | `b2c/occupancy` | Tailles de groupe fr/en, enfant + âge, persistance multi-tours (« moins cher » garde 2A+1E), non-invention, capacité vs childrenCapacity |
| `evals/datasets/b2c-language-robustness.jsonl` | `b2c/language-robustness` | Les cas que les regex primaires ratent : affirmatifs es/it/de/pt, typos, code-switching, emoji, ordinaux |

Import : `scripts/langfuse_seed_datasets.py` (SDK 4.14.1 déjà pinné, env `LANGFUSE_*`), voir `evals/datasets/README.md` (assertions → évaluateurs Python OBS6, `run_experiment`/`Evaluation`).

**Usage prévu** : baseline AVANT les fixes P0 (les items `metadata.status="target"` échouent aujourd'hui — c'est le but), re-run après chaque fix, comparaison des `DatasetRun` dans l'UI. La boucle « échec prod → trace → item `source_trace_id` » (OBS6 §3) complètera ces familles semées à la main.

## 6. Sources

- Anthropic — [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents) (les descriptions de tools/params sont le contrat ; de petites précisions de description → gros gains) ; [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).
- Toponymes & LLM : [Coordinates from Context (arXiv 2510.08741)](https://arxiv.org/pdf/2510.08741) — LLM fort sur les références indirectes ; [Scalable Toponym Resolution with LLMs (CEUR-WS)](https://ceur-ws.org/Vol-3969/paper6.pdf) et [survey geocoding/toponym resolution](https://www.researchgate.net/publication/381324415_A_survey_on_geocoding_algorithms_and_datasets_for_toponym_resolution) — le pattern gagnant = NER/contexte LLM + module géocodage + gazetteer candidats (RAG) ; [GDELT — Why LLM-based geocoders struggle](https://blog.gdeltproject.org/generative-ai-experiments-why-llm-based-geocoders-struggle/) — jamais de coordonnées LLM directes ; [Element 84 — Natural Language Geocoding](https://element84.com/machine-learning/introducing-natural-language-geocoding-v0-1-0-an-llm-enabled-geocoding-database/) — hybride LLM+base géo.
- Langfuse — datasets & experiments : `create_dataset(input_schema=)`, `create_dataset_item(id=, source_trace_id=)`, `run_experiment(evaluators=)` (docs officielles via MCP, 2026-07).
- Interne : `PLAN-REWORK-AGENT-USA.md`, `AUDIT-REWORK-2026-07.md`, HANDOFF (addenda S-G3/S-G9/S-G10/S-G11, L960 gare de lyon), `phases/OBS6-datasets-experiments.md`.
