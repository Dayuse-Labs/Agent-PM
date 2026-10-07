from types import SimpleNamespace
import inspect
from hotel_search_agent.geo_resolver import rank_landmark
from hotel_search_agent.mapbox_client import GeocodeCandidate
from hotel_search_agent import mcp_guard
from hotel_search_agent.resilience import CircuitBreaker


def place(name, kind="poi", categories=()):
    args = dict(
        latitude=48.87,
        longitude=2.78,
        name=name,
        place_name=name,
        place_formatted="France",
        feature_type=kind,
        country_code="FR",
        region="Ile-de-France",
        bbox=None,
        rank=0,
    )
    if "poi_categories" in inspect.signature(GeocodeCandidate).parameters:
        args["poi_categories"] = categories
    return GeocodeCandidate(**args)


def select(candidates, name, kind):
    kw = dict(requested_zone=name, inventory=SimpleNamespace(count_near=lambda *a, **k: 100))
    if "location_kind" in inspect.signature(rank_landmark).parameters:
        kw["location_kind"] = kind
    return rank_landmark(candidates, **kw)


def test_theme_park_not_taxi_named_after_park():
    taxi = place("Taxi Disneyland Paris", categories=("taxi", "transportation"))
    assert select([taxi], "Disneyland", "landmark") is None


def test_district_not_storage_business():
    storage = place("Homebox Rennes Sud", categories=("storage", "services"))
    assert select([storage], "Rennes Sud", "area") is None


def test_business_homonym_not_administrative_area():
    restaurant = place("La Défense", categories=("restaurant",))
    sculpture = place("La Défense", categories=("public_artwork",))
    assert select([restaurant, sculpture], "La Défense", "area") is None


def test_circuit_recovers_despite_rejected_local_traffic(monkeypatch):
    clock = [0.0]
    breaker = CircuitBreaker(3, 30, clock=lambda: clock[0])
    monkeypatch.setattr(mcp_guard, "breaker", breaker)
    tool = SimpleNamespace(name="search_offers")
    for _ in range(3):
        mcp_guard.mcp_circuit_after_tool(tool, {}, None, {"isError": True})
    clock[0] = 29
    rejected = mcp_guard.mcp_circuit_before_tool(tool, {}, None)
    assert rejected is not None
    mcp_guard.mcp_circuit_after_tool(tool, {}, None, rejected)
    clock[0] = 31
    assert mcp_guard.mcp_circuit_before_tool(tool, {}, None) is None
