"""Provider-backed place identity and bounded clarification transport.

The concierge owns persistence. These pure validators never infer a place from
customer text, execute a search, or trust coordinates proposed by the model.
"""
from __future__ import annotations

import math
from typing import Any

CLARIFICATION_KEY = "temp:hotel_search_location_clarification"
RESOLVED_PLACE_KEY = "temp:hotel_search_resolved_place"


def grounded_landmark(value: Any, message: str, *, confirmed_city: str | None = None,
                      confirmed_country: str | None = None) -> dict | None:
    """Validate an existing model extraction, never infer intent or coordinates."""
    if not isinstance(value, dict):
        return None
    query, evidence = value.get("query"), value.get("evidence")
    if (not isinstance(query, str) or not query.strip() or len(query) > 200
            or not isinstance(evidence, str) or not evidence.strip() or evidence not in message
            or query.strip().casefold() not in evidence.casefold()):
        return None
    city = value.get("city")
    if city is not None and (not isinstance(city, str) or not city.strip()):
        return None
    inherited_parent = bool(
        city and confirmed_city and city.strip().casefold() == confirmed_city.casefold()
        and (not value.get("country_guess") or str(value["country_guess"]).upper() == confirmed_country)
    )
    if city and city.strip().casefold() not in message.casefold() and not inherited_parent:
        # An invented parent is not authority. Only the identical, already
        # provider-confirmed city can supply a missing current-message parent.
        city = None
    guess = value.get("country_guess")
    if guess is not None and (not isinstance(guess, str) or len(guess) != 2 or not guess.isascii() or not guess.isalpha()):
        return None
    if value.get("kind") not in (None, "landmark", "address", "postcode"):
        return None
    return {"query": query.strip(), "city": city.strip() if city else None,
            **({"kind": value["kind"]} if value.get("kind") in {"address", "postcode"} else {}),
            "country_guess": guess.upper() if guess else None}


def verified_place(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    strings = ("provider_id", "name", "label", "country_code", "feature_type")
    if any(not isinstance(value.get(k), str) or not value[k].strip() for k in strings):
        return None
    if value["feature_type"] not in {"place", "locality", "poi", "address", "postcode"}:
        return None  # Administrative boundaries retain their resolution contract.
    search_context = None
    if value["feature_type"] in {"poi", "address", "postcode"} or value.get("search_context") is not None:
        # A provider place/locality can also answer a scoped zone request.
        # Keep that scope without relabelling the provider feature as a POI.
        context = value.get("search_context")
        if not isinstance(context, dict) or not isinstance(context.get("zone"), str) or not context["zone"].strip():
            return None
        if any(context.get(k) is not None and not isinstance(context[k], str) for k in ("city", "metro")):
            return None
        search_context = {k: (context.get(k) or "").strip() or None for k in ("city", "zone", "metro")}
    country = value["country_code"].upper()
    if len(country) != 2 or not country.isascii() or not country.isalpha():
        return None
    provider_city = value.get("provider_city")
    parent = ({k: provider_city[k].strip() for k in ("name", "provider_id")}
              if isinstance(provider_city, dict) and all(
                  isinstance(provider_city.get(k), str) and provider_city[k].strip()
                  for k in ("name", "provider_id")) else None)
    for key, bound in (("latitude", 90), ("longitude", 180)):
        n = value.get(key)
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or abs(n) > bound:
            return None
    return {**({"search_context": search_context} if search_context else {}),
            **({"provider_city": parent} if parent else {}),
            **({"administrative_code": value["administrative_code"]} if isinstance(value.get("administrative_code"), str) and value["administrative_code"] else {}),
            **{k: value[k].strip() for k in strings}, "country_code": country,
            "latitude": float(value["latitude"]), "longitude": float(value["longitude"]),
            "region": value.get("region") if isinstance(value.get("region"), str) else ""}


def pending_location(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("question"), str):
        return None
    options = value.get("options")
    minimum = 1 if value.get("confirmation_required") is True else 2
    if not isinstance(options, list) or not minimum <= len(options) <= 3 or not value["question"].strip():
        return None
    valid = [verified_place(o) for o in options]
    if any(o is None for o in valid):
        return None  # Never renumber an incomplete list the customer already saw.
    if len({o["provider_id"] for o in valid if o}) != len(valid):
        return None
    return {"question": value["question"].strip(), "options": valid,
            **({"confirmation_required": True} if value.get("confirmation_required") is True else {})}


def context_for_triage(pending: Any, confirmed: Any, *, unresolved: dict | None = None,
                       areas: list | None = None, device_available: bool = False,
                       requested: Any = None) -> dict[str, Any] | None:
    from .destination_request import destination_request
    request = destination_request(requested)
    request_context: dict[str, Any] = {"requested_destination": request.model_dump(exclude_none=True)} if request else {}
    if device_available:
        request_context["device_available"] = True
    p, c = pending_location(pending), verified_place(confirmed)
    if p:
        return {**request_context, "question": p["question"], "options": [
            {"position": i, "label": o["label"], "region": o["region"], "country": o["country_code"], **({"administrative_code": o["administrative_code"]} if o.get("administrative_code") else {})}
            for i, o in enumerate(p["options"], 1)
        ]}
    if c:
        return {**request_context, "confirmed_place": c["label"],
                **({"search_context": c["search_context"]} if c.get("search_context") else {}),
                # A POI's display name is not its city. Only the structured
                # provider parent can authorize a later street/landmark reply;
                # search_context.city is a request string, not that evidence.
                "confirmed_city": (c["name"] if c["feature_type"] in {"place", "locality"}
                                   else (c.get("provider_city") or {}).get("name")),
                "region": c["region"],
                "country": c["country_code"], "administrative_code": c.get("administrative_code")}
    context: dict[str, Any] = dict(request_context)
    if unresolved is not None:
        context["unresolved_request"] = {k: v for k, v in unresolved.items() if v}
    if areas:
        context["requested_areas"] = areas
    if device_available:
        context["device_available"] = True  # No coordinates in the triage prompt.
    return context or None


def location_intent(value: Any, message: str, context: dict | None) -> dict | None:
    if not isinstance(value, dict):
        return None
    action = value.get("action")
    kind = value.get("kind")
    # New wire responses carry a mandatory semantic kind. Older stored test/
    # caller values without it retain their legacy shape; kinds never come
    # from matching the customer's words in code.
    typed = "kind" in value
    if typed and kind not in {"none", "city", "area", "landmark", "hotel", "device"}:
        return None
    # A no-op asserts no new geographic fact. Requiring a quote for it turned
    # price/hour replies into location questions when triage copied the old
    # place name. The caller discards all accompanying destination updates;
    # relaxing this no-op cannot authorize a change or promote an identity.
    if action == "preserve":
        return {"action": "preserve", **({"kind": "none"} if typed else {})}
    evidence = value.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip() or evidence not in message:
        return None
    extra = {"kind": kind} if typed else {}
    # The operation is authoritative. A copied description of the old target
    # cannot turn a time-only preserve into a location change, or device into
    # a named landmark. Kind is descriptive, not a second competing operation.
    if typed and action in {"preserve", "missing", "device"}:
        extra = {"kind": "device" if action == "device" else "none"}
    if action == "select":
        n = value.get("position")
        options = (context or {}).get("options") or []
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= len(options):
            return None
        return {"action": action, "position": n, **extra}
    if action == "refine":
        parent = value.get("parent_city")
        # A quoted parent is a request label, never provider evidence. Keep it
        # separate from the old landmark so history need not masquerade as a
        # new, verbatim landmark extraction.
        if (isinstance(parent, str) and parent.strip() and len(parent) <= 200
                and parent.strip().casefold() in message.casefold()):
            return {"action": action, "parent_city": parent.strip(), **extra}
        return {"action": action, **extra}
    if action in {"preserve", "change", "correct", "device", "missing", "unknown"}:
        parent = value.get("parent_city")
        if (action in {"change", "correct"} and isinstance(parent, str)
                and parent.strip() and parent.casefold() in message.casefold()):
            extra["parent_city"] = parent.strip()
        return {"action": action, **extra}
    return None
