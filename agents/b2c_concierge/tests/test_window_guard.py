"""guard_window_match (mcp-dayuse#8): cards shown as matches cover the slot."""
from __future__ import annotations

import logging

import b2c_concierge.agent as agent_module
from b2c_concierge.window_guard import (
    enforce_window_disclosure,
    enforce_window_match,
    window_label,
)

from .test_spine import _drive, scripted  # noqa: F401  (fixture)


def _card(i, start, end):
    return {"hotel_id": i, "name": f"Hotel {i}", "timeslots": [{"start": start, "end": end}]}


QA_22H = [_card(1, "17:00", "22:00"), _card(2, "17:00", "23:00"), _card(3, "15:00", "22:00")]


def test_cards_not_covering_are_dropped():
    kept, dropped = enforce_window_match(QA_22H, "22:01", "23:01")
    assert [c["hotel_id"] for c in kept] == [2]
    assert dropped == 2


def test_all_failing_keeps_everything_for_a_labelled_fallback():
    cards = [_card(1, "08:00", "14:00"), _card(2, "10:00", "16:00")]
    kept, dropped = enforce_window_match(cards, "06:00", "16:00")
    assert kept == cards and dropped == 2


def test_no_window_no_check():
    assert enforce_window_match(QA_22H, None, None) == (QA_22H, 0)


def test_a_card_without_slots_is_not_judged():
    cards = [{"hotel_id": 9, "name": "Named"}, _card(2, "17:00", "23:00")]
    assert enforce_window_match(cards, "22:00", "23:00") == (cards, 0)


def test_window_label():
    assert window_label("22:01", "23:01") == "22:00–23:00"
    assert window_label("14:00", None) == "14:00"
    assert window_label(None, None) == ""


def test_disclosure_is_appended_once():
    text, added = enforce_window_disclosure("Voici 2 hôtels.", "06:00–16:00", "fr")
    assert added and text.endswith("voici les offres les plus proches.")
    again, added_again = enforce_window_disclosure(text, "06:00–16:00", "fr")
    assert again == text and not added_again


class TestSpine:
    def _install(self, scripted, monkeypatch, response, synthesis="Vous pouvez réserver ce créneau."):  # noqa: F811
        fired: list[set[str]] = []
        monkeypatch.setattr(agent_module, "score_guards", lambda f: fired.append(set(f)))
        hotels: list[list[dict]] = []
        original = agent_module._B2cConcierge._hotels_event

        def spy(self, ctx, resp, language, picks):
            hotels.append(list(resp.get("results") or []))
            return original(self, ctx, resp, language, picks)

        monkeypatch.setattr(agent_module._B2cConcierge, "_hotels_event", spy)
        scripted('{"family": "search", "language": "fr"}', synthesis, response=response)
        return fired, hotels

    def test_qa_22h_cards_closing_at_22h_never_reach_the_screen(self, scripted, monkeypatch):  # noqa: F811
        fired, hotels = self._install(scripted, monkeypatch, {
            "results": QA_22H,
            "profile_delta": {"city": "Lyon", "timeslot_start": "22:01", "timeslot_end": "23:01"},
        })
        answer = _drive("Un hôtel à Lyon demain de 22h01 à 23h01")
        assert [c["hotel_id"] for c in hotels[-1]] == [2]
        assert "window_match" in fired[-1]
        assert answer == "Vous pouvez réserver ce créneau."

    def test_leaf_fallback_is_always_disclosed(self, scripted, monkeypatch, caplog):  # noqa: F811
        # The synthesis dropped the leaf's disclosure in the 22h01 QA trace.
        fired, hotels = self._install(scripted, monkeypatch, {
            "results": [_card(1, "08:00", "14:00")],
            "timeslot_fallback": "06:00–16:00",
            "profile_delta": {"city": "Lyon", "timeslot_start": "06:00", "timeslot_end": "16:00"},
        })
        with caplog.at_level(logging.INFO, logger="b2c_concierge.metrics"):
            answer = _drive("Un hôtel à Lyon demain de 6h à 16h")
        assert answer == (
            "Vous pouvez réserver ce créneau.\n\nAucune offre ne couvre tout le créneau "
            "06:00–16:00 ; voici les offres les plus proches."
        )
        assert "window_match" not in fired[-1]  # labelled, not claimed

    def test_covering_cards_pass_untouched(self, scripted, monkeypatch):  # noqa: F811
        cards = [_card(1, "08:00", "14:00"), _card(2, "10:00", "16:00")]
        fired, hotels = self._install(scripted, monkeypatch, {
            "results": cards,
            "profile_delta": {"city": "Lyon", "timeslot_start": "12:00", "timeslot_end": "13:00"},
        }, synthesis="Deux hôtels couvrent 12h–13h.")
        assert _drive("Un hôtel à Lyon demain de 12h à 13h") == "Deux hôtels couvrent 12h–13h."
        assert hotels[-1] == cards
        assert "window_match" not in fired[-1]


def test_saying_none_covers_is_not_enough_the_cards_must_be_labelled_closest():
    # Live 2026-10-06: "aucune ne couvre entièrement le créneau de 6h à 16h".
    text, added = enforce_window_disclosure(
        "Plusieurs options, mais aucune ne couvre entièrement le créneau de 6h à 16h.",
        "06:00–16:00", "fr",
    )
    assert added and text.endswith("voici les offres les plus proches.")
