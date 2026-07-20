"""Multilingual amenity matcher, ported from agent-usa's
`src/application/matching/amenity_synonyms.py` (behavior AND data — this table
is Dayuse's own curated content, not a third-party library).

A naive substring check ("pool" in "piscine couverte" -> False) makes
worldwide inventory look like it is missing amenities it actually has. This
module keeps a synonym table covering en/fr/es/it/de/pt/nl and exposes a
single helper (`amenity_present`) used by amenity_guard.py's post-LLM claim
verifier (S07). Only the matcher is ported here — agent-usa's
`amenity_backed` (which also reads derived boolean flags like `has_pool` on
ITS OWN serialized hotel-card schema) is not: the MCP_B2C hotel shape this
spine consumes has no such derived flags, only a plain amenity name list.
"""
from __future__ import annotations

# Canonical amenity -> list of substrings (lowercased) that count as a match.
# Keys are the English canonical names the amenity-claim patterns key on.
_AMENITY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "pool": (
        "pool",
        "swimming pool",
        "indoor pool",
        "outdoor pool",
        "piscine",  # fr
        "piscina",  # es, it, pt
        "schwimmbad",
        "pool-",  # de
        "zwembad",  # nl
    ),
    "spa": (
        "spa",
        "wellness",
        "balneario",  # es
        "centro benessere",  # it
        "wellnessbereich",  # de
        "centro de bem-estar",  # pt
        "wellnesscentrum",  # nl
    ),
    "gym": (
        "gym",
        "fitness room",
        "fitness center",
        "fitness centre",
        "salle de sport",
        "salle de fitness",
        "salle de gym",  # fr
        "gimnasio",
        "sala de fitness",  # es
        "palestra",
        "sala fitness",  # it
        "fitnessraum",
        "fitnessstudio",
        "sportraum",  # de
        "academia",
        "sala de ginástica",  # pt
        "fitnessruimte",
        "sportschool",  # nl
    ),
    "jacuzzi": (
        "jacuzzi",
        "hot tub",
        "whirlpool",
        "bain à remous",
        "bain a remous",  # fr
        "bañera de hidromasaje",  # es
        "vasca idromassaggio",
        "idromassaggio",  # it
        "banheira de hidromassagem",  # pt
        "bubbelbad",  # nl
    ),
    "sauna": (
        "sauna",
        "hammam",  # cross-language
        "bain de vapeur",  # fr
        "baño de vapor",  # es
        "bagno turco",  # it
        "dampfbad",  # de
        "banho turco",  # pt
        "stoombad",  # nl
    ),
    "rooftop": (
        "rooftop",
        "roof bar",
        "roof terrace",
        "terrasse sur le toit",  # fr
        "azotea",
        "terraza en la azotea",  # es
        "terrazza panoramica",  # it
        "dachterrasse",
        "dachbar",  # de
        "terraço",  # pt
        "dakterras",  # nl
    ),
    "parking": (
        "parking",
        "valet parking",
        "stationnement",  # fr
        "aparcamiento",
        "estacionamiento",  # es
        "parcheggio",  # it
        "parkplatz",  # de
        "estacionamento",  # pt
        "parkeerplaats",  # nl
    ),
    "restaurant": (
        "restaurant",
        "restaurante",  # es, pt
        "ristorante",  # it
    ),
    "breakfast": (
        "breakfast",
        "breakfast area",
        "petit déjeuner",
        "petit dejeuner",
        "coin petit-déjeuner",  # fr
        "desayuno",
        "área de desayuno",  # es
        "colazione",  # it
        "frühstück",
        "fruehstueck",  # de
        "café da manhã",  # pt
        "ontbijt",  # nl
    ),
    "pet_friendly": (
        "pets allowed",
        "pet friendly",
        "dogs allowed",
        "dog friendly",
        "animaux domestiques",
        "animaux acceptes",
        "animaux acceptés",  # fr
        "se admiten mascotas",
        "mascotas permitidas",  # es
        "animali ammessi",  # it
        "haustiere erlaubt",
        "haustiere willkommen",  # de
        "animais permitidos",  # pt
        "huisdieren toegestaan",  # nl
    ),
    "shuttle": (
        "shuttle",
        "airport shuttle",
        "navette",  # fr
        "traslado",
        "lanzadera",  # es
        "navetta",  # it
        "flughafentransfer",  # de
        "transfer",  # pt
        "pendelbus",  # nl
    ),
}


def _expand_alias(amenity: str) -> tuple[str, ...]:
    """The list of substrings to look for when matching `amenity`."""
    key = amenity.strip().lower()
    if key in _AMENITY_SYNONYMS:
        return _AMENITY_SYNONYMS[key]
    # Always include the literal caller-supplied token so an amenity outside
    # the curated table still gets a substring chance.
    return (key,)


def amenity_present(amenity: str, hotel_amenities: list[str] | None) -> bool:
    """True when any synonym of `amenity` appears in the hotel amenity list.

    Lowercases everything and runs substring matches. The hotel list may be
    in any supported language — that's the whole point (a Parisian hotel
    listing "Piscine couverte" correctly satisfies an English "pool" claim).
    """
    if not amenity or not hotel_amenities:
        return False
    haystack = " ".join(str(a).lower() for a in hotel_amenities)
    return any(needle in haystack for needle in _expand_alias(amenity))
