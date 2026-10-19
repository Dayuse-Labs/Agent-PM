"""Typed budget through the concierge spine (PORT1 slice 3, from #134 + #136 B3).

- the triage's grounded budget owns the cap; a leaf delta can never relabel it;
- no written currency → the display currency (EUR unless the widget says
  otherwise), never a question that blocks the search (B3);
- a budget question after a search is appended to its results, never asked
  instead of them (B3);
- a bare number is a budget only when it answers a budget question (B3).
"""
from __future__ import annotations

import asyncio

import pytest

from google.adk.runners import InMemoryRunner

from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.no_offers import no_offers_line
from b2c_concierge.profile import BUDGET_SOURCE_EXPLICIT, SessionProfile

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

QUESTION = "What is your maximum total budget?"


class TestTypedBudgetThroughSpine:
    def test_usd_survives_leaf_delta_and_later_refinement(self, monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
        fake_leg.response_payload = {"results": [], "profile_delta": {"city": "Orlando", "country_anchor": "US", "budget_max": 100}}
        _scripted_llm(
            monkeypatch,
            '{"family":"search","language":"en","requested_budget":{"amount":100,"currency":"USD","unit":"total","evidence":"under 100 USD"}}',
            "No offers.",
            '{"family":"search","language":"en","requested_budget":null}',
            "Still none.",
        )
        runner = InMemoryRunner(agent=root_agent)
        session = _new_session(runner)
        _run_turn(runner, session.id, "Orlando under 100 USD")
        _run_turn(runner, session.id, "Any area is fine")
        profile = asyncio.run(fake_profile_store.get(session.id))
        assert profile.requested_budget == {"amount": 100.0, "currency": "USD", "unit": "total"}
        assert profile.budget_max is None
        outgoing = find_datapart(fake_leg.seen_outgoing_parts)
        assert outgoing["profile_in"]["requested_budget"] == profile.requested_budget
        assert outgoing["profile_in"]["budget_max"] is None

    def test_hourly_budget_is_not_searched_as_total(self, monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
        llm = _scripted_llm(monkeypatch,
            '{"family":"search","language":"en","requested_budget":{"amount":10,"currency":"USD","unit":"hour","evidence":"10 dollars per hour"}}')
        runner = InMemoryRunner(agent=root_agent)
        session = _new_session(runner)
        text = _run_turn(runner, session.id, "Dallas for 10 dollars per hour")
        assert "maximum total" in text
        assert fake_leg.call_count == 0  # nothing retrieved yet: nothing discarded
        assert len(llm.calls) == 1
        profile = asyncio.run(fake_profile_store.get(session.id))
        assert profile.requested_budget["unit"] == "hour"
        assert profile.budget_max is None

    def test_no_cap_signal_blocks_default_on_cheaper(self, monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
        fake_leg.response_payload = {"results": [], "profile_delta": {"budget_max": 100}}
        _scripted_llm(monkeypatch, '{"family":"search","language":"fr","requested_budget":null}', "Voici les offres.")
        runner = InMemoryRunner(agent=root_agent)
        session = _new_session(runner)
        _run_turn(runner, session.id, "Paris moins cher")
        profile = asyncio.run(fake_profile_store.get(session.id))
        assert profile.requested_budget == {}
        assert profile.budget_max is None

    def test_eur_budget_reaches_the_mcp_cap_and_the_reply_states_fees(self, monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
        fake_leg.response_payload = {"results": [{"id": 1, "name": "Hotel A", "offer_totals": {"EUR": 7500}}],
                                     "profile_delta": {"city": "Paris"}}
        _scripted_llm(monkeypatch,
            '{"family":"search","language":"en","requested_budget":{"amount":80,"currency":"EUR","unit":"total","evidence":"80 euros"}}',
            "Here is Hotel A.")
        runner = InMemoryRunner(agent=root_agent)
        session = _new_session(runner)
        text = _run_turn(runner, session.id, "Paris under 80 euros")
        profile = asyncio.run(fake_profile_store.get(session.id))
        assert profile.budget_max == 80.0 and profile.budget_request_source == BUDGET_SOURCE_EXPLICIT
        assert find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]["budget_max"] == 80.0
        assert text.rstrip().endswith("including booking fees. Any extras still need checking.")


class TestReviewFixes:
    """Second-look fixes on slice 3 (review of the PORT1 branch)."""

    def test_an_unfiltered_named_card_is_never_said_to_fit_the_budget(self, monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
        fake_leg.response_payload = {"results": [{"id": 1, "name": "Novotel", "offer_totals": {"EUR": 9000}}]}
        llm = _scripted_llm(monkeypatch, '{"family":"search","language":"en","requested_budget":null}', "Here is the Novotel.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(
            city="Paris", requested_budget={"amount": 50.0, "currency": "EUR", "unit": "total"}, budget_max=50.0)))
        text = _run_turn(runner, session.id, "and the Novotel Gare de Lyon?")
        assert "fit your" not in text
        assert "fit your" not in llm.calls[-1]["messages"][1]["content"]

    def test_the_budget_question_is_remembered_as_the_question_asked(self, monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
        _scripted_llm(monkeypatch,
            '{"family":"search","language":"en","requested_budget":{"amount":10,"currency":"EUR","unit":"hour","evidence":"10 euros per hour"}}')
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        text = _run_turn(runner, session.id, "Lyon at 10 euros per hour")
        assert asyncio.run(fake_profile_store.get(session.id)).last_clarifying_question == text

    def test_an_unanswered_budget_question_never_blocks_the_next_search(self, monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
        fake_leg.response_payload = {"results": [{"id": 1, "name": "Hotel A"}]}
        _scripted_llm(monkeypatch,
            '{"family":"search","language":"en","requested_budget":{"amount":10,"currency":"EUR","unit":"hour","evidence":"10 euros per hour"}}',
            '{"family":"search","language":"en","requested_budget":null}', "Here is Hotel A.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _run_turn(runner, session.id, "Lyon at 10 euros per hour")
        _run_turn(runner, session.id, "rather tomorrow")
        assert fake_leg.call_count == 1
        assert asyncio.run(fake_profile_store.get(session.id)).requested_budget == {}

    def test_the_appended_currency_question_is_remembered(self, monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
        fake_leg.response_payload = {"results": [{"id": 1, "name": "Hotel A"}],
                                     "profile_delta": {"city": "Paris", "country_anchor": "FR"}}
        _scripted_llm(monkeypatch,
            '{"family":"search","language":"en","requested_budget":{"amount":100,"currency_basis":"dollar","unit":"total","evidence":"$100"}}',
            "Here is Hotel A.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        text = _run_turn(runner, session.id, "Paris under $100")
        question = asyncio.run(fake_profile_store.get(session.id)).last_clarifying_question
        assert question and text.rstrip().endswith(question)


class TestBudgetWithoutWrittenCurrency:
    """PR134-FIX B3: a written amount with no currency never blocks the search
    (as on main), and a budget question never throws away results already
    retrieved."""

    def test_an_amount_without_currency_searches_in_the_display_currency(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A"}], "profile_delta": {"city": "Paris"},
        }
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "requested_budget": {"amount": 100,'
            ' "currency": null, "unit": "total", "evidence": "moins de 100"}}',
            "Voici le Hotel A.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        text = _run_turn(runner, session.id, "à Paris pour moins de 100")

        assert fake_leg.call_count == 1  # never "Dans quelle devise ?" with 0 leaf call
        assert "devise" not in text
        assert len(llm.calls) == 2
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.requested_budget == {"amount": 100.0, "currency": "EUR", "unit": "total"}
        assert find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]["requested_budget"]["currency"] == "EUR"

    def test_the_widget_currency_is_the_unit_of_an_unwritten_amount(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        fake_leg.response_payload = {"results": [], "profile_delta": {"city": "Orlando"}}
        _scripted_llm(monkeypatch,
            '{"family":"search","language":"en","requested_budget":{"amount":100,"unit":"total","evidence":"under 100"}}',
            "No offers.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        asyncio.run(fake_profile_store.set(session.id, SessionProfile(currency="USD")))
        _run_turn(runner, session.id, "Orlando under 100")
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.requested_budget == {"amount": 100.0, "currency": "USD", "unit": "total"}
        assert stored.budget_max is None  # MCP's cap is EUR-only: never a converted amount

    def test_a_budget_question_after_a_search_keeps_its_results(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # "$" in a market the geocode does not establish as a dollar market:
        # the unit genuinely needs asking — but the hotels found stay on screen.
        fake_leg.response_payload = {
            "results": [{"id": 1, "name": "Hotel A"}],
            "profile_delta": {"city": "Paris", "country_anchor": "FR"},
        }
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr", "requested_budget": {"amount": 100,'
            ' "currency": null, "currency_basis": "dollar", "unit": "total", "evidence": "moins de 100$"}}',
            "Voici le Hotel A.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        text = _run_turn(runner, session.id, "à Paris pour moins de 100$")

        assert fake_leg.call_count == 1
        assert "Voici le Hotel A." in text
        assert text.rstrip().endswith("Dans quelle devise est votre budget maximum de 100 au total ?")
        assert len(llm.calls) == 2
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert stored.last_results and stored.last_results[0]["name"] == "Hotel A"


def test_currency_answer_completes_budget_without_switching_display(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    fake_leg.response_payload = {"results": [], "profile_delta": {"city": "Paris", "country_anchor": "FR"}}
    _scripted_llm(monkeypatch,
        '{"family":"search","language":"en","requested_budget":{"amount":50,"currency":null,"currency_basis":"dollar","unit":"total","evidence":"$50"}}',
        '{"family":"details","language":"en","display_currency":"USD","requested_budget":{"currency":"USD","evidence":"USD"}}',
        "No offers in USD either.")
    runner = InMemoryRunner(agent=root_agent)
    session = _new_session(runner)
    text = _run_turn(runner, session.id, "Paris under $50")
    assert "Which currency" in text and fake_leg.call_count == 1
    _run_turn(runner, session.id, "USD")
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.requested_budget == {"amount": 50.0, "currency": "USD", "unit": "total"}
    assert profile.display_currency is None and profile.requested_currency is None
    assert fake_leg.call_count == 2


class TestBareNumber:
    def test_a_bare_number_answering_a_budget_question_is_never_auto_widened(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # cbe88b9's "100" case, ported (PR134-FIX B3, Fabien 2026-10-12).
        fake_leg.response_payload = {"results": ["hotel A"]}
        _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "en"}', QUESTION,
            '{"family":"search","language":"en","requested_budget":'
            '{"amount":100,"unit":"total","evidence":"100","answer_to":"What is your maximum total budget?"}}',
            "No luck yet.",
            '{"family": "search", "language": "en"}', "Still nothing.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        fake_leg.text = QUESTION  # Q11: the question is the LEAF's own text, not the synthesis's
        _run_turn(runner, session.id, "A day room in Paris please")
        fake_leg.text = "results: hotel A"
        fake_leg.response_payload = {"results": [], "profile_delta": {"budget_max": 100}}
        _run_turn(runner, session.id, "100")
        fake_leg.response_payload = {"results": []}
        _run_turn(runner, session.id, "still looking")

        stored = asyncio.run(fake_profile_store.get(session.id))
        assert fake_leg.call_count == 3
        assert stored.budget_request_source == BUDGET_SOURCE_EXPLICIT
        assert stored.consecutive_empty_searches == 2
        assert stored.budget_max == 100.0
        assert stored.auto_widen_disclosure is None

    def test_a_bare_number_nobody_asked_for_is_not_a_budget(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        # "75008" may be a postcode: the leaf's own priceRangeMax cannot make it a cap.
        fake_leg.response_payload = {"results": [{"id": 1, "name": "Hotel A"}],
                                     "profile_delta": {"budget_max": 75008}}
        _scripted_llm(monkeypatch,
            '{"family":"search","language":"fr","requested_budget":{"amount":75008,"unit":"total","evidence":"75008"}}',
            "Voici le Hotel A.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _run_turn(runner, session.id, "75008")
        stored = asyncio.run(fake_profile_store.get(session.id))
        assert fake_leg.call_count == 1  # the search still runs
        assert stored.budget_max is None and stored.requested_budget == {}


def test_empty_results_keep_budget_authority_in_synthesis(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    fake_leg.text = "No hotels for your 50 EUR budget."
    fake_leg.response_payload = {
        "results": [], "profile_delta": {"budget_max": 50},
        "search_context": {"city": "Arlington", "date": "2026-10-10"},
    }
    llm = _scripted_llm(monkeypatch,
        '{"family":"search","language":"en","requested_budget":null}', "No offers for this date.")
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    _run_turn(runner, session.id, "Arlington on October 10")
    prompt = llm.calls[-1]["messages"][1]["content"]
    assert "No numeric budget was established" in prompt
    assert asyncio.run(fake_profile_store.get(session.id)).budget_max is None


def test_no_offers_line_states_the_typed_cap_with_its_fees():
    line = no_offers_line({"city": "Orlando"}, "en",
                          requested_budget={"amount": 100.0, "currency": "USD", "unit": "total"})
    assert "with a total at or below 100 USD, including booking fees" in line
    legacy = no_offers_line({"city": "Lyon", "budget_max": 20}, "fr")
    assert "20 €" in legacy


# --- PORT1 slice 4: "moins cher" (from #134) ----------------------------------------------------


def test_cheaper_overrides_more_flag_and_persists_separate_from_user_budget(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    import json
    _scripted_llm(monkeypatch, json.dumps({'family':'search','language':'en','wants_more_options':True,
                   'price_comparison':{'value':'lower','evidence':'cheaper'},'requested_budget':None}),
                  'Here are lower-priced alternatives.',
                  json.dumps({'family':'search','language':'en','wants_more_options':True,'requested_budget':None}),
                  'Here is another matching option.')
    runner=InMemoryRunner(root_agent)
    session=_new_session(runner)
    origin={'type':'gps','latitude':48.6,'longitude':1.6}
    asyncio.run(fake_profile_store.set(session.id,SessionProfile(
        city='Yvelines',date='2026-10-10',amenities=['spa'],distance_origin=origin,search_cursor=2,
        shown_hotel_ids=[12],search_anchor={'type':'gps','lat':48.6,'lon':1.6},requested_budget={},
        last_results=[{'hotel_id':12,'name':'Example','offer_id':'shown','offer_date':'2026-10-10','offer_totals':{'EUR':11700}}],
    )))
    fake_leg.response_payload={'results':[{'id':13,'name':'Lower','offer_id':'lower','offer_date':'2026-10-10','offer_totals':{'EUR':9900}}]}
    _run_turn(runner,session.id,'Anything cheaper?')
    outgoing=find_datapart(fake_leg.seen_outgoing_parts)['profile_in']
    assert outgoing['search_cursor']==0
    assert outgoing['price_comparison']['reference_minor']==11700
    assert outgoing['requested_budget']=={}
    assert outgoing['amenities']==['spa']
    _run_turn(runner,session.id,'Show other options')
    outgoing=find_datapart(fake_leg.seen_outgoing_parts)['profile_in']
    assert outgoing['search_cursor']==1
    assert outgoing['price_comparison']['reference_minor']==11700


def test_price_reference_missing_stops_before_search(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    _scripted_llm(monkeypatch,'{"family":"search","language":"en","price_comparison":{"value":"lower","evidence":"cheaper"}}')
    runner=InMemoryRunner(root_agent)
    session=_new_session(runner)
    asyncio.run(fake_profile_store.set(session.id,SessionProfile(city='Paris',last_results=[{'hotel_id':12,'name':'Unpriced'}])))
    answer=_run_turn(runner,session.id,'Anything cheaper?')
    assert fake_leg.call_count==0 and 'verified total' in answer


@pytest.mark.parametrize('update,message', [
    ('"requested_budget":{"amount":150,"currency":"EUR","unit":"total","evidence":"150 EUR"}', 'max 150 EUR'),
    ('"price_comparison":{"value":"clear","evidence":"any price"}', 'any price'),
])
def test_new_budget_or_price_retraction_clears_only_relative_constraint(monkeypatch,fake_leg,fake_profile_store,update,message):  # noqa: F811
    _scripted_llm(monkeypatch,'{"family":"search","language":"en",'+update+'}', 'Matching offers.')
    runner=InMemoryRunner(root_agent)
    session=_new_session(runner)
    asyncio.run(fake_profile_store.set(session.id,SessionProfile(city='Paris',requested_budget={},amenities=['spa'],
        price_comparison={'relation':'lower','currency':'EUR','reference_minor':11700})))
    fake_leg.response_payload={'results':[{'id':13,'name':'Example'}]}
    _run_turn(runner,session.id,message)
    outgoing=find_datapart(fake_leg.seen_outgoing_parts)['profile_in']
    assert outgoing['price_comparison'] is None and outgoing['amenities']==['spa']


def test_an_empty_cheaper_page_says_so_without_claiming_no_availability(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    llm = _scripted_llm(monkeypatch,
        '{"family":"search","language":"en","price_comparison":{"value":"lower","evidence":"cheaper"}}')
    runner=InMemoryRunner(root_agent)
    session=_new_session(runner)
    asyncio.run(fake_profile_store.set(session.id,SessionProfile(city='Paris',requested_budget={},
        last_results=[{'hotel_id':12,'name':'Example','offer_id':'shown','offer_date':'2026-10-10','offer_totals':{'EUR':11700}}])))
    fake_leg.response_payload={'results':[]}
    answer=_run_turn(runner,session.id,'Anything cheaper?')
    assert 'strictly cheaper than 117 EUR' in answer and 'does not mean that no offers are available' in answer
    assert len(llm.calls) == 1  # triage only: the code-owned notice needs no synthesis
    stored = asyncio.run(fake_profile_store.get(session.id))
    assert stored.auto_widen_disclosure is None and stored.price_comparison['reference_minor'] == 11700


def test_cheaper_outcome_reaches_the_synthesis(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    llm = _scripted_llm(monkeypatch,
        '{"family":"search","language":"en","price_comparison":{"value":"lower","evidence":"cheaper"}}',
        'A cheaper option.')
    runner=InMemoryRunner(root_agent)
    session=_new_session(runner)
    asyncio.run(fake_profile_store.set(session.id,SessionProfile(city='Paris',requested_budget={},
        last_results=[{'hotel_id':12,'name':'Example','offer_id':'shown','offer_date':'2026-10-10','offer_totals':{'EUR':11700}}])))
    fake_leg.response_payload={'results':[{'id':13,'name':'Lower','offer_totals':{'EUR':9900}}],
                               'price_comparison':{'relation':'lower','currency':'EUR','reference_minor':11700}}
    _run_turn(runner,session.id,'Anything cheaper?')
    prompt = llm.calls[-1]['messages'][1]['content']
    assert 'RELATIVE PRICE REQUEST' in prompt and 'saving 18 EUR' in prompt


def test_a_cheaper_reference_ends_with_the_next_non_paging_search(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    # Review fix: "cheaper" is relative to the offers shown, not a standing cap.
    _scripted_llm(monkeypatch, '{"family":"search","language":"en"}', 'Lyon offers.')
    runner=InMemoryRunner(root_agent)
    session=_new_session(runner)
    asyncio.run(fake_profile_store.set(session.id,SessionProfile(city='Paris',requested_budget={},
        price_comparison={'relation':'lower','currency':'EUR','reference_minor':5400})))
    fake_leg.response_payload={'results':[{'id':13,'name':'Example'}]}
    _run_turn(runner,session.id,'and in Lyon?')
    assert find_datapart(fake_leg.seen_outgoing_parts)['profile_in']['price_comparison'] is None


def test_the_reference_question_is_remembered(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    _scripted_llm(monkeypatch,'{"family":"search","language":"en","price_comparison":{"value":"lower","evidence":"cheaper"}}')
    runner=InMemoryRunner(root_agent)
    session=_new_session(runner)
    asyncio.run(fake_profile_store.set(session.id,SessionProfile(city='Paris',last_results=[{'hotel_id':12,'name':'Unpriced'}])))
    answer=_run_turn(runner,session.id,'Anything cheaper?')
    assert asyncio.run(fake_profile_store.get(session.id)).last_clarifying_question == answer
