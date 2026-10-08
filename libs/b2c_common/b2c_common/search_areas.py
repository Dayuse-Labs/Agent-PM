"""Closed geographic intent shared by the profile owner and stateless search leaf."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

MAX_AREAS = 3

class AreaRequest(BaseModel):
    """Closed tool schema: names/intent only; geometry always comes from provider."""
    model_config = ConfigDict(extra="forbid")
    query: str = Field(description="Full area name for geocoding, for example Yvelines or Brescia.")
    kind: Literal["administrative", "municipality"]
    country: str = Field(description="ISO2 country of the requested area, e.g. FR, IT, GB.")
    evidence: str = Field(description="Shortest exact quote from the CURRENT user message naming this area, e.g. 78 or Brescia. Never add words.")
    boundary_evidence: str = Field(default="", description="Exact current words explicitly changing administrative boundary to city limits; omit for a repeated place name or country clarification.")
    code: str = Field(default="", description="Administrative code explicitly named, e.g. 78. Omit when only the name was stated.")


def validate_areas(value: Any, message: str | None = None) -> list[dict[str, str]] | None:
    """Closed typed extraction; optional literal current-message grounding.

    Literal evidence checks provenance, not perfect semantic understanding.
    A numeric department identifier additionally MUST match the provider code.
    """
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_AREAS:
        return None
    result = []
    for item in value:
        if isinstance(item, AreaRequest):
            item = item.model_dump(exclude_defaults=True)
        if not isinstance(item, dict) or set(item) - {"query", "kind", "country", "code", "evidence", "boundary_evidence"}:
            return None
        if any(not isinstance(item.get(k), str) or not item[k].strip() for k in ("query", "kind", "country", "evidence")):
            return None
        clean = {k: v.strip() for k, v in item.items() if isinstance(v, str)}
        if clean["kind"] not in {"administrative", "municipality"}:
            return None
        if len(clean["country"]) != 2 or not clean["country"].isascii() or not clean["country"].isalpha():
            return None
        clean["country"] = clean["country"].upper()
        if message is not None and clean["evidence"].casefold() not in message.casefold():
            # A model may paraphrase the surrounding preposition while the
            # actual destination name is verbatim. Ground on that exact name.
            if clean["query"].casefold() not in message.casefold():
                return None
            clean["evidence"] = clean["query"]
        if clean["evidence"].isdigit():
            if clean.get("code") and clean["code"] != clean["evidence"]:
                return None
            clean["code"] = clean["evidence"]
        # JSON null means no optional code was supplied, just like omission.
        # Named provinces still require provider identity; a stated numeric
        # code remains mandatory/matching through the evidence guard above.
        if item.get("code") is not None and not isinstance(item["code"], str):
            return None
        if clean.get("boundary_evidence") and message is not None and clean["boundary_evidence"].casefold() not in message.casefold():
            return None
        if message is not None:
            words = "".join(c if c.isalnum() else " " for c in message.casefold()).split()
            named = clean["query"].casefold() in message.casefold()
            coded = bool(clean.get("code") and clean["code"].casefold() in words)
            if not named and not coded:
                return None  # "all", "cheaper", etc. cannot invent a new area identity

        if clean not in result:
            result.append(clean)
    return result



def preserve_area_boundary(previous: list[dict[str, str]] | None,
                           update: list[dict[str, str]] | None) -> list[dict[str, str]] | None:
    """A repeated name/country clarification does not narrow a whole province.

    A new city, changed alternatives or explicit boundary-change quote still
    replaces the scope. Language understanding stays in the typed extraction.
    """
    if previous and update and len(previous) == len(update) == 1:
        old, new = previous[0], update[0]
        if (old.get("kind") == "administrative" and new.get("kind") == "municipality"
                and old.get("query", "").casefold() == new.get("query", "").casefold()
                and old.get("country") == new.get("country") and not new.get("boundary_evidence")):
            return previous
    return update
