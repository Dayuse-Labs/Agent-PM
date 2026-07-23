"""Inline MCP tools (S07): get_hotel_details/compare_hotels/generate_booking_link
wired to real MCP_B2C calls — tested offline against a fake ClientSession (no
network, no API key, per pytest.ini). Field shapes below mirror what MCP_B2C
staging actually returns (verified live during this session): `hotelId`,
amenities as `[{"id", "name"}, ...]`, `priceEuro` in EUR cents, and
`generate_booking_link`'s `{"link": {"url": ...}}` / no-link summary shapes.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from b2c_concierge import inline_tools
from b2c_concierge.profile import SessionProfile

SHORTLIST = [{"hotel_id": 22293, "name": "Villa Paris Orly"}]

HOTEL_DETAILS_RESPONSE = {
    "hotel": {
        "hotelId": 22293,
        "name": "Villa Paris Orly",
        "cityName": "rungis",
        "countryName": "France",
        "starRating": 3,
        "globalAverageRating": 4.64,
        "amenities": [{"id": 28, "name": "Free WiFi"}, {"id": 35, "name": "Spa"}],
    },
    "offers": [
        {
            "ratePlanId": 88333,
            "ratePlanUuid": "019d2b0c-4f34-7110-882d-d5709ca05b6f",
            "availabilityDate": "2026-07-20",
            "startHour": 17,
            "endHour": 23,
            "priceEuro": 5400,
        }
    ],
}

COMPARE_RESPONSE = {
    "hotels": [
        {
            "hotelId": 22293,
            "name": "Villa Paris Orly",
            "cityName": "rungis",
            "globalAverageRating": 4.64,
            "starRating": 3,
            "bestOffer": {"priceEuro": 5400},
            "amenities": [{"id": 28, "name": "Free WiFi"}],
        },
        {
            "hotelId": 22294,
            "name": "Red Roof Inn PLUS+ Secaucus",
            "cityName": "secaucus",
            "globalAverageRating": 4.6,
            "starRating": 3,
            "bestOffer": {"priceEuro": 5923},
            "amenities": [{"id": 35, "name": "Spa"}],
        },
    ],
    "bestBy": {"cheapest": 22293},
}

FIND_BY_NAME_RESPONSE = {"hotelId": 99001, "name": "Moxy NYC Chelsea", "cityName": "New York"}


class FakeResult:
    def __init__(self, data=None, is_error=False):
        self.structuredContent = data
        self.isError = is_error
        self.content: list = [] if not is_error else [SimpleNamespace(text="boom")]


class FakeSession:
    """`script` maps tool name -> a FakeResult, an Exception, or a callable
    `(arguments) -> FakeResult` for tools called more than once with
    different expected args (e.g. generate_booking_link)."""

    def __init__(self, script: dict):
        self.script = script
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        outcome = self.script.get(name)
        if callable(outcome) and not isinstance(outcome, FakeResult):
            outcome = outcome(arguments)
        if isinstance(outcome, Exception):
            raise outcome
        assert outcome is not None, f"unscripted call to {name}"
        return outcome


def _install(monkeypatch, script) -> FakeSession:
    session = FakeSession(script)

    @asynccontextmanager
    async def fake_mcp_session():
        yield session

    monkeypatch.setattr(inline_tools, "_mcp_session", fake_mcp_session)
    return session


def _run(coro):
    return asyncio.run(coro)


class TestGetHotelDetails:
    def test_resolves_via_shortlist_without_a_find_by_name_call(self, monkeypatch):
        session = _install(
            monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)}
        )
        profile = SessionProfile(last_results=SHORTLIST)
        result = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert result["ok"] is True
        hotel = result["hotel"]
        assert hotel["id"] == 22293
        assert hotel["amenities"] == ["Free WiFi", "Spa"]
        assert hotel["price"] == "€54.00"
        assert [c[0] for c in session.calls] == ["get_hotel_details"]

    def test_resolves_the_real_photo_url_from_main_photo_normal(self, monkeypatch):
        response = {
            **HOTEL_DETAILS_RESPONSE,
            "hotel": {**HOTEL_DETAILS_RESPONSE["hotel"], "mainPhotoNormal": "/hotels/22293/photo.png"},
        }
        _install(monkeypatch, {"get_hotel_details": FakeResult(response)})
        profile = SessionProfile(last_results=SHORTLIST)
        result = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert result["hotel"]["image_urls"] == ["https://static.dayuse.com/hotels/22293/photo.png"]

    def test_omits_image_urls_without_a_main_photo_normal(self, monkeypatch):
        _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
        profile = SessionProfile(last_results=SHORTLIST)
        result = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert "image_urls" not in result["hotel"]

    def test_stamps_currency_code_when_mcp_sends_it(self, monkeypatch):
        # S-G7: live-probed 2026-07-23 — get_hotel_details returns a per-hotel
        # currencyCode; display-only, priceEuro is unaffected (no conversion).
        response = {
            **HOTEL_DETAILS_RESPONSE,
            "hotel": {**HOTEL_DETAILS_RESPONSE["hotel"], "currencyCode": "usd"},
        }
        _install(monkeypatch, {"get_hotel_details": FakeResult(response)})
        profile = SessionProfile(last_results=SHORTLIST)
        result = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert result["hotel"]["currency_code"] == "USD"
        assert result["hotel"]["price"] == "€54.00"

    def test_omits_currency_code_when_absent(self, monkeypatch):
        _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
        profile = SessionProfile(last_results=SHORTLIST)
        result = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert "currency_code" not in result["hotel"]

    def test_falls_back_to_find_hotel_by_name_when_not_in_shortlist(self, monkeypatch):
        session = _install(
            monkeypatch,
            {
                "find_hotel_by_name": FakeResult(FIND_BY_NAME_RESPONSE),
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
            },
        )
        profile = SessionProfile(last_results=[])
        result = _run(inline_tools.get_hotel_details("Moxy Chelsea", profile))
        assert result["ok"] is True
        assert [c[0] for c in session.calls] == ["find_hotel_by_name", "get_hotel_details"]

    def test_hotel_not_found_degrades_honestly(self, monkeypatch):
        _install(monkeypatch, {"find_hotel_by_name": FakeResult(is_error=True)})
        profile = SessionProfile()
        result = _run(inline_tools.get_hotel_details("nonexistent", profile))
        assert result == {"ok": False, "error": "hotel not found"}

    def test_find_by_name_response_wrapped_under_hotel_key_is_unwrapped(self, monkeypatch):
        # Verified live against MCP_B2C: find_hotel_by_name wraps the
        # identity under "hotel" ({"hotel": {"hotelId": ..., "name": ...}}),
        # NOT flat at the top level like get_hotel_details/compare_hotels.
        session = _install(
            monkeypatch,
            {
                "find_hotel_by_name": FakeResult(
                    {"hotel": {"hotelId": 22293, "name": "Villa Paris Orly"}}
                ),
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
            },
        )
        profile = SessionProfile(last_results=[])
        result = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert result["ok"] is True
        details_call = next(c for c in session.calls if c[0] == "get_hotel_details")
        assert details_call[1]["hotelId"] == 22293

    def test_a_full_sentence_reference_is_stripped_before_the_mcp_fallback(self, monkeypatch):
        # Verified live: MCP find_hotel_by_name tolerates typos/partial input
        # in the NAME itself, but not a whole surrounding sentence ("Book
        # Villa Paris Orly for me" -> HotelNotFoundError). No LLM entity
        # extraction runs in this spine, so the fallback strips common
        # request phrasing itself before querying.
        session = _install(
            monkeypatch,
            {
                "find_hotel_by_name": FakeResult({"hotelId": 22293, "name": "Villa Paris Orly"}),
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
            },
        )
        profile = SessionProfile(last_results=[])
        result = _run(inline_tools.get_hotel_details("Book Villa Paris Orly for me", profile))
        assert result["ok"] is True
        find_call = next(c for c in session.calls if c[0] == "find_hotel_by_name")
        assert find_call[1]["name"] == "Villa Paris Orly"

    def test_empty_reference_degrades_without_any_mcp_call(self, monkeypatch):
        session = _install(monkeypatch, {})
        result = _run(inline_tools.get_hotel_details("   ", SessionProfile()))
        assert result["ok"] is False
        assert session.calls == []

    def test_stale_token_only_shortlist_hit_never_shadows_the_global_lookup(self, monkeypatch):
        # S12 audit 2026-07-20: a stale shortlist entry ("Wren Valley Inn")
        # sharing only the word "wren" with the explicitly-named "Sir
        # Christopher Wren Hotel" must NOT resolve to itself with zero
        # verification — the global find_hotel_by_name must still run, and
        # ITS result must win.
        session = _install(
            monkeypatch,
            {
                "find_hotel_by_name": FakeResult(
                    {"hotelId": 55, "name": "Sir Christopher Wren Hotel"}
                ),
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
            },
        )
        profile = SessionProfile(last_results=[{"hotel_id": 99, "name": "Wren Valley Inn"}])
        result = _run(inline_tools.get_hotel_details("Sir Christopher Wren Hotel", profile))
        assert result["ok"] is True
        assert [c[0] for c in session.calls] == ["find_hotel_by_name", "get_hotel_details"]
        details_call = next(c for c in session.calls if c[0] == "get_hotel_details")
        assert details_call[1]["hotelId"] == 55  # the MCP hotel, never the stale 99

    def test_stale_token_only_shortlist_hit_is_a_last_resort_when_mcp_degrades(self, monkeypatch):
        # Same stale, token-only shortlist — but this time MCP itself fails.
        # The weak hit must still be used rather than dead-ending (honest
        # degradation, "never a dead end" precedent).
        session = _install(
            monkeypatch,
            {
                "find_hotel_by_name": FakeResult(is_error=True),
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
            },
        )
        profile = SessionProfile(last_results=[{"hotel_id": 99, "name": "Wren Valley Inn"}])
        result = _run(inline_tools.get_hotel_details("Sir Christopher Wren Hotel", profile))
        assert result["ok"] is True
        details_call = next(c for c in session.calls if c[0] == "get_hotel_details")
        assert details_call[1]["hotelId"] == 99


class TestCompareHotels:
    SHORTLIST_TWO = [
        {"hotel_id": 22293, "name": "Villa Paris Orly"},
        {"hotel_id": 22294, "name": "Red Roof Inn PLUS+ Secaucus"},
    ]

    def test_two_hotels_named_in_the_message_resolve_from_the_shortlist(self, monkeypatch):
        session = _install(monkeypatch, {"compare_hotels": FakeResult(COMPARE_RESPONSE)})
        profile = SessionProfile(last_results=self.SHORTLIST_TWO)
        result = _run(inline_tools.compare_hotels("compare Villa Paris Orly and Red Roof", profile))
        assert result["ok"] is True
        assert len(result["hotels"]) == 2
        assert result["hotels"][0]["price"] == "€54.00"
        compare_call = next(c for c in session.calls if c[0] == "compare_hotels")
        assert set(compare_call[1]["hotelIds"]) == {22293, 22294}
        # compare_hotels never falls back to MCP find_hotel_by_name (scope:
        # shortlist only) — nothing else should have been called.
        assert {c[0] for c in session.calls} == {"compare_hotels"}

    def test_compared_hotels_carry_the_real_photo_url(self, monkeypatch):
        response = {
            **COMPARE_RESPONSE,
            "hotels": [
                {**COMPARE_RESPONSE["hotels"][0], "mainPhotoNormal": "/hotels/22293/photo.png"},
                COMPARE_RESPONSE["hotels"][1],
            ],
        }
        _install(monkeypatch, {"compare_hotels": FakeResult(response)})
        profile = SessionProfile(last_results=self.SHORTLIST_TWO)
        result = _run(inline_tools.compare_hotels("compare Villa Paris Orly and Red Roof", profile))
        villa = next(h for h in result["hotels"] if h["id"] == 22293)
        red_roof = next(h for h in result["hotels"] if h["id"] == 22294)
        assert villa["image_urls"] == ["https://static.dayuse.com/hotels/22293/photo.png"]
        assert "image_urls" not in red_roof

    def test_defaults_to_the_on_screen_shortlist_when_no_names_resolve(self, monkeypatch):
        session = _install(monkeypatch, {"compare_hotels": FakeResult(COMPARE_RESPONSE)})
        profile = SessionProfile(last_results=self.SHORTLIST_TWO)
        result = _run(inline_tools.compare_hotels("compare these hotels", profile))
        assert result["ok"] is True
        compare_call = next(c for c in session.calls if c[0] == "compare_hotels")
        assert set(compare_call[1]["hotelIds"]) == {22293, 22294}

    def test_fewer_than_two_resolvable_hotels_degrades_honestly(self, monkeypatch):
        session = _install(monkeypatch, {})
        profile = SessionProfile(last_results=[{"hotel_id": 1, "name": "Solo Hotel"}])
        result = _run(inline_tools.compare_hotels("compare hotels", profile))
        assert result == {"ok": False, "error": "need at least 2 hotels to compare"}
        assert session.calls == []


class TestOrdinalSelection:
    """A bare list position ("2") replying to the numbered shortlist resolves
    from that shortlist directly — never MCP find_hotel_by_name (whose exact
    cityName filter mis-handles greater-metro inventory)."""

    SHORTLIST3 = [
        {"hotel_id": 111, "name": "Cadillac Hotel & Beach Club"},
        {"hotel_id": 222, "name": "Wyndham Garden Miami International Airport"},
        {"hotel_id": 333, "name": "Regency Miami Airport by Sonesta"},
    ]

    def test_details_by_ordinal_uses_shortlist_id_no_name_lookup(self, monkeypatch):
        session = _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
        profile = SessionProfile(last_results=self.SHORTLIST3)
        result = _run(inline_tools.get_hotel_details("2", profile))
        assert result["ok"] is True
        # resolved the 2nd shortlist hotel by position — and ONLY get_hotel_details ran.
        assert [c[0] for c in session.calls] == ["get_hotel_details"]
        assert session.calls[0][1]["hotelId"] == 222

    def test_booking_by_ordinal_quotes_the_right_shortlist_hotel(self, monkeypatch):
        _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
                "generate_booking_link": lambda args: FakeResult(
                    {"confirmationRequired": True, "hotel": {}, "offer": {}}
                ),
            },
        )
        profile = SessionProfile(last_results=self.SHORTLIST3)
        result = _run(inline_tools.generate_booking_link("1", profile, user_confirmed=False))
        assert result["ok"] is True and result["confirmed"] is False
        # picked position #1 from the shortlist, no find_hotel_by_name round-trip.
        assert profile.pending_booking["hotel_id"] == 111

    def test_out_of_range_ordinal_falls_through_to_name_matching(self, monkeypatch):
        # "9" is not a valid position (3 hotels) → not an ordinal hit; with no
        # name match and no shortlist name, resolution degrades honestly.
        session = _install(monkeypatch, {"find_hotel_by_name": FakeResult(is_error=True)})
        profile = SessionProfile(last_results=self.SHORTLIST3)
        result = _run(inline_tools.generate_booking_link("9", profile, user_confirmed=False))
        assert result["ok"] is False
        # it did try the name path (not silently swallowed as a bogus ordinal).
        assert any(c[0] == "find_hotel_by_name" for c in session.calls)


class TestGenerateBookingLinkR9:
    """Guard #12: confirmed is derived from server-side state, never from the
    caller's own assertion — the two legitimate paths, plus the bypass
    attempt that must never produce a link."""

    def test_first_request_always_quotes_confirmed_false(self, monkeypatch):
        session = _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
                "generate_booking_link": lambda args: FakeResult(
                    {
                        "confirmationRequired": True,
                        "hotel": {"name": "Villa Paris Orly"},
                        "offer": {},
                    }
                ),
            },
        )
        profile = SessionProfile(last_results=SHORTLIST)
        # Even asserting user_confirmed=True on a hotel never quoted before
        # must NOT reach MCP with confirmed=true (the bypass attempt).
        result = _run(inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=True))
        assert result["ok"] is True
        assert result["confirmed"] is False
        assert "url" not in result
        link_call = next(c for c in session.calls if c[0] == "generate_booking_link")
        assert link_call[1]["confirmed"] is False
        # The offer identity is now pending, keyed on the resolved hotel id.
        assert profile.pending_booking is not None
        assert profile.pending_booking["hotel_id"] == 22293
        assert profile.pending_booking["rate_plan_uuid"] == "019d2b0c-4f34-7110-882d-d5709ca05b6f"
        # S-G6: HOTEL_DETAILS_RESPONSE's offer has no startMinute/endMinute ->
        # defaults to :00, but as a real "HH:MM" string now, not a bare int.
        assert result["start_time"] == "17:00"
        assert result["end_time"] == "23:00"

    def test_quote_captures_real_offer_minutes_not_forced_to_zero(self, monkeypatch):
        details_with_minutes = {
            **HOTEL_DETAILS_RESPONSE,
            "offers": [{**HOTEL_DETAILS_RESPONSE["offers"][0], "startMinute": 30, "endMinute": 15}],
        }
        _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(details_with_minutes),
                "generate_booking_link": lambda args: FakeResult(
                    {"confirmationRequired": True, "hotel": {"name": "Villa Paris Orly"}, "offer": {}}
                ),
            },
        )
        profile = SessionProfile(last_results=SHORTLIST)
        result = _run(
            inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=False)
        )
        assert result["start_time"] == "17:30"
        assert result["end_time"] == "23:15"

    def test_confirmation_turn_with_matching_pending_offer_returns_the_link(self, monkeypatch):
        session = _install(
            monkeypatch,
            {
                "generate_booking_link": lambda args: FakeResult(
                    {"link": {"url": "https://www.dayuse.fr/tunnel/booking?offerId=abc"}}
                )
            },
        )
        profile = SessionProfile(
            last_results=SHORTLIST,
            pending_booking={
                "hotel_id": 22293,
                "hotel_name": "Villa Paris Orly",
                "date": "2026-07-20",
                "rate_plan_uuid": "019d2b0c-4f34-7110-882d-d5709ca05b6f",
                "rate_plan_id": None,
            },
        )
        result = _run(inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=True))
        assert result["ok"] is True
        assert result["confirmed"] is True
        assert result["url"] == "https://www.dayuse.fr/tunnel/booking?offerId=abc"
        assert profile.pending_booking is None
        link_call = next(c for c in session.calls if c[0] == "generate_booking_link")
        assert link_call[1]["confirmed"] is True
        # get_hotel_details must NOT be re-queried: the pending offer identity
        # (stored at the quote step) is reused verbatim, no drift.
        assert "get_hotel_details" not in {c[0] for c in session.calls}

    def test_bypass_attempt_without_any_prior_pending_offer_never_confirms(self, monkeypatch):
        session = _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
                "generate_booking_link": lambda args: FakeResult(
                    {"confirmationRequired": True, "hotel": {}, "offer": {}}
                ),
            },
        )
        profile = SessionProfile(last_results=SHORTLIST)  # no pending_booking at all
        result = _run(inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=True))
        assert result["confirmed"] is False
        assert "url" not in result
        link_call = next(c for c in session.calls if c[0] == "generate_booking_link")
        assert link_call[1]["confirmed"] is False

    def test_pending_offer_for_a_different_hotel_does_not_confirm_this_one(self, monkeypatch):
        session = _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
                "generate_booking_link": lambda args: FakeResult(
                    {"confirmationRequired": True, "hotel": {}, "offer": {}}
                ),
            },
        )
        profile = SessionProfile(
            last_results=SHORTLIST,
            pending_booking={
                "hotel_id": 999999,  # a DIFFERENT hotel's pending offer
                "hotel_name": "Some Other Hotel",
                "date": "2026-07-20",
                "rate_plan_uuid": "other-uuid",
                "rate_plan_id": None,
            },
        )
        result = _run(inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=True))
        assert result["confirmed"] is False
        link_call = next(c for c in session.calls if c[0] == "generate_booking_link")
        assert link_call[1]["confirmed"] is False
        # The stale pending offer for the other hotel is replaced by this
        # turn's own fresh quote, not silently kept.
        assert profile.pending_booking["hotel_id"] == 22293

    def test_hotel_not_found_degrades_honestly(self, monkeypatch):
        _install(monkeypatch, {"find_hotel_by_name": FakeResult(is_error=True)})
        result = _run(
            inline_tools.generate_booking_link("nonexistent", SessionProfile(), user_confirmed=False)
        )
        assert result == {"ok": False, "error": "hotel not found"}

    def test_bare_yes_confirmation_needs_no_hotel_name_at_all(self, monkeypatch):
        # REGRESSION (found live against MCP_B2C during S07): a real
        # confirmation turn's message is a BARE "yes" — it names no hotel at
        # all, and the shortlist may be empty (last_results not carried over
        # from the quote step). The pending offer's own stored identity must
        # be reused directly, never re-resolved from "yes".
        session = _install(
            monkeypatch,
            {
                "generate_booking_link": lambda args: FakeResult(
                    {"link": {"url": "https://www.dayuse.fr/tunnel/booking?offerId=abc"}}
                )
            },
        )
        profile = SessionProfile(
            last_results=None,
            pending_booking={
                "hotel_id": 22293,
                "hotel_name": "Villa Paris Orly",
                "date": "2026-07-20",
                "rate_plan_uuid": "019d2b0c-4f34-7110-882d-d5709ca05b6f",
                "rate_plan_id": None,
            },
        )
        result = _run(inline_tools.generate_booking_link("yes", profile, user_confirmed=True))
        assert result["ok"] is True
        assert result["confirmed"] is True
        assert result["url"] == "https://www.dayuse.fr/tunnel/booking?offerId=abc"
        assert profile.pending_booking is None
        assert {c[0] for c in session.calls} == {"generate_booking_link"}
        link_call = next(c for c in session.calls if c[0] == "generate_booking_link")
        assert link_call[1]["hotelId"] == 22293
        assert link_call[1]["confirmed"] is True

    def test_confirmation_mcp_failure_keeps_the_offer_quotable(self, monkeypatch):
        _install(monkeypatch, {"generate_booking_link": FakeResult(is_error=True)})
        pending = {
            "hotel_id": 22293,
            "hotel_name": "Villa Paris Orly",
            "date": "2026-07-20",
            "rate_plan_uuid": "abc",
            "rate_plan_id": None,
        }
        profile = SessionProfile(pending_booking=dict(pending))
        result = _run(inline_tools.generate_booking_link("yes", profile, user_confirmed=True))
        assert result["ok"] is False
        # A transient MCP failure on the confirm step must not silently drop
        # the user's already-quoted offer — it stays confirmable next turn.
        assert profile.pending_booking == pending

    def test_no_bookable_offer_degrades_honestly(self, monkeypatch):
        _install(
            monkeypatch,
            {"get_hotel_details": FakeResult({"hotel": {"hotelId": 22293}, "offers": []})},
        )
        profile = SessionProfile(last_results=SHORTLIST)
        result = _run(
            inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=False)
        )
        assert result == {"ok": False, "error": "no bookable offer for this hotel"}
