from evals.langfuse_evaluators import response_evaluator


def test_missing_faq_response_does_not_pass_absence_based_assertions():
    scores = response_evaluator(input={}, output={"response": None},
        expected_output={"max_hotels": 0, "message_must_not_contain_any": ["cancelled"]}, metadata={})
    assert len(scores) == 2
    assert all(s.value == "skipped" and s.data_type == "CATEGORICAL" for s in scores)


def test_real_empty_shortlist_can_still_pass_its_narrow_assertion():
    scores = response_evaluator(input={}, output={"response": {"message": "Check your confirmation email.", "hotels": []}},
        expected_output={"max_hotels": 0}, metadata={})
    assert scores[0].value == 1
