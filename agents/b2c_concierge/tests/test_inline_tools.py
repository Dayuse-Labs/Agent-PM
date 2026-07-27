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

    def test_keeps_the_numeric_price_and_review_count_on_the_card(self, monkeypatch):
        # S-CX3a: the details card mirrors the search leaf's — `price_eur_cents`
        # next to the display string, `rating_count` from MCP's `totalReview`.
        response = {
            **HOTEL_DETAILS_RESPONSE,
            "hotel": {**HOTEL_DETAILS_RESPONSE["hotel"], "totalReview": 412},
        }
        _install(monkeypatch, {"get_hotel_details": FakeResult(response)})
        profile = SessionProfile(last_results=SHORTLIST)
        hotel = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))["hotel"]
        assert hotel["price"] == "€54.00"
        assert hotel["price_eur_cents"] == 5400
        assert hotel["rating_count"] == 412

    def test_rating_count_is_none_when_mcp_omits_total_review(self, monkeypatch):
        _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
        profile = SessionProfile(last_results=SHORTLIST)
        result = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert result["hotel"]["rating_count"] is None

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

    def test_builds_page_url_from_es_slug_never_from_the_name(self, monkeypatch):
        # S-G12: url only when the server sends its ES slug — the display
        # name ("Villa Paris Orly") must never be slugified into one.
        _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
        profile = SessionProfile(last_results=SHORTLIST)
        result = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert "url" not in result["hotel"]  # fixture has no slug

        response = {
            **HOTEL_DETAILS_RESPONSE,
            "hotel": {**HOTEL_DETAILS_RESPONSE["hotel"], "slug": "villa-paris-orly-rungis"},
        }
        _install(monkeypatch, {"get_hotel_details": FakeResult(response)})
        result = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert result["hotel"]["url"] == "https://www.dayuse.fr/hotels/france/villa-paris-orly-rungis"

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


class TestQuotesTheOfferTheUserSaw:
    """S-CX5 — prod session 2026-07-27: the card on screen said €87,
    11:00-19:00, TOMORROW; the link booked €90, 17:00-23:00, TODAY. The quote
    re-fetched the hotel with no date and took `offers[0]` instead of the offer
    the card was priced on."""

    # The shortlist as record_search_shortlist now stores it, from that session.
    SHOWN = [
        {
            "hotel_id": 22293,
            "name": "Hôtel Mercure Paris La Défense",
            "offer_id": "1836debf-aaee-11ee-99ec-0272db9e0c27",
            "offer_date": "2026-07-28",
            "price": "€87.00",
            "price_eur_cents": 8700,
            "start_time": "11:00",
            "end_time": "19:00",
        }
    ]

    def test_regression_the_quote_is_the_card_not_todays_first_offer(self, monkeypatch):
        session = _install(
            monkeypatch,
            {
                # If this were reached, it would answer with the WRONG offer —
                # today's 17:00-23:00 at €90, exactly the prod defect.
                "get_hotel_details": FakeResult(
                    {
                        "hotel": {"hotelId": 22293, "name": "Hôtel Mercure Paris La Défense"},
                        "offers": [
                            {
                                "ratePlanUuid": "todays-wrong-offer",
                                "availabilityDate": "2026-07-27",
                                "startHour": 17,
                                "endHour": 23,
                                "priceEuro": 9000,
                            }
                        ],
                    }
                ),
                "generate_booking_link": lambda args: FakeResult(
                    {"confirmationRequired": True, "hotel": {}, "offer": {}}
                ),
            },
        )
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = _run(
            inline_tools.generate_booking_link(
                "Hôtel Mercure Paris La Défense", profile, user_confirmed=False
            )
        )
        assert result["date"] == "2026-07-28"
        assert (result["start_time"], result["end_time"]) == ("11:00", "19:00")
        assert result["price"] == "€87.00"
        link_call = next(c for c in session.calls if c[0] == "generate_booking_link")
        assert link_call[1]["ratePlanUuid"] == "1836debf-aaee-11ee-99ec-0272db9e0c27"
        assert link_call[1]["date"] == "2026-07-28"
        # And the offer the user saw needs no second lookup at all.
        assert "get_hotel_details" not in {c[0] for c in session.calls}
        assert profile.pending_booking["date"] == "2026-07-28"
        assert profile.pending_booking["rate_plan_uuid"] == "1836debf-aaee-11ee-99ec-0272db9e0c27"

    def test_hotel_off_the_shortlist_looks_up_the_SESSION_date(self, monkeypatch):
        """A hotel named but never shown has no stored offer — the fallback
        lookup must still be scoped to the date the user asked for, not
        "today onward"."""
        session = _install(
            monkeypatch,
            {
                "find_hotel_by_name": FakeResult({"hotel": {"hotelId": 99001, "name": "Moxy"}}),
                "get_hotel_details": FakeResult(
                    {
                        "hotel": {"hotelId": 99001, "name": "Moxy"},
                        "offers": [
                            {
                                "ratePlanUuid": "moxy-offer",
                                "availabilityDate": "2026-07-28",
                                "startHour": 10,
                                "endHour": 18,
                                "priceEuro": 7500,
                            }
                        ],
                    }
                ),
                "generate_booking_link": lambda args: FakeResult(
                    {"confirmationRequired": True, "hotel": {}, "offer": {}}
                ),
            },
        )
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = _run(inline_tools.generate_booking_link("Moxy", profile, user_confirmed=False))
        assert result["ok"] is True
        details_call = next(c for c in session.calls if c[0] == "get_hotel_details")
        assert details_call[1] == {"hotelId": 99001, "date": "2026-07-28"}

    def test_fallback_lookup_takes_the_cheapest_offer_not_the_first(self, monkeypatch):
        """Same rule as the card (`response_bridge._best_offer`) — otherwise
        the fallback path re-introduces the very mismatch this class covers."""
        _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(
                    {
                        "hotel": {"hotelId": 22293, "name": "Villa Paris Orly"},
                        "offers": [
                            {
                                "ratePlanUuid": "pricey",
                                "availabilityDate": "2026-07-28",
                                "startHour": 17,
                                "endHour": 23,
                                "priceEuro": 9000,
                            },
                            {
                                "ratePlanUuid": "cheapest",
                                "availabilityDate": "2026-07-28",
                                "startHour": 11,
                                "endHour": 19,
                                "priceEuro": 8700,
                            },
                        ],
                    }
                ),
                "generate_booking_link": lambda args: FakeResult(
                    {"confirmationRequired": True, "hotel": {}, "offer": {}}
                ),
            },
        )
        # SHORTLIST (module-level) has no stored offer -> the fallback path.
        profile = SessionProfile(last_results=SHORTLIST, date="2026-07-28")
        result = _run(
            inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=False)
        )
        assert result["price"] == "€87.00"
        assert profile.pending_booking["rate_plan_uuid"] == "cheapest"

    def test_no_session_date_quotes_the_soonest_day_not_the_cheapest_week(self, monkeypatch):
        """Probed live: an unscoped get_hotel_details returns ~90 offers over a
        month. Picking the global minimum would quote a cheaper day weeks out
        that the user never asked for — the day is pinned to the soonest
        bookable one first, and only then is the cheapest offer chosen ON it."""
        _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(
                    {
                        "hotel": {"hotelId": 22293, "name": "Villa Paris Orly"},
                        "offers": [
                            {
                                "ratePlanUuid": "soon-pricey",
                                "availabilityDate": "2026-07-28",
                                "startHour": 17,
                                "endHour": 23,
                                "priceEuro": 9000,
                            },
                            {
                                "ratePlanUuid": "soon-cheaper",
                                "availabilityDate": "2026-07-28",
                                "startHour": 10,
                                "endHour": 17,
                                "priceEuro": 8700,
                            },
                            {
                                "ratePlanUuid": "three-weeks-out-bargain",
                                "availabilityDate": "2026-08-20",
                                "startHour": 10,
                                "endHour": 17,
                                "priceEuro": 3900,
                            },
                        ],
                    }
                ),
                "generate_booking_link": lambda args: FakeResult(
                    {"confirmationRequired": True, "hotel": {}, "offer": {}}
                ),
            },
        )
        profile = SessionProfile(last_results=SHORTLIST)  # no date at all
        result = _run(
            inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=False)
        )
        assert result["date"] == "2026-07-28"
        assert result["price"] == "€87.00"
        assert profile.pending_booking["rate_plan_uuid"] == "soon-cheaper"

    def test_without_a_session_date_the_lookup_stays_unscoped(self, monkeypatch):
        """No date in the profile = nothing to scope to. The call must stay as
        it was rather than invent one."""
        session = _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
                "generate_booking_link": lambda args: FakeResult(
                    {"confirmationRequired": True, "hotel": {}, "offer": {}}
                ),
            },
        )
        profile = SessionProfile(last_results=SHORTLIST)  # date is None
        _run(inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=False))
        details_call = next(c for c in session.calls if c[0] == "get_hotel_details")
        assert details_call[1] == {"hotelId": 22293}


class TestExplicitPickAuthorizesTheLink:
    """S-CX5 / R9 redefined (decided with Fabien 2026-07-27): what authorizes a
    booking link is still an explicit, code-owned flag in the turn state — but
    a resolved user SELECTION now satisfies it as well as a prior quote + yes.
    The reply carries a card stating hotel/day/slot/price next to the button,
    so the user sees what they are about to book. Nothing is booked either way:
    the link opens the tunnel, payment happens there."""

    SHOWN = [
        {
            "hotel_id": 22293,
            "name": "Villa Paris Orly",
            "offer_id": "offer-villa",
            "offer_date": "2026-07-28",
            "price": "€54.00",
            "price_eur_cents": 5400,
            "start_time": "10:00",
            "end_time": "17:00",
            "image_urls": ["https://static.dayuse.com/villa.jpg"],
            "url": "https://www.dayuse.fr/hotels/france/villa-paris-orly",
        }
    ]

    def _mcp(self, monkeypatch):
        return _install(
            monkeypatch,
            {
                "generate_booking_link": lambda args: FakeResult(
                    {"link": {"url": "https://www.dayuse.fr/tunnel/booking?offerId=offer-villa"}}
                    if args.get("confirmed")
                    else {"confirmationRequired": True, "hotel": {}, "offer": {}}
                )
            },
        )

    def test_a_picked_hotel_returns_the_link_in_one_turn(self, monkeypatch):
        session = self._mcp(monkeypatch)
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = _run(
            inline_tools.generate_booking_link(
                "le moins cher", profile, user_confirmed=False, picked_hotel_id=22293
            )
        )
        assert result["confirmed"] is True
        assert result["url"].endswith("offerId=offer-villa")
        link_call = next(c for c in session.calls if c[0] == "generate_booking_link")
        assert link_call[1]["confirmed"] is True
        # Everything the card needs, all from the offer the link was built on.
        assert result["date"] == "2026-07-28"
        assert (result["start_time"], result["end_time"]) == ("10:00", "17:00")
        assert result["price"] == "€54.00"
        assert result["image_url"] == "https://static.dayuse.com/villa.jpg"
        # Nothing left dangling for a later "yes" to re-confirm.
        assert profile.pending_booking is None

    def test_without_a_pick_the_original_two_step_is_untouched(self, monkeypatch):
        """The typed path with no resolved selection still quotes first."""
        session = self._mcp(monkeypatch)
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = _run(
            inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=False)
        )
        assert result["confirmed"] is False
        assert "url" not in result
        assert next(c for c in session.calls if c[0] == "generate_booking_link")[1]["confirmed"] is False
        assert profile.pending_booking["hotel_id"] == 22293

    def test_asserting_confirmation_without_a_pick_or_a_pending_offer_still_cannot_link(
        self, monkeypatch
    ):
        """The bypass attempt R9 exists for: a caller claiming confirmation on a
        session that never quoted anything, and naming no picked hotel."""
        session = self._mcp(monkeypatch)
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = _run(
            inline_tools.generate_booking_link("Villa Paris Orly", profile, user_confirmed=True)
        )
        assert result["confirmed"] is False
        assert next(c for c in session.calls if c[0] == "generate_booking_link")[1]["confirmed"] is False

    def test_a_pick_naming_another_hotel_never_confirms_the_pending_one(self, monkeypatch):
        """Defense in depth, mirroring the named-hotel mismatch rule."""
        self._mcp(monkeypatch)
        profile = SessionProfile(
            last_results=self.SHOWN,
            date="2026-07-28",
            pending_booking={
                "hotel_id": 999999,
                "hotel_name": "Another Hotel",
                "date": "2026-07-28",
                "rate_plan_uuid": "stale",
                "rate_plan_id": None,
            },
        )
        result = _run(
            inline_tools.generate_booking_link(
                "yes", profile, user_confirmed=True, picked_hotel_id=22293
            )
        )
        # It resolved the PICKED hotel, never the stale pending one.
        assert result["url"].endswith("offerId=offer-villa")
        assert result["hotel_name"] == "Villa Paris Orly"
