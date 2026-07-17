"""Routing table + leaf endpoints + inline stubs — all code-owned, all pinned."""
from b2c_concierge import inline_tools
from b2c_concierge.routing import (
    LEAF_ENDPOINTS,
    LEAF_FAQ,
    LEAF_HOTEL_SEARCH,
    ROUTES,
    bearer_token,
    card_url,
)


class TestRoutingTable:
    def test_search_and_faq_go_to_the_two_leaves(self):
        assert ROUTES["search"].kind == "leaf"
        assert ROUTES["search"].target == LEAF_HOTEL_SEARCH
        assert ROUTES["faq"].kind == "leaf"
        assert ROUTES["faq"].target == LEAF_FAQ

    def test_details_compare_booking_are_inline_stubs(self):
        for family, tool in (
            ("details", "get_hotel_details"),
            ("compare", "compare_hotels"),
            ("booking", "generate_booking_link"),
        ):
            assert ROUTES[family].kind == "inline"
            assert ROUTES[family].target == tool
            assert tool in inline_tools.STUBS

    def test_ack_is_a_template(self):
        assert ROUTES["ack"].kind == "template"


class TestLeafEndpoints:
    def test_local_default_card_urls(self, monkeypatch):
        monkeypatch.delenv("HOTEL_SEARCH_CARD_URL", raising=False)
        monkeypatch.delenv("FAQ_AGENT_CARD_URL", raising=False)
        assert card_url(LEAF_HOTEL_SEARCH) == "http://localhost:8101/.well-known/agent-card.json"
        assert card_url(LEAF_FAQ) == "http://localhost:8102/.well-known/agent-card.json"

    def test_card_url_env_override(self, monkeypatch):
        monkeypatch.setenv(
            "HOTEL_SEARCH_CARD_URL",
            "http://hotel-search-agent.railway.internal:8101/.well-known/agent-card.json",
        )
        assert "railway.internal" in card_url(LEAF_HOTEL_SEARCH)

    def test_bearer_tokens_are_per_leaf_and_stripped(self, monkeypatch):
        monkeypatch.setenv("HOTEL_SEARCH_A2A_TOKEN", " tok-search \n")
        monkeypatch.setenv("FAQ_AGENT_A2A_TOKEN", "tok-faq")
        assert bearer_token(LEAF_HOTEL_SEARCH) == "tok-search"
        assert bearer_token(LEAF_FAQ) == "tok-faq"

    def test_bearer_token_defaults_to_empty(self, monkeypatch):
        monkeypatch.delenv("HOTEL_SEARCH_A2A_TOKEN", raising=False)
        assert bearer_token(LEAF_HOTEL_SEARCH) == ""

    def test_every_leaf_route_has_an_endpoint(self):
        leaf_targets = {r.target for r in ROUTES.values() if r.kind == "leaf"}
        assert leaf_targets == set(LEAF_ENDPOINTS)


class TestInlineStubs:
    def test_stubs_return_deterministic_no_op_payloads(self):
        for name, stub in inline_tools.STUBS.items():
            payload = stub()
            assert payload["tool"] == name
            assert payload["status"] == "stub_s2"
            assert payload["results"] == []

    def test_booking_link_stub_never_emits_a_link(self):
        # R9 posture: no confirmation flag machinery exists yet, so the stub
        # must be structurally unable to hand out a booking link.
        payload = inline_tools.generate_booking_link("offer-42")
        assert "url" not in payload
        assert "link" not in payload
        assert payload["results"] == []
