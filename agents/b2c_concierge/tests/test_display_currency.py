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

    @pytest.mark.parametrize(
        "message, requested",
        [
            ("donne le prix en hkd", "HKD"),
            ("je veux dans la monnaie de l'hotel", "HOTEL"),
            ("affiche les prix en devise locale", "HOTEL"),
        ],
    )
    def test_a_currency_request_filed_as_faq_still_repaints(
        self, monkeypatch, fake_leg, fake_profile_store, message, requested
    ):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            "Voici un hôtel.",
            f'{{"family": "faq", "language": "fr", "display_currency": "{requested}"}}',
            "Voici les prix en dollars de Hong Kong.",
        )
        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)], "profile_delta": {"city": "Hong Kong"}}
        _run_turn(runner, session.id, "un hôtel à Hong Kong demain")

        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)]}
        _run_turn(runner, session.id, message)

        assert fake_leg.call_count == 2  # the search leaf, not the faq one
        outgoing = find_datapart(fake_leg.seen_outgoing_parts)
        assert outgoing["query_params"] == {"repeat_previous_search": True}
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.last_results[0]["price"] == "HKD 780.00"

    def test_a_payment_question_keeps_its_faq_route(self, monkeypatch, fake_leg, fake_profile_store):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            "Voici un hôtel.",
            '{"family": "faq", "language": "fr", "display_currency": "HKD"}',
            "Vous pouvez payer par carte.",
        )
        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)], "profile_delta": {"city": "Hong Kong"}}
        _run_turn(runner, session.id, "un hôtel à Hong Kong demain")

        _run_turn(runner, session.id, "je peux payer en HKD ?")

        outgoing = find_datapart(fake_leg.seen_outgoing_parts)
        assert outgoing.get("query_params") != {"repeat_previous_search": True}
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.last_results[0]["price"] == "€95.00"

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
    @pytest.mark.parametrize(
        "message, expected",
        [
            ("donne le prix en sgd", False),
            ("je veux dans la monnaie de l'hotel", False),
            ("les prix dans la devise du pays", False),
            ("je peux payer en SGD ?", True),
            ("quelles devises acceptez-vous ?", True),
            ("conditions d'annulation", True),
        ],
    )
    def test_asks_policy(self, message, expected):
        from b2c_concierge.triage import asks_policy

        assert asks_policy(message) is expected

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

    def test_night_rate_and_discount_follow_the_display_currency(self):
        from b2c_concierge.inline_tools import _rate_plan_view

        offer = {
            "ratePlanUuid": "p1",
            "availabilityDate": "2026-09-26",
            "priceEuroWithBookingFees": 9800,
            "originalPriceEuro": 20000,
            "hotelCurrency": "HKD",
            "hotelPriceWithBookingFees": 80000,
            "originalHotelPrice": 160000,
        }
        eur = _rate_plan_view(offer, {})
        assert (eur["original_price"], eur["discount_pct"]) == ("€200.00", 51)
        hotel = _rate_plan_view(offer, {}, HOTEL)
        assert (hotel["original_price"], hotel["discount_pct"]) == ("HKD 1600.00", 50)


def test_display_currency_stays_concierge_side():
    from b2c_concierge.profile import SessionProfile, leaf_profile_view

    profile = SessionProfile(display_currency=HOTEL)
    assert SessionProfile.from_dict(profile.to_dict()).display_currency == HOTEL
    assert "display_currency" not in leaf_profile_view(profile)


class TestReviewFixes:
    def test_a_new_search_in_its_hotels_own_currency_switches_to_it(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        # "un hôtel à Tokyo en yens" on turn 1: no shortlist yet, the code is
        # checked against the hotels the search returns.
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "display_currency": "JPY"}',
            "Voici un hôtel.",
        )
        tokyo = {**copy.deepcopy(HK_CARD), "hotel_price": "JPY 12000", "hotel_price_minor": 12000,
                 "hotel_currency_code": "JPY", "currency_code": "JPY"}
        fake_leg.response_payload = {"results": [tokyo], "profile_delta": {"city": "Tokyo"}}

        reply = _run_turn(runner, session.id, "un hôtel à Tokyo en yens")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.display_currency == HOTEL
        assert stored.last_results[0]["price"] == "JPY 12000"
        assert "Je ne peux pas encore" not in reply  # no refusal appended

    def test_a_new_search_in_another_currency_names_the_new_hotels_currency(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "display_currency": "USD"}',
            "Voici un hôtel.",
        )
        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)], "profile_delta": {"city": "Hong Kong"}}

        reply = _run_turn(runner, session.id, "un hôtel à Hong Kong en dollars américains")

        assert reply.endswith("Laquelle préférez-vous ?")
        assert "USD" in reply and "HKD" in reply
        assert asyncio.run(fake_profile_store.get(session.id)).display_currency is None

    def test_a_named_hotel_keeps_its_details_route(self, monkeypatch, fake_leg, fake_profile_store):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            "Voici un hôtel.",
            '{"family": "details", "language": "fr", "display_currency": "HOTEL", "hotel_name": "Hotel Harbour"}',
            "Voici le détail.",
        )
        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)], "profile_delta": {"city": "Hong Kong"}}
        _run_turn(runner, session.id, "un hôtel à Hong Kong demain")
        details_card = {"id": 1, "name": "Hotel Harbour", "price": "€98.00", **{
            k: HK_CARD[k] for k in ("hotel_price", "hotel_price_minor", "hotel_currency_code")
        }}
        calls = []

        async def fake_details(*args, **kwargs):
            calls.append(args)
            return {"ok": True, "hotel": copy.deepcopy(details_card)}

        monkeypatch.setattr(agent_module.inline_tools, "get_hotel_details", fake_details)
        _run_turn(runner, session.id, "montre-moi le Hotel Harbour en devise locale")

        assert fake_leg.call_count == 1  # no repaint search
        assert len(calls) == 1  # the details lookup it asked for
        assert asyncio.run(fake_profile_store.get(session.id)).display_currency == HOTEL

    def test_asking_for_the_currency_already_shown_repaints_nothing(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            "Voici un hôtel.",
            '{"family": "details", "language": "fr", "display_currency": "EUR"}',
        )
        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)], "profile_delta": {"city": "Hong Kong"}}
        _run_turn(runner, session.id, "un hôtel à Hong Kong demain")

        reply = _run_turn(runner, session.id, "en euros")

        assert fake_leg.call_count == 1
        assert reply == "Les prix sont déjà affichés en euros."

    def test_a_card_left_in_eur_keeps_the_eur_disclosure(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "details", "language": "fr", "display_currency": "HOTEL"}',
            '{"family": "search", "language": "fr"}',
            "Voici un hôtel.",
        )
        _run_turn(runner, session.id, "je veux la devise locale")
        eur_only = {k: v for k, v in HK_CARD.items() if not k.startswith("hotel_")}
        fake_leg.response_payload = {"results": [eur_only], "profile_delta": {"city": "Hong Kong"}}

        _run_turn(runner, session.id, "un hôtel à Hong Kong demain")

        assert "CURRENCY" in llm.calls[-1]["messages"][1]["content"]


class TestSecondReviewFixes:
    def test_the_screen_decides_already_shown_not_the_saved_preference(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        # A details-only turn saved HOTEL without repainting the EUR cards: the
        # next currency request must still repaint them.
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            "Voici un hôtel.",
            '{"family": "details", "language": "fr", "display_currency": "HOTEL", "hotel_name": "Hotel Harbour"}',
            "Voici le détail.",
            '{"family": "details", "language": "fr", "display_currency": "HOTEL"}',
            "Voici les prix en HK$.",
        )
        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)], "profile_delta": {"city": "Hong Kong"}}
        _run_turn(runner, session.id, "un hôtel à Hong Kong demain")

        async def fake_details(*args, **kwargs):
            return {"ok": True, "hotel": {"id": 1, "name": "Hotel Harbour", "price": "€98.00"}}

        monkeypatch.setattr(agent_module.inline_tools, "get_hotel_details", fake_details)
        _run_turn(runner, session.id, "montre-moi le Hotel Harbour en devise locale")
        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)]}

        reply = _run_turn(runner, session.id, "affiche les prix en devise locale")

        assert fake_leg.call_count == 2  # repainted, not "already shown"
        assert reply != "Les prix sont déjà affichés dans la devise de chaque hôtel."

    def test_no_generic_eur_disclosure_on_a_mixed_list(self, monkeypatch, fake_leg, fake_profile_store):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "details", "language": "fr", "display_currency": "HOTEL"}',
            '{"family": "search", "language": "fr"}',
            "Voici deux hôtels.",
        )
        _run_turn(runner, session.id, "je veux la devise locale")
        eur_only = {k: v for k, v in HK_CARD.items() if not k.startswith("hotel_")}
        eur_only.update(id=2, name="Hotel Eur")
        fake_leg.response_payload = {
            "results": [copy.deepcopy(HK_CARD), eur_only],
            "profile_delta": {"city": "Hong Kong"},
        }

        reply = _run_turn(runner, session.id, "un hôtel à Hong Kong demain")

        assert "CURRENCY" not in llm.calls[-1]["messages"][1]["content"]
        assert "Prix affichés en euros" not in reply

    def test_unknown_destination_currency_is_deferred_without_results(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "display_currency": "PLN"}',
            "Dans quelle ville cherchez-vous ?",
        )
        fake_leg.text = "Dans quelle ville cherchez-vous ?"
        fake_leg.response_payload = None  # the leaf asked a question, no results

        reply = _run_turn(runner, session.id, "un hôtel en zlotys")

        assert "Je ne peux pas encore afficher" not in reply
        saved = asyncio.run(fake_profile_store.get(session.id))
        assert saved.requested_currency == "PLN"

    def test_an_unsupported_currency_notice_is_not_repeated_on_later_searches(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "display_currency": "PLN"}', "Voici un hôtel.",
            '{"family": "search", "language": "fr"}', "Voici un autre hôtel.",
        )
        fake_leg.response_payload = {"results": [copy.deepcopy(HK_CARD)], "profile_delta": {"city": "Hong Kong"}}
        first = _run_turn(runner, session.id, "un hôtel à Hong Kong en zlotys")
        second = _run_turn(runner, session.id, "et demain ?")
        assert "Je ne peux pas encore" in first
        assert "Je ne peux pas encore" not in second

    def test_deferred_currency_is_resolved_by_the_answer_to_the_pending_question(
        self, monkeypatch, fake_leg, fake_profile_store
    ):
        # PORT1 open question 2 (#134 rewrite vs #135): the deferral leaves
        # #135's pending question intact, and the currency asked on turn 1 is
        # decided against the hotels the answer's search returns.
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "display_currency": "PLN"}',
            "Dans quelle ville cherchez-vous ?",
            '{"family": "search", "language": "fr"}',
            "Voici un hôtel.",
        )
        fake_leg.text = "Dans quelle ville cherchez-vous ?"
        fake_leg.response_payload = None
        _run_turn(runner, session.id, "un hôtel en zlotys")
        assert asyncio.run(fake_profile_store.get(session.id)).pending_search == {
            "request": "un hôtel en zlotys", "question": "Dans quelle ville cherchez-vous ?",
            "asked": 1,  # QA14707 (Q28): the free-question anti-loop's count
        }

        warsaw = {**copy.deepcopy(HK_CARD), "hotel_price": "PLN 400.00", "hotel_price_minor": 40000,
                  "hotel_currency_code": "PLN", "currency_code": "PLN"}
        fake_leg.text = "Voici un hôtel."
        fake_leg.response_payload = {"results": [warsaw], "profile_delta": {"city": "Varsovie"}}
        reply = _run_turn(runner, session.id, "Varsovie")

        outgoing = " ".join(p.text or "" for p in fake_leg.seen_outgoing_parts)
        assert "EARLIER REQUEST" in outgoing and "un hôtel en zlotys" in outgoing
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.display_currency == HOTEL
        assert stored.last_results[0]["price"] == "PLN 400.00"
        assert "Je ne peux pas encore" not in reply
