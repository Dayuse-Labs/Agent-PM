"""Relative price requests grounded in previously displayed, indexed offers.

The existing triage labels intent; code owns the monetary reference. This is
separate from a user-stated numerical budget and never computes an FX rate.
"""
from decimal import Decimal
from typing import Any

from .pricing import minor_units
from .search_budget import offer_within_budget


def grounded_price_comparison(value: Any, message: str) -> str | None:
    if not isinstance(value, dict) or value.get("value") not in {"lower", "clear"}:
        return None
    evidence = value.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip() or evidence.casefold() not in message.casefold():
        return None
    return value["value"]


def offer_totals(offer: dict) -> dict[str, int]:
    quotes = {"EUR": offer.get("priceEuroWithBookingFees")}
    code = offer.get("hotelCurrency")
    if isinstance(code, str) and code != "EUR" and len(code) == 3 and code.isascii() and code.isupper() and code.isalpha():
        quotes[code] = offer.get("hotelPriceWithBookingFees")
    return {code: value for code, value in quotes.items()
            if isinstance(value, int) and not isinstance(value, bool) and value > 0}


def cheaper_reference(results: list[dict] | None, display_mode: str | None) -> dict | None:
    rows = [r for r in results or [] if isinstance(r, dict)]
    if not rows or any(not r.get("offer_id") or not r.get("offer_date") for r in rows):
        return None
    # EUR is the B2C default. HOTEL requests must share one indexed currency;
    # unlike currencies cannot be compared by their numeric amounts.
    currency = display_mode or "EUR"
    if currency == "HOTEL":
        codes = {r.get("hotel_currency_code") for r in rows}
        if len(codes) != 1:
            return None
        only_code = next(iter(codes))
        if not isinstance(only_code, str):
            return None
        currency = only_code
    if not isinstance(currency, str):
        return None
    priced = []
    for row in rows:
        total = (row.get("offer_totals") or {}).get(currency)
        if not isinstance(total, int) or isinstance(total, bool) or total <= 1:
            return None  # An unpriced card prevents a claim about the cheapest shown.
        priced.append((total, row))
    amount, row = min(priced, key=lambda p: p[0])
    return {"relation": "lower", "currency": currency, "reference_minor": amount,
            "reference_offer_id": row["offer_id"], "reference_date": row["offer_date"]}


def comparison_budget(comparison: Any) -> dict | None:
    if not isinstance(comparison, dict) or comparison.get("relation") != "lower":
        return None
    amount, code = comparison.get("reference_minor"), comparison.get("currency")
    if (isinstance(amount, bool) or not isinstance(amount, int) or amount <= 1
            or not isinstance(code, str) or len(code) != 3 or not code.isascii()
            or not code.isalpha() or not code.isupper()):
        return None
    # Strictly cheaper, down to the indexed currency's minor unit.
    return {"amount": float(Decimal(amount - 1) / (10 ** minor_units(code))),
            "currency": code, "unit": "total"}


def offer_below_reference(offer: dict, hotel: dict, comparison: dict) -> bool:
    cap = comparison_budget(comparison)
    return cap is not None and offer_within_budget(offer, hotel, cap)


def comparison_context(comparison: dict, results: list[dict]) -> str:
    code = comparison["currency"]
    amount = Decimal(comparison["reference_minor"]) / (10 ** minor_units(code))
    verified = [total for row in results if isinstance(row, dict)
                for total in [(row.get("offer_totals") or {}).get(code)]
                if isinstance(total, int) and not isinstance(total, bool)
                and 0 < total < comparison["reference_minor"]]
    if verified:
        lowest = Decimal(min(verified)) / (10 ** minor_units(code))
        outcome = (f"CURRENT VERIFIED OUTCOME: {len(verified)} displayed offers are strictly cheaper. "
                   f"The lowest verified total is {lowest} {code}, versus the PREVIOUS "
                   f"reference {amount} {code}: saving {amount - lowest} {code}. "
                   "A cheaper offer WAS found; do not claim otherwise. This is the lowest "
                   "in the displayed sample, not a claim about all inventory. ")
    elif not results:
        outcome = "CURRENT VERIFIED OUTCOME: no cheaper offer verified in the retrieved sample. "
    else:
        outcome = "CURRENT VERIFIED OUTCOME: displayed quotes do not prove a cheaper total in the comparison currency. "
    return (f"RELATIVE PRICE REQUEST: seek a total strictly below {amount} {code}, "
            "the lowest verified total among the previous offers, including booking fees. "
            + outcome +
            "This is an offer comparison, not a numeric budget stated by the customer. "
            "Do not describe equal or higher prices as cheaper. "
            "Keep the other constraints; ask before relaxing them.")


_REFERENCE_QUESTIONS = {
    "fr": "Je n’ai pas de prix total vérifié pour comparer les offres précédentes. Quel montant maximum, avec sa devise, souhaitez-vous ?",
    "en": "I don’t have a verified total to compare the previous offers. What maximum amount and currency would you like?",
    "es": "No tengo un total verificado para comparar las ofertas anteriores. ¿Cuál es su importe máximo y moneda?",
    "it": "Non ho un totale verificato per confrontare le offerte precedenti. Qual è il suo importo massimo e la valuta?",
    "de": "Mir fehlt ein verifizierter Gesamtpreis der vorherigen Angebote. Welchen Höchstbetrag und welche Währung wünschen Sie?",
    "pt": "Não tenho um total verificado para comparar as ofertas anteriores. Qual é o valor máximo e a moeda desejados?",
    "nl": "Ik heb geen geverifieerd totaalbedrag om de eerdere aanbiedingen te vergelijken. Wat is uw maximumbedrag en valuta?",
}


def reference_question(language: str) -> str:
    return _REFERENCE_QUESTIONS.get(language, _REFERENCE_QUESTIONS["en"])
