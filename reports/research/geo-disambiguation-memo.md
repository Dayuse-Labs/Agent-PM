# Research memo — Multi-candidate, inventory-aware geo resolution for the Dayuse concierge

> Research memo — 2026-07-23. Input for `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md`.
> Scope: Mapbox Geocoding v6 / Search Box capabilities, industry + academic disambiguation practice, GPS/anchor patterns, LLM-agent geo tool design. ~10 web searches, 14 source fetches. Unverified items flagged in §E.

## A. Mapbox capabilities relevant to multi-candidate ranking

### A.1 Geocoding v6 — forward endpoint (`/search/geocode/v6/forward`)

Source: https://docs.mapbox.com/api/search/geocoding/

- **`limit`** — default is already **5**, max **10**. Our current `limit=1` is throwing away candidates the API returns for free; multi-candidate is a parameter change, not a re-architecture.
- **`proximity`** — `longitude,latitude` **or the string `ip`**. A soft **bias** that affects result ordering, never a filter. This is the correct slot for the user's GPS (`native_context.geolocation`), with `proximity=ip` as fallback.
- **`country`** — **hard filter**, ISO 3166 alpha-2, comma-separated. Use only when the user explicitly named/implied a country ("Lisbonne au Portugal"), never from the locale alone — locale should bias, not restrict.
- **`language`** — IETF tag; sets response text language **and affects scoring**: "results matching the query in the requested language preferred over others". Passing the user's locale (`pt` for a pt-PT user typing "Lisboa") directly attacks the Lisboa→Arkansas failure.
- **`bbox`** — hard restrict to `minLon,minLat,maxLon,maxLat`.
- **`worldview`** — one of `ar, cn, in, jp, ma, rs, ru, tr, us`; defaults to `us`; max one per query. Matters for a 29-market product in disputed-boundary regions.
- **`types`** — `country, region, postcode, district, place, locality, neighborhood, street, address`. **v6 dropped POI support entirely** — Mapbox's docs say to use Search Box for POI (https://docs.mapbox.com/help/getting-started/search/). For destination queries, `types=place,locality,neighborhood,district,region` cuts street/address noise.
  - Type semantics: `district` = "smaller than top-level administrative features but typically larger than cities" (US counties, Chinese prefectures) → "Orange County" is a `district`-type feature (not live-verified, see §E). `locality` = official sub-city units (arrondissements in France). `neighborhood` = colloquial sub-city areas without official status — the likely bucket for "La Défense" (not live-verified).
- **`autocomplete`** — default `true`; set `false` for one-shot complete queries (our case: the LLM hands us a full destination string, not keystrokes).

**Ranking/response fields — important limitation:** the v6 response exposes **no numeric relevance or score field** for place-type features. `match_code` + `confidence` (`exact/high/medium/low`) exist **for address-type features only** (Smart Address Match, https://www.mapbox.com/blog/mapbox-geocoding-v6-now-generally-available). Internally, Mapbox orders by textual relevance then breaks ties with a prominence/popularity score ("Paris, France" before "Paris, Texas" — https://docs.mapbox.com/help/dive-deeper/geocoding/), but for city/zone candidates **the only ranking signal returned is list position**. Consequence: the re-ranking must be built from our own signals plus rank position — Mapbox will not hand us a confidence number to threshold on. (The `relevance` numeric field is v5-era: https://docs.mapbox.com/api/search/geocoding-v5/.)

Useful v6 fields per candidate: `feature_type`, `full_address` / `place_formatted` (human-readable disambiguator, ready-made for clarifying questions), `context` (hierarchical country/region/place — ISO country and region codes per candidate for hint matching), `bbox` (use it for the inventory-density ES count), `mapbox_id`.

### A.2 Search Box API — for POIs, zones, and "distance origin"

Source: https://docs.mapbox.com/api/search/search-box/

- Endpoints: `/suggest` + `/retrieve` (session-token billing), **`/forward`** (one-shot, per-request billing — the right shape for a server-side agent), `/category`.
- Types cover **everything v6 covers plus `poi` and `category`** — neighborhoods, districts, localities included. Mapbox's positioning: Geocoding = addresses/places; Search Box = "POIs, categories, brands, street names, neighborhoods, localities, places, districts, postcodes, regions, countries" (https://www.mapbox.com/blog/mapbox-search-box-api-expanded-poi-coverage-smarter-search).
- Same steering params (`limit` up to 10–25, `proximity` incl. `ip`, `country`, `language`, `bbox`, `types`), plus two that matter:
  - **`origin`** — a coordinate from which the API computes a **`distance` field (meters)** per result (and ETA with `navigation_profile`). A first-class "distance origin" concept, *separate from* `proximity` (ranking bias). Directly reusable: `proximity` = GPS bias for ranking; `origin` = whatever anchor we display distances from.
  - `poi_category` / `poi_category_exclusions`.

**Practical implication:** two-tier tool. Tier 1 = Geocoding v6 `/forward` with `types=place,locality,neighborhood,district,region`, `limit≈5-10`. Tier 2 = Search Box `/forward` when (a) v6 returns zero/weak candidates, or (b) the LLM tags the mention as POI/landmark ("Tour Eiffel", "Orange County Convention Center"). Google's docs recommend exactly this split for ambiguous input (https://developers.google.com/maps/documentation/geocoding/best-practices).

## B. Industry & academic disambiguation approaches

**1. Pelias open-source geocoder — explicit deterministic ordering rules** (https://github.com/pelias/sorting). Closest published analogue: 16-level type ordering with population thresholds (very-large city >4M outranks country; mid-size city 5k–500k below region/county…), ties broken by **population**, and — key — for mid-size cities ties are broken by **proximity to `focus.point`** when supplied. Their canonical example is literally our bug: "Lancaster" → Lancaster, CA (most populous) without focus; → Lancaster, England with a UK focus point. Pattern to copy: **proximity re-ranks within a prominence band; it does not let a hamlet beat a capital.**

**2. Airbnb — inventory/booking-density-aware location interpretation.**
- "Location Relevance at Airbnb" (https://medium.com/airbnb-engineering/location-relevance-at-airbnb-12c004247b07): replaced hand-tuned distance-demotion curves with **P(booking location | searched location)** learned from logs, normalized by inventory density.
- "Transforming Location Retrieval at Airbnb" (https://medium.com/airbnb-engineering/transforming-location-retrieval-at-airbnb-a-journey-from-heuristics-to-reinforcement-learning-d33ffc4ddb8f): destination string → retrieval area, evolved from admin boundaries/fixed radii to a model predicting the bbox from **where guests actually booked**. Signal: **your own supply + demand distribution is a legitimate first-class ranking signal for interpreting a destination** — a "Lisboa" with 40 bookable day-use hotels beats a "Lisbon, AR" with zero, regardless of what the geocoder ranked first.

**3. Google Maps Platform — bias vs restrict, locale priors.** `locationBias` vs `locationRestriction` are deliberately distinct (https://developers.google.com/maps/documentation/places/web-service/text-search); `region` (ccTLD) biasing "influences, not fully restricts"; `language` has "a small influence on the set of results and the order" (https://developers.google.com/maps/documentation/geocoding/faq). Their best-practices doc explicitly says the plain geocoder "is not designed to cope with ambiguous queries" — multi-candidate + choice is the sanctioned pattern (https://developers.google.com/maps/documentation/geocoding/best-practices).

**4. Expedia Rapid Typeahead — travel-domain, inventory-aware suggestions.** Dedicated destination-resolution API returning cities/neighborhoods/POIs/airports/properties, "dynamically ranked by relevance" and based on "geographic regions, relevant locations, and available properties" — i.e., inventory-aware; parameters include `language` (BCP47), `type` filters, `region_id` scoping (https://developers.expediagroup.com/rapid/shared-apis/typeahead/typeahead). Travel players do not use a raw geocoder for destinations; they rank against their own supply graph.

**5. Academic toponym resolution — standard heuristic stack** (https://en.wikipedia.org/wiki/Toponym_resolution, Leidner 2007; Gritta et al., https://arxiv.org/abs/1810.12368; recent systematic review https://arxiv.org/abs/2503.18888): (i) **population/prominence prior** as default tie-breaker — known to fail in localized contexts; (ii) **co-occurring toponyms / admin containment** ("Paris, Texas" — for us: country/state hints the LLM extracts); (iii) spatial-context minimality; (iv) learned rankers on top. Our locale/GPS/inventory signals are conversational-commerce instances of (ii) and (iii).

**6. Muroň et al., "User-Driven Toponym Disambiguation Using Dialogue" (J. of Map & Geography Libraries 19(3), 2024** — https://www.tandfonline.com/doi/full/10.1080/15420353.2024.2363212). Purpose-built for chatbots: when ambiguity survives automatic ranking, ask a clarifying question, and choose the question feature by **"equi-population partitioning"** — pick the attribute (typically country/region) whose answer best splits the remaining candidate probability mass, rather than dumping a candidate list. Outperformed alternative question-selection strategies. Full text paywalled — summary from abstract/metadata (§E).

**LLM + geocoding division of labor.** Mapbox's own MCP-server design codifies the pattern: **the LLM extracts location mentions and orchestrates; deterministic geo APIs resolve coordinates** — "LLMs handle reasoning and conversation, while deterministic geospatial APIs provide grounded, real-world data" (https://www.mapbox.com/blog/introducing-the-mapbox-model-context-protocol-mcp-server). Academic parallels: GeoAgent (ACL Findings 2024, https://aclanthology.org/2024.findings-acl.362.pdf) and ReaGeo (https://arxiv.org/abs/2604.21357) — LLM plans/extracts, tools geocode, code ranks. This matches the existing AgentB2C stance (leaf LLM extracts a closed-enum intent, code owns values) and the ≤3-LLM-calls budget: **the ranking layer must be deterministic code, not another LLM call.**

## C. Recommended ranking-signal shortlist for Dayuse

**Call shape (tier 1):** v6 `/forward`, `limit=10`, `autocomplete=false`, `types=place,locality,neighborhood,district,region`, `language=<user locale>`, `proximity=<GPS|ip>`, `worldview=<market>`; `country=` only when the utterance names one. **Tier 2:** Search Box `/forward` for POI-tagged mentions or empty tier-1.

**Deterministic re-rank of the ≤10 candidates** (weights to tune on the eval pack):

1. **Explicit hint match (hard)** — country/region extracted by the leaf LLM vs candidate `context`. A stated country is a filter, not a boost.
2. **Inventory density (near-hard)** — count of bookable Dayuse hotels inside candidate `bbox` (or radius) from our ES. Zero-inventory candidates demoted below any with-inventory candidate; among survivors a strong weight. The Airbnb/Expedia lesson and our biggest structural edge over raw Mapbox — it alone kills Lisbon-AR and Victoria homonyms.
3. **Locale/domain/currency prior (soft)** — candidate country == locale/domain country gets a bounded boost (pt user → PT Lisboa; it user → Milano). Google-style "influence, not restrict".
4. **GPS proximity (soft, band-limited)** — Pelias rule: proximity breaks ties within a prominence band; it must not override an explicit distant destination ("hôtel à New York" typed from Paris). Google local search shows the same convention: a geo-modified query anchors on the named place's centroid, only "near me"-type queries anchor on the device (https://searchengineland.com/guide/google-proximity-bias-in-local-search).
5. **Mapbox rank position + feature-type prior** — position is the only relevance proxy v6 exposes; prefer `place` > `locality`/`neighborhood` > `district` > `region` for hotel destinations.
6. **Decision policy** — top-1 margin over top-2 ≥ threshold → auto-select silently; else ask **one** clarifying question, max 2–3 options, differentiated by the most-discriminating attribute (usually country — equi-partitioning idea), using Mapbox's `place_formatted` strings. Never loop (fits the 1-retry-then-deterministic guard doctrine).
7. **Distance origin, separate from resolution** — keep "which place" (above) independent of "distance shown from what": GPS if user is in the destination city, city/zone centroid otherwise, POI coordinate when a POI anchors the query. Search Box's split of `proximity` (bias) vs `origin` (distance computation) is the API-level template.

## D. Sources

- https://docs.mapbox.com/api/search/geocoding/ · https://docs.mapbox.com/api/search/geocoding-v5/ · https://docs.mapbox.com/api/search/search-box/ · https://docs.mapbox.com/help/dive-deeper/geocoding/ · https://docs.mapbox.com/help/getting-started/search/ · https://docs.mapbox.com/api/search/changelog/
- https://www.mapbox.com/blog/mapbox-geocoding-v6-now-generally-available · https://www.mapbox.com/blog/geocoding-v6 · https://www.mapbox.com/blog/mapbox-search-box-api-expanded-poi-coverage-smarter-search · https://www.mapbox.com/blog/introducing-the-mapbox-model-context-protocol-mcp-server · https://www.mapbox.com/blog/geoai-in-2026-four-predictions-on-agents-mcp-and-live-data
- https://github.com/pelias/sorting
- https://medium.com/airbnb-engineering/location-relevance-at-airbnb-12c004247b07 · https://medium.com/airbnb-engineering/transforming-location-retrieval-at-airbnb-a-journey-from-heuristics-to-reinforcement-learning-d33ffc4ddb8f
- https://developers.google.com/maps/documentation/geocoding/best-practices · https://developers.google.com/maps/documentation/geocoding/faq · https://developers.google.com/maps/documentation/places/web-service/text-search · https://developers.google.com/maps/documentation/places/web-service/place-autocomplete
- https://developers.expediagroup.com/rapid/shared-apis/typeahead/typeahead
- https://www.tandfonline.com/doi/full/10.1080/15420353.2024.2363212
- https://en.wikipedia.org/wiki/Toponym_resolution · https://arxiv.org/abs/1810.12368 · https://arxiv.org/abs/2503.18888 · https://aclanthology.org/2024.findings-acl.362.pdf · https://arxiv.org/abs/2604.21357
- https://searchengineland.com/guide/google-proximity-bias-in-local-search

## E. Not verified / caveats

1. **No live Mapbox probes** this session: "La Défense" resolving as v6 `neighborhood` vs requiring Search Box, and "Orange County" returning as `district`, are inferred from documented type definitions, not tested. Worth 15 minutes of curl with the leaf's token before freezing the tier-1/tier-2 boundary.
2. **v6 exposes no numeric relevance for place candidates** — verified against the v6 response-object docs; the "relevance + score" description on the help page appears to describe v5-era behavior. Re-confirm on a live response.
3. Booking.com's named-entity post was unreachable (server down, archive blocked); only search-snippet-level detail, no verifiable disambiguation signals.
4. The dialogue-disambiguation paper is paywalled; equi-population partitioning summarized from abstract/publisher metadata only.
5. Pelias thresholds quoted from the repo README (repo may evolve).
