"""What the search relaxed, said in code (point 3, prod 2026-10-27/28).

The hotel-search leaf rescues an empty first page step by step (slot, an amenity
that was not a must-have, a wider ring, the next day — `relaxation.py` of the
leaf) and applies the user's request to loosen the search (« retirer un
filtre », « augmenter le budget »). Its DataPart says what it did, under
`relaxation`. This module writes it down before the synthesis, the same way the
« aucune offre » sentence is written (`no_offers.py`): the user reads that
nothing matched everything, and what was relaxed to show these hotels — never a
model's guess at it. The recovery chips are the concierge's own labels: a click
on « augmenter le budget » / « retirer un filtre » reaches the leaf as data
(`query_params.relax`), like « élargir la zone » (`clicked_widen_chip`).
"""
from __future__ import annotations

from typing import Any

from .date_format import format_date_human
from .no_offers import _AMENITY, _join, _lang, no_offers_line
from .profile import _RECOVERY_SUGGESTIONS

#: `_RECOVERY_SUGGESTIONS` order: budget, zone (`clicked_widen_chip`), filter.
_CHIP_ACTIONS = {0: "budget", 2: "filters"}


def clicked_relax_chip(message: str) -> str | None:
    """« augmenter le budget » / « retirer un filtre », clicked or typed as the
    whole message: one of the concierge's own chip labels, in any of the 7
    languages. The words of the user are never read here — only whether the
    message IS a label the concierge offered."""
    text = (message or "").strip().lower()
    for labels in _RECOVERY_SUGGESTIONS.values():
        for index, action in _CHIP_ACTIONS.items():
            if text == labels[index].lower():
                return action
    return None


_RELAXED_LEAD: dict[str, str] = {
    "fr": "Voici les offres les plus proches, en assouplissant {items}.",
    "en": "Here are the closest offers, relaxing {items}.",
    "es": "Estas son las ofertas más cercanas, flexibilizando {items}.",
    "it": "Ecco le offerte più vicine, allentando {items}.",
    "de": "Hier die nächstgelegenen Angebote, mit gelockerten Kriterien: {items}.",
    "pt": "Estas são as ofertas mais próximas, flexibilizando {items}.",
    "nl": "Dit zijn de dichtstbijzijnde aanbiedingen, met versoepeld: {items}.",
}
_TIMESLOT: dict[str, str] = {
    "fr": "le créneau horaire", "en": "the time slot", "es": "la franja horaria",
    "it": "la fascia oraria", "de": "das Zeitfenster", "pt": "o horário", "nl": "het tijdslot",
}
_AMENITIES: dict[str, str] = {
    "fr": "le critère {names}", "en": "the {names} requirement", "es": "el criterio {names}",
    "it": "il criterio {names}", "de": "das Kriterium {names}", "pt": "o critério {names}",
    "nl": "het criterium {names}",
}
_RADIUS: dict[str, str] = {
    "fr": "la zone (jusqu'à {km} km)", "en": "the area (up to {km} km)", "es": "la zona (hasta {km} km)",
    "it": "la zona (fino a {km} km)", "de": "den Umkreis (bis {km} km)", "pt": "a zona (até {km} km)",
    "nl": "het gebied (tot {km} km)",
}
_NEXT_DAY: dict[str, str] = {
    "fr": "la date ({day})", "en": "the date ({day})", "es": "la fecha ({day})", "it": "la data ({day})",
    "de": "das Datum ({day})", "pt": "a data ({day})", "nl": "de datum ({day})",
}
_REMOVED_AMENITIES: dict[str, str] = {
    "fr": "J'ai retiré le filtre {names}.", "en": "I removed the {names} filter.",
    "es": "He quitado el filtro {names}.", "it": "Ho rimosso il filtro {names}.",
    "de": "Ich habe den Filter {names} entfernt.", "pt": "Retirei o filtro {names}.",
    "nl": "Ik heb het filter {names} verwijderd.",
}
_REMOVED_TIMESLOT: dict[str, str] = {
    "fr": "J'ai retiré le créneau horaire.", "en": "I removed the time slot.",
    "es": "He quitado la franja horaria.", "it": "Ho rimosso la fascia oraria.",
    "de": "Ich habe das Zeitfenster entfernt.", "pt": "Retirei o horário.",
    "nl": "Ik heb het tijdslot verwijderd.",
}
_REMOVED_STANDING: dict[str, str] = {
    "fr": "J'ai retiré le filtre 4-5 étoiles.", "en": "I removed the 4-5 star filter.",
    "es": "He quitado el filtro de 4-5 estrellas.", "it": "Ho rimosso il filtro 4-5 stelle.",
    "de": "Ich habe den 4-5-Sterne-Filter entfernt.", "pt": "Retirei o filtro de 4-5 estrelas.",
    "nl": "Ik heb het 4-5 sterrenfilter verwijderd.",
}
_NOTHING_TO_REMOVE: dict[str, str] = {
    "fr": "Aucun filtre n'était appliqué à cette recherche.",
    "en": "No filter was applied to this search.",
    "es": "No había ningún filtro aplicado a esta búsqueda.",
    "it": "Nessun filtro era applicato a questa ricerca.",
    "de": "Für diese Suche war kein Filter gesetzt.",
    "pt": "Nenhum filtro estava aplicado a esta pesquisa.",
    "nl": "Er was geen filter op deze zoekopdracht toegepast.",
}
_BUDGET_RAISED: dict[str, str] = {
    "fr": "J'ai relevé le budget de {old} à {new} {currency} pour cette recherche.",
    "en": "I raised the budget from {old} to {new} {currency} for this search.",
    "es": "He subido el presupuesto de {old} a {new} {currency} para esta búsqueda.",
    "it": "Ho alzato il budget da {old} a {new} {currency} per questa ricerca.",
    "de": "Ich habe das Budget für diese Suche von {old} auf {new} {currency} erhöht.",
    "pt": "Aumentei o orçamento de {old} para {new} {currency} nesta pesquisa.",
    "nl": "Ik heb het budget voor deze zoekopdracht verhoogd van {old} naar {new} {currency}.",
}
_NO_BUDGET: dict[str, str] = {
    "fr": "Aucun plafond de prix n'était appliqué à cette recherche.",
    "en": "No price cap was applied to this search.",
    "es": "No había ningún límite de precio en esta búsqueda.",
    "it": "Nessun limite di prezzo era applicato a questa ricerca.",
    "de": "Für diese Suche galt keine Preisobergrenze.",
    "pt": "Nenhum limite de preço estava aplicado a esta pesquisa.",
    "nl": "Er gold geen prijslimiet voor deze zoekopdracht.",
}


def _names(keys: Any, lang: str) -> str:
    labels = [_AMENITY[lang].get(key, key.replace("_", " ")) for key in keys or [] if isinstance(key, str)]
    return _join(labels, lang) if labels else ""


def _km(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return f"{float(value):g}"
    return None


def _request_lines(request: Any, lang: str) -> list[str]:
    if not isinstance(request, dict):
        return []
    lines: list[str] = []
    removed = request.get("removed") or []
    if "amenities" in removed:
        names = _names(request.get("amenities"), lang)
        if names:
            lines.append(_REMOVED_AMENITIES[lang].format(names=names))
    if "timeslot" in removed:
        lines.append(_REMOVED_TIMESLOT[lang])
    if "standing" in removed:
        lines.append(_REMOVED_STANDING[lang])
    if request.get("nothing_to_remove"):
        lines.append(_NOTHING_TO_REMOVE[lang])
    budget = request.get("budget")
    if isinstance(budget, dict) and _km(budget.get("from")) and _km(budget.get("to")):
        lines.append(_BUDGET_RAISED[lang].format(
            old=_km(budget["from"]), new=_km(budget["to"]), currency=budget.get("currency") or "EUR",
        ))
    elif request.get("no_budget"):
        lines.append(_NO_BUDGET[lang])
    return lines


def relaxation_line(relaxation: Any, search_context: Any, language: str) -> str:
    """« Aucune offre à Dublin le jeudi 29 octobre 2026, avec jacuzzi. Voici
    les offres les plus proches, en assouplissant le critère jacuzzi. » — the
    search that came back empty, cited as it ran, then what was relaxed; and
    what the user's request to loosen it changed. Empty when nothing was."""
    if not isinstance(relaxation, dict):
        return ""
    lang = _lang(language)
    lines = _request_lines(relaxation.get("request"), lang)
    steps = [step for step in relaxation.get("steps") or [] if isinstance(step, str)]
    items: list[str] = []
    for step in steps:
        if step == "timeslot":
            items.append(_TIMESLOT[lang])
        elif step == "amenities":
            names = _names(relaxation.get("amenities"), lang)
            if names:
                items.append(_AMENITIES[lang].format(names=names))
        elif step == "radius" and _km(relaxation.get("radius_km")):
            items.append(_RADIUS[lang].format(km=_km(relaxation["radius_km"])))
        elif step == "next_day" and isinstance(relaxation.get("offered_date"), str):
            items.append(_NEXT_DAY[lang].format(day=format_date_human(relaxation["offered_date"], lang)))
    if items:
        # The search that came back empty, on the day it ran (the cards may
        # now be the next day's: the context carries the day served).
        context = dict(search_context) if isinstance(search_context, dict) else {}
        if isinstance(relaxation.get("searched_date"), str):
            context["date"] = relaxation["searched_date"]
        empty = no_offers_line(context, lang) if context else ""
        lines.append(" ".join(part for part in (empty, _RELAXED_LEAD[lang].format(items=_join(items, lang))) if part))
    return "\n\n".join(lines)


def relaxation_note(relaxation: Any) -> str:
    """The same facts for the synthesis (its COMPLETED block): the cards come
    from a relaxed search, so no reply may present them as matching
    everything asked."""
    if not isinstance(relaxation, dict):
        return ""
    bits: list[str] = []
    steps = [step for step in relaxation.get("steps") or [] if isinstance(step, str)]
    if steps:
        bits.append(
            "NO offer matched everything asked: every card comes from a relaxed search ("
            + ", ".join(steps)
            + "). Your reply comes right after a sentence saying so: never present a card as "
            "matching the relaxed criteria."
        )
    request = relaxation.get("request")
    if isinstance(request, dict) and request:
        bits.append(
            "The user asked to loosen the search; the sentence before your reply says what "
            "changed (or that there was nothing to loosen). Do not say you cannot change it."
        )
    return " ".join(bits)
