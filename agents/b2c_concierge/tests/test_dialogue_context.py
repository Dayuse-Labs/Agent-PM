from types import SimpleNamespace

from b2c_concierge.dialogue_context import recent_user_messages


def event(text, author="user", role="user"):
    return SimpleNamespace(author=author, content=SimpleNamespace(role=role, parts=[SimpleNamespace(text=text)]))


def test_context_contains_only_prior_user_text_and_is_bounded():
    events = [event("old"), event("x" * 900), event("find my booking"),
              event("A hallucinated policy", "b2c_concierge", "model"),
              event("tool result", "leaf", "user"), event("I booked as a guest"), event("no email")]
    assert recent_user_messages(events, "no email") == ["x" * 400, "find my booking", "I booked as a guest"]


def test_repeated_user_question_keeps_prior_occurrence_but_no_current_duplicate():
    assert recent_user_messages([event("where is my booking"), event("where is my booking")],
                                "where is my booking") == ["where is my booking"]
    assert recent_user_messages([], "where is my booking") == []
