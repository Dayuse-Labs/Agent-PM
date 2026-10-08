"""guard_date_served (mcp-dayuse#8): the search runs on the day the user named.

QA 2026-09-30 (Côte d'Azur) and local repro 2026-10-06: "le 10 octobre" was
asked, the leaf asked a clarification, and the next turn searched today.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest
from google.adk.runners import InMemoryRunner

import b2c_concierge.agent as agent_module
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.requested_date import (
    date_served_notice,
    expected_search_date,
    mentions_a_date,
    parse_requested_date,
)

from .test_spine_profile import FakeLeg, _new_session, _run_turn, _scripted_llm

TODAY = date(2026, 10, 6)  # a Tuesday


class TestParseRequestedDate:
    @pytest.mark.parametrize(
        "message,expected",
        [
            ("Un hôtel sur la Côte d'Azur le 10 octobre", date(2026, 10, 10)),
            ("le 3 octobre", date(2027, 10, 3)),  # already past this year
            ("samedi 10 octobre", date(2026, 10, 10)),
            ("10. Oktober in Berlin", date(2026, 10, 10)),
            ("3 de octubre", date(2027, 10, 3)),
            ("October 10th, 2026", date(2026, 10, 10)),
            ("2026-10-12", date(2026, 10, 12)),
            ("demain de 12h à 13h", date(2026, 10, 7)),
            ("après-demain", date(2026, 10, 8)),
            ("tomorrow in Paris", date(2026, 10, 7)),
            ("mañana en Madrid", date(2026, 10, 7)),
            ("heute Morgen in Berlin", date(2026, 10, 6)),
            ("ce soir à Lyon", date(2026, 10, 6)),
        ],
    )
    def test_unambiguous_dates(self, message, expected):
        assert parse_requested_date(message, TODAY) == expected

    @pytest.mark.parametrize(
        "message",
        [
            "Côte d'Azur en France",
            "à Nice",
            "le 3",  # could be a pick
            "vendredi",  # left to the leaf's own label
            "du 10 au 12 octobre",  # a range is not one day
            "aujourd'hui ou demain",
            "I may 2 rooms",
            "Guten Morgen, ein Hotel",
            "por la mañana en Madrid",
            "de 12h à 13h",
        ],
    )
    def test_nothing_certain(self, message):
        assert parse_requested_date(message, TODAY) is None

    def test_weekday_counts_as_a_date_mention(self):
        assert mentions_a_date("am Freitag", TODAY)
        assert mentions_a_date("le 3", TODAY)
        assert not mentions_a_date("Côte d'Azur en France", TODAY)
        assert not mentions_a_date("de 12h à 13h", TODAY)


class TestExpectedSearchDate:
    def test_from_the_message(self):
        assert expected_search_date("le 10 octobre", None, TODAY) == ("2026-10-10", True)

    def test_carried_when_the_message_says_nothing_about_a_day(self):
        assert expected_search_date("à Nice", "2026-10-10", TODAY) == ("2026-10-10", False)

    def test_unknown_when_the_message_names_a_day_code_cannot_resolve(self):
        assert expected_search_date("plutôt vendredi", "2026-10-10", TODAY) == (None, False)

    def test_a_stale_carried_date_is_not_expected(self):
        assert expected_search_date("à Nice", "2026-10-01", TODAY) == (None, False)


def test_notice_names_both_days():
    assert date_served_notice("2026-10-10", "2026-10-06", "fr") == (
        "Attention : ces offres sont pour le mardi 6 octobre 2026, pas pour le samedi "
        "10 octobre 2026 que vous avez demandé. Dites-moi si je relance la recherche "
        "pour le samedi 10 octobre 2026."
    )


_FR_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _in_days(n: int) -> date:
    return date.today() + timedelta(days=n)


def _fr(d: date) -> str:
    return f"{d.day} {_FR_MONTHS[d.month - 1]}"


@pytest.fixture
def leg(monkeypatch):
    fake = FakeLeg()
    monkeypatch.setattr(agent_module, "_get_leg", lambda leaf: fake)
    return fake


def _sent_profile(leg: FakeLeg) -> dict:
    decoded = find_datapart(leg.seen_outgoing_parts)
    assert decoded is not None
    return decoded["profile_in"]


class TestDateSurvivesAClarification:
    def test_the_named_date_reaches_the_next_turn(self, monkeypatch, leg, fake_profile_store):
        asked = _in_days(4)
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        # Turn 1: the leaf asks which Côte d'Azur — no search ran.
        leg.text = "Côte d'Azur en France ou Azur dans les Landes ?"
        leg.response_payload = {"profile_delta": {}}
        _scripted_llm(monkeypatch, '{"family": "search", "language": "fr"}', "Laquelle ?")
        _run_turn(runner, session.id, f"Un hôtel sur la Côte d'Azur le {_fr(asked)}")
        assert asyncio.run(fake_profile_store.get(session.id)).date == asked.isoformat()

        # Turn 2: no date in the message — the leaf still receives it.
        leg.text = "5 offres trouvées."
        leg.response_payload = {
            "results": [{"hotel_id": 1, "name": "Hotel A"}],
            "search_date": {"date": asked.isoformat()},
            "profile_delta": {"city": "Nice"},
        }
        _scripted_llm(monkeypatch, '{"family": "search", "language": "fr"}', "Voici Hotel A.")
        answer = _run_turn(runner, session.id, "à Nice")
        assert _sent_profile(leg)["date"] == asked.isoformat()
        assert answer == "Voici Hotel A."


class TestGuardDateServed:
    def _turn(self, monkeypatch, leg, message, served, scored, **search_date):
        monkeypatch.setattr(agent_module, "score_guards", lambda fired: scored.append(set(fired)))
        leg.response_payload = {
            "results": [{"hotel_id": 1, "name": "Hotel A"}],
            "search_date": {"date": served, **search_date},
            "profile_delta": {"city": "Nice", "date": served},
        }
        _scripted_llm(monkeypatch, '{"family": "search", "language": "fr"}', "Voici Hotel A.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        return runner, session, _run_turn(runner, session.id, message)

    def test_another_day_served_is_flagged_and_disclosed(self, monkeypatch, leg, fake_profile_store):
        asked, served = _in_days(4), date.today()
        scored: list[set[str]] = []
        _, session, answer = self._turn(
            monkeypatch, leg, f"un hôtel à Nice le {_fr(asked)}", served.isoformat(), scored
        )
        assert answer.startswith("Voici Hotel A.")
        assert answer.endswith(date_served_notice(asked.isoformat(), served.isoformat(), "fr"))
        assert "date_served" in scored[-1]
        # A follow-up "oui, relance" searches the day that was asked.
        assert asyncio.run(fake_profile_store.get(session.id)).date == asked.isoformat()

    def test_the_named_day_served_is_silent(self, monkeypatch, leg, fake_profile_store):
        asked = _in_days(4)
        scored: list[set[str]] = []
        _, _, answer = self._turn(
            monkeypatch, leg, f"un hôtel à Nice le {_fr(asked)}", asked.isoformat(), scored
        )
        assert answer == "Voici Hotel A."
        assert "date_served" not in scored[-1]

    def test_a_disclosed_cutoff_swap_is_not_flagged(self, monkeypatch, leg, fake_profile_store):
        today, tomorrow = date.today(), _in_days(1)
        scored: list[set[str]] = []
        _, _, answer = self._turn(
            monkeypatch, leg, "un hôtel à Nice aujourd'hui", tomorrow.isoformat(), scored,
            cutoff_fallback_from=today.isoformat(),
        )
        assert answer == "Voici Hotel A."
        assert "date_served" not in scored[-1]

    def test_a_day_code_cannot_resolve_is_left_to_the_leaf(self, monkeypatch, leg, fake_profile_store):
        scored: list[set[str]] = []
        _, _, answer = self._turn(
            monkeypatch, leg, "un hôtel à Nice vendredi", _in_days(3).isoformat(), scored
        )
        assert answer == "Voici Hotel A."
        assert "date_served" not in scored[-1]


@pytest.mark.parametrize('quote,weekday,today,expected', [
    ('Saturday', 'saturday', date(2026, 10, 7), '2026-10-10'),
    ('samedi', 'saturday', date(2026, 10, 10), '2026-10-17'),
])
def test_weekday_survives_clarification_and_faq_without_being_repeated(
    monkeypatch, leg, fake_profile_store, quote, weekday, today, expected
):
    import json

    monkeypatch.setattr(agent_module, 'reference_today', lambda _: today)
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    leg.response_payload = {'profile_delta': {}}
    leg.text = 'Which Orange County?'
    _scripted_llm(monkeypatch, json.dumps({
        'family': 'search', 'language': 'en',
        'requested_weekday': {'value': weekday, 'evidence': quote},
        'requested_window': {'start': '15:00', 'evidence': '3pm'},
    }), 'Which Orange County?')
    _run_turn(runner, session.id, f'I need to check in at 3pm on {quote} in Orange County')
    assert _sent_profile(leg)['date'] == expected
    assert asyncio.run(fake_profile_store.get(session.id)).date == expected

    # A policy question must not replace the search day with its own weekday.
    _scripted_llm(monkeypatch, json.dumps({
        'family': 'faq', 'language': 'en',
        'requested_weekday': {'value': 'sunday', 'evidence': 'Sunday'},
    }), 'Arrival is during the booked slot.')
    _run_turn(runner, session.id, 'Does the same arrival policy apply on Sunday?')
    assert asyncio.run(fake_profile_store.get(session.id)).date == expected

    for followup in ('Orange County, California.', 'Anaheim is fine.'):
        _scripted_llm(monkeypatch, '{"family":"search","language":"en"}', 'Searching.')
        _run_turn(runner, session.id, followup)
        assert _sent_profile(leg)['date'] == expected
        assert _sent_profile(leg)['timeslot_start'] == '15:00'


def test_explicit_calendar_date_outranks_conflicting_weekday_label():
    assert expected_search_date('Saturday 2026-10-10', None, TODAY, weekday='sunday') == ('2026-10-10', True)
