"""Display currency (2026-09-25): EUR by default, the hotel's own currency on
request — kept for the conversation — and any other currency answered with the
two available choices. Nothing is ever converted: the leaf sends both prices."""
from __future__ import annotations

import asyncio
import copy

import pytest
from google.adk.runners import InMemoryRunner

import b2c_concierge.agent as agent_module

from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.display_currency import (
    HOTEL,
    apply_hotel_currency,
    noted_message,
    resolve_currency_request,
    unsupported_currency_message,
)

from .test_spine_profile import FakeLeg, _new_session, _run_turn, _scripted_llm

HK_CARD = {
    "id": 1,
    "name": "Hotel Harbour",
    "price": "€95.00",
    "price_eur_cents": 9500,
    "hotel_price": "HKD 780.00",
    "hotel_price_minor": 78000,
    "hotel_currency_code": "HKD",
    "currency_code": "HKD",
    "timeslots": [
        {"start": "10:00", "end": "17:00", "original_price": 200.0, "hotel_original_price": 1600.0}
    ],
}
SHORTLIST_HK = [{"hotel_id": 1, "name": "Hotel Harbour", "hotel_currency_code": "HKD"}]


class TestResolveCurrencyRequest:
    def test_no_request(self):
        assert resolve_currency_request(None, SHORTLIST_HK).kind == "none"

    def test_euros_and_hotel_currency(self):
        assert resolve_currency_request("EUR", SHORTLIST_HK).mode is None
        assert resolve_currency_request("HOTEL", SHORTLIST_HK).mode == HOTEL

    def test_naming_the_hotels_own_currency_is_asking_for_it(self):
        decision = resolve_currency_request("HKD", SHORTLIST_HK)
        assert (decision.kind, decision.mode) == ("set", HOTEL)

    def test_any_other_currency_is_unsupported(self):
        decision = resolve_currency_request("USD", SHORTLIST_HK)
        assert decision.kind == "unsupported"
        assert decision.hotel_currencies == ("HKD",)


class TestApplyHotelCurrency:
    def test_switches_price_and_night_rate_to_the_hotel_currency(self):
        cards = [copy.deepcopy(HK_CARD)]
        apply_hotel_currency(cards)
        card = cards[0]
        assert card["price"] == "HKD 780.00"
        assert (card["display_currency"], card["display_price_minor"]) == ("HKD", 78000)
        assert card["timeslots"][0]["original_price"] == 1600.0
        assert card["price_eur_cents"] == 9500  # budget logic stays in EUR

    def test_drops_a_eur_night_rate_that_has_no_hotel_currency_twin(self):
        card = copy.deepcopy(HK_CARD)
        del card["timeslots"][0]["hotel_original_price"]
        apply_hotel_currency([card])
        assert "original_price" not in card["timeslots"][0]

    def test_a_card_without_hotel_price_keeps_its_eur_price(self):
        card = {"name": "X", "price": "€95.00"}
        apply_hotel_currency([card])
        assert card == {"name": "X", "price": "€95.00"}


class TestMessages:
    def test_unsupported_names_both_choices(self):
        message = unsupported_currency_message(resolve_currency_request("USD", SHORTLIST_HK), "fr")
        assert "USD" in message and "euros" in message and "HKD" in message

    def test_unsupported_without_hotels_on_screen(self):
        message = unsupported_currency_message(resolve_currency_request("USD", None), "en")
        assert "each hotel's local currency" in message

    def test_unsupported_when_the_hotels_already_charge_in_euros(self):
        decision = resolve_currency_request(
            "USD", [{"hotel_id": 1, "name": "Paris", "hotel_currency_code": "EUR"}]
        )
        assert "already in their own currency" in unsupported_currency_message(decision, "en")

    def test_every_language_has_every_message(self):
        for language in ("fr", "en", "es", "it", "de", "pt", "nl"):
            for decision in (
                resolve_currency_request("USD", SHORTLIST_HK),
                resolve_currency_request("USD", None),
            ):
                assert "USD" in unsupported_currency_message(decision, language)
            assert noted_message(HOTEL, language) and noted_message(None, language)


@pytest.fixture
def fake_leg(monkeypatch):
    leg = FakeLeg()
    monkeypatch.setattr(agent_module, "_get_leg", lambda leaf: leg)
    return leg


class TestThroughTheSpine:
    def test_asking_for_the_hotel_currency_repaints_the_cards(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            "Voici un hôtel.",
            '{"family": "details", "language": "fr", "display_currency": "HOTEL"}',
            "Voici les prix en dollars de Hong Kong.",
        )
        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)], "profile_delta": {"city": "Hong Kong"}}
        _run_turn(runner, session.id, "un hôtel à Hong Kong demain")
        assert fake_leg.call_count == 1

        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)]}
        _run_turn(runner, session.id, "affiche les prix dans la devise de l'hôtel")

        assert fake_leg.call_count == 2  # the same search, repainted
        outgoing = find_datapart(fake_leg.seen_outgoing_parts)
        assert outgoing["query_params"] == {"repeat_previous_search": True}
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.display_currency == HOTEL
        assert stored.last_results[0]["price"] == "HKD 780.00"
        synthesis_prompt = llm.calls[-1]["messages"][1]["content"]
        assert "HKD 780.00" in synthesis_prompt
        assert "CURRENCY" not in synthesis_prompt  # no "EUR, no conversion" disclosure

    def test_another_currency_gets_the_two_choices_without_any_search(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            "Voici un hôtel.",
            '{"family": "details", "language": "fr", "display_currency": "USD"}',
        )
        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)], "profile_delta": {"city": "Hong Kong"}}
        _run_turn(runner, session.id, "un hôtel à Hong Kong demain")

        reply = _run_turn(runner, session.id, "mets les prix en dollars américains")

        assert fake_leg.call_count == 1  # no new search
        assert "USD" in reply and "euros" in reply and "HKD" in reply
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.display_currency is None

    def test_preference_before_any_search_is_noted(self, monkeypatch, fake_leg, fake_profile_store):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch, '{"family": "details", "language": "fr", "display_currency": "HOTEL"}'
        )

        reply = _run_turn(runner, session.id, "je veux voir les prix en devise locale")

        assert fake_leg.call_count == 0
        assert reply == noted_message(HOTEL, "fr")
        assert asyncio.run(fake_profile_store.get(session.id)).display_currency == HOTEL


class TestTriageSlot:
    def test_display_currency_slot(self):
        from b2c_concierge.triage import _display_currency_slot

        assert _display_currency_slot("hotel") == "HOTEL"
        assert _display_currency_slot("usd") == "USD"
        assert _display_currency_slot("dollars") is None
        assert _display_currency_slot(None) is None


class TestAnglesFollowTheDisplayedCurrency:
    def test_price_spread_is_stated_in_the_hotel_currency(self):
        from b2c_concierge.ground_truth import synthesis_angle

        cheap, dear = copy.deepcopy(HK_CARD), copy.deepcopy(HK_CARD)
        dear.update(name="Hotel Peak", hotel_price="HKD 1600.00", hotel_price_minor=160000, price_eur_cents=19500)
        for card in (cheap, dear):
            card["timeslots"][0].pop("original_price")
            card["timeslots"][0].pop("hotel_original_price")
        apply_hotel_currency([cheap, dear])
        key, directive = synthesis_angle({"results": [cheap, dear]})
        assert key == "spread" and "780-1600 HKD" in directive


class TestRatePlansInTheHotelCurrency:
    def test_booking_card_rows_follow_the_display_currency(self):
        from b2c_concierge.inline_tools import _rate_plan_view

        offer = {
            "ratePlanUuid": "p1",
            "availabilityDate": "2026-09-26",
            "priceEuro": 9500,
            "priceEuroWithBookingFees": 9800,
            "hotelCurrency": "HKD",
            "hotelPrice": 78000,
            "hotelPriceWithBookingFees": 80500,
        }
        assert _rate_plan_view(offer, {})["price"] == "€98.00"
        plan = _rate_plan_view(offer, {}, HOTEL)
        assert plan["price"] == "HKD 805.00"
        assert plan["price_eur_cents"] == 9800  # sorting stays on one scale


def test_display_currency_stays_concierge_side():
    from b2c_concierge.profile import SessionProfile, leaf_profile_view

    profile = SessionProfile(display_currency=HOTEL)
    assert SessionProfile.from_dict(profile.to_dict()).display_currency == HOTEL
    assert "display_currency" not in leaf_profile_view(profile)
