"""Details and comparison quote the displayed dated offer, never another day or formula.

Ported from #134 (`test_inline_tools.py`, `test_comparison_context.py`), slice 2
of PORT1. Left out: the named-hotel availability search (`for_search`,
`allow_text_name` — main resolves named hotels in the leaf, #135), the
comparison positions and `hotel_scope` (triage prompt changes), and the
daypart / bedding / party branches of `_search_offer` (slices 5 and Dates).
"""
from copy import deepcopy
import asyncio
import json

import pytest

from b2c_concierge import inline_tools
from b2c_concierge.display_currency import apply_hotel_currency
from b2c_concierge.ground_truth import shortlist_ground_truth_block
from b2c_concierge.profile import SessionProfile

from .test_inline_tools import HOTEL_DETAILS_RESPONSE, FakeResult, _install, _run
from .test_spine import _new_session, _drive_in, scripted  # noqa: F401


def _offer(**changes):
    return {**HOTEL_DETAILS_RESPONSE['offers'][0], 'availabilityDate': '2030-10-09',
            'startHour': 10, 'endHour': 18, 'priceEuro': 9000,
            'priceEuroWithBookingFees': 9500, 'hotelPriceWithBookingFees': 8000,
            'hotelCurrency': 'USD', 'capacity': 2, 'childrenCapacity': 1, **changes}


# --- get_hotel_details ------------------------------------------------------------------------


def test_details_keeps_the_displayed_formula_and_its_own_clock(monkeypatch):
    selected = dict(HOTEL_DETAILS_RESPONSE["offers"][0], ratePlanUuid="selected", startHour=10,
                    startMinute=30, endHour=16, priceEuro=8000)
    session = _install(monkeypatch, {"get_hotel_details": FakeResult({
        "hotel": HOTEL_DETAILS_RESPONSE["hotel"],
        "offers": HOTEL_DETAILS_RESPONSE["offers"] + [selected],
    })})
    profile = SessionProfile(date="2026-07-20", last_results=[{
        "hotel_id": 22293, "name": "Villa Paris Orly", "offer_id": "selected",
        "offer_date": "2026-07-20",
    }])
    hotel = _run(inline_tools.get_hotel_details("", profile, picked_hotel_id=22293))["hotel"]
    assert hotel["offer_id"] == "selected"
    assert hotel["price_eur_cents"] == 8000
    assert hotel["timeslots"] == [{"start": "10:30", "end": "16:00"}]
    assert session.calls == [("get_hotel_details", {"hotelId": 22293, "date": "2026-07-20"})]


def test_details_without_a_session_date_asks_for_the_displayed_offer_s_day(monkeypatch):
    session = _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
    profile = SessionProfile(last_results=[{
        "hotel_id": 22293, "name": "Villa Paris Orly",
        "offer_id": HOTEL_DETAILS_RESPONSE["offers"][0]["ratePlanUuid"], "offer_date": "2026-07-20",
    }])
    hotel = _run(inline_tools.get_hotel_details("", profile, picked_hotel_id=22293))["hotel"]
    assert session.calls == [("get_hotel_details", {"hotelId": 22293, "date": "2026-07-20"})]
    assert hotel["offer_date"] == "2026-07-20"


def test_details_does_not_silently_replace_unavailable_displayed_formula(monkeypatch):
    _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
    profile = SessionProfile(date="2026-07-20", last_results=[{
        "hotel_id": 22293, "name": "Villa Paris Orly", "offer_id": "no-longer-available",
        "offer_date": "2026-07-20",
    }])
    hotel = _run(inline_tools.get_hotel_details("", profile, picked_hotel_id=22293))["hotel"]
    assert "price" not in hotel
    assert "offer_id" not in hotel
    assert "timeslots" not in hotel
    assert hotel["amenities"]


def test_an_offer_of_another_day_is_never_attached_to_the_requested_day(monkeypatch):
    _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
    hotel = _run(inline_tools.get_hotel_details(
        "", SessionProfile(date="2026-07-21"), picked_hotel_id=22293))["hotel"]
    # The fixture only contains an offer for July 20.
    assert "price" not in hotel and "offer_id" not in hotel
    assert hotel["requested_offer_unavailable"] is True
    block = shortlist_ground_truth_block({"results": [hotel]}, SessionProfile(date="2026-07-21"))
    assert "no dated formula matching the requested hours was verified" in block


def test_details_gives_synthesis_all_valid_formulas_without_changing_selected_offer(monkeypatch):
    selected = _offer(ratePlanUuid='selected', startHour=9, endHour=16)
    alternative = _offer(ratePlanUuid='afternoon', startHour=12, endHour=20,
                         priceEuroWithBookingFees=10000, hotelPriceWithBookingFees=8500)
    hotel = {**HOTEL_DETAILS_RESPONSE['hotel'], 'amenities': [
        {'name': 'Facility '+str(i)} for i in range(12)] + [{'name': 'Outdoor pool'}]}
    _install(monkeypatch, {'get_hotel_details': FakeResult({'hotel': hotel, 'offers': [
        selected, alternative, _offer(ratePlanUuid='expired', cutoffDeadlineUtc='2000-01-01T12:00:00Z'),
        _offer(ratePlanUuid='wrong-day', availabilityDate='2030-10-10'),
        _offer(ratePlanUuid='over-budget', priceEuroWithBookingFees=10500)]})})
    profile = SessionProfile(date='2030-10-09', budget_max=100,
        last_results=[{'hotel_id': 22293, 'offer_id': 'selected', 'offer_date': '2030-10-09'}])
    result = _run(inline_tools.get_hotel_details('', profile, picked_hotel_id=22293))
    card = result['hotel']
    assert card['offer_id'] == 'selected' and card['price'] == '€95.00'
    assert [o['offer_id'] for o in card['available_offers']] == ['selected', 'afternoon']
    block = shortlist_ground_truth_block({'results': [card]}, profile)
    assert '09:00–16:00 €95.00' in block and '12:00–20:00 €100.00' in block
    assert 'not displayed on the selected card' in block
    apply_hotel_currency([card])
    block = shortlist_ground_truth_block({'results': [card]}, profile)
    assert '09:00–16:00 USD 80.00' in block and '12:00–20:00 USD 85.00' in block
    assert card['offer_id'] == 'selected'


def test_details_alternatives_still_apply_requested_clock(monkeypatch):
    _install(monkeypatch, {'get_hotel_details': FakeResult({'hotel': HOTEL_DETAILS_RESPONSE['hotel'],
        'offers': [_offer(ratePlanUuid='covers', startHour=9, endHour=18),
                   _offer(ratePlanUuid='starts-late', startHour=13, endHour=20)]})})
    profile = SessionProfile(date='2030-10-09', timeslot_start='11:00', timeslot_end='16:00')
    card = _run(inline_tools.get_hotel_details('', profile, picked_hotel_id=22293))['hotel']
    assert [o['offer_id'] for o in card['available_offers']] == ['covers']
    assert card['offer_id'] == 'covers'


@pytest.mark.parametrize("matching", [True, False])
def test_return_to_older_hotel_details_keeps_requested_hours(monkeypatch, matching):
    wrong = {"ratePlanUuid": "daytime", "availabilityDate": "2026-11-01",
             "startHour": 12, "endHour": 17, "priceEuro": 10000}
    evening = {**wrong, "ratePlanUuid": "evening", "startHour": 15,
               "endHour": 20, "priceEuro": 15450}
    _install(monkeypatch, {"get_hotel_details": FakeResult({
        "hotel": {"hotelId": 22293, "name": "Previous hotel"},
        "offers": [wrong, evening] if matching else [wrong],
    })})
    # Details may quote a price above the search budget: the budget filters a
    # search, not the facts of a hotel the customer asked about.
    p = SessionProfile(date="2026-11-01", timeslot_start="18:00", budget_max=90,
                       last_results=[{"hotel_id": 99, "name": "Another hotel"}])
    h = _run(inline_tools.get_hotel_details("", p, picked_hotel_id=22293))["hotel"]
    if matching:
        assert h["offer_id"] == "evening"
        assert h["price_eur_cents"] == 15450
        assert h["timeslots"] == [{"start": "15:00", "end": "20:00"}]
    else:
        assert h["requested_offer_unavailable"]
        assert "price" not in h and "offer_id" not in h and "timeslots" not in h


def test_details_preserve_verified_shown_formula_over_cheaper_matching_one(monkeypatch):
    offer = {"ratePlanUuid": "shown", "availabilityDate": "2026-11-01",
             "startHour": 15, "endHour": 20, "priceEuro": 15450}
    _install(monkeypatch, {"get_hotel_details": FakeResult({
        "hotel": {"hotelId": 22293, "name": "Previous hotel"},
        "offers": [{**offer, "ratePlanUuid": "cheaper", "priceEuro": 13000}, offer],
    })})
    p = SessionProfile(date="2026-11-01", timeslot_start="18:00", last_results=[{
        "hotel_id": 22293, "name": "Previous hotel", "offer_id": "shown",
        "offer_date": "2026-11-01", "start_time": "15:00", "end_time": "20:00",
    }])
    h = _run(inline_tools.get_hotel_details("", p, picked_hotel_id=22293))["hotel"]
    assert h["offer_id"] == "shown" and h["price_eur_cents"] == 15450


# --- compare_hotels -------------------------------------------------------------------------


def _dated_profile(n=5):
    return SessionProfile(date="2026-11-01", timeslot_start="00:00", last_results=[
        {"hotel_id": i, "name": f"Hotel {i}", "offer_id": f"offer-{i}",
         "offer_date": "2026-11-01", "start_time": "00:00", "end_time": "08:00"}
        for i in range(1, n + 1)
    ])


def receipt(args):
    i = args["hotelId"]
    return {"hotel": {"hotelId": i, "name": f"Hotel {i}"}, "offers": [
        {"ratePlanUuid": f"other-{i}", "availabilityDate": "2026-11-04", "startHour": 10,
         "endHour": 14, "priceEuro": 5000},
        {"ratePlanUuid": f"offer-{i}", "availabilityDate": "2026-11-01", "startHour": 0,
         "endHour": 8, "priceEuro": 9000, "priceEuroWithBookingFees": 9500},
    ]}


def test_undated_comparison_snapshot_cannot_replace_a_dated_shortlist(monkeypatch):
    wrong = [{**receipt({"hotelId": i})["hotel"],
              "bestOffer": receipt({"hotelId": i})["offers"][0]} for i in range(5, 0, -1)]
    session = _install(monkeypatch, {"compare_hotels": FakeResult({"hotels": wrong}),
                                     "get_hotel_details": lambda a: FakeResult(receipt(a))})
    result = _run(inline_tools.compare_hotels("Compare these hotels", _dated_profile()))
    assert [h["id"] for h in result["hotels"]] == [1, 2, 3, 4, 5]
    assert all(h["offer_date"] == "2026-11-01" for h in result["hotels"])
    assert [h["offer_id"] for h in result["hotels"]] == [f"offer-{i}" for i in range(1, 6)]
    assert {name for name, _ in session.calls} == {"get_hotel_details"}
    assert {args["date"] for _, args in session.calls} == {"2026-11-01"}


@pytest.mark.parametrize("change", ["missing", "time", "expired", "identity"])
def test_changed_or_missing_offer_is_not_replaced_with_another_formula(monkeypatch, change):
    def response(args):
        r = deepcopy(receipt(args))
        if change == "missing":
            r["offers"] = r["offers"][:1]
        elif change == "time":
            r["offers"][1]["startHour"] = 10
        elif change == "expired":
            r["offers"][1]["cutoffDeadlineUtc"] = "2020-01-01T00:00:00Z"
        else:
            r["hotel"]["hotelId"] = 99
        return FakeResult(r)
    _install(monkeypatch, {"get_hotel_details": response})
    result = _run(inline_tools.compare_hotels("Compare these hotels", _dated_profile(2)))
    if change == "identity":
        assert not result["ok"]
    else:
        assert result["ok"]
        assert all(not h.get("offer_id") and not h.get("price") for h in result["hotels"])
        assert all(h["shown_offer_unavailable"] for h in result["hotels"])


def test_undated_shortlist_still_uses_one_compare_call(monkeypatch):
    compare = {"hotels": [{"hotelId": i, "name": f"Hotel {i}"} for i in (1, 2)], "bestBy": {"price": 1}}
    session = _install(monkeypatch, {"compare_hotels": FakeResult(compare)})
    profile = SessionProfile(last_results=[{"hotel_id": i, "name": f"Hotel {i}"} for i in (1, 2)])
    result = _run(inline_tools.compare_hotels("compare these hotels", profile))
    assert result["ok"] and result["best_by"] == {"price": 1}
    assert [name for name, _ in session.calls] == ["compare_hotels"]


def test_comparison_discloses_a_displayed_offer_that_could_not_be_revalidated(
    scripted, monkeypatch, fake_profile_store,  # noqa: F811
):
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, _dated_profile(2)))

    def gone(args):
        r = deepcopy(receipt(args))
        r["offers"] = r["offers"][:1]
        return FakeResult(r)

    _install(monkeypatch, {"get_hotel_details": gone})
    llm, _ = scripted(json.dumps({"family": "compare", "language": "en"}), "Both hotels compared.")
    _drive_in(runner, session.id, "Compare these hotels")
    synthesis_prompt = json.dumps(llm.calls[-1]["messages"], ensure_ascii=False)
    assert "could not be revalidated for: Hotel 1, Hotel 2" in synthesis_prompt


def test_closest_slot_cards_are_still_revalidated_by_identity(monkeypatch):
    # Review fix: cards shown as "closest" to the slot do not cover it by
    # definition; the comparison must not call them unavailable for that.
    _install(monkeypatch, {"get_hotel_details": lambda a: FakeResult(receipt(a))})
    profile = _dated_profile(2)
    profile.timeslot_start, profile.timeslot_end = "10:00", "18:00"
    result = _run(inline_tools.compare_hotels("Compare these hotels", profile))
    assert [h["offer_id"] for h in result["hotels"]] == ["offer-1", "offer-2"]
    assert not any(h.get("shown_offer_unavailable") for h in result["hotels"])
