"""The circuit breaker, one per registry name.

`failure_threshold` consecutive failures open a breaker at the injected clock's time. While
open, `BreakerStore.call` refuses to run the callable and raises `CircuitOpenError` so the
Loop's stop rule can fire. After `reset_timeout_s` the breaker is half-open and admits one
trial call; a success closes it and clears the count, a failure re-opens it with a fresh
timestamp. State is kept as JSON at `path`, so a new process sees what the last one left.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path


class BreakerState(StrEnum):
    """Closed admits calls, open refuses them, half-open admits one trial."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised by `BreakerStore.call` while the named breaker is open; the callable never runs."""


@dataclass
class _Breaker:
    """Consecutive failures so far and, once open, the clock reading at which it opened."""

    failures: int = 0
    opened_at: float | None = None


class BreakerStore:
    """Runs callables under named breakers and persists their state to a JSON file."""

    def __init__(
        self,
        path: Path,
        *,
        failure_threshold: int = 3,
        reset_timeout_s: float = 60.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path
        self._failure_threshold = failure_threshold
        self._reset_timeout_s = reset_timeout_s
        self._clock = clock
        self._breakers = self._load()

    def call[T](self, name: str, fn: Callable[[], T]) -> T:
        """Run `fn` under the breaker `name`; raise `CircuitOpenError` while it is open."""
        breaker = self._breakers.setdefault(name, _Breaker())
        if self._state_of(breaker) is BreakerState.OPEN:
            raise CircuitOpenError(f"breaker {name!r} is open")
        try:
            result = fn()
        except Exception:
            breaker.failures += 1
            if breaker.failures >= self._failure_threshold:
                breaker.opened_at = self._clock()
            self._save()
            raise
        breaker.failures = 0
        breaker.opened_at = None
        self._save()
        return result

    def states(self) -> dict[str, BreakerState]:
        """The current state of every known breaker, with the reset timeout applied."""
        return {name: self._state_of(breaker) for name, breaker in self._breakers.items()}

    def _state_of(self, breaker: _Breaker) -> BreakerState:
        if breaker.opened_at is None:
            return BreakerState.CLOSED
        if self._clock() - breaker.opened_at >= self._reset_timeout_s:
            return BreakerState.HALF_OPEN
        return BreakerState.OPEN

    def _load(self) -> dict[str, _Breaker]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text())
        return {
            name: _Breaker(failures=fields["failures"], opened_at=fields["opened_at"])
            for name, fields in raw.items()
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {name: asdict(breaker) for name, breaker in self._breakers.items()}
        self._path.write_text(json.dumps(payload))
