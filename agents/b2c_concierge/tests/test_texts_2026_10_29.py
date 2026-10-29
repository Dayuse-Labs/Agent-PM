"""Point 6 (prod after #173, 97 conversations of 2026-10-28/29): the texts.

- The ANGLE said « EVERY option is outside the centre … the user asked for the
  city » around a device position, an airport, a region or a spot the
  geocoder missed (19 syntheses: « tutte fuori dal centro di Ferrara »,
  « 15–25 km outside the city center » for O'Hare). It is now said from the
  point the distances are measured from, and never for an area.
- 56 of 95 syntheses led on the biggest discount, a romantic, 5-star, pool or
  near-the-airport request included. The need the search recorded (its hard
  amenity filter, its clock window, its standing, the point to be near) now
  leads; the saving comes second.
- « a pool (not confirmed) (not confirmed) (The Delphi Hotel) »: a claim is
  read in its sentence, hedged once, never in a question.
- « relaxing the a pool and a spa requirement », « up to 50 km » above cards
  under 5 km, « Aucun plafond de prix n'était appliqué à cette recherche. »
  opening a reply nobody asked it of.

Fixtures: hotel names and facts as the synthesis input carried them (no
message of any user).
"""
from __future__ import annotations

from b2c_concierge.agent import root_agent
from b2c_concierge.amenity_guard import amenity_claim_violations, apply_amenity_truthfulness
from b2c_concierge.ground_truth import synthesis_angle
from b2c_concierge.profile import SessionProfile
from b2c_concierge.relaxation_notice import relaxation_line, relaxation_note
from google.adk.runners import InMemoryRunner

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

# --- the angle: from the right point ------------------------------------------------------


def _far_cards(*km: float) -> list[dict]:
    return [
        {"name": f"Hotel {i}", "price_eur_cents": 9000 + i, "distance_km": d, "rating": 4.5, "rating_count": 40}
        for i, d in enumerate(km)
    ]


def test_a_city_search_far_from_its_centre_still_says_so():
    profile = SessionProfile(city="Milano", distance_origin={"type": "city_centroid", "feature_type": "place"})
    key, angle = synthesis_angle({"results": _far_cards(8.2, 10.9), "search_context": {"city": "Milano"}},
                                 profile=profile)
    assert key == "distance"
    assert "outside the centre of Milano (8-11 km" in angle


def test_around_the_device_position_the_distance_is_from_the_user_never_the_centre():
    # S011 (« Day room near me », GPS in New Jersey): cards at 5.9-16 km.
    profile = SessionProfile(distance_origin={"type": "gps", "label": "your current location"})
    key, angle = synthesis_angle({"results": _far_cards(5.9, 6.0, 16.1)}, profile=profile)
    assert key == "distance"
    assert "the user's own position" in angle
    assert "centre" not in angle.replace("never call it « the centre »", "")
    assert "asked for the city" not in angle


def test_around_an_airport_the_distance_is_from_the_airport():
    # O'Hare, prod: « 15–25 km outside the city center ».
    profile = SessionProfile(distance_origin={
        "type": "poi", "label": "O'Hare International Airport, Chicago", "place_kind": "airport",
    })
    _, angle = synthesis_angle({"results": _far_cards(15.0, 25.0)}, profile=profile)
    assert "from O'Hare International Airport, Chicago" in angle
    assert "asked for the city" not in angle


def test_an_area_searched_as_a_whole_has_no_centre_to_complain_about():
    # « Île-de-France », « Puglia » (Bari/Palese at 7-8 km): a region's point is its main city's.
    for profile in (
        SessionProfile(city="Puglia", city_is_area=True, distance_origin={"type": "city_centroid"}),
        SessionProfile(distance_origin={"type": "city_centroid", "place_kind": "region", "feature_type": "region"}),
    ):
        key, angle = synthesis_angle({"results": _far_cards(7.4, 8.1)}, profile=profile)
        assert key != "distance" and "centre" not in angle


def test_a_spot_that_could_not_be_placed_gets_no_centre_claim():
    # S028 « Santa Maria Maddalena » → « tutte fuori dal centro di Ferrara ».
    profile = SessionProfile(city="Ferrara", distance_origin={"type": "city_centroid"})
    response = {"results": _far_cards(29.0, 43.0),
                "search_context": {"city": "Ferrara", "landmark_unresolved": "Santa Maria Maddalena"}}
    assert synthesis_angle(response, profile=profile)[0] != "distance"


# --- the angle: the need first, the saving second --------------------------------------------


def _deal(name: str, cents: int, night: float, **extra) -> dict:
    return {"name": name, "price_eur_cents": cents, "rating": 4.6, "rating_count": 30,
            "timeslots": [{"start": "08:00", "end": "14:00", "original_price": night}], **extra}


def test_a_requested_amenity_leads_before_the_biggest_saving():
    # la_rooftop_pool: « the best value pick is Hotel Indigo (54 % below) ».
    hotels = [
        _deal("The Delphi Hotel", 11500, 160.0, distance_km=1.2, amenities=["pool"]),
        _deal("Hotel Indigo - Los Angeles Downtown", 13800, 300.0, distance_km=2.0, amenities=["pool"]),
    ]
    profile = SessionProfile(city="Los Angeles", distance_origin={"type": "city_centroid", "feature_type": "place"})
    response = {"results": hotels, "search_context": {"city": "Los Angeles", "amenities": ["pool"]}}
    key, angle = synthesis_angle(response, profile=profile)
    assert key == "amenity"
    assert "The Delphi Hotel" in angle and "pool" in angle
    assert "saving only after that" in angle
    # The anti-repeat still falls through to the saving on the next turn.
    assert synthesis_angle(response, "amenity", profile=profile)[0] == "discount"


def test_an_amenity_the_rescue_relaxed_is_not_claimed_for_every_card():
    hotels = [_deal("Hilton Munich Airport", 9000, 200.0, distance_km=28.9)]
    response = {"results": hotels + [_deal("B", 9500, 120.0, distance_km=29.0)],
                "search_context": {"city": "Munich", "amenities": ["jacuzzi"]},
                "relaxation": {"steps": ["amenities"], "amenities": ["jacuzzi"]}}
    assert synthesis_angle(response, profile=SessionProfile())[0] != "amenity"


def test_the_requested_window_names_the_cards_that_cover_it():
    # roma_pomeriggio style: a 13-18 window, one card of four covers it.
    hotels = [
        _deal("Comfort Hotel Bolivar", 12500, 300.0),
        {**_deal("Hotel Villa Delle Rose", 5900, 90.0), "timeslots": [{"start": "10:00", "end": "18:00"}]},
    ]
    response = {"results": hotels, "search_context": {"timeslot_start": "13:00", "timeslot_end": "18:00"}}
    key, angle = synthesis_angle(response, profile=SessionProfile(distance_origin={"type": "city_centroid"}))
    assert key == "window"
    assert "only Hotel Villa Delle Rose cover" in angle and "13:00-18:00" in angle


def test_near_a_landmark_the_nearest_card_leads_before_the_saving():
    # tour_eiffel_14_18: the reply led on Hôtel de Castiglione's 49 %.
    hotels = [
        _deal("Hôtel de Castiglione", 15000, 300.0, distance_km=2.4),
        _deal("Pullman Paris Tour Eiffel", 12900, 160.0, distance_km=0.3),
    ]
    profile = SessionProfile(distance_origin={"type": "poi", "label": "Tour Eiffel, Paris", "place_kind": "landmark"})
    key, angle = synthesis_angle({"results": hotels}, profile=profile)
    assert key == "nearest"
    assert "Pullman Paris Tour Eiffel, about 0.3 km away" in angle and "Tour Eiffel, Paris" in angle


def test_an_upscale_request_leads_with_the_best_rated_hotel():
    hotels = [
        {**_deal("The Scott Hotel", 6000, 200.0), "rating": 4.1, "rating_count": 50},
        {**_deal("Hotel Amigo", 19000, 260.0), "rating": 4.8, "rating_count": 22},
    ]
    response = {"results": hotels, "search_context": {"standing": "upscale"}}
    key, angle = synthesis_angle(response, profile=SessionProfile(distance_origin={"type": "city_centroid"}))
    assert key == "standing" and "Hotel Amigo" in angle and "4.8/5" in angle


def test_with_no_expressed_need_the_saving_still_leads():
    hotels = [_deal("Deal Palace", 5000, 150.0, distance_km=1.0), _deal("B", 9000, 100.0, distance_km=2.0)]
    profile = SessionProfile(distance_origin={"type": "city_centroid", "feature_type": "place"})
    assert synthesis_angle({"results": hotels, "search_context": {"city": "Paris"}}, profile=profile)[0] == "discount"


def test_the_origin_reaches_the_synthesis_prompt(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    """Wired: the profile's `distance_origin` (the leaf's delta of THIS turn)
    decides the angle the prompt carries."""
    fake_leg.response_payload = {
        "results": [
            {"id": 1, "name": "Residence Inn Deptford", "price_eur_cents": 8741, "distance_km": 5.9},
            {"id": 2, "name": "Fairfield Inn Deptford", "price_eur_cents": 8742, "distance_km": 6.0},
        ],
        "profile_delta": {"distance_origin": {"type": "gps", "latitude": 39.8, "longitude": -75.0,
                                              "label": "your current location"}},
    }
    llm = _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Two options near you.")
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    _run_turn(runner, session.id, "day room near me")
    prompt = llm.calls[-1]["messages"][1]["content"]
    assert "the user's own position" in prompt
    assert "outside the centre" not in prompt


def test_a_completed_page_cites_the_added_cards_real_distance_not_the_radius():
    # tour_eiffel_14_18: « recherche élargie (jusqu'à 50 km) » above cards at 2.0-2.4 km.
    from b2c_concierge.agent import completed_note

    cards = [{"name": n, "distance_km": d} for n, d in (("A", 1.9), ("B", 2.0), ("C", 2.0), ("D", 2.3), ("E", 2.4))]
    note = completed_note({"added": 3, "radius_km": 50.0}, 5, cards)
    assert "the farthest of them is 2.4 km away" in note
    assert "50" not in note


# --- « (not confirmed) »: the sentence, once, never a question ----------------------------------


_LA = [
    {"name": "AC Hotel by Marriott Beverly Hills", "amenities": []},
    {"name": "Courtyard Los Angeles LAX", "amenities": []},
    {"name": "The Delphi Hotel", "amenities": []},
]


def test_a_paragraph_naming_three_hotels_hedges_the_word_once():
    # S059: « … or a pool (not confirmed) (not confirmed) (The Delphi Hotel) ».
    text = ("For Wednesday, October 28, 2026 near Beverly Hills/Westside, AC Hotel by Marriott Beverly Hills "
            "is the most on-target; higher prices may buy longer hours (Courtyard Los Angeles LAX 09:00–20:00) "
            "or a pool (The Delphi Hotel). Want only Beverly Hills/Westside?")
    result, corrections = apply_amenity_truthfulness(text, _LA, "en")
    assert result.count("(not confirmed)") == 1
    assert "a pool (not confirmed) (The Delphi Hotel)" in result
    assert corrections == {"The Delphi Hotel": ["pool"]}


def test_an_offer_or_a_question_to_the_user_is_never_annotated():
    # S090 / S081 / S092: « … must-haves like parking (not confirmed) or a pool (not confirmed) ».
    hotels = [{"name": "Home2 Suites by Hilton Falls Church", "amenities": []}]
    texts = [
        "For Friday, October 30, 2026 in Fairfax, the standout value is Home2 Suites by Hilton Falls Church. "
        "Tell me whether you need anything specific like parking or a pool, and I'll narrow it down.",
        "Want me to keep Home2 Suites by Hilton Falls Church only if it has parking or a pool?",
    ]
    for text in texts:
        assert apply_amenity_truthfulness(text, hotels, "en") == (text, {})


def test_the_word_belongs_to_the_nearest_hotel_of_its_sentence():
    hotels = [{"name": "Hotel Bristol Spa", "amenities": ["Spa"]},
              {"name": "Novotel Toronto North York", "amenities": ["Indoor pool"]}]
    text = "Hotel Bristol Spa is the cheapest, and Novotel Toronto North York has an indoor pool."
    assert amenity_claim_violations(text, hotels) == {}


# --- the relaxation sentence ----------------------------------------------------------------------


def test_relaxed_amenities_read_without_a_doubled_article():
    # S060 / S080: « relaxing the a pool and a spa requirement ».
    line = relaxation_line({"steps": ["amenities"], "amenities": ["pool", "spa"], "searched_date": "2026-10-30"},
                           {"city": "Perth", "date": "2026-10-30"}, "en")
    assert "relaxing the requirement for a pool and a spa." in line
    assert "the a " not in line and "the an " not in line
    removed = relaxation_line({"request": {"requested": ["filters"], "removed": ["amenities"],
                                           "amenities": ["shuttle"], "chip": "filters"}}, None, "en")
    assert removed == "I removed the filter for an airport shuttle."


def test_the_widened_area_is_the_cards_real_distance():
    # D6 (SFO, midnight-6:30): « relaxing the area (up to 50 km) » above cards all under 5 km.
    relaxation = {"steps": ["radius", "timeslot"], "radius_km": 50.0, "searched_date": "2026-10-29"}
    context = {"city": "San Francisco", "zone": "SFO", "date": "2026-10-29", "radius_km": 5.0}
    near = [{"name": "A", "distance_km": 1.4}, {"name": "B", "distance_km": 4.6}]
    line = relaxation_line(relaxation, context, "en", results=near)
    assert "50 km" not in line and "the area" not in line
    assert "relaxing the time slot." in line
    far = [{"name": "A", "distance_km": 3.0}, {"name": "B", "distance_km": 28.9}]
    assert "the area (up to 29 km)" in relaxation_line(relaxation, context, "en", results=far)
    # A city search sent no radius: MCP's 20 km disc is the yardstick.
    city = {"city": "Munich", "date": "2026-10-30"}
    assert "the area" not in relaxation_line(relaxation, city, "en", results=[{"distance_km": 12.0}])


def test_a_relax_the_model_read_into_a_message_is_not_answered_nothing_to_loosen():
    # S052 T1 « … prix abordable » → « Aucun plafond de prix n'était appliqué à cette recherche. »;
    # S015 « Uhrzeit egal » → « Für diese Suche war kein Filter gesetzt. »
    assert relaxation_line({"request": {"requested": ["budget"], "no_budget": True}}, None, "fr") == ""
    assert relaxation_line({"request": {"requested": ["filters"], "nothing_to_remove": True}}, None, "de") == ""
    assert relaxation_note({"request": {"requested": ["budget"], "no_budget": True}}) == ""
    # The concierge's chip, clicked: still answered.
    assert relaxation_line({"request": {"requested": ["budget"], "no_budget": True, "chip": "budget"}},
                           None, "fr") == "Aucun plafond de prix n'était appliqué à cette recherche."
    assert "loosen" in relaxation_note({"request": {"requested": ["filters"], "nothing_to_remove": True,
                                                    "chip": "filters"}})
