"""Contract envelope tests (DataPart payloads) — S1 pins the envelope only,
business fields inside the dicts are S4/S5 scope."""
from hotel_search_agent.contract import SearchRequest, SearchResponse


class TestSearchRequest:
    def test_defaults_are_empty(self):
        request = SearchRequest()
        assert request.query_params == {}
        assert request.profile_in == {}

    def test_round_trip(self):
        request = SearchRequest(
            query_params={"destination": "paris", "date": "2026-07-20"},
            profile_in={"language": "en"},
        )
        assert SearchRequest.model_validate(request.model_dump()) == request


class TestSearchResponse:
    def test_defaults_are_empty(self):
        response = SearchResponse()
        assert response.results == []
        assert response.profile_delta == {}
        assert response.diagnostics == {}

    def test_round_trip(self):
        response = SearchResponse(
            results=[{"hotel_id": 42, "offer": "day-use"}],
            profile_delta={"preferred_city": "paris"},
            diagnostics={"tool_called": "search_offers"},
        )
        assert SearchResponse.model_validate(response.model_dump()) == response
