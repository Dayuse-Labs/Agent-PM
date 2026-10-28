"""`GeoIntent` v1.1 — what the user means by "where", as a closed schema.

The search leaf's LLM fills this object as a structured argument of
`geocode_location` (plan qa14707, DQ1). The LLM understands; the code owns the
values and checks them against the provider's facts (Mapbox, inventory).
Contract: `reports/PLAN-LEAF-GEO-2026-10-08.md` §3, plus the v1.1 additions:

- `places[].postal_code`: the postcode as written. In QA trace C
  (« 2 boulevard Poissonnière 75009 », `phases/QA14707/DIAGNOSTIC.md`) the
  two free strings `city` / `zone` had no room for it, and it was thrown away.
- `mention` / `canonical`, for `places[]` and for `city`: `mention` is the
  user's exact text, `canonical` the name the LLM normalized (« Pari » →
  « Paris »). The code checks that the mention is anchored in the message and
  that the canonical name is real (Q07).
- `ambiguity` holds only `reason` — no `options` (DQ5): no option of a question
  is ever written by an LLM, they come from the geocoder only.
- `ambiguity.reason = "city_needed"` carries the S5 rule (DQ6): a place named
  after a city it is not in (gare de Lyon, in Paris).

Invariants, each locked by a test:

- NO coordinate field, anywhere: latitude/longitude only ever come from the
  geocoder.
- `extra="forbid"` on every model, closed enumerations.
- A default on EVERY field, so an absent or partial argument is never rejected
  by ADK before the tool runs (an ADK parameter with no default is) and still
  converts to a `GeoIntent`.

How to declare it on an ADK 2.4 tool (proved offline in
`tests/test_geo_intent_contract.py`): `geo_intent: GeoIntent = GeoIntent()`.
ADK converts the LLM's dict with `model_validate` only when the resolved
annotation is the class itself or a `typing.Optional[...]` that is not a
string. `GeoIntent | None` never converts, and `Optional[GeoIntent]` stops
converting under `from __future__ import annotations` (which
`geocode_tool.py` has): the function then gets a plain dict. An argument that
fails validation (an unknown `kind`, a third place…) also reaches the function
as the raw dict, not rejected: the tool has to validate it itself. The
declaration keeps the field descriptions only on ADK's default
`JSON_SCHEMA_FOR_FUNC_DECL` path; the legacy path drops them.

Every `description` and every class docstring below ends up in the JSON schema
of the tool declaration the LLM reads: they are prompt, written for the leaves'
model, gpt-6-luna since 2026-10-15 (DQ11). Rationale goes in this module
docstring or in comments, never there.

`Place`'s field ORDER and its JSON-schema `required` list are prompt too
(Q23). The model writes the keys in the order it reads them: in H3, with
`city` 5th and `country` 7th after `postal_code`, gpt-4o-mini filled a
landmark's city 0 times in 25 and its country never, so every landmark without
a typed city got the city question. Hence mention, kind, canonical, then city
and country, then postal_code. `PLACE_REQUIRED` makes the model write those six
keys, null when unknown. It binds the model's output only: no field is
required by pydantic, so an absent or partial argument still converts with the
defaults above. The probe also showed gpt-4o-mini breaking both city guards
under this wording (Gare du Nord given Paris, gare de Lyon not flagged): it is
tuned for gpt-6-luna, not for gpt-4o-mini.

`contracts/geo_intent.schema.json` is the frozen snapshot of
`GeoIntent.model_json_schema()` (`tests/test_geo_intent_contract.py`);
regenerate it with
`python libs/b2c_common/b2c_common/geo_intent.py > contracts/geo_intent.schema.json`.

Import it as a submodule (`from b2c_common.geo_intent import GeoIntent`).
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SchemaVersion = Literal["1.1"]
SCHEMA_VERSION: SchemaVersion = "1.1"
MAX_PLACES = 2

PlaceKind = Literal[
    "city",
    "admin_district",
    "neighborhood",
    "landmark",
    "street",
    "station",
    "airport",
    "address",
    "hotel",
    "region",
    "city_centre",
]
Relation = Literal["in", "near", "whole_city"]
Carryover = Literal["new", "keep", "replace_place_keep_city", "refine"]
AmbiguityReason = Literal["homonym", "city_needed", "too_vague"]

#: The `Place` keys the model must write, in the order it reads them (Q23).
PLACE_REQUIRED = ("mention", "kind", "canonical", "city", "country", "postal_code")

# frozen: the code reads the LLM's intent and never rewrites it in place, and a
# frozen `GeoIntent()` is safe as a shared parameter default (see below).
_FORBID = ConfigDict(extra="forbid", frozen=True)


class Place(BaseModel):
    """A place the user named."""

    # Field order and `required` are prompt too (Q23, see the module docstring):
    # the model writes the keys in the order it reads them, so the place's city
    # and country come right after its name. `required` binds the model's
    # output only: every field keeps its default, and a partial dict still
    # validates.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={"required": list(PLACE_REQUIRED)},
    )

    mention: str = Field(
        default="",
        description="The user's exact words for the place, copied as written, typos included.",
    )
    kind: PlaceKind | None = Field(
        default=None,
        description=(
            "What the place is. city_centre: the centre of the city (\"in centro\", "
            "\"centre-ville\", \"downtown\"), with that city in `city`; never a business "
            "whose name contains the word."
        ),
    )
    canonical: str = Field(
        default="",
        description=(
            "The place's correct full name, spelling fixed "
            "(\"champs elysee\" -> \"Champs-Élysées\", \"St Paul's\" in London -> "
            "\"St Paul's Cathedral\")."
        ),
    )
    city: str | None = Field(
        default=None,
        description=(
            "The city the place is in, from your knowledge when the user did not write it "
            "(\"Buckingham Palace\" -> \"London\", \"le Louvre\" -> \"Paris\", "
            "\"times square\" -> \"New York\"). "
            "Homonyms are decided by the tool, not by you. "
            "null only when the place is named after a city it is not in "
            "(\"gare de Lyon\") or when the place is itself a city."
        ),
    )
    country: str | None = Field(
        default=None,
        description=(
            "ISO-3166-1 alpha-2 code of the country the place is in (\"FR\"), from your "
            "knowledge. null when unsure."
        ),
    )
    postal_code: str | None = Field(
        default=None,
        description=(
            "The postcode or ZIP code exactly as written (\"75009\"), also when the postcode "
            "alone is the place (\"dans le 75009\"). null when none is written."
        ),
    )
    region: str | None = Field(
        default=None,
        description="Code of the state or province the place is in, when known (\"CT\"). Else null.",
    )
    city_inferred: bool = Field(
        default=False,
        description="true when `city` comes from your knowledge, false when the user wrote it.",
    )


class CityRef(BaseModel):
    """The city of the search."""

    model_config = _FORBID

    mention: str = Field(
        default="",
        description="The user's exact words for the city, as written. Empty when not written in this message.",
    )
    canonical: str = Field(
        default="",
        description="The city's correct name (\"paris\" -> \"Paris\", \"Pari\" -> \"Paris\").",
    )
    region: str | None = Field(
        default=None,
        description="Code of the state or province of the city, when known (\"CT\"). Else null.",
    )
    country: str | None = Field(
        default=None,
        description="ISO-3166-1 alpha-2 country of the city (\"FR\"). Null when unsure.",
    )


class Exclusion(BaseModel):
    """A place the user wants to avoid."""

    model_config = _FORBID

    mention: str = Field(default="", description="The user's exact words for the place, as written.")
    canonical: str = Field(default="", description="The place's correct full name.")
    kind: PlaceKind | None = Field(default=None, description="What the place is.")


class Ambiguity(BaseModel):
    """Why you cannot tell where to search."""

    # No `options` field, ever (DQ5): the options of a question come from the
    # geocoder, through `Clarification` (Q03), never from an LLM.
    model_config = _FORBID

    reason: AmbiguityReason | None = Field(
        default=None,
        description=(
            "homonym: the name fits several places and nothing says which one. "
            "city_needed: the place is named after a city it is NOT in "
            "(\"gare de Lyon\" is a station in Paris): then give no city. Not when the "
            "place is in that city (\"vieux Lyon\" is in Lyon). "
            "too_vague: no searchable place (\"somewhere nice\")."
        ),
    )


class GeoIntent(BaseModel):
    """Where the user wants to search, as understood from the message. Never coordinates."""

    model_config = _FORBID

    schema_version: SchemaVersion = Field(default=SCHEMA_VERSION, description="Always \"1.1\".")
    places: list[Place] = Field(
        default_factory=list,
        max_length=MAX_PLACES,
        description=(
            "The places named in THIS message, most important first, at most 2. "
            "Empty when the message names no place."
        ),
    )
    city: CityRef | None = Field(
        default=None,
        description=(
            "The city of the search: written in the message, or kept from the earlier "
            "request when this message names none. Null when unknown."
        ),
    )
    country_named: str | None = Field(
        default=None,
        description=(
            "ISO-3166-1 alpha-2 code of a country the user NAMED in words (\"in Italy\" "
            "-> \"IT\"). Null when no country is written: never guess here."
        ),
    )
    region_named: str | None = Field(
        default=None,
        description="Code of a state or province the user NAMED (\"Milford ct\" -> \"CT\"). Else null.",
    )
    relation: Relation = Field(
        default="in",
        description=(
            "in: inside the place. near: around it (\"near\", \"close to\"). "
            "whole_city: anywhere in the city."
        ),
    )
    # 2026-10-28: « près de moi » (the entry chip agent-usa served 489 times
    # since September). The user's own position is not a place: the tool
    # searches around the device's position when the browser or the app gave
    # one, and says it has none otherwise — never a lookup of « moi ».
    near_user: bool = Field(
        default=False,
        description=(
            "true when the user wants to search around THEIR OWN current position "
            "(\"near me\", \"près de moi\", \"autour de moi\", \"cerca de mí\", "
            "\"vicino a me\", \"in meiner Nähe\", \"perto de mim\", \"bij mij in de "
            "buurt\"). Their position is not a place: never put it in `places`."
        ),
    )
    # Default `keep` = fill the empty slots from the earlier search, which is
    # what `geocode_location` does today: an omitted carryover changes nothing.
    carryover: Carryover = Field(
        default="keep",
        description=(
            "How this message relates to the earlier destination. new: a new destination. "
            "keep: no new place, same destination. replace_place_keep_city: a new place "
            "in the same city. refine: narrows the earlier destination."
        ),
    )
    exclusions: list[Exclusion] = Field(
        default_factory=list,
        description="Places the user wants to AVOID (\"not in NYC\"). Usually empty.",
    )
    ambiguity: Ambiguity | None = Field(
        default=None,
        description="Null in most cases. Set only when you cannot tell where to search.",
    )


if __name__ == "__main__":
    print(json.dumps(GeoIntent.model_json_schema(), indent=2, ensure_ascii=False))
