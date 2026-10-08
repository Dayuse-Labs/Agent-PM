import json
from types import SimpleNamespace

from b2c_concierge.a2a_datapart import find_datapart
from faq_agent.response_bridge import capture_policy_evidence, emit_policy_evidence, skip_policy_summary


def capture(ctx, payload, error=False):
    capture_policy_evidence(tool=SimpleNamespace(name='get_faq_conditions'), args={'hotelId': 12},
                            tool_context=ctx, tool_response={'isError': error, 'content': [
                                {'type': 'text', 'text': json.dumps(payload)}]})


def test_raw_policy_scopes_survive_a2a_without_model_summary():
    ctx = SimpleNamespace(state={})
    payload = {'hotel': {'hotelId': 12, 'name': 'Example'}, 'sections': {
        'hotelConditions': 'Deposit $250.'}, 'generalFaq': [
            {'title': 'ID', 'body': 'In the United States, typically 21 years old.'}]}
    capture(ctx, payload)
    reply = emit_policy_evidence(ctx)
    data = find_datapart(reply.parts)
    assert data['faq_evidence'] == [payload]
    assert 'results' not in data  # Policies cannot become hotel cards.
    assert '21' not in reply.parts[0].text  # No generated property-age claim.
    result = skip_policy_summary(ctx, None)
    assert result is not None and not result.content.parts[0].function_call


def test_failed_or_unrelated_payload_never_becomes_policy_evidence():
    for payload, error in [({'sections': {'hotelConditions': 'Bad data'}}, True),
                           ({'error': 'unavailable'}, False), ({'message': 'hello'}, False)]:
        ctx = SimpleNamespace(state={})
        capture(ctx, payload, error)
        assert emit_policy_evidence(ctx) is None
        assert skip_policy_summary(ctx, None) is None


def test_policy_capture_is_invocation_scoped_and_does_not_mutate_payload():
    first, second = SimpleNamespace(state={}), SimpleNamespace(state={})
    raw = {'market': 'US', 'sections': {'hotelConditions': 'ID required.'}}
    capture(first, raw)
    assert raw == {'market': 'US', 'sections': {'hotelConditions': 'ID required.'}}
    assert emit_policy_evidence(second) is None
    assert all(key.startswith('temp:') for key in first.state)


def test_structured_mcp_policy_output_is_supported():
    ctx = SimpleNamespace(state={})
    payload = {'sections': {'hotelConditions': 'Minimum age 18.'}}
    capture_policy_evidence(tool=SimpleNamespace(name='get_faq_conditions'), args={}, tool_context=ctx,
                            tool_response={'isError': False, 'structuredContent': payload, 'content': []})
    assert find_datapart(emit_policy_evidence(ctx).parts)['faq_evidence'] == [payload]
