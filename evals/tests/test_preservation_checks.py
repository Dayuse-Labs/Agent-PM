import pytest

from evals.preservation_checks import check_displayed_offers


def window(start, end):
    return {"start": start, "end": end}


def cards(*slots):
    return {"hotels": [{"timeslots": list(slots)}]}


def test_offer_must_cover_the_stay_not_be_contained_inside_it():
    assert check_displayed_offers(cards(window("10:00", "16:00")), {
        "stay_window": window("12:00", "13:00")})[0]["status"] == "pass"
    assert check_displayed_offers(cards(window("12:00", "13:00")), {
        "stay_window": window("10:00", "16:00")})[0]["status"] == "fail"


@pytest.mark.parametrize("slot,expected", [
    (window("12:00", "13:00"), "pass"),
    (window("12:01", "13:00"), "fail"),
    (window("12:00", "12:59"), "fail"),
    (window("13:00", "14:00"), "fail"),
    (window("10:00", "12:00"), "fail"),
])
def test_full_minute_precision_and_boundary_overlap_are_not_full_coverage(slot, expected):
    assert check_displayed_offers(cards(slot), {"stay_window": window("12:00", "13:00")})[0]["status"] == expected


@pytest.mark.parametrize("response", [None, {}, {"hotels": []}, {"hotels": [{}]}, {"hotels": [None]}])
def test_missing_evidence_is_never_a_pass(response):
    checks = check_displayed_offers(response, {"offer_date": "2026-07-03", "stay_window": window("12:00", "13:00")})
    assert {c["status"] for c in checks} == {"skipped"}


def test_one_covering_slot_is_enough_but_a_missing_slot_cannot_prove_no_coverage():
    expected = {"stay_window": window("12:00", "13:00")}
    assert check_displayed_offers(cards(window("10:00", "11:00"), {}), expected)[0]["status"] == "skipped"
    assert check_displayed_offers(cards(window("10:00", "16:00"), {}), expected)[0]["status"] == "pass"


def test_known_counterexample_fails_while_retaining_unknown_card_coverage():
    result = check_displayed_offers({"hotels": [{"offer_date": "2026-07-04"}, {}]}, {"offer_date": "2026-07-03"})[0]
    assert result["status"] == "fail"
    assert result["verified_mismatching_cards"] == 1 and result["unverifiable_cards"] == 1


def test_date_checks_every_displayed_card_and_does_not_trust_active_filters():
    response = {"active_filters": {"date": "2026-07-03"}, "hotels": [
        {"offer_date": "2026-07-03"}, {"offer_date": "2026-07-04"}]}
    result = check_displayed_offers(response, {"offer_date": "2026-07-03"})[0]
    assert result["status"] == "fail" and result["verified_matching_cards"] == 1


@pytest.mark.parametrize("expected", [
    {"offer_date": "2026-02-30"}, {"offer_date": "03/07/2026"},
    {"stay_window": window("23:00", "01:00")}, {"stay_window": window("12:60", "14:00")},
    {"stay_window": window("12:00", "12:00")}, {"undeclared_requirement": True},
])
def test_invalid_or_unsupported_oracles_fail_loudly(expected):
    with pytest.raises(ValueError):
        check_displayed_offers({}, expected)


def test_end_of_day_is_supported_and_undeclared_requirements_are_not_scored():
    assert check_displayed_offers(cards(window("22:00", "24:00")), {
        "stay_window": window("23:00", "24:00")})[0]["status"] == "pass"
    assert check_displayed_offers(None, {}) == []
