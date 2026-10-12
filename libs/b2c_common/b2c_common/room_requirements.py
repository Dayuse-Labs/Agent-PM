"""Concierge-owned bedding preference; provider bedding is offer-level evidence.

Ported from #134 (PORT1 slice 5), bedding only: the private/included/access
amenity scopes of #134 belong to the equipment family and are not ported.
The triage LLM labels the bed (closed enum); code owns which provider codes
prove it.
"""
from __future__ import annotations

from typing import Any

_KEYS = frozenset({'bedding', 'evidence'})
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
    return result or None


def apply_room_update(current: dict | None, update: dict | None) -> dict:
    result = {**(current or {}), **(update or {})}
    if result.get('bedding') == 'any':
        result.pop('bedding')
    return {k: v for k, v in result.items() if v}


def bedding_matches(offer: dict, requirements: dict | None) -> bool:
    """A bed is proved by the formula's own `bedding` code, never by its
    capacity or its commercial name; an unknown code is not a match."""
    wanted = (requirements or {}).get('bedding')
    if not wanted:
        return True
    codes = {'double': _DOUBLE, 'king': frozenset({'double_king'}),
             'queen': frozenset({'double_queen'}), 'twin': _TWIN}.get(wanted, frozenset())
    return offer.get('bedding') in codes
