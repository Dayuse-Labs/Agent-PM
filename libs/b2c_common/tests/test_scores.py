"""scores.py (OBS3) — deterministic Langfuse scores, opt-in and inert by
default. Locks: GUARD_SCORE_NAMES is exhaustive/stable/snake_case (a
renamed/dropped/added-without-review entry breaks per-guard history), BOOLEAN
values are always 0.0/1.0 (never Python True/False), `degraded` only accepts
its closed set (RGPD: never a free-text field), and every function here is a
no-op — never raises — when Langfuse is disabled.
"""
from __future__ import annotations

import re

import pytest

from b2c_common import scores


@pytest.fixture(autouse=True)
def _disabled(monkeypatch):
    monkeypatch.setattr(scores, "get_langfuse", lambda: None)


class TestGuardScoreNamesContract:
    _SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

    def test_exactly_15_names(self):
        # 13 → 14 on 2026-08-26 (`poi_anchor_coherence`), 14 → 15 on 2026-08-27
        # (`filter_relaxation_honored`, UX1). The contract allows ADDING a
        # guard; it forbids renaming or removing one, which is what would break
        # a score's history.
        assert len(scores.GUARD_SCORE_NAMES) == 15

    def test_no_duplicates(self):
        assert len(set(scores.GUARD_SCORE_NAMES)) == len(scores.GUARD_SCORE_NAMES)

    def test_all_snake_case(self):
        offenders = [n for n in scores.GUARD_SCORE_NAMES if not self._SNAKE_CASE_RE.match(n)]
        assert offenders == []

    def test_is_a_tuple_not_a_mutable_container(self):
        # A permanent contract must not be a `list`/`set` some later import
        # could mutate in place.
        assert isinstance(scores.GUARD_SCORE_NAMES, tuple)

    def test_expected_names_present(self):
        # The 11 ported from agent-usa's 2026-06 audit + the 4 AgentB2C-only
        # additions (R9 = booking_confirmation, S-G12 = hotel_link_truthfulness,
        # poi_anchor_coherence = the M4 "the name is right, the place is wrong"
        # hole, filter_relaxation_honored = UX1's "enlève le spa" retraction).
        assert set(scores.GUARD_SCORE_NAMES) == {
            "geocode_echo_back",
            "generic_location_demotion",
            "state_anchoring",
            "date_hallucinated_year_rolled_forward",
            "date_carryover_stale_floored",
            "budget_integrity",
            "timeslot_sanitization",
            "recovery_ack",
            "anti_clarification_loop",
            "amenity_truthfulness",
            "named_hotel_lookup",
            "booking_confirmation",
            "hotel_link_truthfulness",
            "poi_anchor_coherence",
            "filter_relaxation_honored",
        }


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def score_current_trace(self, **kwargs):
        self.calls.append(kwargs)


class TestDisabledByDefault:
    def test_score_guards_is_a_noop(self):
        scores.score_guards({"recovery_ack"})  # must not raise

    def test_score_turn_is_a_noop(self):
        scores.score_turn(hotels_returned=3, llm_calls=2)  # must not raise

    def test_score_degraded_is_a_noop(self):
        scores.score_degraded("facade_shield")  # must not raise

    def test_score_ttft_is_a_noop(self):
        scores.score_ttft(123.4)  # must not raise


class TestScoreGuardsEnabled:
    def test_emits_one_boolean_score_per_guard_name(self, monkeypatch):
        client = _RecordingClient()
        monkeypatch.setattr(scores, "get_langfuse", lambda: client)
        scores.score_guards({"recovery_ack", "hotel_link_truthfulness"})
        assert len(client.calls) == len(scores.GUARD_SCORE_NAMES)
        by_name = {c["name"]: c for c in client.calls}
        assert set(by_name) == {f"guard_{n}" for n in scores.GUARD_SCORE_NAMES}
        assert by_name["guard_recovery_ack"]["value"] == 1.0
        assert by_name["guard_hotel_link_truthfulness"]["value"] == 1.0
        assert by_name["guard_budget_integrity"]["value"] == 0.0
        for call in client.calls:
            assert call["data_type"] == "BOOLEAN"
            # Never Python True/False — Langfuse BOOLEAN scores are 0/1.
            assert call["value"] in (0.0, 1.0)
            assert call["value"] is not True and call["value"] is not False

    def test_config_id_is_attached_when_one_exists(self, monkeypatch):
        """Wires each score to its Langfuse score config (min/max/category
        validation + annotation-queue usability, OBS2-LANGFUSE-BRIEF.md §2) —
        except the one guard whose `guard_` name exceeds Langfuse's 35-char
        config-name limit (known gap, score-configs.json), which still emits,
        just with no config_id."""
        client = _RecordingClient()
        monkeypatch.setattr(scores, "get_langfuse", lambda: client)
        scores.score_guards(set())
        by_name = {c["name"]: c for c in client.calls}
        assert by_name["guard_recovery_ack"]["config_id"] == scores._SCORE_CONFIG_IDS["guard_recovery_ack"]
        assert by_name["guard_date_hallucinated_year_rolled_forward"]["config_id"] is None

    def test_unknown_fired_names_are_ignored(self, monkeypatch):
        """A caller-side bug (a typo'd guard name) must never silently mint a
        new, un-configured score series — only `GUARD_SCORE_NAMES` entries
        are ever emitted."""
        client = _RecordingClient()
        monkeypatch.setattr(scores, "get_langfuse", lambda: client)
        scores.score_guards({"not_a_real_guard"})
        assert {c["name"] for c in client.calls} == {f"guard_{n}" for n in scores.GUARD_SCORE_NAMES}
        assert all(c["value"] == 0.0 for c in client.calls)

    def test_never_raises_when_the_client_raises(self, monkeypatch):
        class _BrokenClient:
            def score_current_trace(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(scores, "get_langfuse", lambda: _BrokenClient())
        scores.score_guards({"recovery_ack"})  # must not raise


class TestScoreTurnEnabled:
    def test_emits_hotels_returned_empty_shortlist_and_llm_calls(self, monkeypatch):
        client = _RecordingClient()
        monkeypatch.setattr(scores, "get_langfuse", lambda: client)
        scores.score_turn(hotels_returned=0, llm_calls=3)
        by_name = {c["name"]: c for c in client.calls}
        assert by_name["hotels_returned"] == {
            "name": "hotels_returned", "value": 0.0, "data_type": "NUMERIC",
            "config_id": scores._SCORE_CONFIG_IDS["hotels_returned"],
        }
        assert by_name["empty_shortlist"] == {
            "name": "empty_shortlist", "value": 1.0, "data_type": "BOOLEAN",
            "config_id": scores._SCORE_CONFIG_IDS["empty_shortlist"],
        }
        assert by_name["llm_calls"] == {
            "name": "llm_calls", "value": 3.0, "data_type": "NUMERIC",
            "config_id": scores._SCORE_CONFIG_IDS["llm_calls"],
        }

    def test_empty_shortlist_is_false_when_hotels_were_returned(self, monkeypatch):
        client = _RecordingClient()
        monkeypatch.setattr(scores, "get_langfuse", lambda: client)
        scores.score_turn(hotels_returned=4, llm_calls=1)
        by_name = {c["name"]: c for c in client.calls}
        assert by_name["empty_shortlist"]["value"] == 0.0

    def test_never_raises_when_the_client_raises(self, monkeypatch):
        class _BrokenClient:
            def score_current_trace(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(scores, "get_langfuse", lambda: _BrokenClient())
        scores.score_turn(hotels_returned=1, llm_calls=1)  # must not raise


class TestScoreDegradedEnabled:
    def test_emits_a_categorical_score_for_a_known_reason(self, monkeypatch):
        client = _RecordingClient()
        monkeypatch.setattr(scores, "get_langfuse", lambda: client)
        scores.score_degraded("leaf_call_failed")
        # The "degraded" score config now exists (created 2026-08-24, closing the
        # gap that score-configs.json used to record), so the score carries its
        # config_id and Langfuse validates the value against the closed set.
        assert client.calls == [
            {
                "name": "degraded", "value": "leaf_call_failed", "data_type": "CATEGORICAL",
                "config_id": "5499df51-d40d-43ca-ad99-f79247af1959",
            }
        ]

    def test_unknown_reason_is_dropped_not_emitted(self, monkeypatch):
        """RGPD backstop: `degraded` must never become a free-text field —
        anything outside the closed set is silently dropped."""
        client = _RecordingClient()
        monkeypatch.setattr(scores, "get_langfuse", lambda: client)
        scores.score_degraded("some free text a bug injected")  # type: ignore[arg-type]
        assert client.calls == []

    def test_never_raises_when_the_client_raises(self, monkeypatch):
        class _BrokenClient:
            def score_current_trace(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(scores, "get_langfuse", lambda: _BrokenClient())
        scores.score_degraded("facade_shield")  # must not raise


class TestScoreTtftEnabled:
    def test_emits_a_numeric_score(self, monkeypatch):
        client = _RecordingClient()
        monkeypatch.setattr(scores, "get_langfuse", lambda: client)
        scores.score_ttft(42.5)
        assert client.calls == [
            {
                "name": "ttft_ms", "value": 42.5, "data_type": "NUMERIC",
                "config_id": scores._SCORE_CONFIG_IDS["ttft_ms"],
            }
        ]

    def test_never_raises_when_the_client_raises(self, monkeypatch):
        class _BrokenClient:
            def score_current_trace(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(scores, "get_langfuse", lambda: _BrokenClient())
        scores.score_ttft(1.0)  # must not raise
