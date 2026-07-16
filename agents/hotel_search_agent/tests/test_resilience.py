"""CircuitBreaker unit tests — injectable fake clock, no sleeping."""
import pytest

from hotel_search_agent.resilience import CircuitBreaker


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def breaker(clock):
    return CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0, clock=clock)


def test_starts_closed(breaker):
    assert breaker.allow()


def test_stays_closed_below_threshold(breaker):
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow()


def test_opens_after_threshold_consecutive_failures(breaker):
    for _ in range(3):
        breaker.record_failure()
    assert not breaker.allow()


def test_success_resets_the_failure_count(breaker):
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow()


def test_stays_open_until_cooldown_elapses(breaker, clock):
    for _ in range(3):
        breaker.record_failure()
    clock.advance(29.9)
    assert not breaker.allow()


def test_resets_fully_after_cooldown(breaker, clock):
    for _ in range(3):
        breaker.record_failure()
    clock.advance(30.0)
    assert breaker.allow()
    # Counter was zeroed on reset: one new failure must not instantly reopen.
    breaker.record_failure()
    assert breaker.allow()


def test_rejects_nonsense_configuration():
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=0)
    with pytest.raises(ValueError):
        CircuitBreaker(cooldown_seconds=0)
