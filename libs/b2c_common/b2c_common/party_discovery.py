"""Explore offers for an unresolved party without inventing its composition."""
from __future__ import annotations

from typing import Any


def discovery_total(params: Any) -> int | None:
    value = params.get("party_total") if isinstance(params, dict) else None
    return value if type(value) is int and 1 <= value <= 30 else None


def possible_party(offer: dict, total: int) -> bool:
    """Existence of a possible composition, NEVER proof for this customer.

    The provider exposes separate adult and child limits. Missing limits do
    not prove capacity. At least one adult must be possible. Booking still
    requires the customer's actual composition and ordinary eligibility.
    """
    adults, children = offer.get("capacity"), offer.get("childrenCapacity")
    return (type(adults) is int and adults >= 1 and (adults >= total or (
        type(children) is int and children >= 0 and adults + children >= total)))


def discovery_message(total: int, language: str) -> str:
    messages = {
        "fr": "Voici des pistes issues de la recherche. Leur capacité pour votre groupe de {total} personnes reste à confirmer : combien y a-t-il d’adultes et d’enfants ?",
        "en": "Here are options from the search. Suitability for your group of {total} still needs confirmation: how many adults and children are there?",
        "es": "Estas son opciones de la búsqueda. Falta confirmar la capacidad para vuestro grupo de {total}: ¿cuántos adultos y niños sois?",
        "it": "Ecco alcune opzioni dalla ricerca. La capienza per il gruppo di {total} persone va ancora confermata: quanti adulti e bambini siete?",
        "de": "Hier sind Optionen aus der Suche. Die Eignung für Ihre Gruppe von {total} Personen muss noch bestätigt werden: Wie viele Erwachsene und Kinder sind es?",
        "pt": "Aqui estão opções da pesquisa. Falta confirmar a capacidade para o grupo de {total} pessoas: quantos adultos e crianças são?",
        "nl": "Hier zijn opties uit de zoekopdracht. Geschiktheid voor jullie groep van {total} moet nog worden bevestigd: hoeveel volwassenen en kinderen zijn er?",
    }
    return messages.get(language, messages["en"]).format(total=total)
