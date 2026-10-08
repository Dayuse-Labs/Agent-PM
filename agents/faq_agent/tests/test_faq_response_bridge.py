import json
from types import SimpleNamespace

from b2c_concierge.a2a_datapart import find_datapart
from faq_agent.response_bridge import capture_policy_evidence, emit_policy_evidence, skip_policy_summary, mark_policy_attempt


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
        assert find_datapart(emit_policy_evidence(ctx).parts)['faq_evidence'] == []
        assert skip_policy_summary(ctx, None) is None


def test_policy_capture_is_invocation_scoped_and_does_not_mutate_payload():
    first, second = SimpleNamespace(state={}), SimpleNamespace(state={})
    raw = {'market': 'US', 'sections': {'hotelConditions': 'ID required.'}}
    capture(first, raw)
    assert raw == {'market': 'US', 'sections': {'hotelConditions': 'ID required.'}}
    assert find_datapart(emit_policy_evidence(second).parts)['faq_evidence'] == []
    assert all(key.startswith('temp:') for key in first.state)


def test_structured_mcp_policy_output_is_supported():
    ctx = SimpleNamespace(state={})
    payload = {'sections': {'hotelConditions': 'Minimum age 18.'}}
    capture_policy_evidence(tool=SimpleNamespace(name='get_faq_conditions'), args={}, tool_context=ctx,
                            tool_response={'isError': False, 'structuredContent': payload, 'content': []})
    assert find_datapart(emit_policy_evidence(ctx).parts)['faq_evidence'] == [payload]


def test_failed_lookup_ends_model_loop_and_sends_unverified_diagnostic():
    ctx = SimpleNamespace(state={})
    mark_policy_attempt(SimpleNamespace(name='get_faq_conditions'), {}, ctx)
    capture(ctx, {'error': 'upstream unavailable'}, error=True)
    end = skip_policy_summary(ctx, None)
    assert end is not None and not end.content.parts[0].function_call
    payload = find_datapart(emit_policy_evidence(ctx).parts)
    assert payload['faq_evidence'] == []
    assert payload['faq_diagnostics']['source_verified'] is False


def test_model_prose_without_lookup_cannot_be_exposed_as_verified_faq():
    ctx = SimpleNamespace(state={})
    result = emit_policy_evidence(ctx)
    assert result is not None
    assert find_datapart(result.parts)['faq_diagnostics']['source_verified'] is False
    assert 'could not be checked' in result.parts[0].text


def test_faq_lookup_requirement_reaches_litellm_transport(monkeypatch):
    import asyncio
    from google.adk.models.lite_llm import LiteLLMClient
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types
    from litellm import ModelResponse
    from faq_agent.agent import MODEL
    requests = []
    class Client(LiteLLMClient):
        async def acompletion(self, **kwargs):
            requests.append(kwargs)
            return ModelResponse(model="gpt-4o-mini", choices=[{
                "message": {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_faq", "type": "function", "function": {
                        "name": "get_faq_conditions", "arguments": '{"market":"FR"}'}}]},
                "finish_reason": "tool_calls"}])
    monkeypatch.setattr(MODEL, 'llm_client', Client())
    request = LlmRequest(contents=[types.Content(role='user', parts=[types.Part(text='Question')])],
                         config=types.GenerateContentConfig(tools=[types.Tool(function_declarations=[
                             types.FunctionDeclaration(name='get_faq_conditions')])]))
    async def run():
        return [event async for event in MODEL.generate_content_async(request)]
    events = asyncio.run(run())
    assert events and requests[0]['tool_choice'] == 'required'
    assert requests[0]['tools'][0]['function']['name'] == 'get_faq_conditions'


def oversized_lookup(ctx):
    tool = SimpleNamespace(name='get_faq_conditions')
    args = {'market': 'CH', 'topic': 'all'}
    mark_policy_attempt(tool, args, ctx)
    capture_policy_evidence(tool, args, ctx, {
        'isError': True, 'structuredContent': {
            'error': {'kind': 'ResultTooLargeError', 'length': 69037}}})
    return tool


def test_oversized_all_topics_can_narrow_once_and_preserve_source_scope():
    ctx = SimpleNamespace(state={})
    tool = oversized_lookup(ctx)
    assert skip_policy_summary(ctx, None) is None
    args = {'market': 'CH', 'topic': 'booking'}
    assert mark_policy_attempt(tool, args, ctx) is None
    payload = {'market': 'CH', 'generalFaq': [{'title': 'Privacy', 'body': 'Official rule'}]}
    capture_policy_evidence(tool, args, ctx, {'structuredContent': payload})
    assert skip_policy_summary(ctx, None) is not None
    assert find_datapart(emit_policy_evidence(ctx).parts)['faq_evidence'] == [payload]


def test_oversized_retry_cannot_repeat_all_topics_or_switch_market():
    for args in [{'market': 'CH', 'topic': 'all'}, {'market': 'FR', 'topic': 'booking'}]:
        ctx = SimpleNamespace(state={})
        tool = oversized_lookup(ctx)
        blocked = mark_policy_attempt(tool, args, ctx)
        assert blocked is not None and blocked['isError'] is True
        assert skip_policy_summary(ctx, None) is not None
        assert not find_datapart(emit_policy_evidence(ctx).parts)['faq_diagnostics']['source_verified']


def test_second_oversized_result_ends_without_retry_loop():
    ctx = SimpleNamespace(state={})
    tool = oversized_lookup(ctx)
    args = {'market': 'CH', 'topic': 'booking'}
    mark_policy_attempt(tool, args, ctx)
    capture_policy_evidence(tool, args, ctx, {'isError': True, 'structuredContent': {
        'error': {'kind': 'ResultTooLargeError'}}})
    assert skip_policy_summary(ctx, None) is not None
    assert find_datapart(emit_policy_evidence(ctx).parts)['faq_evidence'] == []
