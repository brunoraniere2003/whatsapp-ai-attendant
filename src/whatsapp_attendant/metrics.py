"""Instance counters and processing latency, derived from the service's own traffic (RQ-24)."""

from __future__ import annotations

import math
import threading
from collections import Counter, deque

COUNTERS = (
    "received",
    "replied",
    "duplicates",
    "not_understood",
    "unsupported",
    "handoff_customer_request",
    "handoff_repeated_failures",
    "send_failures",
    "invalid_signatures",
    "oversized_bodies",
    "processing_errors",
    "dead_letters",
)


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile; 0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


class Metrics:
    def __init__(self, window: int = 2_000) -> None:
        self._counts: Counter[str] = Counter({name: 0 for name in COUNTERS})
        self._latency: deque[float] = deque(maxlen=window)
        self._lock = threading.Lock()

    def inc(self, name: str, by: int = 1) -> None:
        if name not in COUNTERS:
            raise KeyError(name)
        with self._lock:
            self._counts[name] += by

    def observe_latency(self, ms: float) -> None:
        with self._lock:
            self._latency.append(ms)

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            values = list(self._latency)
            data: dict[str, float | int] = dict(self._counts)
        data["latency_p50_ms"] = round(percentile(values, 50), 3)
        data["latency_p95_ms"] = round(percentile(values, 95), 3)
        return data
