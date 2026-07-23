"""build_active_filters (facade.py) — golden-contract test for S-G1's schema
de-nulling. `active_filters` is a value INSIDE the `/v3/chat` response, not
the top-level contract shape (CONTRACT_KEYS) — this only locks that the
inner dict now surfaces real profile values instead of hardcoded nulls, and
that CONTRACT_KEYS itself is untouched by this change."""
from __future__ import annotations

from b2c_concierge.facade import CONTRACT_KEYS, build_active_filters
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
            }
        )
