"""Cheaper means a verified price improvement, not another expensive page."""
from types import SimpleNamespace
from copy import deepcopy

import pytest
from google.genai import types
from b2c_common.price_comparison import (
    cheaper_reference, comparison_budget, grounded_price_comparison, offer_below_reference,
)
from b2c_concierge.profile import SessionProfile, apply_profile_delta, record_search_shortlist, leaf_profile_view, pagination_search_key
from hotel_search_agent.response_bridge import normalize_hotel, normalize_search_results, encode_datapart
from hotel_search_agent.budget_injection import inject_profile_budget


def offer(price, *, currency="EUR", native=None, **extra):
    return {"ratePlanUuid": "offer-1", "availabilityDate": "2026-10-10",
            "startHour": 13, "endHour": 20, "priceEuro": price,
            "priceEuroWithBookingFees": price, "hotelCurrency": currency,
            "hotelPriceWithBookingFees": native if native is not None else price, **extra}


def make_profile(*offers, currency="EUR"):
    p = SessionProfile(city="Paris", requested_budget={}, requested_window={"start": "14:30", "end": "16:30"},
                       date="2026-10-10", amenities=["spa"], display_currency=currency)
    record_search_shortlist(p, [normalize_hotel({"hotelId": i, "name": f"Example {i}", "offers": [o]})
                               for i, o in enumerate(offers, 1)])
    return SessionProfile.from_dict(p.to_dict())


def test_actual_card_to_stored_profile_to_search_reference_and_fee_filter():
    p = make_profile(offer(11700), offer(14600))
    assert p.last_results[0]["offer_totals"] == {"EUR": 11700}
    old_key = pagination_search_key(p)
    p.price_comparison = cheaper_reference(p.last_results, p.display_currency)
    assert pagination_search_key(p) != old_key
    assert p.requested_budget == {}  # No fabricated numeric user budget.
    envelope = leaf_profile_view(p)
    assert envelope['price_comparison']['reference_minor'] == 11700
    ctx = SimpleNamespace(user_content=types.Content(parts=[encode_datapart({'profile_in': envelope})]))
    args = {'priceRangeMax': 999, 'date': '2026-10-10', 'endHour': 20, 'hotelEquipmentIds': [19]}
    inject_profile_budget(SimpleNamespace(name='search_offers'), args, ctx)
    assert args['priceRangeMax'] == 116.99 and args['endHour'] == 20
    data = {'results': [{'hotelId': 1, 'name': 'Too expensive', 'offers': [offer(14400)]},
                        {'hotelId': 2, 'name': 'Equal', 'offers': [offer(11700)]},
                        {'hotelId': 3, 'name': 'Fees exceed', 'showPricesWithoutBookingFees': True,
                         'offers': [offer(9900, priceEuroWithBookingFees=11800)]},
                        {'hotelId': 4, 'name': 'Actually cheaper', 'offers': [offer(11699)]}]}
    cards = normalize_search_results(data, price_comparison=p.price_comparison)
    assert [c['id'] for c in cards] == [4]
    assert normalize_search_results(data, requested_budget={'amount': 110, 'currency': 'EUR', 'unit': 'total'},
                                    price_comparison=p.price_comparison) == []
    # A leaf cannot delete the concierge-owned comparison on the next turn.
    apply_profile_delta(p, {'price_comparison': {'op': 'clear'}, 'budget_max': 900}, 'later')
    assert p.price_comparison['reference_minor'] == 11700 and p.budget_max is None
    assert p.requested_window == {'start': '14:30', 'end': '16:30'} and p.amenities == ['spa']


@pytest.mark.parametrize('currency,reference,below,threshold', [('EUR',11700,11699,116.99),('JPY',17000,16999,16999),('KWD',20500,20499,20.499)])
def test_strict_comparison_uses_the_same_currency_and_minor_unit(currency,reference,below,threshold):
    comparison={'relation':'lower','reference_minor':reference,'currency':currency}
    assert comparison_budget(comparison)['amount'] == threshold
    assert not offer_below_reference(offer(reference,currency=currency,native=reference),{},comparison)
    assert offer_below_reference(offer(below,currency=currency,native=below),{},comparison)


def test_distinct_indexed_currencies_and_user_cap_both_apply_without_fx():
    p=make_profile(offer(9000,currency='USD',native=10000),currency='HOTEL')
    comparison=cheaper_reference(p.last_results,p.display_currency)
    assert comparison['currency']=='USD'
    h={'hotelId':1,'name':'Example','offers':[offer(8000,currency='USD',native=9999)]}
    assert normalize_search_results({'results':[h]},price_comparison=comparison)
    assert not normalize_search_results({'results':[h]},requested_budget={'amount':75,'currency':'EUR','unit':'total'},price_comparison=comparison)
    h['offers'][0]['hotelCurrency']='CAD'
    assert not normalize_search_results({'results':[h]},price_comparison=comparison)


@pytest.mark.parametrize('change', [{'offer_totals': {}},{'offer_id':None},{'offer_date':None}])
def test_unverified_reference_never_uses_display_string_or_invents_fees(change):
    p=make_profile(offer(11700))
    p.last_results[0].update(change)
    assert cheaper_reference(p.last_results,'EUR') is None


def test_mixed_local_currencies_cannot_be_compared_by_numeric_amount():
    p=make_profile(offer(8000,currency='USD',native=9000),offer(9000,currency='CAD',native=8000))
    assert cheaper_reference(p.last_results,'HOTEL') is None
    # Canonical EUR quotes allow a comparison with no inferred FX conversion.
    assert cheaper_reference(p.last_results,'EUR')['reference_minor']==8000


def test_intent_needs_current_literal_evidence_but_no_keyword_parser():
    assert grounded_price_comparison({'value':'lower','evidence':'moins cher'},'plus tard') is None
    assert grounded_price_comparison({'value':'lower','evidence':'plus économique'},'Une option plus économique ?')=='lower'
    assert grounded_price_comparison({'value':'clear','evidence':'peu importe le prix'},'peu importe le prix')=='clear'
    assert grounded_price_comparison({'value':'lower','evidence':''},'moins cher') is None


def test_relative_eur_cap_does_not_loosen_an_explicit_cap():
    p=make_profile(offer(11700))
    p.price_comparison=cheaper_reference(p.last_results,'EUR')
    p.requested_budget={'amount':100,'currency':'EUR','unit':'total'}
    args={}
    ctx=SimpleNamespace(user_content=types.Content(parts=[encode_datapart({'profile_in':p.to_dict()})]))
    inject_profile_budget(SimpleNamespace(name='search_offers'),args,ctx)
    assert args['priceRangeMax']==100
    before=deepcopy(p.to_dict())
    assert before['price_comparison']['reference_minor']==11700


def test_current_price_outcome_uses_fee_totals_without_rebasing_the_previous_reference():
    from b2c_common.price_comparison import comparison_context
    comparison = {'relation': 'lower', 'currency': 'EUR', 'reference_minor': 5800}
    rows = [normalize_hotel({'hotelId': 1, 'offers': [offer(5700)]})]
    text = comparison_context(comparison, rows)
    assert '1 displayed offers are strictly cheaper' in text
    assert '57 EUR' in text and 'reference 58 EUR' in text and 'saving 1 EUR' in text
    assert 'no cheaper offer verified' not in text
    assert comparison['reference_minor'] == 5800
    assert 'no cheaper offer verified in the retrieved sample' in comparison_context(comparison, [])
    for totals in ({'EUR': 5800}, {'EUR': 5900}, {'USD': 5700}, {}):
        assert 'do not prove a cheaper total' in comparison_context(comparison, [{'offer_totals': totals}])
