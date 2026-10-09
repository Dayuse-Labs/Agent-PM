"""Customer destination intent, independent of provider-resolved identity.

Only the concierge creates this record from grounded semantic extractions.
The search leaf consumes it; neither model deltas nor provider labels edit it.
Names here are search requests, never proof of coordinates or membership.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .search_areas import requires_area_membership, validate_areas


class LandmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=200)
    country_guess: str | None = None

    @model_validator(mode="after")
    def coherent(self) -> LandmarkRequest:
        if not self.query.strip() or (self.city is not None and not self.city.strip()):
            raise ValueError("Landmark names cannot be blank")
        if self.country_guess is not None and (
            len(self.country_guess) != 2 or not self.country_guess.isascii()
            or not self.country_guess.isalpha()
        ):
            raise ValueError("Country hint must be ISO2 shaped")
        return self


class DestinationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["landmark", "landmarks", "address", "postcode", "hotel", "areas", "device"]
    query: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=200)
    country_guess: str | None = None
    areas: list[dict[str, str]] | None = None
    radius_km: float | None = Field(default=None, gt=0, le=200)
    landmarks: list[LandmarkRequest] | None = Field(default=None, min_length=2, max_length=3)

    @model_validator(mode="after")
    def coherent(self) -> DestinationRequest:
        if self.radius_km is not None and not (
            self.kind in {"landmark", "address", "postcode"}
            or (self.kind == "areas" and self.areas and len(self.areas) == 1
                and self.areas[0].get("kind") == "municipality"
                and not requires_area_membership(self.areas))
        ):
            raise ValueError("A radius needs one point origin, not an area boundary or alternative origins")
        if self.kind != "landmarks" and self.landmarks is not None:
            raise ValueError("Only an alternative-landmark request carries landmarks")
        if self.kind == "landmarks":
            if not self.landmarks or any((self.query, self.city, self.country_guess, self.areas)):
                raise ValueError("Alternative landmarks retain their separate requests")
        elif self.kind in {"landmark", "address", "postcode", "hotel"}:
            if not self.query or not self.query.strip() or self.areas is not None:
                raise ValueError("A landmark needs a requested name, not area geometry")
            if self.city is not None and not self.city.strip():
                raise ValueError("An absent parent is null")
            if self.country_guess is not None and (
                len(self.country_guess) != 2 or not self.country_guess.isascii()
                or not self.country_guess.isalpha()
            ):
                raise ValueError("Country hint must be ISO2 shaped")
        elif self.kind == "areas":
            if validate_areas(self.areas) is None or any((self.query, self.city, self.country_guess)):
                raise ValueError("Areas retain their existing grounded request contract")
        elif any((self.query, self.city, self.country_guess, self.areas)):
            raise ValueError("Device intent cannot carry model-supplied locations")
        return self


def destination_request(value: Any) -> DestinationRequest | None:
    try:
        return DestinationRequest.model_validate(value)
    except (ValidationError, TypeError):
        return None


def requested_parent(value: Any) -> str | None:
    """Return a previous customer parent label, never a provider confirmation."""
    request = destination_request(value)
    if request is None:
        return None
    if request.kind in {"landmark", "address", "postcode", "hotel"}:
        return request.city
    if request.kind == "areas" and request.areas and len(request.areas) == 1:
        area = request.areas[0]
        if area["kind"] == "municipality":
            return area["query"]
    return None


def refine_landmark(update: dict | None, previous: Any, action: str | None,
                    parent_city: str | None) -> dict | None:
    """Reduce typed corrections without treating earlier request text as proof.

    A new destination never inherits a parent implicitly. A correction of the
    same target can retain the customer's parent even before geocoding succeeds.
    """
    request = destination_request(previous)
    if update is not None:
        result = dict(update)
        if not result.get("city") and action in {"correct", "refine"}:
            result["city"] = parent_city or requested_parent(previous)
        if (request and request.radius_km is not None and action == "refine"
                and result.get("query") == request.query):
            result["radius_km"] = request.radius_km
        return result
    if request and request.kind in {"landmark", "address", "postcode"} and action == "refine" and parent_city:
        return {"query": request.query, "city": parent_city, "country_guess": None,
                **({"radius_km": request.radius_km} if request.radius_km is not None else {}),
                **({"kind": request.kind} if request.kind in {"address", "postcode"} else {})}
    return None


def address_context_question(query: str, language: str) -> str:
    questions = {
        "fr": "Je n’arrive pas à confirmer l’adresse « {address} ». Peux-tu vérifier le numéro, la rue et le code postal ?",
        "en": "I can’t confirm the address “{address}”. Could you check the street number, street name and postcode?",
        "de": "Ich kann die Adresse „{address}“ nicht bestätigen. Kannst du Hausnummer, Straße und Postleitzahl prüfen?",
        "es": "No puedo confirmar la dirección «{address}». ¿Puedes comprobar el número, la calle y el código postal?",
        "it": "Non riesco a confermare l’indirizzo «{address}». Puoi verificare il numero civico, la via e il codice postale?",
        "pt": "Não consigo confirmar o endereço «{address}». Podes verificar o número, a rua e o código postal?",
        "nl": "Ik kan het adres ‘{address}’ niet bevestigen. Kun je het huisnummer, de straat en de postcode controleren?",
    }
    return questions.get(language, questions["en"]).format(address=query)


def refine_hotel(name: str | None, previous: Any, action: str | None,
                 parent_city: str | None, message: str) -> dict | None:
    """Keep the named property when its containing city is clarified.

    Request names are literal user evidence, not provider identities. A new
    named hotel has no inherited city; a parent-only answer keeps its old name.
    """
    request = destination_request(previous)
    if name and name.strip().casefold() in message.casefold():
        return {"kind": "hotel", "query": name.strip()}
    if request and request.kind == "hotel" and action == "refine" and parent_city:
        return {**request.model_dump(exclude_none=True), "city": parent_city}
    return None


def landmark_context_question(request: DestinationRequest, language: str) -> str:
    """Keep all accepted alternatives in the clarification shown to the user."""
    points = request.landmarks or []
    labels = " / ".join(p.query + (f" ({p.city})" if p.city else "") for p in points)
    if points and all(p.city for p in points):
        questions = {
            "fr": "Je garde ces lieux comme alternatives : {places}. Peux-tu préciser leur adresse ou leur terminal pour les localiser ?",
            "en": "I’m keeping these places as alternatives: {places}. Could you specify their address or terminal so I can locate them?",
            "de": "Diese Orte bleiben als Alternativen erhalten: {places}. Welche Adresse oder welches Terminal ist gemeint?",
            "es": "Mantengo estas alternativas: {places}. ¿Puedes indicar su dirección o terminal para localizarlas?",
            "it": "Mantengo queste alternative: {places}. Puoi indicare il loro indirizzo o terminal per localizzarle?",
            "pt": "Mantenho estas alternativas: {places}. Podes indicar o endereço ou terminal para as localizar?",
            "nl": "Ik behoud deze alternatieven: {places}. Kun je het adres of de terminal opgeven zodat ik ze kan vinden?",
        }
    else:
        questions = {
            "fr": "Je garde ces lieux comme alternatives : {places}. Dans quelle ville dois-je les situer ?",
            "en": "I’m keeping these places as alternatives: {places}. In which city should I locate them?",
            "de": "Diese Orte bleiben als Alternativen erhalten: {places}. In welcher Stadt liegen sie?",
            "es": "Mantengo estas alternativas: {places}. ¿En qué ciudad están?",
            "it": "Mantengo queste alternative: {places}. In quale città si trovano?",
            "pt": "Mantenho estas alternativas: {places}. Em que cidade ficam?",
            "nl": "Ik behoud deze alternatieven: {places}. In welke stad liggen ze?",
        }
    return questions.get(language, questions["en"]).format(places=labels)


def postcode_context_question(query: str, language: str) -> str:
    questions = {
        "fr": "Je n’arrive pas à confirmer le code postal « {code} ». Dans quelle ville et quel pays se trouve-t-il ?",
        "en": "I can’t confirm the postcode “{code}”. Which city and country is it in?",
        "de": "Ich kann die Postleitzahl „{code}“ nicht bestätigen. Zu welcher Stadt und welchem Land gehört sie?",
        "es": "No puedo confirmar el código postal «{code}». ¿En qué ciudad y país está?",
        "it": "Non riesco a confermare il codice postale «{code}». In quale città e paese si trova?",
        "pt": "Não consigo confirmar o código postal «{code}». Em que cidade e país fica?",
        "nl": "Ik kan postcode ‘{code}’ niet bevestigen. Bij welke stad en welk land hoort deze?",
    }
    return questions.get(language, questions["en"]).format(code=query)
