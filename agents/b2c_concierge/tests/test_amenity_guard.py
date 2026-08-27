"""Amenity claim verifier — behavior ported from agent-usa's production audit
(2026-06-09, tests/unit/application/test_audit_fixes_2026_06.py, "P7: anti-
hallucination state block + amenity claim verifier" section). The BEHAVIOR is
the spec; the old implementation lived in an AgentOrchestrator classmethod
mutating a long-lived Conversation and is not reused (amenity_guard.py is
plain, pure functions).
"""
from __future__ import annotations

from b2c_concierge.amenity_guard import amenity_claim_violations, apply_amenity_truthfulness


class TestAmenityClaimViolations:
    def test_violation_detected_for_unbacked_hot_tub(self):
        # Prod session 3cec10e5: "includes a Hot tub" on a hotel listing only
        # an indoor pool.
        message = "- Sonesta Select Indianapolis Carmel — from $96 — includes a Hot tub + indoor pool"
        hotels = [
            {
                "name": "Sonesta Select Indianapolis Carmel",
                "amenities": ["Indoor pool", "Free WiFi", "Fitness room"],
            }
        ]
        violations = amenity_claim_violations(message, hotels)
        assert violations == {"Sonesta Select Indianapolis Carmel": {"jacuzzi"}}

    def test_negated_line_is_not_a_violation(self):
        message = "- The Wellington — from $132.91 — close daytime fit; spa not listed"
        hotels = [{"name": "The Wellington", "amenities": ["Fitness room"]}]
        assert amenity_claim_violations(message, hotels) == {}

    def test_backed_by_multilingual_label_passes(self):
        # Worldwide inventory: "piscina al aire libre" must satisfy a "pool" claim.
        message = "- InterContinental Barcelona — rooftop pool and spa"
        hotels = [
            {
                "name": "InterContinental Barcelona",
                "amenities": ["Piscina al aire libre", "Sauna", "Centro de masajes"],
            }
        ]
        violations = amenity_claim_violations(message, hotels)
        assert "pool" not in violations.get("InterContinental Barcelona", set())

    def test_hotels_own_name_backing_the_claim_is_never_a_violation(self):
        message = "- Saccardi Hotel & Spa — great value, close to the station"
        hotels = [{"name": "Saccardi Hotel & Spa", "amenities": ["Free WiFi"]}]
        assert amenity_claim_violations(message, hotels) == {}

    def test_no_hotels_or_empty_message_is_never_a_violation(self):
        assert amenity_claim_violations("", [{"name": "Hotel A", "amenities": []}]) == {}
        assert amenity_claim_violations("has a pool", None) == {}


class TestApplyAmenityTruthfulness:
    def test_hedges_claim_in_place(self):
        # Was: append a trailing "⚠️ Correction" note, shipping the false
        # claim AND its contradiction in the same message. The claim token is
        # now hedged in place instead.
        message = "- Sonesta Carmel Suites — includes a Hot tub + indoor pool"
        hotels = [{"name": "Sonesta Carmel Suites", "amenities": ["Indoor pool"]}]
        result, corrections = apply_amenity_truthfulness(message, hotels, "en")
        assert "Hot tub (not confirmed)" in result
        assert "⚠️" not in result
        assert "Sonesta Carmel Suites" in result
        assert corrections == {"Sonesta Carmel Suites": ["jacuzzi"]}

    def test_no_change_when_clean(self):
        message = "- Radisson Blu — indoor pool and spa access"
        hotels = [{"name": "Radisson Blu", "amenities": ["Indoor pool", "Spa"]}]
        result, corrections = apply_amenity_truthfulness(message, hotels, "en")
        assert result == message
        assert corrections == {}

    def test_french_hedge_uses_the_localized_marker(self):
        message = "- Le Meridien — jacuzzi et piscine"
        hotels = [{"name": "Le Meridien", "amenities": ["Piscine"]}]
        result, corrections = apply_amenity_truthfulness(message, hotels, "fr")
        assert "jacuzzi (non confirmé)" in result
        assert corrections == {"Le Meridien": ["jacuzzi"]}

    def test_correction_already_issued_is_never_repeated_across_turns(self):
        message = "- Sonesta Carmel Suites — includes a Hot tub + indoor pool"
        hotels = [{"name": "Sonesta Carmel Suites", "amenities": ["Indoor pool"]}]
        # First turn already recorded the jacuzzi correction (persisted from a
        # PRIOR call) — a later re-scan hedges the token again (idempotent,
        # in-place) but must not append a duplicate correction NOTE.
        result, corrections = apply_amenity_truthfulness(
            message, hotels, "en", already_issued={"Sonesta Carmel Suites": ["jacuzzi"]}
        )
        assert "Hot tub (not confirmed)" in result
        assert result.count("⚠️") == 0
        assert corrections == {"Sonesta Carmel Suites": ["jacuzzi"]}

    def test_never_raises_on_malformed_hotels(self):
        result, corrections = apply_amenity_truthfulness("has a pool", [None, 42], "en")
        assert result == "has a pool"
        assert corrections == {}


class TestUX2SevenLanguageHedges:
    """UX2 (2026-08-27): the hedge/correction text widened from fr/en to the
    7 languages the concierge can now answer in."""

    def test_spanish_hedge_uses_the_localized_marker(self):
        message = "- Le Meridien — jacuzzi y piscina"
        hotels = [{"name": "Le Meridien", "amenities": ["Piscine"]}]
        result, corrections = apply_amenity_truthfulness(message, hotels, "es")
        assert "jacuzzi (no confirmado)" in result
        assert corrections == {"Le Meridien": ["jacuzzi"]}

    def test_correction_note_is_localized_de(self):
        from b2c_concierge.amenity_guard import _correction_note

        note = _correction_note("Sonesta Carmel Suites", "jacuzzi", "de")
        assert note == (
            "⚠️ Korrektur: Sonesta Carmel Suites listet jacuzzi nicht unter seinen "
            "Dayuse-Ausstattungen — bitte direkt beim Hotel nachfragen."
        )

    def test_unrecognized_language_falls_back_to_the_english_hedge(self):
        message = "- Le Meridien — jacuzzi"
        hotels = [{"name": "Le Meridien", "amenities": []}]
        result, _ = apply_amenity_truthfulness(message, hotels, "ja")
        assert "jacuzzi (not confirmed)" in result
