from decimal import Decimal

import pytest

from evals.live_pair_budget import BudgetStop, ObservedBudget, amount, production_costs


@pytest.mark.parametrize('value', [None, True, -1, 'nan', 'Infinity', 'bad'])
def test_unaccounted_cost_is_not_zero(value):
    with pytest.raises(ValueError):
        amount(value)


def test_interrupted_dispatch_survives_restart(tmp_path):
    path = tmp_path / 'budget.json'
    ObservedBudget(path, ceiling='60', reserve='20').begin('pair-1')
    with pytest.raises(BudgetStop):
        ObservedBudget(path, ceiling='60', reserve='20').begin('pair-2')


def test_settle_is_cumulative_without_double_counting(tmp_path):
    budget = ObservedBudget(tmp_path / 'budget.json', ceiling='60', reserve='20')
    budget.begin('pair-1')
    budget.settle('pair-1', {'prod:1': '0.04', 'new:session': '0.01'})
    budget.begin('pair-2')
    budget.settle('pair-2', {'prod:1': '0.04', 'prod:2': '0.03', 'new:session': '0.02'})
    assert budget.total == Decimal('0.09')


def test_stops_with_reserve_and_rejects_budget_change(tmp_path):
    path = tmp_path / 'budget.json'
    budget = ObservedBudget(path, ceiling='60', reserve='20')
    budget.begin('pair-1')
    budget.settle('pair-1', {'prod:1': '40'})
    with pytest.raises(BudgetStop):
        budget.begin('pair-2')
    with pytest.raises(ValueError):
        ObservedBudget(path, ceiling='100', reserve='20')


def test_unknown_or_decreasing_accounting_leaves_request_pending(tmp_path):
    budget = ObservedBudget(tmp_path / 'budget.json', ceiling='60', reserve='20')
    budget.begin('pair-1')
    budget.settle('pair-1', {'prod:1': '1'})
    budget.begin('pair-2')
    for costs in [{}, {'prod:2': None}, {'prod:1': '.5'}]:
        with pytest.raises(ValueError):
            budget.settle('pair-2', costs)
        assert budget.state['pending'] == 'pair-2'
        assert budget.total == 1


def test_trace_join_requires_exact_coverage_and_costs():
    trace = {'id': 'a', 'sessionId': 's', 'totalCost': '.01'}
    assert production_costs([trace], 's', 1) == {'production:a': '0.01'}
    for traces, expected in [([], 1), ([trace, trace], 2), ([{**trace, 'sessionId': 'other'}], 1),
                             ([{**trace, 'totalCost': None}], 1)]:
        with pytest.raises(ValueError):
            production_costs(traces, 's', expected)


def test_conversations_do_not_reuse_server_session_cookies():
    import asyncio

    async def exercise():
        import httpx
        from evals.live_pair_budget import conversation_clients

        def legacy(request):
            # Same precedence as deployed _resolve_session_id: cookie before header.
            cookie = request.headers.get('cookie', '')
            sid = cookie.split('=', 1)[1] if cookie else request.headers['x-client-session-id']
            return httpx.Response(200, json={'session_id': sid},
                                  headers={'set-cookie': f'du_chat_sid={sid}; Path=/'})

        transport = httpx.MockTransport(legacy)
        for sid in ['case-one', 'case-two']:
            async with conversation_clients(transport=transport) as (production, candidate):
                for _ in range(2):
                    result = await production.post('https://example.test/chat',
                                                   headers={'x-client-session-id': sid})
                    assert result.json()['session_id'] == sid
                assert not candidate.cookies

    asyncio.run(exercise())


def test_zero_cost_requires_completed_template_evidence():
    from evals.live_pair_budget import local_model_costs
    sid = 'codex-ack'
    row = {'x-replay-session-id': sid, 'x-replay-turn': '1', 'event_type': 'turn',
           'llm_calls': 0, 'status': 'ok', 'route': 'template:ack'}
    assert local_model_costs([row], sid, 1) == {'new_main:codex-ack': '0'}
    for rows in [[], [row, row], [{**row, 'route': 'leaf:faq'}], [{**row, 'llm_calls': None}],
                 [{**row, 'status': 'error'}], [{**row, 'llm_calls': True}]]:
        with pytest.raises(ValueError):
            local_model_costs(rows, sid, 1)


def test_costed_turn_then_free_ack_preserves_cost_and_checks_all_generations():
    from evals.live_pair_budget import local_model_costs
    sid = 'codex-mixed'
    turn = {'x-replay-session-id': sid, 'x-replay-turn': '1', 'event_type': 'turn',
            'llm_calls': 1, 'status': 'ok', 'route': 'leaf:search'}
    call = {**turn, 'event_type': 'llm_call', 'cost_usd': '0.01'}
    ack = {**turn, 'x-replay-turn': '2', 'llm_calls': 0, 'route': 'template:ack'}
    assert local_model_costs([turn, call, ack], sid, 2)['new_main:'+sid] == '0.01'
    assert local_model_costs([turn, call, call, ack], sid, 2)['new_main:'+sid] == '0.02'
    for rows in [[turn, ack], [turn, {**call, 'cost_usd': None}, ack],
                 [turn, call, ack, {**call, 'x-replay-turn': '2'}]]:
        with pytest.raises(ValueError):
            local_model_costs(rows, sid, 2)


def test_unpriced_failure_reserve_is_explicit_separate_and_counts_toward_cap(tmp_path):
    from evals.live_pair_budget import local_model_costs
    rows = [
        {"event_type": "turn", "x-replay-session-id": "s", "x-replay-turn": "1", "llm_calls": 1},
        {"event_type": "llm_call", "x-replay-session-id": "s", "x-replay-turn": "1",
         "service": "concierge", "phase": "triage", "status": "error"},
    ]
    with pytest.raises(ValueError):
        local_model_costs(rows, "s", 1)
    costs = local_model_costs(rows, "s", 1, error_reserve="1")
    assert costs == {"new_main:s": "0", "unpriced-reserve:s:concierge:1:triage:1": "1"}
    budget = ObservedBudget(tmp_path / "budget.json", ceiling="2", reserve="1")
    budget.begin("attempt")
    budget.settle("attempt", costs)
    with pytest.raises(BudgetStop):
        budget.begin("next")
    rows[1]["status"] = "ok"
    with pytest.raises(ValueError):
        local_model_costs(rows, "s", 1, error_reserve="1")
