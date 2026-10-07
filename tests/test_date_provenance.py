"""A model-supplied calendar date must be grounded in this customer's turn."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types

from hotel_search_agent import datetime_resolver
from hotel_search_agent.agent import inject_today_before_model
from hotel_search_agent.response_bridge import STATE_RESOLVED_DATE_KEY


def context(message, profile):
    part = a2a_types.Part(root=a2a_types.DataPart(data={'profile_in': profile, 'query_params': {}}))
    return SimpleNamespace(state={}, user_content=types.Content(role='user', parts=[
        types.Part(text=message), convert_a2a_part_to_genai_part(part),
    ]))


@pytest.mark.parametrize('message,carried,expected', [
    ('Bromley', None, '2026-10-08'),
    ('Brescia e provincia', None, '2026-10-08'),
    ('Keep the same date, but in London England', '2026-10-10', '2026-10-10'),
])
def test_model_invented_today_does_not_roll_forward_a_year(monkeypatch, message, carried, expected):
    monkeypatch.setattr(datetime_resolver, 'reference_today', lambda _: date(2026, 10, 8))
    ctx = context(message, {'client_timezone': 'Europe/London', 'date': carried})
    args = {'date': {'type': 'absolute', 'value': '2026-10-07', 'expression': 'today'}}
    datetime_resolver.resolve_search_date(SimpleNamespace(name='search_offers'), args, ctx)
    assert args['date'] == expected
    assert STATE_RESOLVED_DATE_KEY not in ctx.state


@pytest.mark.parametrize('expression', [None, '', '   ', 'tomorrow'])
def test_unsupported_date_label_cannot_overwrite_carried_date(monkeypatch, expression):
    monkeypatch.setattr(datetime_resolver, 'reference_today', lambda _: date(2026, 10, 8))
    ctx = context('near the airport', {'date': '2026-10-10'})
    args = {'date': {'type': 'relative', 'value': 'tomorrow', 'expression': expression}}
    datetime_resolver.resolve_search_date(SimpleNamespace(name='search_offers'), args, ctx)
    assert args['date'] == '2026-10-10'
    assert STATE_RESOLVED_DATE_KEY not in ctx.state


@pytest.mark.parametrize('message,label,expected', [
    ('Actually tomorrow', {'type': 'relative', 'value': 'tomorrow', 'expression': 'tomorrow'}, '2026-10-09'),
    ('Pour le 10 octobre', {'type': 'absolute', 'value': '10-10', 'expression': '10 octobre'}, '2026-10-10'),
])
def test_current_customer_date_can_replace_carried_date(monkeypatch, message, label, expected):
    monkeypatch.setattr(datetime_resolver, 'reference_today', lambda _: date(2026, 10, 8))
    ctx = context(message, {'date': '2026-10-12'})
    args = {'date': label}
    datetime_resolver.resolve_search_date(SimpleNamespace(name='search_offers'), args, ctx)
    assert args['date'] == expected
    assert ctx.state[STATE_RESOLVED_DATE_KEY]['date'] == expected


@pytest.mark.parametrize('zone,expected', [
    ('Europe/London', '2026-10-08'), ('America/Toronto', '2026-10-07'),
])
def test_model_and_resolver_share_the_client_local_day(monkeypatch, zone, expected):
    instant = datetime(2026, 10, 7, 23, 10, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(datetime_resolver, 'datetime', Clock)
    ctx = context('Bromley', {'client_timezone': zone})
    captured = []
    inject_today_before_model(ctx, SimpleNamespace(append_instructions=captured.extend))
    assert 'TODAY is '+expected in ''.join(captured)
    assert datetime_resolver.reference_today({'client_timezone': zone}).isoformat() == expected
