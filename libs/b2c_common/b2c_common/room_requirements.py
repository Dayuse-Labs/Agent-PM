"""Concierge-owned room preferences; provider bedding is offer-level evidence."""
from __future__ import annotations

from typing import Any

_KEYS = frozenset({'bedding', 'private_amenities', 'included_amenities', 'access_amenities', 'evidence'})
_FEATURES = frozenset({'pool', 'jacuzzi', 'spa', 'sauna', 'breakfast', 'parking', 'shuttle'})
_DOUBLE = frozenset({'double', 'double_king', 'double_queen'})
_TWIN = frozenset({'twin', 'twin_single', 'twin_double', 'twin_queen'})


def grounded_room_update(value: Any, message: str) -> dict | None:
    if not isinstance(value, dict) or set(value) - _KEYS:
        return None
    quote = value.get('evidence')
    if not isinstance(quote, str) or not quote.strip() or quote not in message:
        return None
    result: dict[str, Any] = {}
    if 'bedding' in value:
        if not isinstance(value['bedding'], str) or value['bedding'] not in {'double', 'king', 'queen', 'twin', 'any'}:
            return None
        result['bedding'] = value['bedding']
    for key in ('private_amenities', 'included_amenities', 'access_amenities'):
        if key in value:
            items = value[key]
            if not isinstance(items, list) or any(not isinstance(v, str) or v not in _FEATURES for v in items):
                return None
            result[key] = list(dict.fromkeys(items))
    return result or None


def apply_room_update(current: dict | None, update: dict | None) -> dict:
    result = {**(current or {}), **(update or {})}
    if result.get('bedding') == 'any':
        result.pop('bedding')
    return {k: v for k, v in result.items() if v}


def bedding_matches(offer: dict, requirements: dict | None) -> bool:
    wanted = (requirements or {}).get('bedding')
    if not wanted:
        return True
    codes = {'double': _DOUBLE, 'king': frozenset({'double_king'}),
             'queen': frozenset({'double_queen'}), 'twin': _TWIN}.get(wanted, frozenset())
    return offer.get('bedding') in codes


def unverified_access(requirements: dict | None, amenities: list[str] | None = None) -> bool:
    # Current MCP offer data does not prove private use or free/included access.
    # Presence at the hotel, or an unqualified inclusion label, is insufficient.
    return bool(set(amenities or []) & {'pool', 'jacuzzi', 'spa', 'sauna'} or
                (requirements and (requirements.get('private_amenities') or requirements.get('included_amenities') or requirements.get('access_amenities'))))


def access_request_key(requirements: dict | None, amenities: list[str] | None = None) -> list[str] | None:
    """The requested access set `unverified_access` warns about, as a stable
    key: the warning is said once per set, and again only when the set changes."""
    if not unverified_access(requirements, amenities):
        return None
    key = {f'amenity:{a}' for a in amenities or [] if a in {'pool', 'jacuzzi', 'spa', 'sauna'}}
    for kind in ('private_amenities', 'included_amenities', 'access_amenities'):
        key |= {f'{kind}:{a}' for a in (requirements or {}).get(kind) or []}
    return sorted(key)


def conditional_access_message(language: str, results: list[dict] | None = None) -> str:
    messages = {
        'fr': "Ces hôtels sont des pistes, mais l’accès demandé à l’équipement, ou son caractère privatif ou inclus, n’est pas confirmé pour ces offres. Il faut le vérifier auprès de l’hôtel avant de réserver.",
        'en': "These hotels are options to explore, but the requested facility access (including any private-use or inclusion requirement) is not confirmed for these offers. Please confirm it with the hotel before booking.",
        'de': "Diese Hotels kommen als Möglichkeiten infrage. Der gewünschte Zugang zur Ausstattung, einschließlich einer privaten oder inbegriffenen Nutzung, ist für diese Angebote jedoch nicht bestätigt. Bitte klären Sie dies vor der Buchung mit dem Hotel.",
        'es': "Estos hoteles son opciones para explorar, pero el acceso solicitado al equipamiento, incluido su uso privado o incluido, no está confirmado para estas ofertas. Confírmalo con el hotel antes de reservar.",
        'it': "Questi hotel sono opzioni da valutare, ma l’accesso richiesto al servizio, compreso l’uso privato o incluso, non è confermato per queste offerte. Verificalo con l’hotel prima di prenotare.",
        'pt': "Estes hotéis são opções a considerar, mas o acesso solicitado à instalação, incluindo uso privado ou incluído, não está confirmado nestas ofertas. Confirme com o hotel antes de reservar.",
        'nl': "Deze hotels zijn mogelijke opties, maar de gevraagde toegang tot de faciliteit, inclusief privégebruik of inbegrepen toegang, is voor deze aanbiedingen niet bevestigd. Controleer dit vóór het boeken bij het hotel.",
    }
    return messages.get(language, messages['en']) + displayed_slot_fact(results, language)


def displayed_slot_fact(results: list[dict] | None, language: str) -> str:
    """Keep the temporal answer useful without claiming facility inclusion.

    Scope is the displayed dated formulas, never the whole hotel/inventory.
    A longer requested stay is not inferred to fit this provider slot.
    """
    from .timeslot import parse_hhmm
    slots = []
    for row in results or []:
        name = row.get('name')
        if not isinstance(name, str) or not name:
            continue
        for slot in row.get('timeslots') or []:
            start, end = parse_hhmm(slot.get('start')), parse_hhmm(slot.get('end'))
            if start is None or end is None:
                continue
            end = 1440 if end == 0 and start > 0 else end
            if end > start:
                slots.append((end - start, {'name': name, 'start_time': slot['start'], 'end_time': slot['end']}))
    if not slots:
        return ''
    minutes, longest = max(slots, key=lambda item: item[0])
    labels = {
        'en': 'Longest slot among the displayed offers',
        'fr': 'Créneau le plus long parmi les offres affichées',
        'de': 'Längstes Zeitfenster unter den angezeigten Angeboten',
        'it': 'Fascia oraria più lunga tra le offerte mostrate',
        'es': 'Franja más larga entre las ofertas mostradas',
        'pt': 'Período mais longo entre as ofertas apresentadas',
        'nl': 'Langste tijdvak van de getoonde aanbiedingen',
    }
    return (f"\n\n{labels.get(language, labels['en'])} : {longest['name']}, "
            f"{longest['start_time']}–{longest['end_time']} ({minutes} min).")
