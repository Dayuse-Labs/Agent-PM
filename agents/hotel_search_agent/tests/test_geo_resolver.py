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
