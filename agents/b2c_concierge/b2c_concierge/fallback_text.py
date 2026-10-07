"""The text served when the synthesis produced nothing usable (mcp-dayuse#8).

The leaf's outcome line is code-built and grounded, but it was written for
the synthesis to read, not for the user: it carries ISO dates ("Recherche
effectuée pour le 2026-09-30.") and none of the disclosures the synthesis
path adds. QA trace 62207822 (San Francisco, "parking et piscine") served it
verbatim: ISO date, and no word about the parking filter that never ran.

`synthesis_fallback_text` is that same line made presentable, in code:
dates written out, plus the deterministic reserves that do not need an LLM —
auto-widened budget, unfilterable amenity, currency.
"""
from __future__ import annotations

import re
from typing import Any

from .currency_guard import enforce_currency_disclosure
from .date_format import humanize_iso_dates

_WIDEN_LINE: dict[str, str] = {
    "fr": "Le budget a été élargi automatiquement de {from_} à {to} après plusieurs recherches sans résultat.",
    "en": "The budget was automatically raised from {from_} to {to} after several searches with no results.",
    "es": "El presupuesto se amplió automáticamente de {from_} a {to} tras varias búsquedas sin resultados.",
    "it": "Il budget è stato aumentato automaticamente da {from_} a {to} dopo diverse ricerche senza risultati.",
    "de": "Das Budget wurde nach mehreren Suchen ohne Ergebnis automatisch von {from_} auf {to} erhöht.",
    "pt": "O orçamento foi aumentado automaticamente de {from_} para {to} após várias pesquisas sem resultados.",
    "nl": "Het budget is automatisch verhoogd van {from_} naar {to} na meerdere zoekopdrachten zonder resultaat.",
}

# Parking cannot be filtered on (equipment_ids.py: its variants would be
# AND-ed by the MCP), so a parking request always runs unfiltered.
_PARKING_RE = re.compile(
    r"\b(parking|parkings|garage|stationnement|aparcamiento|estacionamiento|parcheggio"
    r"|parkplatz|parkplätze|parkplatze|estacionamento|parkeren|parkeerplaats)\b",
    re.IGNORECASE,
)

_PARKING_LINE: dict[str, str] = {
    "fr": "Je n'ai pas pu filtrer les résultats sur le parking : vérifiez-le sur la fiche de l'hôtel.",
    "en": "I couldn't filter the results on parking: please check it on the hotel page.",
    "es": "No he podido filtrar los resultados por aparcamiento: compruébalo en la ficha del hotel.",
    "it": "Non ho potuto filtrare i risultati per parcheggio: verificalo sulla scheda dell'hotel.",
    "de": "Ich konnte die Ergebnisse nicht nach Parkplatz filtern: Bitte prüfen Sie das auf der Hotelseite.",
    "pt": "Não consegui filtrar os resultados por estacionamento: verifique na página do hotel.",
    "nl": "Ik kon de resultaten niet filteren op parkeren: controleer dit op de hotelpagina.",
}


def _pick(table: dict[str, str], language: str) -> str:
    return table.get(language, table["en"])


def enforce_parking_reserve(text: str, message: str, language: str) -> tuple[str, bool]:
    """Appends the parking reserve when the message asks for parking — in
    code, on the synthesis path too (mcp-dayuse#4: "parking et piscine"
    answered "tous avec piscine" and said nothing about the parking).
    Returns (text, appended); never appended twice."""
    if not _PARKING_RE.search(message or ""):
        return text, False
    line = _pick(_PARKING_LINE, language)
    if line in text:
        return text, False
    return f"{text.rstrip()}\n\n{line}" if text.strip() else line, True


def _eur(amount: Any, language: str) -> str:
    """Budgets are EUR amounts (`profile.budget_max`)."""
    value = f"{float(amount):g}"
    return f"€{value}" if language == "en" else f"{value} €"


def synthesis_fallback_text(
    leaf_text: str,
    *,
    message: str,
    language: str,
    widen: dict[str, Any] | None,
    currency_note: str,
) -> str:
    """The leaf's outcome line, presentable without an LLM. Empty in → empty
    out: the caller's degraded template handles a text-less leaf."""
    text, _ = humanize_iso_dates(leaf_text.strip(), language)
    if not text:
        return ""
    lines = [text]
    if widen and widen.get("from") is not None and widen.get("to") is not None:
        lines.append(_pick(_WIDEN_LINE, language).format(
            from_=_eur(widen["from"], language), to=_eur(widen["to"], language)
        ))
    text, _ = enforce_parking_reserve("\n\n".join(lines), message, language)
    text, _ = enforce_currency_disclosure(text, currency_note, language)
    return text
