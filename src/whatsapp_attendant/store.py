"""In-memory state with TTL and bounded size (ADR-003): sessions and the message ledger.

Both are thread safe. A deployment with more than one replica replaces them with Redis or a
database behind the same methods.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass

Clock = Callable[[], float]


class TTLStore[T]:
    """Least recently used map whose entries expire `ttl` seconds after their last write.

    Entries are kept in the order of their timestamps, oldest first, so eviction only ever looks
    at the front. Writes move an entry to the back with a fresh timestamp; reads never move it.
    """

    def __init__(self, ttl_seconds: float, max_items: int, clock: Clock = time.monotonic) -> None:
        self.ttl = ttl_seconds
        self.max_items = max_items
        self.clock = clock
        self._items: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._lock = threading.Lock()

    def _evict(self, now: float) -> None:
        while self._items:
            key, (seen, _) = next(iter(self._items.items()))
            if now - seen <= self.ttl and len(self._items) <= self.max_items:
                break
            del self._items[key]

    def _put(self, key: str, value: T, now: float) -> None:
        self._items.pop(key, None)
        self._items[key] = (now, value)
        self._evict(now)

    def get_or_create(self, key: str, factory: Callable[[], T]) -> tuple[T, bool]:
        """Return (value, created) and refresh the entry. Expired entries are replaced."""
        with self._lock:
            now = self.clock()
            found = self._items.get(key)
            created = found is None or now - found[0] > self.ttl
            value = factory() if created or found is None else found[1]
            self._put(key, value, now)
            return value, created

    def get(self, key: str) -> T | None:
        """The fresh value of `key`, or None. Does not refresh or move the entry."""
        with self._lock:
            found = self._items.get(key)
            if found is None or self.clock() - found[0] > self.ttl:
                return None
            return found[1]

    def set(self, key: str, value: T) -> None:
        with self._lock:
            self._put(key, value, self.clock())

    def values(self) -> Iterator[T]:
        with self._lock:
            return iter([value for _, value in self._items.values()])

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


IN_FLIGHT, FAILED, DONE = "in_flight", "failed", "done"


@dataclass(frozen=True)
class _Entry:
    state: str
    attempts: int = 0


class MessageLedger:
    """Processing state of webhook message ids (RQ-5, ADR-006).

    `claim` before handling a message, then `complete` after success or `fail` after an error.
    A message in flight or done is a duplicate. A failed one can be claimed again by the
    redelivery, until `max_attempts` failures dead-letter it (it then counts as done).
    """

    def __init__(
        self, ttl_seconds: float, max_items: int, max_attempts: int, clock: Clock = time.monotonic
    ) -> None:
        self.max_attempts = max_attempts
        self._items: TTLStore[_Entry] = TTLStore(ttl_seconds, max_items, clock)
        self._lock = threading.Lock()

    def claim(self, key: str) -> bool:
        """True when the caller now owns the message; False for a duplicate."""
        with self._lock:
            entry = self._items.get(key)
            if entry is not None and entry.state in (IN_FLIGHT, DONE):
                return False
            self._items.set(key, _Entry(IN_FLIGHT, entry.attempts if entry else 0))
            return True

    def complete(self, key: str) -> None:
        with self._lock:
            entry = self._items.get(key)
            self._items.set(key, _Entry(DONE, entry.attempts if entry else 0))

    def fail(self, key: str) -> bool:
        """Record a failed attempt. True when the message is given up (dead letter)."""
        with self._lock:
            entry = self._items.get(key)
            attempts = (entry.attempts if entry else 0) + 1
            given_up = attempts >= self.max_attempts
            self._items.set(key, _Entry(DONE if given_up else FAILED, attempts))
            return given_up

    def __len__(self) -> int:
        return len(self._items)
