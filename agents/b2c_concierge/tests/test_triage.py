"""Triage tests — regex fast-paths and the mocked LLM classify (offline)."""
import asyncio
from types import SimpleNamespace

import pytest

import b2c_concierge.triage as triage_module
from b2c_concierge.budget import TurnBudget
from b2c_concierge.triage import (
    BOOKING_CONFIRMATIONS,
    FALLBACK_FAMILY,
    FALLBACK_PICK,
    FAMILIES,
    LANGUAGES,
    PICKS,
    TEMPLATE_LANGUAGES,
    Triage,
    classify,
    fallback_family,
    fallback_pick,
    guess_language,
    is_social_ack,
    response_language,
)


def _llm_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _classify(message: str, budget: TurnBudget | None = None) -> Triage:
    return asyncio.run(classify(message, budget or TurnBudget()))


def _script(monkeypatch, payload: str) -> None:
    """Module-level twin of TestPickClassification._with_llm, for the P1 slot
    tests below (they are plain classes, not part of that fixture's family)."""

    async def fake_acompletion(**kwargs):
        return _llm_response(payload)

    monkeypatch.setattr(triage_module.litellm, "acompletion", fake_acompletion)


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


class TestTemplateLanguage:
    """The 7 languages for a template answer (UX2, 2026-08-27) — established
    conversation language, then client locale, then the message's own
    detected language."""

    def test_profile_language_wins(self):
        assert triage_module.template_language("fr", "en-GB", "hello") == "fr"

    def test_locale_beats_the_guess_on_a_bare_ok(self):
        assert triage_module.template_language(None, "fr-FR", "ok") == "fr"

    def test_a_now_supported_locale_beats_the_french_hints_guess(self):
        # UX2 widened templates.py to 7 languages: a declared "es" locale now
        # wins, including over a message that would trip the French-hints
        # guess (piège: an Italian/Spanish message can match `_FR_HINTS`).
        assert triage_module.template_language(None, "es-ES", "je cherche un hôtel") == "es"

    def test_unsupported_locale_answers_english(self):
        # Fabien (PR #34 review): no translation for the declared language →
        # English, even when the message text would trip the French-hints guess.
        assert triage_module.template_language(None, "ja-JP", "je cherche un hôtel") == "en"

    def test_no_locale_falls_back_to_the_message_guess(self):
        assert triage_module.template_language(None, None, "je cherche un hôtel") == "fr"

    def test_no_signal_defaults_to_english(self):
        assert triage_module.template_language(None, None, "ok") == "en"

    def test_locale_response_language_maps_primary_tag(self):
        assert triage_module.locale_response_language("fr-FR") == "fr"
        assert triage_module.locale_response_language("en") == "en"
        # UX2: all 7 recognized languages are now answerable, pt included.
        assert triage_module.locale_response_language("pt-PT") == "pt"
        assert triage_module.locale_response_language("ja-JP") is None
        assert triage_module.locale_response_language(None) is None


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


class TestPickClassification:
    """S-CX5. WHICH hotel a message points at, when it points at one by a
    property rather than by name. Understanding the phrasing is the LLM's job
    (Fabien, 2026-07-20: don't push determinism into comprehension); this file
    only checks the contract around it — closed enum, validated, with the same
    regex recovery path every other triage field already has."""

    def _with_llm(self, monkeypatch, payload: str):
        async def fake_acompletion(**kwargs):
            return _llm_response(payload)

        monkeypatch.setattr(triage_module.litellm, "acompletion", fake_acompletion)

    def test_the_llm_pick_is_carried_through(self, monkeypatch):
        self._with_llm(monkeypatch, '{"family": "booking", "language": "fr", "pick": "cheapest"}')
        result = _classify("ok je veux booké le moins cher")
        assert result == Triage("booking", "fr", used_llm=True, pick="cheapest")

    def test_pick_is_independent_of_family(self, monkeypatch):
        """"montre-moi le moins cher" is a search-family message that still
        points at one hotel on screen."""
        self._with_llm(monkeypatch, '{"family": "search", "language": "fr", "pick": "cheapest"}')
        assert _classify("montre-moi le moins cher").pick == "cheapest"

    def test_an_absent_pick_key_is_none(self, monkeypatch):
        """Older/looser model output must never be read as a pick."""
        self._with_llm(monkeypatch, '{"family": "search", "language": "fr"}')
        assert _classify("un hôtel à Paris").pick == FALLBACK_PICK

    def test_explicit_position_survives_an_omitted_redundant_pick_tag(self, monkeypatch):
        self._with_llm(monkeypatch, '{"family":"details","language":"en","pick_position":1}')
        result = _classify("Tell me more about the first option")
        assert (result.pick, result.pick_position) == ("position", 1)

    @pytest.mark.parametrize("pick", ["none", "most_luxurious", None])
    def test_position_does_not_override_an_explicit_conflicting_pick_tag(self, monkeypatch, pick):
        import json
        self._with_llm(monkeypatch, json.dumps({"family":"details", "language":"en", "pick":pick, "pick_position":1}))
        result = _classify("Tell me more")
        assert (result.pick, result.pick_position) == (FALLBACK_PICK, None)

    def test_a_value_outside_the_enum_is_rejected(self, monkeypatch):
        self._with_llm(
            monkeypatch, '{"family": "search", "language": "fr", "pick": "most_luxurious"}'
        )
        assert _classify("le plus luxueux").pick == FALLBACK_PICK

    def test_the_prompt_teaches_the_superlative_vs_comparative_split(self):
        """The distinction the whole fix rests on has to be IN the prompt, not
        only in a test's expectations."""
        instruction = triage_module._TRIAGE_INSTRUCTION
        assert '"pick"' in instruction
        for value in PICKS:
            assert value in instruction
        assert "cheaper" in instruction and "moins cher" in instruction


class TestPerRoleLlmParams:
    """Latency audit 2026-07-28 — the triage call takes its model from
    DAYUSE_MODEL_TRIAGE (falling back to DAYUSE_MODEL), a bounded max_tokens,
    and a provider-aware reasoning cap. The no-op lock matters most: with none
    of the new env vars set, the request must stay bit-identical to before."""

    def _capture(self, monkeypatch) -> dict:
        captured: dict = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)
            return _llm_response('{"family": "search", "language": "fr"}')

        monkeypatch.setattr(triage_module.litellm, "acompletion", fake_acompletion)
        return captured

    def test_no_new_kwargs_when_env_is_unset(self, monkeypatch):
        for var in ("DAYUSE_MODEL", "DAYUSE_MODEL_TRIAGE", "DAYUSE_REASONING_EFFORT"):
            monkeypatch.delenv(var, raising=False)
        captured = self._capture(monkeypatch)
        _classify("un hôtel à Paris")
        assert captured["model"] == "gpt-4o-mini"
        assert "reasoning_effort" not in captured
        assert "extra_body" not in captured
        assert captured["temperature"] == 0.0  # unchanged from pre-audit behaviour
        # The default cap is the one deliberate change: bounded triage output.
        assert captured["max_tokens"] == 768

    def test_role_model_beats_the_shared_slug(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_MODEL", "gpt-5.2")
        monkeypatch.setenv("DAYUSE_MODEL_TRIAGE", "gpt-4o-mini")
        captured = self._capture(monkeypatch)
        _classify("un hôtel à Paris")
        assert captured["model"] == "gpt-4o-mini"

    def test_reasoning_cap_reaches_a_reasoning_model(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_MODEL", "gpt-5.2")
        monkeypatch.delenv("DAYUSE_MODEL_TRIAGE", raising=False)
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "low")
        captured = self._capture(monkeypatch)
        _classify("un hôtel à Paris")
        assert captured["reasoning_effort"] == "low"
        # The collision live-caught 2026-07-28: temperature + effort≠none on
        # gpt-5* = UnsupportedParamsError → temperature must yield to the cap.
        assert "temperature" not in captured

    def test_reasoning_cap_never_leaks_to_a_non_reasoning_model(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_MODEL", "gpt-5.2")
        monkeypatch.setenv("DAYUSE_MODEL_TRIAGE", "gpt-4o-mini")
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "low")
        captured = self._capture(monkeypatch)
        _classify("un hôtel à Paris")
        assert "reasoning_effort" not in captured
        assert "extra_body" not in captured

    def test_max_tokens_zero_disables_the_cap(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_MAX_TOKENS_TRIAGE", "0")
        captured = self._capture(monkeypatch)
        _classify("un hôtel à Paris")
        assert "max_tokens" not in captured

    def test_regex_recovery_only_when_the_llm_is_down(self, monkeypatch):
        async def fake_acompletion(**kwargs):
            raise TimeoutError("triage timeout")

        monkeypatch.setattr(triage_module.litellm, "acompletion", fake_acompletion)
        assert _classify("ok je veux booké le moins cher").pick == "cheapest"
        assert _classify("tu as quelque chose de moins cher ?").pick == FALLBACK_PICK

    @pytest.mark.parametrize(
        "message,expected",
        [
            ("ok je veux booké le moins cher", "cheapest"),
            ("je prends la moins chère", "cheapest"),
            ("les moins chers", "cheapest"),
            ("book the cheapest", "cheapest"),
            ("le meilleur prix", "cheapest"),
            # Comparative: a new, lower-budget search — never a pick.
            ("tu as quelque chose de moins cher ?", FALLBACK_PICK),
            ("un hôtel moins cher", FALLBACK_PICK),
            ("cheaper please", FALLBACK_PICK),
            ("c'est trop cher", FALLBACK_PICK),
        ],
    )
    def test_fallback_pick_separates_superlative_from_comparative(self, message, expected):
        assert fallback_pick(message) == expected


class TestP1Slots:
    """P1-1 (audit 2026-07-30 §P1): the 5 slots that moved from fr/en regex in
    profile.py to the classify already paid for. Contract for all of them: an
    absent or malformed value is None — "no LLM signal, use the regex" — and
    NEVER a default answer, because a consumer reading None as False would
    silently turn a skipped key into a negative."""

    def test_all_five_slots_are_carried_through(self, monkeypatch):
        _script(
            monkeypatch,
            '{"family": "booking", "language": "es", "affirmative": true,'
            ' "booking_confirmation": "confirm", "wants_more_options": false,'
            ' "bare_budget_value": 80, "hotel_name": "Villa Paris Orly"}',
        )
        t = _classify("sí, confírmalo")
        assert t.affirmative is True
        assert t.booking_confirmation == "confirm"
        assert t.wants_more_options is False
        assert t.bare_budget_value == 80.0
        assert t.hotel_name == "Villa Paris Orly"

    def test_absent_keys_are_none_not_false(self, monkeypatch):
        _script(monkeypatch, '{"family": "search", "language": "fr"}')
        t = _classify("un hotel a lyon")
        assert t.affirmative is None
        assert t.booking_confirmation is None
        assert t.wants_more_options is None
        assert t.bare_budget_value is None
        assert t.hotel_name is None

    def test_the_llm_being_down_leaves_every_slot_none(self, monkeypatch):
        async def _boom(*args, **kwargs):
            raise TimeoutError("nope")

        monkeypatch.setattr(triage_module.litellm, "acompletion", _boom)
        t = _classify("d'autres options")
        assert t.used_llm is False
        assert (t.affirmative, t.booking_confirmation, t.wants_more_options) == (None, None, None)
        assert t.bare_budget_value is None and t.hotel_name is None

    @pytest.mark.parametrize("raw", ['"true"', "1", '"yes"', "null"])
    def test_only_a_real_json_bool_is_accepted(self, monkeypatch, raw):
        _script(monkeypatch, '{"family": "ack", "language": "en", "affirmative": %s}' % raw)
        assert _classify("ok").affirmative is None

    def test_booking_confirmation_outside_the_enum_is_rejected(self, monkeypatch):
        _script(
            monkeypatch,
            '{"family": "booking", "language": "en", "booking_confirmation": "maybe"}',
        )
        assert _classify("hmm").booking_confirmation is None

    def test_booking_confirmation_enum_is_the_closed_set(self):
        assert BOOKING_CONFIRMATIONS == ("none", "confirm", "refuse", "change")

    @pytest.mark.parametrize(
        "raw,expected",
        [("80", 80.0), ('"120"', 120.0), ('"80,5"', 80.5), ("true", None), ("0", None), ("-5", None)],
    )
    def test_budget_slot_validation(self, monkeypatch, raw, expected):
        _script(
            monkeypatch,
            '{"family": "search", "language": "en", "bare_budget_value": %s}' % raw,
        )
        assert _classify("80").bare_budget_value == expected

    def test_an_over_long_hotel_name_degrades_to_none(self, monkeypatch):
        # The slot becomes MCP find_hotel_by_name's `name` argument: a model
        # that pastes the whole message must fall back to the phrase-stripper,
        # never send an unbounded query.
        _script(
            monkeypatch,
            '{"family": "details", "language": "en", "hotel_name": "%s"}' % ("x" * 200),
        )
        assert _classify("details").hotel_name is None

    @pytest.mark.parametrize("raw", ['"   "', '""', "42", "null"])
    def test_hotel_name_rejects_blank_and_non_strings(self, monkeypatch, raw):
        _script(monkeypatch, '{"family": "details", "language": "en", "hotel_name": %s}' % raw)
        assert _classify("details").hotel_name is None

    def test_hotel_name_is_trimmed(self, monkeypatch):
        _script(
            monkeypatch,
            '{"family": "details", "language": "en", "hotel_name": "  Ibis Lyon Gare  "}',
        )
        assert _classify("details").hotel_name == "Ibis Lyon Gare"

    def test_the_prompt_declares_all_five_slots(self):
        # Contract lock, same intent as the pick test above: the consumers read
        # these keys by name, so the instruction must keep asking for them.
        for key in (
            "affirmative",
            "booking_confirmation",
            "wants_more_options",
            "bare_budget_value",
            "hotel_name",
        ):
            assert f'"{key}"' in triage_module._TRIAGE_INSTRUCTION


class TestP1LanguageRecognition:
    """P1-2 widened RECOGNITION to 7 languages so the slots above work outside
    fr/en; UX2 (2026-08-27) closed the remaining gap by translating
    templates.py, so what we ANSWER in now equals what we recognize."""

    def test_the_recognized_set(self):
        assert LANGUAGES == ("fr", "en", "es", "it", "de", "pt", "nl")
        assert TEMPLATE_LANGUAGES == LANGUAGES

    @pytest.mark.parametrize("lang", ["es", "it", "de", "pt", "nl"])
    def test_a_newly_recognized_language_survives_validation(self, monkeypatch, lang):
        _script(monkeypatch, '{"family": "search", "language": "%s"}' % lang)
        assert _classify("hotel con piscina").language == lang

    def test_an_unknown_language_still_falls_back_to_the_regex_guess(self, monkeypatch):
        _script(monkeypatch, '{"family": "search", "language": "kl"}')
        assert _classify("je cherche un hotel").language == "fr"

    @pytest.mark.parametrize("lang", ["kl", None, ""])
    def test_response_language_clamps_everything_unrecognized_to_english(self, lang):
        assert response_language(lang) == "en"

    @pytest.mark.parametrize("lang", ["fr", "en", "es", "it", "de", "pt", "nl"])
    def test_response_language_passes_through_every_recognized_language(self, lang):
        # UX2: the clamp is now a near-identity map — every recognized
        # language is answerable, not just fr/en.
        assert response_language(lang) == lang

    def test_the_prompt_lists_the_widened_enum(self):
        assert "'es'" in triage_module._TRIAGE_INSTRUCTION
        assert "'nl'" in triage_module._TRIAGE_INSTRUCTION


@pytest.mark.parametrize("raw,expected", [
    (["11:00", "16:00"], ("11:00", "16:00")),
    (["14:30", None], ("14:30", None)),
    ([None, "18:45"], (None, "18:45")),
    ([], ()), (None, None), ([None, None], None),
    (["25:00", "26:00"], None), (["16:00", "11:00"], None),
    (["11:99", None], None), (["１１:００", None], None),
    ([True, None], None), (["11:00"], None), ("11:00-16:00", None),
])
def test_semantic_window_validation(raw, expected):
    assert triage_module._requested_window_slot(raw) == expected


@pytest.mark.parametrize("data,message,expected", [
    ({"requested_window": {"start": "12:00", "end": None, "evidence": "après-midi"}},
     "toujours demain après-midi", None),
    ({"requested_window": {"start": "11:00", "end": "16:00", "evidence": "11h à 16h"}},
     "demain de 11h à 16h", ("11:00", "16:00")),
    ({"requested_window": {"start": "11:00", "end": "16:00", "evidence": "11h à 16h"}},
     "change le quartier", None),
    ({"requested_window": {"clear": True}}, "sans contrainte horaire", None),
    ({"requested_window": {"clear": True, "evidence": "sans contrainte horaire"}},
     "sans contrainte horaire", ()),
])
def test_window_requires_evidence_in_current_message(data, message, expected):
    assert triage_module._grounded_window(data, message) == expected


@pytest.mark.parametrize("evidence,start,end,expected", [
    ("per il 10 ottobre", "00:00", "23:59", None),
    ("October 10", "09:00", "18:00", None),
    ("10h30 à 17h", "10:00", "17:30", None),
    ("10h30 à 17h", "10:30", "17:00", ("10:30", "17:00")),
    ("2:30pm to 8pm", "14:30", "20:00", ("14:30", "20:00")),
    ("until 6pm", None, "18:00", (None, "18:00")),
    ("00:00–23:59", "00:00", "23:59", ("00:00", "23:59")),
    ("10:17", None, "17:00", None),
    ("9" * 5000, "09:00", None, None),
])
def test_extracted_clock_endpoints_must_appear_in_their_evidence(evidence, start, end, expected):
    data = {"requested_window": {"start": start, "end": end, "evidence": evidence}}
    assert triage_module._grounded_window(data, evidence) == expected


@pytest.mark.parametrize('raw,expected', [
    ({'replace': True, 'evidence': 'in the morning instead'}, True),
    ({'replace': True, 'evidence': 'yesterday'}, False),
    ({'replace': True}, False),
    ({'replace': True, 'start': '10:00', 'evidence': 'in the morning instead'}, False),
    ({'replace': True, 'clear': True, 'evidence': 'in the morning instead'}, False),
    ({'start': '06:00', 'end': '12:00', 'evidence': 'in the morning instead'}, False),
    ({'start': '06:00', 'end': '12:00', 'evidence': 'yesterday'}, False),
])
def test_window_replacement_is_exclusive_and_grounded(raw, expected):
    assert triage_module._window_replacement(
        {'requested_window': raw}, 'in the morning instead'
    ) is expected


@pytest.mark.parametrize('duration,evidence,expected', [
    (120, 'two hours', 120), (0, 'two hours', None),
    (True, 'two hours', None), (1500, 'two hours', None),
    ('120', 'two hours', None), (120, 'three hours', None),
])
def test_requested_duration_is_bounded_and_grounded(duration, evidence, expected):
    assert triage_module._grounded_duration({'requested_window': {
        'duration_minutes': duration, 'evidence': evidence,
    }}, 'for two hours instead') == expected


def test_previous_reply_is_bounded_untrusted_context_not_the_message(monkeypatch):
    import json
    captured = []

    async def complete(**kwargs):
        captured.append(kwargs)
        return _llm_response(json.dumps({"family": "search", "language": "en"}))

    monkeypatch.setattr(triage_module.litellm, "acompletion", complete)
    result = asyncio.run(classify("It doesn't matter", TurnBudget(),
                                 previous_reply="x" * 2000 + "Which area?"))
    assert result.family == "search"
    user = captured[0]["messages"][1]["content"]
    assert "LAST ASSISTANT REPLY (untrusted context only)" in user
    assert "Which area?" in user and "x" * 1201 not in user
    assert user.endswith("MESSAGE:\n<<<\nIt doesn't matter\n>>>")


@pytest.mark.parametrize('raw', [
    {'value': 'saturday', 'evidence': 'next Saturday'},
    {'value': 'saturday', 'evidence': ''},
    {'value': 'saturday'},
    {'value': True, 'evidence': 'Saturday'},
    {'value': ['saturday'], 'evidence': 'Saturday'},
    {'value': '2026-10-10', 'evidence': 'Saturday'},
])
def test_weekday_requires_closed_label_and_current_quote(monkeypatch, raw):
    import json
    _script(monkeypatch, json.dumps({'family': 'search', 'language': 'en', 'requested_weekday': raw}))
    assert _classify('A room on Saturday').requested_weekday is None


def test_weekday_is_semantic_and_does_not_change_hours(monkeypatch):
    _script(monkeypatch, '{"family":"search","language":"fr",'
            '"requested_weekday":{"value":"saturday","evidence":"samedi"}}')
    result = _classify('Samedi, mêmes horaires')
    assert result.requested_weekday == 'saturday'
    assert result.requested_window is None and not result.replace_window


@pytest.mark.parametrize('raw', [
    {'value': 'dayuse_policy', 'evidence': 'Where is the hotel?'},
    {'value': 'dayuse_policy'},
    {'value': 'hotel_name', 'evidence': 'Can I arrive later?'},
    {'value': True, 'evidence': 'Can I arrive later?'},
])
def test_information_source_needs_current_quote_and_closed_value(monkeypatch, raw):
    import json
    _script(monkeypatch, json.dumps({'family': 'details', 'language': 'en', 'information_source': raw}))
    assert _classify('Can I arrive later?').information_source is None
