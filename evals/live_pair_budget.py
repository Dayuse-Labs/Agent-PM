"""Persist observed model costs and stop before issuing another paired turn.

Accounting is telemetry-based, not an invoice-level provider quota. A separate
reserve covers in-flight/accounting uncertainty. Unknown costs and interrupted
requests block continuation instead of being counted as zero.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
from decimal import Decimal, InvalidOperation
from pathlib import Path

from evals.production_corpus import atomic_json


class BudgetStop(RuntimeError):
    pass


def amount(value: object) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("missing or invalid model cost")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid model cost") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("invalid model cost")
    return result


class ObservedBudget:
    def __init__(self, path: Path, *, ceiling: str, reserve: str):
        self.path = path
        self.ceiling, self.reserve = amount(ceiling), amount(reserve)
        if not 0 < self.reserve < self.ceiling:
            raise ValueError("reserve must be positive and below the ceiling")
        self.state = json.loads(path.read_text()) if path.exists() else {
            "ceiling_usd": str(self.ceiling), "reserve_usd": str(self.reserve),
            "costs": {}, "pending": None,
        }
        if (amount(self.state['ceiling_usd']), amount(self.state['reserve_usd'])) != (
            self.ceiling, self.reserve
        ):
            raise ValueError("campaign budget changed")
        self.total  # Validate persisted costs before any dispatch.

    @property
    def total(self) -> Decimal:
        return sum((amount(v) for v in self.state['costs'].values()), Decimal(0))

    def begin(self, request_id: str) -> None:
        if self.state['pending']:
            raise BudgetStop("unsettled previous request; investigate before restarting")
        if self.total >= self.ceiling - self.reserve:
            raise BudgetStop("observed spend reached stop threshold; reserve untouched")
        self.state['pending'] = request_id
        atomic_json(self.path, self.state)

    def settle(self, request_id: str, costs: dict[str, object]) -> None:
        if self.state['pending'] != request_id:
            raise ValueError("request identity mismatch")
        if not costs:
            raise ValueError("no accounting evidence")
        updates = {}
        for key, raw in costs.items():
            value = amount(raw)
            if key in self.state['costs'] and value < amount(self.state['costs'][key]):
                raise ValueError("observed cost decreased; reconcile before continuing")
            updates[key] = str(value)
        self.state['costs'].update(updates)
        self.state['pending'] = None
        self.state['observed_total_usd'] = str(self.total)
        atomic_json(self.path, self.state)


def production_costs(traces: list[dict], session_id: str, expected_turns: int) -> dict:
    if len(traces) != expected_turns or len({t['id'] for t in traces}) != expected_turns:
        raise ValueError("production trace coverage is not exact")
    if any(t.get('sessionId') != session_id for t in traces):
        raise ValueError("Langfuse returned another session")
    return {f"production:{t['id']}": str(amount(t.get('totalCost'))) for t in traces}


@asynccontextmanager
async def conversation_clients(*, timeout: float = 180, transport=None):
    """Fresh cookie jars per conversation, while keeping cookies across its turns.

    Legacy production gives its session cookie priority over caller-supplied
    session IDs. Reusing a client across cases contaminates the next conversation.
    """
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as production:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as candidate:
            yield production, candidate
