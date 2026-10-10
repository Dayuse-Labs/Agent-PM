"""Inline MCP tools (S07): get_hotel_details/compare_hotels/generate_booking_link
wired to real MCP_B2C calls — tested offline against a fake ClientSession (no
network, no API key, per pytest.ini). Field shapes below mirror what MCP_B2C
staging actually returns (verified live during this session): `hotelId`,
amenities as `[{"id", "name"}, ...]`, `priceEuro` in EUR cents, and
`generate_booking_link`'s `{"link": {"url": ...}}` / no-link summary shapes.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

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


_MCP_CONTRACT = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts" / "mcp_b2c_tools.json").read_text()
)


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
        self.metas: list[dict | None] = []

    async def call_tool(self, name, arguments, *, meta=None):
        # `meta` = OBS4's W3C trace context in the MCP `_meta` field (keyword-only,
        # mcp==1.28.1) — None whenever tracing is off, which is the whole suite.
        # mcp-dayuse#8: every argument set the concierge builds is checked
        # against the schema the server publishes, in every test of this file.
        jsonschema.validate(dict(arguments), _MCP_CONTRACT["tools"][name])
        self.calls.append((name, dict(arguments)))
        self.metas.append(meta)
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

    def test_details_card_follows_the_booking_fees_setting(self, monkeypatch):
        # QA n°6: same rule as the search leaf's cards (b2c_common.display_price_euro).
        offer = {**HOTEL_DETAILS_RESPONSE["offers"][0], "priceEuroWithBookingFees": 5900}
        profile = SessionProfile(last_results=SHORTLIST)
        _install(monkeypatch, {"get_hotel_details": FakeResult({**HOTEL_DETAILS_RESPONSE, "offers": [offer]})})
        hotel = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))["hotel"]
        assert hotel["price"] == "€59.00" and hotel["price_eur_cents"] == 5900

        flagged = {**HOTEL_DETAILS_RESPONSE["hotel"], "showPricesWithoutBookingFees": True}
        _install(monkeypatch, {"get_hotel_details": FakeResult({"hotel": flagged, "offers": [offer]})})
        hotel = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))["hotel"]
        assert hotel["price"] == "€54.00" and hotel["price_eur_cents"] == 5400

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

    def test_page_url_opens_on_the_users_date(self, monkeypatch):
        # QA 2026-09-08 n°4: `profile.date` only holds a user-given date.
        response = {
            **HOTEL_DETAILS_RESPONSE,
            "hotel": {**HOTEL_DETAILS_RESPONSE["hotel"], "slug": "villa-paris-orly-rungis"},
        }
        _install(monkeypatch, {"get_hotel_details": FakeResult(response)})
        profile = SessionProfile(last_results=SHORTLIST, date="2026-09-27")
        result = _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert result["hotel"]["url"] == (
            "https://www.dayuse.fr/hotels/france/villa-paris-orly-rungis?checkinDate=2026-09-27"
        )

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
        assert result == {
            "ok": False, "error": "hotel not found", "guards_fired": ["named_hotel_lookup"],
        }

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
        assert result == {
            "ok": False, "error": "hotel not found", "guards_fired": ["named_hotel_lookup"],
        }

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
        assert result == {
            "ok": False, "error": "no bookable offer for this hotel",
            "guards_fired": ["named_hotel_lookup"],
        }


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


class TestRatePlanSelector:
    """S-CX8 (decided with Fabien 2026-07-28, option A of the proposal
    artefact): on the turn a hotel is PICKED, the card offers every formula of
    that day — each with its own tunnel link — instead of only the cheapest.

    The invariant it must not break is S-CX5's: what the user saw is what they
    book. Here that means the DEFAULT selection is the offer the shortlist card
    was priced on, never "whatever is cheapest today".
    """

    # €87 is what the carousel showed — deliberately NOT the cheapest formula
    # of the day, so a selector that defaulted to the cheapest would be caught.
    SHOWN = [
        {
            "hotel_id": 22293,
            "name": "Villa Paris Orly",
            "offer_id": "rp-spa",
            "offer_date": "2026-07-28",
            "price": "€87.00",
            "price_eur_cents": 8700,
            "start_time": "11:00",
            "end_time": "19:00",
            "image_urls": ["https://static.dayuse.com/villa.jpg"],
            "url": "https://www.dayuse.fr/hotels/france/villa-paris-orly",
        }
    ]

    OFFERS = [
        {
            "ratePlanUuid": "rp-spa",
            "ratePlanId": 2,
            "availabilityDate": "2026-07-28",
            "startHour": 11,
            "startMinute": 0,
            "endHour": 19,
            "endMinute": 0,
            "priceEuro": 8700,
            "offerType": "dayuse.day",
            "bedding": "double_king",
            "capacity": 2,
            "ratePlanName": "Day Room + Spa",
            "roomType": "Chambre Deluxe",
            "originalPriceEuro": 21900,
            "includedAmenities": ["Outdoor pool", "Free parking"],
        },
        {
            "ratePlanUuid": "rp-day",
            "ratePlanId": 1,
            "availabilityDate": "2026-07-28",
            "startHour": 10,
            "startMinute": 30,
            "endHour": 16,
            "endMinute": 0,
            "priceEuro": 5400,
            "offerType": "dayuse.early",
            "bedding": "double",
            "capacity": 2,
            "ratePlanName": "Day Room",
            "roomType": "Chambre Classique",
            "includedAmenities": ["Outdoor pool", "Free parking"],
        },
        {
            "ratePlanUuid": "rp-suite",
            "ratePlanId": 3,
            "availabilityDate": "2026-07-28",
            "startHour": 11,
            "endHour": 19,
            "priceEuro": 18900,
            "ratePlanName": "Suite Évasion",
        },
        # Another day entirely: get_hotel_details returns every upcoming offer,
        # and mixing next week's formulas into today's choices is the bug this
        # guards (same live-probed reason as _best_offer's one-day rule).
        {
            "ratePlanUuid": "rp-nextweek",
            "ratePlanId": 4,
            "availabilityDate": "2026-08-04",
            "startHour": 10,
            "endHour": 16,
            "priceEuro": 3900,
            "ratePlanName": "Promo Août",
        },
    ]

    def _mcp(self, monkeypatch, offers=None, link=None):
        return _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(
                    {"hotel": {"hotelId": 22293}, "offers": self.OFFERS if offers is None else offers}
                ),
                "generate_booking_link": link
                or (
                    lambda args: FakeResult(
                        {"link": {"url": f"https://www.dayuse.fr/tunnel?offerId={args['ratePlanUuid']}"}}
                    )
                ),
            },
        )

    def _pick(self, profile):
        return _run(
            inline_tools.generate_booking_link(
                "le moins cher", profile, user_confirmed=False, picked_hotel_id=22293
            )
        )

    def test_the_day_s_formulas_come_back_cheapest_first_each_with_its_link(self, monkeypatch):
        self._mcp(monkeypatch)
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = self._pick(profile)

        assert result["ok"] is True and result["confirmed"] is True
        plans = result["rate_plans"]
        assert [p["offer_id"] for p in plans] == ["rp-day", "rp-spa", "rp-suite"]
        assert [p["price"] for p in plans] == ["€54.00", "€87.00", "€189.00"]
        # Each row books ITS OWN formula — the whole point of the selector.
        assert [p["url"] for p in plans] == [
            "https://www.dayuse.fr/tunnel?offerId=rp-day",
            "https://www.dayuse.fr/tunnel?offerId=rp-spa",
            "https://www.dayuse.fr/tunnel?offerId=rp-suite",
        ]
        assert all(p["date"] == "2026-07-28" for p in plans)
        # Nothing left dangling for a later "yes" to re-confirm.
        assert profile.pending_booking is None

    def test_the_default_selection_is_the_offer_the_carousel_showed(self, monkeypatch):
        """NOT the cheapest: a user who clicked a €87 card must not land on a
        €54 selection — the better deal still reads as a bait-and-switch."""
        self._mcp(monkeypatch)
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = self._pick(profile)

        selected = [p for p in result["rate_plans"] if p["selected"]]
        assert [p["offer_id"] for p in selected] == ["rp-spa"]
        # And the card's own top-level facts describe that same formula, so a
        # widget ignoring `rate_plans` still shows what the link books.
        assert result["price"] == "€87.00"
        assert (result["start_time"], result["end_time"]) == ("11:00", "19:00")
        assert result["url"].endswith("offerId=rp-spa")

    def test_without_a_shown_offer_the_cheapest_is_selected(self, monkeypatch):
        """A hotel picked off a card that carried no offer identity has nothing
        to stay faithful to, so the cheapest formula is the honest default."""
        self._mcp(monkeypatch)
        profile = SessionProfile(
            last_results=[{"hotel_id": 22293, "name": "Villa Paris Orly"}], date="2026-07-28"
        )
        result = self._pick(profile)

        selected = next(p for p in result["rate_plans"] if p["selected"])
        assert selected["offer_id"] == "rp-day"
        assert result["price"] == "€54.00"

    def test_another_day_s_formulas_are_never_offered(self, monkeypatch):
        self._mcp(monkeypatch)
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = self._pick(profile)
        assert "rp-nextweek" not in {p["offer_id"] for p in result["rate_plans"]}

    def test_the_descriptive_fields_ride_through_when_mcp_sends_them(self, monkeypatch):
        """`ratePlanName`/`roomType`/`addonsIncluded` are REQUESTED from MCP_B2C
        and not exposed yet (reports/PROMPT-MCP-B2C-RATEPLANS.md) — this pins
        the mapping so the day they appear, no second implementation is needed."""
        self._mcp(monkeypatch)
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        plans = {p["offer_id"]: p for p in self._pick(profile)["rate_plans"]}

        assert plans["rp-spa"]["name"] == "Day Room + Spa"
        assert plans["rp-spa"]["room_type"] == "Chambre Deluxe"
        # The fields that actually differentiate formulas today (live-probed):
        # offerType is a closed enum, bedding/capacity stand in for the NULL
        # room_type column. Passed through RAW — the widget owns the wording.
        assert plans["rp-spa"]["offer_type"] == "dayuse.day"
        assert plans["rp-day"]["offer_type"] == "dayuse.early"
        assert (plans["rp-spa"]["bedding"], plans["rp-spa"]["capacity"]) == ("double_king", 2)
        # rp-suite carries none of them -> keys absent, never guessed.
        assert "offer_type" not in plans["rp-suite"]
        assert "bedding" not in plans["rp-suite"]
        # Half-hour starts survive (S-G6): 10:30, not 10:00.
        assert plans["rp-day"]["start_time"] == "10:30"
        # Absent stays ABSENT — never a "Chambre standard" placeholder.
        assert "room_type" not in plans["rp-suite"]
        # No per-plan "included services": MCP's includedAmenities is HOTEL-level
        # (identical on every formula across 227 probed days, different on 0), so
        # it must never masquerade as something that tells formulas apart.
        assert all("addons" not in p for p in plans.values())

    def test_the_night_rate_discount_is_computed_only_when_it_is_real(self, monkeypatch):
        """A discount is a claim, so it is computed here where a test covers it
        — and both keys stay absent unless the night rate really is higher."""
        self._mcp(monkeypatch)
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        plans = {p["offer_id"]: p for p in self._pick(profile)["rate_plans"]}

        assert plans["rp-spa"]["original_price"] == "€219.00"
        assert plans["rp-spa"]["discount_pct"] == 60  # (21900-8700)/21900
        # No originalPriceEuro at all -> no claim.
        assert "discount_pct" not in plans["rp-day"]

    def test_a_night_rate_below_the_day_rate_makes_no_badge(self, monkeypatch):
        self._mcp(
            monkeypatch,
            offers=[
                {**self.OFFERS[0], "originalPriceEuro": 8000},
                self.OFFERS[1],
            ],
        )
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        plans = {p["offer_id"]: p for p in self._pick(profile)["rate_plans"]}
        assert "discount_pct" not in plans["rp-spa"]
        assert "original_price" not in plans["rp-spa"]

    def test_a_formula_whose_link_fails_is_dropped_not_shown_unbookable(self, monkeypatch):
        self._mcp(
            monkeypatch,
            link=lambda args: (
                FakeResult(None, is_error=True)
                if args["ratePlanUuid"] == "rp-suite"
                else FakeResult({"link": {"url": f"https://x/?o={args['ratePlanUuid']}"}})
            ),
        )
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = self._pick(profile)
        assert [p["offer_id"] for p in result["rate_plans"]] == ["rp-day", "rp-spa"]

    def test_when_the_selected_formula_has_no_link_the_whole_card_degrades(self, monkeypatch):
        """Rather than silently re-pointing the card at another formula: the
        single-offer path is what has always served this case."""
        session = self._mcp(
            monkeypatch,
            link=lambda args: (
                FakeResult(None, is_error=True)
                if args["ratePlanUuid"] == "rp-spa" and args.get("confirmed")
                else FakeResult({"link": {"url": f"https://x/?o={args['ratePlanUuid']}"}})
            ),
        )
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = self._pick(profile)
        # Degraded to the pre-S-CX8 behaviour: no selector, and it still failed
        # honestly on the same offer rather than booking a different one.
        assert "rate_plans" not in result
        assert result["ok"] is False
        assert "rp-day" not in str(session.calls[-1])

    def test_a_single_formula_leaves_the_card_exactly_as_it_was(self, monkeypatch):
        """One formula is not a choice — no selector, no empty list, no key."""
        self._mcp(monkeypatch, offers=[self.OFFERS[0]])
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = self._pick(profile)
        assert result["ok"] is True and "rate_plans" not in result
        assert result["url"].endswith("offerId=rp-spa")
        assert result["price"] == "€87.00"

    def test_more_formulas_than_the_cap_keeps_the_cheapest_ones(self, monkeypatch):
        many = [
            {
                "ratePlanUuid": f"rp-{i}",
                "availabilityDate": "2026-07-28",
                "startHour": 10,
                "endHour": 16,
                "priceEuro": 1000 * (10 - i),  # rp-0 dearest, rp-9 cheapest
            }
            for i in range(10)
        ]
        self._mcp(monkeypatch, offers=many)
        profile = SessionProfile(last_results=[{"hotel_id": 22293, "name": "V"}], date="2026-07-28")
        plans = self._pick(profile)["rate_plans"]
        assert len(plans) == inline_tools._MAX_RATE_PLANS
        assert [p["offer_id"] for p in plans] == ["rp-9", "rp-8", "rp-7", "rp-6", "rp-5", "rp-4"]

    def test_an_offer_without_an_id_or_a_date_is_not_offerable(self, monkeypatch):
        """Both are exactly what generate_booking_link books."""
        self._mcp(
            monkeypatch,
            offers=[
                self.OFFERS[0],
                self.OFFERS[1],
                {"availabilityDate": "2026-07-28", "priceEuro": 100},  # no uuid
                {"ratePlanUuid": "rp-nodate", "priceEuro": 100},  # no date
            ],
        )
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        ids = {p["offer_id"] for p in self._pick(profile)["rate_plans"]}
        assert ids == {"rp-day", "rp-spa"}

    def test_a_details_failure_still_produces_the_single_offer_card(self, monkeypatch):
        """The degradation that matters most: MCP details down must not cost the
        user their booking link, only the choice of formula."""
        _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(None, is_error=True),
                "generate_booking_link": lambda args: FakeResult(
                    {"link": {"url": f"https://www.dayuse.fr/tunnel?offerId={args['ratePlanUuid']}"}}
                ),
            },
        )
        profile = SessionProfile(last_results=self.SHOWN, date="2026-07-28")
        result = self._pick(profile)
        assert result["ok"] is True and result["confirmed"] is True
        assert "rate_plans" not in result
        # The shortlist's own offer, reused verbatim (S-CX5 fallback intact).
        assert result["url"].endswith("offerId=rp-spa")
        assert result["price"] == "€87.00"

    def test_the_typed_confirmation_path_never_grows_a_selector(self, monkeypatch):
        """A "yes" confirms an offer already quoted; re-opening the choice there
        would re-litigate a decision the user already made."""
        session = self._mcp(monkeypatch)
        profile = SessionProfile(
            last_results=self.SHOWN,
            date="2026-07-28",
            pending_booking={
                "hotel_id": 22293,
                "hotel_name": "Villa Paris Orly",
                "date": "2026-07-28",
                "rate_plan_uuid": "rp-spa",
                "rate_plan_id": 2,
                "price": "€87.00",
            },
        )
        result = _run(
            inline_tools.generate_booking_link("oui je confirme", profile, user_confirmed=True)
        )
        assert result["ok"] is True and "rate_plans" not in result
        assert "get_hotel_details" not in {c[0] for c in session.calls}


class TestRatePlanDedupOnDisplaySignature:
    """UX4 (2026-08-27): dedupe on the
    DISPLAY signature the widget actually renders, not just `offer_id` — two
    MCP offers with different UUIDs but the same `(offer_type, name,
    start_time, end_time, price_eur_cents)` produce two rigorously identical
    rows, and there is no choice to offer when the user cannot tell two rows
    apart. Price stays IN the signature on purpose: a real price difference is
    a real choice and must never be collapsed away.

    Both named edge cases live in `messages.js`'s own `nameLeads` comment —
    Ibis La Ciotat (type+slot collide, names differ) and Mercure Lyon Saxe
    (name collides, slots differ) — and must survive here exactly as the
    frontend heuristic already treats them: kept, not collapsed.
    """

    def _mcp(self, monkeypatch, offers, link=None):
        return _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult({"hotel": {"hotelId": 22293}, "offers": offers}),
                "generate_booking_link": link
                or (
                    lambda args: FakeResult(
                        {"link": {"url": f"https://www.dayuse.fr/tunnel?offerId={args['ratePlanUuid']}"}}
                    )
                ),
            },
        )

    def _pick(self, profile):
        return _run(
            inline_tools.generate_booking_link(
                "le moins cher", profile, user_confirmed=False, picked_hotel_id=22293
            )
        )

    def _profile(self):
        return SessionProfile(
            last_results=[{"hotel_id": 22293, "name": "Villa Paris Orly"}], date="2026-07-28"
        )

    def test_two_different_uuids_with_an_identical_display_signature_collapse_to_one(
        self, monkeypatch
    ):
        session = self._mcp(
            monkeypatch,
            offers=[
                {
                    "ratePlanUuid": "rp-a",
                    "availabilityDate": "2026-07-28",
                    "startHour": 10,
                    "endHour": 15,
                    "priceEuro": 7000,
                    "offerType": "dayuse.day",
                    "ratePlanName": "Standard Room",
                },
                {
                    "ratePlanUuid": "rp-b",
                    "availabilityDate": "2026-07-28",
                    "startHour": 10,
                    "endHour": 15,
                    "priceEuro": 7000,
                    "offerType": "dayuse.day",
                    "ratePlanName": "Standard Room",
                },
            ],
        )
        result = self._pick(self._profile())
        # A single survivor collapses back to the plain, selector-less card —
        # `renderRatePlans`' own NO_PLANS threshold (`plans.length < 2`).
        # Nothing to change on the widget side.
        assert "rate_plans" not in result
        assert result["url"].endswith("offerId=rp-a")  # the first one encountered, kept
        # Deduped BEFORE the link round-trip: rp-b never costs an MCP call —
        # the reason this lives in the backend (MCP 429s on chained calls).
        link_calls = [c[1]["ratePlanUuid"] for c in session.calls if c[0] == "generate_booking_link"]
        assert link_calls == ["rp-a"]

    def test_ibis_la_ciotat_same_type_and_slot_different_names_keeps_all_three(self, monkeypatch):
        """Real edge case: 3 formulas, all `dayuse.day`, all 10:00-15:00,
        differing only by room (sea view / balcony / standard). The signature
        must NOT collapse on type+slot alone — losing real inventory."""
        self._mcp(
            monkeypatch,
            offers=[
                {
                    "ratePlanUuid": f"rp-{i}",
                    "availabilityDate": "2026-07-28",
                    "startHour": 10,
                    "endHour": 15,
                    "priceEuro": 7000,
                    "offerType": "dayuse.day",
                    "ratePlanName": name,
                }
                for i, name in enumerate(
                    ["Chambre Vue Mer", "Chambre avec Balcon", "Chambre Standard"]
                )
            ],
        )
        result = self._pick(self._profile())
        assert {p["offer_id"] for p in result["rate_plans"]} == {"rp-0", "rp-1", "rp-2"}

    def test_mercure_lyon_saxe_same_name_different_slots_keeps_all_three(self, monkeypatch):
        """Real edge case: 3 formulas all named "Standard King Room",
        differing only by timeslot. The signature must NOT collapse on the
        shared name alone."""
        self._mcp(
            monkeypatch,
            offers=[
                {
                    "ratePlanUuid": f"rp-{i}",
                    "availabilityDate": "2026-07-28",
                    "startHour": start,
                    "endHour": end,
                    "priceEuro": 7000,
                    "offerType": "dayuse.day",
                    "ratePlanName": "Standard King Room",
                }
                for i, (start, end) in enumerate([(10, 15), (15, 20), (20, 23)])
            ],
        )
        result = self._pick(self._profile())
        assert {p["offer_id"] for p in result["rate_plans"]} == {"rp-0", "rp-1", "rp-2"}

    def test_a_real_price_difference_is_never_collapsed_away(self, monkeypatch):
        """Same type, name and slot but a different price IS a real choice —
        the price is displayed, the user sees the difference."""
        self._mcp(
            monkeypatch,
            offers=[
                {
                    "ratePlanUuid": "rp-cheap",
                    "availabilityDate": "2026-07-28",
                    "startHour": 10,
                    "endHour": 15,
                    "priceEuro": 7000,
                    "offerType": "dayuse.day",
                    "ratePlanName": "Standard Room",
                },
                {
                    "ratePlanUuid": "rp-costly",
                    "availabilityDate": "2026-07-28",
                    "startHour": 10,
                    "endHour": 15,
                    "priceEuro": 8000,
                    "offerType": "dayuse.day",
                    "ratePlanName": "Standard Room",
                },
            ],
        )
        result = self._pick(self._profile())
        assert {p["offer_id"] for p in result["rate_plans"]} == {"rp-cheap", "rp-costly"}

    def test_priceless_plans_are_not_wrongly_collapsed_on_their_shared_none_price(
        self, monkeypatch
    ):
        """Two formulas with no `priceEuro` both carry `price_eur_cents=None`
        — still bookable, just not comparable. That shared None must not be
        enough to collapse them when they genuinely differ elsewhere: the
        other signature members must suffice on their own."""
        self._mcp(
            monkeypatch,
            offers=[
                {
                    "ratePlanUuid": "rp-noprice-a",
                    "availabilityDate": "2026-07-28",
                    "startHour": 10,
                    "endHour": 15,
                    "offerType": "dayuse.day",
                    "ratePlanName": "Chambre Vue Mer",
                },
                {
                    "ratePlanUuid": "rp-noprice-b",
                    "availabilityDate": "2026-07-28",
                    "startHour": 10,
                    "endHour": 15,
                    "offerType": "dayuse.day",
                    "ratePlanName": "Chambre avec Balcon",
                },
            ],
        )
        result = self._pick(self._profile())
        assert {p["offer_id"] for p in result["rate_plans"]} == {"rp-noprice-a", "rp-noprice-b"}


class TestHotelAmenitiesAreCardLevel:
    """S-CX8 / MCP 2026-07-28: `includedAmenities` arrived with the deploy. It is
    NOT a per-formula inclusion — probed over 227 multi-formula days it was
    identical on every formula 128 times and different 0 times, with 4 distinct
    values ever seen. So it belongs to the CARD, stated once."""

    def test_the_day_s_amenities_are_deduped_onto_the_card(self, monkeypatch):
        _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(
                    {
                        "hotel": {"hotelId": 22293},
                        "offers": [
                            {
                                "ratePlanUuid": "a", "availabilityDate": "2026-07-28",
                                "startHour": 10, "endHour": 16, "priceEuro": 5400,
                                "includedAmenities": ["Outdoor pool", "Free parking"],
                            },
                            {
                                "ratePlanUuid": "b", "availabilityDate": "2026-07-28",
                                "startHour": 17, "endHour": 23, "priceEuro": 6000,
                                "includedAmenities": ["Free parking", "Fitness room"],
                            },
                            # Another day must not contribute its perks.
                            {
                                "ratePlanUuid": "c", "availabilityDate": "2026-08-04",
                                "startHour": 10, "endHour": 16, "priceEuro": 3900,
                                "includedAmenities": ["Indoor pool"],
                            },
                        ],
                    }
                ),
                "generate_booking_link": lambda args: FakeResult(
                    {"link": {"url": f"https://www.dayuse.fr/t?o={args['ratePlanUuid']}"}}
                ),
            },
        )
        profile = SessionProfile(
            last_results=[{"hotel_id": 22293, "name": "V"}], date="2026-07-28"
        )
        result = _run(
            inline_tools.generate_booking_link(
                "pick", profile, user_confirmed=False, picked_hotel_id=22293
            )
        )
        # Union across the DAY's formulas, first-seen order, no duplicates.
        assert result["hotel_amenities"] == ["Outdoor pool", "Free parking", "Fitness room"]
        assert "Indoor pool" not in result["hotel_amenities"]
        # And never copied onto the rows.
        assert all("addons" not in p for p in result["rate_plans"])

    def test_no_amenities_means_no_key(self, monkeypatch):
        _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(
                    {
                        "hotel": {"hotelId": 22293},
                        "offers": [
                            {"ratePlanUuid": "a", "availabilityDate": "2026-07-28",
                             "startHour": 10, "endHour": 16, "priceEuro": 5400},
                            {"ratePlanUuid": "b", "availabilityDate": "2026-07-28",
                             "startHour": 17, "endHour": 23, "priceEuro": 6000},
                        ],
                    }
                ),
                "generate_booking_link": lambda args: FakeResult(
                    {"link": {"url": f"https://www.dayuse.fr/t?o={args['ratePlanUuid']}"}}
                ),
            },
        )
        profile = SessionProfile(
            last_results=[{"hotel_id": 22293, "name": "V"}], date="2026-07-28"
        )
        result = _run(
            inline_tools.generate_booking_link(
                "pick", profile, user_confirmed=False, picked_hotel_id=22293
            )
        )
        assert "hotel_amenities" not in result

    def test_the_night_rate_unit_matches_priceEuro(self, monkeypatch):
        """Live-probed 2026-07-28 over 760 real price pairs: originalPriceEuro is
        EUR cents like priceEuro, night/day ratio median 1.64, and ZERO offers
        had a night rate at or below the day rate."""
        _install(
            monkeypatch,
            {
                "get_hotel_details": FakeResult(
                    {
                        "hotel": {"hotelId": 22293},
                        "offers": [
                            {"ratePlanUuid": "a", "availabilityDate": "2026-07-28",
                             "startHour": 10, "endHour": 16, "priceEuro": 8900,
                             "originalPriceEuro": 11570},
                            {"ratePlanUuid": "b", "availabilityDate": "2026-07-28",
                             "startHour": 17, "endHour": 23, "priceEuro": 6900,
                             "originalPriceEuro": 7670},
                        ],
                    }
                ),
                "generate_booking_link": lambda args: FakeResult(
                    {"link": {"url": f"https://www.dayuse.fr/t?o={args['ratePlanUuid']}"}}
                ),
            },
        )
        profile = SessionProfile(
            last_results=[{"hotel_id": 22293, "name": "V"}], date="2026-07-28"
        )
        plans = {
            p["offer_id"]: p
            for p in _run(
                inline_tools.generate_booking_link(
                    "pick", profile, user_confirmed=False, picked_hotel_id=22293
                )
            )["rate_plans"]
        }
        assert plans["b"]["price"] == "€69.00"
        assert plans["b"]["original_price"] == "€76.70"
        assert plans["b"]["discount_pct"] == 10  # (7670-6900)/7670 = 10.04%
        assert plans["a"]["original_price"] == "€115.70"
        assert plans["a"]["discount_pct"] == 23


class TestObs4McpTraceContext:
    """OBS4: the inline MCP calls carry the W3C trace context in the MCP
    `_meta` field, so MCP_B2C can attach its ES queries to this turn's trace
    (server side = OBS10). Wire format: OBS4-TRACE-PROPAGATION-CONTRACT.md §3.
    ADK's own McpToolset already does this for the leaves' MCP calls — this is
    the concierge catching up, since its inline tools bypass ADK entirely."""

    def test_meta_is_none_when_tracing_is_disabled(self, monkeypatch):
        session = _install(
            monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)}
        )
        profile = SessionProfile(last_results=SHORTLIST)
        _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
        assert session.metas == [None]  # never an empty dict on the wire

    def test_meta_carries_the_traceparent_of_the_tool_span(self, monkeypatch):
        from b2c_common import observability
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.trace import format_trace_id

        tracer = TracerProvider().get_tracer("b2c-test")
        monkeypatch.setattr(observability, "_client", object())
        session = _install(
            monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)}
        )
        profile = SessionProfile(last_results=SHORTLIST)
        with tracer.start_as_current_span("turn") as span:
            _run(inline_tools.get_hotel_details("Villa Paris Orly", profile))
            trace_id = format_trace_id(span.get_span_context().trace_id)

        assert len(session.metas) == 1
        meta = session.metas[0]
        assert meta is not None
        assert meta["traceparent"].split("-")[1] == trace_id
        assert f"langfuse_trace_id={trace_id}" in meta["baggage"]


class TestP1HotelNameSlot:
    """P1-1: triage's `hotel_name` slot is the PRIMARY extraction for MCP
    `find_hotel_by_name`; `_extract_hotel_name_candidate` stays the fallback.
    Unlike the boolean slots this one is a VALUE, so it is LLM-primary rather
    than additive — there is no "OR" to take between two strings."""

    def _script(self, monkeypatch):
        return _install(
            monkeypatch,
            {
                "find_hotel_by_name": FakeResult({"hotel": FIND_BY_NAME_RESPONSE}),
                "get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE),
            },
        )

    def test_the_slot_becomes_the_mcp_name_argument(self, monkeypatch):
        session = self._script(monkeypatch)
        profile = SessionProfile()  # empty shortlist → must go to MCP
        result = _run(
            inline_tools.get_hotel_details(
                "peux-tu me sortir la fiche du Moxy NYC Chelsea s'il te plaît",
                profile,
                llm_hotel_name="Moxy NYC Chelsea",
            )
        )
        assert result["ok"] is True
        by_name = [args for name, args in session.calls if name == "find_hotel_by_name"]
        assert by_name[0]["name"] == "Moxy NYC Chelsea"

    def test_without_the_slot_the_phrase_stripper_still_runs(self, monkeypatch):
        session = self._script(monkeypatch)
        profile = SessionProfile()
        _run(inline_tools.get_hotel_details("book the Moxy NYC Chelsea for me", profile))
        by_name = [args for name, args in session.calls if name == "find_hotel_by_name"]
        # The fr/en stripper removes "book the" and "for me" — which is exactly
        # all it can do, and why the slot exists for every other phrasing.
        assert by_name[0]["name"] == "Moxy NYC Chelsea"

    def test_a_strong_shortlist_hit_never_reaches_mcp_even_with_the_slot(self, monkeypatch):
        """The slot changes EXTRACTION, never MATCHING: a hotel already on
        screen still resolves from the shortlist with zero MCP round-trip."""
        session = _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
        profile = SessionProfile(last_results=SHORTLIST)
        result = _run(
            inline_tools.get_hotel_details(
                "Villa Paris Orly", profile, llm_hotel_name="Villa Paris Orly"
            )
        )
        assert result["ok"] is True
        assert [c[0] for c in session.calls] == ["get_hotel_details"]


def test_shown_details_never_looks_up_question_as_hotel_name(monkeypatch):
    session = _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
    result = _run(inline_tools.get_shown_hotel_details(SessionProfile(
        date="2026-07-21", last_results=SHORTLIST + SHORTLIST
    )))
    assert result["ok"]
    assert session.calls == [("get_hotel_details", {"hotelId": 22293, "date": "2026-07-21"})]
    # The fixture only contains an offer for July 20: never attach it to July 21.
    assert "price" not in result["hotels"][0]
    assert result["hotels"][0]["amenities"] == ["Free WiFi", "Spa"]


def test_empty_shown_details_has_no_network_call(monkeypatch):
    session = _install(monkeypatch, {})
    assert not _run(inline_tools.get_shown_hotel_details(SessionProfile()))["ok"]
    assert session.calls == []


def test_shown_details_failure_is_not_reported_as_all_hotels_verified(monkeypatch):
    _install(monkeypatch, {"get_hotel_details": RuntimeError("unavailable")})
    assert not _run(inline_tools.get_shown_hotel_details(SessionProfile(last_results=SHORTLIST)))["ok"]


def test_details_keeps_the_displayed_formula_and_its_own_clock(monkeypatch):
    selected = dict(HOTEL_DETAILS_RESPONSE["offers"][0], ratePlanUuid="selected", startHour=10,
                    startMinute=30, endHour=16, priceEuro=8000)
    session = _install(monkeypatch, {"get_hotel_details": FakeResult({
        "hotel": HOTEL_DETAILS_RESPONSE["hotel"],
        "offers": HOTEL_DETAILS_RESPONSE["offers"] + [selected],
    })})
    profile = SessionProfile(date="2026-07-20", last_results=[{
        "hotel_id": 22293, "name": "Villa Paris Orly", "offer_id": "selected",
        "offer_date": "2026-07-20",
    }])
    hotel = _run(inline_tools.get_hotel_details("", profile, picked_hotel_id=22293))["hotel"]
    assert hotel["offer_id"] == "selected"
    assert hotel["price_eur_cents"] == 8000
    assert hotel["timeslots"] == [{"start": "10:30", "end": "16:00"}]
    assert session.calls == [("get_hotel_details", {"hotelId": 22293, "date": "2026-07-20"})]


def test_details_does_not_silently_replace_unavailable_displayed_formula(monkeypatch):
    _install(monkeypatch, {"get_hotel_details": FakeResult(HOTEL_DETAILS_RESPONSE)})
    profile = SessionProfile(date="2026-07-20", last_results=[{
        "hotel_id": 22293, "name": "Villa Paris Orly", "offer_id": "no-longer-available",
        "offer_date": "2026-07-20",
    }])
    hotel = _run(inline_tools.get_hotel_details("", profile, picked_hotel_id=22293))["hotel"]
    assert "price" not in hotel
    assert "offer_id" not in hotel
    assert "timeslots" not in hotel
    assert hotel["amenities"]


def test_hotel_details_preserve_property_conditions_without_inventing_age(monkeypatch):
    conditions = 'Photo ID required. Minimum check-in age: 21. Deposit payable at reception.'
    _install(monkeypatch, {'get_hotel_details': FakeResult({
        'hotel': {'hotelId': 12, 'name': 'Example Hotel', 'conditions': conditions,
                  'commonConditions': 'A matching photo ID may be required.'},
        'offers': [],
    })})
    result = asyncio.run(inline_tools.get_hotel_details('', SessionProfile(), picked_hotel_id=12))
    assert result['hotel']['hotel_conditions'] == conditions
    assert result['hotel']['general_conditions'] == 'A matching photo ID may be required.'
    assert 'minimum_age' not in result['hotel']
    assert 'offer_id' not in result['hotel']


def test_missing_or_malformed_property_conditions_are_not_policy_evidence():
    for conditions in (None, '', [], {'minimumAge': 18}):
        result = inline_tools._normalize_hotel_for_display({'id': 1, 'conditions': conditions, 'commonConditions': conditions}, None)
        assert 'hotel_conditions' not in result
        assert 'general_conditions' not in result


class TestNamedAvailabilitySearch:
    def _offer(self, **changes):
        return {**HOTEL_DETAILS_RESPONSE['offers'][0], 'availabilityDate': '2030-10-09',
                'startHour': 10, 'endHour': 18, 'priceEuro': 9000,
                'priceEuroWithBookingFees': 9500, 'hotelPriceWithBookingFees': 8000,
                'hotelCurrency': 'USD', 'capacity': 2, 'childrenCapacity': 1, **changes}

    def test_selects_offer_for_new_date_window_budget_and_party_not_first_or_old_formula(self, monkeypatch):
        offers = [self._offer(availabilityDate='2030-10-08'),
                  self._offer(ratePlanUuid='late', startHour=17),
                  self._offer(ratePlanUuid='expensive', hotelPriceWithBookingFees=9000),
                  self._offer(ratePlanUuid='too-small', capacity=1),
                  self._offer(ratePlanUuid='missing-child-proof', childrenCapacity=None),
                  self._offer(ratePlanUuid='correct')]
        session = _install(monkeypatch, {'get_hotel_details': FakeResult({
            'hotel': HOTEL_DETAILS_RESPONSE['hotel'], 'offers': offers})})
        profile = SessionProfile(date='2030-10-09', timeslot_start='11:30', timeslot_end='16:00',
                                 adults=2, children=1, requested_budget={'amount': 80, 'currency': 'USD', 'unit': 'total'},
                                 last_results=[{'hotel_id': 22293, 'name': 'Villa Paris Orly',
                                                'offer_id': 'old-formula', 'offer_date': '2030-10-08'}])
        result = _run(inline_tools.get_hotel_details('', profile, picked_hotel_id=22293, for_search=True))
        assert result['ok'] is True
        assert result['hotel']['offer_id'] == 'correct'
        assert result['hotel']['offer_date'] == '2030-10-09'
        assert result['hotel']['capacity'] == 2
        assert result['hotel']['children_capacity'] == 1
        assert session.calls[0][0:2] == ('get_hotel_details', {'hotelId': 22293, 'date': '2030-10-09'})

    def test_expired_and_wrong_day_offers_do_not_prove_availability(self, monkeypatch):
        _install(monkeypatch, {'get_hotel_details': FakeResult({
            'hotel': HOTEL_DETAILS_RESPONSE['hotel'],
            'offers': [self._offer(cutoffDeadlineUtc='2000-01-01T12:00:00Z'),
                       self._offer(availabilityDate='2030-10-10')]})})
        result = _run(inline_tools.get_hotel_details('', SessionProfile(date='2030-10-09'),
                                                   picked_hotel_id=22293, for_search=True))
        assert result['ok'] is True
        assert 'offer_id' not in result['hotel']
        assert 'price' not in result['hotel']
        assert result['hotel']['name'] == 'Villa Paris Orly'

    def test_selects_cheapest_matching_offer_instead_of_first(self, monkeypatch):
        _install(monkeypatch, {'get_hotel_details': FakeResult({
            'hotel': HOTEL_DETAILS_RESPONSE['hotel'],
            'offers': [self._offer(ratePlanUuid='pricey', priceEuroWithBookingFees=12000),
                       self._offer(ratePlanUuid='cheaper', priceEuroWithBookingFees=6000)]})})
        result = _run(inline_tools.get_hotel_details('', SessionProfile(date='2030-10-09'),
                                                   picked_hotel_id=22293, for_search=True))
        assert result['hotel']['offer_id'] == 'cheaper'
        assert result['hotel']['price_eur_cents'] == 6000

    def test_details_for_another_hotel_cannot_be_attached_to_the_named_identity(self, monkeypatch):
        _install(monkeypatch, {'get_hotel_details': FakeResult({
            'hotel': {**HOTEL_DETAILS_RESPONSE['hotel'], 'hotelId': 999}, 'offers': [self._offer()]})})
        result = _run(inline_tools.get_hotel_details('', SessionProfile(date='2030-10-09'),
                                                   picked_hotel_id=22293, for_search=True))
        assert result['ok'] is False


def test_semantically_unidentified_question_never_becomes_mcp_hotel_name(monkeypatch):
    session = _install(monkeypatch, {})
    result = _run(inline_tools.get_hotel_details(
        'Can I arrive later if I lose some hours?', SessionProfile(city='Anaheim'), allow_text_name=False,
    ))
    assert not result['ok']
    assert session.calls == []


def test_strict_name_mode_keeps_verified_shortlist_match(monkeypatch):
    session = _install(monkeypatch, {'get_hotel_details': FakeResult(HOTEL_DETAILS_RESPONSE)})
    result = _run(inline_tools.get_hotel_details(
        'Villa Paris Orly', SessionProfile(last_results=SHORTLIST), allow_text_name=False,
    ))
    assert result['ok']
    assert [name for name, args in session.calls] == ['get_hotel_details']


def test_strict_name_mode_keeps_extracted_named_lookup(monkeypatch):
    session = _install(monkeypatch, {
        'find_hotel_by_name': FakeResult({'hotel': {'hotelId': 22293, 'name': 'Villa Paris Orly'}}),
        'get_hotel_details': FakeResult(HOTEL_DETAILS_RESPONSE),
    })
    result = _run(inline_tools.get_hotel_details(
        'Tell me about Villa Paris Orly', SessionProfile(),
        llm_hotel_name='Villa Paris Orly', allow_text_name=False,
    ))
    assert result['ok']
    assert session.calls[0] == ('find_hotel_by_name', {'name': 'Villa Paris Orly'})


def test_details_gives_synthesis_all_valid_formulas_without_changing_selected_offer(monkeypatch):
    from b2c_concierge.ground_truth import shortlist_ground_truth_block
    from b2c_concierge.display_currency import apply_hotel_currency
    make = TestNamedAvailabilitySearch()._offer
    selected = make(ratePlanUuid='selected', startHour=9, endHour=16)
    alternative = make(ratePlanUuid='afternoon', startHour=12, endHour=20,
                       priceEuroWithBookingFees=10000, hotelPriceWithBookingFees=8500)
    hotel = {**HOTEL_DETAILS_RESPONSE['hotel'], 'amenities': [
        {'name': 'Facility '+str(i)} for i in range(12)] + [{'name': 'Outdoor pool'}]}
    _install(monkeypatch, {'get_hotel_details': FakeResult({'hotel': hotel, 'offers': [
        selected, alternative, make(ratePlanUuid='expired', cutoffDeadlineUtc='2000-01-01T12:00:00Z'),
        make(ratePlanUuid='wrong-day', availabilityDate='2030-10-10'),
        make(ratePlanUuid='over-budget', hotelPriceWithBookingFees=10000),
        make(ratePlanUuid='too-small', capacity=1),
        make(ratePlanUuid='morning-only', startHour=8, endHour=10)]})})
    profile = SessionProfile(date='2030-10-09', adults=2, daypart='afternoon',
        requested_budget={'amount': 90, 'currency': 'USD', 'unit': 'total'},
        last_results=[{'hotel_id': 22293, 'offer_id': 'selected', 'offer_date': '2030-10-09'}])
    result = _run(inline_tools.get_hotel_details('', profile, picked_hotel_id=22293))
    card = result['hotel']
    assert card['offer_id'] == 'selected' and card['price'] == '€95.00'
    assert [o['offer_id'] for o in card['available_offers']] == ['selected', 'afternoon']
    block = shortlist_ground_truth_block({'results': [card]}, profile)
    assert 'Outdoor pool' in block and '09:00–16:00 €95.00' in block and '12:00–20:00 €100.00' in block
    apply_hotel_currency([card])
    block = shortlist_ground_truth_block({'results': [card]}, profile)
    assert '09:00–16:00 USD 80.00' in block and '12:00–20:00 USD 85.00' in block
    assert card['offer_id'] == 'selected'


def test_details_alternatives_still_apply_requested_clock(monkeypatch):
    make = TestNamedAvailabilitySearch()._offer
    _install(monkeypatch, {'get_hotel_details': FakeResult({'hotel': HOTEL_DETAILS_RESPONSE['hotel'],
        'offers': [make(ratePlanUuid='covers', startHour=9, endHour=18),
                   make(ratePlanUuid='starts-late', startHour=13, endHour=20)]})})
    profile = SessionProfile(date='2030-10-09', timeslot_start='11:00', timeslot_end='16:00')
    card = _run(inline_tools.get_hotel_details('', profile, picked_hotel_id=22293, for_search=True))['hotel']
    assert [o['offer_id'] for o in card['available_offers']] == ['covers']


@pytest.mark.parametrize('failed', [False, True])
def test_explicit_missing_name_cannot_fall_back_to_city_word_match(monkeypatch, failed):
    session = _install(monkeypatch, {'find_hotel_by_name': FakeResult(
        {} if failed else {'hotel': None}, is_error=failed)})
    profile = SessionProfile(city='Paris', last_results=[
        {'hotel_id': 123, 'name': 'Hôtel Mercure Paris Notre-Dame Saint-Germain-des-Prés'}])
    result = _run(inline_tools.get_hotel_details('Tell me about Ritz Paris', profile,
        llm_hotel_name='Ritz Paris', allow_text_name=False))
    assert result['ok'] is False and result['error'] == 'hotel not found'
    assert [c[0] for c in session.calls] == ['find_hotel_by_name']
