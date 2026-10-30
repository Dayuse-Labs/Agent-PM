"""The "no offers" sentence, written in code from the search the leaf actually
ran (mcp-dayuse#5, decision Mathias 2026-10-06).

Left to the synthesis, an empty state cited what the model remembered of the
request: "Gare du Nord" and the 7h–9h window vanished, the amenities became
"les équipements demandés". The leaf's `search_context` is the executed search
(place, served day, window or daypart, budget, applied amenities, party size);
this sentence restates it word for word, and the synthesis only adds a next step.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from b2c_common.timeslot import parse_hhmm, requested_hours

from .date_format import format_date_human

_LEAD: dict[str, str] = {
    "fr": "Aucune offre {place}",
    "en": "No offers {place}",
    "es": "Ninguna oferta {place}",
    "it": "Nessuna offerta {place}",
    "de": "Keine Angebote {place}",
    "pt": "Nenhuma oferta {place}",
    "nl": "Geen aanbiedingen {place}",
}
# PORT1 slice 3: a typed budget is a fee-inclusive total in its own currency.
_TOTAL_BUDGET: dict[str, str] = {
    "fr": "avec un total maximum de {amount} {currency}, frais de réservation compris",
    "en": "with a total at or below {amount} {currency}, including booking fees",
    "es": "con un total máximo de {amount} {currency}, incluidos los gastos de reserva",
    "it": "con un totale massimo di {amount} {currency}, incluse le spese di prenotazione",
    "de": "mit einem Gesamtpreis bis {amount} {currency} einschließlich Buchungsgebühren",
    "pt": "com um total máximo de {amount} {currency}, incluindo taxas de reserva",
    "nl": "met een totaal tot {amount} {currency}, inclusief boekingskosten",
}
_PLACE: dict[str, str] = {
    "fr": "à {}", "en": "in {}", "es": "en {}", "it": "a {}", "de": "in {}", "pt": "em {}", "nl": "in {}",
}
_AROUND: dict[str, str] = {
    "fr": "autour de {}", "en": "around {}", "es": "cerca de {}", "it": "vicino a {}",
    "de": "in der Nähe von {}", "pt": "perto de {}", "nl": "in de buurt van {}",
}
_ON: dict[str, str] = {
    "fr": "le {}", "en": "on {}", "es": "el {}", "it": "il {}", "de": "am {}", "pt": "em {}", "nl": "op {}",
}
_WINDOW: dict[str, str] = {
    "fr": "de {}h à {}h", "en": "from {}:00 to {}:00", "es": "de {}:00 a {}:00", "it": "dalle {} alle {}",
    "de": "von {} bis {} Uhr", "pt": "das {}h às {}h", "nl": "van {}.00 tot {}.00 uur",
}
_FROM: dict[str, str] = {
    "fr": "à partir de {}h", "en": "from {}:00", "es": "desde las {}:00", "it": "dalle {}",
    "de": "ab {} Uhr", "pt": "a partir das {}h", "nl": "vanaf {}.00 uur",
}
_UNTIL: dict[str, str] = {
    "fr": "jusqu'à {}h", "en": "until {}:00", "es": "hasta las {}:00", "it": "fino alle {}",
    "de": "bis {} Uhr", "pt": "até às {}h", "nl": "tot {}.00 uur",
}
_DAYPART: dict[str, dict[str, str]] = {
    "fr": {"morning": "le matin", "afternoon": "l'après-midi", "evening": "en soirée"},
    "en": {"morning": "in the morning", "afternoon": "in the afternoon", "evening": "in the evening"},
    "es": {"morning": "por la mañana", "afternoon": "por la tarde", "evening": "por la noche"},
    "it": {"morning": "la mattina", "afternoon": "il pomeriggio", "evening": "la sera"},
    "de": {"morning": "am Vormittag", "afternoon": "am Nachmittag", "evening": "am Abend"},
    "pt": {"morning": "de manhã", "afternoon": "à tarde", "evening": "à noite"},
    "nl": {"morning": "'s ochtends", "afternoon": "'s middags", "evening": "'s avonds"},
}
_BUDGET: dict[str, str] = {
    "fr": "à moins de {}", "en": "under {}", "es": "por menos de {}", "it": "sotto i {}",
    "de": "unter {}", "pt": "abaixo de {}", "nl": "onder {}",
}
_WITH: dict[str, str] = {
    "fr": "avec {}", "en": "with {}", "es": "con {}", "it": "con {}", "de": "mit {}", "pt": "com {}", "nl": "met {}",
}
_AND: dict[str, str] = {"fr": "et", "en": "and", "es": "y", "it": "e", "de": "und", "pt": "e", "nl": "en"}
# « très classe » (the leaf's `standing`, mapped to 4- and 5-star hotels).
_UPSCALE: dict[str, str] = {
    "fr": "en hôtel 4 ou 5 étoiles", "en": "at a 4- or 5-star hotel", "es": "en un hotel de 4 o 5 estrellas",
    "it": "in un hotel a 4 o 5 stelle", "de": "in einem 4- oder 5-Sterne-Hotel",
    "pt": "em hotel de 4 ou 5 estrelas", "nl": "in een 4- of 5-sterrenhotel",
}
_ADULTS: dict[str, str] = {
    "fr": "pour {} adultes", "en": "for {} adults", "es": "para {} adultos", "it": "per {} adulti",
    "de": "für {} Erwachsene", "pt": "para {} adultos", "nl": "voor {} volwassenen",
}
# The leaf's amenity keys (hotel_search_agent.equipment_ids.EQUIPMENT_IDS).
_AMENITY: dict[str, dict[str, str]] = {
    "fr": {"indoor_pool": "piscine intérieure", "pool": "piscine", "spa": "spa", "gym": "salle de sport", "jacuzzi": "jacuzzi", "sauna": "sauna",
           "restaurant": "restaurant", "breakfast": "petit-déjeuner", "pet_friendly": "animaux acceptés",
           "shuttle": "navette aéroport"},
    "en": {"indoor_pool": "an indoor pool", "pool": "a pool", "spa": "a spa", "gym": "a gym", "jacuzzi": "a hot tub", "sauna": "a sauna",
           "restaurant": "a restaurant", "breakfast": "breakfast", "pet_friendly": "pets allowed",
           "shuttle": "an airport shuttle"},
    "es": {"indoor_pool": "piscina cubierta", "pool": "piscina", "spa": "spa", "gym": "gimnasio", "jacuzzi": "jacuzzi", "sauna": "sauna",
           "restaurant": "restaurante", "breakfast": "desayuno", "pet_friendly": "mascotas admitidas",
           "shuttle": "traslado al aeropuerto"},
    "it": {"indoor_pool": "piscina coperta", "pool": "piscina", "spa": "spa", "gym": "palestra", "jacuzzi": "idromassaggio", "sauna": "sauna",
           "restaurant": "ristorante", "breakfast": "colazione", "pet_friendly": "animali ammessi",
           "shuttle": "navetta aeroportuale"},
    "de": {"indoor_pool": "Hallenbad", "pool": "Pool", "spa": "Spa", "gym": "Fitnessraum", "jacuzzi": "Whirlpool", "sauna": "Sauna",
           "restaurant": "Restaurant", "breakfast": "Frühstück", "pet_friendly": "Haustiere erlaubt",
           "shuttle": "Flughafenshuttle"},
    "pt": {"indoor_pool": "piscina coberta", "pool": "piscina", "spa": "spa", "gym": "academia", "jacuzzi": "jacuzzi", "sauna": "sauna",
           "restaurant": "restaurante", "breakfast": "café da manhã", "pet_friendly": "animais permitidos",
           "shuttle": "transfer para o aeroporto"},
    "nl": {"indoor_pool": "binnenzwembad", "pool": "zwembad", "spa": "spa", "gym": "fitnessruimte", "jacuzzi": "jacuzzi", "sauna": "sauna",
           "restaurant": "restaurant", "breakfast": "ontbijt", "pet_friendly": "huisdieren toegestaan",
           "shuttle": "luchthavenshuttle"},
}


def _lang(language: str) -> str:
    return language if language in _LEAD else "en"


def _place(context: dict[str, Any], lang: str) -> str:
    zone, city = context.get("zone"), context.get("city")
    if isinstance(zone, str) and zone.strip():
        label = f"{zone}, {city}" if isinstance(city, str) and city and city not in zone else zone
        return _AROUND[lang].format(label)
    if isinstance(city, str) and city.strip():
        return _PLACE[lang].format(city)
    return ""


def _time(context: dict[str, Any], lang: str) -> str:
    daypart = context.get("daypart")
    if daypart in _DAYPART[lang]:
        return _DAYPART[lang][daypart]
    arrival, departure = requested_hours(
        parse_hhmm(context.get("timeslot_start")), parse_hhmm(context.get("timeslot_end"))
    )
    if arrival is not None and departure is not None:
        return _WINDOW[lang].format(arrival, departure)
    if arrival is not None:
        return _FROM[lang].format(arrival)
    if departure is not None:
        return _UNTIL[lang].format(departure)
    return ""


def _join(items: list[str], lang: str) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} {_AND[lang]} {items[-1]}"


def no_offers_line(
    context: dict[str, Any] | None, language: str, *, requested_budget: dict | None = None
) -> str:
    """"Aucune offre à Lyon le mercredi 7 octobre 2026, de 6h à 16h, à moins
    de 20 €, avec piscine et spa." — empty when there is no context to cite."""
    if not isinstance(context, dict):
        return ""
    lang = _lang(language)
    bits: list[str] = []
    day = context.get("date")
    if isinstance(day, str) and day:
        bits.append(_ON[lang].format(format_date_human(day, lang)))
    time = _time(context, lang)
    if time:
        bits.append(time)
    budget = context.get("budget_max")
    if requested_budget:
        bits.append(_TOTAL_BUDGET[lang].format(
            amount=f"{requested_budget['amount']:g}", currency=requested_budget.get("currency") or "?",
        ))
    elif isinstance(budget, (int, float)) and budget > 0:
        amount = f"{float(budget):g}"
        bits.append(_BUDGET[lang].format(f"€{amount}" if lang == "en" else f"{amount} €"))
    amenities = [
        _AMENITY[lang].get(key, key.replace("_", " "))
        for key in context.get("amenities") or []
        if isinstance(key, str)
    ]
    if amenities:
        bits.append(_WITH[lang].format(_join(amenities, lang)))
    if context.get("standing") == "upscale":
        bits.append(_UPSCALE[lang])
    adults = context.get("adults")
    if isinstance(adults, int) and adults > 1:
        bits.append(_ADULTS[lang].format(adults))
    place = _place(context, lang)
    if not place and not bits:
        return ""
    lead = _LEAD[lang].format(place=place).rstrip()
    return f"{lead} {', '.join(bits)}.".replace(" ,", ",").replace(" .", ".")


# A sentence ends at . ! ? — but not after a digit ("7. Oktober", "€30.").
# A full stop after a year ends a sentence before a capital (« … 31 octobre
# 2026. Hotel A … », 2026-10-30); never after a shorter number (« 3.9 km »,
# the German ordinal « Mittwoch, 7. Oktober »).
_SENTENCE_END_RE = re.compile(r"(?<=[^\d\s][.!?])\s+|(?<=\d{4}[.!?])\s+(?=[A-ZÀ-ÖØ-Þ])")
_WORD_RE = re.compile(r"\w{3,}")


def _words(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return set(_WORD_RE.findall(folded))


def drop_restated(text: str, line: str) -> str:
    """The synthesis, shown the sentence, still copies it (live 2026-10-06):
    drop any of its sentences that carries most of the sentence's words."""
    target = _words(line)
    if not text or not target:
        return text
    paragraphs = []
    for paragraph in text.strip().split("\n\n"):
        kept = [
            sentence
            for sentence in _SENTENCE_END_RE.split(paragraph)
            if len(_words(sentence) & target) < 0.6 * len(target)
        ]
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs)
