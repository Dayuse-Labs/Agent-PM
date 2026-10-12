"""Typed search budget: fee-inclusive totals, in the budget's own currency, no FX.

Ported from #134 (`tests/test_requested_budget.py`), slice 3 of PORT1. One
deliberate deviation: #134 recognised currencies in the evidence with a word
list (`_literal_currency`, `currency_answer`). PORT1 forbids new word lists, so
the triage LLM labels a dollar amount with no country (`currency_basis:
"dollar"`, a closed enum) and code owns the market resolution. The cases that
only exercised the word list are replaced by their enum equivalent.
"""
from copy import deepcopy

import pytest

from b2c_common.search_budget import (
    budget_question, grounded_budget, merge_budget, native_eur_cap, offer_within_budget,
    resolve_budget_currency,
)
from b2c_concierge.profile import SessionProfile, apply_profile_delta, search_context_line
from hotel_search_agent.response_bridge import normalize_search_results


def cap(amount=100, currency="USD", unit="total"):
    return {"amount": amount, "currency": currency, "unit": unit}


def dollars(amount=100, evidence="$100"):
    return {"amount": amount, "currency": None, "currency_basis": "dollar", "unit": "total", "evidence": evidence}


def test_grounded_amount_and_atomic_clear():
    request = grounded_budget(dollars(), "Under $100 in Orlando")
    assert request["currency"] is None
    assert resolve_budget_currency(request, "US") == cap()
    assert resolve_budget_currency(request, "CA") == cap(currency="CAD")
    assert budget_question(resolve_budget_currency(request, "GB"), "en", after_search=True)
    assert grounded_budget({**cap(60, None), "evidence": "Like 60"}, "Like 60")["currency"] is None
    assert grounded_budget({**cap(60, "EUR"), "evidence": "60 euros"}, "60 euros") == cap(60, "EUR")
    assert grounded_budget({"clear": True, "evidence": "sans plafond"}, "Paris sans plafond") == {}
    assert grounded_budget({**cap(), "evidence": "$100"}, "cheaper") is None
    assert grounded_budget({**cap(), "evidence": "1000"}, "1000") is None
    assert grounded_budget({**cap(), "evidence": "-100"}, "-100") is None
    assert grounded_budget({**cap(), "clear": True, "evidence": "100"}, "100") is None


def test_a_dollar_label_overrides_a_guessed_code():
    # "$100" in Canada is not USD: the market resolves it, never the model.
    assert grounded_budget({**dollars(), "currency": "USD"}, "$100")["currency"] is None


@pytest.mark.parametrize("currency", ["usd", "US", "EURO", 840, "€"])
def test_a_malformed_currency_code_is_rejected(currency):
    assert grounded_budget({**cap(100, currency), "evidence": "100"}, "100") is None


@pytest.mark.parametrize("amount", [True, float("nan"), float("inf"), 0, -20, 1e12])
def test_untrusted_amount_never_becomes_filter(amount):
    assert grounded_budget({**cap(amount), "evidence": "100"}, "100") is None
    assert native_eur_cap(cap(amount, "EUR")) is None


def test_only_eur_total_reaches_native_cap():
    assert native_eur_cap(cap(100, "EUR")) == 100
    for request in (cap(), cap(10, "EUR", "hour"), cap(50, None), {}, None):
        assert native_eur_cap(request) is None
    assert budget_question(cap(10, "USD", "hour"), "fr")
    assert budget_question(cap(10, None), "en")
    assert budget_question(cap(), "en") is None


def test_profile_leaf_cannot_relabel_or_invent_typed_budget():
    profile = SessionProfile(requested_budget=cap())
    apply_profile_delta(profile, {"budget_max": 100}, "under $100")
    assert profile.budget_max is None
    assert "USD" in search_context_line(profile) and "€" not in search_context_line(profile)
    empty = SessionProfile(requested_budget={})
    apply_profile_delta(empty, {"budget_max": 100}, "moins cher")
    assert empty.budget_max is None
    assert SessionProfile.from_dict(profile.to_dict()).requested_budget == cap()
    legacy = SessionProfile()
    apply_profile_delta(legacy, {"budget_max": 80}, "80")
    assert legacy.budget_max == 80


def offer(eur, local, currency="USD", uuid="offer", **extra):
    return {"priceEuro": eur, "priceEuroWithBookingFees": eur,
            "hotelPrice": local, "hotelPriceWithBookingFees": local,
            "hotelCurrency": currency, "ratePlanUuid": uuid,
            "startHour": 10, "startMinute": 0, "endHour": 17, "endMinute": 0,
            **extra}


def test_orlando_eur_95_is_not_within_usd_100_if_indexed_usd_104():
    o = offer(9500, 10400)
    assert not offer_within_budget(o, {}, cap())
    assert offer_within_budget(o, {}, cap(100, "EUR"))
    assert not offer_within_budget(offer(5000, 9000, "CAD"), {}, cap())


def test_minor_units_and_mandatory_fees_ignore_display_preference():
    assert offer_within_budget(offer(3000, 1600, "JPY"), {}, cap(1600, "JPY"))
    assert not offer_within_budget(offer(3000, 1601, "JPY"), {}, cap(1600, "JPY"))
    assert offer_within_budget(offer(3000, 20500, "KWD"), {}, cap(20.5, "KWD"))
    o = offer(8500, 9900, hotelPriceWithBookingFees=10400)
    assert not offer_within_budget(o, {}, cap())
    assert not offer_within_budget(o, {"showPricesWithoutBookingFees": True}, cap())
    assert offer_within_budget(o, {"showPricesWithoutBookingFees": True}, cap(104))
    assert not offer_within_budget(offer(8500, 9900, hotelPriceWithBookingFees=None), {}, cap())
    assert not offer_within_budget(offer(9900, 9000, priceEuroWithBookingFees=10400),
                                   {"showPricesWithoutBookingFees": True}, cap(100, "EUR"))
    assert not offer_within_budget(offer(9000, True), {}, cap())
    assert not offer_within_budget(offer(9000, None), {}, cap())


def test_live_arlington_display45_total51_cannot_fit_budget50():
    h = {"hotelId": 22589, "showPricesWithoutBookingFees": True,
         "offers": [offer(4000, 4500, hotelPriceWithBookingFees=5100)]}
    assert not normalize_search_results({"results": [h]}, requested_budget=cap(50))
    assert normalize_search_results({"results": [h]}, requested_budget=cap(51))[0]["hotel_price_minor"] == 4500


def test_filter_precedes_best_offer_and_top_five_and_preserves_input():
    hotels = [{"hotelId": i, "offers": [offer(9000, 10500)]} for i in range(1, 7)]
    hotels.append({"hotelId": 7, "offers": [offer(5000, 11000, uuid="wrong"),
                                               offer(6000, 9900, uuid="right")]})
    raw = {"results": hotels}
    original = deepcopy(raw)
    cards = normalize_search_results(raw, requested_budget=cap())
    assert len(cards) == 1 and cards[0]["hotel_id"] == 7
    assert cards[0]["hotel_price"] == "USD 99.00"
    assert cards[0]["offer_id"] == "right"
    assert raw == original
    assert not normalize_search_results(raw, requested_budget=cap(10, "USD", "hour"))


def test_partial_budget_answer_never_invents_a_new_amount():
    dollars_only = grounded_budget({"currency_basis": "dollar", "evidence": "dollars"}, "dollars")
    usd = grounded_budget({"currency": "USD", "evidence": "USD"}, "USD")
    assert merge_budget(None, usd) is None
    pending = {**cap(50, None), "currency_basis": "unspecified"}
    assert merge_budget(pending, usd) == cap(50, "USD")
    assert resolve_budget_currency(merge_budget(pending, dollars_only), "CA") == cap(50, "CAD")
    assert merge_budget(cap(100, "USD"), {**cap(60, None), "currency_basis": "unspecified"}) == cap(60, "USD")
    assert merge_budget(pending, {}) == {}
    question = budget_question(pending, "en")
    assert "50" in question and "100" not in question


def test_native_widget_currency_resolves_bare_amount_but_never_overrides_explicit_unit():
    bare = grounded_budget({**cap(50, None), "evidence": "50"}, "50")
    assert merge_budget(None, bare, "USD") == cap(50, "USD")
    assert merge_budget(cap(100, "GBP"), bare, "USD") == cap(50, "GBP")
    explicit = grounded_budget({**cap(80, "EUR"), "evidence": "80 euros"}, "80 euros")
    assert merge_budget(None, explicit, "USD") == cap(80, "EUR")
    dollar = grounded_budget(dollars(), "$100")
    assert merge_budget(None, dollar, "CAD") == cap(100, "CAD")
    assert merge_budget(None, dollar, "EUR")["currency"] is None
    assert merge_budget(None, bare, None)["currency"] is None


# --- PORT1 open question 1 -------------------------------------------------------------------


def test_budget_integrity_and_offer_within_budget_agree_on_a_hotel_hiding_its_fees():
    """Does main's `budget_integrity` (budget_max) contradict `offer_within_budget`
    when a hotel hides its fees on the card? No: the guard only decides WHETHER a
    stated amount becomes `budget_max` (it never reads an offer), and that cap is
    applied by MCP on the fee-inclusive price — the same total the typed filter
    checks. The card's fee-less price never decides either side."""
    hidden_fees = {"hotelId": 1, "showPricesWithoutBookingFees": True,
                   "offers": [offer(9000, 9000, "EUR", priceEuroWithBookingFees=10500)]}
    fired: set[str] = set()
    profile = apply_profile_delta(SessionProfile(), {"budget_max": 100}, "moins de 100 euros", fired)
    assert profile.budget_max == 100.0 and "budget_integrity" not in fired
    eur_cap = cap(profile.budget_max, "EUR")
    card_price_fits = hidden_fees["offers"][0]["priceEuro"] <= 100 * 100  # what the card shows
    mcp_cap_fits = hidden_fees["offers"][0]["priceEuroWithBookingFees"] <= 100 * 100  # priceRangeMax
    assert card_price_fits and not mcp_cap_fits
    assert offer_within_budget(hidden_fees["offers"][0], hidden_fees, eur_cap) is mcp_cap_fits
    assert normalize_search_results({"results": [hidden_fees]}, requested_budget=eur_cap) == []
