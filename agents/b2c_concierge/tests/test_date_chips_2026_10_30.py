"""Next-day cards: said first by the code, always with their day chips (2026-10-30).

Over the REAL spine (only the A2A leg and the LLM scripted, as
test_spine_profile.py):
- case 1, today's bookings closed (`cutoff_fallback_from`, S-CX6): the code's
  first sentence says it (7 languages); the synthesis' own repeat is dropped;
  chips « Après-demain », « Pas de date précise » — never today's;
- case 5, « demain, plus près » (`closer_from`): « Ce soir quand même (3,9 km) »
  first;
- the chips come whatever the user said about the day and however many times
  the day was announced;
- a click on « Ce soir quand même » is recognized from the concierge's own
  state (`last_suggestions` + `suggestion_kinds`), not from its words: no
  triage call, the leaf told `date_chip=same_day`, the day held on today;
- a click on « Pas de date précise »: `date_chip=first_open_day`, and the day
  the leaf found is said first (or that none of the 7 days had offers).
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from google.adk.runners import InMemoryRunner

from b2c_concierge import templates
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.date_format import format_date_human
from b2c_concierge.facade import build_chat_payload
from b2c_concierge.ground_truth import date_context_block
from b2c_concierge.profile import SessionProfile
from b2c_concierge.requested_date import reference_today

try:  # absent before 2026-10-30: the counter-proof on origin/main runs this file as is
    from b2c_concierge.profile import clicked_suggestion_kind
except ImportError:  # pragma: no cover
    clicked_suggestion_kind = None  # type: ignore[assignment]

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

_TODAY = reference_today(None)
_TOMORROW = _TODAY + timedelta(days=1)
_LANGUAGES = ["fr", "en", "es", "it", "de", "pt", "nl"]
# The code's first sentence, written out here (not read from the code under test).
_CLOSED_TODAY = {
    "fr": "Les réservations sont fermées pour aujourd'hui : voici les offres de {day}.",
    "en": "Bookings are closed for today: here are the offers for {day}.",
    "es": "Las reservas para hoy están cerradas: aquí tienes las ofertas del {day}.",
    "it": "Le prenotazioni per oggi sono chiuse: ecco le offerte di {day}.",
    "de": "Die Buchungen für heute sind geschlossen: Hier die Angebote für {day}.",
    "pt": "As reservas para hoje estão fechadas: aqui estão as ofertas de {day}.",
    "nl": "De boekingen voor vandaag zijn gesloten: hier zijn de aanbiedingen voor {day}.",
}
_OTHER_DAY_FR = "Pour un autre jour, choisissez ci-dessous ou dites-le-moi."


def _triage(language: str = "fr") -> str:
    return '{"family": "search", "language": "%s"}' % language


def _closed_today(**extra) -> dict:
    return {
        "results": ["hotel A"], "profile_delta": {"city": "Paris"},
        "search_date": {"date": _TOMORROW.isoformat(), "same_day": False,
                        "cutoff_fallback_from": _TODAY.isoformat(), **extra},
    }


def _closer_tomorrow() -> dict:
    return {
        "results": ["hotel A"], "profile_delta": {"city": "München"},
        "search_date": {"date": _TOMORROW.isoformat(), "same_day": False,
                        "closer_from": _TODAY.isoformat(), "tonight_nearest_km": 3.9},
    }


def _stored(store, session_id) -> SessionProfile:
    return asyncio.run(store.get(session_id))


def _query_params(leg) -> dict:
    return find_datapart(leg.seen_outgoing_parts)["query_params"]


# --- case 1: today closed -----------------------------------------------------------------------


@pytest.mark.parametrize("language", _LANGUAGES)
def test_today_closed_is_said_first_by_the_code_in_every_language(
    monkeypatch, fake_leg, fake_profile_store, language  # noqa: F811
):
    fake_leg.response_payload = _closed_today()
    _scripted_llm(monkeypatch, _triage(language), "Hotel A is a good pick.")
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)

    answer = _run_turn(runner, session.id, "a hotel in Paris tonight")

    day = format_date_human(_TOMORROW.isoformat(), language)
    first = answer.split("\n\n")[0]
    assert first == _CLOSED_TODAY[language].format(day=day)
    assert day in first
    assert "Hotel A is a good pick." in answer


def test_the_synthesis_repeat_of_the_announcement_is_dropped(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    day = format_date_human(_TOMORROW.isoformat(), "fr")
    fake_leg.response_payload = _closed_today()
    _scripted_llm(
        monkeypatch, _triage("fr"),
        f"Les réservations sont fermées pour aujourd'hui, voici donc les offres de {day}. Hotel A est à 1 km.",
    )
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)

    answer = _run_turn(runner, session.id, "un hôtel à Paris ce soir")

    assert answer.count("fermées pour aujourd'hui") == 1
    assert "Hotel A est à 1 km." in answer


def test_the_synthesis_safety_net_forbids_a_second_announcement():
    block = date_context_block(_closed_today(), "en")
    assert "MANDATORY DISCLOSURE" in block and "do not say it again" in block


@pytest.mark.parametrize("message", ["un hôtel à Paris", "un hôtel à Paris aujourd'hui"])
def test_today_closed_always_comes_with_the_later_day_chips_never_today(
    monkeypatch, fake_leg, fake_profile_store, message  # noqa: F811
):
    """Whatever the user said about the day, and with the day already
    announced in the session (the suite's default), the chips are there."""
    fake_leg.response_payload = _closed_today()
    _scripted_llm(monkeypatch, _triage("fr"), "Voici Hotel A.")
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)

    answer = _run_turn(runner, session.id, message)

    stored = _stored(fake_profile_store, session.id)
    assert stored.last_suggestions == ["Après-demain", "Pas de date précise"]
    assert stored.suggestion_kinds == {"Après-demain": "date_day", "Pas de date précise": "date_flexible"}
    assert "Aujourd'hui" not in stored.last_suggestions
    assert answer.endswith(_OTHER_DAY_FR)


def test_the_rescues_next_day_keeps_its_relaxation_line_and_gets_the_chips(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    fake_leg.response_payload = {
        **_closed_today(),
        "relaxation": {"steps": ["amenities", "next_day"], "searched_date": _TODAY.isoformat(),
                       "offered_date": _TOMORROW.isoformat(), "amenities": ["jacuzzi"]},
    }
    _scripted_llm(monkeypatch, _triage("fr"), "Voici Hotel A.")
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)

    answer = _run_turn(runner, session.id, "un hôtel avec jacuzzi à Paris")

    assert "fermées pour aujourd'hui" not in answer  # the relaxation line names the date
    assert _stored(fake_profile_store, session.id).last_suggestions == ["Après-demain", "Pas de date précise"]


# --- case 5: « demain, plus près » --------------------------------------------------------------


def _closer_turn(monkeypatch, fake_leg, *plan):  # noqa: F811
    fake_leg.response_payload = _closer_tomorrow()
    llm = _scripted_llm(monkeypatch, _triage("fr"), "Voici le Westin.", *plan)
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    answer = _run_turn(runner, session.id, "chambre près d'Arabellapark")
    return llm, runner, session, answer


def test_closer_tomorrow_offers_tonight_anyway_first(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    _llm, _runner, session, answer = _closer_turn(monkeypatch, fake_leg)

    day = format_date_human(_TOMORROW.isoformat(), "fr")
    assert answer.startswith(templates.closer_tomorrow_notice(3.9, day, "fr"))
    stored = _stored(fake_profile_store, session.id)
    assert stored.last_suggestions == ["Ce soir quand même (3,9 km)", "Après-demain", "Pas de date précise"]
    assert stored.suggestion_kinds == {
        "Ce soir quand même (3,9 km)": "date_tonight", "Après-demain": "date_day",
        "Pas de date précise": "date_flexible",
    }
    payload = build_chat_payload(session_id="s", final_text=answer, hotels=None, profile=stored,
                                 language="fr", turn_id="t")
    assert payload["suggestions"] == stored.last_suggestions
    assert payload["suggestion_types"] == stored.suggestion_kinds


@pytest.mark.parametrize("language", _LANGUAGES)
def test_the_next_day_chips_exist_in_every_language(language):
    chips = templates.next_day_chips(language, tonight_km=3.9, tonight=True)
    assert [kind for _label, kind in chips] == ["date_tonight", "date_day", "date_flexible"]
    assert "3,9" in chips[0][0] or "3.9" in chips[0][0]
    assert [kind for _label, kind in templates.next_day_chips(language)] == ["date_day", "date_flexible"]


def test_tonight_anyway_clicked_searches_tonight_without_any_fallback(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    llm, runner, session, _answer = _closer_turn(monkeypatch, fake_leg, "Voici le Rilano, à 3,9 km.")
    fake_leg.response_payload = {
        "results": ["hotel B"],
        "search_date": {"date": _TODAY.isoformat(), "same_day": True},
    }

    answer = _run_turn(runner, session.id, "Ce soir quand même (3,9 km)")

    assert len(llm.calls) == 3  # triage + synthesis, then the synthesis only: no triage on a chip
    assert _query_params(fake_leg)["date_chip"] == "same_day"
    stored = _stored(fake_profile_store, session.id)
    assert stored.date == _TODAY.isoformat()
    assert stored.date_reference == {"resolved_from": "tonight_chip"}
    assert answer == "Voici le Rilano, à 3,9 km."  # no next-day sentence, no chip line


def test_no_specific_date_clicked_says_the_first_day_found(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    _llm, runner, session, _answer = _closer_turn(monkeypatch, fake_leg, "Voici le Westin.")
    found = _TODAY + timedelta(days=2)
    fake_leg.response_payload = {
        "results": ["hotel A"],
        "search_date": {"date": found.isoformat(), "same_day": False, "first_open_from": _TODAY.isoformat(),
                        "first_open_days": 3, "first_open_found": True},
        "profile_delta": {"date": found.isoformat(), "date_reference": {"resolved_from": "first_open_day"}},
    }

    answer = _run_turn(runner, session.id, "Pas de date précise")

    assert _query_params(fake_leg)["date_chip"] == "first_open_day"
    assert answer.startswith(f"Premier jour avec des offres proches : {format_date_human(found.isoformat(), 'fr')}.")
    stored = _stored(fake_profile_store, session.id)
    assert stored.date == found.isoformat()  # not reset by the date guard


def test_no_day_close_by_within_7_days_is_said(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    _llm, runner, session, _answer = _closer_turn(monkeypatch, fake_leg, "Voici l'hôtel.")
    best = _TODAY + timedelta(days=4)
    fake_leg.response_payload = {
        "results": ["hotel A"],
        "search_date": {"date": best.isoformat(), "same_day": False, "first_open_from": _TODAY.isoformat(),
                        "first_open_days": 7, "first_open_found": False},
    }

    answer = _run_turn(runner, session.id, "Pas de date précise")

    assert answer.startswith(
        "Sur les 7 prochains jours, aucun n'a d'offres tout près : voici celles du "
        f"{format_date_human(best.isoformat(), 'fr')}, les plus proches trouvées."
    )


def test_no_offer_at_all_within_7_days_is_said(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    _llm, runner, session, _answer = _closer_turn(monkeypatch, fake_leg, "Aucune offre.")
    fake_leg.response_payload = {
        "results": [],
        "search_date": {"date": _TODAY.isoformat(), "same_day": True, "first_open_from": _TODAY.isoformat(),
                        "first_open_days": 7, "first_open_found": False},
        "search_context": {"city": "München", "date": _TODAY.isoformat()},
    }

    answer = _run_turn(runner, session.id, "Pas de date précise")

    assert answer.startswith("Je n'ai trouvé aucune offre sur les 7 prochains jours.")


def test_the_chip_words_typed_without_the_chip_on_screen_go_to_the_triage(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    fake_leg.response_payload = {"results": ["hotel A"], "profile_delta": {"city": "Paris"}}
    llm = _scripted_llm(monkeypatch, _triage("fr"), "Voici Hotel A.")
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)

    _run_turn(runner, session.id, "Pas de date précise")

    assert len(llm.calls) == 2  # triage + synthesis
    assert "date_chip" not in (_query_params(fake_leg) or {})


def test_a_chip_is_its_exact_label_among_the_ones_offered():
    profile = SessionProfile(
        last_suggestions=["Ce soir quand même (3,9 km)", "Après-demain", "Pas de date précise"],
        suggestion_kinds={"Ce soir quand même (3,9 km)": "date_tonight", "Après-demain": "date_day",
                          "Pas de date précise": "date_flexible"},
    )
    assert clicked_suggestion_kind("  pas de date précise ", profile) == "date_flexible"
    assert clicked_suggestion_kind("Ce soir quand même (3,9 km)", profile) == "date_tonight"
    assert clicked_suggestion_kind("Ce soir quand même", profile) is None  # not the label offered
    assert clicked_suggestion_kind("pas de date précise, plutôt samedi", profile) is None
    assert clicked_suggestion_kind("Pas de date précise", SessionProfile()) is None


@pytest.mark.parametrize("language", _LANGUAGES)
def test_the_first_open_day_sentences_exist_in_every_language(language):
    found = {"first_open_days": 7, "first_open_found": True}
    assert "DAY" in templates.first_open_day_notice(found, "DAY", language, has_cards=True)
    best = templates.first_open_day_notice({"first_open_days": 7}, "DAY", language, has_cards=True)
    assert "DAY" in best and "7" in best
    assert "7" in templates.first_open_day_notice({"first_open_days": 7}, "", language, has_cards=False)


# --- « Après-demain » and the same cards again (replay of 2026-10-30) ----------------------------


def test_the_day_after_tomorrow_clicked_repeats_the_search_on_that_day(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    """Replay: « Dopodomani » typed back as text was geocoded again (« Ci sono
    diversi luoghi chiamati Milan »). The chip now says only the day."""
    llm, runner, session, _answer = _closer_turn(monkeypatch, fake_leg, "Voici dimanche.")
    day = _TODAY + timedelta(days=2)
    fake_leg.response_payload = {"results": ["hotel C"],
                                 "search_date": {"date": day.isoformat(), "same_day": False}}

    _run_turn(runner, session.id, "Après-demain")

    assert len(llm.calls) == 3  # no triage on a chip
    assert _query_params(fake_leg)["date_chip"] == "day"
    stored = _stored(fake_profile_store, session.id)
    assert stored.date == day.isoformat()
    assert stored.date_reference == {"resolved_from": "day_chip"}


def test_no_specific_date_landing_on_the_day_on_screen_is_not_called_unchanged(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):
    """Replay (München, Milano): the first day with hotels close by WAS the day
    on screen; « this change does not alter the results » answered a click
    that asked for a day, not for other offers."""
    westin = {"hotel_id": 5, "name": "The Westin Grand Munich", "offer_date": _TOMORROW.isoformat()}
    fake_leg.response_payload = {**_closer_tomorrow(), "results": [westin],
                                 "search_context": {"city": "München", "date": "x"}}
    _scripted_llm(monkeypatch, _triage("fr"), "Voici le Westin.", "Voici le Westin.")
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    _run_turn(runner, session.id, "chambre près d'Arabellapark")
    fake_leg.response_payload = {
        "results": [westin], "search_context": {"city": "München", "date": "y"},
        "search_date": {"date": _TOMORROW.isoformat(), "same_day": False, "first_open_from": _TODAY.isoformat(),
                        "first_open_days": 2, "first_open_found": True},
    }

    answer = _run_turn(runner, session.id, "Pas de date précise")

    assert answer.startswith("Premier jour avec des offres proches")
    assert templates.refinement_unchanged_notice("fr") not in answer
