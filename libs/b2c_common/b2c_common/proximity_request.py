"""Explicit distance changes: semantic extraction, literal units, owned origin."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from .destination_request import DestinationRequest, destination_request, requested_parent
from .search_budget import _amounts


def grounded_proximity(value: Any, message: str) -> dict | None:
    if not isinstance(value, dict):
        return None
    distance, unit, quote = value.get("distance"), value.get("unit"), value.get("evidence")
    if (type(distance) not in (int, float) or not isinstance(quote, str) or not quote.strip()
            or quote not in message or value.get("anchor") not in ("current", "parent_city")):
        return None
    amount = Decimal(str(distance))
    units = {"km": {"km", "kilometer", "kilometers", "kilometre", "kilometres", "kilomètre", "kilomètres", "chilometri", "kilómetros"},
             "mi": {"mi", "mile", "miles", "miglia", "millas"}}
    words = "".join(c if c.isalpha() else " " for c in quote.casefold()).split()
    if not isinstance(unit, str) or unit not in units or not units[unit].intersection(words) or amount not in _amounts(quote):
        return None
    radius = amount * (Decimal("1.609344") if unit == "mi" else Decimal(1))
    if not radius.is_finite() or not 0 < radius <= 200:
        return None
    return {"radius_km": float(radius), "anchor": value["anchor"]}


def apply_proximity(previous: Any, update: dict) -> DestinationRequest | None:
    request = destination_request(previous)
    if request is None:
        return None
    if update["anchor"] == "parent_city":
        parent = requested_parent(previous)
        if not parent:
            return None
        # The semantic operation explicitly permits leaving the subarea and
        # using its requested parent. The provider must still resolve that city.
        country = (request.areas[0].get("country", "") if request.areas
                   else request.country_guess or "")
        value: dict = {"kind": "areas", "areas": [{"kind": "municipality",
            "query": parent, "country": country, "evidence": parent}]}
    else:
        value = request.model_dump(exclude_none=True)
    try:
        return DestinationRequest.model_validate({**value, "radius_km": update["radius_km"]})
    except ValidationError:
        return None


def proximity_notice(context: Any, language: str) -> str:
    if not isinstance(context, dict) or not isinstance(context.get("radius_origin"), str):
        return ""
    radius, origin = context.get("radius_km"), context["radius_origin"]
    if not isinstance(radius, (int, float)) or isinstance(radius, bool) or not 0 < radius <= 200 or not origin.strip():
        return ""
    labels = {
        "fr": "Recherche dans un rayon de {radius:g} km à vol d’oiseau autour du point géocodé pour {origin}.",
        "en": "Searched within {radius:g} km in a straight line of the mapped point for {origin}.",
        "es": "Búsqueda en un radio de {radius:g} km en línea recta desde el punto localizado para {origin}.",
        "it": "Ricerca entro {radius:g} km in linea d’aria dal punto geolocalizzato per {origin}.",
        "de": "Suche im Umkreis von {radius:g} km Luftlinie um den ermittelten Kartenpunkt für {origin}.",
        "pt": "Pesquisa num raio de {radius:g} km em linha reta a partir do ponto localizado para {origin}.",
        "nl": "Gezocht binnen {radius:g} km hemelsbreed vanaf het gevonden kaartpunt voor {origin}.",
    }
    return labels.get(language, labels["en"]).format(radius=radius, origin=origin)
