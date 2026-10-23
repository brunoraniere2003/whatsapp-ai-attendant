from conftest import FakeClock

from whatsapp_attendant.metrics import Metrics, percentile
from whatsapp_attendant.store import TTLStore


def test_get_or_create_reuses_until_ttl():
    clock = FakeClock()
    store: TTLStore[list] = TTLStore(10, 100, clock)
    first, created = store.get_or_create("a", list)
    assert created
    again, created = store.get_or_create("a", list)
    assert again is first and not created
    clock.advance(11)
    fresh, created = store.get_or_create("a", list)
    assert created and fresh is not first


def test_least_recently_used_entries_are_dropped_beyond_capacity():
    store: TTLStore[int] = TTLStore(100, 2, FakeClock())
    store.get_or_create("a", lambda: 1)
    store.get_or_create("b", lambda: 2)
    store.get_or_create("a", lambda: 9)  # touch a
    store.get_or_create("c", lambda: 3)
    assert len(store) == 2 and sorted(store.values()) == [1, 3]


def test_add_if_absent_is_an_idempotency_check():
    clock = FakeClock()
    seen: TTLStore[None] = TTLStore(60, 100, clock)
    assert seen.add_if_absent("wamid.1") is True
    assert seen.add_if_absent("wamid.1") is False
    clock.advance(61)
    assert seen.add_if_absent("wamid.1") is True


def test_metrics_counters_and_percentiles():
    m = Metrics()
    m.inc("received", 3)
    for ms in (1.0, 2.0, 3.0, 4.0):
        m.observe_latency(ms)
    snap = m.snapshot()
    assert snap["received"] == 3 and snap["latency_p50_ms"] == 2.0 and snap["latency_p95_ms"] == 4.0
    assert percentile([], 95) == 0.0
    try:
        m.inc("unknown")
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("unknown counter accepted")
