"""In-memory state with TTL and bounded size (ADR-003): sessions and processed message ids.

Both stores are thread safe. A deployment with more than one replica replaces them with Redis or
a database behind the same methods.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator

Clock = Callable[[], float]


class TTLStore[T]:
    """Least recently used map whose entries expire `ttl` seconds after their last access."""

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

    def get_or_create(self, key: str, factory: Callable[[], T]) -> tuple[T, bool]:
        """Return (value, created). Expired entries are replaced by a fresh value."""
        with self._lock:
            now = self.clock()
            found = self._items.pop(key, None)
            created = found is None or now - found[0] > self.ttl
            value = factory() if created else found[1]
            self._items[key] = (now, value)
            self._evict(now)
            return value, created

    def add_if_absent(self, key: str) -> bool:
        """Atomically record `key`. Returns False when it was already present and fresh."""
        with self._lock:
            now = self.clock()
            found = self._items.pop(key, None)
            fresh = found is not None and now - found[0] <= self.ttl
            self._items[key] = (found[0] if fresh else now, found[1] if fresh else None)
            self._evict(now)
            return not fresh

    def values(self) -> Iterator[T]:
        with self._lock:
            return iter([value for _, value in self._items.values()])

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
