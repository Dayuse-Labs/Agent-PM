from types import SimpleNamespace

from google.genai import types

from hotel_search_agent.response_bridge import encode_datapart
from hotel_search_agent.named_destination_plan import (
    enforce_named_destination, reset_named_destination, select_named_destination,
)


def _context(authoritative=True):
    return SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[
        types.Part(text="Hongkong"), encode_datapart({"profile_in": {
            "requested_destination": {"kind": "hotel", "query": "Rambler oasis hotel", "city": "Hongkong"},
        }, "query_params": {"destination_authoritative": authoritative}}),
    ]))


def test_parent_reply_calls_original_name_once_without_model_or_persistent_leaf_state():
    ctx = _context()
    reset_named_destination(ctx)
    result = select_named_destination(ctx, object())
    call = result.content.parts[0].function_call
    assert call.name == "find_hotel_by_name" and call.args == {"name": "Rambler oasis hotel", "cityName": "Hongkong"}
    assert select_named_destination(ctx, object()) is None
    reset_named_destination(ctx)
    assert select_named_destination(ctx, object()) is not None


def test_named_lookup_arguments_are_owned_and_city_search_cannot_replace_hotel():
    ctx = _context()
    args = {"name": "Hongkong", "cityName": "Paris"}
    assert enforce_named_destination(SimpleNamespace(name="find_hotel_by_name"), args, ctx) is None
    assert args == {"name": "Rambler oasis hotel", "cityName": "Hongkong"}
    for name in ("geocode_location", "search_offers"):
        assert enforce_named_destination(SimpleNamespace(name=name), {}, ctx)["error"] == "named_destination_required"


def test_old_request_without_current_authority_does_not_intercept_new_search():
    ctx = _context(False)
    assert select_named_destination(ctx, object()) is None
    assert enforce_named_destination(SimpleNamespace(name="search_offers"), {}, ctx) is None


def test_actual_adk_turn_executes_owned_lookup_without_calling_the_model():
    import asyncio
    from google.adk.agents import LlmAgent
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    class NoModel(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            raise AssertionError("Named lookup and completed result need no model scheduling")
            yield  # pragma: no cover

    calls = []
    async def find_hotel_by_name(name: str, cityName: str) -> dict:
        calls.append((name, cityName))
        return {"hotelId": 11370, "name": "Rambler Oasis Hotel"}

    def after(tool, args, tool_context, tool_response):
        tool_context.state["temp:done"] = True

    def done(callback_context, llm_request):
        if callback_context.state.get("temp:done"):
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Resolved")]))

    agent = LlmAgent(name="named_flow", model=NoModel(model="never"),
                     tools=[find_hotel_by_name], before_agent_callback=reset_named_destination,
                     before_model_callback=[done, select_named_destination],
                     before_tool_callback=enforce_named_destination, after_tool_callback=after)
    async def run():
        service = InMemorySessionService()
        session = await service.create_session(app_name="test", user_id="test")
        runner = Runner(app_name="test", agent=agent, session_service=service)
        return [event async for event in runner.run_async(user_id="test", session_id=session.id,
                                                         new_message=_context().user_content)]
    events = asyncio.run(run())
    assert calls == [("Rambler oasis hotel", "Hongkong")]
    assert events[-1].content.parts[0].text == "Resolved"
