"""Minimal circuit breaker for this leaf's owned outbound dependencies.

Wired on the MCP path through `mcp_guard.py` (3 failures, then a 30 s
cooldown). Mapbox keeps its own budget (1.5 s, 1 retry) without the breaker.
Deliberately synchronous and
dependency-free — a counter and a clock, not a resilience framework.
"""
from __future__ import annotations

import time
from typing import Callable


class CircuitBreaker:
    """Opens after `failure_threshold` consecutive failures; closes again after `cooldown_seconds`.

    A guard never re-runs a loop: while open, allow() is False so the caller
    degrades honestly (no result) instead of hammering a dead dependency. Once
    the cooldown elapses the breaker fully resets (closed, counter zeroed).
    `clock` is injectable for tests (defaults to time.monotonic).
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if self._clock() - self._opened_at >= self._cooldown:
            self.reset()
            return False
        return True

    def allow(self) -> bool:
        """True if the caller may attempt the dependency call."""
        return not self.is_open

    def record_success(self) -> None:
        self.reset()

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()

    def reset(self) -> None:
        self._failures = 0
        self._opened_at = None
