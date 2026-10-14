"""Clarification — the one structured shape of a question about a place.

QA14707 (dayuse-com#14707, DIAGNOSTIC §1): the search leaf asked "which city?"
with no option, the concierge's synthesis rewrote that question and INVENTED
options (« Bruxelles », « Versailles (78) »), and the next turn only had a
paraphrase to work with. The question existed only as text, so nothing could
tell a real option from an invented one.

This model is the question as DATA. The search leaf builds it from the
geocoder's own candidates and sends it to the concierge in its DataPart, by the
same channel as `search_context`; the concierge is to render it by template,
without the synthesis (decision DQ2, task Q04 — until then it ignores the key).
Two rules make the "no invented option" guarantee
structural rather than a prompt wish:

- `options` come ONLY from the geocoder's candidates kept by the leaf's
  resolver (`geo_resolver.resolve`, inventory tier included), never from an LLM
  (decision DQ5: `GeoIntent.ambiguity` carries a reason, never options).
- `city_needed` carries NO option on purpose: the question is asked before any
  geocoding, because an un-aimed lookup is biased by the container's egress IP
  and its candidates are the wrong answer (`geo_resolver.city_needed_question`).

Closed schema (`extra="forbid"`) and no coordinate anywhere: an option is
something to SAY to the user, and the answer turn geocodes again. A coordinate
here would be a second, unverified way into `search_offers`.

Imported as a submodule (`from b2c_common.clarification import Clarification`):
the package `__init__` re-exports only part of the package.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Version of this wire shape. A consumer that reads another value must not
#: guess at it.
SCHEMA_VERSION: Literal["1"] = "1"

#: Upper bound on the options of one question. The resolver offers at most 3
#: today (`geo_resolver._MAX_CLARIFY_OPTIONS`); the contract leaves headroom
#: without letting a list grow into something no one can answer.
MAX_OPTIONS = 5

ClarificationKind = Literal["city_needed", "homonym"]


class ClarificationOption(BaseModel):
    """One place the user can pick, exactly as the geocoder returned it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(
        min_length=1,
        description="How the option reads in the question, e.g. 'Victoria (British Columbia, Canada)'.",
    )
    city: str = Field(description="The candidate's own name from the geocoder, e.g. 'Victoria'.")
    region: str = Field(default="", description="The geocoder's region of the candidate, may be empty.")
    country_code: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{2}$",
        description="ISO-3166-1 alpha-2 of the candidate, None when the geocoder gave none.",
    )


class Clarification(BaseModel):
    """A question the search leaf asks instead of searching."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = SCHEMA_VERSION
    kind: ClarificationKind
    subject: str = Field(
        min_length=1,
        description="The place mention the question is about, as the request named it.",
    )
    options: list[ClarificationOption] = Field(default_factory=list, max_length=MAX_OPTIONS)

    @model_validator(mode="after")
    def _options_match_kind(self) -> Clarification:
        # The two kinds differ by exactly this: `city_needed` is asked before
        # any lookup, so an option there could only have come from somewhere
        # other than the geocoder; a homonym with nothing to pick is no question.
        if self.kind == "city_needed" and self.options:
            raise ValueError("a city_needed question carries no option")
        if self.kind == "homonym" and not self.options:
            raise ValueError("a homonym question needs at least one option")
        return self
