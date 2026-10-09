"""Grounded multi-day requests. Code resolves weeks; no prose date parsing."""
from datetime import date, timedelta
from typing import Any

from .date_labels import WEEKDAYS


def grounded_period(value: Any, message: str) -> dict | None:
    if not isinstance(value, dict) or set(value) != {"kind", "evidence"}:
        return None
    if not isinstance(value["kind"], str) or value["kind"] not in {"next_week", "this_week", "range", "flexible"}:
        return None
    quote = value["evidence"]
    if not isinstance(quote, str) or not quote.strip() or len(quote) > 160 or quote not in message:
        return None
    return {"kind": value["kind"], "evidence": quote}


def freeze_period(period: dict, today: date) -> dict:
    """Resolve once: a next-week preference must not slide forward on followup."""
    frozen = dict(period)
    if period["kind"] in {"next_week", "this_week"}:
        monday = today - timedelta(days=today.weekday())
        if period["kind"] == "next_week":
            monday += timedelta(days=7)
        frozen.update(start=monday.isoformat(), end=(monday + timedelta(days=6)).isoformat())
    return frozen


def weekday_in_period(period: dict, weekday: str | None, today: date) -> str | None:
    if weekday not in WEEKDAYS or not period.get("start") or not period.get("end"):
        return None
    try:
        start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    except (ValueError, TypeError):
        return None
    day = start + timedelta(days=(WEEKDAYS[weekday] - start.weekday()) % 7)
    return day.isoformat() if today <= day <= end else None


_QUESTIONS = {
    "fr": "J’ai bien retenu la période «{period}». Je ne peux pas déterminer le jour le moins cher sans comparer ses dates. Quelle date précise souhaites-tu que je vérifie d’abord ?",
    "en": "I’ve kept your preferred period, “{period}”. I can’t determine the cheapest day without comparing its dates. Which specific date would you like me to check first?",
    "es": "He guardado el período «{period}». No puedo determinar el día más barato sin comparar sus fechas. ¿Qué fecha concreta quieres que compruebe primero?",
    "it": "Ho mantenuto il periodo «{period}». Non posso stabilire il giorno più economico senza confrontarne le date. Quale data precisa vuoi che controlli per prima?",
    "de": "Ich habe den Zeitraum „{period}“ gespeichert. Ohne einen Vergleich der Termine kann ich den günstigsten Tag nicht bestimmen. Welches genaue Datum soll ich zuerst prüfen?",
    "pt": "Guardei o período «{period}». Não posso determinar o dia mais barato sem comparar as datas. Qual data exata gostaria que eu verificasse primeiro?",
    "nl": "Ik heb de periode ‘{period}’ bewaard. Zonder de datums te vergelijken kan ik de goedkoopste dag niet bepalen. Welke specifieke datum zal ik eerst controleren?",
}


def period_question(period: dict, language: str) -> str:
    label = period["evidence"]
    if period.get("start") and period.get("end"):
        label += f" ({period['start']} – {period['end']})"
    return _QUESTIONS.get(language, _QUESTIONS["en"]).format(period=label)
