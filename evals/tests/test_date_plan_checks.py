import pytest

from evals.date_plan_checks import check_date_range, check_stay_sequence

STAYS = [{'id': 'first', 'date': '2026-10-31', 'start': '09:00', 'end': '15:00'},
         {'id': 'second', 'date': '2026-11-01', 'start': '08:00', 'end': '14:00'}]


def card(day='2026-10-31', start='09:00', end='15:00', price=5000):
    return {'offer_date': day, 'price_eur_cents': price, 'timeslots': [{'start': start, 'end': end}]}


def test_tomorrow_cards_cannot_pass_a_next_week_range():
    got = check_date_range({'hotels': [card('2026-10-10')]}, start='2026-10-12', end='2026-10-18')
    assert got['status'] == 'fail' and got['outside_range_indices'] == [0]
    assert check_date_range({'hotels': [card('2026-10-12'), card('2026-10-18')]}, start='2026-10-12', end='2026-10-18')['status'] == 'pass'


@pytest.mark.parametrize('response', [None, {}, {'hotels': []}, {'hotels': [{}]}, {'hotels': [None]}])
def test_missing_date_evidence_is_not_a_pass(response):
    assert check_date_range(response, start='2026-10-12', end='2026-10-18')['status'] == 'skipped'
    assert check_stay_sequence(response, STAYS, schema='b2c')['status'] == 'skipped'


def test_each_date_keeps_its_own_window_and_price():
    correct = {'hotels': [card(), card('2026-11-01', '08:00', '14:00')]}
    assert check_stay_sequence(correct, STAYS, schema='b2c', budget={'currency': 'EUR', 'max_minor': 6000})['status'] == 'pass'
    wrong = {'hotels': [card('2026-10-31', '08:00', '14:00'), card('2026-11-01', '09:00', '15:00')]}
    assert check_stay_sequence(wrong, STAYS, schema='b2c')['status'] == 'fail'
    wrong = {'hotels': [card(price=7000), card('2026-11-01', '08:00', '14:00', price=4000)]}
    assert check_stay_sequence(wrong, STAYS, schema='b2c', budget={'currency': 'EUR', 'max_minor': 6000})['status'] == 'fail'


def test_one_date_cannot_prove_two_stays_even_when_text_lists_both():
    response = {'message': 'Both dates are available', 'hotels': [card()]}
    got = check_stay_sequence(response, STAYS, schema='b2c')
    assert got['status'] == 'skipped' and [s['status'] for s in got['stays']] == ['pass', 'skipped']


def test_undated_legacy_export_is_not_future_availability():
    row = {'timeslots': [{'start': '08:00', 'end': '18:00', 'price': 50, 'currency': 'EUR'}]}
    assert check_stay_sequence({'hotels': [row]}, STAYS, schema='legacy', budget={'currency': 'EUR', 'max_minor': 6000})['status'] == 'skipped'


@pytest.mark.parametrize('start,end', [('20261012', '2026-10-18'), ('2026-02-30', '2026-10-18'), ('2026-10-18', '2026-10-12')])
def test_bad_oracles_are_rejected(start, end):
    with pytest.raises(ValueError):
        check_date_range({}, start=start, end=end)


def test_duplicate_stay_cannot_reuse_same_offer_as_two_bookings():
    with pytest.raises(ValueError):
        check_stay_sequence({}, [STAYS[0], {**STAYS[0], 'id': 'duplicate-date'}], schema='b2c')
    with pytest.raises(ValueError):
        check_stay_sequence({}, [{**STAYS[0], 'end': '03:00'}], schema='b2c')


def test_offer_on_an_unrequested_date_is_a_mismatch_not_missing_evidence():
    got = check_stay_sequence({'hotels': [card('2026-11-02')]}, STAYS, schema='b2c')
    assert got['status'] == 'fail' and got['unrequested_date_indices'] == [0]
