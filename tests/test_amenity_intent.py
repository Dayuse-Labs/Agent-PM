"""Current intent must reach the tool without turning FAQ text into filters."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from b2c_common.amenities import AMENITY_KEYS, apply_amenity_update, grounded_amenity_update
from b2c_concierge.budget import TurnBudget
from b2c_concierge.triage import classify
from hotel_search_agent.equipment_ids import EQUIPMENT_IDS


def test_shared_keys_match_supported_mcp_filter_families():
    assert set(AMENITY_KEYS) == set(EQUIPMENT_IDS)


@pytest.mark.parametrize('value', [
    None, [], {'add': ['pool']},
    {'add': ['pool'], 'evidence': 'old pool request'},
    {'add': 'pool', 'evidence': 'pool'},
    {'add': ['bathtub'], 'evidence': 'pool'},
    {'remove': [None], 'evidence': 'pool'},
    {'add': [], 'remove': [], 'evidence': 'pool'},
    {'add': ['pool'], 'remove': ['pool'], 'evidence': 'pool'},
    {'add': ['pool'], 'replace': True, 'evidence': 'pool'},
])
def test_invalid_or_unquoted_change_cannot_erase_carried_filters(value):
    assert grounded_amenity_update(value, 'Get a room with pool access') is None


@pytest.mark.parametrize('message,add,remove,expected', [
    ('Get a room with pool access', ['pool'], [], ['jacuzzi', 'parking', 'pool']),
    ('Pool instead of jacuzzi', ['pool'], ['jacuzzi'], ['parking', 'pool']),
    ('Enlève le jacuzzi', [], ['jacuzzi'], ['parking']),
    ('Sin jacuzzi, con piscina', ['pool'], ['jacuzzi'], ['parking', 'pool']),
])
def test_operations_preserve_unrelated_criteria(message, add, remove, expected):
    update = grounded_amenity_update({'add': add, 'remove': remove, 'evidence': message}, message)
    assert update is not None
    assert apply_amenity_update(['jacuzzi', 'parking'], update) == expected


@pytest.mark.parametrize('family,accepted', [('search', True), ('booking', True), ('faq', False), ('details', False)])
def test_triage_exposes_only_search_constraint_updates(monkeypatch, family, accepted):
    message = 'Get a room with pool access'
    update = {'add': ['pool'], 'remove': [], 'evidence': 'pool access'}
    async def completion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            'family': family, 'language': 'en', 'requested_amenities': update,
        })))])
    monkeypatch.setattr('b2c_concierge.triage.litellm.acompletion', completion)
    result = asyncio.run(classify(message, TurnBudget()))
    assert result.requested_amenities == (update if accepted else None)
