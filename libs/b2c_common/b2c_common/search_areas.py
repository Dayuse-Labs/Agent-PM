"""Closed geographic intent shared by the profile owner and stateless search leaf."""
from typing import Any, Literal
import unicodedata
from pydantic import BaseModel, ConfigDict, Field

MAX_AREAS = 5  # At most one requested area per slot in the five-card shortlist.


def area_name_in_text(name: str, text: str) -> bool:
    """Match whole name tokens despite typography, without interpreting intent.

    Evidence must still be a literal current-message quote. Provider identity,
    country and membership checks remain responsible for geographic validity.
    """
    def words(value: str) -> list[str]:
        folded = "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                         if not unicodedata.combining(c))
        return "".join(c if c.isalnum() else " " for c in folded).split()

    name_words, text_words = words(name), words(text)
    return bool(name_words) and any(
        text_words[i:i + len(name_words)] == name_words
        for i in range(len(text_words) - len(name_words) + 1)
    )

class AreaRequest(BaseModel):
    """Closed tool schema: names/intent only; geometry always comes from provider."""
    model_config = ConfigDict(extra="forbid")
    query: str = Field(description="Full area name for geocoding, for example Yvelines or Brescia.")
    kind: Literal["administrative", "municipality", "neighborhood"]
    country: str = Field(description="ISO2 country when known, e.g. FR, IT, GB; empty string preserves an unresolved request.")
    evidence: str = Field(description="Shortest exact quote from the CURRENT user message naming this area, e.g. 78 or Brescia. Never add words.")
    boundary_evidence: str = Field(default="", description="Exact CURRENT words requiring city limits, e.g. 'only within city limits'. REQUIRED for a single bounded municipality, even on the first turn. Empty for an ordinary city name or country clarification; those use normal city search.")
    subarea: str = Field(default="", description="Verbatim named geographic subset required INSIDE this area, e.g. rive droite or Le Marais. Preserve the entire subset if composite. Empty only when the whole parent area is allowed; never replace a strict subset with its parent.")
    region: str = Field(default="", description="Verbatim containing state/province for this place; never a second alternative destination.")
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
        if not isinstance(item, dict) or set(item) - {"query", "kind", "country", "code", "evidence", "boundary_evidence", "subarea", "region"}:
            return None
        if any(not isinstance(item.get(k), str) or not item[k].strip() for k in ("query", "kind", "evidence")):
            return None
        clean = {k: v.strip() for k, v in item.items() if isinstance(v, str)}
        if clean["kind"] not in {"administrative", "municipality", "neighborhood"}:
            return None
        if not isinstance(item.get("country"), str):
            return None
        if clean["country"] and (len(clean["country"]) != 2 or not clean["country"].isascii() or not clean["country"].isalpha()):
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
        if item.get("region") is not None and not isinstance(item["region"], str):
            return None
        if clean.get("region") and message is not None and not area_name_in_text(clean["region"], message):
            return None
        if item.get("subarea") is not None and not isinstance(item["subarea"], str):
            return None
        if clean.get("subarea") and message is not None and clean["subarea"].casefold() not in message.casefold():
            return None
        if message is not None:
            words = "".join(c if c.isalnum() else " " for c in message.casefold()).split()
            named = area_name_in_text(clean["query"], message)
            coded = bool(clean.get("code") and clean["code"].casefold() in words)
            compact_query = "".join(c for c in clean["query"].casefold() if c.isalnum())
            compact_evidence = "".join(c for c in clean["evidence"].casefold() if c.isalnum())
            normalized_name = bool(compact_query and compact_query == compact_evidence)
            if clean.get("code") and not coded:
                return None
            if not named and not coded and not normalized_name:
                return None  # "all", "cheaper", etc. cannot invent a new area identity

        if clean not in result:
            result.append(clean)
    return result


def requires_area_membership(areas: list[dict[str, str]] | None) -> bool:
    """A single city name alone does not demand an administrative boundary.

    Explicit boundary evidence and administrative/alternative destinations
    retain verified membership. This consumes typed intent, never user prose.
    """
    return bool(areas and (len(areas) > 1 or areas[0]["kind"] in {"administrative", "neighborhood"}
                          or areas[0].get("boundary_evidence") or areas[0].get("subarea")))



def preserve_area_boundary(previous: list[dict[str, str]] | None,
                           update: list[dict[str, str]] | None, *,
                           parent_refinement: bool = False,
                           parent_city: str | None = None) -> list[dict[str, str]] | None:
    """A repeated name/country clarification does not narrow a whole province.

    A new city, changed alternatives or explicit boundary-change quote still
    replaces the scope. Language understanding stays in the typed extraction.
    """
    # The validated operation already contains the current-message parent.
    # Do not require the model to duplicate it in requested_areas: that loses
    # the parent on short clarification replies. Country is retained only
    # when the prior customer requests agree; no provider identity is inferred.
    if (parent_refinement and parent_city and previous and not update
            and all(old["kind"] in {"municipality", "neighborhood"} for old in previous)
            and len({old["country"] for old in previous}) == 1):
        update = [{"query": parent_city, "kind": "municipality",
                   "country": previous[0]["country"], "evidence": parent_city}]
    if previous and update:
        # The semantic action identifies a containing city, not a replacement
        # for the unresolved neighborhoods. Reuse the existing parent/subarea
        # contract: the provider must still prove each child's membership.
        parent = update[0]
        if (parent_refinement and len(update) == 1
                and parent["kind"] == "municipality"
                and not parent.get("subarea") and not parent.get("boundary_evidence")
                and all(old["kind"] in {"municipality", "neighborhood"} and old["country"] == parent["country"]
                        and old["query"].casefold() != parent["query"].casefold() for old in previous)):
            return [{**parent, "subarea": old.get("subarea") or old["query"]} for old in previous]
        retained = []
        for new in update:
            old = next((area for area in previous
                        if area.get("query", "").casefold() == new.get("query", "").casefold()
                        and area.get("country") == new.get("country")), None)
            if (old and (old.get("kind") in {"administrative", "neighborhood"} or old.get("boundary_evidence") or old.get("subarea"))
                and new.get("kind") == "municipality"
                and not new.get("boundary_evidence") and not new.get("subarea")):
                retained.append(old)
            else:
                retained.append(new)
        return retained
    return update
