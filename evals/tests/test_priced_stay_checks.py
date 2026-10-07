import pytest

from evals.priced_stay_checks import check_priced_stays, check_price_transition


BUDGET = {"budget": {"currency": "EUR", "max_minor": 6000}}
STAY = {**BUDGET, "stay_window": {"start": "10:00", "end": "17:00"}}


def legacy(*slots):
    return {"hotels": [{"timeslots": list(slots)}]}


def slot(price=60, **changes):
    return {"price": price, "currency": "EUR", "start": "09:00", "end": "17:00", **changes}


def test_cheap_short_offer_and_expensive_covering_offer_do_not_jointly_pass():
    response = legacy(slot(40, end="16:00"), slot(80))
    assert check_priced_stays(response, BUDGET, schema="legacy")["status"] == "pass"
    assert check_priced_stays(response, STAY, schema="legacy")["status"] == "fail"


def test_boundary_prices_and_covering_slot_agree_across_architectures():
    new = {"hotels": [{"price_eur_cents": 6000, "timeslots": [{"start": "09:00", "end": "17:00"}]}]}
    assert check_priced_stays(legacy(slot()), STAY, schema="legacy")["status"] == "pass"
    assert check_priced_stays(new, STAY, schema="b2c")["status"] == "pass"
    assert check_priced_stays(legacy(slot(60.01)), STAY, schema="legacy")["status"] == "fail"


@pytest.mark.parametrize("changes", [{"currency": None}, {"currency": "USD"}, {"price": True}, {"price": -1}, {"price": float("nan")}, {"price": 60.001}])
def test_unknown_legacy_amount_is_not_zero_or_inferred_from_card(changes):
    response = legacy(slot(**changes))
    response["hotels"][0]["display_currency"] = "EUR"
    assert check_priced_stays(response, STAY, schema="legacy")["status"] == "skipped"


def test_single_known_witness_is_sufficient_but_unknown_offer_prevents_failure():
    assert check_priced_stays(legacy(slot(), {}), STAY, schema="legacy")["status"] == "pass"
    assert check_priced_stays(legacy(slot(80), {}), STAY, schema="legacy")["status"] == "skipped"


def test_new_card_price_cannot_be_joined_to_multiple_offers():
    response = {"hotels": [{"price_eur_cents": 5000, "timeslots": [slot(), slot()]}]}
    assert check_priced_stays(response, STAY, schema="b2c")["status"] == "skipped"


def test_new_market_currency_is_not_currency_of_eur_amount():
    response = {"hotels": [{"price_eur_cents": 5000, "currency_code": "USD", "timeslots": [slot()]}]}
    expected = {"budget": {"currency": "USD", "max_minor": 6000}}
    assert check_priced_stays(response, expected, schema="b2c")["status"] == "skipped"
    response["hotels"][0].update(hotel_currency_code="USD", hotel_price_minor=7000)
    assert check_priced_stays(response, expected, schema="b2c")["status"] == "fail"


@pytest.mark.parametrize("response", [None, {}, {"hotels": []}, {"hotels": [None]}, legacy()])
def test_missing_results_or_slots_are_not_success(response):
    assert check_priced_stays(response, STAY, schema="legacy")["status"] == "skipped"


def test_invalid_schema_and_unsupported_oracles_are_rejected():
    for expected, schema in [({}, "legacy"), (BUDGET, "guessed"), ({"budget": {"currency": "JPY", "max_minor": 60}}, "legacy"), ({**BUDGET, "stay_window": {"start": "22:00", "end": "02:00"}}, "b2c")]:
        with pytest.raises(ValueError):
            check_priced_stays({}, expected, schema=schema)


def test_legacy_cheaper_compares_usd_with_usd_without_relabelling_eur():
    result = check_price_transition(legacy(slot(65, currency="USD")), legacy(slot(60, currency="USD")), schema="legacy")
    assert result["status"] == "pass" and result["currency"] == "USD"


@pytest.mark.parametrize("before,after,status", [
    (legacy(slot(60)), legacy(slot(60)), "fail"),
    (legacy(slot(60)), legacy(slot(65)), "fail"),
    (legacy(slot(60)), legacy(slot(50)), "pass"),
    (legacy(slot(60), {}), legacy(slot(50)), "skipped"),
    (legacy(slot(60)), legacy(slot(50), {}), "skipped"),
    (legacy(slot(60)), legacy(slot(50, currency="USD")), "skipped"),
    ({}, legacy(slot(50)), "skipped"),
])
def test_legacy_transition_requires_verifiable_offer_minima(before, after, status):
    assert check_price_transition(before, after, schema="legacy")["status"] == status


def test_new_transition_known_cheaper_card_is_witness_despite_an_unknown_other_card():
    before = {"hotels": [{"price_eur_cents": 6000}]}
    after = {"hotels": [{"price_eur_cents": 5000}, {}]}
    assert check_price_transition(before, after, schema="b2c")["status"] == "pass"
    assert check_price_transition(after, before, schema="b2c")["status"] == "skipped"
