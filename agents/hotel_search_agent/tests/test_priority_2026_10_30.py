"""What the user puts first orders each ring of distance (2026-10-30).

Prod after #175: « le moins cher » left the cheapest card 3rd to 5th
(Amsterdam « pas cher »: Ibis Stopera at 90 € third; Charleroi « le moins cher
possible, ≤ 50 km »: 68 € fourth; Melbourne « the cheapest »: fifth). The
leaf's model reads the priority (`priority` on search_offers); the code orders
by price inside each ring, the ring itself staying first.
"""
from __future__ import annotations

from types import SimpleNamespace

from hotel_search_agent.geo_rank import prioritize_cards, rank_pool
from hotel_search_agent.relaxation import read_relax_request
from hotel_search_agent.response_bridge import STATE_PRIORITY_KEY

AMSTERDAM = (52.3728, 4.8936)


def _hotel(hotel_id: int, km_east: float, euros: int, score: float) -> dict:
    return {"hotelId": hotel_id, "lat": AMSTERDAM[0], "lon": AMSTERDAM[1] + km_east / 67.8, "score": score,
            "offers": [{"priceEuro": euros * 100, "priceEuroWithBookingFees": euros * 100}]}


# The Amsterdam page of C091 (centre, 0.3-3.1 km), plus a cheap hotel 20 km out.
POOL = [_hotel(1, 0.3, 115, 1.0), _hotel(2, 1.1, 149, 0.95), _hotel(3, 1.0, 90, 0.9),
        _hotel(4, 0.3, 130, 0.85), _hotel(5, 3.1, 109, 0.8), _hotel(6, 20.0, 49, 1.2)]


def test_the_cheapest_comes_first_inside_the_local_ring():
    ranked = rank_pool(POOL, *AMSTERDAM, 5.0, 2.0, "price")
    assert [h["hotelId"] for h in ranked] == [3, 5, 1, 4, 2, 6]


def test_a_cheaper_hotel_far_out_never_jumps_the_ring():
    ranked = rank_pool(POOL, *AMSTERDAM, 5.0, 2.0, "price")
    assert ranked[-1]["hotelId"] == 6


def test_without_a_priority_the_order_is_unchanged():
    assert rank_pool(POOL, *AMSTERDAM, 5.0, 2.0) == rank_pool(POOL, *AMSTERDAM, 5.0, 2.0, None)
    assert rank_pool(POOL, *AMSTERDAM, 5.0, 2.0)[0]["hotelId"] != 3


def _cards() -> list[dict]:
    # Charleroi « le moins cher possible, ≤ 50 km » (C060), searched on 50 km.
    return [{"name": "ibis Styles Airport", "distance_km": 6.9, "price_eur_cents": 7500},
            {"name": "Novotel Centre", "distance_km": 0.5, "price_eur_cents": 9400},
            {"name": "Van Der Valk Airport", "distance_km": 6.2, "price_eur_cents": 10100},
            {"name": "Le Manoir De Morimont", "distance_km": 29.5, "price_eur_cents": 6800},
            {"name": "Van Der Valk Nivelles", "distance_km": 21.9, "price_eur_cents": 10100}]


def test_a_search_on_a_ring_the_user_gave_puts_the_cheapest_first():
    ctx = SimpleNamespace(state={STATE_PRIORITY_KEY: "price"})
    cards = prioritize_cards(ctx, _cards(), 50.0)
    assert cards[0]["name"] == "Le Manoir De Morimont"
    assert [c["price_eur_cents"] for c in cards] == sorted(c["price_eur_cents"] for c in cards)


def test_no_priority_keeps_the_cards_as_they_are():
    assert prioritize_cards(SimpleNamespace(state={}), _cards(), 50.0) == _cards()


def test_the_priority_is_read_for_search_offers_and_never_sent():
    ctx = SimpleNamespace(state={}, user_content=None)
    args = {"lat": 1.0, "lon": 2.0, "priority": "price"}
    read_relax_request(SimpleNamespace(name="search_offers"), args, ctx)
    assert "priority" not in args and ctx.state[STATE_PRIORITY_KEY] == "price"
    named = {"name": "Zelos", "priority": "price"}
    read_relax_request(SimpleNamespace(name="find_hotel_by_name"), named, ctx)
    assert "priority" not in named
