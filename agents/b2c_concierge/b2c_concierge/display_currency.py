"""Display currency — EUR by default, the hotel's own currency on request.

Product rule (2026-09-25): prices are shown in EUR. When the user asks for the
hotel's currency, cards, rate plans and reply switch to it — for the rest of the
conversation, until they ask for euros again. Any OTHER currency is not
available yet: the user is told so, with the two choices that are.

Nothing here converts. The search leaf stamps each card with the SAME offer's
price in the hotel's currency (`hotel_price`, as indexed by MCP_B2C); this module
only chooses which of the two the user sees.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

HOTEL = "HOTEL"


@dataclass(frozen=True)
class CurrencyDecision:
    """`kind`: "none" (no request), "set" (switch to `mode`: None = EUR,
    "HOTEL"), or "unsupported" (`requested` is neither)."""

    kind: str
    mode: str | None = None
    requested: str | None = None
    hotel_currencies: tuple[str, ...] = field(default_factory=tuple)


def shortlist_currencies(last_results: list[dict[str, Any]] | None) -> tuple[str, ...]:
    codes = {
        str(entry["hotel_currency_code"])
        for entry in last_results or []
        if isinstance(entry, dict) and isinstance(entry.get("hotel_currency_code"), str)
    }
    return tuple(sorted(codes))


def shortlist_display_mode(last_results: list[dict[str, Any]] | None) -> str | None:
    """The currency the hotels ON SCREEN are shown in — not the saved preference,
    which a details-only or unavailable turn can set without repainting them.
    Hotels that all charge in EUR look the same either way: EUR."""
    entries = [e for e in last_results or [] if isinstance(e, dict)]
    for entry in entries:
        code = entry.get("hotel_currency_code")
        price = entry.get("price")
        if isinstance(code, str) and code != "EUR" and isinstance(price, str) and price.startswith(f"{code} "):
            return HOTEL
    return None


def resolve_currency_request(
    requested: str | None, last_results: list[dict[str, Any]] | None
) -> CurrencyDecision:
    if requested is None:
        return CurrencyDecision("none")
    if requested == "EUR":
        return CurrencyDecision("set", mode=None)
    if requested == HOTEL:
        return CurrencyDecision("set", mode=HOTEL)
    currencies = shortlist_currencies(last_results)
    # Naming the hotel's own currency ("en HKD" in Hong Kong) IS asking for it.
    if requested in currencies:
        return CurrencyDecision("set", mode=HOTEL)
    return CurrencyDecision("unsupported", requested=requested, hotel_currencies=currencies)


def apply_hotel_currency(cards: list[Any] | None) -> None:
    """Switch each card to its hotel-currency price, in place. A card without
    one keeps its EUR price rather than losing it."""
    for card in cards or []:
        if not isinstance(card, dict) or not isinstance(card.get("hotel_price"), str):
            continue
        card["price"] = card["hotel_price"]
        card["display_currency"] = card.get("hotel_currency_code")
        card["display_price_minor"] = card.get("hotel_price_minor")
        for slot in card.get("timeslots") or []:
            if not isinstance(slot, dict):
                continue
            # The struck-through night rate must be in the currency shown next to it.
            if slot.get("hotel_original_price") is not None:
                slot["original_price"] = slot["hotel_original_price"]
            else:
                slot.pop("original_price", None)


_UNSUPPORTED = {
    "fr": (
        "Je ne peux pas encore afficher les prix en {requested}. Je peux vous les "
        "montrer en euros, ou dans la devise de l'hôtel ({hotel}). Laquelle préférez-vous ?"
    ),
    "en": (
        "I can't show prices in {requested} yet. I can show them in euros, or in the "
        "hotel's own currency ({hotel}). Which would you prefer?"
    ),
    "es": (
        "Todavía no puedo mostrar los precios en {requested}. Puedo mostrártelos en "
        "euros o en la moneda del hotel ({hotel}). ¿Cuál prefieres?"
    ),
    "it": (
        "Non posso ancora mostrare i prezzi in {requested}. Posso mostrarli in euro "
        "oppure nella valuta dell'hotel ({hotel}). Quale preferisci?"
    ),
    "de": (
        "Ich kann die Preise noch nicht in {requested} anzeigen. Ich kann sie in Euro "
        "oder in der Währung des Hotels ({hotel}) anzeigen. Was ist Ihnen lieber?"
    ),
    "pt": (
        "Ainda não consigo mostrar os preços em {requested}. Posso mostrá-los em euros "
        "ou na moeda do hotel ({hotel}). Qual prefere?"
    ),
    "nl": (
        "Ik kan de prijzen nog niet in {requested} tonen. Ik kan ze in euro tonen, of "
        "in de valuta van het hotel ({hotel}). Wat heeft uw voorkeur?"
    ),
}

_UNSUPPORTED_NO_HOTEL = {
    "fr": (
        "Je ne peux pas encore afficher les prix en {requested}. Je peux vous les "
        "montrer en euros, ou dans la devise locale de chaque hôtel. Laquelle préférez-vous ?"
    ),
    "en": (
        "I can't show prices in {requested} yet. I can show them in euros, or in each "
        "hotel's local currency. Which would you prefer?"
    ),
    "es": (
        "Todavía no puedo mostrar los precios en {requested}. Puedo mostrártelos en "
        "euros o en la moneda local de cada hotel. ¿Cuál prefieres?"
    ),
    "it": (
        "Non posso ancora mostrare i prezzi in {requested}. Posso mostrarli in euro "
        "oppure nella valuta locale di ogni hotel. Quale preferisci?"
    ),
    "de": (
        "Ich kann die Preise noch nicht in {requested} anzeigen. Ich kann sie in Euro "
        "oder in der Landeswährung des jeweiligen Hotels anzeigen. Was ist Ihnen lieber?"
    ),
    "pt": (
        "Ainda não consigo mostrar os preços em {requested}. Posso mostrá-los em euros "
        "ou na moeda local de cada hotel. Qual prefere?"
    ),
    "nl": (
        "Ik kan de prijzen nog niet in {requested} tonen. Ik kan ze in euro tonen, of "
        "in de lokale valuta van elk hotel. Wat heeft uw voorkeur?"
    ),
}

_UNSUPPORTED_EUR_ONLY = {
    "fr": (
        "Je ne peux pas encore afficher les prix en {requested}. Ces hôtels facturent "
        "en euros, les prix affichés sont donc déjà dans leur devise."
    ),
    "en": (
        "I can't show prices in {requested} yet. These hotels charge in euros, so the "
        "prices shown are already in their own currency."
    ),
    "es": (
        "Todavía no puedo mostrar los precios en {requested}. Estos hoteles cobran en "
        "euros, así que los precios mostrados ya están en su moneda."
    ),
    "it": (
        "Non posso ancora mostrare i prezzi in {requested}. Questi hotel fatturano in "
        "euro, quindi i prezzi mostrati sono già nella loro valuta."
    ),
    "de": (
        "Ich kann die Preise noch nicht in {requested} anzeigen. Diese Hotels rechnen in "
        "Euro ab, die angezeigten Preise sind also bereits in ihrer Währung."
    ),
    "pt": (
        "Ainda não consigo mostrar os preços em {requested}. Estes hotéis cobram em "
        "euros, por isso os preços apresentados já estão na moeda deles."
    ),
    "nl": (
        "Ik kan de prijzen nog niet in {requested} tonen. Deze hotels rekenen af in "
        "euro, dus de getoonde prijzen zijn al in hun eigen valuta."
    ),
}

_NOTED = {
    HOTEL: {
        "fr": "C'est noté : j'afficherai les prix dans la devise de chaque hôtel. Où et quand souhaitez-vous réserver ?",
        "en": "Noted: I'll show prices in each hotel's own currency. Where and when would you like to book?",
        "es": "Anotado: mostraré los precios en la moneda de cada hotel. ¿Dónde y cuándo quieres reservar?",
        "it": "Ricevuto: mostrerò i prezzi nella valuta di ogni hotel. Dove e quando vuoi prenotare?",
        "de": "Notiert: Ich zeige die Preise in der Währung des jeweiligen Hotels an. Wo und wann möchten Sie buchen?",
        "pt": "Anotado: vou mostrar os preços na moeda de cada hotel. Onde e quando quer reservar?",
        "nl": "Genoteerd: ik toon de prijzen in de valuta van elk hotel. Waar en wanneer wilt u boeken?",
    },
    "EUR": {
        "fr": "C'est noté : les prix seront affichés en euros. Où et quand souhaitez-vous réserver ?",
        "en": "Noted: prices will be shown in euros. Where and when would you like to book?",
        "es": "Anotado: los precios se mostrarán en euros. ¿Dónde y cuándo quieres reservar?",
        "it": "Ricevuto: i prezzi saranno mostrati in euro. Dove e quando vuoi prenotare?",
        "de": "Notiert: Die Preise werden in Euro angezeigt. Wo und wann möchten Sie buchen?",
        "pt": "Anotado: os preços serão apresentados em euros. Onde e quando quer reservar?",
        "nl": "Genoteerd: de prijzen worden in euro getoond. Waar en wanneer wilt u boeken?",
    },
}


_ALREADY = {
    HOTEL: {
        "fr": "Les prix sont déjà affichés dans la devise de chaque hôtel.",
        "en": "Prices are already shown in each hotel's own currency.",
        "es": "Los precios ya se muestran en la moneda de cada hotel.",
        "it": "I prezzi sono già mostrati nella valuta di ogni hotel.",
        "de": "Die Preise werden bereits in der Währung des jeweiligen Hotels angezeigt.",
        "pt": "Os preços já são apresentados na moeda de cada hotel.",
        "nl": "De prijzen worden al in de valuta van elk hotel getoond.",
    },
    "EUR": {
        "fr": "Les prix sont déjà affichés en euros.",
        "en": "Prices are already shown in euros.",
        "es": "Los precios ya se muestran en euros.",
        "it": "I prezzi sono già mostrati in euro.",
        "de": "Die Preise werden bereits in Euro angezeigt.",
        "pt": "Os preços já são apresentados em euros.",
        "nl": "De prijzen worden al in euro getoond.",
    },
}


def already_message(mode: str | None, language: str) -> str:
    table = _ALREADY[HOTEL if mode == HOTEL else "EUR"]
    return table.get(language, table["en"])


def unsupported_currency_message(decision: CurrencyDecision, language: str) -> str:
    requested = decision.requested or ""
    currencies = [c for c in decision.hotel_currencies if c != "EUR"]
    if not decision.hotel_currencies:
        table = _UNSUPPORTED_NO_HOTEL
    elif not currencies:
        table = _UNSUPPORTED_EUR_ONLY
    else:
        table = _UNSUPPORTED
    template = table.get(language, table["en"])
    return template.format(requested=requested, hotel=", ".join(currencies))


def noted_message(mode: str | None, language: str) -> str:
    table = _NOTED[HOTEL if mode == HOTEL else "EUR"]
    return table.get(language, table["en"])
