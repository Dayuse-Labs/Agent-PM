"""Triage tests — regex fast-paths and the mocked LLM classify (offline)."""
import asyncio
from types import SimpleNamespace

import pytest

import b2c_concierge.triage as triage_module
from b2c_concierge.budget import TurnBudget
from b2c_concierge.triage import (
    FALLBACK_FAMILY,
    FAMILIES,
    Triage,
    classify,
    fallback_family,
    guess_language,
    is_social_ack,
)


def _llm_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _classify(message: str, budget: TurnBudget | None = None) -> Triage:
    return asyncio.run(classify(message, budget or TurnBudget()))


class TestSocialAckFastPath:
    @pytest.mark.parametrize(
        "message",
        [
            "Bonjour !",
            "bonjour",
            "Merci beaucoup !!",
            "Hello",
            "ok merci",
            "Bonne journée",
            "Thanks!",
            "salut 👍",
        ],
    )
    def test_pure_social_messages_are_acks(self, message):
        assert is_social_ack(message)

    @pytest.mark.parametrize(
        "message",
        [
            "",
            "Bonjour, je cherche un hôtel à Paris",
            "merci de me trouver un hôtel",
            "hello, any hotel in London today?",
            "quelles sont les conditions d'annulation ?",
        ],
    )
    def test_substantive_messages_are_not_acks(self, message):
        assert not is_social_ack(message)


class TestLanguageGuess:
    def test_french(self):
        assert guess_language("je cherche un hôtel à Paris demain") == "fr"

    def test_english_default(self):
        assert guess_language("any day-use room in London?") == "en"


class TestFallbackFamily:
    @pytest.mark.parametrize(
        ("message", "family"),
        [
            ("quelles sont les conditions d'annulation ?", "faq"),
            ("comment ça marche le remboursement ?", "faq"),
            ("can I cancel my booking?", "faq"),  # faq wins over booking on cancel intent
            ("compare ces deux hôtels", "compare"),
            ("quels équipements a cet hôtel ?", "details"),
            ("je veux réserver", "booking"),
            ("je cherche un hôtel à Paris", FALLBACK_FAMILY),
            ("n'importe quoi 42", FALLBACK_FAMILY),
        ],
    )
    def test_keyword_families(self, message, family):
        assert fallback_family(message) == family


class TestLlmClassify:
    def test_valid_json_drives_family_and_language(self, monkeypatch):
        async def fake_acompletion(**kwargs):
            return _llm_response('{"family": "faq", "language": "fr"}')

        monkeypatch.setattr(triage_module.litellm, "acompletion", fake_acompletion)
        budget = TurnBudget()
        result = _classify("quelles conditions ?", budget)
        assert result == Triage("faq", "fr", used_llm=True)
        assert budget.llm_calls == 1
        assert budget.phases == ["triage"]

    def test_llm_failure_falls_back_to_regex(self, monkeypatch):
        async def fake_acompletion(**kwargs):
            raise TimeoutError("triage timeout")

        monkeypatch.setattr(triage_module.litellm, "acompletion", fake_acompletion)
        budget = TurnBudget()
        result = _classify("quelles sont les conditions d'annulation ?", budget)
        assert result == Triage("faq", "fr", used_llm=False)
        # The attempt consumed the budget slot all the same.
        assert budget.llm_calls == 1

    def test_garbage_json_falls_back_to_regex_family(self, monkeypatch):
        async def fake_acompletion(**kwargs):
            return _llm_response("sorry, no JSON today")

        monkeypatch.setattr(triage_module.litellm, "acompletion", fake_acompletion)
        result = _classify("je cherche un hôtel à Lyon")
        assert result.family == FALLBACK_FAMILY
        assert result.language == "fr"

    def test_unknown_family_falls_back_to_regex_family(self, monkeypatch):
        async def fake_acompletion(**kwargs):
            return _llm_response('{"family": "hack_the_planet", "language": "xx"}')

        monkeypatch.setattr(triage_module.litellm, "acompletion", fake_acompletion)
        result = _classify("compare ces deux hôtels")
        assert result.family == "compare"
        assert result.language in ("fr", "en")

    def test_families_are_the_routing_keys(self):
        # The triage vocabulary and the routing table must never drift apart.
        from b2c_concierge.routing import ROUTES

        assert set(FAMILIES) == set(ROUTES)
