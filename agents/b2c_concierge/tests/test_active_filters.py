"""build_active_filters (facade.py) — golden-contract test for S-G1's schema
de-nulling. `active_filters` is a value INSIDE the `/v3/chat` response, not
the top-level contract shape (CONTRACT_KEYS) — this only locks that the
inner dict now surfaces real profile values instead of hardcoded nulls, and
that CONTRACT_KEYS itself is untouched by this change."""
from __future__ import annotations

from b2c_concierge.facade import (
    CONTRACT_KEYS,
    build_active_filters,
    build_chat_payload,
    build_hotel_picks,
)
from b2c_concierge.profile import SessionProfile


class TestBuildActiveFiltersV2:
    def test_empty_profile_still_yields_all_keys_as_none_or_empty(self):
        filters = build_active_filters(SessionProfile())
        assert filters["named_hotel"] is None
        assert filters["date"] is None
        assert filters["date_reference"] is None
        assert filters["zone"] is None
        assert filters["currency"] is None
        assert filters["distance_origin"] is None
        assert filters["amenities"] == []
        assert filters["client_timezone"] is None

    def test_populated_profile_surfaces_the_new_slots_instead_of_faking_null(self):
        profile = SessionProfile(
            city="Miami",
            zone="Fort Lauderdale",
            currency="EUR",
            distance_origin={"latitude": 48.9, "longitude": 2.2, "label": "here", "type": "gps"},
            named_hotel={"hotel_id": 1, "name": "Villa Paris Orly", "source": "shortlist"},
            date="2026-07-24",
            date_reference={"expression": "demain", "resolved_from": "2026-07-23", "client_tz": "Europe/Paris"},
            client_timezone="Europe/Paris",
        )
        filters = build_active_filters(profile)
        assert filters["named_hotel"] == {"hotel_id": 1, "name": "Villa Paris Orly", "source": "shortlist"}
        assert filters["date"] == "2026-07-24"
        assert filters["date_reference"]["expression"] == "demain"
        assert filters["zone"] == "Fort Lauderdale"
        assert filters["currency"] == "EUR"
        assert filters["distance_origin"] == {
            "latitude": 48.9, "longitude": 2.2, "label": "here", "type": "gps",
        }
        assert filters["client_timezone"] == "Europe/Paris"

    def test_pre_existing_keys_are_unchanged(self):
        profile = SessionProfile(city="Paris", state_anchor="IDF", budget_max=150.0, amenities=["pool"])
        filters = build_active_filters(profile)
        assert filters["city"] == "Paris"
        assert filters["resolved_city"] == "Paris"
        assert filters["state"] == "IDF"
        assert filters["budget_max"] == 150.0
        assert filters["amenities"] == ["pool"]


class TestOccupancyDisclosure:
    """P0-1: the party size the search filtered on must be visible in the
    response. Measured at 0% before this — the leaf was sending adults/children
    to MCP while the response disclosed nothing, so neither a user nor an eval
    could tell whether the occupancy had been honoured."""

    def test_occupancy_is_surfaced_when_the_profile_has_it(self):
        filters = build_active_filters(SessionProfile(city="Paris", adults=2, children=1))
        assert filters["adults"] == 2
        assert filters["children"] == 1

    def test_children_zero_is_disclosed_not_hidden(self):
        # "adults only" is a real filter; None and 0 must stay distinguishable.
        filters = build_active_filters(SessionProfile(city="Paris", adults=2, children=0))
        assert filters["children"] == 0

    def test_unstated_occupancy_is_null_never_defaulted_to_one(self):
        filters = build_active_filters(SessionProfile(city="Paris"))
        assert filters["adults"] is None
        assert filters["children"] is None


class TestContractKeysUntouched:
    def test_contract_keys_shape_is_the_documented_frozenset(self):
        # Iso-contract invariant: active_filters growing internally must never
        # change the top-level /v3/chat response shape.
        assert CONTRACT_KEYS == frozenset(
            {
                "message", "response", "context", "hotels", "suggestions",
                "session_id", "conversation_id", "response_language", "state",
                "ready_to_search", "requires_clarification", "profile_status",
                "active_filters", "market", "market_country",
                "entry_market_country", "search_country", "turn_id",
                # S-CX5 (2026-07-27): the pick buttons and the offer card.
                # `booking_card` is the key agent-usa already emits and the
                # vendored widget already renders — adopting its name is what
                # makes the card work with zero frontend change.
                "hotel_picks", "booking_card",
            }
        )


class TestHotelPicks:
    """S-CX5: the pick buttons. Both product rules live in the backend — WHEN
    they may appear (the request must be qualified enough) and IN WHICH ORDER
    (cheapest first) — so the widget renders a list, not a policy."""

    SHOWN = [
        {"hotel_id": 1, "name": "Mercure La Défense", "price": "€87.00", "price_eur_cents": 8700},
        {"hotel_id": 2, "name": "Drawing House", "price": "€81.00", "price_eur_cents": 8100},
        {"hotel_id": 3, "name": "Pullman Bercy", "price": "€112.00", "price_eur_cents": 11200},
    ]

    def test_sorted_cheapest_first(self):
        profile = SessionProfile(city="Paris", date="2026-07-28", last_results=self.SHOWN)
        picks = build_hotel_picks(profile)
        assert [p["name"] for p in picks] == [
            "Drawing House", "Mercure La Défense", "Pullman Bercy",
        ]
        assert picks[0]["price"] == "€81.00"

    def test_picks_appear_without_a_date_once_the_destination_is_resolved(self):
        """Fabien 2026-07-28: the date defaults to today at search AND at the
        booking quote, so a date-less shortlist is bookable — the pick row
        must not wait for an explicit date."""
        picks = build_hotel_picks(SessionProfile(city="Paris", last_results=self.SHOWN))
        assert [p["name"] for p in picks] == [
            "Drawing House", "Mercure La Défense", "Pullman Bercy",
        ]

    def test_no_picks_without_a_destination(self):
        assert build_hotel_picks(SessionProfile(date="2026-07-28", last_results=self.SHOWN)) == []

    def test_no_picks_without_a_shortlist(self):
        assert build_hotel_picks(SessionProfile(city="Paris", date="2026-07-28")) == []

    def test_unpriced_entries_sort_last_but_stay_pickable(self):
        shown = [{"hotel_id": 9, "name": "No price"}, *self.SHOWN]
        picks = build_hotel_picks(
            SessionProfile(city="Paris", date="2026-07-28", last_results=shown)
        )
        assert [p["name"] for p in picks][-1] == "No price"
        assert len(picks) == 4

    def test_the_payload_carries_picks_and_a_null_card_by_default(self):
        profile = SessionProfile(city="Paris", date="2026-07-28", last_results=self.SHOWN)
        payload = build_chat_payload(
            session_id="s", final_text="hi", hotels=None, profile=profile,
            language="fr", turn_id="t",
        )
        assert [p["hotel_id"] for p in payload["hotel_picks"]] == [2, 1, 3]
        assert payload["booking_card"] is None

    def test_the_payload_carries_the_booking_card_when_one_was_authorized(self):
        card = {"hotel_id": 2, "hotel_name": "Drawing House", "url": "https://dayuse.fr/tunnel/x"}
        payload = build_chat_payload(
            session_id="s", final_text="hi", hotels=None, profile=SessionProfile(),
            language="fr", turn_id="t", booking_card=card,
        )
        assert payload["booking_card"] == card


class TestSeeAllSearchPage:
    """mcp-dayuse#5: the site's search page for the search that ran rides
    `market` — the widget's « Voir tout » opens it instead of the country page."""

    PAGE = {"name": "Lyon", "url": "https://www.dayuse.fr/s/france/auvergne-rhone-alpes/rhone/lyon?checkinDate=2026-10-07"}

    def test_the_page_rides_the_market_object(self):
        payload = build_chat_payload(
            session_id="s", final_text="hi", hotels=[{"id": 1, "name": "H", "country_code": "FR"}],
            profile=SessionProfile(city="Lyon", search_page=self.PAGE), language="fr", turn_id="t",
        )
        assert payload["market"] == {"country_code": "FR", "search_page": self.PAGE}

    def test_no_page_leaves_the_market_object_as_before(self):
        payload = build_chat_payload(
            session_id="s", final_text="hi", hotels=[{"id": 1, "name": "H", "country_code": "FR"}],
            profile=SessionProfile(city="Lyon"), language="fr", turn_id="t",
        )
        assert payload["market"] == {"country_code": "FR"}
