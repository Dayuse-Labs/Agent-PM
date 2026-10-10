"""Comparison preserves the displayed dated offers, not MCP's undated bestOffer."""
from copy import deepcopy
import asyncio
import json

import pytest

from b2c_concierge import inline_tools
from b2c_concierge.profile import SessionProfile
from .test_inline_tools import _install, _run, FakeResult
from .test_spine import _new_session, _drive_in, _marker_payloads, scripted  # noqa: F401


def profile():
    return SessionProfile(date="2026-11-01", timeslot_start="00:00", last_results=[
        {"hotel_id": i, "name": f"Hotel {i}", "offer_id": f"offer-{i}",
         "offer_date": "2026-11-01", "start_time": "00:00", "end_time": "08:00"}
        for i in range(1, 6)
    ])


def receipt(args):
    i = args["hotelId"]
    return {"hotel": {"hotelId": i, "name": f"Hotel {i}"}, "offers": [
        {"ratePlanUuid": f"other-{i}", "availabilityDate": "2026-11-04", "startHour": 10,
         "endHour": 14, "priceEuro": 5000},
        {"ratePlanUuid": f"offer-{i}", "availabilityDate": "2026-11-01", "startHour": 0,
         "endHour": 8, "priceEuro": 9000, "priceEuroWithBookingFees": 9500},
    ]}


def test_comparison_preserves_requested_positions_order_and_dated_offer(monkeypatch):
    session = _install(monkeypatch, {"get_hotel_details": lambda a: FakeResult(receipt(a))})
    p = profile()
    result = _run(inline_tools.compare_hotels("Compare the third and first", p, comparison_positions=(3, 1)))
    assert result["ok"]
    assert [h["id"] for h in result["hotels"]] == [3, 1]
    assert [h["offer_id"] for h in result["hotels"]] == ["offer-3", "offer-1"]
    assert all(h["offer_date"] == "2026-11-01" and h["timeslots"] == [{"start": "00:00", "end": "08:00"}]
               for h in result["hotels"])
    assert {args["date"] for _, args in session.calls} == {"2026-11-01"}
    assert len(session.calls) == 2


def test_undated_comparison_snapshot_cannot_replace_a_dated_shortlist(monkeypatch):
    wrong = [{**receipt({"hotelId": i})["hotel"],
              "bestOffer": receipt({"hotelId": i})["offers"][0]} for i in range(5, 0, -1)]
    _install(monkeypatch, {"compare_hotels": FakeResult({"hotels": wrong}),
                          "get_hotel_details": lambda a: FakeResult(receipt(a))})
    result = _run(inline_tools.compare_hotels("Compare these hotels", profile()))
    assert [h["id"] for h in result["hotels"]] == [1, 2, 3, 4, 5]
    assert all(h["offer_date"] == "2026-11-01" for h in result["hotels"])


def test_positions_are_grounded_in_current_message():
    from b2c_concierge.triage import _comparison_positions
    assert _comparison_positions({"positions": [3, 1], "evidence": "third and first"}, "Compare third and first") == (3, 1)
    assert _comparison_positions({"positions": [1, 2], "evidence": "first two"}, "Compare third and first") == ()
    assert _comparison_positions({"positions": [True, 2], "evidence": "Compare"}, "Compare") == ()
    assert _comparison_positions([1, 2], "Compare the first two options") == (1, 2)
    assert _comparison_positions([1, 6], "Compare") == ()


def test_real_concierge_comparison_updates_visible_order_and_next_pick(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, profile()))
    calls = _install(monkeypatch, {"get_hotel_details": lambda a: FakeResult(receipt(a))})
    scripted(json.dumps({"family": "compare", "language": "en", "pick": "position", "pick_position": 1,
                         "comparison_positions": [3, 1]}), "Both hotels have the requested midnight slot.")
    events = _drive_in(runner, session.id, "Compare the third and first")
    p = asyncio.run(fake_profile_store.get(session.id))
    assert [h["hotel_id"] for h in p.last_results] == [3, 1]
    from b2c_common.price_comparison import cheaper_reference
    assert cheaper_reference(p.last_results, "EUR")["reference_minor"] == 9500
    markers = [m for m in _marker_payloads(events) if m["event"] == "hotels"]
    assert [h["id"] for h in markers[0]["hotels"]] == [3, 1]
    assert len(calls.calls) == 2
    scripted('{"family":"details","language":"en","pick":"position","pick_position":1}', "Hotel 3 details.")
    _drive_in(runner, session.id, "Details of the first one")
    assert calls.calls[-1][1]["hotelId"] == 3


def test_details_card_owns_next_reference_and_cheaper_total(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    from b2c_common.price_comparison import cheaper_reference
    runner, session = _new_session()
    p = profile()
    p.last_results[0]['offer_totals'] = {'EUR': 6300}
    p.requested_destination = {'kind': 'areas', 'areas': [
        {'query': 'Melun', 'kind': 'municipality', 'country': 'FR', 'evidence': 'Melun'}]}
    asyncio.run(fake_profile_store.set(session.id, p))
    calls = _install(monkeypatch, {'get_hotel_details': lambda a: FakeResult(receipt(a))})
    scripted('{"family":"details","language":"en","pick":"position","pick_position":3}', 'Hotel 3.')
    _drive_in(runner, session.id, 'Tell me about the third one')
    current = asyncio.run(fake_profile_store.get(session.id))
    assert [h['hotel_id'] for h in current.last_results] == [1, 2, 3, 4, 5]
    assert [h['hotel_id'] for h in current.detail_results] == [3]
    assert cheaper_reference(current.detail_results, 'EUR')['reference_minor'] == 9500
    assert current.requested_destination == p.requested_destination
    scripted('{"family":"details","language":"en","information_source":{"value":"offer_facts","evidence":"its exact slot"},"location_update":{"action":"preserve"}}', 'The exact slot.')
    _drive_in(runner, session.id, 'What is its exact slot?')
    assert calls.calls[-1][1]['hotelId'] == 3
    # A relative price request refers to the consultation, not the cheapest
    # item in the earlier search. Leaves never receive/write the detail focus.
    import b2c_concierge.agent as concierge
    seen = []
    async def leaf(leaf, ctx, profile_in, **kwargs):
        seen.append(profile_in)
        return 'No cheaper verified offer', {'results': []}
    scripted('{"family":"search","language":"en","location_update":{"action":"preserve"},"price_comparison":{"value":"lower","evidence":"cheaper"}}', 'No cheaper verified offer')
    monkeypatch.setattr(concierge, '_run_leaf', leaf)
    _drive_in(runner, session.id, 'Anything cheaper?')
    assert seen[0]['price_comparison']['reference_minor'] == 9500
    assert 'detail_results' not in seen[0]
    # But a plural comparison still resolves the original list, after both
    # the detail question and the unsuccessful cheaper search.
    scripted('{"family":"compare","language":"en","comparison_positions":[1,2]}', 'The first two compared.')
    events = _drive_in(runner, session.id, 'Compare the first two options')
    markers = [m for m in _marker_payloads(events) if m['event'] == 'hotels']
    assert [h['id'] for h in markers[0]['hotels']] == [1, 2]
    assert asyncio.run(fake_profile_store.get(session.id)).detail_results is None


def test_detail_focus_is_persisted_but_cannot_be_written_by_a_leaf():
    from b2c_concierge.profile import apply_profile_delta, leaf_profile_view, record_search_shortlist
    p = SessionProfile(city='Paris', detail_results=[{'hotel_id': 3, 'name': 'Hotel 3'}])
    restored = SessionProfile.from_dict(p.to_dict())
    assert restored.detail_results == p.detail_results
    assert 'detail_results' not in leaf_profile_view(restored)
    apply_profile_delta(restored, {'detail_results': {'op': 'set', 'value': [{'hotel_id': 999}]}}, '')
    apply_profile_delta(restored, {'detail_results': {'op': 'clear'}}, '')
    assert restored.detail_results == p.detail_results
    record_search_shortlist(restored, [{'id': 4, 'name': 'New search'}])
    assert restored.detail_results is None


@pytest.mark.parametrize("positions", [(), (1,), (1, 6), (1, 1), (True, 2)])
def test_invalid_selection_cannot_silently_compare_the_whole_list(monkeypatch, positions):
    session = _install(monkeypatch, {})
    assert not _run(inline_tools.compare_hotels("Compare", profile(), comparison_positions=positions))["ok"]
    assert session.calls == []


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
    result = _run(inline_tools.compare_hotels("Compare the first two", profile(), comparison_positions=(1, 2)))
    if change == "identity":
        assert not result["ok"]
    else:
        assert result["ok"]
        assert all(not h.get("offer_id") and not h.get("price") for h in result["hotels"])
        assert all(h["shown_offer_unavailable"] for h in result["hotels"])
