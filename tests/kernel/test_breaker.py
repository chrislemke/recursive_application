"""The circuit breaker, exercised through `BreakerStore` with an injected clock.

One breaker per registry name. The clock is a fake the test advances by hand; the state file
lives under `tmp_path` and is never read by a test, only observed through a second store.
"""

from pathlib import Path

import pytest

from recursive_application.kernel.breaker import BreakerState, BreakerStore, CircuitOpenError


class ActFailedError(Exception):
    """The exception a failing Act-phase callable raises; the breaker must re-raise it."""


class FakeClock:
    """A clock that only moves when the test advances it."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Callee:
    """A stand-in for an agent role's callable: counts its invocations, fails on demand."""

    def __init__(self) -> None:
        self.invocations = 0

    def fail(self) -> None:
        self.invocations += 1
        raise ActFailedError

    def succeed(self) -> str:
        self.invocations += 1
        return "done"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "breakers.json"


def fail_times(store: BreakerStore, name: str, callee: Callee, times: int) -> None:
    """Make `times` consecutive failing calls; each must reach the callee and re-raise."""
    for _ in range(times):
        with pytest.raises(ActFailedError):
            store.call(name, callee.fail)


def test_third_consecutive_failure_opens_the_breaker_and_the_next_call_is_not_invoked(
    path: Path, clock: FakeClock
) -> None:
    store = BreakerStore(path, clock=clock)
    callee = Callee()

    fail_times(store, "planner", callee, 3)
    assert callee.invocations == 3

    with pytest.raises(CircuitOpenError):
        store.call("planner", callee.fail)

    assert callee.invocations == 3


def test_an_open_breaker_reads_half_open_once_the_reset_timeout_has_elapsed(
    path: Path, clock: FakeClock
) -> None:
    store = BreakerStore(path, clock=clock)
    fail_times(store, "planner", Callee(), 3)
    assert store.states()["planner"] is BreakerState.OPEN

    clock.advance(60.0)

    assert store.states()["planner"] is BreakerState.HALF_OPEN


def test_after_the_reset_timeout_a_successful_call_goes_through_and_closes_the_breaker(
    path: Path, clock: FakeClock
) -> None:
    store = BreakerStore(path, clock=clock)
    callee = Callee()
    fail_times(store, "planner", callee, 3)

    clock.advance(60.0)

    assert store.call("planner", callee.succeed) == "done"
    assert store.states()["planner"] is BreakerState.CLOSED


def test_a_failure_during_the_half_open_trial_re_opens_the_breaker(
    path: Path, clock: FakeClock
) -> None:
    store = BreakerStore(path, clock=clock)
    callee = Callee()
    fail_times(store, "planner", callee, 3)
    clock.advance(60.0)

    fail_times(store, "planner", callee, 1)

    with pytest.raises(CircuitOpenError):
        store.call("planner", callee.succeed)
    assert callee.invocations == 4


def test_a_re_opened_breaker_waits_the_full_reset_timeout_again(
    path: Path, clock: FakeClock
) -> None:
    store = BreakerStore(path, clock=clock)
    callee = Callee()
    fail_times(store, "planner", callee, 3)
    clock.advance(60.0)
    fail_times(store, "planner", callee, 1)

    clock.advance(30.0)

    assert store.states()["planner"] is BreakerState.OPEN


def test_a_success_after_two_failures_resets_the_count(path: Path, clock: FakeClock) -> None:
    store = BreakerStore(path, clock=clock)
    callee = Callee()
    fail_times(store, "planner", callee, 2)
    store.call("planner", callee.succeed)

    fail_times(store, "planner", callee, 2)

    assert store.states()["planner"] is BreakerState.CLOSED


def test_state_survives_across_store_instances_through_the_file(
    path: Path, clock: FakeClock
) -> None:
    first = BreakerStore(path, clock=clock)
    callee = Callee()
    fail_times(first, "planner", callee, 3)

    second = BreakerStore(path, clock=clock)
    with pytest.raises(CircuitOpenError):
        second.call("planner", callee.succeed)

    clock.advance(60.0)
    assert second.call("planner", callee.succeed) == "done"

    third = BreakerStore(path, clock=clock)
    assert third.states() == {"planner": BreakerState.CLOSED}


def test_breakers_are_independent_by_name(path: Path, clock: FakeClock) -> None:
    store = BreakerStore(path, clock=clock)
    callee = Callee()
    fail_times(store, "planner", callee, 3)

    assert store.call("coder", callee.succeed) == "done"
    assert store.states() == {"planner": BreakerState.OPEN, "coder": BreakerState.CLOSED}


def test_a_fresh_store_reports_no_breakers(path: Path, clock: FakeClock) -> None:
    assert BreakerStore(path, clock=clock).states() == {}
