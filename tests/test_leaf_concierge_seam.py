"""Leaf → concierge wire-seam lock (S-G10, fixes S-G9 finding 1).

The 07/23 gate re-run showed `distance_origin` computed correctly by the leaf
but NEVER reaching the profile: `emit_search_datapart` attached it as a
top-level sibling of `profile_delta`, while the concierge only ever reads
`profile_delta` off the wire. Each side's own unit tests passed around the bug
(the leaf test asserted the buggy top-level placement; the concierge tests
constructed `SessionProfile(distance_origin=...)` directly). This test walks
the actual seam: leaf emit → decoded DataPart → `apply_profile_delta` →
`build_active_filters`, so a placement regression on either side fails here.
"""
from __future__ import annotations

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from b2c_concierge.facade import build_active_filters, normalize_hotels
from b2c_concierge.ground_truth import shortlist_ground_truth_block
from b2c_concierge.profile import (
    SessionProfile,
    apply_profile_delta,
    leaf_profile_view,
    record_search_outcome,
)
from hotel_search_agent.budget_injection import inject_profile_budget
from hotel_search_agent.equipment_ids import enforce_equipment_filters
from hotel_search_agent.response_bridge import (
    STATE_SEARCH_DATE_KEY as _SEARCH_DATE_KEY,
)
from hotel_search_agent.response_bridge import (
    decode_datapart,
    emit_search_datapart,
    normalize_hotel,
)

_RESULTS_KEY = "temp:hotel_search_results"
_DISTANCE_ORIGIN_KEY = "temp:hotel_search_distance_origin"


class _Ctx:
    def __init__(self, state):
        self.state = state


def test_distance_origin_travels_from_leaf_emit_to_active_filters():
    origin = {"latitude": 48.8566, "longitude": 2.3522, "label": "Paris", "type": "city_centroid"}
    content = emit_search_datapart(
        _Ctx({
            _RESULTS_KEY: [{"id": 1, "name": "Villa", "latitude": 48.8, "longitude": 2.3, "distance_km": 0.5}],
            _DISTANCE_ORIGIN_KEY: origin,
        })
    )
    payload = next(d for d in (decode_datapart(p) for p in content.parts) if d is not None)

    profile = SessionProfile()
    apply_profile_delta(profile, payload.get("profile_delta") or {}, "hotel in Paris")

    assert profile.distance_origin == origin
    assert build_active_filters(profile)["distance_origin"] == origin


def test_numeric_price_and_review_count_survive_the_whole_card_path():
    """S-CX3a: a numeric price is worthless if any hop drops or mangles it —
    walk the REAL card path (leaf normalize → emit → JSON DataPart → decode →
    facade payload mapping), the same class of seam that swallowed
    `distance_origin` above. The JSON round-trip is part of the point: the
    price must arrive as a plain int, not a float that prints as 5432.0."""
    card = normalize_hotel(
        {
            "hotelId": 22293,
            "name": "Villa Paris Orly",
            "globalAverageRating": 4.64,
            "totalReview": 412,
            "offers": [
                {"priceEuro": 5432, "startHour": 10, "startMinute": 0, "endHour": 17, "endMinute": 0}
            ],
        }
    )
    content = emit_search_datapart(_Ctx({_RESULTS_KEY: [card]}))
    payload = next(d for d in (decode_datapart(p) for p in content.parts) if d is not None)

    out = normalize_hotels(payload["results"])[0]
    assert out["price"] == "€54.32"  # the display string still ships
    assert out["price_eur_cents"] == 5432 and isinstance(out["price_eur_cents"], int)
    assert out["rating_count"] == 412


def test_the_link_books_the_offer_the_card_showed(monkeypatch):
    """S-CX5, the whole point of the lot: walk the real path from an MCP
    `search_offers` hotel to the arguments `generate_booking_link` is called
    with — leaf normalize → emit → DataPart → record_search_shortlist →
    _quote_fresh_offer — and assert the link describes the SAME offer the card
    displayed.

    Prod session 2026-07-27: the card said €87 / 11:00-19:00 / tomorrow and the
    link carried €90 / 17:00-23:00 / today. Each side's own tests passed around
    it, exactly like `distance_origin` above — the quote step never saw the
    card, so only a seam test can hold this."""
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from b2c_concierge import inline_tools
    from b2c_concierge.profile import record_search_shortlist

    asked_date, today = "2026-07-28", "2026-07-27"
    # One hotel as search_offers really sends it: several offers for the asked
    # day, the cheapest NOT listed first.
    card = normalize_hotel(
        {
            "hotelId": 22293,
            "name": "Hôtel Mercure Paris La Défense",
            "cityName": "courbevoie",
            "offers": [
                {
                    "ratePlanUuid": "evening-plan",
                    "availabilityDate": asked_date,
                    "startHour": 17,
                    "endHour": 23,
                    "priceEuro": 9000,
                },
                {
                    "ratePlanUuid": "day-plan",
                    "availabilityDate": asked_date,
                    "startHour": 11,
                    "endHour": 19,
                    "priceEuro": 8700,
                },
            ],
        }
    )
    assert card["price"] == "€87.00" and card["timeslots"] == [{"start": "11:00", "end": "19:00"}]

    content = emit_search_datapart(_Ctx({_RESULTS_KEY: [card]}))
    payload = next(d for d in (decode_datapart(p) for p in content.parts) if d is not None)

    profile = SessionProfile(date=asked_date)
    record_search_shortlist(profile, payload["results"])

    calls: list[tuple[str, dict]] = []

    class _Result:
        isError = False
        structuredContent = {"confirmationRequired": True, "hotel": {}, "offer": {}}
        content: list = []

    class _Session:
        async def call_tool(self, name, arguments, *, meta=None):
            calls.append((name, dict(arguments)))
            # A lookup here would be the old bug: it answers with TODAY's offer.
            if name == "get_hotel_details":
                return SimpleNamespace(
                    isError=False,
                    content=[],
                    structuredContent={
                        "hotel": {"hotelId": 22293},
                        "offers": [
                            {
                                "ratePlanUuid": "todays-plan",
                                "availabilityDate": today,
                                "startHour": 17,
                                "endHour": 23,
                                "priceEuro": 9000,
                            }
                        ],
                    },
                )
            return _Result()

    @asynccontextmanager
    async def _fake_session():
        yield _Session()

    monkeypatch.setattr(inline_tools, "_mcp_session", _fake_session)
    quote = asyncio.run(
        inline_tools.generate_booking_link(
            "Hôtel Mercure Paris La Défense", profile, user_confirmed=False
        )
    )

    link_args = next(args for name, args in calls if name == "generate_booking_link")
    assert link_args["date"] == asked_date
    assert link_args["ratePlanUuid"] == "day-plan"
    assert link_args["confirmed"] is False
    assert (quote["price"], quote["start_time"], quote["end_time"]) == ("€87.00", "11:00", "19:00")


def test_search_date_travels_from_leaf_emit_to_the_concierge_decisions():
    """S-CX6: the same-day cutoff signal is useless if it dies on the wire — and
    it drives BOTH concierge decisions (the mandatory disclosure and the chips),
    so a placement regression here would silently restore the old dead end.
    Walks emit → JSON DataPart → decode → ground-truth block + chip selection.
    """
    search_date = {
        "date": "2026-07-28",
        "same_day": False,
        "cutoff_fallback_from": "2026-07-27",
    }
    content = emit_search_datapart(
        _Ctx({
            _RESULTS_KEY: [{"id": 1, "name": "Villa Paris Orly", "price": "€54.00"}],
            _SEARCH_DATE_KEY: search_date,
        })
    )
    payload = next(d for d in (decode_datapart(p) for p in content.parts) if d is not None)
    assert payload["search_date"] == search_date  # survived the JSON round-trip

    block = shortlist_ground_truth_block(payload, SessionProfile())
    # The date reaches the prompt written out, never as ISO (QA 2026-09-08 n°2).
    assert "MANDATORY DISCLOSURE" in block and "Tuesday, July 28, 2026" in block


def test_same_day_dead_end_travels_to_the_date_chips():
    content = emit_search_datapart(
        _Ctx({
            _RESULTS_KEY: [],
            _SEARCH_DATE_KEY: {
                "date": "2026-07-27", "same_day": True, "cutoff_closed": True,
            },
        })
    )
    payload = next(d for d in (decode_datapart(p) for p in content.parts) if d is not None)

    profile = SessionProfile()
    wire_search_date = payload["search_date"]
    record_search_outcome(
        profile,
        results_count=len(payload["results"]),
        language="fr",
        same_day_dead_end=bool(wire_search_date.get("cutoff_closed")),
    )
    assert profile.last_suggestions == ["voir demain", "après-demain", "élargir la zone"]


# --- UX1: retracting a filter across turns ("enlève le spa") -----------------------------------
#
# The seam is the whole story here: the leaf's `enforce_equipment_filters`
# unions the request's `profile_in.amenities` with what the model extracted,
# `emit_search_datapart` sends the applied set back, and `apply_profile_delta`
# stores it — so a filter survives every turn by construction. Testing either
# side alone proves nothing about a RETRACTION, which needs both to agree.

_APPLIED_AMENITIES_KEY = "temp:hotel_search_applied_amenities"
_CLARIFY_QUESTION_KEY = "temp:hotel_search_clarify_question"
_GUARDS_FIRED_KEY = "temp:hotel_search_guards_fired"


class _LeafCtx:
    """ToolContext/CallbackContext stand-in for one leaf turn: dict-backed
    `.state`, plus the inbound `{query_params, profile_in}` DataPart the
    concierge really sends — wrapped by the REAL ADK a2a→genai converter, the
    exact hop `equipment_ids._profile_amenities` decodes."""

    def __init__(self, profile: SessionProfile | None = None, state: dict | None = None):
        self.state: dict = dict(state or {})
        self.user_content = None
        if profile is not None:
            datapart = a2a_types.Part(
                root=a2a_types.DataPart(
                    data={"query_params": {}, "profile_in": leaf_profile_view(profile)}
                )
            )
            self.user_content = genai_types.Content(
                role="user",
                parts=[
                    genai_types.Part(text="le message du tour"),
                    convert_a2a_part_to_genai_part(datapart),
                ],
            )


def _leaf_turn(profile: SessionProfile, message: str, **model_args) -> dict:
    """One full leaf→concierge turn: the model's extracted args go through
    `enforce_equipment_filters` (which owns every filter value), the search
    result is emitted as the A2A DataPart, and the concierge folds the delta
    back into `profile`. Returns the args MCP would actually have received."""
    ctx = _LeafCtx(profile)
    args = {"lat": 48.85, "lon": 2.35, "date": "2026-08-28", **model_args}
    enforce_equipment_filters(_LeafTool("search_offers"), args, ctx)
    ctx.state[_RESULTS_KEY] = [{"id": 1, "name": "Villa", "amenities": []}]
    content = emit_search_datapart(ctx)
    payload = next(d for d in (decode_datapart(p) for p in content.parts) if d is not None)
    apply_profile_delta(profile, payload.get("profile_delta") or {}, message)
    return args


class _LeafTool:
    def __init__(self, name: str) -> None:
        self.name = name


class TestFilterRetractionAcrossTurns:
    def test_a_clarification_turn_never_wipes_the_accumulated_amenities(self):
        """🪤 THE trap of this phase, and the only way this fix can break prod.

        On a turn that stops at `geocode_location` (a homonym clarification) or
        at `find_hotel_by_name`, `search_offers` never runs — so
        `enforce_equipment_filters` never writes
        `STATE_APPLIED_AMENITIES_KEY`. "Absent" and "written empty" are two
        different facts, and an unconditional `{"op": "set", "value": []}`
        would collapse them into one: every clarification turn would silently
        drop the filters the user stated three turns ago."""
        profile = SessionProfile(city="Paris", amenities=["spa", "pool"])
        ctx = _LeafCtx(profile, {_CLARIFY_QUESTION_KEY: "Le Paris du Texas ou celui de France ?"})
        content = emit_search_datapart(ctx)
        payload = next(d for d in (decode_datapart(p) for p in content.parts) if d is not None)

        # The slot must be ABSENT from the delta — carryover by construction.
        assert "amenities" not in (payload.get("profile_delta") or {})
        apply_profile_delta(profile, payload.get("profile_delta") or {}, "celui de France")
        assert profile.amenities == ["spa", "pool"]

    def test_a_search_turn_that_applied_nothing_still_wipes_nothing(self):
        # Same distinction, the other branch: a turn where search_offers DID
        # run and the profile carried no amenity writes an empty applied set.
        # Nothing to remove, nothing removed.
        profile = SessionProfile(city="Paris")
        _leaf_turn(profile, "un hôtel à Paris")
        assert profile.amenities == []

    def test_removing_a_filter_drops_it_from_the_next_search(self):
        """THE bug Fabien reported. Turn 1 asks for a spa, turn 2 asks to drop
        it — and the second `search_offers` must go out with NO equipment
        filter at all, not with the spa re-applied from the profile."""
        profile = SessionProfile(city="Paris")

        turn1 = _leaf_turn(profile, "un hôtel à Paris avec spa", amenities=["spa"])
        assert turn1["hotelEquipmentIds"] == [35]
        assert profile.amenities == ["spa"]  # accumulated, as designed

        turn2 = _leaf_turn(profile, "enlève le spa", amenities_removed=["spa"])
        assert "hotelEquipmentIds" not in turn2  # ← the signature of the bug
        assert profile.amenities == []  # and the retraction persists

    def test_a_retraction_survives_a_third_silent_turn(self):
        # The retraction has to be persisted, not just honored once: turn 3
        # mentions no amenity at all and must stay unfiltered.
        profile = SessionProfile(city="Paris")
        _leaf_turn(profile, "un hôtel à Paris avec spa", amenities=["spa"])
        _leaf_turn(profile, "enlève le spa", amenities_removed=["spa"])
        turn3 = _leaf_turn(profile, "moins cher")
        assert "hotelEquipmentIds" not in turn3
        assert profile.amenities == []

    def test_removing_one_filter_of_two_keeps_the_other(self):
        profile = SessionProfile(city="Paris")
        _leaf_turn(profile, "un hôtel à Paris avec spa et piscine", amenities=["spa", "pool"])
        assert profile.amenities == ["spa", "pool"]

        turn2 = _leaf_turn(profile, "enlève le spa", amenities_removed=["spa"])
        assert turn2["hotelEquipmentIds"] == [33, 34, 2982, 3000, 3001]  # pool only
        assert profile.amenities == ["pool"]

    def test_normal_accumulation_still_survives(self):
        # The accumulation rule is NOT the bug (occupancy.py's doctrine): a
        # filter stated on turn 1 must not need restating on turn 2.
        profile = SessionProfile(city="Paris")
        _leaf_turn(profile, "un hôtel à Paris avec piscine", amenities=["pool"])
        turn2 = _leaf_turn(profile, "et un spa", amenities=["spa"])
        assert turn2["hotelEquipmentIds"] == [33, 34, 2982, 3000, 3001, 35]
        assert profile.amenities == ["pool", "spa"]

    def test_a_fresh_negation_clears_a_filter_asked_for_earlier(self):
        # Collateral benefit: MCP has no negative filter, so "sans piscine"
        # and "enlève la piscine" are the same business effect — and today the
        # former keeps filtering on pool.
        profile = SessionProfile(city="Paris")
        _leaf_turn(profile, "un hôtel avec piscine", amenities=["pool"])
        turn2 = _leaf_turn(profile, "en fait un hôtel sans piscine", amenities_removed=["pool"])
        assert "hotelEquipmentIds" not in turn2
        assert profile.amenities == []


def test_a_budget_stated_on_turn_1_reaches_turn_2s_search_offers_args():
    """UX1 follow-up (measured + arbitrated by Fabien 2026-08-27): the exact
    gap the report found. `active_filters.budget_max` kept showing the
    profile's value while `priceRangeMax` was silently absent from the next
    turn's `search_offers` call — the display and the applied filter had
    drifted apart, mirror image of UX1's amenities-retraction bug.

    Walks the REAL seam: `SessionProfile.budget_max` → `leaf_profile_view`
    (what the concierge actually sends) → the real ADK a2a→genai DataPart
    envelope → `inject_profile_budget` (what the leaf actually reads)."""
    profile = SessionProfile(city="Paris", budget_max=80.0)
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(
            data={"query_params": {}, "profile_in": leaf_profile_view(profile)}
        )
    )
    tool_context = type("_ToolCtx", (), {})()
    tool_context.user_content = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part(text="montre m'en d'autres"),  # no price mentioned
            convert_a2a_part_to_genai_part(datapart),
        ],
    )

    args = {"lat": 48.85, "lon": 2.35, "date": "2026-08-28"}
    inject_profile_budget(_LeafTool("search_offers"), args, tool_context)

    assert args["priceRangeMax"] == 80.0


def test_a_daypart_replaces_a_clock_window_across_the_seam():
    """Option B (mcp-dayuse#8): the leaf's daypart delta lands in the profile,
    clears the earlier clock window, and travels back on the next turn."""
    from hotel_search_agent.response_bridge import STATE_DAYPART_KEY

    content = emit_search_datapart(
        _Ctx({_RESULTS_KEY: [{"id": 1, "name": "Villa"}], STATE_DAYPART_KEY: "afternoon"})
    )
    payload = next(d for d in (decode_datapart(p) for p in content.parts) if d is not None)
    profile = SessionProfile(timeslot_start="12:00", timeslot_end="13:00", timeslot_mode="range")
    apply_profile_delta(profile, payload["profile_delta"], "plutôt l'après-midi")
    assert profile.daypart == "afternoon"
    assert (profile.timeslot_start, profile.timeslot_end, profile.timeslot_mode) == (None, None, None)
    assert leaf_profile_view(profile)["daypart"] == "afternoon"


# --- QA14707 (Q04): the leaf's place question comes out as the concierge's template -----------
#
# The leaf (Q03) builds a `Clarification` and relays it top-level in its
# DataPart; the concierge (Q04) reads `data["clarification"]` and renders it by
# template. Each side's unit tests build the object by hand, so only this walk
# can catch a placement bug between them (S-G9): the real `geocode_location`,
# the real leaf callbacks, the real ADK genai↔A2A converters both ways, the real
# `_run_leaf` decode, then the spine's template.


class _V6:
    def __init__(self, candidates):
        self.candidates = candidates

    def geocode_candidates(self, query, **kwargs):
        return list(self.candidates)


class _NoSearchBox:
    def forward_candidates(self, query, **kwargs):
        return []


class _Inventory:
    def __init__(self, by_lat):
        self.by_lat = by_lat

    def count_near(self, lat, lon, *, radius_km=25.0):
        return self.by_lat.get(round(lat, 4), 0)


def _victoria(cc, region, *, rank, lat):
    from hotel_search_agent.mapbox_client import GeocodeCandidate

    return GeocodeCandidate(
        latitude=lat, longitude=0.0, name="Victoria",
        place_name=f"Victoria, {region}, {cc}", place_formatted=f"{region}, {cc}",
        feature_type="place", country_code=cc, region=region, bbox=None, rank=rank,
    )


def _over_the_wire(tool_result: dict) -> list[genai_types.Part]:
    """The leaf's turn as the concierge's leg receives it: leaf callbacks →
    genai parts → A2A parts (leaf executor) → genai parts (RemoteA2aAgent)."""
    from google.adk.a2a.converters.part_converter import convert_genai_part_to_a2a_part
    from hotel_search_agent.response_bridge import capture_after_tool

    ctx = _LeafCtx()
    assert capture_after_tool(_LeafTool("geocode_location"), {}, ctx, tool_result) is None
    content = emit_search_datapart(ctx)
    return [convert_a2a_part_to_genai_part(convert_genai_part_to_a2a_part(p)) for p in content.parts]


def _concierge_answer(monkeypatch, parts: list[genai_types.Part], message: str) -> str:
    import asyncio

    import fakeredis.aioredis
    from google.adk.events import Event
    from google.adk.runners import InMemoryRunner

    import b2c_concierge.agent as agent_module
    from b2c_concierge.profile_store import ProfileStore
    from b2c_concierge.triage import Triage

    class _Leg:
        async def run_async(self, ctx):
            yield Event(
                author="hotel_search_leg", invocation_id=ctx.invocation_id,
                content=genai_types.Content(role="model", parts=parts),
            )

    async def fake_classify(message, budget, invocation_id="", **kwargs):
        budget.charge("triage")
        return Triage("search", "fr", used_llm=False)

    async def no_llm(**kwargs):
        raise AssertionError("a clarification turn makes no synthesis call")

    store = ProfileStore(fakeredis.aioredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(agent_module, "get_profile_store", lambda: store)
    monkeypatch.setattr(agent_module, "_get_leg", lambda leaf: _Leg())
    monkeypatch.setattr(agent_module, "classify", fake_classify)
    monkeypatch.setattr(agent_module.litellm, "acompletion", no_llm)
    runner = InMemoryRunner(agent_module.root_agent)

    async def go():
        session = await runner.session_service.create_session(app_name=runner.app_name, user_id="u")
        content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
        return [
            e async for e in runner.run_async(user_id="u", session_id=session.id, new_message=content)
        ]

    events = asyncio.run(go())
    return "".join(
        p.text for e in events if not e.partial and e.content for p in e.content.parts or [] if p.text
    )


class TestClarificationSeam:
    def test_a_city_needed_question_comes_out_as_the_concierge_template(self, monkeypatch):
        from b2c_common.clarification import Clarification
        from hotel_search_agent import geocode_tool

        from b2c_concierge import templates

        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: _V6([]))
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _NoSearchBox())
        monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory({}))
        result = geocode_tool.geocode_core(
            zone="Gare du Nord", raw_user_message="un hôtel près de Gare du Nord demain"
        )
        assert result["clarification"]["kind"] == "city_needed"  # the leaf asked

        answer = _concierge_answer(monkeypatch, _over_the_wire(result), "un hôtel près de Gare du Nord demain")

        assert answer == templates.clarification_response(
            Clarification(kind="city_needed", subject="Gare du Nord"), "fr"
        )

    def test_a_homonym_comes_out_with_exactly_the_geocoders_options(self, monkeypatch):
        from b2c_common.clarification import Clarification
        from hotel_search_agent import geocode_tool

        from b2c_concierge import templates

        bc = _victoria("CA", "British Columbia", rank=0, lat=48.43)
        tx = _victoria("US", "Texas", rank=1, lat=28.80)
        micro = _victoria("AU", "Victoria", rank=2, lat=-37.47)  # 1 hotel: below the inventory tier
        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: _V6([bc, tx, micro]))
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _NoSearchBox())
        monkeypatch.setattr(
            geocode_tool, "get_inventory", lambda: _Inventory({48.43: 20, 28.80: 15, -37.47: 1})
        )
        result = geocode_tool.geocode_core(city="Victoria", raw_user_message="un hôtel à Victoria")

        answer = _concierge_answer(monkeypatch, _over_the_wire(result), "un hôtel à Victoria")

        expected = templates.clarification_response(Clarification.model_validate(result["clarification"]), "fr")
        assert answer == expected
        assert [line for line in answer.splitlines() if line[:1].isdigit()] == [
            "1. Victoria (British Columbia, CA)",
            "2. Victoria (Texas, US)",
        ]


# --- the user's own words, apart from the concierge's context (Q15) ----------
#
# On a turn that answers a place question, the concierge puts its context
# (EARLIER REQUEST / YOU ASKED <the Clarification as JSON> / REPLY) in a text
# part of its own, BEFORE the user's words. The leaf relies on that split:
# `read_user_words` (the last text part) is what becomes `raw_user_message`, and
# `read_input_text` (every part) is what a GeoIntent mention is checked against.
# The YOU ASKED JSON lists every option of a homonym question, so were it fed to
# the core the text state tier could pick another option's state. Each side's
# tests build their half of the message by hand; only this one builds the
# concierge's real outgoing message and reads it as the leaf does.

_EARLIER_REQUEST = "un hôtel à Manhattan demain de 14h à 18h"
_REPLY = "New York"


def _concierge_outgoing_message() -> list[genai_types.Part]:
    """The concierge's real outgoing parts on a clarification-answer turn
    (`_attach_outgoing_datapart` + `pending_clarification_context`), converted
    genai → A2A → genai as the leaf receives them."""
    from types import SimpleNamespace

    from google.adk.a2a.converters.part_converter import convert_genai_part_to_a2a_part

    from b2c_common.clarification import Clarification, ClarificationOption
    from b2c_concierge.agent import _attach_outgoing_datapart
    from b2c_concierge.profile import pending_clarification_context

    clarification = Clarification(
        kind="homonym",
        subject="Manhattan",
        options=[
            ClarificationOption(
                label="Manhattan (New York, US)", city="Manhattan", region="New York", country_code="US"
            ),
            ClarificationOption(
                label="Manhattan (Kansas, US)", city="Manhattan", region="Kansas", country_code="US"
            ),
        ],
    )
    context_text = pending_clarification_context(
        {"request": _EARLIER_REQUEST, "clarification": clarification.model_dump(mode="json")}
    )
    assert context_text and "YOU ASKED" in context_text
    event = SimpleNamespace(
        content=genai_types.Content(role="user", parts=[genai_types.Part(text=_REPLY)])
    )
    _attach_outgoing_datapart(
        SimpleNamespace(session=SimpleNamespace(events=[event])),
        {"query_params": {}, "profile_in": {}},
        context_text,
    )
    return [convert_a2a_part_to_genai_part(convert_genai_part_to_a2a_part(p)) for p in event.content.parts]


def _leaf_receives(parts: list[genai_types.Part]):
    from types import SimpleNamespace

    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


class TestUserWordsSeam:
    def test_the_context_is_its_own_part_before_the_users_words(self):
        from hotel_search_agent.response_bridge import read_input_text, read_user_words

        parts = _concierge_outgoing_message()
        texts = [p.text for p in parts if p.text]
        assert len(texts) == 2
        assert "YOU ASKED" in texts[0] and "Manhattan (Kansas, US)" in texts[0]
        assert texts[1] == _REPLY  # last text part, nothing joined into it

        ctx = _leaf_receives(parts)
        assert read_user_words(ctx) == _REPLY
        whole = read_input_text(ctx)
        assert _EARLIER_REQUEST in whole
        assert _REPLY in whole

    def test_geocode_core_gets_the_replys_words_and_no_part_of_the_question(self, monkeypatch):
        import asyncio

        from google.adk.tools.function_tool import FunctionTool

        from b2c_common.geo_intent import CityRef, GeoIntent
        from hotel_search_agent import geocode_tool

        seen: list[dict] = []

        def spy(**kwargs):
            seen.append(kwargs)
            return {"ok": False, "error": "spy"}

        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: _V6([]))
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _NoSearchBox())
        monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory({}))
        monkeypatch.setattr(geocode_tool, "geocode_core", spy)

        ctx = _leaf_receives(_concierge_outgoing_message())
        intent = GeoIntent(city=CityRef(mention="New York", canonical="New York"))
        asyncio.run(
            FunctionTool(geocode_tool.geocode_location).run_async(
                args={"intent": intent.model_dump(mode="json")}, tool_context=ctx
            )
        )

        assert len(seen) == 1
        raw = seen[0]["raw_user_message"]
        assert raw == _REPLY
        for leaked in ("Kansas", "YOU ASKED", "EARLIER REQUEST", "REPLY:", "Manhattan (", '"options"'):
            assert leaked not in raw
