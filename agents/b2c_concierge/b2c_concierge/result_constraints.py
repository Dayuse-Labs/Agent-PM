"""Compare the displayed offer to explicit constraints before synthesis."""
from __future__ import annotations

from .profile import SessionProfile


def _minutes(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 2 or not all(x.isascii() and x.isdecimal() for x in parts):
        return None
    h, m = map(int, parts)
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def annotate_constraints(response: dict, profile: SessionProfile) -> list[str]:
    warnings: set[str] = set()
    start, end = _minutes(profile.timeslot_start), _minutes(profile.timeslot_end)
    for hotel in response.get("results") or []:
        if not isinstance(hotel, dict):
            continue
        mismatches = []
        if profile.budget_request_source == "explicit" and profile.budget_max is not None:
            cents = hotel.get("price_eur_cents")
            if isinstance(cents, (int, float)) and not isinstance(cents, bool) and cents > profile.budget_max * 100:
                mismatches.append("budget")
        if profile.timeslot_request_source == "explicit" and (start is not None or end is not None):
            slots = hotel.get("timeslots") or []
            parsed = [(_minutes(s.get("start")), _minutes(s.get("end"))) for s in slots if isinstance(s, dict)]
            known = [(a, b) for a, b in parsed if a is not None and b is not None]
            if known and not any((start is None or a <= start < b) and (end is None or a < end <= b) for a, b in known):
                mismatches.append("hours")
        if mismatches:
            hotel["constraint_mismatches"] = mismatches
            warnings.update(mismatches)
    response["constraint_warnings"] = sorted(warnings)
    return sorted(warnings)


_NOTICES = {
    "fr": "Attention : certaines offres affichées ne respectent pas votre budget ou vos horaires. Ce sont des alternatives ; vérifiez le prix et le créneau de chaque offre.",
    "en": "Some displayed offers do not meet your budget or requested hours. These are alternatives; check each offer's price and time slot.",
    "es": "Algunas ofertas no cumplen tu presupuesto o el horario solicitado. Son alternativas; revisa el precio y el horario de cada oferta.",
    "it": "Alcune offerte non rispettano il budget o gli orari richiesti. Sono alternative: verifica il prezzo e la fascia oraria di ciascuna offerta.",
    "de": "Einige Angebote entsprechen nicht deinem Budget oder den gewünschten Zeiten. Es sind Alternativen; prüfe Preis und Zeitfenster jedes Angebots.",
    "pt": "Algumas ofertas não correspondem ao seu orçamento ou horário solicitado. São alternativas; verifique o preço e o horário de cada oferta.",
    "nl": "Sommige aanbiedingen passen niet bij je budget of gewenste tijden. Dit zijn alternatieven; controleer de prijs en tijden van elke aanbieding.",
}


def constraint_notice(response: dict, language: str) -> str:
    return _NOTICES.get(language, _NOTICES["en"]) if response.get("constraint_warnings") else ""
