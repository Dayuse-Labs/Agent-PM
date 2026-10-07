from evals.conversation_judge import blinded_case


def test_blind_order_can_be_reversed_without_losing_turns_or_offer_units():
    case = {'id': 'sample', 'turns': [{'body': {'message': 'under 60'}}]}
    a = {'turns': [{'response': {'message': 'reference', 'hotels': [{'name': 'H', 'price': 60,
          'display_currency': 'EUR', 'timeslots': [{'start': '10:00', 'end': '18:00', 'price': 60}]}]}}]}
    b = {'turns': [{'response': {'message': 'candidate'}}]}
    payload, mapping = blinded_case(case, a, b)
    inverse, reversed_mapping = blinded_case(case, a, b, reverse=True)
    assert mapping['A'] == reversed_mapping['B']
    assert payload['branches']['A'] == inverse['branches']['B']
    label = next(k for k, v in mapping.items() if v == 'reference')
    assert payload['branches'][label][0]['cards'][0]['timeslots'][0]['price'] == 60
