"""Geo guards — ported from agent-usa's production audit fixes.

Spec: agent-usa `tests/unit/application/test_audit_fixes_2026_06.py`, sections
geocode echo-back (+ state hints, ZIP anchor), generic place words, state
anchoring. Test names mirror the originals 1:1 where the underlying function
is pure (state hints, echo-back, postal anchor, resolve_state_hint, generic
tokens) — same inputs, same expected outputs, just imported from
`geo_guards` instead of agent-usa's `SearchTool`/`SearchProfileBuilder`.

Four tests are ADAPTED (not weakened): agent-usa exercises generic-city
demotion and state anchoring through a long-lived `Conversation`; this leaf is
stateless (decision B3), so those two guards are re-tested against the
dict-in/dict-out shape they actually have here (`demote_generic_city`,
`anchor_state_context`) — same scenario, same asserted outcome, no
`Conversation`/session object survives the port.
"""
from __future__ import annotations

import pytest

from hotel_search_agent.geo_guards import (
    PostalAnchor,
    anchor_state_context,
    demote_generic_city,
    extract_state_hint_from_text,
    geocode_echo_matches,
    is_generic_location_token,
    resolve_state_hint,
    select_us_postal_anchor,
)

# ── State hint extraction from free text ─────────────────────────────────────


def test_state_hint_from_city_string():
    assert extract_state_hint_from_text("florence kentucky") == "Kentucky"


def test_state_hint_from_mass_shorthand():
    assert extract_state_hint_from_text("West Springfield mass") == "Massachusetts"


def test_state_hint_from_address_abbreviation():
    assert extract_state_hint_from_text("10308 North 65th lane Glendale AZ 85302") == "Arizona"


def test_state_hint_ignores_ambiguous_words():
    # "in", "la", "or", "me" are common words, never state hints in free text.
    assert extract_state_hint_from_text("find me a room in la or near me") is None
    assert extract_state_hint_from_text("hotel in paris") is None


def test_state_hint_ignores_washington():
    # DC vs the state is unresolvable from the bare word.
    assert extract_state_hint_from_text("washington") is None


# ── Geocode echo-back guard ──────────────────────────────────────────────────


def test_echo_back_rejects_unrelated_place_for_birmingham():
    assert not geocode_echo_matches(
        "Colorado Springs, Colorado, United States",
        city="Birmingham airport",
        zone="Birmingham airport",
        state_hint=None,
    )


def test_echo_back_rejects_atlanta_for_budapest():
    assert not geocode_echo_matches(
        "Atlanta, Georgia, United States",
        city="Budapest",
        zone="Keleti train station",
        state_hint=None,
    )


def test_echo_back_rejects_wrong_state_for_florence_ky():
    assert not geocode_echo_matches(
        "Florence, Tuscany, Italy",
        city="Florence",
        zone=None,
        state_hint="Kentucky",
    )


def test_echo_back_accepts_matching_state_and_city():
    assert geocode_echo_matches(
        "Florence, Kentucky, United States",
        city="Florence",
        zone=None,
        state_hint="Kentucky",
    )


def test_echo_back_accepts_zone_match():
    assert geocode_echo_matches(
        "Hollywood, Florida, United States",
        city="Miami",
        zone="Hollywood",
        state_hint=None,
    )


def test_echo_back_accepts_saint_st_variants():
    assert geocode_echo_matches(
        "Saint Augustine, Florida, United States",
        city="St Augustine",
        zone=None,
        state_hint=None,
    )


def test_echo_back_accepts_translated_exonym_wien_vienna():
    # S-G9 finding 9: "Wien" resolved as "Vienna, Austria" was rejected —
    # a translated exonym is a different word, not a diacritic variant, so
    # only the explicit pair table can bridge it.
    assert geocode_echo_matches(
        "Vienna, Austria",
        city="Wien",
        zone=None,
        state_hint=None,
    )


def test_echo_back_accepts_exonym_in_the_other_direction():
    assert geocode_echo_matches(
        "Praha, Czechia",
        city="Prague",
        zone=None,
        state_hint=None,
    )


def test_echo_back_still_rejects_unrelated_place_despite_exonym_table():
    # The table must only bridge its own pairs — an unrelated resolution for
    # "Wien" stays rejected.
    assert not geocode_echo_matches(
        "Vienne, Isère, France",
        city="Wien",
        zone=None,
        state_hint=None,
    )


@pytest.mark.parametrize("place", [
    "New York City, New York, United States",
    # cbe88b9's fixture, restored (PR134-FIX R5): Mapbox's canonical label for
    # the city carries no "City" — the alias extends the place's own initials.
    "New York, New York, United States",
])
def test_echo_back_accepts_short_alias_supported_by_provider_name(place):
    # The short alias needs this evidence; an empty token set is no longer a
    # universal pass.
    assert geocode_echo_matches(place, city="NYC", zone=None, state_hint=None)


def test_geocode_echo_rejects_non_latin_city_against_latin_place():
    # Greek-script city cannot validate against a US homonym place name —
    # must NOT vacuously pass (prod 57c626f5: "Κηφισιά" → Buffalo NY).
    assert (
        geocode_echo_matches(
            "Buffalo, New York, United States",
            city="Κηφισιά, Αττική",
            zone=None,
            state_hint=None,
        )
        is False
    )
    # Latin echo still works (city token present in resolved place).
    assert geocode_echo_matches(
        "Paris, Île-de-France, France", city="Paris", zone=None, state_hint=None
    ) is True
    # Empty requests still impose no name constraint.
    assert geocode_echo_matches("Buffalo, NY", city="", zone=None, state_hint=None)


def test_echo_back_folds_german_eszett():
    # The German endonym "Gießen" must echo the ASCII "giessen" the user typed,
    # so the gate keeps the correct DE candidate instead of the Dutch homonym
    # (prod f4ef0259). Before the fold, re.sub deleted "ß" → "gie en" → no echo.
    assert geocode_echo_matches("Gießen, Hessen, Germany", city="giessen", zone=None, state_hint=None)
    # A genuinely unrelated place still fails to echo.
    assert not geocode_echo_matches(
        "Tilburg, Noord-Brabant, Netherlands", city="giessen", zone=None, state_hint=None
    )


# ── ZIP anchor (same spec section as echo-back) ──────────────────────────────


def test_postal_anchor_prefers_zip_after_state_over_street_number():
    anchor = select_us_postal_anchor("10308 North 65th lane Glendale AZ 85302")
    assert anchor is not None
    assert isinstance(anchor, PostalAnchor)
    assert anchor.value == "85302"


# ── resolve_state_hint: tiered resolution (keywords > text > profile anchor) ─


def test_resolve_state_hint_keyword_ct():
    assert (
        resolve_state_hint(
            keywords=["ct"],
            city="Milford",
            zone=None,
            profile_location_hint=None,
            raw_user_message="110",
            profile_state_context=None,
            country_code="US",
        )
        == "Connecticut"
    )


def test_resolve_state_hint_profile_context_fallback():
    # Prod session 3d3618c1: the search turn's message is just "110" and the
    # city is stored bare — without the anchored CT, "Milford, USA" geocodes
    # to the Massachusetts Milford and the results come back from Boston.
    assert (
        resolve_state_hint(
            keywords=[],
            city="Milford",
            zone=None,
            profile_location_hint="Milford",
            raw_user_message="110",
            profile_state_context="CT",
            country_code="US",
        )
        == "Connecticut"
    )


def test_resolve_state_hint_profile_context_ambiguous_code_ok():
    # "ca" is skipped in free text (word collision) but is unambiguous as
    # structured profile state.
    assert (
        resolve_state_hint(
            keywords=[],
            city="Ontario",
            zone=None,
            profile_location_hint=None,
            raw_user_message="under 150",
            profile_state_context="CA",
            country_code="US",
        )
        == "California"
    )


def test_resolve_state_hint_text_wins_over_profile_context():
    assert (
        resolve_state_hint(
            keywords=[],
            city="Milford massachusetts",
            zone=None,
            profile_location_hint=None,
            raw_user_message="",
            profile_state_context="CT",
            country_code="US",
        )
        == "Massachusetts"
    )


def test_resolve_state_hint_non_us_ignores_profile_context():
    assert (
        resolve_state_hint(
            keywords=[],
            city="Madrid",
            zone=None,
            profile_location_hint=None,
            raw_user_message="",
            profile_state_context="CT",
            country_code="ES",
        )
        is None
    )


# ── Generic location words are not cities (prod: 'airport' → Modesto CA) ────


def test_generic_location_tokens_detected():
    assert is_generic_location_token("airport")
    assert is_generic_location_token("The Airport")
    assert is_generic_location_token("Terminal 5")
    assert is_generic_location_token("terminal")
    assert is_generic_location_token("downtown")
    assert is_generic_location_token("near me")


def test_real_cities_are_not_generic():
    assert not is_generic_location_token("Miami Beach")
    assert not is_generic_location_token("Anacortes")
    # "Terminal Island" is a real LA locality — only bare "terminal N" is generic.
    assert not is_generic_location_token("Terminal Island")
    assert not is_generic_location_token("Vancouver")


def test_generic_city_demoted_to_zone():
    # Adapted from agent-usa's test_generic_city_demoted_to_zone_and_gating_asks_city:
    # same scenario (city='airport' + metro='airport'), dict-based instead of a
    # Conversation. The clarification-gating half (`ready_to_search`) is a
    # session/profile concern (S05) — the guard under test here is the
    # demotion itself.
    params = demote_generic_city({"city": "airport", "metro": "airport"})
    assert params.get("city") in (None, "")
    assert params.get("metro") in (None, "")
    assert params.get("zone") == "airport"


def test_terminal_city_demoted_to_zone():
    params = demote_generic_city({"city": "Terminal 5"})
    assert params.get("city") in (None, "")
    assert params.get("zone") == "Terminal 5"


def test_generic_city_demotion_keeps_existing_zone():
    # A real zone already present must not be clobbered by the generic city.
    params = demote_generic_city({"city": "airport", "zone": "Financial District"})
    assert params.get("city") in (None, "")
    assert params.get("zone") == "Financial District"


# ── State anchoring: the named US state qualifies geocoding across turns ────


def test_milford_ct_anchors_state_context():
    # Adapted from agent-usa's test_milford_ct_anchors_state_context: same
    # scenario (bare "Milford ct" anchors CT), stateless signature — the
    # anchor travels via profile_in/profile_delta (contract.py) instead of
    # `Conversation.preferences`.
    anchored, delta = anchor_state_context(
        city="Milford", raw_user_message="Milford ct", profile_in={}
    )
    assert anchored == "CT"
    assert delta["last_state_context"] == "CT"


def test_state_context_cleared_on_explicit_city_switch():
    # Adapted from agent-usa's test_state_context_cleared_on_explicit_city_switch:
    # turn 2 forwards turn 1's profile_delta as profile_in (the orchestrator's
    # job in the real system, S05) — a new city with no state token must
    # clear the stale anchor rather than mis-qualify Phoenix as CT.
    _, delta1 = anchor_state_context(city="Milford", raw_user_message="Milford ct", profile_in={})
    profile_in_turn2 = {
        "last_state_context": delta1["last_state_context"],
        "last_city": delta1["last_city"],
    }
    anchored2, delta2 = anchor_state_context(
        city="Phoenix", raw_user_message="actually Phoenix please", profile_in=profile_in_turn2
    )
    assert not anchored2
    assert "last_state_context" in delta2
    assert delta2["last_state_context"] is None


def test_state_context_reused_without_explicit_state_or_city_change():
    # A bare refinement turn ("under 150") names no city and no state — the
    # anchor from a previous turn must still be reused, not dropped.
    _, delta1 = anchor_state_context(city="Milford", raw_user_message="Milford ct", profile_in={})
    profile_in_turn2 = {
        "last_state_context": delta1["last_state_context"],
        "last_city": delta1["last_city"],
    }
    anchored2, delta2 = anchor_state_context(
        city=None, raw_user_message="under 150", profile_in=profile_in_turn2
    )
    assert anchored2 == "CT"
    assert "last_state_context" not in delta2


class TestGenericTokensAreArticleInsensitive:
    """2026-08-26. The word set carried "the airport" explicitly but no French
    articled form, and the model writes what the user said: "un hôtel près de la
    gare" produces `zone="la gare"`, which was NOT recognised as generic. So a
    generic word reached the Search-Box landmark lookup — the thing the tier-2
    comment warns about ("Search Box would happily return some airport on
    another continent") — and the failure diagnostic named it a landmark."""

    def test_french_articled_generic_words_are_generic(self):
        for token in ("la gare", "le centre ville", "les aeroports", "l'aeroport"):
            assert is_generic_location_token(token) is True, token

    def test_articled_real_landmarks_stay_specific(self):
        # The whole reason this cannot be a blunt "strip every article": these
        # are the landmarks the tier-2 lookup exists for.
        for token in ("les champs élysées", "la défense", "la sagrada familia",
                      "gare de lyon", "the eiffel tower"):
            assert is_generic_location_token(token) is False, token

    def test_a_bare_generic_word_is_unchanged(self):
        assert is_generic_location_token("gare") is True
        assert is_generic_location_token("airport") is True
        assert is_generic_location_token("terminal 2") is True


def test_poi_strict_identity_preserves_city_partial_echo_and_exonyms():
    assert geocode_echo_matches('Kingston, England',city='Kingston upon Thames',zone=None,state_hint=None)
    assert geocode_echo_matches('Palace Rome, Italy',city=None,zone='Palace Roma',state_hint=None,require_all_tokens=True)


def test_missing_name_does_not_prove_strict_poi_identity():
    assert not geocode_echo_matches('',city=None,zone='Solar Pizza',state_hint=None,require_all_tokens=True)


@pytest.mark.parametrize('query', ['JFK', 'JFK area', 'JFK Airport', 'Rio', 'NY'])
def test_short_identity_does_not_vacuously_accept_unrelated_city(query):
    assert not geocode_echo_matches('Brea, California, United States', city=query,
                                    zone=None, state_hint=None)


@pytest.mark.parametrize(('query', 'place'), [
    ('JFK area', 'John F. Kennedy International Airport, New York'),
    ('Rio', 'Rio de Janeiro, Brazil'), ('NY', 'New York, United States'),
    ('NYC', 'NYC, New York City, New York, United States'),
])
def test_short_identity_accepts_provider_name_or_initials(query, place):
    assert geocode_echo_matches(place, city=query, zone=None, state_hint=None)
