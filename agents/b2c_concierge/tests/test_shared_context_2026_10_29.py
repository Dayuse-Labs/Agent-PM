"""2026-10-29 — one dialogue context for the synthesis and the search leaf.

Prod after #173 (review of the 97 real conversations, B8-B10, B15, B17, A9):
the synthesis saw the history on the FAQ route only, and the search leaf saw
the current message alone. « 2 » answering « 1. Brooklyn (Maryland) 2.
Brooklyn (New York) » was answered « When you say "2", do you mean the 2nd
hotel card… or 2 guests? »; « 13 novembre » given before a homonym question
was lost once the question was answered.

Through the REAL runner and `_run_leaf` (only the A2A leg and the LLM are
faked): what the previous turns said, the question asked and the state they
left reach the synthesis prompt and the leaf's `query_params.dialogue`, on
every turn — bounded, with no position and no e-mail.
"""
from __future__ import annotations

import asyncio
import json

import litellm
from b2c_common.clarification import Clarification
from google.adk.runners import InMemoryRunner

from b2c_concierge import dialogue_context as dc
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import SessionProfile, leaf_profile_view

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

_BROOKLYN = Clarification.model_validate({
    "kind": "homonym",
    "subject": "Brooklyn",
    "options": [
        {"label": "Brooklyn (Maryland, US)", "city": "Brooklyn", "region": "Maryland", "country_code": "US"},
        {"label": "Brooklyn (New York, US)", "city": "Brooklyn", "region": "New York", "country_code": "US"},
    ],
})
_CARDS = [
    {"hotel_id": 11, "name": "Hotel Williamsburg"},
    {"hotel_id": 12, "name": "Dumbo House"},
    {"hotel_id": 13, "name": "Park Slope Inn"},
]


def _synthesis_prompt(llm) -> str:
    return llm.calls[-1]["messages"][1]["content"]


def _dialogue_block(prompt: str) -> dict:
    line = next(line for line in prompt.splitlines() if line.startswith("DIALOGUE ("))
    return json.loads(line.split("): ", 1)[1])


class TestThreeTurns:
    """A homonym question, its answer « 2 », then a refinement: the
    clarification, the date and the shortlist are seen by both."""

    def test_the_question_the_date_and_the_shortlist_reach_the_synthesis_and_the_leaf(
        self, monkeypatch, fake_leg, fake_profile_store  # noqa: F811
    ):
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}',
            '{"family": "search", "language": "fr", "answers_pending": "yes", "answer_option": 2}',
            "Voici des hôtels à Brooklyn.",
            '{"family": "search", "language": "fr"}',
            "Voici ceux avec un jacuzzi.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        # Turn 1: the leaf asks which Brooklyn (a template, no synthesis).
        fake_leg.response_payload = {"requires_clarification": True,
                                     "clarification": _BROOKLYN.model_dump(mode="json")}
        question = _run_turn(runner, session.id, "une chambre romantique à Brooklyn le 13 novembre")
        assert "Brooklyn (New York, US)" in question
        first = asyncio.run(fake_profile_store.get(session.id))
        assert first.date  # the day of the first message, stored by the concierge

        # Turn 2: « 2 » answers the question.
        fake_leg.response_payload = {"results": [dict(c) for c in _CARDS],
                                     "profile_delta": {"city": "Brooklyn"}}
        _run_turn(runner, session.id, "2")
        leaf_dialogue_2 = find_datapart(fake_leg.seen_outgoing_parts)["query_params"]["dialogue"]
        assert leaf_dialogue_2["turns"][0]["user"] == "une chambre romantique à Brooklyn le 13 novembre"
        assert "Brooklyn (New York, US)" in leaf_dialogue_2["turns"][0]["reply"]
        block_2 = _dialogue_block(_synthesis_prompt(llm))
        # The synthesis knows « 2 » answered the homonym question (B9) and the
        # day given before it (B8).
        assert "Brooklyn (New York, US)" in block_2["turns"][0]["reply"]
        assert "13 novembre" in block_2["turns"][0]["user"]
        assert block_2["state"]["date"] == first.date

        # Turn 3: a refinement — the whole conversation and the shortlist.
        fake_leg.response_payload = {"results": [dict(_CARDS[0])], "profile_delta": {}}
        _run_turn(runner, session.id, "et avec un jacuzzi ?")
        leaf_dialogue_3 = find_datapart(fake_leg.seen_outgoing_parts)["query_params"]["dialogue"]
        assert [t["user"] for t in leaf_dialogue_3["turns"]] == [
            "une chambre romantique à Brooklyn le 13 novembre", "2",
        ]
        assert leaf_dialogue_3["turns"][1]["hotels"] == 3
        block_3 = _dialogue_block(_synthesis_prompt(llm))
        assert block_3["state"]["date"] == first.date
        assert block_3["state"]["place"]["city"] == "Brooklyn"
        assert [h["name"] for h in block_3["state"]["on_screen"]] == [c["name"] for c in _CARDS]
        assert "Brooklyn (New York, US)" in block_3["turns"][0]["reply"]
        # The leaf reads the state in its profile_in: not sent twice.
        assert "state" not in leaf_dialogue_3

    def test_the_first_turn_carries_no_dialogue(self, monkeypatch, fake_leg):  # noqa: F811
        llm = _scripted_llm(monkeypatch, '{"family": "search", "language": "fr"}', "Voici.")
        fake_leg.response_payload = {"results": [dict(_CARDS[0])], "profile_delta": {"city": "Paris"}}
        runner = InMemoryRunner(root_agent)
        _run_turn(runner, _new_session(runner).id, "un hôtel à Paris demain")
        assert "dialogue" not in find_datapart(fake_leg.seen_outgoing_parts)["query_params"]
        assert "DIALOGUE (" not in _synthesis_prompt(llm)

    def test_a_faq_turn_gets_the_dialogue_too(self, monkeypatch, fake_leg):  # noqa: F811
        """Every route: the FAQ synthesis sees the search that came before."""
        llm = _scripted_llm(
            monkeypatch,
            '{"family": "search", "language": "fr"}', "Voici des hôtels à Paris.",
            '{"family": "faq", "language": "fr"}', "Oui, le paiement se fait à l'hôtel.",
        )
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        fake_leg.response_payload = {"results": [dict(c) for c in _CARDS], "profile_delta": {"city": "Paris"}}
        _run_turn(runner, session.id, "un hôtel à Paris demain")
        fake_leg.text, fake_leg.response_payload = "Payment at the hotel is possible.", {}
        _run_turn(runner, session.id, "je peux payer sur place ?")
        block = _dialogue_block(_synthesis_prompt(llm))
        assert block["turns"][0]["user"] == "un hôtel à Paris demain"
        assert [h["id"] for h in block["state"]["on_screen"]] == [11, 12, 13]


class TestWhatIsKept:
    def test_bounded_to_the_last_turns_and_cut(self):
        profile = SessionProfile()
        for i in range(dc.MAX_TURNS + 2):
            dc.record_exchange(profile, f"message {i} " + "x" * 500, "reply " + "y" * 500 + " Which day?", 5)
        assert len(profile.recent_turns) == dc.MAX_TURNS
        assert profile.recent_turns[0]["user"].startswith(f"message {2}")
        assert all(len(t["user"]) <= 200 and len(t["reply"]) <= 160 for t in profile.recent_turns)
        assert profile.recent_turns[-1]["reply"].endswith("Which day?")  # the tail is kept

    def test_no_email_no_position_no_policy_text(self):
        profile = SessionProfile(
            city="Paris", date="2026-11-13",
            search_anchor={"type": "gps", "lat": 48.871, "lon": 2.332, "label": None, "set_at_turn": 0},
        )
        dc.record_exchange(profile, "ma réservation, mon mail est jane.doe@example.com", "Voici.")
        dc.record_exchange(profile, "je peux annuler ?", "Oui, gratuitement jusqu'à 1 h avant.", policy_answer=True)
        context = dc.dialogue_context(profile)
        text = dc.dialogue_json(context)
        assert "jane.doe@example.com" not in text and "[email]" in text
        assert "48.871" not in text and "2.332" not in text
        assert context["state"]["place"]["near_device_position"] is True
        assert "gratuitement" not in text and dc.POLICY_REPLY in text

    def test_the_question_asked_rides_along_when_the_reply_cut_lacks_it(self):
        profile = SessionProfile(last_clarifying_question="Pour combien de personnes ?")
        dc.record_exchange(profile, "un hôtel à Lyon", "Voici des hôtels à Lyon. " + "z" * 300 + " Bonne journée.")
        assert dc.dialogue_context(profile)["asked"] == "Pour combien de personnes ?"
        profile.recent_turns = []
        dc.record_exchange(profile, "un hôtel à Lyon", "Voici. Pour combien de personnes ?")
        assert "asked" not in dc.dialogue_context(profile)

    def test_the_leaf_profile_view_does_not_carry_the_raw_turns(self):
        profile = SessionProfile()
        dc.record_exchange(profile, "un hôtel à Lyon", "Voici.")
        assert "recent_turns" not in leaf_profile_view(profile)

    def test_size_is_bounded_and_measured(self):
        """Worst case: 3 full turns, a long question, a full state, in words
        (a run of one letter tokenizes unlike text). Measured with the o200k
        tokenizer (the gpt-4o / gpt-5 family's)."""
        words = ("hôtel chambre demain après-midi piscine spa près de la gare avec mon ami pour "
                 "deux personnes Brooklyn New York jacuzzi tomorrow afternoon between 2pm and 6pm").split()

        def text(n: int) -> str:
            out = ""
            while len(out) < n:
                out += words[len(out) % len(words)] + " "
            return out

        profile = SessionProfile(
            city="San Francisco", zone="Fisherman's Wharf", metro="San Francisco Bay Area",
            region_anchor="California", country_anchor="US", date="2026-11-13",
            timeslot_start="14:00", timeslot_end="20:00", amenities=["pool", "spa"],
            preferred_amenities=["jacuzzi"], standing="upscale", adults=2, children=1,
            requested_budget={"amount": 150, "currency": "USD", "unit": "total"},
            last_results=[{"hotel_id": 100000 + i, "name": "Hyatt Regency San Francisco " * 4} for i in range(5)],
            last_clarifying_question=text(400) + "?",
        )
        for _ in range(dc.MAX_TURNS + 1):
            dc.record_exchange(profile, text(900), text(900), 5)
        context = dc.dialogue_context(profile)
        synthesis_tokens = litellm.token_counter(model="gpt-4o", text=dc.dialogue_json(context))
        leaf_tokens = litellm.token_counter(model="gpt-4o", text=dc.dialogue_json(dc.leaf_dialogue(context)))
        assert len(dc.dialogue_json(context)) <= 2200
        assert synthesis_tokens <= 600 and leaf_tokens <= 400
