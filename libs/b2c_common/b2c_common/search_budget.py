"""Requested search budget, independent of MCP's EUR-only cap and UI currency.

No FX, language heuristics or model calls. Semantics come from the existing
triage; code validates evidence/units and checks the same offer's indexed price.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .pricing import display_price_euro, display_price_hotel, minor_units


def _positive(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and 0 < amount <= 1_000_000_000 else None


def _amounts(text: str) -> set[Decimal]:
    """Literal numeric tokens, with a decimal comma accepted. No NLP matching."""
    found: set[Decimal] = set()
    token = ""
    for char in text + " ":
        if char in "0123456789.," or (char in "+-" and not token):
            token += char
        else:
            amount = _positive(token.strip(".,").replace(",", "."))
            if amount is not None:
                found.add(amount)
            token = ""
    return found


_DOLLAR_MARKETS = {"US": "USD", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "SG": "SGD", "HK": "HKD"}


def _literal_currency(evidence: str, proposed: str | None) -> tuple[str | None, str | None]:
    # Currency vocabulary is unit validation, not intent classification. Never
    # infer a currency from a number or assistant prose. ASCII ISO codes work
    # for all currencies, including ones without a translated name below.
    words = "".join(c if c.isalpha() else " " for c in evidence.casefold()).split()
    if proposed and proposed.casefold() in words:
        return proposed, None
    joined = " ".join(words)
    for phrase, code in (("us dollars", "USD"), ("us dollar", "USD"),
                         ("canadian dollars", "CAD"), ("australian dollars", "AUD"),
                         ("singapore dollars", "SGD"), ("hong kong dollars", "HKD")):
        if f" {phrase} " in f" {joined} ":
            return code, None
    if "€" in evidence or any(w in ("euro", "euros") for w in words):
        return "EUR", None
    if "£" in evidence or any(w in ("pound", "pounds", "sterling", "sterlinas", "sterline") for w in words):
        return "GBP", None
    if "$" in evidence or any(w in ("dollar", "dollars", "dólar", "dólares") for w in words):
        return None, "dollar_market"
    return None, "unspecified"



def currency_answer(message: str) -> dict | None:
    """A whole answer consisting only of a currency unit, not free-text intent.

    Used ONLY while the concierge awaits a budget currency. No numbers are
    extracted, no question/policy sentence is matched, and no consent is inferred.
    """
    label = " ".join(message.strip().strip(".?!").casefold().split())
    codes = set(_DOLLAR_MARKETS.values()) | {"EUR", "GBP", "CHF", "JPY", "CNY", "MXN", "BRL", "AED", "THB", "KWD", "SAR", "QAR", "INR"}
    if label.upper() in codes:
        return {"currency": label.upper()}
    labels = {"euro", "euros", "€", "pound", "pounds", "pounds sterling", "£",
              "dollar", "dollars", "$", "us dollar", "us dollars", "canadian dollars",
              "australian dollars", "singapore dollars", "hong kong dollars"}
    if label not in labels:
        return None
    code, basis = _literal_currency(label, None)
    return {"currency": code, **({"currency_basis": basis} if basis else {})}

def resolve_budget_currency(request: Any, country: str | None) -> Any:
    """Dollar symbol uses VERIFIED search country, never language/GPS/LLM guess.

    After resolution, the customer's unit is retained across later destinations.
    Unsupported/ambiguous dollar markets remain unknown and need clarification.
    """
    if not isinstance(request, dict) or request.get("currency_basis") != "dollar_market":
        return request
    code = _DOLLAR_MARKETS.get(country or "")
    if code is None:
        return request
    return {k: v for k, v in {**request, "currency": code}.items() if k != "currency_basis"}


def grounded_budget(value: Any, message: str) -> dict[str, Any] | None:
    """None=no accepted update, {}=explicit clear. Never keep user prose in state."""
    if not isinstance(value, dict):
        return None
    evidence = value.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip() or evidence.casefold() not in message.casefold():
        return None
    if value.get("clear") is True:
        return {} if value.get("amount") is None else None
    amount = _positive(value.get("amount"))
    if value.get("amount") is not None and (amount is None or amount not in _amounts(evidence)):
        return None
    currency = value.get("currency")
    if currency is not None and (
        not isinstance(currency, str) or len(currency) != 3
        or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in currency)
    ):
        return None
    unit = value.get("unit")
    if unit not in (None, "total", "hour", "person", "unknown"):
        return None
    currency, basis = _literal_currency(evidence, currency)
    if amount is None:
        # A short answer can supply just the missing currency/unit. It never
        # creates a budget by itself; merge_budget requires a saved amount.
        changes: dict[str, Any] = {}
        if currency or basis == "dollar_market":
            changes["currency"] = currency
            if basis:
                changes["currency_basis"] = basis
        if unit is not None:
            changes["unit"] = unit
        return changes or None
    if unit is None:
        return None
    result = {"amount": float(amount), "currency": currency, "unit": unit}
    if basis:
        result["currency_basis"] = basis
    return result


def merge_budget(previous: Any, update: dict, native_currency: str | None = None) -> dict | None:
    """Complete an existing user budget without borrowing assistant amounts."""
    if not update:
        return {}
    partial = "amount" not in update
    if partial and (not isinstance(previous, dict) or _positive(previous.get("amount")) is None):
        return None
    merged = {**previous, **update} if partial else dict(update)
    if partial and update.get("currency"):
        merged.pop("currency_basis", None)
    if merged.get("currency_basis") == "unspecified" and previous:
        if previous.get("currency"):
            merged["currency"] = previous["currency"]
            merged.pop("currency_basis", None)
        elif previous.get("currency_basis") == "dollar_market":
            merged["currency_basis"] = "dollar_market"
    fallback = previous.get("currency") if isinstance(previous, dict) else None
    fallback = fallback or native_currency
    valid_fallback = isinstance(fallback, str) and len(fallback) == 3 and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in fallback)
    if valid_fallback and (
        merged.get("currency_basis") == "unspecified"
        or (merged.get("currency_basis") == "dollar_market" and fallback in _DOLLAR_MARKETS.values())
    ):
        merged["currency"] = fallback
        merged.pop("currency_basis", None)
    return merged


def native_eur_cap(request: Any) -> float | None:
    if not isinstance(request, dict) or request.get("currency") != "EUR" or request.get("unit") != "total":
        return None
    amount = _positive(request.get("amount"))
    return float(amount) if amount is not None else None


def offer_within_budget(offer: dict, hotel: dict, request: dict) -> bool:
    """True only for a usable SAME-offer quote <= cap, in the requested currency.

    Prices follow the site's display-fee rule, shared with card normalization.
    This does not prove all optional extras are included in that quote.
    """
    amount = _positive(request.get("amount"))
    currency = request.get("currency")
    if amount is None or not currency or request.get("unit") != "total":
        return False
    if currency == "EUR":
        price = display_price_euro(offer, hotel)
    elif offer.get("hotelCurrency") == currency:
        price = display_price_hotel(offer, hotel)
    else:
        return False
    # The MCP contract provides minor-unit integer quotes. Reject NaN, booleans,
    # negative/absent quotes rather than manufacture an affordable offer.
    if isinstance(price, bool) or not isinstance(price, int) or price < 0:
        return False
    return Decimal(price) <= amount * (10 ** minor_units(currency))


_QUESTIONS = {
    "fr": "Pour vérifier le budget sans convertir ni supposer un tarif horaire, quel est votre plafond total pour la formule, avec sa devise (par exemple 100 USD au total) ?",
    "en": "To check your budget without assuming an exchange rate or hourly pricing, what is your maximum total for the package, including its currency (for example 100 USD total)?",
    "es": "Para comprobar el presupuesto sin suponer un cambio de moneda ni una tarifa por hora, ¿cuál es el máximo total para el paquete, con su moneda (por ejemplo 100 USD en total)?",
    "it": "Per verificare il budget senza ipotizzare un cambio o una tariffa oraria, qual è il massimo totale per il pacchetto, con la valuta (per esempio 100 USD totali)?",
    "de": "Welchen Gesamtbetrag samt Währung möchten Sie höchstens für das Paket zahlen (zum Beispiel insgesamt 100 USD)? Ich nehme keinen Wechselkurs oder Stundentarif an.",
    "pt": "Para verificar o orçamento sem presumir câmbio ou preço por hora, qual é o limite total para o pacote, com a moeda (por exemplo 100 USD no total)?",
    "nl": "Wat is uw maximale totaalbedrag voor het pakket, inclusief valuta (bijvoorbeeld 100 USD totaal)? Ik ga niet uit van een wisselkoers of uurtarief.",
}


_CURRENCY_QUESTIONS = {
    "fr": "Dans quelle devise est votre budget maximum de {amount} au total ?",
    "en": "Which currency is your maximum total budget of {amount} in?",
    "es": "¿En qué moneda está su presupuesto máximo total de {amount}?",
    "it": "In quale valuta è il suo budget massimo totale di {amount}?",
    "de": "In welcher Währung gilt Ihr maximales Gesamtbudget von {amount}?",
    "pt": "Em que moeda está o seu orçamento máximo total de {amount}?",
    "nl": "In welke valuta is uw maximale totaalbudget van {amount}?",
}


def budget_question(request: Any, language: str, *, after_search: bool = False) -> str | None:
    unresolved = request and not request.get("currency")
    can_resolve_at_geocode = request and request.get("currency_basis") == "dollar_market" and not after_search
    if request and request.get("unit") != "total":
        return _QUESTIONS.get(language, _QUESTIONS["en"])
    if unresolved and not can_resolve_at_geocode:
        return _CURRENCY_QUESTIONS.get(language, _CURRENCY_QUESTIONS["en"]).format(amount=f"{request['amount']:g}")
    return None


_NOTICES = {
    "fr": ("Budget {amount} {currency} au total : contrôle sur le prix affiché de la même formule, parmi les offres récupérées. Les suppléments éventuels restent à vérifier.", "Parmi les offres récupérées, aucune formule n'a un prix vérifiable de {amount} {currency} maximum. Cela ne prouve pas l'absence d'autres offres dans ce budget."),
    "en": ("Total budget {amount} {currency}: checked against the same package's displayed price among retrieved offers. Any extras still need checking.", "Among the retrieved offers, no package has a verifiable price at or below {amount} {currency}. This does not establish that no other offers fit the budget."),
    "es": ("Presupuesto total {amount} {currency}: comprobado con el precio mostrado del mismo paquete entre las ofertas recuperadas. Los extras deben verificarse.", "Entre las ofertas recuperadas, ningún paquete tiene un precio verificable de hasta {amount} {currency}. Esto no demuestra que no existan otras ofertas dentro del presupuesto."),
    "it": ("Budget totale {amount} {currency}: verificato sul prezzo mostrato dello stesso pacchetto tra le offerte recuperate. Gli extra restano da verificare.", "Tra le offerte recuperate, nessun pacchetto ha un prezzo verificabile entro {amount} {currency}. Questo non dimostra l'assenza di altre offerte nel budget."),
    "de": ("Gesamtbudget {amount} {currency}: anhand des angezeigten Preises desselben Pakets unter den abgerufenen Angeboten geprüft. Zusatzkosten bleiben zu prüfen.", "Unter den abgerufenen Angeboten hat kein Paket einen verifizierbaren Preis bis {amount} {currency}. Andere passende Angebote sind damit nicht ausgeschlossen."),
    "pt": ("Orçamento total {amount} {currency}: verificado no preço apresentado do mesmo pacote entre as ofertas obtidas. Extras ainda precisam ser verificados.", "Entre as ofertas obtidas, nenhum pacote tem preço verificável até {amount} {currency}. Isso não prova que não existam outras ofertas no orçamento."),
    "nl": ("Totaalbudget {amount} {currency}: gecontroleerd op de getoonde prijs van hetzelfde pakket binnen de opgehaalde aanbiedingen. Extra kosten moeten nog worden gecontroleerd.", "Binnen de opgehaalde aanbiedingen heeft geen pakket een controleerbare prijs tot {amount} {currency}. Dit sluit andere passende aanbiedingen niet uit."),
}


def budget_notice(request: dict, has_results: bool, language: str) -> str:
    table = _NOTICES.get(language, _NOTICES["en"])
    return table[0 if has_results else 1].format(amount=f"{request['amount']:g}", currency=request.get("currency") or "?")
