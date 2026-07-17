"""Contract envelope tests (DataPart payloads) — S2 pins the envelope only,
business fields inside the dicts follow S4/S5."""
from faq_agent.contract import FaqRequest, FaqResponse


class TestFaqRequest:
    def test_defaults_are_empty(self):
        request = FaqRequest()
        assert request.query_params == {}
        assert request.profile_in == {}

    def test_round_trip(self):
        request = FaqRequest(
            query_params={"question": "conditions d'annulation"},
            profile_in={"language": "fr"},
        )
        assert FaqRequest.model_validate(request.model_dump()) == request


class TestFaqResponse:
    def test_defaults_are_empty(self):
        response = FaqResponse()
        assert response.results == []
        assert response.profile_delta == {}
        assert response.diagnostics == {}

    def test_round_trip(self):
        response = FaqResponse(
            results=[{"topic": "cancellation", "conditions": "…"}],
            profile_delta={"language": "fr"},
            diagnostics={"tool_called": "get_faq_conditions"},
        )
        assert FaqResponse.model_validate(response.model_dump()) == response
