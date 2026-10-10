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


def period_decision(value: Any, message: str) -> dict | None:
    """An invalid extraction can request clarification, never invent a date.

    Keep uncertainty when the model saw multiple dates but abbreviated its
    quote. Silently dropping that decision would authorize today's fallback.
    The literal customer request is context, not a validated calendar range.
    """
    valid = grounded_period(value, message)
    if valid is not None or value is None:
        return valid
    if isinstance(value, dict) and message.strip():
        return {"kind": "unresolved", "evidence": message[:300]}
    return None


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
    "fr": "J’ai bien retenu la période «{period}». Quelle date précise souhaites-tu que je vérifie d’abord ?",
    "en": "I’ve kept your preferred period, “{period}”. Which specific date would you like me to check first?",
    "es": "He guardado el período «{period}». ¿Qué fecha concreta quieres que compruebe primero?",
    "it": "Ho mantenuto il periodo «{period}». Quale data precisa vuoi che controlli per prima?",
    "de": "Ich habe den Zeitraum „{period}“ gespeichert. Welches genaue Datum soll ich zuerst prüfen?",
    "pt": "Guardei o período «{period}». Qual data exata gostaria que eu verificasse primeiro?",
    "nl": "Ik heb de periode ‘{period}’ bewaard. Welke specifieke datum zal ik eerst controleren?",
}


def period_question(period: dict, language: str) -> str:
    if period.get("kind") == "unresolved":
        return {
            "fr": "Je n’ai pas pu vérifier les dates de ta demande. Quelle date précise souhaites-tu que je vérifie d’abord, et pour quels horaires ?",
            "en": "I couldn’t verify the dates in your request. Which specific date would you like me to check first, and for which hours?",
            "es": "No pude verificar las fechas de tu solicitud. ¿Qué fecha concreta quieres que compruebe primero y para qué horario?",
            "it": "Non ho potuto verificare le date della richiesta. Quale data precisa vuoi che controlli per prima e per quali orari?",
            "de": "Ich konnte die Daten deiner Anfrage nicht verifizieren. Welches genaue Datum soll ich zuerst prüfen und für welche Uhrzeiten?",
            "pt": "Não consegui verificar as datas do pedido. Qual data exata gostaria que verificasse primeiro e para quais horários?",
            "nl": "Ik kon de datums in je verzoek niet verifiëren. Welke specifieke datum zal ik eerst controleren en voor welke uren?",
        }.get(language, "Which specific date and hours would you like me to check first?")
    label = period["evidence"]
    if period.get("start") and period.get("end"):
        label += f" ({period['start']} – {period['end']})"
    return _QUESTIONS.get(language, _QUESTIONS["en"]).format(period=label)
