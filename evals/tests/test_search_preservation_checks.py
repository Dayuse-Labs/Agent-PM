"""Counterexamples for independent result and follow-up scoring."""
import pytest

from evals.preservation_checks import check_search_cards, check_search_transition


def cards(*items):
    return {"hotels": list(items)}


def test_generated_filters_cannot_certify_displayed_results():
    response = {"active_filters": {"stars": 5, "adults": 3},
                "hotels": [{"stars": 3, "capacity": 2}]}
    assert [r["status"] for r in check_search_cards(response, {"stars_min": 5, "capacity_min": 3})] == ["fail", "fail"]


@pytest.mark.parametrize("response", [None, {}, cards(), cards({}), cards({"capacity": True})])
def test_missing_capacity_is_unscored(response):
    assert check_search_cards(response, {"capacity_min": 3})[0]["status"] == "skipped"


def test_known_counterexample_survives_unknown_other_card():
    result = check_search_cards(cards({"capacity": 2}, {}), {"capacity_min": 3})[0]
    assert result["status"] == "fail"
    assert result["unverifiable_cards"] == 1


def test_market_currency_is_not_the_currency_of_euro_price():
    card = {"currency_code": "USD", "price_eur_cents": 9000}
    expectation = {"budget": {"currency": "USD", "max_minor": 10000}}
    assert check_search_cards(cards(card), expectation)[0]["status"] == "skipped"
    card.update(hotel_currency_code="USD", hotel_price_minor=11000)
    assert check_search_cards(cards(card), expectation)[0]["status"] == "fail"


def test_explicit_local_currency_budget_boundary():
    card = {"hotel_currency_code": "CHF", "hotel_price_minor": 10000}
    assert check_search_cards(cards(card), {"budget": {"currency": "CHF", "max_minor": 10000}})[0]["status"] == "pass"


@pytest.mark.parametrize("expected", [
    {"stars_min": 6}, {"capacity_min": True}, {"capacity_min": 2.5},
    {"budget": {"currency": "usd", "max_minor": 100}},
    {"budget": {"currency": "USD", "max_minor": float("nan")}},
    {"budget": {"currency": "USD", "max_minor": 10.5}},
    {"budget": {"currency": "USD", "max_minor": 100, "convert": True}},
    {"amenities": ["pool"]},
])
def test_invalid_or_unsupported_expectations_fail_loudly(expected):
    with pytest.raises(ValueError):
        check_search_cards(None, expected)


def test_cheaper_means_below_previous_minimum_not_merely_below_most_expensive():
    before = cards({"price_eur_cents": 1000}, {"price_eur_cents": 9000})
    assert check_search_transition(before, cards({"price_eur_cents": 2000}), "cheaper_option")["status"] == "fail"
    assert check_search_transition(before, cards({"price_eur_cents": 999}), "cheaper_option")["status"] == "pass"


def test_identical_price_is_not_a_cheaper_option():
    response = cards({"price_eur_cents": 1000})
    assert check_search_transition(response, response, "cheaper_option")["status"] == "fail"


def test_unknown_old_price_cannot_prove_cheaper():
    before = cards({"price_eur_cents": 1000}, {})
    assert check_search_transition(before, cards({"price_eur_cents": 500}), "cheaper_option")["status"] == "skipped"


def test_one_proven_cheaper_option_is_sufficient_even_with_other_unknowns():
    assert check_search_transition(cards({"price_eur_cents": 1000}), cards({}, {"price_eur_cents": 500}), "cheaper_option")["status"] == "pass"


def test_reordered_or_type_changed_ids_are_not_new_hotels():
    before = cards({"id": 1}, {"id": 2})
    after = cards({"hotel_id": "2"}, {"hotel_id": "1"})
    assert check_search_transition(before, after, "new_hotel")["status"] == "fail"
    assert check_search_transition(before, cards({"hotel_id": 3}), "new_hotel")["status"] == "pass"


def test_unknown_previous_identity_prevents_novelty_claim():
    assert check_search_transition(cards({}), cards({"hotel_id": 3}), "new_hotel")["status"] == "skipped"


@pytest.mark.parametrize("requirement", ["cheaper_option", "new_hotel"])
def test_empty_followup_is_never_a_pass(requirement):
    assert check_search_transition(cards({"id": 1, "price_eur_cents": 1000}), cards(), requirement)["status"] == "skipped"


def test_unsupported_transition_rejected():
    with pytest.raises(ValueError):
        check_search_transition(None, None, "globally_most_relevant")
