"""Concierge-owned room preferences; provider bedding is offer-level evidence."""
from __future__ import annotations

from typing import Any

_KEYS = frozenset({'bedding', 'private_amenities', 'included_amenities', 'evidence'})
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
    for key in ('private_amenities', 'included_amenities'):
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


def unverified_access(requirements: dict | None) -> bool:
    # Current MCP offer data does not prove private use or free/included access.
    # Presence at the hotel, or an unqualified inclusion label, is insufficient.
    return bool(requirements and (requirements.get('private_amenities') or requirements.get('included_amenities')))


def conditional_access_message(language: str) -> str:
    messages = {
        'fr': "Ces hôtels sont des pistes, mais l’équipement privatif ou l’accès inclus que vous demandez n’est pas confirmé pour ces offres. Il faut le vérifier auprès de l’hôtel avant de réserver.",
        'en': "These hotels are options to explore, but the private facility or included access you requested is not confirmed for these offers. Please confirm it with the hotel before booking.",
        'de': "Diese Hotels kommen als Möglichkeiten infrage. Die gewünschte private Ausstattung oder der inbegriffene Zugang ist für diese Angebote jedoch nicht bestätigt. Bitte klären Sie dies vor der Buchung mit dem Hotel.",
        'es': "Estos hoteles son opciones para explorar, pero la instalación privada o el acceso incluido que solicitas no está confirmado para estas ofertas. Confírmalo con el hotel antes de reservar.",
        'it': "Questi hotel sono opzioni da valutare, ma il servizio privato o l’accesso incluso richiesto non è confermato per queste offerte. Verificalo con l’hotel prima di prenotare.",
        'pt': "Estes hotéis são opções a considerar, mas a instalação privada ou o acesso incluído que pediu não está confirmado nestas ofertas. Confirme com o hotel antes de reservar.",
        'nl': "Deze hotels zijn mogelijke opties, maar de gevraagde privéfaciliteit of inbegrepen toegang is voor deze aanbiedingen niet bevestigd. Controleer dit vóór het boeken bij het hotel.",
    }
    return messages.get(language, messages['en'])
