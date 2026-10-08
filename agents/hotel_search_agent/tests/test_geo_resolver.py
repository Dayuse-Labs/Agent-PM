"""geo_resolver — the deterministic, inventory-aware ranker (S-G3).

Every audit geo-failure case is a NAMED test here (Milano, Lisboa-pt, Victoria,
Lisbon-Arkansas-demoted, GPS-does-not-override-a-distant-destination), plus the
policy invariants (hard country/region filter, near-hard inventory tier,
band-limited proximity, clarify-once). Inventory is injected synthetically so
every assertion is deterministic and independent of the shipped snapshot.
"""
from __future__ import annotations

from hotel_search_agent import geo_resolver
from hotel_search_agent.mapbox_client import GeocodeCandidate


def cand(
    name: str,
    cc: str,
    region: str,
    *,
    ftype: str = "place",
    rank: int = 0,
    lat: float = 0.0,
    lon: float = 0.0,
    place_formatted: str | None = None,
) -> GeocodeCandidate:
    return GeocodeCandidate(
        latitude=lat,
        longitude=lon,
        name=name,
        place_name=f"{name}, {region}, {cc}",
        place_formatted=place_formatted or f"{region}, {cc}",
        feature_type=ftype,
        country_code=cc,
        region=region,
        bbox=None,
        rank=rank,
    )


class FakeInventory:
    """count_near keyed on the candidate's latitude (each candidate gets a
    distinct lat in these tests) — radius is irrelevant to the fake."""

    def __init__(self, by_lat: dict[float, int]):
        self._by_lat = by_lat

    def count_near(self, lat: float, lon: float, *, radius_km: float = 25.0) -> int:
        return self._by_lat.get(round(lat, 4), 0)


# ── Named audit failure cases ───────────────────────────────────────────────────
def test_milano_resolves_to_milan_italy_not_texas():
    milan = cand("Milano", "IT", "Milan", lat=45.46, rank=0)
    texas = cand("Milano", "US", "Texas", lat=30.71, rank=2)
    inv = FakeInventory({45.46: 40, 30.71: 0})
    res = geo_resolver.resolve([milan, texas], inventory=inv)
    assert res.decision == "select"
    assert res.chosen is milan


def test_lisboa_pt_beats_us_homonyms_with_locale_prior():
    lisbon_pt = cand("Lisbon", "PT", "Lisboa", lat=38.72, rank=0)
    lisbon_me = cand("Lisbon", "US", "Maine", lat=44.03, rank=1)
    lisbon_oh = cand("Lisbon", "US", "Ohio", lat=40.77, rank=2)
    inv = FakeInventory({38.72: 26, 44.03: 0, 40.77: 0})
    res = geo_resolver.resolve([lisbon_pt, lisbon_me, lisbon_oh], inventory=inv, locale_country="PT")
    assert res.decision == "select"
    assert res.chosen is lisbon_pt


def test_lisbon_arkansas_is_demoted_below_portugal_even_when_mapbox_ranks_it_first():
    # Adversarial: the geocoder puts the zero-inventory US homonym at rank 0.
    # The inventory tier must still lift Portugal above it.
    lisbon_ar = cand("Lisbon", "US", "Arkansas", lat=34.80, rank=0)
    lisbon_pt = cand("Lisbon", "PT", "Lisboa", lat=38.72, rank=1)
    inv = FakeInventory({34.80: 0, 38.72: 26})
    res = geo_resolver.resolve([lisbon_ar, lisbon_pt], inventory=inv)
    assert res.decision == "select"
    assert res.chosen is lisbon_pt


def test_gps_proximity_does_not_override_a_distant_explicit_destination():
    # "hotel in New York" typed from Paris: the near-Paris zero-inventory homonym
    # must NOT win just because the device is in Paris (Pelias band rule).
    nyc = cand("New York", "US", "New York", lat=40.71, lon=-74.0, rank=0)
    paris_homonym = cand("New York", "FR", "Île-de-France", lat=48.86, lon=2.35, rank=1)
    inv = FakeInventory({40.71: 50, 48.86: 0})
    res = geo_resolver.resolve([nyc, paris_homonym], inventory=inv, proximity=(48.85, 2.35))
    assert res.decision == "select"
    assert res.chosen is nyc


def test_victoria_bc_selected_via_explicit_region_hint():
    bc = cand("Victoria", "CA", "British Columbia", lat=48.43, rank=0)
    au = cand("Victoria", "AU", "Victoria", ftype="region", lat=-37.0, rank=1)
    sey = cand("Victoria", "SC", "Saint Louis", lat=-4.62, rank=2)
    inv = FakeInventory({48.43: 5, -37.0: 30, -4.62: 0})
    res = geo_resolver.resolve([bc, au, sey], inventory=inv, region_hint="British Columbia")
    assert res.decision == "select"
    assert res.chosen is bc


def test_budapest_hungary_is_not_silently_lost_to_a_one_hotel_georgia_homonym():
    # S-G9 gate re-run (3/3 reproducible): Budapest HU (place, Mapbox rank 0,
    # zero snapshot inventory — Hungary isn't a market) silently lost to
    # Budapest, Georgia US (locality, rank 1, ONE snapshot hotel: the Quality
    # Inn & Suites Bremen ~7 km away) and a US hotel was served for "Budapest
    # near Keleti station". A micro-inventory homonym must never win the tier:
    # both fall in the same tier, and the cross-country near-tie asks ONE question.
    hu = cand("Budapest", "HU", "Budapest", ftype="place", rank=0, lat=47.4979)
    ga = cand("Budapest", "US", "Georgia", ftype="locality", rank=1, lat=33.7151)
    inv = FakeInventory({47.4979: 0, 33.7151: 1})
    res = geo_resolver.resolve([hu, ga], inventory=inv)
    assert res.decision == "clarify"
    assert hu in res.options and ga in res.options


def test_la_defense_shape_micro_inventory_fuzz_does_not_silently_win():
    # S-G9's second wrong-country: "La Défense" → 'Defense, Al Ain, Abu Dhabi'
    # (neighborhood, rank 2, ONE hotel near Al Aïn) silently beat every
    # zero-inventory candidate via the 0-vs-1 tier. With the tier minimum it
    # competes on score instead — anything but a silent AE select.
    co = cand("La Defensa", "CO", "Vichada", ftype="locality", rank=0, lat=5.5787)
    ae = cand("Defense", "AE", "Abu Dhabi", ftype="neighborhood", rank=2, lat=23.6391)
    inv = FakeInventory({5.5787: 0, 23.6391: 1})
    res = geo_resolver.resolve([co, ae], inventory=inv)
    assert not (res.decision == "select" and res.chosen is ae)
    assert res.decision == "clarify"


def test_exact_name_match_is_not_asked_about_a_differently_named_place():
    # S-G10: "Fort Lauderdale" typed exactly must never trigger "did you mean
    # Lauderdale, Minnesota?" — a same-tier near-tie whose name does NOT match
    # what the user typed is not a genuine alternative when the top's name does.
    fl = cand("Fort Lauderdale", "US", "Florida", lat=26.12, rank=0)
    mn = cand("Lauderdale", "US", "Minnesota", lat=44.99, rank=1)
    inv = FakeInventory({26.12: 20, 44.99: 5})
    res = geo_resolver.resolve([fl, mn], inventory=inv, requested_name="Fort Lauderdale")
    assert res.decision == "select"
    assert res.chosen is fl


def test_two_exact_name_homonyms_still_clarify():
    # The exact-name rule is asymmetric: it trims differently-named options,
    # never a true homonym — Budapest HU vs Budapest GA still asks.
    hu = cand("Budapest", "HU", "Budapest", ftype="place", rank=0, lat=47.4979)
    ga = cand("Budapest", "US", "Georgia", ftype="locality", rank=1, lat=33.7151)
    inv = FakeInventory({47.4979: 0, 33.7151: 1})
    res = geo_resolver.resolve([hu, ga], inventory=inv, requested_name="Budapest")
    assert res.decision == "clarify"


def test_non_exact_top_never_suppresses_alternatives():
    # A fuzzy top ("La Defensa" for "La Défense") keeps the clarify — the rule
    # only fires when the TOP is an exact match for what was typed.
    co = cand("La Defensa", "CO", "Vichada", ftype="locality", rank=0, lat=5.5787)
    ae = cand("Defense", "AE", "Abu Dhabi", ftype="neighborhood", rank=2, lat=23.6391)
    inv = FakeInventory({5.5787: 0, 23.6391: 1})
    res = geo_resolver.resolve([co, ae], inventory=inv, requested_name="La Défense")
    assert res.decision == "clarify"


# ── Hard filters ────────────────────────────────────────────────────────────────
def test_explicit_country_is_a_hard_filter_not_a_boost():
    lisbon_pt = cand("Lisbon", "PT", "Lisboa", lat=38.72, rank=0)
    lisbon_us = cand("Lisbon", "US", "Maine", lat=44.03, rank=1)
    inv = FakeInventory({38.72: 26, 44.03: 0})
    res = geo_resolver.resolve([lisbon_pt, lisbon_us], inventory=inv, country_hint="PT")
    assert res.decision == "select" and res.chosen is lisbon_pt


def test_country_hint_matching_nothing_resolves_none_never_wrong_country():
    lisbon_us = cand("Lisbon", "US", "Maine", lat=44.03, rank=0)
    inv = FakeInventory({44.03: 0})
    res = geo_resolver.resolve([lisbon_us], inventory=inv, country_hint="PT")
    assert res.decision == "none"
    assert res.chosen is None


def test_region_hint_that_matches_nothing_does_not_zero_out():
    # A hint expressed differently from Mapbox's context must not wipe candidates.
    milan = cand("Milano", "IT", "Milan", lat=45.46, rank=0)
    inv = FakeInventory({45.46: 40})
    res = geo_resolver.resolve([milan], inventory=inv, region_hint="Lombardia")
    assert res.decision == "select" and res.chosen is milan


# ── Inventory tier & proximity band ───────────────────────────────────────────────
def test_with_inventory_candidate_beats_zero_inventory_regardless_of_type():
    # A zero-inventory `place` must lose to a with-inventory `district`.
    empty_place = cand("Somewhere", "US", "Nowhere", ftype="place", lat=10.0, rank=0)
    real_district = cand("Orange County", "US", "California", ftype="district", lat=33.7, rank=1)
    inv = FakeInventory({10.0: 0, 33.7: 12})
    res = geo_resolver.resolve([empty_place, real_district], inventory=inv)
    assert res.decision == "select" and res.chosen is real_district


def test_proximity_is_band_limited_never_crosses_a_feature_type_band():
    prominent = cand("Metropolis", "US", "State", ftype="place", lat=0.0, lon=0.0, rank=0)
    minor = cand("Metropolis", "US", "State", ftype="neighborhood", lat=1.0, lon=1.0, rank=1)
    inv = FakeInventory({0.0: 0, 1.0: 0})  # same (empty) tier — only type/rank/proximity decide
    res = geo_resolver.resolve([prominent, minor], inventory=inv, proximity=(1.0, 1.0))
    # Proximity favours `minor`, but it cannot cross the place > neighborhood band.
    assert res.decision == "select" and res.chosen is prominent


# ── Decision policy: clarify-once ────────────────────────────────────────────────
def test_two_inventory_cities_same_type_different_countries_triggers_clarify():
    bc = cand("Victoria", "CA", "British Columbia", lat=48.43, rank=0)
    tx = cand("Victoria", "US", "Texas", lat=28.80, rank=1)
    inv = FakeInventory({48.43: 20, 28.80: 15})
    res = geo_resolver.resolve([bc, tx], inventory=inv)
    assert res.decision == "clarify"
    assert bc in res.options and tx in res.options
    assert res.question and "Victoria" in res.question


def test_clarify_question_lists_the_country_context():
    bc = cand("Victoria", "CA", "British Columbia", lat=48.43, rank=0)
    tx = cand("Victoria", "US", "Texas", lat=28.80, rank=1)
    inv = FakeInventory({48.43: 20, 28.80: 15})
    res = geo_resolver.resolve([bc, tx], inventory=inv)
    assert "British Columbia" in res.question and "Texas" in res.question


def test_clarify_question_is_localized_fr():
    # S-CX2 (audit F5): the clarify question can reach the customer verbatim —
    # a French conversation gets a French question, options unchanged.
    bc = cand("Victoria", "CA", "British Columbia", lat=48.43, rank=0)
    tx = cand("Victoria", "US", "Texas", lat=28.80, rank=1)
    inv = FakeInventory({48.43: 20, 28.80: 15})
    res = geo_resolver.resolve([bc, tx], inventory=inv, language="fr")
    assert res.decision == "clarify"
    assert "lequel vouliez-vous dire" in res.question
    assert "British Columbia" in res.question and "Texas" in res.question


def test_clarify_question_is_localized_es():
    # UX2 (2026-08-27): widened from fr/en to the 7 languages the concierge
    # can now answer in.
    bc = cand("Victoria", "CA", "British Columbia", lat=48.43, rank=0)
    tx = cand("Victoria", "US", "Texas", lat=28.80, rank=1)
    inv = FakeInventory({48.43: 20, 28.80: 15})
    res = geo_resolver.resolve([bc, tx], inventory=inv, language="es")
    assert res.decision == "clarify"
    assert "cuál querías decir" in res.question
    assert "British Columbia" in res.question and "Texas" in res.question


def test_clarify_question_unrecognized_language_falls_back_to_english():
    bc = cand("Victoria", "CA", "British Columbia", lat=48.43, rank=0)
    tx = cand("Victoria", "US", "Texas", lat=28.80, rank=1)
    inv = FakeInventory({48.43: 20, 28.80: 15})
    res = geo_resolver.resolve([bc, tx], inventory=inv, language="ja")
    assert "which did you mean" in res.question


def test_city_needed_question_is_localized_nl():
    assert geo_resolver.city_needed_question("gare de lyon", "nl") == (
        'In de buurt van "gare de lyon" — in welke stad zoek je?'
    )


def test_adjacent_near_duplicate_is_not_asked_about():
    # "New York" vs "West New York, NJ" (~8 km): a suburb sharing the same search
    # area is not a genuine alternative — select the top, never ask.
    nyc = cand("New York", "US", "New York", lat=40.7128, lon=-74.0060, rank=0)
    west_ny = cand("West New York", "US", "New Jersey", lat=40.7879, lon=-74.0143, rank=1)
    inv = FakeInventory({40.7128: 50, 40.7879: 45})
    res = geo_resolver.resolve([nyc, west_ny], inventory=inv)
    assert res.decision == "select"
    assert res.chosen is nyc


def test_same_country_same_region_near_tie_is_not_asked_about():
    # A city vs its own province ("Milano" place vs "Milano" region) is not a
    # user-visible ambiguity — select the top, never ask.
    milan_city = cand("Milano", "IT", "Milan", ftype="place", lat=45.46, rank=0)
    milan_region = cand("Milano", "IT", "Milan", ftype="region", lat=45.50, rank=1)
    inv = FakeInventory({45.46: 40, 45.50: 40})
    res = geo_resolver.resolve([milan_city, milan_region], inventory=inv)
    assert res.decision == "select"


# ── Degenerate inputs ─────────────────────────────────────────────────────────────
def test_no_candidates_resolves_none():
    res = geo_resolver.resolve([], inventory=FakeInventory({}))
    assert res.decision == "none" and res.chosen is None


def test_single_candidate_is_selected():
    only = cand("Reims", "FR", "Grand Est", lat=49.25, rank=0)
    res = geo_resolver.resolve([only], inventory=FakeInventory({49.25: 3}))
    assert res.decision == "select" and res.chosen is only


class TestRankLandmark:
    """`rank_landmark` — the tier-2 (Search Box) ranker, 2026-08-26.

    It exists because Mapbox's top-1 for `/search/searchbox/v1/forward` is
    biased by the CALLER'S EGRESS IP (documented: "if not provided, the default
    is IP proximity"). Trusting it made the leaf's landmark resolution a
    function of which datacenter the container ran in — prod resolved "autour
    des champs élysées" to a shop of that name in Toulon, 830 km away, while the
    same arguments from a laptop returned Paris. Every case below is a real
    candidate list observed live, not a synthetic one.
    """

    def test_selects_only_never_asks(self):
        # `resolve` clarifies between two cities because that is a real
        # question. "Did you mean Azur Café or Unisex?" is not.
        a = cand("Champs-Élysées", "FR", "IdF", ftype="neighborhood", lat=1.0)
        b = cand("Azur Café", "FR", "IdF", ftype="poi", lat=2.0, rank=1)
        got = geo_resolver.rank_landmark(
            [a, b], requested_zone="champs élysées", inventory=FakeInventory({1.0: 700, 2.0: 700})
        )
        assert got is a

    def test_no_candidates_is_none(self):
        assert geo_resolver.rank_landmark(
            [], requested_zone="champs élysées", inventory=FakeInventory({})
        ) is None

    def test_a_leading_article_does_not_hand_the_exact_match_to_a_homonym(self):
        # Live failure: querying "les champs élysées" made "Les Champs Elysées",
        # a venue in Le Havre 200 km away, an EXACT name match while the real
        # "Champs Élysées" district was not one — so the homonym won the bonus.
        havre = cand("Les Champs Elysées", "FR", "Normandie", ftype="poi", lat=49.49, rank=6)
        paris = cand("Champs Élysées", "FR", "IdF", ftype="neighborhood", lat=48.87, rank=8)
        got = geo_resolver.rank_landmark(
            [havre, paris],
            requested_zone="les champs élysées",
            inventory=FakeInventory({49.49: 16, 48.87: 785}),
        )
        assert got is paris

    def test_punctuation_does_not_deny_the_exact_match(self):
        # "Champs-Élysées" folds to "champs-elysees", which is NOT the string
        # "champs elysees" — comparing folded STRINGS gave the bonus to a
        # same-named district in Évry 27 km out, which then won on feature type.
        evry = cand("Champs Élysées", "FR", "Essonne", ftype="neighborhood",
                    lat=48.64, lon=2.43, rank=8)
        paris = cand("Champs-Élysées", "FR", "IdF", ftype="poi", lat=48.87, lon=2.30, rank=7)
        got = geo_resolver.rank_landmark(
            [evry, paris],
            requested_zone="les champs élysées",
            inventory=FakeInventory({48.64: 314, 48.87: 783}),
            city_anchor=(48.869, 2.304),
        )
        assert got is paris

    def test_a_verified_city_anchor_outweighs_a_better_feature_type(self):
        # The whole point of `city_anchor`: within a city the user NAMED, 27 km
        # is not a near-tie, it is the wrong place. `_W_PROXIMITY`'s 25-500 km
        # band (kept for GPS) scored these two within 0.002 of each other.
        far = cand("Champs Élysées", "FR", "Essonne", ftype="neighborhood",
                   lat=48.64, lon=2.43, rank=0)
        near = cand("Champs-Élysées", "FR", "IdF", ftype="poi", lat=48.87, lon=2.30, rank=5)
        got = geo_resolver.rank_landmark(
            [far, near],
            requested_zone="champs élysées",
            inventory=FakeInventory({48.64: 314, 48.87: 783}),
            city_anchor=(48.869, 2.304),
        )
        assert got is near

    def test_zero_inventory_candidate_is_demoted_hard(self):
        empty = cand("Champs Élysées", "FR", "Aisne", ftype="neighborhood", lat=49.85)
        real = cand("Champs Elysees", "FR", "IdF", ftype="poi", lat=48.87, rank=3)
        got = geo_resolver.rank_landmark(
            [empty, real],
            requested_zone="champs élysées",
            inventory=FakeInventory({49.85: 0, 48.87: 780}),
        )
        assert got is real

    def test_a_whole_city_loses_to_the_named_district(self):
        # `_LANDMARK_TYPE_PRIOR` inverts `_TYPE_PRIOR` on purpose: resolving a
        # landmark to its city silently widens the search to the whole metro.
        city = cand("Paris", "FR", "IdF", ftype="place", lat=48.86)
        district = cand("Montmartre", "FR", "IdF", ftype="neighborhood", lat=48.88, rank=1)
        got = geo_resolver.rank_landmark(
            [city, district],
            requested_zone="montmartre",
            inventory=FakeInventory({48.86: 783, 48.88: 783}),
        )
        assert got is district

    def test_a_long_official_name_is_not_demoted_below_a_worse_placed_candidate(self):
        # "JFK" -> "John F. Kennedy International Airport" is 5 words the user
        # never typed; the bloat penalty is capped so verbosity alone cannot
        # lose to a nearer-phrased but worse candidate.
        airport = cand("John F. Kennedy International Airport", "US", "NY", ftype="poi", lat=40.64)
        decoy = cand("JFK", "US", "TX", ftype="poi", lat=32.0, rank=1)
        got = geo_resolver.rank_landmark(
            [airport, decoy],
            requested_zone="JFK",
            inventory=FakeInventory({40.64: 227, 32.0: 0}),
        )
        assert got is airport

    def test_a_business_named_after_the_landmark_loses_the_label_to_a_clean_feature(self):
        # Both are geographically fine; `resolved_place` reaches the customer
        # through active_filters.distance_origin, so the clean one must win.
        shop = cand("Onitsuka Tiger Champs Elysées, Paris Flagship", "FR", "IdF",
                    ftype="poi", lat=48.871)
        clean = cand("Champs-Élysées", "FR", "IdF", ftype="poi", lat=48.870, rank=7)
        got = geo_resolver.rank_landmark(
            [shop, clean],
            requested_zone="les champs élysées",
            inventory=FakeInventory({48.871: 784, 48.870: 783}),
        )
        assert got is clean


def test_city_is_not_replaced_by_same_name_locality_with_more_inventory():
    city = cand("Pescara", "IT", "Pescara", lat=42.47, lon=14.20)
    hamlet = cand("Pescara", "IT", "Perugia", lat=43.02, lon=12.41,
                  ftype="locality", rank=4)
    result = geo_resolver.resolve([city, hamlet], requested_name="Pescara", prefer_municipality=True,
                                  inventory=FakeInventory({42.47: 1, 43.02: 10}))
    assert result.chosen is city


def test_explicit_region_can_select_a_same_name_locality():
    city = cand("Pescara", "IT", "Pescara", lat=42.47)
    hamlet = cand("Pescara", "IT", "Perugia", lat=43.02, ftype="locality", rank=4)
    result = geo_resolver.resolve([city, hamlet], requested_name="Pescara", prefer_municipality=True, region_hint="Perugia",
                                  inventory=FakeInventory({42.47: 10, 43.02: 1}))
    assert result.chosen is hamlet


def test_municipality_homonyms_still_clarify():
    a = cand("Davenport", "US", "Florida", lat=28.16, lon=-81.60)
    b = cand("Davenport", "US", "Iowa", lat=41.52, lon=-90.57, rank=1)
    result = geo_resolver.resolve([a, b], requested_name="Davenport",
                                  inventory=FakeInventory({28.16: 5, 41.52: 5}))
    assert result.decision == "clarify"


def test_city_is_not_replaced_by_inventory_rich_fuzzy_locality():
    city = cand("Pescara", "IT", "Pescara", lat=42.47, lon=14.20)
    fuzzy = cand("Pescaia", "IT", "Arezzo", lat=43.30, lon=11.81, ftype="locality", rank=7)
    result = geo_resolver.resolve([city, fuzzy], requested_name="Pescara", prefer_municipality=True,
                                  inventory=FakeInventory({42.47: 1, 43.30: 10}))
    assert result.chosen is city


def test_landmark_query_retains_locality_candidates():
    city = cand("Pescara", "IT", "Pescara", lat=42.47)
    hamlet = cand("Pescara", "IT", "Perugia", lat=43.02, ftype="locality")
    result = geo_resolver.resolve([city, hamlet], requested_name="Pescara",
                                  inventory=FakeInventory({42.47: 1, 43.02: 10}))
    assert result.chosen is hamlet


def test_better_ranked_borough_survives_a_municipality_homonym():
    # Brooklyn NY is a locality; Brooklyn MD is a place. A municipality
    # preference cannot erase the geocoder's leading borough candidate.
    ny = cand("Brooklyn", "US", "New York", lat=40.65, lon=-73.95, ftype="locality", rank=0)
    md = cand("Brooklyn", "US", "Maryland", lat=39.23, lon=-76.60, rank=1)
    result = geo_resolver.resolve([ny, md], requested_name="Brooklyn", prefer_municipality=True,
                                  inventory=FakeInventory({40.65: 30, 39.23: 30}))
    assert result.decision == "clarify"
    assert set(c.region for c in result.options) == {"New York", "Maryland"}


def test_exact_municipality_identity_precedes_fuzzy_city_inventory():
    # Actual v49 receipt: Mapbox returns three Valence places, then Talence.
    # Talence's larger inventory made it win, then the echo guard rejected it,
    # leaving the conversation stuck despite valid Valence candidates.
    valence = cand("Valence", "FR", "Drôme", lat=44.9329, lon=4.8914, rank=0)
    homonym = cand("Valence", "FR", "Tarn-et-Garonne", lat=44.1086, lon=0.8907, rank=1)
    fuzzy = cand("Talence", "FR", "Gironde", lat=44.8125, lon=-0.5907, rank=3)
    result = geo_resolver.resolve([valence, homonym, fuzzy],
        inventory=FakeInventory({44.9329: 1, 44.1086: 0, 44.8125: 30}),
        requested_name="Valence", prefer_municipality=True, country_hint="FR")
    assert fuzzy not in [s.candidate for s in result.scored]
    assert result.chosen in (None, valence, homonym)


def test_inventory_cannot_silently_replace_leading_exact_homonym():
    first = cand("Valence", "FR", "Drôme", lat=44.9329, lon=4.8914, rank=0)
    inventory_winner = cand("Valence", "FR", "Tarn-et-Garonne", lat=44.1086, lon=0.8907, rank=1)
    result = geo_resolver.resolve([first, inventory_winner],
        inventory=FakeInventory({44.9329: 0, 44.1086: 5}),
        requested_name="Valence", prefer_municipality=True, country_hint="FR")
    assert result.decision == "clarify"
    assert result.options == [first, inventory_winner]
