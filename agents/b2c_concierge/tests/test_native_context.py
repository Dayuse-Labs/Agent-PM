"""Native-context intake (S-G2, 2026-07-23) — facade.py.

Pure unit tests of the parsing/validation helpers against the REAL widget
payload shape confirmed by probing `web/vendor/static/js/chat/` (see
facade.py's module comment + HANDOFF): `locale`/`currency` are top-level
strings, GPS travels as `client_geo_context.device.{latitude, longitude,
accuracy_m, permission}` — NOT `native_context.geolocation`, which the
original phase brief assumed but the probe found unverifiable (opaque mobile
blob, no defined shape in this repo).
"""
from __future__ import annotations

from b2c_concierge.facade import _parse_picked_hotel_id  # noqa: F401
from b2c_concierge.facade import (
    _locale_response_language,
    _native_context_delta,
    _parse_client_timezone,
    _parse_currency,
    _parse_domain,
    _parse_gps_anchor,
    _parse_locale,
    _parse_source,
)


# --- _parse_locale -----------------------------------------------------------------------------
class TestParseLocale:
    def test_accepts_plain_and_regional_tags(self):
        assert _parse_locale("fr") == "fr"
        assert _parse_locale("en-US") == "en-US"
        assert _parse_locale("fr-FR") == "fr-FR"
        assert _parse_locale(" en ") == "en"  # whitespace tolerated

    def test_rejects_malformed_or_wrong_type(self):
        assert _parse_locale("") is None
        assert _parse_locale(None) is None
        assert _parse_locale(123) is None
        assert _parse_locale(["fr"]) is None
        assert _parse_locale("fr_FR!") is None
        assert _parse_locale("<script>") is None


# --- _parse_currency ----------------------------------------------------------------------------
class TestParseCurrency:
    def test_accepts_three_letter_code_and_uppercases(self):
        assert _parse_currency("usd") == "USD"
        assert _parse_currency("EUR") == "EUR"

    def test_rejects_malformed_or_wrong_type(self):
        assert _parse_currency("") is None
        assert _parse_currency(None) is None
        assert _parse_currency("US") is None
        assert _parse_currency("US$") is None
        assert _parse_currency(1) is None


# --- _parse_domain -------------------------------------------------------------------------------
class TestParseDomain:
    def test_accepts_hostname_and_lowercases(self):
        assert _parse_domain("Dayuse.com") == "dayuse.com"
        assert _parse_domain("www.dayuse.de") == "www.dayuse.de"

    def test_rejects_malformed_or_wrong_type(self):
        assert _parse_domain("") is None
        assert _parse_domain(None) is None
        assert _parse_domain("not a domain") is None
        assert _parse_domain("http://dayuse.com") is None  # scheme not a hostname
        assert _parse_domain(42) is None


# --- _locale_response_language ------------------------------------------------------------------
class TestLocaleResponseLanguage:
    def test_maps_supported_primary_subtags(self):
        assert _locale_response_language("fr-FR") == "fr"
        assert _locale_response_language("en-US") == "en"
        assert _locale_response_language("EN") == "en"

    def test_unsupported_or_absent_locale_is_none(self):
        # UX2 (2026-08-27): es is now answerable — use a genuinely
        # unrecognized primary tag to exercise the None branch.
        assert _locale_response_language("ja-JP") is None
        assert _locale_response_language(None) is None
        assert _locale_response_language("") is None


# --- _parse_gps_anchor ---------------------------------------------------------------------------
class TestParseGpsAnchor:
    def test_granted_with_valid_coords_builds_the_anchor(self):
        body = {
            "client_geo_context": {
                "device": {
                    "latitude": 48.8566,
                    "longitude": 2.3522,
                    "accuracy_m": 20.0,
                    "permission": "granted",
                }
            }
        }
        anchor = _parse_gps_anchor(body, turn_index=3)
        # R3 (review of #173): 3 decimals (~110 m), once, at the intake.
        assert anchor == {
            "type": "gps",
            "lat": 48.857,
            "lon": 2.352,
            "label": None,
            "set_at_turn": 3,
        }

    def test_denied_or_unavailable_yields_none(self):
        for permission in ("denied", "unavailable"):
            body = {"client_geo_context": {"device": {"permission": permission}}}
            assert _parse_gps_anchor(body, turn_index=0) is None

    def test_absent_or_malformed_context_yields_none(self):
        assert _parse_gps_anchor({}, turn_index=0) is None
        assert _parse_gps_anchor({"client_geo_context": "nope"}, turn_index=0) is None
        assert _parse_gps_anchor({"client_geo_context": {"device": "nope"}}, turn_index=0) is None
        assert _parse_gps_anchor({"client_geo_context": {}}, turn_index=0) is None

    def test_granted_but_missing_coords_yields_none(self):
        body = {"client_geo_context": {"device": {"permission": "granted"}}}
        assert _parse_gps_anchor(body, turn_index=0) is None

    def test_out_of_range_coords_are_rejected(self):
        for lat, lon in [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0)]:
            body = {
                "client_geo_context": {
                    "device": {"latitude": lat, "longitude": lon, "permission": "granted"}
                }
            }
            assert _parse_gps_anchor(body, turn_index=0) is None

    def test_non_numeric_or_bool_coords_are_rejected(self):
        for lat, lon in [("48.85", "2.35"), (True, False), (None, None)]:
            body = {
                "client_geo_context": {
                    "device": {"latitude": lat, "longitude": lon, "permission": "granted"}
                }
            }
            assert _parse_gps_anchor(body, turn_index=0) is None


# --- _parse_client_timezone (S-G6) -------------------------------------------------------------
class TestParseClientTimezone:
    def test_accepts_a_valid_iana_timezone(self):
        assert _parse_client_timezone("Europe/Paris") == "Europe/Paris"
        assert _parse_client_timezone(" America/New_York ") == "America/New_York"

    def test_rejects_malformed_or_wrong_type(self):
        assert _parse_client_timezone("") is None
        assert _parse_client_timezone(None) is None
        assert _parse_client_timezone("Not/AZone") is None
        assert _parse_client_timezone(123) is None
        assert _parse_client_timezone("CEST") is None  # abbreviation, not an IANA name


# --- _native_context_delta ------------------------------------------------------------------------
class TestNativeContextDelta:
    def test_empty_body_yields_empty_delta(self):
        assert _native_context_delta({}, turn_index=0) == {}

    def test_full_body_yields_every_valid_field(self):
        body = {
            "locale": "fr-FR",
            "currency": "eur",
            "domain": "Dayuse.com",
            "client_geo_context": {
                "device": {"latitude": 1.0, "longitude": 2.0, "permission": "granted"}
            },
            "client_timezone": "Europe/Paris",
        }
        delta = _native_context_delta(body, turn_index=1)
        assert delta["locale"] == "fr-FR"
        assert delta["currency"] == "EUR"
        assert delta["domain"] == "dayuse.com"
        assert delta["search_anchor"] == {
            "type": "gps",
            "lat": 1.0,
            "lon": 2.0,
            "label": None,
            "set_at_turn": 1,
        }
        assert delta["client_timezone"] == "Europe/Paris"

    def test_invalid_fields_are_simply_omitted_never_500(self):
        body = {
            "locale": 123, "currency": "not-a-currency", "domain": None,
            "native_context": "??", "client_timezone": "Not/AZone",
        }
        assert _native_context_delta(body, turn_index=0) == {}

    def test_opaque_native_context_never_breaks_parsing(self):
        # native_context is forwarded from the mobile app's own opaque object —
        # any shape (string, list, deeply nested dict) must never raise.
        for value in ("opaque-string", [1, 2, 3], {"anything": {"nested": True}}, None, 42):
            assert _native_context_delta({"native_context": value}, turn_index=0) == {}


class TestPickedHotelIntake:
    """S-CX5: `hotel_id` in the request body — a pick button was clicked."""

    def test_a_body_hotel_id_reaches_the_profile(self):
        assert _parse_picked_hotel_id({"hotel_id": 22293}) == 22293
        assert _parse_picked_hotel_id({"hotel_id": "22293"}) == 22293

    def test_garbage_is_ignored_like_every_other_optional_field(self):
        for bad in ({}, {"hotel_id": None}, {"hotel_id": "abc"}, {"hotel_id": True},
                    {"hotel_id": [1]}):
            assert _parse_picked_hotel_id(bad) is None


class TestSourceIntake:
    """2026-10-29: the request's `source` (the widget's deep-link `?source=`,
    « dayuse_box » from the dayuse.com AI box): a slug, lowercased."""

    def test_a_slug_is_kept_lowercased(self):
        assert _parse_source("dayuse_box") == "dayuse_box"
        assert _parse_source(" Mobile_App ") == "mobile_app"

    def test_anything_else_is_ignored(self):
        for bad in (None, 3, "", "a b", "x" * 80, "<script>", ["dayuse_box"]):
            assert _parse_source(bad) is None
