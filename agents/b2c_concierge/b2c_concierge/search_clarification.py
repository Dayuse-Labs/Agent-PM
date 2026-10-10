"""Unresolved search intent in the concierge's existing question state.

Names are literal requests, not resolved coordinates. Unsupported relations stay
explicit until a user selects an origin; they never become an arbitrary search.
"""
from __future__ import annotations

from typing import Any


def grounded_need(value: Any, message: str) -> dict | None:
    if not isinstance(value, dict) or set(value) - {"kind", "queries", "relation", "evidence", "parent"}:
        return None
    if value.get("kind") not in {"airport", "multiple_origins"}:
        return None
    quote, queries = value.get("evidence"), value.get("queries")
    if not isinstance(quote, str) or not quote.strip() or quote not in message:
        return None
    if (not isinstance(queries, list) or not 1 <= len(queries) <= 3
            or any(not isinstance(q, str) or not q.strip() or len(q) > 200 or q not in quote for q in queries)):
        return None
    if len(set(queries)) != len(queries):
        return None
    if value["kind"] == "multiple_origins" and (len(queries) < 2 or value.get("relation") not in {"between", "near_all", "choose"}):
        return None
    result = {"kind": value["kind"], "queries": queries, "relation": value.get("relation", "choose")}
    parent = value.get("parent")
    if isinstance(parent, str) and parent.strip() and parent in message:
        result["parent"] = parent
    return result


def reduce_need(current: dict | None, pending: dict | None, message: str,
                intent: dict | None, areas: list[dict] | None, landmark: dict | None) -> dict | None:
    if current:
        return current
    if not pending:
        return None
    action = (intent or {}).get("action")
    if pending.get("kind") == "airport":
        parent = (intent or {}).get("parent_city")
        if action == "refine" and parent and not landmark:
            return {**pending, "parent": parent}
        if areas and len(areas) == 1 and areas[0].get("kind") == "municipality":
            city = areas[0]["query"]
            if message.strip().casefold() == city.casefold():
                return {**pending, "parent": city}
    if action in {"change", "correct", "device", "select"} or landmark or areas:
        return None
    return dict(pending)


def need_question(need: dict, language: str) -> str:
    labels = " / ".join(need["queries"])
    if need["kind"] == "airport":
        labels = need.get("parent") or labels
        texts = {
            "fr": "Je garde la recherche près d’un aéroport ({places}). Quel aéroport ou terminal souhaites-tu ?",
            "en": "I’m keeping your airport proximity request ({places}). Which airport or terminal do you mean?",
            "es": "Mantengo la búsqueda cerca de un aeropuerto ({places}). ¿Qué aeropuerto o terminal prefieres?",
            "it": "Mantengo la ricerca vicino a un aeroporto ({places}). Quale aeroporto o terminal intendi?",
            "de": "Die Suche bleibt in Flughafennähe ({places}). Welchen Flughafen oder welches Terminal meinst du?",
            "pt": "Mantenho a busca perto de um aeroporto ({places}). Qual aeroporto ou terminal pretendes?",
            "nl": "Ik behoud je zoekvraag bij een luchthaven ({places}). Welke luchthaven of terminal bedoel je?",
        }
    else:
        texts = {
            "fr": "Je garde ces lieux : {places}. Je ne peux pas encore vérifier la proximité des deux ensemble. Lequel dois-je prendre comme point de départ, ou quel repère intermédiaire précis préfères-tu ?",
            "en": "I’ve kept these places: {places}. I can’t yet verify proximity to both together. Which should be the search origin, or which specific landmark between them would you prefer?",
            "es": "Mantengo estos lugares: {places}. No puedo verificar la cercanía a ambos a la vez. ¿Cuál priorizamos, o qué punto intermedio concreto prefieres?",
            "it": "Mantengo questi luoghi: {places}. Non posso verificare la vicinanza a entrambi insieme. Quale preferisci come punto di ricerca, o quale punto intermedio preciso?",
            "de": "Diese Orte bleiben gespeichert: {places}. Nähe zu beiden gleichzeitig kann ich nicht prüfen. Welcher Ort oder konkrete Zwischenpunkt soll Ausgangspunkt sein?",
            "pt": "Guardo estes locais: {places}. Não consigo verificar a proximidade de ambos em conjunto. Qual priorizamos, ou que ponto intermédio concreto preferes?",
            "nl": "Ik bewaar deze plaatsen: {places}. Nabijheid tot beide tegelijk kan ik niet verifiëren. Welke plaats of welk specifiek tussenpunt heeft je voorkeur?",
        }
    return texts.get(language, texts["en"]).format(places=labels)
